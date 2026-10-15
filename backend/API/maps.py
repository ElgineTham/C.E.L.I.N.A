"""Transit routes between Griffis Shoreline and University District Station.

The morning card arrives a few minutes before the first event. The evening
card leaves when the last event ends. A current location uses the time she
picks: leave now, leave by, or arrive by.
"""

import json
import os
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import schedule

PACIFIC = ZoneInfo("America/Los_Angeles")
GRIFFIS = "15560 Westminster Way N, Shoreline, WA 98133"
UNIVERSITY_DISTRICT = "University District Station Light Rail"
ARRIVAL_BUFFER_MINUTES = 10
TIMINGS = ("leave_now", "leave_by", "arrive_by")
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = ",".join(
    (
        "routes.polyline.encodedPolyline",
        "routes.legs.steps.travelMode",
        "routes.legs.steps.distanceMeters",
        "routes.legs.steps.staticDuration",
        "routes.legs.steps.navigationInstruction.instructions",
        "routes.legs.steps.polyline.encodedPolyline",
        "routes.legs.steps.startLocation.latLng",
        "routes.legs.steps.endLocation.latLng",
        "routes.legs.steps.transitDetails",
    )
)


def day_window(now):
    """First start and last end among today's events.

    Both times are ``HH:MM`` in Pacific time. An empty day leaves them empty.
    """
    now = _pacific(now)
    events = schedule.get_schedule(now.date().isoformat())
    if not events:
        return {"first_start": None, "last_end": None}
    return {
        "first_start": min(event["start_time"] for event in events),
        "last_end": max(event["end_time"] for event in events),
    }


def route_to_university_district(now, origin=None, timing=None, when=None):
    """Transit to University District Station.

    The origin is Griffis Shoreline unless ``origin`` is a current location,
    ``"latitude,longitude"`` or ``(latitude, longitude)``. The scheduled trip
    arrives ``ARRIVAL_BUFFER_MINUTES`` before the first event. A current
    location, or any explicit ``timing``, uses ``leave_now``, ``leave_by``,
    or ``arrive_by``. ``when`` is ``HH:MM`` or a datetime for the last two.
    """
    now = _pacific(now)
    return _transit_route(
        _origin(origin, GRIFFIS),
        UNIVERSITY_DISTRICT,
        *_departure(now, _arrive_before_first_event, origin, timing, when),
        label="To University District",
    )


def route_to_griffis(now, origin=None, timing=None, when=None):
    """Transit to Griffis Shoreline.

    The origin is University District Station unless ``origin`` is a current
    location. The scheduled trip leaves at the last event's end. A current
    location, or any explicit ``timing``, uses the same time choices as the
    trip to University District.
    """
    now = _pacific(now)
    return _transit_route(
        _origin(origin, UNIVERSITY_DISTRICT),
        GRIFFIS,
        *_departure(now, _leave_after_last_event, origin, timing, when),
        label="To Griffis Shoreline",
    )


def _departure(now, scheduled, origin, timing, when):
    if origin is None and timing is None and when is None:
        return scheduled(now)
    return _chosen_time(now, timing, when)


def _arrive_before_first_event(now):
    window = day_window(now)
    if window["first_start"] is None:
        return now, "leave_by"
    arrive = _on_clock(now, window["first_start"]) - timedelta(minutes=ARRIVAL_BUFFER_MINUTES)
    if arrive <= now:
        return now, "leave_by"
    return arrive, "arrive_by"


def _leave_after_last_event(now):
    window = day_window(now)
    if window["last_end"] is None:
        return now, "leave_by"
    leave = _on_clock(now, window["last_end"])
    if leave <= now:
        return now, "leave_by"
    return leave, "leave_by"


def _chosen_time(now, timing, when):
    if timing not in TIMINGS:
        raise ValueError("timing must be leave_now, leave_by, or arrive_by.")
    if timing == "leave_now":
        return now, "leave_by"
    if when is None:
        raise ValueError("when is required for leave_by and arrive_by.")
    moment = _parse_when(now, when)
    if moment <= now:
        raise ValueError("when must be later than now.")
    return moment, timing


def _transit_route(origin, destination, moment, timing, label):
    body = {
        "origin": _waypoint(origin),
        "destination": _waypoint(destination),
        "travelMode": "TRANSIT",
    }
    if timing == "arrive_by":
        body["arrivalTime"] = moment.isoformat()
    else:
        body["departureTime"] = moment.isoformat()

    request = Request(
        ROUTES_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": _api_key(),
            "X-Goog-FieldMask": FIELD_MASK,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode())
    except HTTPError as error:
        detail = error.read().decode()
        raise RuntimeError(f"Google Maps returned {error.code}. {detail}") from error

    routes = payload.get("routes") or []
    if not routes or not routes[0].get("legs"):
        raise RuntimeError("Google Maps returned no transit route.")
    leg = routes[0]["legs"][0]
    rides = _rides(leg)
    if not rides:
        raise RuntimeError("Google Maps returned no transit route.")
    return {
        "label": label,
        "origin": origin,
        "destination": destination,
        "timing": timing,
        "when": moment.isoformat(),
        "leaveAt": rides[0]["leaveAt"],
        "arriveAt": rides[-1]["arriveAt"],
        "summary": ", then ".join(ride["summary"] for ride in rides),
        "path": (routes[0].get("polyline") or {}).get("encodedPolyline") or "",
        "steps": _follow_steps(leg),
        "mapsUrl": _maps_url(
            origin,
            destination,
            rides[0]["leaveAt"],
            rides[-1]["arriveAt"],
            timing,
            moment,
        ),
    }


def _maps_url(origin, destination, leave_at, arrive_at, timing, moment):
    """Match the card: arrive-by trips open as arrive by, leave-by trips as leave by."""
    if timing == "arrive_by":
        when = _clock_time(arrive_at) or moment
        kind = "6e1"
    else:
        when = _clock_time(leave_at) or moment
        kind = "6e0"
    start = quote(str(origin), safe="")
    end = quote(str(destination), safe="")
    stamp = int(when.timestamp())
    return (
        f"https://www.google.com/maps/dir/{start}/{end}/"
        f"data=!4m6!4m5!2m3!{kind}!7e2!8j{stamp}!3e3"
    )


def _clock_time(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _pacific(parsed)


def _follow_steps(leg):
    steps = []
    for step in leg.get("steps") or []:
        if step.get("travelMode") == "TRANSIT":
            steps.append(_transit_step(step))
        else:
            steps.append(_walk_step(step))
    return [step for step in steps if step]


def _walk_step(step):
    instruction = (step.get("navigationInstruction") or {}).get("instructions") or "Walk"
    point = _lat_lng(step.get("endLocation")) or _lat_lng(step.get("startLocation"))
    return {
        "mode": "walk",
        "title": instruction,
        "detail": _distance_text(step.get("distanceMeters")),
        "lat": point[0] if point else None,
        "lng": point[1] if point else None,
    }


def _transit_step(step):
    details = step.get("transitDetails") or {}
    line = details.get("transitLine") or {}
    stops = details.get("stopDetails") or {}
    depart = (stops.get("departureStop") or {})
    arrive = (stops.get("arrivalStop") or {})
    name = line.get("nameShort") or line.get("name") or "Transit"
    point = _lat_lng(depart.get("location")) or _lat_lng(step.get("startLocation"))
    return {
        "mode": "transit",
        "title": f"{_vehicle_name(line)} {name}".strip(),
        "detail": f"{depart.get('name') or 'the stop'} to {arrive.get('name') or 'the stop'}",
        "leaveAt": stops.get("departureTime"),
        "arriveAt": stops.get("arrivalTime"),
        "lat": point[0] if point else None,
        "lng": point[1] if point else None,
    }


def _lat_lng(place):
    point = (place or {}).get("latLng") or {}
    latitude = point.get("latitude")
    longitude = point.get("longitude")
    if latitude is None or longitude is None:
        return None
    return latitude, longitude


def _distance_text(meters):
    if not isinstance(meters, (int, float)):
        return ""
    if meters >= 1000:
        return f"{meters / 1000:.1f} km"
    return f"{round(meters)} m"


def _rides(leg):
    rides = []
    for step in leg.get("steps") or []:
        if step.get("travelMode") != "TRANSIT":
            continue
        details = step.get("transitDetails") or {}
        line = details.get("transitLine") or {}
        stops = details.get("stopDetails") or {}
        name = line.get("nameShort") or line.get("name") or "Transit"
        depart = (stops.get("departureStop") or {}).get("name") or "the stop"
        arrive = (stops.get("arrivalStop") or {}).get("name") or "the stop"
        rides.append(
            {
                "leaveAt": stops.get("departureTime"),
                "arriveAt": stops.get("arrivalTime"),
                "summary": f"{_vehicle_name(line)} {name} from {depart} to {arrive}",
            }
        )
    return rides


def _vehicle_name(line):
    name = (line.get("vehicle") or {}).get("name")
    if isinstance(name, dict):
        return name.get("text") or "Transit"
    if isinstance(name, str) and name:
        return name
    return "Transit"


def _waypoint(place):
    parts = [part.strip() for part in str(place).split(",")]
    if len(parts) == 2:
        try:
            return {
                "location": {
                    "latLng": {
                        "latitude": float(parts[0]),
                        "longitude": float(parts[1]),
                    }
                }
            }
        except ValueError:
            pass
    return {"address": place}


def _origin(origin, default):
    if origin is None:
        return default
    if isinstance(origin, (tuple, list)):
        if len(origin) != 2:
            raise ValueError("origin must be latitude and longitude.")
        return f"{origin[0]},{origin[1]}"
    text = str(origin).strip()
    if not text:
        raise ValueError("origin must be latitude and longitude.")
    return text


def _parse_when(now, when):
    if isinstance(when, datetime):
        return _pacific(when)
    text = str(when).strip()
    if len(text) == 5 and text[2] == ":":
        return _on_clock(now, text)
    parsed = datetime.fromisoformat(text)
    return _pacific(parsed)


def _on_clock(now, clock):
    hour, minute = clock.split(":")
    return now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)


def _pacific(now):
    if now.tzinfo is None:
        return now.replace(tzinfo=PACIFIC)
    return now.astimezone(PACIFIC)


def _api_key():
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not set.")
    return key

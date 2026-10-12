"""Transit routes between Griffis Shoreline and University District Station.

The morning card arrives a few minutes before the first event. The evening
card leaves when the last event ends. A current location uses the time she
picks: leave now, leave by, or arrive by.
"""

import json
import os
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import schedule

PACIFIC = ZoneInfo("America/Los_Angeles")
GRIFFIS = "15560 Westminster Way N, Shoreline, WA 98133"
UNIVERSITY_DISTRICT = "University District Station Light Rail"
ARRIVAL_BUFFER_MINUTES = 10
TIMINGS = ("leave_now", "leave_by", "arrive_by")
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.legs.steps.travelMode,routes.legs.steps.transitDetails"


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
    rides = _rides(routes[0]["legs"][0])
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
        "mapsUrl": "https://www.google.com/maps/dir/?"
        + urlencode(
            {
                "api": "1",
                "origin": origin,
                "destination": destination,
                "travelmode": "transit",
            }
        ),
    }


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

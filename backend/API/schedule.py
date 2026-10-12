"""Schedule API.

The schedule is a JSON object with one list per weekday. Each list is sorted
by start time. When Redis is not configured, it is kept in memory.
"""

import json
import os
import uuid
import urllib.request
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

SCHEDULE_KEY = "schedule"
PACIFIC = ZoneInfo("America/Los_Angeles")
CHOICES = ("delete", "keep", "merge")
DELETE_CHOICES = ("only_that_day", "all_future")
FREQUENCIES = ("daily", "weekly", "weekdays", "monthly")
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _empty_week():
    return {day: [] for day in WEEKDAYS}


_memory_schedule = _empty_week()


def put_event(
    start_time,
    end_time,
    activity_name,
    day=None,
    date=None,
    repeating_frequency=None,
    repeating_ends=None,
    choice=None,
):
    """Add one event on a weekday.

    A one-time event requires ``date`` (YYYY-MM-DD). Its weekday comes from
    that date. A weekly or monthly event requires ``day``. ``daily`` is added
    to every weekday, and ``weekdays`` is added to Monday through Friday.

    When the new event overlaps a saved one and ``choice`` is omitted, nothing
    is written. The return value asks her to choose ``delete``, ``keep``, or
    ``merge``. Call this function again with that choice.
    """
    new_event = _make_event(
        start_time,
        end_time,
        activity_name,
        event_date=date,
        repeating_frequency=repeating_frequency,
        repeating_ends=repeating_ends,
    )
    targets = _target_days(new_event.get("repeating_frequency"), day, new_event.get("date"))
    week = _load_schedule()
    for weekday in targets:
        week[weekday] = [event for event in week[weekday] if not _expired(event)]

    overlapping = [
        event
        for weekday in targets
        for event in week[weekday]
        if _overlaps(event, new_event)
    ]
    if overlapping and choice is None:
        _save_schedule(week)
        return {
            "prompt": (
                "This overlaps an existing schedule. "
                "Delete the old schedule, keep the old schedule, or merge them?"
            ),
            "choices": list(CHOICES),
            "old": overlapping,
            "new": new_event,
        }
    if overlapping and choice not in CHOICES:
        raise ValueError("choice must be delete, keep, or merge.")

    overlap_ids = {event["id"] for event in overlapping}
    for weekday in targets:
        events = week[weekday]
        if overlapping and choice == "keep":
            week[weekday] = _sort_events(events)
            continue
        if not overlapping or choice == "merge":
            events = _merge_overlapping(events, overlap_ids, new_event)
        elif choice == "delete":
            events = [event for event in events if event["id"] not in overlap_ids]
        week[weekday] = _sort_events(events)

    _save_schedule(week)
    return get_schedule(targets[0])


def get_schedule(day):
    """Return events for one weekday, or for one calendar date.

    A weekday name returns that day's saved events. A YYYY-MM-DD date returns
    the events that occur on that date. Only that weekday is checked.

    An event is deleted when today's date is after its end date. A one-time
    event ends on its ``date``. A repeating event ends on ``repeating_ends``.
    An event is kept for the whole end date, including after its end time.
    """
    queried = _calendar_date(day)
    weekday = (
        WEEKDAYS[date.fromisoformat(queried).weekday()]
        if queried
        else _normalize_weekday(day)
    )
    week = _load_schedule()
    kept = [event for event in week[weekday] if not _expired(event)]
    week[weekday] = _sort_events(kept)
    _save_schedule(week)
    if queried is None:
        return list(week[weekday])
    return [event for event in week[weekday] if _occurs_on(event, queried)]


def delete_event(activity_name, day, choice=None):
    """Delete an event by name on a calendar date.

    ``day`` is YYYY-MM-DD. A one-time event with that name is removed.
    A repeating event is left unchanged until ``choice`` is set.
    ``only_that_day`` skips that date. ``all_future`` ends the series on the
    day before it.
    """
    name = str(activity_name).strip() if activity_name is not None else ""
    if not name:
        raise ValueError("activity_name is required.")
    day_text = _normalize_ends(day)
    if day_text is None:
        raise ValueError("day is required.")

    weekday = WEEKDAYS[date.fromisoformat(day_text).weekday()]
    current = get_schedule(weekday)
    matches = [
        event
        for event in current
        if event["activity_name"] == name and _occurs_on(event, day_text)
    ]
    if not matches:
        raise ValueError(f"No event named {name} on {day_text}.")

    repeating = [event for event in matches if event.get("repeating_frequency")]
    if repeating and choice is None:
        return {
            "prompt": (
                f"{name} repeats. Delete it only on {day_text}, "
                "or on that day and all future dates?"
            ),
            "choices": list(DELETE_CHOICES),
            "day": day_text,
            "events": repeating,
        }
    if repeating and choice not in DELETE_CHOICES:
        raise ValueError("choice must be only_that_day or all_future.")

    remove_ids = {event["id"] for event in matches if not event.get("repeating_frequency")}
    change_ids = {event["id"] for event in repeating}
    updated = []
    for event in current:
        if event["id"] in remove_ids:
            continue
        if event["id"] in change_ids:
            updated.append(_delete_occurrence(event, day_text, choice))
            continue
        updated.append(event)

    week = _load_schedule()
    week[weekday] = _sort_events(updated)
    _save_schedule(week)
    return get_schedule(weekday)


def _make_event(
    start_time,
    end_time,
    activity_name,
    event_date=None,
    repeating_frequency=None,
    repeating_ends=None,
):
    start = _normalize_time(start_time)
    end = _normalize_time(end_time)
    if _minutes(start) >= _minutes(end):
        raise ValueError("end_time must be after start_time.")
    if not activity_name or not str(activity_name).strip():
        raise ValueError("activity_name is required.")

    frequency = _normalize_frequency(repeating_frequency)
    ends = _normalize_ends(repeating_ends)
    scheduled_date = _normalize_ends(event_date)
    if ends and frequency is None:
        raise ValueError("repeating_ends requires repeating_frequency.")
    if frequency is None and scheduled_date is None:
        raise ValueError("date is required for a one-time event.")

    event = {
        "id": f"sch_{uuid.uuid4().hex[:8]}",
        "start_time": start,
        "end_time": end,
        "activity_name": str(activity_name).strip(),
    }
    if scheduled_date:
        event["date"] = scheduled_date
    if frequency:
        event["repeating_frequency"] = frequency
    if ends:
        event["repeating_ends"] = ends
    return event


def _merge_overlapping(events, overlap_ids, new_event):
    merged = []
    for event in events:
        if event["id"] not in overlap_ids:
            merged.append(event)
            continue
        if event.get("repeating_frequency"):
            skip_day = new_event.get("date")
            if not skip_day:
                raise ValueError("date is required to merge over a repeating event.")
            merged.append(_delete_occurrence(event, skip_day, "only_that_day"))
    merged.append(_copy_event(new_event))
    return merged


def _copy_event(event):
    copied = dict(event)
    copied["id"] = f"sch_{uuid.uuid4().hex[:8]}"
    if "skipped_dates" in copied:
        copied["skipped_dates"] = list(copied["skipped_dates"])
    return copied


def _target_days(frequency, day, event_date):
    weekday = None
    if event_date:
        weekday = WEEKDAYS[date.fromisoformat(event_date).weekday()]
    if day:
        named = _normalize_weekday(day)
        if weekday and named != weekday:
            raise ValueError("day does not match date.")
        weekday = named
    if frequency == "daily":
        return list(WEEKDAYS)
    if frequency == "weekdays":
        return list(WEEKDAYS[:5])
    if weekday is None:
        raise ValueError("day is required.")
    return [weekday]


def _normalize_weekday(value):
    if value is None or str(value).strip() == "":
        raise ValueError("day is required.")
    weekday = str(value).strip().lower()
    if weekday not in WEEKDAYS:
        raise ValueError("day must be a weekday name, Monday through Sunday.")
    return weekday


def _normalize_frequency(value):
    if value is None or str(value).strip() == "":
        return None
    frequency = str(value).strip().lower()
    if frequency not in FREQUENCIES:
        raise ValueError(
            "repeating_frequency must be daily, weekly, weekdays, or monthly."
        )
    return frequency


def _calendar_date(value):
    if value is None:
        return None
    text = str(value).strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return _normalize_ends(text)
    return None


def _normalize_ends(value):
    if value is None or str(value).strip() == "":
        return None
    parsed = datetime.strptime(str(value).strip(), "%Y-%m-%d")
    return parsed.strftime("%Y-%m-%d")


def _expired(event, today=None):
    today = today or datetime.now(PACIFIC).date()
    end = event.get("repeating_ends") if event.get("repeating_frequency") else event.get("date")
    if not end:
        return False
    return date.fromisoformat(end) < today


def _overlaps(left, right):
    if _expired(left) or _expired(right):
        return False
    return _minutes(left["start_time"]) < _minutes(right["end_time"]) and _minutes(
        right["start_time"]
    ) < _minutes(left["end_time"])


def _occurs_on(event, day_text):
    if day_text in event.get("skipped_dates", []):
        return False
    if not event.get("repeating_frequency"):
        return event.get("date") == day_text

    start = event.get("date")
    if start and day_text < start:
        return False
    ends = event.get("repeating_ends")
    if ends and day_text > ends:
        return False
    frequency = event.get("repeating_frequency")
    weekday = date.fromisoformat(day_text).weekday()
    if frequency == "weekdays" and weekday >= 5:
        return False
    if frequency == "weekly" and start and weekday != date.fromisoformat(start).weekday():
        return False
    return True


def _delete_occurrence(event, day_text, choice):
    updated = dict(event)
    if choice == "only_that_day":
        skipped = list(updated.get("skipped_dates", []))
        if day_text not in skipped:
            skipped.append(day_text)
        updated["skipped_dates"] = skipped
        return updated

    previous = (date.fromisoformat(day_text) - timedelta(days=1)).isoformat()
    current_end = updated.get("repeating_ends")
    if current_end is None or previous < current_end:
        updated["repeating_ends"] = previous
    return updated


def _sort_events(events):
    return sorted(events, key=lambda event: event["start_time"])


def _normalize_time(value):
    text = str(value).strip()
    parsed = datetime.strptime(text, "%H:%M")
    return parsed.strftime("%H:%M")


def _minutes(value):
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _load_schedule():
    if _redis_configured():
        raw = _redis("GET", SCHEDULE_KEY)
        stored = json.loads(raw) if raw else _empty_week()
    else:
        stored = _memory_schedule
    if not isinstance(stored, dict):
        stored = _empty_week()
    week = _empty_week()
    for weekday in WEEKDAYS:
        week[weekday] = list(stored.get(weekday, []))
    return week


def _save_schedule(week):
    if _redis_configured():
        _redis("SET", SCHEDULE_KEY, json.dumps(week))
        return
    _memory_schedule.clear()
    _memory_schedule.update(week)


def _redis_configured():
    return _redis_credentials() is not None


def _redis_credentials():
    pairs = (
        ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"),
        ("KV_REST_API_URL", "KV_REST_API_TOKEN"),
    )
    for url_name, token_name in pairs:
        url = os.environ.get(url_name, "").strip()
        token = os.environ.get(token_name, "").strip()
        if url and token:
            return url, token
    return None


def _redis(*command):
    url, token = _redis_credentials()
    url = url.rstrip("/")
    request = urllib.request.Request(
        url,
        data=json.dumps(list(command)).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request) as response:
        body = json.loads(response.read().decode())
    return body.get("result")

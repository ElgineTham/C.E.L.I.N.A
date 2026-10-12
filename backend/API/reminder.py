"""Meal, water, and bus reminders.

Meals are at 09:00, 12:00, and 18:00. Water is every two hours from 09:00
through 20:00, which includes those meal hours. Each icon shows whether to
eat or drink now, congratulates the latest slot she checked off, or names the
latest slot she missed.

``hourly`` sends the meal and water reminder due this hour, and a bus
reminder for each scheduled trip whose leave time is still ahead and at most
an hour away. A leave time that has already passed is skipped. Each reminder
is sent once.

When Redis is not configured, reminders are kept in memory.
"""

import json
import os
import urllib.request
from datetime import datetime, timedelta

import maps

REMINDERS_KEY = "reminders"
MEAL_HOURS = (9, 12, 18)
WATER_HOURS = (9, 11, 12, 14, 16, 18, 20)
KINDS = ("meal", "water")
ROUTE_KINDS = ("school", "home")
SCHOOL_LOOKUP = timedelta(hours=3)

_memory_reminders = []


def food_icon(now):
    """Status of the food icon at ``now``."""
    return _icon("meal", now)


def water_icon(now):
    """Status of the water icon at ``now``."""
    return _icon("water", now)


def icons(now):
    """Both icons for the home card."""
    return {"food": food_icon(now), "water": water_icon(now)}


def check_off(kind, now):
    """Record that she followed the latest meal or water slot at ``now``."""
    kind = _normalize_kind(kind)
    slot = _latest_started_slot(kind, now)
    return _upsert(kind, slot, completedAt=_iso(now))


def hourly(now):
    """Send meal, water, and bus reminders that are due at ``now``.

    A meal hour reminds her to eat and drink. Any other water hour reminds
    her to drink. A bus reminder is sent when that trip's leave time is still
    ahead and no more than an hour away. A slot that was already sent, a
    passed leave time, or an hour with nothing due sends nothing.
    """
    sent = []
    meal = _meal_and_water(now)
    if meal is not None:
        sent.append(meal)
    sent.extend(_route_reminders(now))
    return sent


def _meal_and_water(now):
    due = []
    for kind in KINDS:
        if _icon(kind, now)["status"] != "now":
            continue
        slot = _latest_started_slot(kind, now)
        if _field(kind, slot, "sentAt") is None:
            due.append(kind)

    if not due:
        return None

    if due == ["meal", "water"]:
        message = "Time to eat and drink water."
    elif due == ["water"]:
        message = "Time to drink water."
    else:
        message = "Time to eat."

    sent_at = _iso(now)
    saved = []
    for kind in due:
        saved.append(_upsert(kind, _latest_started_slot(kind, now), sentAt=sent_at))
    return {
        "ids": [item["id"] for item in saved],
        "message": message,
        "kinds": due,
        "at": _iso(_latest_started_slot(due[-1], now)),
    }


def _route_reminders(now):
    sent = []
    for kind in ROUTE_KINDS:
        reminder = _route_reminder(kind, now)
        if reminder is not None:
            sent.append(reminder)
    return sent


def _route_reminder(kind, now):
    """One bus reminder, when its leave time is inside the coming hour."""
    if _by_id(_route_id(kind, now), "sentAt") is not None:
        return None
    if not _route_in_range(kind, now):
        return None
    try:
        route = _scheduled_route(kind, now)
    except (RuntimeError, OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
    leave_at = _parse_time(route.get("leaveAt"))
    if leave_at is None or not _within_coming_hour(now, leave_at):
        return None

    reminder_id = _remember_route(kind, now, leave_at)
    clock = maps._pacific(leave_at).strftime("%H:%M")
    summary = (route.get("summary") or "").strip()
    message = f"Leave by {clock}."
    if summary:
        message = f"{message} {summary}."
    return {
        "id": reminder_id,
        "kind": kind,
        "message": message,
        "at": maps._pacific(leave_at).isoformat(),
    }


def _scheduled_route(kind, now):
    if kind == "school":
        return maps.route_to_university_district(now)
    return maps.route_to_griffis(now)


def _route_in_range(kind, now):
    """Whether the scheduled trip can still leave within the coming hour.

    The school trip leaves before arrival, so it is looked up while that
    arrival is still ahead. The home trip leaves at the last event's end, so
    it is looked up only while that end is still ahead and inside the hour.
    """
    window = maps.day_window(now)
    moment = maps._pacific(now)
    if kind == "school":
        start = window["first_start"]
        if not start:
            return False
        arrive = maps._on_clock(moment, start) - timedelta(minutes=maps.ARRIVAL_BUFFER_MINUTES)
        return moment < arrive <= moment + SCHOOL_LOOKUP
    end = window["last_end"]
    if not end:
        return False
    leave = maps._on_clock(moment, end)
    return moment <= leave <= moment + timedelta(hours=1)


def _within_coming_hour(now, leave_at):
    moment = maps._pacific(now)
    leave_at = maps._pacific(leave_at)
    return moment <= leave_at <= moment + timedelta(hours=1)


def _route_id(kind, now):
    day = maps._pacific(now).date().strftime("%Y%m%d")
    return f"rem_route_{kind}_{day}"


def _parse_time(value):
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return maps._pacific(parsed)


def _remember_route(kind, now, leave_at):
    reminders = _load_reminders()
    reminder_id = _route_id(kind, now)
    found = None
    for reminder in reminders:
        if reminder["id"] == reminder_id:
            found = reminder
            break
    if found is None:
        found = {
            "id": reminder_id,
            "kind": kind,
            "dueAt": maps._pacific(leave_at).isoformat(),
            "sentAt": None,
            "completedAt": None,
        }
        reminders.append(found)
    if found.get("sentAt") is None:
        found["sentAt"] = _iso(now)
        found["dueAt"] = maps._pacific(leave_at).isoformat()
    _save_reminders(reminders)
    return reminder_id


def _by_id(reminder_id, name):
    for reminder in _load_reminders():
        if reminder["id"] == reminder_id:
            return reminder.get(name)
    return None


def _icon(kind, now):
    slot = _latest_started_slot(kind, now)
    at = _iso(slot)
    clock = slot.strftime("%H:%M")
    if _is_current_slot(slot, now) and _field(kind, slot, "completedAt") is None:
        action = "eat" if kind == "meal" else "drink water"
        return {
            "kind": kind,
            "status": "now",
            "at": at,
            "message": f"Time to {action}.",
        }
    if _field(kind, slot, "completedAt") is not None:
        verb = "ate" if kind == "meal" else "drank water"
        return {
            "kind": kind,
            "status": "done",
            "at": at,
            "message": f"You {verb} at {clock}. Nice work.",
        }
    verb = "eaten" if kind == "meal" else "drunk water"
    return {
        "kind": kind,
        "status": "missed",
        "at": at,
        "message": f"You should have {verb} at {clock}.",
    }


def _is_current_slot(slot, now):
    return slot.date() == now.date() and slot.hour == now.hour


def _latest_started_slot(kind, now):
    hours = MEAL_HOURS if kind == "meal" else WATER_HOURS
    started = [hour for hour in hours if _on_day(now, hour) <= now]
    if started:
        return _on_day(now, started[-1])
    yesterday = now - timedelta(days=1)
    return _on_day(yesterday, hours[-1])


def _on_day(moment, hour):
    return moment.replace(hour=hour, minute=0, second=0, microsecond=0)


def _normalize_kind(kind):
    if kind not in KINDS:
        raise ValueError("kind must be meal or water.")
    return kind


def _reminder_id(kind, slot):
    return f"rem_{kind}_{slot.strftime('%Y%m%d_%H%M')}"


def _iso(moment):
    return moment.isoformat()


def _field(kind, slot, name):
    reminder_id = _reminder_id(kind, slot)
    for reminder in _load_reminders():
        if reminder["id"] == reminder_id:
            return reminder.get(name)
    return None


def _upsert(kind, slot, **fields):
    reminders = _load_reminders()
    reminder_id = _reminder_id(kind, slot)
    found = None
    for reminder in reminders:
        if reminder["id"] == reminder_id:
            found = reminder
            break
    if found is None:
        found = {
            "id": reminder_id,
            "kind": kind,
            "dueAt": _iso(slot),
            "sentAt": None,
            "completedAt": None,
        }
        reminders.append(found)
    for name, value in fields.items():
        if found[name] is None:
            found[name] = value
    _save_reminders(reminders)
    return dict(found)


def _load_reminders():
    if _redis_configured():
        raw = _redis("GET", REMINDERS_KEY)
        stored = json.loads(raw) if raw else []
    else:
        stored = _memory_reminders
    if not isinstance(stored, list):
        stored = []
    return [dict(reminder) for reminder in stored]


def _save_reminders(reminders):
    if _redis_configured():
        _redis("SET", REMINDERS_KEY, json.dumps(reminders))
        return
    _memory_reminders.clear()
    _memory_reminders.extend(reminders)


def _redis_configured():
    return bool(
        os.environ.get("UPSTASH_REDIS_REST_URL")
        and os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    )


def _redis(*command):
    url = os.environ["UPSTASH_REDIS_REST_URL"].rstrip("/")
    token = os.environ["UPSTASH_REDIS_REST_TOKEN"]
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

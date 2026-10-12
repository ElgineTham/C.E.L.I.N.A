"""Meal and water reminders.

Meals are at 09:00, 12:00, and 18:00. Water is every two hours from 09:00
through 20:00, which includes those meal hours. Each icon shows whether to
eat or drink now, congratulates the latest slot she checked off, or names the
latest slot she missed. ``hourly`` sends one reminder when an icon is due and
that reminder has not been sent yet.

When Redis is not configured, reminders are kept in memory.
"""

import json
import os
import urllib.request
from datetime import timedelta

REMINDERS_KEY = "reminders"
MEAL_HOURS = (9, 12, 18)
WATER_HOURS = (9, 11, 12, 14, 16, 18, 20)
KINDS = ("meal", "water")

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
    """Send the reminder due this hour, or nothing.

    A meal hour reminds her to eat and drink. Any other water hour reminds
    her to drink. A slot that was already sent, or an hour with nothing due,
    sends nothing. Missed and completed slots stay on the icons.
    """
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
    for kind in due:
        _upsert(kind, _latest_started_slot(kind, now), sentAt=sent_at)
    return {
        "message": message,
        "kinds": due,
        "at": _iso(_latest_started_slot(due[-1], now)),
    }


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

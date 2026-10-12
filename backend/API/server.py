"""Serves the home page, today's schedule, transit routes, and the meal and water icons."""

import json
import sys
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import maps
import reminder
import schedule

ROOT = Path(__file__).resolve().parents[2] / "frontend"
PACIFIC = ZoneInfo("America/Los_Angeles")


def pacific_now():
    return datetime.now(PACIFIC)


def events_on(day):
    return schedule.get_schedule(day)


def today_events(now):
    return events_on(now.date().isoformat())


def icon_states(now):
    return reminder.icons(now)


def transit_routes(now, day=None):
    """Both scheduled trips for ``day``, or for today when ``day`` is omitted.

    The school trip arrives before the first event. The home trip leaves at
    the last event's end. A day other than today is planned from midnight,
    so both of those times are still ahead.
    """
    moment = _moment_on(now, day)
    return {
        "school": maps.route_to_university_district(moment),
        "home": maps.route_to_griffis(moment),
    }


def transit_from_here(now, side, origin):
    """Leave now from a current location toward school or home."""
    if origin is None or not str(origin).strip():
        raise ValueError("origin is required.")
    if side == "school":
        return maps.route_to_university_district(now, origin=origin, timing="leave_now")
    if side == "home":
        return maps.route_to_griffis(now, origin=origin, timing="leave_now")
    raise ValueError("side must be school or home.")


def _moment_on(now, day):
    if not day or day == now.date().isoformat():
        return now
    return datetime.fromisoformat(day).replace(tzinfo=PACIFIC)


def complete_icon(kind, now):
    reminder.check_off(kind, now)
    return reminder.icons(now)


def add_today_event(
    now,
    activity_name,
    start_time,
    end_time,
    choice=None,
    repeating_frequency=None,
    repeating_ends=None,
    day=None,
):
    """Add an event that starts on ``day``, or today when ``day`` is omitted.

    With no frequency it happens once. ``daily``, ``weekdays``, ``weekly``,
    and ``monthly`` repeat from that date until ``repeating_ends``, when that
    is set. An overlap returns the prompt from ``put_event`` instead of saving.
    The returned list is the events on that same date.
    """
    day = day or now.date().isoformat()
    result = schedule.put_event(
        start_time,
        end_time,
        activity_name,
        date=day,
        repeating_frequency=repeating_frequency or None,
        repeating_ends=repeating_ends or None,
        choice=choice,
    )
    if isinstance(result, dict):
        return result
    return events_on(day)


def remove_today_event(now, activity_name, choice=None, day=None):
    """Delete an event on ``day``, or today when ``day`` is omitted.

    A repeat asks how far to delete. The returned list is the events still on
    that date.
    """
    day = day or now.date().isoformat()
    result = schedule.delete_event(activity_name, day, choice=choice)
    if isinstance(result, dict):
        return result
    return events_on(day)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        now = pacific_now()
        if path == "/api/today":
            try:
                self._send(events_on(self._requested_day(now)))
            except ValueError as error:
                self._send({"error": str(error)}, status=400)
            return
        if path == "/api/icons":
            self._send(icon_states(now))
            return
        if path == "/api/routes":
            self._routes(now)
            return
        super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        now = pacific_now()
        if path in ("/api/icons/meal", "/api/icons/water"):
            kind = path.rsplit("/", 1)[-1]
            self._send(complete_icon(kind, now))
            return
        if path in ("/api/today", "/api/today/delete"):
            self._change_schedule(path, now)
            return
        if path == "/api/routes":
            self._route_from_here(now)
            return
        self.send_error(404)

    def _change_schedule(self, path, now):
        try:
            payload = self._read_json()
            choice = payload.get("choice") or None
            day = payload.get("date") or None
            if path == "/api/today":
                result = add_today_event(
                    now,
                    payload.get("activity_name"),
                    payload.get("start_time"),
                    payload.get("end_time"),
                    choice,
                    repeating_frequency=payload.get("repeating_frequency"),
                    repeating_ends=payload.get("repeating_ends"),
                    day=day,
                )
            else:
                result = remove_today_event(
                    now,
                    payload.get("activity_name"),
                    choice,
                    day=day,
                )
        except (ValueError, json.JSONDecodeError, KeyError) as error:
            self._send({"error": str(error)}, status=400)
            return
        self._send(result)

    def _routes(self, now):
        try:
            self._send(transit_routes(now, self._requested_day(now)))
        except (ValueError, RuntimeError) as error:
            self._send({"error": str(error)}, status=400 if isinstance(error, ValueError) else 502)

    def _route_from_here(self, now):
        try:
            payload = self._read_json()
            self._send(transit_from_here(now, payload.get("side"), payload.get("origin")))
        except (ValueError, RuntimeError, json.JSONDecodeError) as error:
            status = 502 if isinstance(error, RuntimeError) else 400
            self._send({"error": str(error)}, status=status)

    def _requested_day(self, now):
        query = parse_qs(urlsplit(self.path).query)
        chosen = (query.get("date") or [None])[0]
        return chosen or now.date().isoformat()

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode())

    def _send(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("C.E.L.I.N.A is at http://127.0.0.1:8765")
    server.serve_forever()


if __name__ == "__main__":
    main()

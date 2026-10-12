"""Serves the home page, today's schedule, transit routes, and the meal and water icons."""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
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


def remind(now):
    """Send due reminders to the phone, or leave them due until it is subscribed."""
    reminders = reminder.hourly(now)
    subscription = reminder.load_push()
    pushed = []
    for item in reminders:
        item_ids = item.get("ids") or ([item["id"]] if item.get("id") else [])
        if subscription and _push_message(subscription, item["message"]):
            pushed.extend(item_ids)
            continue
        reminder.clear_sent(item_ids)
    return {"sent": pushed, "reminders": reminders}


def save_subscription(subscription):
    reminder.save_push(subscription)
    return {"ok": True}


def vapid_public_key():
    key = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    if not key:
        raise RuntimeError("VAPID_PUBLIC_KEY is not set.")
    return {"publicKey": key}


def _push_message(subscription, message):
    private_key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if not private_key:
        return False
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return False
    subject = os.environ.get("VAPID_SUBJECT", "").strip() or "https://celina-seven.vercel.app"
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": "C.E.L.I.N.A", "body": message}),
            vapid_private_key=_vapid_key(private_key),
            vapid_claims={"sub": subject},
        )
    except (WebPushException, OSError, ValueError):
        return False
    return True


def _vapid_key(private_key):
    """Turn a PEM or raw VAPID private key into a key object.

    A PEM stored in an environment variable may arrive as one line. pywebpush
    only reads that form from a file, so the key body is loaded directly.
    """
    from py_vapid import Vapid

    text = private_key.replace("\\n", "\n").strip()
    if "BEGIN" not in text:
        return Vapid.from_string(text)
    parts = [part.strip() for part in text.split("-----") if part.strip()]
    der = "".join(parts[1].split()).encode()
    return Vapid.from_der(der)


def qstash_allows(body, signature, url):
    """Accept QStash when its signature matches, or when no keys are configured."""
    keys = [
        os.environ.get("QSTASH_CURRENT_SIGNING_KEY", "").strip(),
        os.environ.get("QSTASH_NEXT_SIGNING_KEY", "").strip(),
    ]
    keys = [key for key in keys if key]
    if not keys:
        return True
    if not signature:
        return False
    payload = body if isinstance(body, bytes) else str(body).encode()
    for token in signature.split(","):
        if _qstash_token_ok(token.strip(), payload, url, keys):
            return True
    return False


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
        if path == "/api/vapid":
            try:
                self._send(vapid_public_key())
            except RuntimeError as error:
                self._send({"error": str(error)}, status=500)
            return
        if path == "/manifest.webmanifest":
            self._send_file(ROOT / "manifest.webmanifest", "application/manifest+json")
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
        if path == "/api/push":
            try:
                self._send(save_subscription(self._read_json()))
            except (ValueError, json.JSONDecodeError) as error:
                self._send({"error": str(error)}, status=400)
            return
        if path == "/api/remind":
            body = self._read_body()
            signature = self.headers.get("Upstash-Signature")
            url = self._public_url()
            if not qstash_allows(body, signature, url):
                self._send({"error": "Unauthorized."}, status=401)
                return
            self._send(remind(now))
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

    def _send_file(self, path, content_type):
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _public_url(self):
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "")
        host = host.split(",")[0].strip()
        if not host:
            return ""
        proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
        if not proto:
            local = host.startswith("127.") or host.startswith("localhost")
            proto = "http" if local else "https"
        return f"{proto}://{host}{urlsplit(self.path).path}"

    def _read_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return b""
        return self.rfile.read(length)

    def _read_json(self):
        body = self._read_body()
        if not body:
            return {}
        return json.loads(body.decode())

    def _send(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _qstash_token_ok(token, body, url, keys):
    parts = token.split(".")
    if len(parts) != 3:
        return False
    try:
        header = json.loads(_b64url_decode(parts[0]))
        claims = json.loads(_b64url_decode(parts[1]))
        digest = _b64url_decode(parts[2])
    except (ValueError, json.JSONDecodeError):
        return False
    if header.get("alg") != "HS256" or claims.get("iss") != "Upstash":
        return False
    if url and not _same_destination(claims.get("sub"), url):
        return False
    expected = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()
    claimed = str(claims.get("body") or "").replace("=", "")
    if claimed != expected:
        return False
    now = int(time.time())
    exp = claims.get("exp")
    nbf = claims.get("nbf")
    if isinstance(exp, (int, float)) and now > exp + 30:
        return False
    if isinstance(nbf, (int, float)) and now + 30 < nbf:
        return False
    signing_input = f"{parts[0]}.{parts[1]}".encode()
    for key in keys:
        signed = hmac.new(key.encode(), signing_input, hashlib.sha256).digest()
        if hmac.compare_digest(signed, digest):
            return True
    return False


def _same_destination(claimed, actual):
    """Accept the https URL QStash signed when the request arrived as http."""
    if claimed == actual:
        return True
    claimed_parts = urlsplit(claimed or "")
    actual_parts = urlsplit(actual or "")
    if claimed_parts.path != actual_parts.path or not claimed_parts.hostname:
        return False
    if claimed_parts.hostname != actual_parts.hostname:
        return False
    return claimed_parts.scheme == "https" and actual_parts.scheme in ("http", "https")


def _b64url_decode(value):
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    print("C.E.L.I.N.A is at http://127.0.0.1:8765")
    server.serve_forever()


if __name__ == "__main__":
    main()

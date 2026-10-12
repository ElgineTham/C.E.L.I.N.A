import base64
import hashlib
import hmac
import json
import os
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reminder
import schedule
import server
from unittest.mock import patch


PACIFIC = ZoneInfo("America/Los_Angeles")


class ServerTests(unittest.TestCase):
    def setUp(self):
        schedule._memory_schedule.clear()
        reminder._memory_reminders.clear()
        reminder._memory_push.clear()
        self._saved_env = {
            name: os.environ.pop(name, None)
            for name in (
                "UPSTASH_REDIS_REST_URL",
                "UPSTASH_REDIS_REST_TOKEN",
                "KV_REST_API_URL",
                "KV_REST_API_TOKEN",
            )
        }

    def tearDown(self):
        schedule._memory_schedule.clear()
        reminder._memory_reminders.clear()
        reminder._memory_push.clear()
        for name, value in self._saved_env.items():
            if value is not None:
                os.environ[name] = value

    def test_today_returns_events_on_that_date(self):
        now = datetime(2026, 10, 13, 15, 0, tzinfo=PACIFIC)
        schedule.put_event("11:00", "12:00", "Library", date="2026-10-13")
        schedule.put_event("09:00", "10:00", "CHEM 210", date="2026-10-14")

        names = [event["activity_name"] for event in server.today_events(now)]

        self.assertEqual(["Library"], names)

    def test_completing_a_meal_updates_only_the_food_icon(self):
        now = datetime(2026, 10, 13, 9, 10, tzinfo=PACIFIC)

        before = server.icon_states(now)
        after = server.complete_icon("meal", now)

        self.assertEqual("now", before["food"]["status"])
        self.assertEqual("done", after["food"]["status"])
        self.assertEqual("now", after["water"]["status"])

    def test_add_and_delete_change_today(self):
        now = datetime(2026, 10, 13, 15, 0, tzinfo=PACIFIC)

        added = server.add_today_event(now, "Library", "11:00", "12:00")
        self.assertEqual(["Library"], [event["activity_name"] for event in added])

        removed = server.remove_today_event(now, "Library")
        self.assertEqual([], removed)

    def test_an_overlap_asks_before_saving(self):
        now = datetime(2026, 10, 13, 15, 0, tzinfo=PACIFIC)
        server.add_today_event(now, "Library", "11:00", "12:00")

        overlap = server.add_today_event(now, "Lab", "11:30", "12:30")

        self.assertIn("prompt", overlap)
        self.assertEqual(["delete", "keep", "merge"], overlap["choices"])
        kept = server.add_today_event(now, "Lab", "11:30", "12:30", choice="keep")
        self.assertEqual(["Library"], [event["activity_name"] for event in kept])

    def test_a_weekly_event_stays_on_today(self):
        now = datetime(2026, 10, 13, 15, 0, tzinfo=PACIFIC)

        added = server.add_today_event(
            now,
            "CHEM 210",
            "09:00",
            "10:15",
            repeating_frequency="weekly",
            repeating_ends="2026-12-01",
        )

        event = added[0]
        self.assertEqual("CHEM 210", event["activity_name"])
        self.assertEqual("weekly", event["repeating_frequency"])
        self.assertEqual("2026-12-01", event["repeating_ends"])

    def test_adding_on_tuesday_leaves_monday_unchanged(self):
        now = datetime(2026, 10, 12, 15, 0, tzinfo=PACIFIC)

        tuesday = server.add_today_event(
            now, "Lab", "10:00", "11:00", day="2026-10-13"
        )
        monday = server.events_on("2026-10-12")

        self.assertEqual(["Lab"], [event["activity_name"] for event in tuesday])
        self.assertEqual([], monday)
        self.assertEqual([], server.remove_today_event(now, "Lab", day="2026-10-13"))

    def test_routes_follow_the_first_start_and_last_end(self):
        now = datetime(2026, 10, 13, 8, 0, tzinfo=PACIFIC)
        schedule.put_event("09:00", "10:15", "CHEM 210", date="2026-10-13")
        schedule.put_event("14:00", "15:30", "Lab", date="2026-10-13")
        seen = {}

        def school(moment, origin=None, timing=None, when=None):
            seen["school"] = (moment, origin, timing)
            return {"label": "To University District"}

        def home(moment, origin=None, timing=None, when=None):
            seen["home"] = (moment, origin, timing)
            return {"label": "To Griffis Shoreline"}

        with patch("server.maps.route_to_university_district", school), patch(
            "server.maps.route_to_griffis", home
        ):
            routes = server.transit_routes(now, "2026-10-13")

        self.assertEqual("To University District", routes["school"]["label"])
        self.assertEqual("To Griffis Shoreline", routes["home"]["label"])
        self.assertEqual(now, seen["school"][0])
        self.assertIsNone(seen["school"][1])
        self.assertIsNone(seen["home"][2])

    def test_current_location_leaves_now_toward_the_pressed_side(self):
        now = datetime(2026, 10, 13, 16, 0, tzinfo=PACIFIC)
        seen = {}

        def school(moment, origin=None, timing=None, when=None):
            seen["school"] = (origin, timing)
            return {"label": "To University District"}

        def home(moment, origin=None, timing=None, when=None):
            seen["home"] = (origin, timing)
            return {"label": "To Griffis Shoreline"}

        with patch("server.maps.route_to_university_district", school), patch(
            "server.maps.route_to_griffis", home
        ):
            server.transit_from_here(now, "school", "47.66,-122.31")
            server.transit_from_here(now, "home", "47.66,-122.31")

        self.assertEqual(("47.66,-122.31", "leave_now"), seen["school"])
        self.assertEqual(("47.66,-122.31", "leave_now"), seen["home"])

    def test_remind_waits_until_the_phone_is_subscribed(self):
        now = datetime(2026, 10, 13, 9, 2, tzinfo=PACIFIC)

        first = server.remind(now)
        second = server.remind(now)

        self.assertEqual([], first["sent"])
        self.assertEqual("Time to eat and drink water.", first["reminders"][0]["message"])
        self.assertEqual("Time to eat and drink water.", second["reminders"][0]["message"])

    def test_remind_pushes_the_due_reminder_once(self):
        now = datetime(2026, 10, 13, 9, 2, tzinfo=PACIFIC)
        reminder.save_push({
            "endpoint": "https://web.push.apple.com/test",
            "keys": {"p256dh": "key", "auth": "auth"},
        })

        with patch("server._push_message", return_value=True):
            first = server.remind(now)
            second = server.remind(now)

        self.assertEqual(first["reminders"][0]["ids"], first["sent"])
        self.assertEqual([], second["reminders"])

    def test_qstash_signature_is_required_when_keys_are_set(self):
        body = b"{}"
        url = "https://celina-seven.vercel.app/api/remind"
        key = "test-signing-key"
        os.environ["QSTASH_CURRENT_SIGNING_KEY"] = key
        os.environ["QSTASH_NEXT_SIGNING_KEY"] = "next-signing-key"
        try:
            signature = _qstash_signature(body, key, url)
            self.assertTrue(server.qstash_allows(body, signature, url))
            self.assertFalse(server.qstash_allows(body, signature, "https://example.com/api/remind"))
            self.assertFalse(server.qstash_allows(body, None, url))
        finally:
            os.environ.pop("QSTASH_CURRENT_SIGNING_KEY", None)
            os.environ.pop("QSTASH_NEXT_SIGNING_KEY", None)


def _qstash_signature(body, key, url):
    def encode(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    claims = {
        "iss": "Upstash",
        "sub": url,
        "body": encode(hashlib.sha256(body).digest()),
        "iat": now,
        "nbf": now,
        "exp": now + 60,
    }
    payload = encode(json.dumps(claims, separators=(",", ":")).encode())
    digest = hmac.new(key.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{encode(digest)}"


if __name__ == "__main__":
    unittest.main()

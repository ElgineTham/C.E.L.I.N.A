import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reminder
import schedule

PACIFIC = ZoneInfo("America/Los_Angeles")


class ReminderTests(unittest.TestCase):
    def setUp(self):
        reminder._memory_reminders.clear()
        reminder._memory_push.clear()
        schedule._memory_schedule.clear()
        schedule._memory_schedule.update(schedule._empty_week())
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
        reminder._memory_reminders.clear()
        reminder._memory_push.clear()
        schedule._memory_schedule.clear()
        schedule._memory_schedule.update(schedule._empty_week())
        for name, value in self._saved_env.items():
            if value is not None:
                os.environ[name] = value

    def test_meal_hour_asks_her_to_eat_and_drink_once(self):
        now = datetime(2026, 10, 13, 9, 2)

        self.assertEqual("now", reminder.food_icon(now)["status"])
        self.assertEqual("now", reminder.water_icon(now)["status"])
        sent = reminder.hourly(now)

        self.assertEqual("Time to eat and drink water.", sent[0]["message"])
        self.assertEqual(["meal", "water"], sent[0]["kinds"])
        self.assertEqual([], reminder.hourly(now))
        self.assertEqual("now", reminder.food_icon(now)["status"])

    def test_checking_off_during_the_hour_congratulates_that_icon(self):
        now = datetime(2026, 10, 13, 9, 10)
        reminder.hourly(now)
        reminder.check_off("meal", now)

        food = reminder.food_icon(now)
        self.assertEqual("done", food["status"])
        self.assertEqual("You ate at 09:00. Nice work.", food["message"])
        self.assertEqual("now", reminder.water_icon(now)["status"])
        self.assertEqual([], reminder.hourly(now))

    def test_water_hour_reminds_her_to_drink_and_food_shows_the_last_meal(self):
        missed = datetime(2026, 10, 13, 11, 0)
        drink = reminder.hourly(missed)

        self.assertEqual(["water"], drink[0]["kinds"])
        self.assertEqual("missed", reminder.food_icon(missed)["status"])
        self.assertEqual(
            "You should have eaten at 09:00.",
            reminder.food_icon(missed)["message"],
        )

        reminder._memory_reminders.clear()
        reminder.check_off("meal", datetime(2026, 10, 13, 9, 20))
        later = datetime(2026, 10, 13, 11, 5)

        self.assertEqual("done", reminder.food_icon(later)["status"])
        self.assertEqual("Time to drink water.", reminder.hourly(later)[0]["message"])

    def test_quiet_hours_send_nothing(self):
        self.assertEqual([], reminder.hourly(datetime(2026, 10, 13, 10, 0)))
        self.assertEqual([], reminder.hourly(datetime(2026, 10, 13, 21, 0)))

    def test_before_the_window_uses_yesterday(self):
        now = datetime(2026, 10, 13, 8, 30)

        self.assertEqual("missed", reminder.food_icon(now)["status"])
        self.assertEqual("You should have eaten at 18:00.", reminder.food_icon(now)["message"])
        self.assertEqual(
            "You should have drunk water at 20:00.",
            reminder.water_icon(now)["message"],
        )
        self.assertEqual([], reminder.hourly(now))

    def test_a_late_check_off_still_counts(self):
        now = datetime(2026, 10, 13, 10, 30)
        reminder.check_off("water", now)

        water = reminder.water_icon(now)
        self.assertEqual("done", water["status"])
        self.assertEqual("You drank water at 09:00. Nice work.", water["message"])

    def test_a_push_subscription_is_saved_and_loaded(self):
        saved = reminder.save_push({
            "endpoint": "https://web.push.apple.com/test",
            "keys": {"p256dh": "key", "auth": "auth"},
        })

        self.assertEqual(saved, reminder.load_push())

        with self.assertRaises(ValueError):
            reminder.save_push({"endpoint": "https://web.push.apple.com/test"})

    def test_school_route_sends_once_when_leave_time_is_within_the_hour(self):
        now = datetime(2026, 10, 13, 8, 0, tzinfo=PACIFIC)
        schedule.put_event("09:30", "10:30", "CHEM 210", date="2026-10-13")

        with self._routes(school_leave="2026-10-13T08:40:00-07:00"):
            sent = reminder.hourly(now)
            again = reminder.hourly(now)

        self.assertEqual(["school"], [item["kind"] for item in sent])
        self.assertEqual(
            "Leave by 08:40. Light Rail 1 from Westminster Way to University District.",
            sent[0]["message"],
        )
        self.assertEqual("rem_route_school_20261013", sent[0]["id"])
        self.assertEqual([], again)

    def test_leave_time_right_now_still_sends(self):
        now = datetime(2026, 10, 13, 8, 0, tzinfo=PACIFIC)
        schedule.put_event("09:00", "10:00", "CHEM 210", date="2026-10-13")

        with self._routes(school_leave="2026-10-13T08:00:00-07:00"):
            sent = reminder.hourly(now)

        self.assertEqual(["school"], [item["kind"] for item in sent])

    def test_leave_time_an_hour_away_sends_and_a_minute_later_does_not(self):
        now = datetime(2026, 10, 13, 8, 0, tzinfo=PACIFIC)
        schedule.put_event("10:00", "11:00", "CHEM 210", date="2026-10-13")

        with self._routes(school_leave="2026-10-13T09:00:00-07:00"):
            sent = reminder.hourly(now)
        self.assertEqual(["school"], [item["kind"] for item in sent])

        reminder._memory_reminders.clear()
        with self._routes(school_leave="2026-10-13T09:01:00-07:00"):
            self.assertEqual([], reminder.hourly(now))

    def test_a_passed_leave_time_is_not_sent(self):
        now = datetime(2026, 10, 13, 8, 10, tzinfo=PACIFIC)
        schedule.put_event("09:00", "10:00", "CHEM 210", date="2026-10-13")

        with self._routes(school_leave="2026-10-13T08:09:00-07:00"):
            self.assertEqual([], reminder.hourly(now))

        self.assertIsNone(reminder._by_id("rem_route_school_20261013", "sentAt"))

    def test_home_route_sends_when_the_last_event_is_within_the_hour(self):
        now = datetime(2026, 10, 13, 15, 0, tzinfo=PACIFIC)
        schedule.put_event("09:00", "15:40", "Lab", date="2026-10-13")

        with self._routes(home_leave="2026-10-13T15:20:00-07:00", school_called=False):
            sent = reminder.hourly(now)

        self.assertEqual(["home"], [item["kind"] for item in sent])
        self.assertEqual("Leave by 15:20. Bus 67 from Campus to Griffis.", sent[0]["message"])

    def test_a_route_lookup_failure_still_sends_the_meal(self):
        now = datetime(2026, 10, 13, 9, 2, tzinfo=PACIFIC)
        schedule.put_event("10:00", "11:00", "CHEM 210", date="2026-10-13")

        def school(moment, origin=None, timing=None, when=None):
            raise RuntimeError("Google Maps returned no transit route.")

        with patch("reminder.maps.route_to_university_district", school), patch(
            "reminder.maps.route_to_griffis", lambda *args, **kwargs: {}
        ):
            sent = reminder.hourly(now)

        self.assertEqual(["Time to eat and drink water."], [item["message"] for item in sent])

    def test_an_empty_day_does_not_look_up_a_route(self):
        now = datetime(2026, 10, 13, 8, 0, tzinfo=PACIFIC)

        def unavailable(moment, origin=None, timing=None, when=None):
            raise AssertionError("no route on an empty day")

        with patch("reminder.maps.route_to_university_district", unavailable), patch(
            "reminder.maps.route_to_griffis", unavailable
        ):
            self.assertEqual([], reminder.hourly(now))

    def _routes(self, school_leave=None, home_leave=None, school_called=True):
        def school(moment, origin=None, timing=None, when=None):
            if not school_called:
                raise AssertionError("school route is not due")
            return {
                "leaveAt": school_leave,
                "summary": "Light Rail 1 from Westminster Way to University District",
            }

        def home(moment, origin=None, timing=None, when=None):
            if home_leave is None:
                raise AssertionError("home route is not due")
            return {
                "leaveAt": home_leave,
                "summary": "Bus 67 from Campus to Griffis",
            }

        return patch.multiple(
            "reminder.maps",
            route_to_university_district=school,
            route_to_griffis=home,
        )


if __name__ == "__main__":
    unittest.main()

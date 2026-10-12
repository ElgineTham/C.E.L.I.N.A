import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reminder
import schedule
import server


PACIFIC = ZoneInfo("America/Los_Angeles")


class ServerTests(unittest.TestCase):
    def setUp(self):
        schedule._memory_schedule.clear()
        reminder._memory_reminders.clear()
        self._saved_env = {
            name: os.environ.pop(name, None)
            for name in ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN")
        }

    def tearDown(self):
        schedule._memory_schedule.clear()
        reminder._memory_reminders.clear()
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


if __name__ == "__main__":
    unittest.main()

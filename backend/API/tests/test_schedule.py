import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import schedule


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        schedule._memory_schedule.clear()
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
        for name, value in self._saved_env.items():
            if value is not None:
                os.environ[name] = value

    def test_valid_events_appear_on_their_dates(self):
        start = _next_weekday(0)
        middle = start + timedelta(days=14)
        end = start + timedelta(days=28)
        visit = _next_weekday(1)

        schedule.put_event("11:00", "12:00", "Library", date=_text(visit))
        schedule.put_event(
            "09:00",
            "10:15",
            "CHEM 210",
            date=_text(start),
            repeating_frequency="weekly",
            repeating_ends=_text(end),
        )

        self.assertEqual(["Library"], _names(schedule.get_schedule(_text(visit))))
        self.assertEqual(["CHEM 210"], _names(schedule.get_schedule(_text(start))))
        self.assertEqual(["CHEM 210"], _names(schedule.get_schedule(_text(middle))))
        self.assertEqual(["CHEM 210"], _names(schedule.get_schedule(_text(end))))

    def test_overlap_keep_and_merge_for_a_one_time_event(self):
        visit = _text(_next_weekday(1))
        schedule.put_event("09:00", "10:15", "CHEM 210", date=visit)
        schedule.put_event("10:00", "11:00", "Lab", date=visit, choice="keep")

        self.assertEqual(["CHEM 210"], _names(schedule.get_schedule(visit)))

        schedule._memory_schedule.clear()
        schedule.put_event("09:00", "10:15", "CHEM 210", date=visit)
        schedule.put_event("10:00", "11:00", "Lab", date=visit, choice="merge")

        self.assertEqual(["Lab"], _names(schedule.get_schedule(visit)))

    def test_overlap_keep_and_merge_for_a_repeating_event(self):
        start = _next_weekday(0)
        changed = start + timedelta(days=14)
        later = start + timedelta(days=28)

        schedule.put_event(
            "09:00",
            "10:15",
            "CHEM 210",
            date=_text(start),
            repeating_frequency="weekly",
            repeating_ends=_text(later),
        )
        schedule.put_event("09:30", "10:45", "Lab", date=_text(changed), choice="keep")

        self.assertEqual(["CHEM 210"], _names(schedule.get_schedule(_text(changed))))
        self.assertNotIn("Lab", _names(schedule.get_schedule(_text(later))))

        schedule._memory_schedule.clear()
        schedule.put_event(
            "09:00",
            "10:15",
            "CHEM 210",
            date=_text(start),
            repeating_frequency="weekly",
            repeating_ends=_text(later),
        )
        schedule.put_event("09:30", "10:45", "Lab", date=_text(changed), choice="merge")

        self.assertEqual(["Lab"], _names(schedule.get_schedule(_text(changed))))
        self.assertEqual(["CHEM 210"], _names(schedule.get_schedule(_text(start))))
        self.assertEqual(["CHEM 210"], _names(schedule.get_schedule(_text(later))))

    def test_delete_removes_a_repeating_series_from_that_date_and_a_one_time_event(self):
        start = _next_weekday(0)
        removed = start + timedelta(days=14)
        later = start + timedelta(days=28)
        visit = _next_weekday(2)

        schedule.put_event(
            "09:00",
            "10:15",
            "CHEM 210",
            date=_text(start),
            repeating_frequency="weekly",
            repeating_ends=_text(later),
        )
        schedule.put_event("11:00", "12:00", "Library", date=_text(visit))

        schedule.delete_event("CHEM 210", _text(removed), choice="all_future")

        self.assertNotIn("CHEM 210", _names(schedule.get_schedule(_text(removed))))
        self.assertNotIn("CHEM 210", _names(schedule.get_schedule(_text(later))))
        self.assertEqual(["CHEM 210"], _names(schedule.get_schedule(_text(start))))

        schedule.delete_event("Library", _text(visit))

        self.assertNotIn("Library", _names(schedule.get_schedule(_text(visit))))


def _next_weekday(weekday):
    today = date.today()
    delta = (weekday - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _text(value):
    return value.isoformat()


def _names(events):
    return [event["activity_name"] for event in events]


if __name__ == "__main__":
    unittest.main()

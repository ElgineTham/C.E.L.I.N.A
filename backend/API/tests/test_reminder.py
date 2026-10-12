import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reminder


class ReminderTests(unittest.TestCase):
    def setUp(self):
        reminder._memory_reminders.clear()
        self._saved_env = {
            name: os.environ.pop(name, None)
            for name in ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN")
        }

    def tearDown(self):
        reminder._memory_reminders.clear()
        for name, value in self._saved_env.items():
            if value is not None:
                os.environ[name] = value

    def test_meal_hour_asks_her_to_eat_and_drink_once(self):
        now = datetime(2026, 10, 13, 9, 2)

        self.assertEqual("now", reminder.food_icon(now)["status"])
        self.assertEqual("now", reminder.water_icon(now)["status"])
        sent = reminder.hourly(now)

        self.assertEqual("Time to eat and drink water.", sent["message"])
        self.assertEqual(["meal", "water"], sent["kinds"])
        self.assertIsNone(reminder.hourly(now))
        self.assertEqual("now", reminder.food_icon(now)["status"])

    def test_checking_off_during_the_hour_congratulates_that_icon(self):
        now = datetime(2026, 10, 13, 9, 10)
        reminder.hourly(now)
        reminder.check_off("meal", now)

        food = reminder.food_icon(now)
        self.assertEqual("done", food["status"])
        self.assertEqual("You ate at 09:00. Nice work.", food["message"])
        self.assertEqual("now", reminder.water_icon(now)["status"])
        self.assertIsNone(reminder.hourly(now))

    def test_water_hour_reminds_her_to_drink_and_food_shows_the_last_meal(self):
        missed = datetime(2026, 10, 13, 11, 0)
        drink = reminder.hourly(missed)

        self.assertEqual(["water"], drink["kinds"])
        self.assertEqual("missed", reminder.food_icon(missed)["status"])
        self.assertEqual(
            "You should have eaten at 09:00.",
            reminder.food_icon(missed)["message"],
        )

        reminder._memory_reminders.clear()
        reminder.check_off("meal", datetime(2026, 10, 13, 9, 20))
        later = datetime(2026, 10, 13, 11, 5)

        self.assertEqual("done", reminder.food_icon(later)["status"])
        self.assertEqual("Time to drink water.", reminder.hourly(later)["message"])

    def test_quiet_hours_send_nothing(self):
        self.assertIsNone(reminder.hourly(datetime(2026, 10, 13, 10, 0)))
        self.assertIsNone(reminder.hourly(datetime(2026, 10, 13, 21, 0)))

    def test_before_the_window_uses_yesterday(self):
        now = datetime(2026, 10, 13, 8, 30)

        self.assertEqual("missed", reminder.food_icon(now)["status"])
        self.assertEqual("You should have eaten at 18:00.", reminder.food_icon(now)["message"])
        self.assertEqual(
            "You should have drunk water at 20:00.",
            reminder.water_icon(now)["message"],
        )
        self.assertIsNone(reminder.hourly(now))

    def test_a_late_check_off_still_counts(self):
        now = datetime(2026, 10, 13, 10, 30)
        reminder.check_off("water", now)

        water = reminder.water_icon(now)
        self.assertEqual("done", water["status"])
        self.assertEqual("You drank water at 09:00. Nice work.", water["message"])


if __name__ == "__main__":
    unittest.main()

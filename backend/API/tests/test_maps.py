import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import maps
import schedule


class _Body:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _leg():
    return {
        "routes": [
            {
                "legs": [
                    {
                        "steps": [
                            {
                                "travelMode": "TRANSIT",
                                "transitDetails": {
                                    "stopDetails": {
                                        "departureStop": {"name": "Westminster Way"},
                                        "arrivalStop": {"name": "Shoreline North Station"},
                                        "departureTime": "2026-10-13T08:10:00-07:00",
                                        "arrivalTime": "2026-10-13T08:25:00-07:00",
                                    },
                                    "transitLine": {
                                        "nameShort": "348",
                                        "vehicle": {"name": {"text": "Bus"}},
                                    },
                                },
                            },
                            {
                                "travelMode": "TRANSIT",
                                "transitDetails": {
                                    "stopDetails": {
                                        "departureStop": {"name": "Shoreline North Station"},
                                        "arrivalStop": {"name": "University District Station"},
                                        "departureTime": "2026-10-13T08:32:00-07:00",
                                        "arrivalTime": "2026-10-13T08:50:00-07:00",
                                    },
                                    "transitLine": {
                                        "nameShort": "1 Line",
                                        "vehicle": {"name": {"text": "Light rail"}},
                                    },
                                },
                            },
                        ]
                    }
                ]
            }
        ]
    }


def _sent(request):
    return json.loads(request.data.decode())


class MapsTests(unittest.TestCase):
    def setUp(self):
        schedule._memory_schedule.clear()
        self._saved_env = {
            name: os.environ.pop(name, None)
            for name in (
                "UPSTASH_REDIS_REST_URL",
                "UPSTASH_REDIS_REST_TOKEN",
                "KV_REST_API_URL",
                "KV_REST_API_TOKEN",
                "GOOGLE_MAPS_API_KEY",
            )
        }
        os.environ["GOOGLE_MAPS_API_KEY"] = "test-key"

    def tearDown(self):
        schedule._memory_schedule.clear()
        for name, value in self._saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_day_window_uses_the_earliest_start_and_latest_end(self):
        schedule.put_event("14:00", "15:30", "Lab", date="2026-10-13")
        schedule.put_event("09:00", "10:15", "CHEM 210", date="2026-10-13")
        now = datetime(2026, 10, 13, 8, 0)

        self.assertEqual(
            {"first_start": "09:00", "last_end": "15:30"},
            maps.day_window(now),
        )

    def test_empty_day_has_no_window(self):
        self.assertEqual(
            {"first_start": None, "last_end": None},
            maps.day_window(datetime(2026, 10, 13, 8, 0)),
        )

    def test_campus_route_arrives_before_the_first_event(self):
        schedule.put_event("09:00", "10:15", "CHEM 210", date="2026-10-13")
        schedule.put_event("14:00", "15:30", "Lab", date="2026-10-13")
        captured = {}

        def capture(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Body(_leg())

        with patch("maps.urlopen", capture):
            route = maps.route_to_university_district(datetime(2026, 10, 13, 7, 0))

        body = _sent(captured["request"])
        self.assertEqual(maps.ROUTES_URL, captured["request"].full_url)
        self.assertEqual(
            {"address": "15560 Westminster Way N, Shoreline, WA 98133"},
            body["origin"],
        )
        self.assertEqual(
            {"address": "University District Station Light Rail"},
            body["destination"],
        )
        self.assertEqual("TRANSIT", body["travelMode"])
        self.assertEqual("arrive_by", route["timing"])
        self.assertIn("T08:50:00", route["when"])
        self.assertNotIn("departureTime", body)
        self.assertIn("T08:50:00", body["arrivalTime"])
        self.assertEqual("2026-10-13T08:10:00-07:00", route["leaveAt"])
        self.assertEqual("2026-10-13T08:50:00-07:00", route["arriveAt"])
        self.assertEqual(
            "Bus 348 from Westminster Way to Shoreline North Station, "
            "then Light rail 1 Line from Shoreline North Station to University District Station",
            route["summary"],
        )
        self.assertIn("3e3", route["mapsUrl"])

    def test_home_route_leaves_at_the_last_event_end(self):
        schedule.put_event("09:00", "10:15", "CHEM 210", date="2026-10-13")
        schedule.put_event("14:00", "15:30", "Lab", date="2026-10-13")
        captured = {}

        def capture(request, timeout):
            captured["request"] = request
            return _Body(_leg())

        with patch("maps.urlopen", capture):
            route = maps.route_to_griffis(datetime(2026, 10, 13, 12, 0))

        body = _sent(captured["request"])
        self.assertEqual(
            {"address": "University District Station Light Rail"},
            body["origin"],
        )
        self.assertEqual(
            {"address": "15560 Westminster Way N, Shoreline, WA 98133"},
            body["destination"],
        )
        self.assertEqual("leave_by", route["timing"])
        self.assertIn("T15:30:00", route["when"])
        self.assertIn("T15:30:00", body["departureTime"])
        self.assertNotIn("arrivalTime", body)

    def test_current_location_uses_the_chosen_time(self):
        captured = {}

        def capture(request, timeout):
            captured["request"] = request
            return _Body(_leg())

        with patch("maps.urlopen", capture):
            route = maps.route_to_university_district(
                datetime(2026, 10, 13, 16, 0),
                origin=(47.66, -122.31),
                timing="arrive_by",
                when="18:00",
            )

        body = _sent(captured["request"])
        self.assertEqual(
            {"location": {"latLng": {"latitude": 47.66, "longitude": -122.31}}},
            body["origin"],
        )
        self.assertEqual(
            {"address": "University District Station Light Rail"},
            body["destination"],
        )
        self.assertEqual("arrive_by", route["timing"])
        self.assertIn("T18:00:00", route["when"])

    def test_current_location_requires_a_time_choice(self):
        with self.assertRaises(ValueError):
            maps.route_to_griffis(
                datetime(2026, 10, 13, 16, 0),
                origin="47.66,-122.31",
            )

    def test_maps_link_follows_arrive_by_or_leave_by(self):
        leave = datetime.fromisoformat("2026-10-13T09:40:00-07:00")
        arrive = datetime.fromisoformat("2026-10-13T10:12:00-07:00")
        arrival = maps._maps_url("Home", "School", leave.isoformat(), arrive.isoformat(), "arrive_by", arrive)
        departure = maps._maps_url("School", "Home", leave.isoformat(), arrive.isoformat(), "leave_by", leave)

        self.assertIn("6e1", arrival)
        self.assertNotIn("6e0", arrival)
        self.assertIn(str(int(arrive.timestamp())), arrival)
        self.assertIn("6e0", departure)
        self.assertNotIn("6e1", departure)
        self.assertIn(str(int(leave.timestamp())), departure)

    def test_past_class_start_leaves_now(self):
        schedule.put_event("09:00", "10:15", "CHEM 210", date="2026-10-13")
        captured = {}

        def capture(request, timeout):
            captured["request"] = request
            return _Body(_leg())

        with patch("maps.urlopen", capture):
            route = maps.route_to_university_district(datetime(2026, 10, 13, 9, 30))

        body = _sent(captured["request"])
        self.assertEqual("leave_by", route["timing"])
        self.assertIn("departureTime", body)
        self.assertNotIn("arrivalTime", body)


if __name__ == "__main__":
    unittest.main()

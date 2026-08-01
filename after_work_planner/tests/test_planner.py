import unittest

from planner import create_evening_plan


class PlannerTests(unittest.TestCase):
    def test_home_dinner_adds_dishes_and_shower(self):
        result = create_evening_plan(
            arrival_time="19:00",
            dinner_mode="home",
            shower_mode="quick",
            daily_tasks=["exercise"],
            auto_enjoyment=False,
        )
        tasks = [item["task"] for item in result["evening_schedule"]]
        self.assertIn("Cook and eat dinner at home", tasks)
        self.assertIn("Wash the dishes", tasks)
        self.assertIn("Take a quick shower", tasks)
        self.assertEqual(result["status"], "ok")

    def test_far_restaurant_falls_back_to_home(self):
        result = create_evening_plan(
            arrival_time="19:00",
            dinner_mode="outside",
            restaurant_distance_km=2.4,
            auto_enjoyment=False,
        )
        tasks = [item["task"] for item in result["evening_schedule"]]
        self.assertIn("Cook and eat dinner at home", tasks)
        self.assertTrue(any("exceeds 1 km" in item for item in result["warnings"]))

    def test_overflow_never_pushes_bedtime_past_0130(self):
        result = create_evening_plan(
            arrival_time="21:30",
            dinner_mode="home",
            shower_mode="full",
            daily_tasks=["groceries", "exercise", "study", "cleaning", "laundry"],
            enjoyment_tasks=["cinema", "tv"],
            auto_enjoyment=False,
        )
        self.assertLessEqual(
            int(result["bedtime"].split(":")[0]) * 60
            + int(result["bedtime"].split(":")[1]),
            90,
        )
        self.assertTrue(result["morning_schedule"])

    def test_after_midnight_arrival_uses_next_day_window(self):
        result = create_evening_plan(
            arrival_time="00:10",
            dinner_mode="home",
            shower_mode="quick",
            auto_enjoyment=False,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["bedtime"], "01:30")
        self.assertEqual(result["sleep_duration"], "6h 10min")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from typing import Literal


def create_evening_plan(
    arrival_time: str,
    overtime_minutes: int = 0,
    dinner_mode: Literal["home", "outside"] = "home",
    restaurant_distance_km: float | None = None,
    shower_mode: Literal["quick", "full"] = "quick",
    daily_tasks: list[
        Literal["groceries", "exercise", "study", "cleaning", "laundry"]
    ]
    | None = None,
    enjoyment_tasks: list[
        Literal["cinema", "friends_dinner", "tv", "tiktok", "shopping"]
    ]
    | None = None,
    custom_tasks: list[str] | None = None,
    preferred_bedtime: str = "23:30",
    work_departure_time: str = "08:00",
    auto_enjoyment: bool = True,
) -> dict:
    """Create a constraint-checked after-work plan.

    Args:
        arrival_time: Normal home-arrival time in HH:MM.
        overtime_minutes: Extra delay caused by overtime.
        dinner_mode: "home" or "outside".
        restaurant_distance_km: Restaurant distance from home. Outside dining
            must be at most 1 km. Use null if the restaurant is not selected yet.
        shower_mode: "quick" for 10 minutes or "full" for 30 minutes.
        daily_tasks: Requested daily needs. Durations are groceries 30,
            exercise 60, study 60, cleaning 60, and laundry loading 5 minutes.
        enjoyment_tasks: Optional enjoyment activities. Durations are cinema
            120, dinner with friends 120, TV 60, TikTok 60, and shopping 120.
            Dinner with friends replaces the normal dinner. Shopping is placed
            next to outside dining when both are selected.
        custom_tasks: Extra tasks in the exact form "name|minutes|category",
            where category is mandatory, daily, or enjoyment.
        preferred_bedtime: Normal target bedtime in HH:MM.
        work_departure_time: Time to leave for work in HH:MM. Morning
            preparation occupies the 20 minutes before this time.
        auto_enjoyment: Add one hour of TV when the evening is otherwise light.
    """
    daily_tasks = list(dict.fromkeys(daily_tasks or []))
    enjoyment_tasks = list(dict.fromkeys(enjoyment_tasks or []))
    custom_tasks = custom_tasks or []
    warnings: list[str] = []
    violations: list[str] = []

    try:
        arrival_h, arrival_m = [int(value) for value in arrival_time.split(":")]
        bedtime_h, bedtime_m = [int(value) for value in preferred_bedtime.split(":")]
        work_h, work_m = [int(value) for value in work_departure_time.split(":")]
        if not (
            0 <= arrival_h <= 23
            and 0 <= arrival_m <= 59
            and 0 <= bedtime_h <= 23
            and 0 <= bedtime_m <= 59
            and 0 <= work_h <= 23
            and 0 <= work_m <= 59
            and overtime_minutes >= 0
        ):
            raise ValueError
    except (ValueError, AttributeError):
        return {
            "status": "error",
            "message": "Times must use HH:MM format and overtime_minutes cannot be negative.",
        }

    arrival = arrival_h * 60 + arrival_m
    if arrival < 6 * 60:
        arrival += 1440
    arrival += overtime_minutes
    preferred = bedtime_h * 60 + bedtime_m
    if preferred <= arrival:
        preferred += 1440
    latest_bedtime = 25 * 60 + 30  # 01:30 on the following day
    work_departure = work_h * 60 + work_m
    prep_start = work_departure - 20

    if arrival >= latest_bedtime:
        return {
            "status": "error",
            "message": "The arrival time is already at or after 01:30, so no valid evening plan can be created.",
        }

    if dinner_mode == "outside":
        if restaurant_distance_km is None:
            warnings.append(
                "No restaurant has been selected yet. Outside dining must be within 1 km of home."
            )
        elif restaurant_distance_km > 1:
            warnings.append(
                f"The restaurant is {restaurant_distance_km:g} km away, which exceeds 1 km. Dinner was changed to home cooking."
            )
            dinner_mode = "home"

    friends_dinner = "friends_dinner" in enjoyment_tasks
    if friends_dinner and restaurant_distance_km is not None and restaurant_distance_km > 1:
        friends_dinner = False
        enjoyment_tasks.remove("friends_dinner")
        dinner_mode = "home"
        warnings.append(
            "The dinner location with friends exceeds 1 km, so it was not used as tonight's outside dinner."
        )
    elif friends_dinner:
        dinner_mode = "outside"

    night_candidates: list[dict] = []
    if "laundry" in daily_tasks:
        night_candidates.append(
            {"name": "Load clothes into the washing machine", "minutes": 5, "category": "daily"}
        )
    if "groceries" in daily_tasks and dinner_mode == "home":
        night_candidates.append(
            {"name": "Buy groceries", "minutes": 30, "category": "daily"}
        )
    if "shopping" in enjoyment_tasks and dinner_mode == "outside":
        night_candidates.append(
            {"name": "Shop for clothes", "minutes": 120, "category": "enjoyment"}
        )

    if friends_dinner:
        night_candidates.append(
            {"name": "Have dinner out with friends", "minutes": 120, "category": "mandatory"}
        )
    elif dinner_mode == "outside":
        distance_text = (
            f"{restaurant_distance_km:g} km"
            if restaurant_distance_km is not None
            else "not selected yet (must be ≤ 1 km)"
        )
        night_candidates.append(
            {
                "name": f"Have dinner out; restaurant distance: {distance_text}",
                "minutes": 60,
                "category": "mandatory",
            }
        )
    else:
        night_candidates.extend(
            [
                {"name": "Cook and eat dinner at home", "minutes": 60, "category": "mandatory"},
                {"name": "Wash the dishes", "minutes": 10, "category": "mandatory"},
            ]
        )

    if "exercise" in daily_tasks:
        night_candidates.append(
            {"name": "Exercise", "minutes": 60, "category": "daily"}
        )
    night_candidates.append(
        {
            "name": "Take a quick shower" if shower_mode == "quick" else "Take a full shower",
            "minutes": 10 if shower_mode == "quick" else 30,
            "category": "mandatory",
        }
    )
    for task_name, label, duration in [
        ("study", "Personal development", 60),
        ("cleaning", "Clean the home", 60),
        ("groceries", "Buy groceries", 30),
    ]:
        if task_name in daily_tasks and not (
            task_name == "groceries" and dinner_mode == "home"
        ):
            night_candidates.append(
                {"name": label, "minutes": duration, "category": "daily"}
            )

    if "shopping" in enjoyment_tasks and dinner_mode != "outside":
        night_candidates.append(
            {"name": "Shop for clothes", "minutes": 120, "category": "enjoyment"}
        )
    for task_name, label, duration in [
        ("cinema", "Go to the cinema", 120),
        ("tv", "Watch a TV series", 60),
        ("tiktok", "Browse TikTok", 60),
    ]:
        if task_name in enjoyment_tasks:
            night_candidates.append(
                {"name": label, "minutes": duration, "category": "enjoyment"}
            )

    for raw_task in custom_tasks:
        try:
            name, minutes_text, category = [part.strip() for part in raw_task.split("|")]
            minutes = int(minutes_text)
            if not name or minutes <= 0 or category not in {
                "mandatory",
                "daily",
                "enjoyment",
            }:
                raise ValueError
            night_candidates.append(
                {"name": name, "minutes": minutes, "category": category}
            )
        except (ValueError, AttributeError):
            warnings.append(
                f'Ignored malformed custom task: "{raw_task}". Use name|minutes|category.'
            )

    evening_schedule: list[dict] = []
    morning_pending: list[dict] = []
    skipped_enjoyment: list[str] = []
    cursor = arrival

    for task in night_candidates:
        task_end = cursor + task["minutes"]
        if task_end <= latest_bedtime:
            evening_schedule.append(
                {
                    "start": f"{(cursor // 60) % 24:02d}:{cursor % 60:02d}",
                    "end": f"{(task_end // 60) % 24:02d}:{task_end % 60:02d}",
                    "task": task["name"],
                    "type": task["category"],
                }
            )
            cursor = task_end
        elif task["category"] == "daily":
            morning_pending.append(task)
        elif task["category"] == "enjoyment":
            skipped_enjoyment.append(task["name"])
        else:
            violations.append(
                f'The mandatory task "{task["name"]}" cannot be completed before 01:30.'
            )

    explicit_enjoyment = bool(enjoyment_tasks) or any(
        item.endswith("|enjoyment") for item in custom_tasks
    )
    if (
        auto_enjoyment
        and not explicit_enjoyment
        and cursor + 60 <= min(preferred, latest_bedtime)
    ):
        evening_schedule.append(
            {
                "start": f"{(cursor // 60) % 24:02d}:{cursor % 60:02d}",
                "end": f"{((cursor + 60) // 60) % 24:02d}:{(cursor + 60) % 60:02d}",
                "task": "Watch a TV series (automatically added leisure activity)",
                "type": "enjoyment",
            }
        )
        cursor += 60

    bedtime = min(max(cursor, preferred), latest_bedtime)
    if cursor < bedtime:
        evening_schedule.append(
            {
                "start": f"{(cursor // 60) % 24:02d}:{cursor % 60:02d}",
                "end": f"{(bedtime // 60) % 24:02d}:{bedtime % 60:02d}",
                "task": "Free time, relaxation, and bedtime preparation",
                "type": "buffer",
            }
        )

    morning_schedule: list[dict] = []
    morning_cursor = 6 * 60
    unscheduled: list[str] = []
    for task in morning_pending:
        task_end = morning_cursor + task["minutes"]
        if task_end <= prep_start:
            morning_schedule.append(
                {
                    "start": f"{morning_cursor // 60:02d}:{morning_cursor % 60:02d}",
                    "end": f"{task_end // 60:02d}:{task_end % 60:02d}",
                    "task": f'{task["name"]} (moved from evening to morning)',
                    "type": "daily",
                }
            )
            morning_cursor = task_end
        else:
            unscheduled.append(task["name"])

    wake_time = 6 * 60 if morning_schedule else prep_start
    morning_schedule.append(
        {
            "start": f"{prep_start // 60:02d}:{prep_start % 60:02d}",
            "end": f"{work_departure // 60:02d}:{work_departure % 60:02d}",
            "task": "Get ready for work",
            "type": "mandatory",
        }
    )
    sleep_minutes = wake_time + 1440 - bedtime
    if sleep_minutes < 360:
        warnings.append(
            f"The current plan allows only {sleep_minutes // 60} hours and {sleep_minutes % 60} minutes of sleep. Remove or shorten some activities."
        )
    if skipped_enjoyment:
        warnings.append(
            "Not enough time; cancelled: " + ", ".join(skipped_enjoyment) + "."
        )
    if unscheduled:
        warnings.append(
            "These tasks fit neither the evening nor the 06:00–work-preparation window: "
            + ", ".join(unscheduled)
            + "."
        )

    return {
        "status": "ok" if not violations else "constraint_violation",
        "arrival_after_overtime": f"{(arrival // 60) % 24:02d}:{arrival % 60:02d}",
        "evening_schedule": evening_schedule,
        "bedtime": f"{(bedtime // 60) % 24:02d}:{bedtime % 60:02d}",
        "wake_time": f"{wake_time // 60:02d}:{wake_time % 60:02d}",
        "sleep_duration": f"{sleep_minutes // 60}h {sleep_minutes % 60}min",
        "morning_schedule": morning_schedule,
        "warnings": warnings,
        "violations": violations,
        "rules_applied": [
            "Dinner and a shower are mandatory every day",
            "Home cooking requires washing the dishes",
            "Outside dining must be within 1 km of home",
            "Bedtime cannot be later than 01:30",
            "Daily tasks that do not fit in the evening are moved to 06:00 when possible",
            "Reserve 20 minutes to get ready before leaving for work at 08:00",
        ],
    }

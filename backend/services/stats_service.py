"""İstatistik, PR, hacim ve split hesaplama servisleri."""
from typing import Optional
from routers.exercises import _display_muscle_groups
from services.workout_service import (
    _canonical_exercise_from_entry,
    _legacy_exercise_key,
)

HAFTA_GUNLERI = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

EXERCISE_TIPS = {
    "Push A": [
        ("Bench Press", "3x6-8", "Temel bileşik — ağırlık artırma odağı"),
        ("Overhead Press", "3x8-10", "Omuz bileşiği"),
        ("Incline Dumbbell Press", "3x8-12", "Üst göğüs"),
        ("Lateral Raises", "3x12-15", "Orta omuz izolasyonu"),
        ("Tricep Push Down", "3x10-12", "Triceps izolasyonu"),
    ],
    "Push B": [
        ("Overhead Press", "3x6-8", "Açılış hareketi — Bench yerine önce omuz"),
        ("Incline Bench Press", "3x8-10", "Üst göğüs bileşiği"),
        ("Dumbbell Flyes", "3x10-15", "Göğüs izolasyonu"),
        ("Cable Lateral Raises", "3x12-15", "Orta omuz"),
        ("Dips (Ağırlıksız)", "2xTükenişe kadar", "Ağırlıksız finale"),
    ],
    "Pull A": [
        ("Pull Ups (Ağırlıksız Barfiks)", "3xTükenişe kadar", "Dikey çekiş bileşiği"),
        ("Barbell Row", "3x6-8", "Kalınlık odaklı"),
        ("Lat Pull Down", "3x8-12", "Kanat genişliği"),
        ("Face Pulls", "3x12-15", "Arka omuz + rotator cuff"),
        ("Hammer Curl", "3x10-12", "Biceps + brachialis"),
    ],
    "Pull B": [
        ("Chin Ups (Ağırlıksız)", "3xTükenişe kadar", "Biceps ağırlıklı çekiş"),
        ("T-Bar Row", "3x8-10", "Orta sırt"),
        ("Seated Row", "3x10-12", "Kontrol odaklı çekme"),
        ("Dumbbell Rear Delt Fly", "3x12-15", "Arka omuz izolasyonu"),
        ("Preacher Curl (Z Bar)", "3x8-12", "Biceps izolasyonu"),
    ],
    "Legs A": [
        ("Squat", "3x6-8", "Ana bacak bileşiği"),
        ("Romanian Deadlift", "3x8-10", "Hamstring + kalça"),
        ("Leg Press", "3x10-12", "Hacim"),
        ("Leg Curl", "3x10-12", "Hamstring izolasyonu"),
        ("Calf Raises", "4x12-15", "Baldır"),
    ],
    "Legs B": [
        ("Front Squat", "3x6-8", "Quad odaklı açılış"),
        ("Hip Thrust", "3x8-10", "Gluteus odaklı bileşik"),
        ("Bulgarian Split Squat", "3x10-12", "Tek bacak"),
        ("Seated Leg Curl", "3x10-12", "Hamstring izolasyonu"),
        ("Standing Calf Raise (Barbell)", "4x12-15", "Baldır"),
    ],
    "Upper": [
        ("Bench Press", "3x6-8", "Göğüs bileşiği"),
        ("Barbell Row", "3x6-8", "Sırt bileşiği"),
        ("Overhead Press", "3x8-10", "Omuz"),
        ("Lat Pull Down", "3x8-12", "Genişlik"),
        ("Bicep Curl", "3x10-12", "Kol"),
    ],
    "Lower": [
        ("Squat", "3x6-8", "Bacak bileşiği"),
        ("Romanian Deadlift", "3x8-10", "Arka bacak"),
        ("Leg Press", "3x10-12", "Hacim"),
        ("Calf Raises", "3x12-15", "Baldır"),
        ("Plank", "3x45-60sn", "Core"),
    ],
    "Full Body A": [
        ("Squat", "3x6-8", "Alt vücut bileşiği"),
        ("Bench Press", "3x6-8", "İtiş"),
        ("Barbell Row", "3x6-8", "Çekiş"),
        ("Overhead Press", "3x8-10", "Omuz"),
        ("Bicep Curl", "2x10-12", "Kol"),
    ],
    "Full Body B": [
        ("Deadlift", "3x5", "Tüm vücut kuvvet"),
        ("Incline Dumbbell Press", "3x8-10", "Üst göğüs"),
        ("Pull Ups (Ağırlıksız Barfiks)", "3xTükenişe kadar", "Sırt"),
        ("Lateral Raises", "3x12-15", "Omuz"),
        ("Tricep Push Down", "2x10-12", "Triceps"),
    ],
    "Full Body C": [
        ("Leg Press", "3x10-12", "Alt vücut"),
        ("Dumbbell Bench Press", "3x8-10", "Göğüs"),
        ("Seated Row", "3x10-12", "Sırt"),
        ("Romanian Deadlift", "3x8-10", "Arka bacak"),
        ("Hammer Curl", "2x10-12", "Biceps"),
    ],
}


def calculate_stats(user: dict) -> dict:
    h = user.get("height", 0) or 0
    w = user.get("weight", 0) or 0
    age = user.get("age", 0) or 0
    gender = user.get("gender", "male")
    level = user.get("fitness_level", "Beginner")

    bmi = round(w / ((h / 100) ** 2), 1) if h > 0 and w > 0 else 0

    bmr = (
        (88.362 + (13.397 * w) + (4.799 * h) - (5.677 * age))
        if gender == "male"
        else (447.593 + (9.247 * w) + (3.098 * h) - (4.330 * age))
    )

    multipliers = {"Beginner": 1.2, "Intermediate": 1.375, "Advanced": 1.55}
    tdee = round(bmr * multipliers.get(level, 1.2))

    goal = user.get("goal", "bulk")
    target_calories = tdee
    if goal == "bulk":
        target_calories += 300
    elif goal == "cut":
        target_calories -= 500

    protein = round(w * (2.2 if goal == "cut" else 2.0))
    fat = round(w * 0.9)
    carbs = round(max(0, (target_calories - protein * 4 - fat * 9)) / 4)

    if bmi < 18.5:
        bmi_category = "Zayıf"
    elif bmi < 25:
        bmi_category = "Normal"
    elif bmi < 30:
        bmi_category = "Fazla Kilolu"
    else:
        bmi_category = "Obez"

    macro = {"protein": protein, "carbs": carbs, "fat": fat}
    return {
        "bmi": bmi,
        "bmi_category": bmi_category,
        "bmr": round(bmr),
        "tdee": tdee,
        "target_calories": target_calories,
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
        "macro": macro,
    }


def generate_split(days_per_week: int, goal: str = "bulk") -> dict:
    week_templates = {
        1: [{"type": "Full Body A"}],
        2: [{"type": "Upper Body"}, {"type": "Lower Body"}],
        3: [{"type": "Full Body A"}, {"type": "Full Body B"}, {"type": "Full Body C"}],
        4: [{"type": "Upper"}, {"type": "Lower"}, {"type": "Upper"}, {"type": "Lower"}],
        5: [
            {"type": "Push A"},
            {"type": "Pull A"},
            {"type": "Legs A"},
            {"type": "Upper"},
            {"type": "Lower"},
        ],
        6: [
            {"type": "Push A"},
            {"type": "Pull A"},
            {"type": "Legs A"},
            {"type": "Push B"},
            {"type": "Pull B"},
            {"type": "Legs B"},
        ],
        7: [
            {"type": "Push A"},
            {"type": "Pull A"},
            {"type": "Legs A"},
            {"type": "Rest"},
            {"type": "Upper"},
            {"type": "Lower"},
            {"type": "Rest"},
        ],
    }
    template = week_templates.get(days_per_week, week_templates[4])
    days = []
    for i, slot in enumerate(template):
        day_type = slot["type"]
        exercises = EXERCISE_TIPS.get(day_type, [])
        days.append({
            "day": HAFTA_GUNLERI[i],
            "type": day_type,
            "rest": day_type == "Rest",
            "exercises": [{"name": n, "sets": s, "note": nt} for n, s, nt in exercises],
        })
    split_name_map = {
        1: "Full Body",
        2: "Upper/Lower",
        3: "Full Body x3",
        4: "Upper/Lower x2",
        5: "PPL + Üst/Alt",
        6: "PPL x2",
        7: "PPL + Dinlenme",
    }
    rest_count = sum(1 for d in days if d["rest"])
    return {
        "name": split_name_map.get(days_per_week, "Upper/Lower x2"),
        "days": days,
        "rest_count": rest_count,
    }


def get_personal_records(workouts):
    records = {}
    for workout in workouts:
        for entry in workout.get("exercises", []):
            meta = _canonical_exercise_from_entry(entry)
            record_id = (
                meta["id"]
                if meta
                else _legacy_exercise_key(
                    entry.get("canonical_exercise_id") or entry.get("exercise_id"),
                    entry.get("legacy_exercise_name")
                    or entry.get("exercise_name")
                    or entry.get("name"),
                )
            )
            display_name = (
                meta["name"]
                if meta
                else str(
                    entry.get("legacy_exercise_name")
                    or entry.get("exercise_name")
                    or entry.get("name")
                    or "Bilinmeyen hareket"
                )
            )
            if meta:
                muscle = _display_muscle_groups(meta, meta.get("analysis", {}))[0]
            else:
                m = entry.get("muscle_group", "Diğer")
                trans = {"Back": "Sırt", "Chest": "Göğüs", "Shoulders": "Omuz", "Legs": "Bacak"}
                muscle = trans.get(m, m)

            load_mode = (
                meta.get("analysis", {}).get("load_mode", "external_load")
                if meta
                else "external_load"
            )
            metric_type = "reps" if load_mode == "bodyweight" else "weight_kg"
            sets_list = entry.get("sets_data", [])
            if not sets_list:
                continue
            try:
                best_value = max(
                    int(item.get("reps", 0))
                    if metric_type == "reps"
                    else float(item.get("weight_kg", 0))
                    for item in sets_list
                )
            except (TypeError, ValueError):
                continue
            if best_value <= 0:
                continue
            if record_id not in records or best_value > records[record_id]["record_value"]:
                records[record_id] = {
                    "exercise_id": record_id,
                    "exercise": display_name,
                    "muscle": muscle,
                    "primary_muscles": (
                        meta.get("analysis", {}).get("primary_muscles", [])
                        if meta
                        else (
                            ["upper_back"]
                            if "upper-back" in str(record_id).lower()
                            or "upper back" in display_name.lower()
                            else []
                        )
                    ),
                    "category": meta.get("category", "") if meta else "",
                    "record_value": best_value,
                    "metric_type": metric_type,
                    "max_weight": best_value if metric_type == "weight_kg" else 0,
                    "max_reps": (
                        best_value
                        if metric_type == "reps"
                        else max(int(item.get("reps", 0)) for item in sets_list)
                    ),
                    "date": workout.get("date", ""),
                }
    return list(records.values())


def get_top_progress(workouts, limit: Optional[int] = None) -> list:
    if not workouts:
        return []

    exercise_series = {}
    for workout in sorted(workouts, key=lambda x: x.get("date", "")):
        d = workout.get("date", "")
        for entry in workout.get("exercises", []):
            meta = _canonical_exercise_from_entry(entry)
            record_id = (
                meta["id"]
                if meta
                else _legacy_exercise_key(
                    entry.get("canonical_exercise_id") or entry.get("exercise_id"),
                    entry.get("legacy_exercise_name")
                    or entry.get("exercise_name")
                    or entry.get("name"),
                )
            )
            display_name = (
                meta["name"]
                if meta
                else str(
                    entry.get("legacy_exercise_name")
                    or entry.get("exercise_name")
                    or entry.get("name")
                    or "Bilinmeyen hareket"
                )
            )
            if meta:
                muscle = _display_muscle_groups(meta, meta.get("analysis", {}))[0]
            else:
                m = entry.get("muscle_group", "Diğer")
                trans = {"Back": "Sırt", "Chest": "Göğüs", "Shoulders": "Omuz", "Legs": "Bacak"}
                muscle = trans.get(m, m)

            is_bw = (meta and meta.get("is_bodyweight") is True) or bool(
                entry.get("is_bodyweight")
            )
            load_mode = (
                meta.get("analysis", {}).get("load_mode", "external_load")
                if meta
                else "external_load"
            )
            metric_type = (
                "reps"
                if (is_bw and load_mode != "bodyweight_plus_external")
                else ("reps" if load_mode == "bodyweight" else "weight_kg")
            )

            sets_list = entry.get("sets_data", [])
            if not sets_list:
                continue

            try:
                best_val = max(
                    int(item.get("reps", 0))
                    if metric_type == "reps"
                    else float(item.get("weight_kg", 0))
                    for item in sets_list
                )
            except (TypeError, ValueError):
                continue

            if best_val <= 0:
                continue

            if record_id not in exercise_series:
                exercise_series[record_id] = {
                    "exercise_id": record_id,
                    "exercise": display_name,
                    "muscle": muscle,
                    "metric_type": metric_type,
                    "history": [],
                }
            exercise_series[record_id]["history"].append({"date": d, "value": best_val})

    COMPOUND_KEYWORDS = [
        "bench",
        "squat",
        "deadlift",
        "overhead press",
        "barbell row",
        "bulgarian",
        "pull ups",
        "chin ups",
    ]

    top_list = []
    for record_id, data in exercise_series.items():
        hist = data["history"]
        if len(hist) < 2:
            continue

        first_entry = hist[0]
        first_val = first_entry["value"]

        running_max = first_val
        last_increase_date = first_entry["date"]
        has_increase = False

        for h in hist[1:]:
            if h["value"] > running_max:
                running_max = h["value"]
                last_increase_date = h["date"]
                has_increase = True

        diff = round(running_max - first_val, 1)

        if has_increase and diff > 0 and first_val > 0:
            pct = round((diff / first_val) * 100, 1)
            name_lower = data["exercise"].lower()
            is_compound = any(k in name_lower for k in COMPOUND_KEYWORDS)
            top_list.append({
                "exercise_id": record_id,
                "exercise": data["exercise"],
                "muscle": data["muscle"],
                "metric_type": data["metric_type"],
                "first_value": first_val,
                "first_date": first_entry["date"],
                "current_pr_value": running_max,
                "current_pr_date": last_increase_date,
                "last_increase_date": last_increase_date,
                "diff": diff,
                "percentage": pct,
                "sessions_count": len(hist),
                "is_compound": is_compound,
            })

    top_list.sort(
        key=lambda x: (
            x.get("last_increase_date", "") or "",
            x["diff"],
            x["percentage"],
        ),
        reverse=True,
    )
    if limit is not None:
        return top_list[:limit]
    return top_list

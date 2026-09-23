"""Egzersiz kataloğu ve kas filtreleri API uç noktası."""
from fastapi import APIRouter
from exercise_catalog import EXERCISE_POOL

router = APIRouter(prefix="/api/exercises", tags=["exercises"])

EXERCISE_MUSCLE_TR = {
    "Chest": "Göğüs",
    "Back": "Sırt",
    "Shoulders": "Omuz",
    "Legs": "Alt Vücut",
    "Biceps": "Biceps",
    "Triceps": "Triceps",
    "Traps": "Sırt",
    "Core": "Core",
    "Rotator Cuff": "Rotatorlar",
    "Hip Rotators": "Adductors",
    "Adductors": "Adductors",
}

LEG_PRIMARY_MUSCLE_TR = {
    "quads": "Quadriceps",
    "hamstrings": "Hamstring",
    "glutes": "Gluteus",
    "gluteus_maximus": "Gluteus",
    "gluteus_medius": "Gluteus",
    "calves": "Calf",
    "adductors": "Adductors",
    "hip_external_rotators": "Adductors",
    "hip_internal_rotators": "Adductors",
}

WORKOUT_UI_MUSCLE_GROUPS = (
    "Göğüs",
    "Sırt",
    "Omuz",
    "Biceps",
    "Triceps",
    "Quadriceps",
    "Hamstring",
    "Gluteus",
    "Calf",
    "Adductors",
    "Rotatorlar",
    "Core",
)


def _display_muscle_groups(exercise: dict, analysis: dict) -> list[str]:
    group = exercise.get("muscle_group", "")
    primary_muscles = set(analysis.get("primary_muscles", []))
    if group == "Rotator Cuff" or any(
        m in primary_muscles
        for m in (
            "infraspinatus",
            "subscapularis",
            "supraspinatus",
            "teres_minor",
            "rotator_cuff",
        )
    ):
        return ["Rotatorlar"]
    if group in {"Hip Rotators", "Adductors"} or any(
        m in primary_muscles
        for m in ("adductors", "hip_external_rotators", "hip_internal_rotators")
    ):
        return ["Adductors"]
    if "rear_delts" in primary_muscles:
        if analysis.get("family") == "row":
            return ["Sırt"]
        return ["Omuz", "Sırt"]
    if group == "Legs":
        detailed = [
            LEG_PRIMARY_MUSCLE_TR[item]
            for item in LEG_PRIMARY_MUSCLE_TR
            if item in primary_muscles
        ]
        return detailed or ["Alt Vücut"]
    return [EXERCISE_MUSCLE_TR.get(group, group)]


def _enrich_exercise_pool(pool):
    out = []
    for exercise in pool:
        item = dict(exercise)
        analysis = dict(exercise.get("analysis", {}))
        display_groups = _display_muscle_groups(exercise, analysis)
        item["muscle"] = display_groups[0]
        item["display_muscle_groups"] = display_groups
        item["bw"] = bool(exercise.get("is_bodyweight", False))
        item["weighted"] = analysis.get("load_mode") == "bodyweight_plus_external"
        item["canonical_exercise_id"] = exercise["id"]
        item["analysis"] = analysis
        out.append(item)
    return out


@router.get("")
@router.get("/")
def get_exercises():
    """Egzersiz havuzu ve kayıt ekranındaki ayrıntılı kas filtreleri."""
    return {
        "exercises": _enrich_exercise_pool(EXERCISE_POOL),
        "muscle_groups": list(WORKOUT_UI_MUSCLE_GROUPS),
    }

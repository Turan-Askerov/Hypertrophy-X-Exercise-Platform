"""Antrenman (Workout) CRUD, normalizasyon ve takvim senkronizasyon servisleri."""
import json
import re
import unicodedata
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from core.config import DATABASE_BACKEND
from core.database import get_db
from exercise_aliases import EXERCISE_ALIASES
from exercise_catalog import EXERCISE_META_VERSION, EXERCISE_POOL
from program_schedule_sync import (
    clean_non_active_week,
    current_week_actuals,
    is_rest_day,
    reconcile_week,
)
from services.user_service import get_user_by_id


def _normalize_exercise_text(value: object) -> str:
    text = str(value or "").strip().lower()
    text = (
        text.replace("ı", "i")
        .replace("İ", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s*\(\s*(?:vucut agirligi|agirlikli|bodyweight|weighted)\s*\)", "", text)
    text = text.replace("dumbell", "dumbbell").replace("dumbel", "dumbbell")
    text = text.replace("barfiks", "pull up").replace("pull-up", "pull up")
    text = text.replace("pulldown", "pull down").replace("t bar", "tbar")
    text = text.replace("cross over", "crossover").replace(
        "bulgarian split squad", "bulgarian split squat"
    )
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


EXERCISE_BY_ID = {exercise["id"]: exercise for exercise in EXERCISE_POOL}
EXERCISE_ID_BY_NORMALIZED_NAME = {}
for _pool_exercise in EXERCISE_POOL:
    _n_name = _normalize_exercise_text(_pool_exercise["name"])
    if _n_name not in EXERCISE_ID_BY_NORMALIZED_NAME or not _pool_exercise.get("is_bodyweight"):
        EXERCISE_ID_BY_NORMALIZED_NAME[_n_name] = _pool_exercise["id"]
    EXERCISE_ID_BY_NORMALIZED_NAME[_normalize_exercise_text(_pool_exercise["id"])] = (
        _pool_exercise["id"]
    )


def resolve_exercise_metadata(exercise_id: object = None, exercise_name: object = None):
    """Kayıttan kanonik havuz hareketini çözer; bilinmeyen ad için None döndürür."""
    raw_id = str(exercise_id or "").strip()
    if raw_id in EXERCISE_BY_ID:
        return EXERCISE_BY_ID[raw_id]

    clean_id = re.sub(
        r"\s*\((?:vücut ağırlığı|vucut agirligi|ağırlıklı|agirlikli|bodyweight|weighted)\)",
        "",
        raw_id,
        flags=re.IGNORECASE,
    ).strip()
    if clean_id in EXERCISE_BY_ID:
        return EXERCISE_BY_ID[clean_id]

    for reference in (raw_id, clean_id, exercise_name):
        normalized = _normalize_exercise_text(reference)
        if not normalized:
            continue
        canonical_id = EXERCISE_ID_BY_NORMALIZED_NAME.get(normalized)
        if not canonical_id:
            canonical_id = EXERCISE_ALIASES.get(normalized)
        if canonical_id:
            return EXERCISE_BY_ID.get(canonical_id)
    return None


def _legacy_exercise_key(exercise_id: object = None, exercise_name: object = None) -> str:
    raw_id = str(exercise_id or "").strip()
    if raw_id.lower().startswith("legacy:"):
        suffix = raw_id.split(":", 1)[1].strip()
        return f"legacy:{suffix}" if suffix else ""
    reference = exercise_name or raw_id
    normalized = _normalize_exercise_text(reference)
    return f"legacy:{normalized}" if normalized else ""


def _canonical_exercise_from_entry(entry: dict):
    return resolve_exercise_metadata(
        entry.get("canonical_exercise_id") or entry.get("exercise_id"),
        entry.get("exercise_name") or entry.get("name"),
    )


def _normalize_workout_exercises(exercises):
    normalized = []
    for raw in exercises or []:
        entry = dict(raw)
        meta = _canonical_exercise_from_entry(entry)
        if meta:
            entry["exercise_id"] = meta["id"]
            entry["canonical_exercise_id"] = meta["id"]
            entry["exercise_name"] = meta["name"]
            entry["muscle_group"] = meta["muscle_group"]
            entry["is_bodyweight"] = bool(meta["is_bodyweight"])
            entry["exercise_meta_version"] = EXERCISE_META_VERSION
        else:
            entry.setdefault(
                "legacy_exercise_name",
                entry.get("exercise_name") or entry.get("name") or entry.get("exercise_id", ""),
            )
            entry["canonical_exercise_id"] = _legacy_exercise_key(
                entry.get("canonical_exercise_id") or entry.get("exercise_id"),
                entry.get("exercise_name") or entry.get("name"),
            )
            entry.setdefault("exercise_meta_version", 0)
        normalized.append(entry)
    return normalized


def _iter_workout_exercises(workout: dict):
    raw = workout.get("exercises", [])
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    return _normalize_workout_exercises(raw)


def _parse_dashboard_preferences(raw_preferences) -> dict:
    if isinstance(raw_preferences, dict):
        preferences = dict(raw_preferences)
    else:
        try:
            preferences = json.loads(raw_preferences or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            preferences = {}

    if not isinstance(preferences, dict):
        preferences = {}
    if not isinstance(preferences.get("pr_targets"), dict):
        preferences["pr_targets"] = {}
    preferences.setdefault("schema_version", 1)
    return preferences


def _schedule_week_index(
    total_weeks: int, start_date: date | datetime | str | None = None
) -> int:
    if total_weeks <= 1 or not start_date:
        return 0
    try:
        if isinstance(start_date, str):
            clean_str = start_date.replace("Z", "+00:00")
            parsed_date = datetime.fromisoformat(clean_str).date()
        elif isinstance(start_date, datetime):
            parsed_date = start_date.date()
        elif isinstance(start_date, date):
            parsed_date = start_date
        else:
            return 0
    except Exception:
        return 0

    today = date.today()
    start_monday = parsed_date - timedelta(days=parsed_date.weekday())
    today_monday = today - timedelta(days=today.weekday())
    elapsed = (today_monday - start_monday).days // 7
    if elapsed < 0:
        return 0
    return elapsed % max(1, total_weeks)


def _read_custom_program(raw_program: object) -> list:
    if isinstance(raw_program, list):
        return raw_program
    try:
        parsed = json.loads(raw_program or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _sync_programs_with_real_workouts(user_id: int) -> dict:
    user = get_user_by_id(user_id)
    if not user:
        return {"changed": False}
    user_workouts = get_workouts_by_user(user_id)
    today_index = date.today().weekday()

    custom_program = _read_custom_program(user.get("custom_split", "[]"))
    custom_changed = False
    preferences = _parse_dashboard_preferences(user.get("dashboard_preferences", "{}"))
    custom_date_raw = (
        preferences.get("custom_program_updated_at")
        or user.get("updated_at")
        or user.get("created_at")
    )
    custom_start_date = None
    custom_start_weekday = 0
    if custom_date_raw:
        try:
            c_date_obj = datetime.fromisoformat(str(custom_date_raw).replace("Z", "+00:00"))
            custom_start_date = c_date_obj.date()
            u_week_start = date.today() - timedelta(days=today_index)
            if custom_start_date >= u_week_start:
                custom_start_weekday = c_date_obj.weekday()
        except Exception:
            pass

    custom_actuals = current_week_actuals(user_workouts, min_date=custom_start_date)

    if custom_program:
        custom_week_index = _schedule_week_index(len(custom_program), custom_start_date)
        for c_idx, c_days in enumerate(custom_program):
            if isinstance(c_days, list) and len(c_days) == 7:
                if c_idx == custom_week_index:
                    reconciled, c_changed = reconcile_week(
                        c_days,
                        custom_actuals,
                        today_index,
                        start_weekday=custom_start_weekday,
                    )
                else:
                    reconciled, c_changed = clean_non_active_week(c_days, c_idx)
                if c_changed:
                    custom_program[c_idx] = reconciled
                    custom_changed = True

    if not custom_changed:
        return {"changed": False}

    conn = get_db()
    try:
        c_json = json.dumps(custom_program, ensure_ascii=False)
        conn.execute("UPDATE users SET custom_split = ? WHERE id = ?", (c_json, user_id))
        conn.execute(
            "UPDATE athlete_profiles SET custom_split = ? WHERE user_id = ?",
            (c_json, user_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "changed": True,
        "custom_split": json.dumps(custom_program, ensure_ascii=False),
        "dashboard_preferences": preferences,
    }


def get_workouts_by_user(user_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM workouts WHERE user_id = ? ORDER BY date DESC", (user_id,)
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        workout = dict(row)
        workout["exercises"] = _iter_workout_exercises(workout)
        result.append(workout)
    return result


def create_workout(user_id: int, data: dict) -> dict:
    exercises = _normalize_workout_exercises(data.get("exercises", []))
    total_volume = 0.0
    for ex in exercises:
        for s in ex.get("sets_data", []):
            total_volume += float(s.get("weight_kg", 0)) * int(s.get("reps", 0))

    values = (
        user_id,
        data.get("date", str(date.today())),
        data.get("session_type", "Workout"),
        data.get("notes", ""),
        data.get("gym_id"),
        str(data.get("gym_name") or "")[:80],
        total_volume,
        json.dumps(exercises, ensure_ascii=False),
    )
    conn = get_db()
    if DATABASE_BACKEND == "postgresql":
        row = conn.execute(
            """INSERT INTO workouts (user_id, date, session_type, notes, gym_id, gym_name, total_volume, exercises)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
            values,
        ).fetchone()
        new_id = row["id"]
    else:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO workouts (user_id, date, session_type, notes, gym_id, gym_name, total_volume, exercises)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )
        new_id = cur.lastrowid
    conn.commit()
    conn.close()
    _sync_programs_with_real_workouts(user_id)
    return {"success": True, "message": "Antrenman kaydedildi", "id": new_id}


def delete_workout(workout_id: int, user_id: int):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM workouts WHERE id = ? AND user_id = ?", (workout_id, user_id)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Antrenman bulunamadı")
    conn.execute(
        "DELETE FROM workouts WHERE id = ? AND user_id = ?", (workout_id, user_id)
    )
    conn.commit()
    conn.close()
    return {"success": True, "message": "Antrenman silindi"}


def update_workout(workout_id: int, data: dict, user_id: int) -> dict:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM workouts WHERE id = ? AND user_id = ?", (workout_id, user_id)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Antrenman bulunamadı")

    fields, values = [], []
    if "date" in data:
        fields.append("date=?")
        values.append(data["date"])
    if "session_type" in data:
        fields.append("session_type=?")
        values.append(data["session_type"])
    if "notes" in data:
        fields.append("notes=?")
        values.append(data["notes"])
    if "gym_id" in data:
        fields.append("gym_id=?")
        values.append(data["gym_id"])
    if "gym_name" in data:
        fields.append("gym_name=?")
        values.append(str(data["gym_name"] or "")[:80])
    if "exercises" in data and data["exercises"] is not None:
        exercises = _normalize_workout_exercises(data["exercises"])
        total_vol = 0.0
        for ex in exercises:
            for s in ex.get("sets_data", []):
                total_vol += float(s.get("weight_kg", 0)) * int(s.get("reps", 0))
        fields.append("exercises=?")
        values.append(json.dumps(exercises, ensure_ascii=False))
        fields.append("total_volume=?")
        values.append(total_vol)

    if fields:
        values.extend([workout_id, user_id])
        conn.execute(
            f"UPDATE workouts SET {', '.join(fields)} WHERE id = ? AND user_id = ?",
            values,
        )
        conn.commit()
    conn.close()
    _sync_programs_with_real_workouts(user_id)
    return {"success": True, "message": "Antrenman güncellendi"}

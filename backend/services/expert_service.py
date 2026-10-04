"""Uzman sistemi veri tabanı, profil, DOMS, ekipman, sakatlık ve analiz servis katmanı."""
from collections import defaultdict
from datetime import date, datetime, timedelta
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from core.database import get_db
from exercise_catalog import EXERCISE_POOL
from expert_system import (
    AVAILABLE_EQUIPMENT_OPTIONS,
    DETAILED_MUSCLE_OPTIONS,
    GYM_EQUIPMENT_CATALOG,
    PRIMARY_GOALS,
    UI_MUSCLE_GROUPS,
    build_expert_result,
    build_recommendation_program,
    eligibility as expert_eligibility,
    format_tr_date,
    generate_dynamic_program,
    is_expert_catalog_excluded,
    normalize_detailed_muscle,
    normalize_gym_equipment,
    normalize_muscle_group,
    rpe_summary_from_rir,
)
from models.schemas import ExpertInjuryDataRequest
from routers.exercises import _display_muscle_groups
from services.user_service import get_user_by_id
from services.workout_service import (
    _canonical_exercise_from_entry,
    _iter_workout_exercises,
    _parse_dashboard_preferences,
    get_workouts_by_user,
)

logger = logging.getLogger("hypertrophy-x")


def expert_date(value: Optional[str] = None) -> str:
    """Kullanıcıdan gelen tarihi güvenli ISO-8601 biçimine çevirir."""
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Tarih YYYY-MM-DD biçiminde olmalıdır.") from exc


def json_dict(raw_value: Any) -> dict:
    """JSON nesnesi alanlarını bozuk eski değerlerde güvenli biçimde çözer."""
    if isinstance(raw_value, dict):
        return raw_value
    try:
        value = json.loads(raw_value or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def json_list(raw_value: Any) -> list:
    """Bozuk veya eski JSON alanlarında API yanıtını güvenli biçimde korur."""
    if isinstance(raw_value, list):
        return raw_value
    try:
        value = json.loads(raw_value or "[]")
        return value if isinstance(value, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def normalize_gyms_with_default(gyms: object) -> list[dict]:
    """Eski salon kayıtlarını korur ve API'de yalnız bir varsayılan döndürür."""
    normalized = [dict(item) for item in (gyms or []) if isinstance(item, dict) and item.get("id")]
    selected_id = next((str(item["id"]) for item in normalized if bool(item.get("is_default"))), None)
    if not selected_id and normalized:
        selected_id = str(normalized[0]["id"])
    for item in normalized:
        item["is_default"] = str(item.get("id")) == selected_id
    return normalized


def exercise_preference_selection(dashboard_preferences: object) -> dict:
    """Tercihleri mevcut dashboard JSON'unda saklar; eski kullanıcıları korur."""
    preferences = _parse_dashboard_preferences(dashboard_preferences)
    raw = preferences.get("exercise_preferences") if isinstance(preferences.get("exercise_preferences"), dict) else {}
    known_ids = {
        str(item.get("id"))
        for item in EXERCISE_POOL
        if isinstance(item, dict) and item.get("id") and not is_expert_catalog_excluded(item)
    }
    preferred = []
    avoided = []
    for value in raw.get("preferred_exercise_ids") or []:
        exercise_id = str(value).strip()
        if exercise_id in known_ids and exercise_id not in preferred:
            preferred.append(exercise_id)
    for value in raw.get("avoid_exercise_ids") or []:
        exercise_id = str(value).strip()
        if exercise_id in known_ids and exercise_id not in avoided:
            avoided.append(exercise_id)
    preferred = [value for value in preferred if value not in set(avoided)]
    return {"preferred_exercise_ids": preferred, "avoid_exercise_ids": avoided}


def expert_exercise_catalog() -> list[dict]:
    """Yalnız uzman motorunun kullandığı kanonik hareketleri sade biçimde döndürür."""
    items = []
    for exercise in EXERCISE_POOL:
        if not isinstance(exercise, dict) or not exercise.get("id") or not exercise.get("name") or is_expert_catalog_excluded(exercise):
            continue
        analysis = exercise.get("analysis") or {}
        primary = [str(value) for value in analysis.get("primary_muscles") or []]
        items.append({
            "id": str(exercise["id"]),
            "name": str(exercise["name"]),
            "group": str(exercise.get("muscle_group") or "Diğer"),
            "display_groups": _display_muscle_groups(exercise, analysis),
            "primary_muscles": primary,
            "category": str(exercise.get("category") or ""),
            "bw": bool(exercise.get("is_bodyweight", False)),
            "weighted": analysis.get("load_mode") == "bodyweight_plus_external"
        })
    return sorted(items, key=lambda item: (str(item["display_groups"][0] if item["display_groups"] else item["group"]), item["name"]))


def clean_gym_equipment(values: List[str]) -> list[str]:
    equipment: list[str] = []
    for raw_value in values or []:
        equipment_id = normalize_gym_equipment(raw_value)
        if not equipment_id:
            continue
        if equipment_id not in equipment:
            equipment.append(equipment_id)
    return equipment


def equipment_selection(profile: dict, dashboard_preferences: object) -> dict:
    gyms = normalize_gyms_with_default(profile.get("gyms") or [])
    preferences = _parse_dashboard_preferences(dashboard_preferences)
    raw_preferred = (preferences.get("equipment_preferences") or {}).get("preferred_equipment") or []
    preferred = clean_gym_equipment(raw_preferred) if raw_preferred else []
    default_gym = next((item for item in gyms if item.get("is_default")), None)
    default_equipment = list(default_gym.get("equipment") or []) if default_gym else []
    all_equipment = sorted({str(item) for gym in gyms for item in (gym.get("equipment") or []) if item})
    if preferred:
        source, label, equipment = "preferred", "Tercih edilen ve hâkim olunan ekipmanlar", preferred
    elif default_gym and default_equipment:
        source, label, equipment = "default_gym", f"Varsayılan salon: {default_gym.get('name')}", default_equipment
    elif all_equipment:
        source, label, equipment = "all_gyms", "Kayıtlı salonların ortak ekipmanları", all_equipment
    else:
        source, label, equipment = "none", "Ekipman bilgisi henüz belirtilmedi", []
    return {
        "gyms": gyms,
        "preferred_equipment": preferred,
        "default_gym_id": default_gym.get("id") if default_gym else None,
        "default_gym_name": default_gym.get("name") if default_gym else None,
        "equipment": equipment,
        "equipment_source": source,
        "equipment_source_label": label,
    }


def expert_data_profile(conn, user_id: int, create: bool = True) -> dict | None:
    """Kullanıcı başına tek uzman sistemi kaydını okur; gerekirse boş kayıt açar."""
    select = (
        "SELECT user_id, target_muscles_json, doms_daily_json, gym_equipment_json, injuries_json, rpe_checkins_json, "
        "created_at, updated_at FROM expert_profiles WHERE user_id = ?"
    )
    row = conn.execute(select, (user_id,)).fetchone()
    if not row and create:
        conn.execute(
            "INSERT INTO expert_profiles "
            "(user_id, target_muscles_json, doms_daily_json, gym_equipment_json, injuries_json, rpe_checkins_json) "
            "VALUES (?, '{}', '{}', '[]', '[]', '[]') ON CONFLICT(user_id) DO NOTHING",
            (user_id,),
        )
        conn.commit()
        row = conn.execute(select, (user_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    return {
        "user_id": data["user_id"],
        "target_muscles": json_dict(data.get("target_muscles_json")),
        "doms_daily": json_dict(data.get("doms_daily_json")),
        "gyms": normalize_gyms_with_default(json_list(data.get("gym_equipment_json"))),
        "injuries": json_list(data.get("injuries_json")),
        "rpe_checkins": json_list(data.get("rpe_checkins_json")),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }


def save_expert_data_profile(conn, user_id: int, profile: dict) -> None:
    conn.execute(
        """
        INSERT INTO expert_profiles
            (user_id, target_muscles_json, doms_daily_json, gym_equipment_json, injuries_json, rpe_checkins_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            target_muscles_json = excluded.target_muscles_json,
            doms_daily_json = excluded.doms_daily_json,
            gym_equipment_json = excluded.gym_equipment_json,
            injuries_json = excluded.injuries_json,
            rpe_checkins_json = excluded.rpe_checkins_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            user_id,
            json.dumps(profile.get("target_muscles") or {}, ensure_ascii=False),
            json.dumps(profile.get("doms_daily") or {}, ensure_ascii=False),
            json.dumps(normalize_gyms_with_default(profile.get("gyms") or []), ensure_ascii=False),
            json.dumps(profile.get("injuries") or [], ensure_ascii=False),
            json.dumps(profile.get("rpe_checkins") or [], ensure_ascii=False),
        ),
    )
    conn.commit()


def expert_data_metrics(doms_daily: dict) -> list[dict]:
    """Her kasın en güncel günlük ağrı bildirimini görselleştirme için döndürür."""
    latest_by_muscle: dict[str, dict] = {}
    for report_date, entries in (doms_daily or {}).items():
        if not isinstance(entries, list):
            continue
        for raw_entry in entries:
            entry = raw_entry if isinstance(raw_entry, dict) else {}
            muscle = normalize_detailed_muscle(entry.get("muscle_group"))
            if not muscle:
                continue
            previous = latest_by_muscle.get(muscle)
            if not previous or str(report_date) >= str(previous.get("report_date") or ""):
                latest_by_muscle[muscle] = {
                    "muscle_group": muscle,
                    "pain_level": max(0, min(5, int(entry.get("severity") or 0))),
                    "report_date": str(report_date),
                    "notes": str(entry.get("notes") or ""),
                }
    return sorted(latest_by_muscle.values(), key=lambda item: (-item["pain_level"], item["muscle_group"]))


def expert_preferences_for_user(conn, user_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT primary_goal, priority_muscles, created_at, updated_at FROM expert_preferences WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    try:
        data["priority_muscles"] = json.loads(data.get("priority_muscles") or "[]")
    except (TypeError, json.JSONDecodeError):
        data["priority_muscles"] = []
    return data


def expert_latest_checkin(conn, user_id: int) -> Optional[dict]:
    row = conn.execute(
        """
        SELECT checkin_date, checkin_type, session_rpe, day_fatigue,
               recovery_feeling, completion_percentage, notes, updated_at
        FROM expert_checkins
        WHERE user_id = ?
        ORDER BY checkin_date DESC, updated_at DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def expert_active_doms(conn, user_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, muscle_group, started_on, status, last_severity,
               last_report_date, resolved_on, updated_at
        FROM expert_doms_cases
        WHERE user_id = ? AND status = 'active'
        ORDER BY last_severity DESC, last_report_date DESC, id DESC
        """,
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def expert_equipment_for_user(conn, user_id: int) -> tuple[list[str], bool]:
    row = conn.execute(
        "SELECT available_equipment FROM expert_equipment WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not row:
        return [], False
    return json_list(dict(row).get("available_equipment")), True


def expert_active_constraints(conn, user_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, muscle_group, constraint_type, severity, notes, started_on,
               resolved_on, status, updated_at
        FROM expert_constraints
        WHERE user_id = ? AND status = 'active' AND resolved_on IS NULL
        ORDER BY severity DESC, started_on DESC, id DESC
        """,
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def expert_active_program(conn, user_id: int) -> dict | None:
    """Eski program modülü kaldırılmış şemalarda dashboard geri uyumluluğu sağlar."""
    try:
        row = conn.execute(
            """
            SELECT id, program_json, is_active, created_at, activated_at
            FROM expert_program_versions
            WHERE user_id = ? AND is_active = TRUE
            ORDER BY activated_at DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    except Exception as exc:
        if "expert_program_versions" in str(exc):
            return None
        raise
    if not row:
        return None
    data = dict(row)
    try:
        program = json.loads(data.pop("program_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        program = {}
    return {"version_id": data.get("id"), "created_at": data.get("created_at"), "activated_at": data.get("activated_at"), "program": program}


def parse_iso_date_safe(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def expert_history_context(workouts: list[dict]) -> tuple[dict, dict[str, str]]:
    """Son yedi takvim gününün doğrudan setlerini ve kas seansı tarihlerini çıkarır."""
    cutoff = date.today() - timedelta(days=6)
    volume: dict[str, int] = defaultdict(int)
    latest_dates: dict[str, str] = {}
    for workout in workouts or []:
        workout_date = expert_date(workout.get("date")) if parse_iso_date_safe(workout.get("date")) else None
        if not workout_date:
            continue
        parsed_date = parse_iso_date_safe(workout_date)
        for entry in _iter_workout_exercises(workout):
            meta = _canonical_exercise_from_entry(entry)
            if meta:
                muscles = (meta.get("analysis") or {}).get("primary_muscles") or []
            else:
                broad = normalize_muscle_group(entry.get("muscle_group"))
                muscles = [option["id"] for option in DETAILED_MUSCLE_OPTIONS if option["ui_group"] == broad]
            set_count = len(entry.get("sets_data") or [])
            for raw_muscle in muscles:
                muscle = normalize_detailed_muscle(raw_muscle)
                if not muscle:
                    continue
                if parsed_date >= cutoff:
                    volume[muscle] += set_count
                if muscle not in latest_dates or workout_date > latest_dates[muscle]:
                    latest_dates[muscle] = workout_date
    return {"sets_by_muscle": dict(volume)}, latest_dates


def expert_state(user: dict) -> dict:
    workouts = get_workouts_by_user(user["id"])
    eligibility = expert_eligibility(user, len(workouts))
    conn = get_db()
    try:
        preferences = expert_preferences_for_user(conn, user["id"])
        latest_checkin = expert_latest_checkin(conn, user["id"])
        active_doms = expert_active_doms(conn, user["id"])
        equipment, equipment_configured = expert_equipment_for_user(conn, user["id"])
        constraints = expert_active_constraints(conn, user["id"])
        active_prog = expert_active_program(conn, user["id"])
    finally:
        conn.close()

    result = None
    history, latest_dates = expert_history_context(workouts)
    if eligibility["ready"] and preferences:
        if equipment_configured:
            result = build_expert_result(user, preferences, workouts, latest_checkin, active_doms)
            result["dynamic_program"] = generate_dynamic_program(
                user, preferences, EXERCISE_POOL, equipment, active_doms, constraints,
                history=history, last_workout_dates=latest_dates,
            )
        else:
            result = build_expert_result(user, preferences, workouts, latest_checkin, active_doms)

    return {
        "eligibility": eligibility,
        "preferences": preferences,
        "latest_checkin": latest_checkin,
        "active_doms": active_doms,
        "equipment": equipment,
        "equipment_configured": equipment_configured,
        "constraints": constraints,
        "active_program": active_prog,
        "result": result,
        "catalog": {
            "primary_goals": PRIMARY_GOALS,
            "muscle_groups": list(UI_MUSCLE_GROUPS),
            "detailed_muscles": list(DETAILED_MUSCLE_OPTIONS),
            "equipment_options": list(AVAILABLE_EQUIPMENT_OPTIONS),
            "constraint_types": {
                "pain": "Kas / eklem ağrısı",
                "tendon": "Tendon hassasiyeti",
                "medical_clearance": "Tıbbi değerlendirme bekleniyor",
            },
            "max_priority_muscles": 3,
        },
    }


def expert_require_ready(user: dict) -> None:
    workouts = get_workouts_by_user(user["id"])
    state = expert_eligibility(user, len(workouts))
    if not state["ready"]:
        raise HTTPException(status_code=409, detail=state)


def expert_require_preferences(conn, user_id: int) -> dict:
    preferences = expert_preferences_for_user(conn, user_id)
    if not preferences:
        raise HTTPException(
            status_code=409,
            detail="Önce amaç ve öncelikli kas grupları anketini kaydedin.",
        )
    return preferences


def expert_store_program_version(conn, user_id: int, program: dict) -> int:
    conn.execute(
        "INSERT INTO expert_program_versions (user_id, program_json, is_active) VALUES (?, ?, FALSE)",
        (user_id, json.dumps(program, ensure_ascii=False)),
    )
    row = conn.execute(
        "SELECT id FROM expert_program_versions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if not row:
        raise RuntimeError("Program sürümü kaydedilemedi.")
    return int(row["id"])


def expert_recent_rir_summary(user_id: int) -> dict | None:
    for workout in get_workouts_by_user(user_id):
        rir_values: list[int] = []
        exercise_names: list[str] = []
        for exercise in workout.get("exercises") or []:
            exercise_has_rir = False
            for set_data in exercise.get("sets_data") or []:
                value = set_data.get("rir") if isinstance(set_data, dict) else None
                if isinstance(value, bool):
                    continue
                try:
                    rir = int(value)
                except (TypeError, ValueError):
                    continue
                if 0 <= rir <= 5:
                    rir_values.append(rir)
                    exercise_has_rir = True
            if exercise_has_rir:
                exercise_names.append(str(exercise.get("name") or exercise.get("exercise_name") or exercise.get("id") or "Egzersiz"))
        if rir_values:
            vol = float(workout.get("total_volume") or 0.0)
            if vol <= 0:
                for exercise_item in workout.get("exercises") or []:
                    for s_item in exercise_item.get("sets_data") or []:
                        if isinstance(s_item, dict):
                            try:
                                vol += float(s_item.get("weight_kg") or 0) * int(s_item.get("reps") or 0)
                            except (TypeError, ValueError):
                                pass
            return {
                "workout_date": str(workout.get("date") or ""),
                "session_type": str(workout.get("session_type") or "Antrenman"),
                "set_count": len(rir_values),
                "average_rir": round(sum(rir_values) / len(rir_values), 1),
                "lowest_rir": min(rir_values),
                "near_failure_sets": sum(1 for value in rir_values if value <= 1),
                "exercise_names": sorted(set(exercise_names)),
                "total_volume": round(vol, 1),
            }
    return None


def expert_rule_context(profile: dict, user_id: int, dashboard_preferences: object = "{}") -> dict:
    labels = {item["id"]: item["label"] for item in DETAILED_MUSCLE_OPTIONS}
    metrics = []
    for item in expert_data_metrics(profile.get("doms_daily") or {}):
        copied = dict(item)
        copied["muscle_label"] = labels.get(copied.get("muscle_group"), copied.get("muscle_group"))
        metrics.append(copied)
    equip_sel = equipment_selection(profile, dashboard_preferences)
    targets = profile.get("target_muscles") or {}
    target_ids = targets.get("priority_muscles") or []
    recent_rir = expert_recent_rir_summary(user_id)
    return {
        "targets": targets,
        "target_muscle_labels": [labels.get(item, str(item)) for item in target_ids],
        "doms_metrics": metrics,
        "injuries": profile.get("injuries") or [],
        "equipment": equip_sel["equipment"],
        "preferred_equipment": equip_sel["preferred_equipment"],
        "default_gym_id": equip_sel["default_gym_id"],
        "default_gym_name": equip_sel["default_gym_name"],
        "equipment_source": equip_sel["equipment_source"],
        "equipment_source_label": equip_sel["equipment_source_label"],
        "recent_rir": recent_rir,
        "rpe_summary": rpe_summary_from_rir(recent_rir),
    }


def expert_data_analysis(user: dict) -> dict:
    from expert_system import evaluate_expert_rules
    conn = get_db()
    try:
        profile = expert_data_profile(conn, user["id"])
    finally:
        conn.close()
    analysis = evaluate_expert_rules(expert_rule_context(profile or {}, user["id"], dict(user).get("dashboard_preferences", "{}")))
    analysis["generated_on_display"] = format_tr_date(analysis.get("generated_on"))

    user_workouts = get_workouts_by_user(user["id"])
    total_workouts = len(user_workouts)
    total_sets = 0
    all_rpe_list = []
    total_volume_sum = 0.0
    for w in user_workouts:
        w_vol = float(w.get("total_volume") or 0.0)
        calc_vol = 0.0
        for ex in w.get("exercises") or []:
            for s in ex.get("sets_data") or []:
                if isinstance(s, dict):
                    total_sets += 1
                    try:
                        calc_vol += float(s.get("weight_kg") or 0) * int(s.get("reps") or 0)
                    except (TypeError, ValueError):
                        pass
                    val = s.get("rir")
                    if val is not None and not isinstance(val, bool):
                        try:
                            rir_val = int(val)
                            if 0 <= rir_val <= 5:
                                all_rpe_list.append(10.0 - rir_val)
                        except (TypeError, ValueError):
                            pass
        total_volume_sum += (w_vol if w_vol > 0 else calc_vol)

    recent_workout = None
    if user_workouts:
        latest = user_workouts[0]
        l_vol = float(latest.get("total_volume") or 0.0)
        if l_vol <= 0:
            for ex in latest.get("exercises") or []:
                for s in ex.get("sets_data") or []:
                    if isinstance(s, dict):
                        try:
                            l_vol += float(s.get("weight_kg") or 0) * int(s.get("reps") or 0)
                        except (TypeError, ValueError):
                            pass
        l_sets = sum(len(ex.get("sets_data") or []) for ex in latest.get("exercises") or [])
        recent_workout = {
            "date": str(latest.get("date") or ""),
            "workout_date_display": format_tr_date(latest.get("date")),
            "session_type": str(latest.get("session_type") or "Antrenman"),
            "total_volume": round(l_vol, 1),
            "set_count": l_sets,
        }

    overall_avg_rpe = round(sum(all_rpe_list) / len(all_rpe_list), 1) if all_rpe_list else None

    analysis["recent_workout"] = recent_workout
    analysis["history_summary"] = {
        "total_workouts": total_workouts,
        "total_sets": total_sets,
        "average_rpe": overall_avg_rpe,
        "total_volume_sum": round(total_volume_sum, 1),
    }

    if analysis.get("rpe_summary") and recent_workout:
        if not analysis["rpe_summary"].get("total_volume"):
            analysis["rpe_summary"]["total_volume"] = recent_workout["total_volume"]
    elif not analysis.get("rpe_summary") and recent_workout:
        analysis["rpe_summary"] = {
            "workout_date": recent_workout["date"],
            "workout_date_display": recent_workout["workout_date_display"],
            "session_type": recent_workout["session_type"],
            "set_count": recent_workout["set_count"],
            "average_rpe": None,
            "highest_rpe": None,
            "high_effort_sets": 0,
            "derivation": "Son antrenman kaydı",
            "total_volume": recent_workout["total_volume"],
        }

    return analysis


def recommendation_days_per_week(user: dict) -> int:
    try:
        days = int(dict(user).get("days_per_week") or 3)
    except (TypeError, ValueError):
        days = 3
    return max(1, min(7, days))


def build_expert_recommendation(user: dict) -> dict:
    conn = get_db()
    try:
        profile = expert_data_profile(conn, user["id"])
    finally:
        conn.close()
    profile = profile or {}
    context = expert_rule_context(profile, user["id"], dict(user).get("dashboard_preferences", "{}"))
    days_per_week = recommendation_days_per_week(user)
    targets = context.get("targets") or {}
    planner_profile = dict(user)
    planner_profile["days_per_week"] = days_per_week
    movement_preferences = exercise_preference_selection(dict(user).get("dashboard_preferences", "{}"))
    raw_goal = str(targets.get("primary_goal") or dict(user).get("goal") or "hypertrophy").strip().lower()
    goal_map = {
        "bulk": "hypertrophy",
        "cut": "fat_loss",
        "maintain": "maintenance",
        "maintenance": "maintenance",
        "strength": "strength",
        "hypertrophy": "hypertrophy",
        "fat_loss": "fat_loss",
    }
    normalized_goal = goal_map.get(raw_goal, "hypertrophy")
    preferences = {
        "primary_goal": normalized_goal,
        "priority_muscles": list(targets.get("priority_muscles") or []),
        "exercise_preferences": movement_preferences,
    }
    active_doms = [
        {"muscle_group": item.get("muscle_group"), "severity": item.get("pain_level", 0)}
        for item in (context.get("doms_metrics") or []) if isinstance(item, dict)
    ]
    constraints = [
        {"muscle_group": item.get("area"), "severity": item.get("severity", 0), "status": "active"}
        for item in (context.get("injuries") or [])
        if isinstance(item, dict) and bool(item.get("is_active", True))
    ]
    workouts = get_workouts_by_user(user["id"])
    history, latest_dates = expert_history_context(workouts)
    dynamic_program = generate_dynamic_program(
        planner_profile, preferences, EXERCISE_POOL, context.get("equipment") or [],
        active_doms, constraints, history=history, last_workout_dates=latest_dates,
        exercise_preferences=movement_preferences,
    )
    recommendation = build_recommendation_program(
        dynamic_program, context, days_per_week, context.get("rpe_summary"),
    )
    recommendation.update({key: context.get(key) for key in ("equipment_source", "equipment_source_label", "default_gym_name", "preferred_equipment")})
    recommendation.update(movement_preferences)
    return recommendation


def save_expert_recommendation(user: dict, recommendation: dict) -> dict:
    preferences = _parse_dashboard_preferences(dict(user).get("dashboard_preferences", "{}"))
    preferences["schema_version"] = max(2, int(preferences.get("schema_version") or 1))
    preferences["expert_recommendation"] = recommendation
    pref_json = json.dumps(preferences, ensure_ascii=False)
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET dashboard_preferences = ? WHERE id = ?",
            (pref_json, user["id"]),
        )
        conn.execute(
            "UPDATE athlete_profiles SET dashboard_preferences = ? WHERE user_id = ?",
            (pref_json, user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return preferences


EXPERT_WEEKDAY_LABELS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
EXPERT_CONTENT_KEYS = (
    "content_id", "type", "focus", "isRest", "session_id", "content_status",
    "content_reason", "exercises",
)


def expert_slot_id(week_number: int, day_index: int) -> str:
    return f"week-{week_number}-day-{day_index + 1}"


def expert_content_from_day(day: dict, fallback_content_id: str) -> dict:
    content = {key: day.get(key) for key in EXPERT_CONTENT_KEYS if key in day}
    content["content_id"] = str(content.get("content_id") or day.get("day_id") or fallback_content_id)
    content["type"] = str(content.get("type") or "Dinlenme")
    content["focus"] = str(content.get("focus") or ("Toparlanma" if content.get("isRest") else "Genel antrenman"))
    normalized_exs = []
    for ex in (content.get("exercises") or []):
        if not isinstance(ex, dict):
            continue
        ex_dict = dict(ex)
        ex_name = ex_dict.get("name") or ex_dict.get("exercise_name") or "Egzersiz"
        ex_id = ex_dict.get("id") or ex_dict.get("exercise_id") or "exercise"
        ex_dict["name"] = str(ex_name)
        ex_dict["exercise_name"] = str(ex_name)
        ex_dict["id"] = str(ex_id)
        ex_dict["exercise_id"] = str(ex_id)
        if not ex_dict.get("sets"):
            sets_d = ex_dict.get("sets_data")
            ex_dict["sets"] = str(len(sets_d)) if isinstance(sets_d, list) and sets_d else "3"
        if not ex_dict.get("reps"):
            sets_d = ex_dict.get("sets_data")
            if isinstance(sets_d, list) and sets_d and isinstance(sets_d[0], dict) and sets_d[0].get("reps"):
                ex_dict["reps"] = str(sets_d[0]["reps"])
            else:
                ex_dict["reps"] = "8-12"
        normalized_exs.append(ex_dict)
    content["exercises"] = normalized_exs
    return content


def expert_normalize_week_slots(days: object, week_number: int) -> list[dict]:
    source_days = [item for item in (days or []) if isinstance(item, dict)]
    normalized: list[dict] = []
    for index, label in enumerate(EXPERT_WEEKDAY_LABELS):
        source = source_days[index] if index < len(source_days) else {}
        slot_id = expert_slot_id(week_number, index)
        content = expert_content_from_day(source, f"week-{week_number}-content-{index + 1}")
        normalized.append({"day_id": slot_id, "slot_id": slot_id, "day": label, **content})
    return normalized


def expert_normalize_recommendation_slots(recommendation: dict) -> dict:
    weeks = recommendation.get("weeks") if isinstance(recommendation, dict) else None
    if not isinstance(weeks, list):
        return recommendation
    for index, week in enumerate(weeks, start=1):
        if isinstance(week, dict):
            week["days"] = expert_normalize_week_slots(week.get("days"), index)
    return recommendation


def validate_injury_payload(data: ExpertInjuryDataRequest, existing: dict | None = None) -> dict:
    allowed_areas = {
        "Omuz", "Dirsek", "Bilek", "El", "Boyun", "Bel", "Kalça", "Diz", "Ayak bileği",
        "Göğüs", "Sırt", "Biceps", "Triceps", "Quadriceps", "Hamstring", "Gluteus", "Calf",
    }
    allowed_types = {"tendon", "joint", "muscle_tissue", "bone", "nerve", "other"}
    area = str(data.area or "").strip()
    injury_type = str(data.injury_type or "other").strip()
    if area not in allowed_areas:
        raise HTTPException(status_code=400, detail="Geçerli bir sakatlık bölgesi seçin.")
    if injury_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Geçerli bir sakatlık türü seçin.")
    if not 0 <= int(data.severity) <= 5:
        raise HTTPException(status_code=400, detail="Şiddet değeri 0 ile 5 arasında olmalıdır.")

    is_active = bool(data.is_active)
    today = date.today().isoformat()
    was_active = bool((existing or {}).get("is_active", True))
    if is_active:
        started_on = today if not existing or not was_active else expert_date(existing.get("started_on") or today)
    else:
        started_on = expert_date((existing or {}).get("started_on")) if existing and (existing or {}).get("started_on") else None

    return {
        "area": area,
        "injury_type": injury_type,
        "severity": int(data.severity),
        "is_active": is_active,
        "started_on": started_on,
        "notes": str(data.notes or "").strip()[:500],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def expert_data_state(user: dict) -> dict:
    conn = get_db()
    try:
        profile = expert_data_profile(conn, user["id"])
    finally:
        conn.close()
    account = get_user_by_id(user["id"]) or user
    equip_sel = equipment_selection(profile, account.get("dashboard_preferences", "{}"))
    move_prefs = exercise_preference_selection(account.get("dashboard_preferences", "{}"))
    workouts = get_workouts_by_user(user["id"])
    sessions_data = [
        {
            "id": w.get("id"),
            "date": str(w.get("date", ""))[:10],
            "type": w.get("session_type", "Workout"),
            "notes": w.get("notes", ""),
            "exercises": w.get("exercises") or [],
        }
        for w in workouts
    ]
    return {
        "success": True,
        "user": {
            "id": account["id"],
            "username": account.get("username"),
            "created_at": str(account.get("created_at", "")),
        },
        "sessions": sessions_data,
        "target_muscles": profile.get("target_muscles") or {},
        "doms_daily": profile.get("doms_daily") or {},
        "gyms": equip_sel["gyms"],
        "preferred_equipment": equip_sel["preferred_equipment"],
        "preferred_exercise_ids": move_prefs["preferred_exercise_ids"],
        "avoid_exercise_ids": move_prefs["avoid_exercise_ids"],
        "default_gym_id": equip_sel["default_gym_id"],
        "default_gym_name": equip_sel["default_gym_name"],
        "equipment_source": equip_sel["equipment_source"],
        "equipment_source_label": equip_sel["equipment_source_label"],
        "injuries": profile.get("injuries") or [],
        "rpe_checkins": profile.get("rpe_checkins") or [],
        "recommendation": _parse_dashboard_preferences(account.get("dashboard_preferences", "{}")).get("expert_recommendation"),
        "metrics": expert_data_metrics(profile.get("doms_daily") or {}),
        "catalog": {
            "primary_goals": PRIMARY_GOALS,
            "detailed_muscles": list(DETAILED_MUSCLE_OPTIONS),
            "gym_equipment": [item for item in GYM_EQUIPMENT_CATALOG if item.get("group") not in {"Sehpalar", "Ağırlıklar"}],
            "exercise_preferences": expert_exercise_catalog(),
            "injury_areas": [
                "Omuz", "Dirsek", "Bilek", "El", "Boyun", "Bel", "Kalça", "Diz", "Ayak bileği",
                "Göğüs", "Sırt", "Biceps", "Triceps", "Quadriceps", "Hamstring", "Gluteus", "Calf",
            ],
            "injury_types": {
                "tendon": "Tendon",
                "joint": "Eklem",
                "muscle_tissue": "Kas dokusu",
                "bone": "Kemik",
                "nerve": "Sinir",
                "other": "Diğer",
            },
            "pain_scale": {"min": 0, "max": 5, "labels": ["Yok", "Hafif", "Düşük", "Orta", "Yüksek", "Çok yüksek"]},
            "rpe_scale": {"min": 1, "max": 10, "labels": ["Çok kolay", "Maksimale yakın"]},
            "max_priority_muscles": 3,
        },
    }

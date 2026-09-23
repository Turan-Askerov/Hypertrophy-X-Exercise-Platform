"""Uzman Sistemi ve Veri Toplama Uç Noktaları."""
from datetime import date, datetime, timedelta
from typing import Optional, List
import json
import secrets
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Body

from core.database import get_db, DATABASE_BACKEND
from core.security import _resolve_current_user
from services.user_service import get_user_by_id
from services.workout_service import (
    get_workouts_by_user,
    _iter_workout_exercises,
    _parse_dashboard_preferences,
    _canonical_exercise_from_entry,
)
from exercise_catalog import EXERCISE_POOL
from expert_system import (
    AVAILABLE_EQUIPMENT_OPTIONS,
    GYM_EQUIPMENT_CATALOG,
    DETAILED_MUSCLE_OPTIONS,
    PRIMARY_GOALS,
    UI_MUSCLE_GROUPS,
    build_expert_result,
    eligibility as expert_eligibility,
    generate_dynamic_program,
    get_exercise_alternatives,
    handle_missed_session,
    is_expert_catalog_excluded,
    normalize_detailed_muscle,
    normalize_gym_equipment,
    validate_detailed_preferences,
    validate_preferences as validate_expert_preferences,
    validate_score as validate_expert_score,
    build_recommendation_program,
    format_tr_date,
    rpe_summary_from_rir,
)
from routers.exercises import _display_muscle_groups
from models.schemas import (
    ExpertPreferencesRequest,
    ExpertCheckinRequest,
    ExpertDomsReportRequest,
    ExpertEquipmentRequest,
    ExpertConstraintRequest,
    ExpertGenerateProgramRequest,
    ExpertActivateProgramRequest,
    ExpertMissedSessionRequest,
    ExpertLegacyResetRequest,
    ExpertRpeDataRequest,
    ExpertInjuryDataRequest,
    ExpertGoalsDataRequest,
    ExpertDomsDataRequest,
    ExpertDomsEntryUpdateRequest,
    ExpertGymDataRequest,
    ExpertEquipmentPreferencesRequest,
    ExpertMovementPreferencesRequest,
)

router = APIRouter(tags=["expert"])


# ═══════════════════════════════════════════════
# UZMAN SİSTEMİ — KALICILIK VE DURUM YARDIMCILARI
# ═══════════════════════════════════════════════
def _expert_date(value: Optional[str] = None) -> str:
    """Kullanıcıdan gelen tarihi güvenli ISO-8601 biçimine çevirir."""
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Tarih YYYY-MM-DD biçiminde olmalıdır.") from exc


def _json_dict(raw_value) -> dict:
    """JSON nesnesi alanlarını bozuk eski değerlerde güvenli biçimde çözer."""
    if isinstance(raw_value, dict):
        return raw_value
    try:
        value = json.loads(raw_value or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _json_list(raw_value) -> list:
    """Bozuk veya eski JSON alanlarında API yanıtını güvenli biçimde korur."""
    if isinstance(raw_value, list):
        return raw_value
    try:
        value = json.loads(raw_value or "[]")
        return value if isinstance(value, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _normalize_gyms_with_default(gyms: object) -> list[dict]:
    """Eski salon kayıtlarını korur ve API'de yalnız bir varsayılan döndürür."""
    normalized = [dict(item) for item in (gyms or []) if isinstance(item, dict) and item.get("id")]
    selected_id = next((str(item["id"]) for item in normalized if bool(item.get("is_default"))), None)
    if not selected_id and normalized:
        selected_id = str(normalized[0]["id"])
    for item in normalized:
        item["is_default"] = str(item.get("id")) == selected_id
    return normalized


def _exercise_preference_selection(dashboard_preferences: object) -> dict:
    """Tercihleri mevcut dashboard JSON'unda saklar; eski kullanıcıları korur."""
    preferences = _parse_dashboard_preferences(dashboard_preferences)
    raw = preferences.get("exercise_preferences") if isinstance(preferences.get("exercise_preferences"), dict) else {}
    known_ids = {str(item.get("id")) for item in EXERCISE_POOL if isinstance(item, dict) and item.get("id") and not is_expert_catalog_excluded(item)}
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


def _expert_exercise_catalog() -> list[dict]:
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


def _clean_gym_equipment(values: List[str]) -> list[str]:
    equipment: list[str] = []
    for raw_value in values or []:
        equipment_id = normalize_gym_equipment(raw_value)
        if not equipment_id:
            continue
        if equipment_id not in equipment:
            equipment.append(equipment_id)
    return equipment


def _equipment_selection(profile: dict, dashboard_preferences: object) -> dict:
    gyms = _normalize_gyms_with_default(profile.get("gyms") or [])
    preferences = _parse_dashboard_preferences(dashboard_preferences)
    raw_preferred = (preferences.get("equipment_preferences") or {}).get("preferred_equipment") or []
    preferred = _clean_gym_equipment(raw_preferred) if raw_preferred else []
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


def _expert_data_profile(conn, user_id: int, create: bool = True) -> dict | None:
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
        "target_muscles": _json_dict(data.get("target_muscles_json")),
        "doms_daily": _json_dict(data.get("doms_daily_json")),
        "gyms": _normalize_gyms_with_default(_json_list(data.get("gym_equipment_json"))),
        "injuries": _json_list(data.get("injuries_json")),
        "rpe_checkins": _json_list(data.get("rpe_checkins_json")),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }


def _save_expert_data_profile(conn, user_id: int, profile: dict) -> None:
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
            json.dumps(_normalize_gyms_with_default(profile.get("gyms") or []), ensure_ascii=False),
            json.dumps(profile.get("injuries") or [], ensure_ascii=False),
            json.dumps(profile.get("rpe_checkins") or [], ensure_ascii=False),
        ),
    )
    conn.commit()


def _expert_data_metrics(doms_daily: dict) -> list[dict]:
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


def _expert_preferences_for_user(conn, user_id: int) -> Optional[dict]:
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


def _expert_latest_checkin(conn, user_id: int) -> Optional[dict]:
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


def _expert_active_doms(conn, user_id: int) -> list[dict]:
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


def _expert_equipment_for_user(conn, user_id: int) -> tuple[list[str], bool]:
    row = conn.execute(
        "SELECT available_equipment FROM expert_equipment WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not row:
        return [], False
    return _json_list(dict(row).get("available_equipment")), True


def _expert_active_constraints(conn, user_id: int) -> list[dict]:
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


def _expert_active_program(conn, user_id: int) -> dict | None:
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


def _parse_iso_date_safe(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _expert_history_context(workouts: list[dict]) -> tuple[dict, dict[str, str]]:
    """Son yedi takvim gününün doğrudan setlerini ve kas seansı tarihlerini çıkarır."""
    cutoff = date.today() - timedelta(days=6)
    volume: dict[str, int] = defaultdict(int)
    latest_dates: dict[str, str] = {}
    for workout in workouts or []:
        workout_date = _expert_date(workout.get("date")) if _parse_iso_date_safe(workout.get("date")) else None
        if not workout_date:
            continue
        parsed_date = _parse_iso_date_safe(workout_date)
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


def _expert_state(user: dict) -> dict:
    workouts = get_workouts_by_user(user["id"])
    eligibility = expert_eligibility(user, len(workouts))
    conn = get_db()
    try:
        preferences = _expert_preferences_for_user(conn, user["id"])
        latest_checkin = _expert_latest_checkin(conn, user["id"])
        active_doms = _expert_active_doms(conn, user["id"])
        equipment, equipment_configured = _expert_equipment_for_user(conn, user["id"])
        constraints = _expert_active_constraints(conn, user["id"])
        active_program = _expert_active_program(conn, user["id"])
    finally:
        conn.close()

    result = None
    history, latest_dates = _expert_history_context(workouts)
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
        "active_program": active_program,
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


def _expert_require_ready(user: dict) -> None:
    workouts = get_workouts_by_user(user["id"])
    state = expert_eligibility(user, len(workouts))
    if not state["ready"]:
        raise HTTPException(status_code=409, detail=state)


def _expert_require_preferences(conn, user_id: int) -> dict:
    preferences = _expert_preferences_for_user(conn, user_id)
    if not preferences:
        raise HTTPException(
            status_code=409,
            detail="Önce amaç ve öncelikli kas grupları anketini kaydedin.",
        )
    return preferences


def _expert_store_program_version(conn, user_id: int, program: dict) -> int:
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


def _expert_recent_rir_summary(user_id: int) -> dict | None:
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


def _expert_rule_context(profile: dict, user_id: int, dashboard_preferences: object = "{}") -> dict:
    labels = {item["id"]: item["label"] for item in DETAILED_MUSCLE_OPTIONS}
    metrics = []
    for item in _expert_data_metrics(profile.get("doms_daily") or {}):
        copied = dict(item)
        copied["muscle_label"] = labels.get(copied.get("muscle_group"), copied.get("muscle_group"))
        metrics.append(copied)
    equipment_selection = _equipment_selection(profile, dashboard_preferences)
    targets = profile.get("target_muscles") or {}
    target_ids = targets.get("priority_muscles") or []
    recent_rir = _expert_recent_rir_summary(user_id)
    return {
        "targets": targets,
        "target_muscle_labels": [labels.get(item, str(item)) for item in target_ids],
        "doms_metrics": metrics,
        "injuries": profile.get("injuries") or [],
        "equipment": equipment_selection["equipment"],
        "preferred_equipment": equipment_selection["preferred_equipment"],
        "default_gym_id": equipment_selection["default_gym_id"],
        "default_gym_name": equipment_selection["default_gym_name"],
        "equipment_source": equipment_selection["equipment_source"],
        "equipment_source_label": equipment_selection["equipment_source_label"],
        "recent_rir": recent_rir,
        "rpe_summary": rpe_summary_from_rir(recent_rir),
    }


def _expert_data_analysis(user: dict) -> dict:
    from expert_system import evaluate_expert_rules
    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
    finally:
        conn.close()
    analysis = evaluate_expert_rules(_expert_rule_context(profile or {}, user["id"], user.get("dashboard_preferences", "{}")))
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


def _recommendation_days_per_week(user: dict) -> int:
    try:
        days = int(user.get("days_per_week") or 3)
    except (TypeError, ValueError):
        days = 3
    return max(1, min(7, days))


def _build_expert_recommendation(user: dict) -> dict:
    conn = get_db()
    try:
        expert_profile = _expert_data_profile(conn, user["id"])
    finally:
        conn.close()
    expert_profile = expert_profile or {}
    context = _expert_rule_context(expert_profile, user["id"], user.get("dashboard_preferences", "{}"))
    days_per_week = _recommendation_days_per_week(user)
    targets = context.get("targets") or {}
    planner_profile = dict(user)
    planner_profile["days_per_week"] = days_per_week
    movement_preferences = _exercise_preference_selection(user.get("dashboard_preferences", "{}"))
    raw_goal = str(targets.get("primary_goal") or user.get("goal") or "hypertrophy").strip().lower()
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
    history, latest_dates = _expert_history_context(workouts)
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


def _save_expert_recommendation(user: dict, recommendation: dict) -> dict:
    preferences = _parse_dashboard_preferences(user.get("dashboard_preferences", "{}"))
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


_EXPERT_WEEKDAY_LABELS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
_EXPERT_CONTENT_KEYS = (
    "content_id", "type", "focus", "isRest", "session_id", "content_status",
    "content_reason", "exercises",
)


def _expert_slot_id(week_number: int, day_index: int) -> str:
    return f"week-{week_number}-day-{day_index + 1}"


def _expert_content_from_day(day: dict, fallback_content_id: str) -> dict:
    content = {key: day.get(key) for key in _EXPERT_CONTENT_KEYS if key in day}
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


def _expert_normalize_week_slots(days: object, week_number: int) -> list[dict]:
    source_days = [item for item in (days or []) if isinstance(item, dict)]
    normalized: list[dict] = []
    for index, label in enumerate(_EXPERT_WEEKDAY_LABELS):
        source = source_days[index] if index < len(source_days) else {}
        slot_id = _expert_slot_id(week_number, index)
        content = _expert_content_from_day(source, f"week-{week_number}-content-{index + 1}")
        normalized.append({"day_id": slot_id, "slot_id": slot_id, "day": label, **content})
    return normalized


def _expert_normalize_recommendation_slots(recommendation: dict) -> dict:
    weeks = recommendation.get("weeks") if isinstance(recommendation, dict) else None
    if not isinstance(weeks, list):
        return recommendation
    for index, week in enumerate(weeks, start=1):
        if isinstance(week, dict):
            week["days"] = _expert_normalize_week_slots(week.get("days"), index)
    return recommendation


def _validate_injury_payload(data: ExpertInjuryDataRequest, existing: dict | None = None) -> dict:
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
        started_on = today if not existing or not was_active else _expert_date(existing.get("started_on") or today)
    else:
        started_on = _expert_date((existing or {}).get("started_on")) if existing and (existing or {}).get("started_on") else None

    return {
        "area": area,
        "injury_type": injury_type,
        "severity": int(data.severity),
        "is_active": is_active,
        "started_on": started_on,
        "notes": str(data.notes or "").strip()[:500],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _expert_data_state(user: dict) -> dict:
    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
    finally:
        conn.close()
    account = get_user_by_id(user["id"]) or user
    equipment_selection = _equipment_selection(profile, account.get("dashboard_preferences", "{}"))
    movement_preferences = _exercise_preference_selection(account.get("dashboard_preferences", "{}"))
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
        "gyms": equipment_selection["gyms"],
        "preferred_equipment": equipment_selection["preferred_equipment"],
        "preferred_exercise_ids": movement_preferences["preferred_exercise_ids"],
        "avoid_exercise_ids": movement_preferences["avoid_exercise_ids"],
        "default_gym_id": equipment_selection["default_gym_id"],
        "default_gym_name": equipment_selection["default_gym_name"],
        "equipment_source": equipment_selection["equipment_source"],
        "equipment_source_label": equipment_selection["equipment_source_label"],
        "injuries": profile.get("injuries") or [],
        "rpe_checkins": profile.get("rpe_checkins") or [],
        "recommendation": _parse_dashboard_preferences(account.get("dashboard_preferences", "{}")).get("expert_recommendation"),
        "metrics": _expert_data_metrics(profile.get("doms_daily") or {}),
        "catalog": {
            "primary_goals": PRIMARY_GOALS,
            "detailed_muscles": list(DETAILED_MUSCLE_OPTIONS),
            "gym_equipment": [item for item in GYM_EQUIPMENT_CATALOG if item.get("group") not in {"Sehpalar", "Ağırlıklar"}],
            "exercise_preferences": _expert_exercise_catalog(),
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


# ═══════════════════════════════════════════════
# UZMAN SİSTEMİ ENDPOINT'LERİ (/api/expert-system/...)
# ═══════════════════════════════════════════════
@router.get("/api/expert-system")
def expert_system_state(user: dict = Depends(_resolve_current_user)):
    """Uzman sistemi ekranının ihtiyaç duyduğu tüm merkezi durumu döndürür."""
    return _expert_state(user)


@router.post("/api/expert-system/preferences")
def save_expert_preferences(
    data: ExpertPreferencesRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    _expert_require_ready(user)
    try:
        try:
            preferences = validate_detailed_preferences(data.primary_goal, data.priority_muscles)
        except ValueError:
            preferences = validate_expert_preferences(data.primary_goal, data.priority_muscles)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    conn = get_db()
    try:
        exists = conn.execute(
            "SELECT user_id FROM expert_preferences WHERE user_id = ?", (user["id"],)
        ).fetchone()
        payload = json.dumps(preferences.priority_muscles, ensure_ascii=False)
        if exists:
            conn.execute(
                """
                UPDATE expert_preferences
                SET primary_goal = ?, priority_muscles = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (preferences.primary_goal, payload, user["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO expert_preferences (user_id, primary_goal, priority_muscles)
                VALUES (?, ?, ?)
                """,
                (user["id"], preferences.primary_goal, payload),
            )
        conn.commit()
    finally:
        conn.close()
    return _expert_state(user)


@router.post("/api/expert-system/checkins")
def save_expert_checkin(
    data: ExpertCheckinRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    _expert_require_ready(user)
    checkin_type = str(data.checkin_type or "").strip().lower()
    if checkin_type not in {"session", "daily"}:
        raise HTTPException(status_code=400, detail="Kontrol türü session veya daily olmalıdır.")
    try:
        checkin_date = _expert_date(data.checkin_date)
        session_rpe = validate_expert_score(
            data.session_rpe, "Son seansın RPE değeri", required=checkin_type == "session"
        )
        fatigue = validate_expert_score(data.day_fatigue, "Gün içi yorgunluk", required=True)
        recovery = validate_expert_score(data.recovery_feeling, "Toparlanma hissi", required=True)
        completion = validate_expert_score(
            data.completion_percentage,
            "Set tamamlama oranı",
            minimum=0,
            maximum=100,
            required=checkin_type == "session",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    conn = get_db()
    try:
        _expert_require_preferences(conn, user["id"])
        existing = conn.execute(
            """
            SELECT id FROM expert_checkins
            WHERE user_id = ? AND checkin_date = ? AND checkin_type = ?
            ORDER BY id DESC LIMIT 1
            """,
            (user["id"], checkin_date, checkin_type),
        ).fetchone()
        values = (
            session_rpe,
            fatigue,
            recovery,
            completion,
            str(data.notes or "").strip()[:1000],
        )
        if existing:
            conn.execute(
                """
                UPDATE expert_checkins
                SET session_rpe = ?, day_fatigue = ?, recovery_feeling = ?,
                    completion_percentage = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*values, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO expert_checkins (
                    user_id, checkin_date, checkin_type, session_rpe, day_fatigue,
                    recovery_feeling, completion_percentage, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user["id"], checkin_date, checkin_type, *values),
            )
        conn.commit()
    finally:
        conn.close()
    return _expert_state(user)


@router.post("/api/expert-system/doms-reports")
def save_expert_doms_reports(
    data: ExpertDomsReportRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    _expert_require_ready(user)
    if not data.reports or len(data.reports) > len(UI_MUSCLE_GROUPS):
        raise HTTPException(status_code=400, detail="En az 1, en fazla 7 kas ağrısı kaydı gönderin.")
    report_date = _expert_date(data.report_date)

    cleaned: list[tuple[str, float, str]] = []
    seen: set[str] = set()
    for report in data.reports:
        group = normalize_muscle_group(report.muscle_group)
        if not group:
            raise HTTPException(status_code=400, detail="Geçersiz kas grubu seçildi.")
        if group in seen:
            raise HTTPException(status_code=400, detail="Bir kas grubu aynı ankette yalnızca bir kez girilebilir.")
        try:
            severity = validate_expert_score(report.severity, f"{group} DOMS", required=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        seen.add(group)
        cleaned.append((group, float(severity), str(report.notes or "").strip()[:600]))

    conn = get_db()
    try:
        _expert_require_preferences(conn, user["id"])
        for group, severity, notes in cleaned:
            active = conn.execute(
                """
                SELECT id FROM expert_doms_cases
                WHERE user_id = ? AND muscle_group = ? AND status = 'active'
                ORDER BY last_report_date DESC, id DESC LIMIT 1
                """,
                (user["id"], group),
            ).fetchone()
            if active:
                case_id = active["id"]
                if severity <= 0:
                    conn.execute(
                        """
                        UPDATE expert_doms_cases
                        SET last_severity = 0, last_report_date = ?, status = 'resolved',
                            resolved_on = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (report_date, report_date, case_id),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE expert_doms_cases
                        SET last_severity = ?, last_report_date = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (severity, report_date, case_id),
                    )
                conn.execute(
                    """
                    INSERT INTO expert_doms_reports (doms_case_id, report_date, severity, notes)
                    VALUES (?, ?, ?, ?)
                    """,
                    (case_id, report_date, severity, notes),
                )
            elif severity > 0:
                conn.execute(
                    """
                    INSERT INTO expert_doms_cases (
                        user_id, muscle_group, started_on, status, last_severity, last_report_date
                    ) VALUES (?, ?, ?, 'active', ?, ?)
                    """,
                    (user["id"], group, report_date, severity, report_date),
                )
                new_case = conn.execute(
                    """
                    SELECT id FROM expert_doms_cases
                    WHERE user_id = ? AND muscle_group = ? AND status = 'active'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (user["id"], group),
                ).fetchone()
                conn.execute(
                    """
                    INSERT INTO expert_doms_reports (doms_case_id, report_date, severity, notes)
                    VALUES (?, ?, ?, ?)
                    """,
                    (new_case["id"], report_date, severity, notes),
                )
        conn.commit()
    finally:
        conn.close()
    return _expert_state(user)


@router.post("/api/expert-system/equipment")
def save_expert_equipment(
    data: ExpertEquipmentRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    _expert_require_ready(user)
    allowed = {item["id"] for item in AVAILABLE_EQUIPMENT_OPTIONS}
    cleaned: list[str] = []
    for raw in data.available_equipment or []:
        equipment_id = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
        if equipment_id not in allowed:
            raise HTTPException(status_code=400, detail="Geçersiz ekipman seçildi.")
        if equipment_id not in cleaned:
            cleaned.append(equipment_id)
    if not cleaned:
        raise HTTPException(status_code=400, detail="Program üretmek için en az bir erişilebilir ekipman seçin.")

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT user_id FROM expert_equipment WHERE user_id = ?", (user["id"],)
        ).fetchone()
        payload = json.dumps(cleaned, ensure_ascii=False)
        if existing:
            conn.execute(
                "UPDATE expert_equipment SET available_equipment = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (payload, user["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO expert_equipment (user_id, available_equipment) VALUES (?, ?)",
                (user["id"], payload),
            )
        conn.commit()
    finally:
        conn.close()
    return _expert_state(user)


@router.post("/api/expert-system/constraints")
def save_expert_constraint(
    data: ExpertConstraintRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    _expert_require_ready(user)
    muscle = normalize_detailed_muscle(data.muscle_group)
    if not muscle:
        raise HTTPException(status_code=400, detail="Geçerli bir ayrıntılı kas bölgesi seçin.")
    allowed_types = {"pain", "tendon", "medical_clearance"}
    constraint_type = str(data.constraint_type or "pain").strip().lower()
    if constraint_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Geçersiz kısıt türü seçildi.")
    try:
        severity = float(validate_expert_score(data.severity, "Kısıt şiddeti", required=True))
        started_on = _expert_date(data.started_on)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resolved = bool(data.resolved) or severity <= 0
    status = "resolved" if resolved else "active"
    resolved_on = date.today().isoformat() if resolved else None
    notes = str(data.notes or "").strip()[:600]

    conn = get_db()
    try:
        _expert_require_preferences(conn, user["id"])
        if data.constraint_id:
            existing = conn.execute(
                "SELECT id FROM expert_constraints WHERE id = ? AND user_id = ?",
                (data.constraint_id, user["id"]),
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Kısıt kaydı bulunamadı.")
            conn.execute(
                """
                UPDATE expert_constraints
                SET muscle_group = ?, constraint_type = ?, severity = ?, notes = ?,
                    started_on = ?, status = ?, resolved_on = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                (muscle, constraint_type, 0 if resolved else severity, notes, started_on, status, resolved_on, data.constraint_id, user["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO expert_constraints (
                    user_id, muscle_group, constraint_type, severity, notes, started_on, resolved_on, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user["id"], muscle, constraint_type, 0 if resolved else severity, notes, started_on, resolved_on, status),
            )
        conn.commit()
    finally:
        conn.close()
    return _expert_state(user)


@router.post("/api/expert-system/generate-program")
def generate_expert_program(
    data: ExpertGenerateProgramRequest = Body(default=ExpertGenerateProgramRequest()),
    user: dict = Depends(_resolve_current_user),
):
    _expert_require_ready(user)
    profile = dict(user)
    if data.days_per_week is not None:
        if not 1 <= int(data.days_per_week) <= 7:
            raise HTTPException(status_code=400, detail="Haftalık gün sayısı 1 ile 7 arasında olmalıdır.")
        profile["days_per_week"] = int(data.days_per_week)

    workouts = get_workouts_by_user(user["id"])
    history, latest_dates = _expert_history_context(workouts)
    conn = get_db()
    try:
        preferences = _expert_require_preferences(conn, user["id"])
        equipment, equipment_configured = _expert_equipment_for_user(conn, user["id"])
        if not equipment_configured or not equipment:
            raise HTTPException(status_code=409, detail="Önce erişebildiğiniz ekipmanı kaydedin.")
        active_doms = _expert_active_doms(conn, user["id"])
        constraints = _expert_active_constraints(conn, user["id"])
        try:
            program = generate_dynamic_program(
                profile, preferences, EXERCISE_POOL, equipment, active_doms, constraints,
                history=history, last_workout_dates=latest_dates,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        version_id = _expert_store_program_version(conn, user["id"], program)
        conn.commit()
    finally:
        conn.close()
    return {"message": "Uzman programı taslak olarak üretildi; aktif etmek için onay verin.", "program_version_id": version_id, "program": program}


@router.post("/api/expert-system/activate-program")
def activate_expert_program(
    data: ExpertActivateProgramRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    _expert_require_ready(user)
    conn = get_db()
    try:
        version = conn.execute(
            "SELECT id FROM expert_program_versions WHERE id = ? AND user_id = ?",
            (data.program_version_id, user["id"]),
        ).fetchone()
        if not version:
            raise HTTPException(status_code=404, detail="Aktifleştirilecek uzman programı bulunamadı.")
        conn.execute("UPDATE expert_program_versions SET is_active = FALSE WHERE user_id = ?", (user["id"],))
        conn.execute(
            "UPDATE expert_program_versions SET is_active = TRUE, activated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (data.program_version_id, user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return _expert_state(user)


@router.post("/api/expert-system/missed-session")
def reschedule_missed_expert_session(
    data: ExpertMissedSessionRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    """Kaçırılan uzman seansı için pasif, kullanıcı onaylı yeni taslak sürüm üretir."""
    _expert_require_ready(user)
    try:
        recovery_score = float(data.recovery_score)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Toparlanma puanı geçersiz.") from exc
    if not 0 <= recovery_score <= 100:
        raise HTTPException(status_code=400, detail="Toparlanma puanı 0 ile 100 arasında olmalıdır.")

    conn = get_db()
    try:
        requested_id = data.program_version_id
        if requested_id:
            row = conn.execute(
                "SELECT id, program_json FROM expert_program_versions WHERE id = ? AND user_id = ?",
                (requested_id, user["id"]),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT id, program_json FROM expert_program_versions
                WHERE user_id = ? AND is_active = TRUE
                ORDER BY activated_at DESC, created_at DESC, id DESC LIMIT 1
                """,
                (user["id"],),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=409, detail="Telafi için önce bir uzman programını aktifleştirin.")
        try:
            source_program = json.loads(row["program_json"] or "{}")
            split_program = source_program.get("program") or source_program
            adjusted_split = handle_missed_session(
                split_program, data.session_id, _expert_active_doms(conn, user["id"]), recovery_score,
                _expert_active_constraints(conn, user["id"]),
            )
        except (TypeError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if "program" in source_program:
            source_program["program"] = adjusted_split
        else:
            source_program = adjusted_split
        source_program["rescheduled_from_version_id"] = int(row["id"])
        version_id = _expert_store_program_version(conn, user["id"], source_program)
        conn.commit()
    finally:
        conn.close()
    return {"message": "Telafi planı taslak olarak hazırlandı; isterseniz aktifleştirin.", "program_version_id": version_id, "program": source_program}


# ═══════════════════════════════════════════════
# UZMAN SİSTEMİ — VERİ TOPLAMA API'LERİ (/api/expert-data/...)
# ═══════════════════════════════════════════════
@router.get("/api/expert-data/analysis")
def get_expert_data_analysis(user: dict = Depends(_resolve_current_user)):
    return {"success": True, "analysis": _expert_data_analysis(user)}


@router.post("/api/expert-data/recommendation/generate")
def generate_expert_recommendation(user: dict = Depends(_resolve_current_user)):
    """Kullanıcının profilindeki gün sayısı ve uzman verileriyle taslak üretir."""
    fresh_user = get_user_by_id(user["id"]) or user
    try:
        recommendation = _build_expert_recommendation(fresh_user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    preferences = _save_expert_recommendation(fresh_user, recommendation)
    return {"success": True, "recommendation": recommendation, "dashboard_preferences": preferences}


@router.put("/api/expert-data/recommendation/reorder")
def reorder_expert_recommendation(data: dict = Body(...), user: dict = Depends(_resolve_current_user)):
    """Sabit Pazartesi–Pazar slotlarındaki içerikleri yer değiştirir ve GÜNCEL HAREKETLERİ kaydeder."""
    preferences = _parse_dashboard_preferences(user.get("dashboard_preferences", "{}"))
    recommendation = preferences.get("expert_recommendation")
    requested_weeks = data.get("weeks") if isinstance(data, dict) else None

    if not isinstance(recommendation, dict) or not isinstance(requested_weeks, list):
        raise HTTPException(status_code=404, detail="Düzenlenecek uzman önerisi bulunamadı.")

    recommendation = _expert_normalize_recommendation_slots(recommendation)
    current_weeks = recommendation.get("weeks") or []

    if not current_weeks:
        raise HTTPException(status_code=400, detail="Geçersiz öneri programı.")

    for index, current_week in enumerate(current_weeks, start=1):
        if index - 1 >= len(requested_weeks):
            continue
        sent_week = requested_weeks[index - 1] if isinstance(requested_weeks[index - 1], dict) else {}
        sent_days = sent_week.get("days") if isinstance(sent_week, dict) else None
        expected_slots = [_expert_slot_id(index, day_index) for day_index in range(7)]

        if not isinstance(sent_days, list) or len(sent_days) != 7:
            continue

        updated_days = []
        for day_index, slot_id in enumerate(expected_slots):
            sent_day = sent_days[day_index] if isinstance(sent_days[day_index], dict) else {}
            fallback_cid = f"week-{index}-content-{day_index + 1}"
            content = _expert_content_from_day(sent_day, fallback_cid)
            updated_days.append({
                "day_id": slot_id,
                "slot_id": slot_id,
                "day": _EXPERT_WEEKDAY_LABELS[day_index],
                **content,
            })
        current_week["days"] = updated_days

    preferences = _save_expert_recommendation(user, recommendation)
    return {"success": True, "recommendation": recommendation, "dashboard_preferences": preferences}


@router.post("/api/expert-data/rpe-checkins")
def save_expert_data_rpe_checkin(
    data: ExpertRpeDataRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    rpe = int(data.session_rpe)
    if not 1 <= rpe <= 10:
        raise HTTPException(status_code=400, detail="RPE değeri 1 ile 10 arasında olmalıdır.")
    checkin_date = _expert_date(data.checkin_date)
    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
        reports = [item for item in (profile.get("rpe_checkins") or []) if isinstance(item, dict) and item.get("checkin_date") != checkin_date]
        reports.append({
            "checkin_date": checkin_date,
            "session_rpe": rpe,
            "notes": str(data.notes or "").strip()[:600],
        })
        reports.sort(key=lambda item: str(item.get("checkin_date") or ""), reverse=True)
        profile["rpe_checkins"] = reports[:90]
        _save_expert_data_profile(conn, user["id"], profile)
    finally:
        conn.close()
    return {"success": True, "rpe_checkins": reports, "analysis": _expert_data_analysis(user)}


@router.get("/api/expert-data")
def get_expert_data(user: dict = Depends(_resolve_current_user)):
    """Yalnızca veri toplama ekranının tek profil kaydını ve kataloglarını döndürür."""
    return _expert_data_state(user)


@router.put("/api/expert-data/goals")
def save_expert_goals(data: ExpertGoalsDataRequest = Body(...),
                      user: dict = Depends(_resolve_current_user)):
    primary_goal = str(data.primary_goal or "").strip()
    if primary_goal not in PRIMARY_GOALS:
        raise HTTPException(status_code=400, detail="Geçerli bir ana hedef seçin.")

    priority_muscles: list[str] = []
    for raw_muscle in data.priority_muscles or []:
        muscle = normalize_detailed_muscle(raw_muscle)
        if muscle and muscle not in priority_muscles:
            priority_muscles.append(muscle)
    if len(priority_muscles) > 3:
        raise HTTPException(status_code=400, detail="En fazla 3 hedef kas seçebilirsiniz.")
    if primary_goal == "hypertrophy" and len(priority_muscles) < 1:
        raise HTTPException(status_code=400, detail="Kas kazanımı hedefinde en az 1 öncelikli kas seçmelisiniz.")

    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
        profile["target_muscles"] = {
            "primary_goal": primary_goal,
            "priority_muscles": priority_muscles,
            "priority_note": str(data.priority_note or "").strip()[:500],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        _save_expert_data_profile(conn, user["id"], profile)
    finally:
        conn.close()
    return _expert_data_state(user)


@router.post("/api/expert-system/doms")
@router.put("/api/expert-data/doms")
def upsert_expert_doms(data: ExpertDomsDataRequest = Body(...),
                       user: dict = Depends(_resolve_current_user)):
    """Bugün ve aynı kas grubu için önceki ağrı bildirimini değiştirir."""
    muscle = normalize_detailed_muscle(data.muscle_group)
    if not muscle:
        raise HTTPException(status_code=400, detail="Geçerli bir kas grubu seçin.")
    if not 0 <= int(data.severity) <= 5:
        raise HTTPException(status_code=400, detail="Kas ağrısı değeri 0 ile 5 arasında olmalıdır.")

    report_date = date.today().isoformat()
    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
        daily = profile.get("doms_daily") or {}
        same_day = daily.get(report_date) if isinstance(daily.get(report_date), list) else []
        daily[report_date] = [
            item for item in same_day
            if normalize_detailed_muscle((item or {}).get("muscle_group")) != muscle
        ]
        daily[report_date].append({
            "muscle_group": muscle,
            "severity": int(data.severity),
            "notes": str(data.notes or "").strip()[:500],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        profile["doms_daily"] = daily
        _save_expert_data_profile(conn, user["id"], profile)
    finally:
        conn.close()
    return _expert_data_state(user)


@router.put("/api/expert-system/doms/{report_date}/{muscle_group}")
@router.put("/api/expert-data/doms/{report_date}/{muscle_group}")
def update_expert_doms_entry(
    report_date: str,
    muscle_group: str,
    data: ExpertDomsEntryUpdateRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    target_date = _expert_date(report_date)
    muscle = normalize_detailed_muscle(muscle_group)
    if not muscle:
        raise HTTPException(status_code=400, detail="Geçerli bir kas grubu seçin.")
    if not 0 <= int(data.severity) <= 5:
        raise HTTPException(status_code=400, detail="Kas ağrısı değeri 0 ile 5 arasında olmalıdır.")

    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
        daily = profile.get("doms_daily") or {}
        entries = daily.get(target_date) if isinstance(daily.get(target_date), list) else []
        found = False
        updated_entries = []
        for raw_entry in entries:
            entry = raw_entry if isinstance(raw_entry, dict) else {}
            if normalize_detailed_muscle(entry.get("muscle_group")) == muscle:
                updated_entries.append({
                    "muscle_group": muscle,
                    "severity": int(data.severity),
                    "notes": str(data.notes or "").strip()[:500],
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                })
                found = True
            else:
                updated_entries.append(entry)
        if not found:
            raise HTTPException(status_code=404, detail="Kas ağrısı kaydı bulunamadı.")
        daily[target_date] = updated_entries
        profile["doms_daily"] = daily
        _save_expert_data_profile(conn, user["id"], profile)
    finally:
        conn.close()
    return _expert_data_state(user)


@router.delete("/api/expert-system/doms/{report_date}/{muscle_group}")
@router.delete("/api/expert-data/doms/{report_date}/{muscle_group}")
def delete_expert_doms_entry(
    report_date: str,
    muscle_group: str,
    user: dict = Depends(_resolve_current_user),
):
    target_date = _expert_date(report_date)
    muscle = normalize_detailed_muscle(muscle_group)
    if not muscle:
        raise HTTPException(status_code=400, detail="Geçerli bir kas grubu seçin.")

    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
        daily = profile.get("doms_daily") or {}
        entries = daily.get(target_date) if isinstance(daily.get(target_date), list) else []
        kept_entries = [
            entry for entry in entries
            if normalize_detailed_muscle((entry or {}).get("muscle_group")) != muscle
        ]
        if len(kept_entries) == len(entries):
            raise HTTPException(status_code=404, detail="Kas ağrısı kaydı bulunamadı.")
        if kept_entries:
            daily[target_date] = kept_entries
        else:
            daily.pop(target_date, None)
        profile["doms_daily"] = daily
        _save_expert_data_profile(conn, user["id"], profile)
    finally:
        conn.close()
    return _expert_data_state(user)


@router.post("/api/expert-system/gyms")
@router.post("/api/expert-data/gyms")
def create_expert_gym(data: ExpertGymDataRequest = Body(...),
                      user: dict = Depends(_resolve_current_user)):
    name = str(data.name or "").strip()
    if not 2 <= len(name) <= 80:
        raise HTTPException(status_code=400, detail="Salon adı 2 ile 80 karakter arasında olmalıdır.")
    equipment = _clean_gym_equipment(data.equipment)
    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
        gyms = profile.get("gyms") or []
        if any(str(item.get("name") or "").casefold() == name.casefold() for item in gyms if isinstance(item, dict)):
            raise HTTPException(status_code=409, detail="Bu isimde bir salon zaten kayıtlı.")
        if data.is_default:
            for existing_gym in gyms:
                if isinstance(existing_gym, dict):
                    existing_gym["is_default"] = False
        gyms.append({
            "id": "gym_" + secrets.token_hex(6),
            "name": name,
            "equipment": equipment,
            "is_default": bool(data.is_default) or not gyms,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        profile["gyms"] = _normalize_gyms_with_default(gyms)
        _save_expert_data_profile(conn, user["id"], profile)
    finally:
        conn.close()
    return _expert_data_state(user)


@router.put("/api/expert-system/gyms/{gym_id}")
@router.put("/api/expert-data/gyms/{gym_id}")
def update_expert_gym(gym_id: str, data: ExpertGymDataRequest = Body(...),
                      user: dict = Depends(_resolve_current_user)):
    name = str(data.name or "").strip()
    if not 2 <= len(name) <= 80:
        raise HTTPException(status_code=400, detail="Salon adı 2 ile 80 karakter arasında olmalıdır.")
    equipment = _clean_gym_equipment(data.equipment)
    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
        gyms = profile.get("gyms") or []
        gym = next((item for item in gyms if isinstance(item, dict) and item.get("id") == gym_id), None)
        if not gym:
            raise HTTPException(status_code=404, detail="Salon kaydı bulunamadı.")
        if any(item is not gym and str(item.get("name") or "").casefold() == name.casefold() for item in gyms if isinstance(item, dict)):
            raise HTTPException(status_code=409, detail="Bu isimde bir salon zaten kayıtlı.")
        if data.is_default:
            for existing_gym in gyms:
                if isinstance(existing_gym, dict) and existing_gym is not gym:
                    existing_gym["is_default"] = False
        gym.update({"name": name, "equipment": equipment, "is_default": bool(data.is_default), "updated_at": datetime.now().isoformat(timespec="seconds")})
        profile["gyms"] = _normalize_gyms_with_default(gyms)
        _save_expert_data_profile(conn, user["id"], profile)
    finally:
        conn.close()
    return _expert_data_state(user)


@router.delete("/api/expert-system/gyms/{gym_id}")
@router.delete("/api/expert-data/gyms/{gym_id}")
def delete_expert_gym(gym_id: str, user: dict = Depends(_resolve_current_user)):
    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
        gyms = profile.get("gyms") or []
        updated = [item for item in gyms if not (isinstance(item, dict) and item.get("id") == gym_id)]
        if len(updated) == len(gyms):
            raise HTTPException(status_code=404, detail="Salon kaydı bulunamadı.")
        profile["gyms"] = _normalize_gyms_with_default(updated)
        _save_expert_data_profile(conn, user["id"], profile)
    finally:
        conn.close()
    return _expert_data_state(user)


@router.put("/api/expert-data/equipment-preferences")
def save_expert_equipment_preferences(data: ExpertEquipmentPreferencesRequest = Body(...), user: dict = Depends(_resolve_current_user)):
    preferred = _clean_gym_equipment(data.preferred_equipment)
    conn = get_db()
    try:
        row = conn.execute("SELECT dashboard_preferences FROM users WHERE id = ?", (user["id"],)).fetchone()
        preferences = _parse_dashboard_preferences((dict(row) if row else {}).get("dashboard_preferences", "{}"))
        preferences["equipment_preferences"] = {"preferred_equipment": preferred, "updated_at": datetime.now().isoformat(timespec="seconds")}
        pref_json = json.dumps(preferences, ensure_ascii=False)
        conn.execute("UPDATE users SET dashboard_preferences = ? WHERE id = ?", (pref_json, user["id"]))
        conn.execute("UPDATE athlete_profiles SET dashboard_preferences = ? WHERE user_id = ?", (pref_json, user["id"]))
        conn.commit()
    finally:
        conn.close()
    return _expert_data_state(user)


@router.put("/api/expert-data/movement-preferences")
def save_expert_movement_preferences(data: ExpertMovementPreferencesRequest = Body(...), user: dict = Depends(_resolve_current_user)):
    known_ids = {str(item.get("id")) for item in EXERCISE_POOL if isinstance(item, dict) and item.get("id") and not is_expert_catalog_excluded(item)}
    avoided = []
    for value in data.avoid_exercise_ids:
        exercise_id = str(value).strip()
        if exercise_id in known_ids and exercise_id not in avoided:
            avoided.append(exercise_id)
    preferred = []
    for value in data.preferred_exercise_ids:
        exercise_id = str(value).strip()
        if exercise_id in known_ids and exercise_id not in avoided and exercise_id not in preferred:
            preferred.append(exercise_id)
    conn = get_db()
    try:
        row = conn.execute("SELECT dashboard_preferences FROM users WHERE id = ?", (user["id"],)).fetchone()
        preferences = _parse_dashboard_preferences((dict(row) if row else {}).get("dashboard_preferences", "{}"))
        preferences["exercise_preferences"] = {
            "preferred_exercise_ids": preferred,
            "avoid_exercise_ids": avoided,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        pref_json = json.dumps(preferences, ensure_ascii=False)
        conn.execute("UPDATE users SET dashboard_preferences = ? WHERE id = ?", (pref_json, user["id"]))
        conn.execute("UPDATE athlete_profiles SET dashboard_preferences = ? WHERE user_id = ?", (pref_json, user["id"]))
        conn.commit()
    finally:
        conn.close()
    return _expert_data_state(user)


@router.get("/api/expert-data/exercise-alternatives/{exercise_id}")
def expert_exercise_alternatives(
    exercise_id: str,
    exclude: str = "",
    user: dict = Depends(_resolve_current_user),
):
    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
    finally:
        conn.close()
    account = get_user_by_id(user["id"]) or user
    profile = profile or {}
    context = _expert_rule_context(profile, user["id"], account.get("dashboard_preferences", "{}"))
    movement_preferences = _exercise_preference_selection(account.get("dashboard_preferences", "{}"))
    active_doms = [
        {"muscle_group": item.get("muscle_group"), "severity": item.get("pain_level", 0)}
        for item in (context.get("doms_metrics") or []) if isinstance(item, dict)
    ]
    constraints = [
        {"muscle_group": item.get("area"), "severity": item.get("severity", 0), "status": "active"}
        for item in (context.get("injuries") or []) if isinstance(item, dict) and bool(item.get("is_active", True))
    ]
    excluded_ids = {value.strip() for value in str(exclude or "").split(",") if value.strip()}
    alternatives = [
        item for item in get_exercise_alternatives(
            exercise_id, EXERCISE_POOL, context.get("equipment") or [], active_doms, constraints, movement_preferences,
        )
        if str(item.get("id") or "") not in excluded_ids
    ]
    return {"success": True, "exercise_id": exercise_id, "alternatives": alternatives}


@router.put("/api/expert-data/recommendation/exercise-replace")
def replace_expert_recommendation_exercise(data: dict = Body(...), user: dict = Depends(_resolve_current_user)):
    payload = data if isinstance(data, dict) else {}
    try:
        week_index = int(payload.get("week_index"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Geçerli bir öneri haftası seçin.")
    slot_id = str(payload.get("slot_id") or "").strip()
    source_exercise_id = str(payload.get("source_exercise_id") or "").strip()
    alternative_exercise_id = str(payload.get("alternative_exercise_id") or "").strip()
    if not slot_id or not source_exercise_id or not alternative_exercise_id or source_exercise_id == alternative_exercise_id:
        raise HTTPException(status_code=400, detail="Geçerli kaynak ve alternatif hareket seçin.")

    preferences = _parse_dashboard_preferences(user.get("dashboard_preferences", "{}"))
    recommendation = preferences.get("expert_recommendation")
    if not isinstance(recommendation, dict):
        raise HTTPException(status_code=404, detail="Düzenlenecek uzman önerisi bulunamadı.")
    recommendation = _expert_normalize_recommendation_slots(recommendation)
    weeks = recommendation.get("weeks") or []
    if not 0 <= week_index < len(weeks):
        raise HTTPException(status_code=400, detail="Geçerli bir öneri haftası seçin.")
    days = weeks[week_index].get("days") if isinstance(weeks[week_index], dict) else None
    day = next((item for item in (days or []) if str(item.get("slot_id") or item.get("day_id") or "") == slot_id), None)
    if not isinstance(day, dict) or bool(day.get("isRest")):
        raise HTTPException(status_code=400, detail="Hareket değişimi yalnız antrenman günü yapılabilir.")

    alternative = next((item for item in EXERCISE_POOL if str(item.get("id") or "") == alternative_exercise_id), None)
    if not isinstance(alternative, dict) or is_expert_catalog_excluded(alternative):
        raise HTTPException(status_code=400, detail="Seçilen alternatif egzersiz havuzunda bulunamadı.")

    exercises = list(day.get("exercises") or [])
    if any(str(item.get("id") or "") == alternative_exercise_id for item in exercises if isinstance(item, dict)):
        raise HTTPException(status_code=400, detail="Bu hareket aynı günün önerisinde zaten bulunuyor.")

    source_catalog = next((item for item in EXERCISE_POOL if str(item.get("id") or "") == source_exercise_id), None)
    source_name = str((source_catalog or {}).get("name") or "").strip().casefold()
    replacement_index = next((
        index for index, item in enumerate(exercises)
        if isinstance(item, dict) and (
            str(item.get("id") or "") == source_exercise_id
            or (not item.get("id") and source_name and str(item.get("name") or "").strip().casefold() == source_name)
        )
    ), None)
    if replacement_index is None:
        raise HTTPException(status_code=404, detail="Değiştirilecek hareket taslakta bulunamadı.")

    replaced = dict(exercises[replacement_index])
    replaced["id"] = alternative_exercise_id
    replaced["name"] = str(alternative.get("name") or "Hareket")
    exercises[replacement_index] = replaced
    day["exercises"] = exercises
    preferences = _save_expert_recommendation(user, recommendation)
    return {
        "success": True,
        "recommendation": recommendation,
        "dashboard_preferences": preferences,
        "replaced_exercise": replaced,
    }


@router.post("/api/expert-system/injuries")
@router.post("/api/expert-data/injuries")
def create_expert_injury(data: ExpertInjuryDataRequest = Body(...),
                         user: dict = Depends(_resolve_current_user)):
    injury = _validate_injury_payload(data)
    injury["id"] = "inj_" + secrets.token_hex(6)
    injury["created_at"] = datetime.now().isoformat(timespec="seconds")
    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
        injuries = profile.get("injuries") or []
        injuries.append(injury)
        profile["injuries"] = injuries
        _save_expert_data_profile(conn, user["id"], profile)
    finally:
        conn.close()
    return _expert_data_state(user)


@router.put("/api/expert-system/injuries/{injury_id}")
@router.put("/api/expert-data/injuries/{injury_id}")
def update_expert_injury(injury_id: str, data: ExpertInjuryDataRequest = Body(...),
                         user: dict = Depends(_resolve_current_user)):
    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
        injuries = profile.get("injuries") or []
        injury = next((item for item in injuries if isinstance(item, dict) and item.get("id") == injury_id), None)
        if not injury:
            raise HTTPException(status_code=404, detail="Sakatlık kaydı bulunamadı.")
        updated = _validate_injury_payload(data, existing=injury)
        updated["id"] = injury_id
        updated["created_at"] = injury.get("created_at") or datetime.now().isoformat(timespec="seconds")
        injury.clear()
        injury.update(updated)
        profile["injuries"] = injuries
        _save_expert_data_profile(conn, user["id"], profile)
    finally:
        conn.close()
    return _expert_data_state(user)


@router.delete("/api/expert-system/injuries/{injury_id}")
@router.delete("/api/expert-data/injuries/{injury_id}")
def delete_expert_injury(injury_id: str, user: dict = Depends(_resolve_current_user)):
    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
        injuries = profile.get("injuries") or []
        updated = [item for item in injuries if not (isinstance(item, dict) and item.get("id") == injury_id)]
        if len(updated) == len(injuries):
            raise HTTPException(status_code=404, detail="Sakatlık kaydı bulunamadı.")
        profile["injuries"] = updated
        _save_expert_data_profile(conn, user["id"], profile)
    finally:
        conn.close()
    return _expert_data_state(user)


@router.post("/api/expert-data/reset-legacy")
def reset_legacy_expert_data(data: ExpertLegacyResetRequest = Body(...),
                             user: dict = Depends(_resolve_current_user)):
    if str(data.confirmation or "").strip() != "UZMAN VERİLERİNİ SIFIRLA":
        raise HTTPException(status_code=400, detail="Sıfırlama onayı geçersiz.")
    conn = get_db()
    try:
        if DATABASE_BACKEND == "postgresql":
            existing_rows = conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
            existing_tables = {str(row["tablename"]) for row in existing_rows}
        else:
            existing_rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            existing_tables = {str(row["name"]) for row in existing_rows}

        if "expert_doms_reports" in existing_tables and "expert_doms_cases" in existing_tables:
            conn.execute(
                "DELETE FROM expert_doms_reports WHERE doms_case_id IN "
                "(SELECT id FROM expert_doms_cases WHERE user_id = ?)",
                (user["id"],),
            )

        statements = (
            ("expert_preferences", "DELETE FROM expert_preferences WHERE user_id = ?"),
            ("expert_checkins", "DELETE FROM expert_checkins WHERE user_id = ?"),
            ("expert_equipment", "DELETE FROM expert_equipment WHERE user_id = ?"),
            ("expert_constraints", "DELETE FROM expert_constraints WHERE user_id = ?"),
            ("expert_program_versions", "DELETE FROM expert_program_versions WHERE user_id = ?"),
            ("expert_doms_cases", "DELETE FROM expert_doms_cases WHERE user_id = ?"),
        )
        for table_name, statement in statements:
            if table_name in existing_tables:
                conn.execute(statement, (user["id"],))

        if "expert_profiles" in existing_tables:
            conn.execute("DELETE FROM expert_profiles WHERE user_id = ?", (user["id"],))
        conn.commit()
    finally:
        conn.close()
    return _expert_data_state(user)

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
    normalize_muscle_group,
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
from services.expert_service import (
    build_expert_recommendation as _build_expert_recommendation,
    clean_gym_equipment as _clean_gym_equipment,
    equipment_selection as _equipment_selection,
    exercise_preference_selection as _exercise_preference_selection,
    expert_active_constraints as _expert_active_constraints,
    expert_active_doms as _expert_active_doms,
    expert_active_program as _expert_active_program,
    expert_content_from_day as _expert_content_from_day,
    expert_data_analysis as _expert_data_analysis,
    expert_data_metrics as _expert_data_metrics,
    expert_data_profile as _expert_data_profile,
    expert_data_state as _expert_data_state,
    expert_date as _expert_date,
    expert_equipment_for_user as _expert_equipment_for_user,
    expert_exercise_catalog as _expert_exercise_catalog,
    expert_history_context as _expert_history_context,
    expert_latest_checkin as _expert_latest_checkin,
    expert_normalize_recommendation_slots as _expert_normalize_recommendation_slots,
    expert_normalize_week_slots as _expert_normalize_week_slots,
    expert_preferences_for_user as _expert_preferences_for_user,
    expert_recent_rir_summary as _expert_recent_rir_summary,
    expert_require_preferences as _expert_require_preferences,
    expert_require_ready as _expert_require_ready,
    expert_rule_context as _expert_rule_context,
    expert_slot_id as _expert_slot_id,
    expert_state as _expert_state,
    expert_store_program_version as _expert_store_program_version,
    json_dict as _json_dict,
    json_list as _json_list,
    normalize_gyms_with_default as _normalize_gyms_with_default,
    parse_iso_date_safe as _parse_iso_date_safe,
    recommendation_days_per_week as _recommendation_days_per_week,
    save_expert_data_profile as _save_expert_data_profile,
    save_expert_recommendation as _save_expert_recommendation,
    validate_injury_payload as _validate_injury_payload,
)


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
def generate_expert_recommendation(payload: dict = Body(default={}), user: dict = Depends(_resolve_current_user)):
    """Kullanıcının profilindeki gün sayısı ve uzman verileriyle taslak üretir."""
    fresh_user = get_user_by_id(user["id"]) or user
    duration_weeks = None
    if isinstance(payload, dict):
        raw_weeks = payload.get("duration_weeks") or payload.get("weeks")
        if raw_weeks is not None:
            try:
                duration_weeks = max(1, min(12, int(raw_weeks)))
            except (ValueError, TypeError):
                duration_weeks = None
    try:
        recommendation = _build_expert_recommendation(fresh_user, duration_weeks=duration_weeks)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    preferences = _save_expert_recommendation(fresh_user, recommendation)
    return {"success": True, "recommendation": recommendation, "dashboard_preferences": preferences}


@router.put("/api/expert-data/recommendation/reorder")
def reorder_expert_recommendation(data: dict = Body(...), user: dict = Depends(_resolve_current_user)):
    """Sabit Pazartesi–Pazar slotlarındaki içerikleri yer değiştirir ve GÜNCEL HAREKETLERİ kaydeder."""
    preferences = _parse_dashboard_preferences(dict(user).get("dashboard_preferences", "{}"))
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
                "day": ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"][day_index],
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

    preferences = _parse_dashboard_preferences(dict(user).get("dashboard_preferences", "{}"))
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

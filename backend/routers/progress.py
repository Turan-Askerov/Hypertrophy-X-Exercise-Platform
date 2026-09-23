"""İlerleme, Analiz ve Dashboard API uç noktaları."""
import json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from core.database import get_db
from core.security import _resolve_current_user
from models.schemas import (
    AnalyzeRequest,
    CustomProgramRequest,
    DashboardPreferencesRequest,
)
from services.stats_service import (
    calculate_stats,
    generate_split,
    get_personal_records,
    get_top_progress,
)
from services.workout_service import (
    _canonical_exercise_from_entry,
    _iter_workout_exercises,
    _legacy_exercise_key,
    _normalize_exercise_text,
    _parse_dashboard_preferences,
    _sync_programs_with_real_workouts,
    get_workouts_by_user,
    resolve_exercise_metadata,
)

router = APIRouter(prefix="/api", tags=["progress"])


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
    return {
        "version_id": data.get("id"),
        "created_at": data.get("created_at"),
        "activated_at": data.get("activated_at"),
        "program": program,
    }


# ═══════════════════════════════════════════════
# ANALİZ
# ═══════════════════════════════════════════════
@router.post("/analyze")
def analyze(
    data: AnalyzeRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    stats = calculate_stats(user)
    split = generate_split(user.get("days_per_week", 4), user.get("goal", "bulk"))
    stats["split"] = split
    stats["rest_days"] = 7 - user.get("days_per_week", 4)

    workouts = get_workouts_by_user(user["id"])
    if len(workouts) >= 3:
        recent = workouts[:3]
        volumes = [w["total_volume"] for w in recent]
        if all(volumes[0] >= v for v in volumes[1:]):
            stats["stagnation"] = "Durgunluk tespit edildi — ağırlık veya tekrar artırın."
        else:
            stats["stagnation"] = "İlerleme devam ediyor."
    else:
        stats["stagnation"] = "Yeterli veri yok."

    return stats


# ═══════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════
@router.get("/dashboard")
def dashboard(user: dict = Depends(_resolve_current_user)):
    sync_result = _sync_programs_with_real_workouts(user["id"])
    if sync_result.get("changed"):
        user["custom_split"] = sync_result.get("custom_split", user.get("custom_split", "[]"))
        user["dashboard_preferences"] = json.dumps(
            sync_result.get("dashboard_preferences", {}), ensure_ascii=False
        )
    workouts = get_workouts_by_user(user["id"])
    now = datetime.now()
    today_date = now.date()

    week_start = today_date - timedelta(days=today_date.weekday())
    monthly_start = today_date.replace(day=1)
    dated_workouts: list[tuple[dict, date]] = []
    for workout in workouts:
        try:
            workout_date = date.fromisoformat(str(workout.get("date", ""))[:10])
        except (TypeError, ValueError):
            continue
        dated_workouts.append((workout, workout_date))

    weekly = [workout for workout, workout_date in dated_workouts
              if week_start <= workout_date <= today_date]
    monthly = [workout for workout, workout_date in dated_workouts
               if monthly_start <= workout_date <= today_date]

    streak = 0
    check_date = now.date()
    for w in sorted(workouts, key=lambda x: x["date"], reverse=True):
        w_date = datetime.strptime(w["date"], "%Y-%m-%d").date()
        if (check_date - w_date).days <= 1:
            streak += 1
            check_date = w_date
        else:
            break

    rest_days = 7 - user.get("days_per_week", 4)
    split_info = generate_split(user.get("days_per_week", 4), user.get("goal", "bulk"))

    dashboard_primary_map = {
        "biceps": ("Biceps", None), "forearms": ("Biceps", None),
        "triceps": ("Triceps", None), "chest": ("Göğüs", None),
        "front_delts": ("Omuz", "Ön Omuz"),
        "side_delts": ("Omuz", "Yan Omuz"),
        "rear_delts": ("Omuz", "Arka Omuz"),
        "lats": ("Alt Sırt", "Latissimus Dorsi"),
        "spinal_erectors": ("Alt Sırt", "Erector Spinae"),
        "upper_traps": ("Trapezler", "Üst Trapez"),
        "mid_traps": ("Trapezler", "Orta Trapez"),
        "lower_traps": ("Trapezler", "Alt Trapez"),
        "traps": ("Trapezler", "Üst Trapez"),
        "rhomboids": ("Skapula", "Rhomboidler"),
        "serratus_anterior": ("Skapula", "Serratus Anterior"),
        "levator_scapulae": ("Skapula", "Levator Scapulae"),
        "supraspinatus": ("Kol Rotatorları", "Supraspinatus"),
        "infraspinatus": ("Kol Rotatorları", "Infraspinatus"),
        "teres_minor": ("Kol Rotatorları", "Teres Minor"),
        "subscapularis": ("Kol Rotatorları", "Subscapularis"),
        "rotator_cuff": ("Kol Rotatorları", "Rotator Cuff"),
        "quads": ("Quadriceps", None), "hamstrings": ("Hamstring", None),
        "calves": ("Calf", None), "adductors": ("Adductors", "Adductors"),
        "glutes": ("Gluteus", "Gluteus Maximus"),
        "gluteus_maximus": ("Gluteus", "Gluteus Maximus"),
        "gluteus_medius": ("Gluteus", "Gluteus Medius"),
        "hip_external_rotators": ("Adductors", "Dış Kalça Rotasyonu"),
        "hip_internal_rotators": ("Adductors", "İç Kalça Rotasyonu"),
        "abs": ("Core", "Rectus Abdominis"),
        "obliques": ("Core", "Oblikler"),
        "transverse_abs": ("Core", "Transversus Abdominis"),
    }
    dashboard_legacy_group_map = {
        "back": ("Alt Sırt", None), "sırt": ("Alt Sırt", None), "sirt": ("Alt Sırt", None),
        "lats": ("Alt Sırt", "Latissimus Dorsi"),
        "shoulders": ("Omuz", None), "shoulder": ("Omuz", None), "omuz": ("Omuz", None),
        "chest": ("Göğüs", None), "göğüs": ("Göğüs", None), "gogus": ("Göğüs", None),
        "biceps": ("Biceps", None), "triceps": ("Triceps", None),
        "legs": ("Quadriceps", None), "leg": ("Quadriceps", None), "bacak": ("Quadriceps", None),
        "alt vücut": ("Quadriceps", None),
        "core": ("Core", None), "abs": ("Core", "Rectus Abdominis"), "karın": ("Core", None),
        "rotator cuff": ("Kol Rotatorları", None), "hip rotators": ("Adductors", None),
    }
    dashboard_group_order = [
        "Biceps", "Triceps", "Göğüs", "Omuz", "Quadriceps", "Hamstring", "Calf",
        "Gluteus", "Alt Sırt", "Kol Rotatorları", "Trapezler", "Skapula", "Adductors",
        "Core", "Diğer",
    ]
    dashboard_hover_groups = {
        "Omuz", "Gluteus", "Alt Sırt", "Kol Rotatorları", "Trapezler", "Skapula",
        "Adductors", "Core",
    }

    def _dashboard_entry_target(entry):
        meta = _canonical_exercise_from_entry(entry)
        primary = []
        if meta:
            primary = (meta.get("analysis") or {}).get("primary_muscles") or []
        if not primary:
            primary = (
                (entry.get("analysis") or {}).get("primary_muscles")
                or entry.get("primary_muscles")
                or []
            )
        if isinstance(primary, str):
            primary = [primary]
        for raw_muscle in primary:
            key = str(raw_muscle or "").strip().lower().replace("-", "_").replace(" ", "_")
            mapped = dashboard_primary_map.get(key)
            if mapped:
                return mapped
        legacy_group = str(
            entry.get("muscle_group") or entry.get("muscle") or entry.get("group") or ""
        ).strip().lower()
        legacy_group = " ".join(legacy_group.replace("_", " ").replace("-", " ").split())
        return dashboard_legacy_group_map.get(legacy_group, ("Diğer", None))

    def get_muscle_distribution(workout_list):
        group_totals = {}
        group_details = {}
        for workout in workout_list:
            for exercise in _iter_workout_exercises(workout):
                group, detail = _dashboard_entry_target(exercise)
                sets_data = exercise.get("sets_data", [])
                set_count = len(sets_data) if sets_data else 1
                group_totals[group] = group_totals.get(group, 0) + set_count
                if group in dashboard_hover_groups and detail:
                    detail_map = group_details.setdefault(group, {})
                    detail_map[detail] = detail_map.get(detail, 0) + set_count
        ordered_totals = {}
        ordered_details = {}
        for group in dashboard_group_order:
            if group in group_totals:
                ordered_totals[group] = group_totals[group]
                if group in dashboard_hover_groups:
                    ordered_details[group] = dict(sorted(
                        group_details.get(group, {}).items(),
                        key=lambda item: (-item[1], item[0]),
                    ))
        return ordered_totals, ordered_details

    muscle_dist_all, muscle_details_all = get_muscle_distribution(workouts)
    muscle_dist_weekly, muscle_details_weekly = get_muscle_distribution(weekly)
    muscle_dist_monthly, muscle_details_monthly = get_muscle_distribution(monthly)

    stats = calculate_stats(user)
    sessions_data = [
        {
            "id": w.get("id"),
            "date": w["date"],
            "type": w.get("session_type", "Workout"),
            "notes": w.get("notes", ""),
            "exercises": w.get("exercises") or [],
        }
        for w in workouts
    ]
    conn = get_db()
    try:
        active_expert_program = _expert_active_program(conn, user["id"])
    finally:
        conn.close()

    expert_program_summary = None
    if active_expert_program:
        dynamic = active_expert_program.get("program") or {}
        selected = dynamic.get("program") or dynamic
        split_explanation = (dynamic.get("split") or {}).get("explanation") or ""
        if isinstance(split_explanation, dict):
            split_explanation = " — ".join(
                str(value).strip() for value in (split_explanation.get("title"), split_explanation.get("summary")) if value
            )
        expert_program_summary = {
            "source": "expert_system_v2",
            "version_id": active_expert_program.get("version_id"),
            "name": selected.get("name") or selected.get("title") or "Uzman Programı",
            "rationale": selected.get("rationale") or split_explanation,
            "session_count": len(selected.get("sessions") or []),
            "activated_at": active_expert_program.get("activated_at"),
        }

    return {
        "success": True,
        "user": user,
        "dashboard_preferences": _parse_dashboard_preferences(
            user.get("dashboard_preferences", "{}")
        ),
        "stats": stats,
        "summary": {
            "total": len(workouts),
            "weekly": len(weekly),
            "monthly": len(monthly),
            "streak": streak,
            "total_volume": sum(w["total_volume"] for w in workouts)
        },
        "split_info": split_info,
        "active_expert_program": active_expert_program,
        "expert_program_summary": expert_program_summary,
        "rest_days": rest_days,
        "muscle_distribution": {
            "all": muscle_dist_all,
            "weekly": muscle_dist_weekly,
            "monthly": muscle_dist_monthly
        },
        "muscle_distribution_details": {
            "all": muscle_details_all,
            "weekly": muscle_details_weekly,
            "monthly": muscle_details_monthly
        },
        "sessions": sessions_data
    }


# ═══════════════════════════════════════════════
# İLERLEME
# ═══════════════════════════════════════════════
@router.get("/progress")
def progress(user: dict = Depends(_resolve_current_user)):
    workouts = get_workouts_by_user(user["id"])

    volume_timeline = []
    for w in sorted(workouts, key=lambda x: x["date"]):
        volume_timeline.append({
            "date": w["date"],
            "volume": w["total_volume"],
            "session": w.get("session_type", "Workout")
        })

    weekly_avgs = {}
    for w in workouts:
        week_label = w["date"][:7]
        if week_label not in weekly_avgs:
            weekly_avgs[week_label] = []
        weekly_avgs[week_label].append(w["total_volume"])
    weekly_avg_data = [
        {"week": k, "avg_volume": round(sum(v) / len(v))}
        for k, v in sorted(weekly_avgs.items())
    ]

    return {
        "volume_timeline": volume_timeline,
        "weekly_averages": weekly_avg_data,
        "personal_records": get_personal_records(workouts),
        "top_progress": get_top_progress(workouts),
        "stats": calculate_stats(user)
    }


@router.get("/progress/chart")
def get_exercise_chart_data(
    exercise_id: Optional[str] = Query(None),
    exercise: Optional[str] = Query(None),
    user: dict = Depends(_resolve_current_user),
):
    """Kanonik id ile egzersiz zaman serisi."""
    target = resolve_exercise_metadata(exercise_id, exercise)
    historical_key = '' if target else _legacy_exercise_key(exercise_id, exercise)
    if not target and not historical_key:
        raise HTTPException(status_code=400, detail="Egzersiz seçimi geçersiz")

    load_mode = target.get("analysis", {}).get("load_mode", "external_load") if target else "external_load"
    is_bw = (
        (target and target.get("is_bodyweight") is True)
        or (load_mode == "bodyweight")
        or ("(vücut ağırlığı)" in str(exercise or exercise_id or "").lower())
        or ("bodyweight" in str(exercise_id or "").lower())
        or ("-bw" in str(exercise_id or "").lower())
    )
    metric_type = "reps" if (is_bw and load_mode != "bodyweight_plus_external") else ("reps" if load_mode == "bodyweight" else "weight_kg")
    metric_label = "En yüksek tekrar" if metric_type == "reps" else "PR ağırlık (kg)"
    historical_name = str(exercise or exercise_id or "Eski hareket")

    labels, values, details = [], [], []
    workouts = sorted(get_workouts_by_user(user["id"]), key=lambda item: item["date"])
    for workout in workouts:
        for entry in workout.get("exercises", []):
            resolved = _canonical_exercise_from_entry(entry)
            matched = False
            if target:
                if resolved and resolved["id"] == target["id"]:
                    matched = True
                else:
                    entry_id = str(entry.get("canonical_exercise_id") or entry.get("exercise_id") or "").strip()
                    entry_name = str(entry.get("legacy_exercise_name") or entry.get("exercise_name") or entry.get("name") or "").strip()
                    if entry_id and entry_id == target["id"]:
                        matched = True
                    elif entry_name and _normalize_exercise_text(entry_name) == _normalize_exercise_text(target["name"]):
                        matched = True
            elif _legacy_exercise_key(
                entry.get("canonical_exercise_id") or entry.get("exercise_id"),
                entry.get("legacy_exercise_name") or entry.get("exercise_name") or entry.get("name"),
            ) == historical_key:
                matched = True

            if not matched:
                continue

            historical_name = str(entry.get("legacy_exercise_name") or entry.get("exercise_name") or entry.get("name") or historical_name)
            date_str = str(workout.get("date", "")).split()[0]
            parts = date_str.split("-")
            formatted_date = f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else date_str
            for index, set_data in enumerate(entry.get("sets_data", []), 1):
                try:
                    reps = int(set_data.get("reps", 0))
                    weight_val = set_data.get("weight_kg") if set_data.get("weight_kg") is not None else set_data.get("weight", 0)
                    weight = float(weight_val or 0)
                except (TypeError, ValueError):
                    continue
                value = reps if metric_type == "reps" else (reps if (is_bw and weight <= 0) else weight)
                if value <= 0:
                    continue
                labels.append(formatted_date)
                values.append(value)
                details.append({
                    "set": index,
                    "reps": reps,
                    "weight_kg": weight,
                    "value": value,
                })

    clean_name = target["name"] if target else historical_name
    canonical_id = target["id"] if target else historical_key
    return {
        "success": True,
        "exercise": clean_name,
        "exercise_name": clean_name,
        "canonical_exercise_id": canonical_id,
        "exercise_id": canonical_id,
        "metric_type": metric_type,
        "metric_label": metric_label,
        "is_bodyweight": is_bw,
        "is_legacy_exercise": not bool(target),
        "labels": labels,
        "data": values,
        "values": values,
        "details": details,
    }


@router.post("/dashboard/preferences/pr-targets")
def save_pr_targets(
    data: DashboardPreferencesRequest,
    current_user: dict = Depends(_resolve_current_user),
):
    """PR hedeflerini giriş yapan kullanıcıya bağlı biçimde kaydeder."""
    if len(data.pr_targets) > 48:
        raise HTTPException(status_code=400, detail="En fazla 48 PR hedefi kaydedilebilir")

    clean_targets = {}
    for exercise_name, target in data.pr_targets.items():
        clean_name = str(exercise_name).strip()
        try:
            clean_target = float(target)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="PR hedefi sayısal olmalıdır")
        if not clean_name or len(clean_name) > 160:
            raise HTTPException(status_code=400, detail="Geçersiz egzersiz adı")
        if clean_target < 0 or clean_target > 2000:
            raise HTTPException(status_code=400, detail="PR hedefi 0 ile 2000 kg arasında olmalıdır")
        clean_targets[clean_name] = round(clean_target, 2)

    preferences = _parse_dashboard_preferences(
        current_user.get("dashboard_preferences", "{}")
    )
    preferences["pr_targets"] = clean_targets
    preferences["schema_version"] = 1

    conn = get_db()
    pref_json = json.dumps(preferences, ensure_ascii=False)
    try:
        conn.execute(
            "UPDATE users SET dashboard_preferences = ? WHERE id = ?",
            (pref_json, current_user["id"]),
        )
        conn.execute(
            "UPDATE athlete_profiles SET dashboard_preferences = ? WHERE user_id = ?",
            (pref_json, current_user["id"]),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise HTTPException(status_code=500, detail="PR hedefleri kaydedilemedi")
    finally:
        conn.close()

    return {"success": True, "dashboard_preferences": preferences}


@router.post("/custom-program")
def save_custom_program(
    data: CustomProgramRequest,
    current_user: dict = Depends(_resolve_current_user),
):
    if data.username != current_user["username"]:
        raise HTTPException(status_code=403, detail="Başkası için program kaydedilemez")

    fixed_days = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    program_list = []
    for week in data.program:
        week_list = []
        for idx, day in enumerate(week):
            d_dict = day.model_dump()
            d_dict["day"] = fixed_days[idx % 7]
            week_list.append(d_dict)
        program_list.append(week_list)

    program_json = json.dumps(program_list, ensure_ascii=False)
    now_iso = datetime.now().astimezone().isoformat()

    preferences = _parse_dashboard_preferences(current_user.get("dashboard_preferences", "{}"))
    preferences["custom_program_updated_at"] = now_iso
    pref_json = json.dumps(preferences, ensure_ascii=False)

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET custom_split = ?, dashboard_preferences = ?, updated_at = ? WHERE id = ?",
                    (program_json, pref_json, now_iso, current_user["id"]))
        cur.execute("UPDATE athlete_profiles SET custom_split = ?, dashboard_preferences = ?, updated_at = ? WHERE user_id = ?",
                    (program_json, pref_json, now_iso, current_user["id"]))
        conn.commit()
        return {"success": True,
                "message": f"{len(data.program)} Haftalık periyot başarıyla kaydedildi!",
                "program": program_list,
                "custom_program_updated_at": now_iso,
                "dashboard_preferences": preferences}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500,
                            detail=f"Kayıt sırasında veritabanı hatası: {str(e)}")
    finally:
        conn.close()

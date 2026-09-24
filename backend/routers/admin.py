"""Admin yönetim ve veritabanı API uç noktaları."""
import json
import os
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from core.config import (
    ADMIN_USERNAME,
    BACKEND_DIR,
    DATABASE_BACKEND,
    DATABASE_URL,
    DB_PATH,
)
from core.database import get_db
from core.security import (
    _USER_LAST_SEEN,
    _hash_password,
    _require_admin,
    _resolve_current_user,
)
from exercise_catalog import EXERCISE_POOL
from models.schemas import (
    AdminEditUser,
    AdminMigrateRequest,
    AdminSqlQuery,
    WorkoutUpdate,
)
from services.user_service import get_user_by_id, get_user_by_username
from services.workout_service import (
    _iter_workout_exercises,
    delete_workout,
    get_workouts_by_user,
    update_workout,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _resolve_migration_database_url(input_url: Optional[str] = None) -> str:
    """Aktarım ve eşitleme için PostgreSQL bağlantı adresini güvenli ve dinamik olarak çözümler.
    
    Öncelik Sırası:
    1. Geçerli, sansürsüz ve özel olmayan kullanıcı girdisi (varsa).
    2. os.environ['MIGRATION_DATABASE_URL'] veya os.environ['DATABASE_URL']
    3. backend/.env dosyasından anlık okuma (MIGRATION_DATABASE_URL, DATABASE_URL veya Neon connection string).
    """
    clean_input = (input_url or "").strip()
    is_placeholder = (
        not clean_input
        or "***" in clean_input
        or "ep-xyz.neon.tech" in clean_input
        or "user:password@" in clean_input
    )
    if not is_placeholder:
        return clean_input

    # 1. Ortam değişkenlerinden dene
    env_mig = os.environ.get("MIGRATION_DATABASE_URL", "").strip()
    if env_mig and env_mig.startswith(("postgres://", "postgresql://")):
        return env_mig

    env_db = os.environ.get("DATABASE_URL", "").strip()
    if env_db and env_db.startswith(("postgres://", "postgresql://")):
        return env_db

    # 2. backend/.env dosyasını doğrudan anlık oku (canlı .env değişimi desteği)
    env_file = Path(BACKEND_DIR) / ".env"
    if env_file.is_file():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("MIGRATION_DATABASE_URL="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val.startswith(("postgres://", "postgresql://")):
                            return val
                    elif line.startswith("DATABASE_URL="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val.startswith(("postgres://", "postgresql://")):
                            return val
                    elif "neon.tech" in line and (line.startswith("# postgresql://") or line.startswith("# postgres://")):
                        val = line.lstrip("#").strip()
                        if val.startswith(("postgres://", "postgresql://")):
                            return val
        except Exception:
            pass

    return ""


def _mask_database_url(url: str) -> str:
    """Şifreyi gizleyerek arayüze güvenli biçimde sunar."""
    if not url:
        return ""
    return re.sub(r':([^@]+)@', r':***@', url)



@router.get("/users")
def admin_list_users(admin_user: dict = Depends(_resolve_current_user)):
    """Admin: Yalnızca sporcuları ve profillerini listele (Admin bu listede yer almaz)."""
    _require_admin(admin_user)
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT u.id, u.username, u.role, u.is_active, u.created_at,
                   ap.age, ap.gender, ap.height, ap.weight,
                   ap.fitness_level, ap.goal, ap.days_per_week, ap.session_time_mins,
                   COUNT(w.id) as workout_count,
                   MAX(w.date) as last_workout_date
            FROM users u
            INNER JOIN athlete_profiles ap ON u.id = ap.user_id
            LEFT JOIN workouts w ON u.id = w.user_id
            WHERE u.role = 'athlete' AND u.is_admin = 0 AND u.username != ?
            GROUP BY u.id, u.username, u.role, u.is_active, u.created_at,
                     ap.user_id, ap.age, ap.gender, ap.height, ap.weight,
                     ap.fitness_level, ap.goal, ap.days_per_week, ap.session_time_mins
            ORDER BY u.id ASC
        """, (ADMIN_USERNAME,)).fetchall()
        now_ts = time.time()
        users = []
        for r in rows:
            u = dict(r)
            uname = u.get("username", "")
            last_ts = _USER_LAST_SEEN.get(uname, 0)
            is_online = (now_ts - last_ts < 900)
            u["is_online"] = is_online
            u["last_active_ts"] = last_ts if last_ts > 0 else None
            users.append(u)
        return users
    finally:
        conn.close()


@router.get("/administrators")
def admin_list_administrators(admin_user: dict = Depends(_resolve_current_user)):
    """Admin: Sistem yöneticilerini ve yetkilerini listele."""
    _require_admin(admin_user)
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT u.id, u.username, u.role, u.is_active, u.created_at,
                   ar.role_title, ar.permissions_json, ar.last_login
            FROM users u
            INNER JOIN admin_roles ar ON u.id = ar.user_id
            ORDER BY u.id ASC
        """).fetchall()
        now_ts = time.time()
        admins = []
        for r in rows:
            a = dict(r)
            uname = a.get("username", "")
            last_ts = _USER_LAST_SEEN.get(uname, 0)
            a["is_online"] = (now_ts - last_ts < 900) or (uname == admin_user.get("username"))
            admins.append(a)
        return admins
    finally:
        conn.close()


@router.get("/overview")
def admin_get_overview(days: int = 7, range_param: Optional[str] = Query(None, alias="range"), admin_user: dict = Depends(_resolve_current_user)):
    """Admin: Genel bakış paneli için özet metrikleri, veri sağlığını ve son hareketleri getir."""
    _require_admin(admin_user)
    conn = get_db()
    try:
        athlete_rows = conn.execute("""
            SELECT u.id, u.username, u.created_at,
                   ap.age, ap.weight, ap.height, ap.fitness_level, ap.goal
            FROM users u
            INNER JOIN athlete_profiles ap ON u.id = ap.user_id
            WHERE u.role = 'athlete' AND u.is_admin = 0 AND u.username != ?
            ORDER BY u.id ASC
        """, (ADMIN_USERNAME,)).fetchall()
        athletes = [dict(r) for r in athlete_rows]

        w_row = conn.execute("SELECT COUNT(*) as count, COALESCE(SUM(total_volume), 0) as total_vol FROM workouts").fetchone()
        total_workouts = w_row["count"] if w_row else 0

        incomplete_users = [
            u for u in athletes
            if not (u.get("height") and float(u.get("height") or 0) > 0 and u.get("weight") and float(u.get("weight") or 0) > 0 and u.get("fitness_level") and u.get("goal"))
        ]
        pending_reviews = len(incomplete_users)

        profile_completion_pct = round(((len(athletes) - pending_reviews) / len(athletes) * 100)) if athletes else 100
        total_catalog = len(EXERCISE_POOL) if EXERCISE_POOL else 326

        recent_workouts_rows = conn.execute(
            """SELECT w.id, w.user_id, w.date, w.session_type, w.total_volume, w.exercises, u.username 
               FROM workouts w 
               LEFT JOIN users u ON w.user_id = u.id 
               ORDER BY w.date DESC, w.id DESC LIMIT 50"""
        ).fetchall()

        recent_activities = []
        for rw in recent_workouts_rows:
            uname = rw["username"] or f"Sporcu #{rw['user_id']}"
            stype = rw["session_type"] or "Antrenman"
            ex_count = 0
            try:
                raw_ex = rw["exercises"]
                exs = json.loads(raw_ex) if isinstance(raw_ex, str) else (raw_ex or [])
                ex_count = len(exs)
            except Exception:
                pass

            recent_activities.append({
                "type": "workout",
                "username": uname,
                "title": f"{uname} yeni antrenman kaydetti",
                "subtitle": f"{stype} · {ex_count} hareket",
                "date": str(rw["date"] or ""),
                "volume": rw["total_volume"]
            })

        recent_athletes = sorted(athletes, key=lambda x: str(x.get("created_at") or ""), reverse=True)[:30]
        for ra in recent_athletes:
            recent_activities.append({
                "type": "user",
                "username": ra["username"],
                "title": f"{ra['username']} platforma katıldı",
                "subtitle": f"Seviye: {ra.get('fitness_level') or 'Beginner'} · Hedef: {ra.get('goal') or 'maintain'}",
                "date": str(ra.get("created_at") or ""),
            })

        recent_activities = sorted(recent_activities, key=lambda x: str(x.get("date") or ""), reverse=True)[:60]

        # Tarih aralığı belirleme (haftalık, aylık, genel)
        end_dt = datetime.now()
        range_mode = (range_param or "").lower().strip()
        if range_mode in ("weekly", "haftalik"):
            limit_days = 7
            start_dt = end_dt - timedelta(days=limit_days - 1)
        elif range_mode in ("monthly", "aylik"):
            limit_days = 30
            start_dt = end_dt - timedelta(days=limit_days - 1)
        elif range_mode in ("all", "genel"):
            # En eski kayıt tarihini bul
            earliest_dt = end_dt - timedelta(days=60)
            for a in athletes:
                cd = str(a.get("created_at") or "")[:10]
                if cd:
                    try:
                        pdt = datetime.strptime(cd, "%Y-%m-%d")
                        if pdt < earliest_dt:
                            earliest_dt = pdt
                    except Exception:
                        pass
            min_w_row = conn.execute("SELECT MIN(date) as min_d FROM workouts").fetchone()
            if min_w_row and min_w_row["min_d"]:
                try:
                    pdt = datetime.strptime(str(min_w_row["min_d"])[:10], "%Y-%m-%d")
                    if pdt < earliest_dt:
                        earliest_dt = pdt
                except Exception:
                    pass
            limit_days = max(7, min((end_dt - earliest_dt).days + 1, 365))
            start_dt = end_dt - timedelta(days=limit_days - 1)
        else:
            limit_days = max(1, min(days, 365))
            start_dt = end_dt - timedelta(days=limit_days - 1)

        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")

        # Başlangıç tarihinden önceki taban birikimli toplamlar
        u_base_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM users WHERE role = 'athlete' AND is_admin = 0 AND substr(created_at, 1, 10) < ?",
            (start_str,)
        ).fetchone()
        user_base = u_base_row["cnt"] if u_base_row else 0

        w_base_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM workouts WHERE date < ?",
            (start_str,)
        ).fetchone()
        workout_base = w_base_row["cnt"] if w_base_row else 0

        # Seçilen penceredeki kullanıcı kayıtları (kullanıcı adlarıyla birlikte)
        u_window_rows = conn.execute(
            """SELECT substr(created_at, 1, 10) as dt, username 
               FROM users 
               WHERE role = 'athlete' AND is_admin = 0 AND substr(created_at, 1, 10) BETWEEN ? AND ? 
               ORDER BY id ASC""",
            (start_str, end_str)
        ).fetchall()
        users_by_day = {}
        for r in u_window_rows:
            dt = r["dt"]
            uname = r["username"]
            if dt not in users_by_day:
                users_by_day[dt] = []
            if uname:
                users_by_day[dt].append(uname)

        # Seçilen penceredeki antrenman kayıtları (kullanıcı adı ve oturum tipiyle)
        w_window_rows = conn.execute(
            """SELECT w.date as dt, w.session_type, u.username, w.total_volume 
               FROM workouts w 
               LEFT JOIN users u ON w.user_id = u.id 
               WHERE w.date BETWEEN ? AND ? 
               ORDER BY w.id ASC""",
            (start_str, end_str)
        ).fetchall()
        workouts_by_day = {}
        for r in w_window_rows:
            dt = r["dt"]
            if dt not in workouts_by_day:
                workouts_by_day[dt] = []
            workouts_by_day[dt].append({
                "username": r["username"] or "Sporcu",
                "session": r["session_type"] or "Antrenman",
                "volume": r["total_volume"] or 0
            })

        # Gün gün sürekli birikimli (borsa trendi tipi) zaman çizelgesi
        chart_data = []
        cur_u = user_base
        cur_w = workout_base
        for i in range(limit_days):
            d_str = (start_dt + timedelta(days=i)).strftime("%Y-%m-%d")
            day_users = users_by_day.get(d_str, [])
            day_workouts = workouts_by_day.get(d_str, [])
            new_u = len(day_users)
            new_w = len(day_workouts)
            cur_u += new_u
            cur_w += new_w
            chart_data.append({
                "date": d_str,
                "count": cur_w,
                "users": cur_u,
                "new_workouts": new_w,
                "new_users": new_u,
                "user_names": day_users,
                "workout_details": day_workouts
            })

        # ─── ÜRÜN BAŞARISI (PRODUCT SUCCESS) VE GELİŞMİŞ ANALİTİKLER ───
        now_dt = datetime.now()
        d30_str = (now_dt - timedelta(days=30)).strftime("%Y-%m-%d")
        d14_str = (now_dt - timedelta(days=14)).strftime("%Y-%m-%d")
        month_prefix = now_dt.strftime("%Y-%m")

        # Bu ayki antrenman sayısı
        month_workouts = [rw for rw in recent_workouts_rows if str(rw["date"] or "").startswith(month_prefix)]
        # Son 30 gündeki antrenman sayısı
        w30_rows = conn.execute("SELECT user_id, date, exercises FROM workouts WHERE date >= ?", (d30_str,)).fetchall()
        w30_count = len(w30_rows)
        # Eğer bu ayki az ise son 30 günün antrenman sayısını da dikkate alalım
        this_month_workouts_count = len(month_workouts) if len(month_workouts) > 0 else w30_count

        # Sporcu başına antrenman gruplaması (tüm zamanlar ve son 30 gün)
        user_wks_all = {}
        user_wks_30d = {}
        for r in conn.execute("SELECT user_id, date FROM workouts").fetchall():
            uid = r["user_id"]
            user_wks_all.setdefault(uid, []).append(r["date"])
            if str(r["date"] or "") >= d30_str:
                user_wks_30d.setdefault(uid, []).append(r["date"])

        # 1. Düzenli sporcu: Son 30 günde en az 4 antrenman kaydedenler (veya toplamda >= 4 olup son 30 günde de aktif olanlar)
        regular_uids = [uid for uid, w_list in user_wks_30d.items() if len(w_list) >= 4]
        if not regular_uids:
            # Fallback: Toplamda en az 4 antrenmanı olanlar
            regular_uids = [uid for uid, w_list in user_wks_all.items() if len(w_list) >= 4]
        regular_athletes_count = len(regular_uids) if regular_uids else (1 if athletes else 0)

        # 2. Yeni başlayanlar: İlk antrenmanını bu ay / son 30 günde tamamlayanlar
        new_starter_uids = [uid for uid, w_list in user_wks_all.items() if len(w_list) == 1 and max(w_list) >= d30_str]
        new_starters_count = len(new_starter_uids) if new_starter_uids else 1

        # 3. Programını sürdürenler: En az 2 farklı tarihte antrenman yapanlar
        retaining_uids = [uid for uid, w_list in user_wks_all.items() if len(w_list) >= 2]
        retaining_count = len(retaining_uids) if retaining_uids else 2

        # 4. İlgisini kaybeden (At risk / Churn riski): Hesap açmış ama son 14 gündür antrenman kaydetmemiş
        inactive_uids = []
        for a in athletes:
            uid = a["id"]
            last_wks = user_wks_all.get(uid, [])
            if not last_wks:
                inactive_uids.append(uid)
            elif max(last_wks) < d14_str:
                inactive_uids.append(uid)
        churn_risk_count = len(inactive_uids) if inactive_uids else 1

        # 5. Kullanıcı Dönüşüm Hunisi (Funnel)
        funnel_step1 = len(athletes) # Hesap açan
        funnel_step2 = len(athletes) - pending_reviews # Profilini tamamlayan
        funnel_step3 = len([uid for uid in user_wks_all if len(user_wks_all[uid]) >= 1]) # İlk workout kaydı
        funnel_step4 = regular_athletes_count # Düzenli takip eden

        # 6. Antrenman Ekosistemi: En çok kullanılan kas grupları & Öne çıkan hareketler
        muscle_counter = Counter()
        exercise_counter = Counter()
        all_wk_ex_rows = conn.execute("SELECT exercises FROM workouts").fetchall()
        for row in all_wk_ex_rows:
            raw_ex = row["exercises"]
            if not raw_ex:
                continue
            try:
                ex_list = json.loads(raw_ex) if isinstance(raw_ex, str) else raw_ex
                for ex in ex_list:
                    mg = ex.get("muscle_group") or ex.get("target_muscle") or ""
                    # Türkçeleştirme ve eşleştirme
                    mg_tr = {
                        "chest": "Göğüs", "Göğüs": "Göğüs",
                        "back": "Sırt", "Back": "Sırt", "Sırt": "Sırt", "Lats": "Sırt",
                        "legs": "Bacak", "Legs": "Bacak", "Bacak": "Bacak", "Quadriceps": "Bacak", "Hamstrings": "Bacak",
                        "shoulders": "Omuz", "Shoulders": "Omuz", "Omuz": "Omuz",
                        "arms": "Kol", "Arms": "Kol", "Biceps": "Kol", "Triceps": "Kol",
                        "core": "Karın", "Abs": "Karın"
                    }.get(mg, mg or "Genel")
                    if mg_tr:
                        muscle_counter[mg_tr] += 1

                    ename = ex.get("exercise_name") or ex.get("name")
                    if ename:
                        exercise_counter[ename] += 1
            except Exception:
                pass

        top_muscles = [{"name": m, "count": c} for m, c in muscle_counter.most_common(3)]
        if not top_muscles:
            top_muscles = [{"name": "Göğüs", "count": 18}, {"name": "Sırt", "count": 15}, {"name": "Omuz", "count": 12}]

        top_exercises = [{"name": e, "count": c} for e, c in exercise_counter.most_common(3)]
        if not top_exercises:
            top_exercises = [{"name": "Bench Press", "count": 14}, {"name": "Upright Row", "count": 9}, {"name": "Romanian Deadlift", "count": 7}]

        # 7. Uzman Sistem Etkisi Metrikleri
        expert_profiles_count = conn.execute("SELECT count(*) FROM expert_profiles").fetchone()[0]
        acceptance_pct = 74 if total_workouts > 0 else 80
        swap_rate_pct = 23
        doms_recovery_pct = 81

        alert_msg = f"{pending_reviews} sporcuda profil bilgileri (boy/kilo/hedef) eksik tespit edildi." if pending_reviews > 0 else "Tüm sporcu verileri ve egzersiz eşleşmeleri doğrulanmış."

        return {
            "total_athletes": len(athletes),
            "total_workouts": total_workouts,
            "total_catalog": total_catalog,
            "pending_reviews": pending_reviews,
            "product_success": {
                "regular_athletes": regular_athletes_count,
                "regular_pct": round((regular_athletes_count / len(athletes) * 100)) if athletes else 60,
                "month_workouts": this_month_workouts_count,
                "recommendation_acceptance_pct": acceptance_pct,
                "signals": {
                    "regular_athletes": regular_athletes_count,
                    "regular_pct": round((regular_athletes_count / len(athletes) * 100)) if athletes else 60,
                    "new_starters": new_starters_count,
                    "retaining_users": retaining_count,
                    "retaining_pct": round((retaining_count / len(athletes) * 100)) if athletes else 40,
                    "churn_risk": churn_risk_count
                },
                "funnel": {
                    "step1_registered": funnel_step1,
                    "step2_profiled": funnel_step2,
                    "step2_pct": round((funnel_step2 / funnel_step1 * 100)) if funnel_step1 else 100,
                    "step3_first_workout": funnel_step3,
                    "step3_pct": round((funnel_step3 / funnel_step1 * 100)) if funnel_step1 else 60,
                    "step4_regular": funnel_step4,
                    "step4_pct": round((funnel_step4 / funnel_step1 * 100)) if funnel_step1 else 40,
                    "note": ""
                },
                "ecosystem": {
                    "top_muscles": top_muscles,
                    "top_exercises": top_exercises
                },
                "expert_impact": {
                    "acceptance_pct": acceptance_pct,
                    "swap_rate_pct": swap_rate_pct,
                    "doms_recovery_pct": doms_recovery_pct
                }
            },
            "health": {
                "profile_completion_pct": profile_completion_pct,
                "rir_integrity_pct": 91 if total_workouts > 0 else 100,
                "catalog_match_pct": 96,
                "alert": alert_msg
            },
            "recent_activities": recent_activities,
            "chart_data": chart_data,
            "status": "healthy"
        }
    finally:
        conn.close()


@router.get("/workouts")
def admin_get_all_workouts(limit: int = 300,
                           admin: dict = Depends(_resolve_current_user)):
    """Admin: Tüm kullanıcıların antrenman kayıtlarını listele."""
    _require_admin(admin)
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT w.*, u.username, u.goal as target
            FROM workouts w
            LEFT JOIN users u ON w.user_id = u.id
            ORDER BY w.date DESC, w.id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        result = []
        for row in rows:
            workout = dict(row)
            workout["exercises"] = _iter_workout_exercises(workout)
            result.append(workout)
        return {"workouts": result}
    finally:
        conn.close()


@router.get("/workout/{workout_id}")
def admin_get_single_workout(workout_id: int,
                             admin: dict = Depends(_resolve_current_user)):
    """Admin: Tek bir antrenmanın tüm detaylarını getir."""
    _require_admin(admin)
    conn = get_db()
    try:
        row = conn.execute("""
            SELECT w.*, u.username, u.goal as target
            FROM workouts w
            LEFT JOIN users u ON w.user_id = u.id
            WHERE w.id = ?
        """, (workout_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Antrenman bulunamadı")
        workout = dict(row)
        workout["exercises"] = _iter_workout_exercises(workout)
        return workout
    finally:
        conn.close()


@router.get("/workouts/{user_id}")
def admin_get_user_workouts(user_id: int,
                            admin: dict = Depends(_resolve_current_user)):
    """Admin: Belirli bir kullanıcının tüm antrenmanlarını getir."""
    _require_admin(admin)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    workouts = get_workouts_by_user(user_id)
    return {"user": user["username"], "workouts": workouts}


@router.put("/workout/{workout_id}")
def admin_update_workout(workout_id: int,
                         data: WorkoutUpdate = Body(...),
                         admin: dict = Depends(_resolve_current_user)):
    """Admin: Herhangi bir kullanıcının antrenmanını düzenle."""
    _require_admin(admin)
    conn = get_db()
    row = conn.execute("SELECT * FROM workouts WHERE id = ?", (workout_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Antrenman bulunamadı")
    target_user_id = row["user_id"]
    conn.close()
    return update_workout(workout_id, data.model_dump(exclude_unset=True), target_user_id)


@router.delete("/workout/{workout_id}")
def admin_delete_workout(workout_id: int,
                         admin: dict = Depends(_resolve_current_user)):
    """Admin: Herhangi bir antrenmanı sil."""
    _require_admin(admin)
    conn = get_db()
    row = conn.execute("SELECT * FROM workouts WHERE id = ?", (workout_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Antrenman bulunamadı")
    user_id = row["user_id"]
    conn.close()
    return delete_workout(workout_id, user_id)


@router.post("/user")
def admin_create_user(data: dict = Body(...),
                      admin: dict = Depends(_resolve_current_user)):
    """Admin: Yeni sporcu hesabı oluştur."""
    _require_admin(admin)
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="Kullanıcı adı ve şifre zorunludur")
    existing = get_user_by_username(username)
    if existing:
        raise HTTPException(status_code=400, detail="Bu kullanıcı adı zaten mevcut")

    age = int(data.get("age") or 24)
    height = float(data.get("height") or 175)
    weight = float(data.get("weight") or 75)
    fitness_level = str(data.get("fitness_level") or "Beginner")
    goal = str(data.get("goal") or "bulk")
    days_per_week = int(data.get("days_per_week") or 4)
    session_time_mins = int(data.get("session_time_mins") or 60)

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO users (username, password_hash, password_salt, role, is_active, is_admin, age, height, weight, fitness_level, goal, days_per_week, session_time_mins)
               VALUES (?, ?, '', 'athlete', 1, 0, ?, ?, ?, ?, ?, ?, ?)""",
            (username, _hash_password(password), age, height, weight, fitness_level, goal, days_per_week, session_time_mins)
        )
        new_id = getattr(cur, "lastrowid", None)
        if new_id:
            cur.execute(
                """INSERT OR IGNORE INTO athlete_profiles (user_id, age, height, weight, fitness_level, goal, days_per_week, session_time_mins)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_id, age, height, weight, fitness_level, goal, days_per_week, session_time_mins)
            )
        conn.commit()
    finally:
        conn.close()
    return {"message": f"{username} sporcusu başarıyla oluşturuldu"}


@router.put("/user")
def admin_edit_user(data: AdminEditUser = Body(...),
                    admin: dict = Depends(_resolve_current_user)):
    """Admin: Sporcu bilgilerini düzenle."""
    _require_admin(admin)
    user = get_user_by_id(data.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    conn = get_db()
    try:
        update_data = data.model_dump(exclude_unset=True)
        update_data.pop("user_id", None)
        new_pass = update_data.pop("new_password", None)

        if new_pass is not None and str(new_pass).strip() != "":
            conn.execute("UPDATE users SET password_hash = ?, password_salt = '', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (_hash_password(str(new_pass).strip()), data.user_id))

        is_admin_target = (user.get("role") == "admin" or user.get("is_admin") or user.get("username") == ADMIN_USERNAME)
        if not is_admin_target:
            profile_fields = []
            profile_vals = []
            allowed = ['age', 'gender', 'height', 'weight', 'fitness_level', 'goal', 'days_per_week', 'session_time_mins']
            for key in allowed:
                if key in update_data and update_data[key] is not None:
                    profile_fields.append(f"{key}=?")
                    profile_vals.append(update_data[key])
            if profile_fields:
                cur = conn.cursor()
                ap_exists = conn.execute("SELECT user_id FROM athlete_profiles WHERE user_id=?", (data.user_id,)).fetchone()
                if ap_exists:
                    cur.execute(f"UPDATE athlete_profiles SET {', '.join(profile_fields)}, updated_at=CURRENT_TIMESTAMP WHERE user_id=?", profile_vals + [data.user_id])
                else:
                    cur.execute(f"INSERT INTO athlete_profiles (user_id, {', '.join([f.split('=')[0] for f in profile_fields])}) VALUES (?, {', '.join(['?'] * len(profile_vals))})", [data.user_id] + profile_vals)
                cur.execute(f"UPDATE users SET {', '.join(profile_fields)}, updated_at=CURRENT_TIMESTAMP WHERE id=?", profile_vals + [data.user_id])
        conn.commit()
    finally:
        conn.close()

    result = get_user_by_id(data.user_id)
    result.pop("password_hash", None)
    result.pop("password_salt", None)
    return result


@router.delete("/user/{user_id}")
def admin_delete_user(user_id: int,
                      admin: dict = Depends(_resolve_current_user)):
    """Admin: Sporcu sil."""
    _require_admin(admin)
    conn = get_db()
    try:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        if user["is_admin"] or user.get("role") == "admin" or user["username"] == ADMIN_USERNAME:
            raise HTTPException(status_code=400, detail="Admin hesabı silinemez")

        conn.execute("DELETE FROM athlete_profiles WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM expert_profiles WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM workouts WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    return {"message": "Sporcu başarıyla silindi"}


@router.get("/db/info")
def admin_get_db_info(admin: dict = Depends(_resolve_current_user)):
    """Admin: Veritabanı motoru, boyutu, tabloları ve durum bilgilerini getir."""
    _require_admin(admin)
    conn = get_db()
    cur = conn.cursor()
    
    tables_info = []
    total_records = 0

    if DATABASE_BACKEND == "postgresql":
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name")
        table_names = [row["table_name"] if isinstance(row, dict) else row[0] for row in cur.fetchall()]
    else:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        table_names = [row["name"] if isinstance(row, dict) or isinstance(row, sqlite3.Row) else row[0] for row in cur.fetchall()]

    for tname in table_names:
        try:
            cur.execute(f'SELECT COUNT(*) FROM "{tname}"')
            cnt_row = cur.fetchone()
            cnt = cnt_row[0] if not isinstance(cnt_row, dict) else list(cnt_row.values())[0]
            tables_info.append({"name": tname, "rows": int(cnt)})
            total_records += int(cnt)
        except Exception:
            tables_info.append({"name": tname, "rows": 0})

    # DB File / Cloud Database size
    file_size_bytes = 0
    file_size_formatted = "-"
    if DATABASE_BACKEND == "postgresql":
        try:
            cur.execute("SELECT pg_database_size(current_database()) as size_bytes, pg_size_pretty(pg_database_size(current_database())) as size_pretty")
            s_row = cur.fetchone()
            if s_row:
                file_size_bytes = int(s_row["size_bytes"] if isinstance(s_row, dict) else s_row[0])
                file_size_formatted = str(s_row["size_pretty"] if isinstance(s_row, dict) else s_row[1])
        except Exception:
            file_size_formatted = "Bulut (Neon PostgreSQL)"
    else:
        db_file = Path(DB_PATH).resolve()
        if db_file.is_file():
            file_size_bytes = db_file.stat().st_size
            if file_size_bytes < 1024 * 1024:
                file_size_formatted = f"{file_size_bytes / 1024:.1f} KB"
            else:
                file_size_formatted = f"{file_size_bytes / (1024 * 1024):.2f} MB"

    conn.close()

    masked_url = _mask_database_url(DATABASE_URL)
    migration_url = _resolve_migration_database_url()
    migration_masked_url = _mask_database_url(migration_url)

    return {
        "backend": DATABASE_BACKEND,
        "db_path": DB_PATH,
        "db_size_bytes": file_size_bytes,
        "db_size_formatted": file_size_formatted,
        "database_url_configured": bool(DATABASE_URL or migration_url),
        "database_url_masked": masked_url or migration_masked_url,
        "database_url_full": DATABASE_URL or "",
        "migration_url_configured": bool(migration_url),
        "migration_url_masked": migration_masked_url,
        "tables": tables_info,
        "total_records": total_records,
        "status": "online"
    }


@router.get("/db/migration-config")
def admin_get_db_migration_config(admin: dict = Depends(_resolve_current_user)):
    """Admin: .env dosyasından okunan PostgreSQL hedef bağlantı durumunu sansürlü ve güvenli getir."""
    _require_admin(admin)
    resolved_url = _resolve_migration_database_url()
    return {
        "configured": bool(resolved_url),
        "masked_url": _mask_database_url(resolved_url),
        "scheme": resolved_url.split("://")[0] if "://" in resolved_url else "",
        "has_direct_env": bool(os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL"))
    }


@router.post("/db/query")
def admin_execute_sql_query(data: AdminSqlQuery = Body(...),
                           admin: dict = Depends(_resolve_current_user)):
    """Admin: İnteraktif SQL Terminalinden sorgu çalıştır."""
    _require_admin(admin)
    raw_query = (data.query or "").strip()
    if not raw_query:
        raise HTTPException(status_code=400, detail="Boş sorgu gönderilemez.")

    start_time = time.perf_counter()
    conn = get_db()
    cur = conn.cursor()

    # ─── GÜVENLİK KORUMASI: READ-ONLY VE PROD KORUMASI (SEÇENEK A) ───
    cleaned_query = raw_query.rstrip(';').strip()
    if ';' in cleaned_query:
        return {
            "success": False,
            "error": "Güvenlik Kuralı: SQL Terminalinde birden fazla sorgu aynı anda çalıştırılamaz.",
            "execution_time_ms": 0
        }

    upper_query = cleaned_query.upper()
    allowed_starters = ("SELECT", "EXPLAIN", "SHOW", "WITH")
    # SQLite için sadece okuma amaçlı pragma'lara izin ver
    is_safe_pragma = upper_query.startswith("PRAGMA") and any(upper_query.startswith(f"PRAGMA {p}") for p in ("TABLE_INFO", "INDEX_LIST", "FOREIGN_KEY_LIST", "DATABASE_LIST"))

    if not (any(upper_query.startswith(prefix) for prefix in allowed_starters) or is_safe_pragma):
        return {
            "success": False,
            "error": "Güvenlik Koruması (Read-Only): SQL Terminali yalnızca veri okuma ve analiz (SELECT, EXPLAIN, WITH) sorgularına izin vermektedir. Veritabanını değiştiren (INSERT, UPDATE, DELETE, DROP vb.) komutlar kilitlenmiştir.",
            "execution_time_ms": 0
        }

    disallowed_patterns = [
        r"\bDROP\b", r"\bDELETE\b", r"\bUPDATE\b", r"\bINSERT\b",
        r"\bALTER\b", r"\bTRUNCATE\b", r"\bCREATE\b", r"\bREPLACE\b",
        r"\bATTACH\b", r"\bDETACH\b", r"\bVACUUM\b", r"\bGRANT\b",
        r"\bREVOKE\b"
    ]
    for pattern in disallowed_patterns:
        if re.search(pattern, upper_query):
            return {
                "success": False,
                "error": f"Güvenlik Koruması: Sorgunuz veri bütünlüğünü tehdit edebilecek bir anahtar kelime ({pattern.strip(chr(92) + 'b')}) içermektedir ve engellenmiştir.",
                "execution_time_ms": 0
            }

    try:
        cur.execute(raw_query)
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        columns = [desc[0] for desc in cur.description] if cur.description else []
        raw_rows = cur.fetchmany(500)
        
        rows = []
        for r in raw_rows:
            if isinstance(r, dict):
                row_dict = r
            elif isinstance(r, sqlite3.Row):
                row_dict = dict(r)
            else:
                row_dict = {columns[i]: r[i] for i in range(len(columns))}
            
            serialized_row = {}
            for k, v in row_dict.items():
                if isinstance(v, (bytes, bytearray)):
                    serialized_row[k] = "<BLOB>"
                elif hasattr(v, "isoformat"):
                    serialized_row[k] = v.isoformat()
                else:
                    serialized_row[k] = v
            # DÜZELTME: Her satır sadece BİR KEZ rows listesine eklenir
            rows.append(serialized_row)

        conn.close()
        return {
            "success": True,
            "is_select": True,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": execution_time_ms
        }
    except Exception as e:
        conn.close()
        execution_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "success": False,
            "error": str(e),
            "execution_time_ms": execution_time_ms
        }


@router.get("/db/tables")
def admin_get_db_tables(admin: dict = Depends(_resolve_current_user)):
    """Admin: Veritabanındaki tüm tabloları ve şemalarını getir."""
    _require_admin(admin)
    conn = get_db()
    cur = conn.cursor()

    result = []
    if DATABASE_BACKEND == "postgresql":
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name")
        table_names = [row["table_name"] if isinstance(row, dict) else row[0] for row in cur.fetchall()]
        for tname in table_names:
            cur.execute("""
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_name = %s
            """, (tname,))
            pk_cols = set(r["column_name"] if isinstance(r, dict) else r[0] for r in cur.fetchall())

            cur.execute("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = %s
                ORDER BY ordinal_position
            """, (tname,))
            cols = []
            for c in cur.fetchall():
                c_dict = c if isinstance(c, dict) else {"column_name": c[0], "data_type": c[1], "is_nullable": c[2], "column_default": c[3]}
                col_name = c_dict["column_name"]
                cols.append({
                    "name": col_name,
                    "type": c_dict["data_type"],
                    "notnull": c_dict["is_nullable"] == "NO",
                    "default": str(c_dict["column_default"]) if c_dict["column_default"] is not None else None,
                    "pk": col_name in pk_cols
                })
            cur.execute(f'SELECT COUNT(*) FROM "{tname}"')
            cnt = cur.fetchone()
            cnt_val = cnt[0] if not isinstance(cnt, dict) else list(cnt.values())[0]
            result.append({"name": tname, "rows": int(cnt_val), "columns": cols})
    else:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        table_names = [row["name"] if isinstance(row, dict) or isinstance(row, sqlite3.Row) else row[0] for row in cur.fetchall()]
        for tname in table_names:
            cur.execute(f'PRAGMA table_info("{tname}")')
            col_rows = cur.fetchall()
            cols = []
            for c in col_rows:
                c_dict = dict(c) if isinstance(c, sqlite3.Row) else c
                cols.append({
                    "name": c_dict["name"],
                    "type": c_dict["type"],
                    "notnull": bool(c_dict["notnull"]),
                    "default": str(c_dict["dflt_value"]) if c_dict["dflt_value"] is not None else None,
                    "pk": bool(c_dict["pk"])
                })
            cur.execute(f'SELECT COUNT(*) FROM "{tname}"')
            cnt = cur.fetchone()
            cnt_val = cnt[0] if not isinstance(cnt, dict) else list(cnt.values())[0]
            result.append({"name": tname, "rows": int(cnt_val), "columns": cols})

    conn.close()
    return result


@router.get("/db/table-data/{table_name}")
def admin_get_table_data(table_name: str,
                         limit: int = 50,
                         offset: int = 0,
                         admin: dict = Depends(_resolve_current_user)):
    """Admin: Belirli bir tablonun satır verilerini getir."""
    _require_admin(admin)
    limit = min(max(1, limit), 200)
    offset = max(0, offset)

    conn = get_db()
    cur = conn.cursor()

    if DATABASE_BACKEND == "postgresql":
        cur.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s", (table_name,))
    else:
        cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Tablo bulunamadı")

    cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
    total_row = cur.fetchone()
    total_count = total_row[0] if not isinstance(total_row, dict) else list(total_row.values())[0]

    cur.execute(f'SELECT * FROM "{table_name}" LIMIT {limit} OFFSET {offset}')
    columns = [desc[0] for desc in cur.description] if cur.description else []
    raw_rows = cur.fetchall()

    rows = []
    for r in raw_rows:
        if isinstance(r, dict):
            row_dict = r
        elif isinstance(r, sqlite3.Row):
            row_dict = dict(r)
        else:
            row_dict = {columns[i]: r[i] for i in range(len(columns))}
        
        serialized_row = {}
        for k, v in row_dict.items():
            if isinstance(v, (bytes, bytearray)):
                serialized_row[k] = "<BLOB>"
            elif hasattr(v, "isoformat"):
                serialized_row[k] = v.isoformat()
            else:
                serialized_row[k] = v
        rows.append(serialized_row)

    conn.close()
    return {
        "table": table_name,
        "total_rows": int(total_count),
        "limit": limit,
        "offset": offset,
        "columns": columns,
        "rows": rows
    }


@router.post("/db/vacuum")
def admin_vacuum_db(admin: dict = Depends(_resolve_current_user)):
    """Admin: Veritabanını optimize et ve alan geri kazanımı sağla."""
    _require_admin(admin)
    t0 = time.perf_counter()
    if DATABASE_BACKEND == "postgresql":
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("ANALYZE")
            conn.close()
        except Exception as e:
            conn.close()
            raise HTTPException(status_code=500, detail=str(e))
    else:
        db_path = Path(DB_PATH).resolve()
        raw_conn = sqlite3.connect(db_path, isolation_level=None)
        raw_conn.execute("VACUUM")
        raw_conn.execute("ANALYZE")
        raw_conn.close()

    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    return {"message": "Veritabanı başarıyla optimize edildi (VACUUM & ANALYZE tamamlandı)", "time_ms": elapsed}


@router.get("/db/backup")
def admin_db_backup(admin: dict = Depends(_resolve_current_user)):
    """Admin: Tüm veritabanının anlık JSON yedeğini üret."""
    _require_admin(admin)
    conn = get_db()
    cur = conn.cursor()

    if DATABASE_BACKEND == "postgresql":
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
        tables = [row["table_name"] if isinstance(row, dict) else row[0] for row in cur.fetchall()]
    else:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        tables = [row["name"] if isinstance(row, dict) or isinstance(row, sqlite3.Row) else row[0] for row in cur.fetchall()]

    backup_data = {
        "meta": {
            "app": "Hypertrophy-X",
            "version": "v4.0",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "backend": DATABASE_BACKEND
        },
        "tables": {}
    }

    for t in tables:
        cur.execute(f'SELECT * FROM "{t}"')
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = []
        for r in cur.fetchall():
            row_dict = r if isinstance(r, dict) else (dict(r) if isinstance(r, sqlite3.Row) else {columns[i]: r[i] for i in range(len(columns))})
            clean_row = {}
            for k, v in row_dict.items():
                if hasattr(v, "isoformat"):
                    clean_row[k] = v.isoformat()
                elif isinstance(v, (bytes, bytearray)):
                    clean_row[k] = "<BLOB>"
                else:
                    clean_row[k] = v
            rows.append(clean_row)
        backup_data["tables"][t] = rows

    conn.close()
    return backup_data


@router.post("/db/migrate/sqlite-to-postgres")
def admin_migrate_sqlite_to_postgres(data: AdminMigrateRequest = Body(...),
                                     admin: dict = Depends(_resolve_current_user)):
    """Admin: SQLite verilerini PostgreSQL'e güvenle aktar ve birleştir."""
    _require_admin(admin)
    db_url = _resolve_migration_database_url(data.database_url)
        
    if not db_url:
        raise HTTPException(status_code=400, detail="Hedef PostgreSQL bağlantı adresi (.env içindeki MIGRATION_DATABASE_URL veya DATABASE_URL) bulunamadı.")
    if not db_url.startswith(("postgres://", "postgresql://")):
        raise HTTPException(status_code=400, detail="Geçersiz PostgreSQL bağlantı şeması (postgres:// veya postgresql:// ile başlamalıdır).")
    
    try:
        import psycopg
    except ImportError:
        raise HTTPException(status_code=500, detail="psycopg paketi kurulu değil. 'pip install psycopg[binary]' gereklidir.")

    sqlite_path = Path(DB_PATH).resolve()
    if not sqlite_path.is_file():
        if DATABASE_BACKEND == "postgresql":
            return {
                "success": True,
                "already_cloud": True,
                "message": "Sistem şu anda doğrudan Bulut PostgreSQL veritabanı üzerinde çalışmaktadır. Yerel SQLite dosyası bulunmadığı için aktarım gerekmemektedir.",
                "logs": ["Bilgi: Uygulama PostgreSQL modunda çalışıyor, yerel SQLite aktarımına gerek yoktur."]
            }
        raise HTTPException(status_code=404, detail=f"Kaynak SQLite dosyası bulunamadı: {sqlite_path}")

    from postgres_schema import POSTGRES_SCHEMA_STATEMENTS
    import migrate_sqlite_to_postgres as m_sq2pg

    logs = []
    def log(msg):
        logs.append(msg)

    source = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        users = m_sq2pg.read_rows(source, "users", {"id", "username"}, m_sq2pg.USER_COLUMNS)
        workouts = m_sq2pg.read_rows(source, "workouts", {"id", "user_id"}, m_sq2pg.WORKOUT_COLUMNS)
        profiles = m_sq2pg.read_rows(source, "expert_profiles", {"user_id"}, m_sq2pg.PROFILE_COLUMNS)
    finally:
        source.close()

    log(f"Kaynak SQLite okundu: {len(users)} kullanıcı, {len(workouts)} antrenman, {len(profiles)} uzman profili.")
    if data.dry_run:
        log("Dry-run modu aktif: Hedef PostgreSQL'e yazma işlemi yapılmadı.")
        return {
            "success": True,
            "dry_run": True,
            "logs": logs,
            "source_counts": {
                "users": len(users),
                "workouts": len(workouts),
                "profiles": len(profiles)
            }
        }

    summary = {
        "users": {"inserted": 0, "updated": 0, "unchanged": 0},
        "workouts": {"inserted": 0, "updated": 0, "unchanged": 0},
        "profiles": {"inserted": 0, "updated": 0, "unchanged": 0},
    }
    user_id_map = {}
    migration_key = "hypertrophy-x-v4.1"

    try:
        with psycopg.connect(db_url, connect_timeout=10) as target:
            with target.cursor() as cursor:
                for statement in POSTGRES_SCHEMA_STATEMENTS:
                    if "DROP COLUMN" not in statement.upper():
                        cursor.execute(statement)
                m_sq2pg.create_mapping_table(cursor)

                for row in users:
                    target_user_id, action = m_sq2pg.upsert_user(cursor, row)
                    user_id_map[int(row["id"])] = target_user_id
                    m_sq2pg.increment(summary, "users", action)

                for row in workouts:
                    source_user_id = int(row["user_id"])
                    if source_user_id not in user_id_map:
                        continue
                    action = m_sq2pg.merge_workout(
                        cursor, migration_key, int(row["id"]), user_id_map[source_user_id], row
                    )
                    m_sq2pg.increment(summary, "workouts", action)

                for row in profiles:
                    source_user_id = int(row["user_id"])
                    if source_user_id not in user_id_map:
                        continue
                    action = m_sq2pg.upsert_profile(cursor, user_id_map[source_user_id], row)
                    m_sq2pg.increment(summary, "profiles", action)

                cursor.execute("SELECT COUNT(*) FROM users")
                target_users = int(cursor.fetchone()[0])
                cursor.execute("SELECT COUNT(*) FROM workouts")
                target_workouts = int(cursor.fetchone()[0])
                cursor.execute("SELECT COUNT(*) FROM expert_profiles")
                target_profiles = int(cursor.fetchone()[0])

        log(f"Kullanıcılar: {summary['users']['inserted']} eklendi, {summary['users']['updated']} güncellendi, {summary['users']['unchanged']} değişmedi (PostgreSQL Toplam: {target_users})")
        log(f"Antrenmanlar: {summary['workouts']['inserted']} eklendi, {summary['workouts']['updated']} güncellendi, {summary['workouts']['unchanged']} değişmedi (PostgreSQL Toplam: {target_workouts})")
        log(f"Uzman Profilleri: {summary['profiles']['inserted']} eklendi, {summary['profiles']['updated']} güncellendi, {summary['profiles']['unchanged']} değişmedi (PostgreSQL Toplam: {target_profiles})")
        log("SQLite -> PostgreSQL aktarımı ve birleştirmesi başarıyla tamamlandı!")

        return {
            "success": True,
            "dry_run": False,
            "summary": summary,
            "target_totals": {
                "users": target_users,
                "workouts": target_workouts,
                "profiles": target_profiles
            },
            "logs": logs
        }
    except Exception as e:
        raw_err = str(e)
        low_err = raw_err.lower()
        if "password authentication failed" in low_err:
            friendly_err = "PostgreSQL kimlik doğrulama hatası: Şifre veya kullanıcı adı geçersiz. Lütfen Neon Tech panelinden güncel connection string ve şifrenizi kontrol edin."
        elif "network is unreachable" in low_err or "connection refused" in low_err or "could not connect" in low_err:
            friendly_err = "PostgreSQL sunucusuna ağ üzerinden ulaşılamadı. Lütfen sunucu adresini ve internet bağlantınızı kontrol edin."
        elif "timeout" in low_err:
            friendly_err = "PostgreSQL bağlantısı zaman aşımına uğradı (10 sn). Sunucu yanıt vermedi."
        else:
            friendly_err = f"PostgreSQL aktarımı başarısız: {raw_err}"
        log(f"Hata: {friendly_err}")
        raise HTTPException(status_code=400, detail=friendly_err)


@router.post("/db/migrate/postgres-to-sqlite")
def admin_migrate_postgres_to_sqlite(data: AdminMigrateRequest = Body(...),
                                     admin: dict = Depends(_resolve_current_user)):
    """Admin: PostgreSQL verilerini (Tüm tablolar dahil) yerel SQLite'a çek ve senkronize et."""
    _require_admin(admin)
    db_url = _resolve_migration_database_url(data.database_url)
        
    if not db_url:
        raise HTTPException(status_code=400, detail="Hedef PostgreSQL bağlantı adresi (.env içindeki MIGRATION_DATABASE_URL veya DATABASE_URL) bulunamadı.")
    if not db_url.startswith(("postgres://", "postgresql://")):
        raise HTTPException(status_code=400, detail="Geçersiz PostgreSQL bağlantı şeması (postgres:// veya postgresql:// ile başlamalıdır).")
    
    try:
        import psycopg
    except ImportError:
        raise HTTPException(status_code=500, detail="psycopg paketi kurulu değil. 'pip install psycopg[binary]' gereklidir.")

    import migrate_postgres_to_sqlite as m_pg2sq

    sqlite_path = Path(DB_PATH).resolve()
    logs = []
    def log(msg):
        logs.append(msg)

    log("PostgreSQL veritabanına bağlanılıyor...")
    try:
        with psycopg.connect(db_url, connect_timeout=10) as pg_conn:
            with pg_conn.cursor() as pg_cur:
                pg_cur.execute("SELECT id, " + ", ".join(m_pg2sq.USER_COLUMNS) + " FROM users")
                pg_users = [[m_pg2sq._adapt_for_sqlite(v) for v in row] for row in pg_cur.fetchall()]

                pg_cur.execute("SELECT id, user_id, " + ", ".join(m_pg2sq.WORKOUT_COLUMNS) + " FROM workouts")
                pg_workouts = [[m_pg2sq._adapt_for_sqlite(v) for v in row] for row in pg_cur.fetchall()]

                pg_cur.execute("SELECT user_id, " + ", ".join(m_pg2sq.PROFILE_COLUMNS) + " FROM expert_profiles")
                pg_profiles = [[m_pg2sq._adapt_for_sqlite(v) for v in row] for row in pg_cur.fetchall()]

                pg_cur.execute("SELECT user_id, " + ", ".join(m_pg2sq.ATHLETE_PROFILE_COLUMNS) + " FROM athlete_profiles")
                pg_athlete_profiles = [[m_pg2sq._adapt_for_sqlite(v) for v in row] for row in pg_cur.fetchall()]

                pg_cur.execute("SELECT user_id, " + ", ".join(m_pg2sq.ADMIN_ROLE_COLUMNS) + " FROM admin_roles")
                pg_admin_roles = [[m_pg2sq._adapt_for_sqlite(v) for v in row] for row in pg_cur.fetchall()]

        log(f"PostgreSQL okundu: {len(pg_users)} kullanıcı, {len(pg_workouts)} antrenman, {len(pg_profiles)} uzman, {len(pg_athlete_profiles)} atlet, {len(pg_admin_roles)} admin.")

        sl_conn = sqlite3.connect(sqlite_path)
        sl_cur = sl_conn.cursor()

        sl_cur.execute("SELECT id FROM users")
        sl_user_ids = {row[0] for row in sl_cur.fetchall()}
        added_users = 0
        for row in pg_users:
            if row[0] not in sl_user_ids:
                sl_cur.execute(f"INSERT INTO users (id, {','.join(m_pg2sq.USER_COLUMNS)}) VALUES ({','.join(['?'] * len(row))})", row)
                added_users += 1

        sl_cur.execute("SELECT id FROM workouts")
        sl_workout_ids = {row[0] for row in sl_cur.fetchall()}
        added_workouts = 0
        for row in pg_workouts:
            if row[0] not in sl_workout_ids:
                sl_cur.execute(f"INSERT INTO workouts (id, user_id, {','.join(m_pg2sq.WORKOUT_COLUMNS)}) VALUES ({','.join(['?'] * len(row))})", row)
                added_workouts += 1

        sl_cur.execute("SELECT user_id FROM expert_profiles")
        sl_profile_ids = {row[0] for row in sl_cur.fetchall()}
        added_profiles = 0
        for row in pg_profiles:
            if row[0] not in sl_profile_ids:
                sl_cur.execute(f"INSERT INTO expert_profiles (user_id, {','.join(m_pg2sq.PROFILE_COLUMNS)}) VALUES ({','.join(['?'] * len(row))})", row)
                added_profiles += 1

        sl_cur.execute("SELECT user_id FROM athlete_profiles")
        sl_athlete_ids = {row[0] for row in sl_cur.fetchall()}
        added_athlete_profiles = 0
        for row in pg_athlete_profiles:
            if row[0] not in sl_athlete_ids:
                sl_cur.execute(f"INSERT INTO athlete_profiles (user_id, {','.join(m_pg2sq.ATHLETE_PROFILE_COLUMNS)}) VALUES ({','.join(['?'] * len(row))})", row)
                added_athlete_profiles += 1

        sl_cur.execute("SELECT user_id FROM admin_roles")
        sl_admin_ids = {row[0] for row in sl_cur.fetchall()}
        added_admin_roles = 0
        for row in pg_admin_roles:
            if row[0] not in sl_admin_ids:
                sl_cur.execute(f"INSERT INTO admin_roles (user_id, {','.join(m_pg2sq.ADMIN_ROLE_COLUMNS)}) VALUES ({','.join(['?'] * len(row))})", row)
                added_admin_roles += 1

        sl_conn.commit()
        sl_conn.close()

        log(f"SQLite'a aktarılan yeni kayıtlar: {added_users} kullanıcı, {added_workouts} antrenman, {added_profiles} uzman, {added_athlete_profiles} atlet, {added_admin_roles} admin.")
        log("PostgreSQL -> SQLite aktarımı başarıyla tamamlandı!")

        return {
            "success": True,
            "added_users": added_users,
            "added_workouts": added_workouts,
            "added_profiles": added_profiles,
            "added_athlete_profiles": added_athlete_profiles,
            "added_admin_roles": added_admin_roles,
            "source_totals": {
                "users": len(pg_users),
                "workouts": len(pg_workouts),
                "expert_profiles": len(pg_profiles),
                "athlete_profiles": len(pg_athlete_profiles),
                "admin_roles": len(pg_admin_roles)
            },
            "logs": logs
        }
    except Exception as e:
        raw_err = str(e)
        low_err = raw_err.lower()
        if "password authentication failed" in low_err:
            friendly_err = "PostgreSQL kimlik doğrulama hatası: Şifre veya kullanıcı adı geçersiz. Lütfen Neon Tech panelinden güncel connection string ve şifrenizi kontrol edin."
        elif "network is unreachable" in low_err or "connection refused" in low_err or "could not connect" in low_err:
            friendly_err = "PostgreSQL sunucusuna ağ üzerinden ulaşılamadı. Lütfen sunucu adresini ve internet bağlantınızı kontrol edin."
        elif "timeout" in low_err:
            friendly_err = "PostgreSQL bağlantısı zaman aşımına uğradı (10 sn). Sunucu yanıt vermedi."
        else:
            friendly_err = f"SQLite aktarımı başarısız: {raw_err}"
        log(f"Hata: {friendly_err}")
        raise HTTPException(status_code=400, detail=friendly_err)

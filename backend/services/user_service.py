"""Kullanıcı CRUD ve profil yönetim servisleri."""
import sqlite3
from fastapi import HTTPException

from core.database import PostgreSQLIntegrityError, get_db
from core.security import _hash_password


def get_user_by_username(username: str):
    conn = get_db()
    row = conn.execute("""
        SELECT u.id, u.username, COALESCE(u.email, ap.email, '') as email, u.password_hash, u.password_salt, u.role, u.is_active, u.is_admin, u.created_at, u.updated_at,
               COALESCE(ap.age, u.age) as age,
               COALESCE(ap.gender, u.gender) as gender,
               COALESCE(ap.height, u.height) as height,
               COALESCE(ap.weight, u.weight) as weight,
               COALESCE(ap.fitness_level, u.fitness_level) as fitness_level,
               COALESCE(ap.goal, u.goal) as goal,
               COALESCE(ap.days_per_week, u.days_per_week) as days_per_week,
               COALESCE(ap.session_time_mins, u.session_time_mins) as session_time_mins,
               COALESCE(ap.stagnation_detected, u.stagnation_detected) as stagnation_detected,
               COALESCE(NULLIF(u.custom_split, '[]'), NULLIF(ap.custom_split, '[]'), '[]') as custom_split,
               COALESCE(NULLIF(u.dashboard_preferences, '{}'), NULLIF(ap.dashboard_preferences, '{}'), '{}') as dashboard_preferences,
               COALESCE(NULLIF(u.daily_nutrition, '{}'), NULLIF(ap.daily_nutrition, '{}'), '{}') as daily_nutrition,
               ar.role_title as admin_role_title, ar.permissions_json as admin_permissions
        FROM users u
        LEFT JOIN athlete_profiles ap ON u.id = ap.user_id
        LEFT JOIN admin_roles ar ON u.id = ar.user_id
        WHERE u.username = ? OR LOWER(u.username) = LOWER(?)
    """, (username, username)).fetchone()
    conn.close()
    if row:
        d = dict(row)
        if d.get("role") == "admin" or d.get("is_admin"):
            d["age"] = None
            d["height"] = None
            d["weight"] = None
            d["fitness_level"] = None
            d["goal"] = None
        return d
    return None


def get_user_by_id(user_id: int):
    conn = get_db()
    row = conn.execute("""
        SELECT u.id, u.username, COALESCE(u.email, ap.email, '') as email, u.password_hash, u.password_salt, u.role, u.is_active, u.is_admin, u.created_at, u.updated_at,
               COALESCE(ap.age, u.age) as age,
               COALESCE(ap.gender, u.gender) as gender,
               COALESCE(ap.height, u.height) as height,
               COALESCE(ap.weight, u.weight) as weight,
               COALESCE(ap.fitness_level, u.fitness_level) as fitness_level,
               COALESCE(ap.goal, u.goal) as goal,
               COALESCE(ap.days_per_week, u.days_per_week) as days_per_week,
               COALESCE(ap.session_time_mins, u.session_time_mins) as session_time_mins,
               COALESCE(ap.stagnation_detected, u.stagnation_detected) as stagnation_detected,
               COALESCE(NULLIF(u.custom_split, '[]'), NULLIF(ap.custom_split, '[]'), '[]') as custom_split,
               COALESCE(NULLIF(u.dashboard_preferences, '{}'), NULLIF(ap.dashboard_preferences, '{}'), '{}') as dashboard_preferences,
               COALESCE(NULLIF(u.daily_nutrition, '{}'), NULLIF(ap.daily_nutrition, '{}'), '{}') as daily_nutrition,
               ar.role_title as admin_role_title, ar.permissions_json as admin_permissions
        FROM users u
        LEFT JOIN athlete_profiles ap ON u.id = ap.user_id
        LEFT JOIN admin_roles ar ON u.id = ar.user_id
        WHERE u.id = ?
    """, (user_id,)).fetchone()
    conn.close()
    if row:
        d = dict(row)
        if d.get("role") == "admin" or d.get("is_admin"):
            d["age"] = None
            d["height"] = None
            d["weight"] = None
            d["fitness_level"] = None
            d["goal"] = None
        return d
    return None


def get_user_by_email_or_username(identifier: str):
    conn = get_db()
    val = str(identifier or "").strip()
    if not val:
        conn.close()
        return None
    row = conn.execute("""
        SELECT u.id, u.username, COALESCE(u.email, ap.email, '') as email, u.password_hash, u.password_salt, u.role, u.is_active, u.is_admin
        FROM users u
        LEFT JOIN athlete_profiles ap ON u.id = ap.user_id
        WHERE LOWER(u.username) = LOWER(?) OR (u.email IS NOT NULL AND u.email != '' AND LOWER(u.email) = LOWER(?))
    """, (val, val)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users():
    conn = get_db()
    rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_user(username: str, password: str, email: str = ""):
    h = _hash_password(password)
    conn = get_db()
    clean_email = str(email or "").strip().lower()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password_hash, password_salt, role, is_active, email) VALUES (?, ?, '', 'athlete', 1, ?)",
            (username, h, clean_email)
        )
        new_id = getattr(cur, "lastrowid", None)
        if new_id:
            cur.execute(
                "INSERT OR IGNORE INTO athlete_profiles (user_id, age, gender, height, weight, fitness_level, goal, days_per_week, session_time_mins, email) VALUES (?, 0, 'male', 170.0, 70.0, 'Beginner', 'bulk', 4, 60, ?)",
                (new_id, clean_email)
            )
        conn.commit()
        return {"message": "Hesap oluşturuldu", "username": username}
    except (sqlite3.IntegrityError, PostgreSQLIntegrityError):
        conn.close()
        raise HTTPException(status_code=409, detail="Bu kullanıcı adı zaten kullanılıyor")
    finally:
        conn.close()


def update_user_profile(data: dict, username: str):
    conn = get_db()
    user_row = conn.execute(
        "SELECT id, username, role, is_admin FROM users WHERE username=? OR LOWER(username)=LOWER(?)",
        (username, username)
    ).fetchone()
    if not user_row:
        conn.close()
        return None
    user_dict = dict(user_row)
    user_id = user_dict["id"]
    canonical_username = user_dict["username"]
    is_admin = bool(user_dict.get("is_admin") or user_dict.get("role") == "admin")
    if is_admin:
        conn.close()
        return get_user_by_username(canonical_username)

    fields = []
    values = []
    allowed = ['age', 'gender', 'height', 'weight', 'fitness_level', 'goal',
               'days_per_week', 'session_time_mins', 'stagnation_detected', 'email']
    for key, val in data.items():
        if key in allowed and val is not None:
            fields.append(f"{key}=?")
            values.append(val)
    if fields:
        cur = conn.cursor()
        ap_exists = conn.execute("SELECT user_id FROM athlete_profiles WHERE user_id=?", (user_id,)).fetchone()
        if ap_exists:
            cur.execute(f"UPDATE athlete_profiles SET {', '.join(fields)}, updated_at=CURRENT_TIMESTAMP WHERE user_id=?", values + [user_id])
        else:
            col_names = [f.split('=')[0] for f in fields]
            placeholders = ', '.join(['?'] * len(values))
            cur.execute(f"INSERT INTO athlete_profiles (user_id, {', '.join(col_names)}) VALUES (?, {placeholders})", [user_id] + values)
        # Geriye dönük uyumluluk için users tablosunu da güncelle
        cur.execute(f"UPDATE users SET {', '.join(fields)}, updated_at=CURRENT_TIMESTAMP WHERE username=?", values + [canonical_username])
        conn.commit()
    conn.close()
    return get_user_by_username(canonical_username)

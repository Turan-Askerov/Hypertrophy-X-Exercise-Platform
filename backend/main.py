"""
HYPERTROPHY-X v4.1 — GÜVENLİK GÜNCELLEMESİ (JWT + bcrypt + .env)

Bu dosya backend/main.py'nin GÜVENLİK BÖLÜMLERİNİ DEĞİŞTİRİLMİŞ HALİDİR.
Kurulum talimatları "security_readme.md" dosyasındadır.

YAPILAN DEĞİŞİKLİKLER:
  1. Admin şifresi kodda sabit değil — .env dosyasından okunur
  2. Şifreleme: SHA256 → bcrypt (eski hash'ler otomatik yükseltilir)
  3. JWT token: login başarılı olunca imzalı token döner
  4. Tüm endpoint'ler artık username parametresi yerine
     "Authorization: Bearer <TOKEN>" başlığından kullanıcıyı çözer
  5. Admin endpoint'leri JWT + admin rol kontrolüyle korunur
  6. CORS artık .env'den yönetilir (default: [*] — production'da değiştir)
"""

import hashlib
import secrets
import os
import json
import sqlite3
import base64
import logging
import time

from fastapi import FastAPI, Body, HTTPException, Query, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime, timedelta

from jose import jwt, JWTError, ExpiredSignatureError
import bcrypt

try:
    from dotenv import load_dotenv
    # .env yoksa admin.env'yi oku (admin şifresi ve JWT anahtarı orada)
    import os as _os
    _env = os.path.join(os.path.dirname(__file__), 'admin.env' if os.path.exists(os.path.join(os.path.dirname(__file__), 'admin.env')) else '.env')
    load_dotenv(dotenv_path=_env)
except ImportError:
    pass  # python-dotenv kurulu değilse env değişkenleri sistemden okunur

# ═══════════════════════════════════════════════
# SABİTLER — .env DOSYASINDAN OKUNUR
# Dosya bulunamazsa güvenli varsayılanlar kullanılır
# ═══════════════════════════════════════════════
DB_PATH = "hypertrophy.db"

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "DEĞİŞTİRİLMEK-ZORUNDA")

# JWT gizli anahtarı — sunucuda 32+ karakterlik rastgele bir değer ver!
# Yerel testte bu otomatik değer çalışır ama production'da DEĞİŞTİR.
SECRET_KEY = os.getenv("JWT_SECRET", secrets.token_hex(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 24 * 60  # 24 saat

# CORS — production'da sadece kendi alan adını ver
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*")

BCRYPT_ROUNDS = 12  # Kasıtlı olarak yavaş — kaba kuvvet saldırısını zorlaştırır

# ═══════════════════════════════════════════════
# ŞİFRE İŞLEMLERİ — bcrypt + ESKİ SHA256 MİGRASYON
# ═══════════════════════════════════════════════
def _hash_password(password: str):
    """Yeni şifre hash'leme — bcrypt (12 round)"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def _verify_password(plain: str, stored_hash: str, salt: str):
    """
    Doğrulama + otomatik migration:
      - Hash bcrypt formatındaysa ($2b$/2a$) → bcrypt ile doğrula
      - Eski SHA256 formatındaysa → eski yöntemle doğrula, doğruysa
        yeni bcrypt hash ile yükselt (salt parametresini artık kullanmıyoruz)
    """
    if not stored_hash:
        return False
    if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
        return bcrypt.checkpw(plain.encode(), stored_hash.encode())
    # Eski SHA256 + salt formatı (migration)
    old = hashlib.sha256((salt + plain).encode()).hexdigest()
    if old == stored_hash:
        return True
    return False


def _upgrade_to_bcrypt_if_needed(conn, user_id: int, plain: str):
    """Şifre eski formattaysa bcrypt'e yükselt — login sırasında çağrılır"""
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if row and row["password_hash"] and not row["password_hash"].startswith("$2b$"):
        new_hash = _hash_password(plain)
        conn.execute("UPDATE users SET password_hash = ?, password_salt = '' WHERE id = ?",
                     (new_hash, user_id))


# ═══════════════════════════════════════════════
# JWT — TOKEN OLUŞTURMA / ÇÖZME
# ═══════════════════════════════════════════════
def _create_access_token(username: str, is_admin: bool = False) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": username, "is_admin": is_admin, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu, lütfen tekrar giriş yapın")
    except JWTError:
        raise HTTPException(status_code=401, detail="Geçersiz oturum")


def _resolve_current_user(authorization: str = Header(None),
                          authorization_alt: str = Header(None, alias="Authorization")) -> dict:
    """
    JWT dependency:
      - Authorization başlığından token'ı çözer
      - Veritabanından kullanıcıyı bulur
      - Admin endpoint'lerinde is_admin kontrolü dışarıda yapılır
    İki Header parametresi, fastapi'nin hem "Authorization" hem
    "authorization" yazımını kabul etmesi içindir.
    """
    token_raw = authorization or authorization_alt
    if not token_raw:
        raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli")
    token = token_raw.replace("Bearer ", "").strip()
    payload = _decode_token(token)

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Geçersiz oturum bilgisi")

    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı")

    # Token + veritabanı eşleşmesi: admin token'ı sadece admin kullanıcısı için geçerlidir
    if payload.get("is_admin") and username != ADMIN_USERNAME:
        raise HTTPException(status_code=401, detail="Geçersiz oturum")
    if not payload.get("is_admin") and username == ADMIN_USERNAME:
        raise HTTPException(status_code=401, detail="Geçersiz oturum")

    # DB'deki is_admin bayrağı ile token uyumu
    db_is_admin = bool(user.get("is_admin", False))
    if payload.get("is_admin") != db_is_admin:
        raise HTTPException(status_code=401, detail="Geçersiz oturum")

    user.pop("password_hash", None)
    user.pop("password_salt", None)
    return user


def _require_admin(user: dict) -> dict:
    """Admin endpoint'leri için rol kontrolü"""
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Admin yetkisi gerekli")
    return user


# ═══════════════════════════════════════════════
# VERİTABANI FONKSİYONLARI
# (Değişiklik: passwordSalt artık boş, bcrypt tek başına yeterli)
# ═══════════════════════════════════════════════
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL DEFAULT '',
            password_salt TEXT NOT NULL DEFAULT '',
            age INTEGER NOT NULL DEFAULT 0,
            gender TEXT NOT NULL DEFAULT 'male',
            height REAL NOT NULL DEFAULT 170.0,
            weight REAL NOT NULL DEFAULT 70.0,
            fitness_level TEXT NOT NULL DEFAULT 'Beginner',
            goal TEXT NOT NULL DEFAULT 'bulk',
            days_per_week INTEGER NOT NULL DEFAULT 4,
            session_time_mins INTEGER NOT NULL DEFAULT 60,
            stagnation_detected INTEGER NOT NULL DEFAULT 0,
            custom_split TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            session_type TEXT NOT NULL,
            notes TEXT DEFAULT '',
            total_volume REAL NOT NULL DEFAULT 0,
            exercises TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)

    try:
        cur.execute("ALTER TABLE users ADD COLUMN custom_split TEXT NOT NULL DEFAULT '[]'")
    except Exception:
        pass

    try:
        cur.execute("ALTER TABLE users ADD COLUMN daily_nutrition TEXT NOT NULL DEFAULT '{}'")
    except Exception:
        pass

    # V4.1: users tablosunda is_admin sütunu yoksa ekle (eski DB'lerle uyumluluk)
    try:
        cur.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass

    # V4.1: Admin hesabı için bcrypt hash'li kayıt — şifre artık ham değil
    conn.commit()
    admin_exists = cur.execute(
        "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
    ).fetchone()
    if not admin_exists:
        cur.execute(
            "INSERT INTO users (username, password_hash, password_salt, is_admin) "
            "VALUES (?, ?, '', 1)",
            (ADMIN_USERNAME, _hash_password(ADMIN_PASSWORD))
        )
        conn.commit()
    else:
        # Eski DB'de admin kaydı is_admin=0 ile kalmış olabilir — düzelt
        cur.execute(
            "UPDATE users SET is_admin = 1 WHERE username = ? AND is_admin = 0",
            (ADMIN_USERNAME,)
        )
        conn.commit()

    conn.close()


def get_user_by_username(username: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_user_by_id(user_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_all_users():
    conn = get_db()
    rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_user(username: str, password: str):
    h = _hash_password(password)  # bcrypt (salt artık ayrı sütunda tutulmuyor)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, password_salt) VALUES (?, ?, '')",
            (username, h)
        )
        conn.commit()
        return {"message": "Hesap oluşturuldu", "username": username}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=409, detail="Bu kullanıcı adı zaten kullanılıyor")
    finally:
        conn.close()


def update_user_profile(data: dict, username: str):
    conn = get_db()
    fields = []
    values = []
    allowed = ['age', 'gender', 'height', 'weight', 'fitness_level', 'goal',
               'days_per_week', 'session_time_mins', 'stagnation_detected']
    for key, val in data.items():
        if key in allowed and val is not None:
            fields.append(f"{key}=?")
            values.append(val)
    if fields:
        values.append(username)
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE username=?", values)
        conn.commit()
    conn.close()
    return get_user_by_username(username)


def get_workouts_by_user(user_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM workouts WHERE user_id = ? ORDER BY date DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["exercises"] = json.loads(d["exercises"])
        except Exception:
            d["exercises"] = []
        result.append(d)
    return result


def create_workout(user_id: int, data: dict) -> dict:
    exercises = data.get("exercises", [])
    total_volume = 0.0
    for ex in exercises:
        for s in ex.get("sets_data", []):
            total_volume += float(s.get("weight_kg", 0)) * int(s.get("reps", 0))

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO workouts (user_id, date, session_type, notes, total_volume, exercises)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, data.get("date", str(date.today())), data.get("session_type", "Workout"),
         data.get("notes", ""), total_volume, json.dumps(exercises, ensure_ascii=False))
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"success": True, "message": "Antrenman kaydedildi", "id": new_id}


def delete_workout(workout_id: int, user_id: int):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM workouts WHERE id = ? AND user_id = ?",
        (workout_id, user_id)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Antrenman bulunamadı")
    conn.execute("DELETE FROM workouts WHERE id = ? AND user_id = ?", (workout_id, user_id))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Antrenman silindi"}


def update_workout(workout_id: int, data: dict, user_id: int) -> dict:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM workouts WHERE id = ? AND user_id = ?",
        (workout_id, user_id)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Antrenman bulunamadı")

    fields, values = [], []
    if "date" in data:
        fields.append("date=?"); values.append(data["date"])
    if "session_type" in data:
        fields.append("session_type=?"); values.append(data["session_type"])
    if "notes" in data:
        fields.append("notes=?"); values.append(data["notes"])
    if "exercises" in data:
        exercises = data["exercises"]
        total_volume = 0.0
        for ex in exercises:
            for s in ex.get("sets_data", []):
                total_volume += float(s.get("weight_kg", 0)) * int(s.get("reps", 0))
        fields.append("exercises=?"); values.append(json.dumps(exercises, ensure_ascii=False))
        fields.append("total_volume=?"); values.append(total_volume)
    if fields:
        values.append(workout_id)
        conn.execute(f"UPDATE workouts SET {','.join(fields)} WHERE id=?", values)
        conn.commit()

    conn.close()
    return {"success": True, "message": "Antrenman güncellendi"}


def calculate_stats(user: dict) -> dict:
    h = user.get("height", 0)
    w = user.get("weight", 0)
    age = user.get("age", 0)
    gender = user.get("gender", "male")
    level = user.get("fitness_level", "Beginner")

    bmi = round(w / ((h / 100) ** 2), 1) if h > 0 and w > 0 else 0

    bmr = (88.362 + (13.397 * w) + (4.799 * h) - (5.677 * age)) if gender == "male" \
        else (447.593 + (9.247 * w) + (3.098 * h) - (4.330 * age))

    multipliers = {"Beginner": 1.2, "Intermediate": 1.375, "Advanced": 1.55}
    tdee = round(bmr * multipliers.get(level, 1.2))

    goal = user.get("goal", "bulk")
    target_calories = tdee
    if goal == "bulk":
        target_calories += 300
    elif goal == "cut":
        target_calories -= 500

    protein = round(w * (2.0 if goal == "bulk" else 2.2))
    fat = round(w * 0.9)
    carbs = round(max(0, (target_calories - protein * 4 - fat * 9)) / 4)
    # BMI kategorisi (dashboard kartı için)
    if bmi < 18.5:
        bmi_category = "Zayıf"
    elif bmi < 25:
        bmi_category = "Normal"
    elif bmi < 30:
        bmi_category = "Fazla Kilolu"
    else:
        bmi_category = "Obez"
    # Frontend uyumluluk alias'ı: stats.macro.protein/carbs/fat
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


# ── Uzman Sistemi: Gün tipine göre örnek hareket önerileri ──
# Aynı haftada aynı hareketin iki kez çıkmasını önlemek için
# Push/Pull/Legs günleri A ve B varyantlarında farklı açılış hareketleriyle başlar.
# İçeriği buradan kolayca düzenleyebilirsin.
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
        ("Hip Thrust", "3x8-10", "Kalça"),
        ("Bulgarian Split Squat", "3x8-10 (ayak başına)", "Denge + tek bacak"),
        ("Leg Extension", "3x12-15", "Quad izolasyonu"),
        ("Russian Twist", "3x15", "Karın stabilitesi"),
    ],
    "Upper": [
        ("Incline Bench Press", "3x6-8", "Üst göğüs bileşiği"),
        ("Bent-over Row", "3x6-8", "Sırt bileşiği"),
        ("Arnold Press", "3x8-10", "Omuz"),
        ("Cable Bicep Curl", "3x10-12", "Biceps"),
        ("Overhead Tricep Extension", "3x10-12", "Triceps"),
    ],
    "Lower": [
        ("Deadlift", "3x5", "Ana çekme bileşiği (ağır, az tekrar)"),
        ("Front Squat", "3x8-10", "Quad"),
        ("Leg Press", "3x10-12", "Hacim"),
        ("Hyperextension (Ağırlıklı)", "3x10-12", "Bel + kalça"),
        ("Calf Raises", "4x12-15", "Baldır"),
    ],
    "Full Body A": [
        ("Bench Press", "3x6-8", "İtme bileşiği"),
        ("Barbell Row", "3x6-8", "Çekme bileşiği"),
        ("Squat", "3x6-8", "Bacak bileşiği"),
    ],
    "Full Body B": [
        ("Overhead Press", "3x6-8", "Omuz"),
        ("Pull Ups (Ağırlıksız Barfiks)", "3xTükenişe kadar", "Sırt"),
        ("Romanian Deadlift", "3x8-10", "Arka zincir"),
    ],
    "Full Body C": [
        ("Incline Dumbbell Press", "3x8-10", "Üst göğüs"),
        ("Seated Row", "3x10-12", "Sırt"),
        ("Lunges / Leg Press", "3x10-12", "Bacak"),
    ],
    "Upper Body": [
        ("Bench Press", "3x6-8", "Göğüs bileşiği"),
        ("Barbell Row", "3x6-8", "Sırt bileşiği"),
        ("Overhead Press", "3x8-10", "Omuz"),
        ("Bicep Curl", "3x10-12", "Kol"),
    ],
    "Lower Body": [
        ("Squat", "3x6-8", "Ana bacak bileşiği"),
        ("Romanian Deadlift", "3x8-10", "Arka zincir"),
        ("Leg Press", "3x10-12", "Hacim"),
        ("Calf Raises", "4x12-15", "Baldır"),
    ],
}

HAFTA_GUNLERI = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

def generate_split(days_per_week: int, goal: str = "bulk") -> dict:
    """Gün bazlı haftalık program üretir.
    PPL x2'de Push A / Push B gibi varyantlarla aynı hareketin
    hafta içinde iki kez çıkması engellenir."""
    week_templates = {
        1: [{"type": "Full Body A"}],
        2: [{"type": "Upper Body"}, {"type": "Lower Body"}],
        3: [{"type": "Full Body A"}, {"type": "Full Body B"}, {"type": "Full Body C"}],
        4: [{"type": "Upper"}, {"type": "Lower"}, {"type": "Upper"}, {"type": "Lower"}],
        5: [{"type": "Push A"}, {"type": "Pull A"}, {"type": "Legs A"}, {"type": "Upper"}, {"type": "Lower"}],
        6: [{"type": "Push A"}, {"type": "Pull A"}, {"type": "Legs A"}, {"type": "Push B"}, {"type": "Pull B"}, {"type": "Legs B"}],
        7: [{"type": "Push A"}, {"type": "Pull A"}, {"type": "Legs A"}, {"type": "Rest"}, {"type": "Upper"}, {"type": "Lower"}, {"type": "Rest"}],
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
    split_name_map = {1: "Full Body", 2: "Upper/Lower", 3: "Full Body x3",
                      4: "Upper/Lower x2", 5: "PPL + Üst/Alt", 6: "PPL x2", 7: "PPL + Dinlenme"}
    rest_count = sum(1 for d in days if d["rest"])
    return {"name": split_name_map.get(days_per_week, "Upper/Lower x2"),
            "days": days, "rest_count": rest_count}


# ═══════════════════════════════════════════════
# EGZERSİZ HAVUZU — KOLAYCA EDİTLENEBİLİR
# ═══════════════════════════════════════════════
# Bir hareket eklemek için bu dict'e yeni entry ekle.
# is_bodyweight: vücut ağırlığıyla yapılan hareketler
# category: "compound" (çok kaslı) / "isolation" (tek kaslı)
EXERCISE_POOL = [
    {"id": "bench-press", "name": "Bench Press", "muscle_group": "Chest",
     "category": "compound", "is_bodyweight": False},
    {"id": "incline-bench-press", "name": "Incline Bench Press", "muscle_group": "Chest",
     "category": "compound", "is_bodyweight": False},
    {"id": "incline-dumbbell-press", "name": "Incline Dumbbell Press", "muscle_group": "Chest",
     "category": "compound", "is_bodyweight": False},
    {"id": "decline-bench-press", "name": "Decline Bench Press", "muscle_group": "Chest",
     "category": "compound", "is_bodyweight": False},
    {"id": "chest-press-machine", "name": "Chest Press Machine", "muscle_group": "Chest",
     "category": "isolation", "is_bodyweight": False},
    {"id": "dumbbell-flyes", "name": "Dumbbell Flyes", "muscle_group": "Chest",
     "category": "isolation", "is_bodyweight": False},
    {"id": "cable-cross-over", "name": "Cable Cross Over", "muscle_group": "Chest",
     "category": "isolation", "is_bodyweight": False},
    {"id": "pull-ups-bw", "name": "Pull Ups (Ağırlıksız Barfiks)", "muscle_group": "Back",
     "category": "compound", "is_bodyweight": True},
    {"id": "weighted-pull-up", "name": "Weighted Pull Up (Ağırlıklı Barfiks)", "muscle_group": "Back",
     "category": "compound", "is_bodyweight": False},
    {"id": "chin-ups-bw", "name": "Chin Ups (Ağırlıksız)", "muscle_group": "Back",
     "category": "compound", "is_bodyweight": True},
    {"id": "chin-ups-weighted", "name": "Chin Ups (Ağırlıklı)", "muscle_group": "Back",
     "category": "compound", "is_bodyweight": False},
    {"id": "lat-pull-down", "name": "Lat Pull Down", "muscle_group": "Back",
     "category": "compound", "is_bodyweight": False},
    {"id": "barbell-row", "name": "Barbell Row", "muscle_group": "Back",
     "category": "compound", "is_bodyweight": False},
    {"id": "t-bar-row", "name": "T-Bar Row", "muscle_group": "Back",
     "category": "compound", "is_bodyweight": False},
    {"id": "seated-row", "name": "Seated Row", "muscle_group": "Back",
     "category": "compound", "is_bodyweight": False},
    {"id": "bent-over-row", "name": "Bent-over Row", "muscle_group": "Back",
     "category": "compound", "is_bodyweight": False},
    {"id": "overhead-press", "name": "Overhead Press", "muscle_group": "Shoulders",
     "category": "compound", "is_bodyweight": False},
    {"id": "arnold-press", "name": "Arnold Press", "muscle_group": "Shoulders",
     "category": "compound", "is_bodyweight": False},
    {"id": "lateral-raises", "name": "Lateral Raises", "muscle_group": "Shoulders",
     "category": "isolation", "is_bodyweight": False},
    {"id": "cable-lateral-raises", "name": "Cable Lateral Raises", "muscle_group": "Shoulders",
     "category": "isolation", "is_bodyweight": False},
    {"id": "dumbbell-front-raises", "name": "Dumbbell Front Raises", "muscle_group": "Shoulders",
     "category": "isolation", "is_bodyweight": False},
    {"id": "dumbbell-rear-delt-fly", "name": "Dumbbell Rear Delt Fly", "muscle_group": "Shoulders",
     "category": "isolation", "is_bodyweight": False},
    {"id": "rear-delt-fly", "name": "Rear Delt Fly (Arka Omuz)", "muscle_group": "Shoulders",
     "category": "isolation", "is_bodyweight": False},
    {"id": "face-pulls", "name": "Face Pulls", "muscle_group": "Shoulders",
     "category": "isolation", "is_bodyweight": False},
    {"id": "squat", "name": "Squat", "muscle_group": "Legs", "category": "compound",
     "is_bodyweight": False},
    {"id": "front-squat", "name": "Front Squat", "muscle_group": "Legs",
     "category": "compound", "is_bodyweight": False},
    {"id": "bulgarian-split-squad", "name": "Bulgarian Split Squat", "muscle_group": "Legs",
     "category": "compound", "is_bodyweight": False},
    {"id": "leg-press", "name": "Leg Press", "muscle_group": "Legs",
     "category": "compound", "is_bodyweight": False},
    {"id": "romanian-deadlift", "name": "Romanian Deadlift", "muscle_group": "Legs",
     "category": "compound", "is_bodyweight": False},
    {"id": "leg-extension", "name": "Leg Extension", "muscle_group": "Legs",
     "category": "isolation", "is_bodyweight": False},
    {"id": "leg-curl", "name": "Leg Curl", "muscle_group": "Legs",
     "category": "isolation", "is_bodyweight": False},
    {"id": "hip-thrust", "name": "Hip Thrust", "muscle_group": "Legs",
     "category": "compound", "is_bodyweight": False},
    {"id": "dumbbell-calf-raises", "name": "Dumbbell Calf Raise", "muscle_group": "Legs",
     "category": "isolation", "is_bodyweight": False},
    {"id": "barbell-calf-raises", "name": "Barbell Calf Raise", "muscle_group": "Legs",
        "category": "isolation", "is_bodyweight": False},
    {"id": "deadlift", "name": "Deadlift", "muscle_group": "Back",
     "category": "compound", "is_bodyweight": False},
    {"id": "bicep-curl", "name": "Bicep Curl", "muscle_group": "Biceps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "hammer-curl", "name": "Hammer Curl", "muscle_group": "Biceps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "preacher-curl-dumbbell", "name": "Preacher Curl (Dumbbell)", "muscle_group": "Biceps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "preacher-curl-z-bar", "name": "Preacher Curl (Z Bar)", "muscle_group": "Biceps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "preacher-curl-machine", "name": "Preacher Curl Machine", "muscle_group": "Biceps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "incline-dumbbell-curl", "name": "Incline Dumbbell Curl", "muscle_group": "Biceps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "concentration-curl", "name": "Concentration Curl", "muscle_group": "Biceps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "cable-bicep-curl", "name": "Cable Bicep Curl", "muscle_group": "Biceps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "tricep-push-down", "name": "Tricep Push Down", "muscle_group": "Triceps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "skull-crushers", "name": "Skull Crushers", "muscle_group": "Triceps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "overhead-tricep-extension", "name": "Overhead Tricep Extension", "muscle_group": "Triceps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "cable-rope-overhead-tricep-extension", "name": "Cable Rope Overhead Tricep Extension",
     "muscle_group": "Triceps", "category": "isolation", "is_bodyweight": False},
    {"id": "dumbbell-kickbacks", "name": "Dumbbell Kickbacks", "muscle_group": "Triceps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "close-grip-bench-press", "name": "Close-grip Bench Press", "muscle_group": "Triceps",
     "category": "compound", "is_bodyweight": False},
    {"id": "dips-weighted", "name": "Dips (Ağırlıklı)", "muscle_group": "Triceps",
     "category": "compound", "is_bodyweight": False},
    {"id": "dips-bw", "name": "Dips (Ağırlıksız)", "muscle_group": "Triceps",
     "category": "compound", "is_bodyweight": True},
    {"id": "dumbbell-shrugs", "name": "Dumbbell Shrugs", "muscle_group": "Traps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "barbell-shrugs", "name": "Barbell Shrugs", "muscle_group": "Traps",
     "category": "isolation", "is_bodyweight": False},
    {"id": "upright-row-z-bar", "name": "Upright Row (Z Bar)", "muscle_group": "Shoulders",
     "category": "compound", "is_bodyweight": False},
    {"id": "cable-upright-row", "name": "Cable Upright Row", "muscle_group": "Shoulders",
     "category": "compound", "is_bodyweight": False},
    {"id": "barbell-upright-row", "name": "Barbell Upright Row", "muscle_group": "Shoulders",
     "category": "compound", "is_bodyweight": False},
    {"id": "russian-twist", "name": "Russian Twist", "muscle_group": "Core",
     "category": "isolation", "is_bodyweight": True},
    {"id": "kettlebell-swings", "name": "Kettlebell Swings", "muscle_group": "Core",
     "category": "compound", "is_bodyweight": False},
    {"id": "cable-crunches", "name": "Cable Crunches", "muscle_group": "Core",
     "category": "isolation", "is_bodyweight": False},
    {"id": "seated-crunch", "name": "Seated Crunch", "muscle_group": "Core",
     "category": "isolation", "is_bodyweight": False},
    {"id": "hyperextension-weighted", "name": "Hyperextension (Ağırlıklı)", "muscle_group": "Back",
     "category": "isolation", "is_bodyweight": False},
]

MUSCLE_GROUPS = sorted(set(ex["muscle_group"] for ex in EXERCISE_POOL))


# ═══════════════════════════════════════════════
# PYDANTIC MODELLER
# ═══════════════════════════════════════════════
class AuthRequest(BaseModel):
    username: str
    password: str


class UserProfile(BaseModel):
    username: str
    age: Optional[int] = None
    gender: Optional[str] = None
    height: Optional[float] = None
    weight: Optional[float] = None
    fitness_level: Optional[str] = None
    goal: Optional[str] = None
    days_per_week: Optional[int] = None
    session_time_mins: Optional[int] = None
    new_password: Optional[str] = None


class SetData(BaseModel):
    reps: int
    weight_kg: float = 0


class ExerciseEntry(BaseModel):
    exercise_id: str
    exercise_name: str
    muscle_group: str
    sets_data: List[SetData]
    is_bodyweight: bool = False


class WorkoutCreate(BaseModel):
    date: str
    session_type: str
    notes: Optional[str] = ""
    exercises: List[ExerciseEntry]


class WorkoutUpdate(BaseModel):
    date: Optional[str] = None
    session_type: Optional[str] = None
    notes: Optional[str] = None
    exercises: Optional[List[ExerciseEntry]] = None


class AdminEditUser(BaseModel):
    user_id: int
    age: Optional[int] = None
    gender: Optional[str] = None
    height: Optional[float] = None
    weight: Optional[float] = None
    fitness_level: Optional[str] = None
    goal: Optional[str] = None
    days_per_week: Optional[int] = None
    session_time_mins: Optional[int] = None
    new_password: Optional[str] = None


class AnalyzeRequest(BaseModel):
    stagnation_detected: Optional[bool] = False


class CustomDay(BaseModel):
    day: str
    type: str
    focus: str
    isRest: bool


class CustomProgramRequest(BaseModel):
    username: str
    program: List[List[CustomDay]]


class NutritionLogSchema(BaseModel):
    username: str
    log_date: str = ""
    calories: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    notes: str = ""


# ═══════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════
# ═══════════════════════════════════════════════
# LOGLAMA — Production için bilgi logları
# ═══════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("hypertrophy-x")
log.info("Hypertrophy-X v5.0 backend başlatılıyor...")


class CacheControlMiddleware(BaseHTTPMiddleware):
    """
    Modern platform caching katmanı:
      - API endpoint'leri (/api/*) → no-cache (her istek taze veri alır)
      - index.html (SPA) → no-store (güncel kod her zaman yüklensin)
      - Statik dosyalar (.js/.css/.png/...) → public max-age (uzun süre cache)
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache, no-store"
            response.headers["Pragma"] = "no-cache"
        elif "." in path.split("/")[-1]:  # statik dosya: chart.js, css, png...)
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:  # SPA sayfası — index.html asla cache'lenmesin
            response.headers["Cache-Control"] = "no-store"
        return response


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Tüm istekleri info seviyesinde logla (monitoring için)"""
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        ms = int((time.time() - start) * 1000)
        log.info(f"{request.method} {request.url.path} — {response.status_code} ({ms}ms)")
        return response


app = FastAPI(title="Hypertrophy-X API", version="5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[CORS_ORIGIN] if CORS_ORIGIN != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(CacheControlMiddleware)
log.info("Middleware katmanı aktif: CORS + Cache-Control + İstek Loglama")


# ═══════════════════════════════════════════════
# AUTH ENDPOINT'LERİ
# ═══════════════════════════════════════════════
@app.post("/api/auth/register")
def register(data: AuthRequest = Body(...)):
    if len(data.username) < 2:
        raise HTTPException(status_code=400, detail="Kullanıcı adı en az 2 karakter olmalı")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Şifre en az 6 karakter olmalı")
    if data.username == ADMIN_USERNAME:
        raise HTTPException(status_code=400, detail="Bu kullanıcı adı kullanılamaz")
    return create_user(data.username, data.password)


@app.post("/api/auth/login")
def login(data: AuthRequest = Body(...)):
    # ─── Admin giriş ───
    if data.username == ADMIN_USERNAME:
        if data.password == ADMIN_PASSWORD:
            token = _create_access_token(ADMIN_USERNAME, is_admin=True)
            return {"username": ADMIN_USERNAME, "is_admin": True, "token": token}
        raise HTTPException(status_code=401, detail="Admin şifresi hatalı")

    # ─── Normal kullanıcı ───
    user = get_user_by_username(data.username)
    if not user:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı")
    if not _verify_password(data.password, user["password_hash"], user["password_salt"]):
        raise HTTPException(status_code=401, detail="Şifre hatalı")

    # Eski SHA256 hash ise bcrypt'e yükselt
    conn = get_db()
    _upgrade_to_bcrypt_if_needed(conn, user["id"], data.password)
    conn.commit()
    conn.close()

    # JWT token üret
    token = _create_access_token(data.username, is_admin=False)

    user.pop("password_hash", None)
    user.pop("password_salt", None)
    return {**user, "token": token}


@app.post("/api/auth/change-password")
def change_password(user: dict = Depends(_resolve_current_user),
                    data: dict = Body(...)):
    """Şifre değiştirme — JWT gerektirir"""
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")

    if user.get("username") == ADMIN_USERNAME:
        raise HTTPException(status_code=403, detail="Admin şifresi değiştirilemez")

    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Yeni şifre en az 6 karakter olmalı")

    conn = get_db()
    row = conn.execute(
        "SELECT password_hash, password_salt FROM users WHERE username = ?",
        (user["username"],)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    if not _verify_password(old_password, row["password_hash"], row["password_salt"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Mevcut şifre hatalı")

    conn.execute(
        "UPDATE users SET password_hash = ?, password_salt = '', updated_at = datetime('now') "
        "WHERE username = ?",
        (_hash_password(new_password), user["username"])
    )
    conn.commit()
    conn.close()
    return {"message": "Şifre güncellendi"}


# ═══════════════════════════════════════════════
# KULLANICI ENDPOINT'LERİ — JWT korumalı
# ═══════════════════════════════════════════════
@app.get("/api/user")
def get_user(user: dict = Depends(_resolve_current_user)):
    return user


@app.post("/api/user")
def save_user(data: UserProfile = Body(...),
              current_user: dict = Depends(_resolve_current_user)):
    # Token'daki kullanıcı sadece KENDİ profilini düzenleyebilir
    if data.username != current_user["username"]:
        raise HTTPException(status_code=403, detail="Başkasının profili düzenlenemez")
    result = update_user_profile(data.model_dump(), data.username)
    result.pop("password_hash", None)
    result.pop("password_salt", None)
    return result


# ═══════════════════════════════════════════════
# ANTRENMAN ENDPOINT'LERİ — JWT korumalı
# ═══════════════════════════════════════════════
@app.post("/api/workouts")
def save_workout(data: WorkoutCreate = Body(...),
                 user: dict = Depends(_resolve_current_user)):
    return create_workout(user["id"], data.model_dump())


@app.get("/api/workouts")
def list_workouts(user: dict = Depends(_resolve_current_user)):
    return get_workouts_by_user(user["id"])


@app.delete("/api/workouts/{workout_id}")
def delete_workout_endpoint(workout_id: int,
                            user: dict = Depends(_resolve_current_user)):
    return delete_workout(workout_id, user["id"])


@app.put("/api/workouts/{workout_id}")
def update_workout_endpoint(workout_id: int,
                            data: WorkoutUpdate = Body(...),
                            user: dict = Depends(_resolve_current_user)):
    return update_workout(workout_id, data.model_dump(exclude_unset=True), user["id"])


# ═══════════════════════════════════════════════
# ADMIN ENDPOINT'LERİ — JWT + Admin rol kontrolü
# ═══════════════════════════════════════════════
@app.get("/api/admin/users")
def admin_list_users(admin_user: dict = Depends(_resolve_current_user)):
    admin = _require_admin(admin_user)
    users = get_all_users()
    for u in users:
        u.pop("password_hash", None)
        u.pop("password_salt", None)
    return users


@app.get("/api/admin/workouts/{user_id}")
def admin_get_user_workouts(user_id: int,
                            admin: dict = Depends(_resolve_current_user)):
    """Admin: Belirli bir kullanıcının tüm antrenmanlarını getir."""
    _require_admin(admin)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    workouts = get_workouts_by_user(user_id)
    return {"user": user["username"], "workouts": workouts}


@app.put("/api/admin/workout/{workout_id}")
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


@app.delete("/api/admin/workout/{workout_id}")
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


@app.put("/api/admin/user")
def admin_edit_user(data: AdminEditUser = Body(...),
                    admin: dict = Depends(_resolve_current_user)):
    """Admin: Kullanıcı bilgilerini düzenle."""
    _require_admin(admin)
    user = get_user_by_id(data.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    conn = get_db()
    fields = []
    values = []

    update_data = data.model_dump(exclude_unset=True)
    update_data.pop("user_id", None)
    new_pass = update_data.pop("new_password", None)

    for key, val in update_data.items():
        if val is not None:
            fields.append(f"{key}=?")
            values.append(val)

    if new_pass:
        if len(new_pass) < 6:
            conn.close()
            raise HTTPException(status_code=400, detail="Yeni şifre en az 6 karakter olmalı")
        fields.append("password_hash=?")
        values.append(_hash_password(new_pass))
        fields.append("password_salt=?")
        values.append("")

    if fields:
        values.append(data.user_id)
        conn.execute(f"UPDATE users SET {','.join(fields)} WHERE id=?", values)
        conn.commit()

    conn.close()
    result = get_user_by_id(data.user_id)
    result.pop("password_hash", None)
    result.pop("password_salt", None)
    return result


@app.delete("/api/admin/user/{user_id}")
def admin_delete_user(user_id: int,
                      admin: dict = Depends(_resolve_current_user)):
    """Admin: Kullanıcı sil."""
    _require_admin(admin)
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.execute("DELETE FROM workouts WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"message": "Kullanıcı ve antrenmanları silindi"}


# ═══════════════════════════════════════════════
# ANALİZ
# ═══════════════════════════════════════════════
@app.post("/api/analyze")
def analyze(data: AnalyzeRequest = Body(...),
            user: dict = Depends(_resolve_current_user)):
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
@app.get("/api/dashboard")
def dashboard(user: dict = Depends(_resolve_current_user)):
    workouts = get_workouts_by_user(user["id"])
    now = datetime.now()

    week_start = now - timedelta(days=now.weekday())
    weekly = [w for w in workouts if datetime.strptime(w["date"], "%Y-%m-%d") >= week_start]

    month_start = now.replace(day=1)
    monthly = [w for w in workouts if datetime.strptime(w["date"], "%Y-%m-%d") >= month_start]

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

    def get_muscle_distribution(workout_list):
        dist = {}
        for w in workout_list:
            exercises_raw = w.get("exercises", [])
            if isinstance(exercises_raw, str):
                try:
                    exercises_list = json.loads(exercises_raw)
                except Exception:
                    exercises_list = []
            else:
                exercises_list = exercises_raw
            for ex in exercises_list:
                m = ex.get("muscle_group", ex.get("muscle", "Bilinmiyor"))
                dist[m] = dist.get(m, 0) + 1
        return dist

    muscle_dist_all = get_muscle_distribution(workouts)
    muscle_dist_weekly = get_muscle_distribution(weekly)
    muscle_dist_monthly = get_muscle_distribution(monthly)

    stats = calculate_stats(user)
    sessions_data = [
        {"date": w["date"], "type": w.get("session_type", "Workout")} for w in workouts
    ]

    return {
        "success": True,
        "user": user,
        "stats": stats,
        "summary": {
            "total": len(workouts),
            "weekly": len(weekly),
            "monthly": len(monthly),
            "streak": streak,
            "total_volume": sum(w["total_volume"] for w in workouts)
        },
        "split_info": split_info,
        "rest_days": rest_days,
        "muscle_distribution": {
            "all": muscle_dist_all,
            "weekly": muscle_dist_weekly,
            "monthly": muscle_dist_monthly
        },
        "sessions": sessions_data
    }


# ═══════════════════════════════════════════════
# İLERLEME
# ═══════════════════════════════════════════════
@app.get("/api/progress")
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
        "stats": calculate_stats(user)
    }


@app.get("/api/progress/chart")
def get_exercise_chart_data(exercise: str = Query(...),
                            user: dict = Depends(_resolve_current_user)):
    workouts = get_workouts_by_user(user["id"])
    workouts_sorted = sorted(workouts, key=lambda x: x["date"])

    labels = []
    weights = []
    details = []
    target_exercise = exercise.lower().strip()

    for w in workouts_sorted:
        exercises_raw = w.get("exercises", "[]")
        if isinstance(exercises_raw, str):
            try:
                exercises_list = json.loads(exercises_raw)
            except Exception:
                exercises_list = []
        else:
            exercises_list = exercises_raw

        for ex in exercises_list:
            ex_name = ex.get("exercise_name", ex.get("name", "")).lower().strip()
            if ex_name == target_exercise:
                sets = ex.get("sets_data", [])
                date_str = w["date"].split()[0]
                parts = date_str.split("-")
                formatted_date = f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else date_str

                for idx, s in enumerate(sets, 1):
                    try:
                        weight = float(s.get("weight_kg", 0))
                        reps = int(s.get("reps", 0))
                        if weight > 0:
                            labels.append(formatted_date)
                            weights.append(weight)
                            details.append({"set": idx, "reps": reps})
                    except Exception:
                        continue

    return {"labels": labels, "data": weights, "details": details}


def get_personal_records(workouts):
    """Her egzersiz için en yüksek ağırlığı bul."""
    records = {}
    for w in workouts:
        for ex in w.get("exercises", []):
            name = ex.get("exercise_name", "")
            sets_list = ex.get("sets_data", [])
            if sets_list:
                max_weight = max(float(s.get("weight_kg", 0)) for s in sets_list)
                if name not in records or max_weight > records[name]["max_weight"]:
                    records[name] = {
                        "exercise": name,
                        "muscle": ex.get("muscle_group", ""),
                        "max_weight": max_weight,
                        "max_reps": max(int(s.get("reps", 0)) for s in sets_list),
                        "date": w["date"]
                    }
    return list(records.values())


# ═══════════════════════════════════════════════
# ÖZEL PROGRAM
# ═══════════════════════════════════════════════
@app.post("/api/custom-program")
def save_custom_program(data: CustomProgramRequest,
                        current_user: dict = Depends(_resolve_current_user)):
    # Token'daki kullanıcı sadece kendi programını kaydeder
    if data.username != current_user["username"]:
        raise HTTPException(status_code=403, detail="Başkası için program kaydedilemez")

    program_list = [[day.model_dump() for day in week] for week in data.program]
    program_json = json.dumps(program_list, ensure_ascii=False)

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET custom_split = ? WHERE id = ?",
                    (program_json, current_user["id"]))
        conn.commit()
        return {"success": True,
                "message": f"{len(data.program)} Haftalık periyot başarıyla kaydedildi!"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500,
                            detail=f"Kayıt sırasında veritabanı hatası: {str(e)}")
    finally:
        conn.close()


# İngilizce kas grubu -> Türkçe karşılık (havuz editlenirken bu listeden yararlan)
EXERCISE_MUSCLE_TR = {
    "Chest": "Göğüs", "Back": "Sırt", "Shoulders": "Omuz",
    "Legs": "Bacak", "Biceps": "Biceps", "Triceps": "Triceps",
    "Traps": "Traps", "Core": "Core",
}

# LEGS alt kas eşlemesi: EXERCISE_POOL'da bacak hareketleri tek "Legs" grubunda toplanır
# (editlenebilirlik için). Frontend ise bacak gününde Quadriceps/Hamstring/Glute/Calf
# alt kaslarını bekler. Bu tablo hareket adından alt kası belirler; adı listede olmayan
# Legs hareketleri varsayılan olarak Quadriceps kabul edilir.
LEG_SUBMUSCLE = {
    "quadriceps": {"squat", "front squat", "bulgarian split squat", "leg press", "leg extension", "lunge", "hack squat", "goblet squat"},
    "hamstring": {"romanian deadlift", "leg curl", "stiff leg", "good morning", "nordic curl"},
    "glute": {"hip thrust", "glute bridge", "kickback"},
    "calf": {"calf raise", "calf raises"},
}


def _enrich_exercise_pool(pool):
    """Frontend uyumluluğu: her hareket için muscle/bw/weighted alias üretir.
    Havuzun kendisine dokunulmaz; havuz backend'de kolayca editlenebilir kalır."""
    out = []
    for ex in pool:
        e = dict(ex)
        mg = ex.get("muscle_group", "")
        if mg == "Legs":
            # Backend'in editlenebilir tek "Legs" grubunu frontend'in beklediği
            # alt kas gruplarına (Quadriceps/Hamstring/Glute/Calf) eşle
            name_low = ex.get("name", "").lower()
            sub = "Quadriceps"
            for muscle, keywords in LEG_SUBMUSCLE.items():
                if any(k in name_low for k in keywords):
                    sub = muscle.title() if muscle != "calf" else "Calf"
                    break
            e["muscle"] = sub
        else:
            e["muscle"] = EXERCISE_MUSCLE_TR.get(mg, mg)
        e["bw"] = bool(ex.get("is_bodyweight", False))
        e["weighted"] = not bool(ex.get("is_bodyweight", False))
        out.append(e)
    return out

@app.get("/api/exercises")
def get_exercises():
    """Egzersiz havuzu + kas grupları (Türkçe alias'larla)."""
    return {"exercises": _enrich_exercise_pool(EXERCISE_POOL),
            "muscle_groups": [EXERCISE_MUSCLE_TR.get(g, g) for g in MUSCLE_GROUPS]}


# ═══════════════════════════════════════════════
# BESLENME ENDPOINT'LERİ — JWT korumalı
# ═══════════════════════════════════════════════
@app.get("/api/nutrition/today")
def get_today_nutrition(user: dict = Depends(_resolve_current_user)):
    raw_nutri = user.get("daily_nutrition", "{}")
    try:
        history_dict = json.loads(raw_nutri) if isinstance(raw_nutri, str) else raw_nutri
    except Exception:
        history_dict = {}

    today_str = str(date.today())
    today_log = history_dict.get(today_str,
                                 {"calories": 0, "protein": 0, "carbs": 0, "fat": 0})
    return {"success": True, "log": today_log}


@app.get("/api/nutrition/history")
def get_nutrition_history(user: dict = Depends(_resolve_current_user)):
    raw_nutri = user.get("daily_nutrition", "{}")
    try:
        history_dict = json.loads(raw_nutri) if isinstance(raw_nutri, str) else raw_nutri
    except Exception:
        history_dict = {}

    history_list = []
    for date_str, data in history_dict.items():
        item = {"date": date_str}
        item.update(data)
        history_list.append(item)

    history_list.sort(key=lambda x: x["date"], reverse=True)
    return {"success": True, "history": history_list}


@app.post("/api/nutrition/log")
def save_nutrition_log(data: NutritionLogSchema,
                       current_user: dict = Depends(_resolve_current_user)):
    # Token'daki kullanıcı sadece kendi verisini yazar
    if data.username != current_user["username"]:
        raise HTTPException(status_code=403, detail="Başkası için kayıt yapılamaz")

    raw_nutri = current_user.get("daily_nutrition", "{}")
    try:
        history_dict = json.loads(raw_nutri) if isinstance(raw_nutri, str) else raw_nutri
    except Exception:
        history_dict = {}

    target_date = data.log_date or str(date.today())
    if target_date > str(date.today()):
        raise HTTPException(status_code=400, detail="Gelecek gün için kayıt yapılamaz")

    calories = data.calories
    if calories <= 0:
        calories = (data.protein * 4) + (data.carbs * 4) + (data.fat * 9)

    history_dict[target_date] = {
        "calories": calories,
        "protein": data.protein,
        "carbs": data.carbs,
        "fat": data.fat,
        "notes": data.notes or "",
        "updated_at": str(datetime.now())
    }

    conn = get_db()
    conn.execute(
        "UPDATE users SET daily_nutrition = ?, updated_at = datetime('now') WHERE username = ?",
        (json.dumps(history_dict, ensure_ascii=False), current_user["username"])
    )
    conn.commit()
    conn.close()
    return {"success": True, "message": "Beslenme verisi kaydedildi"}


@app.delete("/api/nutrition/log")
def delete_nutrition_log(log_date: str = Query(...),
                         user: dict = Depends(_resolve_current_user)):
    raw_nutri = user.get("daily_nutrition", "{}")
    try:
        history_dict = json.loads(raw_nutri) if isinstance(raw_nutri, str) else raw_nutri
    except Exception:
        history_dict = {}

    if log_date in history_dict:
        del history_dict[log_date]
        conn = get_db()
        conn.execute(
            "UPDATE users SET daily_nutrition = ?, updated_at = datetime('now') WHERE username = ?",
            (json.dumps(history_dict, ensure_ascii=False), user["username"])
        )
        conn.commit()
        conn.close()

    return {"success": True, "message": "Kayıt başarıyla silindi"}


# ═══════════════════════════════════════════════
# SAĞLIK KONTROLÜ — Monitoring için
# ═══════════════════════════════════════════════
@app.get("/api/health")
def health_check():
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok", "db": "ok", "version": "5.0"}
    except Exception as e:
        return {"status": "degraded", "db": "error", "detail": str(e)}


# ═══════════════════════════════════════════════
# STATIC DOSYALAR + SPA CATCH-ALL
# ÖNEMLİ: StaticFiles mount'u her şeyi yakalar. Bu yüzden SPA route'ları
# mount'tan ÖNCE bir APIRouter içine alınıyor — böylece /dashboard,
# /nutrition vb. statik dosya araması yapmadan doğrudan index.html döner.
# API istekleri ve gerçek dosyalar (css/js/img) mount tarafından sunulur.
# ═══════════════════════════════════════════════
SPA_PAGES = {"dashboard", "workout", "history", "analyze", "progress",
             "nutrition", "profile", "admin", "custom-program", "app", ""}

from fastapi import APIRouter

spa_router = APIRouter()


@spa_router.get("/")
def spa_root():
    return FileResponse("static/index.html")


# Gerçek statik dosyalar (favicon, css, img, js) catch-all'a düşmeden
# önce burada karşılanır — mount ile sıralama çakışmasını önler.
from pathlib import Path as _Path
STATIC_DIR = _Path(__file__).parent / "static"


@app.get("/static/{filename}")
@app.get("/{filename}")
def serve_static_file(filename: str):
    file_path = STATIC_DIR / filename
    if file_path.is_file():
        return FileResponse(file_path)
    # Dosya değilse SPA sayfası olabilir (tek segmentli path: /dashboard)
    if filename in SPA_PAGES:
        return FileResponse("static/index.html")
    raise HTTPException(status_code=404, detail="Not Found")


# NOT: StaticFiles mount'u catch-all router'ı gölgeleyebildiği için
# SPA yönlendirme doğrudan app'e ekleniyor — mount'tan önce çalışır.
@app.get("/{path:path}")
def serve_spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    first = path.split("/")[0]
    if first in SPA_PAGES:
        return FileResponse("static/index.html")
    raise HTTPException(status_code=404, detail="Not Found")


app.include_router(spa_router)
# StaticFiles mount'u kaldırıldı: FastAPI'de mount tüm yol eşleşmelerini
# yakaladığı için SPA route'larını ({path:path}) gölgede bırakıyordu.
# Dosyalar artık serve_static_file (satır 1483) ile sunuluyor.


# ═══════════════════════════════════════════════
# BAŞLATMA
# ═══════════════════════════════════════════════
init_db()

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
from pathlib import Path as _Path
import json
import sqlite3
import re
import unicodedata

try:
    import psycopg
    from psycopg import IntegrityError as PostgreSQLIntegrityError
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None
    PostgreSQLIntegrityError = RuntimeError
import logging
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import FastAPI, APIRouter, Body, HTTPException, Query, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime, timedelta

from jose import jwt, JWTError, ExpiredSignatureError
import bcrypt
from postgres_schema import POSTGRES_SCHEMA_STATEMENTS
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
    normalize_muscle_group,
    validate_detailed_preferences,
    validate_preferences as validate_expert_preferences,
    validate_score as validate_expert_score,
)
from expert_system import build_recommendation_program, format_tr_date, rpe_summary_from_rir
from program_schedule_sync import align_rest_slots, current_week_actuals, is_rest_day, reconcile_week

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

# Ortam değişkenlerinde sistemin verdiği değerler her zaman önceliklidir.
# Yerelde .env dosyası tercih edilir. Eski admin.env yalnızca development
# kolaylığı için fallback olarak okunur; production'da asla otomatik yüklenmez.
try:
    from dotenv import load_dotenv

    env_path = os.path.join(BACKEND_DIR, ".env")
    legacy_env_path = os.path.join(BACKEND_DIR, "admin.env")
    requested_env = os.getenv("APP_ENV", "").strip().lower()
    if os.path.isfile(env_path):
        load_dotenv(dotenv_path=env_path, override=False)
    elif requested_env != "production" and os.path.isfile(legacy_env_path):
        load_dotenv(dotenv_path=legacy_env_path, override=False)
except ImportError:
    pass  # python-dotenv yoksa platformun ortam değişkenleri kullanılır

# ═══════════════════════════════════════════════
# SABİTLER — ORTAM DEĞİŞKENLERİNDEN OKUNUR
# ═══════════════════════════════════════════════
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
if APP_ENV not in {"development", "test", "production"}:
    raise RuntimeError("APP_ENV yalnızca development, test veya production olabilir.")
IS_PRODUCTION = APP_ENV == "production"

# Veritabanı seçimi:
# - DATABASE_URL tanımlıysa PostgreSQL kullanılır.
# - Tanımlı değilse mevcut SQLite dosyasıyla yerel geliştirme devam eder.
# Bu fallback, eski veritabanını korur; production modunda ise PostgreSQL zorunludur.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_BACKEND = "postgresql" if DATABASE_URL else "sqlite"
DB_PATH = os.getenv("DB_PATH", os.path.join(BACKEND_DIR, "hypertrophy.db"))

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip()
# Şifre yalnızca ortam değişkeninden gelir; production kontrolü startup'ta yapılır.
ADMIN_PASSWORD_PLAIN = os.getenv("ADMIN_PASSWORD", "")
ADMIN_PASSWORD_HASH = None

# Development'ta eksik secret geçici olarak üretilir; production'da bu yasaktır.
SECRET_KEY = os.getenv("JWT_SECRET", "").strip()
if not SECRET_KEY and not IS_PRODUCTION:
    SECRET_KEY = secrets.token_urlsafe(48)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 24 * 60  # 24 saat

# Birden çok izinli origin virgülle ayrılabilir.
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*").strip()
CORS_ORIGINS = [origin.strip().rstrip("/") for origin in CORS_ORIGIN.split(",") if origin.strip()]
if not CORS_ORIGINS:
    CORS_ORIGINS = ["*"]

ENABLE_HSTS = os.getenv("ENABLE_HSTS", "false").strip().lower() in {"1", "true", "yes"}
# Aynı istemciden kısa süreli çoklu giriş/kayıt denemesini sınırlar.
LOGIN_RATE_LIMIT_MAX = max(1, int(os.getenv("LOGIN_RATE_LIMIT_MAX", "10")))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = max(60, int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "900")))
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower() in {"1", "true", "yes"}
BCRYPT_ROUNDS = 12  # Kasıtlı olarak yavaş — kaba kuvvet saldırısını zorlaştırır


# Üretimde yanlış veya örnek ayarlarla sunucuyu başlatmak veri güvenliği riskidir.
# Kontrol startup'ta çalışır; geliştirme/test çalışma akışı değişmez.
def validate_runtime_configuration() -> None:
    if not IS_PRODUCTION:
        return

    errors = []
    insecure_secrets = {"", "change-me", "changeme", "secret", "jwt_secret", "example", "test"}
    insecure_admin_passwords = {
        "", "admin", "admin123", "password", "password123", "123456",
        "12345678", "değiştirilmek-zorunda", "degistirilmek-zorunda",
    }

    if len(SECRET_KEY) < 32 or SECRET_KEY.lower() in insecure_secrets:
        errors.append("JWT_SECRET production için en az 32 karakterlik rastgele bir değer olmalıdır.")
    if len(ADMIN_PASSWORD_PLAIN) < 12 or ADMIN_PASSWORD_PLAIN.strip().lower() in insecure_admin_passwords:
        errors.append("ADMIN_PASSWORD production için varsayılan olmayan, en az 12 karakterlik güçlü bir değer olmalıdır.")
    if "*" in CORS_ORIGINS:
        errors.append("CORS_ORIGIN=*, production ortamında kullanılamaz.")
    if any(not origin.startswith("https://") for origin in CORS_ORIGINS):
        errors.append("CORS_ORIGIN production ortamında yalnızca https:// ile başlayan alan adları içermelidir.")
    if not DATABASE_URL:
        errors.append("DATABASE_URL production ortamında PostgreSQL bağlantısı için zorunludur.")
    if DATABASE_URL and psycopg is None:
        errors.append("psycopg paketi yüklü değil; PostgreSQL bağlantısı kurulamaz.")

    if errors:
        raise RuntimeError("Güvensiz production yapılandırması: " + " ".join(errors))

# ═══════════════════════════════════════════════
# ŞİFRE İŞLEMLERİ — bcrypt + ESKİ SHA256 MİGRASYON
# ═══════════════════════════════════════════════
def _hash_password(password: str):
    """Yeni şifre hash'leme — bcrypt (12 round)"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def _verify_admin_password(plain: str, stored_hash: str) -> bool:
    """Admin şifresini bcrypt hash ile doğrular."""
    try:
        return bcrypt.checkpw(plain.encode(), stored_hash.encode())
    except Exception:
        return False


def _init_admin_password_hash():
    """Admin şifresini ilk başlatmada bcrypt ile hash'ler. Düz metin
    karşılaştırma kalmaması için login her zaman hash üzerinden doğrulanır."""
    global ADMIN_PASSWORD_HASH
    ADMIN_PASSWORD_HASH = bcrypt.hashpw(
        ADMIN_PASSWORD_PLAIN.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    ).decode()


_init_admin_password_hash()


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
class PostgreSQLCursor:
    """Mevcut SQLite tarzı ? placeholder kullanan sorguları PostgreSQL'e uyarlar."""
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query: str, params=None):
        self._cursor.execute(query.replace("?", "%s"), params or ())
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class PostgreSQLConnection:
    """Uygulamadaki mevcut get_db() sözleşmesini PostgreSQL için korur."""
    def __init__(self, connection):
        self._connection = connection

    def execute(self, query: str, params=None):
        return self._connection.execute(query.replace("?", "%s"), params or ())

    def cursor(self):
        return PostgreSQLCursor(self._connection.cursor())

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def get_db():
    if DATABASE_BACKEND == "postgresql":
        if psycopg is None:
            raise RuntimeError("PostgreSQL için psycopg paketi yüklü olmalıdır.")
        return PostgreSQLConnection(
            psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=8)
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    if DATABASE_BACKEND == "postgresql":
        # Şema ve aktarım aracı aynı merkezi tanımı kullanır.
        for statement in POSTGRES_SCHEMA_STATEMENTS:
            cur.execute(statement)
    else:
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
                dashboard_preferences TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                session_type TEXT NOT NULL,
                notes TEXT DEFAULT '',
                gym_id TEXT DEFAULT NULL,
                gym_name TEXT DEFAULT '',
                total_volume REAL NOT NULL DEFAULT 0,
                exercises TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)
        # Uzman Sistemi; kullanıcı başına tek kayıt ve JSON koleksiyonları kullanır.
        # Bu veri toplama sürümünde kas ağrısı, salonlar ve sakatlıklar ayrı
        # tablolara bölünmez. Böylece yalnızca uzman sistemi verisi sadeleşir;
        # uygulamanın kullanıcı, antrenman ve beslenme tabloları etkilenmez.
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS expert_profiles (
                user_id INTEGER PRIMARY KEY,
                target_muscles_json TEXT NOT NULL DEFAULT '{}',
                doms_daily_json TEXT NOT NULL DEFAULT '{}',
                gym_equipment_json TEXT NOT NULL DEFAULT '[]',
                injuries_json TEXT NOT NULL DEFAULT '[]',
                rpe_checkins_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)

        # Eski tek-kayıt denemesi farklı JSON sütunlarıyla kurulmuş olabilir.
        # Bu sürümde yalnızca uzman sistemi verisinin sıfırlanmasına izin verildiği
        # için eski şema, kullanıcıya ait diğer hiçbir tabloya dokunulmadan yeniden
        # oluşturulur. Yeni şema zaten varsa bu blok işlem yapmaz.
        expert_columns = {
            str(row["name"]) for row in cur.execute("PRAGMA table_info(expert_profiles)").fetchall()
        }
        required_expert_columns = {
            "user_id", "target_muscles_json", "doms_daily_json",
            "gym_equipment_json", "injuries_json", "created_at", "updated_at",
        }
        if expert_columns and not required_expert_columns.issubset(expert_columns):
            cur.execute("DROP TABLE expert_profiles")
            cur.executescript("""
                CREATE TABLE expert_profiles (
                    user_id INTEGER PRIMARY KEY,
                    target_muscles_json TEXT NOT NULL DEFAULT '{}',
                    doms_daily_json TEXT NOT NULL DEFAULT '{}',
                    gym_equipment_json TEXT NOT NULL DEFAULT '[]',
                    injuries_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
            """)

        # Eski SQLite dosyaları için geriye dönük şema uyumluluğu.
        for statement in (
            "ALTER TABLE users ADD COLUMN custom_split TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE users ADD COLUMN dashboard_preferences TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE users ADD COLUMN daily_nutrition TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE workouts ADD COLUMN gym_id TEXT DEFAULT NULL",
            "ALTER TABLE workouts ADD COLUMN gym_name TEXT DEFAULT ''",
            "ALTER TABLE expert_profiles ADD COLUMN rpe_checkins_json TEXT NOT NULL DEFAULT '[]'",
        ):
            try:
                cur.execute(statement)
            except sqlite3.OperationalError:
                pass

    # Admin hesabı env parolasını otorite kabul eder. Böylece PostgreSQL'e taşınan
    # eski hash, yeni production parolasıyla çelişmez.
    conn.commit()
    admin_exists = cur.execute(
        "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
    ).fetchone()
    admin_hash = _hash_password(ADMIN_PASSWORD_PLAIN)
    if not admin_exists:
        cur.execute(
            "INSERT INTO users (username, password_hash, password_salt, is_admin) "
            "VALUES (?, ?, '', 1)",
            (ADMIN_USERNAME, admin_hash)
        )
    else:
        cur.execute(
            "UPDATE users SET is_admin = 1, password_hash = ?, password_salt = '' WHERE username = ?",
            (admin_hash, ADMIN_USERNAME)
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
    except (sqlite3.IntegrityError, PostgreSQLIntegrityError):
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


def _parse_dashboard_preferences(raw_preferences) -> dict:
    """Bozuk/eski tercih kayıtlarında dashboard’un çalışmaya devam etmesini sağlar."""
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



# HX_REAL_WORKOUT_SCHEDULE_SYNC_V1
# Antrenman geçmişi gerçekleşen gerçektir. Takvimdeki Pazartesi–Pazar slotları
# sabit kalır; yalnız seans/dinlenme içerikleri uygun slotlar arasında taşınır.
def _schedule_week_index(total_weeks: int) -> int:
    return date.today().isocalendar().week % max(1, total_weeks)


def _read_custom_program(raw_program: object) -> list:
    if isinstance(raw_program, list):
        return raw_program
    try:
        parsed = json.loads(raw_program or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _sync_programs_with_real_workouts(user_id: int) -> dict:
    """Bu haftanın kayıtlarını yalnız kullanıcının takvim içeriklerine uygular.

    Geçmiş workout satırları değiştirilmez. Değişiklik varsa aynı kullanıcıya ait
    özel program ve/veya uzman önerisi tek veritabanı işlemiyle kalıcılaştırılır.
    """
    user = get_user_by_id(user_id)
    if not user:
        return {"changed": False}
    actuals = current_week_actuals(get_workouts_by_user(user_id))
    if not actuals:
        return {"changed": False}

    today_index = date.today().weekday()
    custom_program = _read_custom_program(user.get("custom_split", "[]"))
    custom_changed = False
    custom_rest_indices: set[int] = set()
    if custom_program:
        custom_week_index = _schedule_week_index(len(custom_program))
        custom_days = custom_program[custom_week_index]
        if isinstance(custom_days, list) and len(custom_days) == 7:
            reconciled, custom_changed = reconcile_week(custom_days, actuals, today_index)
            if custom_changed:
                custom_program[custom_week_index] = reconciled
            current_custom_days = custom_program[custom_week_index]
            if isinstance(current_custom_days, list) and len(current_custom_days) == 7:
                custom_rest_indices = {
                    index for index, item in enumerate(current_custom_days) if is_rest_day(item)
                }

    preferences = _parse_dashboard_preferences(user.get("dashboard_preferences", "{}"))
    recommendation = preferences.get("expert_recommendation")
    expert_changed = False
    if isinstance(recommendation, dict) and isinstance(recommendation.get("weeks"), list):
        weeks = recommendation.get("weeks") or []
        if weeks:
            recommendation = _expert_normalize_recommendation_slots(recommendation)
            week_index = _schedule_week_index(len(weeks))
            active_week = recommendation.get("weeks", [])[week_index]
            if isinstance(active_week, dict) and isinstance(active_week.get("days"), list):
                expert_days = active_week.get("days")
                if len(expert_days) == 7:
                    # Özel programdaki kullanıcı seçimi (ör. Salı dinlenme) uzman
                    # taslağında da öncelikle korunur. Gerçek antrenman yine üstündür.
                    rest_aligned = align_rest_slots(expert_days, custom_rest_indices)
                    reconciled, reconciled_changed = reconcile_week(
                        expert_days, actuals, today_index, protected_rest_indices=custom_rest_indices
                    )
                    if rest_aligned or reconciled_changed:
                        active_week["days"] = reconciled
                        expert_changed = True

    if not custom_changed and not expert_changed:
        return {"changed": False}

    conn = get_db()
    try:
        if custom_changed:
            conn.execute(
                "UPDATE users SET custom_split = ? WHERE id = ?",
                (json.dumps(custom_program, ensure_ascii=False), user_id),
            )
        if expert_changed:
            preferences["expert_recommendation"] = recommendation
            conn.execute(
                "UPDATE users SET dashboard_preferences = ? WHERE id = ?",
                (json.dumps(preferences, ensure_ascii=False), user_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "changed": True,
        "custom_split": json.dumps(custom_program, ensure_ascii=False) if custom_changed else user.get("custom_split", "[]"),
        "dashboard_preferences": preferences if expert_changed else _parse_dashboard_preferences(user.get("dashboard_preferences", "{}")),
    }


def get_workouts_by_user(user_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM workouts WHERE user_id = ? ORDER BY date DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        workout = dict(row)
        # Eski JSON kayıtlarını değiştirmeden, API çıktısında kanonik meta
        # bilgilerle zenginleştir. Böylece eski veriler de grafikte görünür.
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
        user_id, data.get("date", str(date.today())), data.get("session_type", "Workout"),
        data.get("notes", ""), data.get("gym_id"), str(data.get("gym_name") or "")[:80],
        total_volume, json.dumps(exercises, ensure_ascii=False),
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
    if "gym_id" in data:
        fields.append("gym_id=?"); values.append(data["gym_id"])
    if "gym_name" in data:
        fields.append("gym_name=?"); values.append(str(data["gym_name"] or "")[:80])
    if "exercises" in data:
        exercises = _normalize_workout_exercises(data["exercises"])
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
    _sync_programs_with_real_workouts(user_id)
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


from exercise_catalog import EXERCISE_META_VERSION, EXERCISE_POOL
from exercise_aliases import EXERCISE_ALIASES

# ═══════════════════════════════════════════════
# EGZERSİZ KİMLİĞİ — ESKİ KAYIT UYUMLULUĞU
# ═══════════════════════════════════════════════
# Kullanıcı hiçbir zaman bu kimlikleri görmez. Hareket seçildiğinde frontend
# gerçek id'yi kaydeder. Eski kayıtlarda id eksik veya yazım farklıysa isim
# normalizasyonu ve kontrollü alias tablosu devreye girer.

def _normalize_exercise_text(value: object) -> str:
    text = str(value or '').strip().lower()
    text = (text.replace('ı', 'i').replace('İ', 'i').replace('ğ', 'g')
                 .replace('ü', 'u').replace('ş', 's').replace('ö', 'o').replace('ç', 'c'))
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    # Eski kayıt ve kullanıcı araması için yaygın yazım farklılıkları.
    text = text.replace('dumbell', 'dumbbell').replace('dumbel', 'dumbbell')
    text = text.replace('barfiks', 'pull up').replace('pull-up', 'pull up')
    text = text.replace('pulldown', 'pull down').replace('t bar', 'tbar')
    text = text.replace('cross over', 'crossover').replace('bulgarian split squad', 'bulgarian split squat')
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


EXERCISE_BY_ID = {exercise['id']: exercise for exercise in EXERCISE_POOL}
# İsim, görünen ad ve teknik id birlikte indekslenir. Böylece eski kayıtta
# `leg-extension`, `Leg Extension` veya `leg extension` bulunması sonucu bozmaz.
EXERCISE_ID_BY_NORMALIZED_NAME = {}
for _pool_exercise in EXERCISE_POOL:
    EXERCISE_ID_BY_NORMALIZED_NAME[_normalize_exercise_text(_pool_exercise['name'])] = _pool_exercise['id']
    EXERCISE_ID_BY_NORMALIZED_NAME[_normalize_exercise_text(_pool_exercise['id'])] = _pool_exercise['id']
# Eski/yaygın egzersiz adlarının kanonik kimlik eşlemeleri ayrı modülde tutulur.
# Bu sayede katalog ve geçmiş uyumluluğu, API kodundan bağımsız düzenlenebilir.
def resolve_exercise_metadata(exercise_id: object = None, exercise_name: object = None):
    """Kayıttan kanonik havuz hareketini çözer; bilinmeyen ad için None döndürür."""
    raw_id = str(exercise_id or '').strip()
    if raw_id in EXERCISE_BY_ID:
        return EXERCISE_BY_ID[raw_id]

    for reference in (raw_id, exercise_name):
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
    """Havuzda artık bulunmayan hareketler için de kararlı, kullanıcıya görünmeyen kimlik.

    Bu anahtar yalnızca eski kaydı aynı eski kayıtla eşleştirmek içindir. Böylece
    bilinmeyen/özel bir hareket silinmez ve ilerleme grafiğinde veri kaybolmaz.
    """
    raw_id = str(exercise_id or '').strip()
    if raw_id.lower().startswith('legacy:'):
        suffix = raw_id.split(':', 1)[1].strip()
        return f"legacy:{suffix}" if suffix else ''
    reference = exercise_name or raw_id
    normalized = _normalize_exercise_text(reference)
    return f"legacy:{normalized}" if normalized else ''


def _canonical_exercise_from_entry(entry: dict):
    return resolve_exercise_metadata(
        entry.get('canonical_exercise_id') or entry.get('exercise_id'),
        entry.get('exercise_name') or entry.get('name'),
    )


def _normalize_workout_exercises(exercises):
    """Yeni kaydı zenginleştirir; eski veya bilinmeyen hareketi silmeden korur."""
    normalized = []
    for raw in exercises or []:
        entry = dict(raw)
        meta = _canonical_exercise_from_entry(entry)
        if meta:
            entry['exercise_id'] = meta['id']
            entry['canonical_exercise_id'] = meta['id']
            entry['exercise_name'] = meta['name']
            entry['muscle_group'] = meta['muscle_group']
            entry['is_bodyweight'] = bool(meta['is_bodyweight'])
            entry['exercise_meta_version'] = EXERCISE_META_VERSION
        else:
            # Kaldırılmış / özel hareket için de kararlı bir tarihsel kimlik tut.
            # Eski isim aynen korunur; hiçbir kayıt sessizce silinmez.
            entry.setdefault('legacy_exercise_name', entry.get('exercise_name') or entry.get('name') or entry.get('exercise_id', ''))
            entry['canonical_exercise_id'] = _legacy_exercise_key(
                entry.get('canonical_exercise_id') or entry.get('exercise_id'),
                entry.get('exercise_name') or entry.get('name'),
            )
            entry.setdefault('exercise_meta_version', 0)
        normalized.append(entry)
    return normalized


def _iter_workout_exercises(workout: dict):
    raw = workout.get('exercises', [])
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    return _normalize_workout_exercises(raw)


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
    # RIR: sette teknik bozulmadan kalan tahmini tekrar sayısı.
    # Eski kayıtlar bu alan olmadan geçerlidir; 0 failure'a çok yakın anlamına gelir.
    rir: Optional[int] = None


class ExerciseEntry(BaseModel):
    # Eski alanlar zorunlu olarak korunur. Yeni kanonik kimlik kullanıcıya
    # gösterilmez; ilerleme ve uzman sistemi için arka planda saklanır.
    exercise_id: str
    exercise_name: str
    muscle_group: str
    sets_data: List[SetData]
    is_bodyweight: bool = False
    canonical_exercise_id: Optional[str] = None
    exercise_meta_version: int = 1


class WorkoutCreate(BaseModel):
    date: str
    session_type: str
    notes: Optional[str] = ""
    exercises: List[ExerciseEntry]
    # Salon kaydı yalnız bağlam bilgisidir; uzman taslağını otomatik değiştirmez.
    gym_id: Optional[str] = None
    gym_name: Optional[str] = None


class WorkoutUpdate(BaseModel):
    date: Optional[str] = None
    session_type: Optional[str] = None
    notes: Optional[str] = None
    exercises: Optional[List[ExerciseEntry]] = None
    gym_id: Optional[str] = None
    gym_name: Optional[str] = None


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


class DashboardPreferencesRequest(BaseModel):
    """Tarayıcı yerine kullanıcı hesabında saklanan dashboard tercihleri."""
    pr_targets: dict[str, float]


class ExpertPreferencesRequest(BaseModel):
    primary_goal: str
    priority_muscles: List[str]


class ExpertCheckinRequest(BaseModel):
    # session: antrenman sonu; daily: isteğe bağlı günlük toparlanma kontrolü
    checkin_type: str
    checkin_date: Optional[str] = None
    session_rpe: Optional[float] = None
    day_fatigue: Optional[float] = None
    recovery_feeling: Optional[float] = None
    completion_percentage: Optional[float] = None
    notes: Optional[str] = ""


class ExpertDomsReportInput(BaseModel):
    muscle_group: str
    severity: float
    notes: Optional[str] = ""


class ExpertDomsReportRequest(BaseModel):
    report_date: Optional[str] = None
    reports: List[ExpertDomsReportInput]


class ExpertEquipmentRequest(BaseModel):
    available_equipment: List[str]


class ExpertConstraintRequest(BaseModel):
    constraint_id: Optional[int] = None
    muscle_group: str
    constraint_type: str = "pain"
    severity: float
    notes: Optional[str] = ""
    started_on: Optional[str] = None
    resolved: bool = False


class ExpertGenerateProgramRequest(BaseModel):
    # İstemci bu alanı göndermezse kullanıcı profilindeki gün sayısı kullanılır.
    days_per_week: Optional[int] = None


class ExpertActivateProgramRequest(BaseModel):
    program_version_id: int


class ExpertMissedSessionRequest(BaseModel):
    session_id: str
    recovery_score: float
    program_version_id: Optional[int] = None


class ExpertRpeDataRequest(BaseModel):
    checkin_date: Optional[str] = None
    session_rpe: int
    notes: Optional[str] = ""


class ExpertGoalsDataRequest(BaseModel):
    primary_goal: str
    priority_muscles: List[str]
    priority_note: Optional[str] = ""


class ExpertDomsDataRequest(BaseModel):
    muscle_group: str
    severity: int
    notes: Optional[str] = ""


class ExpertDomsEntryUpdateRequest(BaseModel):
    """Var olan günlük kas ağrısı kaydında yalnızca seviye ve not güncellenir."""
    severity: int
    notes: Optional[str] = ""


class ExpertGymDataRequest(BaseModel):
    gym_id: Optional[str] = None
    name: str
    equipment: List[str] = []
    is_default: bool = False


class ExpertEquipmentPreferencesRequest(BaseModel):
    preferred_equipment: List[str] = Field(default_factory=list)


class ExpertMovementPreferencesRequest(BaseModel):
    preferred_exercise_ids: List[str] = Field(default_factory=list)
    avoid_exercise_ids: List[str] = Field(default_factory=list)


class ExpertInjuryDataRequest(BaseModel):
    injury_id: Optional[str] = None
    area: str
    injury_type: str = "other"
    severity: int
    is_active: bool = True
    notes: Optional[str] = ""
    tingling_severity: Optional[int] = Field(None, ge=0, le=5, description="Sızlama ağrısı şiddeti (özellikle tendonlar için)")


class ExpertLegacyResetRequest(BaseModel):
    confirmation: str


class NutritionLogSchema(BaseModel):
    username: str
    log_date: str = ""
    calories: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    notes: str = ""


class NutritionLogUpdateSchema(NutritionLogSchema):
    # JSON içindeki eski tarih anahtarı. Tarih değişmediğinde de açıkça gönderilir.
    original_date: str


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


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    """Giriş ve kayıt endpoint'leri için bellek içi kayan pencere limiti uygular.

    Tek instance PaaS dağıtımlarında temel koruma sağlar. Çoklu instance'a
    geçildiğinde aynı mantık Redis gibi merkezi bir store'a taşınmalıdır.
    """
    protected_paths = {"/api/auth/login", "/api/auth/register"}
    _attempts = defaultdict(deque)
    _lock = Lock()

    @staticmethod
    def _client_identifier(request: Request) -> str:
        if TRUST_PROXY_HEADERS:
            forwarded_for = request.headers.get("x-forwarded-for", "")
            if forwarded_for:
                return forwarded_for.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and request.url.path in self.protected_paths:
            identifier = self._client_identifier(request)
            key = f"{request.url.path}:{identifier}"
            now = time.monotonic()
            with self._lock:
                attempts = self._attempts[key]
                while attempts and now - attempts[0] >= LOGIN_RATE_LIMIT_WINDOW_SECONDS:
                    attempts.popleft()
                if len(attempts) >= LOGIN_RATE_LIMIT_MAX:
                    retry_after = max(1, int(LOGIN_RATE_LIMIT_WINDOW_SECONDS - (now - attempts[0])))
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Çok fazla deneme yapıldı. Lütfen daha sonra tekrar deneyin."},
                        headers={"Retry-After": str(retry_after)},
                    )
                attempts.append(now)

            response = await call_next(request)
            # Başarılı giriş/kayıt, ilgili istemcinin eski başarısız denemelerini sıfırlar.
            if 200 <= response.status_code < 300:
                with self._lock:
                    self._attempts.pop(key, None)
            return response
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Tarayıcı tabanlı yaygın saldırılara karşı güvenli varsayılan başlıklar ekler."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # HSTS yalnızca HTTPS domaini doğrulandıktan sonra ENABLE_HSTS=true ile açılır.
        if IS_PRODUCTION and ENABLE_HSTS:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


app = FastAPI(title="Hypertrophy-X API", version="5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials="*" not in CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(CacheControlMiddleware)
app.add_middleware(AuthRateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
log.info("Middleware katmanı aktif: CORS + Cache-Control + İstek Loglama + Güvenlik Başlıkları + Giriş Limiti")


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


# HX_EQUIPMENT_PREFERENCES_DEFAULT_GYM_DATES_V1
def _normalize_gyms_with_default(gyms: object) -> list[dict]:
    """Eski salon kayıtlarını korur ve API'de yalnız bir varsayılan döndürür."""
    normalized = [dict(item) for item in (gyms or []) if isinstance(item, dict) and item.get("id")]
    selected_id = next((str(item["id"]) for item in normalized if bool(item.get("is_default"))), None)
    if not selected_id and normalized:
        selected_id = str(normalized[0]["id"])
    for item in normalized:
        item["is_default"] = str(item.get("id")) == selected_id
    return normalized


# HX_MOVEMENT_PREFERENCES_ALTERNATIVES_V1
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
    return {"gyms": gyms, "preferred_equipment": preferred, "default_gym_id": default_gym.get("id") if default_gym else None, "default_gym_name": default_gym.get("name") if default_gym else None, "equipment": equipment, "equipment_source": source, "equipment_source_label": label}


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


def _expert_data_state(user: dict) -> dict:
    conn = get_db()
    try:
        profile = _expert_data_profile(conn, user["id"])
    finally:
        conn.close()
    account = get_user_by_id(user["id"]) or user
    equipment_selection = _equipment_selection(profile, account.get("dashboard_preferences", "{}"))
    movement_preferences = _exercise_preference_selection(account.get("dashboard_preferences", "{}"))
    return {
        "success": True,
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
        "recommendation": _parse_dashboard_preferences(user.get("dashboard_preferences", "{}")).get("expert_recommendation"),
        "metrics": _expert_data_metrics(profile.get("doms_daily") or {}),
        "catalog": {
            "primary_goals": PRIMARY_GOALS,
            "detailed_muscles": list(DETAILED_MUSCLE_OPTIONS),
            # Sehpa ve serbest ağırlıklar temel kabul edilir; kullanıcıdan ayrıca seçmesi istenmez.
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


def _json_list(raw_value) -> list:
    """Bozuk veya eski JSON alanlarında API yanıtını güvenli biçimde korur."""
    if isinstance(raw_value, list):
        return raw_value
    try:
        value = json.loads(raw_value or "[]")
        return value if isinstance(value, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


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
        # Veri toplama sürümünde expert_program_versions artık kurulmaz. Yalnızca
        # bu beklenen şema farkını sessizce boş program olarak ele al; diğer
        # veritabanı hataları görünür kalmalıdır.
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


def _parse_iso_date_safe(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _expert_state(user: dict) -> dict:
    """İstemcinin tek istekle ekranı kurabilmesi için uzman sistemi durumunu döndürür.

    `result` alanı V1 ile aynı kalır. Ekipman kaydedilmişse aynı nesneye V2'nin
    `dynamic_program` alanı eklenir; böylece eski arayüz güvenle çalışmaya devam eder.
    """
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
        if ADMIN_PASSWORD_HASH and _verify_admin_password(data.password, ADMIN_PASSWORD_HASH):
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
        "UPDATE users SET password_hash = ?, password_salt = '', updated_at = CURRENT_TIMESTAMP "
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
# UZMAN SİSTEMİ ENDPOINT'LERİ — JWT korumalı, açıklanabilir kural motoru
# ═══════════════════════════════════════════════
@app.get("/api/expert-system")
def expert_system_state(user: dict = Depends(_resolve_current_user)):
    """Uzman sistemi ekranının ihtiyaç duyduğu tüm merkezi durumu döndürür."""
    return _expert_state(user)


@app.post("/api/expert-system/preferences")
def save_expert_preferences(
    data: ExpertPreferencesRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    _expert_require_ready(user)
    try:
        # V2 ayrıntılı kas kimlikleri önceliklidir. Eski V1 arayüzünün geniş kas
        # grupları ise mevcut kullanıcıların tercihini kaybetmemesi için korunur.
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


@app.post("/api/expert-system/checkins")
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


@app.post("/api/expert-system/doms-reports")
def save_expert_doms_reports(
    data: ExpertDomsReportRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    _expert_require_ready(user)
    if not data.reports or len(data.reports) > len(UI_MUSCLE_GROUPS):
        raise HTTPException(status_code=400, detail="En az 1, en fazla 7 kas ağrısı kaydı gönderin.")
    try:
        report_date = _expert_date(data.report_date)
    except HTTPException:
        raise

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


# ═══════════════════════════════════════════════
# UZMAN SİSTEMİ V2 ENDPOINT'LERİ — ekipman, kısıt ve kullanıcı onayı
# ═══════════════════════════════════════════════
@app.post("/api/expert-system/equipment")
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


@app.post("/api/expert-system/constraints")
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


def _expert_store_program_version(conn, user_id: int, program: dict) -> int:
    """Öneriyi pasif sürüm olarak kaydeder; aktif program yalnızca ayrı uçla değişir."""
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


@app.post("/api/expert-system/generate-program")
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


@app.post("/api/expert-system/activate-program")
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
        # Özel Programım alanına hiçbir yazım yapılmaz: iki program alanı bağımsızdır.
        conn.execute("UPDATE expert_program_versions SET is_active = FALSE WHERE user_id = ?", (user["id"],))
        conn.execute(
            "UPDATE expert_program_versions SET is_active = TRUE, activated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (data.program_version_id, user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return _expert_state(user)


@app.post("/api/expert-system/missed-session")
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
# ADMIN ENDPOINT'LERİ — JWT + Admin rol kontrolü
# ═══════════════════════════════════════════════
@app.get("/api/admin/users")
def admin_list_users(admin_user: dict = Depends(_resolve_current_user)):
    _require_admin(admin_user)
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
    sync_result = _sync_programs_with_real_workouts(user["id"])
    if sync_result.get("changed"):
        user["custom_split"] = sync_result.get("custom_split", user.get("custom_split", "[]"))
        user["dashboard_preferences"] = json.dumps(
            sync_result.get("dashboard_preferences", {}), ensure_ascii=False
        )
    workouts = get_workouts_by_user(user["id"])
    now = datetime.now()
    today_date = now.date()

    # Haftalık sayaç pazartesi 00:00'dan başlar. Kayıtlar tarih (YYYY-MM-DD)
    # olarak tutulduğu için datetime ile karşılaştırma, pazartesi gününün
    # kaydını "00:00 < şu an" diye yanlışlıkla dışarıda bırakabiliyordu.
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

    # Dashboard anatomik pasta sözleşmesi: her kayıtlı hareket yalnızca bir
    # kanonik dilime yazılır. Set sayısı veya ikinci kaslar toplamı şişirmez.
    # Ayrıntılar, yalnız kullanıcının istediği dilimlerde tooltip için tutulur.
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
                # Eski tutarlı metrik: her kaydedilmiş hareket yalnız bir kez sayılır.
                group_totals[group] = group_totals.get(group, 0) + 1
                if group in dashboard_hover_groups and detail:
                    detail_map = group_details.setdefault(group, {})
                    detail_map[detail] = detail_map.get(detail, 0) + 1
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
        {"date": w["date"], "type": w.get("session_type", "Workout")} for w in workouts
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
def get_exercise_chart_data(
    exercise_id: Optional[str] = Query(None),
    exercise: Optional[str] = Query(None),
    user: dict = Depends(_resolve_current_user),
):
    """Kanonik id ile egzersiz zaman serisi.

    `exercise` parametresi eski frontend ile uyum için kalır. Yeni frontend
    daima `exercise_id` gönderir; böylece isim yazım farkı grafiği bozmaz.
    """
    target = resolve_exercise_metadata(exercise_id, exercise)
    # Havuzdan çıkarılmış veya özel bir hareket de eski antrenman kaydında
    # kalabilir. Bu durumda istek 404 dönmez; yalnızca aynı tarihsel kimliği
    # taşıyan kayıtlar bulunur ve grafikte gösterilir.
    historical_key = '' if target else _legacy_exercise_key(exercise_id, exercise)
    if not target and not historical_key:
        raise HTTPException(status_code=400, detail="Egzersiz seçimi geçersiz")

    load_mode = target.get("analysis", {}).get("load_mode", "external_load") if target else "external_load"
    metric_type = "reps" if load_mode == "bodyweight" else "weight_kg"
    metric_label = "En yüksek tekrar" if metric_type == "reps" else "PR ağırlık (kg)"
    historical_name = str(exercise or exercise_id or "Eski hareket")

    labels, values, details = [], [], []
    workouts = sorted(get_workouts_by_user(user["id"]), key=lambda item: item["date"])
    for workout in workouts:
        for entry in workout.get("exercises", []):
            resolved = _canonical_exercise_from_entry(entry)
            if target:
                if not resolved or resolved["id"] != target["id"]:
                    continue
            elif _legacy_exercise_key(
                entry.get("canonical_exercise_id") or entry.get("exercise_id"),
                entry.get("legacy_exercise_name") or entry.get("exercise_name") or entry.get("name"),
            ) != historical_key:
                continue

            historical_name = str(entry.get("legacy_exercise_name") or entry.get("exercise_name") or entry.get("name") or historical_name)
            date_str = str(workout.get("date", "")).split()[0]
            parts = date_str.split("-")
            formatted_date = f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else date_str
            for index, set_data in enumerate(entry.get("sets_data", []), 1):
                try:
                    reps = int(set_data.get("reps", 0))
                    weight = float(set_data.get("weight_kg", 0))
                except (TypeError, ValueError):
                    continue
                value = reps if metric_type == "reps" else weight
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

    return {
        "exercise_id": target["id"] if target else historical_key,
        "exercise_name": target["name"] if target else historical_name,
        "metric_type": metric_type,
        "metric_label": metric_label,
        "is_legacy_exercise": not bool(target),
        "labels": labels,
        "data": values,
        "details": details,
    }


def get_personal_records(workouts):
    """Her kanonik hareket için kayıt; eski hareket adı farklılıklarını birleştirir."""
    records = {}
    for workout in workouts:
        for entry in workout.get("exercises", []):
            meta = _canonical_exercise_from_entry(entry)
            record_id = meta["id"] if meta else _legacy_exercise_key(
                entry.get("canonical_exercise_id") or entry.get("exercise_id"),
                entry.get("legacy_exercise_name") or entry.get("exercise_name") or entry.get("name"),
            )
            display_name = meta["name"] if meta else str(entry.get("legacy_exercise_name") or entry.get("exercise_name") or entry.get("name") or "Bilinmeyen hareket")
            if meta:
                # Eski kayıtlarda muscle_group "Bacak" olsa bile kanonik havuz
                # meta verisiyle gerçek alt kas etiketi üretilir.
                muscle = _display_muscle_groups(meta, meta.get("analysis", {}))[0]
            else:
                m = entry.get("muscle_group", "Diğer")
                trans = {"Back": "Sırt", "Chest": "Göğüs", "Shoulders": "Omuz", "Legs": "Bacak"}
                muscle = trans.get(m, m)

            load_mode = meta.get("analysis", {}).get("load_mode", "external_load") if meta else "external_load"
            metric_type = "reps" if load_mode == "bodyweight" else "weight_kg"
            sets_list = entry.get("sets_data", [])
            if not sets_list:
                continue
            try:
                best_value = max(
                    int(item.get("reps", 0)) if metric_type == "reps" else float(item.get("weight_kg", 0))
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
                    "primary_muscles": meta.get("analysis", {}).get("primary_muscles", []) if meta else (["upper_back"] if "upper-back" in str(record_id).lower() or "upper back" in display_name.lower() else []),

                    "category": meta.get("category", "") if meta else "",
                    "record_value": best_value,
                    "metric_type": metric_type,
                    "max_weight": best_value if metric_type == "weight_kg" else 0,
                    "max_reps": best_value if metric_type == "reps" else max(int(item.get("reps", 0)) for item in sets_list),
                    "date": workout.get("date", ""),
                }
    return list(records.values())


# ═══════════════════════════════════════════════
# ÖZEL PROGRAM
# ═══════════════════════════════════════════════
@app.post("/api/dashboard/preferences/pr-targets")
def save_pr_targets(data: DashboardPreferencesRequest,
                    current_user: dict = Depends(_resolve_current_user)):
    """PR hedeflerini giriş yapan kullanıcıya bağlı biçimde kaydeder.

    Kullanıcı adı istemciden alınmaz; JWT ile çözülen kullanıcı tek otoritedir.
    Bu sayede aynı hesabın tüm cihazları ortak Neon/SQLite kaydını kullanır.
    """
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
    try:
        conn.execute(
            "UPDATE users SET dashboard_preferences = ? WHERE id = ?",
            (json.dumps(preferences, ensure_ascii=False), current_user["id"]),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise HTTPException(status_code=500, detail="PR hedefleri kaydedilemedi")
    finally:
        conn.close()

    return {"success": True, "dashboard_preferences": preferences}


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
                "message": f"{len(data.program)} Haftalık periyot başarıyla kaydedildi!",
                "program": program_list}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500,
                            detail=f"Kayıt sırasında veritabanı hatası: {str(e)}")
    finally:
        conn.close()


# İngilizce havuz grubu -> kullanıcıya gösterilecek sade Türkçe filtre adı.
# Rotatorlar, omuz rotasyon hareketlerini (Rotator Cuff) kapsar.
# Kalça/femur rotasyonları ve adduksiyon hareketleri ise Adductors altında toplanır.
EXERCISE_MUSCLE_TR = {
    "Chest": "Göğüs", "Back": "Sırt", "Shoulders": "Omuz",
    "Legs": "Alt Vücut", "Biceps": "Biceps", "Triceps": "Triceps",
    "Traps": "Sırt", "Core": "Core",
    "Rotator Cuff": "Rotatorlar", "Hip Rotators": "Adductors",
    "Adductors": "Adductors",
}
# Leg/Lower yalnız seans türüdür. Alt kaslar primer meta veriden görünür olur.
LEG_PRIMARY_MUSCLE_TR = {
    "quads": "Quadriceps", "hamstrings": "Hamstring", "glutes": "Gluteus",
    "gluteus_maximus": "Gluteus", "gluteus_medius": "Gluteus",
    "calves": "Calf", "adductors": "Adductors",
    "hip_external_rotators": "Adductors", "hip_internal_rotators": "Adductors",
}
WORKOUT_UI_MUSCLE_GROUPS = (
    "Göğüs", "Sırt", "Omuz", "Biceps", "Triceps",
    "Quadriceps", "Hamstring", "Gluteus", "Calf", "Adductors", "Rotatorlar", "Core",
)
def _display_muscle_groups(exercise: dict, analysis: dict) -> list[str]:
    """Kayıt ekranındaki filtre/etiket gruplarını döndürür.

    ``Legs`` bir seans türüdür, bağımsız bir kas grubu değildir. Leg hareketleri
    primary_muscles verisinden Quadriceps, Hamstring, Gluteus, Calf veya
    Adductors altında listelenir. Arka omuz hareketleri ise hem Omuz hem Sırt
    filtresinde görünmeye devam eder.
    Rotatorlar seansında ise Rotator Cuff (omuz) ve Adductors (femur/kalça)
    olarak iki ayrı bölge bulunur.
    """
    group = exercise.get("muscle_group", "")
    primary_muscles = set(analysis.get("primary_muscles", []))
    if group == "Rotator Cuff" or any(m in primary_muscles for m in ("infraspinatus", "subscapularis", "supraspinatus", "teres_minor", "rotator_cuff")):
        return ["Rotatorlar"]
    if group in {"Hip Rotators", "Adductors"} or any(m in primary_muscles for m in ("adductors", "hip_external_rotators", "hip_internal_rotators")):
        return ["Adductors"]
    if "rear_delts" in primary_muscles:
        return ["Omuz", "Sırt"]
    if group == "Legs":
        detailed = [LEG_PRIMARY_MUSCLE_TR[item] for item in LEG_PRIMARY_MUSCLE_TR if item in primary_muscles]
        return detailed or ["Alt Vücut"]
    return [EXERCISE_MUSCLE_TR.get(group, group)]


def _enrich_exercise_pool(pool):
    """Frontend için eski alias'ları ve görünmez analiz meta verisini birlikte sunar."""
    out = []
    for exercise in pool:
        item = dict(exercise)
        analysis = dict(exercise.get("analysis", {}))
        display_groups = _display_muscle_groups(exercise, analysis)

        # `muscle` eski arayüz kodu için birincil görünür etikettir.
        # `display_muscle_groups` ise arka omuzdaki gibi çoklu filtre desteğidir.
        item["muscle"] = display_groups[0]
        item["display_muscle_groups"] = display_groups
        item["bw"] = bool(exercise.get("is_bodyweight", False))
        item["weighted"] = analysis.get("load_mode") == "bodyweight_plus_external"
        item["canonical_exercise_id"] = exercise["id"]
        item["analysis"] = analysis
        out.append(item)
    return out

@app.get("/api/exercises")
def get_exercises():
    """Egzersiz havuzu ve kayıt ekranındaki ayrıntılı kas filtreleri."""
    return {
        "exercises": _enrich_exercise_pool(EXERCISE_POOL),
        "muscle_groups": list(WORKOUT_UI_MUSCLE_GROUPS),
    }


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
        "UPDATE users SET daily_nutrition = ?, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
        (json.dumps(history_dict, ensure_ascii=False), current_user["username"])
    )
    conn.commit()
    conn.close()
    return {"success": True, "message": "Beslenme verisi kaydedildi"}


@app.put("/api/nutrition/log")
def update_nutrition_log(data: NutritionLogUpdateSchema,
                         current_user: dict = Depends(_resolve_current_user)):
    """Tek bir beslenme kaydını günceller; tarih değiştiyse eski anahtarı taşır."""
    if data.username != current_user["username"]:
        raise HTTPException(status_code=403, detail="Başkası için kayıt güncellenemez")

    original_date = str(data.original_date or "")[:10]
    target_date = str(data.log_date or original_date)[:10]
    try:
        original_day = date.fromisoformat(original_date)
        target_day = date.fromisoformat(target_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Kayıt tarihi geçerli bir tarih olmalıdır")
    if target_day > date.today():
        raise HTTPException(status_code=400, detail="Gelecek gün için kayıt güncellenemez")

    raw_nutri = current_user.get("daily_nutrition", "{}")
    try:
        history_dict = json.loads(raw_nutri) if isinstance(raw_nutri, str) else raw_nutri
    except Exception:
        history_dict = {}

    if original_day.isoformat() not in history_dict:
        raise HTTPException(status_code=404, detail="Düzenlenecek beslenme kaydı bulunamadı")
    if target_day.isoformat() != original_day.isoformat() and target_day.isoformat() in history_dict:
        raise HTTPException(status_code=409, detail="Seçilen tarihte zaten bir beslenme kaydı bulunuyor")

    calories = data.calories
    if calories <= 0:
        calories = (data.protein * 4) + (data.carbs * 4) + (data.fat * 9)

    # Önce eski günü silmek, tarih düzenlemesinin iki ayrı kayıt oluşturmamasını sağlar.
    del history_dict[original_day.isoformat()]
    history_dict[target_day.isoformat()] = {
        "calories": calories,
        "protein": data.protein,
        "carbs": data.carbs,
        "fat": data.fat,
        "notes": data.notes or "",
        "updated_at": str(datetime.now())
    }

    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET daily_nutrition = ?, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
            (json.dumps(history_dict, ensure_ascii=False), current_user["username"])
        )
        conn.commit()
    finally:
        conn.close()
    return {"success": True, "message": "Beslenme kaydı güncellendi", "date": target_day.isoformat()}


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
            "UPDATE users SET daily_nutrition = ?, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
            (json.dumps(history_dict, ensure_ascii=False), user["username"])
        )
        conn.commit()
        conn.close()

    return {"success": True, "message": "Kayıt başarıyla silindi"}


# ═══════════════════════════════════════════════
# UZMAN SİSTEMİ — VERİ TOPLAMA API'LERİ
# Analiz, program oluşturma veya tıbbi yorum üretmez; yalnızca kullanıcının
# kendi bildirdiği verileri tek JSON kayıt altında saklar.
# ═══════════════════════════════════════════════
# HX_MODULAR_EXPERT_RPE_V1
# HX_SET_BASED_RIR_V1
def _expert_recent_rir_summary(user_id: int) -> dict | None:
    """Son RIR içeren antrenman kaydını salt-okunur olarak özetler.

    RIR setin kendi JSON verisinde saklanır. Eski setlerde RIR yoksa analiz
    yalnızca veri eksik bilgisini gösterir; hiçbir geçmiş kayıt değiştirilmez.
    """
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
            return {
                "workout_date": str(workout.get("date") or ""),
                "session_type": str(workout.get("session_type") or "Antrenman"),
                "set_count": len(rir_values),
                "average_rir": round(sum(rir_values) / len(rir_values), 1),
                "lowest_rir": min(rir_values),
                "near_failure_sets": sum(1 for value in rir_values if value <= 1),
                "exercise_names": sorted(set(exercise_names)),
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
        # RIR kaydı yalnızca iç hesaplamada kalır; kullanıcıya RPE özeti döner.
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
    return analysis


def _recommendation_days_per_week(user: dict) -> int:
    try:
        days = int(user.get("days_per_week") or 3)
    except (TypeError, ValueError):
        days = 3
    return max(1, min(7, days))


def _build_expert_recommendation(user: dict) -> dict:
    """Yeni veri merkezi profilinden taslak üretir; mevcut özel programı değiştirmez."""
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
    preferences = {
        "primary_goal": targets.get("primary_goal") or user.get("goal") or "hypertrophy",
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
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET dashboard_preferences = ? WHERE id = ?",
            (json.dumps(preferences, ensure_ascii=False), user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return preferences


# HX_EXPERT_FIXED_WEEK_SLOTS_V1
# Gün slotları (Pazartesi–Pazar) yerinde kalır. Sürükle-bırak yalnız bu slotların
# içeriğini değiştirir; böylece gün adı ile seans hiçbir zaman birlikte taşınmaz.
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
    content["isRest"] = bool(content.get("isRest"))
    content["exercises"] = list(content.get("exercises") or [])
    return content


def _expert_normalize_week_slots(days: object, week_number: int) -> list[dict]:
    """Eski sıralamayı bulunduğu görsel konumla koruyup sabit slotlara taşır."""
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


@app.get("/api/expert-data/analysis")
def get_expert_data_analysis(user: dict = Depends(_resolve_current_user)):
    return {"success": True, "analysis": _expert_data_analysis(user)}


@app.post("/api/expert-data/recommendation/generate")
def generate_expert_recommendation(user: dict = Depends(_resolve_current_user)):
    """Kullanıcının profilindeki gün sayısı ve uzman verileriyle taslak üretir."""
    try:
        recommendation = _build_expert_recommendation(user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    preferences = _save_expert_recommendation(user, recommendation)
    return {"success": True, "recommendation": recommendation, "dashboard_preferences": preferences}


@app.put("/api/expert-data/recommendation/reorder")
def reorder_expert_recommendation(data: dict = Body(...), user: dict = Depends(_resolve_current_user)):
    """Sabit Pazartesi–Pazar slotlarındaki içerikleri yer değiştirir ve GÜNCEL HAREKETLERİ kaydeder."""
    preferences = _parse_dashboard_preferences(user.get("dashboard_preferences", "{}"))
    recommendation = preferences.get("expert_recommendation")
    requested_weeks = data.get("weeks") if isinstance(data, dict) else None
    
    if not isinstance(recommendation, dict) or not isinstance(requested_weeks, list):
        raise HTTPException(status_code=404, detail="Düzenlenecek uzman önerisi bulunamadı.")
        
    recommendation = _expert_normalize_recommendation_slots(recommendation)
    current_weeks = recommendation.get("weeks") or []
    
    if len(current_weeks) != len(requested_weeks) or not 1 <= len(current_weeks) <= 3:
        raise HTTPException(status_code=400, detail="Geçersiz öneri hafta sırası.")
        
    for index, current_week in enumerate(current_weeks, start=1):
        current_days = current_week.get("days") or []
        sent_week = requested_weeks[index - 1] if isinstance(requested_weeks[index - 1], dict) else {}
        sent_days = sent_week.get("days") if isinstance(sent_week, dict) else None
        expected_slots = [_expert_slot_id(index, day_index) for day_index in range(7)]
        
        if not isinstance(sent_days, list) or len(current_days) != 7 or len(sent_days) != 7:
            raise HTTPException(status_code=400, detail="Her öneri haftası yedi sabit gün içermelidir.")
            
        sent_slots = [str(day.get("slot_id") or day.get("day_id") or "") for day in sent_days if isinstance(day, dict)]
        
        # Frontend'den gelen güncel içeriği (sent_content) kullanıyoruz!
        sent_content = {str(day.get("content_id")): _expert_content_from_day(day, str(day.get("content_id"))) for day in sent_days}
        requested_content_ids = [str(day.get("content_id") or "") for day in sent_days if isinstance(day, dict)]
        
        current_content_ids = {str(day.get("content_id") or "") for day in current_days}
        
        if sent_slots != expected_slots or len(current_content_ids) != 7 or set(requested_content_ids) != current_content_ids:
            raise HTTPException(status_code=400, detail="Yalnız mevcut seans veya dinlenme kartları sabit günler arasında taşınabilir.")
            
        # Artık sisteme Frontend'in yolladığı yeni/değiştirilmiş egzersizleri kaydediyoruz
        current_week["days"] = [
            {"day_id": slot_id, "slot_id": slot_id, "day": _EXPERT_WEEKDAY_LABELS[day_index], **sent_content[requested_content_ids[day_index]]}
            for day_index, slot_id in enumerate(expected_slots)
        ]
        
    preferences = _save_expert_recommendation(user, recommendation)
    return {"success": True, "recommendation": recommendation, "dashboard_preferences": preferences}

@app.post("/api/expert-data/rpe-checkins")
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


@app.get("/api/expert-data")
def get_expert_data(user: dict = Depends(_resolve_current_user)):
    """Yalnızca veri toplama ekranının tek profil kaydını ve kataloglarını döndürür."""
    return _expert_data_state(user)


def _clean_gym_equipment(values: List[str]) -> list[str]:
    equipment: list[str] = []
    for raw_value in values or []:
        equipment_id = normalize_gym_equipment(raw_value)
        
        # KURALI ESNEDİYORUZ: Eğer veritabanındaki eski veri geçersizse,
        # sistemi çökertmek (raise HTTPException) yerine bu veriyi pas geç (continue).
        if not equipment_id:
            continue
            
        if equipment_id not in equipment:
            equipment.append(equipment_id)
            
    return equipment


def _validate_injury_payload(data: ExpertInjuryDataRequest, existing: dict | None = None) -> dict:
    """Sakatlık verisini kullanıcının değiştiremediği aktivasyon tarihiyle hazırlar."""
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
        # Yeni kayıtta veya pasif kaydın yeniden etkinleştirilmesinde tarih bugündür.
        started_on = today if not existing or not was_active else _expert_date(existing.get("started_on") or today)
    else:
        # Pasif kayıt için bitiş tarihi tutulmaz; varsa geçmiş aktivasyon tarihi korunur.
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


@app.put("/api/expert-data/goals")
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
    if not 1 <= len(priority_muscles) <= 3:
        raise HTTPException(status_code=400, detail="En az 1, en fazla 3 hedef kas seçin.")

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


@app.post("/api/expert-system/doms")
@app.put("/api/expert-data/doms")
def upsert_expert_doms(data: ExpertDomsDataRequest = Body(...),
                       user: dict = Depends(_resolve_current_user)):
    """Bugün ve aynı kas grubu için önceki ağrı bildirimini değiştirir."""
    muscle = normalize_detailed_muscle(data.muscle_group)
    if not muscle:
        raise HTTPException(status_code=400, detail="Geçerli bir kas grubu seçin.")
    if not 0 <= int(data.severity) <= 5:
        raise HTTPException(status_code=400, detail="Kas ağrısı değeri 0 ile 5 arasında olmalıdır.")

    # Kas ağrısı yalnızca güncel gün için kaydedilir; tarih istemciden seçilemez.
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


@app.put("/api/expert-system/doms/{report_date}/{muscle_group}")
@app.put("/api/expert-data/doms/{report_date}/{muscle_group}")
def update_expert_doms_entry(
    report_date: str,
    muscle_group: str,
    data: ExpertDomsEntryUpdateRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    """Seçilmiş günlük kas ağrısı kaydını tarihini değiştirmeden günceller."""
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


@app.delete("/api/expert-system/doms/{report_date}/{muscle_group}")
@app.delete("/api/expert-data/doms/{report_date}/{muscle_group}")
def delete_expert_doms_entry(
    report_date: str,
    muscle_group: str,
    user: dict = Depends(_resolve_current_user),
):
    """Geçmiş veya güncel kas ağrısı kaydını tek başına siler."""
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


@app.post("/api/expert-system/gyms")
@app.post("/api/expert-data/gyms")
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


@app.put("/api/expert-system/gyms/{gym_id}")
@app.put("/api/expert-data/gyms/{gym_id}")
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


@app.delete("/api/expert-system/gyms/{gym_id}")
@app.delete("/api/expert-data/gyms/{gym_id}")
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


@app.put("/api/expert-data/equipment-preferences")
def save_expert_equipment_preferences(data: ExpertEquipmentPreferencesRequest = Body(...), user: dict = Depends(_resolve_current_user)):
    """Tercih listesi yalnız sonraki taslak üretiminde kullanılır; mevcut taslağı değiştirmez."""
    preferred = _clean_gym_equipment(data.preferred_equipment)
    conn = get_db()
    try:
        row = conn.execute("SELECT dashboard_preferences FROM users WHERE id = ?", (user["id"],)).fetchone()
        preferences = _parse_dashboard_preferences((dict(row) if row else {}).get("dashboard_preferences", "{}"))
        preferences["equipment_preferences"] = {"preferred_equipment": preferred, "updated_at": datetime.now().isoformat(timespec="seconds")}
        conn.execute("UPDATE users SET dashboard_preferences = ? WHERE id = ?", (json.dumps(preferences, ensure_ascii=False), user["id"]))
        conn.commit()
    finally:
        conn.close()
    return _expert_data_state(user)


@app.put("/api/expert-data/movement-preferences")
def save_expert_movement_preferences(data: ExpertMovementPreferencesRequest = Body(...), user: dict = Depends(_resolve_current_user)):
    """Hareket tercihleri yalnız sonraki taslak üretiminde kullanılır."""
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
        conn.execute("UPDATE users SET dashboard_preferences = ? WHERE id = ?", (json.dumps(preferences, ensure_ascii=False), user["id"]))
        conn.commit()
    finally:
        conn.close()
    return _expert_data_state(user)


# HX_EXPERT_ALTERNATIVE_REPLACE_DEDUPE_V1
@app.get("/api/expert-data/exercise-alternatives/{exercise_id}")
def expert_exercise_alternatives(
    exercise_id: str,
    exclude: str = "",
    user: dict = Depends(_resolve_current_user),
):
    """Kullanıcı tercihi ve mevcut kural bağlamıyla filtrelenmiş alternatifleri verir."""
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


@app.put("/api/expert-data/recommendation/exercise-replace")
def replace_expert_recommendation_exercise(data: dict = Body(...), user: dict = Depends(_resolve_current_user)):
    """Seçilen uygun alternatifi yalnız ilgili uzman taslağı günündeki hareketin yerine koyar."""
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


@app.post("/api/expert-system/injuries")
@app.post("/api/expert-data/injuries")
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


@app.put("/api/expert-system/injuries/{injury_id}")
@app.put("/api/expert-data/injuries/{injury_id}")
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


@app.delete("/api/expert-system/injuries/{injury_id}")
@app.delete("/api/expert-data/injuries/{injury_id}")
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


@app.post("/api/expert-data/reset-legacy")
def reset_legacy_expert_data(data: ExpertLegacyResetRequest = Body(...),
                             user: dict = Depends(_resolve_current_user)):
    """Kullanıcının eski uzman sistemi kayıtlarını açık onayla temizler.

    Kullanıcı hesabı, profil, antrenman, beslenme, özel split ve PR verileri bu
    işlemden etkilenmez. Yeni tek-kayıt uzman verisi boş olarak oluşturulur.
    """
    if str(data.confirmation or "").strip() != "UZMAN VERİLERİNİ SIFIRLA":
        raise HTTPException(status_code=400, detail="Sıfırlama onayı geçersiz.")
    conn = get_db()
    try:
        # Yeni şemada eski tablolar kurulmaz; eski üretim veritabanlarında ise
        # tamamı bulunabilir. PostgreSQL'de bulunmayan bir tabloya sorgu atmak
        # işlemi geçersiz kılacağından, silmeden önce tablo varlığı denetlenir.
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

        # Raporlar, DOMS vakalarına bağlı olduğundan önce silinir.
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

spa_router = APIRouter()


@spa_router.get("/")
def spa_root():
    return FileResponse("static/index.html")


# Gerçek statik dosyalar (favicon, css, img, js) catch-all'a düşmeden
# önce burada karşılanır — mount ile sıralama çakışmasını önler.
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
        raise HTTPException(status_code=405, detail="Not Found")
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
@app.on_event("startup")
async def on_startup():
    validate_runtime_configuration()
    init_db()
    log.info("Hypertrophy-X v4.0 hazır. Ortam: %s", APP_ENV)
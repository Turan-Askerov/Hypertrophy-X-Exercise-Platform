"""Hypertrophy-X veritabanı bağlantı yöneticisi (SQLite ve PostgreSQL desteği)."""
import logging
import os
import sqlite3

try:
    import psycopg
    from psycopg import IntegrityError as PostgreSQLIntegrityError
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None
    PostgreSQLIntegrityError = RuntimeError

from core.config import (
    ADMIN_PASSWORD_PLAIN,
    ADMIN_USERNAME,
    DATABASE_BACKEND,
    DATABASE_URL,
    DB_PATH,
)
from core.security import _hash_password
from postgres_schema import POSTGRES_SCHEMA_STATEMENTS

logger = logging.getLogger("hypertrophy-x")


class PostgreSQLCursor:
    """Mevcut SQLite tarzı ? placeholder kullanan sorguları PostgreSQL'e uyarlar."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query: str, params=None):
        q = query.replace("?", "%s")
        if "INSERT OR IGNORE INTO" in q:
            q = q.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            if "ON CONFLICT" not in q:
                q = q + " ON CONFLICT DO NOTHING"
        self._cursor.execute(q, params or ())
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=500):
        return self._cursor.fetchmany(size)

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount


class PostgreSQLConnection:
    """Uygulamadaki mevcut get_db() sözleşmesini PostgreSQL için korur."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, query: str, params=None):
        q = query.replace("?", "%s")
        if "INSERT OR IGNORE INTO" in q:
            q = q.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            if "ON CONFLICT" not in q:
                q = q + " ON CONFLICT DO NOTHING"
        return self._connection.execute(q, params or ())

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

    target_path = os.getenv("DB_PATH", DB_PATH)
    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    return conn



def init_db():
    conn = get_db()
    cur = conn.cursor()

    if DATABASE_BACKEND == "postgresql":
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

            CREATE TABLE IF NOT EXISTS athlete_profiles (
                user_id INTEGER PRIMARY KEY,
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
                daily_nutrition TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS admin_roles (
                user_id INTEGER PRIMARY KEY,
                role_title TEXT NOT NULL DEFAULT 'Sistem Yöneticisi',
                permissions_json TEXT NOT NULL DEFAULT '["all"]',
                last_login TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                code TEXT NOT NULL,
                reset_token TEXT NOT NULL,
                verified_token TEXT DEFAULT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)

        # Eski SQLite dosyaları için geriye dönük sütun eklemeleri
        for statement in (
            "ALTER TABLE users ADD COLUMN custom_split TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE users ADD COLUMN dashboard_preferences TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE users ADD COLUMN daily_nutrition TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'athlete'",
            "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''",
            "ALTER TABLE athlete_profiles ADD COLUMN email TEXT DEFAULT ''",
            "ALTER TABLE workouts ADD COLUMN gym_id TEXT DEFAULT NULL",
            "ALTER TABLE workouts ADD COLUMN gym_name TEXT DEFAULT ''",
            "ALTER TABLE expert_profiles ADD COLUMN rpe_checkins_json TEXT NOT NULL DEFAULT '[]'",
        ):
            try:
                cur.execute(statement)
            except sqlite3.OperationalError:
                pass

    conn.commit()

    # Admin hesabı env parolasını otorite kabul eder
    admin_exists = cur.execute(
        "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
    ).fetchone()
    admin_hash = _hash_password(ADMIN_PASSWORD_PLAIN)
    if not admin_exists:
        cur.execute(
            "INSERT INTO users (username, password_hash, password_salt, role, is_active, is_admin) "
            "VALUES (?, ?, '', 'admin', 1, 1)",
            (ADMIN_USERNAME, admin_hash),
        )
    else:
        cur.execute(
            "UPDATE users SET role = 'admin', is_admin = 1, password_hash = ?, password_salt = '' WHERE username = ?",
            (admin_hash, ADMIN_USERNAME),
        )
    conn.commit()

    # Sporcu ve Admin profillerini senkronize et
    try:
        if DATABASE_BACKEND == "postgresql":
            cur.execute("""
                INSERT INTO athlete_profiles (
                    user_id, age, gender, height, weight, fitness_level, goal,
                    days_per_week, session_time_mins, stagnation_detected,
                    custom_split, dashboard_preferences, daily_nutrition, created_at, updated_at
                )
                SELECT id, age, gender, height, weight, fitness_level, goal,
                       days_per_week, session_time_mins, stagnation_detected,
                       custom_split, dashboard_preferences, daily_nutrition, created_at, updated_at
                FROM users
                WHERE (is_admin = 0 AND username != %s)
                ON CONFLICT (user_id) DO NOTHING
            """, (ADMIN_USERNAME,))
            cur.execute("UPDATE users SET role = 'admin', is_admin = 1 WHERE username = %s", (ADMIN_USERNAME,))
        else:
            cur.execute("""
                INSERT OR IGNORE INTO athlete_profiles (
                    user_id, age, gender, height, weight, fitness_level, goal,
                    days_per_week, session_time_mins, stagnation_detected,
                    custom_split, dashboard_preferences, daily_nutrition, created_at, updated_at
                )
                SELECT id, age, gender, height, weight, fitness_level, goal,
                       days_per_week, session_time_mins, stagnation_detected,
                       custom_split, dashboard_preferences, daily_nutrition, created_at, updated_at
                FROM users
                WHERE (is_admin = 0 AND username != ?)
            """, (ADMIN_USERNAME,))
            cur.execute("UPDATE users SET role = 'admin', is_admin = 1 WHERE username = ?", (ADMIN_USERNAME,))
        conn.commit()
    except Exception as e:
        logger.warning(f"Sporcu/Admin profil ayrıştırma migrasyonu uyarısı: {e}")
    finally:
        conn.close()

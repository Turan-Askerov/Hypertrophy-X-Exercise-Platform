"""Veritabanı aktarım, yedekleme ve SQLite <-> PostgreSQL senkronizasyon servisleri."""
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from core.config import BACKEND_DIR, DATABASE_BACKEND, DB_PATH
from models.schemas import AdminMigrateRequest

logger = logging.getLogger("hypertrophy-x")


def resolve_migration_database_url(input_url: Optional[str] = None) -> str:
    """Aktarım ve eşitleme için PostgreSQL bağlantı adresini güvenli ve dinamik olarak çözümler."""
    clean_input = (input_url or "").strip()
    is_placeholder = (
        not clean_input
        or "***" in clean_input
        or "ep-xyz.neon.tech" in clean_input
        or "user:password@" in clean_input
    )
    if not is_placeholder:
        return clean_input

    env_mig = os.environ.get("MIGRATION_DATABASE_URL", "").strip()
    if env_mig and env_mig.startswith(("postgres://", "postgresql://")):
        return env_mig

    env_db = os.environ.get("DATABASE_URL", "").strip()
    if env_db and env_db.startswith(("postgres://", "postgresql://")):
        return env_db

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


def mask_database_url(url: str) -> str:
    """Şifreyi gizleyerek arayüze güvenli biçimde sunar."""
    if not url:
        return ""
    try:
        import re
        return re.sub(r':([^@]+)@', r':***@', url)
    except Exception:
        return url


def run_sqlite_to_postgres_migration(data: AdminMigrateRequest) -> Dict[str, Any]:
    """SQLite verilerini PostgreSQL'e güvenle aktarır ve birleştirir."""
    db_url = resolve_migration_database_url(data.database_url)
    if not db_url:
        raise HTTPException(
            status_code=400,
            detail="Hedef PostgreSQL bağlantı adresi (.env içindeki MIGRATION_DATABASE_URL veya DATABASE_URL) bulunamadı."
        )
    if not db_url.startswith(("postgres://", "postgresql://")):
        raise HTTPException(
            status_code=400,
            detail="Geçersiz PostgreSQL bağlantı şeması (postgres:// veya postgresql:// ile başlamalıdır)."
        )

    try:
        import psycopg
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="psycopg paketi kurulu değil. 'pip install psycopg[binary]' gereklidir."
        )

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

    logs: List[str] = []
    def log(msg: str):
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
    user_id_map: Dict[int, int] = {}
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


def run_postgres_to_sqlite_migration(data: AdminMigrateRequest) -> Dict[str, Any]:
    """PostgreSQL verilerini (Tüm tablolar dahil) yerel SQLite'a çeker ve senkronize eder."""
    db_url = resolve_migration_database_url(data.database_url)
    if not db_url:
        raise HTTPException(
            status_code=400,
            detail="Hedef PostgreSQL bağlantı adresi (.env içindeki MIGRATION_DATABASE_URL veya DATABASE_URL) bulunamadı."
        )
    if not db_url.startswith(("postgres://", "postgresql://")):
        raise HTTPException(
            status_code=400,
            detail="Geçersiz PostgreSQL bağlantı şeması (postgres:// veya postgresql:// ile başlamalıdır)."
        )

    try:
        import psycopg
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="psycopg paketi kurulu değil. 'pip install psycopg[binary]' gereklidir."
        )

    import migrate_postgres_to_sqlite as m_pg2sq

    sqlite_path = Path(DB_PATH).resolve()
    logs: List[str] = []
    def log(msg: str):
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

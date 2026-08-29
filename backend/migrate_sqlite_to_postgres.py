#!/usr/bin/env python3
"""Hypertrophy-X v4.1 SQLite -> Neon PostgreSQL silmeden birleştirme aracı.

Kurallar:
- Kaynak SQLite veritabanı salt-okunur açılır ve asla değiştirilmez.
- Neon'da yalnız bulunan kayıtlar silinmez veya değiştirilmez.
- Aynı kullanıcı/antrenman/uzman profili iki tarafta aynıysa SQL UPDATE çalıştırılmaz.
- Yerel kayıttaki alanlar farklıysa yalnız o eşleşen kayıt güncellenir.
- Yerelde olup Neon'da olmayan kayıtlar eklenir.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable

try:
    import psycopg
except ImportError as exc:
    raise SystemExit("psycopg yüklü değil. Önce: pip install -r requirements.txt") from exc

from postgres_schema import POSTGRES_SCHEMA_STATEMENTS

USER_COLUMNS = (
    "username", "password_hash", "password_salt", "age", "gender", "height",
    "weight", "fitness_level", "goal", "days_per_week", "session_time_mins",
    "stagnation_detected", "custom_split", "dashboard_preferences", "daily_nutrition",
    "is_admin", "created_at", "updated_at",
)
WORKOUT_COLUMNS = (
    "date", "session_type", "notes", "gym_id", "gym_name", "total_volume", "exercises", "created_at",
)
PROFILE_COLUMNS = (
    "target_muscles_json", "doms_daily_json", "gym_equipment_json", "injuries_json",
    "created_at", "updated_at",
)
# Yalnız otomatik zaman damgası farkı, içerik değişikliği sayılmaz.
USER_COMPARE_COLUMNS = tuple(column for column in USER_COLUMNS if column not in {"created_at", "updated_at"})
WORKOUT_COMPARE_COLUMNS = tuple(column for column in WORKOUT_COLUMNS if column != "created_at")
PROFILE_COMPARE_COLUMNS = tuple(column for column in PROFILE_COLUMNS if column not in {"created_at", "updated_at"})
DEFAULTS: dict[str, Any] = {
    "password_hash": "", "password_salt": "", "age": 0, "gender": "male",
    "height": 170.0, "weight": 70.0, "fitness_level": "Beginner", "goal": "bulk",
    "days_per_week": 4, "session_time_mins": 60, "stagnation_detected": 0,
    "custom_split": "[]", "dashboard_preferences": "{}", "daily_nutrition": "{}",
    "is_admin": 0, "notes": "", "gym_id": None, "gym_name": "", "total_volume": 0.0, "exercises": "[]",
    "target_muscles_json": "{}", "doms_daily_json": "{}",
    "gym_equipment_json": "[]", "injuries_json": "[]",
}


def load_local_environment() -> None:
    """backend/.env içindeki DATABASE_URL'i kabuk geçmişine yazmadan yükler."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).with_name(".env"), override=False)


def parse_args() -> argparse.Namespace:
    load_local_environment()
    parser = argparse.ArgumentParser(description="Hypertrophy-X verisini Neon'a silmeden birleştirir.")
    parser.add_argument(
        "--sqlite-path",
        default=str(Path(__file__).with_name("hypertrophy.db")),
        help="Korunacak SQLite dosyası (varsayılan: backend/hypertrophy.db)",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="PostgreSQL bağlantı adresi (varsayılan: DATABASE_URL ortam değişkeni)",
    )
    parser.add_argument(
        "--migration-key",
        default="hypertrophy-x-v4.1",
        help="Aynı SQLite kaynağı için sabit eşleme anahtarı",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Yalnız kaynak sayımlarını denetler; Neon'a yazmaz.",
    )
    return parser.parse_args()


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def sqlite_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}


def read_rows(
    conn: sqlite3.Connection,
    table: str,
    required: set[str],
    columns: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not table_exists(conn, table):
        return []

    available = sqlite_columns(conn, table)
    missing_required = required - available
    if missing_required:
        raise RuntimeError(
            f"SQLite {table} tablosunda zorunlu alanlar eksik: {', '.join(sorted(missing_required))}"
        )

    selected = sorted(required | (set(columns) & available))
    order_column = "id" if "id" in available else "user_id"
    rows = conn.execute(
        f'SELECT {", ".join(selected)} FROM "{table}" ORDER BY {order_column}'
    ).fetchall()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        value = dict(row)
        for column in columns:
            if value.get(column) is None:
                value[column] = DEFAULTS.get(column)
        normalized.append(value)
    return normalized


def comparable(value: Any) -> Any:
    """SQLite ve PostgreSQL tip farklarında güvenli değer karşılaştırması yapar."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return value


def values_equal(target: dict[str, Any], source: dict[str, Any], columns: Iterable[str]) -> bool:
    return all(comparable(target.get(column)) == comparable(source.get(column)) for column in columns)


def create_mapping_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sqlite_workout_migration_map (
            migration_key TEXT NOT NULL,
            source_workout_id BIGINT NOT NULL,
            target_workout_id BIGINT NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
            PRIMARY KEY (migration_key, source_workout_id)
        )
        """
    )


def insert_row(cursor, table: str, columns: tuple[str, ...], values: tuple[Any, ...]) -> int:
    placeholders = ", ".join(["%s"] * len(columns))
    cursor.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) RETURNING id",
        values,
    )
    return int(cursor.fetchone()[0])


def upsert_user(cursor, row: dict[str, Any]) -> tuple[int, str]:
    cursor.execute(
        f"SELECT id, {', '.join(USER_COLUMNS)} FROM users WHERE username = %s",
        (row["username"],),
    )
    existing = cursor.fetchone()
    if not existing:
        return insert_row(cursor, "users", USER_COLUMNS, tuple(row[c] for c in USER_COLUMNS)), "inserted"

    target = dict(zip(("id",) + USER_COLUMNS, existing))
    if values_equal(target, row, USER_COMPARE_COLUMNS):
        return int(target["id"]), "unchanged"

    assignments = ", ".join(f"{column} = %s" for column in USER_COLUMNS if column != "username")
    update_values = tuple(row[c] for c in USER_COLUMNS if c != "username") + (target["id"],)
    cursor.execute(f"UPDATE users SET {assignments} WHERE id = %s", update_values)
    return int(target["id"]), "updated"


def upsert_profile(cursor, target_user_id: int, row: dict[str, Any]) -> str:
    cursor.execute(
        f"SELECT {', '.join(PROFILE_COLUMNS)} FROM expert_profiles WHERE user_id = %s",
        (target_user_id,),
    )
    existing = cursor.fetchone()
    if not existing:
        columns = ("user_id",) + PROFILE_COLUMNS
        placeholders = ", ".join(["%s"] * len(columns))
        cursor.execute(
            f"INSERT INTO expert_profiles ({', '.join(columns)}) VALUES ({placeholders})",
            (target_user_id,) + tuple(row[c] for c in PROFILE_COLUMNS),
        )
        return "inserted"

    target = dict(zip(PROFILE_COLUMNS, existing))
    if values_equal(target, row, PROFILE_COMPARE_COLUMNS):
        return "unchanged"

    assignments = ", ".join(f"{column} = %s" for column in PROFILE_COLUMNS)
    cursor.execute(
        f"UPDATE expert_profiles SET {assignments} WHERE user_id = %s",
        tuple(row[c] for c in PROFILE_COLUMNS) + (target_user_id,),
    )
    return "updated"


def workout_matches(cursor, target_workout_id: int, target_user_id: int, row: dict[str, Any]) -> bool:
    cursor.execute(
        f"SELECT user_id, {', '.join(WORKOUT_COLUMNS)} FROM workouts WHERE id = %s",
        (target_workout_id,),
    )
    existing = cursor.fetchone()
    if not existing:
        return False
    target = dict(zip(("user_id",) + WORKOUT_COLUMNS, existing))
    return int(target["user_id"]) == target_user_id and values_equal(target, row, WORKOUT_COMPARE_COLUMNS)


def update_workout(cursor, target_workout_id: int, target_user_id: int, row: dict[str, Any]) -> None:
    assignments = ", ".join(["user_id = %s"] + [f"{column} = %s" for column in WORKOUT_COLUMNS])
    cursor.execute(
        f"UPDATE workouts SET {assignments} WHERE id = %s",
        (target_user_id,) + tuple(row[c] for c in WORKOUT_COLUMNS) + (target_workout_id,),
    )


def map_workout(cursor, migration_key: str, source_workout_id: int, target_workout_id: int) -> None:
    cursor.execute(
        "INSERT INTO sqlite_workout_migration_map "
        "(migration_key, source_workout_id, target_workout_id) VALUES (%s, %s, %s) "
        "ON CONFLICT (migration_key, source_workout_id) DO NOTHING",
        (migration_key, source_workout_id, target_workout_id),
    )


def merge_workout(
    cursor,
    migration_key: str,
    source_workout_id: int,
    target_user_id: int,
    row: dict[str, Any],
) -> str:
    cursor.execute(
        "SELECT target_workout_id FROM sqlite_workout_migration_map "
        "WHERE migration_key = %s AND source_workout_id = %s",
        (migration_key, source_workout_id),
    )
    mapped = cursor.fetchone()
    if mapped:
        target_workout_id = int(mapped[0])
        if workout_matches(cursor, target_workout_id, target_user_id, row):
            return "unchanged"
        update_workout(cursor, target_workout_id, target_user_id, row)
        return "updated"

    # Önceki id-korumalı aktarımın aynı kaydı varsa onu eşleyip karşılaştırır.
    cursor.execute("SELECT user_id FROM workouts WHERE id = %s", (source_workout_id,))
    same_id = cursor.fetchone()
    if same_id and int(same_id[0]) == target_user_id:
        if workout_matches(cursor, source_workout_id, target_user_id, row):
            map_workout(cursor, migration_key, source_workout_id, source_workout_id)
            return "unchanged"
        # Aynı kaynak kimliği ve aynı kullanıcı, eski id-korumalı aktarımın güncellenecek kaydıdır.
        update_workout(cursor, source_workout_id, target_user_id, row)
        map_workout(cursor, migration_key, source_workout_id, source_workout_id)
        return "updated"

    target_workout_id = insert_row(
        cursor,
        "workouts",
        ("user_id",) + WORKOUT_COLUMNS,
        (target_user_id,) + tuple(row[c] for c in WORKOUT_COLUMNS),
    )
    map_workout(cursor, migration_key, source_workout_id, target_workout_id)
    return "inserted"


def increment(summary: dict[str, dict[str, int]], group: str, action: str) -> None:
    summary[group][action] = summary[group].get(action, 0) + 1


def main() -> int:
    args = parse_args()
    sqlite_path = Path(args.sqlite_path).expanduser().resolve()
    if not sqlite_path.is_file():
        raise SystemExit(f"SQLite dosyası bulunamadı: {sqlite_path}")

    source = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        users = read_rows(source, "users", {"id", "username"}, USER_COLUMNS)
        workouts = read_rows(source, "workouts", {"id", "user_id"}, WORKOUT_COLUMNS)
        profiles = read_rows(source, "expert_profiles", {"user_id"}, PROFILE_COLUMNS)
    finally:
        source.close()

    print(f"Kaynak denetlendi: {len(users)} kullanıcı, {len(workouts)} antrenman, {len(profiles)} uzman profili.")
    print(f"SQLite salt-okunur korunuyor: {sqlite_path}")
    if args.dry_run:
        print("Dry-run tamamlandı: Neon PostgreSQL'e hiçbir veri yazılmadı.")
        return 0

    if not args.database_url:
        raise SystemExit("DATABASE_URL veya --database-url verilmelidir.")
    if not args.database_url.startswith(("postgres://", "postgresql://")):
        raise SystemExit("DATABASE_URL PostgreSQL bağlantı adresi olmalıdır.")

    user_id_map: dict[int, int] = {}
    summary = {
        "users": {"inserted": 0, "updated": 0, "unchanged": 0},
        "workouts": {"inserted": 0, "updated": 0, "unchanged": 0},
        "profiles": {"inserted": 0, "updated": 0, "unchanged": 0},
    }
    with psycopg.connect(args.database_url) as target:
        with target.cursor() as cursor:
            # DROP COLUMN ifadelerini geçerek Neon'daki eski alanları da korur.
            for statement in POSTGRES_SCHEMA_STATEMENTS:
                if "DROP COLUMN" not in statement.upper():
                    cursor.execute(statement)
            create_mapping_table(cursor)

            for row in users:
                target_user_id, action = upsert_user(cursor, row)
                user_id_map[int(row["id"])] = target_user_id
                increment(summary, "users", action)

            for row in workouts:
                source_user_id = int(row["user_id"])
                if source_user_id not in user_id_map:
                    raise RuntimeError(
                        f"Antrenman {row['id']} için SQLite kullanıcı kaydı bulunamadı: {source_user_id}"
                    )
                action = merge_workout(
                    cursor, args.migration_key, int(row["id"]), user_id_map[source_user_id], row
                )
                increment(summary, "workouts", action)

            for row in profiles:
                source_user_id = int(row["user_id"])
                if source_user_id not in user_id_map:
                    raise RuntimeError(
                        f"Uzman profili için SQLite kullanıcı kaydı bulunamadı: {source_user_id}"
                    )
                action = upsert_profile(cursor, user_id_map[source_user_id], row)
                increment(summary, "profiles", action)

            cursor.execute("SELECT COUNT(*) FROM users")
            target_users = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM workouts")
            target_workouts = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM expert_profiles")
            target_profiles = int(cursor.fetchone()[0])

    print("Birleştirme başarıyla tamamlandı. Hiçbir Neon kaydı silinmedi.")
    print(
        f"Kullanıcılar — eklenen: {summary['users']['inserted']}, "
        f"güncellenen: {summary['users']['updated']}, değişmeyen: {summary['users']['unchanged']}; "
        f"Neon toplam: {target_users}."
    )
    print(
        f"Antrenmanlar — eklenen: {summary['workouts']['inserted']}, "
        f"güncellenen: {summary['workouts']['updated']}, değişmeyen: {summary['workouts']['unchanged']}; "
        f"Neon toplam: {target_workouts}."
    )
    print(
        f"Uzman profilleri — eklenen: {summary['profiles']['inserted']}, "
        f"güncellenen: {summary['profiles']['updated']}, değişmeyen: {summary['profiles']['unchanged']}; "
        f"Neon toplam: {target_profiles}."
    )
    print("Render aynı Neon DATABASE_URL değerini kullanıyorsa verileri yeniden başlatma sonrasında görür.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

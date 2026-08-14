#!/usr/bin/env python3
"""Hypertrophy-X v4.1 SQLite -> PostgreSQL veri aktarım aracı.

Kaynak SQLite dosyası salt okunur açılır ve bu araç hiçbir zaman onu silmez,
değiştirmez veya taşınmış olarak işaretlemez. Aktarım tekrar çalıştırılabilir:
aynı id'ler üzerinde güvenli UPSERT yapılır.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

try:
    import psycopg
except ImportError as exc:  # Kullanıcıya açık ve anlaşılır hata
    raise SystemExit("psycopg yüklü değil. Önce: pip install -r requirements.txt") from exc

from postgres_schema import POSTGRES_SCHEMA_STATEMENTS

USERS_COLUMNS = (
    "id", "username", "password_hash", "password_salt", "age", "gender",
    "height", "weight", "fitness_level", "goal", "days_per_week",
    "session_time_mins", "stagnation_detected", "custom_split",
    "daily_nutrition", "is_admin", "created_at", "updated_at",
)
WORKOUTS_COLUMNS = (
    "id", "user_id", "date", "session_type", "notes", "total_volume",
    "exercises", "created_at",
)
DEFAULTS: dict[str, Any] = {
    "password_hash": "", "password_salt": "", "age": 0, "gender": "male",
    "height": 170.0, "weight": 70.0, "fitness_level": "Beginner", "goal": "bulk",
    "days_per_week": 4, "session_time_mins": 60, "stagnation_detected": 0,
    "custom_split": "[]", "daily_nutrition": "{}", "is_admin": 0,
    "notes": "", "total_volume": 0.0, "exercises": "[]",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hypertrophy-X SQLite verisini PostgreSQL'e aktarır.")
    parser.add_argument(
        "--sqlite-path",
        default=str(Path(__file__).with_name("hypertrophy.db")),
        help="Korunacak eski SQLite dosyası (varsayılan: backend/hypertrophy.db)",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="PostgreSQL bağlantı adresi (varsayılan: DATABASE_URL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Yalnızca SQLite şeması ve aktarılacak kayıt sayılarını denetler; PostgreSQL'e yazmaz.",
    )
    return parser.parse_args()


def sqlite_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}


def read_rows(conn: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    available = sqlite_columns(conn, table)
    required = {"id", "username"} if table == "users" else {"id", "user_id"}
    missing_required = required - available
    if missing_required:
        raise RuntimeError(f"SQLite {table} tablosunda zorunlu alanlar eksik: {', '.join(sorted(missing_required))}")

    selected = [column for column in columns if column in available]
    rows = conn.execute(f'SELECT {", ".join(selected)} FROM "{table}" ORDER BY id').fetchall()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        value = dict(row)
        for column in columns:
            value.setdefault(column, DEFAULTS.get(column))
        normalized.append(value)
    return normalized


def build_upsert(table: str, columns: tuple[str, ...]) -> str:
    placeholders = ", ".join(["%s"] * len(columns))
    assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column != "id")
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO UPDATE SET {assignments}"
    )


def reset_sequence(cursor, table: str) -> None:
    # Tablo adları sabit kod içindedir; kullanıcı girdisi SQL'e eklenmez.
    cursor.execute(
        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
        f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
        f"EXISTS (SELECT 1 FROM {table}))"
    )


def main() -> int:
    args = parse_args()
    sqlite_path = Path(args.sqlite_path).expanduser().resolve()
    if not sqlite_path.is_file():
        raise SystemExit(f"SQLite dosyası bulunamadı: {sqlite_path}")

    # mode=ro, kaynak verinin uygulama veya yanlış komut tarafından değişmesini engeller.
    source = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        users = read_rows(source, "users", USERS_COLUMNS)
        workouts = read_rows(source, "workouts", WORKOUTS_COLUMNS)
    finally:
        source.close()

    print(f"Kaynak denetlendi: {len(users)} kullanıcı, {len(workouts)} antrenman kaydı.")
    print(f"SQLite korunuyor: {sqlite_path}")
    if args.dry_run:
        print("Dry-run tamamlandı: PostgreSQL'e hiçbir veri yazılmadı.")
        return 0

    if not args.database_url:
        raise SystemExit("DATABASE_URL veya --database-url verilmelidir.")
    if not args.database_url.startswith(("postgres://", "postgresql://")):
        raise SystemExit("DATABASE_URL PostgreSQL bağlantı adresi olmalıdır.")

    with psycopg.connect(args.database_url) as target:
        with target.cursor() as cursor:
            for statement in POSTGRES_SCHEMA_STATEMENTS:
                cursor.execute(statement)

            user_sql = build_upsert("users", USERS_COLUMNS)
            workout_sql = build_upsert("workouts", WORKOUTS_COLUMNS)
            for row in users:
                cursor.execute(user_sql, tuple(row[column] for column in USERS_COLUMNS))
            for row in workouts:
                cursor.execute(workout_sql, tuple(row[column] for column in WORKOUTS_COLUMNS))

            reset_sequence(cursor, "users")
            reset_sequence(cursor, "workouts")
            cursor.execute("SELECT COUNT(*) FROM users")
            postgres_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM workouts")
            postgres_workouts = cursor.fetchone()[0]

    if postgres_users < len(users) or postgres_workouts < len(workouts):
        raise RuntimeError("Aktarım doğrulaması başarısız: PostgreSQL kayıt sayısı beklenenden düşük.")

    print("Aktarım başarıyla tamamlandı.")
    print(f"PostgreSQL doğrulaması: {postgres_users} kullanıcı, {postgres_workouts} antrenman kaydı.")
    print("Not: Uygulamayı PostgreSQL ile başlatmadan önce DATABASE_URL değerini environment variable olarak ayarlayın.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

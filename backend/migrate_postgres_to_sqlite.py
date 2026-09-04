#!/usr/bin/env python3
import os
import sqlite3
import json
from pathlib import Path
from datetime import datetime
try:
    import psycopg
except ImportError:
    raise SystemExit("psycopg required")

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

def _adapt_for_sqlite(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value

def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL must be set")
        return
    
    sqlite_path = Path("hypertrophy.db")
    
    print("Reading from PostgreSQL...")
    with psycopg.connect(database_url) as pg_conn:
        with pg_conn.cursor() as pg_cur:
            pg_cur.execute("SELECT id, " + ", ".join(USER_COLUMNS) + " FROM users")
            pg_users = [[_adapt_for_sqlite(v) for v in row] for row in pg_cur.fetchall()]
            
            pg_cur.execute("SELECT id, user_id, " + ", ".join(WORKOUT_COLUMNS) + " FROM workouts")
            pg_workouts = [[_adapt_for_sqlite(v) for v in row] for row in pg_cur.fetchall()]
            
            pg_cur.execute("SELECT user_id, " + ", ".join(PROFILE_COLUMNS) + " FROM expert_profiles")
            pg_profiles = [[_adapt_for_sqlite(v) for v in row] for row in pg_cur.fetchall()]

    print(f"PostgreSQL has {len(pg_users)} users, {len(pg_workouts)} workouts, {len(pg_profiles)} profiles.")

    print("Writing to SQLite...")
    sl_conn = sqlite3.connect(sqlite_path)
    sl_cur = sl_conn.cursor()
    
    # Check users
    sl_cur.execute("SELECT id FROM users")
    sl_user_ids = {row[0] for row in sl_cur.fetchall()}
    added_users = 0
    for row in pg_users:
        if row[0] not in sl_user_ids:
            sl_cur.execute(f"INSERT INTO users (id, {','.join(USER_COLUMNS)}) VALUES ({','.join(['?'] * len(row))})", row)
            added_users += 1

    # Check workouts
    sl_cur.execute("SELECT id FROM workouts")
    sl_workout_ids = {row[0] for row in sl_cur.fetchall()}
    added_workouts = 0
    for row in pg_workouts:
        if row[0] not in sl_workout_ids:
            sl_cur.execute(f"INSERT INTO workouts (id, user_id, {','.join(WORKOUT_COLUMNS)}) VALUES ({','.join(['?'] * len(row))})", row)
            added_workouts += 1

    # Check profiles
    sl_cur.execute("SELECT user_id FROM expert_profiles")
    sl_profile_ids = {row[0] for row in sl_cur.fetchall()}
    added_profiles = 0
    for row in pg_profiles:
        if row[0] not in sl_profile_ids:
            sl_cur.execute(f"INSERT INTO expert_profiles (user_id, {','.join(PROFILE_COLUMNS)}) VALUES ({','.join(['?'] * len(row))})", row)
            added_profiles += 1

    sl_conn.commit()
    sl_conn.close()

    print(f"Added {added_users} users, {added_workouts} workouts, {added_profiles} profiles to SQLite.")

if __name__ == '__main__':
    main()

# ============================================================
# HYPERTROPHY-X  v4.0  —  Tek Dosya Backend
# ============================================================

from fastapi import HTTPException
from fastapi import FastAPI, Body, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime, timedelta
import sqlite3
import os
import json
import hashlib
import secrets

# ═══════════════════════════════════════════════
# SABİTLER
# ═══════════════════════════════════════════════
DB_PATH = "hypertrophy.db"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"

# ═══════════════════════════════════════════════
# EGZERSİZ HAVUZU — KOLAYCA EDİTLENEBİLİR
# ═══════════════════════════════════════════════
# Bir hareket eklemek için bu dict'e yeni entry ekle
# "bw" = true ise ağırlıksız (bodyweight) hareket, ağırlıksız varyant olarak gösterilir
# "weighted" = true ise hem ağırlıklı hem ağırlıksız varyantı gösterilir
EXERCISE_POOL = [
    # ─── GÖĞÜS ───
    {"id": "bench_press", "name": "Bench Press", "muscle": "Göğüs", "bw": False, "weighted": False},
    {"id": "incline_bb_press", "name": "Incline Barbell Press", "muscle": "Göğüs", "bw": False, "weighted": False},
    {"id": "incline_db_press", "name": "Incline Dumbbell Press", "muscle": "Göğüs", "bw": False, "weighted": False},
    {"id": "db_press", "name": "Dumbbell Bench Press", "muscle": "Göğüs", "bw": False, "weighted": False},
    {"id": "cable_fly", "name": "Cable Fly", "muscle": "Göğüs", "bw": False, "weighted": False},
    {"id": "db_fly", "name": "Dumbbell Fly", "muscle": "Göğüs", "bw": False, "weighted": False},
    {"id": "chest_dip", "name": "Chest Dip", "muscle": "Göğüs", "bw": True, "weighted": True},
    {"id": "push_up", "name": "Push-Up", "muscle": "Göğüs", "bw": True, "weighted": False},
    {"id": "weighted_push_up", "name": "Weighted Push-Up", "muscle": "Göğüs", "bw": False, "weighted": False},
    {"id": "chest_press_machine", "name": "Chest Press Machine", "muscle": "Göğüs", "bw": False, "weighted": False},

    # ─── SIRT ───
    {"id": "barbell_row", "name": "Barbell Row", "muscle": "Sırt", "bw": False, "weighted": False},
    {"id": "db_row", "name": "Dumbbell Row", "muscle": "Sırt", "bw": False, "weighted": False},
    {"id": "lat_pulldown", "name": "Lat Pulldown", "muscle": "Sırt", "bw": False, "weighted": False},
    {"id": "single_arm_pulldown", "name": "Single-Arm Pulldown", "muscle": "Sırt", "bw": False, "weighted": False},
    {"id": "seated_row", "name": "Seated Cable Row", "muscle": "Sırt", "bw": False, "weighted": False},
    {"id": "t_bar_row", "name": "T-Bar Row", "muscle": "Sırt", "bw": False, "weighted": False},
    {"id": "face_pull", "name": "Face Pull", "muscle": "Sırt", "bw": False, "weighted": False},
    {"id": "pull_up", "name": "Pull-Up", "muscle": "Sırt", "bw": True, "weighted": True},
    {"id": "weighted_pull_up", "name": "Pull-Up", "muscle": "Sırt", "bw": False, "weighted": True},
    {"id": "chin_up", "name": "Chin-Up", "muscle": "Sırt", "bw": True, "weighted": True},
    {"id": "weighted_chin_up", "name": "Chin-Up", "muscle": "Sırt", "bw": False, "weighted": True},
    {"id": "hyperextension", "name": "Back Hyperextension", "muscle": "Sırt", "bw": True, "weighted": False},
    {"id": "weighted_hyperextension", "name": "Back Hyperextension", "muscle": "Sırt", "bw": False, "weighted": True},
    {"id": "single_arm_low_row", "name": "Single-Arm Low Row", "muscle": "Sırt", "bw": False, "weighted": False},
    {"id": "low_row", "name": "Low Row", "muscle": "Sırt", "bw": False, "weighted": False},
    {"id": "dumbbell_low_row", "name": "Dumbbell Low Row", "muscle": "Sırt", "bw": False, "weighted": False},
    {"id": "dumbbell_shruge", "name": "Dumbbell Shruge", "muscle": "Sırt", "bw": False, "weighted": False},
    {"id": "barbell_shruge", "name": "Barbell Shruge", "muscle": "Sırt", "bw": False, "weighted": False},
    {"id": "reverse_fly", "name": "Reverse Fly", "muscle": "Sırt", "bw": False, "weighted": False},


    # ─── OMUZ ───
    {"id": "overhead_press", "name": "Barbell Overhead Press", "muscle": "Omuz", "bw": False, "weighted": False},
    {"id": "shoulder_press", "name": "Shoulder Press", "muscle": "Omuz", "bw": False, "weighted": False},
    {"id": "shoulder_press_machine", "name": "Shoulder Press Machine", "muscle": "Omuz", "bw": False, "weighted": False},
    {"id": "arnold_press", "name": "Dumbbell Arnold Press", "muscle": "Omuz", "bw": False, "weighted": False},
    {"id": "barbell_arnold_press", "name": "Barbell Arnold Press", "muscle": "Omuz", "bw": False, "weighted": False},
    {"id": "lateral_raise", "name": "Lateral Raise", "muscle": "Omuz", "bw": False, "weighted": False},
    {"id": "cable_lateral", "name": "Cable Lateral Raise", "muscle": "Omuz", "bw": False, "weighted": False},
    {"id": "front_raise", "name": "Dumbbell Front Raise", "muscle": "Omuz", "bw": False, "weighted": False},
    {"id": "rear_delt_fly", "name": "Rear Delt Fly", "muscle": "Omuz", "bw": False, "weighted": False},
    {"id": "reverse_fly", "name": "Reverse Fly", "muscle": "Omuz", "bw": False, "weighted": False},
    {"id": "upright_row", "name": "Upright Row", "muscle": "Omuz", "bw": False, "weighted": False},
    {"id": "face_pull_shoulder", "name": "Face Pull", "muscle": "Omuz", "bw": False, "weighted": False},

    # ─── QUADRICEPS ───
    {"id": "squat", "name": "Squat", "muscle": "Quadriceps", "bw": False, "weighted": False},
    {"id": "front_squat", "name": "Front Squat", "muscle": "Quadriceps", "bw": False, "weighted": False},
    {"id": "hack_squat", "name": "Hack Squat", "muscle": "Quadriceps", "bw": False, "weighted": False},
    {"id": "leg_press", "name": "Leg Press", "muscle": "Quadriceps", "bw": False, "weighted": False},
    {"id": "leg_extension", "name": "Leg Extension", "muscle": "Quadriceps", "bw": False, "weighted": False},
    {"id": "bulgarian_split", "name": "Bulgarian Split Squat", "muscle": "Quadriceps", "bw": True, "weighted": True},
    {"id": "weighted_bulgarian_split", "name": "Bulgarian Split Squat", "muscle": "Quadriceps", "bw": False, "weighted": True},
    {"id": "goblet_squat", "name": "Goblet Squat", "muscle": "Quadriceps", "bw": False, "weighted": False},
    {"id": "bodyweight_squat", "name": "Bodyweight Squat", "muscle": "Quadriceps", "bw": True, "weighted": True},

    # ─── HAMSTRING ───
    {"id": "romanian_deadlift", "name": "Romanian Deadlift", "muscle": "Hamstring", "bw": False, "weighted": False},
    {"id": "deadlift", "name": "Deadlift", "muscle": "Hamstring", "bw": False, "weighted": False},
    {"id": "leg_curl", "name": "Leg Curl", "muscle": "Hamstring", "bw": False, "weighted": False},
    {"id": "nordic_curl", "name": "Nordic Hamstring Curl", "muscle": "Hamstring", "bw": True, "weighted": False},
    {"id": "weighted_nordic_curl", "name": "Weighted Nordic Hamstring Curl", "muscle": "Hamstring", "bw": False, "weighted": True},
    {"id": "good_morning", "name": "Good Morning", "muscle": "Hamstring", "bw": False, "weighted": False},
    {"id": "stiff_leg_deadlift", "name": "Stiff-Leg Deadlift", "muscle": "Hamstring", "bw": False, "weighted": False},

    # ─── GLUTE ───
    {"id": "hip_thrust", "name": "Barbell Hip Thrust", "muscle": "Glute", "bw": False, "weighted": False},
    {"id": "weight_bulgarian_split", "name": "Bulgarian Split Squat", "muscle": "Glute", "bw": False, "weighted": True},
    {"id": "cable_kickback", "name": "Cable Glute Kickback", "muscle": "Glute", "bw": False, "weighted": False},
    {"id": "glute_bridge", "name": "Glute Bridge", "muscle": "Glute", "bw": True, "weighted": False},
    {"id": "step_up", "name": "Step-Up", "muscle": "Glute", "bw": False, "weighted": False},

    # ─── CALF ───
    {"id": "standing_calf_raise", "name": "Standing Calf Raise", "muscle": "Calf", "bw": False, "weighted": False},
    {"id": "dumbbell_calf_raise", "name": "Dumbbell Calf Raise", "muscle": "Calf", "bw": False, "weighted": False},
    {"id": "barbell_calf_raise", "name": "Barbell Calf Raise", "muscle": "Calf", "bw": False, "weighted": False},
    {"id": "seated_calf_raise", "name": "Seated Calf Raise", "muscle": "Calf", "bw": False, "weighted": False},
    {"id": "bodyweight_calf", "name": "Bodyweight Calf Raise", "muscle": "Calf", "bw": True, "weighted": False},

    # ─── BICEPS ───
    {"id": "barbell_curl", "name": "Barbell Curl", "muscle": "Biceps", "bw": False, "weighted": False},
    {"id": "db_curl", "name": "Dumbbell Curl", "muscle": "Biceps", "bw": False, "weighted": False},
    {"id": "hammer_curl", "name": "Hammer Curl", "muscle": "Biceps", "bw": False, "weighted": False},
    {"id": "dumbbell_preacher_curl", "name": "Dumbbell Preacher Curl", "muscle": "Biceps", "bw": False, "weighted": False},
    {"id": "EZ_bar_preacher_curl", "name": "EZ Bar Preacher Curl", "muscle": "Biceps", "bw": False, "weighted": False},
    {"id": "incline_curl", "name": "Incline Dumbbell Curl", "muscle": "Biceps", "bw": False, "weighted": False},
    {"id": "concentration_curl", "name": "Concentration Curl", "muscle": "Biceps", "bw": False, "weighted": False},

    # ─── TRICEPS ───
    {"id": "triceps_pushdown", "name": "Cable Triceps Pushdown", "muscle": "Triceps", "bw": False, "weighted": False},
    {"id": "overhead_extension", "name": "Overhead Triceps Extension", "muscle": "Triceps", "bw": False, "weighted": False},
    {"id": "skull_crusher", "name": "Skull Crusher", "muscle": "Triceps", "bw": False, "weighted": False},
    {"id": "db_kickback", "name": "Dumbbell Triceps Kickback", "muscle": "Triceps", "bw": False, "weighted": False},
    {"id": "close_grip_bench", "name": "Close-Grip Bench Press", "muscle": "Triceps", "bw": False, "weighted": False},
    {"id": "bench_dip", "name": "Bench Dip", "muscle": "Triceps", "bw": True, "weighted": True},
    {"id": "bodyweight_dip", "name": "Bodyweight Dip", "muscle": "Triceps", "bw": True, "weighted": True},
    {"id": "weighted_dip", "name": "Weighted Dip", "muscle": "Triceps", "bw": False, "weighted": True},
    {"id": "diamond_push_up", "name": "Diamond Push Up", "muscle": "Triceps", "bw": True, "weighted": False},

    # ─── CORE / ABDOMINALS ───
    {"id": "cable_crunch", "name": "Cable Crunch", "muscle": "Core", "bw": False, "weighted": False},
    {"id": "hanging_leg_raise", "name": "Hanging Leg Raise", "muscle": "Core", "bw": True, "weighted": True},
    {"id": "plank", "name": "Plank", "muscle": "Core", "bw": True, "weighted": False},
    {"id": "crunch", "name": "Crunch", "muscle": "Core", "bw": True, "weighted": False},
    {"id": "ab_wheel", "name": "Ab Wheel Rollout", "muscle": "Core", "bw": True, "weighted": False},
    {"id": "weighted_russian_twist", "name": "Weighted Russian Twist", "muscle": "Core", "bw": False, "weighted": True},
    {"id": "russian_twist", "name": "Russian Twist", "muscle": "Core", "bw": True, "weighted": False},

    # ─── COMPOUND HAREKETLER ───
    #{"id": "compound_ohp", "name": "Barbell Overhead Press", "muscle": "Omuz", "bw": False, "weighted": False},
    #{"id": "compound_incline_bb", "name": "Incline Barbell Press", "muscle": "Göğüs", "bw": False, "weighted": False},
    #{"id": "compound_incline_db", "name": "Incline Dumbbell Press", "muscle": "Göğüs", "bw": False, "weighted": False},
    #{"id": "compound_db_press", "name": "Dumbbell Bench Press", "muscle": "Göğüs", "bw": False, "weighted": False},
    #{"id": "compound_deadlift", "name": "Conventional Deadlift", "muscle": "Sırt", "bw": False, "weighted": False},
    #{"id": "compound_squat", "name": "Squat", "muscle": "Quadriceps", "bw": False, "weighted": False},
    #{"id": "compound_pull_up", "name": "Weighted Pull-Up", "muscle": "Sırt", "bw": False, "weighted": True},
    #{"id": "compound_row", "name": "Barbell Row", "muscle": "Sırt", "bw": False, "weighted": False},
    #{"id": "compound_dip", "name": "Weighted Dip", "muscle": "Göğüs", "bw": False, "weighted": True},
    #{"id": "compound_bulgarian", "name": "Bulgarian Split Squat", "muscle": "Quadriceps", "bw": False, "weighted": True},
    #{"id": "compound_romanian_deadlift", "name": "Romanian Deadlift", "muscle": "Hamstring", "bw": False, "weighted": False}
]

# Kas grupları listesi (frontende gönderilecek)
MUSCLE_GROUPS = sorted(set(e["muscle"] for e in EXERCISE_POOL))


# ═══════════════════════════════════════════════
# VERİTABANI
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
    
    # Custom Split Sütunu Kontrolü
    try:
        cur.execute("ALTER TABLE users ADD COLUMN custom_split TEXT NOT NULL DEFAULT '[]'")
    except Exception:
        pass

    # daily_nutrition sütunu kontrolü
    try:
        cur.execute("ALTER TABLE users ADD COLUMN daily_nutrition TEXT NOT NULL DEFAULT '{}'")
    except Exception:
        pass

    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════
# ŞİFRE İŞLEMLERİ
# ═══════════════════════════════════════════════
def _hash_password(password: str):
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return h, salt


def _verify_password(stored_hash: str, salt: str, password: str) -> bool:
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return h == stored_hash


def _is_admin(username: str, password: str) -> bool:
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD


# ═══════════════════════════════════════════════
# VERİTABANI FONKSİYONLARI
# ═══════════════════════════════════════════════
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
    h, s = _hash_password(password)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, password_salt) VALUES (?, ?, ?)",
            (username, h, s)
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
    allowed = ['age', 'gender', 'height', 'weight', 'fitness_level', 'goal', 'days_per_week', 'session_time_mins']
    for key, val in data.items():
        if key in allowed and val is not None:
            fields.append(f"{key}=?")
            values.append(val)
    if fields:
        values.append(username)
        conn.execute(f"UPDATE users SET {','.join(fields)}, updated_at=datetime('now') WHERE username=?", values)
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
        except:
            d["exercises"] = []
        result.append(d)
    return result


def create_workout(user_id: int, data: dict):
    exercises = data.get("exercises", [])
    total_volume = 0.0
    for ex in exercises:
        sets_list = ex.get("sets_data", [])
        for s in sets_list:
            total_volume += float(s.get("reps", 0)) * float(s.get("weight_kg", 0))

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO workouts (user_id, date, session_type, notes, total_volume, exercises) VALUES (?,?,?,?,?,?)",
        (user_id, data["date"], data["session_type"], data.get("notes", ""), total_volume, json.dumps(exercises, ensure_ascii=False))
    )
    conn.commit()
    wid = cur.lastrowid
    conn.close()
    return {"id": wid, "message": "Antrenman kaydedildi"}


def delete_workout(workout_id: int, user_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM workouts WHERE id = ? AND user_id = ?", (workout_id, user_id)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Antrenman bulunamadı")
    conn.execute("DELETE FROM workouts WHERE id = ?", (workout_id,))
    conn.commit()
    conn.close()
    return {"message": "Antrenman silindi"}


def update_workout(workout_id: int, data: dict, user_id: int):
    """Admin veya kullanıcı tarafından antrenman düzenleme."""
    conn = get_db()
    row = conn.execute("SELECT * FROM workouts WHERE id = ? AND user_id = ?", (workout_id, user_id)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Antrenman bulunamadı")

    exercises = data.get("exercises", json.loads(row["exercises"]))
    total_volume = 0.0
    for ex in exercises:
        sets_list = ex.get("sets_data", [])
        for s in sets_list:
            total_volume += float(s.get("reps", 0)) * float(s.get("weight_kg", 0))

    conn.execute(
        "UPDATE workouts SET date=?, session_type=?, notes=?, total_volume=?, exercises=? WHERE id=? AND user_id=?",
        (data.get("date", row["date"]),
         data.get("session_type", row["session_type"]),
         data.get("notes", row["notes"]),
         total_volume,
         json.dumps(exercises, ensure_ascii=False),
         workout_id, user_id)
    )
    conn.commit()
    conn.close()
    return {"message": "Antrenman güncellendi"}


# ═══════════════════════════════════════════════
# UZMAN SİSTEMİ
# ═══════════════════════════════════════════════
def calculate_stats(user: dict):
    age = user.get("age", 25)
    gender = user.get("gender", "male")
    height = user.get("height", 170)
    weight = user.get("weight", 70)

    # BMI
    bmi = weight / ((height / 100) ** 2)

    # BMR (Mifflin-St Jeor)
    if gender == "male":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161

    # TDEE (aktiveite seviyesi)
    activity_levels = {"Beginner": 1.4, "Intermediate": 1.55, "Advanced": 1.7}
    activity = activity_levels.get(user.get("fitness_level", "Intermediate"), 1.55)
    tdee = bmr * activity

    # Hedef
    goal = user.get("goal", "bulk")
    if goal == "bulk":
        target_cal = tdee + 400
        macro = {"protein": weight * 2.0, "carbs": weight * 5.0, "fat": weight * 1.0}
    elif goal == "cut":
        target_cal = tdee - 400
        macro = {"protein": weight * 2.2, "carbs": weight * 2.5, "fat": weight * 0.9}
    else:
        target_cal = tdee
        macro = {"protein": weight * 2.0, "carbs": weight * 4.0, "fat": weight * 1.0}

    return {
        "bmi": round(bmi, 1),
        "bmr": round(bmr),
        "tdee": round(tdee),
        "target_calories": round(target_cal),
        "macro": {k: round(v, 1) for k, v in macro.items()},
        "bmi_category": "Düşük" if bmi < 18.5 else "Normal" if bmi < 25 else "Fazla" if bmi < 30 else "Obez"
    }


def generate_split(days: int, goal: str):
    if days <= 2:
        return {"split": "Full Body", "days": [{"day": f"Day {i+1}", "type": "Full Body"} for i in range(days)]}
    elif days == 3:
        return {"split": "Upper-Lower / Full Body Split", "days": [
            {"day": "Day 1", "type": "Upper (Sırt, Göğüs, Omuz, Kollar)"},
            {"day": "Day 2", "type": "Rest Day (Dinlenme Günü)"},
            {"day": "Day 3", "type": "Lower (Bacak, Alt bacak, Glute)"},
            {"day": "Day 4", "type": "Rest Day (Dinlenme Günü)"},
            {"day": "Day 5", "type": "Full Body (Tüm Kas Grupları)"},
            {"day": "Day 6", "type": "Rest Day (Dinlenme Günü)"},
            {"day": "Day 7", "type": "Rest Day (Dinlenme Günü)"}
        ]}
    elif days == 4:
        return {"split": "Upper-Lower Split", "days": [
            {"day": "Day 1", "type": "Upper A (Push Focus)"},
            {"day": "Day 2", "type": "Lower A (Quad Focus)"},
            {"day": "Day 3", "type": "Rest Day (Dinlenme Günü)"},
            {"day": "Day 4", "type": "Upper B (Pull Focus)"},
            {"day": "Day 5", "type": "Lower B (Hamstring Focus)"},
            {"day": "Day 6", "type": "Rest Day (Dinlenme Günü)"},
            {"day": "Day 7", "type": "Rest Day (Dinlenme Günü)"}
        ]}
    elif days == 5:
        return {"split": "PPl / Upper-Lower Split", "days": [
            {"day": "Day 1", "type": "Push"},
            {"day": "Day 2", "type": "Pull"},
            {"day": "Day 3", "type": "Legs"},
            {"day": "Day 4", "type": "Rest Day (Dinlenme Günü)"},
            {"day": "Day 5", "type": "Upper"},
            {"day": "Day 6", "type": "Lower"},
            {"day": "Day 7", "type": "Rest Day (Dinlenme Günü)"},
        ]}
    elif days == 6:
        return {"split": "Push-Pull-Legs (PPL)", "days": [
            {"day": "Day 1", "type": "Push"},
            {"day": "Day 2", "type": "Pull"},
            {"day": "Day 3", "type": "Legs"},
            {"day": "Day 4", "type": "Rest Day (Dinlenme Günü)"},
            {"day": "Day 5", "type": "Push"},
            {"day": "Day 6", "type": "Pull"},
            {"day": "Day 7", "type": "Legs"},
        ]}


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
app = FastAPI(title="Hypertrophy-X API", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════
# AUTH ENDPOINT'LERİ
# ═══════════════════════════════════════════════
@app.post("/api/auth/register")
def register(data: AuthRequest = Body(...)):
    if len(data.username) < 2:
        raise HTTPException(status_code=400, detail="Kullanıcı adı en az 2 karakter olmalı")
    if len(data.password) < 3:
        raise HTTPException(status_code=400, detail="Şifre en az 3 karakter olmalı")
    if data.username == ADMIN_USERNAME:
        raise HTTPException(status_code=400, detail="Bu kullanıcı adı kullanılamaz")
    return create_user(data.username, data.password)


@app.post("/api/auth/login")
def login(data: AuthRequest = Body(...)):
    # Admin kontrolü
    if data.username == ADMIN_USERNAME:
        if data.password == ADMIN_PASSWORD:
            return {"username": ADMIN_USERNAME, "is_admin": True}
        raise HTTPException(status_code=401, detail="Admin şifresi hatalı")

    # Normal kullanıcı
    user = get_user_by_username(data.username)
    if not user:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı")
    if not _verify_password(user["password_hash"], user["password_salt"], data.password):
        raise HTTPException(status_code=401, detail="Şifre hatalı")

    # Şifre hash'ini temizle
    user.pop("password_hash", None)
    user.pop("password_salt", None)
    return user


@app.post("/api/auth/change-password")
def change_password(data: dict = Body(...)):
    username = data.get("username", "")
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")

    if username == ADMIN_USERNAME:
        raise HTTPException(status_code=403, detail="Admin şifresi değiştirilemez")

    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    if not _verify_password(user["password_hash"], user["password_salt"], old_password):
        raise HTTPException(status_code=401, detail="Mevcut şifre hatalı")
    if len(new_password) < 3:
        raise HTTPException(status_code=400, detail="Yeni şifre en az 3 karakter olmalı")

    h, s = _hash_password(new_password)
    conn = get_db()
    conn.execute("UPDATE users SET password_hash=?, password_salt=? WHERE username=?", (h, s, username))
    conn.commit()
    conn.close()
    return {"message": "Şifre güncellendi"}


# ═══════════════════════════════════════════════
# KULLANICI ENDPOINT'LERİ
# ═══════════════════════════════════════════════
@app.get("/api/user")
def get_user(username: str = Query(...)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    user.pop("password_hash", None)
    user.pop("password_salt", None)
    return user


@app.post("/api/user")
def save_user(data: UserProfile = Body(...)):
    result = update_user_profile(data.model_dump(), data.username)
    result.pop("password_hash", None)
    result.pop("password_salt", None)
    return result


# ═══════════════════════════════════════════════
# ANTRENMAN ENDPOINT'LERİ
# ═══════════════════════════════════════════════
@app.post("/api/workouts")
def save_workout(data: WorkoutCreate = Body(...), username: str = Query(...)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    return create_workout(user["id"], data.model_dump())


@app.get("/api/workouts")
def list_workouts(username: str = Query(...)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    return get_workouts_by_user(user["id"])


@app.delete("/api/workouts/{workout_id}")
def delete_workout_endpoint(workout_id: int, username: str = Query(...)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    return delete_workout(workout_id, user["id"])


@app.put("/api/workouts/{workout_id}")
def update_workout_endpoint(workout_id: int, data: WorkoutUpdate = Body(...), username: str = Query(...)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    return update_workout(workout_id, data.model_dump(exclude_unset=True), user["id"])


# ═══════════════════════════════════════════════
# ADMIN ENDPOINT'LERİ
# ═══════════════════════════════════════════════
@app.get("/api/admin/users")
def admin_list_users():
    users = get_all_users()
    for u in users:
        u.pop("password_hash", None)
        u.pop("password_salt", None)
    return users


@app.get("/api/admin/workouts/{user_id}")
def admin_get_user_workouts(user_id: int):
    """Admin: Belirli bir kullanıcının tüm antrenmanlarını getir."""
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    workouts = get_workouts_by_user(user_id)
    return {"user": user["username"], "workouts": workouts}


@app.put("/api/admin/workout/{workout_id}")
def admin_update_workout(workout_id: int, data: WorkoutUpdate = Body(...), username: str = Query(...)):
    """Admin: Herhangi bir kullanıcının antrenmanını düzenle."""
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    conn = get_db()
    row = conn.execute("SELECT * FROM workouts WHERE id = ?", (workout_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Antrenman bulunamadı")
    target_user_id = row["user_id"]
    conn.close()
    return update_workout(workout_id, data.model_dump(exclude_unset=True), target_user_id)


@app.delete("/api/admin/workout/{workout_id}")
def admin_delete_workout(workout_id: int):
    """Admin: Herhangi bir antrenmanı sil."""
    conn = get_db()
    row = conn.execute("SELECT * FROM workouts WHERE id = ?", (workout_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Antrenman bulunamadı")
    user_id = row["user_id"]
    conn.close()
    return delete_workout(workout_id, user_id)


@app.put("/api/admin/user")
def admin_edit_user(data: AdminEditUser = Body(...)):
    """Admin: Kullanıcı bilgilerini düzenle."""
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
        h, s = _hash_password(new_pass)
        fields.append("password_hash=?")
        values.append(h)
        fields.append("password_salt=?")
        values.append(s)

    if fields:
        fields.append("updated_at=datetime('now')")
        values.append(data.user_id)
        conn.execute(f"UPDATE users SET {','.join(fields)} WHERE id=?", values)
        conn.commit()

    conn.close()
    result = get_user_by_id(data.user_id)
    result.pop("password_hash", None)
    result.pop("password_salt", None)
    return result


@app.delete("/api/admin/user/{user_id}")
def admin_delete_user(user_id: int):
    """Admin: Kullanıcı sil."""
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
def analyze(data: AnalyzeRequest = Body(...), username: str = Query(...)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    stats = calculate_stats(user)
    split = generate_split(user.get("days_per_week", 4), user.get("goal", "bulk"))
    stats["split"] = split
    stats["rest_days"] = 7 - user.get("days_per_week", 4)

    # Durgunluk analizi
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
# DAHSBOARD
# ═══════════════════════════════════════════════
@app.get("/api/dashboard")
def dashboard(username: str = Query(...)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    workouts = get_workouts_by_user(user["id"])
    now = datetime.now()

    # Haftalık
    week_start = now - timedelta(days=now.weekday())
    weekly = [w for w in workouts if datetime.strptime(w["date"], "%Y-%m-%d") >= week_start]

    # Aylık
    month_start = now.replace(day=1)
    monthly = [w for w in workouts if datetime.strptime(w["date"], "%Y-%m-%d") >= month_start]

    # Seri (streak) hesaplama
    streak = 0
    check_date = now.date()
    for w in sorted(workouts, key=lambda x: x["date"], reverse=True):
        w_date = datetime.strptime(w["date"], "%Y-%m-%d").date()
        if (check_date - w_date).days <= 1:
            streak += 1
            check_date = w_date
        else:
            break

    # Dinlenme süreleri
    rest_days = 7 - user.get("days_per_week", 4)
    split_info = generate_split(user.get("days_per_week", 4), user.get("goal", "bulk"))

    # Kas grubu dağılımı
    muscle_count = {}
    for w in workouts:
        for ex in w.get("exercises", []):
            m = ex.get("muscle_group", "Bilinmiyor")
            muscle_count[m] = muscle_count.get(m, 0) + 1

    # Kas dağılımını hesaplayan pratik bir alt fonksiyon
    def get_muscle_distribution(workout_list):
        dist = {}
        for w in workout_list:
            exercises_raw = w.get("exercises", [])
            # Eğer exercises string (JSON) olarak kayıtlıysa listeye çevir
            if isinstance(exercises_raw, str):
                try:
                    exercises_list = json.loads(exercises_raw)
                except:
                    exercises_list = []
            else:
                exercises_list = exercises_raw
                
            for ex in exercises_list:
                m = ex.get("muscle_group", ex.get("muscle", "Bilinmiyor"))
                dist[m] = dist.get(m, 0) + 1
        return dist

    # Her 3 zaman dilimi için ayrı ayrı dağılımı çıkarıyoruz
    muscle_dist_all = get_muscle_distribution(workouts)
    muscle_dist_weekly = get_muscle_distribution(weekly)
    muscle_dist_monthly = get_muscle_distribution(monthly)

    stats = calculate_stats(user)
    sessions_data = [{"date": w["date"], "type": w.get("session_type", "Workout")} for w in workouts]

    # Return kısmını güncelliyoruz (muscle_distribution artık 3 parçalı bir obje)
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
def progress(username: str = Query(...)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    workouts = get_workouts_by_user(user["id"])

    # Hacim zaman serisi
    volume_timeline = []
    for w in sorted(workouts, key=lambda x: x["date"]):
        volume_timeline.append({
            "date": w["date"],
            "volume": w["total_volume"],
            "session": w["session_type"]
        })

    # Haftalık ortalamalar
    weekly_avgs = {}
    for w in workouts:
        week_label = w["date"][:7]
        if week_label not in weekly_avgs:
            weekly_avgs[week_label] = []
        weekly_avgs[week_label].append(w["total_volume"])
    weekly_avg_data = [{"week": k, "avg_volume": round(sum(v) / len(v))} for k, v in sorted(weekly_avgs.items())]

    return {
        "volume_timeline": volume_timeline,
        "weekly_averages": weekly_avg_data,
        "personal_records": get_personal_records(workouts),
        "stats": calculate_stats(user)
    }

# Egzersiz İlerleme Analizi
@app.get("/api/progress/chart")
def get_exercise_chart_data(username: str = Query(...), exercise: str = Query(...)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

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
            except:
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
                            details.append({
                                "set": idx,
                                "reps": reps
                            })
                    except:
                        continue

    return {
        "labels": labels,
        "data": weights,
        "details": details
    }

def get_personal_records(workouts):
    """Her egzersiz için en yüksek hacmi bul."""
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
# Özel Program
# ═══════════════════════════════════════════════
@app.post("/api/custom-program")
async def save_custom_program(data: CustomProgramRequest):
    # 1. Kullanıcıyı doğrula
    user = get_user_by_username(data.username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    # 2. Pydantic modelini (List[List[CustomDay]]) veritabanı için string (JSON) formatına çevir
    program_list = [[day.model_dump() for day in week] for week in data.program]
    program_json = json.dumps(program_list, ensure_ascii=False)

    # 3. Veritabanına kaydet
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET custom_split = ? WHERE id = ?", (program_json, user["id"]))
        conn.commit()
        return {"success": True, "message": f"{len(data.program)} Haftalık periyot başarıyla kaydedildi!"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Kayıt sırasında veritabanı hatası: {str(e)}")
    finally:
        conn.close()


@app.get("/api/exercises")
def get_exercises():
    """Egzersiz havuzu + kas grupları."""
    return {
        "exercises": EXERCISE_POOL,
        "muscle_groups": MUSCLE_GROUPS
    }

# ═══════════════════════════════════════════════
# BESLENME ENDPOINT'LERİ
# ═══════════════════════════════════════════════

@app.get("/api/nutrition/today")
def get_today_nutrition(username: str = Query(...)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    
    raw_nutri = user.get("daily_nutrition", "{}")
    try:
        history_dict = json.loads(raw_nutri) if isinstance(raw_nutri, str) else raw_nutri
    except:
        history_dict = {}
        
    today_str = str(date.today())
    today_log = history_dict.get(today_str, {"calories": 0, "protein": 0, "carbs": 0, "fat": 0})
        
    return {"success": True, "log": today_log}


@app.get("/api/nutrition/history")
def get_nutrition_history(username: str = Query(...)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    
    raw_nutri = user.get("daily_nutrition", "{}")
    try:
        history_dict = json.loads(raw_nutri) if isinstance(raw_nutri, str) else raw_nutri
    except:
        history_dict = {}
        
    history_list = []
    for date_str, data in history_dict.items():
        item = {"date": date_str}
        item.update(data)
        history_list.append(item)
        
    history_list.sort(key=lambda x: x["date"], reverse=True)
    return {"success": True, "history": history_list}


@app.post("/api/nutrition/log")
def save_nutrition_log(data: NutritionLogSchema):
    user = get_user_by_username(data.username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    raw_nutri = user.get("daily_nutrition", "{}")
    try:
        history_dict = json.loads(raw_nutri) if isinstance(raw_nutri, str) else raw_nutri
    except:
        history_dict = {}

    target_date = data.log_date or str(date.today())
    
    # Gelecek gün kontrolü
    if target_date > str(date.today()):
        raise HTTPException(status_code=400, detail="Gelecek gün için kayıt yapılamaz")

    # Makrolardan kalori hesapla (eğer kalori 0 ise)
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
        (json.dumps(history_dict, ensure_ascii=False), data.username)
    )
    conn.commit()
    conn.close()

    return {"success": True, "message": "Beslenme verisi kaydedildi"}


@app.delete("/api/nutrition/log")
def delete_nutrition_log(username: str = Query(...), log_date: str = Query(...)):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    raw_nutri = user.get("daily_nutrition", "{}")
    try:
        history_dict = json.loads(raw_nutri) if isinstance(raw_nutri, str) else raw_nutri
    except:
        history_dict = {}

    if log_date in history_dict:
        del history_dict[log_date]
        conn = get_db()
        conn.execute(
            "UPDATE users SET daily_nutrition = ?, updated_at = datetime('now') WHERE username = ?",
            (json.dumps(history_dict, ensure_ascii=False), username)
        )
        conn.commit()
        conn.close()

    return {"success": True, "message": "Kayıt başarıyla silindi"}

# ═══════════════════════════════════════════════
# STATIC DOSYALAR
# ═══════════════════════════════════════════════
app.mount("/", StaticFiles(directory="static", html=True), name="static")


@app.get("/app")
def serve_app():
    return FileResponse("static/index.html")

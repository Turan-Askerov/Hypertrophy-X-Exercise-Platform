"""Beslenme takibi API uç noktaları."""
import json
import logging
from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from core.database import get_db
from core.security import _resolve_current_user
from models.schemas import NutritionLogSchema, NutritionLogUpdateSchema

logger = logging.getLogger("hypertrophy-x")

router = APIRouter(prefix="/api/nutrition", tags=["nutrition"])


@router.get("/today")
def get_today_nutrition(user: dict = Depends(_resolve_current_user)):
    raw_nutri = user.get("daily_nutrition", "{}")
    try:
        history_dict = json.loads(raw_nutri) if isinstance(raw_nutri, str) else raw_nutri
    except Exception:
        history_dict = {}

    today_str = str(date.today())
    today_log = history_dict.get(
        today_str, {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}
    )
    return {"success": True, "log": today_log}


@router.get("/history")
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


@router.post("/log")
def save_nutrition_log(
    data: NutritionLogSchema,
    current_user: dict = Depends(_resolve_current_user),
):
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
        "updated_at": str(datetime.now()),
    }

    conn = get_db()
    conn.execute(
        "UPDATE users SET daily_nutrition = ?, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
        (json.dumps(history_dict, ensure_ascii=False), current_user["username"]),
    )
    conn.commit()
    conn.close()
    return {"success": True, "message": "Beslenme verisi kaydedildi"}


@router.put("/log")
def update_nutrition_log(
    data: NutritionLogUpdateSchema,
    current_user: dict = Depends(_resolve_current_user),
):
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

    del history_dict[original_day.isoformat()]
    history_dict[target_day.isoformat()] = {
        "calories": calories,
        "protein": data.protein,
        "carbs": data.carbs,
        "fat": data.fat,
        "notes": data.notes or "",
        "updated_at": str(datetime.now()),
    }

    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET daily_nutrition = ?, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
            (json.dumps(history_dict, ensure_ascii=False), current_user["username"]),
        )
        conn.commit()
    finally:
        conn.close()
    return {"success": True, "message": "Beslenme kaydı güncellendi", "date": target_day.isoformat()}


@router.delete("/log")
def delete_nutrition_log(
    log_date: str = Query(...),
    user: dict = Depends(_resolve_current_user),
):
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
            (json.dumps(history_dict, ensure_ascii=False), user["username"]),
        )
        conn.commit()
        conn.close()
        return {"success": True, "message": "Beslenme kaydı silindi"}
    return {"success": False, "message": "Kayıt bulunamadı"}

"""Kullanıcı profili görüntüleme ve güncelleme API uç noktaları."""
import logging
from fastapi import APIRouter, Body, Depends, HTTPException

from core.security import _resolve_current_user
from models.schemas import UserProfile
from services.user_service import update_user_profile

logger = logging.getLogger("hypertrophy-x")

router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("")
@router.get("/")
def get_user(user: dict = Depends(_resolve_current_user)):
    return user


@router.post("")
@router.post("/")
def save_user(
    data: UserProfile = Body(...),
    current_user: dict = Depends(_resolve_current_user),
):
    try:
        # Token'daki kullanıcı sadece KENDİ profilini düzenleyebilir
        if data.username.strip().lower() != current_user["username"].strip().lower():
            raise HTTPException(status_code=403, detail="Başkasının profili düzenlenemez")
        result = update_user_profile(data.model_dump(), current_user["username"])
        if not result:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        result.pop("password_hash", None)
        result.pop("password_salt", None)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"save_user error for {data.username}: {exc}")
        raise HTTPException(status_code=500, detail="Profil güncellenirken hata oluştu")

"""Kimlik doğrulama ve şifre sıfırlama API uç noktaları."""
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException

from core.config import (
    ADMIN_USERNAME,
    SMTP_PASS,
    SMTP_USER,
)
from core.database import get_db
from core.email import mask_email, send_password_reset_email
from core.security import (
    ADMIN_PASSWORD_HASH,
    _create_access_token,
    _hash_password,
    _require_admin,
    _resolve_current_user,
    _upgrade_to_bcrypt_if_needed,
    _verify_admin_password,
    _verify_password,
)
from models.schemas import (
    AuthRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyResetCodeRequest,
)
from services.user_service import (
    create_user,
    get_user_by_email_or_username,
    get_user_by_username,
)

logger = logging.getLogger("hypertrophy-x")

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
def register(data: AuthRequest = Body(...)):
    if len(data.username) < 2:
        raise HTTPException(status_code=400, detail="Kullanıcı adı en az 2 karakter olmalı")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Şifre en az 6 karakter olmalı")
    if data.username == ADMIN_USERNAME:
        raise HTTPException(status_code=400, detail="Bu kullanıcı adı kullanılamaz")
    return create_user(data.username, data.password, data.email or "")


@router.post("/login")
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


@router.post("/change-password")
def change_password(
    user: dict = Depends(_resolve_current_user),
    data: dict = Body(...),
):
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
        (user["username"],),
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
        (_hash_password(new_password), user["username"]),
    )
    conn.commit()
    conn.close()
    return {"message": "Şifre güncellendi"}


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest = Body(...)):
    """1. Adım: Kullanıcı adı veya e-posta ile 4 haneli doğrulama kodu üretir ve e-posta gönderir."""
    target = str(data.email_or_username or "").strip()
    if not target:
        raise HTTPException(
            status_code=400, detail="Lütfen kullanıcı adı veya e-posta adresinizi girin."
        )

    user = get_user_by_email_or_username(target)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Bu kullanıcı adı veya e-posta ile kayıtlı bir hesap bulunamadı.",
        )

    user_email = str(user.get("email") or "").strip()
    if not user_email and "@" in target:
        user_email = target.lower()
        conn = get_db()
        conn.execute("UPDATE users SET email = ? WHERE id = ?", (user_email, user["id"]))
        conn.execute(
            "UPDATE athlete_profiles SET email = ? WHERE user_id = ?",
            (user_email, user["id"]),
        )
        conn.commit()
        conn.close()

    if not user_email:
        raise HTTPException(
            status_code=400,
            detail="Bu hesaba henüz bir e-posta adresi tanımlanmamış. Lütfen sistem yöneticisi ile iletişime geçin.",
        )

    code = f"{secrets.randbelow(10000):04d}"
    reset_token = secrets.token_hex(20)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()

    conn = get_db()
    conn.execute(
        "INSERT INTO password_resets (user_id, email, code, reset_token, expires_at, used) VALUES (?, ?, ?, ?, ?, 0)",
        (user["id"], user_email, code, reset_token, expires_at),
    )
    conn.commit()
    conn.close()

    sent = send_password_reset_email(user_email, user["username"], code)
    if not sent and SMTP_USER and SMTP_PASS:
        raise HTTPException(
            status_code=500,
            detail="E-posta gönderilirken bir hata oluştu. Lütfen biraz sonra tekrar deneyin.",
        )

    return {
        "success": True,
        "reset_token": reset_token,
        "masked_email": mask_email(user_email),
        "expires_in_minutes": 15,
        "message": f"{mask_email(user_email)} adresine 4 haneli doğrulama kodu gönderildi.",
    }


@router.post("/verify-reset-code")
def verify_reset_code(data: VerifyResetCodeRequest = Body(...)):
    """2. Adım: 4 haneli doğrulama kodunu kontrol eder; doğruysa şifre sıfırlama biletini onaylar."""
    token = str(data.reset_token or "").strip()
    code = str(data.code or "").strip()

    if not token or not code:
        raise HTTPException(
            status_code=400, detail="Doğrulama kodu ve sıfırlama bileti gereklidir."
        )
    if len(code) != 4 or not code.isdigit():
        raise HTTPException(
            status_code=400, detail="Doğrulama kodu 4 haneli bir sayı olmalıdır."
        )

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM password_resets WHERE reset_token = ? AND used = 0 ORDER BY id DESC LIMIT 1",
        (token,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(
            status_code=400, detail="Geçersiz veya süresi dolmuş sıfırlama talebi."
        )

    record = dict(row)
    try:
        exp_str = record["expires_at"]
        if isinstance(exp_str, str):
            exp_time = datetime.fromisoformat(exp_str)
        else:
            exp_time = exp_str
        now = (
            datetime.now(exp_time.tzinfo)
            if getattr(exp_time, "tzinfo", None)
            else datetime.now(timezone.utc)
        )
        if now > exp_time:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail="Doğrulama kodunun süresi (15 dk) dolmuş. Lütfen yeni bir kod isteyin.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(f"Süre ayrıştırma uyarısı: {exc}")

    if str(record["code"]).strip() != code:
        conn.close()
        raise HTTPException(
            status_code=400, detail="Girdiğiniz 4 haneli doğrulama kodu hatalı."
        )

    verified_token = secrets.token_hex(20)
    conn.execute(
        "UPDATE password_resets SET verified_token = ? WHERE id = ?",
        (verified_token, record["id"]),
    )
    conn.commit()
    conn.close()

    return {
        "success": True,
        "verified_token": verified_token,
        "message": "Doğrulama başarılı! Şimdi yeni şifrenizi belirleyebilirsiniz.",
    }


@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest = Body(...)):
    """3. Adım: Onaylanan biletle kullanıcının yeni şifresini kaydeder."""
    token = str(data.verified_token or "").strip()
    new_password = str(data.new_password or "").strip()

    if not token or not new_password:
        raise HTTPException(
            status_code=400,
            detail="Geçerli bir yetkilendirme bileti ve yeni şifre gereklidir.",
        )
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Yeni şifre en az 6 karakter olmalıdır.")

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM password_resets WHERE verified_token = ? AND used = 0 ORDER BY id DESC LIMIT 1",
        (token,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Yetkilendirme oturumu geçersiz, süresi dolmuş veya daha önce kullanılmış.",
        )

    record = dict(row)
    user_id = record["user_id"]
    new_hash = _hash_password(new_password)

    conn.execute(
        "UPDATE users SET password_hash = ?, password_salt = '', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_hash, user_id),
    )
    conn.execute("UPDATE password_resets SET used = 1 WHERE id = ?", (record["id"],))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": "Şifreniz başarıyla sıfırlandı. Yeni şifrenizle giriş yapabilirsiniz.",
    }

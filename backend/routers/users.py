"""Kullanıcı profili görüntüleme ve güncelleme API uç noktaları."""
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException

from core.config import ADMIN_USERNAME, DATABASE_BACKEND
from core.database import get_db
from core.email import mask_email, send_security_code_email
from core.security import _resolve_current_user, _verify_password
from models.schemas import (
    DeleteAccountRequest,
    EmailConfirmRequest,
    EmailUpdateRequest,
    UserProfile,
)
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

        dump = data.model_dump()
        current_email = str(current_user.get("email") or "").strip().lower()
        new_email = str(dump.get("email") or "").strip().lower()

        # E-posta adresinin sessizce OTP olmadan değiştirilmesini engelle
        if current_email and new_email and new_email != current_email:
            dump.pop("email", None)

        result = update_user_profile(dump, current_user["username"])
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


@router.post("/email/request-update")
def request_email_update(
    data: EmailUpdateRequest = Body(...),
    current_user: dict = Depends(_resolve_current_user),
):
    """1. Adım: Kullanıcının yeni e-posta adresine 6 haneli OTP doğrulama kodu gönderir."""
    new_email = str(data.new_email or "").strip().lower()
    if not new_email or "@" not in new_email or "." not in new_email.split("@")[-1]:
        raise HTTPException(
            status_code=400, detail="Lütfen geçerli bir e-posta adresi girin."
        )

    current_email = str(current_user.get("email") or "").strip().lower()
    if current_email == new_email:
        raise HTTPException(
            status_code=400,
            detail="Girdiğiniz e-posta adresi zaten mevcut kayıtlı e-posta adresinizdir.",
        )

    # Başka bir kullanıcı tarafından kullanılıp kullanılmadığını kontrol et
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM users WHERE LOWER(email) = ? AND id != ?",
        (new_email, current_user["id"]),
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="Bu e-posta adresi başka bir kullanıcı tarafından kullanılmaktadır.",
        )

    code = f"{secrets.randbelow(1000000):06d}"
    token = secrets.token_hex(20)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()

    conn.execute(
        "INSERT INTO security_verifications (user_id, action, payload, code, token, expires_at, used, failed_attempts) "
        "VALUES (?, 'email_update', ?, ?, ?, ?, 0, 0)",
        (current_user["id"], new_email, code, token, expires_at),
    )
    conn.commit()
    conn.close()

    sent = send_security_code_email(
        new_email, current_user["username"], code, action_type="email_update"
    )
    if not sent:
        logger.warning(f"E-posta gönderim uyarısı: {new_email}")

    return {
        "success": True,
        "token": token,
        "masked_email": mask_email(new_email),
        "message": f"{mask_email(new_email)} adresine 6 haneli doğrulama kodu gönderildi.",
    }


@router.post("/email/confirm-update")
def confirm_email_update(
    data: EmailConfirmRequest = Body(...),
    current_user: dict = Depends(_resolve_current_user),
):
    """2. Adım: Yeni e-postaya gönderilen 6 haneli OTP kodunu kontrol eder ve onaylar."""
    token = str(data.token or "").strip()
    code = str(data.code or "").strip()

    if not token or not code:
        raise HTTPException(
            status_code=400, detail="Doğrulama kodu ve işlem bileti gereklidir."
        )
    if len(code) != 6 or not code.isdigit():
        raise HTTPException(
            status_code=400, detail="Doğrulama kodu 6 haneli bir sayı olmalıdır."
        )

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM security_verifications WHERE token = ? AND action = 'email_update' AND used = 0 ORDER BY id DESC LIMIT 1",
        (token,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Geçersiz, süresi dolmuş veya daha önce kullanılmış doğrulama talebi.",
        )

    record = dict(row)
    if record["user_id"] != current_user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Bu işlem size ait değil.")

    failed_attempts = int(record.get("failed_attempts") or 0)
    if failed_attempts >= 5:
        conn.execute(
            "UPDATE security_verifications SET used = 2 WHERE id = ?", (record["id"],)
        )
        conn.commit()
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Çok fazla hatalı kod girildi. Bu doğrulama işlemi iptal edildi. Lütfen yeni bir kod isteyin.",
        )

    # Süre kontrolü
    try:
        exp_str = record["expires_at"]
        exp_time = (
            datetime.fromisoformat(exp_str)
            if isinstance(exp_str, str)
            else exp_str
        )
        now = (
            datetime.now(exp_time.tzinfo)
            if getattr(exp_time, "tzinfo", None)
            else datetime.now(timezone.utc)
        )
        if now > exp_time:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail="Doğrulama kodunun süresi dolmuş. Lütfen yeni bir kod isteyin.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(f"Süre ayrıştırma: {exc}")

    # Sabit zamanlı kod kontrolü
    stored_code = str(record["code"]).strip()
    if not secrets.compare_digest(stored_code, code):
        new_failed = failed_attempts + 1
        used_status = 2 if new_failed >= 5 else 0
        conn.execute(
            "UPDATE security_verifications SET failed_attempts = ?, used = ? WHERE id = ?",
            (new_failed, used_status, record["id"]),
        )
        conn.commit()
        conn.close()
        remaining = max(0, 5 - new_failed)
        if remaining == 0:
            raise HTTPException(
                status_code=400,
                detail="Çok fazla hatalı kod girildi. Güvenlik nedeniyle işlem iptal edildi.",
            )
        raise HTTPException(
            status_code=400,
            detail=f"Girdiğiniz doğrulama kodu hatalı. Kalan deneme hakkı: {remaining}",
        )

    new_email = record["payload"]
    conn.execute(
        "UPDATE users SET email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_email, current_user["id"]),
    )
    conn.execute(
        "UPDATE athlete_profiles SET email = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
        (new_email, current_user["id"]),
    )
    conn.execute(
        "UPDATE security_verifications SET used = 1 WHERE id = ?", (record["id"],)
    )
    conn.commit()
    conn.close()

    return {
        "success": True,
        "email": new_email,
        "message": "E-posta adresiniz başarıyla güncellendi!",
    }


@router.post("/delete-account")
@router.delete("/me")
def delete_my_account(
    data: DeleteAccountRequest = Body(...),
    current_user: dict = Depends(_resolve_current_user),
):
    """Kullanıcının kendi hesabını ve tüm ilişkili verilerini parola doğrulamasıyla kalıcı olarak siler."""
    password = str(data.password or "").strip()
    if not password:
        raise HTTPException(
            status_code=400,
            detail="Hesabınızı silmek için mevcut şifrenizi girmelisiniz.",
        )

    confirmation = str(data.confirmation or "").strip()
    if confirmation != "HESABIMI KALICI OLARAK SİL":
        raise HTTPException(
            status_code=400,
            detail="Onay metni eşleşmiyor. Lütfen 'HESABIMI KALICI OLARAK SİL' yazın.",
        )

    user_id = current_user["id"]
    conn = get_db()
    try:
        user_row = conn.execute(
            "SELECT password_hash, password_salt, is_admin, username FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")

        # Admin hesabı silme koruması
        if (
            user_row["is_admin"]
            or current_user.get("is_admin")
            or str(user_row["username"] or "").lower() == ADMIN_USERNAME.lower()
            or str(current_user.get("username") or "").lower() == ADMIN_USERNAME.lower()
        ):
            raise HTTPException(
                status_code=403,
                detail="Sistem yöneticisi (admin) hesabı silinemez.",
            )

        # Mevcut şifreyi doğrula
        if not _verify_password(password, user_row["password_hash"], user_row["password_salt"]):
            raise HTTPException(
                status_code=401,
                detail="Mevcut şifrenizi hatalı girdiniz. Hesap silinemedi.",
            )

        # Uzman sistemi ve ilişkili tabloları kontrol et
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

        if "expert_doms_reports" in existing_tables and "expert_doms_cases" in existing_tables:
            conn.execute(
                "DELETE FROM expert_doms_reports WHERE doms_case_id IN "
                "(SELECT id FROM expert_doms_cases WHERE user_id = ?)",
                (user_id,),
            )

        expert_tables = (
            "expert_preferences",
            "expert_checkins",
            "expert_equipment",
            "expert_constraints",
            "expert_program_versions",
            "expert_doms_cases",
        )
        for tbl in expert_tables:
            if tbl in existing_tables:
                conn.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (user_id,))

        cascade_tables = (
            "password_resets",
            "security_verifications",
            "athlete_profiles",
            "expert_profiles",
            "workouts",
            "admin_roles",
        )
        for tbl in cascade_tables:
            if tbl in existing_tables:
                conn.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (user_id,))

        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        logger.exception(f"Hesap silinirken beklenmeyen hata: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Hesap silinirken bir sunucu hatası oluştu.",
        )
    finally:
        conn.close()

    return {"success": True, "message": "Hesabınız ve tüm verileriniz başarıyla silindi."}



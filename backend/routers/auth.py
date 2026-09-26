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
from core.email import mask_email, send_password_reset_email, send_security_code_email
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
    ChangePasswordConfirmRequest,
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


@router.post("/change-password/request")
def request_change_password(
    data: ChangePasswordRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    """1. Adım: Şifre değişikliği için kayıtlı e-postaya 6 haneli OTP kodu gönderir."""
    old_password = str(data.old_password or "").strip()
    new_password = str(data.new_password or "").strip()

    if user.get("username", "").casefold() == ADMIN_USERNAME.casefold() or user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin şifresi değiştirilemez")

    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Yeni şifre en az 6 karakter olmalı")

    conn = get_db()
    row = conn.execute(
        "SELECT password_hash, password_salt, email FROM users WHERE id = ?",
        (user["id"],),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    if not _verify_password(old_password, row["password_hash"], row["password_salt"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Mevcut şifre hatalı")

    user_email = str(row["email"] or user.get("email") or "").strip()
    if not user_email or "@" not in user_email:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Hesap güvenliğiniz için şifre değiştirmeden önce profilinizde geçerli bir e-posta adresi tanımlayıp doğrulamanız gerekmektedir.",
        )

    temp_hash = _hash_password(new_password)
    code = f"{secrets.randbelow(1000000):06d}"
    token = secrets.token_hex(20)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()

    conn.execute(
        "INSERT INTO security_verifications (user_id, action, payload, code, token, expires_at, used, failed_attempts) "
        "VALUES (?, 'password_change', ?, ?, ?, ?, 0, 0)",
        (user["id"], temp_hash, code, token, expires_at),
    )
    conn.commit()
    conn.close()

    sent = send_security_code_email(
        user_email, user["username"], code, action_type="password_change"
    )
    if not sent:
        logger.warning(f"Şifre değişikliği OTP e-posta uyarısı: {user_email}")

    return {
        "success": True,
        "token": token,
        "masked_email": mask_email(user_email),
        "message": f"Hesap güvenliğiniz için {mask_email(user_email)} adresine 6 haneli onay kodu gönderildi.",
    }


@router.post("/change-password/confirm")
def confirm_change_password(
    data: ChangePasswordConfirmRequest = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    """2. Adım: E-postaya gönderilen 6 haneli OTP kodu ile yeni şifreyi onaylar ve günceller."""
    token = str(data.token or "").strip()
    code = str(data.code or "").strip()

    if not token or not code:
        raise HTTPException(status_code=400, detail="Onay kodu ve işlem bileti gereklidir.")
    if len(code) != 6 or not code.isdigit():
        raise HTTPException(status_code=400, detail="Onay kodu 6 haneli bir sayı olmalıdır.")

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM security_verifications WHERE token = ? AND action = 'password_change' AND used = 0 ORDER BY id DESC LIMIT 1",
        (token,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Geçersiz, süresi dolmuş veya daha önce kullanılmış onay talebi.",
        )

    record = dict(row)
    if record["user_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Bu işlem size ait değil.")

    failed_attempts = int(record.get("failed_attempts") or 0)
    if failed_attempts >= 5:
        conn.execute("UPDATE security_verifications SET used = 2 WHERE id = ?", (record["id"],))
        conn.commit()
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Çok fazla hatalı kod girildi. Bu şifre değişikliği talebi iptal edildi.",
        )

    try:
        exp_str = record["expires_at"]
        exp_time = datetime.fromisoformat(exp_str) if isinstance(exp_str, str) else exp_str
        now = datetime.now(exp_time.tzinfo) if getattr(exp_time, "tzinfo", None) else datetime.now(timezone.utc)
        if now > exp_time:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail="Onay kodunun süresi dolmuş. Lütfen yeni bir şifre değişikliği talebi oluşturun.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(f"Süre ayrıştırma: {exc}")

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
            detail=f"Girdiğiniz onay kodu hatalı. Kalan deneme hakkı: {remaining}",
        )

    new_hash = record["payload"]
    conn.execute(
        "UPDATE users SET password_hash = ?, password_salt = '', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_hash, user["id"]),
    )
    conn.execute("UPDATE security_verifications SET used = 1 WHERE id = ?", (record["id"],))
    conn.commit()
    conn.close()

    return {"success": True, "message": "Şifreniz başarıyla güncellendi!"}


@router.post("/change-password")
def change_password(
    user: dict = Depends(_resolve_current_user),
    data: dict = Body(...),
):
    """Geriye dönük uyumluluk: Doğrudan veya OTP başlatma köprüsü."""
    if user.get("username", "").casefold() == ADMIN_USERNAME.casefold() or user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin şifresi değiştirilemez")

    # Eğer token ve code verilmişse confirm akışını çalıştır
    if "token" in data and "code" in data:
        return confirm_change_password(ChangePasswordConfirmRequest(token=data["token"], code=data["code"]), user)

    # Aksi takdirde request başlatıp token döndür (e-posta doğrulaması şart)
    req = ChangePasswordRequest(
        old_password=data.get("old_password", ""),
        new_password=data.get("new_password", "")
    )
    return request_change_password(req, user)


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest = Body(...)):
    """1. Adım: Kullanıcı adı veya e-posta ile 6 haneli doğrulama kodu üretir ve e-posta gönderir."""
    target = str(data.email_or_username or "").strip()
    if not target:
        raise HTTPException(
            status_code=400, detail="Lütfen kullanıcı adı veya e-posta adresinizi girin."
        )

    # ── GÜVENLİK 1: Admin hesabı şifre sıfırlamadan tamamen muaftır (.env üzerinden yönetilir) ──
    if target.casefold() == ADMIN_USERNAME.casefold():
        dummy_token = secrets.token_hex(20)
        return {
            "success": True,
            "reset_token": dummy_token,
            "masked_email": "a***@***.***",
            "expires_in_minutes": 15,
            "message": "Eğer bu hesap sistemde kayıtlıysa, 6 haneli doğrulama kodu gönderildi.",
        }

    user = get_user_by_email_or_username(target)

    # ── GÜVENLİK 2: User Enumeration Koruması ──
    # Kullanıcı sistemde yoksa veya admin ise saldırgana bilgi sızdırmamak adına jenerik yanıt dönülür
    if not user or user.get("username", "").casefold() == ADMIN_USERNAME.casefold() or user.get("is_admin"):
        dummy_token = secrets.token_hex(20)
        masked_dummy = mask_email(target) if "@" in target else "k***@***.***"
        return {
            "success": True,
            "reset_token": dummy_token,
            "masked_email": masked_dummy,
            "expires_in_minutes": 15,
            "message": "Eğer bu hesap sistemde kayıtlıysa, 6 haneli doğrulama kodu gönderildi.",
        }

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
        dummy_token = secrets.token_hex(20)
        return {
            "success": True,
            "reset_token": dummy_token,
            "masked_email": "k***@***.***",
            "expires_in_minutes": 15,
            "message": "Eğer bu hesap sistemde kayıtlıysa, 6 haneli doğrulama kodu gönderildi.",
        }

    # ── GÜVENLİK 3: 6 Haneli Kriptografik OTP (1.000.000 kombinasyon) ──
    code = f"{secrets.randbelow(1000000):06d}"
    reset_token = secrets.token_hex(20)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()

    conn = get_db()
    conn.execute(
        "INSERT INTO password_resets (user_id, email, code, reset_token, expires_at, used, failed_attempts) VALUES (?, ?, ?, ?, ?, 0, 0)",
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
        "message": f"{mask_email(user_email)} adresine 6 haneli doğrulama kodu gönderildi.",
    }


@router.post("/verify-reset-code")
def verify_reset_code(data: VerifyResetCodeRequest = Body(...)):
    """2. Adım: 6 haneli doğrulama kodunu kontrol eder; doğruysa şifre sıfırlama biletini onaylar."""
    token = str(data.reset_token or "").strip()
    code = str(data.code or "").strip()

    if not token or not code:
        raise HTTPException(
            status_code=400, detail="Doğrulama kodu ve sıfırlama bileti gereklidir."
        )
    if len(code) != 6 or not code.isdigit():
        raise HTTPException(
            status_code=400, detail="Doğrulama kodu 6 haneli bir sayı olmalıdır."
        )

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM password_resets WHERE reset_token = ? AND used = 0 ORDER BY id DESC LIMIT 1",
        (token,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(
            status_code=400, detail="Geçersiz, kilitlenmiş veya süresi dolmuş sıfırlama talebi."
        )

    record = dict(row)

    # ── GÜVENLİK 4: Maksimum 5 Hatalı Deneme (Brute-Force Lockout) ──
    failed_attempts = int(record.get("failed_attempts") or 0)
    if failed_attempts >= 5:
        conn.execute("UPDATE password_resets SET used = 2 WHERE id = ?", (record["id"],))
        conn.commit()
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Çok fazla hatalı kod girildi. Bu sıfırlama talebi güvenlik nedeniyle iptal edildi. Lütfen yeni bir kod isteyin.",
        )

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

    # ── GÜVENLİK 5: Sabit Zamanlı Karşılaştırma (Timing Attack Koruması) ──
    stored_code = str(record["code"]).strip()
    if not secrets.compare_digest(stored_code, code):
        new_failed = failed_attempts + 1
        used_status = 2 if new_failed >= 5 else 0
        conn.execute(
            "UPDATE password_resets SET failed_attempts = ?, used = ? WHERE id = ?",
            (new_failed, used_status, record["id"]),
        )
        conn.commit()
        conn.close()
        remaining = max(0, 5 - new_failed)
        if remaining == 0:
            raise HTTPException(
                status_code=400,
                detail="Çok fazla hatalı kod girildi. Bu sıfırlama talebi iptal edildi. Lütfen yeni bir kod isteyin.",
            )
        raise HTTPException(
            status_code=400,
            detail=f"Girdiğiniz 6 haneli doğrulama kodu hatalı. Kalan deneme hakkı: {remaining}",
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

    # ── GÜVENLİK 6: Admin Kullanıcısı Şifre Sıfırlamadan Kesinlikle Muaf ──
    user_check = conn.execute(
        "SELECT username, is_admin, role FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if user_check:
        u_dict = dict(user_check)
        if (
            u_dict.get("username", "").casefold() == ADMIN_USERNAME.casefold()
            or u_dict.get("is_admin")
            or u_dict.get("role") == "admin"
        ):
            conn.close()
            raise HTTPException(
                status_code=403,
                detail="Yönetici (admin) parolasını bu uç noktadan sıfırlayamazsınız. Yönetici parolası yalnızca .env dosyası üzerinden yönetilir.",
            )

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

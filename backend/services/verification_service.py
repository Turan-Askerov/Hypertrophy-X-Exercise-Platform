"""E-posta ve güvenlik doğrulama (OTP) servis katmanı.

Bu modül; yeni kayıt doğrulamaları, şifre sıfırlama, şifre değişikliği ve
e-posta adresi güncelleme gibi tüm güvenlik işlemlerinin OTP kod üretimini,
süre kontrolünü, brute-force korumasını (5 hatalı deneme) ve zamanlama
saldırılarına karşı güvenli (constant-time) doğrulamalarını tek bir merkezden yönetir.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException

from core.database import PostgreSQLIntegrityError, get_db
from core.email import mask_email, send_security_code_email
from core.security import _hash_password

logger = logging.getLogger("hypertrophy-x")

OTP_EXPIRY_MINUTES = 15
MAX_FAILED_ATTEMPTS = 5


def generate_otp_code() -> str:
    """Kriptografik olarak güvenli 6 haneli OTP kodu üretir."""
    return f"{secrets.randbelow(1000000):06d}"


def generate_secure_token(length_bytes: int = 20) -> str:
    """İşlem için güvenli hex bilet üretir."""
    return secrets.token_hex(length_bytes)


def calculate_expiry(minutes: int = OTP_EXPIRY_MINUTES) -> str:
    """UTC zamanında geçerlilik sonlanma zamanı üretir."""
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def is_expired(expires_at: Any) -> bool:
    """Tarih alanının süresinin dolup dolmadığını kontrol eder."""
    try:
        exp_time = (
            datetime.fromisoformat(expires_at)
            if isinstance(expires_at, str)
            else expires_at
        )
        now = (
            datetime.now(exp_time.tzinfo)
            if getattr(exp_time, "tzinfo", None)
            else datetime.now(timezone.utc)
        )
        return now > exp_time
    except Exception as exc:
        logger.warning(f"Zaman ayrıştırma hatası: {exc}")
        return False


# ─── 1. KULLANICI KAYDI DOĞRULAMA (PENDING REGISTRATION) ───

def start_registration(username: str, email: str, password: str) -> Dict[str, Any]:
    """
    Yeni kullanıcı kaydı başlatır, e-posta benzersizliğini doğrular ve 6 haneli OTP gönderir.
    Kullanıcı hesabı henüz oluşturulmaz, doğrulama tamamlanana kadar pending_registrations tablosunda bekletilir.
    """
    clean_user = str(username or "").strip()
    clean_email = str(email or "").strip().lower()

    if len(clean_user) < 2:
        raise HTTPException(status_code=400, detail="Kullanıcı adı en az 2 karakter olmalıdır.")
    if not clean_email or "@" not in clean_email or "." not in clean_email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Geçerli bir e-posta adresi girilmesi zorunludur.")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Şifre en az 6 karakter olmalıdır.")

    conn = get_db()
    # 1. Kullanıcı adı veya e-posta zaten kullanımda mı?
    existing = conn.execute(
        """
        SELECT u.id FROM users u
        LEFT JOIN athlete_profiles ap ON u.id = ap.user_id
        WHERE LOWER(u.username) = LOWER(?)
           OR (u.email IS NOT NULL AND u.email != '' AND LOWER(u.email) = ?)
           OR (ap.email IS NOT NULL AND ap.email != '' AND LOWER(ap.email) = ?)
        LIMIT 1
        """,
        (clean_user, clean_email, clean_email),
    ).fetchone()

    if existing:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="Bu kullanıcı adı veya e-posta adresi zaten kullanılmaktadır.",
        )

    # 2. Şifreyi hash'le ve OTP hazırla
    pwd_hash = _hash_password(password)
    code = generate_otp_code()
    token = generate_secure_token()
    expires_at = calculate_expiry()

    # Önceki tamamlanmamış bekleyen kayıtları geçersiz kıl (aynı e-posta veya kullanıcı adı için)
    conn.execute(
        "UPDATE pending_registrations SET used = 2 WHERE (LOWER(username) = LOWER(?) OR LOWER(email) = ?) AND used = 0",
        (clean_user, clean_email),
    )

    conn.execute(
        """
        INSERT INTO pending_registrations (username, email, password_hash, code, token, expires_at, used, failed_attempts)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0)
        """,
        (clean_user, clean_email, pwd_hash, code, token, expires_at),
    )
    conn.commit()
    conn.close()

    # E-posta gönderimi (arka planda / SMTP)
    send_security_code_email(clean_email, clean_user, code, action_type="registration")

    res_data = {
        "success": True,
        "token": token,
        "masked_email": mask_email(clean_email),
        "message": f"{mask_email(clean_email)} adresine 6 haneli onay kodu gönderildi. Lütfen kodunuzu girerek kaydı tamamlayın.",
    }
    from core.config import APP_ENV
    if APP_ENV == "test":
        res_data["test_code"] = code

    return res_data


def confirm_registration(token: str, code: str) -> Dict[str, Any]:
    """
    Gönderilen 6 haneli OTP kodunu doğrular, başarılı ise users ve athlete_profiles tablolarına hesabı kaydeder.
    """
    clean_token = str(token or "").strip()
    clean_code = str(code or "").strip()

    if not clean_token or not clean_code:
        raise HTTPException(status_code=400, detail="Doğrulama kodu ve işlem bileti gereklidir.")
    if len(clean_code) != 6 or not clean_code.isdigit():
        raise HTTPException(status_code=400, detail="Doğrulama kodu 6 haneli bir sayı olmalıdır.")

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM pending_registrations WHERE token = ? AND used = 0 ORDER BY id DESC LIMIT 1",
        (clean_token,),
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Geçersiz, süresi dolmuş veya daha önce tamamlanmış kayıt talebi.",
        )

    record = dict(row)
    failed_attempts = int(record.get("failed_attempts") or 0)

    # Brute-force deneme sınırı kontrolü
    if failed_attempts >= MAX_FAILED_ATTEMPTS:
        conn.execute("UPDATE pending_registrations SET used = 2 WHERE id = ?", (record["id"],))
        conn.commit()
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Çok fazla hatalı kod girildi. Bu kayıt talebi iptal edildi, lütfen yeniden kayıt olun.",
        )

    # Süre aşımı kontrolü
    if is_expired(record["expires_at"]):
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Doğrulama kodunun süresi dolmuş (15 dakika). Lütfen yeniden kayıt oluşturun.",
        )

    # Constant-time kod karşılaştırma
    stored_code = str(record["code"]).strip()
    if not secrets.compare_digest(stored_code, clean_code):
        new_failed = failed_attempts + 1
        used_status = 2 if new_failed >= MAX_FAILED_ATTEMPTS else 0
        conn.execute(
            "UPDATE pending_registrations SET failed_attempts = ?, used = ? WHERE id = ?",
            (new_failed, used_status, record["id"]),
        )
        conn.commit()
        conn.close()
        remaining = max(0, MAX_FAILED_ATTEMPTS - new_failed)
        if remaining == 0:
            raise HTTPException(
                status_code=400,
                detail="Çok fazla hatalı kod girildi. Güvenlik nedeniyle işlem iptal edildi.",
            )
        raise HTTPException(
            status_code=400,
            detail=f"Girdiğiniz doğrulama kodu hatalı. Kalan deneme hakkı: {remaining}",
        )

    # Kod doğru -> Kullanıcıyı oluştur
    username = record["username"]
    email = record["email"]
    password_hash = record["password_hash"]

    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password_hash, password_salt, role, is_active, email) VALUES (?, ?, '', 'athlete', 1, ?)",
            (username, password_hash, email),
        )
        new_id = getattr(cur, "lastrowid", None)
        if not new_id:
            u_row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if u_row:
                new_id = u_row["id"] if isinstance(u_row, dict) else u_row[0]
        if new_id:
            cur.execute(
                "INSERT OR IGNORE INTO athlete_profiles (user_id, age, gender, height, weight, fitness_level, goal, days_per_week, session_time_mins, email) VALUES (?, 0, 'male', 170.0, 70.0, 'Beginner', 'bulk', 4, 60, ?)",
                (new_id, email),
            )
        # Kaydı kullanıldı olarak işaretle
        cur.execute("UPDATE pending_registrations SET used = 1 WHERE id = ?", (record["id"],))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "message": "Hesabınız başarıyla doğrulandı ve oluşturuldu!",
            "username": username,
            "email": email,
        }
    except Exception as exc:
        conn.close()
        logger.error(f"Kullanıcı oluşturulurken hata: {exc}")
        raise HTTPException(
            status_code=409,
            detail="Kayıt oluşturulurken bir çakışma yaşandı. Lütfen tekrar deneyin.",
        )


# ─── 2. GENEL GÜVENLİK İŞLEMİ DOĞRULAMA (SECURITY_VERIFICATIONS) ───

def create_security_verification(
    user_id: int,
    username: str,
    target_email: str,
    action: str,
    payload: str,
) -> Dict[str, Any]:
    """
    Şifre değişikliği veya e-posta güncelleme gibi mevcut kullanıcı işlemleri için OTP başlatır.
    """
    code = generate_otp_code()
    token = generate_secure_token()
    expires_at = calculate_expiry()

    conn = get_db()
    # Önceki aynı işlem tipindeki aktif biletleri geçersiz kıl
    conn.execute(
        "UPDATE security_verifications SET used = 2 WHERE user_id = ? AND action = ? AND used = 0",
        (user_id, action),
    )
    conn.execute(
        """
        INSERT INTO security_verifications (user_id, action, payload, code, token, expires_at, used, failed_attempts)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0)
        """,
        (user_id, action, payload, code, token, expires_at),
    )
    conn.commit()
    conn.close()

    send_security_code_email(target_email, username, code, action_type=action)

    return {
        "success": True,
        "token": token,
        "masked_email": mask_email(target_email),
        "message": f"{mask_email(target_email)} adresine 6 haneli doğrulama kodu gönderildi.",
    }


def verify_security_code(
    token: str,
    code: str,
    action: str,
    user_id: Optional[int] = None,
) -> Tuple[Dict[str, Any], Any]:
    """
    security_verifications tablosundaki bilet ve kodu güvenle doğrular.
    Başarılı olursa (record, db_connection) döndürür; çağıran yer işlemi bitirip used=1 yapıp commit eder.
    """
    clean_token = str(token or "").strip()
    clean_code = str(code or "").strip()

    if not clean_token or not clean_code:
        raise HTTPException(status_code=400, detail="Doğrulama kodu ve işlem bileti gereklidir.")
    if len(clean_code) != 6 or not clean_code.isdigit():
        raise HTTPException(status_code=400, detail="Doğrulama kodu 6 haneli bir sayı olmalıdır.")

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM security_verifications WHERE token = ? AND action = ? AND used = 0 ORDER BY id DESC LIMIT 1",
        (clean_token, action),
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Geçersiz, süresi dolmuş veya daha önce kullanılmış doğrulama talebi.",
        )

    record = dict(row)
    if user_id is not None and record["user_id"] != user_id:
        conn.close()
        raise HTTPException(status_code=403, detail="Bu işlem size ait değil.")

    failed_attempts = int(record.get("failed_attempts") or 0)
    if failed_attempts >= MAX_FAILED_ATTEMPTS:
        conn.execute("UPDATE security_verifications SET used = 2 WHERE id = ?", (record["id"],))
        conn.commit()
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Çok fazla hatalı kod girildi. Bu güvenlik işlemi iptal edildi.",
        )

    if is_expired(record["expires_at"]):
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="Doğrulama kodunun süresi dolmuş. Lütfen yeni bir talep oluşturun.",
        )

    stored_code = str(record["code"]).strip()
    if not secrets.compare_digest(stored_code, clean_code):
        new_failed = failed_attempts + 1
        used_status = 2 if new_failed >= MAX_FAILED_ATTEMPTS else 0
        conn.execute(
            "UPDATE security_verifications SET failed_attempts = ?, used = ? WHERE id = ?",
            (new_failed, used_status, record["id"]),
        )
        conn.commit()
        conn.close()
        remaining = max(0, MAX_FAILED_ATTEMPTS - new_failed)
        if remaining == 0:
            raise HTTPException(
                status_code=400,
                detail="Çok fazla hatalı kod girildi. Güvenlik nedeniyle işlem iptal edildi.",
            )
        raise HTTPException(
            status_code=400,
            detail=f"Girdiğiniz onay kodu hatalı. Kalan deneme hakkı: {remaining}",
        )

    return record, conn

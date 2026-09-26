"""Şifre sıfırlama ve e-posta bildirim yardımcıları."""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from core.config import SMTP_FROM, SMTP_HOST, SMTP_PASS, SMTP_PORT, SMTP_USER

logger = logging.getLogger("hypertrophy-x")


def mask_email(email: str) -> str:
    """E-posta adresini gizleyerek döndürür (örn: t***v@gmail.com)."""
    if not email or "@" not in email:
        return email or ""
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked_name = name[0] + "*"
    else:
        masked_name = name[0] + "*" * (len(name) - 2) + name[-1]
    return f"{masked_name}@{domain}"


def send_security_code_email(
    to_email: str, username: str, code: str, action_type: str = "password_reset"
) -> bool:
    """6 haneli tek kullanımlık güvenlik kodunu (OTP) e-posta ile gönderir."""
    action_configs = {
        "email_update": {
            "subject": f"Hypertrophy-X E-posta Değişikliği Doğrulama Kodu: {code}",
            "header": "E-POSTA DEĞİŞİKLİĞİ DOĞRULAMA",
            "message": "Hesabınızın e-posta adresini güncellemek için bir talepte bulundunuz. Aşağıdaki 6 haneli tek kullanımlık güvenlik kodunu kullanarak işlemi tamamlayabilirsiniz:",
        },
        "password_change": {
            "subject": f"Hypertrophy-X Şifre Değişikliği Onay Kodu: {code}",
            "header": "ŞİFRE DEĞİŞİKLİĞİ ONAYI",
            "message": "Hesabınızın şifresini değiştirmek için bir talepte bulundunuz. Güvenliğiniz için bu işlemi onaylamak üzere aşağıdaki 6 haneli güvenlik kodunu girin:",
        },
        "password_reset": {
            "subject": f"Hypertrophy-X Şifre Sıfırlama Kodu: {code}",
            "header": "ŞİFRE SIFIRLAMA",
            "message": "Hesabınız için şifre sıfırlama talebinde bulundunuz. Aşağıdaki 6 haneli tek kullanımlık doğrulama kodunu kullanarak yeni şifrenizi belirleyebilirsiniz:",
        },
    }

    cfg = action_configs.get(action_type, action_configs["password_reset"])
    subject = cfg["subject"]
    header_text = cfg["header"]
    body_message = cfg["message"]

    html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px;background:#0b0f19;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#f1f5f9;">
  <div style="max-width:480px;margin:0 auto;background:#141b2d;border-radius:16px;padding:32px 24px;border:1px solid rgba(99,102,241,0.25);box-shadow:0 12px 40px rgba(0,0,0,0.5);">
    <div style="text-align:center;margin-bottom:24px;">
      <div style="display:inline-block;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;font-weight:900;font-size:18px;padding:8px 14px;border-radius:10px;margin-bottom:12px;">HX</div>
      <h2 style="margin:0;font-size:20px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;">Hypertrophy-X</h2>
      <div style="font-size:12px;color:#38bdf8;font-weight:600;margin-top:2px;">{header_text}</div>
    </div>
    <p style="font-size:14px;line-height:1.6;color:#cbd5e1;margin:0 0 16px;">
      Merhaba <strong>{username}</strong>,<br>
      {body_message}
    </p>
    <div style="background:rgba(99,102,241,0.12);border:2px dashed rgba(99,102,241,0.5);border-radius:12px;text-align:center;padding:18px;margin:24px 0;">
      <div style="font-size:11px;font-weight:700;letter-spacing:1px;color:#94a3b8;margin-bottom:6px;text-transform:uppercase;">Güvenlik Kodunuz</div>
      <div style="font-size:36px;font-weight:900;letter-spacing:10px;color:#38bdf8;font-family:monospace;">{code}</div>
      <div style="font-size:11.5px;color:#94a3b8;margin-top:6px;">⏱️ Bu kod <strong>15 dakika</strong> boyunca geçerlidir.</div>
    </div>
    <p style="font-size:12px;line-height:1.5;color:#94a3b8;margin:0 0 20px;">
      Eğer bu işlemi siz başlatmadıysanız lütfen bu e-postayı dikkate almayınız. Bilgileriniz siz bu kodu girmedikçe değişmeyecektir.
    </p>
    <div style="border-top:1px solid rgba(148,163,184,0.15);padding-top:16px;text-align:center;font-size:11px;color:#64748b;">
      Hypertrophy-X Akıllı Egzersiz Platformu
    </div>
  </div>
</body>
</html>"""
    plain_content = (
        f"Merhaba {username},\n\n{body_message}\n\nDoğrulama kodunuz: {code}\n"
        "Bu kod 15 dakika boyunca geçerlidir.\n\nHypertrophy-X Ekibi"
    )

    logger.info(
        f"🔑 [GÜVENLİK KODU - {action_type.upper()}] Kullanıcı: {username} | E-posta: {to_email} | KOD: {code}"
    )

    if not SMTP_USER or not SMTP_PASS:
        logger.info(
            "SMTP_USER veya SMTP_PASS tanımlı olmadığı için e-posta gönderimi simüle edildi (Kod konsola yazıldı)."
        )
        return True

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(plain_content, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, [to_email], msg.as_string())
        logger.info(f"Güvenlik onay e-postası başarıyla gönderildi: {to_email}")
        return True
    except Exception as exc:
        logger.error(f"E-posta gönderiminde hata: {exc}")
        return False


def send_password_reset_email(to_email: str, username: str, code: str) -> bool:
    """Geriye dönük uyumluluk: Şifre sıfırlama e-postası gönderir."""
    return send_security_code_email(to_email, username, code, action_type="password_reset")

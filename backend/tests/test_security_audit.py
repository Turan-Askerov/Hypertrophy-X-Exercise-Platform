"""Güvenlik denetimi ve saldırı simülasyonu testleri (Security Hardening & Adversarial Test Suite)."""
import os
import sqlite3
import pytest
from core.database import get_db


def test_user_enumeration_prevention(client):
    """Sistemde kayıtlı olmayan bir kullanıcı için bilgi sızdırmadan jenerik yanıt dönüldüğünü doğrular."""
    res = client.post("/api/auth/forgot-password", json={
        "email_or_username": "nonexistent_hacker_target_12345"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "reset_token" in data
    assert "Eğer bu hesap sistemde kayıtlıysa" in data["message"]


def test_admin_cannot_be_reset_via_api(client):
    """Admin hesabı için parola sıfırlama talebi gönderildiğinde admin parolasının korunduğunu doğrular."""
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    res = client.post("/api/auth/forgot-password", json={
        "email_or_username": admin_username
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    dummy_token = data["reset_token"]

    # Veritabanında admin için gerçek bir sıfırlama kaydı açılmadığını doğrula
    conn = get_db()
    row = conn.execute("SELECT * FROM password_resets WHERE reset_token = ?", (dummy_token,)).fetchone()
    conn.close()
    assert row is None, "Admin için veritabanında sıfırlama bileti oluşturulmamalıdır!"


def test_password_reset_brute_force_lockout(client):
    """5 hatalı 6 haneli kod denemesi yapıldığında biletin kilitlendiğini ve saldırının engellendiğini doğrular."""
    username = "victim_athlete"
    email = "victim@example.com"
    client.post("/api/auth/register", json={
        "username": username,
        "password": "InitialVictimPassword123!",
        "email": email
    })

    # Sıfırlama talebi başlat
    res = client.post("/api/auth/forgot-password", json={
        "email_or_username": username
    })
    assert res.status_code == 200
    reset_token = res.json()["reset_token"]

    # Veritabanından gerçek 6 haneli kodu oku (saldırgan bunu bilmiyor)
    conn = get_db()
    db_row = conn.execute("SELECT code FROM password_resets WHERE reset_token = ?", (reset_token,)).fetchone()
    conn.close()
    real_code = db_row["code"]
    assert len(real_code) == 6

    # 4 kez ardışık yanlış kod dene
    for attempt in range(1, 5):
        wrong_code = f"99999{attempt}"
        if wrong_code == real_code:
            wrong_code = "000000"
        err_res = client.post("/api/auth/verify-reset-code", json={
            "reset_token": reset_token,
            "code": wrong_code
        })
        assert err_res.status_code == 400
        detail = err_res.json()["detail"]
        expected_remaining = 5 - attempt
        assert f"Kalan deneme hakkı: {expected_remaining}" in detail

    # 5. kez yanlış kod dene (Bilet kilitlenmeli)
    err_res_5 = client.post("/api/auth/verify-reset-code", json={
        "reset_token": reset_token,
        "code": "111111" if real_code != "111111" else "222222"
    })
    assert err_res_5.status_code == 400
    assert "Çok fazla hatalı kod girildi" in err_res_5.json()["detail"]

    # Şimdi doğru kodu denese bile bilet kilitlendiği için işlem reddedilmeli!
    correct_attempt_after_lock = client.post("/api/auth/verify-reset-code", json={
        "reset_token": reset_token,
        "code": real_code
    })
    assert correct_attempt_after_lock.status_code == 400
    assert "Geçersiz, kilitlenmiş veya süresi dolmuş" in correct_attempt_after_lock.json()["detail"]


def test_admin_change_password_forbidden(client, admin_headers):
    """Admin kullanıcısının web arayüzünden şifre değiştiremeyeceğini doğrular."""
    res = client.post("/api/auth/change-password", headers=admin_headers, json={
        "old_password": "testadminpass123",
        "new_password": "HackedAdminPass123!"
    })
    assert res.status_code == 403
    assert "Admin şifresi değiştirilemez" in res.json()["detail"]


def test_email_update_otp_flow(client):
    """E-posta güncelleme işleminin 6 haneli OTP kodu ile doğrulandığını ve brute-force korumasını test eder."""
    username = "email_otp_user"
    password = "EmailTestPassword123!"
    client.post("/api/auth/register", json={
        "username": username,
        "password": password,
        "email": "initial_user_email@example.com"
    })
    login_res = client.post("/api/auth/login", json={"username": username, "password": password})
    token_jwt = login_res.json().get("token")
    headers = {"Authorization": f"Bearer {token_jwt}", "Content-Type": "application/json"}

    new_email = "new_verified_email@example.com"

    # 1. Adım: Kod iste
    req_res = client.post("/api/user/email/request-update", headers=headers, json={
        "new_email": new_email
    })
    assert req_res.status_code == 200
    req_data = req_res.json()
    assert req_data["success"] is True
    token = req_data["token"]
    assert len(token) > 0

    # DB'den gerçek OTP kodunu al
    conn = get_db()
    row = conn.execute("SELECT * FROM security_verifications WHERE token = ?", (token,)).fetchone()
    conn.close()
    assert row is not None
    real_code = row["code"]
    assert len(real_code) == 6

    # 4 kez hatalı kod dene
    for attempt in range(1, 5):
        wrong_code = "000000" if real_code != "000000" else "111111"
        err_res = client.post("/api/user/email/confirm-update", headers=headers, json={
            "token": token,
            "code": wrong_code
        })
        assert err_res.status_code == 400
        assert f"Kalan deneme hakkı: {5 - attempt}" in err_res.json()["detail"]

    # 5. kez hatalı kod dene (Kilitlenmeli)
    err_res_5 = client.post("/api/user/email/confirm-update", headers=headers, json={
        "token": token,
        "code": "000000" if real_code != "000000" else "111111"
    })
    assert err_res_5.status_code == 400
    assert "Çok fazla hatalı kod girildi" in err_res_5.json()["detail"]

    # Kilitlendikten sonra doğru kod bile geçersiz olmalı
    late_res = client.post("/api/user/email/confirm-update", headers=headers, json={
        "token": token,
        "code": real_code
    })
    assert late_res.status_code == 400

    # Yeni bilet iste ve doğru kodla onayla
    req2_res = client.post("/api/user/email/request-update", headers=headers, json={
        "new_email": new_email
    })
    assert req2_res.status_code == 200
    token2 = req2_res.json()["token"]

    conn = get_db()
    code2 = conn.execute("SELECT code FROM security_verifications WHERE token = ?", (token2,)).fetchone()["code"]
    conn.close()

    confirm_res = client.post("/api/user/email/confirm-update", headers=headers, json={
        "token": token2,
        "code": code2
    })
    assert confirm_res.status_code == 200
    assert confirm_res.json()["success"] is True

    # Kullanıcı profilinde e-postanın güncellendiğini doğrula
    me_res = client.get("/api/user", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["email"] == new_email


def test_password_change_email_otp_flow(client):
    """Şifre değiştirmenin kayıtlı e-postaya gelen 6 haneli OTP kodu ile yapıldığını test eder."""
    username = "pwd_otp_user"
    old_password = "OldStrongPassword123!"
    client.post("/api/auth/register", json={
        "username": username,
        "password": old_password,
        "email": "pwd_test@example.com"
    })
    login_res = client.post("/api/auth/login", json={"username": username, "password": old_password})
    token_jwt = login_res.json().get("token")
    headers = {"Authorization": f"Bearer {token_jwt}", "Content-Type": "application/json"}

    # Yanlış eski şifre ile talep başlatılamamalı
    fail_req = client.post("/api/auth/change-password/request", headers=headers, json={
        "old_password": "WrongPassword123!",
        "new_password": "NewStrongPassword456!"
    })
    assert fail_req.status_code == 401
    assert "Mevcut şifre hatalı" in fail_req.json()["detail"]

    # Doğru eski şifre ile OTP başlat
    req_res = client.post("/api/auth/change-password/request", headers=headers, json={
        "old_password": old_password,
        "new_password": "NewStrongPassword456!"
    })
    assert req_res.status_code == 200
    req_data = req_res.json()
    assert req_data["success"] is True
    token = req_data["token"]

    # DB'den kodu al
    conn = get_db()
    row = conn.execute("SELECT code FROM security_verifications WHERE token = ?", (token,)).fetchone()
    conn.close()
    assert row is not None
    real_code = row["code"]

    # Hatalı kod denemesi
    wrong_res = client.post("/api/auth/change-password/confirm", headers=headers, json={
        "token": token,
        "code": "000000" if real_code != "000000" else "111111"
    })
    assert wrong_res.status_code == 400
    assert "Kalan deneme hakkı: 4" in wrong_res.json()["detail"]

    # Doğru kodla onayla
    confirm_res = client.post("/api/auth/change-password/confirm", headers=headers, json={
        "token": token,
        "code": real_code
    })
    assert confirm_res.status_code == 200
    assert confirm_res.json()["success"] is True

    # Yeni şifreyle login olunabildiğini, eski şifreyle olunamadığını doğrula
    old_login = client.post("/api/auth/login", json={
        "username": username,
        "password": old_password
    })
    assert old_login.status_code == 401

    new_login = client.post("/api/auth/login", json={
        "username": username,
        "password": "NewStrongPassword456!"
    })
    assert new_login.status_code == 200
    assert "token" in new_login.json()


def test_delete_account_security_flow(client, admin_headers):
    """Hesap silme işleminde parola doğrulaması, onay metni kontrolü ve admin korumasını test eder."""
    username = "victim_to_delete"
    password = "CorrectUserPass123!"
    client.post("/api/auth/register", json={
        "username": username,
        "password": password,
        "email": "delete_me@example.com"
    })
    login_res = client.post("/api/auth/login", json={"username": username, "password": password})
    token = login_res.json().get("token")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Hatalı şifre denemesi (401 dönmeli)
    wrong_pass_res = client.post("/api/user/delete-account", headers=headers, json={
        "password": "WrongPassword123!",
        "confirmation": "HESABIMI KALICI OLARAK SİL"
    })
    assert wrong_pass_res.status_code == 401
    assert "Mevcut şifrenizi hatalı girdiniz" in wrong_pass_res.json()["detail"]

    # 2. Hatalı onay metni denemesi (400 dönmeli)
    wrong_conf_res = client.post("/api/user/delete-account", headers=headers, json={
        "password": password,
        "confirmation": "HESABI SİL"
    })
    assert wrong_conf_res.status_code == 400
    assert "Onay metni eşleşmiyor" in wrong_conf_res.json()["detail"]

    # 3. Admin hesabını silme denemesi (403 dönmeli)
    admin_del_res = client.post("/api/user/delete-account", headers=admin_headers, json={
        "password": "testadminpass123",
        "confirmation": "HESABIMI KALICI OLARAK SİL"
    })
    assert admin_del_res.status_code == 403
    assert "Sistem yöneticisi (admin) hesabı silinemez" in admin_del_res.json()["detail"]

    # 4. Doğru şifre ve onay metni ile başarılı silme
    del_res = client.post("/api/user/delete-account", headers=headers, json={
        "password": password,
        "confirmation": "HESABIMI KALICI OLARAK SİL"
    })
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # 5. Silinen kullanıcının oturum açamayacağını doğrula
    login_again = client.post("/api/auth/login", json={"username": username, "password": password})
    assert login_again.status_code == 401

    # Veritabanında kullanıcının silindiğini doğrula
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    assert row is None




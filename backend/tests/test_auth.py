import pytest


def test_register_and_login(client):
    """Kullanıcı kaydı ve sonrasında başarılı giriş testi."""
    user_data = {
        "username": "newrunner",
        "password": "SecurePassword123!",
        "email": "newrunner@example.com"
    }
    
    # 1. Kayıt testi
    reg_res = client.post("/api/auth/register", json=user_data)
    assert reg_res.status_code == 200
    reg_json = reg_res.json()
    assert "username" in reg_json or reg_json.get("success") is True or "message" in reg_json

    # 2. Aynı kullanıcı adıyla tekrar kayıt engellenmeli
    dup_res = client.post("/api/auth/register", json=user_data)
    assert dup_res.status_code in [400, 409]

    # 3. Giriş testi
    login_res = client.post("/api/auth/login", json={
        "username": user_data["username"],
        "password": user_data["password"]
    })
    assert login_res.status_code == 200
    token_data = login_res.json()
    assert "token" in token_data
    assert token_data.get("username") == user_data["username"]


def test_login_invalid_password(client):
    """Hatalı şifre ile giriş reddedilmeli."""
    client.post("/api/auth/register", json={
        "username": "athlete_wrong_pass",
        "password": "CorrectPassword123!",
        "email": "wrong@example.com"
    })
    
    res = client.post("/api/auth/login", json={
        "username": "athlete_wrong_pass",
        "password": "WrongPassword123!"
    })
    assert res.status_code == 401


def test_user_profile_endpoints(client, auth_headers):
    """Giriş yapmış kullanıcının profilini okuma ve güncelleme testi."""
    # 1. Profil getirme
    get_res = client.get("/api/user", headers=auth_headers)
    assert get_res.status_code == 200
    user_info = get_res.json()
    assert "username" in user_info

    # 2. Profil güncelleme
    update_data = {
        "username": "testathlete",
        "age": 25,
        "height": 180.0,
        "weight": 75.5,
        "fitness_level": "Intermediate",
        "goal": "bulk",
        "days_per_week": 4,
        "session_time_mins": 60
    }
    put_res = client.post("/api/user", json=update_data, headers=auth_headers)
    assert put_res.status_code == 200

    # 3. Güncellenen profili tekrar okuyup doğrula
    get_res_after = client.get("/api/user", headers=auth_headers)
    assert get_res_after.status_code == 200
    updated_info = get_res_after.json()
    assert updated_info["weight"] == 75.5
    assert updated_info["fitness_level"] == "Intermediate"


def test_unauthorized_access(client):
    """Token olmadan korunan uçlara erişim engellenmeli."""
    res = client.get("/api/user")
    assert res.status_code == 401

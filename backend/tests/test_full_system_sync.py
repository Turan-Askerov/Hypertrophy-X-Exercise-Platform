from datetime import date

from core.database import get_db
from services.user_service import get_user_by_id


def _register_and_login(client, username: str, email: str, password: str = "StrongPass123!"):
    reg = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "email": email},
    )
    assert reg.status_code == 200, reg.text
    reg_data = reg.json()
    conf = client.post(
        "/api/auth/register/confirm",
        json={"token": reg_data["token"], "code": reg_data["test_code"]},
    )
    assert conf.status_code == 200, conf.text
    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    return {
        "id": body["id"],
        "username": username,
        "password": password,
        "token": body["token"],
        "headers": {"Authorization": f"Bearer {body['token']}"},
    }


def _seven_day_split():
    return [
        [
            {"day": d, "type": "Push" if i < 5 else "Rest", "focus": "Chest", "isRest": i >= 5}
            for i, d in enumerate(
                ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
            )
        ]
    ]


def test_mobile_flows_succeed_without_username_payloads(client):
    """Mobil istemcinin username göndermediği tüm akışlar user_id ile uçtan uca çalışır."""
    ctx = _register_and_login(client, "mobile_decoupled", "mobile_dec@example.com")
    headers = ctx["headers"]
    today_str = str(date.today())

    # 1. Profil, nickname, avatar ve hedef kilo güncellemesi (username olmadan)
    prof_res = client.post(
        "/api/user",
        json={
            "nickname": "Mobil Atlet",
            "avatar_url": "data:image/jpeg;base64,/9j/4AAQ==",
            "age": 25,
            "height": 182.0,
            "weight": 84.0,
            "target_weight": 79.5,
        },
        headers=headers,
    )
    assert prof_res.status_code == 200, prof_res.text
    p_data = prof_res.json()
    assert p_data["nickname"] == "Mobil Atlet"
    assert p_data["target_weight"] == 79.5

    # 2. Özel program kaydetme (username olmadan)
    prog_res = client.post(
        "/api/custom-program",
        json={"program": _seven_day_split()},
        headers=headers,
    )
    assert prog_res.status_code == 200, prog_res.text
    assert prog_res.json()["success"] is True

    # 3. Beslenme ekleme / güncelleme / okuma (username olmadan)
    nutri_add = client.post(
        "/api/nutrition/log",
        json={
            "log_date": today_str,
            "calories": 2500,
            "protein": 185,
            "carbs": 260,
            "fat": 75,
            "notes": "Temiz kütle",
        },
        headers=headers,
    )
    assert nutri_add.status_code == 200, nutri_add.text

    nutri_upd = client.put(
        "/api/nutrition/log",
        json={
            "original_date": today_str,
            "log_date": today_str,
            "calories": 2600,
            "protein": 190,
            "carbs": 270,
            "fat": 78,
            "notes": "Güncellendi",
        },
        headers=headers,
    )
    assert nutri_upd.status_code == 200, nutri_upd.text

    # 4. Antrenman, dashboard ve expert_data_state kontrolü
    w_res = client.post(
        "/api/workouts",
        json={
            "date": today_str,
            "session_type": "Push",
            "exercises": [
                {
                    "exercise_id": "bench-press",
                    "exercise_name": "Bench Press",
                    "muscle_group": "Chest",
                    "sets_data": [{"weight_kg": 90.0, "reps": 6, "rir": 2}],
                }
            ],
        },
        headers=headers,
    )
    assert w_res.status_code == 200, w_res.text

    dash = client.get("/api/dashboard", headers=headers)
    assert dash.status_code == 200, dash.text

    exp = client.get("/api/expert-data", headers=headers)
    assert exp.status_code == 200, exp.text
    assert exp.json()["user"]["id"] == ctx["id"]
    assert exp.json()["user"]["nickname"] == "Mobil Atlet"


def test_admin_create_user_supports_nickname_and_target_weight(client, admin_headers):
    """Admin üzerinden açılan sporcuda nickname ve target_weight iki tabloda da oluşur."""
    create_res = client.post(
        "/api/admin/user",
        json={
            "username": "created_athlete_x",
            "password": "StrongPass123!",
            "nickname": "Demir Koç",
            "age": 28,
            "height": 179,
            "weight": 82,
            "target_weight": 76.5,
        },
        headers=admin_headers,
    )
    assert create_res.status_code == 200, create_res.text

    login = client.post(
        "/api/auth/login",
        json={"username": "created_athlete_x", "password": "StrongPass123!"},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["nickname"] == "Demir Koç"
    assert body["target_weight"] == 76.5


def test_account_deletion_cascade_works_after_username_rename(client):
    """Kullanıcı adı DB'de değişse bile hesap silme tüm ilişkili kayıtları id ile temizler."""
    ctx = _register_and_login(client, "del_before", "del_cascade@example.com")
    uid = ctx["id"]
    headers = ctx["headers"]

    assert (
        client.post(
            "/api/workouts",
            json={
                "date": str(date.today()),
                "session_type": "Pull",
                "exercises": [
                    {
                        "exercise_id": "barbell-row",
                        "exercise_name": "Barbell Row",
                        "muscle_group": "Back",
                        "sets_data": [{"weight_kg": 70.0, "reps": 8, "rir": 2}],
                    }
                ],
            },
            headers=headers,
        ).status_code
        == 200
    )

    # DB'de username yeniden adlandırılır
    conn = get_db()
    conn.execute("UPDATE users SET username = ? WHERE id = ?", ("del_after", uid))
    conn.commit()
    conn.close()

    # Eski JWT ile hesap silme OTP'si başlatılır ve onaylanır
    req_del = client.post(
        "/api/user/delete-account/request",
        json={"password": ctx["password"]},
        headers=headers,
    )
    assert req_del.status_code == 200, req_del.text
    req_data = req_del.json()

    conf_del = client.post(
        "/api/user/delete-account",
        json={
            "password": ctx["password"],
            "token": req_data["token"],
            "code": req_data["test_code"],
        },
        headers=headers,
    )
    assert conf_del.status_code == 200, conf_del.text

    assert get_user_by_id(uid) is None
    conn = get_db()
    assert conn.execute("SELECT COUNT(*) FROM workouts WHERE user_id = ?", (uid,)).fetchone()[0] == 0
    assert (
        conn.execute("SELECT COUNT(*) FROM athlete_profiles WHERE user_id = ?", (uid,)).fetchone()[0]
        == 0
    )
    conn.close()

from datetime import date, datetime, timedelta, timezone

from jose import jwt

from core.config import ADMIN_USERNAME, ALGORITHM, SECRET_KEY
from core.database import get_db
from core.security import _USER_LAST_SEEN, _decode_token
from services.user_service import (
    get_user_by_id,
    get_user_by_username,
    update_user_profile,
)


def _register_confirm_and_login(
    client, username: str, password: str, email: str
) -> dict:
    """Yeni kullanıcı kaydeder, OTP ile onaylar ve giriş tokenını döner."""
    reg = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "email": email},
    )
    assert reg.status_code == 200, reg.text
    reg_data = reg.json()

    confirm = client.post(
        "/api/auth/register/confirm",
        json={"token": reg_data["token"], "code": reg_data["test_code"]},
    )
    assert confirm.status_code == 200, confirm.text

    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text

    user = get_user_by_username(username)
    assert user is not None
    return {
        "user": user,
        "user_id": user["id"],
        "confirm_token": confirm.json()["token"],
        "login_token": login.json()["token"],
        "headers": {"Authorization": f"Bearer {login.json()['token']}"},
    }


def _sample_week_program(focus_label: str = "Chest"):
    days = [
        ("Pazartesi", "Push", focus_label, False),
        ("Salı", "Pull", "Back", False),
        ("Çarşamba", "Legs", "Quads", False),
        ("Perşembe", "Rest", "Dinlenme", True),
        ("Cuma", "Upper", "Shoulders", False),
        ("Cumartesi", "Lower", "Hamstrings", False),
        ("Pazar", "Rest", "Dinlenme", True),
    ]
    return [
        [
            {"day": d, "type": t, "focus": f, "isRest": rest}
            for d, t, f, rest in days
        ]
    ]


def test_tokens_embed_immutable_uid_on_confirm_and_login(client):
    """Kayıt onayı ve girişte üretilen JWT'ler değişmez uid taşır."""
    ctx = _register_confirm_and_login(
        client, "uid_token_user", "StrongPass123!", "uid_token@example.com"
    )
    expected_uid = ctx["user_id"]

    for raw_token in (ctx["confirm_token"], ctx["login_token"]):
        payload = _decode_token(raw_token)
        assert payload["uid"] == expected_uid
        assert payload["sub"] == str(expected_uid)


def test_legacy_token_without_uid_and_numeric_username_still_resolves(client):
    """Eski (uid'siz) JWT'ler sayısal kullanıcı adları dahil geriye dönük çalışır."""
    ctx = _register_confirm_and_login(
        client, "987654321", "StrongPass123!", "numeric_legacy@example.com"
    )
    assert ctx["user_id"] != 987654321

    legacy_token = jwt.encode(
        {
            "sub": "987654321",
            "is_admin": False,
            "exp": datetime.now(timezone.utc) + timedelta(hours=2),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    res = client.get(
        "/api/user", headers={"Authorization": f"Bearer {legacy_token}"}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == ctx["user_id"]
    assert body["username"] == "987654321"


def test_username_change_preserves_session_and_all_routes(client):
    """DB'de username değişse bile mevcut uid'li token tüm uçlarda kesintisiz çalışır."""
    ctx = _register_confirm_and_login(
        client, "original_nick", "StrongPass123!", "rename_flow@example.com"
    )
    uid = ctx["user_id"]
    headers = ctx["headers"]
    today_str = str(date.today())

    # 1. Yeniden adlandırma öncesi antrenman, beslenme, profil ve program verisi oluştur
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
                    "sets_data": [{"weight_kg": 85.0, "reps": 8, "rir": 2}],
                }
            ],
        },
        headers=headers,
    )
    assert w_res.status_code == 200, w_res.text
    workout_id = w_res.json()["id"]

    n_post = client.post(
        "/api/nutrition/log",
        json={
            "log_date": today_str,
            "calories": 2300,
            "protein": 170,
            "carbs": 240,
            "fat": 70,
            "notes": "Ilk kayit",
        },
        headers=headers,
    )
    assert n_post.status_code == 200, n_post.text

    p_post = client.post("/api/user", json={"age": 26}, headers=headers)
    assert p_post.status_code == 200, p_post.text

    cp_post = client.post(
        "/api/custom-program",
        json={"program": _sample_week_program("Chest")},
        headers=headers,
    )
    assert cp_post.status_code == 200, cp_post.text

    # 2. Kullanıcı adını doğrudan DB'de değiştir (yeniden login olmadan)
    conn = get_db()
    conn.execute(
        "UPDATE users SET username = ? WHERE id = ?",
        ("renamed_nick", uid),
    )
    conn.commit()
    conn.close()

    # 3. Eski token ile tüm uç noktalar yeni username ve eski verilerle çalışmaya devam etmeli
    me_res = client.get("/api/user", headers=headers)
    assert me_res.status_code == 200, me_res.text
    assert me_res.json()["id"] == uid
    assert me_res.json()["username"] == "renamed_nick"

    u_upd = client.post("/api/user", json={"age": 27}, headers=headers)
    assert u_upd.status_code == 200, u_upd.text
    assert get_user_by_id(uid)["age"] == 27

    workouts_res = client.get("/api/workouts", headers=headers)
    assert workouts_res.status_code == 200, workouts_res.text
    assert any(w["id"] == workout_id for w in workouts_res.json())

    n_today = client.get("/api/nutrition/today", headers=headers)
    assert n_today.status_code == 200, n_today.text
    assert n_today.json()["log"]["calories"] == 2300

    n_put = client.put(
        "/api/nutrition/log",
        json={
            "original_date": today_str,
            "log_date": today_str,
            "calories": 2450,
            "protein": 180,
            "carbs": 250,
            "fat": 72,
            "notes": "Yeniden adlandirma sonrasi guncelleme",
        },
        headers=headers,
    )
    assert n_put.status_code == 200, n_put.text

    n_hist = client.get("/api/nutrition/history", headers=headers)
    assert n_hist.status_code == 200, n_hist.text
    assert any(
        item["date"] == today_str and item["calories"] == 2450
        for item in n_hist.json()["history"]
    )

    cp_upd = client.post(
        "/api/custom-program",
        json={"program": _sample_week_program("Shoulders")},
        headers=headers,
    )
    assert cp_upd.status_code == 200, cp_upd.text

    n_del = client.delete(
        f"/api/nutrition/log?log_date={today_str}", headers=headers
    )
    assert n_del.status_code == 200, n_del.text


def test_optional_username_compatibility_and_mismatch_still_forbidden(client):
    """username alanı opsiyoneldir; eşleşmeyen bir username gelirse 403 korunur."""
    owner = _register_confirm_and_login(
        client, "payload_owner", "StrongPass123!", "payload_owner@example.com"
    )
    _register_confirm_and_login(
        client, "payload_other", "StrongPass123!", "payload_other@example.com"
    )
    headers = owner["headers"]
    today_str = str(date.today())

    # Eski istemci gibi username gönderildiğinde çalışır
    assert (
        client.post(
            "/api/user",
            json={"username": "payload_owner", "age": 29},
            headers=headers,
        ).status_code
        == 200
    )

    # Açıkça None / null gönderildiğinde de çalışır
    assert (
        client.post(
            "/api/user",
            json={"username": None, "age": 30},
            headers=headers,
        ).status_code
        == 200
    )

    # Farklı username gönderildiğinde 403 verir
    assert (
        client.post(
            "/api/user",
            json={"username": "payload_other", "age": 31},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/custom-program",
            json={
                "username": "payload_other",
                "program": _sample_week_program("Arms"),
            },
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/nutrition/log",
            json={
                "username": "payload_other",
                "log_date": today_str,
                "calories": 2000,
                "protein": 150,
                "carbs": 200,
                "fat": 60,
            },
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/nutrition/log",
            json={
                "username": "payload_other",
                "original_date": today_str,
                "log_date": today_str,
                "calories": 2100,
                "protein": 155,
                "carbs": 205,
                "fat": 65,
            },
            headers=headers,
        ).status_code
        == 403
    )


def test_user_last_seen_tracks_by_user_id_across_username_change(
    client, admin_headers
):
    """_USER_LAST_SEEN id bazlı tutulur ve username değişse bile online bilgisini korur."""
    _USER_LAST_SEEN.clear()
    ctx = _register_confirm_and_login(
        client, "online_before", "StrongPass123!", "online_uid@example.com"
    )
    uid = ctx["user_id"]

    # Kullanıcı bir istek attığında _USER_LAST_SEEN[uid] güncellenir
    assert client.get("/api/user", headers=ctx["headers"]).status_code == 200
    assert uid in _USER_LAST_SEEN
    assert "online_before" not in _USER_LAST_SEEN

    # DB'de username değiştir
    conn = get_db()
    conn.execute(
        "UPDATE users SET username = ? WHERE id = ?",
        ("online_after", uid),
    )
    conn.commit()
    conn.close()

    # Admin kullanıcı listesi user_id üzerinden is_online=True görmeli
    admin_res = client.get("/api/admin/users", headers=admin_headers)
    assert admin_res.status_code == 200, admin_res.text
    body = admin_res.json()
    users = body if isinstance(body, list) else body["users"]
    renamed_entry = next(u for u in users if u["id"] == uid)
    assert renamed_entry["username"] == "online_after"
    assert renamed_entry["is_online"] is True

    # Admin'in kendi tokenında da uid/is_admin korunur
    admin_token = admin_headers["Authorization"].split(" ", 1)[1]
    admin_payload = _decode_token(admin_token)
    assert admin_payload["is_admin"] is True
    assert admin_payload["sub"] in (
        ADMIN_USERNAME,
        str(get_user_by_username(ADMIN_USERNAME)["id"]),
    )


def test_update_user_profile_service_accepts_both_id_and_username(client):
    """update_user_profile hem int user_id hem eski str username ile sorunsuz çalışır."""
    ctx = _register_confirm_and_login(
        client, "svc_user", "StrongPass123!", "svc_user@example.com"
    )
    uid = ctx["user_id"]

    res_by_id = update_user_profile({"age": 33}, uid)
    assert res_by_id is not None
    assert res_by_id["id"] == uid
    assert res_by_id["age"] == 33

    res_by_name = update_user_profile({"age": 34}, "svc_user")
    assert res_by_name is not None
    assert res_by_name["id"] == uid
    assert res_by_name["age"] == 34

import sqlite3

from core.config import DB_PATH
from core.database import get_db
from postgres_schema import POSTGRES_SCHEMA_STATEMENTS
from services.user_service import get_user_by_id, get_user_by_username


def _create_logged_in_athlete(client, username: str, email: str, password: str = "StrongPass123!"):
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
    login_data = login.json()
    return {
        "id": login_data["id"],
        "username": username,
        "password": password,
        "token": login_data["token"],
        "headers": {"Authorization": f"Bearer {login_data['token']}"},
    }


def test_profile_schema_columns_present_on_both_tables_and_pg_order(client):
    """Hem SQLite hem POSTGRES_SCHEMA_STATEMENTS yeni profil sütunlarını içerir."""
    conn = get_db()
    for table in ("users", "athlete_profiles"):
        cols = {
            r["name"] if isinstance(r, sqlite3.Row) or hasattr(r, "keys") else r[1]
            for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        assert {"nickname", "avatar_url", "target_weight"}.issubset(cols), (
            f"{table} eksik sütunlar: {cols}"
        )
    conn.close()

    create_ap_idx = next(
        i
        for i, s in enumerate(POSTGRES_SCHEMA_STATEMENTS)
        if "CREATE TABLE IF NOT EXISTS athlete_profiles" in s
    )
    alter_ap_indices = [
        i
        for i, s in enumerate(POSTGRES_SCHEMA_STATEMENTS)
        if "ALTER TABLE athlete_profiles" in s
    ]
    assert alter_ap_indices and all(i > create_ap_idx for i in alter_ap_indices)

    pg_joined = "\n".join(POSTGRES_SCHEMA_STATEMENTS)
    for col in ("nickname", "avatar_url", "target_weight"):
        assert f"users ADD COLUMN IF NOT EXISTS {col}" in pg_joined
        assert f"athlete_profiles ADD COLUMN IF NOT EXISTS {col}" in pg_joined


def test_target_weight_save_preserve_clear_and_validation(client):
    """Hedef kilo kaydedilir, başka güncellemede korunur, 0 ile temizlenir ve doğrulanır."""
    athlete = _create_logged_in_athlete(client, "target_wt_user", "targetwt@example.com")
    headers = athlete["headers"]

    initial = client.get("/api/user", headers=headers)
    assert initial.status_code == 200, initial.text
    assert initial.json()["target_weight"] is None
    assert initial.json()["nickname"] == ""
    assert initial.json()["avatar_url"] == ""

    # 1. Hedef kilo kaydet (ondalıklı değer)
    upd = client.post("/api/user", json={"target_weight": 78.5}, headers=headers)
    assert upd.status_code == 200, upd.text
    assert upd.json()["target_weight"] == 78.5

    # 2. Hedef kilo göndermeden başka alan güncelle -> target_weight korunmalı
    upd_age = client.post("/api/user", json={"age": 26}, headers=headers)
    assert upd_age.status_code == 200, upd_age.text
    assert upd_age.json()["age"] == 26
    assert upd_age.json()["target_weight"] == 78.5

    # Login yanıtı da target_weight içermeli
    relogin = client.post(
        "/api/auth/login",
        json={"username": athlete["username"], "password": athlete["password"]},
    )
    assert relogin.status_code == 200
    assert relogin.json()["target_weight"] == 78.5

    # 3. 0 gönderilince hedef kilo NULL (None) olarak temizlenmeli
    clr = client.post("/api/user", json={"target_weight": 0}, headers=headers)
    assert clr.status_code == 200, clr.text
    assert clr.json()["target_weight"] is None
    assert get_user_by_id(athlete["id"])["target_weight"] is None

    # 4. Geçersiz aralıklar 422 döndürmeli
    assert client.post("/api/user", json={"target_weight": -2}, headers=headers).status_code == 422
    assert client.post("/api/user", json={"target_weight": 550}, headers=headers).status_code == 422


def test_nickname_and_avatar_save_clear_and_validation(client):
    """Nickname ve avatar kaydedilir, login username korunur, temizlenebilir ve doğrulanır."""
    athlete = _create_logged_in_athlete(client, "avatar_nick_user", "avatarnick@example.com")
    headers = athlete["headers"]
    sample_avatar = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="

    upd = client.post(
        "/api/user",
        json={"nickname": "  Demir Bükücü  ", "avatar_url": sample_avatar},
        headers=headers,
    )
    assert upd.status_code == 200, upd.text
    body = upd.json()
    assert body["username"] == "avatar_nick_user"
    assert body["nickname"] == "Demir Bükücü"
    assert body["avatar_url"] == sample_avatar

    # Login username bozulmamış olmalı ve login yanıtı yeni alanları taşımalı
    relogin = client.post(
        "/api/auth/login",
        json={"username": "avatar_nick_user", "password": athlete["password"]},
    )
    assert relogin.status_code == 200, relogin.text
    assert relogin.json()["nickname"] == "Demir Bükücü"
    assert relogin.json()["avatar_url"] == sample_avatar
    assert get_user_by_username("avatar_nick_user")["nickname"] == "Demir Bükücü"

    # Temizleme
    clr = client.post(
        "/api/user",
        json={"nickname": "", "avatar_url": ""},
        headers=headers,
    )
    assert clr.status_code == 200, clr.text
    assert clr.json()["nickname"] == ""
    assert clr.json()["avatar_url"] == ""

    # Doğrulama kontrolleri
    assert client.post("/api/user", json={"nickname": "A"}, headers=headers).status_code == 422
    assert (
        client.post("/api/user", json={"avatar_url": "javascript:alert(1)"}, headers=headers).status_code
        == 422
    )
    large_valid = "data:image/jpeg;base64," + ("A" * 1_100_000)
    assert (
        client.post("/api/user", json={"avatar_url": large_valid}, headers=headers).status_code
        == 200
    )

    oversized = "data:image/jpeg;base64," + ("A" * 2_800_050)
    assert (
        client.post("/api/user", json={"avatar_url": oversized}, headers=headers).status_code
        == 422
    )


def test_admin_lists_and_updates_target_weight_and_nickname(client, admin_headers):
    """Admin kullanıcı listesi ve düzenlemesi nickname ile target_weight alanlarını destekler."""
    athlete = _create_logged_in_athlete(client, "admin_view_user", "adminview@example.com")

    edit_res = client.put(
        "/api/admin/user",
        json={"user_id": athlete["id"], "nickname": "Arena Şampiyonu", "target_weight": 82.0},
        headers=admin_headers,
    )
    assert edit_res.status_code == 200, edit_res.text
    assert edit_res.json()["nickname"] == "Arena Şampiyonu"
    assert edit_res.json()["target_weight"] == 82.0

    list_res = client.get("/api/admin/users", headers=admin_headers)
    assert list_res.status_code == 200, list_res.text
    row = next(u for u in list_res.json() if u["id"] == athlete["id"])
    assert row["nickname"] == "Arena Şampiyonu"
    assert row["target_weight"] == 82.0

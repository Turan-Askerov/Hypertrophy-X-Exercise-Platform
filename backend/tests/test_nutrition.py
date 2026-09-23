from datetime import date
import pytest


def test_nutrition_endpoints(client, auth_headers):
    """Beslenme kaydı ekleme, günlüğü getirme ve geçmişi listeleme testi."""
    today_str = str(date.today())

    # 1. Başlangıçta bugünün beslenmesini kontrol et
    today_res = client.get("/api/nutrition/today", headers=auth_headers)
    assert today_res.status_code == 200

    # 2. Beslenme günlüğü kaydet
    nutri_payload = {
        "username": "testathlete",
        "log_date": today_str,
        "protein": 160.0,
        "carbs": 220.0,
        "fat": 65.0,
        "calories": 2105,
        "notes": "Antrenman sonrası bol tavuk pilav"
    }
    log_res = client.post("/api/nutrition/log", json=nutri_payload, headers=auth_headers)
    assert log_res.status_code == 200

    # 3. Güncellenen bugünün beslenmesini oku
    updated_today = client.get("/api/nutrition/today", headers=auth_headers).json()
    assert updated_today["success"] is True
    assert updated_today["log"]["protein"] == 160.0
    assert updated_today["log"]["calories"] == 2105

    # 4. Geçmişi oku
    hist_res = client.get("/api/nutrition/history", headers=auth_headers)
    assert hist_res.status_code == 200
    history = hist_res.json().get("history", [])
    assert any(h["date"] == today_str for h in history)

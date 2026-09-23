import pytest


def test_health_check_endpoint(client):
    """GET /api/health servis durum kontrolünü test et."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") == "ok"
    assert data.get("db") == "ok"


def test_dashboard_and_progress_endpoints(client, auth_headers):
    """GET /api/dashboard ve GET /api/progress uç noktalarının çalıştığını doğrula."""
    res_dash = client.get("/api/dashboard", headers=auth_headers)
    assert res_dash.status_code == 200
    dash_data = res_dash.json()
    assert "user" in dash_data or "stats" in dash_data or "workouts" in dash_data

    res_prog = client.get("/api/progress", headers=auth_headers)
    assert res_prog.status_code == 200
    prog_data = res_prog.json()
    assert "top_progress" in prog_data
    assert "personal_records" in prog_data


def test_progress_chart_endpoint(client, auth_headers):
    """GET /api/progress/chart uç noktasının doğru veri formatı döndürdüğünü doğrula."""
    # Önce test antrenmanı oluştur
    workout_payload = {
        "date": "2026-08-10",
        "session_type": "Push",
        "exercises": [
            {
                "exercise_id": "overhead-press",
                "exercise_name": "Overhead Press",
                "muscle_group": "Shoulders",
                "sets_data": [
                    {"weight_kg": 50.0, "reps": 8},
                    {"weight_kg": 55.0, "reps": 6},
                ],
            }
        ],
    }
    client.post("/api/workouts", json=workout_payload, headers=auth_headers)

    res_chart = client.get("/api/progress/chart?exercise_id=overhead-press", headers=auth_headers)
    assert res_chart.status_code == 200
    chart_data = res_chart.json()
    assert "data" in chart_data
    assert "labels" in chart_data
    assert "details" in chart_data
    assert "is_bodyweight" in chart_data
    assert len(chart_data["data"]) >= 2
    assert chart_data["details"][0]["weight_kg"] == 50.0
    assert chart_data["details"][0]["reps"] == 8



def test_custom_program_save_and_retrieve(client, auth_headers):
    """Özel program kaydetme ve dashboard preferences güncellemesini test et."""
    program_payload = {
        "username": "testathlete",
        "program": [
            [
                {"day": "Pazartesi", "type": "Push", "focus": "Göğüs & Omuz", "isRest": False},
                {"day": "Salı", "type": "Pull", "focus": "Sırt & Biceps", "isRest": False},
                {"day": "Çarşamba", "type": "Dinlenme", "focus": "Toparlanma", "isRest": True},
            ]
        ],
    }
    res = client.post("/api/custom-program", json=program_payload, headers=auth_headers)
    assert res.status_code == 200
    assert res.json().get("success") is True

    # PR hedefleri güncelleme
    pr_payload = {"pr_targets": {"bench_press": 100.0, "squat": 140.0}}
    res_pr = client.post("/api/dashboard/preferences/pr-targets", json=pr_payload, headers=auth_headers)
    assert res_pr.status_code == 200
    assert res_pr.json().get("success") is True


def test_admin_endpoints(client, admin_headers):
    """Admin genel bakış ve kullanıcı listesi uç noktalarını test et."""
    res_overview = client.get("/api/admin/overview", headers=admin_headers)
    assert res_overview.status_code == 200
    overview = res_overview.json()
    assert "user_count" in overview or "total_workouts" in overview or "users" in overview

    res_users = client.get("/api/admin/users", headers=admin_headers)
    assert res_users.status_code == 200
    users = res_users.json()
    assert isinstance(users, list)
    assert len(users) >= 1


def test_expert_goals_and_doms_flow(client, auth_headers):
    """Uzman sistemi hedef belirleme ve DOMS bildirim akışını test et."""
    # Hedef güncelle
    goals_payload = {
        "primary_goal": "hypertrophy",
        "priority_muscles": ["chest", "lats"],
        "priority_note": "Hacim odaklı antrenman",
    }
    res_goals = client.put("/api/expert-data/goals", json=goals_payload, headers=auth_headers)
    assert res_goals.status_code == 200
    data = res_goals.json()
    assert data.get("success") is True
    assert data["target_muscles"]["primary_goal"] == "hypertrophy"

    # DOMS bildir
    doms_payload = {
        "muscle_group": "chest",
        "severity": 3,
        "notes": "Hafif göğüs ağrısı",
    }
    res_doms = client.post("/api/expert-system/doms", json=doms_payload, headers=auth_headers)
    assert res_doms.status_code == 200
    data_doms = res_doms.json()
    assert data_doms.get("success") is True
    assert "doms_daily" in data_doms


def test_admin_sql_terminal_security_and_read_only(client, admin_headers):
    """Admin SQL terminalinin Seçenek A read-only kurallarını test et."""
    # 1. Güvenli SELECT sorgusu çalışmalıdır
    res_select = client.post("/api/admin/db/query", json={"query": "SELECT id, username FROM users LIMIT 2;"}, headers=admin_headers)
    assert res_select.status_code == 200
    d_sel = res_select.json()
    assert d_sel["success"] is True
    assert d_sel["is_select"] is True
    assert "columns" in d_sel

    # 2. DROP TABLE engellenmelidir
    res_drop = client.post("/api/admin/db/query", json={"query": "DROP TABLE users;"}, headers=admin_headers)
    assert res_drop.status_code == 200
    d_drop = res_drop.json()
    assert d_drop["success"] is False
    assert "Güvenlik" in d_drop["error"]

    # 3. DELETE FROM engellenmelidir
    res_del = client.post("/api/admin/db/query", json={"query": "DELETE FROM workouts;"}, headers=admin_headers)
    assert res_del.status_code == 200
    d_del = res_del.json()
    assert d_del["success"] is False

    # 4. Çoklu sorgu injection engellenmelidir
    res_multi = client.post("/api/admin/db/query", json={"query": "SELECT 1; DROP TABLE users;"}, headers=admin_headers)
    assert res_multi.status_code == 200
    d_multi = res_multi.json()
    assert d_multi["success"] is False


def test_admin_db_info_and_tables(client, admin_headers):
    """Admin veritabanı bilgi ve şema endpoint'lerini doğrula."""
    res_info = client.get("/api/admin/db/info", headers=admin_headers)
    assert res_info.status_code == 200
    d_info = res_info.json()
    assert "backend" in d_info
    assert "tables" in d_info
    assert "db_size_formatted" in d_info

    res_tables = client.get("/api/admin/db/tables", headers=admin_headers)
    assert res_tables.status_code == 200
    assert isinstance(res_tables.json(), list)


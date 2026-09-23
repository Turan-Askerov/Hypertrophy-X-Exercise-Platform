import pytest


def test_workout_crud_lifecycle(client, auth_headers):
    """Antrenman oluşturma, listeleme, güncelleme ve silme yaşam döngüsü."""
    workout_payload = {
        "date": "2026-09-23",
        "session_type": "Push Day",
        "notes": "Harika bir göğüs idmanı",
        "exercises": [
            {
                "exercise_id": "bench-press",
                "exercise_name": "Bench Press",
                "muscle_group": "Chest",
                "is_bodyweight": False,
                "sets_data": [
                    {"weight_kg": 80.0, "reps": 8, "rir": 2},
                    {"weight_kg": 80.0, "reps": 7, "rir": 1}
                ]
            }
        ]
    }

    # 1. Workout Oluştur
    create_res = client.post("/api/workouts", json=workout_payload, headers=auth_headers)
    assert create_res.status_code == 200
    created_data = create_res.json()
    assert "id" in created_data
    workout_id = created_data["id"]

    # 2. Workout Listele ve Kontrol Et
    list_res = client.get("/api/workouts", headers=auth_headers)
    assert list_res.status_code == 200
    workouts = list_res.json()
    assert any(w["id"] == workout_id for w in workouts)

    # 3. Workout Güncelle
    update_payload = {
        "notes": "Güncellenmiş seans notu",
        "session_type": "Heavy Push Day"
    }
    update_res = client.put(f"/api/workouts/{workout_id}", json=update_payload, headers=auth_headers)
    assert update_res.status_code == 200

    # 4. Workout Sil
    delete_res = client.delete(f"/api/workouts/{workout_id}", headers=auth_headers)
    assert delete_res.status_code == 200

    # 5. Silindiğini teyit et
    list_after = client.get("/api/workouts", headers=auth_headers).json()
    assert not any(w["id"] == workout_id for w in list_after)


def test_workout_isolation_between_users(client, auth_headers):
    """Farklı bir kullanıcının başkasına ait antrenmanı silemediğini doğrula."""
    # 1. Kullanıcı A antrenman oluşturur
    w_res = client.post("/api/workouts", json={
        "date": "2026-09-23",
        "session_type": "Pull Day",
        "exercises": [
            {
                "exercise_id": "lat-pull-down",
                "exercise_name": "Lat Pulldown",
                "muscle_group": "Back",
                "sets_data": [{"weight_kg": 60.0, "reps": 10, "rir": 2}]
            }
        ]
    }, headers=auth_headers)
    workout_id = w_res.json()["id"]

    # 2. Kullanıcı B oluşturulur ve giriş yapar
    client.post("/api/auth/register", json={
        "username": "intruder_user",
        "password": "Password123!",
        "email": "intruder@example.com"
    })
    token_b = client.post("/api/auth/login", json={
        "username": "intruder_user",
        "password": "Password123!"
    }).json()["token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 3. Kullanıcı B, Kullanıcı A'nın antrenmanını silememeli
    del_res = client.delete(f"/api/workouts/{workout_id}", headers=headers_b)
    assert del_res.status_code in [403, 404]

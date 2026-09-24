import pytest
from expert_system.fuzzy_logic import rising, falling, _clamp
from expert_system.core import normalize_muscle_group, UI_MUSCLE_GROUPS
from expert_system.recommendation import rpe_summary_from_rir


def test_fuzzy_logic_functions():
    """Bulanık mantık üyelik fonksiyonlarının (rising/falling/clamp) sınır değerlerini test et."""
    # Clamp test
    assert _clamp(5, 0, 10) == 5
    assert _clamp(-1, 0, 10) == 0
    assert _clamp(15, 0, 10) == 10

    # Rising test (0'dan 1'e artış)
    assert rising(0, 0, 10) == 0.0
    assert rising(10, 0, 10) == 1.0
    assert rising(5, 0, 10) == 0.5
    assert rising(-5, 0, 10) == 0.0
    assert rising(15, 0, 10) == 1.0

    # Falling test (1'den 0'a azalış)
    assert falling(0, 0, 10) == 1.0
    assert falling(10, 0, 10) == 0.0
    assert falling(5, 0, 10) == 0.5


def test_muscle_group_normalization():
    """İngilizce ve Türkçe kas grubu adlarının UI standardına çevrilmesini doğrula."""
    assert normalize_muscle_group("Chest") == "Göğüs"
    assert normalize_muscle_group("Back") == "Sırt"
    assert normalize_muscle_group("Shoulders") == "Omuz"
    assert normalize_muscle_group("Göğüs") == "Göğüs"
    assert normalize_muscle_group("Legs") == "Bacak"


def test_rpe_from_rir():
    """RIR değerinden RPE karşılığının doğru hesaplandığını doğrula."""
    sample_data = {
        "set_count": 4,
        "average_rir": 2.0,
        "lowest_rir": 1,
        "near_failure_sets": 2,
        "workout_date": "2026-09-23",
        "session_type": "Push",
    }
    summary = rpe_summary_from_rir(sample_data)
    assert summary is not None
    assert summary["average_rpe"] == 8.0
    assert summary["highest_rpe"] == 9


def test_expert_data_endpoint(client, auth_headers):
    """GET /api/expert-data uç noktasının doğru şema döndürdüğünü doğrula."""
    res = client.get("/api/expert-data", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "target_muscles" in data or "eligibility" in data or "goals" in data


def test_priority_muscles_exercise_ordering():
    """Öncelikli kasların set sayısını artırmadan, o kasları hedefleyen hareketleri öne aldığını doğrula."""
    from expert_system.core import build_session_content
    
    mock_pool = [
        {
            "id": "ex_bench_flat",
            "name": "Flat Barbell Bench Press",
            "category": "compound",
            "target_muscles": ["Chest"],
            "secondary_muscles": ["Triceps", "Front Delts"],
            "equipment": ["barbell", "bench"],
            "analysis": {"family": "bench_press", "fatigue_cost": "high"}
        },
        {
            "id": "ex_incline_db_press",
            "name": "Incline Dumbbell Press",
            "category": "compound",
            "target_muscles": ["Upper Chest"],
            "secondary_muscles": ["Triceps", "Front Delts"],
            "equipment": ["dumbbell", "incline_bench"],
            "analysis": {"family": "incline_press", "fatigue_cost": "medium"}
        },
        {
            "id": "ex_tricep_pushdown",
            "name": "Triceps Pushdown",
            "category": "isolation",
            "target_muscles": ["Triceps"],
            "equipment": ["cable"],
            "analysis": {"family": "pushdown", "fatigue_cost": "low"}
        }
    ]
    
    # Priority_muscles verilmediğinde Flat Bench Press önde olabilir
    res_no_priority = build_session_content(
        muscle_groups=["Chest", "Upper Chest", "Triceps"],
        available_equipment=["barbell", "dumbbell", "bench", "incline_bench", "cable"],
        doms_state=[],
        constraints=[],
        exercise_pool=mock_pool,
        priority_muscles=[]
    )
    assert res_no_priority["status"] == "ready"
    
    # Priority_muscles olarak 'Upper Chest' verildiğinde Incline Dumbbell Press ilk sıraya gelmeli
    res_with_priority = build_session_content(
        muscle_groups=["Chest", "Upper Chest", "Triceps"],
        available_equipment=["barbell", "dumbbell", "bench", "incline_bench", "cable"],
        doms_state=[],
        constraints=[],
        exercise_pool=mock_pool,
        priority_muscles=["Upper Chest"]
    )
    assert res_with_priority["status"] == "ready"
    first_ex = res_with_priority["exercises"][0]
    assert first_ex["id"] == "ex_incline_db_press"
    # Fazla set eklenmediğini (standart 3 set kaldığını) doğrula
    assert first_ex["prescription"]["sets"] <= 3


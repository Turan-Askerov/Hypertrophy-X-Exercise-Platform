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

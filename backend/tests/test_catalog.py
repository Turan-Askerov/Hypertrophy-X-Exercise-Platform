import pytest
from exercise_catalog import EXERCISE_POOL
from exercise_aliases import EXERCISE_ALIASES
import main


def test_exercise_pool_integrity():
    """Egzersiz havuzunun temel alanlarının eksiksiz olduğunu doğrula."""
    assert len(EXERCISE_POOL) >= 60

    ids = set()
    for ex in EXERCISE_POOL:
        assert "id" in ex and ex["id"]
        assert "name" in ex and ex["name"]
        assert "muscle_group" in ex
        assert "analysis" in ex
        assert ex["id"] not in ids, f"Tekrarlanan exercise id: {ex['id']}"
        ids.add(ex["id"])


def test_exercise_aliases_resolve_valid():
    """Yaygın aliasların resolve_exercise_metadata ile doğru çözümlendiğini doğrula."""
    # Bench press alias testi
    resolved = main.resolve_exercise_metadata("dumbell bench press", "dumbell bench press")
    assert resolved is not None
    assert resolved["id"] == "dumbbell-bench-press"

    # Barfiks alias testi
    resolved_pullup = main.resolve_exercise_metadata("barfiks", "barfiks")
    assert resolved_pullup is not None
    assert resolved_pullup["id"] == "pull-ups-bw"


def test_api_exercises_endpoint(client):
    """GET /api/exercises uç noktasının doğru şemayı döndürdüğünü test et."""
    res = client.get("/api/exercises")
    assert res.status_code == 200
    data = res.json()
    assert "exercises" in data
    assert "muscle_groups" in data
    exercises = data["exercises"]
    assert isinstance(exercises, list)
    assert len(exercises) >= 60
    first = exercises[0]
    assert "id" in first
    assert "name" in first
    assert "muscle_group" in first

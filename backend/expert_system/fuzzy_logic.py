"""Hypertrophy-X kural tabanlı fuzzy uzman sistemi.

Bu modül üretken yapay zekâ veya dış API kullanmaz. Kararlar, görünür olgular
(profile, antrenman geçmişi, seans kontrolü ve DOMS kayıtları) ile açık kurallardan
üretilir. Fuzzy üyelikler 0.0–1.0 aralığındadır; kullanıcıya sonuçla birlikte
hangi kuralların etkinleştiği de döndürülür.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

UI_MUSCLE_GROUPS = (
    "Göğüs", "Sırt", "Omuz", "Biceps", "Triceps", "Bacak", "Core",
)

PRIMARY_GOALS = {
    "hypertrophy": "Kas kazanımı",
    "strength": "Güç kazanımı",
    "fat_loss": "Yağ kaybı ve kas korunumu",
}

ENGLISH_TO_UI_MUSCLE = {
    "Chest": "Göğüs",
    "Back": "Sırt",
    "Shoulders": "Omuz",
    "Biceps": "Biceps",
    "Triceps": "Triceps",
    "Legs": "Bacak",
    "Core": "Core",
    "Traps": "Sırt",
}


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def rising(value: float, start: float, end: float) -> float:
    """start'ta 0, end'de 1 olan doğrusal fuzzy üyelik."""
    if end <= start:
        return 1.0 if value >= end else 0.0
    return _clamp((float(value) - start) / (end - start))


def falling(value: float, start: float, end: float) -> float:
    """start'ta 1, end'de 0 olan doğrusal fuzzy üyelik."""
    if end <= start:
        return 1.0 if value <= start else 0.0
    return _clamp((end - float(value)) / (end - start))



"""Hypertrophy-X uzman öneri programı yardımcıları.

Bu modül RIR kaydını kullanıcıya gösterilecek RPE özetine dönüştürür ve mevcut
uzman motorunun ürettiği seansları 1–3 haftalık, yeniden sıralanabilir bir
takvime yerleştirir. Veritabanına doğrudan yazmaz.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

WEEKDAY_LABELS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_tr_date(value: Any) -> str:
    """ISO tarihleri kullanıcı arayüzü için gg.aa.yyyy biçimine çevirir."""
    raw = str(value or "").strip()[:10]
    parts = raw.split("-")
    if len(parts) == 3 and all(parts):
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return raw or "—"


def rpe_summary_from_rir(recent_rir: dict[str, Any] | None) -> dict[str, Any] | None:
    """RIR 0..5 değerini set bazında RPE 10..5 karşılığına dönüştürür.

    RPE = 10 - RIR eşlemesi yalnızca arayüz özeti içindir. Kullanıcının girdiği
    ve saklanan veri RIR olarak kalır; bu fonksiyon geçmiş setleri değiştirmez.
    """
    if not isinstance(recent_rir, dict) or not recent_rir:
        return None
    count = max(0, int(_number(recent_rir.get("set_count"))))
    if not count:
        return None
    average_rir = max(0.0, min(5.0, _number(recent_rir.get("average_rir"))))
    lowest_rir = max(0, min(5, int(_number(recent_rir.get("lowest_rir")))))
    return {
        "workout_date": str(recent_rir.get("workout_date") or ""),
        "workout_date_display": format_tr_date(recent_rir.get("workout_date")),
        "session_type": str(recent_rir.get("session_type") or "Antrenman"),
        "set_count": count,
        "average_rpe": round(10.0 - average_rir, 1),
        "highest_rpe": 10 - lowest_rir,
        "high_effort_sets": max(0, int(_number(recent_rir.get("near_failure_sets")))),
        "derivation": "Set bazlı RIR kayıtlarından türetildi",
    }


def recommended_duration_weeks(
    context: dict[str, Any], rpe_summary: dict[str, Any] | None, days_per_week: int
) -> int:
    """Yalnız plan döngüsünün uzunluğunu seçer; sağlık kararı vermez."""
    active_injuries = [
        item for item in (context.get("injuries") or [])
        if isinstance(item, dict) and bool(item.get("is_active", True))
    ]
    highest_injury = max((_number(item.get("severity")) for item in active_injuries), default=0.0)
    highest_doms = max(
        (_number(item.get("pain_level")) for item in (context.get("doms_metrics") or []) if isinstance(item, dict)),
        default=0.0,
    )
    if highest_injury >= 4:
        return 1
    if highest_doms >= 4 or (rpe_summary and _number(rpe_summary.get("average_rpe")) >= 9):
        return 2
    targets = (context.get("targets") or {}).get("priority_muscles") or []
    if days_per_week >= 5 and targets:
        return 3
    return 1


def _training_positions(days_per_week: int) -> list[int]:
    patterns = {
        1: [0],
        2: [0, 3],
        3: [0, 2, 4],
        4: [0, 1, 3, 5],
        5: [0, 1, 2, 4, 5],
        6: [0, 1, 2, 3, 4, 5],
        7: [0, 1, 2, 3, 4, 5, 6],
    }
    return patterns.get(max(1, min(7, int(days_per_week))), patterns[4])


# HX_ALTERNATIVE_EXERCISE_ID_PROPAGATION_V1
def _exercise_view(item: dict[str, Any]) -> dict[str, str]:
    prescription = item.get("prescription") if isinstance(item.get("prescription"), dict) else {}
    return {
        # ID sonraki alternatif isteği için korunur; eski taslaklar arayüzde isimden çözülür.
        "id": str(item.get("id") or item.get("exercise_id") or ""),
        "name": str(item.get("name") or item.get("exercise_name") or "Hareket"),
        "sets": str(prescription.get("sets") or item.get("sets") or "—"),
        "reps": str(prescription.get("reps") or item.get("reps") or "—"),
        "effort": str(prescription.get("effort_note") or item.get("effort") or ""),
    }


def _week_days(program: dict[str, Any], week_index: int, days_per_week: int) -> list[dict[str, Any]]:
    sessions = [
        item for item in (program.get("sessions") or [])
        if isinstance(item, dict) and not item.get("is_recovery_day")
    ]
    positions = _training_positions(days_per_week)
    days: list[dict[str, Any]] = []
    session_cursor = 0
    for day_index, label in enumerate(WEEKDAY_LABELS):
        session = sessions[session_cursor % len(sessions)] if sessions and day_index in positions else None
        if session is not None:
            session_cursor += 1
        if session:
            content = session.get("content") if isinstance(session.get("content"), dict) else {}
            exercise_items = [
                _exercise_view(item) for item in (content.get("exercises") or []) if isinstance(item, dict)
            ]
            muscle_labels = session.get("muscle_labels") or []
            days.append({
                "day_id": f"week-{week_index + 1}-day-{day_index + 1}",
                # slot_id günün sabit kimliği, content_id ise sürüklenebilen seans içeriğidir.
                "slot_id": f"week-{week_index + 1}-day-{day_index + 1}",
                "content_id": f"week-{week_index + 1}-content-{day_index + 1}",
                "day": label,
                "type": str(session.get("title") or "Antrenman"),
                "focus": ", ".join(str(item) for item in muscle_labels if item) or "Genel antrenman",
                "isRest": False,
                "session_id": str(session.get("session_id") or ""),
                "content_status": str(content.get("status") or "ready"),
                "content_reason": str(content.get("reason") or ""),
                "exercises": exercise_items,
            })
        else:
            days.append({
                "day_id": f"week-{week_index + 1}-day-{day_index + 1}",
                # Dinlenme de taşınabilir bir içeriktir; gün slotu sabit kalır.
                "slot_id": f"week-{week_index + 1}-day-{day_index + 1}",
                "content_id": f"week-{week_index + 1}-content-{day_index + 1}",
                "day": label,
                "type": "Dinlenme",
                "focus": "Toparlanma",
                "isRest": True,
                "session_id": "",
                "content_status": "recovery",
                "content_reason": "Planlı dinlenme günü.",
                "exercises": [],
            })
    return days


def build_recommendation_program(
    dynamic_program: dict[str, Any],
    context: dict[str, Any],
    days_per_week: int,
    rpe_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Dinamik uzman motoru sonucunu kullanıcıya düzenlenebilir takvime çevirir."""
    safe_days = max(1, min(7, int(days_per_week)))
    duration = recommended_duration_weeks(context, rpe_summary, safe_days)
    selected = (dynamic_program.get("program") or {}) if isinstance(dynamic_program, dict) else {}
    split = (dynamic_program.get("split") or {}) if isinstance(dynamic_program, dict) else {}
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    weeks = [
        {"week_index": index, "label": f"{index + 1}. Hafta", "days": _week_days(selected, index, safe_days)}
        for index in range(duration)
    ]
    return {
        "schema_version": 1,
        "name": str(selected.get("name") or split.get("selected", {}).get("name") or "Uzman Önerisi"),
        "generated_at": generated_at,
        "generated_on_display": format_tr_date(generated_at),
        "days_per_week": safe_days,
        "duration_weeks": duration,
        "goal": str(dynamic_program.get("goal") or "hypertrophy"),
        "priority_muscle_labels": list(dynamic_program.get("priority_muscle_labels") or []),
        "rpe_summary": rpe_summary,
        "split_explanation": dict(split.get("explanation") or {}),
        "catalog_note": str(dynamic_program.get("catalog_note") or ""),
        "weeks": weeks,
    }


__all__ = [
    "build_recommendation_program",
    "format_tr_date",
    "recommended_duration_weeks",
    "rpe_summary_from_rir",
]
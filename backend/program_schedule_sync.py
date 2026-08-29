"""Gerçek antrenmanları sabit haftalık program slotlarıyla eşleştiren saf yardımcılar."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import re
import unicodedata
from typing import Any

WEEKDAY_COUNT = 7
SLOT_KEYS = {"day", "day_id", "slot_id"}
REST_WORDS = ("dinlenme", "rest", "recovery", "off")


def _plain(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(char for char in raw if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()


def is_rest_day(item: Any) -> bool:
    if not isinstance(item, dict):
        return True
    if bool(item.get("isRest")):
        return True
    return any(word in _plain(item.get("type")).split() for word in REST_WORDS)


def session_kind(value: Any) -> str | None:
    """Push A/Push Day, Pull B/Pull Day ve Legs/Leg Day başlıklarını eşler."""
    text = _plain(value)
    tokens = set(text.split())
    if not text or text in {"workout", "antrenman", "training"}:
        return None
    if tokens.intersection(REST_WORDS):
        return "rest"
    if "push" in tokens or "itme" in tokens:
        return "push"
    if "pull" in tokens or "cekis" in tokens or "ceki" in tokens:
        return "pull"
    if tokens.intersection({"leg", "legs", "bacak", "lower"}):
        return "legs"
    return text


def _slot_shell(day: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in day.items() if key in SLOT_KEYS}


def _content(day: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in day.items() if key not in SLOT_KEYS}


def _replace_content(days: list[dict[str, Any]], index: int, content: dict[str, Any]) -> None:
    days[index] = {**_slot_shell(days[index]), **deepcopy(content)}


def _swap_contents(days: list[dict[str, Any]], left: int, right: int) -> None:
    left_content = _content(days[left])
    right_content = _content(days[right])
    _replace_content(days, left, right_content)
    _replace_content(days, right, left_content)


def _actual_content(actual: dict[str, Any]) -> dict[str, Any]:
    session_type = str(actual.get("session_type") or "Antrenman")
    workout_date = str(actual.get("date") or "")
    token = actual.get("id") or workout_date or "record"
    return {
        "content_id": f"actual-workout-{token}",
        "type": session_type,
        "focus": f"Gerçek antrenman kaydı · {workout_date}".rstrip(" ·"),
        "isRest": False,
        "session_id": f"actual-workout-{token}",
        "content_status": "completed",
        "content_reason": "Kullanıcının kaydettiği gerçek antrenman bu güne işlendi.",
        "exercises": [],
    }


def current_week_actuals(workouts: list[dict[str, Any]], today: date | None = None) -> dict[int, dict[str, Any]]:
    """Bugünün ISO haftasındaki, türü belirlenebilen son gerçek seansları döndürür."""
    reference = today or date.today()
    target_year, target_week, _ = reference.isocalendar()
    chosen: dict[int, dict[str, Any]] = {}
    for workout in workouts or []:
        try:
            workout_date = date.fromisoformat(str(workout.get("date") or "")[:10])
        except (TypeError, ValueError):
            continue
        year, week, weekday = workout_date.isocalendar()
        if (year, week) != (target_year, target_week) or workout_date > reference:
            continue
        if not session_kind(workout.get("session_type")):
            continue
        index = weekday - 1
        previous = chosen.get(index)
        if previous is None or int(workout.get("id") or 0) >= int(previous.get("id") or 0):
            chosen[index] = dict(workout)
    return chosen


def align_rest_slots(days: list[dict[str, Any]], desired_rest_indices: set[int]) -> bool:
    """Dinlenme içeriklerini kullanıcının özel programdaki dinlenme slotlarına taşır."""
    if len(days) != WEEKDAY_COUNT:
        return False
    changed = False
    for desired_index in sorted(index for index in desired_rest_indices if 0 <= index < WEEKDAY_COUNT):
        if is_rest_day(days[desired_index]):
            continue
        source_index = next(
            (index for index, item in enumerate(days) if index not in desired_rest_indices and is_rest_day(item)),
            None,
        )
        if source_index is None:
            continue
        _swap_contents(days, desired_index, source_index)
        changed = True
    return changed


def reconcile_week(
    days: list[dict[str, Any]],
    actual_by_slot: dict[int, dict[str, Any]],
    today_index: int,
    protected_rest_indices: set[int] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Gerçek seansı gününe işler ve yalnız mümkünse kaçırılan seansı ileri dinlenmeye taşır."""
    result = [deepcopy(item) if isinstance(item, dict) else {} for item in (days or [])[:WEEKDAY_COUNT]]
    if len(result) != WEEKDAY_COUNT:
        return result, False
    changed = False
    protected = set(protected_rest_indices or set())
    actual_slots = set(actual_by_slot)

    # Öncelik 1: Kaydedilen gerçek antrenman, ait olduğu günün içeriğini belirler.
    for source_index in sorted(actual_by_slot):
        actual = actual_by_slot[source_index]
        actual_kind = session_kind(actual.get("session_type"))
        if not actual_kind or actual_kind == "rest" or not 0 <= source_index < WEEKDAY_COUNT:
            continue
        planned_kind = session_kind(result[source_index].get("type"))
        if planned_kind == actual_kind and not is_rest_day(result[source_index]):
            continue
        # Aynı tür tekrarlanıyorsa gelecekteki en yakın kart önce seçilir.
        candidates = list(range(source_index + 1, WEEKDAY_COUNT)) + list(range(source_index - 1, -1, -1))
        target_index = next(
            (index for index in candidates
             if index not in actual_slots
             and not is_rest_day(result[index])
             and session_kind(result[index].get("type")) == actual_kind),
            None,
        )
        if target_index is not None:
            displaced_content = _content(result[source_index])
            _replace_content(result, source_index, _actual_content(actual))
            _replace_content(result, target_index, displaced_content)
            changed = True
            continue

        # Eş seans kartı yoksa, kaynak içerik ancak ileri boş bir dinlenmeye korunur.
        rest_target = next(
            (index for index in range(source_index + 1, WEEKDAY_COUNT)
             if index not in actual_slots and index not in protected and is_rest_day(result[index])),
            None,
        )
        previous_content = _content(result[source_index])
        _replace_content(result, source_index, _actual_content(actual))
        if rest_target is not None and not is_rest_day(previous_content):
            _replace_content(result, rest_target, previous_content)
        changed = True

    # Öncelik 2: Yalnız bitmiş günlerdeki gerçek kayıtsız planlı seanslar telafi edilir.
    # Bugün henüz bitmediği için otomatik olarak "kaçırıldı" sayılmaz.
    for missed_index in range(max(0, min(today_index, WEEKDAY_COUNT - 1))):
        if missed_index in actual_slots or is_rest_day(result[missed_index]) or missed_index in protected:
            continue
        rest_target = next(
            (index for index in range(missed_index + 1, WEEKDAY_COUNT)
             if index not in actual_slots and index not in protected and is_rest_day(result[index])),
            None,
        )
        if rest_target is None:
            continue
        _swap_contents(result, missed_index, rest_target)
        changed = True

    return result, changed


__all__ = ["align_rest_slots", "current_week_actuals", "is_rest_day", "reconcile_week"]


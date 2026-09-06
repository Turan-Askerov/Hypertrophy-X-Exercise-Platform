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


SESSION_DISPLAY_TITLES = {
    "push": "Push Day",
    "pull": "Pull Day",
    "legs": "Legs Day",
    "upper": "Upper Body",
    "lower": "Lower Body",
    "full_body": "Full Body Day",
    "rest": "Dinlenme",
}

SESSION_DEFAULT_FOCUS = {
    "push": "Göğüs, Ön Omuz, Triceps",
    "pull": "Latissimus, Üst Sırt, Biceps",
    "legs": "Quadriceps, Hamstring, Gluteus, Calf",
    "upper": "Göğüs, Sırt, Omuz, Kollar",
    "lower": "Quadriceps, Hamstring, Gluteus, Calf",
    "full_body": "Tüm Vücut Bileşik Egzersizler",
    "rest": "Toparlanma",
}


def format_session_title(raw_type: Any) -> str:
    text = str(raw_type or "").strip()
    if not text:
        return "Antrenman"
    kind = session_kind(text)
    if kind in SESSION_DISPLAY_TITLES:
        return SESSION_DISPLAY_TITLES[kind]
    lower = text.lower()
    if "day" not in lower and "gün" not in lower and "body" not in lower and "dinlenme" not in lower and "rest" not in lower:
        return f"{text} Day"
    return text


def is_focus_compatible(raw_type: Any, focus_text: Any) -> bool:
    if not raw_type or not focus_text:
        return True
    kind = session_kind(raw_type)
    f = str(focus_text).lower()
    if kind == "push":
        if any(w in f for w in ["latissimus", "biceps", "quadriceps", "hamstring"]):
            if not any(w in f for w in ["göğüs", "gogus", "triceps", "omuz", "ön omuz", "yan omuz"]):
                return False
    elif kind == "pull":
        if any(w in f for w in ["göğüs", "gogus", "quadriceps", "hamstring", "ön omuz"]):
            if not any(w in f for w in ["latissimus", "biceps", "sırt", "sirt", "arka omuz", "trapez"]):
                return False
    elif kind == "legs":
        if any(w in f for w in ["göğüs", "gogus", "latissimus", "biceps", "triceps"]):
            if not any(w in f for w in ["quad", "hamstring", "glute", "bacak", "calf", "kalf"]):
                return False
    return True


def format_session_focus(raw_type: Any, existing_focus: Any = None) -> str:
    existing = str(existing_focus or "").strip()
    if not existing or existing.startswith(("Antrenman yapıldı", "Gerçek antrenman kaydı", "Genel antrenman")) or not is_focus_compatible(raw_type, existing):
        kind = session_kind(raw_type)
        return SESSION_DEFAULT_FOCUS.get(kind, "Genel antrenman")
    return existing


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


def _format_day_month_year(date_str: str) -> str:
    raw = str(date_str or "").strip()[:10]
    parts = raw.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return raw


def _actual_content(actual: dict[str, Any], fallback_focus: str | None = None) -> dict[str, Any]:
    raw_type = str(actual.get("session_type") or "Antrenman").strip()
    session_title = format_session_title(raw_type)
    focus_text = format_session_focus(raw_type, fallback_focus or actual.get("focus") or actual.get("notes"))
    workout_date = str(actual.get("date") or "")
    token = actual.get("id") or workout_date or "record"
    return {
        "content_id": f"actual-workout-{token}",
        "type": session_title,
        "focus": focus_text,
        "isRest": False,
        "session_id": f"actual-workout-{token}",
        "content_status": "completed",
        "content_reason": f"Kullanıcının kaydettiği {session_title} bu güne işlendi.",
        "exercises": actual.get("exercises") or [],
        "date": workout_date,
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

    # Adım 0: Önceki haftalardan kalmış bayat gerçek antrenman etiketlerini temizle
    valid_actual_dates = {str(act.get("date") or "")[:10] for act in actual_by_slot.values()}
    for i, item in enumerate(result):
        if not isinstance(item, dict):
            continue
        focus_str = str(item.get("focus") or "")
        content_id = str(item.get("content_id") or "")
        session_id = str(item.get("session_id") or "")
        is_actual = (
            item.get("content_status") == "completed"
            or content_id.startswith("actual-workout")
            or session_id.startswith("actual-workout")
            or focus_str.startswith(("Gerçek antrenman kaydı", "Antrenman yapıldı"))
        )
        if is_actual:
            matched = False
            for d in valid_actual_dates:
                if d and (d in focus_str or d in content_id or d in session_id or _format_day_month_year(d) in focus_str):
                    matched = True
                    break
            if not matched:
                item.pop("content_status", None)
                item.pop("content_reason", None)
                if content_id.startswith("actual-workout"):
                    item["content_id"] = f"content-{i+1}"
                if session_id.startswith("actual-workout"):
                    item["session_id"] = f"session-{i+1}"
                if focus_str.startswith(("Gerçek antrenman kaydı", "Antrenman yapıldı")):
                    item["focus"] = "Toparlanma" if is_rest_day(item) else "Genel antrenman"
                changed = True

    # Öncelik 1: Kaydedilen gerçek antrenman, ait olduğu günün içeriğini belirler.
    for source_index in sorted(actual_by_slot):
        actual = actual_by_slot[source_index]
        actual_kind = session_kind(actual.get("session_type"))
        if not actual_kind or actual_kind == "rest" or not 0 <= source_index < WEEKDAY_COUNT:
            continue
        planned_kind = session_kind(result[source_index].get("type"))
        if planned_kind == actual_kind and not is_rest_day(result[source_index]):
            result[source_index]["type"] = format_session_title(result[source_index].get("type"))
            result[source_index]["focus"] = format_session_focus(result[source_index].get("type"), result[source_index].get("focus"))
            result[source_index]["content_status"] = "completed"
            result[source_index]["date"] = str(actual.get("date") or "")
            if actual.get("exercises"):
                result[source_index]["exercises"] = actual.get("exercises")
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
            _replace_content(result, source_index, _actual_content(actual, fallback_focus=result[source_index].get("focus")))
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
        _replace_content(result, source_index, _actual_content(actual, fallback_focus=result[source_index].get("focus")))
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


def clean_non_active_week(
    days: list[dict[str, Any]],
    week_index: int = 0,
    reference_pool: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Aktif olmayan (gelecek veya geçmiş şablon) haftaları gerçek antrenman artıklarından temizler."""
    result = [deepcopy(item) if isinstance(item, dict) else {} for item in (days or [])[:WEEKDAY_COUNT]]
    if len(result) != WEEKDAY_COUNT:
        return result, False
    changed = False
    for i, item in enumerate(result):
        if not isinstance(item, dict):
            continue
        rest = is_rest_day(item)
        content_reason = str(item.get("content_reason") or "")
        content_status = str(item.get("content_status") or "")
        content_id = str(item.get("content_id") or "")
        session_id = str(item.get("session_id") or "")
        focus_str = str(item.get("focus") or "")

        # 1. content_status temizliği
        expected_status = "recovery" if rest else "ready"
        if content_status == "completed" or (rest and content_status != "recovery"):
            item["content_status"] = expected_status
            changed = True

        # 2. content_reason temizliği (gerçek antrenman nedenlerini kaldır)
        if (
            "Kullanıcının kaydettiği" in content_reason
            or "Gerçek antrenman" in content_reason
            or "bu güne işlendi" in content_reason
        ):
            item["content_reason"] = "Planlı dinlenme günü." if rest else "Ekipman, DOMS ve aktif kısıtlara göre hareket seçildi."
            changed = True

        # 3. content_id ve session_id temizliği
        if content_id.startswith("actual-workout"):
            item["content_id"] = f"week-{week_index + 1}-content-{i + 1}"
            changed = True
        if session_id.startswith("actual-workout"):
            item["session_id"] = f"week-{week_index + 1}-session-{i + 1}"
            changed = True

        # 4. date anahtarı temizliği
        if "date" in item:
            item.pop("date", None)
            changed = True

        # 5. focus uyumluluğu ve temizliği
        new_focus = "Toparlanma" if rest else format_session_focus(item.get("type"), focus_str)
        if new_focus != focus_str:
            item["focus"] = new_focus
            changed = True

        # 6. Boş kalan egzersiz listesini doldur (şablon veya referans havuzundan)
        if not rest and (not item.get("exercises") or len(item.get("exercises")) == 0):
            kind = session_kind(item.get("type"))
            fallback_exs = next(
                (deepcopy(other.get("exercises")) for other in result
                 if not is_rest_day(other) and session_kind(other.get("type")) == kind and other.get("exercises")),
                None,
            )
            if not fallback_exs and reference_pool and kind in reference_pool:
                fallback_exs = deepcopy(reference_pool[kind])
            if fallback_exs:
                item["exercises"] = fallback_exs
                changed = True

    return result, changed


__all__ = ["align_rest_slots", "clean_non_active_week", "current_week_actuals", "is_focus_compatible", "is_rest_day", "reconcile_week"]



from __future__ import annotations

from datetime import date
from typing import Any, Callable

from expert_system.recommendation import format_tr_date


Rule = Callable[[dict[str, Any]], list[dict[str, Any]]]


def _number(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _label(value: Any) -> str:
    return str(value or "Belirtilmedi").strip() or "Belirtilmedi"


def _finding(
    rule_id: str,
    priority: int,
    category: str,
    title: str,
    message: str,
    action: str,
    tone: str = "info",
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "priority": priority,
        "category": category,
        "title": title,
        "message": message,
        "action": action,
        "tone": tone,
    }



from typing import Any
from expert_system.rule_utils import _number, _label, _finding, format_tr_date

def rule_equipment(context: dict[str, Any]) -> list[dict[str, Any]]:
    equipment = context.get("equipment") or []
    if equipment:
        return []
    return [_finding(
        "equipment-missing", 65, "Ekipman", "Salon ekipmanı belirtilmemiş",
        "Hareket önerilerinin uygulanabilir olması için en az bir salonun ekipmanını kaydetmek gerekir.",
        "Kurulum > Salonlar sekmesinden erişebildiğin ekipmanı kaydet.", "warn",
    )]


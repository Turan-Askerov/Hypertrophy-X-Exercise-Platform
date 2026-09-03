from typing import Any
from expert_system.rule_utils import _number, _label, _finding, format_tr_date

def rule_targets(context: dict[str, Any]) -> list[dict[str, Any]]:
    targets = (context.get("targets") or {}).get("priority_muscles") or []
    if not targets:
        return [_finding(
            "targets-missing", 32, "Hedef", "Öncelikli kas seçimi bekleniyor",
            "Split odağının kişiselleşmesi için en az bir öncelikli kas grubu seçilmelidir.",
            "Kurulum > Hedefler sekmesinden en fazla üç öncelikli kas seç.", "info",
        )]
    labels = ", ".join(_label(item) for item in targets[:3])
    return [_finding(
        "targets-available", 20, "Hedef", "Öncelikli kaslar tanımlı",
        f"Mevcut öncelik: {labels}. Koruma ve toparlanma kuralları izin verdiğinde Split odağı bu kaslara yönelir.",
        "Kural çakışması yoksa bir sonraki taslakta bu kasları ana odak olarak kullan.", "good",
    )]


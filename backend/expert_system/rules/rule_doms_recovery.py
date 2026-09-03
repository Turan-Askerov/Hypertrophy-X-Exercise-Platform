from typing import Any
from expert_system.rule_utils import _number, _label, _finding, format_tr_date

def rule_doms_recovery(context: dict[str, Any]) -> list[dict[str, Any]]:
    entries = [item for item in (context.get("doms_metrics") or []) if _number(item.get("pain_level")) > 0]
    if not entries:
        return []
    highest = max(entries, key=lambda item: _number(item.get("pain_level")))
    level = int(_number(highest.get("pain_level")))
    muscle = _label(highest.get("muscle_label") or highest.get("muscle_group"))
    if level >= 4:
        return [_finding(
            "high-doms-recovery", 84, "Toparlanma", "Yüksek kas ağrısı bildirimi",
            f"{muscle} için DOMS seviyesi {level}/5. Aynı kasın doğrudan yükünü artırmak yerine toparlanmayı öncele.",
            "Split taslağında bu kası ertele veya doğrudan setlerini azaltılmış seçenek olarak göster.", "warn",
        )]
    return [_finding(
        "doms-monitoring", 60, "Toparlanma", "Kas ağrısı takibi",
        f"{muscle} için DOMS seviyesi {level}/5. Seans sırasında teknik, hareket açıklığı ve toparlanma hissini izle.",
        "Bu kas için yük artışını zorunlu öneri yapma; kullanıcıya kontrollü seçenek sun.", "info",
    )]


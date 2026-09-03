from typing import Any
from expert_system.rule_utils import _number, _label, _finding, format_tr_date

def rule_active_injury(context: dict[str, Any]) -> list[dict[str, Any]]:
    active = [
        item for item in (context.get("injuries") or [])
        if bool(item.get("is_active", True))
    ]
    if not active:
        return []

    highest = max(active, key=lambda item: _number(item.get("severity")))
    severity = int(_number(highest.get("severity")))
    area = _label(highest.get("area"))
    other_count = len(active) - 1
    suffix = f" Ayrıca {other_count} aktif kayıt daha var." if other_count else ""
    if severity >= 4:
        message = (
            f"{area} için yüksek şiddetli aktif kısıt kaydı var.{suffix} "
            "Bu alanı belirgin biçimde zorlayan hareketleri seçmeden önce uzman görüşü alın."
        )
        action = "Bu bölgeyi zorlayan hareketleri plan taslağında korumaya al; seansı değiştirmeden önce kullanıcı onayı iste."
        tone = "danger"
        priority = 100
    else:
        message = f"{area} için aktif kısıt kaydı var.{suffix} Hareket seçimi ve yük artışı dikkatle değerlendirilmelidir."
        action = "İlgili hareket desenlerini Split taslağında korumalı göster; otomatik yük artışı önerme."
        tone = "warn"
        priority = 92
    return [_finding("active-injury-protection", priority, "Kısıt", "Aktif kısıt önceliği", message, action, tone)]


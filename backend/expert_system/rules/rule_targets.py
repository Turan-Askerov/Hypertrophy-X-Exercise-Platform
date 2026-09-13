from typing import Any
from expert_system.rule_utils import _number, _label, _finding, format_tr_date

def rule_targets(context: dict[str, Any]) -> list[dict[str, Any]]:
    target_info = context.get("targets") or {}
    targets = target_info.get("priority_muscles") or []
    primary_goal = str(target_info.get("primary_goal") or "").lower()

    if not targets:
        if primary_goal in ("fat_loss", "maintenance"):
            goal_label = "Yağ Kaybı / Definasyon" if primary_goal == "fat_loss" else "Durum Koruma / Rekompozisyon"
            return [_finding(
                "targets-balanced", 15, "Hedef", f"Dengeli Tüm Vücut Odak ({goal_label})",
                f"{goal_label} hedefinde öncelikli kas seçimi isteğe bağlıdır; tüm kas grupları dengeli koruma hacmiyle çalıştırılır.",
                "İsterseniz zayıf bir bölgeyi öne çıkarmak için Kurulum > Hedefler sekmesinden 1 ila 3 kas belirleyebilirsiniz.", "good",
            )]
        return [_finding(
            "targets-missing", 32, "Hedef", "Öncelikli kas seçimi bekleniyor",
            "Kas kazanımı splitinin kişiselleşmesi için en az bir öncelikli kas grubu seçilmelidir.",
            "Kurulum > Hedefler sekmesinden 1 ila 3 öncelikli kas seç.", "info",
        )]
    labels = ", ".join(_label(item) for item in targets[:3])
    return [_finding(
        "targets-available", 20, "Hedef", "Öncelikli kaslar tanımlı",
        f"Mevcut öncelik: {labels}. Koruma ve toparlanma kuralları izin verdiğinde Split odağı bu kaslara yönelir.",
        "Kural çakışması yoksa bir sonraki taslakta bu kasları ana odak olarak kullan.", "good",
    )]


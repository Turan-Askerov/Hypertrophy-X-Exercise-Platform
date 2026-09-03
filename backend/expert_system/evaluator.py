from typing import Any
from datetime import date
from expert_system.rule_utils import _finding, _label, _number
from expert_system.rules.rule_active_injury import rule_active_injury
from expert_system.rules.rule_doms_recovery import rule_doms_recovery
from expert_system.rules.rule_rpe_effort import rule_rpe_effort
from expert_system.rules.rule_equipment import rule_equipment
from expert_system.rules.rule_targets import rule_targets

Rule = Any
# priority büyüdükçe koordinatörün kararında daha önce gösterilir.
RULES: list[Rule] = [
    rule_active_injury,
    rule_doms_recovery,
    rule_equipment,
    rule_rpe_effort,
    rule_targets,
]


def evaluate_expert_rules(context: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for rule in RULES:
        try:
            produced = rule(context)
            if isinstance(produced, list):
                findings.extend(item for item in produced if isinstance(item, dict))
        except Exception:  # Bir hatalı yeni kural tüm uzman ekranını kapatmasın.
            findings.append(_finding(
                f"{getattr(rule, '__name__', 'rule')}-error", 1, "Sistem",
                "Kural çalıştırılamadı", "Bir kural bu değerlendirmede atlandı.",
                "Kural modülünü gözden geçir.", "info",
            ))

    findings.sort(key=lambda item: (-int(item.get("priority", 0)), str(item.get("id", ""))))
    highest = findings[0] if findings else None
    protection = any(item.get("priority", 0) >= 92 for item in findings)
    recovery = any(70 <= item.get("priority", 0) < 92 for item in findings)

    if protection:
        status = {
            "key": "protection",
            "title": "Koruma öncelikli",
            "message": "Aktif kısıt kaydı, performans veya hacim önerilerinden önce değerlendirilir.",
            "tone": "danger",
        }
    elif recovery:
        status = {
            "key": "adjust",
            "title": "Kontrollü seans önerisi",
            "message": "Toparlanma veya set bazlı RPE özeti nedeniyle yük artışı yerine kontrollü seçenekler öne çıkar.",
            "tone": "warn",
        }
    elif findings:
        status = {
            "key": "ready",
            "title": "Veriye göre planlanabilir",
            "message": "Mevcut bildirimlerde koruma gerektiren yüksek öncelikli bir durum görünmüyor.",
            "tone": "good",
        }
    else:
        status = {
            "key": "waiting",
            "title": "Veri bekleniyor",
            "message": "Daha anlamlı bir öneri için hedef, DOMS veya set bazlı RPE özetinden en az biri gerekir.",
            "tone": "info",
        }

    targets = (context.get("targets") or {}).get("priority_muscles") or []
    if protection:
        split_guidance = "Aktif kısıt varken Split yalnızca taslak olarak gösterilir; otomatik program değişikliği yapılmaz."
    elif recovery:
        split_guidance = "Yüksek öncelikli hedef kaslar korunur, ancak bildirilen DOMS/RPE durumuna göre doğrudan set artışı önerilmez."
    elif targets:
        split_guidance = "Koruma kuralı oluşmadıkça bir sonraki Split taslağında öncelikli kaslara daha görünür yer verilebilir."
    else:
        split_guidance = "Önce hedef kas seçimi yapıldığında Split odağı kişiselleştirilebilir."

    target_labels = context.get("target_muscle_labels") or [str(item) for item in targets]
    high_doms = [
        _label(item.get("muscle_label") or item.get("muscle_group"))
        for item in (context.get("doms_metrics") or [])
        if _number(item.get("pain_level")) >= 4
    ]
    active_areas = [
        _label(item.get("area")) for item in (context.get("injuries") or [])
        if bool(item.get("is_active", True))
    ]
    recent_rir = context.get("recent_rir") or {}
    rir_exercises = [_label(item) for item in (recent_rir.get("exercise_names") or [])]
    if protection:
        split_plan = {
            "title": "Koruma öncelikli split",
            "summary": "Aktif kısıt varken hedef kas odağından önce koruma yaklaşımı uygulanır.",
            "focus": target_labels,
            "monitor": sorted(set(active_areas + high_doms)),
            "approach": "Program otomatik değiştirilmez. Kısıtlı bölgeyi zorlayan hareketler için kullanıcı onaylı, kontrollü alternatif taslak gerekir.",
        }
    elif recovery:
        split_plan = {
            "title": "Kontrollü split",
            "summary": "Toparlanma verileri doğrudan set veya yük artışından önce değerlendirilir.",
            "focus": target_labels,
            "monitor": sorted(set(high_doms + rir_exercises)),
            "approach": "Hedef kasları tamamen silmeden, yüksek DOMS veya RPE 9–10 aralığındaki hareketlerde kontrollü seans seçeneğini öne çıkar.",
        }
    else:
        rpe_summary = context.get("rpe_summary") or {}
        rpe_note = ""
        if rpe_summary:
            rpe_note = f" Son türetilmiş ortalama RPE {rpe_summary.get('average_rpe', '—')}."
        split_plan = {
            "title": "Hedef odaklı split taslağı",
            "summary": "Kısıt veya yüksek toparlanma uyarısı görünmediği için hedef kaslar bir sonraki taslakta öne çıkarılabilir." + rpe_note,
            "focus": target_labels,
            "monitor": [],
            "approach": "Mevcut program korunur. Kullanıcı onayı olmadan hareket, set veya yük değiştirilmez.",
        }

    return {
        "generated_on": date.today().isoformat(),
        "status": status,
        "findings": findings,
        "highest_priority": highest,
        "split_guidance": split_guidance,
        "split_plan": split_plan,
        "rpe_summary": context.get("rpe_summary") or None,
        "rule_order": ["Kısıt", "Toparlanma", "Ekipman", "RPE", "Hedef"],
        "disclaimer": "Bu ekran antrenman planlama desteği sunar; tıbbi tanı veya tedavi önerisi değildir. Keskin, artan veya günlük yaşamı etkileyen ağrıda sağlık uzmanına başvurun.",
    }


__all__ = ["RULES", "evaluate_expert_rules"]
"""Hypertrophy-X modüler uzman kural motoru.

Bu modül yalnızca okunabilir bağlam verisinden bulgu üretir. Veritabanına yazmaz,
programı otomatik değiştirmez ve tıbbi tanı koymaz. Yeni bir kural eklemek için
aynı sözleşmeye uyan bir fonksiyon yazıp RULES listesine eklemek yeterlidir.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

from expert_recommendation import format_tr_date


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


def rule_rpe_effort(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Kullanıcının RIR kaydından türetilen set bazlı RPE çabasını yorumlar."""
    summary = context.get("rpe_summary") or {}
    if not summary:
        return [_finding(
            "rpe-missing", 35, "RPE", "Set bazlı RPE özeti yok",
            "Antrenman kaydındaki set verileriyle RPE özeti otomatik hesaplanır.",
            "Yeni antrenman kaydında setlerini tamamla; eski kayıtlar olduğu gibi korunur.", "info",
        )]
    average = _number(summary.get("average_rpe"))
    highest = int(_number(summary.get("highest_rpe")))
    count = int(_number(summary.get("set_count")))
    date_label = _label(summary.get("workout_date_display") or format_tr_date(summary.get("workout_date")))
    high_effort = int(_number(summary.get("high_effort_sets")))
    if highest >= 10 or average >= 9:
        return [_finding(
            "rpe-near-limit", 72, "RPE", "Son antrenmanda set çabası çok yüksekti",
            f"{date_label} tarihli antrenmanda {count} setin türetilmiş ortalama RPE değeri {average:g}; en yüksek RPE {highest}. RPE 9–10 aralığında {high_effort} set var.",
            "Bir sonraki benzer kas grubunda yük/hacim artışını seçenek olarak değil, kontrollü sabit çalışma olarak göster.", "warn",
        )]
    if average >= 8:
        return [_finding(
            "rpe-high-effort", 48, "RPE", "Son antrenman yüksek çabadaydı",
            f"{date_label} tarihli {count} setin türetilmiş ortalama RPE değeri {average:g}. DOMS ve kısıt verileri izin vermeden ek zorluk önerme.",
            "Mevcut yükü koru; Split odağını toparlanma sinyalleriyle birlikte değerlendir.", "info",
        )]
    if average >= 7:
        return [_finding(
            "rpe-productive", 42, "RPE", "Son antrenman kontrollü çabadaydı",
            f"{date_label} tarihli {count} setin türetilmiş ortalama RPE değeri {average:g}. Teknik ve toparlanma uygunsa mevcut düzen sürdürülebilir görünüyor.",
            "Kısıt ve DOMS kuralı yoksa hedef kas odağını koru; otomatik artış yapma.", "good",
        )]
    return [_finding(
        "rpe-reserve-high", 38, "RPE", "Son antrenmanda çaba rezervi yüksekti",
        f"{date_label} tarihli {count} setin türetilmiş ortalama RPE değeri {average:g}. Kullanıcı bunu kasıtlı kontrollü çalıştıysa mevcut yaklaşım geçerlidir.",
        "Bir sonraki seans için teknik ve hedefe göre küçük ilerleme seçeneğini kullanıcıya sun; otomatik uygulama yapma.", "info",
    )]


def rule_equipment(context: dict[str, Any]) -> list[dict[str, Any]]:
    equipment = context.get("equipment") or []
    if equipment:
        return []
    return [_finding(
        "equipment-missing", 65, "Ekipman", "Salon ekipmanı belirtilmemiş",
        "Hareket önerilerinin uygulanabilir olması için en az bir salonun ekipmanını kaydetmek gerekir.",
        "Kurulum > Salonlar sekmesinden erişebildiğin ekipmanı kaydet.", "warn",
    )]


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


# Kural ekleme noktası: Her yeni kural yalnızca context alır ve bulgu listesi döndürür.
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
        except Exception as exc:  # Bir hatalı yeni kural tüm uzman ekranını kapatmasın.
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

from typing import Any
from expert_system.rule_utils import _number, _label, _finding, format_tr_date

from expert_system.recommendation import format_tr_date

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


"""Hypertrophy-X kural tabanlı fuzzy uzman sistemi.

Bu modül üretken yapay zekâ veya dış API kullanmaz. Kararlar, görünür olgular
(profile, antrenman geçmişi, seans kontrolü ve DOMS kayıtları) ile açık kurallardan
üretilir. Fuzzy üyelikler 0.0–1.0 aralığındadır; kullanıcıya sonuçla birlikte
hangi kuralların etkinleştiği de döndürülür.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

UI_MUSCLE_GROUPS = (
    "Göğüs", "Sırt", "Omuz", "Biceps", "Triceps", "Bacak", "Core",
)

PRIMARY_GOALS = {
    "hypertrophy": "Kas kazanımı",
    "strength": "Güç kazanımı",
    "fat_loss": "Yağ kaybı ve kas korunumu",
}

ENGLISH_TO_UI_MUSCLE = {
    "Chest": "Göğüs",
    "Back": "Sırt",
    "Shoulders": "Omuz",
    "Biceps": "Biceps",
    "Triceps": "Triceps",
    "Legs": "Bacak",
    "Core": "Core",
    "Traps": "Sırt",
}


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def rising(value: float, start: float, end: float) -> float:
    """start'ta 0, end'de 1 olan doğrusal fuzzy üyelik."""
    if end <= start:
        return 1.0 if value >= end else 0.0
    return _clamp((float(value) - start) / (end - start))


def falling(value: float, start: float, end: float) -> float:
    """start'ta 1, end'de 0 olan doğrusal fuzzy üyelik."""
    if end <= start:
        return 1.0 if value <= start else 0.0
    return _clamp((end - float(value)) / (end - start))


def normalize_muscle_group(value: object) -> str | None:
    raw = str(value or "").strip()
    if raw in UI_MUSCLE_GROUPS:
        return raw
    return ENGLISH_TO_UI_MUSCLE.get(raw)


def missing_profile_fields(profile: dict[str, Any]) -> list[str]:
    """Profil tamamlandı mı sorusunu varsayılan değerleri de dikkate alarak yanıtlar.

    Kullanıcı tablosu bazı alanlara varsayılan değer verdiği için yalnızca değer
    varlığı yeterli değildir. Yaşın 0 olması profilin henüz kaydedilmediğinin
    güvenilir işaretidir; diğer alanlar makul aralıklarla kontrol edilir.
    """
    missing: list[str] = []
    age = profile.get("age") or 0
    height = profile.get("height") or 0
    weight = profile.get("weight") or 0
    days = profile.get("days_per_week") or 0
    session_time = profile.get("session_time_mins") or 0
    level = str(profile.get("fitness_level") or "").strip()
    goal = str(profile.get("goal") or "").strip()

    if not 13 <= float(age) <= 100:
        missing.append("age")
    if not 120 <= float(height) <= 250:
        missing.append("height")
    if not 30 <= float(weight) <= 350:
        missing.append("weight")
    if not level:
        missing.append("fitness_level")
    if not goal:
        missing.append("goal")
    if not 1 <= int(days) <= 7:
        missing.append("days_per_week")
    if not 20 <= int(session_time) <= 300:
        missing.append("session_time_mins")
    return missing


def eligibility(profile: dict[str, Any], workout_count: int) -> dict[str, Any]:
    missing = missing_profile_fields(profile)
    if missing:
        return {
            "ready": False,
            "reason": "profile_incomplete",
            "missing_fields": missing,
            "message": "Uzman sistemini açmak için Profil sayfasındaki bilgileri tamamlayın.",
        }
    if workout_count < 1:
        return {
            "ready": False,
            "reason": "workout_required",
            "missing_fields": [],
            "message": "Uzman sisteminin sizi tanıması için önce en az bir antrenman kaydı ekleyin.",
        }
    return {
        "ready": True,
        "reason": "ready",
        "missing_fields": [],
        "message": "Uzman sistemi kullanıma hazır.",
    }


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _latest_active_doms_by_muscle(active_doms: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in active_doms or []:
        group = normalize_muscle_group(item.get("muscle_group"))
        if not group:
            continue
        if str(item.get("status", "active")) != "active":
            continue
        previous = latest.get(group)
        if not previous or str(item.get("last_report_date", "")) >= str(previous.get("last_report_date", "")):
            clone = dict(item)
            clone["muscle_group"] = group
            latest[group] = clone
    return latest


def _workout_muscle_sets(workouts: Iterable[dict[str, Any]], limit: int = 8) -> dict[str, int]:
    """Son antrenmanlardaki doğrudan set sayısını geniş kullanıcı gruplarında toplar."""
    totals = {group: 0 for group in UI_MUSCLE_GROUPS}
    for workout in list(workouts or [])[:limit]:
        for exercise in workout.get("exercises", []) or []:
            group = normalize_muscle_group(exercise.get("muscle_group"))
            if not group:
                # Yeni API yanıtlarında görünür grup listesi bulunabilir.
                display = exercise.get("display_muscle_groups") or []
                group = normalize_muscle_group(display[0]) if display else None
            if not group:
                continue
            sets = exercise.get("sets_data") or []
            totals[group] += len(sets)
    return totals


def _profile_volume_range(profile: dict[str, Any], primary_goal: str) -> tuple[int, int]:
    level = str(profile.get("fitness_level") or "Beginner").lower()
    if "advanced" in level or "ileri" in level:
        low, high = 12, 18
    elif "intermediate" in level or "orta" in level:
        low, high = 10, 16
    else:
        low, high = 8, 12
    if primary_goal == "strength":
        low, high = max(6, low - 2), max(10, high - 2)
    elif primary_goal == "fat_loss":
        low, high = max(6, low - 1), max(10, high - 2)
    return low, high


def build_program_focus(profile: dict[str, Any], preferences: dict[str, Any], workouts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    primary_goal = str(preferences.get("primary_goal") or "hypertrophy")
    if primary_goal not in PRIMARY_GOALS:
        primary_goal = "hypertrophy"
    priorities = []
    for group in preferences.get("priority_muscles") or []:
        normalized = normalize_muscle_group(group)
        if normalized and normalized not in priorities:
            priorities.append(normalized)
    priorities = priorities[:3]
    weekly_sets = _workout_muscle_sets(workouts)
    lower, upper = _profile_volume_range(profile, primary_goal)
    focus = []
    for group in priorities:
        current = weekly_sets.get(group, 0)
        if current < lower:
            action = "artır"
            text = f"{group} için doğrudan set sayısı son kayıtlarda düşük görünüyor; toparlanma uygunsa kademeli artış değerlendirilebilir."
        elif current > upper:
            action = "koru_veya_azalt"
            text = f"{group} için son kayıtlardaki doğrudan set sayısı üst sınıra yakın; toparlanma verisini izleyerek hacmi koruyun veya azaltın."
        else:
            action = "koru"
            text = f"{group} için son kayıtlardaki doğrudan set sayısı hedef aralıkta görünüyor."
        focus.append({
            "muscle_group": group,
            "recent_direct_sets": current,
            "recommended_weekly_sets": {"min": lower, "max": upper},
            "action": action,
            "message": text,
        })
    goal_message = {
        "hypertrophy": "Öncelik, kaliteli setleri toparlanabilecek hacimle sürdürmek ve progresif yüklemeyi izlemektir.",
        "strength": "Öncelik, ana hareketlerde teknik kaliteyi koruyarak yük veya tekrar performansını kademeli geliştirmektir.",
        "fat_loss": "Öncelik, kas kütlesini korurken sürdürülebilir antrenman kalitesini ve toparlanmayı muhafaza etmektir.",
    }[primary_goal]
    return {
        "primary_goal": primary_goal,
        "primary_goal_label": PRIMARY_GOALS[primary_goal],
        "priority_muscles": priorities,
        "weekly_focus": focus,
        "message": goal_message,
    }


def evaluate_recovery(latest_checkin: dict[str, Any] | None, active_doms: Iterable[dict[str, Any]], preferences: dict[str, Any]) -> dict[str, Any]:
    """Fuzzy üyelikleri açık kurallara dönüştürür.

    Skor, tıbbi teşhis veya sakatlık değerlendirmesi değildir. Sadece kullanıcının
    kendi bildirdiği antrenman algısı ve DOMS eğilimine göre sonraki antrenman
    hacmi hakkında temkinli bir antrenman planlama önerisi üretir.
    """
    checkin = latest_checkin or {}
    rpe = _float(checkin.get("session_rpe"), 0.0)
    fatigue = _float(checkin.get("day_fatigue"), 0.0)
    recovery_feeling = _float(checkin.get("recovery_feeling"), 5.0)
    completion = _float(checkin.get("completion_percentage"), 100.0)

    rpe_high = rising(rpe, 7.0, 9.5)
    fatigue_high = rising(fatigue, 5.0, 9.0)
    recovery_low = falling(recovery_feeling, 2.5, 6.5)
    completion_low = falling(completion, 70.0, 95.0)

    doms_by_muscle = _latest_active_doms_by_muscle(active_doms)
    doms_memberships: dict[str, float] = {}
    for group, case in doms_by_muscle.items():
        severity = _float(case.get("last_severity"), 0.0)
        doms_memberships[group] = rising(severity, 3.0, 8.0)
    max_doms = max(doms_memberships.values(), default=0.0)

    # Fuzzy ağırlıklı toplam: her değişken 0–1, skor 0–100 aralığına taşınır.
    strain = _clamp(
        0.26 * rpe_high
        + 0.24 * fatigue_high
        + 0.28 * recovery_low
        + 0.12 * completion_low
        + 0.10 * max_doms
    )
    recovery_score = round((1.0 - strain) * 100)

    priority_groups = []
    for group in preferences.get("priority_muscles") or []:
        normalized = normalize_muscle_group(group)
        if normalized and normalized not in priority_groups:
            priority_groups.append(normalized)

    rule_trace: list[dict[str, str]] = []
    protected_muscles: list[str] = []
    for group in doms_memberships:
        severity = _float(doms_by_muscle[group].get("last_severity"), 0.0)
        if severity >= 7:
            protected_muscles.append(group)
            rule_trace.append({
                "rule": "DOMS-Yüksek",
                "detail": f"{group} için DOMS {severity:.0f}/10; bu kası doğrudan ağır yüklemek yerine dinlenme ve yeniden değerlendirme önerilir.",
            })
        elif severity >= 4:
            protected_muscles.append(group)
            rule_trace.append({
                "rule": "DOMS-Orta",
                "detail": f"{group} için DOMS {severity:.0f}/10; sonraki doğrudan set hacmi azaltılmalı veya ertelenmelidir.",
            })

    if rpe_high >= 0.5:
        rule_trace.append({"rule": "Seans-Zorluğu", "detail": f"Son seans RPE {rpe:.1f}/10 olarak girildi; yüksek algılanan efor toparlanma ihtiyacını artırır."})
    if fatigue_high >= 0.5:
        rule_trace.append({"rule": "Günlük-Yorgunluk", "detail": f"Gün içi yorgunluk {fatigue:.1f}/10; genel antrenman yükü temkinli yönetilmelidir."})
    if recovery_low >= 0.5:
        rule_trace.append({"rule": "Toparlanma-Hissi", "detail": f"Toparlanmış hissetme {recovery_feeling:.1f}/10; sonraki seans öncesi yük artışı önerilmez."})
    if completion_low >= 0.5:
        rule_trace.append({"rule": "Set-Tamamlama", "detail": f"Planlanan setlerin tamamlanma oranı %{completion:.0f}; kapasite veya toparlanma sınırına işaret edebilir."})

    if not checkin:
        decision = "veri_bekleniyor"
        title = "Toparlanma verisi bekleniyor"
        message = "İlk değerlendirme için Son Seansı Değerlendir veya Günlük Toparlanma Kontrolü anketini isteğe bağlı doldurun."
    elif recovery_score < 45 or (max_doms >= 0.70 and protected_muscles):
        decision = "dinlen_veya_ertele"
        title = "Toparlanma önceliği"
        message = "Genel yük veya aktif DOMS yüksek görünüyor. Etkilenen kasları doğrudan yükleyen seansı ertelemeyi; gerekiyorsa daha hafif bir kas grubuna geçmeyi değerlendirin."
    elif recovery_score < 70 or protected_muscles:
        decision = "hacmi_azalt"
        title = "Kontrollü antrenman"
        message = "Antrenman yapılabilir görünüyor; ancak etkilenen kaslarda doğrudan set hacmini azaltın, failure'a yaklaşmayın ve sonraki günlük kontrolde DOMS eğilimini yeniden girin."
    elif recovery_score >= 85:
        decision = "normal_ilerleme"
        title = "Normal ilerleme için uygun görünüm"
        message = "Bildirdiğiniz toparlanma verileri normal planlanan seans için uygun görünüyor. Yük veya tekrar artışını yalnızca teknik kalite korunuyorsa küçük adımlarla uygulayın."
    else:
        decision = "normal_hacmi_koru"
        title = "Planı koru"
        message = "Bildirdiğiniz veriler normal hacmi korumaya uygun görünüyor. Gereksiz hacim artışı yerine performans ve teknik kaliteyi izleyin."

    # Öncelikli kaslara ait DOMS aktifse kullanıcıya özellikle görünür kıl.
    priority_protection = [group for group in protected_muscles if group in priority_groups]
    if priority_protection:
        rule_trace.append({
            "rule": "Öncelikli-Kas-Koruması",
            "detail": f"Öncelikli kaslarınızdan {', '.join(priority_protection)} hâlâ toparlanıyor; öncelik hedefi kısa vadede ek hacim gerekçesi değildir.",
        })

    return {
        "recovery_score": recovery_score,
        "decision": decision,
        "title": title,
        "message": message,
        "protected_muscles": protected_muscles,
        "active_doms": [
            {
                "muscle_group": group,
                "severity": round(_float(case.get("last_severity"), 0.0), 1),
                "started_on": case.get("started_on"),
                "last_report_date": case.get("last_report_date"),
            }
            for group, case in doms_by_muscle.items()
        ],
        "fuzzy_memberships": {
            "high_rpe": round(rpe_high, 2),
            "high_fatigue": round(fatigue_high, 2),
            "low_recovery_feeling": round(recovery_low, 2),
            "low_set_completion": round(completion_low, 2),
            "high_doms": round(max_doms, 2),
        },
        "rule_trace": rule_trace or [{
            "rule": "Veri-Dengesi",
            "detail": "Aktif yüksek DOMS veya belirgin toparlanma uyarısı bildirilmedi.",
        }],
        "disclaimer": "Bu değerlendirme tanı koymaz. Keskin/alışılmadık ağrı, şişlik, uyuşma veya günlük yaşamı etkileyen belirti varsa antrenmanı bırakıp uygun bir sağlık uzmanına başvurun.",
    }


def build_expert_result(
    profile: dict[str, Any],
    preferences: dict[str, Any],
    workouts: Iterable[dict[str, Any]],
    latest_checkin: dict[str, Any] | None,
    active_doms: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "program_focus": build_program_focus(profile, preferences, workouts),
        "recovery": evaluate_recovery(latest_checkin, active_doms, preferences),
    }


@dataclass(frozen=True)
class ExpertPreferenceInput:
    primary_goal: str
    priority_muscles: list[str]


def validate_preferences(primary_goal: str, priority_muscles: Iterable[object]) -> ExpertPreferenceInput:
    goal = str(primary_goal or "").strip().lower()
    if goal not in PRIMARY_GOALS:
        raise ValueError("Geçerli bir ana hedef seçin.")
    muscles: list[str] = []
    for item in priority_muscles or []:
        group = normalize_muscle_group(item)
        if not group:
            raise ValueError("Geçersiz kas grubu seçildi.")
        if group not in muscles:
            muscles.append(group)
    if not 1 <= len(muscles) <= 3:
        raise ValueError("En az 1, en fazla 3 öncelikli kas grubu seçin.")
    return ExpertPreferenceInput(primary_goal=goal, priority_muscles=muscles)


def validate_score(value: float | None, label: str, minimum: float = 0.0, maximum: float = 10.0, required: bool = False) -> float | None:
    if value is None:
        if required:
            raise ValueError(f"{label} zorunludur.")
        return None
    score = _float(value, -1)
    if not minimum <= score <= maximum:
        raise ValueError(f"{label} {minimum:g} ile {maximum:g} arasında olmalıdır.")
    return round(score, 1)


# ═══════════════════════════════════════════════════════════════════════════
# UZMAN SİSTEMİ V2 — DİNAMİK PROGRAM KURAL MOTORU
# ═══════════════════════════════════════════════════════════════════════════
# V2, V1'in sonuç sözleşmesini değiştirmez. Aşağıdaki fonksiyonlar API katmanı
# tarafından isteğe bağlı çağrılır; böylece V1 kullanan eski istemciler çalışmaya
# devam eder. Egzersiz seçimi hareket havuzundaki görünür isim yerine yalnızca
# `analysis` meta verisiyle yapılır.

from datetime import date as _date
from datetime import datetime as _datetime
import copy as _copy

AVAILABLE_EQUIPMENT_OPTIONS = (
    {"id": "barbell", "label": "Barbell / olimpik bar"},
    {"id": "dumbbell", "label": "Dumbbell"},
    {"id": "flat_bench", "label": "Düz bench"},
    {"id": "adjustable_bench", "label": "Ayarlanabilir bench"},
    {"id": "cable_machine", "label": "Kablo istasyonu"},
    {"id": "cable_row_machine", "label": "Seated row makinesi"},
    {"id": "lat_pulldown_machine", "label": "Lat pulldown makinesi"},
    {"id": "pull_up_bar", "label": "Barfiks barı"},
    {"id": "chest_press_machine", "label": "Chest press makinesi"},
    {"id": "shoulder_press_machine", "label": "Shoulder press makinesi"},
    {"id": "leg_press_machine", "label": "Leg press makinesi"},
    {"id": "leg_extension_machine", "label": "Leg extension makinesi"},
    {"id": "leg_curl_machine", "label": "Leg curl makinesi"},
    {"id": "hack_squat_machine", "label": "Hack squat makinesi"},
    {"id": "smith_machine", "label": "Smith machine"},
    {"id": "reverse_pec_deck", "label": "Reverse pec deck"},
    {"id": "ez_bar", "label": "EZ bar"},
    {"id": "dip_station", "label": "Dip istasyonu"},
    {"id": "resistance_band", "label": "Direnç bandı"},
    {"id": "bodyweight", "label": "Vücut ağırlığı"},
)

# Veri toplama ekranı, V2 program motorunun ayrıntılı ekipman listesinden ayrı
# olarak salon bazlı sade bir var/yok kataloğu kullanır. Kapasite, kilogram veya
# çift/tek dumbbell gibi kullanıcıyı yoran detaylar özellikle tutulmaz.
GYM_EQUIPMENT_CATALOG = (
    # Sehpalar
    {"id": "flat_bench", "label": "Flat Bench", "group": "Sehpalar"},
    {"id": "incline_bench", "label": "İncline Bench", "group": "Sehpalar"},
    {"id": "decline_bench", "label": "Decline Bench", "group": "Sehpalar"},
    {"id": "adjustable_bench", "label": "Ayarlanabilir Bench", "group": "Sehpalar"},
    {"id": "preacher_curl_bench", "label": "Preacher Curl Bench", "group": "Sehpalar"},
    {"id": "hyperextension_machine", "label": "Hyperextension Machine", "group": "Sehpalar"},

    # Ağırlıklar
    {"id": "dumbbell", "label": "Dumbbell", "group": "Ağırlıklar"},
    {"id": "barbell", "label": "Barbell", "group": "Ağırlıklar"},
    {"id": "ez_bar", "label": "Z – Bar", "group": "Ağırlıklar"},
    {"id": "kettlebell", "label": "Kettlebell", "group": "Ağırlıklar"},
    {"id": "weight_plates", "label": "Ağırlık Plakaları", "group": "Ağırlıklar"},

    # Fitness makineleri ve istasyonlar
    {"id": "barbell_bench_press_station", "label": "Barbell Bench Press", "group": "Fitness Makineleri"},
    {"id": "incline_barbell_bench_press_station", "label": "İncline Barbell Bench Press", "group": "Fitness Makineleri"},
    {"id": "decline_barbell_bench_press_station", "label": "Decline Barbell Bench Press", "group": "Fitness Makineleri"},
    {"id": "pec_deck", "label": "Pec Deck Fly", "group": "Fitness Makineleri"},
    {"id": "cable_station", "label": "Cable Cross", "group": "Fitness Makineleri"},
    {"id": "smith_machine", "label": "Smith Machine", "group": "Fitness Makineleri"},
    {"id": "chest_press", "label": "Chest Press Machine", "group": "Fitness Makineleri"},
    {"id": "shoulder_press", "label": "Shoulder Press Machine", "group": "Fitness Makineleri"},
    {"id": "lat_pulldown", "label": "Lat Pulldown", "group": "Fitness Makineleri"},
    {"id": "seated_cable_row", "label": "Cable Row", "group": "Fitness Makineleri"},
    {"id": "low_row_machine", "label": "Low Row Machine", "group": "Fitness Makineleri"},
    {"id": "biceps_curl_machine", "label": "Biceps Curl Machine", "group": "Fitness Makineleri"},
    {"id": "triceps_press_machine", "label": "Triceps Press Makinesi", "group": "Fitness Makineleri"},
    {"id": "leg_press", "label": "Leg Press", "group": "Fitness Makineleri"},
    {"id": "hack_squat", "label": "Hack Squat", "group": "Fitness Makineleri"},
    {"id": "leg_extension", "label": "Leg Extension", "group": "Fitness Makineleri"},
    {"id": "seated_leg_curl", "label": "Seated Leg Curl", "group": "Fitness Makineleri"},
    {"id": "lying_leg_curl", "label": "Lying Leg Curl", "group": "Fitness Makineleri"},
    {"id": "adductor_machine", "label": "Adductor Machine", "group": "Fitness Makineleri"},
    {"id": "seated_calf_raise", "label": "Oturarak Calf Makinesi", "group": "Fitness Makineleri"},
    {"id": "assisted_pullup_dip", "label": "Assisted Pull-up / Dip", "group": "Fitness Makineleri"},

    # Standlar
    {"id": "squat_rack", "label": "Squat Rack – Squat Standı", "group": "Standlar"},
    {"id": "squat_stand", "label": "Squat Standı", "group": "Standlar"},
    {"id": "half_rack", "label": "Half Rack", "group": "Standlar"},
    {"id": "power_rack", "label": "Power Rack", "group": "Standlar"},
    {"id": "pullup_dip_station", "label": "Barfiks – Dips Standı", "group": "Standlar"},
    {"id": "pullup_bar", "label": "Pull-up Bar", "group": "Standlar"},
    {"id": "dip_bar", "label": "Dip Bar", "group": "Standlar"},

    # Kardiyo aletleri
    {"id": "treadmill", "label": "Koşu Bandı", "group": "Kardiyo Aletleri"},
    {"id": "elliptical_bike", "label": "Eliptik Bisiklet", "group": "Kardiyo Aletleri"},
    {"id": "recumbent_bike", "label": "Yatay Bisiklet", "group": "Kardiyo Aletleri"},
    {"id": "exercise_mat", "label": "Egzersiz Minderi (Yoga Matı)", "group": "Kardiyo Aletleri"},
    {"id": "cardio_area", "label": "Diğer Kardiyo Alanı", "group": "Kardiyo Aletleri"},
)

_GYM_EQUIPMENT_IDS = {item["id"] for item in GYM_EQUIPMENT_CATALOG}
_GYM_EQUIPMENT_ALIASES = {
    "cable_machine": "cable_station", "cable_cross": "cable_station",
    "lat_pulldown_machine": "lat_pulldown", "cable_row_machine": "seated_cable_row",
    "chest_press_machine": "chest_press", "shoulder_press_machine": "shoulder_press",
    "leg_press_machine": "leg_press", "hack_squat_machine": "hack_squat",
    "leg_extension_machine": "leg_extension", "leg_curl_machine": "seated_leg_curl",
    "calf_machine": "calf_raise", "seated_calf_machine": "seated_calf_raise",
    "pull_up_bar": "pullup_dip_station", "pullup_bar": "pullup_dip_station", "dip_station": "pullup_dip_station",
    "dip_bars": "pullup_dip_station",
    "barfiks_dips_standi": "pullup_dip_station", "barfiks_barı": "pullup_bar",
    "barfiks_bari": "pullup_bar", "squat_standi": "squat_stand",
    "bench_press": "barbell_bench_press_station", "incline_bench_press": "incline_barbell_bench_press_station",
    "decline_bench_press": "decline_barbell_bench_press_station",
    "low_row": "low_row_machine", "low_row_machine": "low_row_machine",
    "hip_adduction_machine": "adductor_machine", "adduction_machine": "adductor_machine",
    "hyperextension_bench": "hyperextension_machine", "back_extension_machine": "hyperextension_machine",
    "yoga_mat": "exercise_mat", "exercise_mat": "exercise_mat", "egzersiz_minderi": "exercise_mat",
}


def normalize_gym_equipment(value: object) -> str | None:
    """Salon ekipmanı kimliğini katalogdaki güvenli değere dönüştürür."""
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in _GYM_EQUIPMENT_IDS:
        return raw
    return _GYM_EQUIPMENT_ALIASES.get(raw)

# Kimlikler, havuzdaki analysis.primary_muscles / secondary_muscles değerleri
# ile eşleşir. `ui_group`, V1 DOMS kayıtları ile geriye dönük eşleştirme içindir.
DETAILED_MUSCLE_OPTIONS = (
    {"id": "chest", "label": "Göğüs", "ui_group": "Göğüs"},
    {"id": "lats", "label": "Latissimus (Kanat)", "ui_group": "Sırt"},
    {"id": "upper_back", "label": "Üst Sırt", "ui_group": "Sırt"},
    {"id": "traps", "label": "Trapez", "ui_group": "Sırt"},
    {"id": "spinal_erectors", "label": "Bel / Omurga Erektörleri", "ui_group": "Sırt"},
    {"id": "front_delts", "label": "Ön Omuz", "ui_group": "Omuz"},
    {"id": "side_delts", "label": "Yan Omuz", "ui_group": "Omuz"},
    {"id": "rear_delts", "label": "Arka Omuz", "ui_group": "Omuz"},
    {"id": "rotator_cuff", "label": "Rotator Cuff", "ui_group": "Omuz"},
    {"id": "biceps", "label": "Biceps", "ui_group": "Biceps"},
    {"id": "triceps", "label": "Triceps", "ui_group": "Triceps"},
    {"id": "quadriceps", "label": "Quadriceps", "ui_group": "Bacak"},
    {"id": "hamstrings", "label": "Hamstring", "ui_group": "Bacak"},
    {"id": "glutes", "label": "Gluteus", "ui_group": "Bacak"},
    {"id": "calves", "label": "Calf", "ui_group": "Bacak"},
    {"id": "adductors", "label": "Adductors", "ui_group": "Bacak"},
    {"id": "forearms", "label": "Bilek Kasları", "ui_group": "Bilek"},
    {"id": "core", "label": "Core", "ui_group": "Core"},
)

_DETAILED_BY_ID = {item["id"]: item for item in DETAILED_MUSCLE_OPTIONS}
_DETAILED_ALIASES = {
    "göğüs": "chest", "chest": "chest",
    "latissimus": "lats", "kanat": "lats", "lats": "lats",
    "üst sırt": "upper_back", "upper back": "upper_back", "upper_back": "upper_back",
    "trapez": "traps", "traps": "traps",
    "bel": "spinal_erectors", "spinal erectors": "spinal_erectors", "spinal_erectors": "spinal_erectors",
    "ön omuz": "front_delts", "front delts": "front_delts", "front_delts": "front_delts",
    "yan omuz": "side_delts", "side delts": "side_delts", "side_delts": "side_delts",
    "arka omuz": "rear_delts", "rear delts": "rear_delts", "rear_delts": "rear_delts",
    "rotator cuff": "rotator_cuff", "rotator_cuff": "rotator_cuff",
    "supraspinatus": "rotator_cuff", "subraspinatus": "rotator_cuff",
    "infraspinatus": "rotator_cuff", "teres minor": "rotator_cuff", "teres_minor": "rotator_cuff",
    "subscapularis": "rotator_cuff", "teres major": "rotator_cuff", "teres_major": "rotator_cuff",
    "biceps": "biceps", "triceps": "triceps",
    "quadriceps": "quadriceps", "quad": "quadriceps", "quadricepsler": "quadriceps",
    "hamstring": "hamstrings", "hamstrings": "hamstrings",
    "gluteus": "glutes", "glutes": "glutes", "kalça": "glutes",
    "calf": "calves", "calves": "calves", "baldır": "calves",
    "adductors": "adductors", "adductor": "adductors", "adduktor": "adductors", "adduktör": "adductors", "iç bacak": "adductors", "ic bacak": "adductors",
    "forearms": "forearms", "forearm": "forearms", "bilek": "forearms", "bilek kasları": "forearms", "ön kol": "forearms", "on kol": "forearms",
    "core": "core", "karın": "core",
}

_UI_TO_DETAILED = {
    "Göğüs": {"chest"},
    "Sırt": {"lats", "upper_back", "traps", "spinal_erectors", "rear_delts"},
    "Omuz": {"front_delts", "side_delts", "rear_delts", "rotator_cuff"},
    "Biceps": {"biceps"},
    "Triceps": {"triceps"},
    "Bacak": {"quadriceps", "hamstrings", "glutes", "calves", "adductors"},
    "Core": {"core"},
}

# Kullanıcı odağının split puanına etki etmesi için her seansın ayrıntılı
# kas kapsaması tanımlıdır. Bu liste, görünür antrenman kaydı akışını etkilemez.
_SPLIT_LIBRARY = {
    2: (
        {
            "id": "full_body_2", "name": "Full Body A/B", "description": "İki gün için her ana kas grubuna dengeli frekans sağlar.",
            "sessions": (("Full Body A", ("chest", "upper_back", "quadriceps", "side_delts", "biceps")), ("Full Body B", ("lats", "hamstrings", "glutes", "front_delts", "triceps", "core"))),
        },
        {
            "id": "upper_lower_2", "name": "Upper / Lower", "description": "Daha uzun iki seans için üst ve alt vücudu ayırır.",
            "sessions": (("Upper", ("chest", "lats", "upper_back", "front_delts", "side_delts", "biceps", "triceps")), ("Lower", ("quadriceps", "hamstrings", "glutes", "calves", "core"))),
        },
    ),
    3: (
        {
            "id": "full_body_3", "name": "Full Body 3 Gün", "description": "Kas kazanımı için düşük gün sayısında frekansı korur.",
            "sessions": (("Full Body A", ("chest", "upper_back", "quadriceps", "side_delts")), ("Full Body B", ("lats", "hamstrings", "glutes", "biceps", "triceps")), ("Full Body C", ("chest", "upper_back", "quadriceps", "rear_delts", "core"))),
        },
        {
            "id": "ppl_3", "name": "Push / Pull / Legs", "description": "Hareket kalitesi ve tek seans odağı için üç günlük klasik ayrım.",
            "sessions": (("Push", ("chest", "front_delts", "side_delts", "triceps")), ("Pull", ("lats", "upper_back", "rear_delts", "biceps", "traps")), ("Legs", ("quadriceps", "hamstrings", "glutes", "calves", "core"))),
        },
    ),
    4: (
        {
            "id": "upper_lower_4", "name": "Upper / Lower x2", "description": "Dört günde dengeli iki kez uyarım sağlar.",
            "sessions": (("Upper A", ("chest", "lats", "upper_back", "front_delts", "triceps")), ("Lower A", ("quadriceps", "hamstrings", "glutes", "calves")), ("Upper B", ("chest", "upper_back", "rear_delts", "side_delts", "biceps")), ("Lower B", ("quadriceps", "hamstrings", "glutes", "core"))),
        },
        {
            "id": "ppl_upper_4", "name": "PPL + Upper", "description": "Üst vücut veya omuz-kol önceliğinde ek üst seans verir.",
            "sessions": (("Push", ("chest", "front_delts", "side_delts", "triceps")), ("Pull", ("lats", "upper_back", "rear_delts", "biceps")), ("Legs", ("quadriceps", "hamstrings", "glutes", "calves")), ("Upper Priority", ("chest", "lats", "upper_back", "side_delts", "rear_delts", "biceps", "triceps"))),
        },
    ),
    5: (
        {
            "id": "upper_priority_ppl_5", "name": "Üst Vücut Öncelikli PPL 5", "description": "Push ve pull iki kez, bacak bir kez çalışır; üst vücut önceliği için tasarlanmıştır.",
            "sessions": (("Push A", ("chest", "front_delts", "side_delts", "triceps")), ("Pull A", ("lats", "upper_back", "rear_delts", "biceps")), ("Legs", ("quadriceps", "hamstrings", "glutes", "calves", "core")), ("Push B", ("chest", "side_delts", "triceps")), ("Pull B", ("lats", "upper_back", "rear_delts", "biceps", "traps"))),
        },
        {
            "id": "upper_lower_plus_5", "name": "Upper / Lower + Upper", "description": "Dengeli üst-alt tabanı, üçüncü üst seansla birleştirir.",
            "sessions": (("Upper A", ("chest", "lats", "front_delts", "triceps")), ("Lower A", ("quadriceps", "hamstrings", "glutes", "calves")), ("Upper B", ("upper_back", "rear_delts", "side_delts", "biceps")), ("Lower B", ("quadriceps", "hamstrings", "glutes", "core")), ("Upper Priority", ("chest", "lats", "side_delts", "rear_delts", "biceps", "triceps"))),
        },
        {
            "id": "balanced_ppl_ul_5", "name": "PPL + Upper / Lower", "description": "Haftalık hacmi üst ve alt vücuda daha dengeli dağıtır.",
            "sessions": (("Push", ("chest", "front_delts", "side_delts", "triceps")), ("Pull", ("lats", "upper_back", "rear_delts", "biceps")), ("Legs", ("quadriceps", "hamstrings", "glutes", "calves")), ("Upper", ("chest", "lats", "upper_back", "side_delts", "biceps", "triceps")), ("Lower", ("quadriceps", "hamstrings", "glutes", "core"))),
        },
    ),
    6: (
        {
            "id": "ppl_6", "name": "Push / Pull / Legs x2", "description": "Altı günde tüm ana kasları haftada iki kez uyarır.",
            "sessions": (("Push A", ("chest", "front_delts", "side_delts", "triceps")), ("Pull A", ("lats", "upper_back", "rear_delts", "biceps")), ("Legs A", ("quadriceps", "hamstrings", "glutes", "calves")), ("Push B", ("chest", "side_delts", "triceps")), ("Pull B", ("lats", "upper_back", "rear_delts", "biceps", "traps")), ("Legs B", ("quadriceps", "hamstrings", "glutes", "calves", "core"))),
        },
        {
            "id": "upper_lower_6", "name": "Upper / Lower x3", "description": "Hareket seçimini çeşitlendirmek isteyenler için üç üst-alt döngüsü.",
            "sessions": (("Upper A", ("chest", "lats", "front_delts", "triceps")), ("Lower A", ("quadriceps", "hamstrings", "glutes", "calves")), ("Upper B", ("upper_back", "rear_delts", "side_delts", "biceps")), ("Lower B", ("quadriceps", "hamstrings", "glutes", "core")), ("Upper C", ("chest", "lats", "side_delts", "biceps", "triceps")), ("Lower C", ("quadriceps", "hamstrings", "glutes", "calves"))),
        },
    ),
}


def normalize_detailed_muscle(value: object) -> str | None:
    """Havuz kimliklerini, Türkçe etiketleri ve V1 geniş kaslarını normalize eder."""
    raw = str(value or "").strip()
    if not raw:
        return None
    # Türkçe büyük İ harfi casefold sonrasında birleşik nokta taşıyabilir.
    # Bu temizleme, örneğin "İç Bacak" girişinin aynı katalog anahtarına
    # güvenli biçimde eşleşmesini sağlar.
    lowered = raw.casefold().replace("\u0307", "")
    if lowered in _DETAILED_BY_ID:
        return lowered
    for item in DETAILED_MUSCLE_OPTIONS:
        if lowered == str(item["label"]).casefold().replace("\u0307", ""):
            return item["id"]
    if lowered in _DETAILED_ALIASES:
        return _DETAILED_ALIASES[lowered]
    wide = normalize_muscle_group(raw)
    # V1 geniş grup bilgisi birden fazla ayrıntılı kasa karşılık geldiğinden tek
    # bir kas uydurulmaz; çağıran fonksiyon gerekirse _expand_muscle_set kullanır.
    return None if wide else None


def _expand_muscle_set(values: Iterable[object]) -> set[str]:
    expanded: set[str] = set()
    for value in values or []:
        detailed = normalize_detailed_muscle(value)
        if detailed:
            expanded.add(detailed)
            continue
        wide = normalize_muscle_group(value)
        if wide:
            expanded.update(_UI_TO_DETAILED.get(wide, set()))
    return expanded


def detailed_muscle_label(value: object) -> str:
    key = normalize_detailed_muscle(value)
    return _DETAILED_BY_ID.get(key or "", {}).get("label", str(value or ""))


def validate_detailed_preferences(primary_goal: str, priority_muscles: Iterable[object]) -> ExpertPreferenceInput:
    """V2 ayrıntılı kas önceliklerini V1 tercihiyle aynı limitte doğrular."""
    goal = str(primary_goal or "").strip().lower()
    if goal not in PRIMARY_GOALS:
        raise ValueError("Geçerli bir ana hedef seçin.")
    muscles: list[str] = []
    for item in priority_muscles or []:
        muscle = normalize_detailed_muscle(item)
        if not muscle:
            raise ValueError("Geçersiz ayrıntılı kas önceliği seçildi.")
        if muscle not in muscles:
            muscles.append(muscle)
    if not 1 <= len(muscles) <= 3:
        raise ValueError("En az 1, en fazla 3 öncelikli kas grubu seçin.")
    return ExpertPreferenceInput(primary_goal=goal, priority_muscles=muscles)


def _session_payload(index: int, title: str, muscles: Iterable[str]) -> dict[str, Any]:
    muscle_ids = list(muscles)
    return {
        "session_id": f"session-{index + 1}",
        "sequence": index + 1,
        "title": title,
        "muscles": muscle_ids,
        "muscle_labels": [detailed_muscle_label(item) for item in muscle_ids],
    }


def generate_split_candidates(days_per_week: int, priority_muscles: Iterable[object], goal: str) -> list[dict[str, Any]]:
    """Gün sayısına göre birden fazla açıklanabilir split adayı döndürür.

    Yedi gün seçimi altı günlük planın ardından bir toparlanma günü şeklinde ele
    alınır. Bir gün seçimi ise güvenli hacim dağıtımı için Full Body 2'nin ilk
    seansına indirgenir.
    """
    try:
        days = int(days_per_week)
    except (TypeError, ValueError):
        raise ValueError("Haftalık antrenman günü 1 ile 7 arasında olmalıdır.")
    if not 1 <= days <= 7:
        raise ValueError("Haftalık antrenman günü 1 ile 7 arasında olmalıdır.")
    priorities = list(_expand_muscle_set(priority_muscles))
    clean_goal = str(goal or "").strip().lower()
    if clean_goal not in PRIMARY_GOALS:
        raise ValueError("Geçerli bir ana hedef seçin.")

    template_days = 2 if days == 1 else min(days, 6)
    templates = _SPLIT_LIBRARY[template_days]
    candidates: list[dict[str, Any]] = []
    for template in templates:
        sessions = [_session_payload(index, title, muscles) for index, (title, muscles) in enumerate(template["sessions"])]
        if days == 1:
            sessions = sessions[:1]
            sessions[0]["title"] = "Full Body"
        elif days == 7:
            sessions.append({
                "session_id": "recovery-day", "sequence": 7, "title": "Aktif Toparlanma",
                "muscles": [], "muscle_labels": [], "is_recovery_day": True,
            })
        candidates.append({
            "id": template["id"],
            "name": template["name"],
            "description": template["description"],
            "days_per_week": days,
            "priority_muscles": priorities,
            "sessions": sessions,
        })
    return candidates


def _history_pressure(history: Any, muscle: str) -> float:
    """Geçmiş hacim verisini esnek bir sözleşmeyle 0–1 aralığına indirger."""
    if not history:
        return 0.0
    values: dict[str, Any]
    if isinstance(history, dict):
        values = history.get("volume_by_muscle") or history.get("sets_by_muscle") or history
    else:
        return 0.0
    target = _expand_muscle_set([muscle])
    sets = 0.0
    for key, value in values.items():
        key_set = _expand_muscle_set([key])
        if target.intersection(key_set):
            sets += _float(value, 0.0)
    # 18 direkt set üstü, o kas için belirgin haftalık hacim baskısı kabul edilir.
    return _clamp(sets / 18.0)


def score_split_candidate(candidate: dict[str, Any], priority_muscles: Iterable[object], goal: str, history: Any = None) -> dict[str, Any]:
    """Split adayını frekans, amaç ve son hafta hacmiyle puanlar.

    Puan, tıbbi veya performans tahmini değildir. Sistem yalnızca şeffaf tercih
    sıralaması yapar ve `score_details` ile kararın nedenini API'ye taşır.
    """
    priorities = _expand_muscle_set(priority_muscles)
    sessions = [item for item in candidate.get("sessions", []) if not item.get("is_recovery_day")]
    exposure = {muscle: 0 for muscle in priorities}
    for session in sessions:
        session_muscles = set(session.get("muscles") or [])
        for muscle in priorities:
            if muscle in session_muscles:
                exposure[muscle] += 1

    score = 50.0
    reasons: list[str] = []
    if priorities:
        for muscle, count in exposure.items():
            pressure = _history_pressure(history, muscle)
            preferred_frequency = 2 if str(goal).lower() == "hypertrophy" else 1
            if pressure >= 0.8:
                preferred_frequency = 1
            if count >= preferred_frequency:
                score += 13.0
                reasons.append(f"{detailed_muscle_label(muscle)} haftada {count} kez doğrudan kapsanıyor.")
            elif count == 1:
                score += 5.0
                reasons.append(f"{detailed_muscle_label(muscle)} haftada bir kez kapsanıyor.")
            else:
                score -= 18.0
                reasons.append(f"{detailed_muscle_label(muscle)} için doğrudan seans bulunmuyor.")
            if pressure >= 0.8 and count > 1:
                score -= 9.0
                reasons.append(f"Son hafta {detailed_muscle_label(muscle)} hacmi yüksek olduğundan ek frekans azaltıldı.")

    goal_key = str(goal or "").lower()
    if goal_key == "hypertrophy":
        score += min(10.0, len(sessions) * 1.5)
        reasons.append("Kas kazanımı hedefinde düzenli frekans ve yeterli seans sayısı ödüllendirildi.")
    elif goal_key == "strength":
        # Daha az farklı gün, hareket tekrarına ve toparlanmaya alan açar.
        score += 7.0 if len(sessions) <= 4 else 2.0
        reasons.append("Güç hedefinde toparlanma aralığı ve ana hareket tekrarına ağırlık verildi.")
    else:
        score += 6.0 if len(sessions) <= 5 else 1.0
        reasons.append("Yağ kaybı hedefinde sürdürülebilir seans hacmi tercih edildi.")

    return {
        **_copy.deepcopy(candidate),
        "score": round(_clamp(score, 0.0, 100.0), 1),
        "score_details": {
            "priority_exposure": exposure,
            "reasons": reasons,
        },
    }


def select_best_split(candidates: Iterable[dict[str, Any]], priority_muscles: Iterable[object], goal: str, history: Any = None) -> dict[str, Any]:
    """En yüksek puanlı adayı, eşitlikte öncelikli kas frekansını koruyarak seçer."""
    scored = [score_split_candidate(candidate, priority_muscles, goal, history) for candidate in candidates or []]
    if not scored:
        raise ValueError("Split adayı üretilemedi.")
    scored.sort(key=lambda item: (item["score"], sum(item["score_details"]["priority_exposure"].values()), item["name"]), reverse=True)
    best = scored[0]
    return {
        "selected": best,
        "candidates": scored,
        "explanation": {
            "title": f"Önerilen split: {best['name']}",
            "summary": best["description"],
            "rules": best["score_details"]["reasons"],
        },
    }


def _normalize_equipment(value: object) -> str:
    """Havuzdaki eski ekipman adlarını salon kataloğunun güvenli kimliklerine bağlar."""
    raw = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return _GYM_EQUIPMENT_ALIASES.get(raw, raw)


def _exercise_required_equipment(exercise: dict[str, Any]) -> list[str]:
    analysis = exercise.get("analysis") or {}
    raw = analysis.get("equipment") or exercise.get("equipment") or []
    return [_normalize_equipment(item) for item in raw if _normalize_equipment(item)]


def _is_equipment_satisfied(required: Iterable[str], available: set[str]) -> bool:
    # Zemin, serbest ağırlıklar, sehpalar ve kablo uçları kullanıcıdan
    # ayrıca istenmeyen "temel imkânlar" olarak kabul edilir.
    ignored = {
        "floor", "bodyweight", "bench_optional", "step_optional", 
        "weight_plate_or_vest", "dip_belt_or_vest",
        "bench", "flat_bench", "incline_bench", "decline_bench", "adjustable_bench", 
        "preacher_bench", "preacher_curl_bench",
        "dumbbell", "barbell", "ez_bar", "kettlebell", "weight_plates", "free_weight",
        "landmine", "bar", "bar_or_suspension_trainer", 
        "rope", "single_handle", "ankle_strap", "rope_or_handles", "handles"
    }
    for item in required:
        if item in ignored or item.endswith("_optional"):
            continue
        if "_or_" in item:
            choices = set(item.split("_or_"))
            # Eğer seçeneklerden biri (örneğin dumbbell) temel ekipmansa veya 
            # kullanıcının salonunda mevcutsa bu şart sağlanmış sayılır.
            if choices.intersection(ignored) or item in available or choices.intersection(available):
                continue
            return False
        if item not in available:
            return False
    return True


def filter_exercises_by_equipment(exercise_pool: Iterable[dict[str, Any]], available_equipment: Iterable[object]) -> list[dict[str, Any]]:
    """Yalnızca kullanıcının bildirdiği ekipmanla yapılabilen hareketleri döndürür."""
    available = {_normalize_equipment(item) for item in available_equipment or [] if _normalize_equipment(item)}
    pool = [_copy.deepcopy(item) for item in exercise_pool or []]
    
    # DÜZELTME: Eski koddaki `if not available: return pool` kuralı TAMAMEN KESİLDİ!
    # Böylece listende hiç makine yoksa, tüm makineler kusursuzca elenir ve 
    # ilk üretimde sadece serbest ağırlık / vücut ağırlığı hareketleri kalır.
    
    return [item for item in pool if _is_equipment_satisfied(_exercise_required_equipment(item), available)]


def _exercise_muscles(exercise: dict[str, Any]) -> tuple[set[str], set[str]]:
    analysis = exercise.get("analysis") or {}
    primary = _expand_muscle_set(analysis.get("primary_muscles") or exercise.get("primary_muscles") or [])
    secondary = _expand_muscle_set(analysis.get("secondary_muscles") or exercise.get("secondary_muscles") or [])
    return primary, secondary


def _case_muscles(cases: Iterable[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for case in cases or []:
        if str(case.get("status", "active")).lower() not in {"active", "open", "aktif"}:
            continue
        severity = _float(case.get("last_severity", case.get("severity")), 0.0)
        for muscle in _expand_muscle_set([case.get("muscle_group")]):
            result[muscle] = max(result.get(muscle, 0.0), severity)
    return result


def _constraint_muscles(constraints: Iterable[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in constraints or []:
        if item.get("resolved_on") or str(item.get("status", "active")).lower() not in {"active", "open", "aktif"}:
            continue
        severity = _float(item.get("severity"), 0.0)
        for muscle in _expand_muscle_set([item.get("muscle_group")]):
            result[muscle] = max(result.get(muscle, 0.0), severity)
    return result


def _exercise_risk_reason(exercise: dict[str, Any], doms: dict[str, float], constraints: dict[str, float]) -> str | None:
    primary, secondary = _exercise_muscles(exercise)
    all_muscles = primary | secondary
    # 5+/10 ağrı/kısıt, ilgili ekleme anlamlı ölçüde yük bindiren hareketi seçmez.
    for muscle, severity in constraints.items():
        if severity >= 5 and muscle in all_muscles:
            return f"{detailed_muscle_label(muscle)} kısıtı ({severity:g}/10)"
    # DOMS'ta ana hedef kasın 6+/10 olması ağır hareketi çıkarmak için yeterlidir.
    for muscle, severity in doms.items():
        if severity >= 6 and muscle in primary:
            return f"{detailed_muscle_label(muscle)} DOMS'u ({severity:g}/10)"
    pattern = str((exercise.get("analysis") or {}).get("movement_pattern") or "")
    if doms.get("hamstrings", 0.0) >= 6 and ("hinge" in pattern or "deadlift" in pattern):
        return f"Hamstring DOMS'u ({doms['hamstrings']:g}/10)"
    return None


# HX_MOVEMENT_PREFERENCES_ALTERNATIVES_V1
# HX_EXPERT_CATALOG_CLEANUP_LAYOUT_V1
# HX_EXPERT_LAYOUT_MOVEMENT_VARIATIONS_V1
# Bu liste yalnız uzman önerileri ve hareket tercih ekranı içindir. Eski workout
# kayıtları değişmez; kullanıcı yalnızca yeni taslaklarda bu hareketleri görmez.
_EXPERT_CATALOG_EXCLUDED_IDS = {
    # Biceps: yalnız istenmeyen generic, dumbbell preacher ve makine varyasyonları gizli.
    "preacher-curl",
    "preacher-curl-dumbbell",
    "preacher-curl-machine",
    # Calf için yalnız üç açık dış yük varyasyonu kullanılır.
    "calf-raises-bw",
    "bulgarian-split-squat-bw",
    "cable-hip-abduction",
    "glute-bridge-bw",
    "bodyweight-squat",
    "inverted-row-bw",
    # Eski reverse-pec-deck kaydı geçmişle uyum için kalır; yeni cable varyasyonu önerilir.
    "rear-delt-fly",
}


def is_expert_catalog_excluded(exercise: dict[str, Any] | None) -> bool:
    """Kullanıcının uzman sisteminden çıkardığı hareketleri tek noktada tanımlar."""
    item = exercise if isinstance(exercise, dict) else {}
    exercise_id = str(item.get("id") or "").strip().casefold()
    if exercise_id in _EXPERT_CATALOG_EXCLUDED_IDS:
        return True
    analysis = item.get("analysis") if isinstance(item.get("analysis"), dict) else {}
    group = str(item.get("muscle_group") or "").strip().casefold()
    searchable = " ".join((
        exercise_id,
        str(item.get("name") or "").casefold(),
        str(analysis.get("family") or "").casefold(),
        str(analysis.get("movement_pattern") or "").casefold(),
    ))
    # Platformdaki omuz ve kalça rotasyonları kullanıcı arayüzünde birlikte
    # "Rotatorlar" olarak sunulduğu için her ikisi tek kuralda dışlanır.
    return group in {"rotator cuff", "hip rotators"} or "retraction" in searchable


# Hareket tercihleri, kısıt/DOMS ekipman filtresinden sonra aday sırasını etkiler.
# "preferred" öncelik verir; "avoid" hareketi uzman taslağından çıkarır.
def _clean_exercise_preference_ids(values: Iterable[object] | None, exercise_pool: Iterable[dict[str, Any]] | None) -> set[str]:
    known = {str(item.get("id")) for item in (exercise_pool or []) if isinstance(item, dict) and item.get("id")}
    return {str(value).strip() for value in (values or []) if str(value).strip() in known}


def _exercise_preference_sets(exercise_preferences: dict[str, Any] | None, exercise_pool: Iterable[dict[str, Any]] | None) -> tuple[set[str], set[str]]:
    raw = exercise_preferences if isinstance(exercise_preferences, dict) else {}
    preferred = _clean_exercise_preference_ids(raw.get("preferred_exercise_ids"), exercise_pool)
    avoided = _clean_exercise_preference_ids(raw.get("avoid_exercise_ids"), exercise_pool)
    # Aynı hareket iki listede olsa bile "önerme" kararı güvenlik için baskındır.
    return preferred - avoided, avoided


def _alternative_candidates(
    source_exercise_id: object,
    exercise_pool: Iterable[dict[str, Any]] | None,
    available_equipment: Iterable[object],
    doms_state: Iterable[dict[str, Any]] | dict[str, Any] | None = None,
    constraints: Iterable[dict[str, Any]] | None = None,
    exercise_preferences: dict[str, Any] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Tüm kısıtlamalardan arındırılmış, doğrudan katalogdaki kas ve gruplara bakan alternatif sıralayıcı."""
    full_pool = list(exercise_pool or [])
    source = next((item for item in full_pool if str(item.get("id")) == str(source_exercise_id)), None)
    if not source:
        return []
        
    # Asıl hareketin geniş grubu (Örn: "Legs", "Back") ve detaylı kasları
    source_group = source.get("muscle_group")
    source_analysis = source.get("analysis") or {}
    source_primary = set(source_analysis.get("primary_muscles") or [])
    source_secondary = set(source_analysis.get("secondary_muscles") or [])
    source_all = source_primary | source_secondary
    
    # Kişisel tercihler (Önerme / Tercih Et)
    preferred, avoided = _exercise_preference_sets(exercise_preferences, full_pool)
    
    candidates: list[dict[str, Any]] = []
    
    for exercise in full_pool:
        exercise_id = str(exercise.get("id") or "")
        
        # Kendisini veya "önerme" listesindeki hareketleri atla
        if not exercise_id or exercise_id == str(source_exercise_id) or exercise_id in avoided:
            continue
            
        # 1. KURAL: Aynı ana kas grubunda (Chest, Back, Legs vb.) olmalı.
        # Bu kural, Squat (Legs) ile Barbell Row (Back) hareketlerinin "spinal_erectors" 
        # (bel) kası yüzünden birbirine karışmasını KESİN olarak engeller.
        if exercise.get("muscle_group") != source_group:
            continue
            
        ex_analysis = exercise.get("analysis") or {}
        ex_primary = set(ex_analysis.get("primary_muscles") or [])
        ex_secondary = set(ex_analysis.get("secondary_muscles") or [])
        ex_all = ex_primary | ex_secondary
        
        # 2. KURAL: Birinci kuralı geçenler arasında, en azından bir Primary veya Secondary kas KESİŞMELİ.
        # Örn: Squat (quads, glutes) ile Leg Extension (quads) kesişir ve listelenir.
        # Ancak Squat ile Calf Raises (calves) kesişmez ve elenir.
        if not source_all.intersection(ex_all):
            continue
            
        candidates.append(exercise)
        
    # Sıralama: "Tercih Edilenler" en üstte, sonrasında alfabetik sıra. (Puanlama yok)
    candidates.sort(key=lambda ex: (
        0 if str(ex.get("id", "")) in preferred else 1,
        str(ex.get("name", "")).lower()
    ))
    
    # Limit ve ekipman/DOMS filtreleri KALDIRILDI. Şartları sağlayan tüm alternatifler listelenir.
    return [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            # Çevirmen yüzünden boş dönmemesi için doğrudan analysis içindeki ham veriyi gösteriyoruz
            "primary_muscle_labels": [detailed_muscle_label(v) for v in (item.get("analysis") or {}).get("primary_muscles", [])],
            "equipment": _exercise_required_equipment(item),
            "is_preferred": str(item.get("id")) in preferred,
        }
        for item in candidates
    ]

def get_exercise_alternatives(
    source_exercise_id: object,
    exercise_pool: Iterable[dict[str, Any]] | None,
    available_equipment: Iterable[object],
    doms_state: Iterable[dict[str, Any]] | dict[str, Any] | None = None,
    constraints: Iterable[dict[str, Any]] | None = None,
    exercise_preferences: dict[str, Any] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Arayüz/endpoint için açık isimli alternatif hareket sağlayıcısı."""
    return _alternative_candidates(source_exercise_id, exercise_pool, available_equipment, doms_state, constraints, exercise_preferences, limit)


def _prescription_for_exercise(exercise: dict[str, Any], goal: str, reduced: bool = False) -> dict[str, Any]:
    analysis = exercise.get("analysis") or {}
    category = str(exercise.get("category") or "").lower()
    fatigue = str(analysis.get("fatigue_cost") or "medium").lower()
    goal_key = str(goal or "hypertrophy").lower()
    if goal_key == "strength" and category == "compound":
        sets, reps = (3 if reduced else 4), "3–6"
    elif goal_key == "fat_loss":
        sets, reps = (2 if reduced else 3), "8–15"
    elif category == "isolation":
        sets, reps = (2 if reduced else 3), "10–15"
    else:
        sets, reps = (2 if reduced else 3), "6–12"
    if fatigue == "high" and reduced:
        sets = max(1, sets - 1)
    return {"sets": sets, "reps": reps, "effort_note": "RIR 2–3; form bozulursa seti sonlandırın." if reduced else "RIR 1–3 aralığını hedefleyin."}


def build_session_content(
    muscle_groups: Iterable[object],
    available_equipment: Iterable[object],
    doms_state: Iterable[dict[str, Any]] | dict[str, Any] | None,
    constraints: Iterable[dict[str, Any]] | None,
    exercise_pool: Iterable[dict[str, Any]] | None = None,
    goal: str = "hypertrophy",
    max_exercises: int = 6,
    exercise_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Split seansını hareket havuzu, ekipman, DOMS ve kısıtlara göre kurar.

    Kural: şiddetli DOMS ve aktif ağrı/kısıt, ilgili kası ana hedefleyen hareketi
    çıkarır. Örneğin hamstring DOMS'unda hip-hinge/deadlift varyasyonları
    elenirken quadriceps odaklı squat/leg extension adayları korunur.
    """
    target_muscles = _expand_muscle_set(muscle_groups)
    raw_doms = list(doms_state.values()) if isinstance(doms_state, dict) else list(doms_state or [])
    doms = _case_muscles(raw_doms)
    active_constraints = _constraint_muscles(constraints or [])
    full_pool = list(exercise_pool or [])
    pool = filter_exercises_by_equipment(full_pool, available_equipment)
    preferred_ids, avoided_ids = _exercise_preference_sets(exercise_preferences, full_pool)

    blocked_targets = {muscle for muscle, severity in active_constraints.items() if severity >= 7}
    if target_muscles and target_muscles.issubset(blocked_targets):
        return {
            "status": "deferred", "reason": "Bu seansın ana kasları aktif yüksek şiddetli kısıt nedeniyle ertelendi.",
            "exercises": [], "excluded": [], "target_muscles": sorted(target_muscles),
        }

    candidates: list[tuple[int, dict[str, Any]]] = []
    excluded: list[dict[str, str]] = []
    for exercise in pool:
        if is_expert_catalog_excluded(exercise):
            continue
        primary, secondary = _exercise_muscles(exercise)
        relevance = len(target_muscles.intersection(primary)) * 3 + len(target_muscles.intersection(secondary))
        if relevance <= 0:
            continue
        exercise_id = str(exercise.get("id") or "")
        if exercise_id in avoided_ids:
            excluded.append({"name": str(exercise.get("name", "Hareket")), "reason": "Kullanıcı bu hareketin önerilmemesini tercih etti."})
            continue
        reason = _exercise_risk_reason(exercise, doms, active_constraints)
        if reason:
            excluded.append({"name": str(exercise.get("name", "Hareket")), "reason": reason})
            continue
        category = str(exercise.get("category") or "").lower()
        fatigue = str((exercise.get("analysis") or {}).get("fatigue_cost") or "medium").lower()
        # Önce doğrudan hedef, sonra compound; yüksek DOMS'ta düşük yorgunluk avantajı.
        score = relevance * 10 + (4 if category == "compound" else 2)
        if fatigue == "low":
            score += 2
        if any(doms.get(muscle, 0) >= 5 for muscle in primary):
            score -= 5
        if exercise_id in preferred_ids:
            score += 25
        candidates.append((score, exercise))

    candidates.sort(key=lambda item: (item[0], str(item[1].get("name", ""))), reverse=True)
    selected: list[dict[str, Any]] = []
    represented_families: set[str] = set()
    for _, exercise in candidates:
        analysis = exercise.get("analysis") or {}
        family = str(analysis.get("family") or exercise.get("id") or exercise.get("name"))
        if family in represented_families:
            continue
        primary, _ = _exercise_muscles(exercise)
        reduced = bool(primary.intersection({muscle for muscle, severity in doms.items() if severity >= 4}))
        selected.append({
            "id": exercise.get("id"),
            "name": exercise.get("name"),
            "category": exercise.get("category"),
            "primary_muscles": sorted(primary),
            "primary_muscle_labels": [detailed_muscle_label(item) for item in sorted(primary)],
            "equipment": _exercise_required_equipment(exercise),
            "prescription": _prescription_for_exercise(exercise, goal, reduced),
            "adapted_for_recovery": reduced,
        })
        represented_families.add(family)
        if len(selected) >= max(1, min(int(max_exercises or 6), 8)):
            break

    status = "ready" if selected else "limited"
    reason = "Ekipman, DOMS ve aktif kısıtlara göre hareket seçildi." if selected else "Uygun hareket bulunamadı; ekipman veya aktif kısıtları gözden geçirin."
    return {
        "status": status,
        "reason": reason,
        "target_muscles": sorted(target_muscles),
        "target_muscle_labels": [detailed_muscle_label(item) for item in sorted(target_muscles)],
        "exercises": selected,
        "excluded": excluded[:12],
    }


def _parse_iso_date(value: Any) -> _date | None:
    if isinstance(value, _date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return _date.fromisoformat(raw[:10])
    except ValueError:
        try:
            return _datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None


def calculate_muscle_readiness(muscle_group: object, doms_cases: Iterable[dict[str, Any]], last_workout_date: Any = None) -> dict[str, Any]:
    """Bir kasın sonraki seans için 0–100 hazırlık puanını hesaplar.

    Başlangıç puanı 100'dür. Aktif DOMS puanı doğrudan, çok yakın kas seansı ise
    kademeli indirim uygular. Dönüşteki nedenler arayüzün "neden" alanında
    gösterilmek üzere açıkça tutulur.
    """
    target = _expand_muscle_set([muscle_group])
    if not target:
        raise ValueError("Kas hazırlık puanı için geçerli bir kas grubu seçin.")
    doms = _case_muscles(doms_cases or [])
    relevant_doms = max((doms.get(muscle, 0.0) for muscle in target), default=0.0)
    score = 100.0 - relevant_doms * 8.0
    reasons: list[str] = []
    if relevant_doms > 0:
        reasons.append(f"Aktif DOMS bildirimi: {relevant_doms:g}/10.")

    latest_date: _date | None = None
    if isinstance(last_workout_date, dict):
        latest_date = _parse_iso_date(last_workout_date.get("date") or last_workout_date.get("last_workout_date"))
    elif isinstance(last_workout_date, (list, tuple)):
        dates = [_parse_iso_date(item.get("date") if isinstance(item, dict) else item) for item in last_workout_date]
        latest_date = max((item for item in dates if item), default=None)
    else:
        latest_date = _parse_iso_date(last_workout_date)
    if latest_date:
        days_since = max(0, (_date.today() - latest_date).days)
        if days_since == 0:
            score -= 30
            reasons.append("Bu kas bugün çalıştırılmış görünüyor.")
        elif days_since == 1:
            score -= 18
            reasons.append("Son kas seansından yalnızca 1 gün geçti.")
        elif days_since == 2:
            score -= 8
            reasons.append("Son kas seansından 2 gün geçti.")
        else:
            reasons.append(f"Son kas seansından {days_since} gün geçti.")
    else:
        days_since = None
        reasons.append("Bu kas için son seans tarihi bulunamadı; puan DOMS verisine dayalıdır.")

    final_score = int(round(_clamp(score, 0.0, 100.0)))
    if final_score >= 80:
        status = "ready"
        message = "Normal planlanmış hacim genellikle uygundur."
    elif final_score >= 60:
        status = "caution"
        message = "Hacmi koruyun veya hafif azaltın; ilk setlerde durumu yeniden değerlendirin."
    else:
        status = "recover"
        message = "Bu kas için hacmi azaltın, hareket seçimini değiştirin veya seansı erteleyin."
    return {
        "muscle": next(iter(sorted(target))),
        "label": detailed_muscle_label(next(iter(sorted(target)))),
        "score": final_score,
        "status": status,
        "message": message,
        "doms_severity": round(relevant_doms, 1),
        "days_since_last_workout": days_since,
        "reasons": reasons,
    }


def handle_missed_session(program: dict[str, Any], missed_day: object, doms_state: Iterable[dict[str, Any]] | None, recovery_score: float, constraints: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Kaçırılan seansı, toparlanma uygunsa sıradaki antrenmanın başına taşır.

    Sistemin amacı haftalık sırayı güvenli biçimde yeniden düzenlemektir; kaçırılan
    hacmi aynı günlere eklemez ve kullanıcının onayı olmadan aktif programı
    değiştirmez.
    """
    adjusted = _copy.deepcopy(program or {})
    sessions = list(adjusted.get("sessions") or [])
    if not sessions:
        raise ValueError("Telafi için program seansı bulunamadı.")
    identifier = str(missed_day.get("session_id") if isinstance(missed_day, dict) else missed_day or "").strip().lower()
    target: dict[str, Any] | None = None
    for session in sessions:
        aliases = {str(session.get("session_id", "")).lower(), str(session.get("title", "")).lower(), str(session.get("sequence", "")).lower()}
        if identifier in aliases:
            target = session
            break
    if not target:
        raise ValueError("Kaçırılan seans programda bulunamadı.")

    recovery = _clamp(_float(recovery_score, 0.0), 0.0, 100.0)
    doms = _case_muscles(doms_state or [])
    restrictions = _constraint_muscles(constraints or [])
    muscles = set(target.get("muscles") or [])
    high_doms = [muscle for muscle in muscles if doms.get(muscle, 0.0) >= 6]
    high_constraints = [muscle for muscle in muscles if restrictions.get(muscle, 0.0) >= 5]

    can_prioritize = recovery >= 70 and not high_doms and not high_constraints
    sessions.remove(target)
    if can_prioritize:
        sessions.insert(0, target)
        action = "prioritized"
        message = f"{target.get('title')} toparlanma yeterli olduğu için sıradaki seans olarak öne alındı."
    else:
        sessions.append(target)
        action = "deferred"
        signals: list[str] = []
        if recovery < 70:
            signals.append(f"genel hazırlık {recovery:.0f}/100")
        if high_doms:
            signals.append("yüksek DOMS: " + ", ".join(detailed_muscle_label(item) for item in high_doms))
        if high_constraints:
            signals.append("aktif kısıt: " + ", ".join(detailed_muscle_label(item) for item in high_constraints))
        message = f"{target.get('title')} güvenlik için haftanın sonrasına alındı ({'; '.join(signals)})."
    for index, session in enumerate(sessions, start=1):
        session["sequence"] = index
    adjusted["sessions"] = sessions
    adjusted["recovery_adjustment"] = {
        "action": action,
        "missed_session_id": target.get("session_id"),
        "message": message,
        "recovery_score": round(recovery, 1),
    }
    return adjusted


def generate_dynamic_program(
    profile: dict[str, Any],
    preferences: dict[str, Any],
    exercise_pool: Iterable[dict[str, Any]],
    available_equipment: Iterable[object],
    active_doms: Iterable[dict[str, Any]] | None = None,
    constraints: Iterable[dict[str, Any]] | None = None,
    history: Any = None,
    last_workout_dates: dict[str, Any] | None = None,
    exercise_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """V2 program üretiminin tek giriş noktasıdır.

    Bu fonksiyon yalnızca öneri nesnesi üretir. Kalıcı "aktif program" kararı
    özellikle API'deki activate-program endpoint'ine bırakılır.
    """
    goal = str(preferences.get("primary_goal") or profile.get("goal") or "hypertrophy").lower()
    priorities = preferences.get("priority_muscles") or []
    candidates = generate_split_candidates(profile.get("days_per_week"), priorities, goal)
    split = select_best_split(candidates, priorities, goal, history)
    selected = split["selected"]
    sessions: list[dict[str, Any]] = []
    readiness: list[dict[str, Any]] = []
    for session in selected.get("sessions", []):
        session_copy = _copy.deepcopy(session)
        if session_copy.get("is_recovery_day"):
            session_copy["content"] = {"status": "recovery", "reason": "Planlı aktif toparlanma günü.", "exercises": []}
        else:
            session_copy["content"] = build_session_content(
                session_copy.get("muscles", []), available_equipment, active_doms, constraints,
                exercise_pool=exercise_pool, goal=goal, exercise_preferences=exercise_preferences,
            )
            for muscle in session_copy.get("muscles", []):
                readiness.append(calculate_muscle_readiness(muscle, active_doms or [], (last_workout_dates or {}).get(muscle)))
        sessions.append(session_copy)
    selected["sessions"] = sessions
    # Aynı kas bir seans içinde birkaç kez geçtiyse kullanıcıya tek puan gösterilir.
    unique_readiness = {item["muscle"]: item for item in readiness}
    return {
        "schema_version": 2,
        "generated_at": _datetime.now().astimezone().isoformat(timespec="seconds"),
        "goal": goal,
        "priority_muscles": list(_expand_muscle_set(priorities)),
        "priority_muscle_labels": [detailed_muscle_label(item) for item in _expand_muscle_set(priorities)],
        "split": split,
        "program": selected,
        "muscle_readiness": list(unique_readiness.values()),
        "catalog_note": "Hareketler bildirilen ekipman, aktif DOMS, geçici kısıtlar ve hareket tercihlerine göre filtrelendi.",
    }

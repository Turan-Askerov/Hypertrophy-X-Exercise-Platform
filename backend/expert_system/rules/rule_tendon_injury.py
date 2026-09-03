from typing import Any
from datetime import date
from expert_system.rule_utils import _number, _label, _finding

def rule_tendon_injury(context: dict[str, Any]) -> list[dict[str, Any]]:
    active = [
        item for item in (context.get("injuries") or [])
        if bool(item.get("is_active", True)) and str(item.get("injury_type", "")) == "tendon"
    ]
    if not active:
        return []

    findings = []
    for item in active:
        severity = int(_number(item.get("severity")))
        if severity < 3:
            continue
            
        area = _label(item.get("area"))
        started_on_str = item.get("started_on")
        tingling = item.get("tingling_severity")
        
        tingling_msg = ""
        if tingling is not None and int(tingling) > 0:
            tingling_msg = f" (Aktif sızlama şiddeti: {tingling}/5)"

        days_since = 0
        if started_on_str:
            try:
                started_date = date.fromisoformat(started_on_str[:10])
                days_since = max(0, (date.today() - started_date).days)
            except ValueError:
                pass
                
        weeks_since = days_since / 7.0
        
        if weeks_since < 2.0:
            message = (
                f"{area} bölgesi için tendon sakatlığının erken safhasındasınız (1.-2. Hafta).{tingling_msg} "
                "Tendon iyileşmesi zaman alır ve ağrı yanıltıcı olabilir. Kasa yük bindiren ana ve yan "
                "tüm hareketler sistem tarafından tamamen dışlanmıştır. Tüm seanslar, güvenlik amacıyla tamamen ertelenmiştir."
            )
            action = "Programda tam dinlenme (aktif toparlanma) önerilir. Hedef kaslara yüklenilmez."
            priority = 105
            tone = "danger"
            findings.append(_finding(f"tendon-alarm-week-1-2-{area}", priority, "Tendon Protokolü", "Tendon Alarmı: 1.-2. Hafta (Tam Dinlenme)", message, action, tone))
        elif weeks_since < 3.0:
            message = (
                f"{area} tendon sakatlığında 3. haftadasınız.{tingling_msg} Tam iyileşme gerçekleşmediğinden, "
                "kasa doğrudan çekiş/itiş uygulanmamalıdır. Karşıt kas grupları için hafif antrenmanlar "
                "yapılabilir ancak hacim düşük tutulmalıdır."
            )
            action = "Sakat kası korumaya devam et, yalnızca zıt kas gruplarında hafif antrenmanlara başla."
            priority = 95
            tone = "warn"
            findings.append(_finding(f"tendon-alarm-week-3-{area}", priority, "Tendon Protokolü", "Tendon Alarmı: 3. Hafta (Sınırlı İzin)", message, action, tone))
        elif weeks_since < 6.0:
            message = (
                f"{area} tendon sakatlığında dönüş aşamasındasınız (1-1.5 Ay).{tingling_msg} Ağrı geçmiş olsa da tendon "
                "henüz eski kapasitesine ulaşmamıştır. Eski ağırlıklarınızın en fazla %60'ı ile "
                "başlamanız ve seans başı toplam ilgili hareketleri 3 ile sınırlandırmanız önerilir."
            )
            action = "Hareketler programa dahil edilir ancak RIR düşürülür, ağırlıklar eski ağırlıkların %60 ile sınırlandırılır."
            priority = 88
            tone = "info"
            findings.append(_finding(f"tendon-alarm-return-{area}", priority, "Tendon Protokolü", "Tendon Geri Dönüş Protokolü", message, action, tone))

    return findings

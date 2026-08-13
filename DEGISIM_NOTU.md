# Hypertrophy-X v5.0 — Değişim Notu

Bu sürümde yapılan tüm değişiklikler aşağıda özetlenmiştir. Mevcut tasarım ve mimari yapı korunmuş, yalnızca istenen düzeltmeler ve eklemeler yapılmıştır.

## 1. Hareket Listesi Düzeltmesi (Antrenman Kaydı Sayfası)

**Sorun:** Antrenman kaydı sayfasında hareket listesi boş görünüyordu; sabit 5-6 öğe dışında havuzdan hiçbir hareket gelmiyordu.

**Kök Sebep:** Backend'deki hareket havuzu (`EXERCISE_POOL`) hareketleri `muscle_group` alan adıyla döndürüyordu, ancak frontend filtreleme kodu `muscle` alan adını bekliyordu. Alan adı uyumsuzluğu yüzünden 60+ hareketlik havuz filtreye takılıyor ve ekrana boş düşüyordu.

**Çözüm:** Backend `/api/exercises` endpoint'ine `muscle` alan adı alias'ı eklendi. Frontend koduna dokunulmadı — tüm sayfalar artık kas bölgesine göre filtreleme ile birlikte tam hareket havuzunu (60+ hareket) listeliyor. Ağırlıklı / Vücut Ağırlığı rozetleri de çalışır durumda.

## 2. Uzman Sistemi — Otomatik Analiz

**Sorun:** Uzman Sistemi sayfası "Analyze'i Başlat" butonu istiyordu; kullanıcı sayfaya girdiğinde içerik boş duruyordu.

**Çözüm:** Buton kaldırıldı. "Uzman Sistemi" sayfasına girildiğinde analiz **otomatik** olarak çalışıyor ve şu bilgiler anında sunuluyor:

- BMI / BMR / TDEE ve hedef kalori hesabı
- Makro hedefleri (Protein / Karb / Yağ — kullanıcının hedefine göre)
- **Günlere göre haftalık program kartları** (Pazartesi → Pazar)
- PPL gibi 2 tekrarlı programlarda **A/B varyantları**: örneğin 6 gün PPL'de iki Push günü farklı açılış hareketleriyle başlıyor — aynı hareket haftada iki kez çıkmıyor
- Dinlenme günlerinin haftaya dağılımı

Hareket önerileri `EXERCISE_TIPS` sözlüğünden gelir (`backend/main.py` içinde) — içeriğini istediğin zaman rahatça düzenleyebilirsin.

## 3. Modern Platform Gereksinimleri

| Eklenen Özellik | Açıklama |
|---|---|
| **Cache-Control Middleware** | API cevapları: `no-cache, no-store`; SPA sayfaları (index.html): `no-store`; statik dosyalar: `public, max-age=1y, immutable` |
| **Sağlık Kontrolü** | `/api/health` → `{"status":"ok","db":"ok","version":"5.0"}` — Railway/Render health check için hazır |
| **İstek Loglama** | Tüm istekler formatlı loglanır: `[zaman] METHOD /yol — durum kodu (süre ms)` |
| **Ortam Değişkenleri** | `.env.example` şablonu + `admin.env` / `.env` desteği (`JWT_SECRET`, `ADMIN_PASSWORD`, `CORS_ORIGIN`) |
| **Deploy Şablonları** | `railway.toml`, `render.yaml`, `Procfile` |
| **Routing Güçlendirme** | SPA catch-all ile statik dosya servisleri tek noktada toplanıyor; `/dashboard`, `/nutrition` gibi sayfalar tarayıcıdan doğrudan açılınca da yükleniyor |

## 4. Diğer Düzeltmeler

- **Dashboard:** BMI kutusu artık kategoriyi gösteriyor ("Fazla Kilolu" gibi) ve altında kilo/boy bilgisi var. Makro hedefleri (Protein/Karb/Yağ) kartta doğrudan görünüyor.
- **Profil Güncelleme:** Profil sayfasından yapılan değişiklikler artık gerçekten veritabanına yazılıyor (eski sürümde SQL hatası nedeniyle yazılmıyordu).
- **SPA Navigasyon:** Tarayıcıdan doğrudan adres yazıldığında (ör. `site.com/nutrition`) sayfa artık 404 vermiyor.

## 5. Kurulum (Yerel)

```bash
cd Hypertrophy-X-v5.0/backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # JWT_SECRET ve ADMIN_PASSWORD değerlerini değiştir
uvicorn main:app --host 0.0.0.0 --port 8000
```

Cloud deploy adımları `README.md` içinde (Railway, Render, VPS/Nginx).

## 6. Cloud'a Geçmeden Önce Yapılacaklar

1. `.env` dosyasındaki `JWT_SECRET` değerini güçlü bir rastgele dize ile değiştir
2. `ADMIN_PASSWORD` değerini güçlü bir şifre yap
3. `.env` dosyasını hiçbir şekilde paylaşma (`.gitignore` zaten koruyor)

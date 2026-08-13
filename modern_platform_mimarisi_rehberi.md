# Hypertrophy-X — Modern Platform Mimarisi Rehberi

**Hazırlayan:** Manus AI
**Tarih:** 8 Ağustos 2026
**İlgili proje sürümü:** Hypertrophy-X v4.0 (FastAPI + SQLite + Vanilla JS SPA)

---

## Giriş: Bu Rehber Ne Anlatıyor?

Bu rehber, Hypertrophy-X projesini "kendi bilgisayarında çalışan bir API sunucusu" halinden çıkarıp **kullanıcılara sunabileceğin gerçek bir web platformu** haline getirmek için yazıldı. Rehber üç bölümden oluşuyor:

1. **Modern platformlar nasıl çalışır?** — Instagram, Spotify, Notion gibi platformların mimarisi, tarayıcı cache'i, CDN, kimlik doğrulama gibi kavramların sıfırdan açıklaması
2. **Senin projenin bugünkü durumu** — Projeni modern standartlarla karşılaştıran dürüst bir analiz ve tespit ettiğim kritik noktalar
3. **Adım adım dönüşüm yol haritası** — "Şu yaptığını şöyle değiştirirsen modern platforma uyumlu olur" formatında somut, sıralı öneriler

Amacım sana "her şeyi baştan yaz" demek değil. Projenin çekirdek mimarisi (FastAPI + SQLite + SPA) bu işin üstesinden gelebilecek kadar sağlam. Sorun, etrafındaki **kabuk** katmanında: güvenlik, dağıtım, cache ve kimlik doğrulama. Bu rehber o kabuğu nasıl kuracağını gösteriyor.

---

## BÖLÜM 1 — Modern Platformlar Nasıl Çalışır? (Sıfırdan Anlatım)

### 1.1 Bir Kullanıcı Tarayıcıya Adres Yazdığında Gerçekten Ne Olur?

Bir kullanıcı `hipertrofy-x.com` adresine girdiğinde, arka planda şu zincir gerçekleşir. Her modern platform bu zincirin aynısını kullanır — fark sadece her halkadaki araçların kalitesindedir.

| Adım | Ne Olur | Sen Proje Dediğin Şey |
|---|---|---|
| 1. DNS | Alan adı, sunucu IP adresine çevrilir | `127.0.0.1` — bilgisayarın kendisi |
| 2. TLS/SSL | Tarayıcı ile sunucu arasında şifreli tünel açılır (HTTPS) | HTTP — şifresiz, düz metin |
| 3. Sunucu | İstek Nginx gibi bir "kapı bekçisi"nden geçer, sonra uygulamanıza ulaşır | Doğrudan uvicorn — kapı bekçisi yok |
| 4. Önbellek katmanı | Sunucu "bu sayfa çok soruluyor, hazır halini vereyim" der | Cache yok — her istek her seferinde hesaplanıyor |
| 5. Uygulama | FastAPI kodun çalışır, veritabanına sorar | ✅ Bu kısım çalışıyor |
| 6. Veritabanı | SQLite/PostgreSQL veriyi döndürür | ✅ SQLite çalışıyor |
| 7. Tarayıcı | Gelen yanıtı ekrana çizer ve bir sonraki ziyaret için saklar | Kısmen saklıyor (localStorage) |

İşte bu zincirin her halkasında "modern platform" ile "şimdiki projen" arasında fark var. Bu rehberin geri kalanı, bu farkları tek tek kapatmayı anlatıyor.

### 1.2 Cache (Önbellek) Nedir ve Tarayıcı Nasıl Saklıyor?

Cache, "aynı şeyi tekrar tekrar hesaplamak/indirmek yerine, bir kere yap ve sakla" ilkesidir. Web'de 4 farklı cache katmanı vardır ve hepsi farklı şeyler saklar:

**Katman 1 — HTTP Cache (Tarayıcı Cache'i).** Sunucu, her yanıtla birlikte bir not gönderir: "Bu dosya 1 yıl değişmez, tarayıcıda sakla." Tarayıcı bu notu görünce, o dosyayı (CSS, JS, resim) bir daha sunucudan **indirmmez** — direkt kendi diskinden açar. Instagram'a her girdiğinde sayfada ilk görünen şey, aslında sunucudan yeni gelmez; tarayıcında zaten durur. Sadece yeni veri API'den çekilir.

```
Sunucu yanıt başlığı örneği:
Cache-Control: public, max-age=31536000, immutable
```

Bu satır "bu dosya 1 yıl boyunca aynısıdır" demektir. Tarayıcı o dosyayı 1 yıl hiç indirmeyebilir.

**Katman 2 — CDN (İçerik Dağıtım Ağı).** Dünyanın dört bir yanına dağılmış kopya sunuculardır. `hipertrofy-x.com`'a İstanbul'dan giren kullanıcı ile Tokyo'dan giren kullanıcı, **aynı sunucuya** gitmez; ikisi de kendisine en yakın CDN düğümünden alır. Dosyaların kopyası bu düğümlerde saklanır. Cloudflare en bilinen örneğidir ve ücretsiz katmanı küçük projeler için yeterlidir.

**Katman 3 — Service Worker (Uygulama içi cache).** Tarayıcıda çalışan küçük bir JavaScript programıdır. "Şu API yanıtını sakla, internet yokken bunu göster" diyebilirsin. Instagram web, uçak modundayken bile eski fotoğrafları gösterebilmesinin sebebi budur.

**Katman 4 — Uygulama seviyesi cache (Server-side).** Sunucu tarafında "bu hesaplama pahalı, sonucu 5 dakika saklayayım" mantığıdır. Senin projende Dashboard her istekte BMI, TDEE, split hesabı yapıyor — 1000 kullanıcı olsa, aynı hesap 1000 kez yapılır. Basit bir `@lru_cache` veya Redis ile bu sayı 1'e iner.

**Senin projende durum:** Tarayıcıda sadece `localStorage` kullanıyorsun (oturum flag'leri, tema tercihi). HTTP cache, CDN, Service Worker ve server-side cache **hiçbiri yok**. Ziyaretçi her sayfa açılışında tüm HTML, CSS ve JS'i baştan indiriyor.

### 1.3 Kimlik Doğrulama (Authentication) ve Oturum (Session) Nasıl Çalışır?

Şimdiki projen şu şekilde çalışıyor: Kullanıcı giriş yapar → frontend `localStorage`'a `hx_loggedIn = true` yazar → her API isteğinde `username=Turan` parametresi gönderir → backend sadece bu username'e bakar.

Bu modelin iki büyük açığı var:

1. **Kimse doğrulanmıyor.** `username=Turan` parametresini `username=Ali` yaparsan, Ali'nin tüm verilerini görürsün. Çünkü backend "bu isteği Turan mı gönderdi?" sorusunu sormuyor. Şifre sadece girişte kontrol ediliyor, sonrasında **hiçbir şey** kontrol edilmiyor.
2. **Oturum yok.** Kullanıcı sayfayı kapattığında `localStorage` duruyor, ama sunucu tarafında "Turan şu an girişte" diye bir kayıt yok. Yani Turan'ın oturumunu **uzaktan sonlandıramazsın**, "diğer cihazlardan çıkış yap" diyemezsin.

**Modern platformlarda nasıl çalışır:** JWT (JSON Web Token) denilen bir sistem kullanılır. Giriş başarılı olunca sunucu, **imzalı bir belge** üretir:

```
EylhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...  (Turan'ın kimliği + sonlanma tarihi + sunucu imzası)
```

Bu belge tarayıcıda saklanır ve her API isteğinin **başlığına** eklenir (`Authorization: Bearer ...`). Backend her istekte imzayı doğrular: "Bu belgeyi BEN verdim mi? Süresi dolmuş mu? Bu kullanıcı kim?" Üçünü de kontrol eder. Kimliği başkasının adına yazdırmak imkansızdır çünkü imza sadece sunucunun elinde olan gizli bir anahtarla atılır.

### 1.4 Bir Modern Platformun Katmanlı Mimarisi

Instagram gibi platformlar şu katmanlardan oluşur (her katmanın tek bir görevi vardır):

```
┌─────────────────────────────────────────────────────────┐
│  1. CDN (Cloudflare)   → Statik dosyaların dünyaya dağıtımı │
│  2. Nginx (Reverse Proxy) → HTTPS, güvenlik duvarı, routing │
│  3. Uygulama (FastAPI) → İş mantığı, API endpoint'leri      │
│  4. Veritabanı (PostgreSQL) → Kalıcı veri                    │
│  5. Cache (Redis)      → Hızlı tekrar erişim                 │
│  6. Depolama (S3)      → Fotoğraf/dosya saklama              │
└─────────────────────────────────────────────────────────┘
```

Senin projen şu an 3. ve 4. katmana sahip. 1, 2, 5 ve 6'nın olmadığını biliyoruz; bunlar "kullanıcılara sunma" aşamasında eklenir. Ama en kritik eksik, 3. katmanın içinde bir güvenlik mekanizması olmaması (JWT + CORS kısıtlaması).

### 1.5 "Tek Sayfalık Uygulama" (SPA) ve URL — Senin Navigation Sorunun Nereden Geliyor?

Bu bölümü özel olarak yazıyorum çünkü son haftalardaki navigation sorunları bu kavramı anlamadan çözülemezdi.

Klasik web sitelerinde her sayfa ayrı bir HTML dosyasıdır; linke tıklamak = yeni dosya indirmek demektir. SPA'da ise **tek bir HTML dosyası** vardır; "sayfa geçişleri" aslında JavaScript'in aynı dosya içindeki div'leri gösterip gizlemesinden ibarettir. History API (`pushState`) bunu tarayıcıya "sanki yeni sayfaya geçiyormuşuz gibi" hissettirir ve adres çubuğundaki URL'yi değiştirir.

Modern platformlar bunu iki stratejiyle çözer:

| Strateji | Nasıl Çalışır | Örneği |
|---|---|---|
| **Client-side routing** | Her `/nutrition` gibi istek aynı `index.html`'i döndürür, JS hangi sayfayı göstereceğine karar verir | Senin projen (SPA catch-all ile) |
| **Server-side routing + hydration** | Sunucu her sayfanın HTML'ini hazır döndürür, JS sadece etkileşimi devralır | Next.js uygulamaları |

Senin projen ilk stratejiyi doğru kullanıyor — `@app.get("/{path:path}")` catch-all route'u bu işi yapıyor. Navigation motorundaki son düzeltmeler de (replaceState + popstate + history.forward kilidi) bu mimari içinde en sağlam modeldir. **Bu kısım tamam, tekrar dokunmaya gerek yok.**

---

## BÖLÜM 2 — Senin Projenin Bugünkü Durumu: Dürüst Analiz

Projeni v4.0 haliyle baştan taradım. İşte modern standartlarla karşılaştırma tablosu:

| Alan | Senin Şimdiki Halin | Modern Standart | Durum |
|---|---|---|---|
| Backend framework | FastAPI (asenkron, modern) | ✅ Aynısı | Tamam |
| API tasarımı | RESTful, `/api/` altında toplanmış | ✅ Aynısı | Tamam |
| SPA frontend | Tek index.html, History API | ✅ Aynısı | Tamam |
| Veritabanı | SQLite tek dosya | PostgreSQL önerilir | ⚠️ Geliştirilebilir |
| Şifreleme | SHA256 + salt (hash var) | ⚠️ bcrypt/argon2 önerilir | Kısmen |
| Admin şifresi | **Kodda sabit: `ADMIN_PASSWORD = "admin"`** | Ortam değişkeni + hash | 🔴 Kritik |
| Oturum yönetimi | localStorage flag + username param | JWT token | 🔴 Eksik |
| API güvenliği | Kimlik doğrulaması sadece username'e bakıyor | Her istekte JWT kontrolü | 🔴 Eksik |
| CORS | `allow_origins=["*"]` (herkese açık) | Sadece kendi alan adın | ⚠️ Riskli |
| HTTPS | Yok (HTTP) | TLS zorunlu | 🔴 Eksik |
| Cache başlıkları | Yok | Cache-Control gerekli | Eksik |
| CDN | Yok | Cloudflare ücretsiz yeterli | Eksik |
| Deployment | `uvicorn` terminalden el ile | Nginx + systemd veya PaaS | Eksik |
| Otomatik yedekleme | DB dosyası kopyala-yapıştır | Zamanlanmış yedek | Eksik |
| Loglama | uvicorn istek logu | Yapılandırılmış log + monitoring | Eksik |
| .gitignore | venv ve DB dosyası zip'e dahil | Dışarıda kalmalı | Küçük ama önemli |

### 2.1 En Kritik Üç Sorun (Sunuma Geçmeden Önce ŞART)

**Sorun 1 — Admin şifresi kodun içinde ve zayıf.** `backend/main.py` satır 24-25'te `ADMIN_USERNAME = "admin"`, `ADMIN_PASSWORD = "admin"` yazıyor. Yani projeni GitHub'a yüklersen veya sunucuya koyarsan, admin paneline **herkes** "admin / admin" ile girebilir ve tüm kullanıcıların verilerini silebilir. Bu, sunuma geçmeden önce **mutlaka** kapatılmalı.

**Sorun 2 — API istekleri kimliği doğrulamıyor.** Her endpoint sadece `username=Turan` parametresine bakıyor. Bir kullanıcı tarayıcı konsolundan `username=Başkası` gönderirse, başkasının tüm antrenman, beslenme ve profil verisini görür, düzenler, siler. JWT ile bunu kapatmalıyız.

**Sorun 3 — CORS herkese açık.** `allow_origins=["*"]` demek, internetten herhangi bir site JavaScript ile senin API'na istek atabilir demek. Kendi alan adın belli olduktan sonra bunu sadece kendi adresine kısıtlamalıyız.

### 2.2 Güçlü Yanların (Değişmesin)

Projenin bazı kararları zaten modern platformlarla aynı hizada ve bunlar **korunmalı**: Tek `main.py` altında API toplama (senin istediğin dinamik mimari), esnek `EXERCISE_POOL` JSON yapısı, SQLite'ın düşük bakım gerektirmesi (ilk 1000 kullanıcı için gayet yeterli), SPA navigation motorunun son hali, ve admin/normal kullanıcı menü ayrımı.

---

## BÖLÜM 3 — Adım Adım Dönüşüm Yol Haritası

Aşağıdaki adımlar sıralıdır ve her biri öncekinin üzerine kurulur. "Şu yaptığını şöyle değiştirirsen modern olur" isteğine birebir karşılık: her başlıkta **bugünkü hal → yapılacak değişiklik → neden** formatı var.

### ADIM 1 — Güvenliği Önce Kapat (2-3 saatlik iş)

**a) Admin şifresini ortam değişkenine taşı.** Bugünkü hal: kod içinde sabit metin. Yeni hal:

```python
# Kötü (şimdiki)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"

# İyi (yeni)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")  # Sunucuda .env dosyasında
```

Sunucuda `ADMIN_PASSWORD` değerini güçlü bir şifreyle `.env` dosyasında tutarsın ve bu dosyayı asla git'e yüklemezsin. Ayrıca girişte bu şifre de hash'lenip karşılaştırılmalı — ham metin karşılaştırma kaldırılmalı.

**b) JWT kimlik doğrulaması ekle.** Bugünkü hal: her API isteğinde `username=Turan` parametresi. Yeni hal:

```
Giriş başarılı → sunucu JWT üretir (24 saat geçerli)
Her API isteği → Authorization: Bearer <TOKEN> başlığı
Backend → her endpoint'te token'ı doğrular → kullanıcıyı çözer
```

FastAPI tarafında bu yaklaşık 150 satır ekleme: `python-jose` ve `passlib[bcrypt]` paketleri kurulur, `/api/auth/login` token döndürmeye başlar, ve mevcut endpoint'lerin başına bir `get_current_user` bağımlılığı (dependency) eklenir. **Frontend'te değişiklik küçük:** giriş sonrası token `localStorage`'a kaydedilir ve `apiGet/apiPost/apiDelete/apiPut` helper'larına tek satır eklenir — `headers: {"Authorization": f"Bearer {token}"}`.

**c) CORS'u kısıtla.** Sunucunun alan adı belli olduktan sonra:

```python
# Kötü (şimdiki)
allow_origins=["*"]

# İyi (yeni)
allow_origins=[os.getenv("FRONTEND_URL", "https://hipertrofy-x.com")]
```

**d) Şifre hash'leme algoritmasını yükselt.** SHA256+salt iş görür ama endüstri standardı **bcrypt**'tir (kasıtlı olarak yavaştır — kaba kuvvet saldırısını zorlaştırır). Değişiklik: `passlib[bcrypt]` kur, `_hash_password` fonksiyonunu `bcrypt.hashpw` kullanacak şekilde değiştir, veritabanındaki eski hash'leri ilk girişte yeni formata dönüştür (migration).

### ADIM 2 — Sunucuya Taşıma: Deployment (1-2 günlük iş)

Modern platformların tamamı bir "sunucu üzerinde 7/24 çalışan" servistir. Senin projenin üç makul taşıma yolu var:

| Yöntem | Maliyet | Zorluk | Önerim |
|---|---|---|---|
| **Railway / Render (PaaS)** | Ücretsiz katman mevcut | Çok kolay (git push ile deploy) | ✅ İlk sunum için ideal |
| **VPS (Hetzner/DigitalOcean) + Nginx** | ~4-6 €/ay | Orta (Linux bilgisi gerekir) | ✅ Uzun vadede en iyisi |
| AWS / Google Cloud | Karmaşık fiyatlandırma | Yüksek | ❌ Şimdilik gereksiz |

**Önerdiğim yol:** İlk sunumu Railway ile hızlıca yapıp canlıya almak, sonra kullanıcı sayısı artınca Hetzner VPS'e taşımak. Railway'de süreç şudur: kodu GitHub'a yükle → Railway projesine bağla → ortama değişkenleri (ADMIN_PASSWORD, SECRET_KEY) gir → otomatik deploy. `requirements.txt` ve bir `Procfile` (`web: uvicorn main:app --host 0.0.0.0 --port $PORT`) yeterlidir.

**VPS yolunda** kurulum şöyle görünür (Nginx + systemd):

```
Nginx (port 80/443)  →  Gunicorn worker'lar  →  FastAPI (uvicorn)
      ↓
HTTPS sertifikası (Let's Encrypt, ücretsiz, Certbot ile)
```

Nginx burada üç iş yapar: HTTPS'i yönetir, statik dosyaları (index.html, CSS, JS) **doğrudan kendisi** servis eder (FastAPI'nin iş yükünü hafifletir) ve FastAPI'ye gelen trafiği yönlendirir. İşte bu, "kapı bekçisi" dediğim katmandır.

### ADIM 3 — Cache Katmanı Ekle (1 günlük iş)

**a) HTTP Cache başlıkları.** Nginx konfigurasyonuna statik dosyalar için şu eklenir:

```nginx
# static dosyalar 1 yıl cache'lensin
location ~* \.(js|css|png|jpg|svg|ico|woff2)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}

# index.html asla cache'lenmesin (yeni sürüm hemen gelsin)
location = / {
    add_header Cache-Control "no-cache";
}
```

Bu tek satırlar, sitenin açılış hızını 2-4 kat düşürür. İlk ziyarette HTML gelir, sonraki ziyaretlerde sadece JSON API verisi.

**b) API tarafında basit cache.** FastAPI'de `@lru_cache` ile pahalı hesapları sakla:

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def compute_tdee(age, gender, height, weight, level):
    # hesap (günlük kalori hedefi gibi)
```

Dashboard'a giren her kullanıcıda TDEE hesabı tekrar tekrar yapılmaz; 128 farklı kombinasyona kadar sonuç bellekte durur.

**c) Service Worker (opsiyonel, ileri aşama).** PWA'ya çevirme: uygulaman "telefon ekranına ekle" ile kurulabilir hale gelir, offline çalışır. Bu, v5.0 sonrası için güzel bir hedef ama sunum için şart değil.

### ADIM 4 — Veritabanını Güçlendir (kullanıcı sayısı 1000'i geçince)

SQLite şaşırtıcı derecede dayanıklıdır — Instagram bile başlangıçta SQLite kullanıyordu. Ama yazma işlemlerinde tek bağlantıya izin verdiği için **aynı anda iki kişi antrenman kaydetmeye çalışırsa** biri bekler. Kullanıcıların ilk aylarında sorun yaşamazsın.

Geçiş zamanı geldiğinde yapılacaklar: SQLite → **PostgreSQL** (Railway'de ve Hetzner'da ücretsiz/ucuz managed servis var), ve şema değişiklikleri için **migration** sistemi (örn. `alembic`). Şu anki `ALTER TABLE ... try/except` tekniği, 5 tablo için idare eder ama 30 tabloya çıkınca yönetilemez.

**Yedekleme:** SQLite'da basit bir cron job her gece `cp hypertrophy.db backup/db_$(date).db` yapar. PostgreSQL'de `pg_dump` benzeri işi görür. Kayıp veri, kullanıcıların güvenini kaybetmek demek — yedek şart.

### ADIM 5 — Profesyonel Proje Düzeni (yarım günlük iş)

Sunucuya taşımadan önce proje dosya düzenini toparla:

```
Hypertrophy-X/
├── .env.example          # Ortam değişkeni şablonu (gizli DEĞİL)
├── .gitignore            # venv/, *.db, .env, __pycache__/
├── requirements.txt
├── Procfile              # Railway deploy
├── backend/
│   ├── main.py
│   └── static/
├── frontend/
│   └── index.html
└── scripts/
    ├── backup.sh         # Otomatik yedekleme
    └── deploy.sh         # Sunucu güncelleme scripti
```

Özellikle `.gitignore` — zip dosyasında `venv/` klasörünün (93 MB) yer alması, sürüm kontrolünün ne kadar önemli olduğunun göstergesi. Bundan sonra `git add .` yapmadan önce bu dosyanın hazır olması lazım.

### ADIM 6 — Monitoring ve Sağlık Kontrolü (birkaç saatlik iş)

Modern platformlar kendilerini "izler". Senin projene eklenecekler:

1. **Health check endpoint:** `GET /api/health` → `{"status": "ok", "db": "ok"}` döndürsün. Uptime monitörleri (örn. ücretsiz UptimeRobot) bu adresi her 5 dakikada sorgular; sunucu çökerse sana SMS/e-posta gelir. Kullanıcılarından önce sen haberdar olursun.
2. **Yapılandırılmış log:** uvicorn'un varsayılan logu iyidir ama dosyaya yazdır (`--log-file access.log`) ve kritik hataları ayrı yakala.
3. **Hata sayfası:** Şimdiki `404 Not Found` JSON yanıtı kullanıcı dostu değil — Nginx tarafında şık bir "Sayfa bulunamadı" HTML'i göster.

### ADIM 7 — AI Entegrasyonu (Sonraki Büyük Görev)

Navigation sorunu çözüldükten sonraki büyük görev olan AI Coach, mimari olarak nasıl oturmalı:

1. **OpenAI API key'ini asla kodda tutma.** `.env` dosyasında `OPENAI_API_KEY=sk-...` — GPT-4o-mini fiyatları çok düşüktür (1 milyon token ~0.15 USD), ayda 1000 kullanıcıya analiz versen bile aylık maliyet birkaç doları geçmez.
2. **Rate limit koruması:** AI endpoint'ine her kullanıcı dakikada 1 istek atabilsin (JWT + basit sayaç). Aksi halde biri script yazıp API kotanı yakar.
3. **Yanıt cache'i:** Aynı profil bilgileriyle analiz 24 saat içinde tekrar istenirse, cached sonuç dönsün (gereksiz OpenAI ücretinden kurtarır).

---

## Özet Tablo: Öncelik Sırası

| Öncelik | Görev | Süre | Risk seviyesi |
|---|---|---|---|
| 🔴 1 | Admin şifresi koddan çıkar + hash yükselt | 2 saat | Kritik |
| 🔴 2 | JWT kimlik doğrulaması | 1 gün | Kritik |
| 🟡 3 | Railway/Render ile ilk canlıya alma | 1 gün | Yüksek |
| 🟡 4 | HTTPS + Nginx (VPS'e geçince) | 1 gün | Yüksek |
| 🟢 5 | HTTP cache başlıkları | 2 saat | Orta |
| 🟢 6 | `.gitignore`, `.env`, proje düzeni | Yarım gün | Orta |
| 🟢 7 | Health check + loglama | Yarım gün | Düşük |
| 🔵 8 | AI Coach entegrasyonu (bir sonraki büyük görev) | — | — |

## Son Söz

Projenin çekirdeği — API tasarımı, veritabanı yapısı, SPA mimarisi, hareket havuzu — zaten modern platformlardakiyle aynı mantıkta çalışıyor. Eksik olan, **taşıyıcı katman**: güvenlik (JWT), dağıtım (sunucu + HTTPS), ve hız (cache). Bu rehberdeki 7 adımı sırayla uygularsan, Hypertrophy-X birkaç hafta içinde "kendi bilgisayarında çalışan proje" kimliğinden çıkıp, herhangi bir adres çubuğundan girilebilen gerçek bir platforma dönüşür.

Bir sonraki adım olarak, istersen 1. ve 2. maddeleri (admin şifresi + JWT) birlikte kodlayalım — bunlar diğer adımların hepsinin ön koşulu. Hangisinden başlamak istersen söyle, hazır.

<div align="center">

# 🏋️ HYPERTROPHY-X
### Profesyonel Antrenman Platformu — v4.0

**JWT Güvenlik • Uzman Sistem • Modern SPA Mimarisi • Production-Ready**

| | |
|---|---|
| **Versiyon** | 5.0 (Modern Platform) |
| **Backend** | Python 3.10+ / FastAPI |
| **Veritabanı** | SQLite (tek dosya, taşınabilir) |
| **Frontend** | Tek sayfa uygulaması (HTML + CSS + JS) |
| **Kimlik** | JWT + bcrypt (12 round) |
| **Lisans** | Özel kullanım |

</div>

---

## ✨ v4.0 Yenilikleri

| Özellik | Açıklama |
|---|---|
| **Hareket Havuzu API** | 60+ hareket `/api/exercises` üzerinden kas bölgesine göre filtrelenebilir listeleniyor. Ağırlıklı / Vücut Ağırlığı rozetleri destekli |
| **Uzman Sistemi (Otomatik)** | "Uzman Sistemi" sayfasına girildiğinde analiz **otomatik** çalışır. Günlere göre haftalık program, A/B varyantları ile aynı hareketin haftada iki kez çıkması engelleniyor |
| **Cache-Control Middleware** | API → `no-cache`, index.html → `no-store`, statik dosyalar → `public, max-age=1y` |
| **Sağlık Kontrolü** | `/api/health` endpoint'i ile DB + uygulama durumu izlenir (Railway/Render health check) |
| **İstek Loglama** | Tüm HTTP istekleri formatlı olarak loglanır (zaman, method, path, durum, süre) |
| **Dashboard Geliştirmeleri** | BMI kategorisi (Zayıf/Normal/Fazla Kilolu/Obez), makro hedefleri kartta doğrudan görünür |
| **Profil Güncelleme Düzeltmesi** | Profil kaydı artık gerçekten veritabanına yazılıyor |
| **Deploy Şablonları** | `railway.toml`, `render.yaml`, `Procfile` hazır |

---

## 📁 Proje Yapısı

```
Hypertrophy-X-v5.0/
├── backend/
│   ├── main.py              # TÜM endpoint'ler + JWT + uzman sistem (tek dosya mimarisi)
│   ├── requirements.txt     # Python bağımlılıkları
│   ├── .env.example         # Ortam değişkenleri şablonu
│   ├── admin.env            # (İlk kurulum) admin şifresi ve JWT anahtarı buradan okunur
│   ├── Procfile             # Render/Heroku
│   ├── railway.toml         # Railway
│   ├── render.yaml          # Render Blueprint
│   ├── start.sh             # Yerel başlatma scripti (Linux/macOS)
│   └── static/
│       └── index.html       # Tek sayfa frontend (SPA)
├── frontend/
│   └── index.html           # Frontend kaynağı (static ile aynı)
├── README.md                # Bu dosya
├── KULLANIM.md              # Detaylı kullanım kılavuzu
└── modern_platform_mimarisi_rehberi.md   # Detaylı mimari rehberi (ana dizinde)
```

> **Mimari not:** Backend ve frontend bağlantısı tek `main.py` üzerinde toplanmıştır. Frontend'deki tüm API çağrıları `apiGet()` / `apiPost()` yardımcı fonksiyonları üzerinden `Authorization: Bearer <token>` başlığıyla yapılır. Yeni bir sayfa eklerken sadece frontend'de yeni bir `page-*` div ve `navigate()` kaydı eklemen yeterlidir — backend'e dokunmaya gerek kalmaz.

---

## 🚀 Hızlı Başlangıç (Yerel)

### Linux / macOS

```bash
# 1. Backend klasörüne gir
cd Hypertrophy-X-v5.0/backend

# 2. Sanal ortam kur ve aktif et
python3 -m venv venv && source venv/bin/activate

# 3. Bağımlılıkları yükle
pip install -r requirements.txt

# 4. Ortam dosyasını oluştur (ŞART!)
cp .env.example .env
# .env içinde JWT_SECRET ve ADMIN_PASSWORD değerlerini değiştir

# 5. Başlat
uvicorn main:app --host 0.0.0.0 --port 8000
# veya: ./start.sh
```

### Windows (PowerShell)

```powershell
cd Hypertrophy-X-v4.0\backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env     # değerleri .env içinde düzenle
uvicorn main:app --host 0.0.0.0 --port 8000
```

Tarayıcıda `http://127.0.0.1:8000` adresini aç.

| Hesap | Kullanıcı | Şifre |
|---|---|---|
| Admin | `admin` | `.env` / `admin.env` içinde tanımladığın şifre |
| Kullanıcı | Kendi oluşturduğun hesap | — |

---

## ☁️ Cloud Deploy

### Railway
1. Projeyi GitHub'a push et
2. Railway'de "New Project → GitHub Repo" seç
3. `railway.toml` otomatik algılanır
4. **Variables** sekmesinden `JWT_SECRET` ve `ADMIN_PASSWORD` ekle
5. Deploy — sağlık kontrolü `/api/health` otomatik çalışır

### Render
1. Render'da **Blueprint** oluştur, repo'yu bağla
2. `render.yaml` otomatik algılanır
3. Ortam değişkenlerini panelde gir (`JWT_SECRET`, `ADMIN_PASSWORD`)
4. Deploy

### Kendi VPS (Nginx)

```bash
sudo nano /etc/systemd/system/hypertrophy-x.service
```

```ini
[Unit]
Description=Hypertrophy-X
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/hypertrophy-x/backend
Environment="PATH=/var/www/hypertrophy-x/backend/venv/bin"
ExecStart=/var/www/hypertrophy-x/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now hypertrophy-x
```

Nginx reverse proxy:

```nginx
server {
    listen 80;
    server_name senin-alan-adin.com;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 🔒 Güvenlik Kontrol Listesi (Production)

| # | Kontrol | Durum |
|---|---|---|
| 1 | `JWT_SECRET` güçlü ve benzersiz mi? | ⚠️ Varsayılan DEĞİŞTİR |
| 2 | `ADMIN_PASSWORD` güçlü mü? | ⚠️ Varsayılan DEĞİŞTİR |
| 3 | `.env` git'e eklenmedi mi? | ✅ `.gitignore` koruyor |
| 4 | `CORS_ORIGIN` sadece kendi alan adın mı? | ⚠️ Production'da daralt |
| 5 | HTTPS aktif mi? (Railway/Render otomatik verir) | ✅ Cloud'da otomatik |
| 6 | DB dosyası `.gitignore`'da mı? | ✅ |

---

## 🧠 Uzman Sistem — Haftalık Program Mantığı

Kullanıcının `days_per_week` değerine göre program seçilir:

| Gün | Program | Not |
|---|---|---|
| 1 | Full Body | Temel bileşikler |
| 2 | Upper / Lower | Klasik 2'li split |
| 3 | Full Body A-B-C | Her seans farklı odak |
| 4 | Upper / Lower x2 | Frekans artırılmış |
| 5 | PPL + Üst/Alt | Push-Pull-Legs hibrit |
| 6 | **PPL x2** | Push A/B, Pull A/B, Legs A/B — **aynı hareket haftada iki kez çıkmaz** |
| 7 | PPL + Dinlenme | 2 dinlenme günü |

Hareket önerileri `EXERCISE_TIPS` sözlüğünden gelir (`backend/main.py` içinde) — içeriğini istediğin gibi düzenleyebilirsin.

---

## 📝 Notlar

- **Veritabanı:** `backend/hypertrophy.db` — ilk çalıştırmada otomatik oluşur
- **Yeni hareket ekleme:** `backend/main.py` içindeki `EXERCISE_POOL` listesine dict ekle (`muscle_group`, `category`, `is_bodyweight` alanlarıyla)
- **Hata raporlama:** Sunucu logları `INFO` seviyesinde tüm istekleri yazar

---

*Hypertrophy-X v5.0 — Hazırlayan: Manus*

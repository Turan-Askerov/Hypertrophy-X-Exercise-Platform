# Hypertrophy-X v4.0 — Antrenman Platformu

## Hızlı Başlangıç

### Linux (Ubuntu/Debian)

```bash
# 1. Backend klasörüne gir
cd Hypertrophy-X-v4.0/backend

# 2. Start script'ini çalıştır
chmod +x start.sh
./start.sh
```

### Manuel Kurulum

```bash
# 1. Proje ana klasöründe venv oluştur
python3 -m venv venv

# 2. Venv'i aktif et
source venv/bin/activate

# 3. Backend'e gir
cd backend

# 4. Bağımlılıkları yükle
pip install -r requirements.txt

# 5. Static klasör oluştur ve index.html kopyala
mkdir -p static
cp ../frontend/index.html static/

# 6. Eski DB'yi sil (ilk kurulumda)
rm -f hypertrophy.db

# 7. Sunucuyu başlat
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Tarayıcıda Aç

```
http://127.0.0.1:8000/app
```

## Giriş Bilgileri

### Normal Kullanıcı
- Hesap Oluştur butonu ile yeni hesap aç
- Kullanıcı adı + şifre ile giriş yap
- Profil sayfasından kişisel bilgileri doldur

### Admin
- Kullanıcı adı: `admin`
- Şifre: `admin`
- Admin bilgileriyle giriş yapınca otomatik admin paneline yönlendirilir

## Özellikler

### 1. Dashboard
- Haftalık/Aylık/Toplam antrenman + seri gün + dinlenme süresi
- Antrenman programı (split bilgisi)
- BMI + fiziksel durum
- Cut/Bulk hedefi + kalori + makro hedefler
- Haftalık hacim grafiği
- Kas grubu dağılımı
- Vücut & beslenme bilgileri
- Haftalık takvim

### 2. Antrenman Kaydı
- Her set için ayrı tekrar sayısı girişi
- Kas bölgesine göre filtreleme (10 kas grubu)
- 67+ hareket havuzu
- Vücut ağırlığı hareketleri (ağırlık kutusu otomatik devre dışı)
- Hareketler: Bench Press, Squat, Deadlift, Pull-ups, Dips vb.

### 3. Admin Paneli
- Sadece admin girişinde görünür
- Tüm kullanıcıları görüntüleme
- Kullanıcı bilgilerini düzenleme (yaş, kilo, boy, seviye, hedef)
- Kullanıcı şifresi değiştirme
- Kullanıcı antrenmanlarını görüntüleme ve silme
- Kullanıcı silme (tüm antrenmanlarıyla birlikte)
- İstatistikler: toplam kullanıcı, antrenman, hacim, ortalama BMI

### 4. Profil
- Kişisel bilgiler düzenleme
- Şifre değiştirme

### 5. Tema
- Koyu/Açık mod geçişi (sağ üst buton)
- Tercih localStorage'da saklanır

### 6. Sidebar Hamburger Menüsü
- Hamburger butonu ile sidebar'ı simge moduna küçültme
- Icon-only modda sadece ikonlar görünür

## Dosya Yapısı

```
Hypertrophy-X-v4.0/
├── backend/
│   ├── main.py          # Tüm API'ler (887 satır)
│   ├── requirements.txt # Python bağımlılıkları
│   └── start.sh         # Başlatma scripti
├── frontend/
│   └── index.html       # Tüm sayfalar (2198 satır)
└── KULLANIM.md
```

## Endpoint'ler

| Endpoint | Metod | Açıklama |
|----------|-------|----------|
| /api/auth/register | POST | Hesap oluştur |
| /api/auth/login | POST | Giriş yap |
| /api/auth/change-password | POST | Şifre değiştir |
| /api/user | GET | Kullanıcı bilgisi al |
| /api/user | POST | Kullanıcı bilgisi güncelle |
| /api/workouts | GET | Antrenmanları listele |
| /api/workouts | POST | Antrenman kaydet |
| /api/workouts/{id} | DELETE | Antrenman sil |
| /api/dashboard | GET | Dashboard verileri |
| /api/analyze | POST | Uzman sistemi analizi |
| /api/progress | GET | İlerleme verileri |
| /api/exercises | GET | Egzersiz havuzu |
| /api/admin/users | GET | Tüm kullanıcılar |
| /api/admin/user | PUT | Kullanıcı düzenle |
| /api/admin/user/{id} | DELETE | Kullanıcı sil |
| /api/admin/workouts/{uid} | GET | Kullanıcı antrenmanları |
| /api/admin/workout/{id} | DELETE | Antrenman sil |
| /app | GET | Ana sayfa |
| / | GET | /app'e yönlendir |

## Hareket Havuzunu Genişletme

`main.py` içinde `EXERCISE_POOL` listesini bul ve yeni hareket ekle:

```python
{"id": "yeni_hareket", "name": "Hareket Adı", "muscle": "Kas Grubu", "bw": false, "weighted": true}
```

- `bw: true` → Vücut ağırlığı hareketi (ağırlık kutusu gizlenir)
- `weighted: true` → Ağırlıklı hareket
- Her iki değer de `true` ise hem ağırlıklı hem ağırlıksız seçilebilir

# Hypertrophy-X v4.0 — PostgreSQL Aktarım ve Canlıya Alma Rehberi

> SQLite'tan PostgreSQL'e aktarım öncesinde hem mevcut `backend/hypertrophy.db` dosyasını hem de PostgreSQL veritabanını yedeklemek gerekir. 

| Bileşen | v4.0 davranışı | v4.1 davranışı |
|---|---|---|
| Yerel geliştirme | SQLite | `DATABASE_URL` boşsa aynı SQLite dosyası kullanılmaya devam eder. |
| Production | SQLite veya geçici disk riski | `DATABASE_URL` olmadan başlamaz; PostgreSQL zorunludur. |
| Veri aktarımı | Elle SQL yazma riski | `migrate_sqlite_to_postgres.py` kullanıcı ve antrenman id'lerini koruyarak tekrar çalıştırılabilir aktarım yapar. |
| Eski veritabanı | Dosya düzeyinde korunur | Salt okunur açılır; araç bu dosyayı değiştirmez veya silmez. |
| Kimlik doğrulama koruması | Uygulama seviyesinde | Giriş/kayıt uçlarında aynı istemci için varsayılan 15 dakikada 10 deneme limiti bulunur. |

## 1. Eski SQLite Dosyasını Yedekle

Proje kökünde aşağıdaki komutu çalıştırın. Bu adım, orijinal dosyayı yerinde tutar ve tarihli ikinci bir kopya üretir.

```bash
cd ~/Desktop/Hypertrophy-X-v4.0
mkdir -p backups
cp backend/hypertrophy.db "backups/hypertrophy-before-postgres-$(date +%F-%H%M%S).db"
```

## 2. Maliyetsiz PostgreSQL Veritabanını Oluştur

Bu sürümün maliyetsiz başlangıç yolu **Neon Free PostgreSQL + Render Free Web Service** kombinasyonudur. Neon'da proje oluşturup PostgreSQL bağlantı adresini alın. Render'ın ücretsiz PostgreSQL'i 30 gün sonra sona erdiği için kullanıcı verisi için kullanılmamalıdır. Neon Free planı, proje başına 0.5 GB depolama ve ayda 100 CU-saat sağlar; boşta kaldığında veritabanı compute katmanı sıfıra iner.[1]

Yerel bilgisayarınızdan aktarım yapacağınız için Neon panelinden alınan **pooled connection string** veya **direct connection string** gerekir. Render production ortamındaki `DATABASE_URL` değişkenine de aynı Neon bağlantı adresi girilir. Bağlantı bilgisini hiçbir zaman GitHub'a, `.env.example` dosyasına, ekran görüntüsüne veya sohbet mesajına eklemeyin.

> Render'ın ücretsiz web servisi 15 dakika trafiksiz kaldığında uykuya geçer. İlk sonraki istek uygulamayı yeniden başlatacağı için yaklaşık bir dakika bekleme yaşanabilir. Bu, sıfır maliyetli başlangıcın kabul edilmesi gereken sınırlamasıdır.[2]

## 3. Python Bağımlılıklarını Kur

```bash
cd ~/Desktop/Hypertrophy-X-v4.0
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. Önce Dry-Run ile Kaynağı Denetle

Bu komut PostgreSQL'e yazmaz. Yalnızca SQLite dosyasını salt okunur modda açar ve aktarılacak kayıt sayılarını gösterir.

```bash
cd backend
python migrate_sqlite_to_postgres.py --sqlite-path hypertrophy.db --dry-run
```

Beklenen çıktı, mevcut paketteki veri için aşağıdaki biçimdedir:

```text
Kaynak denetlendi: x kullanıcı, xx antrenman kaydı.
SQLite korunuyor: .../backend/hypertrophy.db
Dry-run tamamlandı: PostgreSQL'e hiçbir veri yazılmadı.
```

## 5. PostgreSQL'e Aktar

Aşağıdaki komutta **tırnak içindeki örnek metni aynen bırakmayın**. `NEON_PANELINDEN_KOPYALANAN_GERCEK_POSTGRES_URL` bölümü Neon panelinden kopyaladığınız, `postgresql://` veya `postgres://` ile başlayan gerçek bağlantı adresiyle değiştirilmelidir. Terminal geçmişinde sır kalmasını istemiyorsanız komut tamamlandıktan sonra `unset DATABASE_URL` kullanın; `.env` dosyasını Git'e eklemeyin.

```bash
cd ~/Desktop/Hypertrophy-X-v4.0/backend
export DATABASE_URL='NEON_PANELINDEN_KOPYALANAN_GERCEK_POSTGRES_URL'
python migrate_sqlite_to_postgres.py --sqlite-path hypertrophy.db
unset DATABASE_URL
```

Aktarım, önce `users`, sonra kullanıcı ilişkisini korumak için `workouts` kayıtlarını işler. Kayıt id'leri korunur; PostgreSQL otomatik id sayacı da en yüksek id'ye göre güncellenir. Aynı komut aynı kaynağa tekrar çalıştırılırsa id bazlı güncelleme yaptığı için yinelenen kayıt üretmez.

## 6. Production Ortam Değişkenlerini Tanımla

Canlı ortamda aşağıdaki değerleri hosting sağlayıcısının **Variables/Secrets** panelinden girin. `.env.example` yalnızca şablondur; gerçek değerler asla Git'e eklenmez.

| Değişken | Production gereksinimi |
|---|---|
| `APP_ENV` | `production` |
| `DATABASE_URL` | PostgreSQL bağlantı adresi; boş olamaz. |
| `JWT_SECRET` | En az 32 karakterlik, rastgele ve gizli değer. |
| `ADMIN_USERNAME` | Admin kullanıcı adı. |
| `ADMIN_PASSWORD` | Benzersiz, en az 12 karakterlik güçlü parola. |
| `CORS_ORIGIN` | Yalnızca kendi HTTPS domain'iniz; örneğin `https://uygulamaniz.example`. |
| `TRUST_PROXY_HEADERS` | Railway/Render reverse proxy arkasında `true`. |
| `ENABLE_HSTS` | Özel HTTPS domaininiz doğrulandıktan sonra `true`. |

Güçlü JWT anahtarı üretmek için:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 7. Dağıtım Sonrası Kontrol

Canlı adrese geldikten sonra `/api/health` yolunun `200` yanıt verdiğini ve uygulamaya giriş yapılabildiğini kontrol edin. Ardından eski SQLite dosyasını silmeden saklayın. İlk hafta boyunca PostgreSQL yedeğini düzenli alın ve yalnızca başarılı production denemesinden sonra kullanıcı trafiğini yönlendirin.

## Yedekleme Notu

Ücretsiz katmanlarda otomatik yedekleme garantisi yoktur. Bu nedenle PostgreSQL aktarımı tamamlanınca ve önemli veri girişlerinden sonra elle yedek alın. Ubuntu'da önce istemciyi kurun:

```bash
sudo apt install postgresql-client -y
```

`DATABASE_URL` değerini **unset etmeden önce** aşağıdaki komutu çalıştırın:

```bash
pg_dump "$DATABASE_URL" --format=custom --file "backups/hypertrophy-postgres-$(date +%F-%H%M%S).dump"
```

Bu yedekler kullanıcı bilgisi içerir. Şifreli depolama kullanın, ortak klasörlere koymayın ve GitHub'a göndermeyin.

## Kaynaklar

[1] Neon, [Pricing](https://neon.com/pricing).  
[2] Render, [Deploy for Free](https://render.com/docs/free).  
[3] PostgreSQL Global Development Group, [pg_dump Documentation](https://www.postgresql.org/docs/current/app-pgdump.html).

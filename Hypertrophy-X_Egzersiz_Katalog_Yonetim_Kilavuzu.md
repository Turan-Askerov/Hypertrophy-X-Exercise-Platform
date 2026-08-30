# Hypertrophy-X Egzersiz Kataloğu Yönetim Kılavuzu

Bu belge, `~/Desktop/Hypertrophy-X-v4.0` projesinde **yeni hareket ekleme**, mevcut hareketin **görünen adını değiştirme**, bir hareketi yalnızca **uzman önerilerinden çıkarma** ve eski kayıtlarla güvenli biçimde çalışma adımlarını açıklar.

> **Temel kural:** Egzersiz geçmişi kullanıcı verisidir. Daha önce kaydı olabilecek bir hareketin kanonik `id` değeri silinmez veya değiştirilmez. Gerekirse yalnız görünür adı değişir ya da hareket uzman öneri havuzundan çıkarılır.

## 1. Dosyaların görevleri

| Dosya | Görevi | Ne zaman değiştirilir? |
|---|---|---|
| `backend/exercise_catalog.py` | Ana/kanonik egzersiz havuzu; ad, kas, ekipman ve hareket analizi burada tanımlıdır. | Yeni hareket eklerken veya görünür adı değiştirirken. |
| `backend/exercise_aliases.py` | Eski, yazım hatalı veya farklı isimlerin kanonik harekete bağlandığı eşleme tablosudur. | Yeni ad ile eski ad aynı hareket olduğunda. |
| `backend/expert_system.py` | Uzman öneri motoru ve öneri dışı bırakılan hareket kimlikleri burada bulunur. | Bir hareket geçmişte kalsın ama uzman önerilerinde görünmesin istendiğinde. |
| `backend/static/index.html` | Arayüz kodu. | Normalde yeni hareket eklerken değiştirilmez; katalog API üzerinden otomatik gelir. |

## 2. Her değişiklikten önce güvenli yedek

Terminalde aşağıdaki komutları çalıştır. Bu adım yalnız kaynak dosyalarının kopyasını oluşturur; veritabanını değiştirmez.

```bash
cd ~/Desktop/Hypertrophy-X-v4.0
STAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p ".local-backups/manual-catalog-${STAMP}/backend"
cp -p backend/exercise_catalog.py backend/expert_rule_engine.py backend/expert_recommendation.py backend/exercise_aliases.py backend/expert_system.py ".local-backups/manual-catalog-${STAMP}/backend/"
```

Sonrasında yalnız değiştirdiğin dosyaları kontrol edebilirsin:

```bash
git diff -- backend/exercise_catalog.py backend/exercise_aliases.py backend/expert_system.py backend/expert_recommendation.py backend/expert_rule_engine.py
```

## 3. Yeni hareket ekleme

Yeni bir hareket için **benzersiz ve değişmeyecek** kebab-case kimlik oluşturulur. Örnek olarak `Cable Bayesian Curl` eklemek için `backend/exercise_catalog.py` içindeki kol/biceps bölümüne aşağıdaki kalıba uygun yeni satır eklenir.

```python
_exercise(
    "cable-bayesian-curl",
    "Cable Bayesian Curl",
    "Arms",
    "isolation",
    False,
    family="biceps_curl",
    variation="cable_bayesian",
    primary_muscles=["biceps"],
    secondary_muscles=["forearms"],
    movement_pattern="elbow_flexion",
    equipment=["cable_station"],
    load_mode="external_load",
    fatigue_cost="low",
),
```

Aşağıdaki alanlar hareketin uzman sisteminde doğru çalışması için önemlidir.

| Alan | Açıklama | Örnek |
|---|---|---|
| İlk değer / `id` | Kalıcı, benzersiz kimliktir. Sonradan değiştirilmez. | `cable-bayesian-curl` |
| Görünen ad | Kullanıcının ekranda gördüğü addır. | `Cable Bayesian Curl` |
| Grup | Genel antrenman grubu. | `Arms`, `Legs`, `Back` |
| Tür | `compound` veya `isolation`. | `isolation` |
| Vücut ağırlığı | Vücut ağırlığı hareketiyse `True`; diğerlerinde `False`. | `False` |
| `family` | Aynı hareket ailesini belirtir; alternatif üretimde kullanılır. | `biceps_curl` |
| `primary_muscles` | Doğrudan hedef kaslar. | `["biceps"]` |
| `secondary_muscles` | İkincil çalışan kaslar. | `["forearms"]` |
| `movement_pattern` | Hareket paterni; alternatif üretiminde önemlidir. | `elbow_flexion` |
| `equipment` | Gereken ekipman kimlikleri. | `["cable_station"]` |

Yeni hareketin ekipman kimliği salon kataloğunda hiç yoksa, `backend/expert_system.py` içindeki `GYM_EQUIPMENT_CATALOG` listesine de uygun kimlik/etiket eklenmelidir. Serbest ağırlık ve sehpa türleri artık temel imkân kabul edildiğinden, bunlar için yeni kullanıcı seçimi eklenmez.

## 4. Mevcut bir hareketin adını değiştirme

Bir hareket aynı hareket olarak kalıyorsa **id’yi değiştirme**. Yalnız ikinci parametre olan görünen adı değiştir.

Örneğin eski kayıtların `calf-raises` kimliğiyle kalması istenirken ekranda daha açık ad gösterilmesi için:

```python
# Doğru: id sabit, yalnız görünen ad değişir.
_exercise("calf-raises", "Standing Calf Raise (Dumbbell)", "Legs", ...)
```

Aşağıdaki yaklaşım yanlıştır; eski antrenmanların grafik, alias ve uzman tercih eşlemesini bozar.

```python
# Yanlış: eski kimliği yeni kimlikle değiştirme.
_exercise("standing-calf-raise-dumbbell", "Standing Calf Raise (Dumbbell)", "Legs", ...)
```

Eski kullanıcı isimleri varsa `backend/exercise_aliases.py` dosyasındaki `EXERCISE_ALIASES` sözlüğüne yalnız anlamı kesin olan eşlemeleri ekle.

```python
'calf raise dumbbell': 'calf-raises',
'dumbbell calf raise': 'calf-raises',
```

> Aynı ad iki farklı hareketi ifade edebiliyorsa alias ekleme. Belirsiz eşleme yanlış grafiğe, yanlış PR birleşimine veya hatalı kas dağılımına yol açabilir.

## 5. Hareketi uzman önerilerinden çıkarma

Bir hareket geçmiş workout kayıtlarında görünmeye devam etsin fakat **Hareket Tercihlerim**, yeni uzman taslağı ve alternatif listesinde çıkmasın isteniyorsa hareketi katalogdan silme. Bunun yerine `backend/expert_system.py` içindeki `_EXPERT_CATALOG_EXCLUDED_IDS` kümesine hareket kimliğini ekle.

```python
_EXPERT_CATALOG_EXCLUDED_IDS = {
    # Mevcut dışlamalar...
    "ornek-hareket-id",
}
```

Bu yöntem, örneğin eski `Bicep Curl` veya geçmişte kaydı olan bir hareketi kullanıcı geçmişinden silmeden uzman motorundan çıkarmak için tercih edilir.

## 6. Yeni bir hareketi tamamen silme

Bir hareketin hiç kullanıcı verisinde olmadığından kesin eminsen, ilgili `_exercise(...)` bloğunu `exercise_catalog.py` içinden kaldırabilirsin. Ancak aşağıdaki durumlarda **silme yerine uzman önerilerinden çıkarma** yöntemini kullan.

| Durum | Güvenli işlem |
|---|---|
| Geçmişte workout kaydı olabilir. | `_EXPERT_CATALOG_EXCLUDED_IDS` içine ekle. |
| Eski adlar yeni hareketle aynı anlamdadır. | Kimliği koru, görünen adı değiştir ve alias ekle. |
| Yeni hareket henüz hiç kullanılmadı. | Katalogdaki `_exercise(...)` bloğunu kaldırabilirsin. |
| Bir hareket yanlış eklenmiş, ama eski kayıtlarda var. | Geçmişi koru; uzman önerilerinden dışla ve gerekiyorsa not al. |

## 7. Örnek: Calf varyasyonu ekleme

Calf için kullanılacak açık üç varyasyon aşağıdaki yaklaşımı izler.

| Görünen ad | Kanonik id | Gerekli ekipman | Açıklama |
|---|---|---|---|
| `Standing Calf Raise (Dumbbell)` | `calf-raises` | `dumbbell` | Eski genel calf kayıtları bu kimlikle uyumludur. |
| `Standing Calf Raise (Barbell)` | `standing-calf-raise-barbell` | `barbell` | Ayakta barbell varyasyonu. |
| `Seated Calf Raise` | `seated-calf-raise` | `seated_calf_raise` | Oturarak calf makinesi varyasyonu. |

Bu üçü aynı `family="calf_raise"` ve `movement_pattern="plantar_flexion"` değerlerini paylaşır. Böylece alternatif listesinde aynı güvenli hareket ailesi altında değerlendirilirler.

## 8. Değişiklikten sonra kontrol

Her kaynak değişikliğinden sonra terminalde şunları çalıştır.

```bash
cd ~/Desktop/Hypertrophy-X-v4.0
venv/bin/python -m py_compile backend/main.py backend/exercise_catalog.py backend/exercise_aliases.py backend/expert_system.py
git diff --check
git status --short
```

İlk iki komut hata vermezse sunucuyu yeniden başlat veya çalışan `--reload` sunucusunun yenilenmesini bekle.

```bash
cd ~/Desktop/Hypertrophy-X-v4.0/backend
DATABASE_URL='' ../venv/bin/python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Tarayıcıda `Ctrl+F5` yaptıktan sonra yeni hareketin antrenman kayıt ekranında, **Uzman Sistemi → Hareket Tercihlerim** bölümünde ve uygun olduğunda yeni uzman taslağında göründüğünü kontrol et.

## 9. Asla yapılmaması gerekenler

| Yapılmaması gereken işlem | Neden riskli? |
|---|---|
| `hypertrophy.db` dosyasını silmek, yeniden adlandırmak veya sıfırlamak | Kullanıcı, workout ve uzman verileri kaybolabilir. |
| Eski egzersizin kanonik `id` değerini değiştirmek | Geçmiş workout, alias, grafik ve tercih eşleşmesi kırılabilir. |
| `.env` dosyasını açmak, paylaşmak veya commit etmek | Gizli bağlantı ve anahtar bilgileri içerebilir. |
| `git add .` kullanmak | Veritabanı, yedek veya gizli dosyalar yanlışlıkla sürüm kontrolüne eklenebilir. |
| Önce test etmeden çok sayıda hareketi topluca silmek | Sorun oluştuğunda hangi değişikliğin sebep olduğunu bulmak zorlaşır. |

Bu kural setiyle katalog modüler kalır: egzersiz verisi, eski ad uyumluluğu ve uzman öneri dışlamaları birbirinden ayrı yönetilir.

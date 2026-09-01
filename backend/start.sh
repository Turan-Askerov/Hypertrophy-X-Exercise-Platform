#!/bin/bash
# Hypertrophy-X Başlatma Scripti
cd "$(dirname "$0")"

# Virtual environment oluştur (eğer yoksa)
if [ ! -d "../venv" ]; then
    echo "Virtual environment oluşturuluyor..."
    python3 -m venv ../venv
fi

# Aktif et
source ../venv/bin/activate

# Bağımlılıkları yükle
pip install -r requirements.txt

echo "Sunucu başlatılıyor..."
echo "Tarayıcıda http://127.0.0.1:8000 adresini aç"
echo ""
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

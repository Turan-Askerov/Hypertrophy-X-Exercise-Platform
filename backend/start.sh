#!/bin/bash
# Hypertrophy-X v4.0 Başlatma Scripti
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

# Static klasör
mkdir -p static
cp ../frontend/index.html static/

echo "Sunucu başlatılıyor..."
echo "Tarayıcıda http://127.0.0.1:8000/app adresini aç"
echo ""
echo "Admin: admin / admin"
echo ""
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

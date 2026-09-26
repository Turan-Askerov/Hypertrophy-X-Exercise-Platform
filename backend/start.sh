#!/bin/bash
# Hypertrophy-X Başlatma Scripti
cd "$(dirname "$0")"

# 1. Codebase Memory UI kontrolü ve başlatma (9749 portu)
CBM_BIN="$HOME/.local/bin/codebase-memory-mcp"
if command -v "$CBM_BIN" >/dev/null 2>&1; then
    if ! ss -tuln | grep -q ":9749 "; then
        echo "Codebase Memory MCP Web UI (9749) başlatılıyor..."
        "$CBM_BIN" index_status >/dev/null 2>&1 &
    else
        echo "Codebase Memory MCP (9749) zaten aktif."
    fi
fi

# 2. Virtual environment oluştur (eğer yoksa)
if [ ! -d "../venv" ]; then
    echo "Virtual environment oluşturuluyor..."
    python3 -m venv ../venv
fi

# Aktif et
source ../venv/bin/activate

# Bağımlılıkları yükle
pip install -r requirements.txt

echo ""
echo "Servisler Hazır:"
echo "Platform UI/API   : http://127.0.0.1:8000"
echo "Codebase Graph UI : http://127.0.0.1:9749"
echo ""

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

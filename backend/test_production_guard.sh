#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
LOG_FILE="/tmp/hypertrophy-v41-production-guard.log"
set +e
APP_ENV=production \
JWT_SECRET="production-test-secret-that-is-over-thirty-two-characters" \
ADMIN_USERNAME="admin" \
ADMIN_PASSWORD="Guclu-Test-Admin-Parolasi-2026" \
CORS_ORIGIN="https://app.example.test" \
uvicorn main:app --host 127.0.0.1 --port 8912 >"$LOG_FILE" 2>&1
STATUS=$?
set -e

if [[ "$STATUS" -eq 0 ]]; then
  echo "Hata: DATABASE_URL yokken production sunucusu çalıştı." >&2
  exit 1
fi

grep -q "DATABASE_URL production ortamında PostgreSQL bağlantısı için zorunludur" "$LOG_FILE"
echo "Başarılı: production koruması DATABASE_URL eksikliğini engelledi."

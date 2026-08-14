#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PORT=8911
LOG_FILE="/tmp/hypertrophy-v41-test.log"

APP_ENV=development \
JWT_SECRET="local-test-secret-at-least-thirty-two-characters" \
ADMIN_USERNAME="admin" \
ADMIN_PASSWORD="yerel-test-admin-parolasi" \
CORS_ORIGIN="*" \
LOGIN_RATE_LIMIT_MAX=2 \
LOGIN_RATE_LIMIT_WINDOW_SECONDS=60 \
uvicorn main:app --host 127.0.0.1 --port "$PORT" >"$LOG_FILE" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 20); do
  if curl --silent --fail "http://127.0.0.1:$PORT/api/health" >/tmp/hx-health.json; then
    break
  fi
  sleep 0.25
done

health_status=$(curl --silent --output /tmp/hx-health.json --write-out '%{http_code}' "http://127.0.0.1:$PORT/api/health")
headers=$(curl --silent --head "http://127.0.0.1:$PORT/api/health")
first_login=$(curl --silent --output /tmp/hx-login-1.json --write-out '%{http_code}' \
  --header 'Content-Type: application/json' \
  --data '{"username":"rate-limit-test","password":"yanlis"}' \
  "http://127.0.0.1:$PORT/api/auth/login")
second_login=$(curl --silent --output /tmp/hx-login-2.json --write-out '%{http_code}' \
  --header 'Content-Type: application/json' \
  --data '{"username":"rate-limit-test","password":"yanlis"}' \
  "http://127.0.0.1:$PORT/api/auth/login")
third_login=$(curl --silent --output /tmp/hx-login-3.json --write-out '%{http_code}' \
  --header 'Content-Type: application/json' \
  --data '{"username":"rate-limit-test","password":"yanlis"}' \
  "http://127.0.0.1:$PORT/api/auth/login")

[[ "$health_status" == "200" ]]
[[ "$first_login" == "401" ]]
[[ "$second_login" == "401" ]]
[[ "$third_login" == "429" ]]
grep -qi '^x-content-type-options: nosniff' <<<"$headers"
grep -qi '^x-frame-options: DENY' <<<"$headers"
grep -qi '^referrer-policy: strict-origin-when-cross-origin' <<<"$headers"

echo "Başarılı: health=$health_status, giriş denemeleri=$first_login/$second_login/$third_login"

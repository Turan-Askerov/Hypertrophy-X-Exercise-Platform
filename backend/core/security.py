"""Hypertrophy-X kimlik doğrulama, JWT, parola şifreleme ve güvenlik katmanı."""
import hashlib
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock

import bcrypt
from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse
from jose import ExpiredSignatureError, JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ADMIN_PASSWORD_PLAIN,
    ADMIN_USERNAME,
    ALGORITHM,
    BCRYPT_ROUNDS,
    LOGIN_RATE_LIMIT_MAX,
    LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    SECRET_KEY,
    TRUST_PROXY_HEADERS,
)

logger = logging.getLogger("hypertrophy-x")

ADMIN_PASSWORD_HASH = None


def _hash_password(password: str) -> str:
    """Yeni şifre hash'leme — bcrypt (12 round)"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def _verify_admin_password(plain: str, stored_hash: str) -> bool:
    """Admin şifresini bcrypt hash ile doğrular."""
    try:
        return bcrypt.checkpw(plain.encode(), stored_hash.encode())
    except Exception:
        return False


def _init_admin_password_hash():
    """Admin şifresini ilk başlatmada bcrypt ile hash'ler."""
    global ADMIN_PASSWORD_HASH
    if ADMIN_PASSWORD_PLAIN:
        ADMIN_PASSWORD_HASH = bcrypt.hashpw(
            ADMIN_PASSWORD_PLAIN.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
        ).decode()


_init_admin_password_hash()


def _verify_password(plain: str, stored_hash: str, salt: str) -> bool:
    """Doğrulama: bcrypt veya eski SHA256 formatını kontrol eder."""
    if not stored_hash:
        return False
    if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
        return bcrypt.checkpw(plain.encode(), stored_hash.encode())
    # Eski SHA256 + salt formatı (migration)
    old = hashlib.sha256((salt + plain).encode()).hexdigest()
    return old == stored_hash


def _upgrade_to_bcrypt_if_needed(conn, user_id: int, plain: str):
    """Şifre eski formattaysa bcrypt'e yükselt — login sırasında çağrılır."""
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if row and row["password_hash"] and not row["password_hash"].startswith("$2b$"):
        new_hash = _hash_password(plain)
        conn.execute(
            "UPDATE users SET password_hash = ?, password_salt = '' WHERE id = ?",
            (new_hash, user_id),
        )


def _create_access_token(username: str, is_admin: bool = False) -> str:
    now_utc = datetime.now(timezone.utc)
    expire = now_utc + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": username, "is_admin": is_admin, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=401, detail="Oturum süresi doldu, lütfen tekrar giriş yapın"
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Geçersiz oturum")


_USER_LAST_SEEN: dict[str, float] = {}


def _resolve_current_user(
    authorization: str = Header(None),
    authorization_alt: str = Header(None, alias="Authorization"),
) -> dict:
    from services.user_service import get_user_by_username

    token_raw = authorization or authorization_alt
    if not token_raw:
        raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli")
    token = token_raw.replace("Bearer ", "").strip()
    payload = _decode_token(token)

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Geçersiz oturum bilgisi")

    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı")

    if payload.get("is_admin") and username != ADMIN_USERNAME:
        raise HTTPException(status_code=401, detail="Geçersiz oturum")
    if not payload.get("is_admin") and username == ADMIN_USERNAME:
        raise HTTPException(status_code=401, detail="Geçersiz oturum")

    db_is_admin = bool(user.get("is_admin", False))
    if payload.get("is_admin") != db_is_admin:
        raise HTTPException(status_code=401, detail="Geçersiz oturum")

    _USER_LAST_SEEN[username] = time.time()
    user_clean = dict(user)
    user_clean.pop("password_hash", None)
    user_clean.pop("password_salt", None)
    return user_clean


def _require_admin(user: dict) -> dict:
    """Admin endpoint'leri için rol kontrolü."""
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Admin yetkisi gerekli")
    return user


# ── Güvenlik & Performans Middleware'leri ──
class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache, no-store"
            response.headers["Pragma"] = "no-cache"
        elif "." in path.split("/")[-1] and not path.endswith((".html", ".htm")):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        ms = int((time.time() - start) * 1000)
        logger.info(f"{request.method} {request.url.path} — {response.status_code} ({ms}ms)")
        return response


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    protected_paths = {"/api/auth/login", "/api/auth/register"}
    _attempts = defaultdict(deque)
    _lock = Lock()

    @staticmethod
    def _client_identifier(request: Request) -> str:
        if TRUST_PROXY_HEADERS:
            forwarded_for = request.headers.get("x-forwarded-for", "")
            if forwarded_for:
                return forwarded_for.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and request.url.path in self.protected_paths:
            identifier = self._client_identifier(request)
            key = f"{request.url.path}:{identifier}"
            now = time.monotonic()
            with self._lock:
                attempts = self._attempts[key]
                while attempts and now - attempts[0] >= LOGIN_RATE_LIMIT_WINDOW_SECONDS:
                    attempts.popleft()
                if len(attempts) >= LOGIN_RATE_LIMIT_MAX:
                    retry_after = max(
                        1, int(LOGIN_RATE_LIMIT_WINDOW_SECONDS - (now - attempts[0]))
                    )
                    return JSONResponse(
                        status_code=429,
                        content={
                            "detail": "Çok fazla deneme yapıldı. Lütfen daha sonra tekrar deneyin."
                        },
                        headers={"Retry-After": str(retry_after)},
                    )
                attempts.append(now)

            response = await call_next(request)
            if 200 <= response.status_code < 300:
                with self._lock:
                    self._attempts.pop(key, None)
            return response
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        return response

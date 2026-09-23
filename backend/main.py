"""Hypertrophy-X Backend Uygulaması — Modüler Ana Giriş Noktası."""
from pathlib import Path
from fastapi import FastAPI, APIRouter, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# Merkezi Yapılandırma
from core.config import (
    APP_ENV,
    IS_PRODUCTION,
    CORS_ORIGINS,
    DATABASE_URL,
    DATABASE_BACKEND,
    DB_PATH,
    ADMIN_USERNAME,
    ADMIN_PASSWORD_PLAIN,
    ADMIN_PASSWORD_HASH,
    validate_runtime_configuration,
    log,
)

# Veritabanı
from core.database import get_db, init_db

# Güvenlik, Kimlik Doğrulama ve Middleware'ler
from core.security import (
    RequestLogMiddleware,
    CacheControlMiddleware,
    AuthRateLimitMiddleware,
    _resolve_current_user,
    _require_admin,
    _hash_password,
    _verify_password,
    _create_access_token,
)

# E-posta
from core.email import mask_email, send_password_reset_email

# Servis Katmanı
from services.workout_service import (
    resolve_exercise_metadata,
    get_workouts_by_user,
    create_workout,
    delete_workout,
    update_workout,
    _iter_workout_exercises,
    _sync_programs_with_real_workouts,
    _parse_dashboard_preferences,
)
from services.user_service import (
    get_user_by_username,
    get_user_by_id,
    create_user,
    update_user_profile,
    get_all_users,
)
from services.stats_service import (
    calculate_stats,
    generate_split,
    get_personal_records,
    get_top_progress,
)

# Modüler Router'lar
from routers.auth import router as auth_router
from routers.users import router as users_router
from routers.workouts import router as workouts_router
from routers.nutrition import router as nutrition_router
from routers.exercises import router as exercises_router
from routers.admin import router as admin_router
from routers.progress import router as progress_router
from routers.expert import router as expert_router

# FastAPI Uygulaması
app = FastAPI(title="Hypertrophy-X API", version="4.0")

# Middleware Katmanı
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials="*" not in CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(CacheControlMiddleware)
app.add_middleware(AuthRateLimitMiddleware)
log.info("Middleware katmanı aktif: CORS + Cache-Control + İstek Loglama + Güvenlik Başlıkları + Giriş Limiti")

# Router Kayıtları
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(workouts_router)
app.include_router(nutrition_router)
app.include_router(exercises_router)
app.include_router(admin_router)
app.include_router(progress_router)
app.include_router(expert_router)


# ═══════════════════════════════════════════════
# SAĞLIK KONTROLÜ — Monitoring için
# ═══════════════════════════════════════════════
@app.get("/api/health")
def health_check():
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok", "db": "ok", "version": "5.0"}
    except Exception as e:
        return {"status": "degraded", "db": "error", "detail": str(e)}


# ═══════════════════════════════════════════════
# STATIC DOSYALAR + SPA CATCH-ALL
# ÖNEMLİ: StaticFiles mount'u her şeyi yakalar. Bu yüzden SPA route'ları
# mount'tan ÖNCE bir APIRouter içine alınıyor — böylece /dashboard,
# /nutrition vb. statik dosya araması yapmadan doğrudan index.html döner.
# API istekleri ve gerçek dosyalar (css/js/img) mount tarafından sunulur.
# ═══════════════════════════════════════════════
SPA_PAGES = {
    "dashboard", "workout", "history", "analyze", "progress",
    "nutrition", "profile", "admin", "admin-overview", "admin-users",
    "admin-workouts", "admin-diagnostics", "custom-program", "app",
    "db-management", "db-overview", "db-terminal", "db-migration",
    "db-tables", "db-maintenance", "",
}

spa_router = APIRouter()


@spa_router.get("/")
def spa_root():
    return FileResponse("static/index.html")


STATIC_DIR = Path(__file__).parent / "static"


@app.get("/static/{filename}")
@app.get("/{filename}")
def serve_static_file(filename: str):
    file_path = STATIC_DIR / filename
    if file_path.is_file():
        return FileResponse(file_path)
    if filename in SPA_PAGES:
        return FileResponse("static/index.html")
    raise HTTPException(status_code=404, detail="Not Found")


@app.get("/{path:path}")
def serve_spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=405, detail="Not Found")
    first = path.split("/")[0]
    if first in SPA_PAGES:
        return FileResponse("static/index.html")
    raise HTTPException(status_code=404, detail="Not Found")


app.include_router(spa_router)


# ═══════════════════════════════════════════════
# BAŞLATMA
# ═══════════════════════════════════════════════
@app.on_event("startup")
async def on_startup():
    validate_runtime_configuration()
    init_db()
    log.info("Hypertrophy-X v4.0 hazır. Ortam: %s", APP_ENV)
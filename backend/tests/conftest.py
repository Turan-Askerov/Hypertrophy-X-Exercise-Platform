import os
import sys
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Backend dizinini sys.path'e ekle
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Test için geçici izole veritabanı yolu ve ortam değişkenleri ayarla
TEST_DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEST_DB_PATH = TEST_DB_FILE.name
TEST_DB_FILE.close()

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = ""
os.environ["DB_PATH"] = TEST_DB_PATH
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "testadminpass123"
os.environ["JWT_SECRET"] = "super-secret-jwt-key-for-testing-hypertrophy-x-32chars"

import main

# Test veritabanını başlat
main.DB_PATH = TEST_DB_PATH
main.init_db()


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Test oturumu öncesi DB oluşturur, test bitince temizler."""
    main.DB_PATH = TEST_DB_PATH
    main.init_db()
    yield
    # Oturum bittiğinde geçici test veritabanını sil
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass


@pytest.fixture
def client():
    """FastAPI TestClient nesnesi sağlar."""
    return TestClient(main.app)


@pytest.fixture
def auth_headers(client):
    """Testler için kayıtlı bir kullanıcı ve yetkili Authorization header'ı sağlar."""
    username = "testathlete"
    password = "AthletePassword123!"
    # Kayıt ol veya varsa giriş yap
    client.post("/api/auth/register", json={
        "username": username,
        "password": password,
        "email": "testathlete@example.com"
    })
    res = client.post("/api/auth/login", json={
        "username": username,
        "password": password
    })
    token = res.json().get("token")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture
def admin_headers(client):
    """Admin yetkili Authorization header'ı sağlar."""
    res = client.post("/api/auth/login", json={
        "username": os.environ["ADMIN_USERNAME"],
        "password": os.environ["ADMIN_PASSWORD"]
    })
    token = res.json().get("token")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

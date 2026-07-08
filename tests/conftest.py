import os
import sys
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test environment secrets
os.environ["JWT_SECRET"] = "test_jwt_secret_must_be_thirty_two_bytes_long_minimum"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "test_razorpay_secret"
os.environ["DATABASE_URL"] = "sqlite:///./test.db"

# Import system packages
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Base

# Setup in-memory SQLite database for test runs
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    if os.path.exists("./test.db"):
        try:
            os.remove("./test.db")
        except Exception:
            pass

@pytest.fixture(scope="function", autouse=True)
def override_db(monkeypatch):
    import main
    import database
    # Monkeypatch SessionLocal to use TestingSessionLocal in both modules
    monkeypatch.setattr(main, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    yield

@pytest.fixture(scope="function")
def db_session(override_db):
    session = TestingSessionLocal()
    yield session
    session.close()

@pytest.fixture(scope="function")
def client(override_db):
    from main import app
    with TestClient(app) as test_client:
        yield test_client

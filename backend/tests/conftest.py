"""
Pytest configuration and shared fixtures for the KhmerDub Studio backend.

Provides:
* Backend path setup so the ``app.*`` package imports cleanly.
* Test environment variables (SQLite in-memory database, test Gemini key, etc.)
  that are set before application modules are imported.
* Stubs for optional/heavy modules (``google.generativeai``, ``yt_dlp``, ``cv2``,
  ``numpy``, ``PIL``, etc.) so the application imports in a minimal test env.
* Synthesis of the missing ``app.db`` package so ``app.main``'s
  ``from .db.init_db import init_db`` resolves at import time.
* SQLAlchemy engine / session fixtures backed by an in-memory SQLite database.
* FastAPI ``TestClient`` whose ``get_db`` dependency is overridden to the test
  session.
* Mock Gemini model / generative AI fixtures and service fixtures.
"""

import os
import sys
import types
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Path setup: make the backend directory importable as the ``app`` package.
# ---------------------------------------------------------------------------
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# ---------------------------------------------------------------------------
# Test environment variables (set before app modules are imported so that
# pydantic Settings and the SQLAlchemy engines pick them up).
# ---------------------------------------------------------------------------
os.environ["DB_URL"] = "sqlite:///:memory:"
os.environ["GEMINI_API_KEY"] = "test-api-key"
os.environ["GEMINI_MODEL"] = "gemini-1.5-flash"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["STORAGE_PATH"] = "./storage"
os.environ.setdefault("HF_TOKEN", "test-hf-token")

# ---------------------------------------------------------------------------
# Stub helpers for optional / heavy modules not present in the test env.
# ---------------------------------------------------------------------------
def _install_stub(name, attrs=None):
    """Install (or replace) a module stub in ``sys.modules`` and return it."""
    mod = types.ModuleType(name)
    if attrs:
        for key, value in attrs.items():
            setattr(mod, key, value)
    sys.modules[name] = mod
    return mod

# ``google`` parent package + ``google.generativeai`` stub. The glossary service
# does ``try: import google.generativeai as genai except ImportError: genai =
# None``; stubbing it keeps the import path clean while tests mock the model.
_genai_stub = _install_stub(
    "google.generativeai",
    {
        "configure": MagicMock(),
        "GenerativeModel": MagicMock(),
        "__version__": "0.0.0-stub",
    },
)
if "google" not in sys.modules:
    _install_stub("google", {})

# Stub modules used at module top by application code but not required for tests.
_HEAVY_STUBS = (
    "yt_dlp",
    "cv2",
    "apscheduler",
    "celery",
    "redis",
    "demucs",
    "faster_whisper",
    "pyannote",
    "speechbrain",
    "torchaudio",
    "torch",
    "ffmpeg",
)


def _make_stub_module(name):
    mod = types.ModuleType(name)
    mod.__getattr__ = lambda attr: MagicMock()  # type: ignore[method-assign]
    return mod


for _stub_name in _HEAVY_STUBS:
    if _stub_name not in sys.modules:
        _install_stub(_stub_name)

for _stub_name, _attrs in (
    ("numpy", {"__version__": "0.0.0-stub"}),
    ("PIL", {"Image": MagicMock()}),
):
    try:
        __import__(_stub_name)
    except Exception:
        _install_stub(_stub_name, _attrs)

# ---------------------------------------------------------------------------
# Synthesize the missing ``app.db`` package. ``app/main.py`` imports
# ``from .db.init_db import init_db`` but no ``app/db`` package exists in the
# tree. Synthesize it here so ``import app.main`` (used by the routing tests)
# works without touching application source.
# ---------------------------------------------------------------------------
def _noop_init_db():
    pass


_app_db_pkg = types.ModuleType("app.db")
_app_db_pkg.__path__ = []
_app_db_pkg.init_db = _noop_init_db
sys.modules["app.db"] = _app_db_pkg

_app_db_initdb = types.ModuleType("app.db.init_db")
_app_db_initdb.init_db = _noop_init_db
sys.modules["app.db.init_db"] = _app_db_initdb

# ---------------------------------------------------------------------------
# Application imports (performed after path / env / stub setup).
# ---------------------------------------------------------------------------
from app.config import settings  # noqa: E402
from app.models import Base, SessionLocal, get_db  # noqa: E402

# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------
TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def db_engine():
    """Session-scoped in-memory SQLite engine shared by all tests."""
    engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Transaction-scoped SQLAlchemy session, rolled back after each test."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    """FastAPI TestClient whose ``get_db`` dependency uses the test session."""

    def override_get_db():
        yield db_session

    from app.main import app  # noqa: E402  (imported lazily; app.db is stubbed above)

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Mock Gemini / generative AI fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_model():
    """A MagicMock standing in for a Gemini ``GenerativeModel``."""
    model = MagicMock()
    model.generate_content = MagicMock()
    return model


@pytest.fixture
def mock_genai(mock_model):
    """Patch the glossary service's ``genai`` reference so Gemini calls are
    mocked without the real ``google-generativeai`` package."""
    with patch("app.services.entity_glossary_service.genai", _genai_stub), patch(
        "app.services.entity_glossary_service.genai.GenerativeModel",
        return_value=mock_model,
    ):
        yield mock_model


# ---------------------------------------------------------------------------
# Service fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def glossary_service():
    from app.services.entity_glossary_service import EntityGlossaryService

    return EntityGlossaryService(api_key="test-key")


@pytest.fixture
def thumbnail_service():
    from app.services.thumbnail_ai_service import ThumbnailAIService

    return ThumbnailAIService()


@pytest.fixture
def overlay_service():
    from app.services.thumbnail_ai_service import OverlayService

    return OverlayService()

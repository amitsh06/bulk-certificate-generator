import pytest
from fastapi.testclient import TestClient

from app import database
from app.config import get_settings


def _make_client(tmp_path, monkeypatch, mode: str) -> TestClient:
    monkeypatch.setenv("CERTGEN_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("CERTGEN_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("CERTGEN_PROCESSING_MODE", mode)
    get_settings.cache_clear()
    database.configure_engine(get_settings().database_url)

    from app.main import create_app

    return TestClient(create_app())


@pytest.fixture
def client(tmp_path, monkeypatch):
    """App that processes jobs inside the request, so tests are deterministic."""
    with _make_client(tmp_path, monkeypatch, "sync") as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def background_client(tmp_path, monkeypatch):
    """App that processes jobs on worker threads, like production."""
    with _make_client(tmp_path, monkeypatch, "background") as c:
        yield c
    get_settings.cache_clear()


def job_payload(names, **overrides):
    payload = {
        "title": "Python for Data Science Bootcamp",
        "issued_by": "Aereo Academy",
        "issued_on": "2026-10-08",
        "recipients": [{"name": n, "email": f"{n.split()[0].lower()}@example.com"} for n in names],
    }
    payload.update(overrides)
    return payload

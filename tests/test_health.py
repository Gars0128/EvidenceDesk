import psycopg
import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(db, "initialize", lambda: None)
    with TestClient(app) as client:
        yield client


def test_ready_database(client, monkeypatch):
    monkeypatch.setattr(db, "check_readiness", lambda: True)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_missing_schema(client, monkeypatch):
    monkeypatch.setattr(db, "check_readiness", lambda: False)
    assert client.get("/api/health").status_code == 503


def test_unavailable_database_hides_credentials(client, monkeypatch):
    def unavailable():
        raise psycopg.OperationalError("password=private-secret")

    monkeypatch.setattr(db, "check_readiness", unavailable)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}
    assert "private-secret" not in response.text


def test_initialization_failure_prevents_startup(monkeypatch):
    def fail():
        raise psycopg.OperationalError("Cannot initialize database")

    monkeypatch.setattr(db, "initialize", fail)
    with pytest.raises(psycopg.OperationalError):
        with TestClient(app):
            pass

from fastapi.testclient import TestClient

from app import db
from app.main import app


def test_home_and_static_assets_are_served(monkeypatch):
    monkeypatch.setattr(db, "initialize", lambda: None)
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "text/html" in home.headers["content-type"]
        assert all(f'id="{name}"' in home.text for name in ("upload-form", "question-form", "answer", "retrieval-panel"))
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/style.css").status_code == 200

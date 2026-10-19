from io import BytesIO
import os
import json

import psycopg
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", help="Run tests against an isolated PostgreSQL test database")


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires an isolated PostgreSQL test database")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--integration"):
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Pass --integration and set TEST_DATABASE_URL"))


@pytest.fixture
def postgres(monkeypatch):
    """Use a disposable PostgreSQL database, never the application's database."""
    from app import db

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("Set TEST_DATABASE_URL to an isolated database ending in _test")
    with psycopg.connect(url) as connection:
        if not connection.info.dbname.endswith("_test"):
            pytest.fail("Refusing to modify a database whose name does not end in _test")
    monkeypatch.setenv("DATABASE_URL", url)
    db.initialize()
    with db.connect() as connection:
        connection.execute("TRUNCATE documents CASCADE")
    yield
    with db.connect() as connection:
        connection.execute("TRUNCATE documents CASCADE")


@pytest.fixture
def fake_ollama(monkeypatch):
    """Replace only Ollama's HTTP boundary; retrieval and SQL stay real."""
    import httpx2 as httpx
    from app import embeddings

    real_client = httpx.Client
    state = {
        "requests": [], "error": None, "override": None, "error_after": 0,
        "vector_for": lambda text: [1.0] + [0.0] * 767,
    }

    def respond(request):
        body = json.loads(request.content)
        state["requests"].append(body)
        error = state["error"] if len(state["requests"]) > state["error_after"] else None
        if error == "connection":
            raise httpx.ConnectError("provider-private-secret", request=request)
        if error == "timeout":
            raise httpx.ReadTimeout("provider-private-secret", request=request)
        if error:
            return httpx.Response(error, json={"error": "provider-private-secret"})
        if state["override"] is not None:
            return httpx.Response(200, json=state["override"])
        return httpx.Response(200, json={
            "model": "embeddinggemma:300m",
            "embeddings": [state["vector_for"](text) for text in body["input"]],
        })

    monkeypatch.setattr(embeddings.httpx, "Client", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(respond),
    ))
    return state


@pytest.fixture
def make_pdf():
    def build(texts, password=None):
        writer = PdfWriter()
        for text in texts:
            page = writer.add_blank_page(width=300, height=200)
            if text:
                font = DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                })
                page[NameObject("/Resources")] = DictionaryObject({
                    NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
                })
                escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                stream = DecodedStreamObject()
                stream.set_data(f"BT /F1 12 Tf 20 100 Td ({escaped}) Tj ET".encode("ascii"))
                page.replace_contents(stream)
        if password:
            writer.encrypt(password)
        output = BytesIO()
        writer.write(output)
        return output.getvalue()
    return build

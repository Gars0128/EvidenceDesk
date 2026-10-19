from io import BytesIO

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

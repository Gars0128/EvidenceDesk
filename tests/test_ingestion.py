import pytest

from app import config
from app.ingestion import ProcessingError, clean_filename, extract_pages, split_text


def test_filename_drops_paths_and_control_characters():
    assert clean_filename("C:\\fakepath\\trip\x00.TXT") == ("trip.TXT", "txt")
    assert clean_filename("../../hotel.pdf") == ("hotel.pdf", "pdf")


@pytest.mark.parametrize("filename", [None, "", "x" * 256 + ".txt"])
def test_invalid_filename(filename):
    with pytest.raises(ProcessingError, match="filename"):
        clean_filename(filename)


def test_unsupported_format():
    with pytest.raises(ProcessingError, match="Only PDF"):
        clean_filename("trip.exe")


def test_utf8_bom_and_newlines():
    pages = extract_pages("\ufeffОтель\r\nHotel\rNext".encode("utf-8"), "txt")
    assert pages[0].number == 1
    assert pages[0].text == "Отель\nHotel\nNext"


@pytest.mark.parametrize("data,code", [(b"\xff", "invalid_encoding"), (b"a\x00b", "invalid_text"), (b" \n", "no_text")])
def test_invalid_txt(data, code):
    with pytest.raises(ProcessingError) as exc:
        extract_pages(data, "txt")
    assert exc.value.code == code


def test_pdf_preserves_blank_and_numbered_pages(make_pdf):
    pages = extract_pages(make_pdf(["Hotel Aurora", None, "Free cancellation"]), "pdf")
    assert [p.number for p in pages] == [1, 2, 3]
    assert "Hotel Aurora" in pages[0].text
    assert pages[1].text == ""
    assert "Free cancellation" in pages[2].text


@pytest.mark.parametrize("data", [b"not a pdf", b"%PDF-1.7\nbroken\n%%EOF"])
def test_corrupt_pdf(data):
    with pytest.raises(ProcessingError) as exc:
        extract_pages(data, "pdf")
    assert exc.value.code == "invalid_pdf"


def test_pdf_without_text(make_pdf):
    with pytest.raises(ProcessingError, match="OCR"):
        extract_pages(make_pdf([None]), "pdf")


def test_encrypted_pdf(make_pdf):
    with pytest.raises(ProcessingError) as exc:
        extract_pages(make_pdf(["Secret"], password="secret"), "pdf")
    assert exc.value.code == "encrypted_pdf"


def test_pdf_page_limit(make_pdf, monkeypatch):
    monkeypatch.setattr(config, "MAX_PDF_PAGES", 1)
    with pytest.raises(ProcessingError) as exc:
        extract_pages(make_pdf(["One", "Two"]), "pdf")
    assert exc.value.code == "page_limit"


@pytest.mark.parametrize("kind", ["txt", "pdf"])
def test_text_limit(kind, make_pdf, monkeypatch):
    monkeypatch.setattr(config, "MAX_TEXT_CHARS", 3)
    data = b"abcd" if kind == "txt" else make_pdf(["abcd"])
    with pytest.raises(ProcessingError) as exc:
        extract_pages(data, kind)
    assert exc.value.code == "text_limit"


def test_chunk_overlap_and_full_coverage():
    text = "0123456789abcdefghij"
    chunks = split_text(text, size=8, overlap=3)
    assert chunks == ["01234567", "56789abc", "abcdefgh", "fghij"]
    reconstructed = chunks[0] + "".join(chunk[3:] for chunk in chunks[1:])
    assert reconstructed == text


def test_short_and_empty_chunks():
    assert split_text(" short ") == ["short"]
    assert split_text(" \n") == []
    assert split_text("a" * 1200) == ["a" * 1200]


@pytest.mark.parametrize("size,overlap", [(0, 0), (5, 5), (5, -1)])
def test_invalid_chunk_settings(size, overlap):
    with pytest.raises(ValueError):
        split_text("text", size, overlap)

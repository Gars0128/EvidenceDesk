"""Extract page-aware text and split it into overlapping character chunks."""

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath

from pypdf import PdfReader

from app import config


class ProcessingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Page:
    number: int
    text: str


def clean_filename(filename: str | None) -> tuple[str, str]:
    name = PurePosixPath((filename or "").replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    if not name or len(name) > 255:
        raise ProcessingError("invalid_filename", "A filename of 1 to 255 characters is required.")
    kind = PurePosixPath(name).suffix.lower().lstrip(".")
    if kind not in {"pdf", "txt"}:
        raise ProcessingError("unsupported_format", "Only PDF and UTF-8 TXT files are supported.")
    return name, kind


def extract_pages(data: bytes, kind: str) -> list[Page]:
    if kind == "txt":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ProcessingError("invalid_encoding", "TXT files must use UTF-8 encoding.") from None
        if "\x00" in text:
            raise ProcessingError("invalid_text", "TXT files must not contain null bytes.")
        pages = [Page(1, text.replace("\r\n", "\n").replace("\r", "\n"))]
    elif kind == "pdf":
        pages = _extract_pdf(data)
    else:
        raise ProcessingError("unsupported_format", "Only PDF and UTF-8 TXT files are supported.")

    if sum(len(page.text) for page in pages) > config.MAX_TEXT_CHARS:
        raise ProcessingError("text_limit", "The extracted text exceeds the configured character limit.")
    if not any(page.text.strip() for page in pages):
        message = (
            "No text was found. Upload a PDF with a text layer; OCR is not supported."
            if kind == "pdf" else "The TXT file contains no readable text."
        )
        raise ProcessingError("no_text", message)
    return pages


def _extract_pdf(data: bytes) -> list[Page]:
    if not data.startswith(b"%PDF-"):
        raise ProcessingError("invalid_pdf", "The file is not a readable PDF.")
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ProcessingError("encrypted_pdf", "Encrypted PDFs are not supported. Upload an unencrypted copy.")
        if len(reader.pages) > config.MAX_PDF_PAGES:
            raise ProcessingError("page_limit", "The PDF exceeds the configured page limit.")
        pages = []
        total = 0
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").replace("\x00", "")
            total += len(text)
            if total > config.MAX_TEXT_CHARS:
                raise ProcessingError("text_limit", "The extracted text exceeds the configured character limit.")
            pages.append(Page(number, text))
        return pages
    except ProcessingError:
        raise
    except Exception as exc:
        # Malformed PDFs can trigger several parser exception types.
        raise ProcessingError("invalid_pdf", "The PDF is damaged or could not be read.") from exc


def split_text(text: str, size: int = config.CHUNK_SIZE, overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    if not 0 <= overlap < size:
        raise ValueError("Chunk overlap must be non-negative and smaller than chunk size.")
    text = text.strip()
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = end - overlap
    return chunks

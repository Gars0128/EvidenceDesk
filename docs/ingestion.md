# PDF/TXT ingestion

## What is implemented

- `POST /api/documents`: upload one PDF or UTF-8 TXT file as multipart field `file`.
- `GET /api/documents`: list documents, newest first, with statuses and counts.
- SHA-256 duplicate detection, including renamed files and concurrent uploads.
- Page-aware extraction and overlapping text chunks persisted in PostgreSQL.
- Persistent processing errors and recovery of interrupted processing on startup.

This stage does not implement retrieval, embeddings, answers, or a frontend.
Use the Swagger interface at http://localhost:8000/docs to upload a file.

## Try it

From the repository root, start the current image:

```powershell
docker compose up --build -d --wait
```

Upload a local document (replace the example path):

```powershell
curl.exe -i -F "file=@C:/path/to/trip.txt" http://localhost:8000/api/documents
Invoke-RestMethod "http://localhost:8000/api/documents?limit=20&offset=0"
```

On macOS/Linux use `curl` instead of `curl.exe`. A successful upload returns HTTP
201 and a document object with these fields:

| Field | Meaning |
| --- | --- |
| `id` | UUID of the document |
| `filename` | Display name with path components and control characters removed |
| `file_type` | `pdf` or `txt` |
| `size_bytes` | Original file size |
| `sha256` | Hash of the original bytes |
| `status` | `processing`, `ready`, or `error` |
| `error_message` | Human-readable error, or null |
| `created_at` | Timestamp with timezone |
| `page_count` | Number of saved pages |
| `chunk_count` | Number of saved text chunks |

The list endpoint returns an array of the same objects. `limit` is 1..100 and
`offset` is non-negative. Defaults are 20 and 0.

## Processing and storage

1. Validate filename, extension, size, and non-empty contents.
2. Hash the original bytes and insert a `processing` record in `documents`.
3. Extract PDF text page by page, or decode TXT using UTF-8 (BOM accepted).
4. Split each page separately into chunks of up to 1,200 characters with a
   200-character overlap. Trim surrounding whitespace and omit empty chunks.
5. Save all pages/chunks and change status to `ready` in one transaction.
6. On a parsing failure, persist `error` and a readable message separately.

PDF page numbers start at 1 and preserve blank pages. TXT uses page 1. Chunks
reference pages, which reference documents. Deleting a document at the database
level cascades to its pages/chunks. There is no delete endpoint in this stage.
Raw files are not retained; the multipart upload may use temporary disk storage,
and its file handle is closed after processing. Only metadata and extracted text
are stored persistently.

The unique hash constraint prevents duplicate records even during concurrent
requests. Re-uploading an errored document also returns a duplicate response;
automatic retries and a retry endpoint are not implemented yet.

The initial schema lives in `app/schema.sql`. Migration
`app/migrations/002_documents.sql` adds the ingestion tables. Startup applies each
registered migration once and records its version in `schema_version`. SQL changes
and version records commit together. Startup uses a transaction-level advisory lock
to serialize schema initialization.

This MVP runs one API process, without a queue. Upload requests wait for processing
in a worker thread. On restart, remaining `processing` records become `error` with
an interruption message. Do not run multiple API instances: one instance's startup
recovery could mark another instance's in-flight document as interrupted.

## Limits

Configure these values in `.env` for Docker Compose, or environment variables for
local Python. Recreate the API container after changing them.

| Variable | Default |
| --- | --- |
| `MAX_UPLOAD_BYTES` | 10485760 (10 MiB) |
| `MAX_PDF_PAGES` | 300 |
| `MAX_TEXT_CHARS` | 2000000 |

Only `.pdf` and `.txt` extensions are accepted, case-insensitively. MIME headers
are not trusted as proof of file format: PDFs are parsed, and TXT must decode as
UTF-8 without null bytes. Encrypted PDFs are rejected. Image-only/blank PDFs
receive a no-text error; OCR is not supported. Complex PDF layouts may yield text
in an imperfect reading order.

The byte limit is per file and is checked after the framework's multipart parser.
Page/text limits do not impose a hard parser CPU or memory sandbox. This is a
local single-user application, not an internet-facing upload service.

## Errors

| HTTP | Code | Behavior |
| --- | --- | --- |
| 409 | `duplicate_document` | Existing document returned in `detail.document` |
| 413 | `file_too_large` | No document created |
| 415 | `unsupported_format` | No document created |
| 422 | `empty_file`, `invalid_filename` | No document created |
| 422 | `invalid_pdf`, `encrypted_pdf`, `invalid_encoding`, `invalid_text`, `no_text`, `page_limit`, `text_limit` | Document retained with status `error` |
| 500 | `processing_failed` | Unexpected processing failure; details logged server-side |
| 503 | `database_unavailable` | Database operation failed; no credentials returned |

Application errors use this shape:

```json
{
  "detail": {
    "code": "invalid_encoding",
    "message": "TXT files must use UTF-8 encoding.",
    "document": {
      "id": "...",
      "status": "error"
    }
  }
}
```

The document above is abbreviated; the real response includes all document fields.
FastAPI's request-validation errors (such as a missing file or invalid pagination)
use its standard `detail` array instead. If a database outage prevents saving an
error status, the record may remain `processing` until startup recovery.

## Tests

Install dependencies and run the database-independent suite:

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
```

For real database tests, create a dedicated database once:

```powershell
docker compose exec db createdb -U evidencedesk evidencedesk_ingestion_test
$env:TEST_DATABASE_URL = "postgresql://evidencedesk:evidencedesk_local@127.0.0.1:55432/evidencedesk_ingestion_test"
.\.venv\Scripts\python -m pytest -q --integration -p no:cacheprovider
```

Match the connection string to your `.env` settings. Integration tests explicitly
truncate documents/pages/chunks in the configured test database. They refuse a
database name that does not end in `_test`. Never point them at a database with
data you want to keep. The normal `evidencedesk` database is not used by these tests.

### Verification record — October 19, 2026

- 43 database-independent tests passed.
- Six real PostgreSQL integration tests passed (49 tests in the full run).
- Covered page-aware PDF ingestion, Unicode TXT, missing/empty/oversized uploads,
  corrupt/encrypted/no-text PDFs, encoding and extraction limits, chunk overlap,
  explicit duplicates, and recovery after an invalid upload.
- Verified atomic rollback of pages/chunks, concurrent duplicate protection,
  cascade deletion, pagination, and restart recovery.
- Rebuilt Docker services and checked real HTTP requests: TXT upload (201),
  renamed duplicate (409), corrupt PDF (422 with persisted error), listing,
  readiness, and generated OpenAPI. Removed only temporary smoke-test records.

## References

- [FastAPI file uploads](https://fastapi.tiangolo.com/tutorial/request-files/)
- [pypdf reader](https://pypdf.readthedocs.io/en/stable/modules/PdfReader.html)

ALTER TABLE chunks ADD COLUMN embedding vector(1536);
ALTER TABLE documents
    ADD COLUMN embedding_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (embedding_status IN ('pending', 'ready', 'error')),
    ADD COLUMN embedding_error TEXT,
    ADD COLUMN embedding_model TEXT;

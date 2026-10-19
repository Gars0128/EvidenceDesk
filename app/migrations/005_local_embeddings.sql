-- Embeddings are derived data. Keep every document, page, and text chunk.
-- OpenAI vectors cannot be reused with a different model or dimensionality.
ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(768) USING NULL::vector(768);
UPDATE documents SET embedding_status = 'pending', embedding_model = NULL, embedding_error = NULL;

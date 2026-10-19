ALTER TABLE chunks ADD COLUMN search_vector TSVECTOR GENERATED ALWAYS AS (
    to_tsvector('english'::regconfig, text)
    || to_tsvector('russian'::regconfig, text)
    || to_tsvector('simple'::regconfig, text)
) STORED;

CREATE INDEX chunks_search_vector_idx ON chunks USING gin (search_vector);

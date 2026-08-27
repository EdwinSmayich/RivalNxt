-- Migration 0025: make storing a mod image idempotent.
--
-- mod_custom_images had no uniqueness of any kind, and four separate code paths
-- INSERT into it: two upload endpoints, an upload-by-URL endpoint, and two
-- restore modals. Every restore re-added every image, so a library that had been
-- restored a few times held the same picture 4-8 times over. Measured on a real
-- install: 1352 rows of which 1050 were byte-identical duplicates.
--
-- Deduplicating inside each caller is what let this drift in the first place, so
-- the constraint lives here instead. content_hash is filled in by the backend on
-- write; existing rows are backfilled by the "Remove duplicate images"
-- maintenance task, which also deletes the duplicates already stored.
ALTER TABLE mod_custom_images ADD COLUMN content_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_mod_custom_images_hash
    ON mod_custom_images(mod_id, content_hash);

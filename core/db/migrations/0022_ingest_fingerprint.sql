-- Migration 0022: remember what was already ingested, so re-runs can skip it.
--
-- "Rebuild Local Downloads" re-extracted and re-parsed every archive on every
-- run with no notion of what had already been done. On a 16 GB library that is
-- minutes of decompression to rediscover facts already in pak_assets.
--
-- The fingerprint is size + mtime of the archive, not a content hash: it costs
-- one stat() per download instead of reading 16 GB, and any edit that changes
-- the file changes at least one of the two. A hash is available separately in
-- file_md5 for the cases that genuinely need content identity.
ALTER TABLE local_downloads ADD COLUMN assets_fingerprint TEXT;

CREATE INDEX IF NOT EXISTS idx_local_downloads_assets_fingerprint
    ON local_downloads(assets_fingerprint);

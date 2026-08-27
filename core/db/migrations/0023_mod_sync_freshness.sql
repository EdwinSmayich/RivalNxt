-- Migration 0023: record when each mod was last pulled from the Nexus API.
--
-- "Initial Database Build" re-synced every linked mod on every run: three HTTP
-- requests each (info, files, changelogs) plus a fixed sleep between mods. With
-- 128 linked mods that is ~380 requests and over a minute of pure sleeping,
-- repeated in full even when nothing upstream had changed.
--
-- mods.updated_at already exists but means "when the mod was last updated on
-- Nexus" — it says nothing about when this install last asked. That is the
-- question a skip has to answer, so it needs its own column.
ALTER TABLE mods ADD COLUMN last_synced_at TEXT;

CREATE INDEX IF NOT EXISTS idx_mods_last_synced_at ON mods(last_synced_at);

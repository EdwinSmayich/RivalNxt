-- Create tables for storing Marvel Rivals character and skin IDs
-- Migration 0012: Characters and Skins

BEGIN;

-- Characters table
CREATE TABLE IF NOT EXISTS characters (
    character_id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_characters_name ON characters(name);

-- Skins table
CREATE TABLE IF NOT EXISTS skins (
    skin_id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,
    variant TEXT NOT NULL,
    name TEXT NOT NULL,
    FOREIGN KEY (character_id) REFERENCES characters(character_id) ON DELETE CASCADE,
    UNIQUE (character_id, variant)
);

CREATE INDEX IF NOT EXISTS idx_skins_character ON skins(character_id);
CREATE INDEX IF NOT EXISTS idx_skins_variant ON skins(variant);

COMMIT;

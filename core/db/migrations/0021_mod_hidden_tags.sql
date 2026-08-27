-- Migration 0021: let users suppress auto-detected tags per mod.
--
-- Tags shown on a mod come from two places: user-created rows in
-- mod_custom_tags, and tags derived from Nexus metadata / pak extraction. Only
-- the first kind was removable, so a wrong character or skin tag produced by
-- extraction was stuck on the mod permanently with no way to correct it.
--
-- Deleting the derived tag at its source is not an option: it is recomputed by
-- extraction and overwritten on the next Nexus sync. This table records a
-- suppression instead, which survives both.
--
-- No foreign key to mods(mod_id) on purpose: tags are also shown for local mods
-- addressed by a synthetic negative id that has no row in mods, and hiding a tag
-- must not require materialising a placeholder mod.
CREATE TABLE IF NOT EXISTS mod_hidden_tags (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_id    INTEGER NOT NULL,
    tag       TEXT    NOT NULL COLLATE NOCASE,
    hidden_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(mod_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_mod_hidden_tags_mod_id ON mod_hidden_tags(mod_id);

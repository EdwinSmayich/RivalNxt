-- Migration: Add custom images table for user-uploaded mod images
-- This table stores custom images uploaded by users for mods
-- Images are stored as base64-encoded strings

CREATE TABLE IF NOT EXISTS mod_custom_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_id INTEGER NOT NULL,
    image_data TEXT NOT NULL,
    filename TEXT,
    mime_type TEXT,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(mod_id) REFERENCES mods(mod_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mod_custom_images_mod_id ON mod_custom_images(mod_id);
CREATE INDEX IF NOT EXISTS idx_mod_custom_images_uploaded_at ON mod_custom_images(uploaded_at);

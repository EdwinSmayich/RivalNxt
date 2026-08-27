-- Migration 0024: let the user decide the order of a mod's images.
--
-- Images were shown, and the card preview was chosen, purely by row id — i.e.
-- upload order. There was no way to promote a better screenshot to the front,
-- and the preview endpoint literally selected `HAVING id = MIN(id)`.
--
-- Backfilled from id so every existing mod keeps exactly the order it has
-- today; nothing visibly changes until the user reorders something.
ALTER TABLE mod_custom_images ADD COLUMN sort_order INTEGER;

UPDATE mod_custom_images SET sort_order = id WHERE sort_order IS NULL;

CREATE INDEX IF NOT EXISTS idx_mod_custom_images_order
    ON mod_custom_images(mod_id, sort_order);

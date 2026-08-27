-- Migration 0027: let a mod's Nexus picture be removed from its image list.
--
-- The gallery mixes two sources: mods.picture_url (one image, owned by Nexus)
-- and mod_custom_images (the user's own rows). Only the second kind had a delete
-- button, so on any mod installed from the site the Nexus picture was permanent
-- -- it sat first in the list and there was no way to be rid of it.
--
-- A flag on `mods` would not survive: that row is upserted wholesale by the
-- Nexus metadata sync, so the next refresh would silently bring the picture
-- back. A separate table is never written by the sync, which is the whole point.
CREATE TABLE IF NOT EXISTS mod_hidden_nexus_image (
    mod_id     INTEGER PRIMARY KEY,
    hidden_at  TEXT NOT NULL
);

-- Migration 0026: let a chosen image override the Nexus thumbnail.
--
-- The mod card picked its image as "Nexus picture_url > custom image", so a mod
-- linked with Assign Mod ID always showed the picture from the website and never
-- looked at the user's own images at all. Starring one appeared to do nothing.
--
-- Ordering alone could not express this: "first custom image" is a default, not
-- a decision, and it must not silently outrank the Nexus artwork for the many
-- mods where nobody ever chose anything. This flag records an actual choice.
ALTER TABLE mod_custom_images ADD COLUMN is_preview INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_mod_custom_images_preview
    ON mod_custom_images(mod_id, is_preview);

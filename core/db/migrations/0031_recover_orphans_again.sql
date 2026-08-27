-- Migration 0031: the same recovery as 0030, run once more.
--
-- 0030 reunited the images that were stranded at the time, but the assignment
-- path was still stranding new ones: moving a picture to the real mod id runs
-- before the Nexus sync creates that mods row, so the foreign key rejected it —
-- and a broad `except Exception` turned that rejection into a silent no-op.
-- Nothing appeared in the log, and the images stayed under the old key.
--
-- The insert-first fix in _migrate_local_mod_data stops it happening again.
-- This recovers whatever was stranded in between, on databases where 0030 has
-- already been marked as applied and will never run a second time.

DELETE FROM mod_custom_images
 WHERE mod_id < 0
   AND content_hash IS NOT NULL
   AND EXISTS (
       SELECT 1 FROM local_downloads l
        WHERE l.id = -mod_custom_images.mod_id
          AND l.mod_id IS NOT NULL
     )
   AND EXISTS (
       SELECT 1 FROM mod_custom_images dup
        JOIN local_downloads l2 ON l2.id = -mod_custom_images.mod_id
        WHERE dup.mod_id = l2.mod_id
          AND dup.content_hash = mod_custom_images.content_hash
     );

-- The mods row must exist before the foreign key will accept the move. It is
-- normally created by the metadata sync; a placeholder is enough here, and the
-- next sync fills in the real name.
INSERT OR IGNORE INTO mods (mod_id, game, name)
SELECT DISTINCT l.mod_id, 'marvelrivals', 'Mod ' || l.mod_id
  FROM mod_custom_images i
  JOIN local_downloads l ON l.id = -i.mod_id
 WHERE i.mod_id < 0 AND l.mod_id IS NOT NULL;

UPDATE mod_custom_images
   SET mod_id = (
       SELECT l.mod_id FROM local_downloads l
        WHERE l.id = -mod_custom_images.mod_id
   )
 WHERE mod_id < 0
   AND EXISTS (
       SELECT 1 FROM local_downloads l
        WHERE l.id = -mod_custom_images.mod_id
          AND l.mod_id IS NOT NULL
     );

DELETE FROM mod_custom_tags
 WHERE mod_id < 0
   AND EXISTS (
       SELECT 1 FROM local_downloads l
        WHERE l.id = -mod_custom_tags.mod_id
          AND l.mod_id IS NOT NULL
     )
   AND EXISTS (
       SELECT 1 FROM mod_custom_tags dup
        JOIN local_downloads l2 ON l2.id = -mod_custom_tags.mod_id
        WHERE dup.mod_id = l2.mod_id
          AND dup.tag = mod_custom_tags.tag COLLATE NOCASE
     );

UPDATE mod_custom_tags
   SET mod_id = (
       SELECT l.mod_id FROM local_downloads l
        WHERE l.id = -mod_custom_tags.mod_id
   )
 WHERE mod_id < 0
   AND EXISTS (
       SELECT 1 FROM local_downloads l
        WHERE l.id = -mod_custom_tags.mod_id
          AND l.mod_id IS NOT NULL
     );

-- A mod that now has pictures but no chosen one would show the Nexus cover
-- instead, replacing what the user was looking at.
UPDATE mod_custom_images
   SET is_preview = 1
 WHERE id IN (
       SELECT MIN(i.id) FROM mod_custom_images i
        WHERE NOT EXISTS (
            SELECT 1 FROM mod_custom_images p
             WHERE p.mod_id = i.mod_id AND p.is_preview = 1
          )
        GROUP BY i.mod_id
     );

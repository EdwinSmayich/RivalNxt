-- Migration 0030: reunite images and tags with mods that were linked later.
--
-- While a download has no Nexus id, anything the user attaches is stored against
-- the negated download id — the synthetic key the app uses in that state.
-- Assigning an id changed which key the app reads from without moving the rows,
-- so the pictures were still in the table and nothing looked for them. From the
-- user's side the Images tab simply emptied, at the moment they were told the
-- mod had been linked successfully.
--
-- Measured on a real library: 5 downloads, 31 images stranded this way.
--
-- Assignment now carries them across; this recovers the ones already stranded.
-- Only rows whose download is genuinely linked are touched, and a picture whose
-- content already exists under the real id is dropped rather than duplicated —
-- the same image often arrives again from the Nexus sync.

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

-- Same for tags, minus the ones the target already carries.
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

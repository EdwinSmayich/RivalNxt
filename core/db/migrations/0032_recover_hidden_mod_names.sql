-- Migration 0032: give back the names of mods that Nexus has hidden.
--
-- Every metadata sync used to overwrite a mod's whole row with whatever Nexus
-- answered. For a mod under moderation that answer is a status and nothing
-- else, so the name, the picture and the description were replaced with NULL
-- and the mod became a bare id in the list. One library had 33 of 200 like it.
--
-- upsert_mod_info no longer does that, which protects what is still there.
-- For what is already gone, the name can be had back: the files endpoint
-- refuses a hidden mod with
--
--     File currently not available. <title> (Mod ID: 4380) is under moderation
--
-- and that refusal is in mod_api_cache. The picture and the description are
-- not in it and cannot be recovered this way.
--
-- Only rows with no name are touched, only from a message that carries the
-- row's own id, and a message that yields nothing leaves the row as it was.
-- json_extract() raises on text that is not JSON, and a failed migration
-- stops the app from starting, so every use of it sits behind json_valid()
-- inside a CASE -- the one construct whose evaluation order SQLite promises.

UPDATE mods
   SET name = (
       SELECT CASE
                  WHEN NOT json_valid(c.payload) THEN NULL
                  WHEN json_extract(c.payload, '$.files.body.message') LIKE 'File currently not available. %'
                  THEN NULLIF(TRIM(substr(
                           json_extract(c.payload, '$.files.body.message'),
                           31,
                           instr(json_extract(c.payload, '$.files.body.message'),
                                 ' (Mod ID: ' || mods.mod_id || ') is ') - 31
                       )), '')
                  ELSE NULLIF(TRIM(substr(
                           json_extract(c.payload, '$.files.body.message'),
                           1,
                           instr(json_extract(c.payload, '$.files.body.message'),
                                 ' (Mod ID: ' || mods.mod_id || ') is ') - 1
                       )), '')
              END
         FROM mod_api_cache c
        WHERE c.mod_id = mods.mod_id
   )
 WHERE (name IS NULL OR TRIM(name) = '')
   AND mod_id > 0
   AND EXISTS (
       SELECT 1
         FROM mod_api_cache c
        WHERE c.mod_id = mods.mod_id
          AND CASE
                  WHEN NOT json_valid(c.payload) THEN 0
                  ELSE instr(
                           COALESCE(json_extract(c.payload, '$.files.body.message'), ''),
                           ' (Mod ID: ' || mods.mod_id || ') is '
                       )
              END > 1
   );

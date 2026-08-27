-- Migration 0028: per-pak notes, and per-pak removals that survive a rebuild.
--
-- Notes: a mod often ships a dozen near-identical variants whose names say
-- nothing useful (A_rogueVA / A_rogueVB / A_rogueVC ...). There was nowhere to
-- record which is which, so working it out meant toggling them one at a time,
-- every time.
--
-- Hidden files: removing a pak edits local_downloads.contents, and "Initial
-- Database Build" re-reads every archive and rewrites that column from scratch
-- -- so every removal came back. The removal has to live somewhere the rebuild
-- does not touch, which is what this table is for.
CREATE TABLE IF NOT EXISTS mod_file_notes (
    download_id INTEGER NOT NULL,
    pak_name    TEXT    NOT NULL,
    note        TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    PRIMARY KEY (download_id, pak_name)
);

CREATE TABLE IF NOT EXISTS mod_hidden_files (
    download_id INTEGER NOT NULL,
    pak_name    TEXT    NOT NULL,
    hidden_at   TEXT    NOT NULL,
    PRIMARY KEY (download_id, pak_name)
);

CREATE INDEX IF NOT EXISTS idx_mod_hidden_files_download
    ON mod_hidden_files(download_id);

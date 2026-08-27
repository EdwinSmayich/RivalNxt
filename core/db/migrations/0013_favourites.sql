-- Favourites table: tracks which mods the user has favourited.
CREATE TABLE IF NOT EXISTS favourites (
    mod_id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

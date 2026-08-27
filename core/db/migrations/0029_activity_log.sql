-- Migration 0029: a record of what the app did, and when.
--
-- Every operation here already succeeded or failed silently into a toast that
-- vanished after four seconds. There was no way to answer "did that actually
-- apply?" without reading backend.log, which is a developer artifact — so the
-- honest answer to a user asking was "re-run it and watch".
--
-- Deliberately not a debug log: one row per thing a person did, phrased the way
-- they would describe it. The raw log stays where it is for diagnostics.
CREATE TABLE IF NOT EXISTS activity_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      TEXT NOT NULL,
    kind    TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail  TEXT
);

CREATE INDEX IF NOT EXISTS idx_activity_log_at ON activity_log(at DESC);

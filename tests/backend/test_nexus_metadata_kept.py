"""What Nexus said about a mod yesterday must survive what it fails to say today.

Every sync wrote the whole of a mod's row from the latest answer and never
looked at the status that came with it. So each of these replaced the name, the
picture and the description with NULL:

* a 403 or 404;
* a 429 in the middle of a long sync;
* no network at all (status 0);
* a mod Nexus has put under moderation, which answers 200 with a status and
  nothing else.

The file list went the same way: an error has no ``files`` key, which was read
as "no files" and every stored row deleted. One library had 33 of its 200 mods
reduced to a bare id.
"""
from __future__ import annotations

import json
import socket
import urllib.error
from pathlib import Path

import pytest

from core.db.db import (
    fill_missing_mod_name,
    replace_mod_changelogs,
    replace_mod_files,
    upsert_mod_info,
)
from core.nexus import nexus_api
from core.utils.nexus_metadata import name_from_unavailable_message

GAME = "marvelrivals"
MOD = 4380
TITLE = "The Ting"

GOOD = {
    "name": TITLE,
    "summary": "A short summary",
    "description": "The long description",
    "user": {"name": "SomeAuthor", "member_id": 35355025},
    "version": "1.2",
    "picture_url": "https://staticdelivery.nexusmods.com/mods/1/images/4380.webp",
    "status": "published",
    "available": True,
    "category_id": 5,
    "endorsement_count": 461,
}
# What a mod under moderation answers: 200, and this.
HIDDEN = {"mod_id": MOD, "status": "under_moderation", "available": False, "allow_rating": True}
REFUSED = {
    "error": True,
    "message": "HTTP Error 403: Forbidden",
    "body": {"code": 403, "message": f"File currently not available. {TITLE} (Mod ID: {MOD}) is under moderation"},
}
OFFLINE = {"error": True, "message": "<urlopen error [Errno 11001] getaddrinfo failed>"}
FILES = {
    "files": [
        {"file_id": 9001, "name": "Main", "version": "1.2", "category_name": "MAIN", "size_in_bytes": 10},
        {"file_id": 9002, "name": "Addon", "version": "1.0", "category_name": "OPTIONAL", "size_in_bytes": 5},
    ]
}
CHANGELOGS = {"changelogs": [{"version": "1.2", "changelog": "Fixed the hair"}]}


def row(db, mod_id: int = MOD) -> dict:
    cur = db.execute("SELECT * FROM mods WHERE mod_id = ?", (mod_id,))
    record = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], record)) if record else {}


def file_ids(db) -> list[int]:
    return [r[0] for r in db.execute("SELECT file_id FROM mod_files WHERE mod_id = ? ORDER BY file_id", (MOD,))]


@pytest.fixture
def synced(schema_db):
    """A mod as it stands after one successful sync."""
    upsert_mod_info(schema_db, GAME, MOD, 200, GOOD)
    replace_mod_files(schema_db, MOD, FILES)
    replace_mod_changelogs(schema_db, MOD, CHANGELOGS)
    return schema_db


class TestTheModsRow:
    @pytest.mark.parametrize(
        "status,answer",
        [(403, REFUSED), (404, {"error": True, "message": "HTTP Error 404: Not Found"}), (429, {"error": True, "message": "Too Many Requests"}), (0, OFFLINE)],
        ids=["forbidden", "not-found", "rate-limited", "offline"],
    )
    def test_a_failed_answer_changes_nothing(self, synced, status, answer):
        before = row(synced)

        upsert_mod_info(synced, GAME, MOD, status, answer)

        assert row(synced) == before

    def test_a_bare_error_status_is_enough(self, synced):
        """Some callers pass the status and whatever the body happened to parse to."""
        before = row(synced)
        upsert_mod_info(synced, GAME, MOD, 500, {})
        assert row(synced) == before

    def test_a_hidden_mod_keeps_everything_it_had(self, synced):
        upsert_mod_info(synced, GAME, MOD, 200, HIDDEN)

        after = row(synced)
        assert after["name"] == TITLE
        assert after["picture_url"] == GOOD["picture_url"]
        assert after["author"] == "SomeAuthor"
        assert "long description" in (after["description_html"] or "")
        assert after["endorsement_count"] == 461

    def test_and_is_recorded_as_hidden(self, synced):
        upsert_mod_info(synced, GAME, MOD, 200, HIDDEN)

        after = row(synced)
        assert after["status"] == "under_moderation"
        assert after["available"] == 0

    def test_a_good_answer_still_updates(self, synced):
        newer = dict(GOOD, name="The Ting (Remastered)", version="2.0", endorsement_count=500)

        upsert_mod_info(synced, GAME, MOD, 200, newer)

        after = row(synced)
        assert (after["name"], after["version"], after["endorsement_count"]) == ("The Ting (Remastered)", "2.0", 500)

    def test_an_empty_name_does_not_replace_a_real_one(self, synced):
        upsert_mod_info(synced, GAME, MOD, 200, dict(GOOD, name=""))
        assert row(synced)["name"] == TITLE

    def test_a_first_sight_of_a_failed_mod_still_makes_a_row(self, schema_db):
        """Other tables point at mods.mod_id; the row has to exist."""
        upsert_mod_info(schema_db, GAME, 777, 403, REFUSED)
        assert row(schema_db, 777)["mod_id"] == 777
        assert row(schema_db, 777)["name"] is None

    def test_a_caller_that_builds_its_own_payload_is_unaffected(self, schema_db):
        """Placeholders for local mods pass status 0 and a plain dict."""
        upsert_mod_info(schema_db, GAME, -12, 0, {"name": "Local Mod 12", "author": "Local", "status": "plaintext"})
        assert row(schema_db, -12)["name"] == "Local Mod 12"


class TestTheFileList:
    def test_a_refusal_leaves_the_files_alone(self, synced):
        replace_mod_files(synced, MOD, REFUSED)
        assert file_ids(synced) == [9001, 9002]

    @pytest.mark.parametrize("answer", [None, "Service Unavailable", {}, {"files": None}, 5], ids=repr)
    def test_anything_that_is_not_a_file_list_leaves_them_alone(self, synced, answer):
        replace_mod_files(synced, MOD, answer)
        assert file_ids(synced) == [9001, 9002]

    def test_a_real_list_replaces_them(self, synced):
        replace_mod_files(synced, MOD, {"files": [{"file_id": 9003, "name": "Main", "version": "2.0"}]})
        assert file_ids(synced) == [9003]

    def test_a_real_empty_list_empties_them(self, synced):
        """A mod whose author took every file down has no files, and Nexus says so."""
        replace_mod_files(synced, MOD, {"files": []})
        assert file_ids(synced) == []

    def test_a_bare_list_is_still_accepted(self, synced):
        replace_mod_files(synced, MOD, [{"file_id": 9004, "name": "Main", "version": "3.0"}])
        assert file_ids(synced) == [9004]


class TestTheChangelogs:
    def count(self, db) -> int:
        return db.execute("SELECT COUNT(*) FROM mod_changelogs WHERE mod_id = ?", (MOD,)).fetchone()[0]

    @pytest.mark.parametrize("answer", [{}, None, REFUSED, {"changelogs": []}, []], ids=repr)
    def test_nothing_to_store_keeps_what_is_stored(self, synced, answer):
        replace_mod_changelogs(synced, MOD, answer)
        assert self.count(synced) == 1

    def test_a_real_changelog_replaces_the_old(self, synced):
        replace_mod_changelogs(synced, MOD, {"changelogs": [{"version": "2.0", "changelog": "New"}]})
        stored = [r[0] for r in synced.execute("SELECT version FROM mod_changelogs WHERE mod_id = ?", (MOD,))]
        assert stored == ["2.0"]


class TestANameThatWasAlreadyLost:
    """For libraries the old behaviour has been at already."""

    def test_the_refusal_says_what_the_mod_is_called(self):
        assert name_from_unavailable_message(REFUSED, MOD) == TITLE

    def test_it_reads_a_bare_message_too(self):
        assert name_from_unavailable_message(f"{TITLE} (Mod ID: {MOD}) is hidden", MOD) == TITLE

    def test_a_title_with_brackets_and_punctuation_survives(self):
        message = f"File currently not available. A (B) - C's D. v2 (Mod ID: {MOD}) is under moderation"
        assert name_from_unavailable_message(message, MOD) == "A (B) - C's D. v2"

    def test_a_message_about_another_mod_is_not_used(self):
        assert name_from_unavailable_message(REFUSED, MOD + 1) is None

    @pytest.mark.parametrize(
        "source",
        ["Mod not available: 1", "No Mod Found: 9999999", "", None, 7, {}, {"body": "Forbidden"}, {"body": {"code": 403}}],
        ids=repr,
    )
    def test_messages_that_name_nothing_give_nothing(self, source):
        assert name_from_unavailable_message(source, MOD) is None

    def test_a_missing_name_is_filled_in(self, schema_db):
        upsert_mod_info(schema_db, GAME, MOD, 200, HIDDEN)
        assert fill_missing_mod_name(schema_db, MOD, TITLE) is True
        assert row(schema_db)["name"] == TITLE

    def test_a_name_that_is_there_is_never_replaced(self, synced):
        assert fill_missing_mod_name(synced, MOD, "Something else") is False
        assert row(synced)["name"] == TITLE

    @pytest.mark.parametrize("blank", [None, "", "   "])
    def test_nothing_is_not_a_name(self, schema_db, blank):
        upsert_mod_info(schema_db, GAME, MOD, 200, HIDDEN)
        assert fill_missing_mod_name(schema_db, MOD, blank) is False
        assert row(schema_db)["name"] is None

    def test_a_sync_of_a_hidden_mod_recovers_it_on_its_own(self, schema_db):
        """The four sync paths all end in these two calls, in this order."""
        upsert_mod_info(schema_db, GAME, MOD, 200, HIDDEN)
        replace_mod_files(schema_db, MOD, REFUSED)
        assert row(schema_db)["name"] == TITLE


class TestTheMigration:
    SQL = (Path(__file__).resolve().parents[2] / "core" / "db" / "migrations" / "0032_recover_hidden_mod_names.sql").read_text(
        encoding="utf-8"
    )

    def add(self, db, mod_id: int, name, payload) -> None:
        db.execute("INSERT OR REPLACE INTO mods(mod_id, game, name) VALUES(?, ?, ?)", (mod_id, GAME, name))
        if payload is not None:
            db.execute(
                "INSERT OR REPLACE INTO mod_api_cache(mod_id, fetched_at, payload) VALUES(?, '2026-10-06', ?)",
                (mod_id, payload if isinstance(payload, str) else json.dumps(payload)),
            )
        db.commit()

    def refused(self, mod_id: int, message: str) -> dict:
        return {"mod_info": {"status": "under_moderation"}, "files": {"error": True, "body": {"code": 403, "message": message}}}

    def name(self, db, mod_id: int):
        return db.execute("SELECT name FROM mods WHERE mod_id = ?", (mod_id,)).fetchone()[0]

    def test_it_is_picked_up_by_the_runner(self, schema_db):
        applied = {r[0] for r in schema_db.execute("SELECT version FROM schema_migrations")}
        assert "0032_recover_hidden_mod_names" in applied

    def test_a_lost_name_comes_back(self, schema_db):
        self.add(schema_db, 4380, None, self.refused(4380, "File currently not available. The Ting (Mod ID: 4380) is under moderation"))
        schema_db.executescript(self.SQL)
        assert self.name(schema_db, 4380) == "The Ting"

    def test_it_agrees_with_the_python_parser(self, schema_db):
        messages = {
            101: "File currently not available. Maskless Malice (Remesh) (Mod ID: 101) is under moderation",
            102: "makeup file (Mod ID: 102) is hidden",
            103: "File currently not available. A - B's C. v2 (Mod ID: 103) is under moderation",
            104: "Mod not available: 104",
            105: "No Mod Found: 105",
            106: "File currently not available. Wrong (Mod ID: 999) is under moderation",
        }
        for mod_id, message in messages.items():
            self.add(schema_db, mod_id, None, self.refused(mod_id, message))

        schema_db.executescript(self.SQL)

        for mod_id, message in messages.items():
            assert self.name(schema_db, mod_id) == name_from_unavailable_message(message, mod_id), message

    def test_a_name_that_is_there_is_left_alone(self, schema_db):
        self.add(schema_db, 4380, "My own name for it", self.refused(4380, "File currently not available. The Ting (Mod ID: 4380) is under moderation"))
        schema_db.executescript(self.SQL)
        assert self.name(schema_db, 4380) == "My own name for it"

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            "this is not json",
            "",
            {"files": [{"file_id": 1}]},
            {"files": {"files": []}},
            {"files": {"error": True, "body": "Forbidden"}},
            {"files": {"error": True, "body": {"code": 403}}},
            {"mod_info": {"name": None}},
            [1, 2, 3],
        ],
        ids=lambda p: json.dumps(p)[:40],
    )
    def test_a_cache_entry_with_nothing_in_it_is_harmless(self, schema_db, payload):
        """A migration that raises stops the app from starting."""
        self.add(schema_db, 4380, None, payload)
        schema_db.executescript(self.SQL)
        assert self.name(schema_db, 4380) is None

    def test_local_mods_are_not_touched(self, schema_db):
        self.add(schema_db, -5, None, self.refused(-5, "File currently not available. X (Mod ID: -5) is under moderation"))
        schema_db.executescript(self.SQL)
        assert self.name(schema_db, -5) is None

    def test_running_it_twice_changes_nothing_more(self, schema_db):
        self.add(schema_db, 4380, None, self.refused(4380, "File currently not available. The Ting (Mod ID: 4380) is under moderation"))
        schema_db.executescript(self.SQL)
        schema_db.executescript(self.SQL)
        assert self.name(schema_db, 4380) == "The Ting"


class TestRequestsToNexus:
    def test_they_give_up_after_a_while(self, monkeypatch):
        """With no timeout, a stalled connection held up the download being ingested."""
        seen: dict = {}

        def fake_urlopen(req, **kwargs):
            seen.update(kwargs)
            raise urllib.error.URLError("stop here")

        monkeypatch.setattr(nexus_api.urllib.request, "urlopen", fake_urlopen)
        nexus_api._get("key", "/games/marvelrivals/mods/1.json")

        assert seen.get("timeout") == nexus_api.REQUEST_TIMEOUT_SECONDS
        assert 5 <= nexus_api.REQUEST_TIMEOUT_SECONDS <= 120

    @pytest.mark.parametrize(
        "failure",
        [socket.timeout("timed out"), TimeoutError("The read operation timed out"), ConnectionResetError(10054, "reset")],
        ids=["socket-timeout", "read-timeout", "reset"],
    )
    def test_a_stall_is_an_error_answer_not_a_crash(self, monkeypatch, failure):
        def fake_urlopen(req, **kwargs):
            raise failure

        monkeypatch.setattr(nexus_api.urllib.request, "urlopen", fake_urlopen)

        status, payload = nexus_api._get("key", "/games/marvelrivals/mods/1.json")

        assert status == 0
        assert payload["error"] is True and payload["message"]

    def test_and_that_answer_is_one_the_database_ignores(self, synced, monkeypatch):
        before = row(synced)
        monkeypatch.setattr(
            nexus_api.urllib.request, "urlopen", lambda req, **k: (_ for _ in ()).throw(TimeoutError("timed out"))
        )

        status, payload = nexus_api.get_mod_info("key", GAME, MOD)
        upsert_mod_info(synced, GAME, MOD, status, payload)

        assert row(synced) == before

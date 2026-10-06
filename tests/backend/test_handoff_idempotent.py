"""The same download link arriving twice must not start two downloads.

Every arrival of an nxm:// link used to mint a new handoff, and every handoff
started its own transfer of the same file. The shell has three paths that can
each deliver one click (the single-instance callback, the deep-link handler and
the initial command line), and a download that appears to be doing nothing
invites a second click. One archive was found downloading six times over.

Cancelling had the mirror-image fault: the flag was only ever read by a
transfer already running, so a handoff nobody had started on stayed in the
list and was picked up again.
"""
from __future__ import annotations

import sqlite3
import time

import pytest

import core.api.server as server
from core.api.services import handoffs
from core.api.services.downloads import CancelledSet, InflightRegistry
from core.nexus.nxm import parse_nxm_uri

LINK = "nxm://marvelrivals/mods/6882/files/9001?key=abc&expires=9999999999&user_id=1"
OTHER = "nxm://marvelrivals/mods/6775/files/9002?key=abc&expires=9999999999&user_id=1"


@pytest.fixture(autouse=True)
def clean_state(monkeypatch, tmp_path):
    db = tmp_path / "h.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE handoff_failures (file_id TEXT, mod_id INTEGER, error_message TEXT, "
        "retry_count INTEGER, last_attempt_at TEXT, handoff_id TEXT)"
    )
    conn.commit()
    conn.close()
    import core.api.dependencies as deps

    monkeypatch.setattr(deps, "get_db", lambda: sqlite3.connect(str(db)))
    handoffs._HANDOFFS.clear()
    yield
    handoffs._HANDOFFS.clear()


def register(link: str = LINK) -> dict:
    return handoffs.register_handoff(parse_nxm_uri(link), metadata={})


class TestRegisteringTheSameFileTwice:
    def test_a_repeat_joins_the_handoff_already_there(self):
        first = register()
        second = register()
        assert second["id"] == first["id"]
        assert len(handoffs._HANDOFFS) == 1

    def test_a_different_file_gets_its_own(self):
        assert register(LINK)["id"] != register(OTHER)["id"]

    def test_the_newer_link_replaces_the_key(self):
        first = register()
        fresher = LINK.replace("key=abc", "key=fresh")
        register(fresher)
        assert first["request"]["query"]["key"] == "fresh"

    def test_a_repeat_while_downloading_still_joins(self):
        first = register()
        handoffs.update_handoff_progress(first["id"], stage="downloading", bytes_downloaded=10)
        assert register()["id"] == first["id"]

    @pytest.mark.parametrize("stage", ["failed", "cancelled", "cancelling", "complete"])
    def test_a_finished_handoff_is_not_reused(self, stage):
        """Clicking again after a failure or a cancel has to start afresh."""
        first = register()
        handoffs.update_handoff_progress(first["id"], stage=stage)
        assert register()["id"] != first["id"]

    def test_a_consumed_handoff_is_not_reused(self):
        first = register()
        handoffs.mark_handoff_consumed(first["id"])
        assert register()["id"] != first["id"]


class TestAWaitingHandoffDoesNotExpire:
    def test_progress_pushes_the_expiry_out(self):
        record = register()
        record["expires_at"] = time.time() + 5
        handoffs.update_handoff_progress(record["id"], stage="queued", message="Queued")
        assert record["expires_at"] > time.time() + handoffs.NXM_HANDOFF_TTL_SECONDS - 5

    def test_a_finished_one_is_left_to_expire(self):
        record = register()
        record["expires_at"] = time.time() + 5
        handoffs.update_handoff_progress(record["id"], stage="failed", error="nope")
        assert record["expires_at"] <= time.time() + 6

    def test_the_queued_endpoint_keeps_it_alive(self):
        record = register()
        record["expires_at"] = time.time() + 5
        server.mark_nxm_handoff_queued(record["id"])
        assert record["progress"]["stage"] == "queued"
        assert record["expires_at"] > time.time() + 60


class TestCancellingSomethingThatHasNotStarted:
    @pytest.fixture(autouse=True)
    def fresh_registries(self, monkeypatch):
        monkeypatch.setattr(server, "_CANCELLED_HANDOFFS", CancelledSet())
        monkeypatch.setattr(server, "_INFLIGHT_DOWNLOADS", InflightRegistry())

    def test_it_leaves_the_list_at_once(self):
        record = register()
        result = server.cancel_nxm_handoff(record["id"])

        assert result["was_in_flight"] is False
        listed = [h["id"] for h in server.list_nxm_handoffs()["handoffs"]]
        assert record["id"] not in listed

    def test_one_that_is_transferring_is_left_for_its_own_thread(self):
        """The running transfer notices the flag and cleans up after itself."""
        record = register()
        server._INFLIGHT_DOWNLOADS.claim((6882, 9001), record["id"])

        result = server.cancel_nxm_handoff(record["id"])

        assert result["was_in_flight"] is True
        assert record["id"] in server._CANCELLED_HANDOFFS
        assert not record.get("consumed")

    def test_clicking_download_again_after_a_cancel_starts_afresh(self):
        record = register()
        server.cancel_nxm_handoff(record["id"])
        assert register()["id"] != record["id"]


class TestAHandoffThatHasFailedIsNotJoined:
    """Caught by an existing test while making registration idempotent.

    The frontend counts failures per handoff id and gives up after three. A new
    click folded into such an id would do nothing, and the failure record
    blocking it would never be cleared -- "Too many failed attempts" for good.
    """

    def test_a_click_after_failures_gets_a_fresh_handoff(self):
        first = register()
        handoffs.register_handoff_failure(first["id"], "The read operation timed out")
        assert register()["id"] != first["id"]

    def test_and_the_failure_record_is_cleared(self, tmp_path):
        import core.api.dependencies as deps

        first = register()
        handoffs.register_handoff_failure(first["id"], "boom")
        register()
        conn = deps.get_db()
        try:
            rows = conn.execute("SELECT COUNT(*) FROM handoff_failures WHERE file_id = '9001'").fetchone()[0]
        finally:
            conn.close()
        assert rows == 0

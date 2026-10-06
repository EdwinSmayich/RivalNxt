"""A download that did not finish must never look like one that did.

Six archives in one library turned out to be truncated. Activating a mod from
one failed with

    rar member extraction failed after reconfiguration:
    Failed the read enough data: req=1048576 got=1018368

which says nothing about the cause. The cause was in the download loop:

    chunk = response.read(chunk_size)
    if not chunk:
        break

``HTTPResponse.read(n)`` does not raise when the server closes the connection
early. It returns ``b""``, exactly as it does at a real end of file, and the
only check afterwards was that the result was not empty. Four .rar files
"finished" that way within 330 ms of each other. A fifth was left by closing
the app mid-transfer: the file was written straight to its final name, so a
killed process left something indistinguishable from a real archive.
"""
from __future__ import annotations

import asyncio
import io
import threading
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException

import core.api.server as server
from core.api.services import downloads
from core.api.services.downloads import (
    CancelledSet,
    DownloadSlots,
    InflightRegistry,
    PART_SUFFIX,
    archive_problem,
    cleanup_partial_downloads,
    length_problem,
)


def zip_bytes(payload: bytes = b"x" * 4096) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("Mod_9999999_P.pak", payload)
    return buf.getvalue()


class FakeResponse:
    """What urlopen returns, reduced to what the transfer loop touches."""

    def __init__(self, body: bytes, *, announced: int | None, fail_after: int | None = None):
        self._body = body
        self._pos = 0
        self.length = announced
        self.headers = {"Content-Length": str(announced)} if announced is not None else {}
        self._fail_after = fail_after

    def read(self, n: int) -> bytes:
        if self._fail_after is not None and self._pos >= self._fail_after:
            raise TimeoutError("The read operation timed out")
        chunk = self._body[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def downloads_dir(tmp_path, monkeypatch):
    root = tmp_path / "downloads"
    root.mkdir()
    monkeypatch.setattr(server, "_downloads_root_from_env", lambda: root)
    return root


def serve(monkeypatch, response: FakeResponse) -> None:
    monkeypatch.setattr(server.urllib.request, "urlopen", lambda *a, **k: response)


URL = "https://cdn.example/files/LunaSnow_AbyssalGlow_Symbiote.zip"


class TestATruncatedTransferIsRejected:
    def test_a_connection_closed_early_is_not_a_finished_download(self, downloads_dir, monkeypatch):
        whole = zip_bytes()
        # The server announces the full length, then hangs up part-way. read()
        # returns b"" from there, which is all the old loop ever looked at.
        serve(monkeypatch, FakeResponse(whole[: len(whole) // 2], announced=len(whole)))

        with pytest.raises(HTTPException) as caught:
            server._download_remote_archive(URL, force=True)

        assert caught.value.status_code == 502
        assert "closed early" in str(caught.value.detail)

    def test_nothing_is_left_behind_under_the_real_name(self, downloads_dir, monkeypatch):
        whole = zip_bytes()
        serve(monkeypatch, FakeResponse(whole[:100], announced=len(whole)))

        with pytest.raises(HTTPException):
            server._download_remote_archive(URL, force=True)

        assert list(downloads_dir.iterdir()) == [], "a truncated file was left in the downloads folder"

    def test_a_truncated_zip_is_caught_even_with_no_length_announced(self, downloads_dir, monkeypatch):
        """A zip's directory is at its end, so a cut-off one cannot be opened."""
        whole = zip_bytes()
        serve(monkeypatch, FakeResponse(whole[: len(whole) - 40], announced=None))

        with pytest.raises(HTTPException) as caught:
            server._download_remote_archive(URL, force=True)

        assert "not a complete zip" in str(caught.value.detail)
        assert list(downloads_dir.iterdir()) == []

    def test_a_read_timeout_leaves_nothing_behind(self, downloads_dir, monkeypatch):
        whole = zip_bytes()
        serve(monkeypatch, FakeResponse(whole, announced=len(whole), fail_after=1))

        with pytest.raises(HTTPException) as caught:
            server._download_remote_archive(URL, force=True)

        assert "timed out" in str(caught.value.detail)
        assert list(downloads_dir.iterdir()) == []

    def test_an_error_page_saved_as_an_archive_is_rejected(self, downloads_dir, monkeypatch):
        page = b"<html><body>403 Forbidden</body></html>"
        serve(monkeypatch, FakeResponse(page, announced=len(page)))

        with pytest.raises(HTTPException):
            server._download_remote_archive(URL, force=True)
        assert list(downloads_dir.iterdir()) == []


class TestACompleteTransferIsKept:
    def test_the_file_arrives_under_its_real_name(self, downloads_dir, monkeypatch):
        whole = zip_bytes()
        serve(monkeypatch, FakeResponse(whole, announced=len(whole)))

        path = server._download_remote_archive(URL, force=True)

        assert path.name == "LunaSnow_AbyssalGlow_Symbiote.zip"
        assert path.read_bytes() == whole

    def test_no_partial_file_remains(self, downloads_dir, monkeypatch):
        whole = zip_bytes()
        serve(monkeypatch, FakeResponse(whole, announced=len(whole)))

        server._download_remote_archive(URL, force=True)

        assert [p.name for p in downloads_dir.iterdir()] == ["LunaSnow_AbyssalGlow_Symbiote.zip"]

    def test_a_second_copy_gets_a_suffix_instead_of_overwriting(self, downloads_dir, monkeypatch):
        whole = zip_bytes()
        serve(monkeypatch, FakeResponse(whole, announced=len(whole)))
        server._download_remote_archive(URL, force=True)
        serve(monkeypatch, FakeResponse(whole, announced=len(whole)))

        second = server._download_remote_archive(URL, force=True)

        assert second.name == "LunaSnow_AbyssalGlow_Symbiote-1.zip"

    def test_progress_ends_on_the_full_size(self, downloads_dir, monkeypatch):
        whole = zip_bytes(b"y" * 300_000)
        serve(monkeypatch, FakeResponse(whole, announced=len(whole)))
        seen: list[tuple[int, int | None]] = []

        server._download_remote_archive(URL, force=True, progress_callback=lambda d, t: seen.append((d, t)))

        assert seen[-1] == (len(whole), len(whole))

    def test_the_read_size_keeps_progress_and_cancel_responsive(self):
        """read(n) blocks for n bytes; 1 MiB made a slow link look frozen."""
        assert server.DOWNLOAD_CHUNK_BYTES <= 128 * 1024


class TestCancelling:
    def test_a_cancelled_transfer_leaves_nothing_behind(self, downloads_dir, monkeypatch):
        whole = zip_bytes(b"z" * 500_000)
        serve(monkeypatch, FakeResponse(whole, announced=len(whole)))
        monkeypatch.setattr(server, "_CANCELLED_HANDOFFS", CancelledSet())
        server._CANCELLED_HANDOFFS.add("handoff-1")

        with pytest.raises(server.DownloadCancelledError):
            server._download_remote_archive(URL, force=True, handoff_id="handoff-1")

        assert list(downloads_dir.iterdir()) == []

    def test_the_flag_outlives_the_first_thread_to_read_it(self):
        """It used to be discarded on first sight, which stopped one of several
        transfers of the same handoff and left the rest running."""
        cancelled = CancelledSet()
        cancelled.add("handoff-1")
        assert "handoff-1" in cancelled
        cancelled.discard("handoff-1")
        assert "handoff-1" in cancelled

    def test_old_entries_expire(self):
        cancelled = CancelledSet(ttl_seconds=0.01)
        cancelled.add("old")
        time.sleep(0.05)
        cancelled.add("new")
        assert "old" not in cancelled
        assert "new" in cancelled


class TestLeftoversFromAnEarlierRun:
    def test_partial_files_are_swept(self, tmp_path):
        (tmp_path / f"Mod.zip.ab12cd34{PART_SUFFIX}").write_bytes(b"half")
        keep = tmp_path / "Mod.zip"
        keep.write_bytes(zip_bytes())

        removed = cleanup_partial_downloads(tmp_path)

        assert removed == 1
        assert [p.name for p in tmp_path.iterdir()] == ["Mod.zip"]

    def test_the_scanner_would_never_pick_one_up(self):
        """The folder scan takes .zip/.rar/.7z/.pak; a partial must be none of them."""
        name = downloads.partial_path(Path("Mod.zip"), "ab12cd34").name
        assert not name.lower().endswith((".zip", ".rar", ".7z", ".pak"))

    def test_a_missing_folder_is_not_an_error(self, tmp_path):
        assert cleanup_partial_downloads(tmp_path / "nope") == 0


class TestTheChecksThemselves:
    def test_length(self):
        assert length_problem(100, 100) is None
        assert length_problem(100, None) is None
        assert "closed early" in length_problem(60, 100)
        assert length_problem(120, 100) is not None

    def test_a_partial_file_is_checked_as_the_type_it_will_become(self, tmp_path):
        part = tmp_path / f"Mod.zip.ab12cd34{PART_SUFFIX}"
        part.write_bytes(zip_bytes())
        assert archive_problem(part, suffix=".zip") is None
        part.write_bytes(zip_bytes()[:50])
        assert archive_problem(part, suffix=".zip") is not None

    def test_rar_and_7z_are_checked_by_signature(self, tmp_path):
        rar = tmp_path / "a.rar"
        rar.write_bytes(b"Rar!\x1a\x07\x01\x00rest")
        assert archive_problem(rar) is None
        rar.write_bytes(b"<html>nope</html>")
        assert archive_problem(rar) is not None

        seven = tmp_path / "a.7z"
        seven.write_bytes(b"7z\xbc\xaf\x27\x1crest")
        assert archive_problem(seven) is None

    def test_an_unknown_type_is_not_second_guessed(self, tmp_path):
        other = tmp_path / "a.pak"
        other.write_bytes(b"anything")
        assert archive_problem(other) is None


class TestOnlyAFewAtATime:
    """Every waiting download used to start at once.

    Each holds a connection open for the whole transfer and the webview allows
    six per host, so past that the progress polls and the Cancel button queued
    behind the downloads -- and on a bandwidth-capped account they all crawled.
    """

    def test_the_limit_holds(self):
        slots = DownloadSlots(limit=2)
        assert slots.acquire()
        assert slots.acquire()
        got: list[bool] = []
        waiter = threading.Thread(target=lambda: got.append(slots.acquire()))
        waiter.start()
        time.sleep(0.15)
        assert got == [], "a third download started past the limit"
        slots.release()
        waiter.join(timeout=3)
        assert got == [True]

    def test_waiting_is_first_come_first_served(self):
        slots = DownloadSlots(limit=1)
        assert slots.acquire()
        order: list[str] = []

        def wait(name: str) -> None:
            slots.acquire(poll_seconds=0.02)
            order.append(name)
            slots.release()

        first = threading.Thread(target=wait, args=("first",))
        first.start()
        time.sleep(0.1)
        second = threading.Thread(target=wait, args=("second",))
        second.start()
        time.sleep(0.1)
        slots.release()
        first.join(timeout=3)
        second.join(timeout=3)
        assert order == ["first", "second"]

    def test_a_queued_download_can_be_cancelled(self):
        slots = DownloadSlots(limit=1)
        assert slots.acquire()
        stop = threading.Event()
        got: list[bool] = []
        waiter = threading.Thread(
            target=lambda: got.append(slots.acquire(is_cancelled=stop.is_set, poll_seconds=0.02))
        )
        waiter.start()
        time.sleep(0.1)
        stop.set()
        waiter.join(timeout=3)
        assert got == [False]
        assert slots.waiting == 0

    def test_a_queued_download_knows_its_place(self):
        slots = DownloadSlots(limit=1)
        assert slots.acquire()
        positions: list[int] = []
        stop = threading.Event()
        waiter = threading.Thread(
            target=lambda: slots.acquire(
                is_cancelled=stop.is_set, on_wait=positions.append, poll_seconds=0.02
            )
        )
        waiter.start()
        time.sleep(0.1)
        stop.set()
        waiter.join(timeout=3)
        assert positions and positions[0] == 0


class TestOneTransferPerFile:
    """One archive was found downloading six times over, named ...-1 to ...-5."""

    def test_a_second_claim_is_told_who_has_it(self):
        registry = InflightRegistry()
        assert registry.claim((6882, 9001), "handoff-a") is None
        assert registry.claim((6882, 9001), "handoff-b") == "handoff-a"

    def test_releasing_frees_it(self):
        registry = InflightRegistry()
        registry.claim((6882, 9001), "handoff-a")
        registry.release((6882, 9001), "handoff-a")
        assert registry.claim((6882, 9001), "handoff-b") is None

    def test_only_the_owner_can_release(self):
        registry = InflightRegistry()
        registry.claim((6882, 9001), "handoff-a")
        registry.release((6882, 9001), "someone-else")
        assert registry.is_active("handoff-a")

    def test_a_second_request_for_the_same_file_is_refused(self, monkeypatch):
        monkeypatch.setattr(server, "_INFLIGHT_DOWNLOADS", InflightRegistry())
        monkeypatch.setattr(server, "_DOWNLOAD_SLOTS", DownloadSlots(limit=2))
        started = threading.Event()
        finish = threading.Event()

        def slow(record, game, file_id, desired_filename=None):
            started.set()
            finish.wait(timeout=5)
            return Path("x.zip"), "https://cdn.example/x.zip"

        monkeypatch.setattr(server, "_download_archive_via_nxm", slow)
        first = threading.Thread(
            target=lambda: server._download_once_in_turn({"id": "handoff-a"}, "marvelrivals", 6882, 9001)
        )
        first.start()
        assert started.wait(timeout=3)
        try:
            with pytest.raises(HTTPException) as caught:
                server._download_once_in_turn({"id": "handoff-b"}, "marvelrivals", 6882, 9001)
            assert caught.value.status_code == 409
            assert caught.value.detail["in_progress"] is True
        finally:
            finish.set()
            first.join(timeout=5)

    def test_the_claim_is_released_when_the_transfer_fails(self, monkeypatch):
        registry = InflightRegistry()
        monkeypatch.setattr(server, "_INFLIGHT_DOWNLOADS", registry)
        monkeypatch.setattr(server, "_DOWNLOAD_SLOTS", DownloadSlots(limit=2))

        def boom(*a, **k):
            raise HTTPException(status_code=502, detail="nope")

        monkeypatch.setattr(server, "_download_archive_via_nxm", boom)
        with pytest.raises(HTTPException):
            server._download_once_in_turn({"id": "handoff-a"}, "marvelrivals", 6882, 9001)

        assert not registry.is_active("handoff-a")
        assert server._DOWNLOAD_SLOTS.active == 0

    def test_a_download_cancelled_before_its_turn_never_contacts_nexus(self, monkeypatch):
        """A free slot is granted without asking; the cancel has to be checked after."""
        registry = InflightRegistry()
        cancelled = CancelledSet()
        cancelled.add("handoff-a")
        monkeypatch.setattr(server, "_INFLIGHT_DOWNLOADS", registry)
        monkeypatch.setattr(server, "_DOWNLOAD_SLOTS", DownloadSlots(limit=2))
        monkeypatch.setattr(server, "_CANCELLED_HANDOFFS", cancelled)
        contacted: list[str] = []
        monkeypatch.setattr(
            server, "_download_archive_via_nxm", lambda *a, **k: contacted.append("nexus")
        )

        with pytest.raises(server.DownloadCancelledError):
            server._download_once_in_turn({"id": "handoff-a"}, "marvelrivals", 6882, 9001)

        assert contacted == []
        assert not registry.is_active("handoff-a")
        assert server._DOWNLOAD_SLOTS.active == 0


class FakeUpload:
    """An UploadFile reduced to what the upload route touches."""

    def __init__(self, filename: str, chunks: list, *, die_on: int | None = None):
        self.filename = filename
        self._chunks = list(chunks)
        self._calls = 0
        self._die_on = die_on

    async def read(self, _n: int) -> bytes:
        self._calls += 1
        if self._die_on is not None and self._calls >= self._die_on:
            # What the route sees when the window is closed mid-upload.
            raise asyncio.CancelledError()
        return self._chunks.pop(0) if self._chunks else b""

    async def close(self) -> None:
        pass


class TestFilesAddedByHand:
    """Dropping a file onto the app, or picking one from disk.

    Both wrote straight to the final name in the downloads folder. Stopped
    half-way -- the app closed, the disk filled -- that left a truncated
    archive which looked finished, and which every later attempt to add the
    same file was answered with.
    """

    def test_an_upload_cut_short_leaves_nothing(self, downloads_dir):
        upload = FakeUpload("Mod.zip", [b"PK the first part"], die_on=2)

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(server.upload_mod_file(file=upload))

        assert list(downloads_dir.iterdir()) == []

    def test_so_the_next_attempt_is_not_told_it_already_exists(self, downloads_dir):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(server.upload_mod_file(file=FakeUpload("Mod.zip", [b"half"], die_on=2)))

        whole = zip_bytes()
        result = asyncio.run(server.upload_mod_file(file=FakeUpload("Mod.zip", [whole])))

        assert "already_existed" not in result
        assert result["size"] == len(whole)
        assert (downloads_dir / "Mod.zip").read_bytes() == whole

    def test_a_complete_upload_arrives_under_its_name_only(self, downloads_dir):
        whole = zip_bytes()
        asyncio.run(server.upload_mod_file(file=FakeUpload("Mod.zip", [whole[:100], whole[100:]])))
        assert [p.name for p in downloads_dir.iterdir()] == ["Mod.zip"]

    def test_an_empty_upload_is_refused_and_leaves_nothing(self, downloads_dir):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(server.upload_mod_file(file=FakeUpload("Mod.zip", [])))
        assert caught.value.status_code == 400
        assert list(downloads_dir.iterdir()) == []

    def test_a_copy_cut_short_leaves_nothing(self, downloads_dir, tmp_path, monkeypatch):
        source = tmp_path / "Picked.zip"
        source.write_bytes(zip_bytes())

        def dies_halfway(src, dst, *a, **k):
            Path(dst).write_bytes(Path(src).read_bytes()[:50])
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(server.shutil, "copy2", dies_halfway)

        with pytest.raises(HTTPException) as caught:
            server.copy_to_downloads(server.CopyToDownloadsRequest(source_path=str(source)))

        assert caught.value.status_code == 500
        assert list(downloads_dir.iterdir()) == []

    def test_a_complete_copy_arrives_under_its_name_only(self, downloads_dir, tmp_path):
        source = tmp_path / "Picked.zip"
        source.write_bytes(zip_bytes())

        result = server.copy_to_downloads(server.CopyToDownloadsRequest(source_path=str(source)))

        assert [p.name for p in downloads_dir.iterdir()] == ["Picked.zip"]
        assert result["size"] == source.stat().st_size

    def test_the_copy_is_never_visible_under_its_real_name_while_in_flight(
        self, downloads_dir, tmp_path, monkeypatch
    ):
        source = tmp_path / "Picked.zip"
        source.write_bytes(zip_bytes())
        seen_during: list[list[str]] = []
        real = server.shutil.copy2

        def watching(src, dst, *a, **k):
            out = real(src, dst, *a, **k)
            seen_during.append(sorted(p.name for p in downloads_dir.iterdir()))
            return out

        monkeypatch.setattr(server.shutil, "copy2", watching)
        server.copy_to_downloads(server.CopyToDownloadsRequest(source_path=str(source)))

        assert len(seen_during) == 1
        assert all(name.endswith(PART_SUFFIX) for name in seen_during[0])


class TestTheMessageAPersonSees:
    """Activating from a truncated archive said: "rar member extraction failed
    after reconfiguration: Failed the read enough data: req=1048576
    got=1018368". No cause, no remedy."""

    @pytest.mark.parametrize(
        "raw",
        [
            "rar member extraction failed after reconfiguration: Failed the read enough data: req=1048576 got=1018368",
            "Unexpected end of archive",
            "zip extract failed: File is not a zip file",
            "Error -3 while decompressing data: invalid distance too far back",
            "Bad magic number for central directory",
            "Corrupt file - CRC check failed: a.pak",
        ],
    )
    def test_damage_is_named_as_damage(self, raw):
        message = downloads.describe_archive_failure(raw, "Mod.rar")
        assert message is not None
        assert "Mod.rar" in message
        assert "download it again" in message

    def test_other_failures_are_left_alone(self):
        assert downloads.describe_archive_failure("member not found in rar") is None
        assert downloads.describe_archive_failure("Permission denied") is None

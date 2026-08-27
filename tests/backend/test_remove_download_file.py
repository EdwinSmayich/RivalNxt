"""Removing one pak from a mod, instead of the whole mod.

A mod often ships a dozen variants — SexyWhiteFoxMVA through MVH, plus bush /
pubes / shaved — and only one is wanted. The only option was deleting the entire
download.

The source archive is never touched. Removal records the pak in
mod_hidden_files and every read path filters against that record, so the file
stops being offered without local_downloads.contents being edited at all.

That indirection is the point. contents is rebuilt from the archive by every
ingest, so an edit there was undone by the next "Initial Database Build" while
the record survived — and because the entry really had been deleted, putting it
back needed a full rebuild. Filtering on read means a rebuild cannot resurrect a
hidden file, and restoring one is immediate.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from core.api.server import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def download(client):
    from core.api.dependencies import get_db

    dl_id = 987654
    contents = [
        "A_SexyWhiteFoxMVA_9999999_P.pak",
        "A_SexyWhiteFoxMVB_9999999_P.pak",
        "A_SexyWhiteFoxPbush_99999999_P.pak",
    ]
    conn = get_db()
    try:
        conn.execute("DELETE FROM local_downloads WHERE id = ?", (dl_id,))
        # Removals now live in their own table, which resetting the download row
        # does not clear — without this, one test's removals hid the files for
        # every test that followed.
        conn.execute("DELETE FROM mod_hidden_files WHERE download_id = ?", (dl_id,))
        conn.execute(
            "INSERT INTO local_downloads (id, name, path, contents, active_paks) "
            "VALUES (?, ?, ?, ?, ?)",
            (dl_id, "White Fox Pack", "/tmp/wf.zip", json.dumps(contents), "[]"),
        )
        conn.commit()
    finally:
        conn.close()
    return dl_id, contents


def contents_of(dl_id: int):
    """What the mod actually offers, not what the raw column holds.

    Reads through the API on purpose: removal no longer edits
    local_downloads.contents, so querying that column directly would assert the
    old mechanism rather than the behaviour anyone can observe.
    """
    from core.api.server import get_local_download

    return get_local_download(dl_id)["contents"]


def hidden_of(dl_id: int):
    from core.api.server import get_local_download

    return get_local_download(dl_id)["hidden_contents"]


class TestRemoveDownloadFile:
    def test_removes_only_the_named_pak(self, client, download):
        dl_id, contents = download

        r = client.post(
            f"/api/local_downloads/{dl_id}/remove-file",
            json={"pak_name": "A_SexyWhiteFoxMVB_9999999_P.pak"},
        )

        assert r.status_code == 200
        assert r.json()["remaining"] == 2
        left = contents_of(dl_id)
        assert "A_SexyWhiteFoxMVB_9999999_P.pak" not in left
        assert "A_SexyWhiteFoxMVA_9999999_P.pak" in left
        assert "A_SexyWhiteFoxPbush_99999999_P.pak" in left

    def test_similar_names_are_not_collateral(self, client, download):
        """MVA and MVB differ by one letter; a loose match would take both."""
        dl_id, _ = download
        client.post(
            f"/api/local_downloads/{dl_id}/remove-file",
            json={"pak_name": "A_SexyWhiteFoxMVA_9999999_P.pak"},
        )
        assert "A_SexyWhiteFoxMVB_9999999_P.pak" in contents_of(dl_id)

    def test_a_file_that_is_not_in_the_mod_is_rejected(self, client, download):
        dl_id, contents = download
        r = client.post(
            f"/api/local_downloads/{dl_id}/remove-file",
            json={"pak_name": "SomeOtherMod_P.pak"},
        )
        assert r.status_code == 404
        assert len(contents_of(dl_id)) == len(contents)

    def test_unknown_download_reports_not_found(self, client):
        r = client.post(
            "/api/local_downloads/99999999/remove-file", json={"pak_name": "x.pak"}
        )
        assert r.status_code == 404

    def test_empty_name_is_rejected(self, client, download):
        dl_id, contents = download
        r = client.post(
            f"/api/local_downloads/{dl_id}/remove-file", json={"pak_name": "   "}
        )
        assert r.status_code == 400
        assert len(contents_of(dl_id)) == len(contents)

    def test_removing_every_file_leaves_an_empty_list_not_an_error(
        self, client, download
    ):
        dl_id, contents = download
        for pak in contents:
            r = client.post(
                f"/api/local_downloads/{dl_id}/remove-file", json={"pak_name": pak}
            )
            assert r.status_code == 200
        assert contents_of(dl_id) == []

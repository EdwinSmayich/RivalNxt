"""The user picks which image is the preview, and in what order they appear.

Images were ordered by row id — upload order — and the card preview literally
selected `HAVING id = MIN(id)`. A better screenshot uploaded later could never be
promoted to the front.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.api.server import app


@pytest.fixture(scope="module")
def client():
    # No data-dir juggling here: conftest already points the whole suite at
    # .pytest-data before core.config.settings loads. Overriding it again from a
    # single module redirected get_db() for every test that ran afterwards.
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def mod_with_images(client):
    """A local mod (negative id) with three images, in upload order."""
    from core.api.dependencies import get_db

    mod_id = -777
    conn = get_db()
    try:
        conn.execute("DELETE FROM mod_custom_images WHERE mod_id = ?", (mod_id,))
        conn.execute(
            "INSERT OR IGNORE INTO mods (mod_id, game, name) VALUES (?, ?, ?)",
            (mod_id, "marvelrivals", "Order Test"),
        )
        ids = []
        for n in ("first.png", "second.png", "third.png"):
            cur = conn.execute(
                "INSERT INTO mod_custom_images (mod_id, image_data, filename, mime_type) "
                "VALUES (?, ?, ?, ?)",
                (mod_id, "eA==", n, "image/png"),
            )
            ids.append(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()
    return mod_id, ids


def names(client, mod_id):
    body = client.get(f"/api/mods/{mod_id}/images").json()
    return [i["filename"] for i in body["custom_images"]]


class TestReorder:
    def test_default_order_is_upload_order(self, client, mod_with_images):
        mod_id, _ = mod_with_images
        assert names(client, mod_id) == ["first.png", "second.png", "third.png"]

    def test_reordering_changes_the_listed_order(self, client, mod_with_images):
        mod_id, ids = mod_with_images
        r = client.post(
            f"/api/mods/{mod_id}/images/reorder",
            json={"image_ids": [ids[2], ids[0], ids[1]]},
        )
        assert r.status_code == 200
        assert names(client, mod_id) == ["third.png", "first.png", "second.png"]

    def test_promoting_an_image_makes_it_the_preview(self, client, mod_with_images):
        """The whole point: the card must show the image put first."""
        mod_id, ids = mod_with_images
        client.post(f"/api/mods/{mod_id}/images/reorder", json={"image_ids": [ids[1]]})

        body = client.get(
            "/api/mods/custom-images-preview", params={"mod_ids": str(mod_id)}
        ).json()
        # One preview per mod, and it must be the promoted row.
        assert str(mod_id) in body["images"]
        assert names(client, mod_id)[0] == "second.png"

    def test_a_partial_list_keeps_the_rest_rather_than_dropping_them(
        self, client, mod_with_images
    ):
        mod_id, ids = mod_with_images
        client.post(f"/api/mods/{mod_id}/images/reorder", json={"image_ids": [ids[2]]})
        assert names(client, mod_id) == ["third.png", "first.png", "second.png"]

    def test_reordering_is_stable_when_repeated(self, client, mod_with_images):
        mod_id, ids = mod_with_images
        order = [ids[1], ids[2], ids[0]]
        client.post(f"/api/mods/{mod_id}/images/reorder", json={"image_ids": order})
        once = names(client, mod_id)
        client.post(f"/api/mods/{mod_id}/images/reorder", json={"image_ids": order})
        assert names(client, mod_id) == once

    def test_rejects_an_image_belonging_to_another_mod(self, client, mod_with_images):
        """The id list comes from the client and must not reach other mods."""
        mod_id, _ = mod_with_images
        from core.api.dependencies import get_db

        conn = get_db()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO mods (mod_id, game, name) VALUES (?, ?, ?)",
                (-778, "marvelrivals", "Other"),
            )
            cur = conn.execute(
                "INSERT INTO mod_custom_images (mod_id, image_data, filename, mime_type) "
                "VALUES (?, ?, ?, ?)",
                (-778, "eA==", "other.png", "image/png"),
            )
            foreign_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        r = client.post(
            f"/api/mods/{mod_id}/images/reorder", json={"image_ids": [foreign_id]}
        )
        assert r.status_code == 400
        assert names(client, mod_id)[0] != "other.png"

    def test_unknown_mod_reports_not_found(self, client):
        r = client.post("/api/mods/-999999/images/reorder", json={"image_ids": []})
        assert r.status_code == 404

"""Half a picture must not be stored as the picture.

Images added by address are read with ``response.read(n)``, which does not
raise when the server closes the connection early -- it returns what arrived.
That is the same behaviour that let truncated archives through as complete
downloads; here it stored the top half of a screenshot.
"""
from __future__ import annotations

import io

import pytest

import core.api.server as server

MOD = 7
URL = "https://staticdelivery.example/mods/1/images/7/shot.png"


def png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


class FakeImageResponse:
    def __init__(self, body: bytes, announced: int | None, content_type: str = "image/png"):
        self._body = body
        self.headers = {"Content-Type": content_type}
        if announced is not None:
            self.headers["Content-Length"] = str(announced)

    def read(self, n: int) -> bytes:
        return self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def mod(monkeypatch, schema_db):
    schema_db.execute("INSERT INTO mods(mod_id, game, name) VALUES(?, 'marvelrivals', 'The Ting')", (MOD,))
    schema_db.commit()

    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            pass

    monkeypatch.setattr(server, "get_db", lambda: _NoClose(schema_db))
    return schema_db


def serve(monkeypatch, response: FakeImageResponse) -> None:
    monkeypatch.setattr(server.urllib.request, "urlopen", lambda *a, **k: response)


def stored(db) -> int:
    return db.execute("SELECT COUNT(*) FROM mod_custom_images WHERE mod_id = ?", (MOD,)).fetchone()[0]


def add(urls=(URL,)) -> dict:
    return server.upload_mod_images_by_url(MOD, server.UploadImageByUrlPayload(urls=list(urls)))


def test_an_image_cut_short_is_refused(mod, monkeypatch):
    whole = png_bytes()
    serve(monkeypatch, FakeImageResponse(whole[: len(whole) // 2], announced=len(whole)))

    result = add()

    assert stored(mod) == 0
    failures = result.get("failures") or result.get("failed") or []
    assert any("did not arrive whole" in str(f) for f in failures), result


def test_a_whole_image_is_stored(mod, monkeypatch):
    whole = png_bytes()
    serve(monkeypatch, FakeImageResponse(whole, announced=len(whole)))

    add()

    assert stored(mod) == 1


def test_a_server_that_announces_no_length_is_still_accepted(mod, monkeypatch):
    """Nothing to compare against; refusing these would refuse most CDNs' chunked replies."""
    serve(monkeypatch, FakeImageResponse(png_bytes(), announced=None))

    add()

    assert stored(mod) == 1


def test_a_nonsense_length_header_is_ignored(mod, monkeypatch):
    response = FakeImageResponse(png_bytes(), announced=None)
    response.headers["Content-Length"] = "not-a-number"
    serve(monkeypatch, response)

    add()

    assert stored(mod) == 1

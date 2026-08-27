"""Storage-side image normalization.

Custom mod artwork was stored exactly as uploaded. Uploads in the wild are
mostly already under the display size but encoded as 16-bit/uncompressed PNG at
3.5-4.8 bytes per pixel, so a 177-mod library grew mods.db past 2 GB and made
the JSON backup export exceed the maximum length of a JavaScript string.

``_normalize_image_for_storage`` re-encodes on the way in. These tests pin the
properties that make that safe to run against user data: it must never lose an
upload, never enlarge one, and never silently change how an image looks.
"""
from __future__ import annotations

import base64
import io
import random

import pytest

from core.api.server import _normalize_image_for_storage

Image = pytest.importorskip("PIL.Image", reason="Pillow is required for image storage")
ImageChops = pytest.importorskip("PIL.ImageChops")


def _encode(img, fmt: str = "PNG", **kw) -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    return base64.b64encode(buf.getvalue()).decode()


def _decode(data: str):
    return Image.open(io.BytesIO(base64.b64decode(data)))


def _gradient(w: int, h: int, mode: str = "RGB", alpha: int | None = None):
    """Smooth content, which is what real screenshots look like to an encoder."""
    img = Image.new(mode, (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            rgb = (int(x * 255 / max(w - 1, 1)), int(y * 255 / max(h - 1, 1)), 128)
            px[x, y] = rgb + (alpha,) if mode == "RGBA" and alpha is not None else rgb
    return img


def _photo(w: int, h: int, mode: str = "RGB"):
    """Textured content: PNG stores this poorly and JPEG stores it well.

    A pure gradient is the opposite — PNG beats JPEG on it, the size guard
    returns the original, and no re-encode happens at all. Real mod screenshots
    have texture, so this is the input shape the normalizer exists for.
    """
    rnd = random.Random(1234)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        base_g = int(y * 255 / max(h - 1, 1))
        for x in range(w):
            n = rnd.randint(-28, 28)
            px[x, y] = (
                max(0, min(255, int(x * 255 / max(w - 1, 1)) + n)),
                max(0, min(255, base_g + n)),
                max(0, min(255, 128 + n)),
            )
    return img.convert(mode) if mode != "RGB" else img


class TestShrinking:
    def test_oversized_image_is_downscaled_to_the_max_edge(self):
        src = _encode(_photo(4000, 2000))
        out, mime = _normalize_image_for_storage(src, "image/png")
        result = _decode(out)
        assert max(result.width, result.height) == 1920
        assert result.width / result.height == pytest.approx(2.0, rel=0.01)
        assert mime == "image/jpeg"

    def test_dimension_cap_yields_to_the_size_guard(self):
        # Documents a real consequence of the guard ordering: downscaling runs
        # first, but if the re-encode is not smaller the ORIGINAL is returned —
        # original dimensions included. So the 1920 cap is a byte-size
        # optimisation, not a hard limit on stored resolution. Flat/synthetic
        # art that PNG compresses better than JPEG is kept at full size.
        src = _encode(_gradient(4000, 2000))
        out, mime = _normalize_image_for_storage(src, "image/png")
        assert out == src and mime == "image/png"
        assert _decode(out).size == (4000, 2000)

    def test_uncompressed_png_shrinks_even_when_already_small_enough(self):
        # The whole point: an early return on "already within max edge" is what
        # left ~79% of the bytes in place.
        img = _gradient(1200, 800)
        buf = io.BytesIO()
        img.save(buf, format="PNG", compress_level=0)
        src = base64.b64encode(buf.getvalue()).decode()

        out, mime = _normalize_image_for_storage(src, "image/png")

        assert len(out) < len(src) / 2
        assert mime == "image/jpeg"
        assert _decode(out).size == (1200, 800)

    def test_reported_mime_matches_the_bytes_actually_stored(self):
        # The frontend renders these as data:{mimeType};base64,{data}; storing
        # JPEG bytes under image/png would mislabel every restored image.
        out, mime = _normalize_image_for_storage(_encode(_photo(2500, 1000)), "image/png")
        assert _decode(out).format == "JPEG"
        assert mime == "image/jpeg"


class TestNeverMakesThingsWorse:
    def test_never_returns_more_bytes_than_it_received(self):
        for src, mime in [
            (_encode(_gradient(32, 32), "JPEG", quality=70), "image/jpeg"),
            (_encode(Image.new("RGB", (8, 8), (1, 2, 3))), "image/png"),
            (_encode(_gradient(600, 400)), "image/png"),
        ]:
            out, _ = _normalize_image_for_storage(src, mime)
            assert len(out) <= len(src)

    def test_unparseable_payload_is_stored_unchanged(self):
        garbage = base64.b64encode(b"definitely not an image").decode()
        assert _normalize_image_for_storage(garbage, "image/png") == (garbage, "image/png")

    def test_empty_payload_is_passed_through(self):
        assert _normalize_image_for_storage("", "image/png") == ("", "image/png")

    def test_running_twice_is_stable(self):
        # Compaction may re-run over rows it has already processed; a second
        # pass must not start a generational-loss spiral.
        once, mime1 = _normalize_image_for_storage(_encode(_photo(3000, 1500)), "image/png")
        twice, mime2 = _normalize_image_for_storage(once, mime1)
        assert len(twice) <= len(once)
        assert mime2 == mime1
        assert _decode(twice).size == _decode(once).size


class TestAppearanceIsPreserved:
    def test_transparency_flattens_onto_white_not_black(self):
        src = _encode(_gradient(800, 600, "RGBA", alpha=0))
        out, _ = _normalize_image_for_storage(src, "image/png")
        result = _decode(out)
        assert result.format == "JPEG", "expected the re-encode path to run"
        r, g, b = result.convert("RGB").getpixel((400, 300))
        assert min(r, g, b) > 240, f"transparent area became {(r, g, b)}, expected white"

    def test_exif_orientation_is_applied_before_the_tag_is_dropped(self):
        # Browsers auto-orient from the tag. Re-encoding strips it, so the
        # rotation has to be baked into the pixels or images flip on restore.
        img = _gradient(400, 200)
        exif = img.getexif()
        exif[274] = 6  # rotate 90° CW
        buf = io.BytesIO()
        img.save(buf, format="JPEG", exif=exif, quality=95)

        out, _ = _normalize_image_for_storage(base64.b64encode(buf.getvalue()).decode(), "image/jpeg")

        result = _decode(out)
        assert (result.width, result.height) == (200, 400)

    def test_grayscale_survives_as_a_viewable_image(self):
        out, _ = _normalize_image_for_storage(_encode(_photo(2400, 1200, "L")), "image/png")
        assert _decode(out).size[0] <= 1920

    def test_visual_content_is_not_destroyed(self):
        src_img = _photo(2000, 1000)
        out, _ = _normalize_image_for_storage(_encode(src_img), "image/png")
        result = _decode(out).convert("RGB").resize((200, 100))
        expected = src_img.convert("RGB").resize((200, 100))
        diff = ImageChops.difference(result, expected)
        worst = max(ch[1] for ch in diff.getextrema())
        assert worst < 40, f"re-encode altered the image too much (max channel delta {worst})"


class TestCompactionDoesNotDegrade:
    """Compaction runs over rows that may ALREADY be normalized JPEGs.

    Re-encoding one of those buys a percent or two of disk and costs visible
    generation loss every run, so a rewrite must clear a real margin. Without
    this the "shrink artwork" maintenance task slowly destroys the artwork it
    exists to preserve.
    """

    def test_min_gain_refuses_a_rewrite_that_barely_helps(self):
        from core.api.server import _COMPACT_MIN_GAIN

        already_jpeg, mime = _normalize_image_for_storage(
            _encode(_photo(1200, 800), "JPEG", quality=90), "image/jpeg"
        )

        again, again_mime = _normalize_image_for_storage(
            already_jpeg, mime, min_gain=_COMPACT_MIN_GAIN
        )

        assert again == already_jpeg, "re-encoded an already-normalized JPEG"
        assert again_mime == mime

    def test_repeated_compaction_is_idempotent(self):
        from core.api.server import _COMPACT_MIN_GAIN

        data, mime = _normalize_image_for_storage(_encode(_photo(1600, 1000)), "image/png")
        after_first = data

        for _ in range(10):
            data, mime = _normalize_image_for_storage(
                data, mime, min_gain=_COMPACT_MIN_GAIN
            )

        assert data == after_first, "repeated compaction kept re-encoding"

    def test_upload_path_still_takes_any_shrink(self):
        # The default margin is zero: on upload the source is the user's
        # original and the conversion happens exactly once.
        out, mime = _normalize_image_for_storage(_encode(_photo(1600, 1000)), "image/png")
        assert mime == "image/jpeg"
        assert len(out) < len(_encode(_photo(1600, 1000)))

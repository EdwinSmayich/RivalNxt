"""Extracting one file from an archive must not damage what is already there.

``extract_member`` wrote straight onto the destination. Archive libraries find
out that the data is bad at the *end* of a member, when its checksum does not
match -- by then a working file had been overwritten with a broken one, and the
exception that followed left it in place. For 7z and rar the library was pointed
at the destination's own folder, so a failed extraction also left whatever
folders the archive contained, with partial files in them, inside the game's
mods folder.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import py7zr
import pytest

from core.utils import archive
from core.utils.archive import extract_member

PAYLOAD = bytes(range(256)) * 400  # 102,400 bytes, not compressible to nothing
MEMBER = "Nested/Folder/Mod_9999999_P.pak"


def make_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(MEMBER, PAYLOAD)
        zf.writestr("readme.txt", b"hello")
    return path


def make_7z(path: Path) -> Path:
    with py7zr.SevenZipFile(path, "w", filters=[{"id": py7zr.FILTER_COPY}]) as zf:
        zf.writestr(PAYLOAD, MEMBER)
    return path


def damage(path: Path) -> Path:
    """Flip bytes in the middle of the stored data; the directory stays intact."""
    raw = bytearray(path.read_bytes())
    at = raw.find(PAYLOAD[:64]) + 5000
    assert at > 5000, "payload not found in archive"
    for i in range(at, at + 16):
        raw[i] ^= 0xFF
    path.write_bytes(bytes(raw))
    return path


def listing(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)).replace("\\", "/") for p in folder.rglob("*"))


@pytest.fixture
def mods(tmp_path) -> Path:
    folder = tmp_path / "~mods" / "hela"
    folder.mkdir(parents=True)
    return folder


@pytest.mark.parametrize("make", [make_zip, make_7z], ids=["zip", "7z"])
class TestAGoodArchive:
    def test_the_member_arrives_whole(self, tmp_path, mods, make):
        dest = mods / "Mod_9999999_P.pak"
        extract_member(str(make(tmp_path / "a.bin.zip" if make is make_zip else tmp_path / "a.7z")), MEMBER, str(dest))
        assert dest.read_bytes() == PAYLOAD

    def test_nothing_else_appears_beside_it(self, tmp_path, mods, make):
        dest = mods / "Mod_9999999_P.pak"
        extract_member(str(make(tmp_path / ("a.zip" if make is make_zip else "a.7z"))), MEMBER, str(dest))
        assert listing(mods) == ["Mod_9999999_P.pak"]

    def test_it_replaces_what_was_there(self, tmp_path, mods, make):
        dest = mods / "Mod_9999999_P.pak"
        dest.write_bytes(b"previous version")
        extract_member(str(make(tmp_path / ("a.zip" if make is make_zip else "a.7z"))), MEMBER, str(dest))
        assert dest.read_bytes() == PAYLOAD

    def test_a_member_is_found_by_file_name_alone(self, tmp_path, mods, make):
        dest = mods / "Mod_9999999_P.pak"
        extract_member(
            str(make(tmp_path / ("a.zip" if make is make_zip else "a.7z"))), "mod_9999999_p.PAK", str(dest)
        )
        assert dest.read_bytes() == PAYLOAD


@pytest.mark.parametrize("make", [make_zip, make_7z], ids=["zip", "7z"])
class TestADamagedArchive:
    def source(self, tmp_path, make) -> str:
        return str(damage(make(tmp_path / ("a.zip" if make is make_zip else "a.7z"))))

    def test_the_working_file_survives(self, tmp_path, mods, make):
        dest = mods / "Mod_9999999_P.pak"
        dest.write_bytes(b"the working mod")

        with pytest.raises(Exception):
            extract_member(self.source(tmp_path, make), MEMBER, str(dest))

        assert dest.read_bytes() == b"the working mod"

    def test_no_broken_file_is_created(self, tmp_path, mods, make):
        dest = mods / "Mod_9999999_P.pak"

        with pytest.raises(Exception):
            extract_member(self.source(tmp_path, make), MEMBER, str(dest))

        assert not dest.exists()

    def test_the_mods_folder_is_left_exactly_as_it_was(self, tmp_path, mods, make):
        (mods / "Other_P.pak").write_bytes(b"x")

        with pytest.raises(Exception):
            extract_member(self.source(tmp_path, make), MEMBER, str(mods / "Mod_9999999_P.pak"))

        assert listing(mods) == ["Other_P.pak"]


class TestAMissingMember:
    def test_zip(self, tmp_path, mods):
        with pytest.raises(RuntimeError, match="member not found in zip"):
            extract_member(str(make_zip(tmp_path / "a.zip")), "nope.pak", str(mods / "nope.pak"))
        assert listing(mods) == []

    def test_7z(self, tmp_path, mods):
        with pytest.raises(RuntimeError, match="member not found in 7z"):
            extract_member(str(make_7z(tmp_path / "a.7z")), "nope.pak", str(mods / "nope.pak"))
        assert listing(mods) == []


class TestTheScratchFolder:
    """rar archives cannot be built here; this is the code path they share with 7z."""

    def test_a_library_that_dies_midway_leaves_nothing(self, tmp_path, monkeypatch):
        scratch_seen: list[Path] = []
        out = tmp_path / "out.part"

        def dies(folder: str) -> None:
            scratch_seen.append(Path(folder))
            target = Path(folder) / "Nested" / "Mod_P.pak"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"half of it")
            raise RuntimeError("Failed the read enough data: req=1048576 got=1018368")

        with pytest.raises(RuntimeError):
            archive._extract_via_scratch_dir(dies, "Nested/Mod_P.pak", out, "rar")

        assert not out.exists()
        assert scratch_seen and not scratch_seen[0].exists()

    def test_the_scratch_folder_is_outside_the_destination(self, tmp_path):
        out = tmp_path / "mods" / "out.part"
        out.parent.mkdir()
        seen: list[Path] = []

        def works(folder: str) -> None:
            seen.append(Path(folder))
            (Path(folder) / "Mod_P.pak").write_bytes(b"all of it")

        archive._extract_via_scratch_dir(works, "Mod_P.pak", out, "rar")

        assert out.read_bytes() == b"all of it"
        assert out.parent not in seen[0].parents
        assert not seen[0].exists()

    def test_a_library_that_writes_nothing_is_an_error(self, tmp_path):
        with pytest.raises(RuntimeError, match="extracted member not found in rar"):
            archive._extract_via_scratch_dir(lambda _f: None, "Mod_P.pak", tmp_path / "out", "rar")

    def test_the_rar_failure_keeps_the_wording_the_app_explains(self, tmp_path, monkeypatch):
        """describe_archive_failure() recognises this text and says what to do."""
        from core.api.services.downloads import describe_archive_failure

        class DamagedRar:
            def __init__(self, *_a, **_k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def infolist(self):
                return [type("Info", (), {"filename": "Mod_P.pak"})()]

            def extract(self, _member, _folder):
                raise RuntimeError("Failed the read enough data: req=1048576 got=1018368")

        monkeypatch.setattr(archive.rarfile, "RarFile", DamagedRar)
        monkeypatch.setattr(archive, "_configure_rarfile", lambda: None)
        dest = tmp_path / "Mod_P.pak"
        dest.write_bytes(b"the working mod")

        with pytest.raises(RuntimeError) as caught:
            extract_member(str(tmp_path / "broken.rar"), "Mod_P.pak", str(dest))

        assert "after reconfiguration" in str(caught.value)
        assert describe_archive_failure(caught.value, "broken.rar")
        assert dest.read_bytes() == b"the working mod"
        assert listing(tmp_path) == ["Mod_P.pak"]

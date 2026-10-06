"""A mod is three files that only work together; they must change together.

``Name.pak``, ``Name.utoc`` and ``Name.ucas`` are one mod. The game looks for
the ``.pak`` and opens the other two beside it, and it keeps the ``.ucas`` open
for as long as it runs -- so on Windows that one file cannot be replaced, moved
or deleted while the game is up, and the other two can.

Everything here used to be done a file at a time with failures skipped, which
with the game running meant: a new ``.pak`` and ``.utoc`` describing an old
``.ucas``; a ``.pak`` moved to another folder without its container; and
``.ucas`` files left behind by mods that had been switched off.
"""
from __future__ import annotations

import os
import stat
import time
from pathlib import Path

import pytest

from core.utils import mod_files
from core.utils.mod_files import (
    NEW_SUFFIX,
    OLD_SUFFIX,
    FileInUseError,
    StagedInstall,
    find_orphan_companions,
    in_use_message,
    move_bundle,
    recover_interrupted,
    remove_mod_files,
    set_aside,
    stems_of,
    sweep_orphan_companions,
)

BUNDLE = ("Mod_9999999_P.pak", "Mod_9999999_P.utoc", "Mod_9999999_P.ucas")
windows_only = pytest.mark.skipif(os.name != "nt", reason="open files are only locked on Windows")


def put(folder: Path, names=BUNDLE, content: bytes = b"old") -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name in names:
        path = folder / name
        path.write_bytes(content + b":" + name.encode())
        out.append(path)
    return out


def contents(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir()) if p.is_file()}


def refuse(monkeypatch, attr: str, when):
    """Make os.<attr> raise PermissionError for the paths ``when`` picks out."""
    real = getattr(os, attr)

    def guarded(src, *args, **kwargs):
        if when(Path(src)):
            raise PermissionError(13, "The process cannot access the file", str(src))
        return real(src, *args, **kwargs)

    monkeypatch.setattr(mod_files.os, attr, guarded)


def refuse_unlink(monkeypatch, when):
    real = Path.unlink

    def guarded(self, *args, **kwargs):
        if when(self):
            raise PermissionError(13, "The process cannot access the file", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", guarded)
    monkeypatch.setattr(mod_files.os, "chmod", lambda *_a, **_k: None)


def stage(install: StagedInstall, folder: Path, names=BUNDLE, content: bytes = b"new") -> None:
    for name in names:
        install.reserve(folder / name).write_bytes(content + b":" + name.encode())


# --------------------------------------------------------------------------
# Installing
# --------------------------------------------------------------------------
class TestStagedInstall:
    def test_nothing_is_visible_until_commit(self, tmp_path):
        install = StagedInstall()
        stage(install, tmp_path)

        assert not any((tmp_path / name).exists() for name in BUNDLE)
        assert all(p.name.endswith(NEW_SUFFIX) for p in tmp_path.iterdir())

    def test_commit_puts_everything_in_place(self, tmp_path):
        install = StagedInstall()
        stage(install, tmp_path)

        placed = install.commit()

        assert sorted(p.name for p in placed) == sorted(BUNDLE)
        assert contents(tmp_path) == {name: b"new:" + name.encode() for name in BUNDLE}

    def test_what_was_there_is_replaced_and_no_copies_are_left(self, tmp_path):
        put(tmp_path)
        install = StagedInstall()
        stage(install, tmp_path)

        install.commit()

        assert contents(tmp_path) == {name: b"new:" + name.encode() for name in BUNDLE}

    def test_a_file_the_game_has_open_stops_the_whole_install(self, tmp_path, monkeypatch):
        """The case that used to pair a new .pak with an old .ucas."""
        put(tmp_path)
        before = contents(tmp_path)
        install = StagedInstall()
        stage(install, tmp_path)
        refuse(monkeypatch, "replace", lambda p: p.name == "Mod_9999999_P.ucas")

        with pytest.raises(FileInUseError) as caught:
            install.commit()

        assert caught.value.path.name == "Mod_9999999_P.ucas"
        assert contents(tmp_path) == before

    def test_a_failure_while_placing_puts_the_old_files_back(self, tmp_path, monkeypatch):
        put(tmp_path)
        before = contents(tmp_path)
        install = StagedInstall()
        stage(install, tmp_path)
        real = os.replace

        def disk_trouble(src, dst):
            if str(src).endswith(NEW_SUFFIX) and str(dst).endswith(".utoc"):
                raise OSError(5, "Input/output error")
            return real(src, dst)

        monkeypatch.setattr(mod_files.os, "replace", disk_trouble)

        with pytest.raises(OSError):
            install.commit()

        assert contents(tmp_path) == before

    def test_the_pak_goes_in_last(self, tmp_path, monkeypatch):
        """Until the .pak is there the game does not look at the rest."""
        install = StagedInstall()
        stage(install, tmp_path)
        order: list[str] = []
        real = os.replace

        def recording(src, dst):
            order.append(Path(dst).suffix)
            return real(src, dst)

        monkeypatch.setattr(mod_files.os, "replace", recording)
        install.commit()

        assert order[-1] == ".pak"

    def test_leaving_the_block_without_committing_discards(self, tmp_path):
        put(tmp_path)
        before = contents(tmp_path)

        with pytest.raises(RuntimeError):
            with StagedInstall() as install:
                stage(install, tmp_path)
                raise RuntimeError("archive turned out to be damaged")

        assert contents(tmp_path) == before

    def test_a_reserved_file_that_was_never_written_fails_cleanly(self, tmp_path):
        put(tmp_path)
        before = contents(tmp_path)
        install = StagedInstall()
        install.reserve(tmp_path / BUNDLE[0])

        with pytest.raises(FileNotFoundError):
            install.commit()

        assert contents(tmp_path) == before

    def test_reserving_a_name_twice_gives_the_same_place(self, tmp_path):
        install = StagedInstall()
        first = install.reserve(tmp_path / "Mod_P.pak")
        assert install.reserve(tmp_path / "Mod_P.pak") == first
        assert len(install) == 1

    def test_two_installs_do_not_share_staging_names(self, tmp_path):
        a, b = StagedInstall(), StagedInstall()
        assert a.reserve(tmp_path / "Mod_P.pak") != b.reserve(tmp_path / "Mod_P.pak")

    @windows_only
    def test_a_really_open_file_stops_it(self, tmp_path):
        put(tmp_path)
        before = contents(tmp_path)
        install = StagedInstall()
        stage(install, tmp_path)

        with open(tmp_path / "Mod_9999999_P.ucas", "rb"):
            with pytest.raises(FileInUseError):
                install.commit()

        assert contents(tmp_path) == before


# --------------------------------------------------------------------------
# Removing
# --------------------------------------------------------------------------
class TestRemoveModFiles:
    def test_removes_the_whole_mod(self, tmp_path):
        files = put(tmp_path)
        outcome = remove_mod_files(files)

        assert sorted(p.name for p in outcome.removed) == sorted(BUNDLE)
        assert outcome.blocked == [] and outcome.left_behind == []
        assert contents(tmp_path) == {}

    def test_a_pak_that_will_not_go_keeps_its_mod_whole(self, tmp_path, monkeypatch):
        files = put(tmp_path)
        before = contents(tmp_path)
        refuse_unlink(monkeypatch, lambda p: p.suffix == ".pak")

        outcome = remove_mod_files(files)
        monkeypatch.undo()

        assert [p.name for p in outcome.blocked] == ["Mod_9999999_P.pak"]
        assert outcome.removed == []
        assert contents(tmp_path) == before

    def test_a_stuck_container_is_reported_not_swallowed(self, tmp_path, monkeypatch):
        """What happens when a mod is switched off with the game running."""
        files = put(tmp_path)
        refuse_unlink(monkeypatch, lambda p: p.suffix == ".ucas")

        outcome = remove_mod_files(files)
        monkeypatch.undo()

        assert sorted(p.suffix for p in outcome.removed) == [".pak", ".utoc"]
        assert [p.name for p in outcome.left_behind] == ["Mod_9999999_P.ucas"]
        assert outcome.blocked == []

    def test_the_pak_is_tried_before_anything_else(self, tmp_path, monkeypatch):
        files = put(tmp_path)
        order: list[str] = []
        real = Path.unlink

        def recording(self, *args, **kwargs):
            order.append(self.suffix)
            return real(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", recording)
        remove_mod_files(reversed(files))

        assert order[0] == ".pak"

    def test_one_stuck_mod_does_not_stop_the_others(self, tmp_path, monkeypatch):
        a = put(tmp_path, ("A_P.pak", "A_P.utoc", "A_P.ucas"))
        b = put(tmp_path, ("B_P.pak", "B_P.utoc", "B_P.ucas"))
        refuse_unlink(monkeypatch, lambda p: p.name == "A_P.pak")

        outcome = remove_mod_files([*a, *b])
        monkeypatch.undo()

        assert [p.name for p in outcome.blocked] == ["A_P.pak"]
        assert sorted(contents(tmp_path)) == ["A_P.pak", "A_P.ucas", "A_P.utoc"]

    def test_same_name_in_two_folders_is_two_mods(self, tmp_path, monkeypatch):
        luna = put(tmp_path / "luna")
        hela = put(tmp_path / "hela")
        refuse_unlink(monkeypatch, lambda p: p.suffix == ".pak" and p.parent.name == "luna")

        outcome = remove_mod_files([*luna, *hela])
        monkeypatch.undo()

        assert len(contents(tmp_path / "luna")) == 3
        assert contents(tmp_path / "hela") == {}
        assert len(outcome.blocked) == 1

    def test_files_already_gone_are_not_an_error(self, tmp_path):
        outcome = remove_mod_files([tmp_path / name for name in BUNDLE])
        assert outcome.removed == [] and outcome.blocked == [] and outcome.left_behind == []

    def test_a_path_given_twice_is_handled_once(self, tmp_path):
        files = put(tmp_path)
        outcome = remove_mod_files([*files, *files])
        assert len(outcome.removed) == 3

    def test_a_read_only_file_is_still_removed(self, tmp_path):
        """7z and rar archives carry the attribute into the mods folder."""
        files = put(tmp_path)
        for path in files:
            os.chmod(path, stat.S_IREAD)

        outcome = remove_mod_files(files)

        assert len(outcome.removed) == 3
        assert contents(tmp_path) == {}

    @windows_only
    def test_a_really_open_container_is_left_behind(self, tmp_path):
        files = put(tmp_path)
        with open(tmp_path / "Mod_9999999_P.ucas", "rb"):
            outcome = remove_mod_files(files)

        assert [p.name for p in outcome.left_behind] == ["Mod_9999999_P.ucas"]
        assert sorted(contents(tmp_path)) == ["Mod_9999999_P.ucas"]


# --------------------------------------------------------------------------
# Moving between folders
# --------------------------------------------------------------------------
class TestMoveBundle:
    def test_moves_the_three_together(self, tmp_path):
        files = put(tmp_path)
        moved = move_bundle(files, tmp_path / "luna_snow")

        assert sorted(p.name for p in moved) == sorted(BUNDLE)
        assert contents(tmp_path) == {}
        assert len(contents(tmp_path / "luna_snow")) == 3

    def test_a_container_the_game_has_open_moves_nothing(self, tmp_path, monkeypatch):
        """Otherwise the .pak arrives in its new folder without it."""
        files = put(tmp_path)
        before = contents(tmp_path)
        refuse(monkeypatch, "rename", lambda p: p.suffix == ".ucas")

        with pytest.raises(FileInUseError):
            move_bundle(files, tmp_path / "luna_snow")

        assert contents(tmp_path) == before
        assert contents(tmp_path / "luna_snow") == {}

    def test_a_failure_on_the_last_file_brings_the_others_back(self, tmp_path, monkeypatch):
        files = put(tmp_path)
        before = contents(tmp_path)
        refuse(monkeypatch, "rename", lambda p: p.suffix == ".pak" and p.parent == tmp_path)

        with pytest.raises(FileInUseError):
            move_bundle(files, tmp_path / "luna_snow")

        assert contents(tmp_path) == before
        assert contents(tmp_path / "luna_snow") == {}

    def test_a_name_already_taken_moves_nothing(self, tmp_path):
        files = put(tmp_path)
        before = contents(tmp_path)
        put(tmp_path / "luna_snow", ("Mod_9999999_P.utoc",), b"other")

        with pytest.raises(FileExistsError):
            move_bundle(files, tmp_path / "luna_snow")

        assert contents(tmp_path) == before
        assert contents(tmp_path / "luna_snow") == {"Mod_9999999_P.utoc": b"other:Mod_9999999_P.utoc"}

    @windows_only
    def test_a_really_open_container_moves_nothing(self, tmp_path):
        files = put(tmp_path)
        before = contents(tmp_path)

        with open(tmp_path / "Mod_9999999_P.ucas", "rb"):
            with pytest.raises(FileInUseError):
                move_bundle(files, tmp_path / "luna_snow")

        assert contents(tmp_path) == before


class TestSetAside:
    def test_files_keep_their_layout(self, tmp_path):
        mods = tmp_path / "~mods"
        files = put(mods / "hela") + put(mods, ("Loose_P.pak",))
        holding = tmp_path / "held"

        moved, stuck = set_aside(files, mods, holding)

        assert stuck == []
        assert len(moved) == 4
        assert sorted(contents(holding / "hela")) == sorted(BUNDLE)
        assert (holding / "Loose_P.pak").read_bytes() == b"old:Loose_P.pak"
        assert contents(mods / "hela") == {} and contents(mods) == {}

    def test_a_mod_that_cannot_be_moved_stays_whole(self, tmp_path, monkeypatch):
        mods = tmp_path / "~mods"
        files = put(mods)
        before = contents(mods)
        real = mod_files.shutil.move

        def refusing(src, dst):
            if str(src).endswith(".pak"):
                raise PermissionError(13, "in use", src)
            return real(src, dst)

        monkeypatch.setattr(mod_files.shutil, "move", refusing)
        moved, stuck = set_aside(files, mods, tmp_path / "held")
        monkeypatch.undo()

        assert moved == []
        assert sorted(p.name for p in stuck) == sorted(BUNDLE)
        assert contents(mods) == before


# --------------------------------------------------------------------------
# What a removal with the game running leaves behind
# --------------------------------------------------------------------------
KNOWN = {"mod_9999999_p"}


class TestOrphanCompanions:
    def future(self) -> float:
        """A moment at which every file made by this test counts as old."""
        return time.time() + 3600

    def test_a_container_without_its_pak_is_found(self, tmp_path):
        files = put(tmp_path, ("Mod_9999999_P.ucas",))
        assert find_orphan_companions(files, KNOWN, now=self.future()) == files

    def test_one_with_its_pak_is_not(self, tmp_path):
        files = put(tmp_path)
        assert find_orphan_companions(files, KNOWN, now=self.future()) == []

    def test_a_pak_in_another_folder_still_counts(self, tmp_path):
        files = put(tmp_path / "a", ("Mod_9999999_P.ucas",)) + put(tmp_path / "b", ("Mod_9999999_P.pak",))
        assert find_orphan_companions(files, KNOWN, now=self.future()) == []

    def test_a_pak_renamed_to_switch_it_off_by_hand_still_counts(self, tmp_path):
        files = put(tmp_path, ("Mod_9999999_P.ucas", "Mod_9999999_P.utoc", "Mod_9999999_P.pak.disabled"))
        assert find_orphan_companions(files, KNOWN, now=self.future()) == []

    def test_a_file_this_app_did_not_install_is_never_touched(self, tmp_path):
        files = put(tmp_path, ("Handmade_P.ucas",))
        assert find_orphan_companions(files, KNOWN, now=self.future()) == []

    def test_a_recent_file_is_left_alone(self, tmp_path):
        """Somebody may be half-way through copying a mod in."""
        files = put(tmp_path, ("Mod_9999999_P.ucas",))
        assert find_orphan_companions(files, KNOWN, now=time.time() + 30) == []

    def test_a_similar_name_is_not_the_same_mod(self, tmp_path):
        files = put(tmp_path, ("Mod_9999999_P.ucas", "Mod_9999999_P_Alt.pak"))
        assert find_orphan_companions(files, KNOWN, now=self.future()) == [files[0]]

    def test_sweeping_deletes_them_and_nothing_else(self, tmp_path):
        files = put(tmp_path, ("Mod_9999999_P.ucas", "Handmade_P.ucas", "Other_P.pak"))

        swept = sweep_orphan_companions(files, KNOWN, now=self.future())

        assert [p.name for p in swept] == ["Mod_9999999_P.ucas"]
        assert sorted(contents(tmp_path)) == ["Handmade_P.ucas", "Other_P.pak"]

    def test_one_still_in_use_is_skipped_quietly(self, tmp_path, monkeypatch):
        files = put(tmp_path, ("Mod_9999999_P.ucas",))
        refuse_unlink(monkeypatch, lambda p: True)

        swept = sweep_orphan_companions(files, KNOWN, now=self.future())
        monkeypatch.undo()

        assert swept == []
        assert files[0].exists()


def test_stems_of_reads_paths_and_names():
    assert stems_of(["sub/Mod_9999999_P.pak", "Other_P.UTOC", "readme.txt", "", None, 7]) == {
        "mod_9999999_p",
        "other_p",
    }


def test_stems_of_handles_windows_separators():
    assert stems_of(["sub\\variant\\Mod_P.pak"]) == {"mod_p"}


# --------------------------------------------------------------------------
# After a crash in the middle of an install
# --------------------------------------------------------------------------
class TestRecoverInterrupted:
    def test_a_working_mod_moved_aside_goes_back(self, tmp_path):
        """Killed between moving the old files away and putting the new in."""
        aside = tmp_path / "hela" / f"Mod_9999999_P.pak.0123abcd{OLD_SUFFIX}"
        aside.parent.mkdir()
        aside.write_bytes(b"the working mod")

        report = recover_interrupted(tmp_path)

        assert (tmp_path / "hela" / "Mod_9999999_P.pak").read_bytes() == b"the working mod"
        assert report["restored"] == ["Mod_9999999_P.pak"]
        assert not aside.exists()

    def test_a_superseded_copy_is_deleted(self, tmp_path):
        (tmp_path / "Mod_9999999_P.pak").write_bytes(b"new")
        aside = tmp_path / f"Mod_9999999_P.pak.0123abcd{OLD_SUFFIX}"
        aside.write_bytes(b"old")

        report = recover_interrupted(tmp_path)

        assert (tmp_path / "Mod_9999999_P.pak").read_bytes() == b"new"
        assert not aside.exists()
        assert report["discarded"] == [aside.name]

    def test_a_staged_file_that_never_arrived_is_deleted(self, tmp_path):
        staged = tmp_path / f"Mod_9999999_P.ucas.0123abcd{NEW_SUFFIX}"
        staged.write_bytes(b"half")

        recover_interrupted(tmp_path)

        assert not staged.exists()
        assert not (tmp_path / "Mod_9999999_P.ucas").exists()

    def test_the_temporary_file_of_a_cut_off_extraction_is_deleted(self, tmp_path):
        """extract_member() writes <name>.<8 hex>.part and renames at the end."""
        direct = tmp_path / "Mod_9999999_P.pak.89abcdef.part"
        direct.write_bytes(b"half")
        nested = tmp_path / "hela" / f"Mod_9999999_P.ucas.0123abcd{NEW_SUFFIX}.89abcdef.part"
        nested.parent.mkdir()
        nested.write_bytes(b"half")

        report = recover_interrupted(tmp_path)

        assert not direct.exists() and not nested.exists()
        assert sorted(report["discarded"]) == sorted([direct.name, nested.name])

    def test_a_file_that_only_resembles_one_is_kept(self, tmp_path):
        keep = [tmp_path / "notes.part", tmp_path / "Mod_P.pak.part", tmp_path / "Mod_P.pak.backup"]
        for path in keep:
            path.write_bytes(b"x")

        recover_interrupted(tmp_path)

        assert all(path.exists() for path in keep)

    def test_real_mod_files_are_not_touched(self, tmp_path):
        put(tmp_path / "hela")
        before = contents(tmp_path / "hela")

        report = recover_interrupted(tmp_path)

        assert contents(tmp_path / "hela") == before
        assert report == {"restored": [], "discarded": []}

    def test_a_missing_folder_is_fine(self, tmp_path):
        assert recover_interrupted(tmp_path / "nope") == {"restored": [], "discarded": []}


class TestTheMessage:
    def test_names_the_file_and_the_remedy(self):
        text = in_use_message(["sub/Mod_P.ucas"], doing="nothing was changed")
        assert "Mod_P.ucas is in use" in text
        assert "Close the game" in text
        assert "nothing was changed" in text

    def test_several_files_are_summarised(self):
        text = in_use_message(["A_P.pak", "B_P.pak", "C_P.pak"], doing="they are still on")
        assert "A_P.pak and 2 more are in use" in text

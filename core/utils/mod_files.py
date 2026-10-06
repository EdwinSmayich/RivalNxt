"""Putting mod files into the game's folder, and taking them out again.

Both used to work one file at a time, straight onto the final names, and
neither checked that it had succeeded.

Installing deleted the file already there and then extracted onto its name. A
damaged archive, a full disk or a file the running game had open stopped that
part-way: a mod made of three files could be left with a new ``.pak`` and
``.utoc`` describing an old -- or half-written -- ``.ucas``. The game loads that
as it would any other mod.

Removing wrapped every delete in ``except: pass``. A file the game still had
open stayed where it was, the mod was recorded as off, and nothing said so.

Here an install is collected beside the destinations under names the game does
not read, then put in place together or not at all; and a removal reports what
it could not do.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Suffixes for files in transit. None ends in an extension the game mounts.
NEW_SUFFIX = ".rivalnxt-new"    # written, waiting to be put in place
OLD_SUFFIX = ".rivalnxt-old"    # moved aside to make way; goes back if the install dies
GONE_SUFFIX = ".rivalnxt-gone"  # being deleted; never goes back

BUNDLE_EXTS: Tuple[str, ...] = (".pak", ".utoc", ".ucas")
# With the signature file some setups keep beside a pak. This app never
# installs one, so it is only ever removed along with a download that is being
# deleted outright -- never by switching a mod off, which would leave nothing
# to put it back when the mod is switched on again.
MOD_FILE_EXTS: Tuple[str, ...] = (".pak", ".utoc", ".ucas", ".sig")
COMPANION_EXTS: Tuple[str, ...] = (".utoc", ".ucas")

# A companion is only swept once it has sat untouched this long, so that a
# file somebody is in the middle of copying in by hand is never taken.
ORPHAN_MIN_AGE_SECONDS = 600.0

# Installs and removals take turns. Several requests arrive at once when a
# collection is switched on or off, and two of them moving the same file aside
# would each believe the other's copy was the original.
MODS_FOLDER_LOCK = threading.RLock()

_ASIDE_NAME = re.compile(r"^(?P<original>.+)\.[0-9a-f]{8}" + re.escape(OLD_SUFFIX) + r"$", re.IGNORECASE)
# What extract_member() writes to before renaming: <name>.<8 hex>.part
_EXTRACTION_TEMP = re.compile(r"\.[0-9a-f]{8}\.part$", re.IGNORECASE)


class FileInUseError(Exception):
    """A file in the mods folder could not be replaced: something has it open.

    In practice that something is the game, which keeps the containers of every
    loaded mod open for as long as it runs.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(f"{Path(path).name} is in use by another program")
        self.path = Path(path)


def in_use_message(names: Sequence[str], *, doing: str) -> str:
    """What to tell the user when the game is holding files we need."""
    unique = sorted({os.path.basename(n) for n in names if n})
    if not unique:
        subject = "A file"
    elif len(unique) == 1:
        subject = unique[0]
    else:
        subject = f"{unique[0]} and {len(unique) - 1} more"
    verb = "is" if len(unique) <= 1 else "are"
    return (
        f"{subject} {verb} in use, most likely by Marvel Rivals, so {doing}. "
        "Close the game and try again."
    )


def _delete(path: Path) -> bool:
    """Delete one file. True when it is gone afterwards.

    Archives can carry the read-only attribute into the mods folder, and on
    Windows that alone makes a delete fail the same way a file in use does --
    so it is cleared and the delete tried once more before giving up.
    """
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return True
    except PermissionError:
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False
    except OSError:
        return False


def _is_pak(path: Path) -> bool:
    return path.suffix.lower() == ".pak"


class StagedInstall:
    """Files written beside their destinations, then put in place together.

    ``reserve()`` gives the name to write each file to. ``commit()`` swaps the
    whole set in: every file already at a destination is first moved aside, and
    if any of them cannot be -- the game has it open -- the ones already moved
    are put back and nothing has changed. Used as a context manager, anything
    not committed is discarded on the way out.
    """

    def __init__(self) -> None:
        self._token = uuid.uuid4().hex[:8]
        self._staged: Dict[str, Tuple[Path, Path]] = {}
        self._committed = False

    def __enter__(self) -> "StagedInstall":
        return self

    def __exit__(self, *_exc: object) -> None:
        if not self._committed:
            self.discard()

    def __len__(self) -> int:
        return len(self._staged)

    def reserve(self, final: Path) -> Path:
        """Where to write the file that is to become ``final``."""
        final = Path(final)
        key = os.path.normcase(str(final))
        if key not in self._staged:
            staged = final.with_name(f"{final.name}.{self._token}{NEW_SUFFIX}")
            self._staged[key] = (staged, final)
        return self._staged[key][0]

    def discard(self) -> None:
        for staged, _final in self._staged.values():
            _delete(staged)
        self._staged.clear()

    def commit(self) -> List[Path]:
        """Put every staged file in place. Returns the destinations.

        Raises FileInUseError, having changed nothing, if a file that has to
        make way cannot be moved.
        """
        # The .pak goes last: it is what makes the game look at the rest, so a
        # mod is never visible before all of it is there.
        pairs = sorted(self._staged.values(), key=lambda p: (_is_pak(p[1]), p[1].name.lower()))
        missing = [staged for staged, _final in pairs if not staged.is_file()]
        if missing:
            self.discard()
            raise FileNotFoundError(f"staged file missing: {missing[0].name}")

        moved_aside: List[Tuple[Path, Path]] = []
        placed: List[Path] = []
        try:
            for _staged, final in pairs:
                if not final.exists():
                    continue
                aside = final.with_name(f"{final.name}.{self._token}{OLD_SUFFIX}")
                try:
                    os.replace(final, aside)
                except PermissionError as exc:
                    raise FileInUseError(final) from exc
                moved_aside.append((aside, final))
            for staged, final in pairs:
                os.replace(staged, final)
                placed.append(final)
        except BaseException:
            for final in placed:
                _delete(final)
            for aside, final in reversed(moved_aside):
                try:
                    os.replace(aside, final)
                except OSError:
                    pass
            self.discard()
            raise

        self._committed = True
        self._staged.clear()
        for aside, _final in moved_aside:
            # Still open somewhere, perhaps; recover_interrupted() takes it later.
            _delete(aside)
        return placed


@dataclass
class RemovalOutcome:
    removed: List[Path] = field(default_factory=list)
    # .pak files that would not go. Their mods are untouched and still on.
    blocked: List[Path] = field(default_factory=list)
    # Companions of a .pak that did go. The mod is off; these are dead weight
    # until whatever holds them lets go, and the orphan sweep collects them.
    left_behind: List[Path] = field(default_factory=list)


def remove_mod_files(paths: Iterable[Path]) -> RemovalOutcome:
    """Delete mod files, each mod's ``.pak`` first.

    The ``.pak`` is what the game looks for; without it the ``.utoc`` and
    ``.ucas`` beside it are never opened. So taking the ``.pak`` first means a
    mod is either still whole (its ``.pak`` would not go, and the rest is left
    alone) or off (the ``.pak`` went, and whatever else is stuck is inert).
    The old order -- whatever came first -- could remove a ``.utoc`` and leave
    the ``.pak``: a mod that is still on and no longer loads.
    """
    outcome = RemovalOutcome()
    bundles: Dict[Tuple[str, str], List[Path]] = {}
    seen: Set[str] = set()
    for raw in paths:
        path = Path(raw)
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        bundles.setdefault((os.path.normcase(str(path.parent)), path.stem.lower()), []).append(path)

    for members in bundles.values():
        members.sort(key=lambda p: (not _is_pak(p), p.suffix.lower()))
        pak_blocked = False
        for path in members:
            if pak_blocked:
                break
            if not path.exists():
                continue
            if _delete(path):
                outcome.removed.append(path)
            elif _is_pak(path):
                outcome.blocked.append(path)
                pak_blocked = True
            else:
                outcome.left_behind.append(path)
    return outcome


def find_mod_files(
    mods_dir: Path,
    *,
    stems: Iterable[str] = (),
    names: Iterable[str] = (),
    exts: Sequence[str] = BUNDLE_EXTS,
) -> List[Path]:
    """Files under ``mods_dir`` that belong to the given mods, in one walk.

    A file matches if its name is in ``names``, or its stem is in ``stems``
    and its extension is one of ``exts``. Case does not matter.
    """
    root = Path(mods_dir)
    if not root.is_dir():
        return []
    wanted_stems = {str(st).lower() for st in stems if st}
    wanted_names = {os.path.basename(str(n)).lower() for n in names if n}
    if not wanted_stems and not wanted_names:
        return []
    found: List[Path] = []
    try:
        for path in root.rglob("*"):
            lower = path.name.lower()
            if lower in wanted_names or (
                path.suffix.lower() in exts and path.stem.lower() in wanted_stems
            ):
                if path.is_file():
                    found.append(path)
    except OSError:
        pass
    return found


def remove_all_or_nothing(paths: Iterable[Path]) -> List[Path]:
    """Delete every one of ``paths``, or none of them.

    For deleting a download outright. Once its record and its archive are gone
    there is nothing left to say what a stray ``.ucas`` in the mods folder
    belonged to, so this refuses to start unless it can finish: every file is
    first renamed out of the way, which is exactly what fails for a file the
    game has open, and only when all of them have moved are they deleted.

    Raises FileInUseError with everything back under its own name.
    """
    token = uuid.uuid4().hex[:8]
    moved: List[Tuple[Path, Path]] = []
    seen: Set[str] = set()
    try:
        for raw in paths:
            path = Path(raw)
            key = os.path.normcase(str(path))
            if key in seen or not path.exists():
                continue
            seen.add(key)
            aside = path.with_name(f"{path.name}.{token}{GONE_SUFFIX}")
            try:
                os.replace(path, aside)
            except PermissionError as exc:
                raise FileInUseError(path) from exc
            moved.append((aside, path))
    except BaseException:
        for aside, path in reversed(moved):
            try:
                os.replace(aside, path)
            except OSError:
                pass
        raise
    for aside, _path in moved:
        # Anything that will not go now is collected by recover_interrupted().
        _delete(aside)
    return [path for _aside, path in moved]


# The order in which a mod's files are moved: the container the game keeps open
# first, so that if anything is going to refuse it does so before the rest has
# gone anywhere.
_MOVE_ORDER = {".ucas": 0, ".utoc": 1, ".pak": 3}


def move_bundle(members: Sequence[Path], target_dir: Path) -> List[Path]:
    """Move the files of one mod into ``target_dir`` -- all of them, or none.

    Moved one at a time with failures skipped, a ``.pak`` could arrive in its
    new folder while the ``.ucas`` the game had open stayed in the old one. The
    game finds the ``.pak``, looks beside it for the container, and the mod is
    broken until somebody notices.

    Raises FileExistsError if a name is already taken in ``target_dir`` and
    FileInUseError if a file cannot be moved; either way everything is back
    where it started.
    """
    target = Path(target_dir)
    ordered = sorted((Path(m) for m in members), key=lambda m: _MOVE_ORDER.get(m.suffix.lower(), 2))
    for src in ordered:
        if (target / src.name).exists():
            raise FileExistsError(src.name)
    target.mkdir(parents=True, exist_ok=True)
    done: List[Tuple[Path, Path]] = []
    try:
        for src in ordered:
            dest = target / src.name
            try:
                os.rename(src, dest)
            except PermissionError as exc:
                raise FileInUseError(src) from exc
            done.append((src, dest))
    except BaseException:
        for src, dest in reversed(done):
            try:
                os.rename(dest, src)
            except OSError:
                pass
        raise
    return [dest for _src, dest in done]


def set_aside(paths: Iterable[Path], root: Path, holding_dir: Path) -> Tuple[List[Path], List[Path]]:
    """Move files out of the mods folder into ``holding_dir``, keeping their layout.

    For files this app did not install and so cannot put back: they are taken
    out of the game's reach without being destroyed. Each mod's files go
    together. Returns ``(moved, stuck)``.
    """
    root = Path(root)
    holding = Path(holding_dir)
    bundles: Dict[Tuple[str, str], List[Path]] = {}
    for raw in paths:
        path = Path(raw)
        bundles.setdefault((os.path.normcase(str(path.parent)), path.stem.lower()), []).append(path)

    moved: List[Path] = []
    stuck: List[Path] = []
    for members in bundles.values():
        try:
            relative = members[0].parent.relative_to(root)
        except ValueError:
            relative = Path()
        destination = holding / relative
        done: List[Tuple[Path, Path]] = []
        try:
            destination.mkdir(parents=True, exist_ok=True)
            for src in sorted(members, key=lambda m: _MOVE_ORDER.get(m.suffix.lower(), 2)):
                dest = destination / src.name
                # Another drive is possible here, so this may be a copy.
                shutil.move(str(src), str(dest))
                done.append((src, dest))
        except Exception:
            for src, dest in reversed(done):
                try:
                    shutil.move(str(dest), str(src))
                except OSError:
                    pass
            stuck.extend(m for m in members if m.exists())
            continue
        moved.extend(dest for _src, dest in done)
    return moved, stuck


def find_orphan_companions(
    files: Iterable[Path],
    known_stems: Set[str],
    *,
    min_age_seconds: Optional[float] = None,
    now: Optional[float] = None,
) -> List[Path]:
    """``.utoc`` / ``.ucas`` files whose ``.pak`` is gone.

    These are what a mod switched off while the game was running leaves
    behind: the ``.pak`` could be deleted, the container the game had open
    could not. They do nothing and can be hundreds of megabytes each.

    Deliberately narrow. A file is only an orphan if

    * it belongs to a mod this app installed (``known_stems``), so the archive
      it came from is still in the downloads folder;
    * nothing else anywhere in the tree shares its name -- not a ``.pak``, and
      not a ``Name.pak.disabled`` either, which is how some people switch a mod
      off by hand;
    * it has not been touched for ``min_age_seconds`` (ORPHAN_MIN_AGE_SECONDS
      unless given).
    """
    current = time.time() if now is None else now
    min_age = ORPHAN_MIN_AGE_SECONDS if min_age_seconds is None else min_age_seconds
    live = [Path(f) for f in files]
    companions: List[Path] = []
    other_names: List[str] = []
    for path in live:
        if path.suffix.lower() in COMPANION_EXTS:
            companions.append(path)
        else:
            other_names.append(path.name.lower())

    orphans: List[Path] = []
    for path in companions:
        stem = path.stem.lower()
        if stem not in known_stems:
            continue
        prefix = stem + "."
        if any(name.startswith(prefix) for name in other_names):
            continue
        try:
            info = path.stat()
        except OSError:
            continue
        if current - max(info.st_mtime, info.st_ctime) < min_age:
            continue
        orphans.append(path)
    return orphans


def sweep_orphan_companions(
    files: Iterable[Path],
    known_stems: Set[str],
    *,
    min_age_seconds: Optional[float] = None,
    now: Optional[float] = None,
) -> List[Path]:
    """Delete what find_orphan_companions() finds. Returns what went."""
    removed: List[Path] = []
    for path in find_orphan_companions(files, known_stems, min_age_seconds=min_age_seconds, now=now):
        if _delete(path):
            removed.append(path)
    return removed


def stems_of(names: Iterable[object]) -> Set[str]:
    """Lower-cased stems of the mod files among ``names`` (paths or basenames)."""
    stems: Set[str] = set()
    for name in names:
        if not isinstance(name, str) or not name:
            continue
        stem, ext = os.path.splitext(os.path.basename(name.replace("\\", "/")))
        if stem and ext.lower() in BUNDLE_EXTS:
            stems.add(stem.lower())
    return stems


def recover_interrupted(mods_dir: Path) -> Dict[str, List[str]]:
    """Tidy up after an install that the app did not live to finish.

    A file moved aside whose original name is now empty is the user's working
    mod: it goes back. One whose name was filled is the superseded copy: it is
    deleted. Staged files that never made it are deleted, as are files a
    removal had already taken out of the way and the temporary file of an
    extraction that was cut off. Call only when no install can be running --
    at start-up, or holding MODS_FOLDER_LOCK.
    """
    report: Dict[str, List[str]] = {"restored": [], "discarded": []}
    root = Path(mods_dir)
    if not root.is_dir():
        return report
    try:
        leftovers = [
            p
            for p in root.rglob("*")
            if (
                p.name.lower().endswith((NEW_SUFFIX, OLD_SUFFIX, GONE_SUFFIX))
                or _EXTRACTION_TEMP.search(p.name)
            )
            and p.is_file()
        ]
    except OSError:
        return report
    # Asides first, so a restored original is in place before anything else.
    leftovers.sort(key=lambda p: not p.name.lower().endswith(OLD_SUFFIX))
    for path in leftovers:
        match = _ASIDE_NAME.match(path.name)
        if match:
            original = path.with_name(match.group("original"))
            if not original.exists():
                try:
                    os.replace(path, original)
                    report["restored"].append(original.name)
                    continue
                except OSError:
                    continue
        if _delete(path):
            report["discarded"].append(path.name)
    return report

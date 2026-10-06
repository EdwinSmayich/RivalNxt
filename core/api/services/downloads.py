"""Plumbing for downloads: how many run at once, which are already running,
and whether what arrived is the whole file.

Written after a day in which six archives in one library turned out to be
truncated, the same file was found downloading six times over, and cancelling
did nothing. Each piece here answers one of those.

* **Truncated archives were accepted as complete.** ``HTTPResponse.read(n)``
  does not raise when the server closes the connection early; it returns
  ``b""``, which the download loop took to mean "finished". The only check
  afterwards was that the file was not empty, and it was written straight to
  its final name -- so a download cut short, or a process killed mid-transfer,
  left something indistinguishable from a real archive. Four .rar files ended
  that way within 330 ms of each other; a fifth was left by closing the app.

* **The same file downloaded several times in parallel.** Nothing recorded that
  a download was in flight, so a second request for the same file started a
  second transfer, and every waiting download started at once with no cap. On
  a bandwidth-limited Nexus account that divides one connection's worth of
  speed between all of them, which is why "a pile of downloads" could sit
  there with none of them finishing.

* **Cancel did nothing while a download waited.** The flag was only read
  between chunks of a transfer already running.
"""
from __future__ import annotations

import threading
import time
import zipfile
import zlib
from collections import deque
from pathlib import Path
from typing import Callable, Deque, Dict, Hashable, Optional

#: Appended to a download until it has been verified. The folder scanner only
#: picks up .zip/.rar/.7z/.pak, so nothing with this suffix is ever ingested.
PART_SUFFIX = ".part"

#: Free Nexus accounts are bandwidth-capped per user, not per connection, so
#: more transfers at once only makes each of them slower.
MAX_PARALLEL_DOWNLOADS = 2

_RAR_MAGIC = b"Rar!\x1a\x07"
_7Z_MAGIC = b"7z\xbc\xaf\x27\x1c"


class DownloadSlots:
    """A first-come-first-served limit on simultaneous downloads.

    Waiting is cancellable and reports how many are ahead, so a queued download
    can say so instead of looking stuck.
    """

    def __init__(self, limit: int = MAX_PARALLEL_DOWNLOADS) -> None:
        self._limit = max(1, int(limit))
        self._active = 0
        self._waiting: Deque[object] = deque()
        self._cond = threading.Condition()

    @property
    def active(self) -> int:
        with self._cond:
            return self._active

    @property
    def waiting(self) -> int:
        with self._cond:
            return len(self._waiting)

    def acquire(
        self,
        *,
        is_cancelled: Optional[Callable[[], bool]] = None,
        on_wait: Optional[Callable[[int], None]] = None,
        poll_seconds: float = 0.5,
    ) -> bool:
        """Block until a slot is free. False means cancelled while waiting."""
        ticket = object()
        with self._cond:
            self._waiting.append(ticket)
            try:
                while True:
                    if self._waiting[0] is ticket and self._active < self._limit:
                        self._waiting.popleft()
                        self._active += 1
                        self._cond.notify_all()
                        return True
                    if is_cancelled is not None and is_cancelled():
                        self._waiting.remove(ticket)
                        self._cond.notify_all()
                        return False
                    if on_wait is not None:
                        on_wait(self._waiting.index(ticket))
                    self._cond.wait(timeout=poll_seconds)
            except BaseException:
                if ticket in self._waiting:
                    self._waiting.remove(ticket)
                    self._cond.notify_all()
                raise

    def release(self) -> None:
        with self._cond:
            self._active = max(0, self._active - 1)
            self._cond.notify_all()


class InflightRegistry:
    """Which files are being downloaded right now, and for whom."""

    def __init__(self) -> None:
        self._owners: Dict[Hashable, str] = {}
        self._lock = threading.Lock()

    def claim(self, key: Hashable, owner: str) -> Optional[str]:
        """Take ``key`` for ``owner``. Returns the current owner if already taken."""
        with self._lock:
            existing = self._owners.get(key)
            if existing is not None:
                return existing
            self._owners[key] = owner
            return None

    def release(self, key: Hashable, owner: str) -> None:
        with self._lock:
            if self._owners.get(key) == owner:
                self._owners.pop(key, None)

    def is_active(self, owner: str) -> bool:
        with self._lock:
            return owner in self._owners.values()


class CancelledSet:
    """Cancelled handoff ids, remembered for a while rather than until first read.

    The flag used to be discarded by whichever thread noticed it first. With the
    same handoff downloading more than once, that stopped one transfer and left
    the rest running, which is what "cancel does nothing" looked like.
    """

    def __init__(self, ttl_seconds: float = 3600.0) -> None:
        self._ttl = ttl_seconds
        self._ids: Dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, handoff_id: str) -> None:
        now = time.time()
        with self._lock:
            self._ids[handoff_id] = now
            for stale in [k for k, t in self._ids.items() if now - t > self._ttl]:
                self._ids.pop(stale, None)

    def discard(self, handoff_id: str) -> None:
        """Kept for callers that used to clear the flag; deliberately a no-op.

        Entries expire on their own. Clearing on first sight is the bug this
        class exists to remove.
        """

    def __contains__(self, handoff_id: object) -> bool:
        with self._lock:
            return handoff_id in self._ids


def length_problem(received: int, expected: Optional[int]) -> Optional[str]:
    """Why ``received`` bytes is not the whole file, or None if it is."""
    if expected is None or expected <= 0:
        return None
    if received == expected:
        return None
    if received < expected:
        return (
            f"the connection closed early: received {received:,} of "
            f"{expected:,} bytes"
        )
    return f"received {received:,} bytes where {expected:,} were announced"


def archive_problem(path: Path, *, suffix: Optional[str] = None) -> Optional[str]:
    """Why ``path`` is not a usable archive of the type its name claims.

    ``suffix`` names the type when the file on disk does not say -- a download
    still carries its .part name at the point it has to be checked.

    Cheap by design -- signatures and, for zip, the end-of-central-directory
    record. That record sits at the end of the file, so a truncated zip fails
    here even when the server announced no length. RAR headers sit at the
    start, so for .rar the length check is what catches truncation.
    """
    suffix = (suffix or path.suffix).lower()
    try:
        with path.open("rb") as fh:
            head = fh.read(8)
    except OSError as exc:
        return f"could not be read back: {exc}"

    if suffix == ".zip":
        if not zipfile.is_zipfile(path):
            return "is not a complete zip archive (its directory is missing)"
    elif suffix == ".rar":
        if not head.startswith(_RAR_MAGIC):
            return "is not a RAR archive"
    elif suffix == ".7z":
        if not head.startswith(_7Z_MAGIC):
            return "is not a 7z archive"
    return None


def partial_path(final: Path, token: str) -> Path:
    """Where a download lives until it is verified."""
    return final.with_name(f"{final.name}.{token}{PART_SUFFIX}")


def cleanup_partial_downloads(root: Path, *, older_than_seconds: float = 0.0) -> int:
    """Remove leftover partial downloads. Returns how many were removed."""
    removed = 0
    try:
        candidates = list(root.glob(f"*{PART_SUFFIX}"))
    except OSError:
        return 0
    now = time.time()
    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            if now - candidate.stat().st_mtime < older_than_seconds:
                continue
            candidate.unlink()
            removed += 1
        except OSError:
            continue
    return removed


#: Fragments of the errors the archive libraries raise for a file that is cut
#: short or corrupt. None of them says so in words a person would act on.
_DAMAGE_MARKERS = (
    "failed the read enough data",
    "unexpected end of archive",
    "checksum error",
    "crc check failed",
    "bad crc",
    "file is not a zip file",
    "not a 7z file",
    "not a rar file",
    "bad magic number",
    "invalid header data",
    "invalid distance",
    "invalid block type",
    "invalid stored block",
    "error -3 while decompressing",
    "error -5 while decompressing",
    "compressed file ended before",
    "truncated",
    "corrupt",
)

#: Exception classes that mean the same thing whatever their message says.
#: py7zr's checksum failure, for one, has no message at all: its text is the
#: tuple ``(297193375, 2584611980, 'Mod_P.ucas')``, which is what was shown.
_DAMAGE_ERROR_NAMES = frozenset(
    {
        "BadZipFile",
        "BadZipfile",
        "Bad7zFile",
        "BadRarFile",
        "NotRarFile",
        "CrcError",
        "RarCRCError",
        "LZMAError",
        "DecompressionError",
        "EOFError",
    }
)


def _is_damage(error: object) -> bool:
    seen = 0
    current: object = error
    while current is not None and seen < 6:
        if any(cls.__name__ in _DAMAGE_ERROR_NAMES for cls in type(current).__mro__):
            return True
        if isinstance(current, zlib.error):
            return True
        text = str(current).lower()
        if any(marker in text for marker in _DAMAGE_MARKERS):
            return True
        if not isinstance(current, BaseException):
            return False
        # A wrapper such as "Archive extract failed: ..." keeps the real error
        # underneath it.
        current = current.__cause__ or current.__context__
        seen += 1
    return False


def describe_archive_failure(error: object, archive_name: str = "") -> Optional[str]:
    """A plain explanation when ``error`` means the archive itself is damaged.

    Activating a mod from a truncated download used to surface the library's
    own words: "rar member extraction failed after reconfiguration: Failed the
    read enough data: req=1048576 got=1018368". That names no cause and no
    remedy. Returns None for errors that are about something else.
    """
    if not _is_damage(error):
        return None
    subject = f"{archive_name} is" if archive_name else "This archive is"
    return (
        f"{subject} damaged or incomplete, most likely from a download that "
        "was interrupted. Delete it and download it again."
    )

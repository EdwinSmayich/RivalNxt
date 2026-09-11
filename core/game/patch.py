"""When the game was last patched, and which mods have been rebuilt since.

A game patch can break every installed mod at once. It happened on 2026-09-11:
the game rewrote its containers at 13:03 and afterwards one mod out of ~180
still applied. Nothing about the mod manager was at fault -- the files were in
the right place, the AES key still decrypted the game's containers, the assets
the mods overlay still existed -- but there was no way to see which mods their
authors had since rebuilt except opening each card in turn.

Two questions, answered from data already on disk:

* **When did the game change?** The patcher rewrites the containers under
  ``Content/Paks``, so the newest modification time there is the patch. No
  network, no version string to parse, and it is right even for a game that
  reports no version at all.

* **Which mods moved after that?** ``mods.updated_timestamp`` is the Nexus
  mod's own last-updated time, already synced. A mod updated after the patch is
  one the author has touched since it broke.

"Updated since the patch" is not the same as "fixed", and this module does not
claim it is: an author may have changed a screenshot. It narrows ~180 mods to
the handful worth re-checking, which is the actual problem.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("modmanager.game")

#: Only the container files move on a patch; ignore stray logs or mod folders.
_CONTAINER_SUFFIXES = (".pak", ".utoc", ".ucas", ".sig")


def paks_dir(marvel_rivals_root: Optional[str | Path]) -> Optional[Path]:
    """The game's Paks folder, or None when the root is unset or wrong."""
    if not marvel_rivals_root:
        return None
    candidate = Path(marvel_rivals_root) / "MarvelGame" / "Marvel" / "Content" / "Paks"
    return candidate if candidate.is_dir() else None


def detect_patch_time(marvel_rivals_root: Optional[str | Path]) -> Optional[Dict[str, Any]]:
    """Newest container modification time under Paks, with the file it came from.

    Mod folders live under ``Paks/~mods``; they are excluded deliberately, or
    activating a mod would look like a game patch.
    """
    root = paks_dir(marvel_rivals_root)
    if root is None:
        return None

    newest: Optional[float] = None
    source: Optional[str] = None
    for entry in root.iterdir():
        if not entry.is_file() or entry.suffix.lower() not in _CONTAINER_SUFFIXES:
            continue
        try:
            stamp = entry.stat().st_mtime
        except OSError:
            continue
        if newest is None or stamp > newest:
            newest = stamp
            source = entry.name

    if newest is None:
        return None
    return {
        "patched_at": datetime.fromtimestamp(newest, tz=timezone.utc).isoformat(),
        "patched_at_epoch": int(newest),
        "detected_from": source,
    }


def mods_updated_since(conn: sqlite3.Connection, epoch: int) -> List[Dict[str, Any]]:
    """Mods whose Nexus entry was updated after ``epoch``, newest first."""
    try:
        rows = conn.execute(
            """
            SELECT mod_id, name, author, version, updated_timestamp, picture_url
              FROM mods
             WHERE updated_timestamp IS NOT NULL
               AND updated_timestamp > ?
             ORDER BY updated_timestamp DESC
            """,
            (int(epoch),),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        # A database that predates the mods table should not break the endpoint.
        logger.warning("[patch] could not read mods: %s", exc)
        return []

    out: List[Dict[str, Any]] = []
    for mod_id, name, author, version, updated, picture in rows:
        out.append(
            {
                "mod_id": mod_id,
                "name": name,
                "author": author,
                "version": version,
                "updated_at": datetime.fromtimestamp(
                    int(updated), tz=timezone.utc
                ).isoformat(),
                "updated_timestamp": int(updated),
                "icon": picture,
            }
        )
    return out


def patch_status(
    conn: sqlite3.Connection, marvel_rivals_root: Optional[str | Path]
) -> Dict[str, Any]:
    """Everything the UI needs: when the game changed and what moved after."""
    detected = detect_patch_time(marvel_rivals_root)
    if detected is None:
        return {
            "known": False,
            "reason": "the Marvel Rivals folder is not set, or has no Paks directory",
        }

    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM mods WHERE mod_id IS NOT NULL"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        total = 0

    updated = mods_updated_since(conn, detected["patched_at_epoch"])
    return {
        "known": True,
        **detected,
        "mods_total": int(total),
        "updated_count": len(updated),
        "updated": updated,
    }

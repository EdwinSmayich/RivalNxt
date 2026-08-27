"""One-time migration: re-encode stored mod artwork down to display size.

``mod_custom_images.image_data`` holds base64 originals. Uploads in the wild are
mostly already under 1920px but were saved as 16-bit/uncompressed PNG at 3.5-4.8
bytes per pixel — worse than raw — so the column grew to ~2.2 GB for a few
hundred images. This rewrites each row through the same normalizer the upload
path now uses.

The conversion is lossy and one-way, so the script refuses to touch the database
until :func:`core.backup.service.create_backup` has written a restorable archive.
Restore it from the app's Backups screen, or with ``restore_backup``.

Usage::

    python -m scripts.shrink_custom_images --dry-run    # measure, change nothing
    python -m scripts.shrink_custom_images              # backup, then migrate
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def _db_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SystemExit("APPDATA is not set; cannot locate mods.db")
    return Path(appdata) / "com.rivalnxt.modmanager" / "mods.db"


def _mb(n: int) -> float:
    return n / 1048576


def _reencode(b64: str) -> tuple[str, str] | None:
    """Return (base64, mime) for the shrunk image, or None to leave the row alone.

    Delegates to the same normalizer the upload endpoints and the in-app
    "Compact Mod Artwork" task use. This function previously inlined its own copy
    of the resize/flatten/encode logic; three implementations of "shrink an
    image" drifting apart is how a migration ends up writing artwork that does
    not match what the app produces for new uploads.
    """
    from core.api.server import _COMPACT_MIN_GAIN, _normalize_image_for_storage

    encoded, mime = _normalize_image_for_storage(
        b64, "image/png", min_gain=_COMPACT_MIN_GAIN
    )
    if encoded == b64:
        # Normalizer declined it: already efficient, or it could not be decoded.
        return None

    # Never write bytes we cannot read back.
    from PIL import Image

    Image.open(io.BytesIO(base64.b64decode(encoded))).verify()
    return encoded, mime


def _guard_app_not_running(db: Path) -> None:
    """Refuse to migrate while the app holds the database open."""
    try:
        probe = sqlite3.connect(str(db), timeout=2.0)
        try:
            probe.execute("BEGIN IMMEDIATE")
            probe.rollback()
        finally:
            probe.close()
    except sqlite3.OperationalError as exc:
        raise SystemExit(
            f"Database is locked ({exc}). Close RivalNxt and run this again."
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="measure only, write nothing")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    db = _db_path()
    if not db.exists():
        raise SystemExit(f"database not found at {db}")

    try:
        import PIL  # noqa: F401
    except ImportError:
        raise SystemExit("Pillow is required: pip install Pillow")

    size_before = db.stat().st_size
    print(f"database: {db}")
    print(f"size before: {_mb(size_before):.1f} MB")

    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT id, LENGTH(image_data) FROM mod_custom_images ORDER BY id"
    ).fetchall()
    col_before = sum(r[1] or 0 for r in rows)
    print(f"{len(rows)} image rows, {_mb(col_before):.1f} MB of base64\n")

    if args.dry_run:
        conn.close()
        total_after = 0
        probe = sqlite3.connect(f"file:{str(db).replace(os.sep, '/')}?mode=ro", uri=True)
        skipped = failed = 0
        for img_id, _ in rows:
            b64 = probe.execute(
                "SELECT image_data FROM mod_custom_images WHERE id=?", (img_id,)
            ).fetchone()[0]
            try:
                result = _reencode(b64)
            except Exception as exc:
                print(f"  id={img_id} FAILED: {exc}")
                failed += 1
                total_after += len(b64)
                continue
            if result is None:
                skipped += 1
                total_after += len(b64)
            else:
                total_after += len(result[0])
        probe.close()
        print("\nDRY RUN — nothing written")
        print(f"  would skip (already efficient): {skipped}")
        print(f"  would fail (left as-is):        {failed}")
        print(f"  column: {_mb(col_before):.1f} MB -> {_mb(total_after):.1f} MB")
        print(f"  projected file after VACUUM: ~{_mb(size_before - col_before + total_after):.0f} MB")
        return 0

    _guard_app_not_running(db)

    if not args.yes:
        reply = input("This rewrites artwork irreversibly (a backup is made first). Continue? [y/N] ")
        if reply.strip().lower() not in ("y", "yes"):
            print("aborted")
            return 1

    # Backup gate: the archive is the only way back, so a failure here is fatal.
    print("creating backup (this reads the whole database)...")
    from core.backup.service import create_backup

    try:
        info = create_backup(name="pre-image-shrink")
    except Exception as exc:
        raise SystemExit(f"BACKUP FAILED, refusing to migrate: {exc}")
    archive = info.get("path") or info.get("archive") or info
    print(f"backup written: {archive}\n")

    converted = skipped = failed = 0
    total_after = 0
    for img_id, _ in rows:
        b64 = conn.execute(
            "SELECT image_data FROM mod_custom_images WHERE id=?", (img_id,)
        ).fetchone()[0]
        try:
            result = _reencode(b64)
        except Exception as exc:
            print(f"  id={img_id} FAILED, left unchanged: {exc}")
            failed += 1
            total_after += len(b64)
            continue
        if result is None:
            skipped += 1
            total_after += len(b64)
            continue
        data, mime = result
        conn.execute(
            "UPDATE mod_custom_images SET image_data=?, mime_type=? WHERE id=?",
            (data, mime, img_id),
        )
        converted += 1
        total_after += len(data)
        if converted % 25 == 0:
            conn.commit()
            print(f"  {converted}/{len(rows)} converted...")

    conn.commit()
    print(f"\nconverted={converted} skipped={skipped} failed={failed}")

    # Every row must still decode before we discard the free pages.
    print("verifying all rows decode...")
    from PIL import Image

    bad = 0
    for (img_id,) in conn.execute("SELECT id FROM mod_custom_images").fetchall():
        b64 = conn.execute(
            "SELECT image_data FROM mod_custom_images WHERE id=?", (img_id,)
        ).fetchone()[0]
        try:
            Image.open(io.BytesIO(base64.b64decode(b64))).verify()
        except Exception as exc:
            print(f"  id={img_id} UNREADABLE: {exc}")
            bad += 1
    if bad:
        raise SystemExit(f"{bad} rows unreadable — restore the backup at {archive}")
    print("all rows decode OK")

    # auto_vacuum is 0, so the file keeps its pages until VACUUM rewrites it.
    print("vacuuming (rewrites the file; needs free space equal to the old size)...")
    conn.execute("VACUUM")
    conn.close()

    size_after = db.stat().st_size
    print(f"\ncolumn: {_mb(col_before):.1f} MB -> {_mb(total_after):.1f} MB")
    print(f"file:   {_mb(size_before):.1f} MB -> {_mb(size_after):.1f} MB")
    print(f"reclaimed {_mb(size_before - size_after):.1f} MB")
    print(f"\nbackup retained at: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

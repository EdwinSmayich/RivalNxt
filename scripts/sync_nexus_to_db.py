import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

# Reload settings from disk to ensure we have the latest configuration
from core.config.settings import reload_settings
reload_settings()

from core.db import (
    get_connection,
    init_schema,
    replace_mod_changelogs,
    replace_mod_files,
    upsert_api_cache,
    upsert_mod_info,
)
from core.nexus.nexus_api import collect_all_for_mod, get_api_key, DEFAULT_GAME
from core.utils.nexus_metadata import (
    derive_changelogs_from_files,
    extract_description_text,
)
from field_prefs import load_prefs, filter_aggregate_payload


def iter_mod_ids_from_db(conn) -> Iterable[int]:
    cur = conn.execute(
        "SELECT DISTINCT mod_id FROM local_downloads WHERE mod_id IS NOT NULL ORDER BY mod_id;"
    )
    for (mid,) in cur.fetchall():
        yield int(mid)


# How long a mod's metadata is considered current. A rebuild triggered twice in
# an afternoon should not re-download 380 payloads that cannot have changed
# meaningfully; a genuinely stale install still refreshes.
DEFAULT_MAX_AGE_HOURS = 12

# Concurrent API fetches. Nexus rate-limits per hour, so this stays deliberately
# modest: it turns minutes of serial round-trips into seconds without looking
# like abuse from a single key.
DEFAULT_SYNC_WORKERS = 4


def _fresh_mod_ids(conn, mod_ids: List[int], max_age_hours: float) -> set:
    """Mod ids synced recently enough to skip.

    Uses last_synced_at — when this install last asked — rather than
    mods.updated_at, which records when the mod changed on Nexus and so cannot
    answer "do we need to ask again".
    """
    if max_age_hours <= 0 or not mod_ids:
        return set()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    placeholders = ",".join("?" * len(mod_ids))
    try:
        rows = conn.execute(
            f"SELECT mod_id FROM mods WHERE mod_id IN ({placeholders}) "
            "AND last_synced_at IS NOT NULL AND last_synced_at > ?",
            (*mod_ids, cutoff),
        ).fetchall()
    except Exception:
        # Column missing on an un-migrated database: sync everything rather than
        # silently skipping work.
        return set()
    return {int(r[0]) for r in rows}


def sync_mods(
    mod_ids: List[int],
    game: Optional[str] = None,
    rate_delay: float = 0.6,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    workers: int = DEFAULT_SYNC_WORKERS,
) -> None:
    if game is None:
        game = DEFAULT_GAME
    conn = get_connection()
    init_schema(conn)
    key = get_api_key()
    if not key:
        print("WARNING: Nexus API key not configured - skipping Nexus metadata sync.")
        print("To enable Nexus metadata sync, configure your API key in Settings.")
        return
    prefs = load_prefs()
    requested = list(dict.fromkeys(mod_ids))

    fresh = _fresh_mod_ids(conn, requested, max_age_hours)
    to_process = [m for m in requested if m not in fresh]
    if fresh:
        print(
            f"Skipping {len(fresh)} mod(s) synced within the last {max_age_hours:g}h; "
            "pass max_age_hours=0 to force."
        )
    if not to_process:
        print("All linked mods are already up to date.")
        return

    # Fetch in parallel, write serially. Each collect_all_for_mod is three
    # blocking HTTP round-trips and touches no database state, so the network
    # wait is the only thing being overlapped. The SQLite connection stays on
    # this thread.
    fetched: List[tuple] = []
    workers = max(1, min(int(workers), len(to_process)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(collect_all_for_mod, key, game, mod_id): mod_id
            for mod_id in to_process
        }
        for future in as_completed(futures):
            mod_id = futures[future]
            try:
                fetched.append((mod_id, future.result()))
            except Exception as exc:
                print(f"Failed to fetch mod {mod_id}: {exc}")

    synced_at = datetime.now(timezone.utc).isoformat()
    for mod_id, data in fetched:
        filtered = filter_aggregate_payload(data, prefs)
        # Merge description payload into mod_info so DB can store it
        mod_info_payload = dict(filtered.get("mod_info") or {})
        desc_text = extract_description_text(filtered.get("description"))
        if desc_text:
            mod_info_payload["description"] = desc_text
        upsert_api_cache(conn, mod_id, filtered)
        mod_info_status = int(data.get("mod_info_status", 0))
        files_status = int(data.get("files_status", 0))
        changelogs_status = int(data.get("changelogs_status", 0))
        upsert_mod_info(conn, game, mod_id, mod_info_status, mod_info_payload)
        replace_mod_files(conn, mod_id, filtered.get("files"))
        # If the API didn't provide changelogs, try to synthesize them from the
        # files payload (many mods embed brief changelog text per file).
        changelogs_payload = filtered.get("changelogs") or {}
        if not changelogs_payload or (isinstance(changelogs_payload, dict) and not changelogs_payload.get("changelogs")):
            changelogs_payload = derive_changelogs_from_files(filtered.get("files"))
        replace_mod_changelogs(conn, mod_id, changelogs_payload)

        # Stamped only after the payload is stored, so an interrupted run
        # re-fetches rather than believing it already has the data.
        if mod_info_status == 200:
            try:
                conn.execute(
                    "UPDATE mods SET last_synced_at = ? WHERE mod_id = ?", (synced_at, mod_id)
                )
                conn.commit()
            except Exception:
                pass

        print(
            f"Synced mod {mod_id}: info={mod_info_status} files={files_status} changelogs={changelogs_status}"
        )


def main():
    parser = argparse.ArgumentParser(description="Sync Nexus API data into SQLite")
    parser.add_argument("mod_ids", nargs="*", type=int, help="Specific mod IDs to sync")
    parser.add_argument("--game", default=DEFAULT_GAME, help="Nexus game slug")
    parser.add_argument("--from-file", help="Path to JSON aggregated payload")
    parser.add_argument("--rate-delay", type=float, default=0.6, help="Sleep seconds between requests")
    args = parser.parse_args()
    conn = get_connection()
    init_schema(conn)
    if args.from_file:
        p = json.load(open(args.from_file, "r", encoding="utf-8"))
        mid = int(p.get("mod_id"))
        to_process = [mid]
        payloads = {mid: p}
    else:
        payloads = {}
        if args.mod_ids:
            to_process = list(dict.fromkeys(args.mod_ids))
        else:
            to_process = list(iter_mod_ids_from_db(conn))
    prefs = load_prefs()
    for i, mod_id in enumerate(to_process, 1):
        if args.from_file:
            data = payloads[mod_id]
        else:
            key = get_api_key()
            if not key:
                raise SystemExit("Missing API key. Set NEXUS_API_KEY in .env or environment.")
            data = collect_all_for_mod(key, args.game, mod_id)
            if i < len(to_process):
                time.sleep(max(0.0, args.rate_delay))
        filtered = filter_aggregate_payload(data, prefs)
        # Merge description payload into mod_info so DB can store it
        mod_info_payload = dict(filtered.get("mod_info") or {})
        desc_text = extract_description_text(filtered.get("description"))
        if desc_text:
            mod_info_payload["description"] = desc_text
        upsert_api_cache(conn, mod_id, filtered)
        mod_info_status = int(data.get("mod_info_status", 0))
        files_status = int(data.get("files_status", 0))
        changelogs_status = int(data.get("changelogs_status", 0))
        upsert_mod_info(conn, args.game, mod_id, mod_info_status, mod_info_payload)
        replace_mod_files(conn, mod_id, filtered.get("files"))
        changelogs_payload = filtered.get("changelogs") or {}
        if not changelogs_payload or (isinstance(changelogs_payload, dict) and not changelogs_payload.get("changelogs")):
            changelogs_payload = derive_changelogs_from_files(filtered.get("files"))
        replace_mod_changelogs(conn, mod_id, changelogs_payload)
        print(
            f"Synced mod {mod_id}: info={mod_info_status} files={files_status} changelogs={changelogs_status}"
        )


if __name__ == "__main__":
    main()

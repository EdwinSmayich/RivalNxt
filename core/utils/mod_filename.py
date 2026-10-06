from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

__all__ = ["parse_mod_filename", "parse_mod_filename_to_row"]

# <anything>-<unix time>, with whatever a browser or this app adds to a second
# copy: " (1)", "-1", "_1".
_TIMESTAMPED = re.compile(r"^(?P<body>.+)-(?P<stamp>\d{9,11})(?:[\s\-_]+(?:\(\d+\)|\d+))?$")

# One piece of a version number: 1, 12, 0b, v2, rc1, beta. A number of four
# digits or more is deliberately not one -- that is what a mod id looks like,
# and it is where reading backwards has to stop.
_VERSION_PIECE = re.compile(
    r"^(?:v?\d{1,3}[a-z]{0,2}|(?:a|b|alpha|beta|rc|pre|dev|final|fix|hotfix)\d{0,2})$",
    re.IGNORECASE,
)
_ID_TOKEN = re.compile(r"^[0-9]{1,7}$")
# A version that is a date: 2025-01-15. The year would otherwise be read as a
# mod id, being four digits. Only zero-padded months count, so that an id in
# the 2000s followed by an ordinary "1-0" is not mistaken for one.
_YEAR = re.compile(r"^(?:19|20)[0-9]{2}$")
_MONTH = re.compile(r"^(?:0[1-9]|1[0-2])$")
_VERSION_TOKEN = re.compile(r"^[\w.]+$")


def _split_timestamped_name(base: str) -> Optional[Tuple[str, int, str]]:
    """``(name, mod id, version)`` from ``name-id-version-timestamp``, or None.

    The id is found from the right. Taking the first number in the name, as
    this used to, reads "the-ting-v1-1-7345-1.1-1774361896" as mod 1 and
    "...-vol-3-8567-1.0-..." as mod 3: any number in the *name* wins. Taking the
    last number instead mistakes the end of an ordinary "1-0" version for it.

    What is certain is the far end: the timestamp, and before it the version.

    * A version written with dots ("1.1", as this app writes them when it
      renames a download) is a single token, so the id is the one before it.
    * A version written with dashes ("1-0-2", as Nexus serves them) is a run of
      short pieces; the id is the number standing immediately before that run.
    * If nothing numeric stands before the run, the id was short enough to be
      taken for part of it -- an early mod, id below 1000 -- and it is the
      first number in the run, which is what the old rule would have said.
    """
    match = _TIMESTAMPED.match(base)
    if not match:
        return None
    tokens = match.group("body").split("-")
    if len(tokens) < 3:
        return None
    last = len(tokens) - 1

    id_index: Optional[int] = None
    if "." in tokens[last] and last - 1 >= 1 and _ID_TOKEN.match(tokens[last - 1]):
        id_index = last - 1
    else:
        start = last  # the token before the timestamp is always version
        while start - 1 >= 1:
            previous = tokens[start - 1]
            dated = _YEAR.match(previous) and _MONTH.match(tokens[start])
            if not (_VERSION_PIECE.match(previous) or dated):
                break
            start -= 1
        if start - 1 >= 1 and _ID_TOKEN.match(tokens[start - 1]):
            id_index = start - 1
        else:
            for index in range(start, last):
                if _ID_TOKEN.match(tokens[index]):
                    id_index = index
                    break
    if id_index is None or id_index < 1:
        return None

    version_tokens = tokens[id_index + 1:]
    if not version_tokens or not all(_VERSION_TOKEN.match(t) for t in version_tokens):
        return None
    # A download this app renamed twice carries the id twice:
    #   <name>-12406-1-0-2026-08-25t12-16z-<random>-12406-1.0-<timestamp>
    # The name ends where the id first appears, not where it appears last.
    name_end = tokens.index(tokens[id_index])
    if name_end < 1:
        name_end = id_index
    name_raw = "-".join(tokens[:name_end])
    if not name_raw.strip():
        return None
    return name_raw, int(tokens[id_index]), ".".join(version_tokens)


def parse_mod_filename(filename: str) -> Tuple[str, Optional[int], str]:
    """Extract name, mod_id, and version from a mod filename.
    
    Prioritizes the official Nexus Mods naming convention:
    <name>-<mod_id>-<version>-<timestamp>.<ext>

    Also handles the space-separated NMM/browser style:
    <name words> <mod_id> <version tokens> <timestamp> [optional extra]
    e.g. "Azure Shade Up 4985 1 0 1763999096 8"
    """
    if not filename:
        return "", None, ""
        
    p = Path(filename)
    base = p.stem
    
    # 1. Check for official Nexus naming convention (dash-separated)
    # Pattern: <Name>-<ModID>-<Version>-<Timestamp>[optional suffix]
    #
    # The key to parsing this correctly is anchoring on the TIMESTAMP, which is
    # always a 9-11 digit Unix epoch value (e.g. 1776061797).
    # We then parse BACKWARDS from the timestamp to find:
    #   - timestamp  : 9-11 digits at the end
    #   - version    : 1 or more digit segments (e.g. "1-1", "4-5")
    #   - mod_id     : 1-7 digits (Nexus mod IDs are currently 1-6 digits)
    #   - name       : everything before the mod_id
    #
    # Using a non-greedy name group (.+?) and anchoring the timestamp size
    # prevents the regex from greedily consuming numbers that are part of the mod_id.
    nexus_pattern = re.compile(
        r"^(.+?)"           # Name (non-greedy)
        r"-(\d{1,7})"       # -ModID (1-7 digits, currently Nexus IDs are 1-6 digits)
        r"-([\w][\w\.-]*\w|[\w])"  # -Version (alphanumeric led, alphanumeric, dots, and dashes)
        r"-(\d{9,11})"      # -Timestamp (9-11 digit Unix epoch)
        r"(?:[\s\-_]+(?:\(\d+\)|\d+))?"   # Optional browser duplicate suffix like " (1)", "-1", "_1"
        r"$"
    )
    split = _split_timestamped_name(base)
    if split is not None:
        name_raw, mod_id, version = split
        name = re.sub(r"\s+", " ", name_raw.replace("_", " ").strip())
        return name, mod_id, version

    # Anything the reading above could not make sense of gets the pattern that
    # was here before it.
    nexus_match = nexus_pattern.match(base)
    
    if nexus_match:
        name_raw = nexus_match.group(1)
        mod_id = int(nexus_match.group(2))
        version = nexus_match.group(3).replace("-", ".")
        # Clean up name: normalize underscores but preserve intentional dashes-as-spaces
        name = name_raw.replace("_", " ").strip()
        name = re.sub(r"\s+", " ", name)
        return name, mod_id, version

    # 1b. Space-separated Nexus convention (NMM / browser download-manager style).
    #     Format: <Name words> <ModID> <version tokens> <Timestamp> [optional extra number]
    #     Examples:
    #       "Azure Shade Up 4985 1 0 1763999096 8"
    #       "Thicc Scarlet Witch 5704 1 3 1774422798 1"
    #       "Chaos Radiance User Interface Overhaul 4804 4 5 1762687295 5"
    #
    # Strategy: anchor on the timestamp (9-11 digit epoch), then read backwards:
    #   - optional trailing extra number after timestamp
    #   - version segments (one or more space-separated digit groups before timestamp)
    #   - ModID (single 1-7 digit number just before version)
    #   - name = everything before the ModID
    #
    # We use a non-greedy version group so the ModID is correctly separated.
    nexus_space_pattern = re.compile(
        r"^(.+?)"                   # Name (non-greedy)
        r"\s+(\d{1,7})"             # space + ModID (1-7 digits)
        r"\s+([\w\.]+(?:\s+[\w\.]+)*?)"  # space + Version tokens (non-greedy, 1+ alphanumeric groups)
        r"\s+(\d{9,11})"            # space + Timestamp (9-11 digit epoch)
        r"(?:\s+\d+)?"              # optional trailing extra number (e.g. "8", "5", "1")
        r"$"
    )
    nexus_space_match = nexus_space_pattern.match(base)

    if nexus_space_match:
        name_raw = nexus_space_match.group(1)
        mod_id_candidate = int(nexus_space_match.group(2))
        version_raw = nexus_space_match.group(3)

        # Sanity check: the "name" part must contain at least one non-digit character
        # to avoid misidentifying a pure-numeric string as a name.
        if re.search(r"[^\d\s]", name_raw):
            version = version_raw.replace(" ", ".")
            name = name_raw.replace("_", " ").strip()
            name = re.sub(r"\s+", " ", name)
            return name, mod_id_candidate, version

    # 1c. Underscore convention with an ISO date instead of a Unix epoch:
    #     <Name>_<ModID>_<Version>_<ISO timestamp>_<random suffix>
    #     e.g. "BodyReshape_MagikSoullessSword_Addons_9902_1_2026-06-20T19-12Z_V1FxDq0Zh"
    #          "HeavyBush_10878_1.0_2026-07-16T17-03Z_oET5q7AMd"
    #
    # Both patterns above anchor on a 9-11 digit epoch, so neither matches this
    # shape and the id went unread even though it is right there in the name.
    # In one real library that was 12 downloads, eight of them "_Addons_" files
    # -- which is what made an add-on split away from its base mod on every
    # rebuild, since grouping and artwork are both keyed on the mod id.
    #
    # The version group must start with a digit, so a name that happens to
    # contain "_<digits>_" earlier backtracks to the real id rather than
    # stopping at the first number it sees.
    nexus_iso_pattern = re.compile(
        r"^(.+?)"                              # Name (non-greedy)
        r"_(\d{1,7})"                          # _ModID
        r"_(\d[\w.]*)"                         # _Version, digit-led
        r"_(\d{4}-\d{2}-\d{2}T[\d:\-]+Z?)"     # _ISO-8601 timestamp
        r"(?:_[\w-]+)?"                        # _optional random suffix
        r"$"
    )
    nexus_iso_match = nexus_iso_pattern.match(base)
    if nexus_iso_match:
        name_raw = nexus_iso_match.group(1)
        if re.search(r"[^\d_]", name_raw):
            name = re.sub(r"\s+", " ", name_raw.replace("_", " ").strip())
            return name, int(nexus_iso_match.group(2)), nexus_iso_match.group(3)

    # 2. Heuristic parsing for non-Nexus files
    # Strip Unreal Engine .pak suffixes like _9999999_P, _P, _p
    base = re.sub(r"_(?:\d+_)?(?:P|p)$", "", base)

    # Fallback: Search for version patterns like v1.2.3 or 1.2.3
    # We do this BEFORE the general token split to avoid taking a version-like number as a Mod ID
    version_match = re.search(r"(?:[vV]\s?|[-_ ])(\d+\.\d+(?:\.\d+)*)", base)
    if not version_match:
        version_match = re.search(r"(\d+\.\d+(?:\.\d+)*)", base)

    version = ""
    if version_match:
        version = version_match.group(1)

    # For non-official files, we are much stricter about what looks like a Mod ID.
    # We only take it if it's explicitly labeled or if it's a large number 
    # separated by a dash at the end of the name part.
    
    # Try to find an explicit Mod ID like "ModID_12345"
    explicit_match = re.search(r"ModID[_-]?(\d+)", base, re.I)
    if explicit_match:
        mod_id = int(explicit_match.group(1))
        name = base[:explicit_match.start()].replace("_", " ").replace("-", " ").strip("-_ ")
        name = re.sub(r"\s+", " ", name) or base
        return name, mod_id, version

    # If no official pattern and no explicit ID, we treat the whole thing as the name
    # unless it matches a very specific "Name-12345" where 12345 is at the end.
    # This avoids "Luna-Mirae-2099" being parsed as Mod #2099.
    
    final_name = base.replace("_", " ").replace("-", " ").strip()
    final_name = re.sub(r"\s+", " ", final_name)
    return final_name, None, version





def parse_mod_filename_to_row(filename: str) -> tuple[str, str, str]:
	"""Compatibility helper returning ``(name, mod_id_string, version)``."""
	name, mod_id_val, version = parse_mod_filename(filename)
	return name, str(mod_id_val) if mod_id_val is not None else "", version

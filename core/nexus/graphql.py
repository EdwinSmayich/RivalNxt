"""Nexus Mods GraphQL v2 client — mod browsing and search.

The v1 REST API this project already uses has no search endpoint at all. It can
fetch a mod you already know the id of, and list files for it, but there is no
way to ask "which Marvel Rivals mods match 'magik'". That is why browsing had to
happen on the website.

GraphQL v2 does support it, with filtering, sorting and offset pagination, and
the mods query answers without an API key. The key is still sent when available:
it is what associates the request with the user's account for rate limiting and
adult-content visibility.

This module only finds mods; it never downloads them. Nexus issues download
links through the API to Premium accounts only, so installing goes through the
mod page and the ``nxm://`` handoff the app already accepts — the same path a
Vortex user takes.

Deliberately NOT here: a mod's image gallery. Neither API exposes one. The Mod
type carries pictureUrl plus thumbnail variants, which are all renderings of the
same single image, and the root media() query filters by game and owner but has
no modId, so it cannot be narrowed to one mod. Anything claiming to fetch "all
images of a mod" would have to scrape the website.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

try:
    # Matches nexus_api.py: their certificate chain has caused failures before.
    SSL_CONTEXT = ssl._create_unverified_context()
except AttributeError:  # pragma: no cover - platform dependent
    SSL_CONTEXT = ssl.create_default_context()

GRAPHQL_URL = "https://api.nexusmods.com/v2/graphql"
from core.version import APP_NAME, APP_VERSION  # noqa: F401  (re-exported)

# Marvel Rivals. Numeric id rather than the domain name because ModsFilter
# exposes both and only gameId matched reliably in practice.
MARVEL_RIVALS_GAME_ID = "7106"

DEFAULT_COUNT = 30
MAX_COUNT = 50

# Field set kept small on purpose: this feeds a grid of cards, and every extra
# field is paid for on every row of every page.
_MOD_FIELDS = """
  modId
  name
  summary
  version
  author
  uploader { name memberId }
  adult
  downloads
  endorsements
  createdAt
  updatedAt
  pictureUrl
  thumbnailUrl
  modCategory { name }
  game { domainName }
"""

_SEARCH_QUERY = """
query BrowseMods($filter: ModsFilter, $sort: [ModsSort!], $count: Int, $offset: Int) {
  mods(filter: $filter, sort: $sort, count: $count, offset: $offset) {
    totalCount
    nodes {%s}
  }
}
""" % _MOD_FIELDS


class NexusGraphQLError(Exception):
    """Raised when the GraphQL endpoint cannot be reached or returns errors."""


# Exposed so the API layer can validate before building a query, and so the
# frontend and backend cannot disagree about what is sortable.
SORT_FIELDS = {
    "endorsements": "endorsements",
    "downloads": "downloads",
    "createdAt": "createdAt",
    "updatedAt": "updatedAt",
    "name": "name",
}


def _post(payload: Dict[str, Any], api_key: Optional[str] = None) -> Dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        "Application-Name": APP_NAME,
        "Application-Version": APP_VERSION,
    }
    if api_key:
        headers["apikey"] = api_key

    req = urllib.request.Request(
        GRAPHQL_URL, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise NexusGraphQLError(f"Nexus returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise NexusGraphQLError(f"Could not reach Nexus: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise NexusGraphQLError("Nexus returned a malformed response") from exc

    if body.get("errors"):
        first = body["errors"][0].get("message", "unknown error")
        raise NexusGraphQLError(f"Nexus rejected the query: {first}")
    return body.get("data") or {}


def build_filter(
    *,
    query: Optional[str] = None,
    category: Optional[str] = None,
    author: Optional[str] = None,
    include_adult: bool = True,
    game_id: str = MARVEL_RIVALS_GAME_ID,
) -> Dict[str, Any]:
    """Assemble a ModsFilter. Pure, so the shape can be asserted in tests."""
    filt: Dict[str, Any] = {"gameId": {"value": str(game_id), "op": "EQUALS"}}

    if query and query.strip():
        # `name`, not `nameStemmed`. Stemming looked like the smarter field but
        # measurably loses on real queries against this game:
        #
        #   query              nameStemmed   name
        #   "jiggle physics"             0     17
        #   "invisible woman"            2    316
        #   "magik"                    294    294
        #
        # It collapses on anything multi-word and never wins, so there is no
        # trade-off to balance here.
        filt["name"] = {"value": query.strip(), "op": "WILDCARD"}
    if category and category.strip():
        filt["categoryName"] = {"value": category.strip(), "op": "EQUALS"}
    if author and author.strip():
        filt["uploader"] = {"value": author.strip(), "op": "WILDCARD"}
    if not include_adult:
        # A real boolean: this filter refuses the string "false" that the other
        # ModsFilter fields all take.
        filt["adultContent"] = {"value": False, "op": "EQUALS"}

    return filt


def build_sort(sort_by: str, descending: bool = True) -> List[Dict[str, Any]]:
    field = SORT_FIELDS.get(sort_by, "endorsements")
    return [{field: {"direction": "DESC" if descending else "ASC"}}]


def search_mods(
    *,
    query: Optional[str] = None,
    category: Optional[str] = None,
    author: Optional[str] = None,
    sort_by: str = "endorsements",
    descending: bool = True,
    include_adult: bool = True,
    offset: int = 0,
    count: int = DEFAULT_COUNT,
    api_key: Optional[str] = None,
    game_id: str = MARVEL_RIVALS_GAME_ID,
) -> Tuple[List[Dict[str, Any]], int]:
    """Return ``(mods, total_count)`` for one page of results."""
    count = max(1, min(int(count), MAX_COUNT))
    offset = max(0, int(offset))

    data = _post(
        {
            "query": _SEARCH_QUERY,
            "variables": {
                "filter": build_filter(
                    query=query,
                    category=category,
                    author=author,
                    include_adult=include_adult,
                    game_id=game_id,
                ),
                "sort": build_sort(sort_by, descending),
                "count": count,
                "offset": offset,
            },
        },
        api_key=api_key,
    )

    mods = data.get("mods") or {}
    return list(mods.get("nodes") or []), int(mods.get("totalCount") or 0)


# Mod categories, as ModsFilter.categoryName actually accepts them.
#
# NOT from the categories(gameId:) query — that returns the *collection*
# taxonomy ("Essentials", "Themed", "Vanilla Plus"), which matches no mods at
# all: filtering by "Essentials" returns 0 while "Characters" returns 6302.
# Verified against the live API, counts as of writing:
#   Characters 6302 · Audio 1154 · User Interface 739 · Visuals 208
_MOD_CATEGORIES = [
    "Characters",
    "Audio",
    "User Interface",
    "Visuals",
    "Miscellaneous",
    "Gameplay",
    "Maps",
    "Skins",
]


def list_categories(
    *, api_key: Optional[str] = None, game_id: str = MARVEL_RIVALS_GAME_ID
) -> List[str]:
    """Category names offered in the browse filter.

    A fixed list rather than a query, for the reason documented above. The UI
    also renders whatever category a result reports, so a category missing here
    is still visible on the card — it just is not offered as a filter.
    """
    return list(_MOD_CATEGORIES)


def normalise_mod(node: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a GraphQL node into the shape the frontend renders.

    Done here rather than in the component so the nested GraphQL shape does not
    leak into the UI, and so a schema change has one place to be absorbed.
    """
    uploader = node.get("uploader") or {}
    category = node.get("modCategory") or {}
    game = node.get("game") or {}
    domain = game.get("domainName") or "marvelrivals"
    mod_id = node.get("modId")
    member_id = uploader.get("memberId")

    return {
        "modId": mod_id,
        "name": node.get("name") or "",
        "summary": node.get("summary") or "",
        "version": node.get("version") or "",
        "author": node.get("author") or uploader.get("name") or "",
        "uploaderProfileUrl": (
            f"https://www.nexusmods.com/users/{member_id}" if member_id else None
        ),
        "adult": bool(node.get("adult")),
        "downloads": int(node.get("downloads") or 0),
        "endorsements": int(node.get("endorsements") or 0),
        "createdAt": node.get("createdAt"),
        "updatedAt": node.get("updatedAt"),
        "pictureUrl": node.get("pictureUrl"),
        "thumbnailUrl": node.get("thumbnailUrl") or node.get("pictureUrl"),
        "category": category.get("name") or "",
        "modPageUrl": f"https://www.nexusmods.com/{domain}/mods/{mod_id}" if mod_id else None,
    }


__all__ = [
    "MARVEL_RIVALS_GAME_ID",
    "DEFAULT_COUNT",
    "MAX_COUNT",
    "SORT_FIELDS",
    "NexusGraphQLError",
    "build_filter",
    "build_sort",
    "search_mods",
    "list_categories",
    "normalise_mod",
]

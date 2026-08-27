"""Query building and response shaping for the Nexus browser.

The v1 REST API has no search endpoint, so browsing had to happen on the
website. GraphQL v2 does support it. These tests cover the pure parts — filter
and sort construction, and flattening a node for the UI — without touching the
network.
"""
from __future__ import annotations

import pytest

from core.nexus import graphql


class TestBuildFilter:
    def test_always_scopes_to_the_game(self):
        f = graphql.build_filter()
        assert f["gameId"] == {"value": graphql.MARVEL_RIVALS_GAME_ID, "op": "EQUALS"}

    def test_a_query_searches_the_name_field(self):
        f = graphql.build_filter(query="magik")
        assert f["name"] == {"value": "magik", "op": "WILDCARD"}

    def test_it_does_not_use_the_stemmed_field(self):
        """Measured against the live API, nameStemmed loses and never wins:

            query              nameStemmed   name
            "jiggle physics"             0     17
            "invisible woman"            2    316
            "magik"                    294    294

        It collapses on multi-word queries, which is most of what people type.
        """
        assert "nameStemmed" not in graphql.build_filter(query="jiggle physics")

    def test_blank_query_is_not_a_filter(self):
        assert "name" not in graphql.build_filter(query="   ")

    def test_query_is_trimmed(self):
        assert graphql.build_filter(query="  magik  ")["name"]["value"] == "magik"

    def test_multi_word_queries_are_kept_whole(self):
        # Splitting into separate filters would AND them into nothing.
        assert graphql.build_filter(query="jiggle physics")["name"]["value"] == "jiggle physics"

    def test_adult_is_unfiltered_by_default(self):
        assert "adultContent" not in graphql.build_filter()

    def test_excluding_adult_sends_a_real_boolean(self):
        # This filter rejects the string "false" that every other ModsFilter
        # field accepts, with a coercion error.
        value = graphql.build_filter(include_adult=False)["adultContent"]["value"]
        assert value is False
        assert not isinstance(value, str)

    def test_category_and_author_are_optional(self):
        f = graphql.build_filter(category="Characters", author="someone")
        assert f["categoryName"] == {"value": "Characters", "op": "EQUALS"}
        assert f["uploader"] == {"value": "someone", "op": "WILDCARD"}
        bare = graphql.build_filter()
        assert "categoryName" not in bare and "uploader" not in bare


class TestBuildSort:
    @pytest.mark.parametrize("field", sorted(graphql.SORT_FIELDS))
    def test_every_advertised_sort_field_builds(self, field):
        assert field in graphql.build_sort(field)[0]

    def test_unknown_field_falls_back_rather_than_erroring(self):
        # A stale client must not be able to 500 the endpoint.
        assert "endorsements" in graphql.build_sort("no_such_field")[0]

    def test_direction_is_controllable(self):
        assert graphql.build_sort("downloads", True)[0]["downloads"]["direction"] == "DESC"
        assert graphql.build_sort("downloads", False)[0]["downloads"]["direction"] == "ASC"


class TestNormaliseMod:
    def _node(self, **over):
        node = {
            "modId": 158,
            "name": "Magik Jiggle Physics",
            "summary": "does things",
            "version": "1.2",
            "author": "SomeAuthor",
            "uploader": {"name": "Uploader", "memberId": 4242},
            "adult": True,
            "downloads": 34817,
            "endorsements": 1022,
            "pictureUrl": "https://example/pic.png",
            "thumbnailUrl": "https://example/thumb.png",
            "modCategory": {"name": "Miscellaneous"},
            "game": {"domainName": "marvelrivals"},
        }
        node.update(over)
        return node

    def test_builds_a_mod_page_url(self):
        m = graphql.normalise_mod(self._node())
        assert m["modPageUrl"] == "https://www.nexusmods.com/marvelrivals/mods/158"

    def test_builds_an_uploader_profile_url_from_member_id(self):
        assert graphql.normalise_mod(self._node())["uploaderProfileUrl"].endswith("/users/4242")

    def test_missing_nested_objects_do_not_raise(self):
        m = graphql.normalise_mod(
            {"modId": 1, "name": "x", "uploader": None, "modCategory": None, "game": None}
        )
        assert m["category"] == ""
        assert m["author"] == ""
        assert m["uploaderProfileUrl"] is None
        assert m["modPageUrl"].endswith("/marvelrivals/mods/1")

    def test_author_falls_back_to_the_uploader_name(self):
        m = graphql.normalise_mod(self._node(author=None))
        assert m["author"] == "Uploader"

    def test_thumbnail_falls_back_to_the_full_picture(self):
        m = graphql.normalise_mod(self._node(thumbnailUrl=None))
        assert m["thumbnailUrl"] == "https://example/pic.png"

    def test_counts_are_numbers_even_when_absent(self):
        m = graphql.normalise_mod({"modId": 1, "name": "x"})
        assert m["downloads"] == 0 and m["endorsements"] == 0

    def test_adult_flag_is_a_bool(self):
        assert graphql.normalise_mod(self._node(adult=None))["adult"] is False


class TestCategories:
    """The browse filter must offer categories that actually match mods.

    `categories(gameId:)` returns the *collection* taxonomy — "Essentials",
    "Themed", "Vanilla Plus" — and filtering by those matches nothing:
    "Essentials" returns 0 mods while "Characters" returns 6302. Offering that
    list would have produced a filter that silently empties the page.
    """

    def test_offers_categories_that_mods_actually_use(self):
        cats = graphql.list_categories()
        assert "Characters" in cats
        assert "Audio" in cats

    def test_does_not_offer_the_collection_taxonomy(self):
        cats = {c.lower() for c in graphql.list_categories()}
        for wrong in ("essentials", "themed", "vanilla plus", "total overhaul"):
            assert wrong not in cats, f"{wrong!r} matches no mods but is offered as a filter"

    def test_returns_a_copy_so_callers_cannot_mutate_the_source(self):
        first = graphql.list_categories()
        first.append("Injected")
        assert "Injected" not in graphql.list_categories()

    def test_category_filter_is_built_as_an_exact_match(self):
        f = graphql.build_filter(category="Characters")
        assert f["categoryName"] == {"value": "Characters", "op": "EQUALS"}

"""A number in a mod's *name* must not be taken for its Nexus id.

``name-id-version-timestamp`` was read from the left: the first number after a
dash was the id. So

    the-ting-v1-1-6853-1.1-1771860521.zip

was mod **1**, with version "6853.1.1". In one library four downloads were
attached to mods 1, 3 and 9999999 that way -- three unrelated, long-removed
mods and one that does not exist -- which is where their names, pictures and
update checks came from.

Reading from the right has its own trap ("...-6853-1-0-<ts>" is not mod 1), so
the id is located from the two things that are certain: the timestamp at the
end, and the version in front of it.

Measured on that library's 283 file names: 260 parse exactly as before, 4 get
the right id, and 19 keep their id and name but lose a garbage version.
"""
from __future__ import annotations

import pytest

from core.utils.mod_filename import parse_mod_filename


def parsed_id(filename: str):
    return parse_mod_filename(filename)[1]


class TestNumbersInTheName:
    @pytest.mark.parametrize(
        "filename,mod_id,version,name",
        [
            # The four shapes that were wrong, with the names changed.
            ("the-ting-v1-1-6853-1.1-1771860521.zip", 6853, "1.1", "the-ting-v1-1"),
            ("maskless-malice-v1-1-7345-1.1-1774361896.zip", 7345, "1.1", "maskless-malice-v1-1"),
            ("makeup-file-guardians-vol-3-8567-1.0-1778344834.zip", 8567, "1.0", "makeup-file-guardians-vol-3"),
            ("theting-9999999-p-12746-1-1788950166.rar", 12746, "1", "theting-9999999-p"),
        ],
    )
    def test_the_real_id_is_found(self, filename, mod_id, version, name):
        assert parse_mod_filename(filename) == (name, mod_id, version)

    @pytest.mark.parametrize(
        "filename,mod_id",
        [
            # Version with dashes, as Nexus serves it, and a number in the name.
            ("the-ting-v1-1-6853-1-1-1771860521.zip", 6853),
            ("makeup-file-vol-3-8567-1-0-1778344834.zip", 8567),
            ("skin-pack-12-4985-1-0-1763999096.zip", 4985),
            ("luna-snow-2099-6303-1-0-1759000000.zip", 6303),
            ("theting-9999999-p-12746-1-0-1788950166.rar", 12746),
        ],
    )
    def test_with_a_dashed_version_too(self, filename, mod_id):
        assert parsed_id(filename) == mod_id


class TestWhatAlreadyWorkedStillDoes:
    @pytest.mark.parametrize(
        "filename,mod_id,version",
        [
            ("the-ting-6853-1-0-1771860521.zip", 6853, "1.0"),
            ("the-ting-6853-1-1771860521.zip", 6853, "1"),
            ("the-ting-6853-1-0-2-1771860521.zip", 6853, "1.0.2"),
            ("the-ting-6853-1.0.2-1771860521.zip", 6853, "1.0.2"),
            ("the-ting-6853-v2-1771860521.zip", 6853, "v2"),
            ("the-ting-6853-1-0b-1771860521.zip", 6853, "1.0b"),
            ("the-ting-6853-1-0-beta-1771860521.zip", 6853, "1.0.beta"),
            ("the-ting-6853-beta-1-1771860521.zip", 6853, "beta.1"),
            ("The Ting-6853-1-0-1771860521.zip", 6853, "1.0"),
            ("The_Ting-6853-1-0-1771860521.zip", 6853, "1.0"),
        ],
    )
    def test_plain_names(self, filename, mod_id, version):
        _name, got_id, got_version = parse_mod_filename(filename)
        assert (got_id, got_version) == (mod_id, version)

    @pytest.mark.parametrize(
        "filename",
        [
            "the-ting-6853-1-0-1771860521 (1).zip",
            "the-ting-6853-1-0-1771860521-1.zip",
            "the-ting-6853-1-0-1771860521_2.zip",
        ],
    )
    def test_a_second_copy_of_the_same_download(self, filename):
        assert parse_mod_filename(filename)[:2] == ("the-ting", 6853)

    def test_an_early_mod_with_a_short_id(self):
        """Ids below 1000 look like a piece of the version; nothing stands before them."""
        assert parse_mod_filename("the-ting-812-1-0-1736000000.zip") == ("the-ting", 812, "1.0")
        assert parse_mod_filename("the-ting-5-1-0-1736000000.zip") == ("the-ting", 5, "1.0")
        assert parse_mod_filename("the-ting-42-2-1736000000.zip") == ("the-ting", 42, "2")

    def test_underscores_in_the_name_become_spaces(self):
        assert parse_mod_filename("The_Ting_Remesh-6853-1-0-1771860521.zip")[0] == "The Ting Remesh"

    def test_a_dated_version_after_a_dotted_one_is_not_confused(self):
        assert parse_mod_filename("the-ting-6853-2025.01.15-1771860521.zip") == ("the-ting", 6853, "2025.01.15")


class TestADownloadRenamedTwice:
    """This app's own renaming, applied to a name that already carried the id."""

    NAME = "the-ting-12406-1-0-2026-08-25t12-16z-qb2jneyuj-12406-1.0-1787660185.zip"

    def test_the_id_is_unchanged(self):
        assert parsed_id(self.NAME) == 12406

    def test_the_version_is_the_version(self):
        """Was "1.0.2026.08.25t12.16z.qb2jneyuj.12406.1.0"."""
        assert parse_mod_filename(self.NAME)[2] == "1.0"

    def test_the_name_stops_at_the_first_appearance_of_the_id(self):
        assert parse_mod_filename(self.NAME)[0] == "the-ting"


class TestNamesThatAreNotThisShape:
    @pytest.mark.parametrize(
        "filename",
        [
            "TheTing_9999999_P.pak",
            "the-ting.zip",
            "the-ting-1771860521.zip",
            "",
        ],
    )
    def test_no_id_is_invented(self, filename):
        assert parsed_id(filename) is None

    def test_a_year_in_a_plain_name_is_still_not_an_id(self):
        assert parsed_id("Luna-Mirae-2099.zip") is None

    def test_the_other_shapes_are_untouched(self):
        assert parsed_id("Azure Shade Up 4985 1 0 1763999096 8.zip") == 4985
        assert parsed_id("TheTing_10878_1.0_2026-07-16T17-03Z_oET5q7AMd.zip") == 10878

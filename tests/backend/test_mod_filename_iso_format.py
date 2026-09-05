"""Nexus also writes filenames with an ISO date instead of a Unix epoch.

Both existing patterns in parse_mod_filename anchor on a 9-11 digit epoch at
the end of the name, so neither matches

    BodyReshape_MagikSoullessSword_Addons_9902_1_2026-06-20T19-12Z_V1FxDq0Zh

and the mod id went unread even though it is sitting in the middle of the
name. Measured on one library that was 12 of 209 downloads, eight of them
"_Addons_" files -- which is why an add-on kept detaching from its base mod:
grouping and artwork are both keyed on the mod id.
"""
from __future__ import annotations

import pytest

from core.utils.mod_filename import parse_mod_filename


# (filename, expected mod id, expected version) -- all real names.
ISO_NAMES = [
    ("BodyReshape_MagikSoullessSword_Addons_9902_1_2026-06-20T19-12Z_V1FxDq0Zh.rar", 9902, "1"),
    ("BodyReshape_PhoenixWhiteCrown_Addons_10346_1_2026-07-01T21-21Z_AZYq2mI.rar", 10346, "1"),
    ("BodyReshape_WhiteFoxCoastalKumiho_Addons_10498_1_2026-07-05T01-45Z_Qk3.rar", 10498, "1"),
    ("BodyReshape_MantisAkkabanAcolyte_Addons_11719_1_2026-08-05T07-23Z_a9c.rar", 11719, "1"),
    ("BodyReshape_JubileeMidnightMutant_Base_11019_1_2026-07-17T20-04Z_e3jCYfIEI.rar", 11019, "1"),
    ("HeavyBush_10878_1.0_2026-07-16T17-03Z_oET5q7AMd.zip", 10878, "1.0"),
]


@pytest.mark.parametrize("filename,mod_id,version", ISO_NAMES)
def test_the_id_is_read_from_an_iso_dated_name(filename, mod_id, version):
    _name, parsed_id, parsed_version = parse_mod_filename(filename)
    assert parsed_id == mod_id
    assert parsed_version == version


def test_the_name_keeps_everything_before_the_id():
    name, _id, _v = parse_mod_filename(
        "BodyReshape_MagikSoullessSword_Addons_9902_1_2026-06-20T19-12Z_V1FxDq0Zh.rar"
    )
    assert name == "BodyReshape MagikSoullessSword Addons"


def test_a_number_earlier_in_the_name_is_not_mistaken_for_the_id():
    """The version group must start with a digit, so the match backtracks."""
    _name, parsed_id, _v = parse_mod_filename(
        "BodyReshape_Sue_2_Piece_11276_1_2026-07-20T10-00Z_abc.rar"
    )
    assert parsed_id == 11276


def test_the_suffix_is_optional():
    _name, parsed_id, _v = parse_mod_filename("Something_4321_2.1_2026-01-02T03-04Z.zip")
    assert parsed_id == 4321


class TestTheOlderShapesStillParse:
    """197 of 215 downloads in that library use the dash form; none may regress."""

    @pytest.mark.parametrize(
        "filename,mod_id",
        [
            ("Maskless Malice (Remesh)-2811-1-1-1746649625.zip", 2811),
            ("BodyReshape_DaggerDaringDuo_Alt_Free-7601-1-0-1775061234.rar", 7601),
            ("bodyreshape-feliciacoastalcat-addons-12245-1-0-1780000000.rar", 12245),
            ("Bikini Black Widow-3443-1-0-1750105916.zip", 3443),
        ],
    )
    def test_dash_separated_names(self, filename, mod_id):
        _name, parsed_id, _v = parse_mod_filename(filename)
        assert parsed_id == mod_id

    def test_space_separated_names(self):
        _name, parsed_id, _v = parse_mod_filename("Azure Shade Up 4985 1 0 1763999096 8.zip")
        assert parsed_id == 4985

    def test_a_name_with_no_id_still_yields_none(self):
        _name, parsed_id, _v = parse_mod_filename("Elsa_Cammy (support+content).zip")
        assert parsed_id is None

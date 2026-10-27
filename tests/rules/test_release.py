"""A1 (item 18, P1) — ``parse_version`` e ``parse_tag`` aceitam só ``X.Y.Z`` / ``vX.Y.Z`` estritos; ``Version`` ordena por número."""

import pytest

from empiremuse.rules.release import Version, parse_tag, parse_version

VALIDAS = [
    ("0.0.0", Version(0, 0, 0)),
    ("2.1.0", Version(2, 1, 0)),
    ("10.20.30", Version(10, 20, 30)),
    ("9999.9999.9999", Version(9999, 9999, 9999)),
]
INVALIDAS = [
    "",
    "2.1",
    "2.1.0.1",
    "01.2.3",
    "1.02.3",
    "1.2.03",
    "-1.2.3",
    "1.2.3-rc.1",
    "1.2.3+build.5",
    "1.2.3rc1",
    " 1.2.3",
    "1.2.3 ",
    "1.2.3\n",
    "1. 2.3",
    "10000.0.0",
    "1.10000.0",
    "1.0.10000",
    "a.b.c",
    "v1.2.3",
]


@pytest.mark.parametrize(("texto", "esperada"), VALIDAS)
def test_parse_version_accepts_strict_x_y_z(texto, esperada):
    assert parse_version(texto) == esperada


@pytest.mark.parametrize("texto", INVALIDAS)
def test_parse_version_rejects_anything_else(texto):
    assert parse_version(texto) is None


@pytest.mark.parametrize(("texto", "esperada"), VALIDAS)
def test_parse_tag_requires_the_v_prefix(texto, esperada):
    assert parse_tag(f"v{texto}") == esperada
    assert parse_tag(texto) is None


@pytest.mark.parametrize("texto", [f"v{t}" for t in INVALIDAS[:-1]] + ["V2.1.0", "vv2.1.0", "v", "v v2.1.0"])
def test_parse_tag_applies_the_same_rules_after_the_prefix(texto):
    assert parse_tag(texto) is None


def test_version_prints_as_x_y_z():
    assert str(Version(2, 1, 0)) == "2.1.0"


def test_versions_compare_numerically_not_as_text():
    assert Version(2, 10, 0) > Version(2, 9, 9) > Version(2, 9, 8) > Version(1, 99, 99)
    assert parse_version("2.10.0") > parse_version("2.9.0")
    assert Version(2, 1, 0) == parse_version("2.1.0")

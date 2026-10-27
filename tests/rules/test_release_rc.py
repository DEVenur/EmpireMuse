"""A29 (D13) — só a versão ATUAL da imagem pode ser ``X.Y.Z-rc.N``: ``parse_current_version``, a ordem e o que continua estrito.

``X.Y.Z-rc.N < X.Y.Z`` e rc ordenado por N. Alvos (``parse_version``, ``parse_tag``, ``parse_update_target``, tags do ``ls-remote``)
continuam só estáveis (A1, A9, A23 intactos). Funções puras, sem relógio nem rede.
"""

import pytest

from empiremuse.rules.release import (
    Version,
    changelog_sections,
    parse_current_version,
    parse_ls_remote_annotated,
    parse_tag,
    parse_update_target,
    parse_version,
    pick_target,
)

DIGEST = "sha256:" + "ab" * 32

ACEITAS = ["2.1.0", "2.1.0-rc.2", "2.1.0-rc.10", "2.1.0-rc.0", "2.1.0-rc.9999", "0.0.0-rc.1", "9999.9999.9999-rc.1"]
REJEITADAS = [
    "",
    "2.1.0-rc.02",
    "2.1.0-RC.2",
    "2.1.0-Rc.2",
    "2.1.0-rc2",
    "2.1.0-rc.",
    "2.1.0-rc",
    "2.1.0-",
    "2.1.0rc.2",
    "2.1.0-beta.1",
    "2.1.0-alpha",
    "2.1.0-rc.2+b",
    "2.1.0+b",
    "2.1.0-rc.10000",
    "2.1.0-rc.-1",
    "2.1.0-rc.2-rc.3",
    "2.1.0-rc.2.1",
    "2.1.0-rc.2\n",
    "2.1.0\n",
    " 2.1.0-rc.2",
    "2.1.0-rc.2 ",
    "2.1.0-rc. 2",
    "02.1.0-rc.2",
    "2.1-rc.2",
    "v2.1.0-rc.2",
    "10000.0.0-rc.1",
    "2.1.0-rc.٢",  # dígito árabe-índico: o ``[0-9]`` vale de propósito
]
ORDEM = [
    "2.0.9",
    "2.1.0-rc.0",
    "2.1.0-rc.1",
    "2.1.0-rc.2",
    "2.1.0-rc.10",
    "2.1.0-rc.9999",
    "2.1.0",
    "2.1.1",
    "2.1.1-rc.1",
]


def atual(texto: str) -> Version:
    versao = parse_current_version(texto)
    assert versao is not None
    return versao


@pytest.mark.parametrize("texto", ACEITAS)
def test_parse_current_version_accepts_stable_and_lowercase_rc_with_a_component_rule_number(texto):
    assert parse_current_version(texto) is not None


@pytest.mark.parametrize("texto", REJEITADAS)
def test_parse_current_version_rejects_anything_else(texto):
    assert parse_current_version(texto) is None


@pytest.mark.parametrize("texto", ACEITAS)
def test_str_round_trips_and_never_shows_the_internal_sentinel(texto):
    assert str(atual(texto)) == texto
    assert parse_current_version(str(atual(texto))) == atual(texto)
    assert "10000" not in str(atual("2.1.0")) and "rc" not in str(atual("2.1.0"))


def test_the_ordering_is_rc_by_number_below_the_stable_below_the_next_version():
    ordenadas = [atual(texto) for texto in ORDEM[:7] + ["2.1.1"]]
    assert ordenadas == sorted(ordenadas, reverse=True)[::-1]
    assert sorted(reversed(ordenadas)) == ordenadas
    assert atual("2.0.9") < atual("2.1.0-rc.1") < atual("2.1.0-rc.2") < atual("2.1.0-rc.10") < atual("2.1.0")
    assert atual("2.1.0") < atual("2.1.1") < Version(2, 2, 0)
    assert atual("2.1.0-rc.9999") < atual("2.1.0")
    assert atual("2.1.1-rc.1") > atual("2.1.0")  # a rc da próxima patch já é maior que a estável anterior


def test_a_stable_current_version_is_the_same_value_as_the_strict_one():
    assert Version(2, 1, 0) == parse_version("2.1.0") == parse_current_version("2.1.0")
    assert hash(Version(2, 1, 0)) == hash(parse_current_version("2.1.0"))
    assert {Version(2, 1, 0): "x"}[parse_current_version("2.1.0")] == "x"


def test_an_rc_is_not_equal_to_its_stable_nor_to_another_rc():
    assert atual("2.1.0-rc.2") != Version(2, 1, 0)
    assert atual("2.1.0-rc.2") != atual("2.1.0-rc.3")
    assert atual("2.1.0-rc.2") == atual("2.1.0-rc.2")


def test_is_prerelease_tells_rc_from_stable():
    assert atual("2.1.0-rc.2").is_prerelease is True
    assert atual("2.1.0-rc.0").is_prerelease is True
    assert atual("2.1.0").is_prerelease is False
    assert Version(2, 1, 0).is_prerelease is False
    assert parse_version("2.1.0").is_prerelease is False


# ============================================================================ o que continua estrito (A1, A9, A23)

RCS = ["2.1.0-rc.1", "2.1.0-rc.2", "2.1.0-rc.10"]


@pytest.mark.parametrize("texto", RCS)
def test_parse_version_and_parse_tag_still_reject_rc(texto):
    assert parse_version(texto) is None
    assert parse_tag(f"v{texto}") is None
    assert parse_tag(texto) is None


@pytest.mark.parametrize("texto", RCS)
def test_parse_update_target_still_rejects_an_rc_target(texto):
    assert parse_update_target(f"{texto}@{DIGEST}") is None
    assert parse_update_target(f"2.1.0@{DIGEST}") == (Version(2, 1, 0), DIGEST)


def test_an_annotated_rc_tag_is_still_ignored_by_ls_remote():
    sha_tag, sha_commit = "a" * 40, "b" * 40
    saida = (
        f"{sha_tag}\trefs/tags/v2.1.0-rc.2\n{sha_commit}\trefs/tags/v2.1.0-rc.2^{{}}\n"
        f"{'c' * 40}\trefs/tags/v2.1.0\n{'d' * 40}\trefs/tags/v2.1.0^{{}}\n"
    )

    assert parse_ls_remote_annotated(saida) == {Version(2, 1, 0): "c" * 40}


# ============================================================================ pick_target e changelog com atual rc


def test_pick_target_from_an_rc_chooses_the_stable_of_the_same_triple():
    assert pick_target(atual("2.1.0-rc.2"), {Version(2, 0, 2), Version(2, 1, 0)}) == Version(2, 1, 0)


def test_pick_target_from_an_rc_chooses_the_greatest_stable():
    assert pick_target(atual("2.1.0-rc.2"), {Version(2, 0, 2), Version(2, 1, 0), Version(2, 1, 1)}) == Version(2, 1, 1)


def test_pick_target_from_an_rc_with_only_older_stables_is_none():
    assert pick_target(atual("2.1.0-rc.2"), {Version(2, 0, 2)}) is None
    assert pick_target(atual("2.1.0-rc.2"), set()) is None


CHANGELOG = """# Changelog

## [Unreleased]
- ainda não lançado

## [2.1.1] - 2026-11-01
- D: correção

## [2.1.0] - 2026-10-30
- C: a estável

## [2.1.0-rc.3] - 2026-10-29
- R3: seção rc que não pode aparecer

## [2.1.0-rc.2] - 2026-10-28
- R2: seção rc da versão atual

## [2.0.0] - 2026-09-01
- Z: antiga
"""


def test_changelog_from_an_rc_to_its_stable_has_only_the_stable_section():
    texto = changelog_sections(CHANGELOG, atual("2.1.0-rc.2"), Version(2, 1, 0), 3500)

    assert "[2.1.0]" in texto and "C: a estável" in texto
    assert "R2" not in texto and "R3" not in texto and "rc" not in texto
    assert "D: correção" not in texto and "Z: antiga" not in texto


def test_changelog_from_an_rc_to_the_next_patch_has_both_stable_sections_newest_first():
    texto = changelog_sections(CHANGELOG, atual("2.1.0-rc.2"), Version(2, 1, 1), 3500)

    assert texto.index("D: correção") < texto.index("C: a estável")
    assert "R2" not in texto and "R3" not in texto


def test_changelog_from_a_stable_never_shows_rc_sections():
    texto = changelog_sections(CHANGELOG, Version(2, 0, 0), Version(2, 1, 1), 3500)

    assert "rc" not in texto and "C: a estável" in texto and "D: correção" in texto

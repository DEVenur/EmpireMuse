"""A1 (item 18, P1) — ``parse_version`` e ``parse_tag`` aceitam só ``X.Y.Z`` / ``vX.Y.Z`` estritos; ``Version`` ordena por número.

A9-A11 e ``parse_update_target`` (P2): as regras puras de escolha da versão e do changelog.
"""

import pytest

from empiremuse.rules.release import (
    Version,
    changelog_sections,
    parse_ls_remote_annotated,
    parse_tag,
    parse_update_target,
    parse_version,
    pick_target,
)

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


# ============================================================================ A9 — parse_ls_remote_annotated

SHA_TAG_A = "a" * 40
SHA_COMMIT_A = "b" * 40
SHA_TAG_B = "c" * 40
SHA_COMMIT_B = "d" * 40
SHA_LEVE = "e" * 40


def ls_remote(*linhas: str) -> str:
    return "\n".join(linhas) + "\n"


def test_only_annotated_strict_tags_are_returned_with_the_tag_object_sha():
    saida = ls_remote(
        f"{SHA_TAG_A}\trefs/tags/v2.0.0",
        f"{SHA_COMMIT_A}\trefs/tags/v2.0.0^{{}}",
        f"{SHA_TAG_B}\trefs/tags/v2.1.0",
        f"{SHA_COMMIT_B}\trefs/tags/v2.1.0^{{}}",
    )

    assert parse_ls_remote_annotated(saida) == {Version(2, 0, 0): SHA_TAG_A, Version(2, 1, 0): SHA_TAG_B}


def test_lightweight_tags_have_no_peeled_line_and_are_ignored():
    saida = ls_remote(
        f"{SHA_LEVE}\trefs/tags/v2.5.0", f"{SHA_TAG_A}\trefs/tags/v2.0.0", f"{SHA_COMMIT_A}\trefs/tags/v2.0.0^{{}}"
    )

    assert parse_ls_remote_annotated(saida) == {Version(2, 0, 0): SHA_TAG_A}


@pytest.mark.parametrize(
    "nome",
    [
        "v2.1.0-rc.1",
        "v2.1.0+build.5",
        "2.1.0",
        "v2.1",
        "v02.1.0",
        "v2.1.0.1",
        "vnext",
        "v10000.0.0",
        "release-2.1.0",
        "v2.1.0 ",
    ],
)
def test_annotated_tags_with_a_non_strict_name_are_ignored(nome):
    saida = ls_remote(f"{SHA_TAG_B}\trefs/tags/{nome}", f"{SHA_COMMIT_B}\trefs/tags/{nome}^{{}}")

    assert parse_ls_remote_annotated(saida) == {}


def test_branches_garbage_and_empty_output_yield_nothing():
    saida = ls_remote(f"{SHA_COMMIT_A}\trefs/heads/main", f"{SHA_COMMIT_A}\tHEAD", "isto nao e uma linha", "")

    assert parse_ls_remote_annotated(saida) == {}
    assert parse_ls_remote_annotated("") == {}


# ============================================================================ A10 — pick_target


@pytest.mark.parametrize(
    ("atual", "candidatas", "esperada"),
    [
        ((2, 0, 0), [(2, 0, 0), (2, 1, 0), (2, 0, 5)], (2, 1, 0)),
        ((2, 0, 0), [(2, 1, 0), (2, 10, 0), (2, 9, 9)], (2, 10, 0)),
        ((2, 1, 0), [(2, 1, 0)], None),
        ((2, 1, 0), [(2, 0, 9), (1, 99, 99)], None),
        ((2, 1, 0), [], None),
        ((1, 9, 9), [(2, 0, 0)], (2, 0, 0)),
    ],
    ids=["a-maior", "numerica-nao-textual", "igual", "so-menores", "vazio", "major-novo"],
)
def test_pick_target_is_the_greatest_strictly_greater_version(atual, candidatas, esperada):
    escolhida = pick_target(Version(*atual), [Version(*c) for c in candidatas])

    assert escolhida == (Version(*esperada) if esperada else None)


def test_pick_target_accepts_any_iterable():
    assert pick_target(Version(1, 0, 0), iter([Version(1, 0, 1)])) == Version(1, 0, 1)


# ============================================================================ A11 — changelog_sections

CHANGELOG = """# Changelog

## [Unreleased]
- ainda não lançado

## [2.2.0] - 2026-11-01
- C: a mais nova

## [2.1.1] - 2026-10-30
- B: correção

## [2.1.0] - 2026-10-28
- A: a versão atual

## [2.0.0] - 2026-09-01
- Z: antiga
"""


def test_sections_between_current_exclusive_and_target_inclusive_newest_first():
    texto = changelog_sections(CHANGELOG, Version(2, 1, 0), Version(2, 2, 0), 3500)

    assert "2.2.0" in texto and "2.1.1" in texto
    assert texto.index("2.2.0") < texto.index("2.1.1")
    assert "C: a mais nova" in texto and "B: correção" in texto
    assert "2.1.0" not in texto and "A: a versão atual" not in texto and "Z: antiga" not in texto
    assert "Unreleased" not in texto and "ainda não lançado" not in texto


def test_the_target_itself_is_included_and_later_versions_are_not():
    texto = changelog_sections(CHANGELOG, Version(2, 0, 0), Version(2, 1, 1), 3500)

    assert "B: correção" in texto and "A: a versão atual" in texto
    assert "C: a mais nova" not in texto


def test_the_order_does_not_depend_on_the_order_in_the_file():
    embaralhado = "## [2.1.1]\n- B\n\n## [2.2.0]\n- C\n\n## [2.1.0]\n- A\n"

    texto = changelog_sections(embaralhado, Version(2, 1, 0), Version(2, 2, 0), 3500)

    assert texto.index("- C") < texto.index("- B") and "- A" not in texto


def test_an_oversized_result_is_cut_and_ends_with_an_ellipsis():
    longo = "## [2.1.1]\n" + "- item\n" * 1000

    texto = changelog_sections(longo, Version(2, 1, 0), Version(2, 1, 1), 200)

    assert texto.endswith("\u2026") and len(texto) <= 200


def test_a_result_that_fits_is_not_cut():
    texto = changelog_sections(CHANGELOG, Version(2, 1, 0), Version(2, 1, 1), 3500)

    assert not texto.endswith("\u2026") and "B: correção" in texto


@pytest.mark.parametrize(
    ("atual", "alvo"),
    [((2, 2, 0), (2, 2, 0)), ((3, 0, 0), (3, 1, 0)), ((2, 1, 0), (2, 1, 0))],
    ids=["sem-intervalo", "versoes-sem-secao", "atual-igual-alvo"],
)
def test_without_any_section_the_result_is_empty(atual, alvo):
    assert changelog_sections(CHANGELOG, Version(*atual), Version(*alvo), 3500) == ""


def test_text_without_sections_is_empty():
    assert changelog_sections("", Version(1, 0, 0), Version(2, 0, 0), 3500) == ""
    assert changelog_sections("nada de seções aqui", Version(1, 0, 0), Version(2, 0, 0), 3500) == ""


# ============================================================================ parse_update_target

DIGEST = "sha256:" + "ab" * 32


def test_parse_update_target_splits_the_version_and_the_digest():
    assert parse_update_target(f"2.1.1@{DIGEST}") == (Version(2, 1, 1), DIGEST)


@pytest.mark.parametrize(
    "texto",
    [
        "",
        "2.1.1",
        "2.1.1@",
        f"v2.1.1@{DIGEST}",
        f"02.1.1@{DIGEST}",
        "2.1.1@sha256:abc",
        f"2.1.1@sha256:{'AB' * 32}",
        f"2.1.1@sha512:{'ab' * 32}",
        f"2.1.1@{DIGEST}\n",
        f"2.1.1@{DIGEST} ",
        f"2.1.1@{DIGEST}@{DIGEST}",
        f" 2.1.1@{DIGEST}",
        f"2.1.1-rc.1@{DIGEST}",
    ],
)
def test_parse_update_target_rejects_anything_not_strict(texto):
    assert parse_update_target(texto) is None

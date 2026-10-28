"""Teste do dono em produção 2.1.1, parte E1 — ``changelog_section``: só o bloco da versão pedida, cortado em fim de linha."""

import pytest

from empiremuse.rules import release
from empiremuse.rules.release import Version

pytestmark = pytest.mark.critical

CHANGELOG = """# Changelog

## [Unreleased]
- ainda não lançado

## [2.1.1] - 2026-10-28
### Corrigido
- Primeiro item da 2.1.1
- Segundo item da 2.1.1 com um texto mais comprido para o corte cair no meio dele
- Terceiro item da 2.1.1

## [2.1.0] - 2026-10-20
### Adicionado
- Item da 2.1.0

[2.1.1]: https://exemplo.invalid/compare/v2.1.0...v2.1.1
[2.1.0]: https://exemplo.invalid/compare/v2.0.0...v2.1.0
"""

ELLIPSIS = "…"
V211, V210, V300 = Version(2, 1, 1), Version(2, 1, 0), Version(3, 0, 0)
LINHAS_DA_211 = [
    "## [2.1.1] - 2026-10-28",
    "### Corrigido",
    "- Primeiro item da 2.1.1",
    "- Segundo item da 2.1.1 com um texto mais comprido para o corte cair no meio dele",
    "- Terceiro item da 2.1.1",
]


class TestSoAVersaoPedida:
    def test_it_returns_only_the_block_of_the_asked_version(self) -> None:
        texto = release.changelog_section(CHANGELOG, V211, 3500)

        assert texto == "\n".join(LINHAS_DA_211)

    def test_the_neighbour_blocks_the_unreleased_and_the_link_references_stay_out(self) -> None:
        texto = release.changelog_section(CHANGELOG, V211, 3500)

        assert "2.1.0" not in texto.replace("2.1.1", "") and "Item da 2.1.0" not in texto
        assert "ainda não lançado" not in texto and "exemplo.invalid" not in texto

    def test_the_previous_version_gives_its_own_block(self) -> None:
        texto = release.changelog_section(CHANGELOG, V210, 3500)

        assert "Item da 2.1.0" in texto and "Primeiro item da 2.1.1" not in texto

    def test_a_version_without_a_block_gives_an_empty_string(self) -> None:
        assert release.changelog_section(CHANGELOG, V300, 3500) == ""

    def test_an_empty_changelog_gives_an_empty_string(self) -> None:
        assert release.changelog_section("", V211, 3500) == ""


class TestCorte:
    def test_a_text_that_fits_has_no_ellipsis(self) -> None:
        texto = release.changelog_section(CHANGELOG, V211, len("\n".join(LINHAS_DA_211)))

        assert ELLIPSIS not in texto

    def test_a_longer_text_is_cut_within_the_limit_and_ends_with_the_ellipsis(self) -> None:
        texto = release.changelog_section(CHANGELOG, V211, 120)

        assert texto.endswith(ELLIPSIS) and len(texto) <= 120

    def test_the_cut_falls_at_the_end_of_a_line_never_in_the_middle_of_one(self) -> None:
        texto = release.changelog_section(CHANGELOG, V211, 120)

        mantidas = texto.removesuffix(ELLIPSIS).split("\n")
        assert mantidas and all(linha in LINHAS_DA_211 for linha in mantidas)
        assert mantidas == LINHAS_DA_211[: len(mantidas)]

    def test_the_cut_keeps_as_many_whole_lines_as_fit(self) -> None:
        texto = release.changelog_section(CHANGELOG, V211, 120)

        tres_linhas = "\n".join(LINHAS_DA_211[:3]) + ELLIPSIS
        assert len(tres_linhas) <= 120 < len("\n".join(LINHAS_DA_211[:4]) + ELLIPSIS)
        assert texto == tres_linhas

    def test_a_limit_smaller_than_the_first_line_never_breaks(self) -> None:
        texto = release.changelog_section(CHANGELOG, V211, 5)

        assert len(texto) <= 5

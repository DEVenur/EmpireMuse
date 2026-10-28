"""2.1.2 (E) — as listas do seletor de skin (``/change_skin``) formam links embutidos no Discord desktop.

Screenshot do dono (desktop, 2.1.1): a lista "Modo Normal" saía crua (code span ``[``, code span com o nome, a URL como auto-link
solto e code span ``]``) e a "Modo Fixo" formava os links, embora o código montasse as duas do mesmo jeito. O que as separa é o contexto:
um parágrafo único de ~1,4 mil caracteres entre dois blocos ```ansi (Normal) contra ~0,7 mil seguidos de um code span (Fixo). Além disso os
títulos em ```ansi ficavam quase invisíveis. Agora: títulos em negrito, cada skin é um link embutido SEM code span (só o nome clica) e as
linhas ficam curtas (no máximo ``SKIN_LINKS_PER_ROW`` links, bem abaixo dos ~0,7 mil caracteres que já formaram link). Sem Discord: skins são dublês.
"""

from types import SimpleNamespace

import pytest

import empiremuse.cogs.music_settings as music_settings

pytestmark = pytest.mark.critical

URL = "https://raw.githubusercontent.com/EmpireCommunity/EmpireMuse/v2.1.2/assets/skins/skin_{tipo}_{nome}_preview.png"
LIMITE_DA_LINHA = 600  # o parágrafo de 687 caracteres da "Modo Fixo" formou os links; a de 1378 da "Modo Normal" não


def skins(tipo: str, *nomes: str) -> dict[str, SimpleNamespace]:
    return {nome: SimpleNamespace(preview=URL.format(tipo=tipo, nome=nome)) for nome in nomes}


NORMAIS = skins(
    "normal",
    "classic",
    "default",
    "micro_controller",
    "embed_link",
    "mini",
    "minimalist",
    "miniplayer",
    "default_progressbar",
    "lite",
    "micro_nc",
)
FIXAS = skins("static", "classic", "default", "embed_link", "mini", "default_progressbar")


def descricao() -> str:
    return music_settings.skin_selector_description(NORMAIS, list(NORMAIS), FIXAS, list(FIXAS))


class TestLinkDeUmaSkin:
    def test_the_skin_is_a_masked_link_with_plain_text_and_the_url_in_angle_brackets(self) -> None:
        link = music_settings.skin_link(NORMAIS, "classic")

        assert link == f"[classic](<{NORMAIS['classic'].preview}>)"

    def test_the_label_has_no_code_span_and_underscores_become_spaces(self) -> None:
        link = music_settings.skin_link(NORMAIS, "micro_controller")

        assert link.startswith("[micro controller](<https://")
        assert "`" not in link

    def test_a_skin_without_a_valid_preview_url_is_just_the_name(self) -> None:
        sem_url = {"x": SimpleNamespace(preview=None)}

        assert music_settings.skin_link(sem_url, "x") == "x"


class TestListas:
    def test_every_skin_of_both_lists_is_an_embedded_link(self) -> None:
        texto = descricao()

        for nome, skin in NORMAIS.items():
            assert f"[{nome.replace('_', ' ')}](<{skin.preview}>)" in texto
        for nome, skin in FIXAS.items():
            assert f"[{nome.replace('_', ' ')}](<{skin.preview}>)" in texto

    def test_the_lists_have_no_code_span_around_the_links_and_no_bare_brackets(self) -> None:
        for linha in descricao().splitlines():
            if linha.startswith("**") or not linha.strip() or linha.startswith("`Nota"):
                continue
            assert "`" not in linha
            assert "[`" not in linha and "`]" not in linha

    def test_the_headings_are_bold_and_not_ansi_blocks(self) -> None:
        texto = descricao()

        assert "**Modo Normal:**" in texto
        assert "**Modo Fixo (Song-Request):**" in texto
        assert "```" not in texto and "\x1b" not in texto

    def test_each_row_has_at_most_four_links_and_stays_short(self) -> None:
        for linha in descricao().splitlines():
            assert linha.count("](<") <= music_settings.SKIN_LINKS_PER_ROW == 4
            assert len(linha) <= LIMITE_DA_LINHA

    def test_the_order_and_the_split_into_rows_are_stable(self) -> None:
        linhas = descricao().splitlines()
        normal = linhas[linhas.index("**Modo Normal:**") + 1 : linhas.index("**Modo Fixo (Song-Request):**") - 1]

        assert [linha.count("](<") for linha in normal] == [4, 4, 2]
        assert normal[0].startswith("[classic](<") and " • " in normal[0]
        assert normal[-1].split(" • ")[-1].startswith("[micro nc](<")

    def test_the_global_note_stays_in_the_end(self) -> None:
        assert descricao().endswith("`Nota: No modo global a skin será aplicada globalmente em todos os bots.`")

    def test_a_list_with_a_single_skin_is_one_row(self) -> None:
        texto = music_settings.skin_selector_description(skins("normal", "default"), ["default"], FIXAS, list(FIXAS))

        assert "**Modo Normal:**\n[default](<" in texto

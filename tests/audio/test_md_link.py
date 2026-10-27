"""S-31, S1 — ``md_link``, ``md_url`` e ``md_code`` (``utils/music/converters.py``): escape de markdown em nomes externos.

Funções puras: nada de disnake real, rede ou relógio. As entradas "difíceis" vêm de ``tests/support/marcas_md.py``.
"""

import re

import pytest

from empiremuse.utils.music.converters import fix_characters, md_code, md_link, md_url
from tests.support.marcas_md import (
    ALHEIO,
    NOME_COM_CRASES,
    NOME_COM_MARCAS,
    URL_COM_CONTROLE,
    URL_COM_CRASE,
    URL_COM_ESPACO,
    URL_COM_MAIOR,
    URL_COM_MAIOR_CODIFICADA,
    URL_COM_PARENTESE,
    URL_COM_PARENTESE_CODIFICADA,
    URLS_FORA_DO_PADRAO,
    destinos,
    links_alheios,
    marcas_soltas,
)

pytestmark = pytest.mark.critical

URL = "https://a.exemplo/pasta/arquivo?x=1&y=2#frag"


class TestMdLink:
    def test_the_plain_case_is_a_code_span_label_with_an_angle_bracket_destination(self):
        assert md_link("Nome", URL) == f"[`Nome`](<{URL}>)"

    def test_the_label_goes_through_fix_characters(self):
        assert md_link("a[b]c`d*e_f", URL) == f"[`{fix_characters('a[b]c`d*e_f')}`](<{URL}>)"

    @pytest.mark.parametrize("nome", [NOME_COM_MARCAS, NOME_COM_CRASES], ids=["marcas", "crases"])
    def test_a_name_with_markdown_marks_cannot_close_the_link_or_the_code_span(self, nome):
        saida = md_link(nome, URL)

        assert saida.count("](") == 1 and saida.count("[`") == 1 and saida.count("`") == 2
        assert destinos(saida) == [URL] and links_alheios(saida) == [] and marcas_soltas(saida) == 0

    def test_a_close_paren_in_the_url_is_percent_encoded(self):
        saida = md_link("T", URL_COM_PARENTESE)

        assert saida == f"[`T`](<{URL_COM_PARENTESE_CODIFICADA}>)"
        assert links_alheios(saida) == [] and marcas_soltas(saida) == 0

    def test_a_close_angle_bracket_in_the_url_is_percent_encoded(self):
        saida = md_link("T", URL_COM_MAIOR)

        assert saida == f"[`T`](<{URL_COM_MAIOR_CODIFICADA}>)"
        assert links_alheios(saida) == [] and marcas_soltas(saida) == 0

    @pytest.mark.parametrize(
        ("url", "esperada"),
        [
            ("https://a.exemplo/x(y", "https://a.exemplo/x%28y"),
            ("https://a.exemplo/x)y", "https://a.exemplo/x%29y"),
            ("https://a.exemplo/x<y", "https://a.exemplo/x%3Cy"),
            ("https://a.exemplo/x>y", "https://a.exemplo/x%3Ey"),
            (URL_COM_CRASE, "https://ok.exemplo/x%60y"),
            (URL_COM_ESPACO, "https://ok.exemplo/a%20b"),
            (URL_COM_CONTROLE, "https://ok.exemplo/a%09b%0Ac"),
            ("https://a.exemplo/\x00\x1f\x7f", "https://a.exemplo/%00%1F%7F"),
        ],
        ids=["abre-paren", "fecha-paren", "menor", "maior", "crase", "espaco", "controles", "nulo-e-del"],
    )
    def test_each_dangerous_character_in_the_url_is_percent_encoded(self, url, esperada):
        assert md_url(url) == esperada
        assert md_link("T", url) == f"[`T`](<{esperada}>)"

    def test_nothing_else_in_the_url_changes(self):
        url = "https://usuario@a.exemplo:8080/p%20q/ç?q=[1]&r={2}#f|g"

        assert md_url(url) == url

    @pytest.mark.parametrize("url", ["http://a.exemplo/x", "https://a.exemplo", "HTTPS://A.EXEMPLO/x"])
    def test_http_and_https_with_a_host_are_accepted(self, url):
        assert md_url(url) is not None and md_link("T", url) == f"[`T`](<{md_url(url)}>)"

    @pytest.mark.parametrize("url", URLS_FORA_DO_PADRAO, ids=lambda u: u[:18] or "vazia")
    def test_other_schemes_or_no_host_give_only_the_label(self, url):
        assert md_url(url) is None
        assert md_link("Nome", url) == "`Nome`"
        assert md_link("Nome", url, code=False) == "Nome"

    @pytest.mark.parametrize(
        "url", [None, 123, 1.5, b"https://a.exemplo/x", ["https://a.exemplo/x"], object()], ids=repr
    )
    def test_a_url_that_is_not_a_str_gives_only_the_label(self, url):
        assert md_url(url) is None
        assert md_link("Nome", url) == "`Nome`"

    def test_the_label_is_cut_with_the_ellipsis(self):
        assert md_link("x" * 50, URL, limit=10) == f"[`{'x' * 10}...`](<{URL}>)"

    def test_the_cut_happens_before_the_escape_without_code(self):
        saida = md_link("a*b" * 20, URL, code=False, limit=10)

        assert saida.startswith("[") and saida.count("](") == 1
        assert (
            len(saida.split("](")[0]) <= 1 + 10 + 3 + 12
        )  # rótulo cortado (+ reticências + escapes), não o texto inteiro

    def test_an_empty_label_becomes_a_question_mark(self):
        assert md_link("", URL) == f"[`?`](<{URL}>)"
        assert md_link("", URL, code=False) == f"[?](<{URL}>)"
        assert md_link("", "nao-e-url") == "`?`"

    def test_a_label_that_is_not_a_str_is_converted(self):
        assert md_link(42, URL) == f"[`42`](<{URL}>)"
        assert md_link(None, URL) == f"[`None`](<{URL}>)"

    @pytest.mark.parametrize(
        ("rotulo", "restante"),
        [("a~b|c", "abc"), ("> citacao", " citacao"), ("l1\n> l2", "l1\n l2")],
        ids=["til-e-barra", "citacao", "citacao-na-2a-linha"],
    )
    def test_without_code_the_label_is_outside_backticks_and_markdown_is_escaped(self, rotulo, restante):
        saida = md_link(rotulo, URL, code=False)
        escrito = saida[1 : saida.index("](")]

        assert "`" not in saida
        assert re.sub(r"\\.", "", escrito) == restante  # tudo o que sobra de especial está escapado com barra
        assert destinos(saida) == [URL]

    def test_without_code_a_hostile_name_still_cannot_make_a_link(self):
        saida = md_link(NOME_COM_MARCAS, URL, code=False)

        assert saida.count("](") == 1 and links_alheios(saida) == [] and marcas_soltas(saida) == 0

    def test_the_output_is_a_single_line_for_a_label_without_line_breaks(self):
        assert "\n" not in md_link("Nome", URL_COM_CONTROLE)


class TestMdUrl:
    def test_it_is_the_same_encoder_md_link_uses(self):
        for url in (URL, URL_COM_PARENTESE, URL_COM_MAIOR, URL_COM_CRASE, URL_COM_ESPACO, URL_COM_CONTROLE):
            assert md_link("T", url) == f"[`T`](<{md_url(url)}>)"

    def test_it_is_idempotent_on_its_own_output(self):
        for url in (URL_COM_PARENTESE, URL_COM_MAIOR, URL_COM_ESPACO):
            assert md_url(md_url(url)) == md_url(url)

    def test_the_encoded_url_never_has_a_paren_angle_backtick_space_or_control(self):
        for url in (URL_COM_PARENTESE, URL_COM_MAIOR, URL_COM_CRASE, URL_COM_ESPACO, URL_COM_CONTROLE):
            saida = md_url(url)
            assert saida is not None
            assert not re.search(r"[()<>`\x00-\x20\x7f]", saida), saida


class TestMdCode:
    def test_the_plain_case(self):
        assert md_code("Nome") == "`Nome`"

    def test_it_applies_fix_characters(self):
        assert md_code("a`b[c]d") == f"`{fix_characters('a`b[c]d')}`"

    def test_a_name_with_backticks_cannot_close_the_code_span(self):
        saida = md_code(NOME_COM_MARCAS)

        assert saida.count("`") == 2 and saida.startswith("`") and saida.endswith("`")

    def test_the_limit_cuts_with_the_ellipsis(self):
        assert md_code("x" * 50, limit=10) == f"`{'x' * 10}...`"

    def test_empty_becomes_a_question_mark(self):
        assert md_code("") == "`?`"

    def test_a_non_str_is_converted(self):
        assert md_code(7) == "`7`"


class TestFixCharactersContinuaIdempotente:
    @pytest.mark.parametrize(
        "texto", ["`", "[", "]", "*", "_", "{", "}", "`[]*_{}", NOME_COM_MARCAS, "a`b[c]d*e_f{g}h"]
    )
    def test_applying_it_twice_changes_nothing(self, texto):
        assert fix_characters(fix_characters(texto)) == fix_characters(texto)

    def test_the_alien_domain_constant_is_only_text_in_the_inputs(self):
        assert ALHEIO in NOME_COM_MARCAS and ALHEIO in URL_COM_PARENTESE

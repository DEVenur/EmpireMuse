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
    URL_COM_BARRA,
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
            ("https://a.exemplo/x\\y", "https://a.exemplo/x%5Cy"),
        ],
        ids=[
            "abre-paren",
            "fecha-paren",
            "menor",
            "maior",
            "crase",
            "espaco",
            "controles",
            "nulo-e-del",
            "barra-invertida",
        ],
    )
    def test_each_dangerous_character_in_the_url_is_percent_encoded(self, url, esperada):
        assert md_url(url) == esperada
        assert md_link("T", url) == f"[`T`](<{esperada}>)"

    def test_nothing_else_in_the_url_changes(self):
        url = "https://a.exemplo:8080/p%20q/ç?q=[1]&r={2}#f|g"

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
        [("a~b|c", "abc"), ("> citacao", " citacao")],
        ids=["til-e-barra", "citacao"],
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


USUARIO_E_SENHA = "".join(["usuario", ":", "credencial-qualquer"])
URLS_COM_CREDENCIAL = [
    f"https://{USUARIO_E_SENHA}@a.exemplo/x",
    "https://usuario@a.exemplo/x",
    f"http://{USUARIO_E_SENHA}@a.exemplo:8080/",
    "https://a.exemplo@alheio.exemplo/x",
]
QUEBRAS = ["\n", "\r\n", "\r", "\u2028", "\u2029"]


class TestUrlComCredencial:
    @pytest.mark.parametrize("url", URLS_COM_CREDENCIAL, ids=lambda u: u.split("@")[0][-12:])
    def test_a_url_with_userinfo_is_refused_and_only_the_label_remains(self, url):
        assert md_url(url) is None
        assert md_link("Nome", url) == "`Nome`" and md_link("Nome", url, code=False) == "Nome"

    def test_an_at_sign_after_the_host_is_not_userinfo(self):
        assert md_url("https://a.exemplo/x@y?e=a@b") is not None


class TestRotuloEmUmaLinha:
    @pytest.mark.parametrize("quebra", QUEBRAS, ids=lambda q: repr(q))
    @pytest.mark.parametrize("code", [True, False], ids=["code", "texto"])
    def test_a_line_break_in_the_label_cannot_split_the_masked_link(self, quebra, code):
        saida = md_link(f"antes{quebra}depois", URL, code=code)

        assert not any(c in saida for c in QUEBRAS)
        assert destinos(saida) == [URL] and marcas_soltas(saida) == 0 and "antes" in saida and "depois" in saida

    @pytest.mark.parametrize("quebra", QUEBRAS, ids=lambda q: repr(q))
    def test_a_line_break_in_a_code_span_label_stays_on_one_line(self, quebra):
        assert not any(c in md_code(f"antes{quebra}depois") for c in QUEBRAS)

    def test_a_label_made_only_of_line_breaks_still_gives_a_single_line_link(self):
        saida = md_link("\n\n", URL)

        assert destinos(saida) == [URL] and "\n" not in saida


class TestMdUrl:
    def test_it_is_the_same_encoder_md_link_uses(self):
        for url in (URL, URL_COM_PARENTESE, URL_COM_MAIOR, URL_COM_CRASE, URL_COM_ESPACO, URL_COM_CONTROLE):
            assert md_link("T", url) == f"[`T`](<{md_url(url)}>)"

    def test_it_is_idempotent_on_its_own_output(self):
        for url in (URL_COM_PARENTESE, URL_COM_MAIOR, URL_COM_ESPACO):
            assert md_url(md_url(url)) == md_url(url)

    def test_the_encoded_url_never_has_a_paren_angle_backtick_space_or_control(self):
        for url in (URL_COM_PARENTESE, URL_COM_MAIOR, URL_COM_CRASE, URL_COM_ESPACO, URL_COM_CONTROLE, URL_COM_BARRA):
            saida = md_url(url)
            assert saida is not None
            assert not re.search(r"[()<>`\\\x00-\x20\x7f]", saida), saida


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

"""S-31, S4 — teste-guarda (AST): em ``empiremuse/**`` nenhum texto monta à mão um link mascarado ou um code span com conteúdo externo.

Fora de ``converters.py`` (onde mora o ``md_link``/``md_code``) e da lista de exceções abaixo, é proibido:
* f-string (``JoinedStr``) cujas partes literais tenham ``](`` ou ``[` ``;
* ``+`` ou ``%`` em que um dos lados é um literal de texto com esses marcadores;
* ``.format(...)`` sobre um literal de texto com esses marcadores;
* qualquer outro literal de texto com esses marcadores (modelos em dados).

Docstrings não contam. Cada exceção é um arquivo INTEIRO com o motivo (texto 100% do próprio bot, ou código que lê markdown em vez de montá-lo);
a lista só cresce com o motivo escrito e a conferência do Litmus/Keystone, e uma exceção que não tem mais nenhum caso falha (para a lista não apodrecer).
O scanner tem testes próprios (abaixo) com trechos de código sintéticos.
"""

import ast
from pathlib import Path

import pytest

from tests.support.raiz import RAIZ

pytestmark = pytest.mark.critical

PACOTE = RAIZ / "empiremuse"
MARCADORES = ("](", "[`")
ARQUIVO_DO_HELPER = "empiremuse/utils/music/converters.py"

# arquivo -> (motivo, nº de achados). Só texto 100% do próprio bot ou código que LÊ markdown; nada que mostre nome, título, álbum, playlist,
# favorito ou URL de terceiros. O nº é exato: um achado a mais (código novo na exceção) ou a menos (migrou) falha o teste.
EXCECOES: dict[str, tuple[str, int]] = {
    "empiremuse/updater/notice.py": (
        "link do histórico/changelog do repositório oficial do próprio bot (versão e URL do próprio projeto)",
        2,
    ),
    "empiremuse/logs/redact.py": ("padrões de REDAÇÃO de segredo em texto de log (regex), não monta markdown", 1),
    "empiremuse/utils/music/errors.py": (
        "mensagem fixa do próprio bot sobre o YouTube, com link de documentação do projeto",
        1,
    ),
    "empiremuse/music_cog/song_requests.py": ("texto fixo do próprio bot na conversa de pedidos de música", 1),
    "empiremuse/utils/music/interactions/skin_editor_data.py": (
        "modelos PADRÃO de skin com placeholders (3b): a troca por nomes/URLs reais é do skin_utils, que escapa",
        2,
    ),
    "empiremuse/utils/music/remote_lavalink_serverlist.py": (
        "LÊ markdown da lista pública de nós (split por '](') em vez de montá-lo",
        1,
    ),
}


def _tem_marcador(texto: object) -> bool:
    return isinstance(texto, str) and any(m in texto for m in MARCADORES)


def _texto_literal(no: ast.AST) -> str | None:
    return no.value if isinstance(no, ast.Constant) and isinstance(no.value, str) else None


def achados(codigo: str) -> list[tuple[int, str]]:
    """``(linha, tipo)`` de cada montagem proibida no código: ``fstring``, ``soma``, ``formato-%``, ``format`` ou ``literal``."""
    arvore = ast.parse(codigo)
    docstrings: set[int] = set()
    dentro_de_fstring: set[int] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Expr) and _texto_literal(no.value) is not None:
            docstrings.add(id(no.value))
        if isinstance(no, ast.JoinedStr):
            for parte in no.values:
                if isinstance(parte, ast.Constant):
                    dentro_de_fstring.add(id(parte))
    resultado: list[tuple[int, str]] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.JoinedStr):
            literal = "\0".join(p.value for p in no.values if isinstance(p, ast.Constant) and isinstance(p.value, str))
            lacunado = "".join(p.value if isinstance(p, ast.Constant) else "\0" for p in no.values)
            if _tem_marcador(literal) or _tem_marcador(lacunado):
                resultado.append((no.lineno, "fstring"))
        elif isinstance(no, ast.BinOp) and isinstance(no.op, (ast.Add, ast.Mod)):
            if any(_tem_marcador(_texto_literal(lado)) for lado in (no.left, no.right)):
                resultado.append((no.lineno, "soma" if isinstance(no.op, ast.Add) else "formato-%"))
        elif isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == "format":
            if _tem_marcador(_texto_literal(no.func.value)):
                resultado.append((no.lineno, "format"))
        elif isinstance(no, ast.Constant) and _tem_marcador(no.value):
            if id(no) not in docstrings and id(no) not in dentro_de_fstring:
                resultado.append((no.lineno, "literal"))
    return resultado


def arquivos_do_pacote():
    for caminho in sorted(PACOTE.rglob("*.py")):
        relativo = caminho.relative_to(RAIZ).as_posix()
        if relativo != ARQUIVO_DO_HELPER:
            yield relativo, caminho


# ============================================================================ o scanner (guarda do próprio guarda)


class TestScanner:
    @pytest.mark.parametrize(
        ("codigo", "tipo"),
        [
            ('x = f"[`{nome}`]({url})"', "fstring"),
            ('x = f"[{nome}]({url})"', "fstring"),
            ('x = f"`{nome}`"  # sem link', None),
            ('x = "[`" + nome + "`](" + url + ")"', "soma"),
            ('x = "[`%s`](%s)" % (nome, url)', "formato-%"),
            ('x = "[`{}`]({})".format(nome, url)', "format"),
            ('modelo = {"d": "[{track.title}]({track.url})"}', "literal"),
            ('modelo = ["[`{n}`]"]', "literal"),
            ('x = "[`"', "literal"),
        ],
    )
    def test_it_finds_each_kind_of_hand_built_markup(self, codigo, tipo):
        tipos = [t for _, t in achados(codigo)]

        assert (tipo in tipos) if tipo else (tipos == [])

    @pytest.mark.parametrize(
        "codigo",
        [
            'def f():\n    """Docstring com [`x`](u) dentro."""\n    return 1',
            '"""Docstring de módulo com ]( no texto."""',
            'x = "texto simples"',
            'x = f"{a} e {b}"',
            'x = "a" + "b"',
            'x = "um [colchete] sem parêntese"',
            'x = "só `crase`"',
            "x = md_link(nome, url)",
            "x = md_code(nome)",
        ],
    )
    def test_it_ignores_docstrings_and_text_without_the_markers(self, codigo):
        assert achados(codigo) == []

    def test_an_fstring_is_reported_once_not_once_per_part(self):
        assert achados('x = f"[`{a}`]({b}) e [`{c}`]({d})"') == [(1, "fstring")]

    def test_implicitly_concatenated_fstrings_are_one_string_and_the_marker_forms_between_them(self):
        assert [t for _, t in achados('x = f"[{a}]" f"({b})"')] == ["fstring"]  # "]" e "(" ficam lado a lado: "]("
        assert [
            t for _, t in achados('x = f"[{a}]" + f"({b})"')
        ] == []  # duas f-strings separadas por "+" não têm "](" literal

    def test_the_line_number_is_the_line_of_the_construct(self):
        assert achados('a = 1\nb = 2\nx = f"[`{n}`]({u})"\n') == [(3, "fstring")]


# ============================================================================ a guarda sobre o código do bot


class TestCodigoDoBot:
    def test_nothing_in_the_package_builds_masked_links_or_code_spans_by_hand(self):
        restantes: dict[str, list[tuple[int, str]]] = {}
        for relativo, caminho in arquivos_do_pacote():
            if relativo in EXCECOES:
                continue
            if lista := achados(caminho.read_text(encoding="utf-8")):
                restantes[relativo] = lista

        resumo = {arquivo: len(lista) for arquivo, lista in restantes.items()}
        assert restantes == {}, f"{sum(resumo.values())} montagens à mão em {len(resumo)} arquivos: {resumo}"


class TestExcecoes:
    def test_every_exception_has_a_written_reason(self):
        assert EXCECOES and all(
            isinstance(motivo, str) and len(motivo) > 20 and n > 0 for motivo, n in EXCECOES.values()
        )

    @pytest.mark.parametrize("arquivo", sorted(EXCECOES))
    def test_every_exception_points_to_an_existing_file(self, arquivo):
        assert (RAIZ / arquivo).is_file()

    @pytest.mark.parametrize("arquivo", sorted(EXCECOES))
    def test_the_number_of_findings_in_an_exception_is_exact(self, arquivo):
        achados_do_arquivo = achados((RAIZ / arquivo).read_text(encoding="utf-8"))

        assert len(achados_do_arquivo) == EXCECOES[arquivo][1], (arquivo, achados_do_arquivo)

    def test_the_files_that_show_external_names_are_not_exceptions(self):
        for arquivo in (
            "empiremuse/cogs/lastfm.py",
            "empiremuse/utils/music/interactions/fav_menu_text.py",
            "empiremuse/utils/others.py",
        ):
            assert arquivo not in EXCECOES

    def test_the_helper_file_itself_is_the_only_file_excluded_without_a_reason(self):
        assert ARQUIVO_DO_HELPER == "empiremuse/utils/music/converters.py"
        assert (RAIZ / ARQUIVO_DO_HELPER).is_file()

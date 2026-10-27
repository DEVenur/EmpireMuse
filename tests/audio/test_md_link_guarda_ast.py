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


FUNCOES_SEGURAS_EM_CRASE = {"md_code", "fix_characters", "time_format", "int", "len", "round", "float", "abs"}


def _seguro_em_crase(expressao: ast.expr) -> bool:
    """Número, ou chamada de ``md_code``/``fix_characters``/``time_format`` (e conversões numéricas), ou conta só entre elas."""
    if isinstance(expressao, ast.Constant):
        return isinstance(expressao.value, (int, float))
    if isinstance(expressao, ast.Call):
        funcao = expressao.func
        nome = funcao.id if isinstance(funcao, ast.Name) else funcao.attr if isinstance(funcao, ast.Attribute) else ""
        return nome in FUNCOES_SEGURAS_EM_CRASE
    return isinstance(expressao, ast.BinOp) and _seguro_em_crase(expressao.left) and _seguro_em_crase(expressao.right)


def achados_em_crase(codigo: str) -> list[tuple[int, str]]:
    """S4b: ``(linha, expressão)`` de cada valor de f-string entre crases (``` `{x}` ```) que não é número nem passou por ``md_code``/``fix_characters``."""
    resultado: list[tuple[int, str]] = []
    for no in ast.walk(ast.parse(codigo)):
        if not isinstance(no, ast.JoinedStr):
            continue
        partes = no.values
        for i in range(1, len(partes) - 1):
            valor, antes, depois = partes[i], partes[i - 1], partes[i + 1]
            if not (
                isinstance(valor, ast.FormattedValue)
                and isinstance(antes, ast.Constant)
                and isinstance(depois, ast.Constant)
            ):
                continue
            if (
                str(antes.value).endswith("`")
                and str(depois.value).startswith("`")
                and not _seguro_em_crase(valor.value)
            ):
                resultado.append((valor.lineno, ast.unparse(valor.value)))
    return resultado


# S4b — arquivo -> (motivo, nº de achados). Triagem do Vigil (s31-md-link.md §8) para os da lista dele; os marcados "(extra)" são o MESMO tipo de falso
# positivo (valor numérico ou texto do próprio bot numa variável) que o Keystone não listou. NÃO entram: event_steps.py:260, autoqueue_steps.py:384 e
# music_cog/nodes.py:69 (severity/node vindos do nó), que ficam vermelhos até o fix do Prism. Contagem exata, como no S4.
NUMERO = "valor numérico (contagem, ID, intervalo) em variável (extra)"
EXCECOES_S4B: dict[str, tuple[str, int]] = {
    "empiremuse/cogs/lastfm.py": ("país vindo de lista fixa do Last.fm (Vigil)", 1),
    "empiremuse/cogs/legacy_cmds.py": (
        "prefixo de comando: até 5 caracteres, sem espaço, com escape_markdown quando aplicável (Vigil)",
        3,
    ),
    "empiremuse/cogs/misc.py": (
        "prefixos (Vigil, 662-671) e valores numéricos/versões do painel de informações (extra)",
        22,
    ),
    "empiremuse/cogs/music_settings.py": (
        "nome de skin já validado (Vigil, 1104/1110/1122/1129) e números/status do nodeinfo (extra)",
        7,
    ),
    "empiremuse/music_cog/play_enqueue.py": (
        "query já passa por fix_characters (Vigil, 422) e time_format condicional (extra)",
        2,
    ),
    "empiremuse/utils/music/models/helpers.py": ("plain_snippet já saneia o texto (Vigil)", 1),
    "empiremuse/cogs/help_cog.py": ("nomes de comando do próprio bot (Vigil)", 2),
    "empiremuse/cogs/error_handler.py": ("código ERR- gerado pelo bot (Vigil)", 1),
    "empiremuse/utils/music/errors.py": ("código ERR- gerado pelo bot (Vigil)", 2),
    "empiremuse/updater/git_flow.py": ("_printable já saneia o nome (Vigil)", 1),
    "empiremuse/utils/music/interactions/favorites_texts.py": ("_echo já corta e escapa o nome (Vigil)", 2),
    "empiremuse/cogs/ll_yt_oauth.py": ("token com charset restrito (Vigil)", 1),
    "empiremuse/cogs/server_manager.py": (NUMERO, 4),
    "empiremuse/music_cog/now_playing.py": (NUMERO, 1),
    "empiremuse/music_cog/queue_clear_steps.py": (NUMERO, 4),
    "empiremuse/music_cog/queue_move_steps.py": (NUMERO, 4),
    "empiremuse/music_cog/song_request_steps.py": ("time_format em expressão condicional (extra)", 1),
    "empiremuse/utils/music/models/event_steps.py": (
        "plain_snippet já saneia a mensagem (extra); a 260 (severity do nó) NÃO está aqui e deixa o arquivo vermelho",
        1,
    ),
    "empiremuse/utils/music/skins/normal_player/embed_link.py": ("dica do próprio bot (current_hint) (extra)", 1),
    "empiremuse/utils/music/skins/normal_player/lite.py": ("duração numérica em variável (extra)", 1),
    "empiremuse/utils/music/skins/static_player/default.py": (
        "contagem de repetições e emoji do próprio bot (extra)",
        2,
    ),
    "empiremuse/utils/music/skins/static_player/default_progressbar.py": (
        "contagem de repetições e emoji do próprio bot (extra)",
        2,
    ),
    "empiremuse/utils/music/skins/static_player/embed_link.py": ("contagem de repetições (extra)", 1),
}


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


class TestScannerEmCrase:
    @pytest.mark.parametrize(
        "codigo",
        [
            "x = f\"`{track.info['sourceName']}`\"",
            'x = f"Região: `{node.region.title()}`"',
            'x = f"```{guild.name}```"',
            'x = f"a `{nome}` b"',
        ],
    )
    def test_it_finds_a_raw_value_inside_backticks(self, codigo):
        assert len(achados_em_crase(codigo)) == 1

    @pytest.mark.parametrize(
        "codigo",
        [
            'x = f"`{md_code(nome)}`"',
            'x = f"`{fix_characters(nome, 40)}`"',
            'x = f"`{time_format(ms)}`"',
            'x = f"`{len(lista)}`"',
            'x = f"`{int(total)}`"',
            'x = f"`{3}`"',
            'x = f"{nome} sem crase"',
            'x = f"`aberta {nome}"',
            'x = f"{nome}`"',
        ],
    )
    def test_it_ignores_safe_values_and_values_outside_backticks(self, codigo):
        assert achados_em_crase(codigo) == []

    def test_the_line_number_and_the_expression_are_reported(self):
        assert achados_em_crase('a = 1\nx = f"`{obj.nome}`"') == [(2, "obj.nome")]


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


class TestCrasesNoCodigoDoBot:
    """S4b sobre ``empiremuse/**``: nenhum valor cru de terceiros entre crases fora da lista de exceções com contagem exata."""

    def test_no_file_outside_the_exceptions_has_a_raw_value_inside_backticks(self):
        restantes: dict[str, list[tuple[int, str]]] = {}
        for relativo, caminho in arquivos_do_pacote():
            if relativo in EXCECOES_S4B:
                continue
            if lista := achados_em_crase(caminho.read_text(encoding="utf-8")):
                restantes[relativo] = lista

        assert restantes == {}, restantes

    @pytest.mark.parametrize("arquivo", sorted(EXCECOES_S4B))
    def test_the_number_of_findings_in_an_exception_is_exact(self, arquivo):
        achados_do_arquivo = achados_em_crase((RAIZ / arquivo).read_text(encoding="utf-8"))

        assert len(achados_do_arquivo) == EXCECOES_S4B[arquivo][1], (arquivo, achados_do_arquivo)

    def test_every_exception_has_a_written_reason_and_an_existing_file(self):
        assert all(
            len(motivo) > 15 and n > 0 and (RAIZ / arquivo).is_file() for arquivo, (motivo, n) in EXCECOES_S4B.items()
        )

    def test_the_three_node_text_sites_are_not_exceptions(self):
        for arquivo in ("empiremuse/utils/music/models/autoqueue_steps.py", "empiremuse/music_cog/nodes.py"):
            assert arquivo not in EXCECOES_S4B

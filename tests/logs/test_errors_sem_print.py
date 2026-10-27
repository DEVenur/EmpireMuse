"""Item 7, P4 — B18 (K17): nada de ``print``/``print_exc``/f-string em log nos arquivos da partição do P4; as regras do Ruff estão ligadas.

Os arquivos são os da coluna Turbine de ``s31-md-link.md`` §7 (os do Prism saem pelo S-31). O guarda é por AST (o que o ``T201``/``T203``/``G004``
pegam); a prova final é o CI com as regras ligadas no ``pyproject.toml`` — aqui só se confere que estão em ``select`` e que cada exceção
por arquivo tem motivo escrito.
"""

import ast
import tomllib

import pytest

from tests.support.raiz import RAIZ

pytestmark = pytest.mark.critical

ARQUIVOS = [
    "logs/errors.py",
    "cogs/error_handler.py",
    "__main__.py",
    "utils/client.py",
    "web_app.py",
    "music_cog/controller_dispatch.py",
    "music_cog/play_command.py",
    "music_cog/queue_group.py",
    "music_cog/song_requests.py",
    "music_cog/tracks.py",
    "music_cog/player_lifecycle.py",
    "utils/db.py",
    "utils/music/checks.py",
    "utils/music/errors.py",
    "utils/music/request_channel.py",
    "wavelink/meta.py",
    "panel/handlers/base.py",
]
METODOS_DE_LOG = {"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal"}
IMPRESSAO = {"print", "pprint", "pp"}
TRACEBACK_IMPRESSO = {"print_exc", "print_exception", "print_stack"}


def _montado_a_mao(no: ast.AST) -> bool:
    if isinstance(no, ast.JoinedStr):
        return True
    if isinstance(no, ast.BinOp) and isinstance(no.op, (ast.Add, ast.Mod)):
        return any(isinstance(lado, (ast.Constant, ast.JoinedStr)) for lado in (no.left, no.right))
    return isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == "format"


def _nome_do_receptor(no: ast.expr) -> str:
    return no.id if isinstance(no, ast.Name) else no.attr if isinstance(no, ast.Attribute) else ""


def infracoes(codigo: str) -> list[tuple[int, str]]:
    """``(linha, regra)``: ``T201`` (print/pprint), ``T201-tb`` (``traceback.print_*``) e ``G004`` (log com texto montado à mão)."""
    achados: list[tuple[int, str]] = []
    for no in ast.walk(ast.parse(codigo)):
        if not isinstance(no, ast.Call):
            continue
        funcao = no.func
        if isinstance(funcao, ast.Name) and funcao.id in IMPRESSAO:
            achados.append((no.lineno, "T201"))
        elif isinstance(funcao, ast.Attribute):
            if funcao.attr in TRACEBACK_IMPRESSO and _nome_do_receptor(funcao.value) == "traceback":
                achados.append((no.lineno, "T201-tb"))
            elif funcao.attr in METODOS_DE_LOG and "log" in _nome_do_receptor(funcao.value).lower():
                if no.args and _montado_a_mao(no.args[0]):
                    achados.append((no.lineno, "G004"))
    return achados


class TestScanner:
    @pytest.mark.parametrize(
        ("codigo", "regra"),
        [
            ("print('x')", "T201"),
            ("pprint(x)", "T201"),
            ("import traceback\ntraceback.print_exc()", "T201-tb"),
            ("logger.error(f'falha {x}')", "G004"),
            ("logger.info('a' + x)", "G004"),
            ("logger.warning('a %s' % x)", "G004"),
            ("logger.debug('a {}'.format(x))", "G004"),
            ("commands_logger.info(f'x {y}')", "G004"),
        ],
    )
    def test_it_finds_each_kind(self, codigo, regra):
        assert regra in [r for _, r in infracoes(codigo)]

    @pytest.mark.parametrize(
        "codigo",
        [
            "logger.info('a %s', x)",
            "logger.exception('falha')",
            "logger.error('a %s b', f(x))",
            "texto.format(x)",
            "obj.info(f'x {y}')",
            "traceback.format_exc()",
        ],
    )
    def test_it_ignores_lazy_args_and_calls_that_are_not_logging(self, codigo):
        assert infracoes(codigo) == []


class TestPartitionDoP4:
    def test_the_new_errors_module_exists(self):
        assert (RAIZ / "empiremuse/logs/errors.py").is_file()

    @pytest.mark.parametrize("arquivo", ARQUIVOS)
    def test_the_file_has_no_print_traceback_print_or_handmade_log_text(self, arquivo):
        caminho = RAIZ / "empiremuse" / arquivo
        if not caminho.is_file():
            pytest.fail(f"{arquivo} não existe")

        assert infracoes(caminho.read_text(encoding="utf-8")) == []


class TestRegrasDoRuff:
    @pytest.fixture(scope="class")
    def pyproject(self):
        return tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))

    @pytest.mark.parametrize("regra", ["T201", "T203", "G004", "LOG015"])
    def test_the_rule_is_selected(self, pyproject, regra):
        assert regra in pyproject["tool"]["ruff"]["lint"]["select"]

    def test_every_per_file_exception_has_a_written_reason(self, pyproject):
        linhas = (RAIZ / "pyproject.toml").read_text(encoding="utf-8").splitlines()
        excecoes = pyproject["tool"]["ruff"]["lint"].get("per-file-ignores", {})
        for arquivo in excecoes:
            indice = next(i for i, linha in enumerate(linhas) if arquivo in linha and "=" in linha)
            comentada = "#" in linhas[indice] or linhas[indice - 1].lstrip().startswith("#")
            assert comentada, f"{arquivo}: exceção sem comentário de motivo"

    def test_the_isolated_proxy_script_is_the_only_exception_for_print(self, pyproject):
        excecoes = pyproject["tool"]["ruff"]["lint"].get("per-file-ignores", {})
        com_t201 = [arquivo for arquivo, regras in excecoes.items() if "T201" in regras]

        assert all(arquivo.endswith("updater/proxy.py") for arquivo in com_t201)

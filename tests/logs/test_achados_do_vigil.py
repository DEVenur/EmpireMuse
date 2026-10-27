"""Item 7 (P1) — achados Low/Info do Vigil: V-P1-7 (surrogate solto no arquivo), V-P1-8 (tokens do OAuth do YouTube) e o nome do logger no cabeçalho.

``configure_logging`` real (console em ``StringIO``, arquivo em ``tmp_path``); o ``oauth_command`` roda com a view e a sessão falsas.
"""

import asyncio
import io
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empiremuse.cogs import ll_yt_oauth
from empiremuse.logs.console import ConsoleFormatter, FileFormatter
from empiremuse.logs.redact import REDACTED, redact
from empiremuse.logs.setup import configure_logging
from empiremuse.logs.settings import LogSettings
from tests.logs.apoio import registro

pytestmark = pytest.mark.critical

SURROGATE = "\ud800"


@pytest.fixture
def destinos(tmp_path):
    console = io.StringIO()
    configure_logging(
        LogSettings(logging.INFO, False, True, frozenset(), 300), [], stream=console, logs_dir=tmp_path / ".logs"
    )
    return SimpleNamespace(console=console, arquivo=tmp_path / ".logs" / "disnake.log")


def ler_arquivo(destinos) -> str:
    return destinos.arquivo.read_bytes().decode("utf-8")  # estrito: o que está em disco tem de ser UTF-8 válido


# ============================================================================ V-P1-7 — surrogate solto


class TestSurrogateSolto:
    def test_a_lone_surrogate_in_the_message_reaches_the_file_escaped_and_the_console(self, destinos, capsys):
        logging.getLogger("empiremuse.teste").warning("título " + SURROGATE + " fim")

        err = capsys.readouterr().err
        assert "[log] falha ao emitir um registro" not in err and "UnicodeEncodeError" not in err
        arquivo = ler_arquivo(destinos)
        assert "título" in arquivo and "fim" in arquivo and "\\ud800" in arquivo and SURROGATE not in arquivo
        assert "título" in destinos.console.getvalue() and "fim" in destinos.console.getvalue()

    def test_a_lone_surrogate_in_an_argument_reaches_the_file_escaped(self, destinos, capsys):
        logging.getLogger("empiremuse.teste").warning("faixa %s", "a" + SURROGATE + "b")

        assert "[log] falha ao emitir um registro" not in capsys.readouterr().err
        assert "\\ud800" in ler_arquivo(destinos)

    def test_a_lone_surrogate_in_a_traceback_reaches_the_file_escaped(self, destinos, capsys):
        try:
            raise ValueError("json com " + SURROGATE)
        except ValueError:
            logging.getLogger("empiremuse.teste").exception("falhou")

        assert "[log] falha ao emitir um registro" not in capsys.readouterr().err
        assert "ValueError" in ler_arquivo(destinos) and "\\ud800" in ler_arquivo(destinos)

    def test_the_records_after_a_surrogate_are_still_written_and_valid_text_is_untouched(self, destinos):
        log = logging.getLogger("empiremuse.teste")

        log.warning("ruim " + SURROGATE)
        log.info("depois: ação 🎵 ok")

        arquivo = ler_arquivo(destinos)
        assert "depois: ação 🎵 ok" in arquivo

    def test_a_surrogate_from_json_loads_is_handled_like_any_other(self, destinos, capsys):
        import json

        logging.getLogger("empiremuse.teste").warning("título: %s", json.loads('"\\ud800"'))

        assert "[log] falha ao emitir um registro" not in capsys.readouterr().err
        assert "\\ud800" in ler_arquivo(destinos)


# ============================================================================ V-P1-8 — tokens do OAuth do YouTube


class ViewFalsa:
    """Substituta do ``YtOauthView``: já "autenticada", com os tokens obtidos em tempo de execução."""

    dados: dict = {}

    def __init__(self, **kwargs):
        self.interaction = None
        self.exception_txt = None
        self.data = dict(self.dados)

    async def wait(self):
        return None


def cog_com_sessao_que_para():
    class Sessao:
        def get(self, *args, **kwargs):
            raise RuntimeError("userinfo parado")

    cog = ll_yt_oauth.YtOauthLL.__new__(ll_yt_oauth.YtOauthLL)
    cog.bot = SimpleNamespace(get_color=lambda *a: 0, session=Sessao())
    ctx = SimpleNamespace(
        guild=SimpleNamespace(me=None), send=AsyncMock(return_value=SimpleNamespace(edit=AsyncMock()))
    )
    return cog, ctx


class TestTokensDoOauth:
    def test_the_refresh_and_access_tokens_are_registered_as_soon_as_they_are_obtained(self, monkeypatch):
        refresh, access = "refresh-oauth-runtime-P1x9", "access-oauth-runtime-Q2y8"
        ViewFalsa.dados = {"refresh_token": refresh, "access_token": access}
        monkeypatch.setattr(ll_yt_oauth, "YtOauthView", ViewFalsa)
        cog, ctx = cog_com_sessao_que_para()
        assert redact(f"x {refresh}") == f"x {refresh}"

        with pytest.raises(RuntimeError, match="userinfo parado"):
            asyncio.run(cog.oauth_command(ctx))

        assert redact(f"x {refresh}") == f"x {REDACTED}" and redact(f"x {access}") == f"x {REDACTED}"

    def test_the_url_encoded_forms_are_masked_too(self, monkeypatch):
        from urllib.parse import quote

        refresh = "1//0g refresh/com+especiais=R3z"
        ViewFalsa.dados = {"refresh_token": refresh, "access_token": "access-com-formas-S4w7"}
        monkeypatch.setattr(ll_yt_oauth, "YtOauthView", ViewFalsa)
        cog, ctx = cog_com_sessao_que_para()

        with pytest.raises(RuntimeError):
            asyncio.run(cog.oauth_command(ctx))

        assert refresh not in redact(refresh) and quote(refresh, safe="") not in redact(quote(refresh, safe=""))

    def test_an_expired_flow_without_tokens_registers_nothing_and_raises_the_usual_error(self, monkeypatch):
        from empiremuse.utils.music.errors import GenericError

        ViewFalsa.dados = {}
        monkeypatch.setattr(ll_yt_oauth, "YtOauthView", ViewFalsa)
        cog, ctx = cog_com_sessao_que_para()

        with pytest.raises(GenericError):
            asyncio.run(cog.oauth_command(ctx))


# ============================================================================ nome do logger no cabeçalho

NOME_FORJADO = "x\nERROR forjado"


class TestNomeDoLogger:
    @pytest.mark.parametrize(
        "formatador",
        [lambda: ConsoleFormatter(False), lambda: ConsoleFormatter(True), FileFormatter],
        ids=["console", "console-cor", "arquivo"],
    )
    def test_a_line_break_in_the_logger_name_cannot_forge_a_line(self, formatador):
        saida = formatador().format(registro("mensagem", nome=NOME_FORJADO))

        assert saida.count("\n") == 0 and "x⏎ERROR forjado: mensagem" in saida

    @pytest.mark.parametrize("nome", ["a\x1b[2Jb", "a\x9bb", "a‮b", "a⁦b", "a\rb", "a b"])
    @pytest.mark.parametrize("formatador", [lambda: ConsoleFormatter(False), FileFormatter], ids=["console", "arquivo"])
    def test_controls_and_bidi_in_the_logger_name_never_reach_the_output(self, formatador, nome):
        saida = formatador().format(registro("mensagem", nome=nome))

        assert not any(c in saida for c in ("\x1b", "\x9b", "‮", "⁦", "\r", " ")) and saida.count("\n") == 0

    def test_an_ordinary_logger_name_is_untouched(self):
        assert "empiremuse.wavelink.local: m" in FileFormatter().format(registro("m", nome="empiremuse.wavelink.local"))

    def test_end_to_end_a_forged_logger_name_gives_one_header_in_each_destination(self, destinos):
        logging.getLogger(NOME_FORJADO).warning("do logger forjado")

        for texto in (destinos.console.getvalue(), ler_arquivo(destinos)):
            assert len(texto.splitlines()) == 1 and "x⏎ERROR forjado" in texto

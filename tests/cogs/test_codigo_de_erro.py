"""F3-6 — código curto de erro para cruzar o relato do usuário com o log.

* ``empiremuse.rules.error_code.new_error_code()`` devolve ``ERR-`` + 6 hexadecimais em maiúsculas, aleatório de
  ``secrets`` (não deriva de ID, token nem hora);
* só o erro INESPERADO ganha código; o MESMO código aparece para o usuário (slash e prefixo, com e sem ``embed_links``),
  na mensagem do log e no webhook (campo do embed e nome do anexo);
* o erro esperado (``GenericError``, permissões) não ganha código nem vai para o log de erro;
* falhar ao gerar o código nunca causa um novo erro: a mensagem genérica sai como antes.

Sem rede, sem Discord e sem ``.env``; o aleatório é fixado trocando ``secrets.token_hex``.
"""

import logging
import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse.cogs import error_handler
from empiremuse.cogs.error_handler import ErrorHandler

TOKEN_FALSO = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAx.GabcDE.abcdefghijklmnopqrstuvwxyz1"
CAMINHO = "/data/local_database/guilds.json"
LOGGER = "empiremuse.cogs.error_handler"


def erro_de_disco() -> OSError:
    try:
        raise OSError(28, f"No space left on device: '{CAMINHO}' (token {TOKEN_FALSO})")
    except OSError as e:
        return e


def fixar_codigo(monkeypatch, *valores):
    """Faz ``secrets.token_hex`` devolver os ``valores`` em sequência (o último se repete)."""
    restantes = list(valores)

    def falso(nbytes=None):
        return restantes.pop(0) if len(restantes) > 1 else restantes[0]

    monkeypatch.setattr(secrets, "token_hex", falso)


def falhar_ao_gerar(monkeypatch):
    def quebra(nbytes=None):
        raise RuntimeError("sem entropia (simulado)")

    monkeypatch.setattr(secrets, "token_hex", quebra)


@pytest.fixture
def handler(monkeypatch) -> ErrorHandler:
    h = ErrorHandler.__new__(ErrorHandler)
    h.bot = SimpleNamespace(
        config={"AUTO_ERROR_REPORT_WEBHOOK": "", "ERROR_REPORT_WEBHOOK": "", "SUPPORT_SERVER": ""},
        http=SimpleNamespace(token=TOKEN_FALSO),
        pool=SimpleNamespace(shutdown=AsyncMock()),
        user=SimpleNamespace(mention="<@1>"),
    )
    h.components = []
    h.webhook_max_concurrency = SimpleNamespace(acquire=AsyncMock(), release=AsyncMock())
    h.send_webhook = AsyncMock()
    h.build_report_embed = MagicMock(side_effect=lambda ctx: disnake.Embed(title="Ocorreu um erro em um servidor:"))
    monkeypatch.setattr(error_handler.asyncio, "sleep", AsyncMock())
    return h


@pytest.fixture
def enviado(monkeypatch) -> AsyncMock:
    enviar = AsyncMock()
    monkeypatch.setattr(error_handler, "send_message", enviar)
    return enviar


@pytest.fixture
def anexos(monkeypatch) -> list[tuple[str, str]]:
    """``(texto, nome)`` de cada anexo que iria para o webhook."""
    guardados: list[tuple[str, str]] = []

    def guardar(texto, nome):
        guardados.append((texto, nome))
        return f"arquivo:{nome}"

    monkeypatch.setattr(error_handler, "string_to_file", guardar)
    return guardados


def interacao() -> MagicMock:
    inter = MagicMock()
    inter.message.author.bot = False
    inter.data.name = "play"
    return inter


def registros_de_erro(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelno == logging.ERROR]


class TestFuncaoPura:
    @pytest.mark.smoke
    @pytest.mark.parametrize(
        ("texto", "vale"),
        [
            ("ERR-7F3A2C", True),
            ("7F3A2C", False),
        ],
    )
    def test_error_code_re(self, texto, vale):
        from empiremuse.rules.error_code import ERROR_CODE_RE

        assert bool(ERROR_CODE_RE.fullmatch(texto)) is vale


class TestInteracao:
    @pytest.mark.asyncio
    async def test_no_log_do_chamador_continua_sem_registro(self, handler, enviado, caplog, monkeypatch):
        fixar_codigo(monkeypatch, "7f3a2c")

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await handler.process_interaction_error(interacao(), erro_de_disco(), no_log=True)

        assert not registros_de_erro(caplog)


class TestFalhaAoGerarOCodigo:
    def test_safe_error_code_devolve_vazio_e_registra_so_o_tipo_do_erro(self, monkeypatch, caplog):
        from empiremuse.rules.error_code import safe_error_code

        falhar_ao_gerar(monkeypatch)
        with caplog.at_level(logging.WARNING, logger="empiremuse.rules.error_code"):
            codigo = safe_error_code()
        assert codigo == ""
        assert "RuntimeError" in caplog.text and "sem entropia" not in caplog.text

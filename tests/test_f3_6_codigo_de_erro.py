"""F3-6 — código curto de erro para cruzar o relato do usuário com o log (desenho em .local/F3-erro-codigo-plano.md).

Escrito pelo Backend por exceção do MAESTRO (o QA estava sem sessão); o QA revisa e faz a mutação depois.

* ``empiremuse.rules.error_code.new_error_code()`` devolve ``ERR-`` + 6 hexadecimais em maiúsculas, aleatório de
  ``secrets`` (não deriva de ID, token nem hora);
* só o erro INESPERADO ganha código; o MESMO código aparece para o usuário (slash e prefixo, com e sem ``embed_links``),
  na mensagem do log e no webhook (campo do embed e nome do anexo);
* o erro esperado (``GenericError``, permissões) não ganha código nem vai para o log de erro;
* falhar ao gerar o código nunca causa um novo erro: a mensagem genérica sai como antes.

Sem rede, sem Discord e sem ``.env``; o aleatório é fixado trocando ``secrets.token_hex``.
"""

import logging
import random
import re
import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest
from disnake.ext import commands

from empiremuse.cogs import error_handler
from empiremuse.cogs.error_handler import ErrorHandler
from empiremuse.utils.music.errors import GenericError

TOKEN_FALSO = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAx.GabcDE.abcdefghijklmnopqrstuvwxyz1"
CAMINHO = "/data/local_database/guilds.json"
LOGGER = "empiremuse.cogs.error_handler"
FORMATO = re.compile(r"ERR-[0-9A-F]{6}")


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


class Contexto:
    def __init__(self, embed_links: bool):
        self.bot = None
        self.author = SimpleNamespace(bot=False, id=7, mention="<@7>")
        self.prefix = "!"
        self.cog = None
        self.command = SimpleNamespace(name="play", usage=None, full_parent_name="")
        self.channel = MagicMock()
        self.channel.permissions_for.return_value.embed_links = embed_links
        self.guild = SimpleNamespace(me=object())
        self.message = SimpleNamespace(content="!play x", delete=AsyncMock())
        self.send = AsyncMock()


def texto_da_interacao(enviar: AsyncMock) -> str:
    kwargs = enviar.await_args.kwargs
    partes = [e.description or "" for e in kwargs.get("embeds", [])]
    if "embed" in kwargs:
        partes.append(kwargs["embed"].description or "")
    partes.append(kwargs.get("text", "") or "")
    return "\n".join(partes)


def texto_do_prefixo(ctx: Contexto) -> str:
    kwargs = ctx.send.await_args.kwargs
    partes = [kwargs.get("content", "") or ""]
    if "embed" in kwargs:
        partes.append(kwargs["embed"].description or "")
    return "\n".join(partes)


def valores_dos_campos(embed: disnake.Embed) -> str:
    return "\n".join(f"{campo.name}: {campo.value}" for campo in embed.fields)


def registros_de_erro(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelno == logging.ERROR]


class TestFuncaoPura:
    def test_formato(self):
        from empiremuse.rules.error_code import new_error_code

        for _ in range(50):
            assert FORMATO.fullmatch(new_error_code())

    def test_usa_secrets_e_coloca_em_maiusculas(self, monkeypatch):
        from empiremuse.rules.error_code import new_error_code

        chamadas = []

        def falso(nbytes=None):
            chamadas.append(nbytes)
            return "7f3a2c"

        monkeypatch.setattr(secrets, "token_hex", falso)
        assert new_error_code() == "ERR-7F3A2C" and chamadas == [3]

    def test_nao_usa_random(self, monkeypatch):
        from empiremuse.rules.error_code import new_error_code

        def proibido(*args, **kwargs):
            raise AssertionError("random não serve para código de erro")

        for nome in ("random", "randint", "choice", "getrandbits", "randrange"):
            monkeypatch.setattr(random, nome, proibido)
        assert FORMATO.fullmatch(new_error_code())

    @pytest.mark.parametrize(
        ("texto", "vale"),
        [
            ("ERR-7F3A2C", True),
            ("ERR-000000", True),
            ("ERR-7f3a2c", False),
            ("ERR-7F3A2", False),
            ("ERR-7F3A2CC", False),
            ("ERR-7F3A2G", False),
            ("err-7F3A2C", False),
            ("7F3A2C", False),
        ],
    )
    def test_error_code_re(self, texto, vale):
        from empiremuse.rules.error_code import ERROR_CODE_RE

        assert bool(ERROR_CODE_RE.fullmatch(texto)) is vale


class TestInteracao:
    @pytest.mark.asyncio
    async def test_o_usuario_ve_o_codigo_e_nada_do_detalhe_interno(self, handler, enviado, monkeypatch):
        fixar_codigo(monkeypatch, "7f3a2c")

        await handler.process_interaction_error(interacao(), erro_de_disco())

        texto = texto_da_interacao(enviado)
        assert "ERR-7F3A2C" in texto and "Código do erro" in texto
        assert "Ocorreu um erro" in texto
        for proibido in ("OSError", "No space left", CAMINHO, "Traceback", TOKEN_FALSO):
            assert proibido not in texto

    @pytest.mark.asyncio
    async def test_o_mesmo_codigo_vai_para_o_log(self, handler, enviado, caplog, monkeypatch):
        fixar_codigo(monkeypatch, "7f3a2c")

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await handler.process_interaction_error(interacao(), erro_de_disco())

        registros = registros_de_erro(caplog)
        assert registros and "ERR-7F3A2C" in registros[0]
        assert TOKEN_FALSO not in registros[0]
        tipo = [r for r in caplog.records if r.name == LOGGER][0].exc_info[0]
        assert tipo is OSError, "o log segue levando o traceback completo"

    @pytest.mark.asyncio
    async def test_o_mesmo_codigo_vai_para_o_webhook_no_embed_e_no_nome_do_anexo(
        self, handler, enviado, anexos, monkeypatch
    ):
        handler.bot.config["AUTO_ERROR_REPORT_WEBHOOK"] = "https://discord.com/api/webhooks/1/segredo"
        fixar_codigo(monkeypatch, "7f3a2c")

        await handler.process_interaction_error(interacao(), erro_de_disco())

        handler.send_webhook.assert_awaited_once()
        embed = handler.send_webhook.await_args.kwargs["embed"]
        assert "ERR-7F3A2C" in valores_dos_campos(embed)
        assert [nome for _, nome in anexos if "ERR-7F3A2C" in nome], "o código precisa estar no nome do anexo"
        assert all(TOKEN_FALSO not in texto for texto, _ in anexos)
        assert "ERR-7F3A2C" in texto_da_interacao(enviado)

    @pytest.mark.asyncio
    async def test_sem_webhook_o_codigo_ainda_aparece_para_o_usuario_e_no_log(
        self, handler, enviado, caplog, monkeypatch
    ):
        fixar_codigo(monkeypatch, "7f3a2c")

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await handler.process_interaction_error(interacao(), erro_de_disco())

        handler.send_webhook.assert_not_awaited()
        assert "ERR-7F3A2C" in texto_da_interacao(enviado) and "ERR-7F3A2C" in registros_de_erro(caplog)[0]

    @pytest.mark.asyncio
    async def test_dois_erros_seguidos_recebem_codigos_diferentes_cada_um_no_seu_log(
        self, handler, enviado, caplog, monkeypatch
    ):
        fixar_codigo(monkeypatch, "aaaaaa", "bbbbbb")

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await handler.process_interaction_error(interacao(), erro_de_disco())
            primeiro = texto_da_interacao(enviado)
            await handler.process_interaction_error(interacao(), KeyError("x"))
            segundo = texto_da_interacao(enviado)

        assert "ERR-AAAAAA" in primeiro and "ERR-BBBBBB" in segundo
        registros = registros_de_erro(caplog)
        assert "ERR-AAAAAA" in registros[0] and "ERR-BBBBBB" in registros[1]

    @pytest.mark.asyncio
    async def test_erro_esperado_nao_ganha_codigo_nem_log_de_erro(self, handler, enviado, caplog):
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await handler.process_interaction_error(interacao(), GenericError("**Você não pode fazer isso.**"))
            await handler.process_interaction_error(interacao(), commands.NotOwner())

        assert "ERR-" not in texto_da_interacao(enviado)
        assert not registros_de_erro(caplog)

    @pytest.mark.asyncio
    async def test_no_log_do_chamador_continua_sem_registro(self, handler, enviado, caplog, monkeypatch):
        fixar_codigo(monkeypatch, "7f3a2c")

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await handler.process_interaction_error(interacao(), erro_de_disco(), no_log=True)

        assert not registros_de_erro(caplog)

    @pytest.mark.asyncio
    async def test_falhar_ao_gerar_o_codigo_nao_causa_novo_erro(self, handler, enviado, anexos, caplog, monkeypatch):
        handler.bot.config["AUTO_ERROR_REPORT_WEBHOOK"] = "https://discord.com/api/webhooks/1/segredo"
        falhar_ao_gerar(monkeypatch)

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await handler.process_interaction_error(interacao(), erro_de_disco())

        texto = texto_da_interacao(enviado)
        assert "Ocorreu um erro" in texto and "ERR-" not in texto
        assert registros_de_erro(caplog), "o erro original continua registrado"
        handler.send_webhook.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_o_codigo_nao_carrega_pedaco_do_token_do_bot(self, handler, enviado):
        await handler.process_interaction_error(interacao(), erro_de_disco())

        codigo = FORMATO.search(texto_da_interacao(enviado)).group(0)
        assert TOKEN_FALSO[:6] not in codigo


class TestPrefixo:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("embed_links", [True, False], ids=["com_embed", "sem_embed"])
    async def test_o_usuario_ve_o_codigo_nos_dois_formatos(self, handler, embed_links, monkeypatch):
        fixar_codigo(monkeypatch, "7f3a2c")
        ctx = Contexto(embed_links)

        await handler.on_legacy_command_error(ctx, erro_de_disco())

        texto = texto_do_prefixo(ctx)
        assert "ERR-7F3A2C" in texto and "Código do erro" in texto
        for proibido in ("OSError", CAMINHO, "Traceback", TOKEN_FALSO):
            assert proibido not in texto

    @pytest.mark.asyncio
    async def test_o_mesmo_codigo_vai_para_o_log_e_para_o_webhook(self, handler, anexos, caplog, monkeypatch):
        handler.bot.config["AUTO_ERROR_REPORT_WEBHOOK"] = "https://discord.com/api/webhooks/1/segredo"
        fixar_codigo(monkeypatch, "7f3a2c")

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await handler.on_legacy_command_error(Contexto(True), erro_de_disco())

        assert "ERR-7F3A2C" in registros_de_erro(caplog)[0]
        embed = handler.send_webhook.await_args.kwargs["embed"]
        assert "ERR-7F3A2C" in valores_dos_campos(embed)
        assert [nome for _, nome in anexos if "ERR-7F3A2C" in nome]

    @pytest.mark.asyncio
    async def test_erro_esperado_nao_ganha_codigo(self, handler, caplog):
        ctx = Contexto(True)

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await handler.on_legacy_command_error(ctx, GenericError("**Sem permissão aqui.**"))

        assert "ERR-" not in texto_do_prefixo(ctx) and not registros_de_erro(caplog)

    @pytest.mark.asyncio
    async def test_falhar_ao_gerar_o_codigo_nao_causa_novo_erro(self, handler, caplog, monkeypatch):
        falhar_ao_gerar(monkeypatch)
        ctx = Contexto(True)

        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await handler.on_legacy_command_error(ctx, erro_de_disco())

        assert "Ocorreu um erro" in texto_do_prefixo(ctx) and "ERR-" not in texto_do_prefixo(ctx)
        assert registros_de_erro(caplog)

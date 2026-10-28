"""Item 7, P4 — B23 (K13, V-P2-2, LGPD): o ``COMMAND_LOG`` leva IDs e um resumo por tipo, nunca nomes, conteúdo nem URL de anexo.

Os dois registros (slash e prefixo) nascem em fechamentos dentro de ``BotPool.setup``; o teste roda o ``setup`` real com ``BotCore`` dublado,
captura o que o fechamento registra no logger ``empiremuse.commands`` e lê a mensagem já formatada. Dono (``is_owner``) continua sem registro.
"""

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse.utils import client
from empiremuse.utils.client import BotPool
from tests.logs.apoio_erros import (
    CANAL,
    SERVIDOR,
    USUARIO,
    anexo,
    contexto_de_prefixo,
    interacao,
    membro,
    sem_nomes,
    servidor,
)
from tests.support.laco_do_pool import encerrar_laco

pytestmark = pytest.mark.critical

TOKEN_FALSO = "".join(["MTIzNDU2Nzg5MDEyMzQ1Njc4", "OTAx.Gabcde.abcdefghijklmnopqrstuvwxyz1"])
LOGGER = "empiremuse.commands"
TEXTO_LIVRE = "".join(["busca ", "livre privada"])


class Captura(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.linhas: list[str] = []

    def emit(self, registro: logging.LogRecord) -> None:
        self.linhas.append(registro.getMessage())


@pytest.fixture
def fechamentos(monkeypatch, tmp_path):
    """Roda ``BotPool.setup`` com ``COMMAND_LOG=true`` e devolve ``{"check": …, "on_command": …}`` capturados do bot dublado."""
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(home))
    monkeypatch.chdir(cwd)
    for chave, valor in {
        "RUN_LOCAL_LAVALINK": "false",
        "RUN_RPC_SERVER": "false",
        "AUTO_DOWNLOAD_LAVALINK_SERVERLIST": "false",
        "TOKEN": TOKEN_FALSO,
        "COMMAND_LOG": "true",
    }.items():
        monkeypatch.setenv(chave, valor)
    pool = BotPool()
    capturados: dict[str, object] = {}

    def bot_falso(**kwargs):
        bot = MagicMock(identifier=kwargs["identifier"])
        bot.loop.create_task.side_effect = lambda corotina: corotina.close()
        bot.is_owner = AsyncMock(return_value=False)

        def guardar_check(**_):
            def decorador(funcao):
                capturados["check"] = funcao
                return funcao

            return decorador

        def guardar_listen(nome):
            def decorador(funcao):
                capturados[nome] = funcao
                return funcao

            return decorador

        bot.application_command_check = guardar_check
        bot.listen = guardar_listen
        return bot

    monkeypatch.setattr(client, "BotCore", bot_falso)
    monkeypatch.setattr(client, "check_pool_bots", AsyncMock())
    for nome in ("run_bots", "setup_pool_extras", "cache_updater", "connect_rpc_ws"):
        setattr(pool, nome, AsyncMock())
    pool.node_check = MagicMock()
    pool.start_lavalink = AsyncMock()
    pool.setup()
    captura = Captura()
    logger = logging.getLogger(LOGGER)
    logger.addHandler(captura)
    nivel = logger.level
    logger.setLevel(logging.DEBUG)
    capturados["linhas"] = captura.linhas
    yield capturados
    logger.removeHandler(captura)
    logger.setLevel(nivel)
    encerrar_laco(pool.loop)
    asyncio.set_event_loop(None)


def inter_com_opcoes():
    inter = interacao({"busca": TEXTO_LIVRE, "alvo": membro(31), "arquivo": anexo("image/png", 4321), "volume": 70})
    inter.guild = servidor()
    inter.guild.__class__ = (
        disnake.Guild
    )  # isinstance(inter.guild, disnake.Guild): cai no caminho de servidor com o bot
    return inter


class TestSlash:
    @pytest.mark.asyncio
    async def test_the_slash_record_has_ids_and_summaries_and_no_name_content_or_cdn_url(self, fechamentos):
        await fechamentos["check"](inter_com_opcoes())

        (linha,) = fechamentos["linhas"]
        assert str(USUARIO) in linha and str(SERVIDOR) in linha and "play" in linha
        assert sem_nomes(linha) == [], linha
        assert TEXTO_LIVRE not in linha

    @pytest.mark.asyncio
    async def test_the_options_are_summarized_by_type(self, fechamentos):
        await fechamentos["check"](inter_com_opcoes())

        (linha,) = fechamentos["linhas"]
        assert f"str(len={len(TEXTO_LIVRE)})" in linha
        assert "Member(id=31)" in linha and "Attachment(tipo=image/png, tamanho=4321)" in linha and "70" in linha

    @pytest.mark.asyncio
    async def test_a_secret_named_option_is_masked(self, fechamentos):
        inter = inter_com_opcoes()
        inter.filled_options = {"token": "valor-privado-N4"}

        await fechamentos["check"](inter)

        (linha,) = fechamentos["linhas"]
        assert "valor-privado-N4" not in linha and "***" in linha

    @pytest.mark.asyncio
    async def test_the_owner_is_still_not_logged(self, fechamentos):
        inter = inter_com_opcoes()
        inter.bot.is_owner = AsyncMock(return_value=True)

        await fechamentos["check"](inter)

        assert fechamentos["linhas"] == []


class TestPrefixo:
    @pytest.mark.asyncio
    async def test_the_prefix_record_has_the_command_and_only_the_length_of_the_rest(self, fechamentos):
        ctx = contexto_de_prefixo("play", "musica secreta")

        await fechamentos["on_command"](ctx)

        (linha,) = fechamentos["linhas"]
        assert str(USUARIO) in linha and str(SERVIDOR) in linha and "play" in linha
        assert "str(len=" in linha
        assert ctx.message.content not in linha and "musica secreta" not in linha
        assert sem_nomes(linha) == [], linha

    @pytest.mark.asyncio
    async def test_the_prefix_record_never_has_the_names(self, fechamentos):
        await fechamentos["on_command"](contexto_de_prefixo())

        assert sem_nomes(" ".join(fechamentos["linhas"])) == []

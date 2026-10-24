"""F3-6 — S-14: o texto de uma exceção não chega ao usuário, ao dono nem à página web (S-14).

Regra: onde o texto da exceção ia para a tela, entra uma mensagem genérica em pt-BR; o detalhe (com traceback) vai para o
``logger``; em erro inesperado a mensagem e o log levam o mesmo código curto (``ERR-…``). Decisões do MAESTRO:

* Lavalink: ``event.message`` (e ``exception.message`` do autoplay) CONTINUA visível, truncado e sem bloco de código; a
  ``cause`` e o ``repr`` saem da mensagem e vão para o log;
* ``start_bot``/``failed_bots``: a página pública mostra um texto genérico por bot; a instrução do PrivilegedIntentsRequired
  (e a do token inválido) continua;
* ``ll_yt_oauth``/``owner_panel``: mesmo para o dono, genérico + log; o texto do HTTP do Lavalink não vai para a mensagem;
* ``song_requests``: nunca mais aparece "None" num bloco de código.

Sem rede, sem Discord e sem ``.env``; o aleatório do código é fixado trocando ``secrets.token_hex``.
"""

import asyncio
import logging
import re
import secrets
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse.utils.music.errors import GenericError
from tests.support.api_publica import fonte_da_familia

pytestmark = pytest.mark.regression

SEGREDO = "detalhe-interno /srv/empiremuse/segredo.json"
TOKEN_FALSO = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAx.GabcDE.abcdefghijklmnopqrstuvwxyz1"
CODIGO = "ERR-7F3A2C"


def fixar_codigo(monkeypatch, valor="7f3a2c"):
    monkeypatch.setattr(secrets, "token_hex", lambda nbytes=None: valor)


def sem_vazamento(texto: str, *extras: str) -> None:
    for proibido in (SEGREDO, "segredo.json", "RuntimeError", "Traceback", "```py", "```java", "repr(", *extras):
        assert proibido not in texto, f"vazou para a tela: {proibido!r} em {texto!r}"


def registros(caplog, logger: str, nivel=logging.WARNING) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == logger and r.levelno >= nivel]


# ============================================================================ helpers puros


class TestHelpers:
    def test_log_unexpected_error_sem_codigo_ainda_registra(self, monkeypatch, caplog):
        from empiremuse.utils.music.errors import log_unexpected_error

        def quebra(nbytes=None):
            raise RuntimeError("sem entropia (simulado)")

        monkeypatch.setattr(secrets, "token_hex", quebra)
        log = logging.getLogger("teste.s14")
        with caplog.at_level(logging.ERROR, logger="teste.s14"):
            codigo = log_unexpected_error(log, ValueError("x"), "origem")
        assert codigo == "" and registros(caplog, "teste.s14", logging.ERROR)


# ============================================================================ ll_yt_oauth (dono)


# ============================================================================ Music.song_requests (usuário e webhook)


def montar_pedido(monkeypatch, erro: BaseException, *, webhook=False):
    from empiremuse.cogs import music

    monkeypatch.setattr(music.asyncio, "sleep", AsyncMock())
    envios = []
    canal = SimpleNamespace(
        id=55,
        name="pedidos",
        send=AsyncMock(side_effect=lambda *a, **k: envios.append((a, k))),
        permissions_for=lambda me: SimpleNamespace(send_messages=True),
    )
    guilda = SimpleNamespace(id=9, name="Servidor", me=SimpleNamespace(voice=None), icon=None)
    autor = SimpleNamespace(
        bot=False,
        id=1,
        mention="<@1>",
        voice=None,
        display_avatar=SimpleNamespace(
            with_static_format=lambda formato: SimpleNamespace(url="https://exemplo.invalid/a.png")
        ),
    )
    mensagem = SimpleNamespace(
        author=autor, mentions=[], guild=guilda, channel=canal, content="tocar algo", attachments=[], type=None
    )
    mensagem.is_system = lambda: False
    webhook_cog = SimpleNamespace(
        webhook_max_concurrency=SimpleNamespace(acquire=AsyncMock(), release=AsyncMock()),
        send_webhook=AsyncMock(),
        mask_token=lambda texto: texto.replace(TOKEN_FALSO, "mytoken"),
    )
    bot = SimpleNamespace(
        intents=SimpleNamespace(message_content=True),
        get_data=AsyncMock(return_value={"player_controller": {"channel": "55"}}),
        music=SimpleNamespace(players={}),
        get_channel=lambda cid: canal,
        get_color=lambda *a: 0,
        http=SimpleNamespace(token=TOKEN_FALSO),
        config={"AUTO_ERROR_REPORT_WEBHOOK": "https://discord.com/api/webhooks/1/segredo" if webhook else ""},
        get_cog=lambda nome: webhook_cog,
    )
    self_ = SimpleNamespace(
        bot=bot,
        song_request_concurrency=SimpleNamespace(acquire=AsyncMock(), release=AsyncMock()),
        delete_message=AsyncMock(),
        parse_song_request=AsyncMock(side_effect=erro),
    )
    ctx = SimpleNamespace(command=None, guild=guilda, channel=canal, author=autor)
    return music.Music, self_, ctx, mensagem, envios, webhook_cog


class TestSongRequests:
    @pytest.mark.asyncio
    async def test_erro_inesperado_mostra_mensagem_generica_com_codigo_e_nunca_none(self, monkeypatch, caplog):
        fixar_codigo(monkeypatch)
        classe, self_, ctx, mensagem, envios, _ = montar_pedido(monkeypatch, RuntimeError(SEGREDO))

        with caplog.at_level(logging.ERROR, logger="empiremuse.cogs.music"):
            await classe.song_requests(self_, ctx, mensagem)

        [(args, _)] = envios
        texto = args[0]
        sem_vazamento(texto, "None")
        assert "ocorreu um erro ao tentar obter resultados para sua busca" in texto and CODIGO in texto
        assert texto.startswith("<@1>")
        [registro] = registros(caplog, "empiremuse.cogs.music", logging.ERROR)
        assert CODIGO in registro.getMessage() and registro.exc_info[0] is RuntimeError


# ============================================================================ owner_panel (dono)


# ============================================================================ BotPool.start_bot / failed_bots (página pública)


class TestStartBot:
    @staticmethod
    def pool():
        return SimpleNamespace(
            config={"KILL_ON_429": False}, killing_state=False, failed_bots={}, bots=[], shutdown=AsyncMock()
        )

    @staticmethod
    def bot(erro):
        return SimpleNamespace(
            identifier="bot-1", http=SimpleNamespace(token=TOKEN_FALSO), start=AsyncMock(side_effect=erro)
        )

    @pytest.mark.asyncio
    async def test_a_instrucao_do_privileged_intents_continua(self):
        from empiremuse.utils.client import BotPool

        pool = self.pool()
        await BotPool.start_bot(pool, self.bot(disnake.PrivilegedIntentsRequired(None)))

        texto = pool.failed_bots["bot-1"]
        assert "Privileged" in texto and "discord.com/developers/applications" in texto
        assert "ERR-" not in texto


# ============================================================================ LavalinkPlayer


def jogador(monkeypatch, **extra):
    """``LavalinkPlayer`` sem o ``__init__`` pesado; as propriedades sem setter viram atributos da subclasse de teste."""
    from empiremuse.utils.music import models

    class JogadorDeTeste(models.LavalinkPlayer):
        is_connected = True
        last_channel = SimpleNamespace(id=7)

    p = JogadorDeTeste.__new__(JogadorDeTeste)
    canal = SimpleNamespace(send=AsyncMock(), permissions_for=lambda me: SimpleNamespace(send_messages=True), id=5)
    p.bot = SimpleNamespace(
        wait_until_ready=AsyncMock(),
        get_color=lambda *a: 0,
        music=SimpleNamespace(players={}),
        dispatch=lambda *a, **k: None,
        latency=0.05,
        get_cog=lambda nome: None,
        loop=MagicMock(),
        config={"IDLE_TIMEOUT": 60},
    )
    p.guild = SimpleNamespace(id=9, name="Servidor", me=SimpleNamespace(voice=None), icon=None)
    p.guild_id = 9
    p.text_channel = canal
    p.node = SimpleNamespace(identifier="no-1", info={"sourceManagers": []}, is_available=True)
    p.locked = False
    p.is_closing = False
    p.update = False
    p.static = False
    p.keep_connected = False
    p.controller_mode = True
    p.queue = deque()
    p.failed_tracks = []
    p.current = None
    p.last_track = None
    p.command_log_list = []
    p._new_node_task = None
    p.set_command_log = MagicMock()
    p.report_error = AsyncMock()
    p.process_next = AsyncMock()
    for nome, valor in extra.items():
        setattr(p, nome, valor)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    return p


def faixa(**extra):
    base = dict(
        title="Faixa X",
        uri="https://exemplo.invalid/x",
        search_uri="",
        id="abc",
        track_loops=0,
        source_name="soundcloud",
        autoplay=False,
        info={"sourceName": "soundcloud"},
    )
    base.update(extra)
    return SimpleNamespace(**base)


class TestOutrasFalhasDoPlayer:
    @pytest.mark.asyncio
    async def test_resolve_track_informa_o_dono_sem_repr(self, monkeypatch, caplog):
        fixar_codigo(monkeypatch)
        p = jogador(monkeypatch)
        parcial = faixa(info={}, duration=0, id="")

        with caplog.at_level(logging.ERROR, logger="empiremuse.utils.music.models"):
            await p.resolve_track(parcial)

        embed = p.report_error.await_args.args[0]
        sem_vazamento(embed.description, "KeyError")
        assert CODIGO in embed.description
        assert registros(caplog, "empiremuse.utils.music.models", logging.ERROR)


# ============================================================================ complemento do AppSec (F-3, F-4, I-11, Info)
#
# Decisões do MAESTRO depois da auditoria complementar:
# * F-3: o ``error_description`` do Spotify não chega mais ao usuário (revoga o "motivo informado" do KI-15); fica no log;
# * F-4: a mensagem do nó Lavalink aparece dentro de um code span (a crase já é trocada), nos dois usos;
# * I-11: a troca do refreshToken por ``***`` no corpo da resposta vem ANTES do corte em 500 caracteres.


class SessaoDeToken:
    """Sessão do aiohttp falsa: o ``POST`` do token devolve sempre o JSON informado."""

    def __init__(self, corpo):
        self.corpo = corpo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, url, headers=None, data=None, **kwargs):
        return self

    async def json(self, *args, **kwargs):
        return dict(self.corpo)


class TestSpotifyAutenticacao:
    MOTIVO = "motivo-externo-do-spotify https://evil.example/login <@123456789012345678>"

    def cliente(self, monkeypatch, tmp_path, corpo):
        from empiremuse.utils.music.audio_sources import spotify

        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(spotify, "ClientSession", lambda *a, **k: SessaoDeToken(corpo))
        return spotify.SpotifyClient(client_id="id-de-teste", client_secret="segredo-de-teste")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "corpo",
        [{"error": "invalid_client", "error_description": "Invalid client"}, {"error": "invalid_client"}],
        ids=["com-descricao", "so-error"],
    )
    async def test_a_mensagem_e_fixa_qualquer_que_seja_o_motivo(self, monkeypatch, tmp_path, corpo):
        textos = set()
        for variante in (corpo, {"error": "outro", "error_description": self.MOTIVO}):
            cliente = self.cliente(monkeypatch, tmp_path, variante)
            with pytest.raises(GenericError) as erro:
                await cliente.get_access_token()
            textos.add(erro.value.text)
            assert cliente.token_refresh is False
        assert len(textos) == 1, textos


class TestLavalinkTextEmCodeSpan:
    def test_o_autoplay_usa_o_mesmo_helper_sem_envolver_em_crases(self):
        """``get_autoqueue_tracks`` é longo demais para dirigir com dublê: a guarda lê o código dos dois usos."""
        fonte = fonte_da_familia("models")
        usos = [linha.strip() for linha in fonte.splitlines() if "lavalink_text(" in linha and "def " not in linha]
        assert len(usos) == 2, usos
        assert any("exception.message" in uso for uso in usos) and any("event.message" in uso for uso in usos)
        assert not [uso for uso in usos if "`{lavalink_text" in uso or "{lavalink_text(" not in uso], usos
        assert not re.search(r"\{(?:exception|event)\.message[^}]*\}", fonte), "mensagem crua do nó numa f-string"


class TestCanalDeVozNoRelatorio:
    """``build_report_embed``: o campo "Canal de voz (bot)" descreve o canal do BOT, em bloco de código fechado e com escape."""

    NOME_DO_BOT = "*negrito* __x__ [link](https://evil.example)"

    @staticmethod
    def canal(id_, nome, limite=0, membros=0):
        return SimpleNamespace(id=id_, name=nome, user_limit=limite, voice_states={n: n for n in range(membros)})

    def embed(self, canal_do_usuario, canal_do_bot, *, usuario_em_voz=True):
        from empiremuse.cogs.error_handler import ErrorHandler

        handler = ErrorHandler.__new__(ErrorHandler)
        handler.bot = SimpleNamespace(get_color=lambda *a: 0, intents=SimpleNamespace(message_content=False))
        guild = SimpleNamespace(
            id=9, name="Servidor", me=SimpleNamespace(voice=SimpleNamespace(channel=canal_do_bot)), icon=None
        )
        autor = SimpleNamespace(
            id=5,
            bot=False,
            voice=SimpleNamespace(channel=canal_do_usuario) if usuario_em_voz else None,
            display_avatar=SimpleNamespace(
                with_static_format=lambda formato: SimpleNamespace(url="https://exemplo.invalid/a.png")
            ),
        )
        ctx = SimpleNamespace(
            bot=handler.bot,
            guild=guild,
            channel=SimpleNamespace(id=3, name="texto"),
            author=autor,
            data=SimpleNamespace(name="play"),
            filled_options={},
        )
        return handler.build_report_embed(ctx)

    @staticmethod
    def campo(embed, nome):
        return [c.value for c in embed.fields if c.name == nome]

    def test_guarda_o_campo_do_usuario_continua_igual(self):
        usuario = self.canal(1, "canal-do-usuario", limite=3, membros=1)

        [valor] = self.campo(self.embed(usuario, self.canal(2, "canal-do-bot")), "Canal de voz (user):")

        assert valor == "```\ncanal-do-usuario (1/3)\nID: 1```"


# ============================================================================ lacunas apontadas pela mutação


class TestLacunasDaMutacao:
    @pytest.mark.asyncio
    async def test_wait_for_new_node_erro_de_pool_tem_o_texto_proprio(self, monkeypatch):
        from empiremuse.utils.music import models
        from empiremuse.utils.music.errors import PoolException

        no = SimpleNamespace(identifier="no-2", players={9: object()})
        p = jogador(monkeypatch)
        p.node = SimpleNamespace(identifier="no-1", players={9: object()}, is_available=False)
        p._voice_state = None
        p.change_node = AsyncMock()
        p.destroy = AsyncMock()
        p.bot.music = SimpleNamespace(get_best_node=lambda ignore_node=None: no, players={})
        monkeypatch.setattr(
            models.player_voice, "can_connect", MagicMock(side_effect=PoolException("nenhum bot livre"))
        )

        await p._wait_for_new_node()

        textos = [c.args[0] if c.args else c.kwargs.get("text", "") for c in p.set_command_log.call_args_list]
        assert any("nenhum bot livre" in t and "ERR-" not in t for t in textos)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("gera", [True, False], ids=["com_codigo", "sem_codigo"])
    async def test_song_request_webhook_nome_do_anexo_e_token_mascarado(self, monkeypatch, gera):
        if gera:
            fixar_codigo(monkeypatch)
        else:

            def quebra(nbytes=None):
                raise RuntimeError("sem entropia (simulado)")

            monkeypatch.setattr(secrets, "token_hex", quebra)
        classe, self_, ctx, mensagem, envios, cog = montar_pedido(
            monkeypatch, RuntimeError(f"falha com {TOKEN_FALSO}"), webhook=True
        )
        anexos = []
        monkeypatch.setattr(
            "empiremuse.music_cog.song_requests.string_to_file", lambda texto, nome: anexos.append((texto, nome))
        )

        await classe.song_requests(self_, ctx, mensagem)

        [(texto, nome)] = anexos
        assert nome == (f"error_traceback_songrequest_{CODIGO}.txt" if gera else "error_traceback_songrequest.txt")
        assert TOKEN_FALSO not in texto and "mytoken" in texto

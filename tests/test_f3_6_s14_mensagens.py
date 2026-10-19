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
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

import empiremuse.wavelink as wavelink
from empiremuse.utils.music.errors import GenericError

SEGREDO = "detalhe-interno /srv/empiremuse/segredo.json"
CAUSA = "java.lang.IllegalStateException: causa-interna-do-lavaplayer em /opt/lavalink/plugin.jar"
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
    @pytest.mark.parametrize(
        ("bruto", "esperado"),
        [
            ("This video is unavailable", "This video is unavailable"),
            ("com `crase` e ```bloco```", "com 'crase' e '''bloco'''"),
            ("linha 1\nlinha 2\r\n   linha 3", "linha 1 linha 2 linha 3"),
            ("a\x00b\u202ec\u200bd", "abcd"),
            (None, ""),
            (123, "123"),
            ("  espaços nas pontas  ", "espaços nas pontas"),
        ],
        ids=repr,
    )
    def test_plain_snippet(self, bruto, esperado):
        from empiremuse.rules.text import plain_snippet

        assert plain_snippet(bruto, 200) == esperado

    def test_plain_snippet_trunca_com_reticencias(self):
        from empiremuse.rules.text import plain_snippet

        resultado = plain_snippet("x" * 500, 200)
        assert len(resultado) == 201 and resultado.endswith("…") and resultado[:200] == "x" * 200
        assert plain_snippet("x" * 200, 200) == "x" * 200

    def test_log_unexpected_error_devolve_o_codigo_e_registra_com_traceback(self, monkeypatch, caplog):
        from empiremuse.utils.music.errors import log_unexpected_error

        fixar_codigo(monkeypatch)
        log = logging.getLogger("teste.s14")
        try:
            raise RuntimeError(SEGREDO)
        except RuntimeError as erro:
            with caplog.at_level(logging.ERROR, logger="teste.s14"):
                codigo = log_unexpected_error(log, erro, "player do servidor 1")
        assert codigo == CODIGO
        [registro] = registros(caplog, "teste.s14", logging.ERROR)
        assert CODIGO in registro.getMessage() and "player do servidor 1" in registro.getMessage()
        assert registro.exc_info[0] is RuntimeError and SEGREDO in str(registro.exc_info[1])

    def test_log_unexpected_error_sem_codigo_ainda_registra(self, monkeypatch, caplog):
        from empiremuse.utils.music.errors import log_unexpected_error

        def quebra(nbytes=None):
            raise RuntimeError("sem entropia (simulado)")

        monkeypatch.setattr(secrets, "token_hex", quebra)
        log = logging.getLogger("teste.s14")
        with caplog.at_level(logging.ERROR, logger="teste.s14"):
            codigo = log_unexpected_error(log, ValueError("x"), "origem")
        assert codigo == "" and registros(caplog, "teste.s14", logging.ERROR)

    def test_code_suffix_e_error_code_text(self):
        from empiremuse.utils.music.errors import code_suffix, error_code_text

        assert CODIGO in code_suffix(CODIGO) and code_suffix("") == ""
        assert CODIGO in error_code_text(CODIGO) and error_code_text("") == ""


# ============================================================================ ll_yt_oauth (dono)


class FakeView:
    def __init__(self, bot=None, ctx=None):
        self.data = {"refresh_token": "refresh-falso", "access_token": "acesso-falso"}
        self.interaction = None
        self.exception_txt = ""

    async def wait(self):
        return None


class FakeAsk:
    """Confirmação aceita; a mensagem final do comando sai por ``edit_original_message`` da interação devolvida."""

    edicao = AsyncMock()

    def __init__(self, ctx=None):
        self.selected = True
        self.interaction_resp = SimpleNamespace(
            response=SimpleNamespace(defer=AsyncMock(), edit_message=AsyncMock()),
            edit_original_message=self.edicao,
        )

    async def wait(self):
        return None


class Resposta:
    def __init__(self, status=200, corpo=None, texto=""):
        self.status, self._corpo, self._texto = status, corpo, texto

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self._corpo

    async def text(self):
        return self._texto

    def raise_for_status(self):
        raise AssertionError("status inesperado")


def montar_oauth(monkeypatch, tmp_path, *, mongo=None, node=None, post=None):
    from empiremuse.cogs import ll_yt_oauth

    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    monkeypatch.setattr(ll_yt_oauth, "YtOauthView", FakeView)
    monkeypatch.setattr(ll_yt_oauth, "AskView", FakeAsk)
    monkeypatch.setattr(FakeAsk, "edicao", AsyncMock())
    sessao = SimpleNamespace(
        get=lambda *a, **k: Resposta(
            200, {"name": "Ana", "email": "ana@exemplo.invalid", "picture": "https://exemplo.invalid/a.png"}
        ),
        post=post or AsyncMock(),
    )
    bot = SimpleNamespace(
        session=sessao,
        pool=SimpleNamespace(mongo_database=mongo),
        music=SimpleNamespace(nodes={"LOCAL": node} if node else {}),
        get_color=lambda *a: 0,
    )
    mensagem = SimpleNamespace(edit=AsyncMock())
    ctx = SimpleNamespace(
        guild=SimpleNamespace(me=object()),
        author=SimpleNamespace(id=1),
        send=AsyncMock(return_value=mensagem),
        inter=None,
    )
    return ll_yt_oauth.YtOauthLL(bot), ctx, FakeAsk.edicao


def texto_final(edicao) -> str:
    return edicao.await_args_list[-1].kwargs["embed"].description


class TestOauthDoDono:
    @pytest.mark.asyncio
    async def test_falha_ao_salvar_no_mongo(self, monkeypatch, tmp_path, caplog):
        fixar_codigo(monkeypatch)
        mongo = SimpleNamespace(update_data=AsyncMock(side_effect=RuntimeError(SEGREDO)))
        cog, ctx, mensagem = montar_oauth(monkeypatch, tmp_path, mongo=mongo)

        with caplog.at_level(logging.WARNING, logger="empiremuse.cogs.ll_yt_oauth"):
            await cog.oauth_command(ctx)

        texto = texto_final(mensagem)
        sem_vazamento(texto)
        assert "MongoDB" in texto and CODIGO in texto
        [registro] = registros(caplog, "empiremuse.cogs.ll_yt_oauth")
        assert CODIGO in registro.getMessage() and registro.exc_info[0] is RuntimeError

    @pytest.mark.asyncio
    async def test_resposta_do_lavalink_local_nao_vai_para_a_mensagem(self, monkeypatch, tmp_path, caplog):
        (tmp_path / "application.yml").write_text(
            "plugins:\n  youtube:\n    oauth:\n      enabled: false\n", encoding="utf-8"
        )
        node = SimpleNamespace(
            info={"plugins": ["youtube-plugin"]},
            rest_uri="http://127.0.0.1:2333",
            _websocket=SimpleNamespace(headers={}),
        )
        post = AsyncMock(return_value=Resposta(500, texto="corpo-interno-do-lavalink /opt/lavalink"))
        cog, ctx, mensagem = montar_oauth(monkeypatch, tmp_path, node=node, post=post)

        with caplog.at_level(logging.WARNING, logger="empiremuse.cogs.ll_yt_oauth"):
            await cog.oauth_command(ctx)

        texto = texto_final(mensagem)
        assert "corpo-interno-do-lavalink" not in texto and "/opt/lavalink" not in texto
        assert "lavalink LOCAL" in texto
        log = "\n".join(r.getMessage() for r in registros(caplog, "empiremuse.cogs.ll_yt_oauth"))
        assert "corpo-interno-do-lavalink" in log, "o corpo da resposta vai para o log"

    @pytest.mark.asyncio
    async def test_falha_ao_salvar_no_application_yml(self, monkeypatch, tmp_path, caplog):
        fixar_codigo(monkeypatch)
        (tmp_path / "application.yml").write_text("plugins: [sem-fechar\n", encoding="utf-8")
        cog, ctx, mensagem = montar_oauth(monkeypatch, tmp_path)

        with caplog.at_level(logging.WARNING, logger="empiremuse.cogs.ll_yt_oauth"):
            await cog.oauth_command(ctx)

        texto = texto_final(mensagem)
        assert "application.yml" in texto and CODIGO in texto
        for proibido in ("ParserError", "ScannerError", "expected", "line 1", "Error("):
            assert proibido not in texto
        assert registros(caplog, "empiremuse.cogs.ll_yt_oauth")

    @pytest.mark.asyncio
    async def test_guarda_sucesso_sem_mongo_nem_yml_continua_igual(self, monkeypatch, tmp_path):
        cog, ctx, mensagem = montar_oauth(monkeypatch, tmp_path)

        await cog.oauth_command(ctx)

        texto = texto_final(mensagem)
        assert "refresh-falso" in texto and "Evite mostrar esse token publicamente!" in texto


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

    @pytest.mark.asyncio
    async def test_o_embed_do_webhook_e_generico_e_leva_o_mesmo_codigo(self, monkeypatch):
        fixar_codigo(monkeypatch)
        classe, self_, ctx, mensagem, envios, cog = montar_pedido(monkeypatch, RuntimeError(SEGREDO), webhook=True)
        monkeypatch.setattr("empiremuse.cogs.music.string_to_file", lambda texto, nome: f"arquivo:{nome}")

        await classe.song_requests(self_, ctx, mensagem)

        cog.send_webhook.assert_awaited_once()
        embed = cog.send_webhook.await_args.kwargs["embed"]
        sem_vazamento(embed.description or "")
        assert CODIGO in (embed.description or "") + "\n".join(f.value for f in embed.fields)

    @pytest.mark.asyncio
    async def test_generic_error_continua_igual(self, monkeypatch, caplog):
        classe, self_, ctx, mensagem, envios, _ = montar_pedido(monkeypatch, GenericError("**Sem permissão aqui.**"))

        with caplog.at_level(logging.ERROR, logger="empiremuse.cogs.music"):
            await classe.song_requests(self_, ctx, mensagem)

        [(args, _)] = envios
        assert args[0].startswith("<@1>. ") and "Sem permissão aqui." in args[0] and "ERR-" not in args[0]
        assert not registros(caplog, "empiremuse.cogs.music", logging.ERROR)


# ============================================================================ owner_panel (dono)


def painel_com_interacao():
    from empiremuse.utils.owner_panel import PanelView

    editar = AsyncMock()
    view = PanelView.__new__(PanelView)
    view.bot = SimpleNamespace(http=SimpleNamespace(token=TOKEN_FALSO))
    interacao = SimpleNamespace(
        message=SimpleNamespace(embeds=[SimpleNamespace(description="")]),
        response=SimpleNamespace(is_done=lambda: True),
        original_message=AsyncMock(return_value=SimpleNamespace(edit=editar)),
    )
    return view, interacao, editar


class TestOwnerPanel:
    @pytest.mark.asyncio
    async def test_on_error_mostra_mensagem_generica_com_codigo(self, monkeypatch, caplog):
        fixar_codigo(monkeypatch)
        view, interacao, editar = painel_com_interacao()

        with caplog.at_level(logging.ERROR, logger="empiremuse.utils.owner_panel"):
            await view.on_error(RuntimeError(SEGREDO), None, interacao)

        texto = editar.await_args.kwargs["embed"].description
        sem_vazamento(texto, TOKEN_FALSO)
        assert "Ocorreu um erro" in texto and CODIGO in texto
        [registro] = registros(caplog, "empiremuse.utils.owner_panel", logging.ERROR)
        assert CODIGO in registro.getMessage() and registro.exc_info[0] is RuntimeError

    @pytest.mark.asyncio
    async def test_erro_esperado_continua_com_a_mensagem_propria(self):
        from disnake.ext import commands

        view, interacao, editar = painel_com_interacao()

        await view.on_error(commands.NotOwner(), None, interacao)

        texto = editar.await_args.kwargs["embed"].description
        assert "Apenas meu(s) desenvolvedor(es)" in texto and "ERR-" not in texto


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
    async def test_erro_inesperado_vira_texto_generico_com_codigo_e_o_detalhe_vai_para_o_log(self, monkeypatch, caplog):
        from empiremuse.utils.client import BotPool

        fixar_codigo(monkeypatch)
        pool = self.pool()

        with caplog.at_level(logging.ERROR, logger="empiremuse.utils.client"):
            await BotPool.start_bot(pool, self.bot(RuntimeError(SEGREDO)))

        texto = pool.failed_bots["bot-1"]
        sem_vazamento(texto, TOKEN_FALSO)
        assert CODIGO in texto and "falha" in texto.lower() and "log" in texto.lower()
        [registro] = registros(caplog, "empiremuse.utils.client", logging.ERROR)
        assert CODIGO in registro.getMessage() and registro.exc_info[0] is RuntimeError

    @pytest.mark.asyncio
    async def test_a_instrucao_do_privileged_intents_continua(self):
        from empiremuse.utils.client import BotPool

        pool = self.pool()
        await BotPool.start_bot(pool, self.bot(disnake.PrivilegedIntentsRequired(None)))

        texto = pool.failed_bots["bot-1"]
        assert "Privileged" in texto and "discord.com/developers/applications" in texto
        assert "ERR-" not in texto

    @pytest.mark.asyncio
    async def test_a_instrucao_do_token_invalido_continua(self):
        from empiremuse.utils.client import BotPool

        pool = self.pool()
        await BotPool.start_bot(pool, self.bot(disnake.LoginFailure("Improper token has been passed.")))

        assert "ERR-" not in pool.failed_bots["bot-1"] and "token" in pool.failed_bots["bot-1"].lower()


# ============================================================================ LavalinkPlayer


class Fim(Exception):
    """Levantada pelo ``sleep`` falso para sair de um laço infinito do código testado."""


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
    monkeypatch.setattr(models.asyncio, "sleep", AsyncMock())
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


def evento_de_falha(mensagem="This video is unavailable", causa=CAUSA, severidade="COMMON"):
    return wavelink.TrackException(
        {
            "track": None,
            "player": None,
            "node": SimpleNamespace(identifier="no-1"),
            "exception": {"message": mensagem, "cause": causa, "severity": severidade},
        }
    )


def enfileirar_e_encerrar(p, monkeypatch, evento):
    """Põe o evento na fila do ``hook_events`` e faz o primeiro ``sleep`` encerrar o laço."""

    async def dormir(segundos):
        p.is_closing = True

    monkeypatch.setattr("empiremuse.utils.music.models.asyncio.sleep", dormir)
    p.event_queue = asyncio.Queue()
    p.event_queue.put_nowait(evento)
    p.event_queue.put_nowait(object())


class TestFalhaDeReproducaoDoLavalink:
    @pytest.mark.asyncio
    async def test_a_mensagem_do_lavalink_fica_e_a_causa_vai_so_para_o_log(self, monkeypatch, caplog):
        fixar_codigo(monkeypatch)
        track = faixa()
        p = jogador(monkeypatch, current=track, last_track=track)
        enfileirar_e_encerrar(p, monkeypatch, evento_de_falha("Vídeo `indisponível`\nneste país"))

        with caplog.at_level(logging.WARNING, logger="empiremuse.utils.music.models"):
            await p.hook_events()

        texto = p.text_channel.send.await_args.kwargs["embed"].description
        assert "Vídeo 'indisponível' neste país" in texto, "a mensagem do Lavalink fica, sem quebrar o markdown"
        assert "```" not in texto and "causa-interna" not in texto and "/opt/lavalink" not in texto
        assert CODIGO in texto
        enviado_ao_webhook = p.report_error.await_args.args[0].description
        assert "causa-interna" not in enviado_ao_webhook
        log = "\n".join(r.getMessage() for r in registros(caplog, "empiremuse.utils.music.models"))
        assert "causa-interna-do-lavaplayer" in log and CODIGO in log

    @pytest.mark.asyncio
    async def test_mensagem_longa_e_truncada(self, monkeypatch):
        track = faixa()
        p = jogador(monkeypatch, current=track, last_track=track)
        enfileirar_e_encerrar(p, monkeypatch, evento_de_falha("m" * 1000))

        await p.hook_events()

        texto = p.text_channel.send.await_args.kwargs["embed"].description
        assert "m" * 201 not in texto and "m" * 100 in texto

    @pytest.mark.asyncio
    async def test_no_log_do_controlador_a_causa_tambem_nao_aparece(self, monkeypatch):
        track = faixa()
        p = jogador(monkeypatch, current=track, last_track=track, locked=True)
        enfileirar_e_encerrar(p, monkeypatch, evento_de_falha())

        async def encerrar(*args, **kwargs):
            p.is_closing = True

        p.report_error = AsyncMock(side_effect=encerrar)

        await p.hook_events()

        textos = [c.kwargs.get("text", c.args[0] if c.args else "") for c in p.set_command_log.call_args_list]
        assert textos and all("causa-interna" not in t and CAUSA not in t and "Causa" not in t for t in textos)


class TestOutrasFalhasDoPlayer:
    @pytest.mark.asyncio
    async def test_process_next_erro_inesperado(self, monkeypatch, caplog):
        fixar_codigo(monkeypatch)
        p = jogador(monkeypatch)
        p.bot.wait_until_ready = AsyncMock(side_effect=RuntimeError(SEGREDO))

        with caplog.at_level(logging.ERROR, logger="empiremuse.utils.music.models"):
            await p._process_next()

        texto = p.text_channel.send.await_args.kwargs["embed"].description
        sem_vazamento(texto)
        assert "Ocorreu um erro ao reproduzir a música" in texto and CODIGO in texto
        [registro] = registros(caplog, "empiremuse.utils.music.models", logging.ERROR)
        assert CODIGO in registro.getMessage() and registro.exc_info[0] is RuntimeError

    @pytest.mark.asyncio
    async def test_process_next_falha_ao_resolver_a_faixa_parcial(self, monkeypatch, caplog):
        from empiremuse.utils.music.models import PartialTrack

        fixar_codigo(monkeypatch)
        parcial = PartialTrack(uri="https://exemplo.invalid/p", title="Parcial", source_name="spotify")
        p = jogador(monkeypatch, queue=deque([parcial]), channel_purged=True, idle_task=None, auto_pause=False)
        p.guild.me.voice = object()
        p.resolve_track = AsyncMock(side_effect=RuntimeError(SEGREDO))

        with caplog.at_level(logging.ERROR, logger="empiremuse.utils.music.models"):
            await p._process_next()

        texto = p.text_channel.send.await_args.kwargs["embed"].description
        sem_vazamento(texto)
        assert "Houve um problema ao tentar processar a música" in texto and CODIGO in texto
        assert registros(caplog, "empiremuse.utils.music.models", logging.ERROR)

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

    @pytest.mark.asyncio
    async def test_wait_for_new_node_erro_inesperado_do_can_connect(self, monkeypatch, caplog):
        from empiremuse.utils.music import models

        fixar_codigo(monkeypatch)
        no = SimpleNamespace(identifier="no-2", players={9: object()})
        p = jogador(monkeypatch)
        p.node = SimpleNamespace(identifier="no-1", players={9: object()}, is_available=False)
        p._voice_state = None
        p.change_node = AsyncMock()
        p.destroy = AsyncMock()
        p.bot.music = SimpleNamespace(get_best_node=lambda ignore_node=None: no, players={})
        monkeypatch.setattr(models, "can_connect", MagicMock(side_effect=RuntimeError(SEGREDO)))

        with caplog.at_level(logging.ERROR, logger="empiremuse.utils.music.models"):
            await p._wait_for_new_node()

        textos = [c.args[0] if c.args else c.kwargs.get("text", "") for c in p.set_command_log.call_args_list]
        finalizado = [t for t in textos if "finalizado" in t]
        assert finalizado and all(SEGREDO not in t and "RuntimeError" not in t for t in finalizado)
        assert CODIGO in finalizado[0]
        assert registros(caplog, "empiremuse.utils.music.models", logging.ERROR)

    @pytest.mark.asyncio
    async def test_wait_for_new_node_mantem_o_texto_dos_erros_esperados(self, monkeypatch):
        from empiremuse.utils.music import models

        no = SimpleNamespace(identifier="no-2", players={9: object()})
        p = jogador(monkeypatch)
        p.node = SimpleNamespace(identifier="no-1", players={9: object()}, is_available=False)
        p._voice_state = None
        p.change_node = AsyncMock()
        p.destroy = AsyncMock()
        p.bot.music = SimpleNamespace(get_best_node=lambda ignore_node=None: no, players={})
        monkeypatch.setattr(models, "can_connect", MagicMock(side_effect=GenericError("**Sem permissão no canal.**")))

        await p._wait_for_new_node()

        textos = [c.args[0] if c.args else c.kwargs.get("text", "") for c in p.set_command_log.call_args_list]
        assert any("Sem permissão no canal." in t and "ERR-" not in t for t in textos)

    @pytest.mark.asyncio
    async def test_reconnect_voice_channel_erro_inesperado(self, monkeypatch, caplog):
        from empiremuse.utils.music import models

        fixar_codigo(monkeypatch)
        p = jogador(monkeypatch)
        p.bot.get_channel = lambda cid: SimpleNamespace(id=7)
        p.bot.music = SimpleNamespace(players={9: p})
        monkeypatch.setattr(models, "can_connect", MagicMock(side_effect=RuntimeError(SEGREDO)))

        async def dormir(segundos):
            raise Fim

        monkeypatch.setattr(models.asyncio, "sleep", dormir)

        with caplog.at_level(logging.ERROR, logger="empiremuse.utils.music.models"):
            with pytest.raises(Fim):
                await p.reconnect_voice_channel()

        texto = p.set_command_log.call_args.args[0]
        assert "falha ao reconectar o player no canal de voz" in texto
        assert SEGREDO not in texto and "RuntimeError" not in texto and CODIGO in texto
        assert registros(caplog, "empiremuse.utils.music.models", logging.ERROR)


# ============================================================================ guarda estrutural para os pontos que não dá para dirigir com dublê


class TestGuardaDeEstruturaEmModels:
    """``get_autoqueue_tracks`` e ``invoke_np`` têm o tratamento de erro no fim de métodos de centenas de linhas; para esses
    dois a guarda lê o código: nenhum texto de exceção, ``cause`` ou ``repr`` é interpolado numa mensagem ao usuário."""

    @pytest.fixture
    def fonte(self):
        import empiremuse.utils.music.models as models

        return Path(models.__file__).read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "padrao",
        [
            r"\{repr\((e|exception)\)\}",
            r"\{exception\.cause",
            r"\{exception\.message\}",
            r"\{event\.cause",
            r"houve um erro na interação: \{",
        ],
        ids=lambda p: p,
    )
    def test_nenhum_texto_de_excecao_na_mensagem(self, fonte, padrao):
        achados = [
            numero
            for numero, linha in enumerate(fonte.splitlines(), 1)
            if re.search(padrao, linha) and "print(" not in linha
        ]
        assert not achados, f"padrão {padrao!r} nas linhas {achados} de models.py"


# ============================================================================ complemento do AppSec (F-3, F-4, I-11, Info)
#
# Decisões do MAESTRO depois da auditoria complementar:
# * F-3: o ``error_description`` do Spotify não chega mais ao usuário (revoga o "motivo informado" do KI-15); fica no log;
# * F-4: a mensagem do nó Lavalink aparece dentro de um code span (a crase já é trocada), nos dois usos;
# * I-11: a troca do refreshToken por ``***`` no corpo da resposta vem ANTES do corte em 500 caracteres.

HOSTIL = "Veja https://evil.example/login <@123456789012345678> <#123456789012345678> @everyone :emoji:"


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
    async def test_o_motivo_do_spotify_nao_chega_ao_usuario_e_vai_para_o_log(self, monkeypatch, tmp_path, caplog):
        cliente = self.cliente(monkeypatch, tmp_path, {"error": "invalid_client", "error_description": self.MOTIVO})

        with caplog.at_level(logging.WARNING):
            with pytest.raises(GenericError) as erro:
                await cliente.get_access_token()

        texto = erro.value.text
        for proibido in ("motivo-externo", "evil.example", "<@", "invalid_client", "motivo informado"):
            assert proibido not in texto, f"vazou para o usuário: {proibido!r} em {texto!r}"
        assert "Spotify" in texto and "responsável" in texto
        assert "motivo-externo-do-spotify" in caplog.text, "o motivo continua disponível, só que no log"
        assert "segredo-de-teste" not in caplog.text and "segredo-de-teste" not in texto

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
    def test_a_mensagem_vira_um_unico_code_span_com_o_conteudo_dentro(self):
        from empiremuse.utils.music.models import lavalink_text

        texto = lavalink_text(HOSTIL)

        assert texto.startswith("`") and texto.endswith("`") and texto.count("`") == 2
        for parte in ("https://evil.example/login", "<@123456789012345678>", "<#123456789012345678>", "@everyone"):
            assert parte in texto[1:-1], f"{parte!r} deveria aparecer, mas dentro do code span"

    def test_crase_da_mensagem_nao_fecha_o_code_span(self):
        from empiremuse.utils.music.models import lavalink_text

        texto = lavalink_text("fecha `aqui` e ``ali`` <@1>")

        assert texto.count("`") == 2 and texto.startswith("`") and texto.endswith("`")
        assert "<@1>" in texto[1:-1]

    def test_sem_escape_dentro_do_span(self):
        """Dentro do code span a barra invertida apareceria literal: o texto vai como está (já sem quebra de linha)."""
        from empiremuse.utils.music.models import lavalink_text

        assert lavalink_text("vídeo *indisponível*\nneste país") == "`vídeo *indisponível* neste país`"

    def test_continua_truncada_e_vazio_nao_gera_span_vazio(self):
        from empiremuse.utils.music.models import lavalink_text

        longa = lavalink_text("m" * 1000)
        assert longa.count("m") == 200 and longa.startswith("`") and longa.endswith("`")
        for vazio in ("", None, "   \n "):
            assert "`" not in lavalink_text(vazio), f"span vazio para {vazio!r}"

    @pytest.mark.asyncio
    async def test_falha_de_reproducao_mostra_o_motivo_no_code_span(self, monkeypatch):
        track = faixa()
        p = jogador(monkeypatch, current=track, last_track=track)
        enfileirar_e_encerrar(p, monkeypatch, evento_de_falha(HOSTIL))

        await p.hook_events()

        texto = p.text_channel.send.await_args.kwargs["embed"].description
        [linha] = [linha for linha in texto.splitlines() if linha.startswith("**Motivo:**")]
        assert re.fullmatch(r"\*\*Motivo:\*\* `[^`]+`", linha), linha
        fora = texto.replace(linha, "")
        for ativo in ("evil.example", "<@", "<#", "@everyone"):
            assert ativo not in fora, f"{ativo!r} fora do code span: {fora!r}"

    def test_o_autoplay_usa_o_mesmo_helper_sem_envolver_em_crases(self):
        """``get_autoqueue_tracks`` é longo demais para dirigir com dublê: a guarda lê o código dos dois usos."""
        import empiremuse.utils.music.models as models

        fonte = Path(models.__file__).read_text(encoding="utf-8")
        usos = [linha.strip() for linha in fonte.splitlines() if "lavalink_text(" in linha and "def " not in linha]
        assert len(usos) == 2, usos
        assert any("exception.message" in uso for uso in usos) and any("event.message" in uso for uso in usos)
        assert not [uso for uso in usos if "`{lavalink_text" in uso or "{lavalink_text(" not in uso], usos
        assert not re.search(r"\{(?:exception|event)\.message[^}]*\}", fonte), "mensagem crua do nó numa f-string"


class TestTokenAtravessandoOLimiteDoLog:
    TOKEN = "OAUTHTOK-AB12CD34EF56GH78"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("antes", [0, 480, 490, 495, 499, 500])
    async def test_o_token_cortado_no_limite_nao_escapa_da_troca(self, monkeypatch, tmp_path, caplog, antes):
        from empiremuse.cogs import ll_yt_oauth

        (tmp_path / "application.yml").write_text(
            "plugins:\n  youtube:\n    oauth:\n      enabled: false\n", encoding="utf-8"
        )

        class VisaoComToken(FakeView):
            def __init__(self, bot=None, ctx=None):
                super().__init__(bot, ctx)
                self.data["refresh_token"] = TestTokenAtravessandoOLimiteDoLog.TOKEN

        node = SimpleNamespace(
            info={"plugins": ["youtube-plugin"]},
            rest_uri="http://127.0.0.1:2333",
            _websocket=SimpleNamespace(headers={}),
        )
        corpo = "x" * antes + self.TOKEN + " cauda"
        post = AsyncMock(return_value=Resposta(500, texto=corpo))
        cog, ctx, mensagem = montar_oauth(monkeypatch, tmp_path, node=node, post=post)
        monkeypatch.setattr(ll_yt_oauth, "YtOauthView", VisaoComToken)

        with caplog.at_level(logging.WARNING, logger="empiremuse.cogs.ll_yt_oauth"):
            await cog.oauth_command(ctx)

        log = "\n".join(r.getMessage() for r in registros(caplog, "empiremuse.cogs.ll_yt_oauth"))
        assert "OAUTHTOK" not in log and "AB12CD" not in log, f"pedaço do token no log: {log!r}"
        assert "HTTP 500" in log
        if antes + len("***") <= 500:  # o marcador cabe antes do corte; mais perto do limite ele mesmo pode ser cortado
            assert "***" in log

    @pytest.mark.asyncio
    async def test_guarda_o_corpo_sem_token_continua_no_log_truncado(self, monkeypatch, tmp_path, caplog):
        (tmp_path / "application.yml").write_text(
            "plugins:\n  youtube:\n    oauth:\n      enabled: false\n", encoding="utf-8"
        )
        node = SimpleNamespace(
            info={"plugins": ["youtube-plugin"]},
            rest_uri="http://127.0.0.1:2333",
            _websocket=SimpleNamespace(headers={}),
        )
        post = AsyncMock(return_value=Resposta(500, texto="erro-interno " + "y" * 2000))
        cog, ctx, _ = montar_oauth(monkeypatch, tmp_path, node=node, post=post)

        with caplog.at_level(logging.WARNING, logger="empiremuse.cogs.ll_yt_oauth"):
            await cog.oauth_command(ctx)

        log = "\n".join(r.getMessage() for r in registros(caplog, "empiremuse.cogs.ll_yt_oauth"))
        assert "erro-interno" in log and "y" * 600 not in log


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

    def test_o_campo_do_bot_descreve_o_canal_do_bot_e_nao_o_do_usuario(self):
        usuario = self.canal(1, "canal-do-usuario", limite=3, membros=1)
        bot = self.canal(2, "canal-do-bot", limite=5, membros=2)

        [valor] = self.campo(self.embed(usuario, bot), "Canal de voz (bot):")

        assert valor == "```\ncanal-do-bot (2/5)\nID: 2```"
        assert "canal-do-usuario" not in valor and "ID: 1" not in valor

    def test_o_nome_do_canal_do_bot_vai_com_escape(self):
        bot = self.canal(2, self.NOME_DO_BOT)

        [valor] = self.campo(self.embed(self.canal(1, "outro"), bot), "Canal de voz (bot):")

        assert disnake.utils.escape_markdown(self.NOME_DO_BOT) in valor
        assert "\\[link]" in valor, "o colchete do link markdown precisa sair escapado"

    def test_o_bloco_de_codigo_do_campo_do_bot_abre_e_fecha(self):
        [valor] = self.campo(self.embed(self.canal(1, "a"), self.canal(2, "b")), "Canal de voz (bot):")

        assert valor.startswith("```\n") and valor.endswith("```") and valor.count("```") == 2

    def test_sem_limite_de_usuarios_nao_mostra_contagem(self):
        [valor] = self.campo(
            self.embed(self.canal(1, "a"), self.canal(2, "b", limite=0, membros=4)), "Canal de voz (bot):"
        )

        assert valor == "```\nb\nID: 2```"

    def test_guarda_o_campo_do_usuario_continua_igual(self):
        usuario = self.canal(1, "canal-do-usuario", limite=3, membros=1)

        [valor] = self.campo(self.embed(usuario, self.canal(2, "canal-do-bot")), "Canal de voz (user):")

        assert valor == "```\ncanal-do-usuario (1/3)\nID: 1```"

    def test_guarda_no_mesmo_canal_nao_ha_campo_do_bot(self):
        mesmo = self.canal(1, "mesmo")

        embed = self.embed(mesmo, mesmo)

        assert self.campo(embed, "Canal de voz (bot):") == []
        assert len(self.campo(embed, "Canal de voz (user):")) == 1

    def test_guarda_usuario_fora_de_voz_nao_gera_os_campos_de_voz(self):
        embed = self.embed(None, self.canal(2, "b"), usuario_em_voz=False)

        assert self.campo(embed, "Canal de voz (bot):") == [] and self.campo(embed, "Canal de voz (user):") == []


# ============================================================================ lacunas apontadas pela mutação


class TestLacunasDaMutacao:
    def test_log_unexpected_error_registra_o_traceback_da_causa_original(self, monkeypatch, caplog):
        """``commands.CommandInvokeError`` e afins embrulham o erro real em ``original``: o log leva o de dentro."""
        from empiremuse.utils.music.errors import log_unexpected_error

        fixar_codigo(monkeypatch)

        class Embrulho(Exception):
            original = ValueError(SEGREDO)

        with caplog.at_level(logging.ERROR, logger="teste.s14"):
            log_unexpected_error(logging.getLogger("teste.s14"), Embrulho("casca"), "origem")
        [registro] = registros(caplog, "teste.s14", logging.ERROR)
        assert registro.exc_info[0] is ValueError

    @pytest.mark.asyncio
    async def test_o_log_do_servidor_leva_a_mensagem_do_lavalink_e_o_controlador_leva_o_codigo(
        self, monkeypatch, caplog
    ):
        fixar_codigo(monkeypatch)
        track = faixa()
        p = jogador(monkeypatch, current=track, last_track=track, locked=True)
        enfileirar_e_encerrar(p, monkeypatch, evento_de_falha("m" * 500))

        async def encerrar(*args, **kwargs):
            p.is_closing = True

        p.report_error = AsyncMock(side_effect=encerrar)

        with caplog.at_level(logging.WARNING, logger="empiremuse.utils.music.models"):
            await p.hook_events()

        log = "\n".join(r.getMessage() for r in registros(caplog, "empiremuse.utils.music.models"))
        assert "m" * 100 in log and CODIGO in log, "o log do servidor leva a mensagem e o código"
        textos = [c.kwargs.get("text", c.args[0] if c.args else "") for c in p.set_command_log.call_args_list]
        assert any(CODIGO in t and "m" * 50 + "…" in t and "m" * 51 not in t for t in textos), textos

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "erro",
        [GenericError("**Sem permissão no canal.**"), RuntimeError(SEGREDO)],
        ids=["esperado", "inesperado"],
    )
    async def test_wait_for_new_node_sempre_encerra_o_player_quando_nao_pode_conectar(self, monkeypatch, erro):
        from empiremuse.utils.music import models

        fixar_codigo(monkeypatch)
        no = SimpleNamespace(identifier="no-2", players={9: object()})
        p = jogador(monkeypatch)
        p.node = SimpleNamespace(identifier="no-1", players={9: object()}, is_available=False)
        p._voice_state = None
        p.change_node = AsyncMock()
        p.destroy = AsyncMock()
        p.connect = AsyncMock()
        p.bot.music = SimpleNamespace(get_best_node=lambda ignore_node=None: no, players={})
        monkeypatch.setattr(models, "can_connect", MagicMock(side_effect=erro))

        await p._wait_for_new_node()

        p.destroy.assert_awaited_once()
        p.connect.assert_not_awaited()

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
        monkeypatch.setattr(models, "can_connect", MagicMock(side_effect=PoolException("nenhum bot livre")))

        await p._wait_for_new_node()

        textos = [c.args[0] if c.args else c.kwargs.get("text", "") for c in p.set_command_log.call_args_list]
        assert any("nenhum bot livre" in t and "ERR-" not in t for t in textos)

    @pytest.mark.asyncio
    async def test_resposta_do_lavalink_local_o_token_e_mascarado_e_o_corpo_vira_uma_linha_curta_no_log(
        self, monkeypatch, tmp_path, caplog
    ):
        (tmp_path / "application.yml").write_text(
            "plugins:\n  youtube:\n    oauth:\n      enabled: false\n", encoding="utf-8"
        )
        node = SimpleNamespace(
            info={"plugins": ["youtube-plugin"]},
            rest_uri="http://127.0.0.1:2333",
            _websocket=SimpleNamespace(headers={}),
        )
        corpo = "linha1\nlinha2 eco do token refresh-falso " + "x" * 600
        post = AsyncMock(return_value=Resposta(500, texto=corpo))
        cog, ctx, mensagem = montar_oauth(monkeypatch, tmp_path, node=node, post=post)

        with caplog.at_level(logging.WARNING, logger="empiremuse.cogs.ll_yt_oauth"):
            await cog.oauth_command(ctx)

        log = "\n".join(r.getMessage() for r in registros(caplog, "empiremuse.cogs.ll_yt_oauth"))
        assert "refresh-falso" not in log and "linha1 linha2 eco do token ***" in log
        assert "x" * 501 not in log and "…" in log
        assert "HTTP 500" in texto_final(mensagem)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("status", "aplicado"), [(204, True), (200, False), (500, False)])
    async def test_so_o_204_vale_como_refresh_token_aplicado_no_lavalink_local(
        self, monkeypatch, tmp_path, status, aplicado
    ):
        (tmp_path / "application.yml").write_text(
            "plugins:\n  youtube:\n    oauth:\n      enabled: false\n", encoding="utf-8"
        )
        node = SimpleNamespace(
            info={"plugins": ["youtube-plugin"]},
            rest_uri="http://127.0.0.1:2333",
            _websocket=SimpleNamespace(headers={}),
        )
        cog, ctx, mensagem = montar_oauth(
            monkeypatch, tmp_path, node=node, post=AsyncMock(return_value=Resposta(status))
        )

        await cog.oauth_command(ctx)

        texto = texto_final(mensagem)
        assert ("configurado automaticamente no servidor lavalink LOCAL" in texto) is aplicado
        assert (f"HTTP {status}" in texto) is not aplicado

    @pytest.mark.asyncio
    async def test_erro_inesperado_do_dono_nao_imprime_o_traceback_no_terminal(self, monkeypatch, capsys):
        fixar_codigo(monkeypatch)
        view, interacao, editar = painel_com_interacao()

        await view.on_error(RuntimeError(SEGREDO), None, interacao)

        saida = capsys.readouterr()
        assert SEGREDO not in saida.out + saida.err, "o detalhe vai para o logger, não para o terminal"

    @pytest.mark.asyncio
    async def test_song_request_erro_inesperado_nao_imprime_o_traceback_no_terminal(self, monkeypatch, capsys):
        fixar_codigo(monkeypatch)
        classe, self_, ctx, mensagem, envios, _ = montar_pedido(monkeypatch, RuntimeError(SEGREDO))

        await classe.song_requests(self_, ctx, mensagem)

        saida = capsys.readouterr()
        assert SEGREDO not in saida.out + saida.err

    @pytest.mark.asyncio
    async def test_song_request_erro_esperado_aparece_sem_bloco_de_codigo(self, monkeypatch):
        classe, self_, ctx, mensagem, envios, _ = montar_pedido(monkeypatch, GenericError("**Sem permissão aqui.**"))

        await classe.song_requests(self_, ctx, mensagem)

        [(args, _)] = envios
        assert "```" not in args[0]

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
        monkeypatch.setattr("empiremuse.cogs.music.string_to_file", lambda texto, nome: anexos.append((texto, nome)))

        await classe.song_requests(self_, ctx, mensagem)

        [(texto, nome)] = anexos
        assert nome == (f"error_traceback_songrequest_{CODIGO}.txt" if gera else "error_traceback_songrequest.txt")
        assert TOKEN_FALSO not in texto and "mytoken" in texto


class TestGuardaAstEmModels:
    """Os dois métodos de centenas de linhas sem dublê: nenhuma exceção entra numa mensagem fora das formas aprovadas
    (qualquer sintaxe: ``{e}``, ``{str(e)}``, ``{e!r}``, ``{exception.cause}``…) e o erro inesperado vai para o log."""

    FUNCOES = ("get_autoqueue_tracks", "invoke_np")
    NOMES_DE_EXCECAO = {"e", "exception", "error", "exc", "err"}
    APROVADAS = {"lavalink_text(exception.message)", "exception.severity"}

    @pytest.fixture
    def funcoes(self):
        import ast

        import empiremuse.utils.music.models as models

        arvore = ast.parse(Path(models.__file__).read_text(encoding="utf-8"))
        achadas = {
            no.name: no
            for no in ast.walk(arvore)
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) and no.name in self.FUNCOES
        }
        assert set(achadas) == set(self.FUNCOES)
        return achadas

    @pytest.mark.parametrize("nome", FUNCOES)
    def test_nenhuma_excecao_na_mensagem_fora_das_formas_aprovadas(self, funcoes, nome):
        import ast

        dentro_de_print = {
            id(no)
            for chamada in ast.walk(funcoes[nome])
            if isinstance(chamada, ast.Call) and isinstance(chamada.func, ast.Name) and chamada.func.id == "print"
            for no in ast.walk(chamada)
        }
        achados = []
        for texto in ast.walk(funcoes[nome]):
            if not isinstance(texto, ast.JoinedStr) or id(texto) in dentro_de_print:
                continue
            for parte in texto.values:
                if not isinstance(parte, ast.FormattedValue):
                    continue
                usa = {n.id for n in ast.walk(parte.value) if isinstance(n, ast.Name)} & self.NOMES_DE_EXCECAO
                if usa and ast.unparse(parte.value) not in self.APROVADAS:
                    achados.append((texto.lineno, ast.unparse(parte.value)))
        assert not achados, f"exceção interpolada em mensagem de {nome}: {achados}"

    def test_o_erro_inesperado_e_registrado_com_codigo(self, funcoes):
        import ast

        chamadas = {
            nome: {
                n.func.id for n in ast.walk(funcoes[nome]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            }
            for nome in self.FUNCOES
        }
        assert "log_unexpected_error" in chamadas["invoke_np"]
        assert {"log_unexpected_error", "log_lavalink_failure", "lavalink_text"} <= chamadas["get_autoqueue_tracks"]

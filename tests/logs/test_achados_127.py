"""Item 7 (P3, #127, CodeRabbit) — RED das threads comportamentais.

(1) o servidor conhecido vai em ``extra={"guild": int}``: com ``LOG_LEVEL=INFO`` e ``LOG_DEBUG_GUILDS={g}``, o ``LevelGate`` só deixa o DEBUG passar
se ``record.guild`` existir; ``player_resume`` (migração e limpeza de sessão) e ``player_lifecycle`` (``Removendo invite``). ``_id`` não numérico
nunca levanta e não leva ``extra``. (2) ``LastFmException`` loga TIPO + CÓDIGO, nunca a mensagem. (3) ``_pn_native``: ``exceptions`` é uma lista;
o aviso traz os TIPOS (``ValueError, KeyError``), não os caracteres, e o traceback só vai para o DEBUG. (4) o ``encerrar_laco`` cancela a ``logs_task``.
"""

import asyncio
import io
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse.cogs import player_resume
from empiremuse.cogs.player_resume import PlayerSession
from empiremuse.logs.setup import configure_logging
from empiremuse.logs.settings import LogSettings
from empiremuse.music_cog.player_lifecycle import PlayerLifecycleMixin
from empiremuse.utils.music.lastfm_tools import LastFmException
from empiremuse.utils.music.models import autoqueue_steps, playback_steps
from tests.logs.apoio import Relogio
from tests.support.laco_do_pool import encerrar_laco

pytestmark = pytest.mark.critical

G, H = 700_000_000_000_000_001, 700_000_000_000_000_002


class DepoisDosFiltros(logging.Handler):
    """Instalado DEPOIS do ``configure_logging``: fotografa o ``guild`` que o ``ContextFilter`` deixou no registro."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.fotos: list[SimpleNamespace] = []

    def emit(self, record):
        self.fotos.append(
            SimpleNamespace(msg=record.getMessage(), guild=getattr(record, "guild", None), levelno=record.levelno)
        )


@pytest.fixture
def console():
    saida = io.StringIO()
    configure_logging(LogSettings(logging.INFO, False, False, frozenset({G}), 300), [], stream=saida, clock=Relogio())
    depois = DepoisDosFiltros()
    logging.getLogger().addHandler(depois)
    saida.fotos = depois.fotos
    return saida


def linhas(console, trecho):
    return [x for x in console.getvalue().splitlines() if trecho in x]


# ============================================================================ (1) player_resume


def cog_de_sessoes(*, mongo=(), local=(), para_mongo=False):
    cog = PlayerSession.__new__(PlayerSession)
    cog.bot = SimpleNamespace(
        player_resuming=False,
        player_resumed=False,
        bot_ready=True,
        wait_until_ready=AsyncMock(),
        config={"PLAYER_SESSIONS_MONGODB": para_mongo, "MONGO": "mongodb://x" if para_mongo else "", "EXTRA_HINTS": ""},
        players_resumed={},
        loop=SimpleNamespace(create_task=lambda coro: (coro.close(), MagicMock())[1]),
        get_guild=lambda _id: None,
        music=SimpleNamespace(players={}),
    )
    cog.get_player_sessions_mongo = AsyncMock(return_value=list(mongo))
    cog.get_player_sessions_local = AsyncMock(return_value=list(local))
    cog.save_session_local = AsyncMock()
    cog.save_session_mongo = AsyncMock()
    cog.delete_data_mongo = AsyncMock()
    cog.delete_data_local = MagicMock()
    cog.delete_data = AsyncMock()
    cog.resume_player = AsyncMock()
    return cog


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch):
    monkeypatch.setattr(player_resume.asyncio, "sleep", AsyncMock())


@pytest.mark.asyncio
class TestMigracaoDeSessao:
    async def test_the_mongo_to_local_migration_debug_comes_out_only_for_the_guild_in_debug(self, console):
        cog = cog_de_sessoes(mongo=[{"_id": str(G)}, {"_id": str(H)}])

        await cog.resume_players()

        achadas = linhas(console, "Migrando dados de sessões do server")
        assert len(achadas) == 1 and str(G) in achadas[0] and str(H) not in achadas[0]

    async def test_the_local_to_mongo_migration_debug_comes_out_only_for_the_guild_in_debug(self, console):
        cog = cog_de_sessoes(local=[{"_id": str(G)}, {"_id": str(H)}], para_mongo=True)

        await cog.resume_players()

        achadas = linhas(console, "Migrando dados de sessões do server")
        assert len(achadas) == 1 and str(G) in achadas[0] and "Local -> Mongo" in achadas[0]

    async def test_the_record_guild_is_an_int(self, console):
        cog = cog_de_sessoes(mongo=[{"_id": str(G)}])

        await cog.resume_players()

        fotos = [f for f in console.fotos if "Migrando dados" in f.msg]
        assert fotos and all(type(f.guild) is int and f.guild == G for f in fotos)

    async def test_a_non_numeric_id_neither_raises_nor_carries_a_guild(self, console):
        cog = cog_de_sessoes(mongo=[{"_id": "nao-numerico"}, {"_id": str(G)}])

        await cog.resume_players()

        assert not linhas(console, "Falha ao retomar players")  # nenhum ERROR por causa do int()
        assert cog.bot.player_resumed is True
        fotos = [f for f in console.fotos if "nao-numerico" in f.msg]
        assert all(f.guild is None for f in fotos)
        assert len(linhas(console, "Migrando dados de sessões do server")) == 1  # só a do servidor G

    async def test_a_snowflake_with_digits_only_after_a_sign_or_spaces_is_not_taken_for_a_guild(self, console):
        cog = cog_de_sessoes(mongo=[{"_id": "-5"}, {"_id": " 12 "}, {"_id": "１２３４５６７８９０１２３４５６７"}])

        await cog.resume_players()

        assert not linhas(console, "Falha ao retomar players")
        assert all(f.guild is None for f in console.fotos if "Migrando dados" in f.msg)


@pytest.mark.asyncio
class TestLimpezaEIgnorado:
    async def test_the_cleanup_debug_comes_out_for_the_guild_in_debug_and_not_for_another(self, console):
        cog = cog_de_sessoes()

        await PlayerSession.resume_player(cog, {"_id": str(G), "time": None})
        await PlayerSession.resume_player(cog, {"_id": str(H), "time": None})

        achadas = linhas(console, "Limpando informações do player")
        assert len(achadas) == 1 and str(G) in achadas[0]
        assert [f.guild for f in console.fotos if "Limpando" in f.msg] == [
            G,
            H,
        ]  # o handler de captura vê os dois; o console só o G

    async def test_the_ignored_player_debug_comes_out_for_the_guild_in_debug_and_not_for_another(self, console):
        cog = cog_de_sessoes()
        recente = disnake.utils.utcnow()

        await PlayerSession.resume_player(cog, {"_id": str(G), "time": recente})
        await PlayerSession.resume_player(cog, {"_id": str(H), "time": recente})

        achadas = linhas(console, "Player ignorado")
        assert len(achadas) == 1 and str(G) in achadas[0]
        assert [f.guild for f in console.fotos if "ignorado" in f.msg] == [G, H]

    async def test_a_non_numeric_id_in_the_cleanup_and_ignored_paths_does_not_raise(self, console):
        cog = cog_de_sessoes()
        recente = disnake.utils.utcnow()

        await PlayerSession.resume_player(cog, {"_id": "xyz", "time": None})
        await PlayerSession.resume_player(cog, {"_id": "xyz", "time": recente})

        assert not [x for x in console.getvalue().splitlines() if "ERROR" in x]
        assert all(f.guild is None for f in console.fotos if "xyz" in f.msg)


# ============================================================================ (1) player_lifecycle


class Parou(Exception):
    pass


def cog_de_ciclo(guild_id: int):
    vc = SimpleNamespace(id=555, guild=SimpleNamespace(id=guild_id))
    bot = SimpleNamespace(
        music=SimpleNamespace(players={}),
        get_data=AsyncMock(),
        get_global_data=AsyncMock(
            return_value={"global_skin": False, "listen_along_invites": {"555": "https://discord.gg/abc"}}
        ),
        fetch_invite=AsyncMock(side_effect=disnake.NotFound(SimpleNamespace(status=404, reason="x"), "Unknown Invite")),
        update_global_data=AsyncMock(side_effect=Parou),
    )
    cog = PlayerLifecycleMixin()
    cog.bot = bot
    inter = SimpleNamespace(
        guild_id=guild_id, guild=SimpleNamespace(id=guild_id), author=SimpleNamespace(voice=SimpleNamespace(channel=vc))
    )
    guild_data = {"player_controller": {"skin": "default", "static_skin": "default"}}
    return cog, bot, inter, guild_data


@pytest.mark.asyncio
class TestCicloDoPlayer:
    async def test_the_removed_invite_debug_comes_out_only_for_the_guild_in_debug(self, console):
        for servidor in (G, H):
            cog, bot, inter, dados = cog_de_ciclo(servidor)
            with pytest.raises(Parou):
                await cog.create_player(
                    inter,
                    bot,
                    SimpleNamespace(id=servidor),
                    SimpleNamespace(),
                    guild_data=dados,
                    node=SimpleNamespace(),
                )

        achadas = linhas(console, "Removendo invite")
        assert len(achadas) == 1 and str(G) in achadas[0]
        assert [f.guild for f in console.fotos if "Removendo invite" in f.msg] == [G, H]


# ============================================================================ (2) Last.FM: tipo e código, nunca a mensagem


@pytest.mark.asyncio
class TestLastFm:
    async def test_the_lastfm_error_logs_the_type_and_the_code_and_nothing_of_the_message(self, caplog, capsys):
        erro = LastFmException({"error": 6, "message": "mensagem-secreta-da-api api_key=SEGREDO"})
        contexto = SimpleNamespace(
            bot=SimpleNamespace(last_fm=SimpleNamespace(get_similar_artists=AsyncMock(side_effect=erro))),
            lastfm_artists=[],
            native_yt=False,
            node=SimpleNamespace(search_providers=[], get_tracks=AsyncMock(), info={"sourceManagers": []}),
        )
        faixa = SimpleNamespace(
            ytid=None, author="Artista", title="Musica", uri="https://x/y", info={"sourceName": "spotify", "extra": {}}
        )
        req = SimpleNamespace(exception=None, t=None, track_data=faixa, tracks=[], tracks_search=[], tracks_ytsearch=[])
        caplog.set_level(logging.DEBUG)

        await autoqueue_steps._aq_lastfm_tracks(contexto, req)

        avisos = [r for r in caplog.records if r.levelno == logging.WARNING and "Last.FM" in r.getMessage()]
        assert len(avisos) == 1
        texto = avisos[0].getMessage()
        assert "LastFmException" in texto and "6" in texto
        assert "mensagem-secreta" not in caplog.text and "SEGREDO" not in caplog.text
        saida = capsys.readouterr()
        assert "mensagem-secreta" not in saida.out + saida.err and "Traceback" not in saida.out + saida.err


# ============================================================================ (3) tipos das exceções, não caracteres


@pytest.mark.asyncio
class TestTiposDasExcecoes:
    def montar(self, falhas):
        faixa = SimpleNamespace(
            title="Musica",
            author="Artista",
            uri="https://youtube.com/watch?v=1",
            duration=200_000,
            is_stream=False,
            identifier="1",
            id=None,
            ytid="1",
            info={"sourceName": "youtube"},
        )
        self_ = SimpleNamespace(
            native_yt=False,
            node=SimpleNamespace(
                search_providers=["scsearch", "dzsearch"],
                prefer_youtube_native_playback=True,
                get_tracks=AsyncMock(side_effect=falhas),
            ),
            bot=SimpleNamespace(pool=SimpleNamespace(partial_track_cache={})),
            played=[],
            locked=True,
            process_next=AsyncMock(),
            set_command_log=MagicMock(),
        )
        req = SimpleNamespace(encoded_track="enc", track=faixa)
        return self_, req

    async def test_the_warning_names_the_exception_types_not_the_characters(self, monkeypatch, caplog, capsys):
        monkeypatch.setattr(playback_steps.asyncio, "sleep", AsyncMock())
        self_, req = self.montar([ValueError("falha a"), KeyError("falha b")])
        caplog.set_level(logging.DEBUG)

        await playback_steps._pn_native(self_, req)

        avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert [r.getMessage() for r in avisos] == ["Faixa sem resultado em outras plataformas (ValueError, KeyError)"]
        assert avisos[0].exc_info is None and "Traceback" not in avisos[0].getMessage()
        saida = capsys.readouterr()
        assert "Traceback" not in saida.out + saida.err

    async def test_the_traceback_detail_lives_only_at_debug(self, monkeypatch, caplog):
        monkeypatch.setattr(playback_steps.asyncio, "sleep", AsyncMock())
        self_, req = self.montar([ValueError("falha a"), KeyError("falha b")])
        caplog.set_level(logging.DEBUG)

        await playback_steps._pn_native(self_, req)

        assert not [r for r in caplog.records if r.levelno >= logging.WARNING and "Traceback" in r.getMessage()]
        detalhes = [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and "ValueError" in r.getMessage() + (caplog.text or "")
        ]
        assert detalhes

    async def test_a_single_failing_provider_lists_one_type(self, monkeypatch, caplog):
        monkeypatch.setattr(playback_steps.asyncio, "sleep", AsyncMock())
        self_, req = self.montar([RuntimeError("x"), []])
        caplog.set_level(logging.DEBUG)

        await playback_steps._pn_native(self_, req)

        avisos = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert avisos == ["Faixa sem resultado em outras plataformas (RuntimeError)"]


# ============================================================================ (4) encerrar_laco cancela a logs_task


class TestEncerrarLaco:
    def test_the_helper_cancels_a_pending_logs_task_and_the_version_task(self):
        laco = asyncio.new_event_loop()

        async def pendurada():
            await asyncio.Event().wait()

        pool = SimpleNamespace(
            logs_task=laco.create_task(pendurada()), version_check_task=laco.create_task(pendurada())
        )

        encerrar_laco(laco)

        assert pool.logs_task.cancelled() and pool.version_check_task.cancelled() and laco.is_closed()

    def test_the_helper_tolerates_a_missing_or_closed_loop(self):
        encerrar_laco(None)
        laco = asyncio.new_event_loop()
        laco.close()
        encerrar_laco(laco)

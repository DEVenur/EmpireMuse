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


# ============================================================================ (1) player_lifecycle


class Parou(Exception):
    pass


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


# ============================================================================ (4) encerrar_laco cancela a logs_task

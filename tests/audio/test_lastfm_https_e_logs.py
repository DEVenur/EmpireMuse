"""S-30 — o Last.fm só fala HTTPS, leva as credenciais do POST no corpo e nenhum log/erro mostra a URL com ``api_key``/``sk``/``api_sig``.

Sessão, bot, player e provedores são fakes; nada sai da máquina.
"""

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from empiremuse.cogs.lastfm import LastFMView, LastFmCog
from empiremuse.music_cog.tracks import TracksMixin
from empiremuse.utils.music import lastfm_tools
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.music.lastfm_tools import LastFM
from empiremuse.utils.music.models import autoqueue_steps
from tests.support.erros_http import erro_response

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

SEGREDO = "SEGREDO-SK"
URL_COM_SEGREDO = f"https://ws.audioscrobbler.com/2.0/?method=track.scrobble&api_key=AK&sk={SEGREDO}&api_sig=SIG"


def erro_com_url_secreta() -> aiohttp.ContentTypeError:
    return erro_response(200, aiohttp.ContentTypeError, url=URL_COM_SEGREDO)


def sem_segredo(texto: str) -> None:
    for proibido in (SEGREDO, "api_key", "api_sig", "RequestInfo"):
        assert proibido not in texto, texto


# ============================================================================ (1) HTTPS e corpo do POST


class RespostaJson:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return {"ok": 1}


class SessaoQueCaptura:
    chamadas: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url, **kwargs):
        self.chamadas.append(("GET", url, kwargs))
        return RespostaJson()

    def post(self, url, **kwargs):
        self.chamadas.append(("POST", url, kwargs))
        return RespostaJson()


@pytest.fixture
def lastfm(monkeypatch):
    SessaoQueCaptura.chamadas = []
    monkeypatch.setattr(lastfm_tools, "ClientSession", SessaoQueCaptura)
    api = LastFM.__new__(LastFM)
    api.api_key, api.api_secret = "AK", "SECRET"
    return api


PARAMS = {"method": "track.scrobble", "api_key": "AK", "sk": SEGREDO, "api_sig": "SIG"}


async def test_the_get_request_uses_https_and_keeps_the_query_params(lastfm):
    await lastfm.request_lastfm({"method": "artist.getSimilar", "api_key": "AK", "artist": "Artista"})

    ((metodo, url, kwargs),) = SessaoQueCaptura.chamadas
    assert metodo == "GET" and url.startswith("https://ws.audioscrobbler.com/2.0/")
    assert kwargs["params"]["artist"] == "Artista" and kwargs["params"]["api_key"] == "AK"


async def test_the_post_request_uses_https_and_sends_the_credentials_in_the_body(lastfm):
    await lastfm.post_lastfm(dict(PARAMS))

    ((metodo, url, kwargs),) = SessaoQueCaptura.chamadas
    assert metodo == "POST" and url.startswith("https://ws.audioscrobbler.com/2.0/")
    assert kwargs["data"]["sk"] == SEGREDO and kwargs["data"]["api_sig"] == "SIG" and kwargs["data"]["format"] == "json"
    assert not kwargs.get("params")


# ============================================================================ (2) link de autorização do usuário


async def test_the_auth_link_sent_to_the_user_is_https():
    visao = LastFMView.__new__(LastFMView)
    visao.auth_url, visao.last_timestamp, visao.check_session_loop = None, None, Mock()
    bot = SimpleNamespace(
        loop=SimpleNamespace(create_task=Mock()),
        last_fm=SimpleNamespace(api_key="AK", get_token=AsyncMock(return_value="TK")),
    )
    visao.ctx = SimpleNamespace(bot=bot)
    interacao = SimpleNamespace(send=AsyncMock())

    await visao.send_authurl_callback(interacao)

    assert visao.auth_url.startswith("https://www.last.fm/api/auth/")


# ============================================================================ (3) logs sem a URL com as credenciais


async def test_a_scrobble_http_failure_logs_the_status_without_url_or_traceback(capsys):
    cog = LastFmCog.__new__(LastFmCog)
    cog.bot = SimpleNamespace(
        pool=SimpleNamespace(lastfm_sessions={7: {"scrobble": True, "sessionkey": "sk"}}),
        last_fm=SimpleNamespace(update_nowplaying=AsyncMock(side_effect=erro_com_url_secreta())),
    )
    player = SimpleNamespace(guild=SimpleNamespace(me=SimpleNamespace(voice=True)), lastfm_users={})
    track = SimpleNamespace(
        is_stream=False,
        duration=200000,
        info={"sourceName": "spotify"},
        album_name="Album",
        author="Artista",
        single_title="Musica",
        url="https://x/y",
        autoplay=False,
        requester=7,
    )

    await cog.startscrooble(player, track, update_np=True, users=[SimpleNamespace(id=7, bot=False)])

    saida = capsys.readouterr()
    visivel = saida.out + saida.err
    sem_segredo(visivel)
    assert "last.fm request failed! user: 7" in visivel and "HTTP 200" in visivel
    assert "Traceback" not in visivel


async def test_the_autoqueue_recommendation_http_failure_logs_the_status_without_url_or_traceback(capsys):
    contexto = SimpleNamespace(
        bot=SimpleNamespace(last_fm=SimpleNamespace(get_similar_artists=AsyncMock(side_effect=erro_com_url_secreta()))),
        lastfm_artists=[],
    )
    track_data = SimpleNamespace(
        ytid=None, author="Artista", title="Musica", info={"sourceName": "spotify"}, url="https://x/y"
    )
    req = SimpleNamespace(
        exception=None, t=None, track_data=track_data, tracks=[], tracks_search=[], tracks_ytsearch=[]
    )

    with contextlib.suppress(Exception):  # o resto do passo (busca nos provedores) não é o assunto aqui
        await autoqueue_steps._aq_lastfm_tracks(contexto, req)

    saida = capsys.readouterr()
    visivel = saida.out + saida.err
    sem_segredo(visivel)
    assert "Last.FM recommendations error: HTTP 200" in visivel and "Traceback" not in visivel


# ============================================================================ (4) mix: o erro mostrado ao usuário


async def test_the_mix_error_shown_to_the_user_has_no_secret():
    falha = AsyncMock(side_effect=erro_com_url_secreta())
    cog = TracksMixin()
    cog.bot = SimpleNamespace(
        pool=SimpleNamespace(last_fm=SimpleNamespace(get_similar_tracks=falha, get_artist_toptracks=falha))
    )

    with pytest.raises(GenericError) as erro:
        await cog.get_tracks("Artista - Musica", SimpleNamespace(), SimpleNamespace(id=1), mix=True)

    sem_segredo(erro.value.error)
    assert "HTTP 200" in erro.value.error


# ============================================================================ credenciais de sessão só no corpo (POST), nunca na URL

SK, TOKEN, SIG = "SK-DO-USUARIO", "TOKEN-DE-AUTH", "ASSINATURA"
CORPO = {"user": {"name": "u"}, "token": TOKEN, "session": {"key": "k"}, "similarartists": {"artist": []}}


class Pedidos:
    """Sessão que registra o pedido e, como o aiohttp, só põe na URL o que foi em ``params=`` (o corpo do POST não aparece nela)."""

    chamadas: list = []
    quebrar = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def _resposta(self, metodo, url, kwargs):
        self.chamadas.append((metodo, url, kwargs))
        consulta = "&".join(f"{k}={v}" for k, v in (kwargs.get("params") or {}).items())
        erro = erro_response(200, aiohttp.ContentTypeError, url=f"{url}?{consulta}") if self.quebrar else None
        return RespostaCom(erro)

    def get(self, url, **kwargs):
        return self._resposta("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._resposta("POST", url, kwargs)


class RespostaCom:
    def __init__(self, erro):
        self.erro = erro

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        if self.erro:
            raise self.erro
        return CORPO


@pytest.fixture
def pedidos(monkeypatch):
    Pedidos.chamadas, Pedidos.quebrar = [], False
    monkeypatch.setattr(lastfm_tools, "ClientSession", Pedidos)
    api = LastFM.__new__(LastFM)
    api.api_key, api.api_secret = "AK", "SECRET"
    return api


@pytest.mark.parametrize(
    "chamar",
    [lambda api: api.user_info(SK), lambda api: api.get_session_key(TOKEN)],
    ids=["user_info", "get_session_key"],
)
async def test_calls_with_session_secrets_go_by_post_with_the_secrets_only_in_the_body(pedidos, chamar):
    await chamar(pedidos)

    ((metodo, url, kwargs),) = Pedidos.chamadas
    assert metodo == "POST" and url == "https://ws.audioscrobbler.com/2.0/"
    assert not kwargs.get("params")
    corpo = kwargs["data"]
    assert corpo["api_key"] == "AK" and (corpo.get("sk") == SK or corpo.get("token") == TOKEN)


@pytest.mark.parametrize(
    "chamar",
    [lambda api: api.get_token(), lambda api: api.get_similar_artists("Artista")],
    ids=["get_token", "get_similar_artists"],
)
async def test_reads_with_only_the_api_key_stay_as_get_with_query_params(pedidos, chamar):
    await chamar(pedidos)

    ((metodo, url, kwargs),) = Pedidos.chamadas
    assert metodo == "GET" and url == "https://ws.audioscrobbler.com/2.0/"
    assert kwargs["params"]["api_key"] == "AK" and "sk" not in kwargs["params"] and "token" not in kwargs["params"]


@pytest.mark.parametrize(
    "chamar",
    [lambda api: api.user_info(SK), lambda api: api.get_session_key(TOKEN)],
    ids=["user_info", "get_session_key"],
)
async def test_the_error_of_a_call_with_session_secrets_does_not_carry_them(pedidos, chamar):
    Pedidos.quebrar = True

    with pytest.raises(aiohttp.ContentTypeError) as erro:
        await chamar(pedidos)

    texto = str(erro.value) + repr(erro.value)
    assert SK not in texto and TOKEN not in texto and "api_sig" not in texto

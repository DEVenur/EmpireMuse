"""S-30 — o Last.fm só fala HTTPS, leva as credenciais do POST no corpo e nenhum log/erro mostra a URL com ``api_key``/``sk``/``api_sig``.

Sessão, bot, player e provedores são fakes; nada sai da máquina.
"""

import contextlib
import hashlib
import logging
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, Self
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from empiremuse.cogs.lastfm import LastFMView, LastFmCog
from empiremuse.music_cog.tracks import TracksMixin
from empiremuse.utils.music import lastfm_tools
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.safe_error import HTTPStatusError, safe_error
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
    status = 200

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def json(self) -> dict[str, int]:
        return {"ok": 1}


class SessaoQueCaptura:
    chamadas: list = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    def get(self, url: str, **kwargs: Any) -> RespostaJson:
        self.chamadas.append(("GET", url, kwargs))
        return RespostaJson()

    def post(self, url: str, **kwargs: Any) -> RespostaJson:
        self.chamadas.append(("POST", url, kwargs))
        return RespostaJson()


@pytest.fixture
def lastfm(monkeypatch: pytest.MonkeyPatch) -> LastFM:
    SessaoQueCaptura.chamadas = []
    monkeypatch.setattr(lastfm_tools, "ClientSession", SessaoQueCaptura)
    api = LastFM.__new__(LastFM)
    api.api_key, api.api_secret = "AK", "SECRET"
    return api


PARAMS = {"method": "track.scrobble", "api_key": "AK", "sk": SEGREDO, "api_sig": "SIG"}


async def test_the_get_request_uses_https_and_keeps_the_query_params(lastfm: LastFM) -> None:
    await lastfm.request_lastfm({"method": "artist.getSimilar", "api_key": "AK", "artist": "Artista"})

    ((metodo, url, kwargs),) = SessaoQueCaptura.chamadas
    assert metodo == "GET" and url.startswith("https://ws.audioscrobbler.com/2.0/")
    assert kwargs["params"]["artist"] == "Artista" and kwargs["params"]["api_key"] == "AK"


async def test_the_post_request_uses_https_and_sends_the_credentials_in_the_body(lastfm: LastFM) -> None:
    await lastfm.post_lastfm(dict(PARAMS))

    ((metodo, url, kwargs),) = SessaoQueCaptura.chamadas
    assert metodo == "POST" and url.startswith("https://ws.audioscrobbler.com/2.0/")
    assert kwargs["data"]["sk"] == SEGREDO and kwargs["data"]["api_sig"] == "SIG" and kwargs["data"]["format"] == "json"
    assert not kwargs.get("params")


# ============================================================================ (2) link de autorização do usuário


async def test_the_auth_link_sent_to_the_user_is_https() -> None:
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


@pytest.mark.parametrize(
    ("erro", "resumo"),
    [(erro_com_url_secreta(), "HTTP 200"), (HTTPStatusError(307), "HTTP 307")],
    ids=["client-error", "redirecionamento-3xx"],
)
async def test_a_scrobble_http_failure_logs_the_status_without_url_or_traceback(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str], erro: Exception, resumo: str
) -> None:
    cog = LastFmCog.__new__(LastFmCog)
    cog.bot = SimpleNamespace(
        pool=SimpleNamespace(lastfm_sessions={7: {"scrobble": True, "sessionkey": "sk"}}),
        last_fm=SimpleNamespace(update_nowplaying=AsyncMock(side_effect=erro)),
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

    with caplog.at_level(logging.WARNING):
        await cog.startscrooble(player, track, update_np=True, users=[SimpleNamespace(id=7, bot=False)])

    sem_segredo(caplog.text)
    assert f"last.fm request failed! user: 7 - {resumo}" in caplog.text
    assert all(registro.exc_info is None for registro in caplog.records)
    assert "Traceback" not in capsys.readouterr().err


async def test_the_autoqueue_recommendation_http_failure_logs_the_status_without_url_or_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
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

    with caplog.at_level(logging.WARNING), contextlib.suppress(Exception):  # o resto do passo não é o assunto aqui
        await autoqueue_steps._aq_lastfm_tracks(contexto, req)

    sem_segredo(caplog.text)
    assert "Last.FM recommendations error: HTTP 200" in caplog.text
    assert all(registro.exc_info is None for registro in caplog.records)


# ============================================================================ (4) mix: o erro mostrado ao usuário


async def test_the_mix_error_shown_to_the_user_has_no_secret() -> None:
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

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    def _resposta(self, metodo: str, url: str, kwargs: dict[str, Any]) -> "RespostaCom":
        self.chamadas.append((metodo, url, kwargs))
        consulta = "&".join(f"{k}={v}" for k, v in (kwargs.get("params") or {}).items())
        erro = erro_response(200, aiohttp.ContentTypeError, url=f"{url}?{consulta}") if self.quebrar else None
        return RespostaCom(erro)

    def get(self, url: str, **kwargs: Any) -> "RespostaCom":
        return self._resposta("GET", url, kwargs)

    def post(self, url: str, **kwargs: Any) -> "RespostaCom":
        return self._resposta("POST", url, kwargs)


class RespostaCom:
    status = 200

    def __init__(self, erro: Exception | None) -> None:
        self.erro = erro

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def json(self) -> dict[str, Any]:
        if self.erro:
            raise self.erro
        return CORPO


@pytest.fixture
def pedidos(monkeypatch: pytest.MonkeyPatch) -> LastFM:
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
async def test_calls_with_session_secrets_go_by_post_with_the_secrets_only_in_the_body(
    pedidos: LastFM, chamar: Callable[[LastFM], Awaitable[Any]]
) -> None:
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
async def test_reads_with_only_the_api_key_stay_as_get_with_query_params(
    pedidos: LastFM, chamar: Callable[[LastFM], Awaitable[Any]]
) -> None:
    await chamar(pedidos)

    ((metodo, url, kwargs),) = Pedidos.chamadas
    assert metodo == "GET" and url == "https://ws.audioscrobbler.com/2.0/"
    assert kwargs["params"]["api_key"] == "AK" and "sk" not in kwargs["params"] and "token" not in kwargs["params"]


@pytest.mark.parametrize(
    "chamar",
    [lambda api: api.user_info(SK), lambda api: api.get_session_key(TOKEN)],
    ids=["user_info", "get_session_key"],
)
async def test_the_error_of_a_call_with_session_secrets_does_not_carry_them(
    pedidos: LastFM, chamar: Callable[[LastFM], Awaitable[Any]]
) -> None:
    Pedidos.quebrar = True

    with pytest.raises(aiohttp.ContentTypeError) as erro:
        await chamar(pedidos)

    texto = str(erro.value) + repr(erro.value)
    assert SK not in texto and TOKEN not in texto and "api_sig" not in texto


# ============================================================================ redirecionamento: o corpo com as credenciais não vai para outro lugar


class RespostaDeRedirecionamento:
    def __init__(self, status: int, local: str | None = None) -> None:
        self.status = status
        self.headers = {"Location": local} if local else {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def json(self) -> dict[str, int]:
        return {"ok": 1}


class SessaoQueRedireciona:
    """Responde ao 1º POST com ``status`` e ``Location``; como o aiohttp, segue o redirecionamento reenviando o corpo, a menos que ``allow_redirects=False``."""

    status = 307
    posts: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    def post(self, url: str, **kwargs: Any) -> RespostaDeRedirecionamento:
        self.posts.append((url, kwargs))
        if len(self.posts) == 1:
            if kwargs.get("allow_redirects", True):
                self.posts.append(("https://outro.exemplo/destino", kwargs))
                return RespostaDeRedirecionamento(200)
            return RespostaDeRedirecionamento(self.status, "https://outro.exemplo/destino")
        return RespostaDeRedirecionamento(200)


@pytest.fixture
def com_redirecionamento(monkeypatch: pytest.MonkeyPatch) -> LastFM:
    SessaoQueRedireciona.posts = []
    monkeypatch.setattr(lastfm_tools, "ClientSession", SessaoQueRedireciona)
    api = LastFM.__new__(LastFM)
    api.api_key, api.api_secret = "AK", "SECRET"
    return api


@pytest.mark.parametrize("status", [307, 308])
@pytest.mark.parametrize("via", ["post_lastfm", "request_lastfm"])
async def test_a_redirect_of_the_post_with_credentials_is_an_error_and_the_body_is_not_resent(
    com_redirecionamento: LastFM, status: int, via: str
) -> None:
    SessaoQueRedireciona.status = status
    chamar = getattr(com_redirecionamento, via)

    with pytest.raises(HTTPStatusError) as erro:
        await chamar({"method": "track.scrobble", "api_key": "AK", "sk": SEGREDO, "api_sig": "SIG"})

    assert safe_error(erro.value) == f"HTTP {status}"
    ((url, kwargs),) = SessaoQueRedireciona.posts  # um único POST, e nenhum para o destino do redirecionamento
    assert url == "https://ws.audioscrobbler.com/2.0/" and kwargs["allow_redirects"] is False


async def test_a_normal_post_response_still_works_with_redirects_disabled(
    com_redirecionamento: LastFM, monkeypatch: pytest.MonkeyPatch
) -> None:
    class SessaoNormal(SessaoQueRedireciona):
        def post(self, url: str, **kwargs: Any) -> RespostaDeRedirecionamento:
            self.posts.append((url, kwargs))
            return RespostaDeRedirecionamento(200)

    monkeypatch.setattr(lastfm_tools, "ClientSession", SessaoNormal)
    SessaoNormal.posts = []

    assert await com_redirecionamento.post_lastfm({"method": "track.scrobble", "api_key": "AK"}) == {"ok": 1}
    assert SessaoNormal.posts[0][1]["allow_redirects"] is False


# ============================================================================ assinatura (api_sig) de toda chamada autenticada


def assinatura_esperada(corpo: dict[str, Any], segredo: str) -> str:
    """Como a API do Last.fm confere: ``md5`` de ``chave+valor`` em ordem alfabética, sem ``api_sig`` nem ``format``, mais o segredo."""
    parametros = {k: v for k, v in corpo.items() if k not in ("api_sig", "format")}
    return hashlib.md5(("".join(f"{k}{parametros[k]}" for k in sorted(parametros)) + segredo).encode()).hexdigest()


@pytest.mark.parametrize(
    "chamar",
    [
        lambda api: api.user_info(SK),
        lambda api: api.track_scrobble("Artista", "Musica", "Album", 200, SK),
        lambda api: api.update_nowplaying("Artista", "Musica", "Album", 200, SK),
        lambda api: api.track_love("Musica", "Artista", SK),
        lambda api: api.track_unlove("Musica", "Artista", SK),
        lambda api: api.get_session_key(TOKEN),
    ],
    ids=["user_info", "track_scrobble", "update_nowplaying", "track_love", "track_unlove", "get_session_key"],
)
async def test_every_post_with_sk_or_token_carries_a_correct_api_sig(
    pedidos: LastFM, chamar: Callable[[LastFM], Awaitable[Any]]
) -> None:
    await chamar(pedidos)

    ((metodo, _, kwargs),) = Pedidos.chamadas
    corpo = kwargs["data"]
    assert metodo == "POST" and ("sk" in corpo or "token" in corpo)
    assert corpo.get("api_sig") == assinatura_esperada(corpo, pedidos.api_secret)

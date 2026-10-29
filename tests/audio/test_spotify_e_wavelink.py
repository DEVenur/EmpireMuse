"""F3-3 / KI-16 … KI-23 — testes RED de Spotify, resolução de faixas e wavelink.

Sem rede, sem Discord e sem ``.env`` real: o aiohttp é substituído por uma sessão falsa, o cache do Spotify vai para
``tmp_path`` e nenhum teste sobe Java nem chama ``setup()``. Valores com cara de segredo são montados em tempo de
execução (``_valor_falso``); nenhum literal de token entra no código.

Convenção: ``test_guarda_*`` são testes de caracterização que PASSAM hoje e precisam continuar passando depois das
correções; os demais falham hoje pelo motivo descrito na docstring.
"""

import asyncio
import logging
import os
import re
import secrets
import stat
import tempfile
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qsl, urlsplit

import pytest
from aiohttp import ClientResponseError, RequestInfo
from multidict import CIMultiDict
from yarl import URL

from empiremuse.utils.music.audio_sources import spotify
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.music.models import LavalinkPlayer, LavalinkTrack

pytestmark = pytest.mark.regression

API_SPOTIFY = "https://api.spotify.com/v1"
TAMANHO_PAGINA = 100


def _valor_falso(prefixo: str = "falso") -> str:
    """Valor único e sem formato de credencial real, montado só em tempo de execução."""
    return f"{prefixo}-{secrets.token_hex(6)}"


# ---------------------------------------------------------------------------------------------------------------------
# Rede falsa do Spotify (substitui ``ClientSession`` do módulo)
# ---------------------------------------------------------------------------------------------------------------------


class _RespostaFalsa:
    def __init__(self, status: int = 200, payload: dict | None = None, texto: str = "", url: str = API_SPOTIFY):
        self.status = status
        self._payload = payload if payload is not None else {}
        self._texto = texto
        self.url = URL(url)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return self._texto

    def raise_for_status(self):
        if self.status >= 400:
            info = RequestInfo(url=self.url, method="GET", headers=CIMultiDict(), real_url=self.url)
            raise ClientResponseError(info, (), status=self.status, message=self._texto)


class _RedeFalsa:
    """Registra as chamadas GET/POST e responde por callbacks; nenhuma conexão real é aberta."""

    def __init__(self, ao_get=None, ao_post=None):
        self.ao_get = ao_get or (lambda url, params: _RespostaFalsa())
        self.ao_post = ao_post or (lambda url, data: _RespostaFalsa())
        self.gets: list[tuple[str, dict | None]] = []
        self.cabecalhos: list[dict | None] = []
        self.posts: list[str] = []

    def __call__(self, *args, **kwargs):  # substitui ClientSession(...)
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url, headers=None, params=None, **kwargs):
        self.gets.append((url, params))
        self.cabecalhos.append(headers)
        return self.ao_get(url, params)

    def post(self, url, headers=None, data=None, **kwargs):
        self.posts.append(url)
        return self.ao_post(url, data)


@pytest.fixture
def cache_isolado(tmp_path, monkeypatch):
    """Isola todo lugar onde o cache do token poderia ir: RUNTIME_DIR (via EMPIREMUSE_HOME), cwd e o tmp do sistema.

    Nada aqui fixa o nome nem o local do arquivo: os testes o encontram com ``_arquivo_do_cache``.
    """
    pastas = SimpleNamespace(runtime=tmp_path / "runtime", sistema=tmp_path / "sistema", cwd=tmp_path / "cwd")
    for pasta in (pastas.runtime, pastas.sistema, pastas.cwd):
        pasta.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(pastas.runtime))
    monkeypatch.chdir(pastas.cwd)
    monkeypatch.setattr(tempfile, "tempdir", str(pastas.sistema))
    monkeypatch.setattr(spotify, "spotify_cache_file", str(pastas.sistema / ".spotify_cache.json"), raising=False)
    return pastas


def _arquivos(*pastas: Path) -> list[Path]:
    return [p for pasta in pastas for p in pasta.rglob("*") if p.is_file()]


def _arquivo_do_cache(pastas) -> Path:
    """O único arquivo gravado em qualquer das pastas isoladas (o cache do token), onde quer que esteja."""
    achados = _arquivos(pastas.runtime, pastas.sistema, pastas.cwd)
    assert len(achados) == 1, f"esperado exatamente 1 arquivo de cache, achei {achados}"
    return achados[0]


@pytest.fixture
def rede(monkeypatch):
    def instalar(ao_get=None, ao_post=None) -> _RedeFalsa:
        falsa = _RedeFalsa(ao_get, ao_post)
        monkeypatch.setattr(spotify, "ClientSession", falsa)
        return falsa

    return instalar


def _cliente(cache_isolado, **kwargs) -> spotify.SpotifyClient:
    return spotify.SpotifyClient(client_id=_valor_falso("id"), client_secret=_valor_falso("segredo"), **kwargs)


def _cliente_com_token_valido(cache_isolado, **kwargs) -> spotify.SpotifyClient:
    cliente = _cliente(cache_isolado, **kwargs)
    cliente.spotify_cache = {"access_token": _valor_falso("tok"), "expires_at": time.time() + 3600}
    return cliente


# ---------------------------------------------------------------------------------------------------------------------
# KI-16 / KI-17 — paginação de get_playlist_info
# ---------------------------------------------------------------------------------------------------------------------


def _playlist_falsa(total: int, falha_no_offset: tuple[int, Exception] | None = None):
    """Devolve (substituto de ``request``, offsets das páginas extras pedidas)."""
    itens = [{"track": {"id": f"faixa-{i}"}} for i in range(total)]
    offsets_pedidos: list[int] = []

    async def request(path: str, params: dict | None = None):
        partes = urlsplit(path)
        consulta = dict(parse_qsl(partes.query))
        consulta.update({k: str(v) for k, v in (params or {}).items()})

        if not partes.path.endswith("/tracks"):
            return {
                "name": "Playlist falsa",
                "images": [{"url": "https://exemplo.invalid/capa.png"}],
                "tracks": {"items": itens[:TAMANHO_PAGINA], "total": total},
            }

        offset = int(consulta["offset"])
        offsets_pedidos.append(offset)
        if falha_no_offset and offset == falha_no_offset[0]:
            raise falha_no_offset[1]
        tem_proxima = offset + TAMANHO_PAGINA < total
        proxima = f"{API_SPOTIFY}/{partes.path}?offset={offset + TAMANHO_PAGINA}" if tem_proxima else None
        return {"items": itens[offset : offset + TAMANHO_PAGINA], "next": proxima}

    return request, offsets_pedidos


def _ids(resultado: dict) -> list[str]:
    return [i["track"]["id"] for i in resultado["tracks"]["items"]]


@pytest.mark.asyncio
async def test_ki16_playlist_de_250_faixas_nao_pula_nem_duplica(cache_isolado):
    """Hoje a faixa 100 é pulada (as páginas extras cobrem 101-200 e 201-249)."""
    cliente = _cliente(cache_isolado, playlist_extra_page_limit=5)
    cliente.request, _ = _playlist_falsa(total=250)

    resultado = await cliente.get_playlist_info("abc")

    assert _ids(resultado) == [f"faixa-{i}" for i in range(250)]


@pytest.mark.asyncio
async def test_ki16_falha_em_pagina_extra_devolve_o_que_ja_veio_sem_vazar_o_erro(cache_isolado, caplog):
    """Falha na 2ª página extra: mantém as faixas já carregadas, não tenta de novo e registra aviso sem o detalhe."""
    detalhe = _valor_falso("detalhe")
    cliente = _cliente(cache_isolado, playlist_extra_page_limit=5)
    cliente.request, offsets = _playlist_falsa(total=1000, falha_no_offset=(200, RuntimeError(detalhe)))

    with caplog.at_level(logging.WARNING, logger=spotify.__name__):
        resultado = await cliente.get_playlist_info("abc")

    assert _ids(resultado) == [f"faixa-{i}" for i in range(200)]
    assert offsets == [100, 200]
    assert any("Spotify" in r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
    assert detalhe not in caplog.text


# ---------------------------------------------------------------------------------------------------------------------
# KI-18 — busca sem dupla codificação


# ---------------------------------------------------------------------------------------------------------------------
# KI-19 — cache de token
# ---------------------------------------------------------------------------------------------------------------------


def _resposta_de_token(token: str):
    return lambda url, data: _RespostaFalsa(payload={"access_token": token, "token_type": "Bearer", "expires_in": 3600})


# ---------------------------------------------------------------------------------------------------------------------
# KI-20 — erro de acesso à playlist (só o contrato da mensagem; o comportamento da API real fica com o dono)


# ---------------------------------------------------------------------------------------------------------------------
# KI-21 / KI-22 — filtro de resultados em LavalinkPlayer._process_next e get_autoqueue_tracks
# ---------------------------------------------------------------------------------------------------------------------

TITULO_ORIGINAL = "Minha Cancao Favorita Do Verao Passado"  # longo: a tag não derruba a similaridade de título
TITULO_DIFERENTE = "Zzz Qqq Xxx Www Vvv"
DURACAO_ORIGINAL = 200_000
BUSCA_FALSA = "scsearch"


def _faixa(
    titulo: str, duracao: int, id_: str, fonte: str, identificador: str | None = None, stream: bool = False
) -> LavalinkTrack:
    info = {
        "title": titulo,
        "author": "Artista Falso",
        "length": duracao,
        "identifier": identificador or id_,
        "isStream": stream,
        "uri": f"https://exemplo.invalid/{fonte}/{id_}",
        "sourceName": fonte,
        "position": 0,
        "artworkUrl": "",
    }
    return LavalinkTrack(id_=id_, info=info, requester=1)


def _original(titulo: str = TITULO_ORIGINAL) -> LavalinkTrack:
    return _faixa(titulo, DURACAO_ORIGINAL, "id-original", "youtube", identificador="abcdefghijk")


def _candidata(titulo: str, id_: str, duracao: int = DURACAO_ORIGINAL) -> LavalinkTrack:
    return _faixa(titulo, duracao, id_, "jiosaavn")


def _jogador(original: LavalinkTrack, resultados: list[LavalinkTrack]) -> LavalinkPlayer:
    """LavalinkPlayer sem ``__init__`` real: só o que os caminhos testados leem, com rede e UI substituídas."""
    jogador = object.__new__(LavalinkPlayer)
    jogador.node = SimpleNamespace(
        info={"sourceManagers": ["youtube"]},
        search_providers=[BUSCA_FALSA],
        prefer_youtube_native_playback=False,
        get_tracks=AsyncMock(return_value=list(resultados)),
        is_available=True,
    )
    jogador.bot = SimpleNamespace(
        wait_until_ready=AsyncMock(),
        pool=SimpleNamespace(partial_track_cache={}, config={}),
        spotify=None,
        last_fm=None,
        user=SimpleNamespace(id=1),
        get_color=lambda: 0,
    )
    jogador.guild = SimpleNamespace(me=SimpleNamespace(voice=object()), id=1)
    jogador.channel_id = 1
    jogador.channel_purged = True
    jogador.static = False
    jogador.text_channel = None
    jogador.idle_task = None
    jogador.controller_mode = True
    jogador.autoplay = False
    jogador.keep_connected = False
    jogador.queue = deque()
    jogador.queue_autoplay = deque(maxlen=30)
    jogador.played = deque(maxlen=20)
    jogador.failed_tracks = deque(maxlen=30)
    jogador.current = original
    jogador.last_track = original
    jogador.lastfm_artists = []
    jogador.native_yt = False
    jogador.auto_pause = False
    jogador.locked = False
    jogador.loop = False
    jogador.set_command_log = MagicMock()
    jogador.process_hint = MagicMock()
    jogador.is_last_message = MagicMock(return_value=True)
    jogador.play = AsyncMock()
    jogador.invoke_np = AsyncMock()
    jogador.process_next = AsyncMock()
    return jogador


async def _rodar_process_next(original: LavalinkTrack, resultados_por_busca: dict[str, list[LavalinkTrack]]):
    """Roda ``_process_next`` com os resultados de cada provedor de busca (na ordem do dict) e devolve o jogador."""
    jogador = _jogador(original, [])
    jogador.node.search_providers = list(resultados_por_busca)
    jogador.queue = deque([original])
    for busca, resultados in resultados_por_busca.items():
        jogador.bot.pool.partial_track_cache[f"{busca}:{original.title}"] = list(resultados)

    await jogador._process_next()

    return jogador


def _id_mandado_tocar(jogador: LavalinkPlayer) -> str | None:
    if not jogador.play.await_args:
        return None
    return jogador.play.await_args.kwargs.get("temp_id")


async def _escolhida_no_process_next(original: LavalinkTrack, resultados: list[LavalinkTrack]) -> str | None:
    """Roda ``_process_next`` e devolve o id da faixa que o player mandou tocar (``temp_id``), ou None."""
    return _id_mandado_tocar(await _rodar_process_next(original, {BUSCA_FALSA: resultados}))


# --- porque quando TODAS são descartadas o código atual ainda devolve ``tracks[0]`` (ver relatório da F3-3).


@pytest.mark.asyncio
async def test_ki22_duracao_certa_e_titulo_errado_e_descartada():
    """Hoje ``A or not B and C``: com a duração dentro da tolerância o título nem é olhado e a faixa é aceita."""
    titulo_errado = _candidata(TITULO_DIFERENTE, "titulo-errado")
    referencia = _candidata(TITULO_ORIGINAL, "referencia")

    escolhida = await _escolhida_no_process_next(_original(), [titulo_errado, referencia])

    assert escolhida == "referencia"


# ---------------------------------------------------------------------------------------------------------------------
# KI-23 — Player.change_node com identificador inexistente


# ---------------------------------------------------------------------------------------------------------------------
# KI-44 — candidatas todas descartadas pelo filtro de duração/título não podem ser tocadas
# ---------------------------------------------------------------------------------------------------------------------
# As candidatas "ruins" erram duração E título (ou são stream): o filtro atual já as descarta, então estes testes não
# dependem da correção do KI-22. O esperado é o mesmo caminho de "a busca não retornou nada": pular para a próxima.


@pytest.fixture
def sem_espera(monkeypatch):
    """``_process_next`` dorme 3 s antes de pular a faixa; os testes não esperam."""
    espera = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", espera)
    return espera


# ---------------------------------------------------------------------------------------------------------------------
# Renovação de token após 401
# ---------------------------------------------------------------------------------------------------------------------

LIMITE_DE_GETS = 6  # trava de segurança do teste: acima disso a requisição está sendo repetida sem limite


def _emissor_de_tokens():
    """Callback de POST que emite um token novo a cada renovação e guarda os emitidos."""
    emitidos: list[str] = []

    def ao_post(url, data):
        token = _valor_falso("tok")
        emitidos.append(token)
        return _RespostaFalsa(payload={"access_token": token, "token_type": "Bearer", "expires_in": 3600})

    return ao_post, emitidos


def _gets_com_status(*status: int, corpo: str = "", token_na_url: str = ""):
    """Responde aos GETs na sequência de ``status`` (repete o último); 200 devolve ``{"ok": True}``."""
    contagem = {"n": 0}

    def ao_get(url, params):
        contagem["n"] += 1
        if contagem["n"] > LIMITE_DE_GETS:
            raise AssertionError(f"mais de {LIMITE_DE_GETS} GETs: a requisição está sendo repetida sem limite")
        atual = status[min(contagem["n"], len(status)) - 1]
        if atual == 200:
            return _RespostaFalsa(payload={"ok": True})
        url_com_token = f"{API_SPOTIFY}/tracks/x?access_token={token_na_url}"
        return _RespostaFalsa(status=atual, texto=corpo, url=url_com_token)

    return ao_get


async def _requisicao_com_dois_401(cache_isolado, rede):
    """Faz uma requisição em que TODA resposta é 401; devolve (exceção, rede falsa, emitidos, token antigo, corpo, cliente)."""
    ao_post, emitidos = _emissor_de_tokens()
    cliente = _cliente_com_token_valido(cache_isolado)
    antigo = cliente.spotify_cache["access_token"]
    corpo = f"corpo-cru-{secrets.token_hex(6)}"
    falsa = rede(ao_get=_gets_com_status(401, corpo=corpo, token_na_url=antigo), ao_post=ao_post)

    with pytest.raises(Exception) as capturado:
        await cliente.get_track_info("x")

    return capturado.value, falsa, emitidos, antigo, corpo, cliente


@pytest.mark.asyncio
async def test_renovacao_de_token_erro_do_segundo_401_e_generico_e_em_portugues(cache_isolado, rede):
    erro, _, emitidos, antigo, corpo, cliente = await _requisicao_com_dois_401(cache_isolado, rede)

    assert isinstance(erro, GenericError), f"esperado GenericError, veio {type(erro).__name__}: {erro}"
    texto = erro.text
    assert "spotify" in texto.lower()
    assert any(palavra in texto.lower() for palavra in ("não", "falha", "autentic"))
    for nome, valor in {
        "token antigo": antigo,
        "token novo": emitidos[0],
        "client_secret": cliente.client_secret,
        "corpo da resposta": corpo,
    }.items():
        assert valor not in texto, f"a mensagem expõe {nome}"
    assert "access_token" not in texto
    assert "api.spotify.com" not in texto


# ---------------------------------------------------------------------------------------------------------------------
# Cache do token: local e permissão
# ---------------------------------------------------------------------------------------------------------------------
# O local não é fixado pelo nome: o arquivo é achado depois de ``get_access_token``. O RUNTIME_DIR é resolvido em tempo
# de uso (EMPIREMUSE_HOME), como nos demais módulos; um cache antigo no tmp do sistema não pode ser lido.


@pytest.mark.skipif(os.name != "posix", reason="permissões POSIX")
@pytest.mark.asyncio
@pytest.mark.parametrize("mascara", [0o000, 0o022])
async def test_cache_do_token_e_criado_com_permissao_0600(cache_isolado, rede, mascara):
    rede(ao_post=_resposta_de_token(_valor_falso("tok")))
    anterior = os.umask(mascara)
    try:
        await _cliente(cache_isolado).get_access_token()
    finally:
        os.umask(anterior)

    modo = stat.S_IMODE(_arquivo_do_cache(cache_isolado).stat().st_mode)
    assert modo == 0o600, f"permissão {modo:#o} (umask {mascara:#o})"


# ---------------------------------------------------------------------------------------------------------------------
# Cache do token: gravação segura e leitura tolerante
# ---------------------------------------------------------------------------------------------------------------------


async def _cache_gravado(cache_isolado, rede):
    """Obtém um token (gravando o cache) e devolve (cliente, arquivo do cache, rede falsa, tokens emitidos)."""
    ao_post, emitidos = _emissor_de_tokens()
    falsa = rede(ao_post=ao_post)
    cliente = _cliente(cache_isolado)
    await cliente.get_access_token()
    return cliente, _arquivo_do_cache(cache_isolado), falsa, emitidos


def _avisos(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING and r.name == spotify.__name__]


@pytest.mark.asyncio
async def test_cache_do_token_falha_na_gravacao_so_gera_aviso_e_nao_deixa_temporario(cache_isolado, rede, caplog):
    """Não consegue gravar (o destino virou um diretório): só um aviso com o nome da exceção; o token segue em memória."""
    cliente, arquivo, _, emitidos = await _cache_gravado(cache_isolado, rede)
    arquivo.unlink()
    arquivo.mkdir()

    with caplog.at_level(logging.WARNING, logger=spotify.__name__):
        await cliente.get_access_token()

    assert cliente.spotify_cache["access_token"] == emitidos[1]
    assert _arquivos(cache_isolado.runtime, cache_isolado.sistema, cache_isolado.cwd) == [], "sobrou arquivo temporário"
    assert any("Spotify" in a and re.search(r"\b\w+Error\b", a) for a in _avisos(caplog)), _avisos(caplog)
    for sensivel in (str(arquivo), emitidos[0], emitidos[1]):
        assert sensivel not in caplog.text, "o aviso expõe caminho ou token"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "modelo",
    ["[]", '{"access_token": "SEGREDO'],
    ids=["lista", "json-truncado"],
)
async def test_cache_do_token_com_conteudo_invalido_e_ignorado(cache_isolado, rede, caplog, modelo):
    _, arquivo, falsa, emitidos = await _cache_gravado(cache_isolado, rede)
    segredo = _valor_falso("segredo")
    arquivo.write_text(modelo.replace("SEGREDO", segredo), "utf-8")

    with caplog.at_level(logging.WARNING, logger=spotify.__name__):
        novo = _cliente(cache_isolado)
        obtido = await novo.get_valid_access_token()

    assert obtido == emitidos[1] and len(falsa.posts) == 2, "devia ignorar o arquivo e pedir um token novo"
    assert segredo not in caplog.text

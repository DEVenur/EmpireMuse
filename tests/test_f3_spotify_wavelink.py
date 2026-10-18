"""F3-3 / KI-16 … KI-23 — testes RED de Spotify, resolução de faixas e wavelink.

Sem rede, sem Discord e sem ``.env`` real: o aiohttp é substituído por uma sessão falsa, o cache do Spotify vai para
``tmp_path`` e nenhum teste sobe Java nem chama ``setup()``. Valores com cara de segredo são montados em tempo de
execução (``_valor_falso``); nenhum literal de token entra no código.

Convenção: ``test_guarda_*`` são testes de caracterização que PASSAM hoje e precisam continuar passando depois das
correções; os demais falham hoje pelo motivo descrito na docstring.
"""

import json
import secrets
import time
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qsl, urlsplit

import pytest
from aiohttp import ClientResponseError, RequestInfo
from multidict import CIMultiDict
from rapidfuzz import fuzz
from yarl import URL

from empiremuse.utils.music import models
from empiremuse.utils.music.audio_sources import spotify
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.music.models import LavalinkPlayer, LavalinkTrack
from empiremuse.wavelink.errors import WavelinkException
from empiremuse.wavelink.player import Player

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
        self.posts: list[str] = []

    def __call__(self, *args, **kwargs):  # substitui ClientSession(...)
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url, headers=None, params=None, **kwargs):
        self.gets.append((url, params))
        return self.ao_get(url, params)

    def post(self, url, headers=None, data=None, **kwargs):
        self.posts.append(url)
        return self.ao_post(url, data)


@pytest.fixture
def cache_isolado(tmp_path, monkeypatch):
    caminho = tmp_path / "spotify_cache.json"
    monkeypatch.setattr(spotify, "spotify_cache_file", str(caminho))
    return caminho


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


def _playlist_falsa(total: int):
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
        tem_proxima = offset + TAMANHO_PAGINA < total
        proxima = f"{API_SPOTIFY}/{partes.path}?offset={offset + TAMANHO_PAGINA}" if tem_proxima else None
        return {"items": itens[offset : offset + TAMANHO_PAGINA], "next": proxima}

    return request, offsets_pedidos


def _ids(resultado: dict) -> list[str]:
    return [i["track"]["id"] for i in resultado["tracks"]["items"]]


@pytest.mark.asyncio
async def test_ki16_segunda_pagina_comeca_no_offset_100(cache_isolado):
    """Hoje o offset inicial é 101: a faixa de índice 100 nunca é carregada."""
    cliente = _cliente(cache_isolado, playlist_extra_page_limit=5)
    cliente.request, offsets = _playlist_falsa(total=250)

    await cliente.get_playlist_info("abc")

    assert offsets[0] == 100


@pytest.mark.asyncio
async def test_ki16_playlist_de_250_faixas_nao_pula_nem_duplica(cache_isolado):
    """Hoje a faixa 100 é pulada (as páginas extras cobrem 101-200 e 201-249)."""
    cliente = _cliente(cache_isolado, playlist_extra_page_limit=5)
    cliente.request, _ = _playlist_falsa(total=250)

    resultado = await cliente.get_playlist_info("abc")

    assert _ids(resultado) == [f"faixa-{i}" for i in range(250)]


@pytest.mark.asyncio
@pytest.mark.parametrize("limite", [1, 2, 3])
async def test_ki17_carrega_no_maximo_o_limite_de_paginas_extras(cache_isolado, limite):
    """Hoje ``page_count <= limite`` é avaliado depois de carregar a página: vêm ``limite + 2`` páginas extras.

    Atenção: trocar só ``<=`` por ``<`` ainda carrega ``limite + 1``; o teste exige exatamente ``limite``.
    """
    cliente = _cliente(cache_isolado, playlist_extra_page_limit=limite)
    cliente.request, offsets = _playlist_falsa(total=1000)

    await cliente.get_playlist_info("abc")

    assert len(offsets) == limite


@pytest.mark.asyncio
async def test_guarda_limite_zero_nao_pede_paginas_extras(cache_isolado):
    cliente = _cliente(cache_isolado, playlist_extra_page_limit=0)
    cliente.request, offsets = _playlist_falsa(total=1000)

    resultado = await cliente.get_playlist_info("abc")

    assert offsets == []
    assert len(_ids(resultado)) == TAMANHO_PAGINA


@pytest.mark.asyncio
async def test_guarda_playlist_curta_nao_pede_paginas_extras(cache_isolado):
    cliente = _cliente(cache_isolado, playlist_extra_page_limit=5)
    cliente.request, offsets = _playlist_falsa(total=40)

    resultado = await cliente.get_playlist_info("abc")

    assert offsets == []
    assert len(_ids(resultado)) == 40


# ---------------------------------------------------------------------------------------------------------------------
# KI-18 — busca sem dupla codificação
# ---------------------------------------------------------------------------------------------------------------------


def _busca_vazia(url, params):
    return _RespostaFalsa(payload={"tracks": {"items": []}})


@pytest.mark.asyncio
@pytest.mark.parametrize("busca", ["faixa com espaço", "canção lenta", "rock & roll", "AC/DC & Co: ação+reação"])
async def test_ki18_busca_chega_ao_spotify_com_a_query_original(cache_isolado, rede, busca):
    """Hoje ``quote(query)`` é aplicado e o aiohttp codifica de novo: o Spotify recebe ``a%20b`` literal."""
    falsa = rede(ao_get=_busca_vazia)
    cliente = _cliente_com_token_valido(cache_isolado)

    await cliente.track_search(busca)

    url, params = falsa.gets[0]
    efetiva = URL(url).extend_query(params or {})  # mesma composição que o aiohttp faz antes de enviar
    assert efetiva.query["q"] == busca


@pytest.mark.asyncio
async def test_ki18_params_levam_a_query_crua(cache_isolado, rede):
    """A codificação é responsabilidade só do aiohttp: ``params['q']`` tem de ser o texto cru."""
    falsa = rede(ao_get=_busca_vazia)
    cliente = _cliente_com_token_valido(cache_isolado)

    await cliente.track_search("rock & roll")

    _, params = falsa.gets[0]
    assert params is not None and params["q"] == "rock & roll"


@pytest.mark.asyncio
async def test_guarda_busca_pede_apenas_faixas_com_limite_10(cache_isolado, rede):
    falsa = rede(ao_get=_busca_vazia)
    cliente = _cliente_com_token_valido(cache_isolado)

    await cliente.track_search("qualquer")

    url, params = falsa.gets[0]
    efetiva = URL(url).extend_query(params or {})
    assert efetiva.path.endswith("/search")
    assert efetiva.query["type"] == "track"
    assert efetiva.query["limit"] == "10"


# ---------------------------------------------------------------------------------------------------------------------
# KI-19 — cache de token
# ---------------------------------------------------------------------------------------------------------------------


def _resposta_de_token(token: str):
    return lambda url, data: _RespostaFalsa(payload={"access_token": token, "token_type": "Bearer", "expires_in": 3600})


@pytest.mark.asyncio
async def test_guarda_cache_vazio_obtem_token_novo_sem_key_error(cache_isolado, rede):
    """Já passa hoje: ``get_valid_access_token`` usa ``.get("expires_at", 0)`` desde a F3-1."""
    token = _valor_falso("tok")
    falsa = rede(ao_post=_resposta_de_token(token))
    cliente = _cliente(cache_isolado)
    assert cliente.spotify_cache == {}

    obtido = await cliente.get_valid_access_token()

    assert obtido == token
    assert len(falsa.posts) == 1


@pytest.mark.asyncio
async def test_ki19_token_novo_grava_a_chave_type_e_nao_tyoe(cache_isolado, rede):
    """Hoje a chave é gravada como ``tyoe`` (typo)."""
    rede(ao_post=_resposta_de_token(_valor_falso("tok")))
    cliente = _cliente(cache_isolado)

    await cliente.get_access_token()

    assert cliente.spotify_cache.get("type") == "api"
    assert "tyoe" not in cliente.spotify_cache


@pytest.mark.asyncio
async def test_ki19_arquivo_de_cache_persistido_usa_a_chave_type(cache_isolado, rede):
    """Hoje o JSON gravado em disco também carrega ``tyoe``."""
    rede(ao_post=_resposta_de_token(_valor_falso("tok")))
    cliente = _cliente(cache_isolado)

    await cliente.get_access_token()

    gravado = json.loads(cache_isolado.read_text("utf-8"))
    assert gravado.get("type") == "api"
    assert "tyoe" not in gravado


@pytest.mark.asyncio
async def test_guarda_cache_antigo_com_tyoe_continua_valido(cache_isolado, rede):
    """Um cache gravado por versão anterior (com ``tyoe``) ainda vale: o token é reaproveitado, sem pedir outro."""
    token = _valor_falso("tok")
    cache_isolado.write_text(
        json.dumps({"access_token": token, "tyoe": "api", "expires_at": time.time() + 3600}), "utf-8"
    )
    falsa = rede(ao_post=_resposta_de_token(_valor_falso("outro")))
    cliente = _cliente(cache_isolado)

    obtido = await cliente.get_valid_access_token()

    assert obtido == token
    assert falsa.posts == []


@pytest.mark.asyncio
async def test_guarda_cache_expirado_obtem_token_novo(cache_isolado, rede):
    novo = _valor_falso("tok")
    falsa = rede(ao_post=_resposta_de_token(novo))
    cliente = _cliente(cache_isolado)
    cliente.spotify_cache = {"access_token": _valor_falso("velho"), "expires_at": time.time() - 10}

    obtido = await cliente.get_valid_access_token()

    assert obtido == novo
    assert len(falsa.posts) == 1


# ---------------------------------------------------------------------------------------------------------------------
# KI-20 — erro de acesso à playlist (só o contrato da mensagem; o comportamento da API real fica com o dono)
# ---------------------------------------------------------------------------------------------------------------------


async def _erro_gerado(cache_isolado, rede, status: int, com_token_na_url: bool):
    """Executa get_playlist_info contra um erro HTTP e devolve (exceção capturada, valores sensíveis usados)."""
    token = _valor_falso("tok")
    corpo = f"corpo-cru-{secrets.token_hex(6)} bearer {token}"
    sufixo = f"?access_token={token}" if com_token_na_url else ""
    url = f"{API_SPOTIFY}/playlists/abc{sufixo}"
    rede(ao_get=lambda u, params: _RespostaFalsa(status=status, texto=corpo, url=url))
    cliente = _cliente(cache_isolado)
    cliente.spotify_cache = {"access_token": token, "expires_at": time.time() + 3600}

    with pytest.raises(Exception) as capturado:
        await cliente.get_playlist_info("abc")

    return capturado.value, {"token": token, "corpo": corpo, "client_secret": cliente.client_secret}


@pytest.mark.asyncio
async def test_ki20_403_na_playlist_gera_generic_error_em_portugues(cache_isolado, rede):
    """Hoje o 403 cai em ``raise_for_status()`` e sobe ``ClientResponseError`` em inglês, não ``GenericError``."""
    erro, _ = await _erro_gerado(cache_isolado, rede, 403, com_token_na_url=False)

    assert isinstance(erro, GenericError), f"esperado GenericError, veio {type(erro).__name__}"
    assert "não" in erro.text.lower()


@pytest.mark.asyncio
async def test_guarda_404_na_playlist_gera_generic_error_em_portugues(cache_isolado, rede):
    erro, _ = await _erro_gerado(cache_isolado, rede, 404, com_token_na_url=False)

    assert isinstance(erro, GenericError)
    assert "não" in erro.text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404])
async def test_ki20_erro_da_playlist_nao_expoe_credenciais_url_com_token_nem_corpo_cru(cache_isolado, rede, status):
    """403: hoje a exceção crua carrega URL e corpo. 404: hoje a mensagem reaproveita a URL inteira da requisição."""
    erro, sensiveis = await _erro_gerado(cache_isolado, rede, status, com_token_na_url=True)

    assert isinstance(erro, GenericError), f"esperado GenericError, veio {type(erro).__name__}"
    for nome, valor in sensiveis.items():
        assert valor not in erro.text, f"a mensagem expõe {nome}"
    assert "access_token" not in erro.text
    assert "api.spotify.com" not in erro.text


# ---------------------------------------------------------------------------------------------------------------------
# KI-21 / KI-22 — filtro de resultados em LavalinkPlayer._process_next e get_autoqueue_tracks
# ---------------------------------------------------------------------------------------------------------------------

TITULO_ORIGINAL = "Minha Cancao Favorita Do Verao Passado"  # longo: a tag não derruba a similaridade de título
TITULO_DIFERENTE = "Zzz Qqq Xxx Www Vvv"
DURACAO_ORIGINAL = 200_000
DURACAO_MUITO_DIFERENTE = DURACAO_ORIGINAL + 90_000
TOLERANCIA_MS = 7_000
LIMIAR_TITULO = 75
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


async def _escolhida_no_autoqueue(original: LavalinkTrack, resultados: list[LavalinkTrack]) -> LavalinkTrack | None:
    return await _jogador(original, resultados).get_autoqueue_tracks()


def _titulo_com_tag(tag: str) -> str:
    titulo = f"{TITULO_ORIGINAL} ({tag})"
    assert fuzz.token_set_ratio(titulo, TITULO_ORIGINAL) >= LIMIAR_TITULO, "a tag não pode derrubar o filtro de título"
    return titulo


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", models.exclude_tags)
async def test_ki21_process_next_prefere_o_original_ao_resultado_com_a_tag(tag):
    """Hoje ``if not [lista]`` nunca é verdadeiro: o resultado com a tag (o primeiro) é escolhido."""
    com_tag = _candidata(_titulo_com_tag(tag), "com-tag")
    sem_tag = _candidata(TITULO_ORIGINAL, "sem-tag")

    escolhida = await _escolhida_no_process_next(_original(), [com_tag, sem_tag])

    assert escolhida == "sem-tag"


@pytest.mark.asyncio
async def test_ki21_process_next_filtro_de_tag_mantem_todos_os_resultados_sem_tag_e_nao_so_o_primeiro():
    """O ``break`` do laço de tags guarda só o 1º resultado sem tag: ao ligar o filtro, o filtro de duração/título
    ficaria sem opção e a faixa descartada ainda seria escolhida. Hoje falha porque o resultado com tag é o escolhido."""
    com_tag = _candidata(_titulo_com_tag("remix"), "com-tag")
    sem_tag_ruim = _candidata(TITULO_DIFERENTE, "sem-tag-ruim", DURACAO_MUITO_DIFERENTE)
    sem_tag_boa = _candidata(TITULO_ORIGINAL, "sem-tag-boa")

    escolhida = await _escolhida_no_process_next(_original(), [com_tag, sem_tag_ruim, sem_tag_boa])

    assert escolhida == "sem-tag-boa"


@pytest.mark.asyncio
async def test_guarda_process_next_sem_tag_em_nenhum_resultado_mantem_a_ordem():
    primeira = _candidata(TITULO_ORIGINAL, "primeira")
    segunda = _candidata(TITULO_ORIGINAL, "segunda")

    escolhida = await _escolhida_no_process_next(_original(), [primeira, segunda])

    assert escolhida == "primeira"


@pytest.mark.asyncio
async def test_guarda_process_next_nao_penaliza_a_tag_quando_o_original_ja_a_tem():
    titulo = _titulo_com_tag("remix")
    com_tag = _candidata(titulo, "com-tag")
    sem_tag = _candidata(TITULO_ORIGINAL, "sem-tag")

    escolhida = await _escolhida_no_process_next(_original(titulo), [com_tag, sem_tag])

    assert escolhida == "com-tag"


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", models.exclude_tags_2)
async def test_ki21_autoqueue_prefere_o_original_ao_resultado_com_a_tag(tag):
    """Hoje o filtro de ``exclude_tags_2`` em get_autoqueue_tracks também nunca executa."""
    com_tag = _candidata(_titulo_com_tag(tag), "com-tag")
    sem_tag = _candidata(TITULO_ORIGINAL, "sem-tag")

    escolhida = await _escolhida_no_autoqueue(_original(), [com_tag, sem_tag])

    assert escolhida is not None and escolhida.id == "sem-tag"


@pytest.mark.asyncio
async def test_guarda_autoqueue_sem_tag_em_nenhum_resultado_mantem_a_ordem():
    primeira = _candidata(TITULO_ORIGINAL, "primeira")
    segunda = _candidata(TITULO_ORIGINAL, "segunda")

    escolhida = await _escolhida_no_autoqueue(_original(), [primeira, segunda])

    assert escolhida is not None and escolhida.id == "primeira"


# --- KI-22: a faixa só vale se duração E título conferem. Cada caso põe a candidata ao lado de uma referência segura,
# --- porque quando TODAS são descartadas o código atual ainda devolve ``tracks[0]`` (ver relatório da F3-3).


def test_guarda_dados_de_ki22_titulo_diferente_fica_abaixo_do_limiar():
    assert fuzz.token_set_ratio(TITULO_DIFERENTE, TITULO_ORIGINAL) < LIMIAR_TITULO
    assert fuzz.token_set_ratio(TITULO_ORIGINAL, TITULO_ORIGINAL) >= LIMIAR_TITULO


@pytest.mark.asyncio
async def test_ki22_duracao_certa_e_titulo_errado_e_descartada():
    """Hoje ``A or not B and C``: com a duração dentro da tolerância o título nem é olhado e a faixa é aceita."""
    titulo_errado = _candidata(TITULO_DIFERENTE, "titulo-errado")
    referencia = _candidata(TITULO_ORIGINAL, "referencia")

    escolhida = await _escolhida_no_process_next(_original(), [titulo_errado, referencia])

    assert escolhida == "referencia"


@pytest.mark.asyncio
@pytest.mark.parametrize("delta", [TOLERANCIA_MS, TOLERANCIA_MS + 1, 60_000, -TOLERANCIA_MS, -(TOLERANCIA_MS + 1)])
async def test_ki22_titulo_certo_e_duracao_fora_da_tolerancia_e_descartada(delta):
    """Hoje o título parecido salva a faixa mesmo com a duração fora da tolerância de 7 s."""
    duracao_errada = _candidata(TITULO_ORIGINAL, "duracao-errada", DURACAO_ORIGINAL + delta)
    referencia = _candidata(TITULO_ORIGINAL, "referencia")

    escolhida = await _escolhida_no_process_next(_original(), [duracao_errada, referencia])

    assert escolhida == "referencia"


@pytest.mark.asyncio
async def test_guarda_ki22_duracao_e_titulo_conferem_a_faixa_e_aceita():
    ruim = _candidata(TITULO_DIFERENTE, "ruim", DURACAO_MUITO_DIFERENTE)
    boa = _candidata(TITULO_ORIGINAL, "boa")

    escolhida = await _escolhida_no_process_next(_original(), [ruim, boa])

    assert escolhida == "boa"


@pytest.mark.asyncio
async def test_guarda_ki22_duracao_e_titulo_errados_a_faixa_e_descartada():
    ruim = _candidata(TITULO_DIFERENTE, "ruim", DURACAO_MUITO_DIFERENTE)
    referencia = _candidata(TITULO_ORIGINAL, "referencia")

    escolhida = await _escolhida_no_process_next(_original(), [ruim, referencia])

    assert escolhida == "referencia"


@pytest.mark.asyncio
@pytest.mark.parametrize("delta", [0, 1, TOLERANCIA_MS - 1, -(TOLERANCIA_MS - 1)])
async def test_guarda_ki22_tolerancia_dentro_de_7s_aceita_com_titulo_certo(delta):
    """Caracteriza a tolerância atual: aceita enquanto ``|delta| < 7000`` ms (os extremos ficam de fora)."""
    ruim = _candidata(TITULO_DIFERENTE, "ruim", DURACAO_MUITO_DIFERENTE)
    dentro = _candidata(TITULO_ORIGINAL, "dentro", DURACAO_ORIGINAL + delta)

    escolhida = await _escolhida_no_process_next(_original(), [ruim, dentro])

    assert escolhida == "dentro"


@pytest.mark.asyncio
@pytest.mark.parametrize("delta", [TOLERANCIA_MS, -TOLERANCIA_MS])
async def test_guarda_ki22_tolerancia_extremo_de_7s_e_descartado_com_titulo_errado(delta):
    no_extremo = _candidata(TITULO_DIFERENTE, "no-extremo", DURACAO_ORIGINAL + delta)
    referencia = _candidata(TITULO_ORIGINAL, "referencia")

    escolhida = await _escolhida_no_process_next(_original(), [no_extremo, referencia])

    assert escolhida == "referencia"


@pytest.mark.asyncio
async def test_guarda_ki22_titulo_exatamente_no_limiar_de_75_ainda_confere():
    """``token_set_ratio < 75`` descarta; exatamente 75 ainda confere (par de uma palavra: sem interseção de tokens)."""
    base, no_limiar = "abcd", "abce"
    assert fuzz.token_set_ratio(base, no_limiar) == LIMIAR_TITULO
    original = _faixa(base, DURACAO_ORIGINAL, "id-original", "youtube", identificador="abcdefghijk")
    ruim = _candidata(TITULO_DIFERENTE, "ruim", DURACAO_MUITO_DIFERENTE)
    candidata = _candidata(no_limiar, "no-limiar")

    escolhida = await _escolhida_no_process_next(original, [ruim, candidata])

    assert escolhida == "no-limiar"


@pytest.mark.asyncio
async def test_guarda_ki22_titulo_logo_abaixo_do_limiar_de_75_e_descartado():
    """O vizinho de baixo do limiar (71,4) com a duração certa não passa: o limiar não foi afrouxado."""
    base, abaixo = "abcdefg", "abcdexy"
    assert fuzz.token_set_ratio(base, abaixo) < LIMIAR_TITULO
    original = _faixa(base, DURACAO_ORIGINAL, "id-original", "youtube", identificador="abcdefghijk")
    abaixo_do_limiar = _candidata(abaixo, "abaixo")
    referencia = _candidata(base, "referencia")

    escolhida = await _escolhida_no_process_next(original, [abaixo_do_limiar, referencia])

    assert escolhida == "referencia"


# --- KI-22 (métrica): prefixo de artista e sufixos do SoundCloud/YouTube não podem reprovar o título. Com
# --- ``token_sort_ratio`` estes pares medem 55-65 (< 75) e, com ``or``, a faixa certa seria PULADA (regressão do KI-44).

TITULOS_QUE_CONFEREM = {
    "prefixo-de-artista": ("Shape of You", "Ed Sheeran - Shape of You"),
    "prefixo-e-sufixo-official-music-video": (
        "Never Gonna Give You Up",
        "Rick Astley - Never Gonna Give You Up (Official Music Video)",
    ),
    "sufixo-official-video": ("Shape of You", "Shape of You (Official Video)"),
    "sufixo-official-audio-entre-colchetes": ("Shape of You", "Shape of You [Official Audio]"),
    "sufixo-remastered": ("Bohemian Rhapsody", "Bohemian Rhapsody - Remastered 2011"),
    "original-com-sufixo-e-candidata-sem": ("Bohemian Rhapsody - Remastered 2011", "Bohemian Rhapsody"),
}

TITULOS_DE_OUTRA_MUSICA = {
    "mesmo-artista-outra-faixa": ("Shape of You", "Ed Sheeran - Perfect"),
    "outra-faixa-com-prefixo-de-artista": ("Bohemian Rhapsody", "Queen - Another One Bites the Dust"),
}


def test_guarda_dados_de_ki22_titulos_que_conferem_so_passam_com_token_set_ratio():
    for original, candidata in TITULOS_QUE_CONFEREM.values():
        assert fuzz.token_sort_ratio(original, candidata) < LIMIAR_TITULO, (original, candidata)
        assert fuzz.token_set_ratio(original, candidata) >= LIMIAR_TITULO, (original, candidata)


def test_guarda_dados_de_ki22_titulos_de_outra_musica_ficam_abaixo_do_limiar():
    for original, candidata in TITULOS_DE_OUTRA_MUSICA.values():
        assert fuzz.token_set_ratio(original, candidata) < LIMIAR_TITULO, (original, candidata)


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", TITULOS_QUE_CONFEREM)
async def test_ki22_titulo_com_prefixo_ou_sufixo_e_duracao_certa_e_aceito(caso, sem_espera):
    """Hoje ``token_sort_ratio`` reprova o par e a faixa é pulada (``None``) em vez de a candidata certa tocar."""
    titulo_original, titulo_candidato = TITULOS_QUE_CONFEREM[caso]
    ruim = _candidata(TITULO_DIFERENTE, "ruim", DURACAO_MUITO_DIFERENTE)
    certa = _candidata(titulo_candidato, "certa")

    escolhida = await _escolhida_no_process_next(_original(titulo_original), [ruim, certa])

    assert escolhida == "certa"


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", TITULOS_DE_OUTRA_MUSICA)
async def test_guarda_ki22_titulo_de_outra_musica_com_duracao_certa_e_descartado(caso):
    titulo_original, titulo_outra = TITULOS_DE_OUTRA_MUSICA[caso]
    outra = _candidata(titulo_outra, "outra")
    referencia = _candidata(titulo_original, "referencia")

    escolhida = await _escolhida_no_process_next(_original(titulo_original), [outra, referencia])

    assert escolhida == "referencia"


@pytest.mark.asyncio
@pytest.mark.parametrize("delta", [TOLERANCIA_MS, -TOLERANCIA_MS, 60_000])
async def test_guarda_ki22_titulo_com_prefixo_e_sufixo_mas_duracao_fora_da_tolerancia_e_descartado(delta):
    """Trocar a métrica do título não pode afrouxar a duração: as duas condições continuam obrigatórias."""
    titulo_original, titulo_candidato = TITULOS_QUE_CONFEREM["prefixo-e-sufixo-official-music-video"]
    fora = _candidata(titulo_candidato, "fora", DURACAO_ORIGINAL + delta)
    referencia = _candidata(titulo_original, "referencia")

    escolhida = await _escolhida_no_process_next(_original(titulo_original), [fora, referencia])

    assert escolhida == "referencia"


# ---------------------------------------------------------------------------------------------------------------------
# KI-23 — Player.change_node com identificador inexistente
# ---------------------------------------------------------------------------------------------------------------------


def _player_com_cliente(no_encontrado) -> Player:
    cliente = SimpleNamespace(get_node=MagicMock(return_value=no_encontrado))
    node_atual = SimpleNamespace(_client=cliente, players={}, version=4)
    return Player(bot=MagicMock(), guild_id=1, node=node_atual)


@pytest.mark.asyncio
async def test_ki23_change_node_com_identificador_inexistente_gera_a_mensagem_amigavel():
    """Hoje ``node.is_available`` é lido antes de ``if not node``: o resultado é ``AttributeError`` em ``None``."""
    player = _player_com_cliente(no_encontrado=None)

    with pytest.raises(WavelinkException, match="No Nodes matching identifier") as capturado:
        await player.change_node("nao-existe")

    assert "nao-existe" in str(capturado.value)


@pytest.mark.asyncio
async def test_guarda_change_node_com_node_indisponivel_mantem_a_mensagem_de_indisponivel():
    indisponivel = SimpleNamespace(is_available=False)
    player = _player_com_cliente(no_encontrado=indisponivel)

    with pytest.raises(WavelinkException, match="Node unavailable") as capturado:
        await player.change_node("fora-do-ar")

    assert "fora-do-ar" in str(capturado.value)


# ---------------------------------------------------------------------------------------------------------------------
# KI-44 — candidatas todas descartadas pelo filtro de duração/título não podem ser tocadas
# ---------------------------------------------------------------------------------------------------------------------
# As candidatas "ruins" erram duração E título (ou são stream): o filtro atual já as descarta, então estes testes não
# dependem da correção do KI-22. O esperado é o mesmo caminho de "a busca não retornou nada": pular para a próxima.


@pytest.fixture
def sem_espera(monkeypatch):
    """``_process_next`` dorme 3 s antes de pular a faixa; os testes não esperam."""
    espera = AsyncMock()
    monkeypatch.setattr(models.asyncio, "sleep", espera)
    return espera


def _ruim(id_: str) -> LavalinkTrack:
    return _candidata(TITULO_DIFERENTE, id_, DURACAO_MUITO_DIFERENTE)


def _stream(id_: str) -> LavalinkTrack:
    return _faixa(TITULO_ORIGINAL, DURACAO_ORIGINAL, id_, "jiosaavn", stream=True)


def _desfecho(jogador: LavalinkPlayer) -> tuple:
    """Resumo observável: (id mandado tocar, chamadas a process_next, ids em played, native_yt)."""
    return (
        _id_mandado_tocar(jogador),
        jogador.process_next.await_count,
        [t.id for t in jogador.played],
        jogador.native_yt,
    )


DESFECHO_FAIXA_PULADA = (None, 1, ["id-original"], True)

CENARIOS_TODAS_DESCARTADAS = {
    "uma-candidata": lambda: {BUSCA_FALSA: [_ruim("ruim-1")]},
    "varias-candidatas": lambda: {BUSCA_FALSA: [_ruim("ruim-1"), _ruim("ruim-2"), _ruim("ruim-3")]},
    "so-stream": lambda: {BUSCA_FALSA: [_stream("stream-1")]},
    "dois-provedores-ambos-descartam": lambda: {BUSCA_FALSA: [_ruim("ruim-1")], "dzsearch": [_ruim("ruim-2")]},
}


@pytest.mark.asyncio
async def test_guarda_ki44_busca_sem_resultado_pula_a_faixa(sem_espera):
    """Caracteriza o caminho esperado: sem resultados, nada toca, a faixa vai para ``played`` e a fila avança."""
    jogador = await _rodar_process_next(_original(), {BUSCA_FALSA: []})

    assert _desfecho(jogador) == DESFECHO_FAIXA_PULADA
    jogador.play.assert_not_awaited()


@pytest.mark.asyncio
async def test_guarda_ki44_sem_resultado_em_dois_provedores_pula_a_faixa(sem_espera):
    jogador = await _rodar_process_next(_original(), {BUSCA_FALSA: [], "dzsearch": []})

    assert _desfecho(jogador) == DESFECHO_FAIXA_PULADA


@pytest.mark.asyncio
async def test_guarda_ki44_descartada_no_primeiro_provedor_e_ultimo_sem_resultado_pula_a_faixa(sem_espera):
    jogador = await _rodar_process_next(_original(), {BUSCA_FALSA: [_ruim("ruim-1")], "dzsearch": []})

    assert _desfecho(jogador) == DESFECHO_FAIXA_PULADA


@pytest.mark.asyncio
@pytest.mark.parametrize("cenario", CENARIOS_TODAS_DESCARTADAS)
async def test_ki44_todas_as_candidatas_descartadas_pulam_a_faixa_como_se_nao_houvesse_resultado(cenario, sem_espera):
    """Hoje ``tracks`` fica com a lista bruta do último provedor e ``tracks[0]`` (descartada) é mandada tocar."""
    jogador = await _rodar_process_next(_original(), CENARIOS_TODAS_DESCARTADAS[cenario]())

    assert _desfecho(jogador) == DESFECHO_FAIXA_PULADA, f"tocou a faixa descartada: {_id_mandado_tocar(jogador)!r}"


@pytest.mark.asyncio
async def test_guarda_ki44_com_uma_boa_entre_as_descartadas_a_boa_e_escolhida(sem_espera):
    jogador = await _rodar_process_next(
        _original(), {BUSCA_FALSA: [_ruim("ruim-1"), _candidata(TITULO_ORIGINAL, "boa"), _ruim("ruim-2")]}
    )

    assert _id_mandado_tocar(jogador) == "boa"
    jogador.process_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_guarda_ki44_descartadas_no_primeiro_provedor_e_boa_no_ultimo_a_boa_e_escolhida(sem_espera):
    resultados = {BUSCA_FALSA: [_ruim("ruim-1")], "dzsearch": [_ruim("ruim-2"), _candidata(TITULO_ORIGINAL, "boa")]}

    jogador = await _rodar_process_next(_original(), resultados)

    assert _id_mandado_tocar(jogador) == "boa"
    jogador.process_next.assert_not_awaited()

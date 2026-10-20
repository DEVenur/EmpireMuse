"""F3-6b, etapa 5 (RED, commit 1) — as faixas dentro da sessão: URLs (condição 3 do 5.1, R1), fonte ``local`` e faixa ruim.

Vale para as 4 listas (``queue``, ``played``, ``queue_autoplay``, ``failed_tracks``), na LEITURA (documento plantado) e na
GRAVAÇÃO:

* R1: ``uri``, ``artworkUrl``, ``playlist.url``/``thumb`` e ``extra.album.url`` inválidos viram ``""`` e a faixa FICA (``None``
  quebra a construção da faixa no YouTube e no SoundCloud; chave ausente quebra ``.url``/``PartialTrack.uri``); ``uri`` ausente ou
  ``None`` também vira ``""``; em ``pluginInfo`` a chave que termina em ``Url``/``url`` com valor inválido SAI;
  ``listen_along_invite`` inválido sai (a sessão fica sem convite);
* a faixa com ``sourceName == "local"`` é recusada (a faixa, não a sessão); ``"http"`` (anexo do Discord) continua aceito;
* faixa que o esquema recusa é descartada e a sessão segue, sem o conteúdo no log;
* a faixa reidratada pelo ``process_track_cls`` real constrói e tem ``.uri``/``.url`` texto (as 18 fontes que o QA mediu).
"""

import copy
import logging
from types import SimpleNamespace

import pytest

from empiremuse.utils.client import BotPool
from tests.helpers_f3_6b_legado import SEGREDO
from tests.helpers_f3_6b_serializacao import falha
from tests.helpers_f3_6b_sessao import bruto, decodificar, faixa_info, session, sessao_minima

LISTAS = ["queue", "played", "queue_autoplay", "failed_tracks"]
URLS_RUINS = [
    "file:///etc/passwd",
    "javascript:alert(1)",
    "ftp://exemplo.invalid/x",
    "https://usuario:senha@exemplo.invalid/",
    "https://exemplo.invalid/<x>",
    "https://exemplo.invalid/a)b",
    "https://exemplo.invalid/[x]",
    "oi",
    "/home/x/y.mp3",
    "https://exemplo.invalid/ com espaço",
    "https://exemplo.invalid/@everyone",
]
URLS_BOAS = [
    "https://exemplo.invalid/x?a=1&b=2",
    "http://exemplo.invalid/musica.mp3",
    "https://www.youtube.com/watch?v=abcdefghijk",
]


def lida_info(info: dict, lista: str = "queue") -> dict:
    """A faixa ``info`` depois de ler um documento PLANTADO (JSON escrito à mão, sem passar pelo ``encode_session``)."""
    return decodificar(bruto(**{lista: [info]}))[lista][0]


def gravada_info(info: dict, lista: str = "queue") -> dict:
    """A faixa ``info`` depois de GRAVAR uma sessão com ela na memória e reler."""
    dados = sessao_minima(**{lista: [info]})
    return session.decode_session(session.encode_session(dados))[lista][0]


def lida(lista="queue", **info) -> dict:
    return lida_info(faixa_info(0, **info), lista)


def gravada(lista="queue", **info) -> dict:
    return gravada_info(faixa_info(0, **info), lista)


LEITORES = pytest.mark.parametrize("ler", [lida, gravada], ids=["leitura", "gravacao"])


# ============================================================================ R1: a URL inválida vira "" e a faixa fica


class TestUri:
    @LEITORES
    @pytest.mark.parametrize("lista", LISTAS)
    @pytest.mark.parametrize("url", URLS_RUINS)
    def test_uri_invalida_vira_texto_vazio_e_a_faixa_fica(self, ler, lista, url):
        faixa = ler(lista, uri=url)
        assert faixa["uri"] == "" and faixa["title"] == "Música 0" and faixa["id"]

    @LEITORES
    @pytest.mark.parametrize("url", URLS_BOAS)
    def test_uri_valida_passa_sem_mudar(self, ler, url):
        assert ler(uri=url)["uri"] == url

    @LEITORES
    @pytest.mark.parametrize("valor", [None, 123, [], {}, True], ids=["none", "numero", "lista", "dict", "bool"])
    def test_uri_que_nao_e_texto_vira_texto_vazio(self, ler, valor):
        assert ler(uri=valor)["uri"] == ""

    @LEITORES
    def test_uri_ausente_vira_texto_vazio(self, ler):
        info = faixa_info(0)
        del info["uri"]
        faixa = (lida_info if ler is lida else gravada_info)(info)
        assert faixa["uri"] == ""

    def test_uri_vazia_continua_vazia(self):
        assert lida(uri="")["uri"] == ""

    def test_o_valor_ruim_nao_vai_ao_log(self, caplog):
        with caplog.at_level(logging.DEBUG):
            lida(uri="javascript:" + SEGREDO)
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)


class TestOutrasUrlsDaFaixa:
    @LEITORES
    @pytest.mark.parametrize("url", URLS_RUINS[:6])
    def test_artwork_invalida_vira_vazio(self, ler, url):
        assert ler(sourceName="deezer", artworkUrl=url)["artworkUrl"] == ""

    @LEITORES
    def test_artwork_valida_passa(self, ler):
        assert (
            ler(sourceName="deezer", artworkUrl="https://exemplo.invalid/capa.jpg")["artworkUrl"]
            == "https://exemplo.invalid/capa.jpg"
        )

    @LEITORES
    @pytest.mark.parametrize("url", URLS_RUINS[:6])
    def test_url_e_miniatura_da_playlist(self, ler, url):
        faixa = ler(playlist={"name": "Minha", "url": url, "thumb": url})
        assert faixa["playlist"] == {"name": "Minha", "url": "", "thumb": ""}

    @LEITORES
    def test_playlist_valida_passa(self, ler):
        playlist = {"name": "Minha", "url": "https://exemplo.invalid/p/1", "thumb": "https://exemplo.invalid/t.jpg"}
        assert ler(playlist=copy.deepcopy(playlist))["playlist"] == playlist

    @LEITORES
    @pytest.mark.parametrize("url", URLS_RUINS[:6])
    def test_url_do_album_em_extra(self, ler, url):
        info = faixa_info(0)
        info["extra"]["album"] = {"name": "Álbum", "url": url}
        faixa = (lida_info if ler is lida else gravada_info)(info)
        assert faixa["extra"]["album"] == {"name": "Álbum", "url": ""}

    def test_album_valido_passa(self):
        info = faixa_info(0)
        info["extra"]["album"] = {"name": "Álbum", "url": "https://exemplo.invalid/album/1"}
        assert (
            decodificar(bruto(queue=[info]))["queue"][0]["extra"]["album"]["url"] == "https://exemplo.invalid/album/1"
        )

    @LEITORES
    def test_em_plugin_info_a_chave_com_url_invalida_sai_e_as_outras_ficam(self, ler):
        plugin = {
            "artistUrl": "javascript:alert(1)",
            "albumUrl": "https://exemplo.invalid/album",
            "previewUrl": "ftp://exemplo.invalid/p",
            "artworkurl": "file:///x",
            "url": "oi",
            "albumName": "Nome",
            "isrc": "BR1",
            "total": 12,
            "lista": [1, 2],
        }
        faixa = ler(pluginInfo=copy.deepcopy(plugin))
        assert faixa["pluginInfo"] == {
            "albumUrl": "https://exemplo.invalid/album",
            "albumName": "Nome",
            "isrc": "BR1",
            "total": 12,
            "lista": [1, 2],
        }

    @LEITORES
    def test_chave_que_nao_termina_em_url_nao_e_tocada_mesmo_com_valor_estranho(self, ler):
        faixa = ler(pluginInfo={"urlBase": "javascript:x", "texto": "ftp://x"})
        assert faixa["pluginInfo"] == {"urlBase": "javascript:x", "texto": "ftp://x"}


class TestConviteDaSessao:
    @pytest.mark.parametrize("url", URLS_RUINS[:6])
    def test_convite_invalido_sai(self, url):
        assert not decodificar(bruto(listen_along_invite=url)).get("listen_along_invite")

    def test_convite_valido_passa(self):
        assert (
            decodificar(bruto(listen_along_invite="https://exemplo.invalid/convite"))["listen_along_invite"]
            == "https://exemplo.invalid/convite"
        )

    def test_convite_vazio_e_valido(self):
        assert not decodificar(bruto(listen_along_invite="")).get("listen_along_invite")

    def test_a_sessao_nao_e_recusada_por_causa_do_convite(self):
        assert decodificar(bruto(listen_along_invite="javascript:alert(1)"))["_id"]


# ============================================================================ fonte local


class TestFonteLocal:
    @LEITORES
    @pytest.mark.parametrize("lista", LISTAS)
    def test_faixa_local_e_recusada_e_a_sessao_e_as_outras_faixas_ficam(self, ler, lista):
        local = faixa_info(1, sourceName="local", uri="/media/musica.mp3")
        boa = faixa_info(2)
        faixas = [faixa_info(0), local, boa]
        if ler is lida:
            resultado = decodificar(bruto(**{lista: faixas}))[lista]
        else:
            resultado = session.decode_session(session.encode_session(sessao_minima(**{lista: faixas})))[lista]
        assert [f["title"] for f in resultado] == ["Música 0", "Música 2"]

    @pytest.mark.parametrize("lista", LISTAS)
    def test_http_e_aceito_porque_e_o_anexo_do_discord(self, lista):
        anexo = faixa_info(1, sourceName="http", uri="https://cdn.discordapp.com/attachments/1/2/musica.mp3")
        resultado = decodificar(bruto(**{lista: [faixa_info(0), anexo]}))[lista]
        assert [f["sourceName"] for f in resultado] == ["youtube", "http"] and resultado[1]["uri"].startswith(
            "https://cdn."
        )

    def test_so_a_fonte_exata_local_e_recusada(self):
        resultado = decodificar(
            bruto(queue=[faixa_info(0, sourceName="localhost"), faixa_info(1, sourceName="mylocal")])
        )["queue"]
        assert len(resultado) == 2

    def test_sessao_so_com_faixa_local_fica_com_fila_vazia(self):
        assert decodificar(bruto(queue=[faixa_info(0, sourceName="local")]))["queue"] == []


# ============================================================================ faixa que o esquema recusa


def sem(chave, info):
    info = copy.deepcopy(info)
    del info[chave]
    return info


def faixas_ruins() -> dict:
    boa = faixa_info(1)
    sem_requester = copy.deepcopy(boa)
    sem_requester["extra"] = {}
    return {
        "nao-e-dicionario": "texto",
        "lista": [1, 2],
        "sem-titulo": sem("title", boa),
        "titulo-numero": {**boa, "title": 3},
        "titulo-longo": {**boa, "title": "t" * 3000},
        "sem-fonte": sem("sourceName", boa),
        "sem-extra": sem("extra", boa),
        "sem-requester": sem_requester,
        "id-nao-base64": {**boa, "id": "isto não é base64!"},
        "length-negativo": {**boa, "length": -1},
        "length-texto": {**boa, "length": "x"},
        "isStream-texto": {**boa, "isStream": "sim"},
    }


class TestFaixaRuim:
    @pytest.mark.parametrize("lista", LISTAS)
    @pytest.mark.parametrize("nome", sorted(faixas_ruins()))
    def test_a_faixa_ruim_e_descartada_e_a_sessao_e_as_outras_faixas_ficam(self, lista, nome):
        documento = bruto(**{lista: [faixa_info(0), faixas_ruins()[nome], faixa_info(2)]})
        resultado = decodificar(documento)[lista]
        assert [f["title"] for f in resultado] == ["Música 0", "Música 2"]

    def test_o_descarte_vai_ao_log_so_com_a_contagem(self, caplog):
        ruim = {**faixa_info(1), "title": SEGREDO, "length": -1}
        with caplog.at_level(logging.DEBUG):
            decodificar(bruto(queue=[faixa_info(0), ruim]))
        avisos = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert avisos and all(SEGREDO not in m for m in avisos)
        assert all(SEGREDO not in repr(r.args) for r in caplog.records)

    @pytest.mark.parametrize("lista", LISTAS)
    def test_surrogate_solto_numa_faixa_recusa_a_sessao_inteira_pelo_leitor_do_json(self, lista):
        faixa = faixa_info(1, title="a" + chr(0xD800) + "b")
        assert falha(decodificar, bruto(**{lista: [faixa_info(0), faixa]})).code == "surrogate"

    def test_toda_a_fila_ruim_deixa_a_fila_vazia_e_a_sessao_valida(self):
        lida_ = decodificar(bruto(queue=[faixas_ruins()["sem-titulo"]] * 3))
        assert lida_["queue"] == [] and lida_["_id"]

    def test_a_ordem_das_faixas_boas_e_mantida(self):
        faixas = [faixa_info(n) for n in range(6)]
        faixas.insert(3, faixas_ruins()["sem-titulo"])
        assert [f["title"] for f in decodificar(bruto(queue=faixas))["queue"]] == [f"Música {n}" for n in range(6)]


# ============================================================================ a faixa reidratada pelo código real (R1, medição do QA)


def reidratar(infos: list):
    return BotPool.process_track_cls(SimpleNamespace(), copy.deepcopy(infos))[0]


FONTES = [
    "youtube",
    "soundcloud",
    "http",
    "tts",
    "flowerytts",
    "reddit",
    "vimeo",
    "twitch",
    "bandcamp",
    "mixcloud",
    "spotify",
    "deezer",
    "applemusic",
]


class TestReidratacao:
    @pytest.mark.parametrize("fonte", FONTES)
    def test_faixa_completa_com_uri_invalida_constroi_e_tem_uri_e_url_de_texto(self, fonte):
        faixas = decodificar(bruto(queue=[faixa_info(0, sourceName=fonte, uri="javascript:alert(1)")]))["queue"]
        (faixa,) = reidratar(faixas)
        assert faixa.uri == "" and faixa.url == "" and type(faixa.title) is str

    @pytest.mark.parametrize("fonte", FONTES)
    def test_faixa_parcial_com_uri_invalida_constroi_e_cai_na_busca(self, fonte):
        info = faixa_info(0, sourceName=fonte, uri="javascript:alert(1)", is_partial=True, id=None)
        (faixa,) = reidratar(decodificar(bruto(queue=[info]))["queue"])
        assert faixa.uri.startswith("https://www.youtube.com/results?search_query=") and faixa.url == faixa.uri

    @pytest.mark.parametrize("fonte", ["youtube", "soundcloud", "spotify"])
    def test_uri_ausente_e_none_na_entrada_tambem_reidratam(self, fonte):
        sem_uri = sem("uri", faixa_info(0, sourceName=fonte))
        com_none = faixa_info(0, sourceName=fonte, uri=None)
        faixas = decodificar(bruto(queue=[sem_uri, com_none]))["queue"]
        assert [type(f.uri) for f in reidratar(faixas)] == [str, str]

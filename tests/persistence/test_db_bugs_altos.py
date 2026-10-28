"""F3-1 — testes RED dos bugs altos KI-01, KI-09 e KI-15 (docs/known-issues.md). Sem rede, sem Discord, sem .env real.

KI-01  ``requirements.txt`` precisa declarar ``tinymongo[serialization]``: ``empiremuse/utils/db.py`` importa
       ``tinydb_serialization``, que só vem com esse extra. CI, Dockerfile e docs instalam o extra à parte, mas a Discloud
       instala SÓ o requirements.txt.

KI-09  ``update_values`` descarta as LISTAS do usuário ao migrar o ``ver`` do modelo. Comportamento esperado da migração
       (nunca perder dados):
         * valor do usuário vence o padrão: escalar, mapeamento e LISTA (inclusive lista vazia e lista de dicts), em
           qualquer profundidade e também dentro de mapeamentos de chaves dinâmicas (``fav_links``, ``custom_skins``...);
         * chave NOVA do modelo (escalar, mapeamento, lista ou subchave aninhada) recebe o padrão do modelo;
         * chave REMOVIDA do modelo é PRESERVADA com o valor salvo, de qualquer tipo (a migração só acrescenta e atualiza,
           não apaga: quem limpa chaves obsoletas é uma tarefa explícita, nunca o efeito colateral de subir o ``ver``);
         * ``ver`` passa a ser o do modelo, ``_id`` é mantido; o documento antigo não é alterado nem compartilha listas
           com o resultado; migrar de novo não muda nada; documento já na versão atual não é reescrito.

KI-15  ``SpotifyClient.get_access_token`` com credenciais inválidas zera as credenciais e chama a si mesma com
       ``token_refresh`` ainda True: a chamada recursiva espera para sempre por ela mesma. Comportamento esperado: a
       chamada TERMINA (aqui, em até 2 s) com ``GenericError`` (ou subclasse) — escolhida porque é o erro de usuário do
       projeto, formatado pelo error_handler e já usado no resto do módulo —, com mensagem clara em pt-BR, sem vazar as
       credenciais, e ``token_refresh`` volta a False; uma chamada seguinte (ou concorrente) também não fica presa.
"""

import ast
import asyncio
import base64
import copy
import re
import sys
import tempfile
from importlib import metadata
from pathlib import Path

import pytest
from aiohttp import ClientError
from packaging.markers import default_environment
from packaging.requirements import Requirement

from empiremuse.utils.db import DBModel, LocalDatabase, db_models, global_db_models, update_values
from empiremuse.utils.music.audio_sources import spotify
from empiremuse.utils.music.errors import GenericError
from tests.support.raiz import RAIZ

pytestmark = [pytest.mark.critical, pytest.mark.regression]

ROOT = RAIZ


# ============================================================================ KI-01 — extra serialization


# ============================================================================ KI-09 — update_values / migração de ver


def modelo(**campos) -> dict:
    return {"ver": 2.0, **campos}


def antigo(**campos) -> dict:
    return {"_id": "1", "ver": 1.0, **campos}


class TestKI09UpdateValues:
    def test_lista_de_dicts_do_usuario_e_mantida(self):
        faixas = [{"url": "https://a", "title": "A"}, {"url": "https://b", "title": "B"}]
        assert update_values(modelo(last_tracks=[]), antigo(last_tracks=faixas))["last_tracks"] == faixas

    def test_chaves_novas_do_modelo_recebem_o_padrao(self):
        resultado = update_values(
            modelo(velha=1, nova_escalar=10, nova_lista=["x"], novo_mapa={"a": 1}, cfg={"antiga": 1, "nova_sub": "s"}),
            antigo(velha=5, cfg={"antiga": 2}),
        )
        assert resultado["velha"] == 5
        assert resultado["nova_escalar"] == 10
        assert resultado["nova_lista"] == ["x"]
        assert resultado["novo_mapa"] == {"a": 1}
        assert resultado["cfg"] == {"antiga": 2, "nova_sub": "s"}

    def test_chave_removida_do_modelo_e_preservada_qualquer_que_seja_o_tipo(self):
        resultado = update_values(
            modelo(atual=1), antigo(atual=2, obsoleta_escalar="a", obsoleta_mapa={"k": 1}, obsoleta_lista=[1, 2])
        )
        assert resultado["obsoleta_escalar"] == "a"
        assert resultado["obsoleta_mapa"] == {"k": 1}
        assert resultado["obsoleta_lista"] == [1, 2], "lista de chave removida do modelo também não pode ser apagada"


def _documento_antigo_do_usuario() -> dict:
    return {
        "_id": "42",
        "ver": 1.0,
        "fav_links": {},
        "token": "t",
        "custom_prefix": "?",
        "last_tracks": [{"url": "https://a", "title": "A"}, {"url": "https://b", "title": "B"}],
        "lastfm": {"username": "u", "sessionkey": "", "scrobble": True},
    }


@pytest.fixture
def pasta_do_banco(tmp_path) -> str:
    return str(tmp_path / "banco")


def semear(pasta: str, collection: str, db_name: str, documento: dict) -> None:
    LocalDatabase(dir_=pasta)._connect[collection][db_name].insert_one(copy.deepcopy(documento))


class TestKI09MigracaoNoLocalDatabase:
    @pytest.mark.asyncio
    async def test_usuario_global_mantem_last_tracks_ao_subir_o_ver(self, pasta_do_banco):
        semear(pasta_do_banco, "global", DBModel.users, _documento_antigo_do_usuario())
        banco = LocalDatabase(dir_=pasta_do_banco)

        dados = await banco.get_data("42", db_name=DBModel.users, collection="global", default_model=global_db_models)

        assert dados["last_tracks"] == _documento_antigo_do_usuario()["last_tracks"], "KI-09: last_tracks perdido"
        assert dados["lastfm"]["scrobble"] is True and dados["custom_prefix"] == "?"
        assert dados["ver"] == global_db_models[DBModel.users]["ver"]


# ============================================================================ KI-15 — Spotify get_access_token


ID_FAKE = "id-spotify-fake"
SEGREDO_FAKE = "segredo-spotify-fake-123"
LIMITE = 2.0


class _RespostaFake:
    def __init__(self, status, corpo, falha_de_rede=False):
        self.status, self._corpo, self._falha = status, corpo, falha_de_rede
        self.url = "https://accounts.spotify.com/api/token"

    async def __aenter__(self):
        if self._falha:
            raise ClientError("sem rede (simulado)")
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, *args, **kwargs):
        # cede o controle ao event loop, como uma resposta de rede de verdade: sem isso a 1ª chamada termina antes de a
        # 2ª começar e o caminho "esperar a renovação em andamento" nunca seria exercitado
        await asyncio.sleep(0.05)
        return copy.deepcopy(self._corpo)


class _SessaoFake:
    def __init__(self, resposta, chamadas):
        self._resposta, self._chamadas = resposta, chamadas

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, headers=None, data=None, **kwargs):
        self._chamadas.append({"url": url, "headers": headers, "data": data})
        return self._resposta

    get = post


@pytest.fixture
def spotify_fake(monkeypatch, tmp_path):
    """SpotifyClient com o aiohttp substituído e o cache do token isolado em tmp_path (nunca o do sistema nem o RUNTIME_DIR real).

    O local do arquivo de cache não é fixado aqui: RUNTIME_DIR (EMPIREMUSE_HOME), cwd e o tmp do sistema apontam para
    pastas de tmp_path, e os testes só olham se ALGUM arquivo foi gravado em tmp_path.
    """
    for pasta in ("runtime", "cwd", "sistema"):
        (tmp_path / pasta).mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path / "runtime"))
    monkeypatch.chdir(tmp_path / "cwd")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "sistema"))
    monkeypatch.setattr(spotify, "spotify_cache_file", str(tmp_path / "sistema" / ".spotify_cache.json"), raising=False)

    def preparar(status=401, corpo=None, falha_de_rede=False):
        chamadas: list[dict] = []
        resposta = _RespostaFake(status, corpo, falha_de_rede)
        monkeypatch.setattr(spotify, "ClientSession", lambda *a, **k: _SessaoFake(resposta, chamadas))
        return spotify.SpotifyClient(client_id=ID_FAKE, client_secret=SEGREDO_FAKE), chamadas

    return preparar


INVALIDO = {"error": "invalid_client", "error_description": "Invalid client"}


async def _terminar(corotina, o_que="get_access_token"):
    try:
        return await asyncio.wait_for(corotina, LIMITE)
    except asyncio.TimeoutError:
        pytest.fail(f"KI-15: {o_que} ficou preso por mais de {LIMITE} s (espera infinita com credenciais inválidas)")


class TestKI15SpotifyCredenciaisInvalidas:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 401])
    async def test_termina_com_generic_error_claro_e_libera_o_token_refresh(self, spotify_fake, status):
        cliente, _ = spotify_fake(status=status, corpo=INVALIDO)

        with pytest.raises(GenericError) as erro:
            await _terminar(cliente.get_access_token())

        assert "spotify" in str(erro.value).lower(), f"mensagem sem contexto: {erro.value}"
        assert cliente.token_refresh is False, "token_refresh ficou True: toda chamada seguinte esperaria para sempre"

    @pytest.mark.asyncio
    async def test_a_mensagem_de_erro_nao_vaza_as_credenciais(self, spotify_fake):
        cliente, _ = spotify_fake(status=401, corpo=INVALIDO)

        with pytest.raises(GenericError) as erro:
            await _terminar(cliente.get_access_token())

        texto = f"{erro.value} {erro.value!r} {getattr(erro.value, 'error', '')}"
        assert SEGREDO_FAKE not in texto and ID_FAKE not in texto

    @pytest.mark.asyncio
    async def test_credenciais_nao_vazam_para_logs_nem_para_a_saida(self, spotify_fake, caplog, capsys):
        cliente, _ = spotify_fake(status=401, corpo=INVALIDO)
        basic = base64.b64encode(f"{ID_FAKE}:{SEGREDO_FAKE}".encode()).decode()

        with caplog.at_level(0), pytest.raises(GenericError):
            await _terminar(cliente.get_access_token())

        saida = capsys.readouterr()
        tudo = f"{caplog.text} {saida.out} {saida.err}"
        assert SEGREDO_FAKE not in tudo and ID_FAKE not in tudo and basic not in tudo

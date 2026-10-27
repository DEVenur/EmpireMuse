"""S-28 — a falha ao aplicar o ``refreshToken`` do YouTube no Lavalink local não pode vazar a senha do node para o stdout.

O ``repr`` de um ``aiohttp.ClientResponseError`` carrega o ``RequestInfo`` com os headers (``Authorization`` = senha do Lavalink).
O node, o Mongo e a rede são fakes; o ``sleep`` do backoff é trocado, então nada dorme nem sai da máquina.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from empiremuse.utils import client
from empiremuse.utils.client import BotPool

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

SENHA = "SEGREDO-123"


class Resposta:
    def __init__(self, status, corpo=None, erro=None):
        self.status, self._corpo, self._erro = status, corpo, erro

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self._corpo

    def raise_for_status(self):
        raise self._erro


class Sessao:
    """``get`` devolve o /v4/info com o youtube-plugin; ``post`` devolve ``resposta_post`` ou levanta ``erro_post``."""

    resposta_post = None
    erro_post = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, *args, **kwargs):
        return Resposta(200, {"plugins": [{"name": "youtube-plugin"}]})

    async def post(self, *args, **kwargs):
        if self.erro_post:
            raise self.erro_post
        return self.resposta_post


def erro_http() -> aiohttp.ClientResponseError:
    url = URL("http://127.0.0.1:8090/youtube")
    info = aiohttp.RequestInfo(url, "POST", CIMultiDictProxy(CIMultiDict({"Authorization": SENHA})), url)
    return aiohttp.ClientResponseError(info, (), status=401, message="Unauthorized")


@pytest.fixture
def rodar(monkeypatch):
    async def executar(*, resposta=None, erro=None):
        class SessaoDoCaso(Sessao):
            resposta_post, erro_post = resposta, erro

        monkeypatch.setattr(client.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(client.aiohttp, "ClientSession", SessaoDoCaso)
        monkeypatch.setattr(client, "ClientSession", SessaoDoCaso)
        pool = BotPool.__new__(BotPool)
        pool.get_all_bots = lambda: []
        colecao = SimpleNamespace(find_one=AsyncMock(return_value={"refresh_tokens": {"a": "tok"}}))
        pool.mongo_database = SimpleNamespace(_connect={"global": {"global": colecao}})
        node = {
            "host": "127.0.0.1",
            "port": 8090,
            "password": SENHA,
            "identifier": "LOCAL",
            "retries": 1,
        }

        await pool.check_node(node)

    return executar


async def test_an_http_error_logs_only_the_status_and_the_node_never_the_headers(rodar, capsys):
    resposta = Resposta(401, erro=erro_http())

    await rodar(resposta=resposta)

    saida = capsys.readouterr()
    visivel = saida.out + saida.err
    assert SENHA not in visivel and "RequestInfo" not in visivel
    assert "401" in visivel and "LOCAL" in visivel
    assert "Falha ao aplicar o Youtube refreshToken" in visivel


async def test_a_non_http_error_logs_only_the_class_name(rodar, capsys):
    await rodar(erro=OSError(f"conexão recusada com Authorization: {SENHA}"))

    saida = capsys.readouterr()
    visivel = saida.out + saida.err
    assert SENHA not in visivel
    assert "OSError" in visivel and "LOCAL" in visivel
    assert "Falha ao aplicar o Youtube refreshToken" in visivel

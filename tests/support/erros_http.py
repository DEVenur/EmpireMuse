"""Erros do aiohttp e fakes de sessão que carregam uma senha nos headers da requisição, para os testes do S-28."""

import aiohttp
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

SENHA = "SEGREDO-123"


def info_da_requisicao() -> aiohttp.RequestInfo:
    url = URL("http://127.0.0.1:8090/v4/info")
    return aiohttp.RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict({"Authorization": SENHA})), url)


def erro_response(status: int = 401, classe=aiohttp.ClientResponseError) -> aiohttp.ClientResponseError:
    return classe(info_da_requisicao(), (), status=status, message="x")


class Resposta:
    """Resposta 200 cujo ``json()`` levanta ``erro`` (ou devolve ``corpo``)."""

    status = 200

    def __init__(self, corpo=None, erro=None):
        self._corpo, self._erro = corpo, erro

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        if self._erro:
            raise self._erro
        return self._corpo

    async def text(self):
        return ""


class SessaoQueNaoEntendeJson:
    """``get`` devolve uma 200 cujo corpo não é JSON (``ContentTypeError`` com a senha no header da requisição)."""

    def get(self, *args, **kwargs):
        return Resposta(erro=erro_response(200, aiohttp.ContentTypeError))

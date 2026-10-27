"""Erros do aiohttp e fakes de sessão que carregam uma senha nos headers da requisição, para os testes do S-28."""

import aiohttp
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

SENHA = "SEGREDO-123"


def info_da_requisicao(url: str = "http://127.0.0.1:8090/v4/info") -> aiohttp.RequestInfo:
    url = URL(url)
    return aiohttp.RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict({"Authorization": SENHA})), url)


def erro_response(
    status: int = 401, classe=aiohttp.ClientResponseError, url: str = "http://127.0.0.1:8090/v4/info"
) -> aiohttp.ClientResponseError:
    return classe(info_da_requisicao(url), (), status=status, message="x")


class Resposta:
    """Resposta 200 cujo ``json()`` levanta ``erro`` (ou devolve ``corpo``)."""

    def __init__(self, corpo=None, erro=None, status=200, texto=""):
        self._corpo, self._erro, self.status, self._texto = corpo, erro, status, texto

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        if self._erro:
            raise self._erro
        return self._corpo

    async def text(self):
        return self._texto


class SessaoQueNaoEntendeJson:
    """``get`` devolve uma 200 cujo corpo não é JSON (``ContentTypeError`` com a senha no header da requisição)."""

    def get(self, *args, **kwargs):
        return Resposta(erro=erro_response(200, aiohttp.ContentTypeError))


CORPO_SECRETO = "CORPO-SECRETO"


class SessaoComStatus:
    """``get`` responde ``status`` com um corpo de texto que também é segredo; usável como sessão e como gerenciador de contexto."""

    def __init__(self, status: int):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, *args, **kwargs):
        return Resposta(status=self.status, texto=CORPO_SECRETO)

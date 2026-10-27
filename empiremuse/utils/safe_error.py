"""Resumo de uma exceção para log e mensagem, sem o que ela carrega por dentro."""

from __future__ import annotations

import aiohttp


class HTTPStatusError(Exception):
    """Resposta HTTP inesperada de um servidor: carrega só o status, nunca o corpo nem os cabeçalhos."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


def safe_error(error: BaseException) -> str:
    """``HTTP <status>`` para uma resposta HTTP de erro (aiohttp ou ``HTTPStatusError``), senão o nome da classe.

    Nunca ``repr`` nem ``str``.

    O ``repr`` de um ``aiohttp.ClientResponseError`` (e de ``ContentTypeError`` e ``WSServerHandshakeError``) traz o
    ``RequestInfo`` com os cabeçalhos da requisição: a senha do Lavalink e o token do Spotify. A mensagem de qualquer outra
    exceção também pode citar a URL ou o cabeçalho, então só o tipo dela sai.
    """
    if isinstance(error, aiohttp.ClientResponseError | HTTPStatusError):
        return f"HTTP {error.status}"
    return type(error).__name__

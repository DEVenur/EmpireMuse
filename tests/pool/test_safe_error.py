"""S-28 — ``safe_error`` resume uma exceção sem expor header, URL nem mensagem (só o status HTTP ou o nome da classe)."""

import aiohttp
import pytest

from empiremuse.utils.safe_error import safe_error
from tests.support.erros_http import SENHA, erro_response

pytestmark = pytest.mark.critical


@pytest.mark.parametrize(
    ("erro", "esperado"),
    [
        (erro_response(401), "HTTP 401"),
        (erro_response(200, aiohttp.ContentTypeError), "HTTP 200"),
        (erro_response(401, aiohttp.WSServerHandshakeError), "HTTP 401"),
        (OSError(SENHA), "OSError"),
        (RuntimeError(f"Authorization: {SENHA}"), "RuntimeError"),
    ],
    ids=["resposta-http", "content-type", "handshake-ws", "oserror", "runtime"],
)
def test_safe_error_is_the_status_or_the_class_name_only(erro, esperado):
    resumo = safe_error(erro)

    assert resumo == esperado and SENHA not in resumo

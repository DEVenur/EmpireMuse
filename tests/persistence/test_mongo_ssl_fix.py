"""A22 (Vigil 5, CWE-295) — ``MONGO_SSL_FIX`` tem parse booleano estrito.

Só ``true``, ``1``, ``yes`` e ``on`` (sem diferenciar maiúsculas) desligam a validação do certificado TLS do MongoDB e, nesse caso,
sai um WARNING no startup. Ausente, vazio, ``false``, ``0`` ou qualquer outro valor → o cliente valida. A senha da URI (aqui uma
senha canário) nunca aparece em log nem em mensagem de exceção.
"""

import logging
from urllib.parse import parse_qs, urlparse

import pytest

from empiremuse.utils import db
from empiremuse.utils.db import MongoDatabase

pytestmark = pytest.mark.critical

CANARIO = "SenhaCanario-9f3a71"
URI = f"mongodb://usuario:{CANARIO}@host.exemplo:27017/banco?retryWrites=true"
VERDADEIROS = ["true", "1", "yes", "on", "TRUE", "Yes", "ON"]
FALSOS = [None, "", "false", "0", "no", "off", "2", "sim", "tlsAllowInvalidCertificates"]


class ClienteFalso:
    """Guarda o que o ``MongoDatabase`` entrega ao driver; nada de rede."""

    ultimo = None

    def __init__(self, uri, **opcoes):
        self.uri, self.opcoes = uri, opcoes
        ClienteFalso.ultimo = self

    def valida_certificado(self) -> bool:
        """``False`` se a URI ou as opções do cliente pedem para aceitar certificado inválido."""
        da_uri = parse_qs(urlparse(self.uri).query).get("tlsAllowInvalidCertificates", [])
        pedidos = [*da_uri, self.opcoes.get("tlsAllowInvalidCertificates", False)]
        return not any(str(valor).lower() == "true" for valor in pedidos)


@pytest.fixture
def cliente(monkeypatch):
    ClienteFalso.ultimo = None
    monkeypatch.setattr(db, "AsyncMongoClient", ClienteFalso)
    return lambda valor: _criar(monkeypatch, valor)


def _criar(monkeypatch, valor):
    if valor is None:
        monkeypatch.delenv("MONGO_SSL_FIX", raising=False)
    else:
        monkeypatch.setenv("MONGO_SSL_FIX", valor)
    MongoDatabase(URI, timeout=5)
    return ClienteFalso.ultimo


@pytest.mark.parametrize("valor", FALSOS, ids=repr)
def test_without_a_true_value_the_certificate_is_validated_and_nothing_is_warned(cliente, caplog, valor):
    with caplog.at_level(logging.DEBUG):
        criado = cliente(valor)

    assert criado.valida_certificado()
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("valor", VERDADEIROS)
def test_a_true_value_disables_validation_and_warns_without_leaking_the_password(cliente, caplog, valor):
    with caplog.at_level(logging.DEBUG):
        criado = cliente(valor)

    assert not criado.valida_certificado()
    avisos = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(avisos) == 1
    assert CANARIO not in caplog.text and "usuario" not in caplog.text


def test_the_connection_timeout_and_the_other_uri_parameters_are_kept(cliente):
    criado = cliente("true")

    assert criado.opcoes["connectTimeoutMS"] == 5000
    assert "retryWrites=true" in criado.uri


def test_an_invalid_uri_raises_without_the_password_in_the_message(monkeypatch):
    """Com o driver real (nada conecta na construção): a opção inválida estoura sem repetir a senha da URI."""
    monkeypatch.delenv("MONGO_SSL_FIX", raising=False)

    with pytest.raises(Exception) as erro:
        MongoDatabase(f"mongodb://usuario:{CANARIO}@host.exemplo/banco?tls=talvez", timeout=5)

    assert CANARIO not in str(erro.value)

"""Item 7 (K8h) — os dois produtores do código de erro o passam ao log como ``extra={"error_code": code}``.

``log_unexpected_error`` de ``utils/music/errors.py`` e ``ErrorHandler.log_unexpected_error`` de ``cogs/error_handler.py``: o registro
carrega ``record.error_code`` igual ao código devolvido; quando ``safe_error_code`` devolve ``""`` não há o atributo.
"""

import logging

import pytest

from empiremuse.cogs import error_handler
from empiremuse.rules.error_code import ERROR_CODE_RE
from empiremuse.utils.music import errors

pytestmark = pytest.mark.critical


class Captura(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.registros: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.registros.append(record)


@pytest.fixture
def captura():
    handler = Captura()
    logger = logging.getLogger("teste.k8h")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    yield handler
    logger.removeHandler(handler)


def produtor_de_musica(captura, erro):
    return errors.log_unexpected_error(logging.getLogger("teste.k8h"), erro, "tocar")


def produtor_do_cog(captura, erro, monkeypatch):
    monkeypatch.setattr(error_handler, "logger", logging.getLogger("teste.k8h"))
    cog = error_handler.ErrorHandler.__new__(error_handler.ErrorHandler)
    return cog.log_unexpected_error(erro, "play")


PRODUTORES = [
    pytest.param(lambda captura, erro, mp: produtor_de_musica(captura, erro), errors, id="utils.music.errors"),
    pytest.param(produtor_do_cog, error_handler, id="cogs.error_handler"),
]


@pytest.mark.parametrize(("produtor", "modulo"), PRODUTORES)
class TestProdutores:
    def test_the_record_carries_the_returned_code_as_error_code(self, captura, monkeypatch, produtor, modulo):
        codigo = produtor(captura, ValueError("falhou"), monkeypatch)

        (registro,) = captura.registros
        assert ERROR_CODE_RE.fullmatch(codigo) and registro.error_code == codigo
        assert registro.levelno == logging.ERROR and codigo in registro.getMessage()

    def test_the_record_still_carries_the_exception_info(self, captura, monkeypatch, produtor, modulo):
        produtor(captura, KeyError("chave"), monkeypatch)

        (registro,) = captura.registros
        assert registro.exc_info is not None and registro.exc_info[0] is KeyError

    def test_without_a_code_there_is_no_error_code_attribute(self, captura, monkeypatch, produtor, modulo):
        monkeypatch.setattr(modulo, "safe_error_code", lambda: "")

        codigo = produtor(captura, ValueError("falhou"), monkeypatch)

        (registro,) = captura.registros
        assert codigo == "" and not hasattr(registro, "error_code")
        assert "ERR-" not in registro.getMessage()

    def test_two_calls_produce_two_distinct_codes_on_their_own_records(self, captura, monkeypatch, produtor, modulo):
        primeiro = produtor(captura, ValueError("a"), monkeypatch)
        segundo = produtor(captura, ValueError("b"), monkeypatch)

        assert [r.error_code for r in captura.registros] == [primeiro, segundo]

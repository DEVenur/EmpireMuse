"""F3-6b, achado 1 do QA — ``SchemaError`` precisa sobreviver a ``copy`` e a ``pickle`` (``path`` e ``code`` intactos).

Com ``super().__init__(mensagem)`` o ``args`` fica sem ``path`` e ``code``, e reconstruir a exceção falha com ``TypeError``.
A mensagem continua a mesma (``"<code> em <path>"``, ``"<raiz>"`` quando o caminho é vazio) e não leva o valor do dado.
"""

import copy

import pytest

from empiremuse.serialization.schema import SchemaError

CASOS = [("queue[3].uri", "length"), ("", "depth"), ("a.b", "type")]


@pytest.mark.parametrize(("path", "code"), CASOS)
class TestSchemaErrorCopiavel:
    def igual(self, copia, original):
        assert type(copia) is type(original)
        assert (copia.path, copia.code) == (original.path, original.code)
        assert str(copia) == str(original) and copia.args == original.args

    def test_deepcopy(self, path, code):
        erro = SchemaError(path, code)
        self.igual(copy.deepcopy(erro), erro)


def test_os_args_sao_o_caminho_e_o_codigo_sem_valor_de_dado():
    assert SchemaError("a.b", "type").args == ("a.b", "type")

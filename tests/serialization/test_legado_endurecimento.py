"""F3-6b, etapa 2 — endurecimentos do leitor legado além do RED do QA (do Backend, para o QA revisar).

* no máximo ``MAX_DEQUES`` chamadas a ``collections.deque`` por documento (``deque(iteravel)`` copia o argumento);
* a pré-varredura respeita a *fence* da ``MARK`` como o ``Unpickler`` real: nomes empilhados ANTES da marca não servem
  de argumento ao ``STACK_GLOBAL`` nem ao ``REDUCE`` depois dela;
* ``LegacyFormatError`` é copiável e picklável, com ``path`` e ``code`` intactos.
"""

import copy
import pickle
import zlib

import pytest

from tests.support.leitor_legado import dicionario, global_, legacy_pickle, pickle_de, texto, tupla

pytestmark = pytest.mark.critical


def ler(dados: bytes, kind: str = "session"):
    return legacy_pickle.load_legacy(zlib.compress(dados), kind)


def recusa(dados: bytes, kind: str = "session") -> str:
    with pytest.raises(legacy_pickle.LegacyFormatError) as info:
        ler(dados, kind)
    return info.value.code


def deque_vazio() -> bytes:
    return global_("collections", "deque") + tupla(pickle.EMPTY_TUPLE) + pickle.REDUCE


def documento_com_deques(quantos: int) -> bytes:
    return pickle_de(dicionario(*((texto(f"d{i}"), deque_vazio()) for i in range(quantos))))


class TestTetoDeDeques:
    def test_o_teto_e_o_declarado(self):
        assert legacy_pickle.MAX_DEQUES == 2

    def test_acima_do_teto_e_recusado(self):
        assert recusa(documento_com_deques(legacy_pickle.MAX_DEQUES + 1)) == "opcode_limit"


class TestFenceDaMarca:
    def test_nomes_abaixo_da_marca_nao_alimentam_o_stack_global(self):
        assert recusa(pickle_de(texto("datetime"), texto("datetime"), pickle.MARK, pickle.STACK_GLOBAL)) == "corrupt"

    def test_append_nao_alcanca_o_conteiner_abaixo_da_marca(self):
        assert recusa(pickle_de(pickle.EMPTY_LIST, pickle.MARK, pickle.NONE, pickle.APPEND)) == "corrupt"


@pytest.mark.parametrize("protocolo", range(2, pickle.HIGHEST_PROTOCOL + 1))
def test_legacy_format_error_e_copiavel_e_picklavel(protocolo):
    erro = legacy_pickle.LegacyFormatError("", "global")
    for copia in (copy.copy(erro), copy.deepcopy(erro), pickle.loads(pickle.dumps(erro, protocolo))):
        assert type(copia) is legacy_pickle.LegacyFormatError
        assert (copia.path, copia.code, str(copia)) == ("", "global", "global em <raiz>")

"""Apoio dos testes da etapa 2 da F3-6b: o leitor legado ``empiremuse/serialization/legacy_pickle.py``.

``legacy_pickle`` é importado SOB DEMANDA (proxy): sem o módulo cada teste falha de verdade com ``ModuleNotFoundError`` no
corpo, nunca na coleta. Este arquivo concentra as DECISÕES DE ASSINATURA da etapa 2 (para inverter uma, troque aqui e na
implementação) e o MONTADOR de pickles à mão: os casos hostis não podem sair de ``pickle.dumps`` (que só gera pickle
bem-comportado) e nenhum deles é executado pelo teste: só ``load_legacy`` os vê, e ele tem de recusar.

DECISÕES DE ASSINATURA
* ``load_legacy(raw, kind)`` com ``kind`` em ``KINDS``; ``kind`` desconhecido é ``ValueError``.
* O que o produto entrega em cada ponto de leitura (inventário da etapa 0):
  - ``"session"``: ``bytes`` do ``.pkl`` (zlib + pickle) no disco, ou ``str`` com o ``base64`` desses bytes (Mongo);
  - ``"queue"``: ``bytes`` do ``.pkl`` (zlib + pickle), só existe no disco;
  - ``"skin"``: ``str`` com o ``base64`` do pickle, SEM zlib (é assim que o editor grava);
  qualquer outro tipo de ``raw`` é ``TYPE``.
* O erro é ``LegacyFormatError``, subclasse de ``SchemaError`` (``path == ""``, ``code`` abaixo), SEM o valor e sem
  encadeamento. NENHUMA outra exceção escapa (nem ``UnpicklingError``, ``EOFError``, ``ValueError``, ``RecursionError``,
  ``MemoryError``, ``OverflowError``...). Falha da validação estrutural mantém o código do ``check_structure``.
* A raiz decodificada tem de ser um ``dict``; bytes depois do ``STOP`` são recusados; a allowlist é por ``kind``.
"""

import base64
import importlib
import pickle
import struct
import time
import tracemalloc
import zlib
from dataclasses import dataclass

from tests.support.serializacao_nucleo import (
    DEPTH,
    ENVELOPE,
    KEY_NOT_TEXT,
    LIMITE_DE_TEMPO,
    NODES,
    NOT_FINITE,
    SEGREDO,
    SURROGATE,
    TOO_BIG,
    TYPE,
    vazamentos,
)

__all__ = [
    "DEPTH",
    "ENVELOPE",
    "KEY_NOT_TEXT",
    "NODES",
    "NOT_FINITE",
    "SEGREDO",
    "SURROGATE",
    "TOO_BIG",
    "TYPE",
    "vazamentos",
]

# Códigos próprios do leitor legado (os demais vêm de ``tests/support/serializacao_nucleo.py``).
PROTOCOL = "protocol"  # sem PROTO, PROTO menor que 4 (inclui o protocolo 3 e o set como classe) ou maior que 5
OPCODE = "opcode"  # opcode fora da lista fechada do kind
GLOBAL = "global"  # STACK_GLOBAL com par (módulo, nome) fora da allowlist do kind
OPCODE_LIMIT = "opcode_limit"  # mais opcodes que o teto do kind
MARK_LIMIT = "mark_limit"  # MARK aninhado acima de 64
SET_LIMIT = "set_limit"  # mais de 1 000 itens de set no documento inteiro
CORRUPT = "corrupt"  # truncado, pilha inconsistente, argumento inválido ou qualquer falha do Unpickler

KINDS = ("session", "queue", "skin")
MIB = 1024 * 1024
MAX_RAW = {"session": 8 * MIB, "queue": 4 * MIB, "skin": 100 * 1024}  # bruto e descomprimido, em bytes
MAX_OPCODES = {"session": 1_500_000, "queue": 600_000, "skin": 50_000}
MAX_MARK_DEPTH = 64
MAX_SET_ITEMS = 1000
GLOBAIS_DATA = frozenset({("datetime", "datetime"), ("datetime", "timezone"), ("datetime", "timedelta")})
ALLOWED_GLOBALS = {
    "session": GLOBAIS_DATA | {("collections", "deque")},
    "queue": GLOBAIS_DATA,
    "skin": frozenset(),
}
OPCODES_PERMITIDOS = frozenset(
    "PROTO FRAME STOP MARK NONE NEWTRUE NEWFALSE BININT BININT1 BININT2 LONG1 BINFLOAT SHORT_BINUNICODE BINUNICODE "
    "SHORT_BINBYTES BINBYTES EMPTY_LIST EMPTY_DICT EMPTY_TUPLE EMPTY_SET APPEND APPENDS SETITEM SETITEMS ADDITEMS "
    "TUPLE1 TUPLE2 TUPLE3 MEMOIZE BINGET LONG_BINGET".split()
)
OPCODES_SO_DE_SESSAO_E_FILA = frozenset({"STACK_GLOBAL", "REDUCE"})


class _Modulo:
    def __init__(self, nome: str):
        self._nome = nome

    def __getattr__(self, atributo: str):
        return getattr(importlib.import_module(self._nome), atributo)


legacy_pickle = _Modulo("empiremuse.serialization.legacy_pickle")


# ============================================================================ montador de pickles (protocolo 4, à mão)


def proto(versao: int = 4) -> bytes:
    return pickle.PROTO + bytes([versao])


def texto(valor: str) -> bytes:
    dados = valor.encode("utf-8", "surrogatepass")
    if len(dados) < 256:
        return pickle.SHORT_BINUNICODE + bytes([len(dados)]) + dados
    return pickle.BINUNICODE + struct.pack("<I", len(dados)) + dados


def inteiro(valor: int) -> bytes:
    if 0 <= valor < 256:
        return pickle.BININT1 + bytes([valor])
    if 0 <= valor < 65536:
        return pickle.BININT2 + struct.pack("<H", valor)
    if -(2**31) <= valor < 2**31:
        return pickle.BININT + struct.pack("<i", valor)
    dados = valor.to_bytes((valor.bit_length() // 8) + 1, "little", signed=True)
    return pickle.LONG1 + bytes([len(dados)]) + dados


def bruto(dados: bytes) -> bytes:
    if len(dados) < 256:
        return pickle.SHORT_BINBYTES + bytes([len(dados)]) + dados
    return pickle.BINBYTES + struct.pack("<I", len(dados)) + dados


def tupla(*itens: bytes) -> bytes:
    if not itens:
        return pickle.EMPTY_TUPLE
    return b"".join(itens) + {1: pickle.TUPLE1, 2: pickle.TUPLE2, 3: pickle.TUPLE3}[len(itens)]


def lista(*itens: bytes) -> bytes:
    return pickle.EMPTY_LIST + (pickle.MARK + b"".join(itens) + pickle.APPENDS if itens else b"")


def conjunto(*itens: bytes) -> bytes:
    return pickle.EMPTY_SET + (pickle.MARK + b"".join(itens) + pickle.ADDITEMS if itens else b"")


def dicionario(*pares: tuple[bytes, bytes]) -> bytes:
    corpo = b"".join(chave + valor for chave, valor in pares)
    return pickle.EMPTY_DICT + (pickle.MARK + corpo + pickle.SETITEMS if pares else b"")


def global_(modulo: str, nome: str) -> bytes:
    return texto(modulo) + texto(nome) + pickle.STACK_GLOBAL


def chamada(modulo: str, nome: str, *argumentos: bytes) -> bytes:
    """``modulo.nome(*argumentos)`` (cada argumento já codificado): STACK_GLOBAL, a tupla de argumentos e REDUCE."""
    return global_(modulo, nome) + tupla(*argumentos) + pickle.REDUCE


def pickle_de(*partes: bytes, versao: int = 4, parar: bool = True) -> bytes:
    return proto(versao) + b"".join(partes) + (pickle.STOP if parar else b"")


def comprimido(dados: bytes) -> bytes:
    return zlib.compress(dados)


def em_base64(dados: bytes) -> str:
    return base64.b64encode(dados).decode("ascii")


def envelope(dados: bytes, kind: str = "session", como_texto: bool = False):
    """Os bytes de um pickle já pronto empacotados como o produto entrega para ``kind``."""
    if kind == "skin":
        return em_base64(dados)
    comprimidos = comprimido(dados)
    return em_base64(comprimidos) if como_texto else comprimidos


def pickle_de_tamanho(tamanho: int, versao: int = 4) -> bytes:
    """Pickle válido (``{"c": "aaa..."}``, protocolo 4) com exatamente ``tamanho`` bytes."""
    base = len(pickle_de(dicionario((texto("c"), texto("a" * 300)))))
    dados = pickle_de(dicionario((texto("c"), texto("a" * (300 + tamanho - base)))), versao=versao)
    assert len(dados) == tamanho
    return dados


def pickle_de_n_opcodes(total: int) -> bytes:
    """Pickle de dicionário com exatamente ``total`` opcodes (``PROTO``, ``STOP`` e o preenchimento contam)."""
    pares = (total - 5) // 3
    sobra = total - 5 - 3 * pares
    corpo = b"".join(texto("a") + pickle.NONE + pickle.SETITEM for _ in range(pares))
    return pickle_de(pickle.EMPTY_DICT, pickle.MEMOIZE * (2 + sobra), corpo)


def aninhado_em_listas(niveis: int) -> bytes:
    """``niveis`` listas encaixadas SEM ``MARK`` (``EMPTY_LIST`` e ``APPEND``), dentro de um dicionário raiz."""
    return pickle_de(
        pickle.EMPTY_DICT, texto("a"), pickle.EMPTY_LIST * niveis, pickle.APPEND * (niveis - 1), pickle.SETITEM
    )


def conjunto_colidente(itens: int, conjuntos: int = 1) -> bytes:
    """Dicionário com ``conjuntos`` sets de ``itens`` inteiros de MESMO hash (``k * (2**61 - 1)``), em lotes de 1 000."""
    primo = 2**61 - 1
    pares = []
    for indice in range(conjuntos):
        partes = []
        for inicio in range(0, itens, 1000):
            lote = [inteiro(primo * (indice * itens + k + 1)) for k in range(inicio, min(inicio + 1000, itens))]
            partes.append(pickle.MARK + b"".join(lote) + pickle.ADDITEMS)
        pares.append((texto(f"s{indice}"), pickle.EMPTY_SET + b"".join(partes)))
    return pickle_de(dicionario(*pares))


# ============================================================================ limites de tempo e de memória


@dataclass
class Medida:
    resultado: object
    erro: BaseException | None
    segundos: float
    pico: int


def medir(funcao, *args, memoria: bool = True, **kwargs) -> Medida:
    """Roda ``funcao`` guardando o resultado OU a exceção, o tempo gasto e o pico de memória (``tracemalloc``).

    ``memoria=False`` não liga o ``tracemalloc`` (que deixa tudo várias vezes mais lento): o pico vem como 0.
    """
    if memoria:
        tracemalloc.start()
    inicio = time.perf_counter()
    resultado, erro = None, None
    try:
        resultado = funcao(*args, **kwargs)
    except BaseException as excecao:  # o teste decide se a exceção é a esperada
        erro = excecao
    segundos = time.perf_counter() - inicio
    pico = 0
    if memoria:
        pico = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    return Medida(resultado, erro, segundos, pico)


def recusado(medida: Medida, codigos, *, segundos: float = LIMITE_DE_TEMPO, pico: int = 64 * MIB) -> None:
    """Confere que ``medida`` terminou em ``LegacyFormatError`` com um dos ``codigos``, dentro do tempo e da memória."""
    codigos = {codigos} if isinstance(codigos, str) else set(codigos)
    assert medida.erro is not None, f"não recusou (devolveu {type(medida.resultado).__name__})"
    assert isinstance(medida.erro, legacy_pickle.LegacyFormatError), f"escapou {type(medida.erro).__name__}"
    assert medida.erro.code in codigos, f"código {medida.erro.code!r}, esperado {sorted(codigos)}"
    assert medida.erro.path == ""
    assert medida.segundos < segundos, f"levou {medida.segundos:.1f} s"
    assert medida.pico < pico, f"usou {medida.pico / MIB:.0f} MiB"

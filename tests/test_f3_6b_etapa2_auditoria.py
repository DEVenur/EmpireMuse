"""F3-6b, etapa 2 — achados H-1 a H-4 da auditoria antecipada do AppSec (testes do Backend; o QA revisa).

Cada caso hostil tem limite de tempo e de memória e roda em SUBPROCESSO: se a correção falhar, quem cai é o processo-filho
(código de saída diferente de zero), nunca a suíte. O que o gravador real produz não pode ser recusado: os testes de
borda mostram o maior valor aceito e o primeiro recusado.

* teto de profundidade de tuplas encadeadas (sem ``MARK``), usadas como chave de dicionário, item de ``set`` ou valor;
* chave de dicionário que não é texto é recusada na pré-varredura, e há um teto de pares por dicionário;
* texto grande revisitado pelo memo é verificado uma vez só (o custo não cresce com o número de referências);
* ``PROTO`` só vale como primeiro opcode.
"""

import os
import pickle
import subprocess
import sys
import time
import zlib
from collections import deque
from pathlib import Path

import pytest

from tests.helpers_f3_6b_legado import (
    PROTOCOL,
    SURROGATE,
    dicionario,
    inteiro,
    legacy_pickle,
    pickle_de,
    proto,
    texto,
)

RAIZ = Path(__file__).resolve().parents[1]
LIMITE_DE_TEMPO = 30  # segundos que o filho pode levar (os casos recusados levam milissegundos)
LIMITE_DE_MEMORIA = 3 * 1024**3
DEPTH = "depth"
KEY_NOT_TEXT = "key_not_text"
DICT_LIMIT = "dict_limit"
MIB = 1024 * 1024

SCRIPT = """
import sys
from empiremuse.serialization import legacy_pickle as leitor
try:
    leitor.load_legacy(sys.stdin.buffer.read(), "session")
except leitor.LegacyFormatError as erro:
    print(erro.code)
else:
    print("ok")
"""


def _limitar_memoria() -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (LIMITE_DE_MEMORIA, LIMITE_DE_MEMORIA))


def em_subprocesso(dados: bytes) -> tuple[str, float]:
    """``(código, segundos)``: ``ok`` se leu, ou o código do ``LegacyFormatError``; falha se o filho caiu."""
    inicio = time.perf_counter()
    resposta = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        input=zlib.compress(dados),
        cwd=RAIZ,
        capture_output=True,
        timeout=LIMITE_DE_TEMPO,
        preexec_fn=_limitar_memoria if hasattr(os, "fork") else None,
    )
    segundos = time.perf_counter() - inicio
    assert resposta.returncode == 0, f"o filho caiu (saída {resposta.returncode}): {resposta.stderr[-300:]!r}"
    return resposta.stdout.decode().strip(), segundos


def recusa_rapida(dados: bytes, codigo: str, segundos: float = 5.0) -> None:
    achado, gasto = em_subprocesso(dados)
    assert achado == codigo, f"código {achado!r}, esperado {codigo!r}"
    assert gasto < segundos, f"levou {gasto:.1f} s"


def na_raiz(chave: str, valor: bytes) -> bytes:
    """``{chave: valor}`` com o valor já codificado."""
    return pickle_de(pickle.EMPTY_DICT, texto(chave), valor, pickle.SETITEM)


# ============================================================================ H-1: tuplas encadeadas


def cadeia_de_tuplas(niveis: int) -> bytes:
    return pickle.NONE + pickle.TUPLE1 * niveis


def tupla_como_chave(niveis: int) -> bytes:
    return pickle_de(pickle.EMPTY_DICT, cadeia_de_tuplas(niveis), pickle.NONE, pickle.SETITEM)


def tupla_como_item_de_set(niveis: int) -> bytes:
    return pickle_de(pickle.EMPTY_SET, pickle.MARK, cadeia_de_tuplas(niveis), pickle.ADDITEMS)


def tupla_como_valor(niveis: int) -> bytes:
    return na_raiz("a", cadeia_de_tuplas(niveis))


class TestProfundidadeDeTuplas:
    def test_o_teto_e_o_declarado(self):
        assert legacy_pickle.MAX_TUPLE_DEPTH == 8

    @pytest.mark.parametrize("construir", [tupla_como_chave, tupla_como_item_de_set, tupla_como_valor])
    @pytest.mark.parametrize("niveis", [9, 100, 100_000, 700_000])
    def test_cadeia_acima_do_teto_e_recusada_sem_derrubar_o_processo(self, construir, niveis):
        recusa_rapida(construir(niveis), DEPTH)

    def test_ate_o_teto_a_cadeia_como_valor_e_lida(self):
        assert em_subprocesso(tupla_como_valor(legacy_pickle.MAX_TUPLE_DEPTH))[0] == "ok"

    def test_ate_o_teto_a_cadeia_como_chave_passa_a_pre_varredura_e_a_chave_nao_e_texto(self):
        assert em_subprocesso(tupla_como_chave(legacy_pickle.MAX_TUPLE_DEPTH))[0] == KEY_NOT_TEXT

    def test_a_profundidade_soma_atraves_do_memo(self):
        """Tupla de 5 níveis guardada no memo e reaproveitada como base de outra de 4 níveis: 9 no total."""
        corpo = cadeia_de_tuplas(5) + pickle.MEMOIZE + pickle.BINGET + b"\x00" + pickle.TUPLE1 * 4
        recusa_rapida(na_raiz("a", corpo + pickle.TUPLE2), DEPTH)

    def test_largura_nao_e_profundidade(self):
        """Tuplas lado a lado, cada uma com 7 níveis, dentro de uma tupla de 3: 8 níveis, passa."""
        corpo = cadeia_de_tuplas(7) * 3 + pickle.TUPLE3
        assert em_subprocesso(na_raiz("a", corpo))[0] == "ok"

    def test_a_sessao_real_tem_tuplas_rasas(self):
        real = {"extra_info": {"guild-yt-oauth": (True, "a", (1, 2))}, "log": deque(maxlen=10)}
        assert em_subprocesso(pickle.dumps(real, protocol=4))[0] == "ok"


# ============================================================================ H-2: pares de dicionário


def setitem_avulso_com_chave_inteira(pares: int) -> bytes:
    primo = 2**61 - 1
    corpo = b"".join(inteiro(primo * (k + 1)) + pickle.NONE + pickle.SETITEM for k in range(pares))
    return pickle_de(pickle.EMPTY_DICT, corpo)


def setitems_em_lotes_com_chave_inteira(pares: int) -> bytes:
    primo = 2**61 - 1
    lotes = []
    for inicio in range(0, pares, 1000):
        itens = b"".join(inteiro(primo * (k + 1)) + pickle.NONE for k in range(inicio, min(inicio + 1000, pares)))
        lotes.append(pickle.MARK + itens + pickle.SETITEMS)
    return pickle_de(pickle.EMPTY_DICT, *lotes)


def pares_de_texto(prefixo: str, quantos: int) -> bytes:
    return b"".join(texto(f"{prefixo}{k}") + pickle.NONE for k in range(quantos))


def setitem_avulso_com_chave_de_texto(pares: int) -> bytes:
    corpo = b"".join(texto(f"k{k}") + pickle.NONE + pickle.SETITEM for k in range(pares))
    return pickle_de(pickle.EMPTY_DICT, corpo)


class TestParesDeDicionario:
    def test_o_teto_e_o_declarado(self):
        assert legacy_pickle.MAX_DICT_PAIRS == 2000

    @pytest.mark.parametrize("pares", [1, 20_000, 400_000])
    def test_chave_inteira_em_setitem_avulso_e_recusada_na_pre_varredura(self, pares):
        recusa_rapida(setitem_avulso_com_chave_inteira(pares), KEY_NOT_TEXT)

    @pytest.mark.parametrize("pares", [1, 20_000, 400_000])
    def test_chave_inteira_em_setitems_e_recusada_na_pre_varredura(self, pares):
        recusa_rapida(setitems_em_lotes_com_chave_inteira(pares), KEY_NOT_TEXT)

    @pytest.mark.parametrize(
        "chave", [pickle.NONE, pickle.NEWTRUE, pickle.EMPTY_TUPLE, inteiro(7), pickle.BINFLOAT + bytes(8)], ids=str
    )
    def test_chave_que_nao_e_texto_de_outros_tipos_tambem(self, chave):
        recusa_rapida(pickle_de(pickle.EMPTY_DICT, chave, pickle.NONE, pickle.SETITEM), KEY_NOT_TEXT)

    def test_chave_de_texto_vinda_do_memo_vale(self):
        corpo = texto("a") + pickle.MEMOIZE + pickle.NONE + pickle.SETITEM + pickle.BINGET + b"\x00" + pickle.NONE
        assert em_subprocesso(pickle_de(pickle.EMPTY_DICT, corpo, pickle.SETITEM))[0] == "ok"

    def test_ate_o_teto_de_pares_passa(self):
        assert em_subprocesso(setitem_avulso_com_chave_de_texto(legacy_pickle.MAX_DICT_PAIRS))[0] == "ok"

    def test_acima_do_teto_de_pares_e_recusado(self):
        recusa_rapida(setitem_avulso_com_chave_de_texto(legacy_pickle.MAX_DICT_PAIRS + 1), DICT_LIMIT)

    def test_o_teto_vale_por_dicionario_e_nao_pelo_documento(self):
        """Quatro dicionários de 1 500 pares (como as faixas de uma fila) somam mais que o teto e passam."""
        faixas = [dicionario(*((texto(f"k{k}"), pickle.NONE) for k in range(1500))) for _ in range(4)]
        corpo = pickle.EMPTY_LIST + pickle.MARK + b"".join(faixas) + pickle.APPENDS
        assert em_subprocesso(na_raiz("queue", corpo))[0] == "ok"

    def test_dicionario_compartilhado_pelo_memo_conta_os_pares_uma_vez_so(self):
        compartilhado = dicionario(*((texto(f"k{k}"), pickle.NONE) for k in range(1500))) + pickle.MEMOIZE
        corpo = pickle.EMPTY_LIST + pickle.MARK + compartilhado + (pickle.BINGET + b"\x00") * 3 + pickle.APPENDS
        assert em_subprocesso(na_raiz("a", corpo))[0] == "ok"

    def test_pares_acrescentados_ao_mesmo_dicionario_por_lotes_somam(self):
        def lote(prefixo: str) -> bytes:
            return pickle.MARK + pares_de_texto(prefixo, 1500) + pickle.SETITEMS

        recusa_rapida(pickle_de(pickle.EMPTY_DICT, lote("k"), lote("j")), DICT_LIMIT)

    def test_setitem_avulso_e_lote_somam_no_mesmo_dicionario(self):
        avulsos = b"".join(texto(f"a{k}") + pickle.NONE + pickle.SETITEM for k in range(1000))
        lote = pickle.MARK + pares_de_texto("b", 1001) + pickle.SETITEMS
        recusa_rapida(pickle_de(pickle.EMPTY_DICT, avulsos, lote), DICT_LIMIT)


# ============================================================================ H-3: texto grande revisitado


def lista_de_referencias(item: bytes, vezes: int) -> bytes:
    """``{"a": [item, item, ...]}``: o primeiro ``item`` é guardado no memo (índice 0) e as demais são ``BINGET``."""
    corpo = item + pickle.MEMOIZE + (pickle.BINGET + b"\x00") * (vezes - 1)
    return na_raiz("a", pickle.EMPTY_LIST + pickle.MARK + corpo + pickle.APPENDS)


def texto_grande_referenciado(vezes: int, tamanho: int = 4 * MIB, sufixo: str = "") -> bytes:
    return lista_de_referencias(texto("a" * tamanho + sufixo), vezes)


def dicionario_de_chave_grande_referenciado(vezes: int, tamanho: int = 4 * MIB) -> bytes:
    pequeno = pickle.EMPTY_DICT + texto("a" * tamanho) + pickle.NONE + pickle.SETITEM
    return lista_de_referencias(pequeno, vezes)


class TestTextoGrandeRevisitado:
    def test_o_texto_compartilhado_e_verificado_uma_vez_so(self):
        achado, segundos = em_subprocesso(texto_grande_referenciado(500))
        assert achado == "ok" and segundos < 3.0, f"{achado}: {segundos:.1f} s"

    def test_o_custo_nao_cresce_com_o_numero_de_referencias(self):
        _, poucas = em_subprocesso(texto_grande_referenciado(10))
        _, muitas = em_subprocesso(texto_grande_referenciado(1000))
        assert muitas < poucas + 2.0, f"10 referências: {poucas:.2f} s; 1000: {muitas:.2f} s"

    def test_chave_grande_de_dicionario_compartilhado_tambem(self):
        achado, segundos = em_subprocesso(dicionario_de_chave_grande_referenciado(500))
        assert achado == "ok" and segundos < 3.0, f"{achado}: {segundos:.1f} s"

    def test_surrogate_no_texto_compartilhado_continua_recusado(self):
        recusa_rapida(texto_grande_referenciado(500, tamanho=MIB, sufixo="\ud800"), SURROGATE, segundos=3.0)

    def test_textos_distintos_continuam_sendo_todos_verificados(self):
        itens = b"".join(texto("a" * 300 + str(k)) for k in range(50))
        corpo = pickle.EMPTY_LIST + pickle.MARK + itens + texto("a" * 300 + "\ud800") + pickle.APPENDS
        recusa_rapida(na_raiz("a", corpo), SURROGATE)


# ============================================================================ H-4: segundo PROTO


class TestSegundoProto:
    @pytest.mark.parametrize("versao", [4, 5, 3, 2, 0, 255])
    def test_proto_no_meio_do_fluxo_e_recusado(self, versao):
        dados = proto(4) + pickle.EMPTY_DICT + proto(versao) + pickle.STOP
        with pytest.raises(legacy_pickle.LegacyFormatError) as erro:
            legacy_pickle.load_legacy(zlib.compress(dados), "session")
        assert erro.value.code == PROTOCOL

    @pytest.mark.parametrize("protocolo", [4, 5])
    def test_proto_so_no_inicio_continua_valendo(self, protocolo):
        dados = zlib.compress(pickle.dumps({"a": 1}, protocol=protocolo))
        assert legacy_pickle.load_legacy(dados, "session") == {"a": 1}

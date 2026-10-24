"""F3-6b, etapa 2 (RED) — ``legacy_pickle.load_legacy``: nenhuma EXECUÇÃO e nenhuma classe fora da allowlist.

Cada caso monta o pickle à mão (``tests/support/leitor_legado.py``) e passa por ``load_legacy``, que tem de recusar com
``LegacyFormatError`` e sem efeito colateral: o comando de cada carga só faz ``touch`` de um arquivo-sentinela dentro de
``tmp_path`` e os chamadores perigosos (``os.system``, ``posix.system``, ``subprocess.Popen``) são trocados por espiões que
registram e não executam. Os testes conferem que o sentinela não existe e que os espiões não foram chamados.

Cobre: os chamadores de execução (``os``, ``posix``, ``subprocess``, ``builtins.eval/exec/__import__/getattr/open``,
``pickle.loads`` aninhado, ``copyreg``, ``_codecs.encode``, ``datetime.date``, ``OrderedDict``), nomes quase certos e com
ponto, o truque do memo (``STACK_GLOBAL`` com strings vindas de ``BINGET``), todos os opcodes fora da lista fechada, o
protocolo (4 e 5; 0 a 3 recusados, inclusive o ``set`` como classe, DE-1 e DE-3), a allowlist por ``kind`` e a raiz.
"""

import os
import pickle
import pickletools
import posix
import struct
import subprocess
import zlib
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from tests.support.leitor_legado import (
    ALLOWED_GLOBALS,
    CORRUPT,
    GLOBAL,
    KINDS,
    OPCODE,
    PROTOCOL,
    TYPE,
    bruto,
    chamada,
    comprimido,
    dicionario,
    em_base64,
    envelope,
    inteiro,
    legacy_pickle,
    lista,
    medir,
    pickle_de,
    proto,
    recusado,
    texto,
    tupla,
)
from tests.support.formato_sessao import gravar, jogador_completo

pytestmark = pytest.mark.critical


def carregar(raw, kind="session"):
    return legacy_pickle.load_legacy(raw, kind)


class Sentinela:
    """O arquivo que qualquer carga EXECUTADA criaria, e as chamadas perigosas que um espião registrou."""

    def __init__(self, alvo, chamadas):
        self.alvo, self.chamadas = alvo, chamadas

    def comando(self) -> str:
        return f"touch {self.alvo}"

    def python(self) -> str:
        return f"open({str(self.alvo)!r}, 'w').close()"

    def intacto(self) -> bool:
        return not self.alvo.exists() and not self.chamadas


@pytest.fixture
def sent(tmp_path, monkeypatch):
    """``Sentinela`` em ``tmp_path``; ``os.system``, ``posix.system`` e ``subprocess.Popen`` viram espiões que não executam."""
    chamadas = []

    def espiao(nome):
        def registrar(*args, **kwargs):
            chamadas.append(nome)
            raise AssertionError(f"{nome} foi chamado")

        return registrar

    monkeypatch.setattr(os, "system", espiao("os.system"))
    monkeypatch.setattr(posix, "system", espiao("posix.system"))
    monkeypatch.setattr(subprocess, "Popen", espiao("subprocess.Popen"))
    return Sentinela(tmp_path / "executou", chamadas)


def cargas_de_execucao(sent):
    """``{descrição: pickle montado}`` para cada chamador de execução; todos teriam efeito se fossem executados."""
    comando, python = texto(sent.comando()), texto(sent.python())
    interno = pickle_de(chamada("posix", "system", comando))
    return {
        "os.system": pickle_de(chamada("os", "system", comando)),
        "posix.system": pickle_de(chamada("posix", "system", comando)),
        "nt.system": pickle_de(chamada("nt", "system", comando)),
        "subprocess.Popen": pickle_de(chamada("subprocess", "Popen", lista(texto("touch"), texto(str(sent.alvo))))),
        "subprocess.check_call": pickle_de(
            chamada("subprocess", "check_call", lista(texto("touch"), texto(str(sent.alvo))))
        ),
        "builtins.eval": pickle_de(chamada("builtins", "eval", python)),
        "builtins.exec": pickle_de(chamada("builtins", "exec", python)),
        "builtins.__import__": pickle_de(chamada("builtins", "__import__", texto("os"))),
        "builtins.getattr": pickle_de(chamada("builtins", "getattr", texto("os"), texto("system"))),
        "builtins.open": pickle_de(chamada("builtins", "open", texto(str(sent.alvo)), texto("w"))),
        "builtins.compile": pickle_de(chamada("builtins", "compile", python, texto("x"), texto("exec"))),
        "pickle.loads aninhado": pickle_de(chamada("pickle", "loads", bruto(interno))),
        "_pickle.loads aninhado": pickle_de(chamada("_pickle", "loads", bruto(interno))),
        "copyreg._reconstructor": pickle_de(chamada("copyreg", "_reconstructor", texto("a"), texto("b"), texto("c"))),
        "copyreg.__newobj__": pickle_de(chamada("copyreg", "__newobj__", texto("a"))),
        "_codecs.encode": pickle_de(chamada("_codecs", "encode", texto("x"), texto("latin1"))),
        "datetime.date": pickle_de(chamada("datetime", "date", inteiro(2026), inteiro(1), inteiro(1))),
        "collections.OrderedDict": pickle_de(chamada("collections", "OrderedDict")),
        "builtins.set": pickle_de(chamada("builtins", "set", lista(inteiro(1)))),
        "builtins.frozenset": pickle_de(chamada("builtins", "frozenset", lista(inteiro(1)))),
        "importlib.import_module": pickle_de(chamada("importlib", "import_module", texto("os"))),
        "marshal.loads": pickle_de(chamada("marshal", "loads", bruto(b"x"))),
    }


NOMES_DAS_CARGAS = sorted(cargas_de_execucao(Sentinela(Path("/tmp/executou"), [])))


class TestExecucaoRecusada:
    @pytest.mark.parametrize("nome", NOMES_DAS_CARGAS)
    @pytest.mark.parametrize("kind", ["session", "queue"])
    def test_chamador_de_execucao_e_recusado_sem_efeito(self, sent, nome, kind):
        dados = cargas_de_execucao(sent)[nome]
        recusado(medir(carregar, envelope(dados, kind), kind), GLOBAL)
        assert sent.intacto(), f"{nome}: o comando foi executado"

    @pytest.mark.parametrize("como_texto", [False, True], ids=["bytes-do-disco", "texto-do-mongo"])
    def test_a_sessao_vinda_do_mongo_tem_a_mesma_recusa(self, sent, como_texto):
        dados = cargas_de_execucao(sent)["os.system"]
        recusado(medir(carregar, envelope(dados, "session", como_texto=como_texto)), GLOBAL)
        assert sent.intacto()

    def test_carga_valida_depois_de_uma_recusada_continua_funcionando(self, sent):
        recusado(medir(carregar, envelope(cargas_de_execucao(sent)["os.system"])), GLOBAL)
        assert carregar(comprimido(pickle_de(dicionario((texto("a"), inteiro(1)))))) == {"a": 1}


# ============================================================================ nomes quase certos, com ponto, e o truque do memo


class TestNomesQuaseCertos:
    @pytest.mark.parametrize("par", sorted(ALLOWED_GLOBALS["session"]), ids=lambda p: ".".join(p))
    def test_o_par_exato_nao_e_recusado_por_ser_um_global(self, par):
        """Só o par EXATO passa pela pré-varredura (a carga abaixo falha depois, por argumentos errados: ``corrupt``)."""
        recusado(medir(carregar, envelope(pickle_de(chamada(*par, texto("sem-sentido"))))), {CORRUPT, TYPE})

    def test_stack_global_sem_duas_strings_e_recusado(self):
        for partes in (
            (pickle.NONE, pickle.NONE),
            (inteiro(1), inteiro(2)),
            (texto("datetime"),),
            (),
            (texto("datetime"), pickle.NONE),
            (lista(), lista()),
        ):
            dados = pickle_de(*partes, pickle.STACK_GLOBAL)
            recusado(medir(carregar, envelope(dados)), {GLOBAL, CORRUPT})


class TestTruqueDoMemo:
    """``STACK_GLOBAL`` com os dois nomes recuperados do memo (``BINGET``): a pré-varredura tem de seguir o memo."""

    def memo_de_os_system(self):
        return texto("os") + pickle.MEMOIZE + texto("system") + pickle.MEMOIZE

    def test_nomes_perigosos_vindos_do_memo_sao_recusados(self, sent):
        comando = texto(sent.comando())
        pegar0, pegar1 = pickle.BINGET + b"\x00", pickle.BINGET + b"\x01"
        dados = pickle_de(
            self.memo_de_os_system(), pegar0, pegar1, pickle.STACK_GLOBAL, comando, pickle.TUPLE1, pickle.REDUCE
        )
        recusado(medir(carregar, envelope(dados)), GLOBAL)
        assert sent.intacto()

    def test_memo_longo(self, sent):
        comando = texto(sent.comando())
        pegar = lambda indice: pickle.LONG_BINGET + struct.pack("<I", indice)  # noqa: E731
        dados = pickle_de(
            self.memo_de_os_system(), pegar(0), pegar(1), pickle.STACK_GLOBAL, comando, pickle.TUPLE1, pickle.REDUCE
        )
        recusado(medir(carregar, envelope(dados)), GLOBAL)
        assert sent.intacto()

    def test_memo_de_nao_string_nao_vira_nome(self):
        dados = pickle_de(
            pickle.EMPTY_LIST, pickle.MEMOIZE, pickle.BINGET + b"\x00", pickle.BINGET + b"\x00", pickle.STACK_GLOBAL
        )
        recusado(medir(carregar, envelope(dados)), {GLOBAL, CORRUPT})

    def test_indice_de_memo_inexistente_e_corrupcao_tratada(self):
        recusado(medir(carregar, envelope(pickle_de(pickle.BINGET + b"\x07"))), CORRUPT)
        recusado(medir(carregar, envelope(pickle_de(pickle.LONG_BINGET + struct.pack("<I", 2**31 - 1)))), CORRUPT)


# ============================================================================ os opcodes fora da lista fechada


NEGADOS = {
    "INT": b"I1\n",
    "LONG": b"L1L\n",
    "LONG4": b"\x8b\x01\x00\x00\x00\x01",
    "STRING": b"S'a'\n",
    "BINSTRING": b"T\x01\x00\x00\x00a",
    "SHORT_BINSTRING": b"U\x01a",
    "BINBYTES8": b"\x8e" + struct.pack("<Q", 1) + b"a",
    "BYTEARRAY8": b"\x96" + struct.pack("<Q", 1) + b"a",
    "NEXT_BUFFER": b"\x97",
    "READONLY_BUFFER": b"\x98",
    "UNICODE": b"Va\n",
    "BINUNICODE8": b"\x8d" + struct.pack("<Q", 1) + b"a",
    "FLOAT": b"F1.0\n",
    "LIST": b"(l",
    "TUPLE": b"(t",
    "DICT": b"(d",
    "FROZENSET": b"(\x91",
    "POP": b"N0",
    "DUP": b"N2",
    "POP_MARK": b"(1",
    "GET": b"g0\n",
    "PUT": b"Np0\n",
    "BINPUT": b"Nq\x00",
    "LONG_BINPUT": b"Nr\x00\x00\x00\x00",
    "EXT1": b"\x82\x01",
    "EXT2": b"\x83\x01\x00",
    "EXT4": b"\x84\x01\x00\x00\x00",
    "GLOBAL": b"cos\nsystem\n",
    "BUILD": b"N}b",
    "INST": b"(ios\nsystem\n",
    "OBJ": b"(No",
    "NEWOBJ": b"N)\x81",
    "NEWOBJ_EX": b"N)}\x92",
    "PERSID": b"Pabc\n",
    "BINPERSID": b"NQ",
}


class TestOpcodesForaDaLista:
    def test_os_trechos_da_tabela_usam_o_opcode_que_dizem(self):
        for nome, trecho in NEGADOS.items():
            usados = {opcode.name for opcode, _arg, _pos in pickletools.genops(pickle_de(trecho, parar=False) + b".")}
            assert nome in usados, nome

    @pytest.mark.parametrize("nome", ["STACK_GLOBAL", "REDUCE"])
    def test_stack_global_e_reduce_so_existem_para_sessao_e_fila(self, nome):
        dados = (
            pickle_de(texto("datetime"), texto("datetime"), pickle.STACK_GLOBAL)
            if nome == "STACK_GLOBAL"
            else pickle_de(pickle.NONE, pickle.EMPTY_TUPLE, pickle.REDUCE)
        )
        recusado(medir(carregar, envelope(dados, "skin"), "skin"), {OPCODE, GLOBAL})

    def test_tuplas_de_0_a_3_itens_passam(self):
        esperado = {"a": (), "b": (1,), "c": (1, 2), "d": (1, 2, 3)}
        assert carregar(comprimido(pickle.dumps(esperado, protocol=4))) == esperado

    def test_frozenset_real_do_pickle_dumps_e_recusado(self):
        recusado(medir(carregar, comprimido(pickle.dumps({"a": frozenset({1})}, protocol=4))), OPCODE)


# ============================================================================ o protocolo (DE-1 e DE-3)


class TestProtocolo:
    def conteudo(self):
        return {
            "dj": {1, 2, 3},
            "time": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "log": deque([1], maxlen=10),
            "n": [1, "a"],
        }

    @pytest.mark.parametrize("versao", [4, 5])
    def test_protocolos_4_e_5_sao_aceitos(self, versao):
        dados = pickle.dumps(self.conteudo(), protocol=versao)
        assert carregar(comprimido(dados)) == self.conteudo()

    @pytest.mark.parametrize("versao", [0, 3])
    def test_protocolos_de_0_a_3_sao_recusados_tambem_sem_set_e_sem_classes(self, versao):
        dados = pickle.dumps({"a": [1, "x", None]}, protocol=versao)
        recusado(medir(carregar, comprimido(dados)), PROTOCOL)

    @pytest.mark.parametrize("versao", [0, 255])
    def test_proto_declarado_fora_de_4_e_5_e_recusado(self, versao):
        dados = pickle_de(dicionario((texto("a"), inteiro(1))), versao=versao)
        recusado(medir(carregar, comprimido(dados)), PROTOCOL)

    def test_sem_proto_no_inicio_e_recusado(self):
        corpo = dicionario((texto("a"), inteiro(1))) + pickle.STOP
        recusado(medir(carregar, comprimido(corpo)), PROTOCOL)

    def test_protocolo_sozinho_sem_nada_e_recusado(self):
        recusado(medir(carregar, comprimido(proto(4))), {CORRUPT, PROTOCOL})


# ============================================================================ a allowlist por kind


class TestAllowlistPorKind:
    @pytest_asyncio.fixture
    async def sessao_real(self):
        from tests.support.formatos_reais import cog_de_sessoes

        return await gravar(cog_de_sessoes(), jogador_completo())

    def test_deque_so_vale_na_sessao(self):
        dados = pickle.dumps({"log": deque([1, 2], maxlen=10)}, protocol=4)
        assert carregar(comprimido(dados), "session")["log"].maxlen == 10
        recusado(medir(carregar, comprimido(dados), "queue"), GLOBAL)
        recusado(medir(carregar, em_base64(dados), "skin"), {OPCODE, GLOBAL})

    def test_dado_de_skin_so_com_tipos_simples_vale_nos_tres_kinds(self):
        skin = {
            "content": "x",
            "embeds": [{"title": "t", "fields": [{"name": "a", "value": "b"}]}],
            "queue_max_entries": 7,
        }
        dados = pickle.dumps(skin, protocol=4)
        assert carregar(em_base64(dados), "skin") == skin
        assert carregar(comprimido(dados), "session") == skin
        assert carregar(comprimido(dados), "queue") == skin

    @pytest.mark.asyncio
    async def test_a_sessao_real_nao_passa_como_fila_nem_como_skin(self, sessao_real):
        dados = pickle.dumps(sessao_real, protocol=4)
        recusado(medir(carregar, comprimido(dados), "queue"), GLOBAL)
        recusado(medir(carregar, em_base64(dados), "skin"), {OPCODE, GLOBAL})

    def test_kind_desconhecido_e_erro_de_uso(self):
        for kind in ("cache", "SESSION", "", None, 1):
            with pytest.raises(ValueError):
                carregar(comprimido(pickle_de(pickle.EMPTY_DICT)), kind)

    @pytest.mark.parametrize("kind", list(KINDS)[:2])
    def test_a_raiz_tem_de_ser_dicionario(self, kind):
        for raiz in (lista(inteiro(1)), pickle.NONE, inteiro(5), texto("x"), tupla(inteiro(1)), conjunto_vazio()):
            recusado(medir(carregar, envelope(pickle_de(raiz), kind), kind), TYPE)


def conjunto_vazio() -> bytes:
    return pickle.EMPTY_SET


# ============================================================================ construtores de classes permitidas com argumentos ruins


class TestClassePermitidaComArgumentosRuins:
    """Mesmo o par certo não pode soltar ``TypeError``/``ValueError``/``OverflowError`` crus."""

    @pytest.mark.parametrize(
        "dados",
        [
            chamada("datetime", "datetime"),
            chamada("collections", "deque", lista(inteiro(1)), inteiro(-5)),
        ],
        ids=range(2),
    )
    def test_argumento_ruim_vira_corrupt(self, dados):
        recusado(medir(carregar, envelope(pickle_de(dados))), CORRUPT)

    def test_corrupcao_do_unpickler_nunca_escapa_crua(self):
        casos = [
            pickle_de(pickle.APPEND),
            pickle_de(pickle.EMPTY_DICT, pickle.NONE, pickle.NONE, pickle.NONE, pickle.SETITEM, pickle.SETITEM),
            pickle_de(pickle.MARK, pickle.SETITEMS),
            pickle_de(pickle.EMPTY_LIST, pickle.APPENDS),
            pickle_de(pickle.NONE, pickle.TUPLE2),
            pickle_de(pickle.NONE, pickle.NONE, pickle.REDUCE),
            pickle_de(pickle.SHORT_BINUNICODE + b"\x02\xff\xfe"),
            pickle_de(pickle.BINUNICODE + struct.pack("<I", 2) + b"\xc3("),
            pickle_de(pickle.EMPTY_DICT, pickle.EMPTY_LIST, pickle.NONE, pickle.SETITEM),  # chave não hashável
            pickle_de(pickle.EMPTY_SET, pickle.MARK, pickle.EMPTY_LIST, pickle.ADDITEMS),  # item não hashável
        ]
        for dados in casos:
            recusado(medir(carregar, envelope(dados)), {CORRUPT, OPCODE})

    def test_zlib_e_pickle_do_mesmo_fluxo_nao_se_confundem(self):
        recusado(medir(carregar, zlib.compress(zlib.compress(pickle_de(pickle.EMPTY_DICT)))), {PROTOCOL, CORRUPT})

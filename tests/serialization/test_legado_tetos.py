"""Tetos do leitor legado testados com o limite reduzido por monkeypatch (sem pickles de milhões de opcodes nem relógio)."""

import pickletools
import zlib

from tests.support.leitor_legado import (
    OPCODE_LIMIT,
    aninhado_em_listas,
    legacy_pickle,
    medir,
    pickle_de_n_opcodes,
    recusado,
)

TETO_REDUZIDO = 300  # em produção: MAX_OPCODES = {"session": 1_500_000, "queue": 600_000, "skin": 50_000}


def ler(dados: bytes):
    return legacy_pickle.load_legacy(zlib.compress(dados), "session")


def test_o_teto_de_opcodes_passa_na_borda_e_recusa_um_a_mais(monkeypatch):
    monkeypatch.setitem(legacy_pickle.MAX_OPCODES, "session", TETO_REDUZIDO)
    dados = pickle_de_n_opcodes(TETO_REDUZIDO)
    assert sum(1 for _ in pickletools.genops(dados)) == TETO_REDUZIDO
    assert ler(dados) == {"a": None}
    recusado(medir(ler, pickle_de_n_opcodes(TETO_REDUZIDO + 1)), OPCODE_LIMIT)


def test_aninhamento_acima_do_teto_de_opcodes_e_recusado_antes_da_estrutura(monkeypatch):
    monkeypatch.setitem(legacy_pickle.MAX_OPCODES, "session", TETO_REDUZIDO)
    recusado(medir(ler, aninhado_em_listas(TETO_REDUZIDO)), OPCODE_LIMIT)

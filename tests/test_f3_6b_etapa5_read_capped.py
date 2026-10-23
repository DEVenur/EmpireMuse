"""F3-6b, etapa 5 (RED, commit 1) — ``empiremuse.serialization.files.read_capped``: o único jeito de ler arquivo de dados.

Movido de ``saved_queue.py`` para ``serialization/files.py`` (plano, seção 6) para as etapas 4 e 5 usarem o mesmo:
``lstat().st_size`` antes de abrir e NUNCA mais que ``limite + 1`` bytes lidos; passou do teto vira ``SchemaError`` (``too_big``)
e o arquivo fica onde está.
"""

import ast
import os
import time
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.helpers_f3_6b_serializacao import TOO_BIG, falha
from tests.helpers_f3_6b_sessao import files
from tests.support.raiz import RAIZ

MIB = 1024 * 1024


def esparso(caminho: Path, tamanho: int) -> Path:
    with open(caminho, "wb") as arquivo:
        arquivo.truncate(tamanho)
    return caminho


class TestReadCapped:
    def test_le_o_arquivo_inteiro_quando_cabe(self, tmp_path):
        alvo = tmp_path / "a.json"
        alvo.write_bytes(b'{"a": 1}')
        assert files.read_capped(alvo, 1024) == b'{"a": 1}'

    def test_arquivo_vazio_devolve_bytes_vazios(self, tmp_path):
        alvo = tmp_path / "vazio"
        alvo.write_bytes(b"")
        assert files.read_capped(alvo, 10) == b""

    def test_exatamente_o_limite_passa_e_um_byte_acima_e_recusado(self, tmp_path):
        alvo = tmp_path / "x"
        alvo.write_bytes(b"a" * 100)
        assert files.read_capped(alvo, 100) == b"a" * 100
        erro = falha(files.read_capped, alvo, 99)
        assert (erro.path, erro.code) == ("", TOO_BIG)

    def test_arquivo_gigante_e_recusado_sem_ser_lido(self, tmp_path):
        alvo = esparso(tmp_path / "gigante", 80 * MIB)
        tracemalloc.start()
        inicio = time.perf_counter()
        try:
            erro = falha(files.read_capped, alvo, 8 * MIB)
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert erro.code == TOO_BIG and time.perf_counter() - inicio < 1.0 and pico < 4 * MIB
        assert alvo.is_file()

    def test_arquivo_que_cresceu_depois_da_conferencia_continua_limitado(self, tmp_path, monkeypatch):
        """O tamanho conferido antes pode mentir (o arquivo cresce): a leitura em si nunca passa de ``limite + 1`` bytes."""
        alvo = esparso(tmp_path / "cresce", 80 * MIB)
        pequeno = SimpleNamespace(st_size=1, st_mode=0o100644)
        for nome in ("lstat", "stat"):
            monkeypatch.setattr(os, nome, lambda *args, _p=pequeno, **kwargs: _p)
            monkeypatch.setattr(Path, nome, lambda self, *args, _p=pequeno, **kwargs: _p)
        tracemalloc.start()
        try:
            erro = falha(files.read_capped, alvo, 1 * MIB)
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert erro.code == TOO_BIG and pico < 4 * MIB

    def test_arquivo_ausente_e_pasta_sao_erros_de_so(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            files.read_capped(tmp_path / "nao-existe", 10)
        with pytest.raises(OSError):
            files.read_capped(tmp_path, 10**6)

    def test_o_conteudo_nao_vai_na_mensagem(self, tmp_path):
        alvo = tmp_path / "x"
        alvo.write_bytes(b"SEGREDO-no-arquivo" * 10)
        erro = falha(files.read_capped, alvo, 5)
        assert "SEGREDO" not in repr(erro.args) + str(erro)


class TestMovidoParaOModuloComum:
    def test_saved_queue_usa_o_helper_comum_e_nao_define_o_proprio(self):
        arvore = ast.parse((RAIZ / "empiremuse" / "utils" / "music" / "saved_queue.py").read_text(encoding="utf-8"))
        definidas = {n.name for n in ast.walk(arvore) if isinstance(n, ast.FunctionDef)}
        importadas = {a.name for n in ast.walk(arvore) if isinstance(n, ast.ImportFrom) for a in n.names}
        assert "_read_capped" not in definidas and "read_capped" in importadas

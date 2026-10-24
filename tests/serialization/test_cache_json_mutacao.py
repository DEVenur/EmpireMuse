"""F3-6b, etapa 6 — complemento do QA depois da mutação do código REAL (``serialization/cache.py`` e ``utils/music/json_cache.py``).

Sobreviventes que não eram equivalentes: teto de profundidade (16) e de nós (2 milhões) do valor de um item, chave de 512
caracteres na gravação e na leitura, a tolerância de 60 s do relógio adiantado, o item que não vale sair já na GRAVAÇÃO, o
teto de bytes (exato, e "os últimos saem" depois do estouro), o aviso da gravação e o da leitura (sem conteúdo), a leitura com
teto de ``max_bytes + 1`` e o erro de ``open`` que não derruba a inicialização.
"""

import json
import time

from empiremuse.serialization.cache import decode_cache, encode_cache
from empiremuse.utils.music.json_cache import load_json_cache
from tests.support.serializacao_nucleo import aninhado

MIB = 1024 * 1024
GRANDE = 64 * MIB


def codificar(itens, **kwargs):
    kwargs.setdefault("max_bytes", GRANDE)
    kwargs.setdefault("saved_at", time.time())
    return encode_cache(itens, **kwargs)


def ler(bruto: bytes, **kwargs):
    kwargs.setdefault("max_bytes", GRANDE)
    kwargs.setdefault("max_age", 600)
    return decode_cache(bruto, **kwargs)


def documento_com(itens, saved_at=None) -> bytes:
    return json.dumps({"v": 1, "saved_at": time.time() if saved_at is None else saved_at, "items": itens}).encode()


class TestProfundidadeENosDoItem:
    def test_um_nivel_acima_o_item_sai_na_gravacao_e_na_leitura(self):
        bruto = codificar([("fundo", aninhado(17)), ("ok", 1)])
        assert b'"fundo"' not in bruto and ler(bruto) == {"ok": 1}
        assert ler(documento_com([{"k": "fundo", "d": aninhado(17)}, {"k": "ok", "d": 1}])) == {"ok": 1}


class TestChaveDeTexto:
    def test_chave_de_512_caracteres_passa_e_a_de_513_sai_na_gravacao(self):
        itens = [("a" * 512, 1), ("b" * 513, 2), ("ok", 3)]
        bruto = codificar(itens)
        assert b"b" * 513 not in bruto and ler(bruto) == {"a" * 512: 1, "ok": 3}


class TestTetoDeBytesNaGravacao:
    def itens(self):
        return [("um", "a" * 100), ("dois", "b" * 100), ("tres", "c" * 100)]

    def test_o_teto_exato_cabe_tudo_e_um_byte_a_menos_tira_o_ultimo(self):
        agora = time.time()
        exato = len(codificar(self.itens(), saved_at=agora))
        assert list(ler(codificar(self.itens(), max_bytes=exato, saved_at=agora))) == ["um", "dois", "tres"]
        assert list(ler(codificar(self.itens(), max_bytes=exato - 1, saved_at=agora))) == ["um", "dois"]


class TestArquivoDeCache:
    def test_erro_de_abertura_nao_derruba_a_inicializacao(self, tmp_path):
        pasta = tmp_path / "e-uma-pasta.json"
        pasta.mkdir()
        assert load_json_cache(pasta, max_bytes=1 * MIB, max_age=600) == {}

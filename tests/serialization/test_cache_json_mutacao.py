"""F3-6b, etapa 6 — complemento do QA depois da mutação do código REAL (``serialization/cache.py`` e ``utils/music/json_cache.py``).

Sobreviventes que não eram equivalentes: teto de profundidade (16) e de nós (2 milhões) do valor de um item, chave de 512
caracteres na gravação e na leitura, a tolerância de 60 s do relógio adiantado, o item que não vale sair já na GRAVAÇÃO, o
teto de bytes (exato, e "os últimos saem" depois do estouro), o aviso da gravação e o da leitura (sem conteúdo), a leitura com
teto de ``max_bytes + 1`` e o erro de ``open`` que não derruba a inicialização.
"""

import json
import logging
import time
import tracemalloc

from empiremuse.serialization.cache import decode_cache, encode_cache
from empiremuse.utils.music.json_cache import load_json_cache, save_json_cache
from tests.support.leitor_legado import SEGREDO
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
    def test_no_teto_de_profundidade_o_item_fica(self):
        valor = aninhado(16)
        assert ler(codificar([("k", valor)])) == {"k": valor}

    def test_um_nivel_acima_o_item_sai_na_gravacao_e_na_leitura(self):
        bruto = codificar([("fundo", aninhado(17)), ("ok", 1)])
        assert b'"fundo"' not in bruto and ler(bruto) == {"ok": 1}
        assert ler(documento_com([{"k": "fundo", "d": aninhado(17)}, {"k": "ok", "d": 1}])) == {"ok": 1}

    def test_item_grande_mas_dentro_do_teto_de_nos_fica(self):
        valor = list(range(100_000))
        assert ler(codificar([("k", valor)])) == {"k": valor}

    def test_acima_de_dois_milhoes_de_nos_o_item_sai(self):
        bruto = codificar([("enorme", [0] * 2_000_001), ("ok", 1)])
        assert b'"enorme"' not in bruto and ler(bruto) == {"ok": 1}


class TestChaveDeTexto:
    def test_chave_de_512_caracteres_passa_e_a_de_513_sai_na_gravacao(self):
        itens = [("a" * 512, 1), ("b" * 513, 2), ("ok", 3)]
        bruto = codificar(itens)
        assert b"b" * 513 not in bruto and ler(bruto) == {"a" * 512: 1, "ok": 3}

    def test_chave_de_513_caracteres_plantada_sai_na_leitura(self):
        assert ler(documento_com([{"k": "a" * 513, "d": 1}, {"k": "a" * 512, "d": 2}])) == {"a" * 512: 2}


class TestRelogioAdiantado:
    AGORA = 1_800_000_000.0

    def test_ate_60_segundos_no_futuro_ainda_vale(self):
        bruto = documento_com([{"k": "k", "d": 1}], saved_at=self.AGORA + 30)
        assert decode_cache(bruto, max_bytes=GRANDE, max_age=600, now=self.AGORA) == {"k": 1}

    def test_alem_de_60_segundos_no_futuro_nao_volta(self):
        bruto = documento_com([{"k": "k", "d": 1}], saved_at=self.AGORA + 120)
        assert decode_cache(bruto, max_bytes=GRANDE, max_age=600, now=self.AGORA) == {}

    def test_o_prazo_e_exclusivo(self):
        quase = documento_com([{"k": "k", "d": 1}], saved_at=self.AGORA - 599)
        no_prazo = documento_com([{"k": "k", "d": 1}], saved_at=self.AGORA - 600)
        assert decode_cache(quase, max_bytes=GRANDE, max_age=600, now=self.AGORA) == {"k": 1}
        assert decode_cache(no_prazo, max_bytes=GRANDE, max_age=600, now=self.AGORA) == {}


class TestTetoDeBytesNaGravacao:
    def itens(self):
        return [("um", "a" * 100), ("dois", "b" * 100), ("tres", "c" * 100)]

    def test_o_teto_exato_cabe_tudo_e_um_byte_a_menos_tira_o_ultimo(self):
        agora = time.time()
        exato = len(codificar(self.itens(), saved_at=agora))
        assert list(ler(codificar(self.itens(), max_bytes=exato, saved_at=agora))) == ["um", "dois", "tres"]
        assert list(ler(codificar(self.itens(), max_bytes=exato - 1, saved_at=agora))) == ["um", "dois"]

    def test_depois_do_estouro_os_que_vem_depois_tambem_saem(self):
        """ "Ao estourar o teto, os últimos saem": um item pequeno depois do que não coube NÃO entra de volta."""
        itens = [("um", "a" * 100), ("grande", "b" * 1000), ("pequeno", "c")]
        agora = time.time()
        limite = len(codificar([itens[0]], saved_at=agora)) + 200
        assert list(ler(codificar(itens, max_bytes=limite, saved_at=agora))) == ["um"]

    def test_o_aviso_da_gravacao_leva_so_a_contagem(self, caplog):
        itens = [(SEGREDO, object()), ("ok", 1), (7, 2)]
        with caplog.at_level(logging.DEBUG):
            codificar(itens)
        avisos = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert avisos and any("2" in m for m in avisos) and all(SEGREDO not in m for m in avisos)

    def test_sem_item_descartado_nao_ha_aviso(self, caplog):
        with caplog.at_level(logging.DEBUG):
            codificar([("ok", 1)])
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


class TestArquivoDeCache:
    def test_arquivo_gigante_e_lido_so_ate_o_teto_mais_um_byte(self, tmp_path):
        alvo = tmp_path / "cache.json"
        with open(alvo, "wb") as arquivo:
            arquivo.truncate(80 * MIB)
        tracemalloc.start()
        try:
            resultado = load_json_cache(alvo, max_bytes=1 * MIB, max_age=600)
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert resultado == {} and pico < 8 * MIB and alvo.is_file()

    def test_erro_de_abertura_nao_derruba_a_inicializacao(self, tmp_path):
        pasta = tmp_path / "e-uma-pasta.json"
        pasta.mkdir()
        assert load_json_cache(pasta, max_bytes=1 * MIB, max_age=600) == {}

    def test_arquivo_ruim_fica_e_o_aviso_leva_o_nome_e_o_motivo_sem_o_conteudo(self, tmp_path, caplog):
        alvo = tmp_path / "cache.json"
        alvo.write_bytes(b'{"v": 1, ' + SEGREDO.encode())
        with caplog.at_level(logging.DEBUG):
            assert load_json_cache(alvo, max_bytes=1 * MIB, max_age=600) == {}
        avisos = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("cache.json" in m for m in avisos) and all(SEGREDO not in m for m in avisos) and alvo.is_file()

    def test_ida_e_volta_pelo_arquivo(self, tmp_path):
        alvo = tmp_path / "cache.json"
        save_json_cache(alvo, [("a", {"x": [1, 2]})], max_bytes=1 * MIB)
        assert load_json_cache(alvo, max_bytes=1 * MIB, max_age=600) == {"a": {"x": [1, 2]}}

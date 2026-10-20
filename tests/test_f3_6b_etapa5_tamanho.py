"""F3-6b, etapa 5 (RED, commit 1) — o teto de 8 MiB da sessão: leitura recusa, gravação REDUZ (R6) e só depois recusa.

A gravação roda a cada 45 s: recusar uma sessão de 9 MiB perderia a retomada, então ``encode_session`` tira, na ordem da seção 1
do plano (decisão final do MAESTRO), e PARA no primeiro passo que couber em 8 MiB:

1. ``extra.lyrics`` de todas as faixas;
2. ``played``;
3. ``queue_autoplay`` e ``failed_tracks``;
4. a cauda de ``queue`` (a faixa que toca agora, a primeira, nunca sai antes das outras);
5. só então a sessão é recusada (``too_big``): com os tetos de faixa do esquema, uma faixa sozinha sempre cabe, então o passo 5 só
   existe por segurança.

Os testes medem o tempo e o log: a contagem de cada passo vai ao log, nunca o conteúdo das faixas.
"""

import json
import logging
import time

import pytest

from tests.helpers_f3_6b_legado import SEGREDO
from tests.helpers_f3_6b_serializacao import TOO_BIG, falha
from tests.helpers_f3_6b_sessao import LIMITES, bruto, codificar, em_bytes, faixa_info, session, sessao_minima

MIB = 1024 * 1024
LIMITE_DE_TEMPO = 30.0
NOS_POR_FAIXA = 4000  # abaixo do teto de 5 000 nós de um campo livre


def peso(prefixo: str, n: int) -> list[str]:
    """~400 KB de JSON em ~4 000 textos distintos (cabe no teto de nós de ``pluginInfo`` e de ``lyrics``)."""
    return [f"{prefixo}-{n}-{i}-" + "x" * 90 for i in range(NOS_POR_FAIXA)]


def com_plugin(n: int, rotulo: str = "p", titulo: str | None = None) -> dict:
    info = faixa_info(n)
    info["pluginInfo"] = {"dados": peso(rotulo, n)}
    if titulo:
        info["title"] = titulo
    return info


def com_letra(n: int, rotulo: str = "l") -> dict:
    info = faixa_info(n)
    info["extra"]["lyrics"] = {"lines": peso(rotulo, n)}
    return info


def com_letra_pequena(n: int) -> dict:
    info = faixa_info(n)
    info["extra"]["lyrics"] = {"lines": ["uma linha"]}
    return info


def normais(inicio: int, quantas: int) -> list[dict]:
    return [faixa_info(inicio + k) for k in range(quantas)]


def ida_e_volta(**campos) -> dict:
    inicio = time.perf_counter()
    dados = session.decode_session(session.encode_session(sessao_minima(**campos)))
    assert time.perf_counter() - inicio < LIMITE_DE_TEMPO
    return dados


def titulos(faixas: list[dict]) -> list[str]:
    return [f["title"] for f in faixas]


def tem_letra(faixas: list[dict]) -> bool:
    return any("lyrics" in f.get("extra", {}) for f in faixas)


def tamanho(dados: dict) -> int:
    return len(session.encode_session(dados))


class TestReducaoNaGravacao:
    def test_o_que_cabe_nao_e_reduzido(self):
        pesadas = [com_plugin(n) for n in range(10, 25)]  # ~6 MiB
        assert sum(len(json.dumps(f)) for f in pesadas) < 8 * MIB
        lidos = ida_e_volta(queue=[com_letra(0)], played=pesadas)
        assert len(lidos["played"]) == 15 and tem_letra(lidos["queue"])

    def test_passo_1_so_as_letras_saem_quando_isso_basta(self):
        lidos = ida_e_volta(
            queue=[com_letra(n) for n in range(25)],  # ~10 MiB só de letra
            played=normais(100, 3),
            queue_autoplay=normais(200, 2),
            failed_tracks=normais(300, 1),
        )
        assert not tem_letra(lidos["queue"]) and len(lidos["queue"]) == 25
        assert titulos(lidos["played"]) == titulos(normais(100, 3))
        assert titulos(lidos["queue_autoplay"]) == titulos(normais(200, 2))
        assert titulos(lidos["failed_tracks"]) == titulos(normais(300, 1))

    def test_a_letra_sai_primeiro_mesmo_quando_nao_basta(self):
        lidos = ida_e_volta(
            queue=[com_letra_pequena(0)] + normais(1, 2),
            played=[com_plugin(n, "played") for n in range(30, 55)],  # ~10 MiB de histórico
            queue_autoplay=normais(200, 2),
            failed_tracks=normais(300, 1),
        )
        assert not tem_letra(lidos["queue"]) and len(lidos["queue"]) == 3
        assert len(lidos["played"]) < 25
        assert titulos(lidos["queue_autoplay"]) == titulos(normais(200, 2))
        assert titulos(lidos["failed_tracks"]) == titulos(normais(300, 1))

    def test_passo_3_played_esgota_antes_de_tocar_no_autoplay_e_nas_falhas(self):
        lidos = ida_e_volta(
            queue=normais(0, 3),
            played=normais(100, 3),
            queue_autoplay=[com_plugin(n, "auto") for n in range(200, 225)],  # ~10 MiB
            failed_tracks=[com_plugin(n, "falha") for n in range(300, 305)],
        )
        assert lidos["played"] == [] and len(lidos["queue"]) == 3
        assert len(lidos["queue_autoplay"]) + len(lidos["failed_tracks"]) < 30

    def test_passo_4_a_cauda_da_fila_sai_depois_de_tudo_e_a_primeira_faixa_fica(self):
        fila = [com_plugin(n, "fila") for n in range(25)]  # ~10 MiB
        lidos = ida_e_volta(
            queue=fila, played=normais(100, 2), queue_autoplay=normais(200, 2), failed_tracks=normais(300, 1)
        )
        assert lidos["played"] == [] and lidos["queue_autoplay"] == [] and lidos["failed_tracks"] == []
        assert 0 < len(lidos["queue"]) < 25
        assert titulos(lidos["queue"]) == titulos(fila)[: len(lidos["queue"])]  # sai a cauda, nunca o começo

    def test_o_resultado_sempre_cabe_no_teto(self):
        dados = sessao_minima(
            queue=[com_plugin(n, "fila") for n in range(25)], played=[com_plugin(n, "played") for n in range(30, 55)]
        )
        assert tamanho(dados) <= LIMITES.max_bytes

    def test_a_ordem_das_faixas_que_ficam_e_a_original(self):
        lidos = ida_e_volta(queue=normais(0, 3), played=[com_plugin(n, "h") for n in range(40, 65)])
        assert titulos(lidos["queue"]) == titulos(normais(0, 3))

    def test_reducao_nao_altera_a_entrada(self):
        fila = [com_letra(n) for n in range(25)]
        dados = sessao_minima(queue=fila)
        session.encode_session(dados)
        assert tem_letra(dados["queue"]) and len(dados["queue"]) == 25

    def test_o_log_leva_so_a_contagem(self, caplog):
        titulo = SEGREDO + "-faixa"
        fila = [com_letra(n) for n in range(25)]
        fila[0] = {**fila[0], "title": titulo}
        with caplog.at_level(logging.DEBUG):
            session.encode_session(sessao_minima(queue=fila))
        mensagens = [r.getMessage() for r in caplog.records]
        assert any(any(c.isdigit() for c in m) for m in mensagens)
        assert all(
            SEGREDO not in m and SEGREDO not in repr(r.args) for m, r in zip(mensagens, caplog.records, strict=True)
        )

    def test_o_resto_da_sessao_nao_muda_na_reducao(self):
        lidos = ida_e_volta(queue=[com_letra(n) for n in range(25)], volume=77, dj={5, 6}, prefix_info="?")
        assert lidos["volume"] == 77 and lidos["dj"] == [5, 6] and lidos["prefix_info"] == "?" and lidos["_id"]


class TestTetoNaLeitura:
    def preencher(self, tamanho_final: int) -> bytes:
        base = codificar()
        assert len(base) < tamanho_final
        return base + b" " * (tamanho_final - len(base))

    def test_um_byte_acima_de_8_mib_e_recusado_antes_de_decodificar(self):
        inicio = time.perf_counter()
        erro = falha(session.decode_session, self.preencher(LIMITES.max_bytes + 1))
        assert erro.code == TOO_BIG and time.perf_counter() - inicio < 2.0

    def test_exatamente_8_mib_ainda_passa(self):
        assert session.decode_session(self.preencher(LIMITES.max_bytes))["_id"]

    def test_documento_gigante_nao_alloca_o_que_promete(self):
        import tracemalloc

        enorme = b"{" + b" " * (50 * MIB)
        tracemalloc.start()
        try:
            erro = falha(session.decode_session, enorme)
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert erro.code == TOO_BIG and pico < 8 * MIB

    def test_texto_no_lugar_de_bytes_tambem_tem_teto(self):
        assert falha(session.decode_session, "{" + " " * (LIMITES.max_bytes + 1)).code == TOO_BIG

    def test_faixa_com_campo_livre_fundo_demais_e_descartada_e_a_sessao_segue(self):
        """Mesmo dentro dos bytes, o campo livre da faixa tem teto de profundidade e de nós."""
        faixa = faixa_info(0)
        faixa["pluginInfo"] = {"a": [[[[[[[[[1]]]]]]]]]}  # fundo demais para um campo livre
        lidos = session.decode_session(em_bytes(bruto(queue=[faixa, faixa_info(1)])))
        assert [f["title"] for f in lidos["queue"]] == ["Música 1"]


@pytest.mark.parametrize("campo", ["queue", "played", "queue_autoplay", "failed_tracks"])
def test_lista_vazia_de_cada_tipo_e_valida(campo):
    assert session.decode_session(codificar(**{campo: []}))[campo] == []

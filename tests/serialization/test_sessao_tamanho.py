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

import time


from tests.support.sessoes import LIMITES, bruto, codificar, em_bytes, faixa_info, session, sessao_minima

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


def normais(inicio: int, quantas: int) -> list[dict]:
    return [faixa_info(inicio + k) for k in range(quantas)]


def ida_e_volta(**campos) -> dict:
    return session.decode_session(session.encode_session(sessao_minima(**campos)))


def titulos(faixas: list[dict]) -> list[str]:
    return [f["title"] for f in faixas]


def tem_letra(faixas: list[dict]) -> bool:
    return any("lyrics" in f.get("extra", {}) for f in faixas)


class TestReducaoNaGravacao:
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

    def test_passo_4_a_cauda_da_fila_sai_depois_de_tudo_e_a_primeira_faixa_fica(self):
        fila = [com_plugin(n, "fila") for n in range(25)]  # ~10 MiB
        lidos = ida_e_volta(
            queue=fila, played=normais(100, 2), queue_autoplay=normais(200, 2), failed_tracks=normais(300, 1)
        )
        assert lidos["played"] == [] and lidos["queue_autoplay"] == [] and lidos["failed_tracks"] == []
        assert 0 < len(lidos["queue"]) < 25
        assert titulos(lidos["queue"]) == titulos(fila)[: len(lidos["queue"])]  # sai a cauda, nunca o começo

    def test_reducao_nao_altera_a_entrada(self):
        fila = [com_letra(n) for n in range(25)]
        dados = sessao_minima(queue=fila)
        session.encode_session(dados)
        assert tem_letra(dados["queue"]) and len(dados["queue"]) == 25


class TestTetoNaLeitura:
    def preencher(self, tamanho_final: int) -> bytes:
        base = codificar()
        assert len(base) < tamanho_final
        return base + b" " * (tamanho_final - len(base))

    def test_exatamente_8_mib_ainda_passa(self):
        assert session.decode_session(self.preencher(LIMITES.max_bytes))["_id"]

    def test_faixa_com_campo_livre_fundo_demais_e_descartada_e_a_sessao_segue(self):
        """Mesmo dentro dos bytes, o campo livre da faixa tem teto de profundidade e de nós."""
        faixa = faixa_info(0)
        faixa["pluginInfo"] = {"a": [[[[[[[[[1]]]]]]]]]}  # fundo demais para um campo livre
        lidos = session.decode_session(em_bytes(bruto(queue=[faixa, faixa_info(1)])))
        assert [f["title"] for f in lidos["queue"]] == ["Música 1"]

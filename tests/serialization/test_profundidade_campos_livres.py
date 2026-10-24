"""F3-6b, etapa 0 — DE-4: profundidade real dos campos livres ``lyrics`` e ``pluginInfo`` (e o que mais é JSON aninhado).

O validador do formato novo (e o validador estrutural do leitor legado) percorre os campos de texto livre com um teto de
profundidade. A proposta inicial é 8. Este arquivo MEDE o dado de verdade, com as formas que os provedores devolvem
(plugin de letras do Lavalink e LavaSrc), montado pelas classes reais e passado pelo ``save_info`` real, e fixa:

* a convenção de contagem: ``profundidade(valor)`` conta NÍVEIS DE CONTÊINER a partir do próprio valor (``{}`` = 1,
  ``{"a": {}}`` = 2, escalar = 0). "Profundidade do campo livre" é a do valor do campo; "profundidade no documento" soma
  os contêineres que o envolvem (sessão → fila → faixa → ``extra`` → campo);
* os números medidos (``TestMedidas``);
* que o teto proposto cabe com folga nos casos reais e no pior caso plausível (``TestTetoProposto``).

Se o dado real mudar (outro plugin, outro formato de letra), as medidas falham e a conversa sobre o teto recomeça.
"""

import pytest

from tests.support.formatos_reais import (
    cog_de_sessoes,
    faixa_parcial,
    letras_com_plugin_por_linha,
    letras_em_texto,
    letras_sincronizadas,
    plugin_info_de_faixa,
    plugin_info_de_playlist,
    profundidade,
)
from tests.support.formato_sessao import gravar, jogador_completo
from tests.persistence.test_formato_skin import skin_realista

TETO_PROPOSTO = 8


def nos(valor) -> int:
    """Visitas ao percorrer ``valor`` (contêineres e escalares, sem contar chaves): é o que o ``max_nodes`` limita."""
    total, pilha = 0, [valor]
    while pilha:
        atual = pilha.pop()
        total += 1
        if isinstance(atual, dict):
            pilha.extend(atual.values())
        elif isinstance(atual, (list, tuple, set, frozenset)):
            pilha.extend(atual)
    return total


def letras_palavra_a_palavra(linhas: int = 20) -> dict:
    """Pior caso plausível: cada linha leva as palavras com tempo próprio dentro do ``plugin`` da linha."""
    letras = letras_com_plugin_por_linha(linhas)
    for linha in letras["lines"]:
        linha["plugin"] = {
            "words": [
                {"word": palavra, "start": indice * 400, "end": indice * 400 + 380}
                for indice, palavra in enumerate(linha["line"].split())
            ]
        }
    return letras


class TestProfundidadeDoHelper:
    """A convenção de contagem, em casos que dá para conferir de cabeça."""

    def test_nao_estoura_a_pilha_em_aninhamento_fundo(self):
        fundo = []
        for _ in range(5_000):
            fundo = [fundo]
        assert profundidade(fundo) == 5_001


class TestMedidas:
    """Os números reais; a coluna do relatório da etapa 0 sai daqui."""

    def test_letras_em_texto_tem_4_niveis(self):
        assert profundidade(letras_em_texto()) == 4

    def test_plugin_info_de_faixa_e_de_playlist_sao_planos(self):
        assert profundidade(plugin_info_de_faixa()) == 1
        assert profundidade(plugin_info_de_playlist()) == 1

    def test_faixa_parcial_e_rasa(self):
        assert profundidade(faixa_parcial(1).info) == 2

    def test_skin_do_editor_tem_5_niveis_e_6_dentro_do_documento_da_sessao(self):
        assert profundidade(skin_realista()) == 5
        assert profundidade({"Minha": skin_realista()}) == 6


class TestTetoProposto:
    def test_o_teto_de_8_cabe_nas_letras_reais_com_folga(self):
        reais = [letras_sincronizadas(), letras_em_texto(), letras_com_plugin_por_linha()]
        assert max(profundidade(letras) for letras in reais) == 4 <= TETO_PROPOSTO - 4

    @pytest.mark.asyncio
    async def test_contado_a_partir_da_raiz_do_documento_8_NAO_cabe_com_folga(self):
        """Se o validador contar do documento (e não do campo), o dado real já gasta os 8 níveis: o teto teria de ser 10."""
        sessao = await gravar(cog_de_sessoes(), jogador_completo())
        assert profundidade(sessao) == TETO_PROPOSTO
        pior_caso = dict(sessao, queue=[{"extra": {"lyrics": letras_palavra_a_palavra()}}])
        assert profundidade(pior_caso) == TETO_PROPOSTO + 2

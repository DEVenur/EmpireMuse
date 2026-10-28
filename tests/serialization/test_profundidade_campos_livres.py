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

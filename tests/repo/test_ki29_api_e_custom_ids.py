"""KI-29 — guardas da divisão de ``music.py``, ``models.py`` e ``interactions.py``: API de módulo e ``custom_id``.

A divisão é só movimentação de código. Estas guardas comparam o estado atual com as listas douradas de
``tests/repo/ki29_golden/`` (geradas do ``main`` antes da divisão; ver ``tests/support/ki29.py``):

* todo nome de nível superior que os módulos originais definiam segue acessível por ``getattr`` no mesmo caminho de
  import (reexportação), porque o resto do bot e os testes importam por ele;
* o conjunto de literais ``custom_id=`` do código da família é idêntico (nenhum componente ganha, perde ou troca de id).
"""

import importlib
import json

import pytest

from tests.support.ki29 import FAMILIAS, GOLDEN, custom_ids_da_familia


def dourado(nome: str) -> dict:
    return json.loads((GOLDEN / nome).read_text(encoding="utf-8"))


@pytest.mark.parametrize("familia", sorted(FAMILIAS))
def test_nomes_de_nivel_superior_seguem_acessiveis_no_caminho_de_import(familia):
    modulo = importlib.import_module(FAMILIAS[familia][0])
    faltando = [nome for nome in dourado("nomes.json")[familia] if not hasattr(modulo, nome)]
    assert not faltando, f"{FAMILIAS[familia][0]} perdeu: {faltando} (faltou reexportar no módulo/pacote?)"


@pytest.mark.parametrize("familia", sorted(FAMILIAS))
def test_custom_ids_literais_sao_os_mesmos(familia):
    atual = custom_ids_da_familia(familia)
    esperado = dourado("custom_ids.json")[familia]
    assert atual == esperado, (
        f"custom_id mudou em {familia}: sumiram {sorted(set(esperado) - set(atual))}, "
        f"apareceram {sorted(set(atual) - set(esperado))}"
    )


def test_o_dourado_nao_esta_vazio():
    """Sem isto, um dourado vazio faria todas as guardas acima passarem sem provar nada."""
    nomes, ids = dourado("nomes.json"), dourado("custom_ids.json")
    assert all(len(nomes[familia]) >= 5 for familia in FAMILIAS)
    assert len(ids["interactions"]) >= 40 and len(ids["music"]) >= 10

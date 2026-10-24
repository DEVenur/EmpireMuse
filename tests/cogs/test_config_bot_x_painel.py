"""F3-5b, etapa 0 — caracterização em VERDE das assimetrias A1 a A25 entre comandos/modais do bot e o painel.

Cada teste fixa o comportamento ATUAL, dos dois lados, chamando os callbacks reais com dublês (sem Discord real, sem
rede, sem ``.env``). Os que passam hoje e continuam passando depois da extração da etapa 1 provam que ela não mexe em
nada. Os marcados ``# MUDA (etapa N, A#)`` são invertidos pela etapa indicada; os demais devem continuar iguais.
Referência: KI-42 (docs/known-issues.md); as assimetrias estão numeradas A1 a A25.
"""

import pytest

from empiremuse.rules.limits import VOLUMES
from tests.cogs.test_canal_de_pedidos_setup_reset import Scenario

# ============================================================================ painel: drivers diretos dos formulários


@pytest.fixture
def world(monkeypatch):
    return Scenario(monkeypatch)


# ============================================================================ A19 — status do canal de voz


# ============================================================================ A20 — volume padrão


class TestA20VolumePadrao:
    ESPERADO = set(range(5, 101, 5)) | set(range(110, 151, 10))

    def test_o_painel_aceita_exatamente_o_mesmo_conjunto(self):
        assert set(VOLUMES) == self.ESPERADO


# ============================================================================ A21, A22 — cargos de DJ

"""A calibração dos tetos de tempo do leitor legado (``tests/support/leitor_legado.py``).

Sob ``coverage`` (ou com a máquina ocupada) o leitor, Python puro, fica várias vezes mais lento e um teto absoluto de segundos
mede o tracing. ``teto_de_tempo`` escala o teto do plano pelo ``fator_de_lentidao``, medido no próprio leitor. Estes testes
impedem que a calibração, por defeito, neutralize todos os tetos de uma vez.
"""

import dataclasses

import pytest

from tests.support.leitor_legado import (
    envelope,
    fator_de_lentidao,
    legacy_pickle,
    medir,
    pickle_de_n_opcodes,
    recusado,
    teto_de_tempo,
)

FATOR_MAXIMO = 25.0  # coverage dá ~5-6x; acima disso a calibração deixaria de apertar o teto
OPCODE_LIMIT = "opcode_limit"
TETO_DE_OPCODES_DA_SKIN = 50_000


def test_o_fator_nunca_aperta_o_teto_do_plano():
    assert fator_de_lentidao() >= 1.0


def test_o_fator_fica_perto_da_realidade_e_nao_afrouxa_em_ordens_de_grandeza():
    assert fator_de_lentidao() < FATOR_MAXIMO, (
        "calibração fora do razoável: os tetos deixariam de pegar custo quadrático"
    )


@pytest.mark.parametrize("segundos", [1.0, 2.0, 8.0])
def test_o_teto_e_o_do_plano_vezes_o_fator(segundos):
    assert teto_de_tempo(segundos) == pytest.approx(segundos * fator_de_lentidao())


def test_o_fator_e_calibrado_uma_vez_por_sessao():
    assert fator_de_lentidao() == fator_de_lentidao()


def test_recusado_ainda_reprova_o_que_passa_muito_do_teto_calibrado():
    """O teto calibrado continua sendo um teto: uma recusa 100 x acima do limite do plano falha com ou sem tracing."""
    dados = envelope(pickle_de_n_opcodes(TETO_DE_OPCODES_DA_SKIN + 1), "skin")
    medida = medir(legacy_pickle.load_legacy, dados, "skin", memoria=False)
    recusado(medida, OPCODE_LIMIT, segundos=8.0)  # a recusa de verdade passa
    lenta = dataclasses.replace(medida, segundos=teto_de_tempo(1.0) * 100)
    with pytest.raises(AssertionError, match="levou"):
        recusado(lenta, OPCODE_LIMIT, segundos=1.0)

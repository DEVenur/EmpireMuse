"""F3-6 — ``retry_after_seconds``: qualquer valor negativo (inteiro ou texto) cai no padrão; o 0 vira o mínimo.

O docstring diz que "negativo" é inválido e cai no padrão (60 s), e a string ``"-5"`` já devolvia 60; o inteiro ``-5`` caía no
piso e devolvia 1 s. Contrato (decisão do MAESTRO): o do docstring, igual para ``int`` e para texto. ``0`` continua sendo um
valor válido que sobe para o mínimo (1 s).
"""

import pytest

from empiremuse.rules.ratelimit import retry_after_seconds


class TestNegativoCaiNoPadrao:
    @pytest.mark.smoke
    @pytest.mark.parametrize("bruto", ["-1", "-3600"], ids=repr)
    def test_texto_negativo_devolve_o_padrao(self, bruto):
        assert retry_after_seconds(bruto) == 60

    def test_negativo_nao_sobe_para_o_minimo_configurado(self):
        """O padrão não é limitado pelo mínimo/máximo de quem chama só por causa do sinal."""
        assert retry_after_seconds(-5, minimum=5, maximum=100) == 60


class TestGuardas:
    @pytest.mark.parametrize("bruto", [None, 1.5], ids=repr)
    def test_invalidos_continuam_no_padrao(self, bruto):
        assert retry_after_seconds(bruto) == 60

    def test_limites_configuraveis_para_positivos(self):
        assert retry_after_seconds(2, minimum=5, maximum=100) == 5
        assert retry_after_seconds(500, minimum=5, maximum=100) == 100
        assert retry_after_seconds(0, minimum=5, maximum=100) == 5

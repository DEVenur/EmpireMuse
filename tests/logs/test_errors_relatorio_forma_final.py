"""Item 7, P4 (CodeRabbit #133) — o nome no embed do relatório é conferido também na forma final.

O redator roda antes do mapeamento de caracteres (R1) e de novo depois dele: um nome que só casa com um segredo registrado depois do mapeamento
sai mascarado em servidor, canais e rodapé, e o teto de 100 caracteres vale para o resultado final.
"""

import pytest

from empiremuse.logs.redact import register_secret
from tests.logs.test_errors_relatorio import prefixo, tratador
from tests.logs.test_errors_relatorio_limites import blocos_de_nome, contexto_com_nome, tudo_do_embed
from tests.logs.test_errors_relatorio_nomes import autor_com_nome

pytestmark = pytest.mark.critical


SEGREDO_FINAL = "".join(["segredo da forma", " final-Z9"])
NOME_CRU = SEGREDO_FINAL.replace(" ", "_")
SEGREDO_COM_ASPAS = "".join(['segredo "entre aspas', '" final-Z8'])
NOME_COM_ASTERISCOS = SEGREDO_COM_ASPAS.replace('"', "*")


@pytest.mark.parametrize(
    ("segredo", "nome"),
    [(SEGREDO_FINAL, NOME_CRU), (SEGREDO_COM_ASPAS, NOME_COM_ASTERISCOS)],
    ids=["underscore", "asterisco"],
)
class TestSegredoSoNaFormaFinal:
    def test_it_is_masked_in_the_guild_the_channels_and_the_footer(self, segredo, nome):
        register_secret(segredo)

        embed = tratador().build_report_embed(contexto_com_nome(f"loja {nome} fim"))

        texto = tudo_do_embed(embed)
        assert segredo not in texto and "***" in texto

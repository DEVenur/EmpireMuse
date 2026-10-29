"""Item 7, P4 (CodeRabbit #133, F1, privacidade) — nomes no embed do relatório do webhook: servidor, canais e rodapé do autor.

Nome de servidor, canal de texto, canal de voz (usuário e bot) e o nome do autor no rodapé são texto de terceiros que sai do host pelo webhook de
erro: segredo registrado sai mascarado, ESC/RLO saem limpos e o nome tem teto de 100 caracteres (R3 do Vigil; os limites do embed estão em ``test_errors_relatorio_limites.py``).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from empiremuse.logs.redact import MAX_MESSAGE_CHARS, register_secret
from tests.logs.test_errors_relatorio import (
    autor,
    canal_de_voz,
    prefixo,
    slash,
    tratador,
)

pytestmark = pytest.mark.critical

SEGREDO_NO_NOME = "".join(["segredo-no-nome-", "do-relatorio-F1x"])
ESC, RLO = "\x1b", "‮"
GIGANTE = "n" * (MAX_MESSAGE_CHARS * 3)


def nome_hostil() -> str:
    return f"{SEGREDO_NO_NOME} a{ESC}[31mb{RLO}c {GIGANTE}"


def autor_com_nome(nome: str):
    a = autor()
    a.__str__ = MagicMock(return_value=nome)
    return a


CAMPOS = [
    ("Servidor:", lambda: {"servidor": {"nome": nome_hostil()}}),
    ("Canal de texto:", lambda: {"canal": nome_hostil()}),
    ("Canal de voz (user):", lambda: {"autor": autor(voz=SimpleNamespace(channel=canal_de_voz(nome_hostil(), 71)))}),
    (
        "Canal de voz (bot):",
        lambda: {
            "autor": autor(voz=SimpleNamespace(channel=canal_de_voz("Outro", 72))),
            "servidor": {"voz_do_bot": SimpleNamespace(channel=canal_de_voz(nome_hostil(), 73))},
        },
    ),
]
IDS = ["servidor", "canal-de-texto", "voz-do-usuario", "voz-do-bot"]


@pytest.mark.parametrize(("campo", "fabrica"), CAMPOS, ids=IDS)
class TestNomesNoEmbed:
    def valor(self, campo: str, fabrica) -> str:
        register_secret(SEGREDO_NO_NOME)
        embed = tratador().build_report_embed(slash({}, **fabrica()))
        return next(f.value for f in embed.fields if f.name == campo)

    def test_a_registered_secret_in_the_name_is_masked(self, campo, fabrica):
        assert SEGREDO_NO_NOME not in self.valor(campo, fabrica)

    def test_escape_and_right_to_left_override_are_stripped(self, campo, fabrica):
        valor = self.valor(campo, fabrica)

        assert ESC not in valor and RLO not in valor

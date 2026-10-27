"""Item 7, P4 (S-31 S5, K-S31-2) — o ``BotCore`` nasce sem menção a ``@everyone`` nem a cargos.

Valor padrão do contrato: ``AllowedMentions(everyone=False, roles=False, users=True, replied_user=True)``. Nome externo com ``@everyone`` num embed ou
mensagem do bot não pode notificar ninguém; menção a usuário e a resposta continuam funcionando. A linha é do ``client.py`` (P4, Turbine).
"""

from types import SimpleNamespace

import disnake
import pytest
from disnake.ext import commands

from empiremuse.utils.client import BotCore

pytestmark = pytest.mark.critical


def bot_novo(**extra) -> BotCore:
    return BotCore(
        command_prefix=commands.when_mentioned,
        intents=disnake.Intents.none(),
        pool=SimpleNamespace(config={"OWNER_IDS": ""}, loop=None),
        identifier="teste",
        **extra,
    )


@pytest.mark.asyncio
class TestMencoesPermitidas:
    async def test_the_bot_starts_without_everyone_or_role_mentions(self):
        permitidas = bot_novo().allowed_mentions

        assert permitidas is not None and permitidas.everyone is False and permitidas.roles is False

    async def test_user_mentions_and_replies_keep_working(self):
        permitidas = bot_novo().allowed_mentions

        assert permitidas is not None and permitidas.users is True and permitidas.replied_user is True

    async def test_an_explicit_allowed_mentions_from_the_caller_is_respected(self):
        explicita = disnake.AllowedMentions.all()

        assert bot_novo(allowed_mentions=explicita).allowed_mentions is explicita

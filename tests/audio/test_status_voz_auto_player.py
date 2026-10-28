"""2.1.2 — status automático do canal de voz no player (contrato I3): padrão D4 e emoji do bot emissor (VP1/VP2), permissão (VP3), palco (VP4),
``disable_voice_status`` (VP5/VP5b), throttle e bucket (VP7/VP9/VP12), reaplicação (VP10) e texto seguro (V-S1/I-S2 dentro do player).

Os métodos de voz do ``PlayerVoiceMixin`` e o ``process_destroy`` são os de produção (``tests/support/voz_auto.py``); relógio e esperas são falsos.
"""

import importlib
from types import ModuleType
from typing import Any

import pytest

from tests.support.voz_auto import (
    REQUISITANTE,
    RelogioFalso,
    executar,
    faixa,
    instalar_relogio,
    jogador,
)

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]


@pytest.fixture
def relogio(monkeypatch: pytest.MonkeyPatch) -> RelogioFalso:
    return instalar_relogio(monkeypatch)


def regras() -> ModuleType:
    return importlib.import_module("empiremuse.rules.voice_status")


def cfg(*, permanente: bool = True, modelo: str | None = None) -> Any:
    r = regras()
    return r.VoiceStatusConfig(permanent=permanente, template=modelo or r.DEFAULT_VOICE_TEMPLATE)


# ============================================================================ V-S1 / I-S2 dentro do player


class TestTextoSeguro:
    async def test_a_title_that_looks_like_a_placeholder_does_not_publish_the_requester_id(
        self, relogio: RelogioFalso
    ) -> None:
        player, bot = jogador(atual=faixa(titulo="{requester.id}"))

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title} / {requester.name}")))

        assert bot.textos == ["{requester.id} / Fulano"] and str(REQUISITANTE) not in bot.textos[0]

    async def test_mentions_and_everyone_in_the_title_are_inert(self, relogio: RelogioFalso) -> None:
        player, bot = jogador(atual=faixa(titulo="<@&1> @everyone <:x:1>", autor="@here"))

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title} - {track.author}")))

        texto = bot.textos[0]
        assert "<" not in texto and "@" not in texto

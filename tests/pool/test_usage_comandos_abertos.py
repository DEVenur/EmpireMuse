"""Regressão do #153: no prefixo todos os bots do pool veem a mesma mensagem; o bot recusado pelo roteamento não fecha o evento do bot que executa."""

from types import SimpleNamespace

from empiremuse.utils.music.errors import PoolException
from empiremuse.utils.usage import UsageRecorder


def test_a_pool_rejection_on_bot_b_does_not_close_bot_a_command():
    usage = UsageRecorder(SimpleNamespace(config={}, metrics=None))
    bot_a = SimpleNamespace(user=SimpleNamespace(id=1), music=SimpleNamespace(players={}))
    bot_b = SimpleNamespace(user=SimpleNamespace(id=2), music=SimpleNamespace(players={}))
    guild = SimpleNamespace(id=10, name="Servidor")
    ctx = SimpleNamespace(guild=guild, channel=SimpleNamespace(id=20, name="geral"), message=SimpleNamespace(id=555))

    usage.command_started("prefix", ctx, "play", bot=bot_a)
    usage.command_finished(ctx, PoolException(), bot=bot_b)  # bot B: PoolException no mesmo id de mensagem
    patches_after_b = [op for op in usage._buffer if op[0] == "patch"]
    usage.command_finished(ctx, None, bot=bot_a)  # bot A: o comando termina bem

    patches = [payload[1] for action, payload in usage._buffer if action == "patch"]
    assert patches_after_b == []
    assert len(patches) == 1 and patches[0]["ok"] is True and "error" not in patches[0]

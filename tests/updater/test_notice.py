"""A15 (item 18, P2) — ``deliver_update_notice(pool, *, runtime_dir, now, detect_version)``: o aviso pós-boot do update.

Entregue uma única vez, pelo bot certo (``bot_id`` pronto), no canal de origem, com o DM a quem pediu como fallback, sem menções e sem
sobrar pendente; pendente com mais de 24 h é descartado. Bots, canais e usuários são fakes; o relógio e a versão detectada são injetados.
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse import paths
from empiremuse.rules.release import Version
from empiremuse.updater.notice import deliver_update_notice
from empiremuse.updater.state import PendingUpdate, pending_path, write_pending

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

AGORA = 1_800_000_000.0
BOT_ID, CANAL, AUTOR = 111, 222, 333
DE, PARA = Version(2, 0, 0), Version(2, 1, 0)
SHA = "a" * 40
CHANGELOG = "# Changelog\n\n## [2.1.0] - 2026-11-01\n- novidade da 2.1.0\n\n## [2.0.0]\n- base\n"


def pendente(**campos) -> PendingUpdate:
    base = {
        "flow": "git",
        "from_version": DE,
        "to_version": PARA,
        "bot_id": BOT_ID,
        "channel_id": CANAL,
        "requested_by": AUTOR,
        "created_at": AGORA - 120,
        "prev_sha": SHA,
        "boots": 1,
    }
    return PendingUpdate(**{**base, **campos})


def erro_http(status=404):
    return disnake.HTTPException(SimpleNamespace(status=status, reason="x"), "falhou")


def bot_falso(identificador=BOT_ID, pronto=True, canal=True, usuario=True):
    bot = MagicMock()
    bot.user = SimpleNamespace(id=identificador)
    bot.bot_ready = pronto
    destino_canal, destino_usuario = MagicMock(), MagicMock()
    destino_canal.send = AsyncMock()
    destino_usuario.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=destino_canal if canal else None)
    bot.fetch_channel = AsyncMock(return_value=destino_canal) if canal else AsyncMock(side_effect=erro_http())
    bot.get_user = MagicMock(return_value=destino_usuario if usuario else None)
    bot.fetch_user = AsyncMock(return_value=destino_usuario) if usuario else AsyncMock(side_effect=erro_http())
    bot.canal, bot.usuario = destino_canal, destino_usuario
    return bot


def pool_com(*bots):
    return SimpleNamespace(get_all_bots=lambda: list(bots))


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    pasta = tmp_path / "runtime"
    pasta.mkdir()
    projeto = tmp_path / "projeto"
    projeto.mkdir()
    (projeto / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    monkeypatch.setattr(paths, "PROJECT_DIR", projeto)
    return pasta


def entregar(pool, runtime, versao):
    async def detectar(pendente_lido):
        return versao

    return deliver_update_notice(pool, runtime_dir=runtime, now=lambda: AGORA, detect_version=detectar)


def sem_mencoes(chamada) -> bool:
    permitido = chamada.kwargs["allowed_mentions"]
    return (
        permitido.everyone is False
        and permitido.users is False
        and permitido.roles is False
        and permitido.replied_user is False
    )


async def test_success_is_delivered_once_by_the_right_bot_in_the_right_channel(runtime):
    certo, outro = bot_falso(), bot_falso(identificador=999)
    write_pending(runtime, pendente())

    await entregar(pool_com(outro, certo), runtime, PARA)
    await entregar(pool_com(outro, certo), runtime, PARA)

    certo.canal.send.assert_awaited_once()
    outro.canal.send.assert_not_awaited()
    outro.get_channel.assert_not_called()
    chamada = certo.canal.send.await_args
    descricao = chamada.kwargs["embed"].description
    assert (
        "Atualizado de 2.0.0 para 2.1.0" in descricao
        and "novidade da 2.1.0" in descricao
        and "v2.1.0/CHANGELOG.md" in descricao
    )
    assert sem_mencoes(chamada)
    certo.get_channel.assert_called_once_with(CANAL)
    assert not pending_path(runtime).exists()


@pytest.mark.parametrize(
    ("campos", "versao"),
    [({"status": "rolled_back"}, DE), ({}, DE)],
    ids=["rollback-pela-guarda", "versao-igual-a-origem"],
)
async def test_a_failed_update_says_it_went_back(runtime, campos, versao):
    bot = bot_falso()
    write_pending(runtime, pendente(**campos))

    await entregar(pool_com(bot), runtime, versao)

    descricao = bot.canal.send.await_args.kwargs["embed"].description
    assert "falhou" in descricao and "voltou para a versão 2.0.0" in descricao and "novidade" not in descricao
    assert not pending_path(runtime).exists()


@pytest.mark.parametrize("versao", [PARA, None], ids=["subiu-a-versao-nova", "versao-nao-detectada"])
async def test_a_rollback_that_is_not_confirmed_by_the_running_version_gets_the_uncertain_notice(runtime, versao):
    """O aviso decide pela versão que SUBIU: o ``rolled_back`` da guarda de boot pode ter falhado em reverter o código."""
    bot = bot_falso()
    write_pending(runtime, pendente(status="rolled_back"))

    await entregar(pool_com(bot), runtime, versao)

    descricao = bot.canal.send.await_args.kwargs["embed"].description
    assert "tentei voltar" in descricao and "não consegui confirmar a versão instalada" in descricao
    assert "Atualizado" not in descricao and "novidade" not in descricao


async def test_an_unconfirmed_version_gets_the_uncertain_notice(runtime):
    bot = bot_falso()
    write_pending(runtime, pendente())

    await entregar(pool_com(bot), runtime, None)

    assert "não consegui confirmar" in bot.canal.send.await_args.kwargs["embed"].description


async def test_without_the_channel_the_notice_goes_by_dm_to_who_asked(runtime):
    bot = bot_falso(canal=False)
    write_pending(runtime, pendente())

    await entregar(pool_com(bot), runtime, PARA)

    bot.canal.send.assert_not_awaited()
    bot.usuario.send.assert_awaited_once()
    assert sem_mencoes(bot.usuario.send.await_args)
    bot.get_user.assert_called_once_with(AUTOR)
    assert not pending_path(runtime).exists()


async def test_without_channel_and_dm_it_only_logs_and_does_not_keep_the_pending(runtime, caplog):
    bot = bot_falso(canal=False, usuario=False)
    write_pending(runtime, pendente())

    with caplog.at_level(logging.INFO):
        await entregar(pool_com(bot), runtime, PARA)

    assert not pending_path(runtime).exists()  # uma única entrega, mesmo que o envio falhe
    assert "novidade" not in caplog.text and "Atualizado" not in caplog.text


@pytest.mark.parametrize(
    "bots",
    [(), ("pronto-de-outro",), ("nao-pronto",)],
    ids=["sem-bots", "so-outro-bot", "bot-certo-ainda-nao-pronto"],
)
async def test_nothing_is_delivered_or_consumed_until_the_requesting_bot_is_ready(runtime, bots):
    mapa = {"pronto-de-outro": bot_falso(identificador=999), "nao-pronto": bot_falso(pronto=False)}
    pool = pool_com(*(mapa[b] for b in bots))
    write_pending(runtime, pendente())

    await entregar(pool, runtime, PARA)

    assert pending_path(runtime).exists()
    assert all(b.canal.send.await_count == 0 and b.usuario.send.await_count == 0 for b in mapa.values())


async def test_a_pending_update_older_than_24_hours_is_dropped_without_a_notice(runtime):
    bot = bot_falso()
    write_pending(runtime, pendente(created_at=AGORA - 25 * 3600))

    await entregar(pool_com(bot), runtime, PARA)

    bot.canal.send.assert_not_awaited()
    assert not pending_path(runtime).exists()


async def test_without_a_pending_update_nothing_happens(runtime):
    bot = bot_falso()

    await entregar(pool_com(bot), runtime, PARA)

    bot.canal.send.assert_not_awaited()

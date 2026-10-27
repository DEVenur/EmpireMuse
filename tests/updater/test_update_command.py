"""A16 (item 18, P2) — o comando ``update`` (``Owner.update.callback(cog, ctx)``), ``ConfirmView`` e a trava ``pool.update_lock``.

Cog, pool, contexto e interações são fakes; ``plan_git_update``/``apply_git_update`` e as consultas de versão são trocados no módulo do
comando. Sem relógio real: a expiração da janela é ``view.on_timeout()`` e a corrida entre dois acionamentos usa um ``Event``.
"""

import asyncio
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from empiremuse import paths
from empiremuse.cogs import legacy_cmds
from empiremuse.cogs.legacy_cmds import Owner
from empiremuse.rules.release import Version
from empiremuse.updater.git_flow import EXIT_RESTART, GitPlan, UpdateError
from tests.support.alvo_git import alvo_git
from empiremuse.updater.state import PendingUpdate, UpdateRequest, read_pending, write_pending
from empiremuse.updater.views import ConfirmView
from empiremuse.utils import client
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.others import CustomContext

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

DONO, BOT_ID, CANAL = 42, 111, 555
DE, PARA = Version(2, 0, 0), Version(2, 1, 0)
SHA = "a" * 40
PLANO = GitPlan(
    current=DE,
    target=PARA,
    tag_object_sha="b" * 40,
    target_commit="c" * 40,
    prev_sha=SHA,
    changelog="- novidade da 2.1.0",
)


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    projeto = tmp_path / "projeto"
    projeto.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(paths, "PROJECT_DIR", projeto)
    monkeypatch.setenv("EMPIREMUSE_HOME", str(runtime))
    monkeypatch.delenv("EMPIREMUSE_VERSION", raising=False)
    monkeypatch.setenv("INVOCATION_ID", "systemd")
    return SimpleNamespace(projeto=projeto, runtime=runtime)


@pytest.fixture
def cog():
    pool = SimpleNamespace(
        update_lock=asyncio.Lock(),
        shutdown=AsyncMock(),
        config={"RUN_RPC_SERVER": False},
        update_ready_checked=False,
        update_watch_task=None,
    )
    bot = SimpleNamespace(
        pool=pool,
        config={},
        user=SimpleNamespace(id=BOT_ID),
        is_owner=AsyncMock(return_value=True),
        get_color=lambda *args: 0,
    )
    cog = Owner.__new__(Owner)
    cog.bot = bot
    cog.log_owner_command = Mock()
    return cog


def ctx_prefixo(autor=DONO):
    ctx = MagicMock(spec=CustomContext)
    ctx.author = SimpleNamespace(id=autor)
    ctx.channel = SimpleNamespace(id=CANAL)
    ctx.send = AsyncMock(return_value=SimpleNamespace(edit=AsyncMock()))
    return ctx


def ctx_painel(autor=DONO):
    ctx = MagicMock()
    ctx.author = SimpleNamespace(id=autor)
    ctx.channel_id = CANAL
    ctx.response.defer = AsyncMock()
    ctx.followup.send = AsyncMock(return_value=SimpleNamespace(edit=AsyncMock()))
    return ctx


def modo_git(ambiente, monkeypatch, plano=PLANO):
    (ambiente.projeto / ".git").mkdir()
    planejar = AsyncMock(return_value=plano)
    monkeypatch.setattr(legacy_cmds, "plan_git_update", planejar)
    return planejar


def clique(autor=DONO):
    interacao = MagicMock()
    interacao.author = SimpleNamespace(id=autor)
    interacao.send = AsyncMock()
    interacao.response.edit_message = AsyncMock()
    interacao.edit_original_message = AsyncMock()
    return interacao


async def oferecer(cog, ctx):
    await Owner.update.callback(cog, ctx)
    return ctx.send.await_args.kwargs["view"]


def pendente_em_disco(runtime):
    write_pending(
        runtime,
        PendingUpdate(
            flow="git",
            from_version=DE,
            to_version=PARA,
            bot_id=1,
            channel_id=2,
            requested_by=3,
            created_at=time.time(),
            prev_sha=SHA,
            **alvo_git(),
        ),
    )


# ============================================================================ recusas


async def test_a_non_owner_is_refused_even_through_the_panel(cog, ambiente, monkeypatch):
    cog.bot.is_owner.return_value = False
    planejar = modo_git(ambiente, monkeypatch)

    with pytest.raises(GenericError):
        await Owner.update.callback(cog, ctx_painel(autor=7))

    planejar.assert_not_awaited()
    assert not cog.bot.pool.update_lock.locked()


async def test_an_existing_pending_update_refuses_a_second_one(cog, ambiente, monkeypatch):
    planejar = modo_git(ambiente, monkeypatch)
    pendente_em_disco(ambiente.runtime)

    with pytest.raises(GenericError) as erro:
        await Owner.update.callback(cog, ctx_prefixo())

    assert "andamento" in erro.value.text
    planejar.assert_not_awaited()
    assert not cog.bot.pool.update_lock.locked()


async def test_an_applying_mark_refuses_a_second_update_even_after_a_day(cog, ambiente, monkeypatch):
    """D9: o ``applying`` (árvore meio aplicada) conta como atualização em andamento e não expira por idade."""
    planejar = modo_git(ambiente, monkeypatch)
    write_pending(
        ambiente.runtime,
        PendingUpdate(
            flow="git",
            from_version=DE,
            to_version=PARA,
            bot_id=1,
            channel_id=2,
            requested_by=3,
            created_at=time.time() - 3 * 24 * 3600,
            prev_sha=SHA,
            status="applying",
            **alvo_git(),
        ),
    )

    with pytest.raises(GenericError) as erro:
        await Owner.update.callback(cog, ctx_prefixo())

    assert "andamento" in erro.value.text
    planejar.assert_not_awaited()


async def test_a_held_lock_refuses_a_second_update_and_is_not_released_by_the_refusal(cog, ambiente, monkeypatch):
    planejar = modo_git(ambiente, monkeypatch)
    await cog.bot.pool.update_lock.acquire()

    with pytest.raises(GenericError):
        await Owner.update.callback(cog, ctx_prefixo())

    planejar.assert_not_awaited()
    assert cog.bot.pool.update_lock.locked()


async def test_two_updates_at_the_same_time_only_one_proceeds(cog, ambiente, monkeypatch):
    liberar, planejando = asyncio.Event(), asyncio.Event()

    async def planejar_devagar(*args, **kwargs):
        planejando.set()
        await liberar.wait()
        return None

    (ambiente.projeto / ".git").mkdir()
    monkeypatch.setattr(legacy_cmds, "plan_git_update", planejar_devagar)
    primeiro = asyncio.create_task(Owner.update.callback(cog, ctx_prefixo()))
    try:
        await asyncio.wait_for(planejando.wait(), timeout=5)  # o 1º já tem a trava e espera o plano
        with pytest.raises(GenericError):
            await Owner.update.callback(cog, ctx_prefixo())
    finally:
        liberar.set()
        await asyncio.wait_for(primeiro, timeout=5)

    assert not cog.bot.pool.update_lock.locked()


# ============================================================================ confirmação: git


async def test_the_confirmation_is_offered_and_keeps_the_lock(cog, ambiente, monkeypatch):
    modo_git(ambiente, monkeypatch)
    ctx = ctx_prefixo()

    view = await oferecer(cog, ctx)

    assert isinstance(view, ConfirmView) and view.requested_by == DONO and view.timeout == 60
    descricao = ctx.send.await_args.kwargs["embed"].description
    assert (
        "2.0.0" in descricao
        and "2.1.0" in descricao
        and "novidade da 2.1.0" in descricao
        and "indisponível" in descricao
    )
    assert cog.bot.pool.update_lock.locked()
    cog.log_owner_command.assert_called_once_with(ctx, "update", "git 2.0.0->2.1.0")


async def test_without_a_supervisor_the_confirmation_warns_the_bot_will_stop(cog, ambiente, monkeypatch):
    monkeypatch.delenv("INVOCATION_ID")
    modo_git(ambiente, monkeypatch)
    ctx = ctx_prefixo()

    await oferecer(cog, ctx)

    assert "vai parar" in ctx.send.await_args.kwargs["embed"].description


async def test_through_the_panel_the_confirmation_is_ephemeral_and_the_command_returns_text(cog, ambiente, monkeypatch):
    modo_git(ambiente, monkeypatch)
    ctx = ctx_painel()

    texto = await Owner.update.callback(cog, ctx)

    assert "só para você" in texto
    assert ctx.followup.send.await_args.kwargs["ephemeral"] is True
    assert isinstance(ctx.followup.send.await_args.kwargs["view"], ConfirmView)
    assert cog.bot.pool.update_lock.locked()


async def test_already_on_the_latest_version_says_so_and_frees_the_lock(cog, ambiente, monkeypatch):
    modo_git(ambiente, monkeypatch, plano=None)
    ctx = ctx_prefixo()

    await Owner.update.callback(cog, ctx)

    assert "mais recente" in ctx.send.await_args.kwargs["embed"].description
    assert not cog.bot.pool.update_lock.locked()


async def test_a_planning_error_is_shown_and_frees_the_lock(cog, ambiente, monkeypatch):
    (ambiente.projeto / ".git").mkdir()
    monkeypatch.setattr(
        legacy_cmds, "plan_git_update", AsyncMock(side_effect=UpdateError("Há alterações locais: app.txt"))
    )

    with pytest.raises(GenericError) as erro:
        await Owner.update.callback(cog, ctx_prefixo())

    assert "app.txt" in erro.value.text and not cog.bot.pool.update_lock.locked()


async def test_only_the_requester_can_click(cog, ambiente, monkeypatch):
    modo_git(ambiente, monkeypatch)
    view = await oferecer(cog, ctx_prefixo())
    intruso = clique(autor=7)

    assert await view.interaction_check(intruso) is False
    intruso.send.assert_awaited_once()
    assert intruso.send.await_args.kwargs["ephemeral"] is True
    assert await view.interaction_check(clique()) is True
    assert cog.bot.pool.update_lock.locked()


async def test_cancel_releases_the_lock_and_allows_a_new_update(cog, ambiente, monkeypatch):
    planejar = modo_git(ambiente, monkeypatch)
    view = await oferecer(cog, ctx_prefixo())
    interacao = clique()

    await view.cancel.callback(interacao)

    assert not cog.bot.pool.update_lock.locked()
    assert "cancelada" in interacao.response.edit_message.await_args.kwargs["content"]
    await oferecer(cog, ctx_prefixo())
    assert planejar.await_count == 2


async def test_expiry_releases_the_lock_once_and_edits_the_message(cog, ambiente, monkeypatch):
    modo_git(ambiente, monkeypatch)
    ctx = ctx_prefixo()
    view = await oferecer(cog, ctx)

    await view.on_timeout()
    await view.on_timeout()

    assert not cog.bot.pool.update_lock.locked()
    mensagem = ctx.send.return_value
    assert "expirou" in mensagem.edit.await_args.kwargs["content"]


async def test_confirm_applies_the_update_and_restarts_with_75(cog, ambiente, monkeypatch):
    modo_git(ambiente, monkeypatch)
    aplicar = AsyncMock()
    monkeypatch.setattr(legacy_cmds, "apply_git_update", aplicar)
    view = await oferecer(cog, ctx_prefixo())
    interacao = clique()

    await view.confirm.callback(interacao)

    aplicar.assert_awaited_once()
    plano, pedido, repo, runtime = aplicar.await_args.args
    assert plano is PLANO and pedido == UpdateRequest(bot_id=BOT_ID, channel_id=CANAL, requested_by=DONO)
    assert Path(repo) == paths.PROJECT_DIR and Path(runtime) == ambiente.runtime
    cog.bot.pool.shutdown.assert_awaited_once_with(EXIT_RESTART)
    assert "Reiniciando" in interacao.edit_original_message.await_args.kwargs["embed"].description
    assert not cog.bot.pool.update_lock.locked()


async def test_the_old_process_stops_its_ready_check_before_the_update_is_applied(cog, ambiente, monkeypatch):
    """I1: o pendente que o apply grava é do processo novo; no instante do apply o velho já não pode marcá-lo como pronto."""
    modo_git(ambiente, monkeypatch)
    pool = cog.bot.pool
    pool.update_watch_task = Mock()
    vistos = {}

    async def aplicar(*args):
        vistos["checado"] = pool.update_ready_checked
        vistos["cancelamentos"] = pool.update_watch_task.cancel.call_count

    monkeypatch.setattr(legacy_cmds, "apply_git_update", aplicar)
    view = await oferecer(cog, ctx_prefixo())

    await view.confirm.callback(clique())

    assert vistos == {"checado": True, "cancelamentos": 1}


async def test_the_old_process_does_not_mark_the_new_pending_update_as_ready(cog, ambiente, monkeypatch):
    """I1 (corrida): pendente novo gravado pelo apply + pool saudável depois dele: quem o promove é o processo novo."""
    modo_git(ambiente, monkeypatch)
    pool = client.BotPool.__new__(client.BotPool)
    pool.update_lock, pool.shutdown = asyncio.Lock(), AsyncMock()
    pool.config, pool.bots, pool.pool_is_healthy = {"RUN_RPC_SERVER": False}, [], lambda: True
    cog.bot.pool = pool

    async def aplicar(*args):
        pendente_em_disco(ambiente.runtime)

    monkeypatch.setattr(legacy_cmds, "apply_git_update", aplicar)
    view = await oferecer(cog, ctx_prefixo())
    await view.confirm.callback(clique())

    await pool.check_pool_ready()

    assert read_pending(ambiente.runtime, time.time()).status == "pending"


async def test_a_second_confirm_click_does_not_apply_twice(cog, ambiente, monkeypatch):
    modo_git(ambiente, monkeypatch)
    aplicar = AsyncMock()
    monkeypatch.setattr(legacy_cmds, "apply_git_update", aplicar)
    view = await oferecer(cog, ctx_prefixo())

    await view.confirm.callback(clique())
    await view.confirm.callback(clique())

    aplicar.assert_awaited_once()


@pytest.mark.parametrize(
    ("erro", "mostra"),
    [
        (UpdateError("O teste de fumaça do código novo falhou; voltei ao anterior."), "fumaça"),
        (RuntimeError("boom"), "Falha inesperada"),
    ],
    ids=["update-error", "erro-inesperado"],
)
async def test_a_failed_update_does_not_restart_and_frees_the_lock(cog, ambiente, monkeypatch, erro, mostra):
    modo_git(ambiente, monkeypatch)
    monkeypatch.setattr(legacy_cmds, "apply_git_update", AsyncMock(side_effect=erro))
    view = await oferecer(cog, ctx_prefixo())
    interacao = clique()

    await view.confirm.callback(interacao)

    cog.bot.pool.shutdown.assert_not_awaited()
    descricao = interacao.edit_original_message.await_args.kwargs["embed"].description
    assert descricao.startswith("❌") and mostra in descricao and "boom" not in descricao
    assert not cog.bot.pool.update_lock.locked()


# ============================================================================ modos sem atualização automática


@pytest.fixture
def versoes(monkeypatch):
    monkeypatch.setattr(legacy_cmds, "latest_official_version", AsyncMock(return_value=PARA))
    monkeypatch.setattr(legacy_cmds, "fetch_remote_changelog", lambda tag: "## [2.1.0]\n- novidade da 2.1.0\n")


async def test_the_panel_mode_shows_the_version_and_points_to_the_host_panel(cog, ambiente, versoes, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_VERSION", "2.0.2")

    texto = await Owner.update.callback(cog, ctx_painel())

    assert "2.1.0" in texto and "2.0.2" in texto and "novidade da 2.1.0" in texto and "painel da hospedagem" in texto
    assert not cog.bot.pool.update_lock.locked()


async def test_the_panel_mode_on_the_latest_version_says_so(cog, ambiente, versoes, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_VERSION", "2.1.0")

    texto = await Owner.update.callback(cog, ctx_painel())

    assert "mais recente" in texto


async def test_the_manual_mode_asks_to_redeploy_the_new_version(cog, ambiente, versoes):
    texto = await Owner.update.callback(cog, ctx_painel())

    assert "Reimplante o código da versão 2.1.0" in texto and not cog.bot.pool.update_lock.locked()


async def test_the_prefix_command_sends_an_embed_instead_of_returning_text(cog, ambiente, versoes):
    ctx = ctx_prefixo()

    assert await Owner.update.callback(cog, ctx) is None
    assert "Reimplante" in ctx.send.await_args.kwargs["embed"].description


async def test_the_panel_mode_still_points_to_the_host_panel_when_the_version_lookup_fails(cog, ambiente, monkeypatch):
    """A imagem não tem o binário do git: a consulta da versão oficial pode falhar, e o dono ainda precisa saber que atualiza pelo painel."""
    monkeypatch.setenv("EMPIREMUSE_VERSION", "2.0.2")
    monkeypatch.setattr(legacy_cmds, "latest_official_version", AsyncMock(return_value=None))

    texto = await Owner.update.callback(cog, ctx_painel())

    assert "Atualize pelo painel" in texto
    assert "mais tarde" not in texto and "Tente de novo" not in texto
    assert not cog.bot.pool.update_lock.locked()


async def test_the_manual_mode_still_points_to_the_redeploy_when_the_version_lookup_fails(cog, ambiente, monkeypatch):
    """Contrato 3.8: sem a versão, o modo manual não manda 'tente mais tarde': diz o que fazer (reimplantar) e onde ver as versões."""
    monkeypatch.setattr(legacy_cmds, "latest_official_version", AsyncMock(return_value=None))

    texto = await Owner.update.callback(cog, ctx_painel())

    assert "Reimplante" in texto
    assert "mais tarde" not in texto and "Tente de novo" not in texto
    assert not cog.bot.pool.update_lock.locked()


async def test_when_the_official_version_cannot_be_read_it_says_so(cog, ambiente, monkeypatch):
    monkeypatch.setattr(legacy_cmds, "latest_official_version", AsyncMock(return_value=None))

    texto = await Owner.update.callback(cog, ctx_painel())

    assert "Não consegui consultar" in texto and not cog.bot.pool.update_lock.locked()


# ============================================================================ defer do painel antes de qualquer I/O de rede


def modo_com_consulta_registrada(modo: str, ambiente, monkeypatch, ctx) -> None:
    """Prepara o modo e troca a consulta de rede por uma que anota quantos ``defer`` já tinham sido aguardados."""
    vistos = ctx.defers_na_rede = []

    async def consulta(*args, **kwargs):
        vistos.append(ctx.response.defer.await_count)
        return PLANO if modo == "git" else PARA

    if modo == "git":
        (ambiente.projeto / ".git").mkdir()
        monkeypatch.setattr(legacy_cmds, "plan_git_update", consulta)
        return
    if modo == "painel":
        monkeypatch.setenv("EMPIREMUSE_VERSION", "2.0.2")
    monkeypatch.setattr(legacy_cmds, "latest_official_version", consulta)
    monkeypatch.setattr(legacy_cmds, "fetch_remote_changelog", lambda tag: "## [2.1.0]\n- novidade\n")


@pytest.mark.parametrize("modo", ["git", "manual", "painel"])
async def test_the_panel_interaction_is_deferred_once_before_any_network_io(cog, ambiente, monkeypatch, modo):
    """O painel só tem 3 s para responder: o defer vem antes da consulta de versão/plano (git ls-remote, API)."""
    ctx = ctx_painel()
    modo_com_consulta_registrada(modo, ambiente, monkeypatch, ctx)

    await Owner.update.callback(cog, ctx)

    assert ctx.defers_na_rede == [1]
    ctx.response.defer.assert_awaited_once()


async def test_the_git_offer_from_the_panel_only_sends_the_ephemeral_confirmation(cog, ambiente, monkeypatch):
    ctx = ctx_painel()
    modo_com_consulta_registrada("git", ambiente, monkeypatch, ctx)

    texto = await Owner.update.callback(cog, ctx)

    ctx.response.defer.assert_awaited_once()
    assert ctx.followup.send.await_args.kwargs["ephemeral"] is True
    assert texto == "Confirmação enviada só para você."


@pytest.mark.parametrize("modo", ["git", "manual"])
async def test_a_prefix_command_is_never_deferred(cog, ambiente, monkeypatch, modo):
    ctx = ctx_prefixo()
    ctx.response = MagicMock(defer=AsyncMock())
    ctx.defer = AsyncMock()
    modo_com_consulta_registrada(modo, ambiente, monkeypatch, ctx)

    await Owner.update.callback(cog, ctx)

    ctx.response.defer.assert_not_awaited()
    ctx.defer.assert_not_awaited()
    assert ctx.defers_na_rede == [0]


async def test_a_failed_rollback_tells_the_channel_and_still_restarts_so_the_boot_guard_reverts(
    cog, ambiente, monkeypatch
):
    """D9: o restore falhou, a marca ``applying`` ficou no disco; o processo precisa reiniciar para o boot_guard reverter limpo."""
    from empiremuse.updater.git_flow import UpdateRollbackFailed

    modo_git(ambiente, monkeypatch)
    erro = UpdateRollbackFailed("A reversão falhou; o bot volta para a versão anterior no próximo início.")
    monkeypatch.setattr(legacy_cmds, "apply_git_update", AsyncMock(side_effect=erro))
    view = await oferecer(cog, ctx_prefixo())
    interacao = clique()

    await view.confirm.callback(interacao)

    descricao = interacao.edit_original_message.await_args.kwargs["embed"].description
    assert descricao.startswith("❌") and "próximo início" in descricao
    cog.bot.pool.shutdown.assert_awaited_once_with(EXIT_RESTART)
    assert not cog.bot.pool.update_lock.locked()


async def test_a_failed_rollback_is_recorded_as_an_error_in_the_log(cog, ambiente, monkeypatch, caplog):
    from empiremuse.updater.git_flow import UpdateRollbackFailed

    modo_git(ambiente, monkeypatch)
    erro = UpdateRollbackFailed("A reversão falhou; o bot volta para a versão anterior no próximo início.")
    monkeypatch.setattr(legacy_cmds, "apply_git_update", AsyncMock(side_effect=erro))
    view = await oferecer(cog, ctx_prefixo())

    with caplog.at_level(logging.ERROR):
        await view.confirm.callback(clique())

    assert [r for r in caplog.records if r.levelno >= logging.ERROR and r.name == legacy_cmds.logger.name]
    cog.bot.pool.shutdown.assert_awaited_once_with(EXIT_RESTART)  # o reinício continua

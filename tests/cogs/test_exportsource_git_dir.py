"""O ``git ls-files`` do ``exportsource`` roda no cwd do processo (a mesma base do ``zip_dir``) com ``--git-dir`` absoluto.

``run_exec`` é trocado no módulo do comando: nada de git de verdade. ``run_git`` sem ``cwd`` (usado pelo ``updatelog``) segue na ``.runtime/``.
"""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import disnake
import pytest

from empiremuse import paths
from empiremuse.cogs import legacy_cmds
from empiremuse.cogs.legacy_cmds import Owner, run_git
from empiremuse.utils.music.errors import GenericError

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    raiz = tmp_path / "projeto"
    runtime = raiz / ".runtime"
    runtime.mkdir(parents=True)
    (raiz / ".example.env").write_text("TOKEN=\n", encoding="utf-8")
    monkeypatch.setattr(paths, "PROJECT_DIR", raiz.resolve())
    monkeypatch.setenv("EMPIREMUSE_HOME", str(runtime))
    outro = tmp_path / "outro"
    (outro / "repo.git").mkdir(parents=True)
    monkeypatch.chdir(outro)
    monkeypatch.setenv("GIT_DIR", "repo.git")
    executar = AsyncMock(return_value=SimpleNamespace(returncode=0, output=""))
    monkeypatch.setattr(legacy_cmds, "run_exec", executar)
    return SimpleNamespace(runtime=runtime.resolve(), outro=outro.resolve(), executar=executar)


@pytest.fixture
def cog():
    cog = Owner.__new__(Owner)
    cog.bot = SimpleNamespace(loop=None, get_color=lambda *args: 0, user="bot")
    cog.log_owner_command = Mock()
    cog.extra_dirs, cog.additional_files = [], []
    return cog


def ctx_dm_fechada():
    ctx = SimpleNamespace(guild=SimpleNamespace(me=None))
    ctx.author = SimpleNamespace(
        send=AsyncMock(side_effect=disnake.Forbidden(SimpleNamespace(status=403, reason="x"), "dm"))
    )
    return ctx


async def test_exportsource_lists_files_from_the_process_cwd_with_an_absolute_git_dir(cog, ambiente):
    cog.bot.loop = asyncio.get_running_loop()
    with pytest.raises(GenericError):  # DM fechada: encerra depois do git ls-files e do zip
        await Owner.exportsource.callback(cog, ctx_dm_fechada())

    comando = ambiente.executar.await_args.args
    git_dir = next(arg for arg in comando if arg.startswith("--git-dir=")).removeprefix("--git-dir=")
    assert "ls-files" in comando
    assert os.path.isabs(git_dir) and Path(git_dir).resolve() == ambiente.outro / "repo.git"
    assert Path(ambiente.executar.await_args.kwargs["cwd"]).resolve() == ambiente.outro


async def test_run_git_without_cwd_keeps_running_in_the_runtime_dir(ambiente):
    await run_git("log", git_dir=str(ambiente.outro / "repo.git"))

    assert Path(ambiente.executar.await_args.kwargs["cwd"]).resolve() == ambiente.runtime

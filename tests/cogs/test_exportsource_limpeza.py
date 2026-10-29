"""V-S29-1 — se o ``zip_dir`` ou o envio falharem por QUALQUER erro, o ``exportsource`` não deixa o ``.env-temp`` (com TOKEN) nem o
``source.zip`` parcial na ``RUNTIME_DIR``.

``run_exec`` (git) e o ``zip_dir`` são trocados no módulo/classe; tudo roda em pastas do ``tmp_path``.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import disnake
import pytest

from empiremuse import paths
from empiremuse.cogs import legacy_cmds
from empiremuse.cogs.legacy_cmds import Owner

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    raiz = tmp_path / "projeto"
    runtime = raiz / ".runtime"
    runtime.mkdir(parents=True)
    (raiz / ".example.env").write_text("TOKEN=\n", encoding="utf-8")
    monkeypatch.setattr(paths, "PROJECT_DIR", raiz.resolve())
    monkeypatch.setenv("EMPIREMUSE_HOME", str(runtime))
    monkeypatch.chdir(raiz)
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.setattr(legacy_cmds, "run_exec", AsyncMock(return_value=SimpleNamespace(returncode=0, output="")))
    return SimpleNamespace(runtime=runtime.resolve())


@pytest.fixture
def cog():
    cog = Owner.__new__(Owner)
    cog.bot = SimpleNamespace(loop=None, get_color=lambda *a: 0, user="bot")
    cog.log_owner_command = Mock()
    cog.extra_dirs, cog.additional_files = [], []
    return cog


def ctx_com_dm(erro):
    ctx = SimpleNamespace(guild=SimpleNamespace(me=None))
    ctx.author = SimpleNamespace(send=AsyncMock(side_effect=erro))
    return ctx


def restos(ambiente) -> list[str]:
    return sorted(p.name for p in ambiente.runtime.iterdir() if p.name in (".env-temp", "source.zip"))


def zip_que_falha_no_meio(erro):
    def zip_dir(filelist):
        (paths.RUNTIME_DIR / "source.zip").write_bytes(b"PK parcial")
        raise erro

    return staticmethod(zip_dir)


@pytest.mark.parametrize(
    "erro", [OSError(40, "Too many levels of symbolic links"), RuntimeError("boom"), ValueError("x")]
)
async def test_a_failing_zip_dir_leaves_no_env_temp_nor_partial_zip(cog, ambiente, monkeypatch, erro):
    cog.bot.loop = asyncio.get_running_loop()
    monkeypatch.setattr(Owner, "zip_dir", zip_que_falha_no_meio(erro))

    with pytest.raises(Exception):
        await Owner.exportsource.callback(
            cog, ctx_com_dm(disnake.Forbidden(SimpleNamespace(status=403, reason="x"), "dm"))
        )

    assert restos(ambiente) == []

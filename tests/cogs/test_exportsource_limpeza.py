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


async def test_a_zip_dir_cancelled_midway_leaves_nothing(cog, ambiente, monkeypatch):
    cog.bot.loop = asyncio.get_running_loop()
    monkeypatch.setattr(Owner, "zip_dir", zip_que_falha_no_meio(asyncio.CancelledError()))

    with pytest.raises(BaseException):
        await Owner.exportsource.callback(
            cog, ctx_com_dm(disnake.Forbidden(SimpleNamespace(status=403, reason="x"), "dm"))
        )

    assert restos(ambiente) == []


async def test_a_dm_send_failing_with_an_http_error_leaves_no_env_temp_nor_zip(cog, ambiente, monkeypatch):
    cog.bot.loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        Owner, "zip_dir", staticmethod(lambda lista: (paths.RUNTIME_DIR / "source.zip").write_bytes(b"PK"))
    )

    with pytest.raises(Exception):
        await Owner.exportsource.callback(
            cog, ctx_com_dm(disnake.HTTPException(SimpleNamespace(status=500, reason="x"), "boom"))
        )

    assert restos(ambiente) == []


async def test_a_closed_dm_still_leaves_nothing(cog, ambiente, monkeypatch):
    """Guarda: o caminho que já limpava continua limpando."""
    cog.bot.loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        Owner, "zip_dir", staticmethod(lambda lista: (paths.RUNTIME_DIR / "source.zip").write_bytes(b"PK"))
    )

    with pytest.raises(Exception):
        await Owner.exportsource.callback(
            cog, ctx_com_dm(disnake.Forbidden(SimpleNamespace(status=403, reason="x"), "dm"))
        )

    assert restos(ambiente) == []


async def test_a_real_symlink_loop_in_the_file_list_does_not_abort_the_export(cog, ambiente, monkeypatch):
    """Ponta a ponta no ``exportsource`` com o ``zip_dir`` real: o laço é pulado e nada sobra depois da DM fechada."""
    raiz = paths.PROJECT_DIR
    (raiz / "a.txt").symlink_to(raiz / "b.txt")
    (raiz / "b.txt").symlink_to(raiz / "a.txt")
    (raiz / "ok.py").write_text("print('ok')\n", encoding="utf-8")
    cog.bot.loop = asyncio.get_running_loop()
    cog.additional_files = []
    vistos: list[list[str]] = []
    real = Owner.zip_dir

    def espiao(lista):
        vistos.append(list(lista))
        return real(["a.txt", "b.txt", "ok.py"])

    monkeypatch.setattr(Owner, "zip_dir", staticmethod(espiao))

    with pytest.raises(Exception) as erro:
        await Owner.exportsource.callback(
            cog, ctx_com_dm(disnake.Forbidden(SimpleNamespace(status=403, reason="x"), "dm"))
        )

    assert vistos and "OSError" not in type(erro.value).__name__ and "Too many levels" not in str(erro.value)
    assert restos(ambiente) == []

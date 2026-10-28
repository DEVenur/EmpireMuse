"""CodeRabbit r4393245316 / r4393245286 — erro de ESCRITA no ``source.zip`` propaga; erro de ORIGEM continua pulado; limpeza que falha não derruba o aviso.

``ZipFile.write`` é dublado para falhar na N-ésima chamada. ``FileNotFoundError`` ao abrir a origem (o arquivo sumiu entre a lista e a
gravação) e link quebrado ou em laço seguem pulados; ``ENOSPC``/``EIO``/``EDQUOT`` na escrita do zip levantam, para o ``exportsource``
apagar o ``source.zip`` parcial e nunca mandá-lo ao dono. Tudo em pastas do ``tmp_path``; nada vai à rede.
"""

import asyncio
import errno
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zipfile import ZipFile

import disnake
import pytest

from empiremuse import paths
from empiremuse.cogs import legacy_cmds
from empiremuse.cogs.legacy_cmds import Owner
from empiremuse.utils.music.errors import GenericError

pytestmark = pytest.mark.critical

ERROS_DE_ESCRITA = [errno.ENOSPC, errno.EIO] + ([errno.EDQUOT] if hasattr(errno, "EDQUOT") else [])


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    raiz = tmp_path / "projeto"
    runtime = raiz / ".runtime"
    runtime.mkdir(parents=True)
    (raiz / ".example.env").write_text("TOKEN=\n", encoding="utf-8")
    for nome in ("a.py", "b.py", "c.py"):
        (raiz / nome).write_text(f"print('{nome}')\n", encoding="utf-8")
    monkeypatch.setattr(paths, "PROJECT_DIR", raiz.resolve())
    monkeypatch.setenv("EMPIREMUSE_HOME", str(runtime))
    monkeypatch.chdir(raiz)
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.setattr(legacy_cmds, "run_exec", AsyncMock(return_value=SimpleNamespace(returncode=0, output="")))
    return SimpleNamespace(raiz=raiz, runtime=runtime.resolve())


@pytest.fixture
def cog():
    cog = Owner.__new__(Owner)
    cog.bot = SimpleNamespace(loop=None, get_color=lambda *a: 0, user="bot")
    cog.log_owner_command = Mock()
    cog.extra_dirs, cog.additional_files = [], ["a.py", "b.py", "c.py"]
    return cog


def falhar_na_chamada(monkeypatch, numero: int, erro: BaseException) -> list[int]:
    """Faz a ``numero``-ésima abertura de entrada do ARQUIVO zip (``ZipFile.open``, onde estouram ENOSPC/EIO/EDQUOT) levantar ``erro``.

    Devolve a lista que registra cada abertura observada.
    """
    original, chamadas = ZipFile.open, []

    def abrir(self, *args, **kwargs):
        chamadas.append(len(chamadas) + 1)
        if len(chamadas) == numero:
            raise erro
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ZipFile, "open", abrir)
    return chamadas


def estragar_depois_da_checagem(monkeypatch, nome: str, como: str) -> None:
    """A origem ``nome`` passa na checagem do ``zip_dir`` e SÓ DEPOIS some (``sumir``) ou vira um laço de links (``laco``)."""
    real = legacy_cmds.is_export_refused

    def checar(caminho):
        recusado = real(caminho)
        if str(caminho) == nome and not recusado:
            os.remove(nome)
            if como == "laco":
                os.symlink(nome, nome)
        return recusado

    monkeypatch.setattr(legacy_cmds, "is_export_refused", checar)


def nomes_no_zip(ambiente) -> list[str]:
    with ZipFile(ambiente.runtime / "source.zip") as pacote:
        return sorted(pacote.namelist())


def restos(ambiente) -> list[str]:
    return sorted(p.name for p in ambiente.runtime.iterdir() if p.name in (".env-temp", "source.zip"))


def ctx(*, enviar):
    return SimpleNamespace(guild=SimpleNamespace(me=None), author=SimpleNamespace(send=enviar))


# ============================================================================ zip_dir


class TestZipDir:
    @pytest.mark.parametrize("codigo", ERROS_DE_ESCRITA, ids=lambda c: errno.errorcode[c])
    def test_a_write_error_in_the_middle_of_the_list_propagates(self, ambiente, monkeypatch, codigo):
        chamadas = falhar_na_chamada(monkeypatch, 2, OSError(codigo, os.strerror(codigo)))

        with pytest.raises(OSError) as erro:
            Owner.zip_dir(["a.py", "b.py", "c.py"])

        assert erro.value.errno == codigo
        assert chamadas == [1, 2], "depois do erro de escrita nada mais deve ser gravado"

    def test_a_write_error_on_the_very_first_file_propagates_too(self, ambiente, monkeypatch):
        falhar_na_chamada(monkeypatch, 1, OSError(errno.ENOSPC, "No space left on device"))

        with pytest.raises(OSError):
            Owner.zip_dir(["a.py", "b.py"])

    def test_a_write_error_on_the_masked_env_propagates(self, ambiente, monkeypatch):
        (ambiente.runtime / ".env-temp").write_text("TOKEN=\n", encoding="utf-8")
        falhar_na_chamada(monkeypatch, 2, OSError(errno.EIO, "Input/output error"))

        with pytest.raises(OSError):
            Owner.zip_dir(["a.py", ".runtime/.env-temp", "c.py"])

    @pytest.mark.parametrize("como", ["sumir", "laco"])
    def test_a_source_file_that_vanishes_or_loops_after_the_check_is_skipped_and_the_rest_goes_in(
        self, ambiente, monkeypatch, como
    ):
        estragar_depois_da_checagem(monkeypatch, "b.py", como)

        Owner.zip_dir(["a.py", "b.py", "c.py"])

        assert nomes_no_zip(ambiente) == ["a.py", "c.py"]

    def test_a_broken_link_and_a_symlink_loop_are_still_skipped_and_the_rest_goes_in(self, ambiente):
        (ambiente.raiz / "quebrado.txt").symlink_to(ambiente.raiz / "nao_existe.txt")
        (ambiente.raiz / "x.txt").symlink_to(ambiente.raiz / "y.txt")
        (ambiente.raiz / "y.txt").symlink_to(ambiente.raiz / "x.txt")

        Owner.zip_dir(["a.py", "quebrado.txt", "x.txt", "b.py"])

        assert nomes_no_zip(ambiente) == ["a.py", "b.py"]

    def test_a_list_with_no_errors_is_written_whole(self, ambiente):
        Owner.zip_dir(["a.py", "b.py", "c.py"])

        assert nomes_no_zip(ambiente) == ["a.py", "b.py", "c.py"]


# ============================================================================ exportsource


class TestExportsource:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("codigo", ERROS_DE_ESCRITA, ids=lambda c: errno.errorcode[c])
    async def test_a_write_error_never_sends_the_partial_zip_and_leaves_nothing(
        self, cog, ambiente, monkeypatch, codigo
    ):
        cog.bot.loop = asyncio.get_running_loop()
        falhar_na_chamada(monkeypatch, 2, OSError(codigo, os.strerror(codigo)))
        enviar = AsyncMock()

        with pytest.raises(Exception):
            await Owner.exportsource.callback(cog, ctx(enviar=enviar))

        enviar.assert_not_awaited()
        assert restos(ambiente) == []

    @pytest.mark.asyncio
    async def test_a_vanished_source_file_does_not_stop_the_export(self, cog, ambiente, monkeypatch):
        cog.bot.loop = asyncio.get_running_loop()
        estragar_depois_da_checagem(monkeypatch, "b.py", "sumir")
        enviar = AsyncMock(side_effect=disnake.Forbidden(SimpleNamespace(status=403, reason="x"), "dm"))

        with pytest.raises(GenericError, match="DM"):
            await Owner.exportsource.callback(cog, ctx(enviar=enviar))

        enviar.assert_awaited_once()  # o zip foi montado e a tentativa de envio aconteceu (a DM fechada é o que encerra)
        assert restos(ambiente) == []


# ============================================================================ r4393245286 — a remoção que falha não derruba o aviso


def remocao_que_falha(monkeypatch, alvo: str = "source.zip"):
    real = os.remove

    def remover(caminho, *args, **kwargs):
        if os.path.basename(str(caminho)) == alvo and os.path.exists(caminho) and os.path.getsize(caminho) > 0:
            raise OSError(errno.EBUSY, "Device or resource busy")
        return real(caminho, *args, **kwargs)

    monkeypatch.setattr(legacy_cmds.os, "remove", remover)


class TestRemocaoQueFalha:
    @pytest.mark.asyncio
    async def test_a_failing_removal_after_a_successful_send_still_reports_success(self, cog, ambiente, monkeypatch):
        cog.bot.loop = asyncio.get_running_loop()
        remocao_que_falha(monkeypatch)
        mensagem = SimpleNamespace(jump_url="https://discord.com/channels/@me/1/2")

        resultado = await Owner.exportsource.callback(cog, ctx(enviar=AsyncMock(return_value=mensagem)))

        assert resultado == f"Arquivo [source.zip](<{mensagem.jump_url}>) foi enviado com sucesso no seu DM."
        assert ".env-temp" not in restos(ambiente)

    @pytest.mark.asyncio
    async def test_a_failing_removal_with_a_closed_dm_still_says_the_dm_is_closed(self, cog, ambiente, monkeypatch):
        cog.bot.loop = asyncio.get_running_loop()
        remocao_que_falha(monkeypatch)
        enviar = AsyncMock(side_effect=disnake.Forbidden(SimpleNamespace(status=403, reason="x"), "dm"))

        with pytest.raises(GenericError, match="DM está desativado"):
            await Owner.exportsource.callback(cog, ctx(enviar=enviar))

        assert ".env-temp" not in restos(ambiente)

    @pytest.mark.asyncio
    async def test_a_failing_removal_of_an_oversized_zip_still_reports_the_size_limit(self, cog, ambiente, monkeypatch):
        cog.bot.loop = asyncio.get_running_loop()
        remocao_que_falha(monkeypatch)
        real = os.path.getsize
        monkeypatch.setattr(
            legacy_cmds.os.path,
            "getsize",
            lambda caminho: 30 * 1024 * 1024 if os.path.basename(str(caminho)) == "source.zip" else real(caminho),
        )
        enviar = AsyncMock()

        with pytest.raises(GenericError, match="25MB"):
            await Owner.exportsource.callback(cog, ctx(enviar=enviar))

        enviar.assert_not_awaited()
        assert ".env-temp" not in restos(ambiente)

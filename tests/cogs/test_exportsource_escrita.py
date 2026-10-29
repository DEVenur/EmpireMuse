"""CodeRabbit r4393245316 / r4393245286 — erro de ESCRITA no ``source.zip`` propaga; erro de ORIGEM continua pulado; limpeza que falha não derruba o aviso.

``ZipFile.write`` é dublado para falhar na N-ésima chamada. ``FileNotFoundError`` ao abrir a origem (o arquivo sumiu entre a lista e a
gravação) e link quebrado ou em laço seguem pulados; ``ENOSPC``/``EIO``/``EDQUOT`` na escrita do zip levantam, para o ``exportsource``
apagar o ``source.zip`` parcial e nunca mandá-lo ao dono. Tudo em pastas do ``tmp_path``; nada vai à rede.
"""

import errno
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zipfile import ZipFile

import pytest

from empiremuse import paths
from empiremuse.cogs import legacy_cmds
from empiremuse.cogs.legacy_cmds import Owner

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


# ============================================================================ zip_dir


class TestZipDir:
    @pytest.mark.parametrize("codigo", ERROS_DE_ESCRITA, ids=lambda c: errno.errorcode[c])
    def test_a_write_error_in_the_middle_of_the_list_propagates(self, ambiente, monkeypatch, codigo):
        chamadas = falhar_na_chamada(monkeypatch, 2, OSError(codigo, os.strerror(codigo)))

        with pytest.raises(OSError) as erro:
            Owner.zip_dir(["a.py", "b.py", "c.py"])

        assert erro.value.errno == codigo
        assert chamadas == [1, 2], "depois do erro de escrita nada mais deve ser gravado"

"""A3-A5 (item 18, P1) — healthcheck por heartbeat: a regra de saúde, o arquivo atômico, a idade e o ``main()``.

O relógio é sempre injetado (``now``); nada dorme. O ``main()`` só lê a variável ``EMPIREMUSE_HEALTH_FILE``. A tarefa do ``BotPool``
(A6) é testada à parte, em ``tests/pool``.
"""

import subprocess
import sys
import time

import pytest

from empiremuse import health
from empiremuse.health import HEALTH_FILE_ENV, MAX_AGE_SECONDS, is_fresh, is_healthy, write_heartbeat
from tests.support.raiz import RAIZ

AGORA = 1_000_000.0


# ============================================================================ A3 — is_healthy


@pytest.mark.parametrize(
    ("bots_prontos", "nos_esperados", "nos_disponiveis", "saudavel"),
    [
        ([], False, 0, False),
        ([], True, 3, False),
        ([True, False], False, 2, False),
        ([False], False, 0, False),
        ([True], True, 0, False),
        ([True, True], True, 0, False),
        ([True], True, 1, True),
        ([True, True], True, 5, True),
        ([True], False, 0, True),
        ([True, True], False, 0, True),
    ],
)
def test_is_healthy(bots_prontos, nos_esperados, nos_disponiveis, saudavel):
    assert is_healthy(bots_prontos, nos_esperados, nos_disponiveis) is saudavel


# ============================================================================ A4 — heartbeat


def test_a_fresh_heartbeat_is_fresh_up_to_the_limit_and_stale_after(tmp_path):
    arquivo = tmp_path / "saude"
    write_heartbeat(arquivo, AGORA)

    assert is_fresh(arquivo, AGORA)
    assert is_fresh(arquivo, AGORA + MAX_AGE_SECONDS)
    assert not is_fresh(arquivo, AGORA + MAX_AGE_SECONDS + 1)
    assert not is_fresh(arquivo, AGORA + 3600)


def test_the_max_age_is_a_parameter(tmp_path):
    arquivo = tmp_path / "saude"
    write_heartbeat(arquivo, AGORA)

    assert is_fresh(arquivo, AGORA + 5, max_age=5)
    assert not is_fresh(arquivo, AGORA + 6, max_age=5)


def test_a_new_write_renews_the_heartbeat(tmp_path):
    arquivo = tmp_path / "saude"
    write_heartbeat(arquivo, AGORA)
    write_heartbeat(arquivo, AGORA + 100)

    assert is_fresh(arquivo, AGORA + 100 + MAX_AGE_SECONDS)
    assert not is_fresh(arquivo, AGORA + 100 + MAX_AGE_SECONDS + 1)


def test_without_the_file_it_is_not_fresh(tmp_path):
    assert not is_fresh(tmp_path / "nao-existe", AGORA)


def test_the_write_leaves_only_the_target_file(tmp_path):
    write_heartbeat(tmp_path / "saude", AGORA)
    write_heartbeat(tmp_path / "saude", AGORA + 1)

    assert [p.name for p in tmp_path.iterdir()] == ["saude"]


def test_the_write_goes_through_a_temporary_in_the_same_directory_and_os_replace(tmp_path, monkeypatch):
    chamadas = []
    real = health.os.replace

    def espia(origem, destino):
        chamadas.append((origem, destino))
        return real(origem, destino)

    monkeypatch.setattr(health.os, "replace", espia)
    alvo = tmp_path / "saude"

    write_heartbeat(alvo, AGORA)

    ((origem, destino),) = chamadas
    assert str(destino) == str(alvo) and str(origem) != str(alvo)
    assert tmp_path == type(tmp_path)(origem).parent


def test_a_failed_replace_keeps_the_previous_heartbeat_whole(tmp_path, monkeypatch):
    alvo = tmp_path / "saude"
    write_heartbeat(alvo, AGORA)

    def falha(origem, destino):
        raise OSError("disco cheio")

    monkeypatch.setattr(health.os, "replace", falha)
    with pytest.raises(OSError, match="disco cheio"):
        write_heartbeat(alvo, AGORA + 500)
    monkeypatch.undo()

    assert is_fresh(alvo, AGORA + MAX_AGE_SECONDS)
    assert not is_fresh(alvo, AGORA + 500 + MAX_AGE_SECONDS)


# ============================================================================ main()


def test_main_is_zero_for_a_fresh_heartbeat(tmp_path, monkeypatch):
    alvo = tmp_path / "saude"
    write_heartbeat(alvo, time.time())
    monkeypatch.setenv(HEALTH_FILE_ENV, str(alvo))

    assert health.main() == 0


def test_main_is_one_for_a_stale_heartbeat(tmp_path, monkeypatch):
    alvo = tmp_path / "saude"
    write_heartbeat(alvo, time.time() - 10 * MAX_AGE_SECONDS)
    monkeypatch.setenv(HEALTH_FILE_ENV, str(alvo))

    assert health.main() == 1


def test_main_is_one_without_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv(HEALTH_FILE_ENV, str(tmp_path / "nao-existe"))

    assert health.main() == 1


def test_main_is_one_without_the_variable(monkeypatch):
    monkeypatch.delenv(HEALTH_FILE_ENV, raising=False)

    assert health.main() == 1


# ============================================================================ A5 — só stdlib


def test_running_the_module_imports_nothing_third_party(tmp_path):
    """``python -m empiremuse.health`` roda no HEALTHCHECK sem o bot: nem disnake, nem aiohttp, nem tornado."""
    codigo = (
        "import runpy, sys\n"
        "try:\n"
        "    runpy.run_module('empiremuse.health', run_name='__main__')\n"
        "except SystemExit as saida:\n"
        "    codigo = saida.code\n"
        "carregados = [m for m in ('disnake', 'aiohttp', 'tornado') if m in sys.modules]\n"
        "print(codigo, carregados)\n"
    )
    ambiente = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(RAIZ), "EMPIREMUSE_HOME": str(tmp_path)}

    resultado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=tmp_path, env=ambiente, capture_output=True, text=True, timeout=60
    )

    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == "1 []"

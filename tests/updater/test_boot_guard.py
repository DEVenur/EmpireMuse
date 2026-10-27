"""A14 (item 18, P2) — a guarda de boot do fluxo git: ``boot_guard.run(runtime_dir, repo_dir, now, *, python, runner)``.

Cada subida com um pendente ``git`` soma 1 em ``boots``; no 3º boot sem o pool ter ficado pronto (``boots > 2``) o código volta ao
``prev_sha`` (checkout + reinstalação do lock), o pendente vira ``rolled_back`` e o processo sai com 75. O fluxo ``docker`` não é tocado,
e um JSON inválido (ou velho demais) é apagado sem mexer em nada. Repositório git real em ``tmp_path``; o ``runner`` só grava e delega.
"""

import asyncio
import json
import shutil
import subprocess

import pytest

from empiremuse.rules.release import Version
from empiremuse.updater import boot_guard
from empiremuse.updater.git_flow import EXIT_RESTART, ExecResult, UpdateError, restore_checkout, run_exec
from empiremuse.updater.state import PendingUpdate, pending_path, write_pending
from tests.updater.test_git_flow import commit, git

pytestmark = pytest.mark.critical

AGORA = 1_800_000_000.0
DIGEST = "sha256:" + "ab" * 32


class Gravador:
    """Grava as chamadas e seus códigos de saída; ``resposta(args)`` pode devolver um ``ExecResult`` no lugar da execução real."""

    def __init__(self, resposta=None):
        self.chamadas = []
        self.resultados = []
        self.resposta = resposta

    async def __call__(self, *args, **kwargs):
        self.chamadas.append(args)
        resultado = (self.resposta(args) if self.resposta else None) or await run_exec(*args, **kwargs)
        self.resultados.append((args, resultado.returncode))
        return resultado


def e_instalacao(args) -> bool:
    return "pip" in [str(a) for a in args] and "install" in [str(a) for a in args]


def instalacao_falha(args):
    return ExecResult(1, "falhou") if e_instalacao(args) else None


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    """Repositório com dois commits, HEAD destacado no segundo (o código novo) e o primeiro como ``prev_sha``."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    anterior = commit(repo, {"app.txt": "antigo\n"}, "antigo")
    commit(repo, {"app.txt": "novo\n"}, "novo")
    git(repo, "checkout", "-q", "--detach", "HEAD")
    python = tmp_path / "python-falso"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)
    monkeypatch.setattr(shutil, "which", lambda *args, **kwargs: None)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    return repo, runtime, anterior, str(python)


def pendente(anterior: str, *, flow="git", boots=0, status="pending", criado=AGORA - 60) -> PendingUpdate:
    return PendingUpdate(
        flow=flow,
        from_version=Version(2, 0, 0),
        to_version=Version(2, 1, 0),
        bot_id=1,
        channel_id=2,
        requested_by=3,
        created_at=criado,
        prev_sha=anterior if flow == "git" else None,
        digest=DIGEST if flow == "docker" else None,
        boots=boots,
        status=status,
    )


def guardar(mundo, gravador):
    repo, runtime, _, python = mundo
    boot_guard.run(runtime, repo, AGORA, python=python, runner=gravador)


def em_disco(runtime) -> dict:
    return json.loads(pending_path(runtime).read_text())


def test_without_a_pending_update_nothing_happens(mundo):
    gravador = Gravador()

    guardar(mundo, gravador)

    assert gravador.chamadas == []


@pytest.mark.parametrize(("antes", "depois"), [(0, 1), (1, 2)], ids=["1o-boot", "2o-boot"])
def test_the_first_two_boots_only_count(mundo, antes, depois):
    repo, runtime, anterior, _ = mundo
    write_pending(runtime, pendente(anterior, boots=antes))
    head = git(repo, "rev-parse", "HEAD")
    gravador = Gravador()

    guardar(mundo, gravador)

    assert em_disco(runtime)["boots"] == depois and em_disco(runtime)["status"] == "pending"
    assert gravador.chamadas == [] and git(repo, "rev-parse", "HEAD") == head


def test_the_third_boot_rolls_back_marks_the_pending_and_exits_with_75(mundo):
    repo, runtime, anterior, python = mundo
    write_pending(runtime, pendente(anterior, boots=2))
    gravador = Gravador()

    with pytest.raises(SystemExit) as saida:
        guardar(mundo, gravador)

    assert saida.value.code == EXIT_RESTART == 75
    assert git(repo, "rev-parse", "HEAD") == anterior
    assert subprocess.run(["git", "-C", str(repo), "symbolic-ref", "-q", "HEAD"], capture_output=True).returncode != 0
    argvs = [[str(a) for a in args] for args in gravador.chamadas]
    assert any("checkout" in a and "--detach" in a and anterior in a for a in argvs)
    assert any(a[0] == python and "pip" in a and "install" in a and "--require-hashes" in a for a in argvs)
    assert em_disco(runtime)["status"] == "rolled_back" and em_disco(runtime)["prev_sha"] == anterior
    assert [codigo for args, codigo in gravador.resultados if e_instalacao(args)] == [
        0
    ]  # a reinstalação do lock deu certo
    assert all(codigo == 0 for _, codigo in gravador.resultados)


def test_a_failing_reinstall_during_the_rollback_still_exits_with_75_and_keeps_the_mark(mundo):
    repo, runtime, anterior, _ = mundo
    write_pending(runtime, pendente(anterior, boots=2))
    gravador = Gravador(instalacao_falha)

    with pytest.raises(SystemExit) as saida:
        guardar(mundo, gravador)

    assert saida.value.code == EXIT_RESTART
    assert [codigo for args, codigo in gravador.resultados if e_instalacao(args)] == [1]
    assert git(repo, "rev-parse", "HEAD") == anterior and em_disco(runtime)["status"] == "rolled_back"


def test_restore_checkout_treats_a_non_zero_reinstall_as_an_update_error(mundo):
    repo, _, anterior, python = mundo

    with pytest.raises(UpdateError):
        asyncio.run(restore_checkout(repo, anterior, python=python, runner=Gravador(instalacao_falha)))

    assert git(repo, "rev-parse", "HEAD") == anterior


def test_a_docker_pending_update_is_never_touched(mundo):
    repo, runtime, anterior, _ = mundo
    write_pending(runtime, pendente(anterior, flow="docker", boots=7))
    antes = pending_path(runtime).read_bytes()
    gravador = Gravador()

    guardar(mundo, gravador)

    assert pending_path(runtime).read_bytes() == antes and gravador.chamadas == []


@pytest.mark.parametrize(
    "conteudo", ["isto não é json", '{"v": 1, "flow": "git"}', "[]"], ids=["texto", "campos-faltando", "lista"]
)
def test_an_invalid_pending_file_is_deleted_without_any_action(mundo, conteudo):
    repo, runtime, _, _ = mundo
    pending_path(runtime).write_text(conteudo, encoding="utf-8")
    head = git(repo, "rev-parse", "HEAD")
    gravador = Gravador()

    guardar(mundo, gravador)

    assert not pending_path(runtime).exists() and gravador.chamadas == [] and git(repo, "rev-parse", "HEAD") == head


@pytest.mark.parametrize("created_at", [10**400, 2**63, 1e300], ids=["gigante", "2-a-63", "float-gigante"])
def test_a_pending_file_with_an_absurd_created_at_is_discarded_and_the_boot_goes_on(mundo, created_at):
    repo, runtime, anterior, _ = mundo
    write_pending(runtime, pendente(anterior))
    dados = em_disco(runtime)
    dados["created_at"] = created_at
    pending_path(runtime).write_text(json.dumps(dados), encoding="utf-8")
    gravador = Gravador()

    guardar(mundo, gravador)

    assert not pending_path(runtime).exists() and gravador.chamadas == []


def test_a_pending_update_older_than_a_day_is_discarded_without_rolling_back(mundo):
    repo, runtime, anterior, _ = mundo
    write_pending(runtime, pendente(anterior, boots=2, criado=AGORA - 25 * 3600))
    head = git(repo, "rev-parse", "HEAD")
    gravador = Gravador()

    guardar(mundo, gravador)

    assert not pending_path(runtime).exists() and gravador.chamadas == [] and git(repo, "rev-parse", "HEAD") == head


@pytest.mark.parametrize("status", ["ready", "rolled_back"])
def test_a_pending_update_already_ready_or_rolled_back_is_left_untouched(mundo, status):
    """``ready`` = a subida deu certo (a guarda para de contar); ``rolled_back`` já foi revertido: nenhum dos dois conta nem reverte de novo."""
    repo, runtime, anterior, _ = mundo
    write_pending(runtime, pendente(anterior, boots=2, status=status))
    antes = pending_path(runtime).read_bytes()
    head = git(repo, "rev-parse", "HEAD")
    gravador = Gravador()

    guardar(mundo, gravador)

    assert pending_path(runtime).read_bytes() == antes and gravador.chamadas == []
    assert git(repo, "rev-parse", "HEAD") == head

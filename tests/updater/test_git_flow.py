"""A12-A13 (item 18, P2) — o fluxo git do auto-update: escolha da tag, plano sem shell e rollback.

Repositórios git reais e locais em ``tmp_path`` (``file://`` com ``allow_protocol="file"``). O ``HOME`` e a configuração do git do
ambiente são isolados; o interpretador das dependências e do smoke é um ``python`` falso (script ``sh``) que registra o que recebeu.
Nomes do contrato: ``plan_git_update``, ``apply_git_update(plan, repo_dir, python=...)``, ``git_env``, ``UpdateError``, ``GitPlan``
(``current``, ``target``, ``tag_object_sha``, ``target_commit``, ``prev_sha``, ``changelog``) e ``update-state.json`` em ``RUNTIME_DIR``.
"""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from empiremuse.rules.release import Version
from empiremuse.updater.git_flow import UpdateError, apply_git_update, git_env, plan_git_update

pytestmark = pytest.mark.critical

AMBIENTE_GIT = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.org",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.org",
    "GIT_TERMINAL_PROMPT": "0",
}


def git(cwd: Path, *args: str) -> str:
    env = {"PATH": os.environ["PATH"], "HOME": str(cwd), **AMBIENTE_GIT}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, arquivos: dict[str, str], mensagem: str) -> str:
    for nome, conteudo in arquivos.items():
        (repo / nome).write_text(conteudo, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", mensagem)
    return git(repo, "rev-parse", "HEAD")


PYPROJECT = '[project]\nname = "empiremuse"\nrequires-python = ">=3.10"\n'
CHANGELOG_21 = "# Changelog\n\n## [2.1.0] - 2026-11-01\n- novidade da 2.1.0\n\n## [2.0.0] - 2026-09-01\n- base\n"


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    """``remoto`` (main com v2.0.0 e v2.1.0 anotadas e v2.5.0 leve) e ``local`` (clone destacado em v2.0.0)."""
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path / "runtime"))
    (tmp_path / "runtime").mkdir()
    remoto = tmp_path / "remoto"
    remoto.mkdir()
    git(remoto, "init", "-q", "-b", "main")
    commit(
        remoto,
        {"pyproject.toml": PYPROJECT, "CHANGELOG.md": "# Changelog\n\n## [2.0.0]\n- base\n", "app.txt": "v2.0.0\n"},
        "v2.0.0",
    )
    git(remoto, "tag", "-a", "v2.0.0", "-m", "2.0.0")
    commit(remoto, {"CHANGELOG.md": CHANGELOG_21, "app.txt": "v2.1.0\n"}, "v2.1.0")
    git(remoto, "tag", "-a", "v2.1.0", "-m", "2.1.0")
    git(remoto, "tag", "v2.5.0")  # leve: tem de ser ignorada
    local = tmp_path / "local"
    git(tmp_path, "clone", "-q", str(remoto), str(local))
    git(local, "checkout", "-q", "--detach", "v2.0.0")
    return remoto, local


def url(remoto: Path) -> str:
    return f"file://{remoto}"


def planejar(remoto: Path, local: Path):
    return asyncio.run(plan_git_update(local, url(remoto), allow_protocol="file"))


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD")


# ============================================================================ git_env


def test_git_env_keeps_only_the_minimal_keys_and_no_secret():
    base = {
        "PATH": "/usr/bin",
        "HOME": "/home/x",
        "LANG": "C.UTF-8",
        "LC_ALL": "C",
        "TOKEN": "segredo",
        "MONGO": "mongodb://u:s@h",
        "GITHUB_TOKEN": "ghp_x",
        "GIT_DIR": "/outro/.git",
        "GIT_WORK_TREE": "/outro",
        "GIT_ASKPASS": "/bin/evil",
    }

    env = git_env(base)

    assert set(env) <= {"PATH", "HOME", "LANG", "GIT_TERMINAL_PROMPT", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL"}
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/x" and env["LANG"] == "C.UTF-8"
    assert (
        env["GIT_TERMINAL_PROMPT"] == "0"
        and env["GIT_CONFIG_NOSYSTEM"] == "1"
        and env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    )


# ============================================================================ A12 — escolha da tag e plano


def test_the_plan_targets_the_newest_annotated_tag_that_is_an_ancestor_of_main(mundo):
    remoto, local = mundo
    antes = head(local)

    plano = planejar(remoto, local)

    assert plano.current == Version(2, 0, 0) and plano.target == Version(2, 1, 0)
    assert plano.prev_sha == antes
    assert plano.tag_object_sha == git(remoto, "rev-parse", "refs/tags/v2.1.0")
    assert plano.target_commit == git(remoto, "rev-parse", "v2.1.0^{commit}")
    assert plano.tag_object_sha != plano.target_commit  # é o objeto da tag anotada, não o commit
    assert "novidade da 2.1.0" in plano.changelog
    assert head(local) == antes  # planejar não mexe no HEAD


def test_a_lightweight_tag_is_never_chosen(mundo):
    remoto, local = mundo

    assert planejar(remoto, local).target == Version(2, 1, 0)  # a v2.5.0 leve foi ignorada


def test_already_on_the_latest_annotated_tag_means_no_plan(mundo):
    remoto, local = mundo
    git(local, "fetch", "-q", url(remoto), "+refs/tags/v2.1.0:refs/tags/v2.1.0")
    git(local, "checkout", "-q", "--detach", "v2.1.0")

    assert planejar(remoto, local) is None


def test_a_tag_that_is_not_on_main_is_refused_and_head_stays(mundo):
    remoto, local = mundo
    git(remoto, "checkout", "-q", "-b", "lateral")
    commit(remoto, {"lateral.txt": "x\n"}, "fora da main")
    git(remoto, "tag", "-a", "v2.3.0", "-m", "2.3.0")
    git(remoto, "checkout", "-q", "main")
    antes = head(local)

    with pytest.raises(UpdateError):
        planejar(remoto, local)

    assert head(local) == antes


def test_a_dirty_tree_is_refused_listing_the_files(mundo):
    remoto, local = mundo
    (local / "app.txt").write_text("alterado à mão\n", encoding="utf-8")
    (local / "novo.txt").write_text("x\n", encoding="utf-8")
    antes = head(local)

    with pytest.raises(UpdateError) as erro:
        planejar(remoto, local)

    assert "app.txt" in str(erro.value) and head(local) == antes


def test_a_seen_tag_that_changed_its_object_sha_aborts(mundo, tmp_path):
    remoto, local = mundo
    (tmp_path / "runtime" / "update-state.json").write_text(json.dumps({"v2.1.0": "0" * 40}), encoding="utf-8")
    antes = head(local)

    with pytest.raises(UpdateError):
        planejar(remoto, local)

    assert head(local) == antes


def test_origin_pointing_elsewhere_is_never_used(mundo):
    remoto, local = mundo
    git(local, "remote", "set-url", "origin", "file:///nao/existe/de/jeito/nenhum")

    assert planejar(remoto, local).target == Version(2, 1, 0)


def test_a_requires_python_above_the_interpreter_is_refused_before_any_checkout(mundo):
    remoto, local = mundo
    git(remoto, "tag", "-d", "v2.1.0")
    commit(
        remoto,
        {"pyproject.toml": '[project]\nname = "empiremuse"\nrequires-python = ">=99.0"\n'},
        "exige python futuro",
    )
    git(remoto, "tag", "-a", "v2.1.0", "-m", "2.1.0")
    antes = head(local)

    with pytest.raises(UpdateError):
        planejar(remoto, local)

    assert head(local) == antes


def test_a_hostile_global_gitconfig_has_no_effect(mundo, tmp_path, monkeypatch):
    remoto, local = mundo
    casa = tmp_path / "casa"
    casa.mkdir()
    marca = tmp_path / "fsmonitor-rodou"
    gancho = tmp_path / "gancho.sh"
    gancho.write_text(f"#!/bin/sh\ntouch {marca}\n", encoding="utf-8")
    gancho.chmod(0o755)
    (casa / ".gitconfig").write_text(
        f'[url "file:///repo/malicioso"]\n\tinsteadOf = {url(remoto)}\n[core]\n\tfsmonitor = {gancho}\n\thooksPath = {casa}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(casa))

    plano = planejar(remoto, local)

    assert plano.target == Version(2, 1, 0)
    assert not marca.exists()


# ============================================================================ A13 — sem shell, ambiente mínimo, -c de segurança

OPCOES_DE_SEGURANCA = [
    "protocol.allow=never",
    "protocol.file.allow=always",
    "core.hooksPath=/dev/null",
    "http.sslVerify=true",
    "credential.helper=",
    "core.fsmonitor=false",
    "transfer.fsckObjects=true",
]
CHAVES_PERMITIDAS = {"PATH", "HOME", "LANG", "GIT_TERMINAL_PROMPT", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL"}


@pytest.fixture
def gravador(monkeypatch):
    """Registra cada subprocesso criado (``argv`` e ``env``) e proíbe o shell."""
    chamadas = []
    real = asyncio.create_subprocess_exec

    async def exec_gravado(*args, **kwargs):
        chamadas.append((args, kwargs.get("env")))
        return await real(*args, **kwargs)

    async def sem_shell(*args, **kwargs):
        raise AssertionError("create_subprocess_shell não pode ser usado no fluxo de atualização")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", exec_gravado)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", sem_shell)
    return chamadas


def test_every_git_runs_without_shell_with_the_security_options_and_the_minimal_env(mundo, gravador, monkeypatch):
    remoto, local = mundo
    for nome in ("TOKEN", "MONGO", "GITHUB_TOKEN", "GIT_DIR", "GIT_WORK_TREE", "GIT_ASKPASS"):
        monkeypatch.setenv(nome, "valor-secreto")

    planejar(remoto, local)

    gits = [(a, e) for a, e in gravador if Path(str(a[0])).name == "git"]
    assert gits and len(gits) == len(gravador)
    for argv, env in gits:
        argv = [str(a) for a in argv]
        for opcao in OPCOES_DE_SEGURANCA:
            assert opcao in argv, (opcao, argv)
        assert f"--git-dir={local}/.git" in argv and f"--work-tree={local}" in argv
        assert set(env) <= CHAVES_PERMITIDAS and "valor-secreto" not in env.values()
    assert any("--end-of-options" in [str(a) for a in argv] for argv, _ in gits)


# ============================================================================ apply: dependências, smoke e rollback

PYTHON_FALSO = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG"
env > "$FAKE_ENV"
if [ "$2 $3" = "pip install" ] && [ -f "$FAKE_PIP_FALHA" ]; then rm -f "$FAKE_PIP_FALHA"; exit 1; fi
case "$1" in
  -c) [ -f "$FAKE_SMOKE_FALHA" ] && exit 1 ;;
esac
exit 0
"""


@pytest.fixture
def python_falso(tmp_path, monkeypatch):
    log, envlog, falha = tmp_path / "python.log", tmp_path / "python.env", tmp_path / "smoke_falha"
    script = tmp_path / "python-falso"
    script.write_text(PYTHON_FALSO, encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_ENV", str(envlog))
    monkeypatch.setenv("FAKE_SMOKE_FALHA", str(falha))
    monkeypatch.setenv("FAKE_PIP_FALHA", str(tmp_path / "pip_falha"))
    monkeypatch.setattr(shutil, "which", lambda *args, **kwargs: None)  # sem uv: o caminho é `python -m pip install`
    return script, log, envlog, falha


def aplicar(plano, local, python):
    return asyncio.run(apply_git_update(plano, local, python=str(python)))


def test_apply_leaves_head_detached_on_the_tag_commit_and_records_the_pending_update(mundo, python_falso, tmp_path):
    remoto, local = mundo
    script, log, envlog, _ = python_falso
    plano = planejar(remoto, local)

    aplicar(plano, local, script)

    assert head(local) == plano.target_commit
    assert subprocess.run(["git", "-C", str(local), "symbolic-ref", "-q", "HEAD"], capture_output=True).returncode != 0
    chamadas = log.read_text().splitlines()
    assert any("-m pip install" in c and "--require-hashes" in c and "requirements-lock.txt" in c for c in chamadas)
    assert any("import empiremuse.utils.client" in c for c in chamadas)
    assert any("-m compileall" in c and "empiremuse" in c for c in chamadas)
    pendente = json.loads((tmp_path / "runtime" / "update-pending.json").read_text())
    assert pendente["flow"] == "git" and pendente["prev_sha"] == plano.prev_sha and pendente["boots"] == 0


def test_the_dependency_install_and_the_smoke_never_see_secrets(mundo, python_falso, monkeypatch):
    remoto, local = mundo
    script, _, envlog, _ = python_falso
    plano = planejar(remoto, local)
    for nome in ("TOKEN", "MONGO", "GITHUB_TOKEN", "GIT_DIR"):
        monkeypatch.setenv(nome, "valor-secreto")

    aplicar(plano, local, script)

    ambiente = envlog.read_text()
    assert "valor-secreto" not in ambiente
    assert not any(linha.startswith(("TOKEN=", "MONGO=", "GIT_DIR=")) for linha in ambiente.splitlines())


def test_a_failing_smoke_rolls_back_to_prev_sha_reinstalls_the_lock_and_leaves_no_pending(
    mundo, python_falso, tmp_path
):
    remoto, local = mundo
    script, log, _, falha = python_falso
    plano = planejar(remoto, local)
    falha.write_text("1", encoding="utf-8")

    with pytest.raises(UpdateError):
        aplicar(plano, local, script)

    assert head(local) == plano.prev_sha
    instalacoes = [c for c in log.read_text().splitlines() if "-m pip install" in c]
    assert len(instalacoes) == 2  # a do alvo e a do lock anterior
    assert not (tmp_path / "runtime" / "update-pending.json").exists()


def test_a_failing_dependency_install_also_rolls_back(mundo, python_falso, tmp_path):
    """A 1ª instalação (a do alvo) falha; a reinstalação do lock anterior passa."""
    remoto, local = mundo
    script, log, _, _ = python_falso
    plano = planejar(remoto, local)
    (tmp_path / "pip_falha").write_text("1", encoding="utf-8")

    with pytest.raises(UpdateError):
        aplicar(plano, local, script)

    assert head(local) == plano.prev_sha
    assert len([c for c in log.read_text().splitlines() if "-m pip install" in c]) == 2
    assert not (tmp_path / "runtime" / "update-pending.json").exists()

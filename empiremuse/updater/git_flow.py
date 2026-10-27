"""Atualização por git (hosts fora de container): escolhe a tag anotada oficial, confere, troca o código e reverte se falhar.

Só stdlib no import (o ``boot_guard`` usa este módulo antes de o bot e as dependências carregarem). Nada passa por shell:
todo processo sai de ``run_exec`` com lista de argumentos, ambiente mínimo (sem ``TOKEN``, ``MONGO`` nem ``GIT_*`` herdados)
e saída truncada e mascarada. Todo git roda com ``--git-dir``/``--work-tree`` explícitos e opções de segurança (só o
protocolo permitido, sem hooks, sem fsmonitor, sem credential helper, ``fsckObjects``); a URL é sempre a oficial
(``branding.SOURCE_REPO_GIT``), nunca ``SOURCE_REPO`` nem o ``origin`` do clone. O plano só lê (``ls-remote``, ``fetch`` de
tag, ``rev-parse``…) e não mexe no HEAD; quem troca o código é ``apply_git_update``.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import re
import shutil
import sys
import time
import tomllib
import urllib.request
import http.client
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from empiremuse import paths
from empiremuse.rules.owner_shell import collect_secret_values, mask_secrets
from empiremuse.rules.release import (
    Version,
    changelog_sections,
    parse_ls_remote_annotated,
    parse_tag,
    pick_target,
)
from empiremuse.updater.state import PendingUpdate, UpdateRequest, read_seen_tags, write_pending, write_seen_tags
from empiremuse.utils import branding

logger = logging.getLogger(__name__)

EXIT_RESTART = 75
MAIN_REF = "refs/remotes/official/main"
LOCK_FILE = "requirements-lock.txt"
CHANGELOG_FILE = "CHANGELOG.md"
CHANGELOG_MAX_CHARS = 3500
MAX_CHANGELOG_BYTES = 1024 * 1024
RAW_BASE = "https://raw.githubusercontent.com/"
GIT_TIMEOUT = 60
GIT_NETWORK_TIMEOUT = 300
INSTALL_TIMEOUT = 600
SMOKE_TIMEOUT = 120
MAX_OUTPUT_CHARS = 4000
MAX_LISTED_FILES = 10

_SHA1 = re.compile(r"[0-9a-f]{40}")
_UNFINISHED_OPERATIONS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")
_WINDOWS_ENV_KEYS = ("SystemRoot", "COMSPEC", "TEMP", "TMP", "USERPROFILE")


class UpdateError(Exception):
    """Falha esperada do update; a mensagem (pt-BR) é segura para ir ao Discord."""


@dataclasses.dataclass(frozen=True)
class ExecResult:
    returncode: int
    output: str


Runner = Callable[..., Awaitable[ExecResult]]


@dataclasses.dataclass(frozen=True)
class GitPlan:
    """O que o update vai fazer, já conferido: de ``current`` para ``target`` (commit ``target_commit`` da tag anotada)."""

    current: Version
    target: Version
    tag_object_sha: str
    target_commit: str
    prev_sha: str
    changelog: str


def _base_env(base: Mapping[str, str], extra: Mapping[str, str]) -> dict[str, str]:
    keys = ("PATH", "HOME", "LANG") + (_WINDOWS_ENV_KEYS if os.name == "nt" else ())
    env = {key: base[key] for key in keys if key in base}
    env.update(extra)
    return env


def git_env(base: Mapping[str, str]) -> dict[str, str]:
    """Ambiente do git: só ``PATH``, ``HOME`` e ``LANG`` do ``base`` mais as travas; nada de ``GIT_DIR`` nem de token."""
    return _base_env(base, {"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})


def minimal_env(base: Mapping[str, str]) -> dict[str, str]:
    """Ambiente do ``pip``/``uv`` e do smoke: o mesmo mínimo, sem as variáveis ``GIT_*``; o sdist não vê ``TOKEN`` nem ``MONGO``."""
    return _base_env(base, {})


def git_command(repo_dir: Path | None, allow_protocol: str, *args: str) -> list[str]:
    """``git`` apontado para ``repo_dir`` (ou sem repositório, para ``ls-remote``) com as opções de segurança; ``args`` começa pelo subcomando."""
    options = (
        "protocol.allow=never",
        f"protocol.{allow_protocol}.allow=always",
        "core.hooksPath=/dev/null",
        "http.sslVerify=true",
        "credential.helper=",
        "core.fsmonitor=false",
        "transfer.fsckObjects=true",
    )
    command = ["git"]
    if repo_dir is not None:
        command += [f"--git-dir={repo_dir}/.git", f"--work-tree={repo_dir}"]
    for option in options:
        command += ["-c", option]
    return command + list(args)


async def run_exec(
    *args: str,
    cwd: str | os.PathLike[str] | None,
    env: Mapping[str, str],
    timeout: float,
    max_output: int = MAX_OUTPUT_CHARS,
) -> ExecResult:
    """Roda ``args`` sem shell. Saída (stdout e stderr juntos) mascarada e truncada nos últimos ``max_output`` caracteres.

    Falha ao iniciar vira o código 127 e tempo esgotado, 124.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            env=dict(env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as error:
        return ExecResult(127, f"não foi possível executar {os.path.basename(str(args[0]))}: {error.strerror}")
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return ExecResult(124, "tempo esgotado")
    text = mask_secrets(stdout.decode("utf-8", errors="replace"), collect_secret_values(os.environ))
    return ExecResult(process.returncode or 0, text[-max_output:])


class _Git:
    """``git`` sobre um clone: monta o comando seguro, usa o ambiente mínimo e traduz falha em ``UpdateError``."""

    def __init__(self, repo_dir: Path, allow_protocol: str, runner: Runner) -> None:
        self._repo_dir = repo_dir
        self._allow_protocol = allow_protocol
        self._runner = runner

    async def __call__(
        self, *args: str, error: str | None = None, timeout: float = GIT_TIMEOUT, max_output: int | None = None
    ) -> ExecResult:
        """Roda o git; com ``error`` uma saída diferente de 0 levanta ``UpdateError(error)`` (o detalhe vai só para o log).

        ``max_output`` (para arquivos lidos com ``git show``) só é repassado ao runner quando pedido: o padrão guarda o fim
        da saída e cortaria o começo de um arquivo grande.
        """
        command = git_command(self._repo_dir, self._allow_protocol, *args)
        extra = {} if max_output is None else {"max_output": max_output}
        result = await self._runner(*command, cwd=self._repo_dir, env=git_env(os.environ), timeout=timeout, **extra)
        if error is not None and result.returncode != 0:
            logger.warning("update: git %s falhou (código %s): %s", args[0], result.returncode, result.output)
            raise UpdateError(error)
        return result

    async def single_line(self, *args: str, error: str) -> str:
        result = await self(*args, error=error)
        lines = result.output.strip().splitlines()
        return lines[-1].strip() if lines else ""

    async def sha(self, revision: str, *, error: str) -> str:
        value = await self.single_line("rev-parse", "--verify", "--end-of-options", revision, error=error)
        if not _SHA1.fullmatch(value):
            raise UpdateError(error)
        return value


def _printable(text: str) -> str:
    return "".join(char if char.isprintable() and char != "`" else "?" for char in text)


async def _current_version(git: _Git) -> Version:
    for args in (
        ("describe", "--tags", "--exact-match", "--match", "v[0-9]*"),
        ("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"),
    ):
        result = await git(*args)
        if result.returncode == 0 and (version := parse_tag(result.output.strip())) is not None:
            return version
    raise UpdateError("Não consegui descobrir a versão atual: este clone não está em nenhuma tag `vX.Y.Z`.")


async def latest_official_version(
    repo_url: str = branding.SOURCE_REPO_GIT, *, allow_protocol: str = "https", runner: Runner = run_exec
) -> Version | None:
    """Maior tag anotada oficial (``ls-remote`` não precisa de clone), ou ``None`` se a consulta falhar."""
    command = git_command(None, allow_protocol, "ls-remote", "--tags", "--end-of-options", repo_url)
    result = await runner(
        *command, cwd=None, env=git_env(os.environ), timeout=GIT_NETWORK_TIMEOUT, max_output=MAX_CHANGELOG_BYTES
    )
    if result.returncode != 0:
        return None
    return max(parse_ls_remote_annotated(result.output), default=None)


def fetch_remote_changelog(tag: str, *, timeout: float = 10) -> str:
    """``CHANGELOG.md`` da tag oficial (bloqueante: rode em executor). Vazio se a tag for inválida ou a consulta falhar."""
    raw_base = branding.REPO_URL.replace("https://github.com/", RAW_BASE, 1)
    if parse_tag(tag) is None or not raw_base.startswith(RAW_BASE):
        return ""
    url = f"{raw_base}/{tag}/{CHANGELOG_FILE}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - URL https fixa, host conferido abaixo
            if not response.geturl().startswith(RAW_BASE):
                return ""
            return response.read(MAX_CHANGELOG_BYTES).decode("utf-8", errors="replace")
    except OSError, ValueError, http.client.HTTPException:
        return ""


async def installed_version(repo_dir: Path, *, runner: Runner = run_exec) -> Version | None:
    """Versão do clone em ``repo_dir`` (tag no HEAD ou a mais próxima), ou ``None`` se não der para descobrir."""
    try:
        return await _current_version(_Git(Path(repo_dir), "https", runner))
    except UpdateError:
        return None


def _python_supported(pyproject: str) -> bool:
    """``requires-python`` do ``pyproject.toml`` da tag atendido pelo interpretador atual (sem a chave: sem restrição)."""
    from packaging.specifiers import InvalidSpecifier, SpecifierSet

    try:
        requires = tomllib.loads(pyproject).get("project", {}).get("requires-python")
        if requires is None:
            return True
        current = ".".join(str(part) for part in sys.version_info[:3])
        return SpecifierSet(requires).contains(current, prereleases=True)
    except tomllib.TOMLDecodeError, InvalidSpecifier, TypeError, AttributeError:
        raise UpdateError("Não consegui ler o `requires-python` da versão nova; a atualização foi recusada.") from None


async def _require_clean_tree(git: _Git, repo_dir: Path) -> None:
    for name in _UNFINISHED_OPERATIONS:
        if (repo_dir / ".git" / name).exists():
            raise UpdateError(
                "Há um merge, rebase ou cherry-pick em andamento neste clone; conclua-o antes de atualizar."
            )
    # Só arquivos rastreados: o que o bot cria no projeto (dados, .env) não bloqueia o checkout; um conflito real o faria falhar e reverter.
    result = await git("status", "--porcelain", "--untracked-files=no", error="Não consegui ler o estado do clone.")
    changed = [line[3:] for line in result.output.splitlines() if len(line) > 3]
    if changed:
        listed = ", ".join(f"`{_printable(name)}`" for name in changed[:MAX_LISTED_FILES])
        more = f" e mais {len(changed) - MAX_LISTED_FILES}" if len(changed) > MAX_LISTED_FILES else ""
        raise UpdateError(
            f"Há alterações locais em arquivos rastreados: {listed}{more}. Descarte-as ou faça commit antes de atualizar."
        )


async def plan_git_update(
    repo_dir: Path,
    repo_url: str = branding.SOURCE_REPO_GIT,
    *,
    allow_protocol: str = "https",
    runner: Runner = run_exec,
) -> GitPlan | None:
    """Plano para a maior tag anotada oficial acima da atual, ou ``None`` se já está na última. Não mexe no HEAD."""
    repo_dir = Path(repo_dir)
    git = _Git(repo_dir, allow_protocol, runner)
    current = await _current_version(git)

    listing = await git(
        "ls-remote",
        "--tags",
        "--end-of-options",
        repo_url,
        error="Não consegui consultar as versões no repositório oficial.",
        timeout=GIT_NETWORK_TIMEOUT,
        max_output=MAX_CHANGELOG_BYTES,
    )
    annotated = parse_ls_remote_annotated(listing.output)
    target = pick_target(current, annotated)
    if target is None:
        return None
    tag, tag_object_sha = f"v{target}", annotated[target]

    await git(
        "fetch",
        "--no-tags",
        "--end-of-options",
        repo_url,
        f"+refs/heads/main:{MAIN_REF}",
        f"+refs/tags/{tag}:refs/tags/{tag}",
        error=f"Não consegui baixar a versão {target} do repositório oficial.",
        timeout=GIT_NETWORK_TIMEOUT,
    )
    refused = f"A tag {tag} não passou na conferência e a atualização foi recusada."
    if await git.sha(f"refs/tags/{tag}", error=refused) != tag_object_sha:
        raise UpdateError(refused)
    if await git.single_line("cat-file", "-t", "--end-of-options", f"refs/tags/{tag}", error=refused) != "tag":
        raise UpdateError(refused)
    # O campo "tag" do objeto (não o texto da mensagem, que pode ser grande e conter qualquer linha).
    named = await git.single_line(
        "for-each-ref", "--format=%(tag)", "--end-of-options", f"refs/tags/{tag}", error=refused
    )
    if named != tag:
        raise UpdateError(refused)
    target_commit = await git.sha(f"refs/tags/{tag}^{{commit}}", error=refused)
    ancestor = await git("merge-base", "--is-ancestor", "--end-of-options", target_commit, MAIN_REF)
    if ancestor.returncode != 0:
        raise UpdateError(f"A tag {tag} não está na `main` oficial; a atualização foi recusada.")

    runtime_dir = paths.get_runtime_dir()
    seen = read_seen_tags(runtime_dir)
    if seen.get(tag, tag_object_sha) != tag_object_sha:
        raise UpdateError(f"A tag {tag} mudou desde que foi vista pela primeira vez; a atualização foi recusada.")
    if tag not in seen:
        write_seen_tags(runtime_dir, {**seen, tag: tag_object_sha})

    pyproject = await git(
        "show", "--end-of-options", f"{target_commit}:pyproject.toml", error=refused, max_output=MAX_CHANGELOG_BYTES
    )
    if not _python_supported(pyproject.output):
        raise UpdateError(
            f"A versão {target} exige uma versão do Python maior que a deste servidor; a atualização foi recusada."
        )
    await _require_clean_tree(git, repo_dir)

    log = await git("show", "--end-of-options", f"{target_commit}:{CHANGELOG_FILE}", max_output=MAX_CHANGELOG_BYTES)
    changelog = changelog_sections(log.output, current, target, CHANGELOG_MAX_CHARS) if log.returncode == 0 else ""
    prev_sha = await git.sha("HEAD", error="Não consegui ler o commit atual do clone.")
    return GitPlan(current, target, tag_object_sha, target_commit, prev_sha, changelog)


async def _install_dependencies(runner: Runner, repo_dir: Path, python: str) -> None:
    uv = shutil.which("uv")
    if uv:
        command = [uv, "pip", "install", "--require-hashes", "-r", LOCK_FILE, "--python", python]
    else:
        command = [python, "-m", "pip", "install", "--require-hashes", "-r", LOCK_FILE]
    result = await runner(*command, cwd=repo_dir, env=minimal_env(os.environ), timeout=INSTALL_TIMEOUT)
    if result.returncode != 0:
        logger.warning("update: instalação das dependências falhou (código %s): %s", result.returncode, result.output)
        raise UpdateError("a instalação das dependências falhou")


async def _smoke_test(runner: Runner, repo_dir: Path, python: str) -> None:
    for args in (("-c", "import empiremuse.utils.client"), ("-m", "compileall", "-q", "empiremuse")):
        result = await runner(python, *args, cwd=repo_dir, env=minimal_env(os.environ), timeout=SMOKE_TIMEOUT)
        if result.returncode != 0:
            logger.warning("update: teste de fumaça falhou (código %s): %s", result.returncode, result.output)
            raise UpdateError("o teste de fumaça do código novo falhou")


async def restore_checkout(
    repo_dir: Path, sha: str, *, python: str = sys.executable, runner: Runner = run_exec, allow_protocol: str = "https"
) -> None:
    """``checkout --detach`` de ``sha`` (o commit anterior) e reinstalação do lock dele; levanta ``UpdateError`` se falhar."""
    if not _SHA1.fullmatch(sha):
        raise UpdateError("O commit anterior é inválido.")
    git = _Git(Path(repo_dir), allow_protocol, runner)
    await git("checkout", "--detach", "--end-of-options", sha, error="Não consegui voltar ao commit anterior.")
    await _install_dependencies(runner, Path(repo_dir), python)


async def apply_git_update(
    plan: GitPlan,
    request: UpdateRequest,
    repo_dir: Path,
    runtime_dir: Path,
    *,
    python: str = sys.executable,
    runner: Runner = run_exec,
    now: Callable[[], float] = time.time,
    allow_protocol: str = "https",
) -> PendingUpdate:
    """Troca o código pelo commit da tag, instala o lock e testa; qualquer falha reverte e levanta ``UpdateError``.

    No sucesso grava o pendente (``boots=0``) e o devolve; quem chamou encerra o pool com ``EXIT_RESTART``.
    """
    repo_dir = Path(repo_dir)
    if not (_SHA1.fullmatch(plan.target_commit) and _SHA1.fullmatch(plan.prev_sha)):
        raise UpdateError("O plano de atualização é inválido.")
    git = _Git(repo_dir, allow_protocol, runner)
    try:
        await git(
            "checkout",
            "--detach",
            "--end-of-options",
            plan.target_commit,
            error="Não consegui trocar para o código novo.",
        )
        await _install_dependencies(runner, repo_dir, python)
        await _smoke_test(runner, repo_dir, python)
    except UpdateError as failure:
        try:
            await restore_checkout(repo_dir, plan.prev_sha, python=python, runner=runner, allow_protocol=allow_protocol)
        except UpdateError:
            logger.error("update: a reversão para %s falhou", plan.prev_sha)
            raise UpdateError(
                f"A atualização falhou ({failure}) e a reversão automática também. Confira o servidor à mão: o clone pode estar na versão {plan.target}."
            ) from failure
        raise UpdateError(
            f"A atualização falhou ({failure}); o código foi revertido para a versão {plan.current}."
        ) from failure
    pending = PendingUpdate(
        flow="git",
        from_version=plan.current,
        to_version=plan.target,
        bot_id=request.bot_id,
        channel_id=request.channel_id,
        requested_by=request.requested_by,
        created_at=now(),
        prev_sha=plan.prev_sha,
    )
    write_pending(runtime_dir, pending)
    return pending

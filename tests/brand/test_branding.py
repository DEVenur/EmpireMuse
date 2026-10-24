"""Teste-guarda de marca da Fase 1 (Identidade EmpireMuse).

Os testes são escritos a partir do CONTRATO (BRIEFING-FASE1.md), não do código
atual. Obra derivada de MuseHeart-MusicBot (zRitsu), GPL-2.0: os créditos ao
upstream são preservados (ver CREDITS.md e utils/branding.py).
"""

import functools
import os
import re
import subprocess
from pathlib import Path

import pytest
from tests.support.raiz import RAIZ

ROOT = RAIZ
ASSETS_DIR = ROOT / "assets"


# --------------------------------------------------------------------------- helpers


def _git_lines(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.split("\0") if line]


def _gitignore_rules(text: str) -> list[tuple[re.Pattern, bool, bool]]:
    """Regras de um ``.gitignore`` como ``(regex, negada, só_diretório)``; cobre ``*``, ``**``, ``?``, ``[...]``, ``!``,
    ``/`` inicial (âncora na raiz), ``/`` no meio (também ancorada) e ``/`` final (só diretório)."""
    rules = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        line = line.rstrip(" ") if not line.endswith("\\ ") else line
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        only_dir = line.endswith("/")
        line = line.rstrip("/")
        anchored = "/" in line
        line = line.lstrip("/")
        regex, i = "", 0
        while i < len(line):
            char = line[i]
            if line.startswith("**/", i):
                regex += "(?:.*/)?"
                i += 3
                continue
            if line.startswith("/**", i) and i + 3 == len(line):
                regex += "/.*"
                i += 3
                continue
            if char == "*":
                regex += "[^/]*"
            elif char == "?":
                regex += "[^/]"
            elif char == "[":
                end = line.find("]", i + 2)
                if end == -1:
                    regex += re.escape(char)
                else:
                    regex += (
                        "["
                        + line[i + 1 : end].replace("\\", "\\\\").replace("!", "^", 1 if line[i + 1] == "!" else 0)
                        + "]"
                    )
                    i = end
            elif char == "\\" and i + 1 < len(line):
                i += 1
                regex += re.escape(line[i])
            else:
                regex += re.escape(char)
            i += 1
        prefix = "" if anchored else "(?:.*/)?"
        rules.append((re.compile(f"^{prefix}{regex}$"), negated, only_dir))
    return rules


def _is_ignored(rel: str, is_dir: bool, rules) -> bool:
    """Como o git: um diretório ignorado esconde tudo dentro dele; senão vale a ÚLTIMA regra que casa."""
    parts = rel.split("/")
    for depth in range(1, len(parts)):
        if _decide("/".join(parts[:depth]), True, rules):
            return True
    return _decide(rel, is_dir, rules)


def _decide(rel: str, is_dir: bool, rules) -> bool:
    ignored = False
    for regex, negated, only_dir in rules:
        if only_dir and not is_dir:
            continue
        if regex.match(rel):
            ignored = not negated
    return ignored


def _walk_files(root: Path) -> list[str]:
    """Sem ``.git`` (tarball, ``pip download``, contêiner): todos os arquivos que o ``.gitignore`` raiz não ignora."""
    gitignore = root / ".gitignore"
    rules = _gitignore_rules(gitignore.read_text(encoding="utf-8", errors="replace")) if gitignore.is_file() else []
    found = []
    for folder, dirs, files in os.walk(root):
        rel_folder = Path(folder).relative_to(root).as_posix()
        rel_folder = "" if rel_folder == "." else rel_folder
        dirs[:] = sorted(
            d for d in dirs if d != ".git" and not _is_ignored(f"{rel_folder}/{d}".lstrip("/"), True, rules)
        )
        for name in files:
            rel = f"{rel_folder}/{name}".lstrip("/")
            if name != ".git" and not _is_ignored(rel, False, rules):
                found.append(rel)
    return found


@functools.lru_cache(maxsize=1)
def _repo_files_cached() -> tuple[str, ...]:
    return tuple(_list_repo_files())


def _list_repo_files() -> list[str]:
    """Arquivos rastreados + novos não rastreados (respeitando .gitignore) que existem em disco.

    Num clone usa o próprio git; sem ``.git`` (ou sem o executável) varre o diretório aplicando o ``.gitignore``.
    """
    if (ROOT / ".git").exists():
        try:
            tracked = _git_lines("ls-files", "-z")
            untracked = _git_lines("ls-files", "-z", "--others", "--exclude-standard")
        except (OSError, subprocess.CalledProcessError):
            tracked, untracked = [], _walk_files(ROOT)
    else:
        tracked, untracked = [], _walk_files(ROOT)
    return sorted(p for p in {*tracked, *untracked} if (ROOT / p).is_file())


@functools.lru_cache(maxsize=None)
def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


_TOKEN_CHARS = r"A-Za-z0-9_"
_HOST_CHARS = r"A-Za-z0-9-"


@functools.lru_cache(maxsize=None)
def _needle_regex(needle: str) -> re.Pattern:
    """Regex de um termo proibido, sem falso positivo por vizinhança e sem falso negativo por caixa.

    * nome ou número (``zRitsu``, ``911370624507707483``): palavra inteira, sem diferenciar maiúsculas;
    * host (``imgur.com``, ``i.ibb.co``): começa num limite de host (``i.imgur.com`` e ``www.imgur.com`` casam,
      ``notimgur.com`` não) e não continua em outro rótulo (``ibb.com`` e ``ibb.co.uk`` não casam ``ibb.co``);
    * host com caminho (``cdn.discordapp.com/attachments/``): mesmo começo, e o caminho casa literalmente.
    """
    body = re.escape(needle)
    if "." not in needle and "/" not in needle:
        return re.compile(rf"(?<![{_TOKEN_CHARS}]){body}(?![{_TOKEN_CHARS}])", re.IGNORECASE)
    start = rf"(?<![{_HOST_CHARS}])"
    end = "" if needle.endswith("/") else rf"(?![{_HOST_CHARS}]|\.[A-Za-z])"
    return re.compile(f"{start}{body}{end}", re.IGNORECASE)


# --------------------------------------------------------------------------- fixtures


class _LazyBranding:
    """Importa utils.branding só no primeiro acesso, dentro do teste (falha individual, não erro de fixture)."""

    def __getattr__(self, name):
        try:
            from empiremuse.utils import branding as module
        except ImportError as exc:
            pytest.fail(f"utils/branding.py ainda não existe ou não importa (RED esperado): {exc}", pytrace=False)
        return getattr(module, name)


class _LazyDefaultConfig:
    def __getitem__(self, key):
        try:
            import empiremuse.config_loader as config_loader
        except ImportError as exc:
            pytest.fail(f"config_loader não importa isolado: {exc}", pytrace=False)
        return config_loader.DEFAULT_CONFIG[key]


@pytest.fixture
def branding():
    return _LazyBranding()


@pytest.fixture
def default_config(monkeypatch, tmp_path):
    """DEFAULT_CONFIG isolado: cwd temporário (sem .env/config.json reais)."""
    monkeypatch.chdir(tmp_path)
    return _LazyDefaultConfig()


# --------------------------------------------------------------------------- R2 Lavalink


# --------------------------------------------------------------------------- R3 Recursos do upstream


# --------------------------------------------------------------------------- R4 Assets


def _asset_files() -> list[Path]:
    if not ASSETS_DIR.is_dir():
        pytest.fail("assets/ não existe", pytrace=False)
    return sorted(p for p in ASSETS_DIR.iterdir() if p.is_file() and p.name != "SHA256SUMS")


@pytest.mark.smoke
def test_asset_url_builds_url_from_base_and_name(branding):
    name = _asset_files()[0].name
    assert branding.asset_url(name) == branding.ASSETS_BASE_URL + "/" + name


@pytest.mark.parametrize("bad_name", ["", "nao_existe_xyz.png"])
def test_asset_url_rejects_invalid_names(branding, bad_name):
    with pytest.raises(ValueError):
        branding.asset_url(bad_name)


# --------------------------------------------------------------------------- R6 Nome antigo


# --------------------------------------------------------------------------- Robustez da varredura (KI-34)


@pytest.fixture
def raiz_falsa(monkeypatch, tmp_path):
    """Troca ``ROOT`` por uma pasta temporária (sem ``.git``) e limpa os caches de listagem e leitura."""
    import sys

    modulo = sys.modules[__name__]
    monkeypatch.setattr(modulo, "ROOT", tmp_path)
    _repo_files_cached.cache_clear()
    _read.cache_clear()
    yield tmp_path
    _repo_files_cached.cache_clear()
    _read.cache_clear()

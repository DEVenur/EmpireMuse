"""Teste-guarda de marca da Fase 1 (Identidade EmpireMuse).

Os testes são escritos a partir do CONTRATO (BRIEFING-FASE1.md), não do código
atual. Obra derivada de MuseHeart-MusicBot (zRitsu), GPL-2.0: os créditos ao
upstream são preservados (ver CREDITS.md e utils/branding.py).
"""

import configparser
import fnmatch
import functools
import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "assets"

# sha256 do LICENSE antes de qualquer mudança da Fase 1 (calculado pelo QA).
LICENSE_SHA256 = "6e786173e40f582911924258618a20534c0fb162bcfef71c68e1b0b98de075e6"

# Valores definitivos do contrato (literais de propósito: não derivam de branding.py).
EXPECTED_CONSTANTS = {
    "BOT_NAME": "EmpireMuse",
    "REPO_URL": "https://github.com/DiscordEmpireHub/EmpireMuse",
    "SOURCE_REPO_GIT": "https://github.com/DiscordEmpireHub/EmpireMuse.git",
    "RAW_BASE_URL": "https://raw.githubusercontent.com/DiscordEmpireHub/EmpireMuse/main",
    "ASSETS_BASE_URL": "https://raw.githubusercontent.com/DiscordEmpireHub/EmpireMuse/main/assets",
    "LICENSE_URL": "https://github.com/DiscordEmpireHub/EmpireMuse/blob/main/LICENSE",
    "GUIDES_URL": "https://github.com/DiscordEmpireHub/EmpireMuse/blob/main/docs/guides",
    "RPC_APP_URL": "https://github.com/DiscordEmpireHub/EmpireMuse-RPC-app",
    "RPC_APP_RELEASES_URL": "https://github.com/DiscordEmpireHub/EmpireMuse-RPC-app/releases",
    "LAVALINK_BINARIES_URL": "https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download/0.0.3",
    "LAVALINK_JAR_URL": "https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download/0.0.3/Lavalink.jar",
    "LAVALINK_APPLICATION_YML_URL": "https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download/0.0.3/application.yml",
    "LAVALINK_JAR_SHA256": "8cb801e591072c3689fafd71ccf571a95a4ead3cc35dfc045e157d763d89119a",
    "LAVALINK_APPLICATION_YML_SHA256": "a342d5575fac9c394faaaecaae17df1c8fc759dc8a8937ff839aeabb07cb6b95",
    "LAVALINK_PLUGIN_SHA256": {
        "youtube-plugin-2be8e542d3f6f178e048dca565892684c2e40177.jar": "b062effdda6abeaa46913dfd1b5d5600120b65f239ce88f30948c7213a3ca1c0",
        "lavasrc-plugin-4.8.3.jar": "4ec389bdae64fd381ee62fcdb902e15d9402823b1ad0b982bd5633619a07c1b3",
        "lavalink-2.6.1.jar": "1fc300ec80d4b1705eff0a3b2b4dae21177467c95a7f1e393ecf018c10f2aaf3",
    },
    "LAVALINK_SERVER_LIST_URL": "https://raw.githubusercontent.com/DiscordEmpireHub/EmpireMuse/main/data/lavalink_servers.ini",
    "UPSTREAM_NAME": "MuseHeart-MusicBot",
    "UPSTREAM_AUTHOR": "zRitsu",
    "UPSTREAM_URL": "https://github.com/zRitsu/MuseHeart-MusicBot",
}

# Extensões/nomes considerados "arquivos de runtime" (R3).
RUNTIME_PATTERNS = (
    "*.py",
    "*.sh",
    "*.yml",
    "*.yaml",
    ".example.env",
    "*.config.example",
    "Dockerfile",
    "*.html",
    "*.json",
    "*.toml",
    "requirements*.txt",
)

# I-7 Deploy: arquivos de deploy com a identidade do EmpireMuse.
DEPLOY_PATTERNS = (
    "Dockerfile",
    "docker-compose*",
    "discloud.config*",
)

UPSTREAM_RESOURCE_PATTERNS = (
    "zRitsu",
    "cdn.discordapp.com/attachments/",
    "media.discordapp.net/attachments/",
    "cdn.discordapp.com/emojis/",
    "i.ibb.co/",
    "i.imgur.com/",
    "iili.io/",
    "iconfinder.com/",
    "911370624507707483",
)
# Exceção explícita: fork do jishaku de zRitsu (TODO saneamento/DevOps).
JISHAKU_EXCEPTION_FILE = "requirements.txt"

# "MuseHeart", "muse heart", "Muse_Heart", "muse-heart"; não casa "amuse heart" (palavra diferente).
OLD_NAME_RE = re.compile(r"(?<![A-Za-z])muse[ _-]?heart", re.IGNORECASE)
ASSET_URL_LITERAL_RE = re.compile(r"""asset_url\(\s*(["'])(?P<name>[^"']+)\1\s*\)""")


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


def _repo_files() -> list[str]:
    return list(_repo_files_cached())


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


def _matches(path: str, patterns) -> bool:
    name = Path(path).name
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def _is_deploy(path: str) -> bool:
    return _matches(path, DEPLOY_PATTERNS)


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


def _contains(text: str, needle: str) -> bool:
    return _needle_regex(needle).search(text) is not None


def _scan(paths, needles, *, ignore_line=None) -> list[str]:
    """Retorna violações no formato 'arquivo:linha: needle'."""
    regexes = [(needle, _needle_regex(needle)) for needle in needles]
    violations = []
    for path in paths:
        for lineno, line in enumerate(_read(path).splitlines(), start=1):
            if ignore_line and ignore_line(path, line):
                continue
            for needle, regex in regexes:
                if regex.search(line):
                    violations.append(f"{path}:{lineno}: {needle!r}")
    return violations


UPSTREAM_LL_REPO_RE = re.compile(r"zRitsu/LL-binaries(?![A-Za-z0-9_-])", re.IGNORECASE)


def _scan_regex(paths, regex: re.Pattern) -> list[str]:
    violations = []
    for path in paths:
        for lineno, line in enumerate(_read(path).splitlines(), start=1):
            if regex.search(line):
                violations.append(f"{path}:{lineno}: {regex.pattern!r}")
    return violations


def _fail_with(title: str, violations: list[str]) -> None:
    if violations:
        pytest.fail(f"{title} ({len(violations)}):\n  " + "\n  ".join(violations), pytrace=False)


def _runtime_files(*, deploy: bool) -> list[str]:
    selected = []
    for path in _repo_files():
        if path.startswith("tests/") or path in ("utils/branding.py", "empiremuse/utils/branding.py"):
            continue
        if _is_deploy(path) != deploy:
            continue
        if _matches(path, RUNTIME_PATTERNS) or (deploy and _is_deploy(path)):
            selected.append(path)
    return selected


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


# --------------------------------------------------------------------------- R1 Atualização


def test_default_source_repo_points_to_empiremuse_git(default_config, branding):
    assert default_config["SOURCE_REPO"] == branding.SOURCE_REPO_GIT, (
        "DEFAULT_CONFIG['SOURCE_REPO'] deve ser SOURCE_REPO_GIT"
    )


def test_example_env_source_repo_matches_contract(branding):
    lines = [l for l in _read(".example.env").splitlines() if l.startswith("SOURCE_REPO=")]
    assert len(lines) == 1, f".example.env deve ter exatamente uma linha SOURCE_REPO= (achou {len(lines)})"
    value = lines[0].split("=", 1)[1].strip().strip("'\"")
    assert value == branding.SOURCE_REPO_GIT, f".example.env SOURCE_REPO={value!r} != {branding.SOURCE_REPO_GIT!r}"


def test_deploy_files_use_no_upstream_image_host():
    hosts = (
        "i.ibb.co",
        "ibb.co",
        "i.imgur.com",
        "imgur.com",
        "iili.io",
        "cdn.discordapp.com/attachments/",
        "media.discordapp.net/attachments/",
    )
    files = [p for p in _repo_files() if _is_deploy(p)]
    if files:
        _fail_with("Host de imagem do upstream em arquivos de deploy", _scan(files, hosts))


# --------------------------------------------------------------------------- R2 Lavalink


def test_default_lavalink_file_url_is_mirrored_jar(default_config, branding):
    assert default_config["LAVALINK_FILE_URL"] == branding.LAVALINK_JAR_URL


def test_default_lavalink_server_list_is_repo_ini(default_config, branding):
    assert default_config["LAVALINK_SERVER_LIST"] == branding.LAVALINK_SERVER_LIST_URL


def test_lavalink_servers_ini_exists_and_is_valid_ini():
    path = ROOT / "data" / "lavalink_servers.ini"
    assert path.is_file(), "data/lavalink_servers.ini não existe"
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(path.read_text(encoding="utf-8"))
    except configparser.Error as exc:
        pytest.fail(f"data/lavalink_servers.ini não é INI válido: {exc}", pytrace=False)
    assert len(parser.sections()) >= 1, "data/lavalink_servers.ini precisa de ao menos 1 seção"


def test_local_lavalink_does_not_use_upstream_binaries():
    path = (
        "empiremuse/utils/music/local_lavalink.py"
        if (ROOT / "empiremuse/utils/music/local_lavalink.py").is_file()
        else "utils/music/local_lavalink.py"
    )
    violations = _scan_regex([path], UPSTREAM_LL_REPO_RE)
    _fail_with("local_lavalink.py ainda aponta para zRitsu/LL-binaries", violations)


RENAMED_LL_REPO = (
    "DiscordEmpireHub/LL-binaries"  # renomeado para DiscordEmpireHub/EmpireMuse-LL-binaries (301 no GitHub)
)
# O nome antigo termina o nome do repositório (``LL-binaries``, ``LL-binaries.git``, ``LL-binaries/``), nunca outro nome.
OLD_LL_REPO_RE = re.compile(r"(?:DiscordEmpireHub|zRitsu)/LL-binaries(?![A-Za-z0-9_-])", re.IGNORECASE)


def test_code_and_docs_use_the_renamed_binaries_repo_and_no_upstream_binaries():
    """O CHANGELOG é histórico e pode citar o nome antigo; o restante (código, .example.env, docs, CREDITS) não."""
    paths = [
        p
        for p in _repo_files()
        if not p.startswith(("tests/", ".git/"))
        and p != "CHANGELOG.md"
        and p.endswith((".py", ".md", ".env", ".yml", ".yaml", ".json", ".toml", ".txt", ".example"))
    ]
    # utils/branding.py (fonte única de identidade) lista de propósito o nome ANTIGO entre as URLs oficiais de versões
    # anteriores, para que instalações com a URL antiga atualizem sozinhas; o upstream (zRitsu) segue proibido nele.
    branding_path = (
        "empiremuse/utils/branding.py" if (ROOT / "empiremuse/utils/branding.py").is_file() else "utils/branding.py"
    )
    others = [p for p in paths if p not in ("utils/branding.py", "empiremuse/utils/branding.py")]
    _fail_with(
        "nome antigo do repositório de binários (use EmpireMuse-LL-binaries)",
        _scan_regex(others, OLD_LL_REPO_RE) + _scan_regex([branding_path], UPSTREAM_LL_REPO_RE),
    )


def test_example_env_leaves_the_jar_url_empty_so_it_follows_the_official_mirror():
    # Fase 2 (defeito de atualização): uma URL fixa no .env quebrava a cada versão nova. Detalhes: tests/test_audio_fase2a3.py.
    match = re.search(r"^LAVALINK_FILE_URL=(.*)$", _read(".example.env"), re.MULTILINE)
    assert match and match.group(1).strip().strip("'\"") == ""


# --------------------------------------------------------------------------- R3 Recursos do upstream


def _jishaku_exception(path: str, line: str) -> bool:
    return path == JISHAKU_EXCEPTION_FILE and re.search(r"jishaku", line, re.IGNORECASE) is not None


PANEL_CREDIT_FILE = (
    "empiremuse/panel/templates/base.html"
    if (ROOT / "empiremuse/panel/templates/base.html").is_file()
    else "panel/templates/base.html"
)
UPSTREAM_REPO_URL = "https://github.com/zRitsu/MuseHeart-MusicBot"
ATTRIBUTION_RE = re.compile(r"zRitsu(?!/)")
OTHER_UPSTREAM_PATTERNS = tuple(p for p in UPSTREAM_RESOURCE_PATTERNS if p != "zRitsu")


def _gpl_credit_exception(path: str, line: str) -> bool:
    """Crédito GPL-2.0 obrigatório no rodapé do painel: só o link para UPSTREAM_URL e o nome do autor
    ('zRitsu' não seguido de '/'); qualquer outro recurso do upstream na mesma linha continua barrado."""
    if path != PANEL_CREDIT_FILE:
        return False
    remainder = line.replace(UPSTREAM_REPO_URL, "")
    if any(_contains(remainder, pattern) for pattern in OTHER_UPSTREAM_PATTERNS):
        return False
    return not re.search(r"zritsu/", remainder, re.IGNORECASE)


def _line_exception(path: str, line: str) -> bool:
    return _jishaku_exception(path, line) or _gpl_credit_exception(path, line)


def test_runtime_files_have_no_upstream_resources():
    # Exceções: utils/branding.py (UPSTREAM_*), tests/**, a linha do jishaku em requirements.txt e o crédito
    # GPL-2.0 ao upstream no rodapé do painel (panel/templates/base.html).
    # Arquivos de deploy ficam fora (I-7 adiado) — ver teste pulado abaixo.
    violations = _scan(_runtime_files(deploy=False), UPSTREAM_RESOURCE_PATTERNS, ignore_line=_line_exception)
    _fail_with("Recursos do upstream em arquivos de runtime", violations)


def test_deploy_files_have_no_upstream_resources():
    violations = _scan(_runtime_files(deploy=True), UPSTREAM_RESOURCE_PATTERNS)
    _fail_with("Recursos do upstream em arquivos de deploy", violations)


# --------------------------------------------------------------------------- R4 Assets


def _asset_files() -> list[Path]:
    if not ASSETS_DIR.is_dir():
        pytest.fail("assets/ não existe", pytrace=False)
    return sorted(p for p in ASSETS_DIR.iterdir() if p.is_file() and p.name != "SHA256SUMS")


def _parse_sums() -> dict[str, str]:
    sums_file = ASSETS_DIR / "SHA256SUMS"
    if not sums_file.is_file():
        pytest.fail("assets/SHA256SUMS não existe", pytrace=False)
    entries = {}
    for lineno, line in enumerate(sums_file.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", line.strip("\r"))
        if not match:
            pytest.fail(f"assets/SHA256SUMS:{lineno}: formato inválido: {line!r}", pytrace=False)
        entries[match.group(2)] = match.group(1)
    return entries


def test_assets_sha256sums_lists_exactly_the_asset_files():
    listed = set(_parse_sums())
    present = {p.name for p in _asset_files()}
    assert listed == present, (
        f"SHA256SUMS divergente. Faltam na lista: {sorted(present - listed)}; "
        f"listados sem arquivo: {sorted(listed - present)}"
    )


def test_assets_sha256sums_hashes_match_files():
    sums = _parse_sums()
    wrong = [
        f"{p.name}: esperado {sums[p.name][:12]}…, obtido {hashlib.sha256(p.read_bytes()).hexdigest()[:12]}…"
        for p in _asset_files()
        if p.name in sums and hashlib.sha256(p.read_bytes()).hexdigest() != sums[p.name]
    ]
    _fail_with("Hashes de assets/ não conferem", wrong)


def test_asset_url_literals_point_to_existing_assets():
    missing = []
    for path in _repo_files():
        if (
            not path.endswith(".py")
            or path.startswith("tests/")
            or path in ("utils/branding.py", "empiremuse/utils/branding.py")
        ):
            continue
        for lineno, line in enumerate(_read(path).splitlines(), start=1):
            for match in ASSET_URL_LITERAL_RE.finditer(line):
                if not (ASSETS_DIR / match.group("name")).is_file():
                    missing.append(f"{path}:{lineno}: asset_url({match.group('name')!r}) sem arquivo em assets/")
    _fail_with("asset_url() apontando para arquivo inexistente", missing)


def test_asset_url_builds_url_from_base_and_name(branding):
    name = _asset_files()[0].name
    assert branding.asset_url(name) == branding.ASSETS_BASE_URL + "/" + name


@pytest.mark.parametrize("bad_name", ["", "../LICENSE", "sub/x.png", "a\\b.png", "nao_existe_xyz.png"])
def test_asset_url_rejects_invalid_names(branding, bad_name):
    with pytest.raises(ValueError):
        branding.asset_url(bad_name)


# --------------------------------------------------------------------------- R5 Créditos


def test_license_file_is_unchanged():
    digest = hashlib.sha256((ROOT / "LICENSE").read_bytes()).hexdigest()
    assert digest == LICENSE_SHA256, "LICENSE foi alterada (GPL-2.0 deve permanecer intacta)"


def test_credits_file_preserves_upstream_attribution():
    path = ROOT / "CREDITS.md"
    assert path.is_file(), "CREDITS.md não existe na raiz"
    content = path.read_text(encoding="utf-8")
    required = ["zRitsu", "MuseHeart-MusicBot", EXPECTED_CONSTANTS["UPSTREAM_URL"], "GPL"]
    missing = [
        item for item in required if not re.search(rf"(?<![A-Za-z0-9_]){re.escape(item)}(?![A-Za-z0-9_])", content)
    ]
    assert not missing, f"CREDITS.md sem: {missing}"


@pytest.mark.parametrize("const", ["UPSTREAM_NAME", "UPSTREAM_AUTHOR", "UPSTREAM_URL"])
def test_upstream_constants_match_contract(branding, const):
    assert getattr(branding, const) == EXPECTED_CONSTANTS[const]


def test_about_command_links_repo_and_upstream():
    misc_path = "empiremuse/cogs/misc.py" if (ROOT / "empiremuse/cogs/misc.py").is_file() else "modules/misc.py"
    content = _read(misc_path)
    for label, const in (("REPO_URL", "REPO_URL"), ("UPSTREAM_URL", "UPSTREAM_URL")):
        literal = EXPECTED_CONSTANTS[const]
        assert re.search(rf"\bbranding\.{label}\b", content) or literal in content, (
            f"modules/misc.py deve referenciar {label} (via branding.{label} ou literal)"
        )


# --------------------------------------------------------------------------- R6 Nome antigo


def _old_name_scan(paths) -> list[str]:
    violations = []
    for path in paths:
        for lineno, line in enumerate(_read(path).splitlines(), start=1):
            if OLD_NAME_RE.search(line):
                violations.append(f"{path}:{lineno}: {line.strip()[:100]}")
    return violations


def test_python_files_do_not_use_old_bot_name():
    py_files = [
        p
        for p in _repo_files()
        if p.endswith(".py")
        and not p.startswith("tests/")
        and p not in ("utils/branding.py", "empiremuse/utils/branding.py")
    ]
    _fail_with("Nome antigo (MuseHeart) em arquivos .py", _old_name_scan(py_files))


def test_deploy_files_do_not_use_old_bot_name():
    _fail_with("Nome antigo (MuseHeart) em arquivos de deploy", _old_name_scan(_runtime_files(deploy=True)))


# --------------------------------------------------------------------------- R7 Constantes


@pytest.mark.parametrize("const,expected", sorted(EXPECTED_CONSTANTS.items()))
def test_branding_constant_has_contract_value(branding, const, expected):
    assert getattr(branding, const, None) == expected, (
        f"utils.branding.{const} ausente ou com valor diferente do contrato"
    )


# --------------------------------------------------------------------------- C3 Escopo EmpireHub e Texto Neutro


def test_client_bot_token_message_has_no_replit_reference():
    """Garante que a mensagem de erro de token em utils/client.py não contém referências à Replit (C-15/C-16)."""
    client_py = (ROOT / "empiremuse" / "utils" / "client.py").read_text(encoding="utf-8")
    assert not re.search(r"\bREPL_SLUG\b", client_py), (
        "utils/client.py ainda contém ramificação específica para REPL_SLUG"
    )
    assert not re.search(r"replit-token\.md", client_py, re.IGNORECASE), (
        "utils/client.py ainda referencia replit-token.md"
    )
    assert not re.search(r"secrets\s+da\s+replit", client_py, re.IGNORECASE), (
        "utils/client.py ainda contém mensagem legada da Replit"
    )


def test_readme_conforms_to_empirehub_scope():
    """Garante que o README não possui seções legadas de auto-hospedagem de terceiros."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert not re.search(r"hospede\s+o\s+seu\s+próprio\s+bot\s+com\s+essa\s+source", readme, re.IGNORECASE)
    assert not re.search(r"source_setup\.sh", readme, re.IGNORECASE)
    assert not re.search(r"replit\.com/@xRitsu", readme, re.IGNORECASE)


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


def _criar(raiz: Path, arquivos: dict[str, str]) -> None:
    for nome, texto in arquivos.items():
        destino = raiz / nome
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")


class TestListagemSemGit:
    GITIGNORE = "\n".join(
        [
            "# comentário",
            "__pycache__/",
            "*.py[cod]",
            "*.log",
            "/build/",
            "docs/rascunho/",
            "!importante.log",
            ".env",
            "segredo?.txt",
            "**/gerado/",
            "dados/**/*.tmp",
            "*.bak # não é comentário: faz parte do padrão",
        ]
    )

    ARQUIVOS = {
        ".gitignore": GITIGNORE,
        "a.py": "x",
        "pkg/b.py": "x",
        "pkg/b.pyc": "x",
        "pkg/__pycache__/c.py": "x",
        "erro.log": "x",
        "importante.log": "x",
        "build/x.py": "x",
        "pkg/build/y.py": "x",
        "docs/rascunho/z.md": "x",
        "docs/guia.md": "x",
        ".env": "x",
        "segredo1.txt": "x",
        "segredo12.txt": "x",
        "a/gerado/g.py": "x",
        "gerado/h.py": "x",
        "dados/d1/d2/lixo.tmp": "x",
        "dados/d1/bom.txt": "x",
        ".git": "gitdir: /em/outro/lugar",
    }

    def test_aplica_as_regras_do_gitignore_como_o_git(self, tmp_path):
        _criar(tmp_path, self.ARQUIVOS)
        encontrados = set(_walk_files(tmp_path))
        assert encontrados == {
            ".gitignore",
            "a.py",
            "pkg/b.py",
            "importante.log",
            "pkg/build/y.py",
            "docs/guia.md",
            "segredo12.txt",
            "dados/d1/bom.txt",
        }

    def test_sem_gitignore_lista_tudo_menos_o_git(self, tmp_path):
        _criar(tmp_path, {"x.py": "1", "sub/y.md": "2", ".git": "g"})
        assert set(_walk_files(tmp_path)) == {"x.py", "sub/y.md"}

    def test_um_diretorio_ignorado_esconde_o_que_foi_reincluido_dentro_dele(self, tmp_path):
        _criar(tmp_path, {".gitignore": "pasta/\n!pasta/ok.txt\n", "pasta/ok.txt": "1", "fora.txt": "2"})
        assert set(_walk_files(tmp_path)) == {".gitignore", "fora.txt"}

    def test_repo_files_sem_dot_git_varre_o_diretorio(self, raiz_falsa):
        _criar(raiz_falsa, {".gitignore": "*.log\n", "a.py": "x", "b.log": "x"})
        assert _repo_files() == [".gitignore", "a.py"]

    def test_repo_files_com_git_ausente_do_sistema_cai_na_varredura(self, raiz_falsa, monkeypatch):
        (raiz_falsa / ".git").mkdir()
        _criar(raiz_falsa, {".gitignore": "*.log\n", "a.py": "x", "b.log": "x"})

        def sem_git(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr(subprocess, "run", sem_git)
        assert _repo_files() == [".gitignore", "a.py"]

    def test_varredura_do_repositorio_real_e_igual_a_listagem_do_git(self):
        """Prova de equivalência: onde há git, a varredura devolve os mesmos arquivos que ``git ls-files``."""
        if not (ROOT / ".git").exists():
            pytest.skip("sem .git: não há listagem do git para comparar")
        try:
            do_git = {*_git_lines("ls-files", "-z"), *_git_lines("ls-files", "-z", "--others", "--exclude-standard")}
        except (OSError, subprocess.CalledProcessError):
            pytest.skip("git indisponível neste ambiente")
        do_git = {p for p in do_git if (ROOT / p).is_file()}
        assert set(_walk_files(ROOT)) == do_git

    def test_o_conjunto_varrido_inclui_os_arquivos_que_as_varreduras_precisam(self):
        arquivos = set(_repo_files())
        assert {"empiremuse/utils/branding.py", "README.md", ".example.env", "assets/SHA256SUMS"} <= arquivos
        assert not any(p.startswith((".git/", ".venv/")) for p in arquivos)


class TestRegrasDoGitignoreEmDetalhe:
    """Cada regra do ``.gitignore`` isolada, com um arquivo que prova o que ela NÃO ignora."""

    @staticmethod
    def listar(pasta, gitignore, arquivos):
        _criar(pasta, {".gitignore": gitignore, **dict.fromkeys(arquivos, "x")})
        return set(_walk_files(pasta)) - {".gitignore"}

    def test_regra_so_de_diretorio_nao_ignora_arquivo_de_mesmo_nome(self, tmp_path):
        assert self.listar(tmp_path, "build/\n", ["build", "sub/build", "x/build/y.py"]) == {"build", "sub/build"}

    def test_asterisco_nao_atravessa_a_barra(self, tmp_path):
        assert self.listar(tmp_path, "a*b\n", ["axb", "a/x/b", "ab"]) == {"a/x/b"}

    def test_interrogacao_nao_casa_a_barra(self, tmp_path):
        assert self.listar(tmp_path, "a?b\n", ["a/b", "a1b"]) == {"a/b"}

    def test_duplo_asterisco_no_fim_ignora_o_conteudo_em_qualquer_profundidade(self, tmp_path):
        arquivos = ["dados/c.txt", "dados/a/b.txt", "dadosx/c.txt", "dados2/a/b.txt"]
        assert self.listar(tmp_path, "dados/**\n", arquivos) == {"dadosx/c.txt", "dados2/a/b.txt"}

    def test_classe_com_negacao_ignora_so_o_que_nao_esta_na_lista(self, tmp_path):
        assert self.listar(tmp_path, "[!a]x\n", ["ax", "bx"]) == {"ax"}

    def test_barra_invertida_escapa_o_primeiro_caractere(self, tmp_path):
        """``\\#nota`` é o nome literal ``#nota`` (não é comentário) e ``\\!x`` o nome literal ``!x`` (não é negação)."""
        assert self.listar(tmp_path, "\\#nota\n\\!x\n", ["#nota", "!x", "outro"]) == {"outro"}

    def test_espacos_no_fim_da_linha_sao_ignorados(self, tmp_path):
        assert self.listar(tmp_path, "foo   \n", ["foo", "foo2"]) == {"foo2"}

    def test_linha_de_comentario_nao_vira_regra(self, tmp_path):
        assert self.listar(tmp_path, "# nota\n", ["# nota", "outro"]) == {"# nota", "outro"}


class TestFiltrosDaListagem:
    def test_arquivo_rastreado_que_nao_existe_mais_nao_e_listado(self, raiz_falsa, monkeypatch):
        """``git ls-files`` ainda lista o arquivo apagado e não commitado; ler o que não existe quebraria as varreduras."""
        import sys

        (raiz_falsa / ".git").mkdir()
        _criar(raiz_falsa, {"existe.py": "x"})

        def do_git(*args):
            return [] if "--others" in args else ["existe.py", "apagado.py"]

        monkeypatch.setattr(sys.modules[__name__], "_git_lines", do_git)
        assert _repo_files() == ["existe.py"]

    @pytest.mark.parametrize(
        ("caminho", "padroes", "esperado"),
        [
            ("pasta/Dockerfile", ("Dockerfile",), True),
            ("pasta/sub/x.py", ("*.py",), True),
            ("Dockerfile.bak/x", ("Dockerfile",), False),
            ("pasta/x.txt", ("*.py",), False),
        ],
    )
    def test_o_padrao_vale_para_o_nome_do_arquivo_em_qualquer_pasta(self, caminho, padroes, esperado):
        assert _matches(caminho, padroes) is esperado


class TestCorrespondenciaPrecisa:
    """Os termos proibidos são casados por palavra/host inteiros, sem diferenciar a caixa."""

    @pytest.mark.parametrize(
        ("termo", "texto"),
        [
            ("imgur.com", "https://i.imgur.com/abc.png"),
            ("imgur.com", "https://IMGUR.COM/x"),
            ("imgur.com", "veja imgur.com."),
            ("i.imgur.com/", "src='https://i.imgur.com/a.png'"),
            ("ibb.co", "http://ibb.co/x e outra"),
            ("i.ibb.co", "https://i.ibb.co/ab/c.png"),
            ("iili.io", "![x](https://iili.io/a.png)"),
            ("cdn.discordapp.com/attachments/", "https://cdn.discordapp.com/attachments/1/2/a.png"),
            ("cdn.discordapp.com/attachments/", "HTTPS://CDN.DISCORDAPP.COM/ATTACHMENTS/1"),
            ("zRitsu", "autor: zRitsu"),
            ("zRitsu", "github.com/zritsu/repo"),
            ("zRitsu", "(zRitsu)"),
            ("911370624507707483", "id=911370624507707483&x=1"),
            ("iconfinder.com/", "https://www.iconfinder.com/icons/1"),
        ],
    )
    def test_acha(self, termo, texto):
        assert _contains(texto, termo), f"{termo!r} deveria ser encontrado em {texto!r}"

    @pytest.mark.parametrize(
        ("termo", "texto"),
        [
            ("imgur.com", "https://notimgur.com/x"),
            ("imgur.com", "https://imgur.company.invalid/x"),
            ("imgur.com", "https://imgur.com.br/x"),
            ("ibb.co", "https://ibb.com/x"),
            ("ibb.co", "https://ibb.co.uk/x"),
            ("ibb.co", "https://fibb.co/x"),
            ("i.ibb.co", "https://xi.ibb.co.invalid/x"),
            ("iili.io", "https://iili.iot/x"),
            ("cdn.discordapp.com/attachments/", "https://mycdn.discordapp.com/attachments/1"),
            ("cdn.discordapp.com/attachments/", "https://cdn.discordapp.com/emojis/1.png"),
            ("zRitsu", "zRitsuX e xzRitsu e z_Ritsu"),
            ("zRitsu", "zRitsu_bot"),
            ("911370624507707483", "9113706245077074830 e 1911370624507707483"),
            ("iconfinder.com/", "https://iconfinder.com.invalid/x"),
        ],
    )
    def test_nao_acha_parecidos(self, termo, texto):
        assert not _contains(texto, termo), f"{termo!r} NÃO deveria ser encontrado em {texto!r}"

    @pytest.mark.parametrize(
        "texto", ["MuseHeart", "museheart", "MUSE-HEART", "Muse_Heart", "muse heart bot", "x MuseHeart-MusicBot"]
    )
    def test_nome_antigo_achado(self, texto):
        assert OLD_NAME_RE.search(texto)

    @pytest.mark.parametrize("texto", ["amuse heart", "Amuse-Heart", "confuse_heart", "music heart", "museum heart"])
    def test_palavras_parecidas_nao_sao_o_nome_antigo(self, texto):
        assert not OLD_NAME_RE.search(texto)

    def test_o_nome_antigo_seguido_de_letras_continua_sendo_o_nome_antigo(self):
        assert OLD_NAME_RE.search("muse hearty")

    @pytest.mark.parametrize(
        ("regex", "texto", "achou"),
        [
            (OLD_LL_REPO_RE, "DiscordEmpireHub/LL-binaries", True),
            (OLD_LL_REPO_RE, "https://github.com/DiscordEmpireHub/LL-binaries.git", True),
            (OLD_LL_REPO_RE, "discordempirehub/ll-binaries/releases", True),
            (OLD_LL_REPO_RE, "DiscordEmpireHub/EmpireMuse-LL-binaries", False),
            (OLD_LL_REPO_RE, "DiscordEmpireHub/LL-binaries-extra", False),
            (UPSTREAM_LL_REPO_RE, "zRitsu/LL-binaries", True),
            (UPSTREAM_LL_REPO_RE, "zRitsu/LL-binariesX", False),
        ],
    )
    def test_nome_antigo_do_repositorio_de_binarios(self, regex, texto, achou):
        assert bool(regex.search(texto)) is achou

    def test_scan_acusa_o_arquivo_a_linha_e_o_termo(self, raiz_falsa):
        _criar(raiz_falsa, {"a.txt": "limpo\nveja https://i.imgur.com/x.png\n", "b.txt": "https://notimgur.com/x\n"})
        assert _scan(["a.txt", "b.txt"], ["imgur.com", "zRitsu"]) == ["a.txt:2: 'imgur.com'"]

    def test_o_crédito_gpl_do_painel_continua_aceito_e_outros_recursos_na_mesma_linha_nao(self):
        base = PANEL_CREDIT_FILE
        assert _gpl_credit_exception(base, f"por zRitsu, {UPSTREAM_REPO_URL}")
        assert not _gpl_credit_exception(base, f"zRitsu {UPSTREAM_REPO_URL} https://i.imgur.com/a.png")
        assert not _gpl_credit_exception(base, "github.com/zRitsu/outro")
        assert not _gpl_credit_exception("outro/arquivo.html", "zRitsu")

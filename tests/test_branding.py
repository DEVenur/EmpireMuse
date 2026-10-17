"""Teste-guarda de marca da Fase 1 (Identidade EmpireMuse).

Os testes são escritos a partir do CONTRATO (BRIEFING-FASE1.md), não do código
atual. Obra derivada de MuseHeart-MusicBot (zRitsu), GPL-2.0: os créditos ao
upstream são preservados (ver CREDITS.md e utils/branding.py).
"""

import configparser
import fnmatch
import hashlib
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
    "*.bat",
    "*.yml",
    "*.yaml",
    ".example.env",
    "*.config.example",
    "Dockerfile",
    ".Dockerfile",
    "*.Dockerfile",
    ".replit",
    "*.html",
    "*.json",
    "*.toml",
    "requirements*.txt",
)

# I-7 Deploy (reativado): estes arquivos de deploy também devem estar com a identidade do EmpireMuse.
DEPLOY_PATTERNS = (
    "render.yaml",
    "discloud.config.example",
    "squarecloud.config.example",
    ".replit",
    ".gitpod.yml",
    "Dockerfile",
    ".Dockerfile",
    "*.Dockerfile",
    "replit.nix",
    "docker-compose*",
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

OLD_NAME_RE = re.compile(r"muse[ _-]?heart", re.IGNORECASE)
ASSET_URL_LITERAL_RE = re.compile(r"""asset_url\(\s*(["'])(?P<name>[^"']+)\1\s*\)""")


# --------------------------------------------------------------------------- helpers


def _git_lines(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.split("\0") if line]


def _repo_files() -> list[str]:
    """Arquivos rastreados + novos não rastreados (respeitando .gitignore) que existem em disco."""
    tracked = _git_lines("ls-files", "-z")
    untracked = _git_lines("ls-files", "-z", "--others", "--exclude-standard")
    return sorted(p for p in {*tracked, *untracked} if (ROOT / p).is_file())


def _matches(path: str, patterns) -> bool:
    name = Path(path).name
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def _is_deploy(path: str) -> bool:
    return _matches(path, DEPLOY_PATTERNS)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def _scan(paths, needles, *, ignore_line=None, case_insensitive=False) -> list[str]:
    """Retorna violações no formato 'arquivo:linha: needle'."""
    violations = []
    for path in paths:
        for lineno, line in enumerate(_read(path).splitlines(), start=1):
            if ignore_line and ignore_line(path, line):
                continue
            haystack = line.lower() if case_insensitive else line
            for needle in needles:
                probe = needle.lower() if case_insensitive else needle
                if probe in haystack:
                    violations.append(f"{path}:{lineno}: {needle!r}")
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


@pytest.mark.parametrize("script", ["source_update.sh", "source_quick_update.sh"])
def test_update_scripts_point_to_empiremuse(script):
    content = _read(script)
    assert "zRitsu" not in content, f"{script} ainda referencia zRitsu: {_scan([script], ['zRitsu'])}"
    assert "DiscordEmpireHub/EmpireMuse.git" in content, f"{script} deve conter DiscordEmpireHub/EmpireMuse.git"


def test_render_yaml_has_no_upstream_author():
    assert "zRitsu" not in _read("render.yaml"), _scan(["render.yaml"], ["zRitsu"])


def test_render_yaml_points_to_the_empiremuse_repo(branding):
    content = _read("render.yaml")
    assert re.search(rf"^\s*repo:\s*{re.escape(branding.SOURCE_REPO_GIT)}\s*$", content, re.MULTILINE), (
        f"render.yaml: repo deve ser {branding.SOURCE_REPO_GIT}"
    )


def test_render_yaml_python_version_is_compatible_with_the_project():
    match = re.search(r"key:\s*PYTHON_VERSION\s*\n\s*value:\s*['\"]?([0-9.]+)", _read("render.yaml"))
    assert match, "render.yaml deve definir PYTHON_VERSION"
    assert re.fullmatch(r"3\.13(\.\d+)?", match.group(1)), f"PYTHON_VERSION {match.group(1)} deve ser 3.13.x"


def test_discloud_avatar_is_the_empiremuse_brand_asset(branding):
    match = re.search(r"^AVATAR=(\S+)\s*$", _read("discloud.config.example"), re.MULTILINE)
    assert match, "discloud.config.example deve definir AVATAR"
    assert (ROOT / "assets/brand/avatar.png").is_file()
    assert match.group(1) == f"{branding.ASSETS_BASE_URL}/brand/avatar.png"


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
    assert files, "nenhum arquivo de deploy encontrado"
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
    violations = _scan([path], ["zRitsu/LL-binaries"])
    _fail_with("local_lavalink.py ainda aponta para zRitsu/LL-binaries", violations)


RENAMED_LL_REPO = (
    "DiscordEmpireHub/LL-binaries"  # renomeado para DiscordEmpireHub/EmpireMuse-LL-binaries (301 no GitHub)
)


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
        _scan(others, [RENAMED_LL_REPO, "zRitsu/LL-binaries"]) + _scan([branding_path], ["zRitsu/LL-binaries"]),
    )


def test_example_env_leaves_the_jar_url_empty_so_it_follows_the_official_mirror():
    # Fase 2 (defeito de atualização): uma URL fixa no .env quebrava a cada versão nova. Detalhes: tests/test_audio_fase2a3.py.
    match = re.search(r"^LAVALINK_FILE_URL=(.*)$", _read(".example.env"), re.MULTILINE)
    assert match and match.group(1).strip().strip("'\"") == ""


# --------------------------------------------------------------------------- R3 Recursos do upstream


def _jishaku_exception(path: str, line: str) -> bool:
    return path == JISHAKU_EXCEPTION_FILE and "jishaku" in line.lower()


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
    if any(pattern in remainder for pattern in OTHER_UPSTREAM_PATTERNS):
        return False
    return "zRitsu/" not in remainder


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
    missing = [item for item in required if item not in content]
    assert not missing, f"CREDITS.md sem: {missing}"


@pytest.mark.parametrize("const", ["UPSTREAM_NAME", "UPSTREAM_AUTHOR", "UPSTREAM_URL"])
def test_upstream_constants_match_contract(branding, const):
    assert getattr(branding, const) == EXPECTED_CONSTANTS[const]


def test_about_command_links_repo_and_upstream():
    misc_path = "empiremuse/cogs/misc.py" if (ROOT / "empiremuse/cogs/misc.py").is_file() else "modules/misc.py"
    content = _read(misc_path)
    for label, const in (("REPO_URL", "REPO_URL"), ("UPSTREAM_URL", "UPSTREAM_URL")):
        literal = EXPECTED_CONSTANTS[const]
        assert f"branding.{label}" in content or literal in content, (
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
    assert "REPL_SLUG" not in client_py, "utils/client.py ainda contém ramificação específica para REPL_SLUG"
    assert "replit-token.md" not in client_py, "utils/client.py ainda referencia replit-token.md"
    assert "secrets da replit" not in client_py, "utils/client.py ainda contém mensagem legada da Replit"


def test_readme_conforms_to_empirehub_scope():
    """Garante que o README não possui seções legadas de auto-hospedagem de terceiros."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Hospede o seu próprio bot com essa source" not in readme
    assert "source_setup.sh" not in readme
    assert "replit.com/@xRitsu" not in readme

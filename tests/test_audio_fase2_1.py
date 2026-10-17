"""Fase 2.1 — (1) JDK baixado com SHA-256 fixo e (2) allowlist de ambiente do processo do Lavalink.

Contrato: BRIEFING-FASE2_1.md (itens 1 e 2). Interpretações: .qa-fase2_1-interp.txt (staging).
Sem rede, sem Java e sem produção: `requests.get` é um dublê, os arquivos de JDK são arquivos MÍNIMOS gerados em memória e
tudo roda em tmp_path. Os valores de SHA-256 reais do JDK NÃO são conferidos aqui (vêm do DevOps): só formato e uso.

API exigida do Backend (nomes fixados pelos testes):
  utils/branding.py       JDK_DOWNLOADS: Mapping[str, tuple[str, str]] com as chaves "windows-amd64", "windows-i586",
                          "linux-amd64", "linux-i586" -> (url oficial, sha256 em 64 hex minúsculos). Lido em tempo de chamada.
  local_lavalink.py       os 4 downloads do JDK passam por download_verified(url, destino, sha256); a extração só ocorre
                          depois da verificação; nenhum java.zip/java.tar.gz pré-existente é usado sem verificação;
                          lavalink_child_env(refresh_token, environ=os.environ) -> dict[str, str] (função pura);
                          o Popen do Lavalink SEMPRE recebe env=lavalink_child_env(token).
"""
import hashlib
import inspect
import io
import logging
import os
import re
import tarfile
import types
import zipfile
from pathlib import Path
from types import MappingProxyType

import pytest

from utils import branding
from utils.music import local_lavalink as ll

ROOT = Path(__file__).resolve().parent.parent

# ============================================================================ constantes do contrato

JDK_KEYS = ("windows-amd64", "windows-i586", "linux-amd64", "linux-i586")
JDK_URLS = {
    "windows-amd64": "https://download.bell-sw.com/java/17.0.13+12/bellsoft-jdk17.0.13+12-windows-amd64.zip",
    "windows-i586": "https://download.bell-sw.com/java/17.0.13+12/bellsoft-jdk17.0.13+12-windows-i586.zip",
    "linux-amd64": "https://download.bell-sw.com/java/21.0.3+12/bellsoft-jdk21.0.3+12-linux-amd64-lite.tar.gz",
    "linux-i586": "https://download.bell-sw.com/java/21.0.3+12/bellsoft-jdk21.0.3+12-linux-i586-lite.tar.gz",
}
COMMON_ALLOWED = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "TEMP", "TMP", "JAVA_HOME", "SERVER_PORT")
WINDOWS_ONLY_ALLOWED = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA")
OAUTH_VARS = ("PLUGINS_YOUTUBE_OAUTH_ENABLED", "PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN",
              "PLUGINS_YOUTUBE_OAUTH_SKIP_INITIALIZATION")
# Valores sintéticos: nunca são segredos reais.
FAKE_TOKEN = "1//0gFAKE-refresh_TOKEN-qa-fase2-1-zZ9"
SECRET_SENTINELS = {
    "TOKEN": "sentinela-token-do-bot",
    "MONGO": "mongodb://usuario:sentinela-senha@host/db",
    "SPOTIFY_CLIENT_SECRET": "sentinela-spotify",
    "PANEL_COOKIE_SECRET": "sentinela-cookie-do-painel",
    "PANEL_OAUTH_CLIENT_SECRET": "sentinela-oauth-do-painel",
    "LASTFM_SECRET": "sentinela-lastfm",
}
NEVER_PASSED = (
    "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "PYTHONPATH", "SPRING_APPLICATION_JSON", "SPRING_CONFIG_LOCATION", "LAVALINK_SERVER_PASSWORD", "HTTP_PROXY",
    "HTTPS_PROXY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "DISCORD_TOKEN", "TOKEN_BOT_1", "PLUGINS_YOUTUBE_ENABLED",
    *SECRET_SENTINELS,
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fail(message: str):
    """Falha SEM eco de valores (o ambiente do desenvolvedor pode conter segredos reais)."""
    pytest.fail(message, pytrace=False)


# ============================================================================ (1a) constantes reais do branding

class TestJdkDownloadsConstant:
    def test_exists_and_is_a_mapping_with_exactly_the_four_platform_keys(self):
        table = getattr(branding, "JDK_DOWNLOADS", None)
        assert table is not None, "utils/branding.py precisa definir JDK_DOWNLOADS"
        assert set(table) == set(JDK_KEYS)

    @pytest.mark.parametrize("key", JDK_KEYS)
    def test_each_entry_is_url_and_sha256_with_the_same_urls_used_today(self, key):
        url, digest = branding.JDK_DOWNLOADS[key]
        assert url == JDK_URLS[key]
        assert re.fullmatch(r"[0-9a-f]{64}", digest), "SHA-256 precisa ter 64 hex minúsculos"

    def test_urls_are_https_from_bellsoft_and_hashes_are_not_placeholders(self):
        digests = [d for _, d in branding.JDK_DOWNLOADS.values()]
        assert all(u.startswith("https://download.bell-sw.com/java/") for u, _ in branding.JDK_DOWNLOADS.values())
        assert len(set(digests)) == len(digests), "cada arquivo tem o seu próprio hash (nada repetido/copiado)"
        assert not any(len(set(d)) <= 2 for d in digests), "hash com cara de placeholder (0000…, aaaa…)"

    def test_local_lavalink_no_longer_hardcodes_the_bellsoft_urls_or_downloads_the_jdk_unverified(self):
        source = (ROOT / "utils/music/local_lavalink.py").read_text(encoding="utf-8")
        assert "download.bell-sw.com" not in source, "as URLs do JDK passam a viver em branding.JDK_DOWNLOADS"
        assert not re.search(r"download_file\(\s*jdk_url", source), "JDK não pode mais passar por download_file (sem verificação)"


# ============================================================================ fixtures do item 1 (JDK)

class Net:
    """Atende só as URLs em ``served``; qualquer outra é requisição inesperada. Suporta `with` e uso direto."""

    def __init__(self):
        self.served, self.calls, self.error = {}, [], None

    def get(self, url, *args, **kwargs):
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        assert url in self.served, f"requisição inesperada: {url}"
        return _Response(self.served[url])


class _Response:
    def __init__(self, data):
        self.data = data
        self.headers = {"content-length": str(len(data))}
        self.status_code = 200

    def iter_content(self, chunk_size=1):
        yield self.data

    def raise_for_status(self):
        return None

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_tar_gz(files: dict) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def make_zip(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def good_archive(key: str) -> bytes:
    """Mini-JDK: uma pasta raiz com bin/java (ou bin/java.exe); o conteúdo identifica a plataforma escolhida."""
    marker = f"JAVA-BOM-{key}".encode()
    if key.startswith("windows"):
        return make_zip({"jdk-17.0.13/bin/java.exe": marker, "jdk-17.0.13/release": b"ok"})
    return make_tar_gz({"jdk-21.0.3-lite/bin/java": marker, "jdk-21.0.3-lite/release": b"ok"})


def evil_archive(key: str) -> bytes:
    if key.startswith("windows"):
        return make_zip({"jdk-evil/bin/java.exe": b"JAVA-MALICIOSO", "jdk-evil/EVIL_MARKER": b"x"})
    return make_tar_gz({"jdk-evil/bin/java": b"JAVA-MALICIOSO", "jdk-evil/EVIL_MARKER": b"x"})


class OsProxy:
    """Só o módulo local_lavalink enxerga `os.name == "nt"`; o resto do processo (pytest, tmp_path) segue POSIX."""

    def __init__(self, real, name):
        self._real, self.name = real, name

    def __getattr__(self, attr):
        return getattr(self._real, attr)


def pretend_windows(monkeypatch):
    monkeypatch.setattr(ll, "os", OsProxy(os, "nt"))
    monkeypatch.setattr(ll.platform, "system", lambda: "Windows")
    if hasattr(ll, "sys"):
        monkeypatch.setattr(ll, "sys", types.SimpleNamespace(platform="win32"))


def tree(base: Path) -> set:
    return {str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()}


@pytest.fixture
def jdk(monkeypatch, tmp_path):
    """Ambiente sem Java: Lavalink.jar/yml/plugins já presentes e verificados; JDK_DOWNLOADS trocado por mini-arquivos."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JAVA_HOME", raising=False)
    jar, yml = b"JAR", b"YML\n"
    plugins = {n: f"plugin {n}".encode() for n in ("youtube-plugin-2be8e542d3f6f178e048dca565892684c2e40177.jar",
                                                   "lavasrc-plugin-4.8.3.jar", "lavalink-2.6.1.jar")}
    monkeypatch.setattr(branding, "LAVALINK_JAR_SHA256", sha(jar))
    monkeypatch.setattr(branding, "LAVALINK_APPLICATION_YML_SHA256", sha(yml))
    monkeypatch.setattr(branding, "LAVALINK_PLUGIN_SHA256", {n: sha(d) for n, d in plugins.items()})
    (tmp_path / "Lavalink.jar").write_bytes(jar)
    (tmp_path / "application.yml").write_bytes(yml)
    (tmp_path / "plugins").mkdir()
    for name, data in plugins.items():
        (tmp_path / "plugins" / name).write_bytes(data)

    archives = {key: good_archive(key) for key in JDK_KEYS}
    test_urls = {key: f"https://example.test/jdk/{key}.{'zip' if key.startswith('windows') else 'tar.gz'}" for key in JDK_KEYS}
    monkeypatch.setattr(branding, "JDK_DOWNLOADS", {k: (test_urls[k], sha(archives[k])) for k in JDK_KEYS}, raising=False)

    net = Net()
    net.served = {test_urls[k]: archives[k] for k in JDK_KEYS}
    monkeypatch.setattr(ll.requests, "get", net.get)

    monkeypatch.setattr(ll, "validate_java",
                        lambda cmd, debug=False: cmd if cmd != "java" and os.path.isfile(cmd) else None)

    real_popen = ll.subprocess.Popen
    started, extractions = [], []

    def popen(args, **kwargs):
        if args and args[0] == "tar":
            extractions.append(("tar", _archive_hash_in(args)))
            return real_popen(args, **kwargs)
        started.append((list(args), kwargs))

    monkeypatch.setattr(ll.subprocess, "Popen", popen)

    real_tar_open, real_zip = tarfile.open, zipfile.ZipFile

    def tar_open(name=None, *a, **k):
        if isinstance(name, (str, os.PathLike)):
            extractions.append(("tarfile", sha(Path(name).read_bytes()) if Path(name).is_file() else None))
        return real_tar_open(name, *a, **k)

    class RecordingZip(real_zip):
        def __init__(self, file, *a, **k):
            if isinstance(file, (str, os.PathLike)) and Path(file).is_file():
                extractions.append(("zipfile", sha(Path(file).read_bytes())))
            super().__init__(file, *a, **k)

    monkeypatch.setattr(tarfile, "open", tar_open)
    monkeypatch.setattr(zipfile, "ZipFile", RecordingZip)

    return types.SimpleNamespace(net=net, archives=archives, urls=test_urls, started=started, extractions=extractions,
                                 base=tmp_path, baseline=tree(tmp_path), monkeypatch=monkeypatch)


def _archive_hash_in(args):
    for arg in args:
        if str(arg).endswith(".tar.gz") and Path(arg).is_file():
            return sha(Path(arg).read_bytes())
    return None


def linux(env, bits):
    env.monkeypatch.setattr(ll.platform, "architecture", lambda *a, **k: (bits, "ELF"))
    env.monkeypatch.setattr(ll.platform, "system", lambda: "Linux")
    key = "linux-amd64" if bits == "64bit" else "linux-i586"
    java = env.base / ".java" / f"Linux-{bits}-ELF" / "bin" / "java"
    return key, java, env.base / "java.tar.gz"


def windows(env, bits):
    pretend_windows(env.monkeypatch)
    env.monkeypatch.setattr(ll.platform, "architecture", lambda *a, **k: (bits, "WindowsPE"))
    wintmp = env.base / "wintmp"
    wintmp.mkdir()
    env.monkeypatch.setattr(ll.tempfile, "gettempdir", lambda: str(wintmp))
    env.baseline = tree(env.base)
    key = "windows-amd64" if bits == "64bit" else "windows-i586"
    java = wintmp / ".java" / f"Windows-{bits}-WindowsPE" / "bin" / "java.exe"
    return key, java, wintmp / "java.zip"


PLATFORMS = [("linux", "64bit"), ("linux", "32bit"), ("windows", "64bit"), ("windows", "32bit")]


def setup_platform(env, system, bits):
    return (linux if system == "linux" else windows)(env, bits)


# ============================================================================ (1b) comportamento dos downloads

@pytest.mark.parametrize("system,bits", PLATFORMS)
class TestJdkDownloadIsVerified:
    def test_downloads_the_entry_of_the_running_platform_and_nothing_else(self, jdk, system, bits):
        key, java, _ = setup_platform(jdk, system, bits)
        ll.run_lavalink()
        assert jdk.net.calls == [jdk.urls[key]], "só a URL (de branding.JDK_DOWNLOADS) da plataforma em uso"

    def test_extracts_the_verified_jdk_and_starts_the_lavalink(self, jdk, system, bits):
        key, java, archive = setup_platform(jdk, system, bits)
        ll.run_lavalink()
        assert java.read_bytes() == f"JAVA-BOM-{key}".encode()
        assert len(jdk.started) == 1 and "Lavalink.jar" in jdk.started[0][0]
        assert not archive.exists(), "o arquivo baixado é removido depois da extração"

    def test_extraction_happens_only_after_the_archive_matches_the_pinned_hash(self, jdk, system, bits):
        key, _, _ = setup_platform(jdk, system, bits)
        ll.run_lavalink()
        assert jdk.extractions, "nenhuma extração observada (tar/tarfile/zipfile)"
        expected = branding.JDK_DOWNLOADS[key][1]
        assert all(digest == expected for _, digest in jdk.extractions), \
            "o arquivo foi aberto/extraído antes de estar verificado (ou diferente do esperado)"

    def test_wrong_hash_aborts_with_integrity_error_and_leaves_nothing_behind(self, jdk, system, bits):
        key, java, archive = setup_platform(jdk, system, bits)
        jdk.net.served[jdk.urls[key]] = evil_archive(key)
        with pytest.raises(ll.IntegrityError):
            ll.run_lavalink()
        assert jdk.extractions == [], "nada pode ser extraído sem verificação"
        assert tree(jdk.base) == jdk.baseline, "nenhum arquivo parcial/extraído/baixado pode sobrar"
        assert jdk.started == [] and not java.exists()

    def test_network_failure_aborts_with_download_error_and_leaves_nothing_behind(self, jdk, system, bits):
        key, java, _ = setup_platform(jdk, system, bits)
        jdk.net.error = ll.requests.ConnectionError("sem rede")
        with pytest.raises(ll.LavalinkDownloadError):
            ll.run_lavalink()
        assert jdk.extractions == [] and tree(jdk.base) == jdk.baseline
        assert jdk.started == [] and not java.exists()

    def test_the_error_message_is_clear_and_does_not_leak_the_environment(self, jdk, system, bits):
        key, _, _ = setup_platform(jdk, system, bits)
        jdk.net.served[jdk.urls[key]] = evil_archive(key)
        jdk.monkeypatch.setenv("TOKEN", SECRET_SENTINELS["TOKEN"])
        with pytest.raises(ll.IntegrityError) as info:
            ll.run_lavalink()
        message = str(info.value)
        assert message.strip() and SECRET_SENTINELS["TOKEN"] not in message

    def test_a_preexisting_unverified_archive_is_never_used(self, jdk, system, bits):
        key, java, archive = setup_platform(jdk, system, bits)
        archive.write_bytes(evil_archive(key))
        ll.run_lavalink()
        assert java.read_bytes() == f"JAVA-BOM-{key}".encode(), "o JDK instalado tem de vir do download verificado"
        assert not (java.parent.parent / "EVIL_MARKER").exists()
        assert jdk.net.calls == [jdk.urls[key]], "o arquivo pré-existente inválido foi substituído por um download"

    def test_a_preexisting_unverified_archive_is_never_extracted_when_the_download_fails(self, jdk, system, bits):
        key, java, archive = setup_platform(jdk, system, bits)
        archive.write_bytes(evil_archive(key))
        jdk.net.error = ll.requests.ConnectionError("sem rede")
        with pytest.raises(ll.LavalinkDownloadError):
            ll.run_lavalink()
        assert jdk.extractions == [] and not java.exists() and jdk.started == []

    def test_a_preexisting_archive_with_the_correct_hash_may_be_used(self, jdk, system, bits):
        key, java, archive = setup_platform(jdk, system, bits)
        archive.write_bytes(jdk.archives[key])
        ll.run_lavalink()
        assert java.read_bytes() == f"JAVA-BOM-{key}".encode() and len(jdk.started) == 1

    def test_a_pinned_table_change_is_honored_at_call_time(self, jdk, system, bits):
        key, java, _ = setup_platform(jdk, system, bits)
        other = b"outro-conteudo-qualquer"
        jdk.monkeypatch.setattr(branding, "JDK_DOWNLOADS", {**branding.JDK_DOWNLOADS, key: (jdk.urls[key], sha(other))})
        with pytest.raises(ll.IntegrityError):
            ll.run_lavalink()
        assert jdk.extractions == []

    def test_no_environment_value_is_printed_or_logged_while_installing(self, jdk, system, bits, capsys, caplog):
        setup_platform(jdk, system, bits)
        caplog.set_level(0)
        for name, value in SECRET_SENTINELS.items():
            jdk.monkeypatch.setenv(name, value)
        ll.run_lavalink()
        out = capsys.readouterr()
        text = out.out + out.err + "\n".join(r.getMessage() for r in caplog.records)
        if any(value in text for value in SECRET_SENTINELS.values()):
            fail("um valor do ambiente apareceu na saída/log durante a instalação do JDK")


class TestInstallationIsSkippedWhenJavaAlreadyWorks:
    def test_a_working_system_java_triggers_no_jdk_download(self, jdk):
        jdk.monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: cmd)
        linux(jdk, "64bit")
        ll.run_lavalink()
        assert jdk.net.calls == [] and len(jdk.started) == 1


# ============================================================================ (2a) lavalink_child_env — função pura

def sentinel_environ(**extra):
    base = {"PATH": "/usr/bin:/bin", "HOME": "/home/bot", "LANG": "pt_BR.UTF-8", "LC_ALL": "C.UTF-8", "LC_CTYPE": "UTF-8",
            "TZ": "America/Sao_Paulo", "TMPDIR": "/tmp", "TEMP": "/tmp", "TMP": "/tmp", "JAVA_HOME": "/opt/jdk",
            "SERVER_PORT": "8123"}
    base.update({name: f"valor-{name}" for name in NEVER_PASSED if name not in SECRET_SENTINELS})
    base.update(SECRET_SENTINELS)
    base.update(extra)
    return base


class TestChildEnvContract:
    def test_function_exists_with_the_documented_signature(self):
        assert hasattr(ll, "lavalink_child_env"), "local_lavalink.lavalink_child_env não existe"
        params = inspect.signature(ll.lavalink_child_env).parameters
        assert list(params)[:2] == ["refresh_token", "environ"]
        assert params["environ"].default is os.environ

    def test_it_replaces_the_old_helper(self):
        assert not hasattr(ll, "_youtube_oauth_popen_kwargs"), "_youtube_oauth_popen_kwargs deve ser substituída"

    def test_passes_exactly_the_common_allowlist_on_posix(self):
        env = ll.lavalink_child_env(None, sentinel_environ(**{n: f"w-{n}" for n in WINDOWS_ONLY_ALLOWED}))
        assert set(env) == set(COMMON_ALLOWED)
        assert env["PATH"] == "/usr/bin:/bin" and env["JAVA_HOME"] == "/opt/jdk"

    def test_server_port_is_passed_because_the_bot_talks_to_the_local_lavalink_on_it(self):
        assert ll.lavalink_child_env(None, {"SERVER_PORT": "9001"}) == {"SERVER_PORT": "9001"}

    @pytest.mark.parametrize("name", NEVER_PASSED)
    def test_nothing_outside_the_allowlist_ever_passes(self, name):
        env = ll.lavalink_child_env(FAKE_TOKEN, {**sentinel_environ(), name: "qualquer"})
        assert name not in env

    def test_java_option_injection_vectors_are_blocked_even_with_token(self):
        env = ll.lavalink_child_env(FAKE_TOKEN, sentinel_environ())
        assert not [k for k in env if k.upper() in {"JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"}]

    def test_absent_names_are_simply_absent_not_empty(self):
        assert ll.lavalink_child_env(None, {"PATH": "/bin"}) == {"PATH": "/bin"}
        assert ll.lavalink_child_env(None, {}) == {}

    def test_posix_names_are_case_sensitive(self):
        assert ll.lavalink_child_env(None, {"path": "/x", "Home": "/y", "server_port": "1"}) == {}

    def test_windows_only_names_are_not_passed_on_posix(self):
        assert ll.lavalink_child_env(None, {n: "x" for n in WINDOWS_ONLY_ALLOWED}) == {}

    def test_returns_a_new_plain_dict_of_strings_and_never_mutates_its_input(self):
        source = sentinel_environ()
        snapshot = dict(source)
        env = ll.lavalink_child_env(FAKE_TOKEN, source)
        assert type(env) is dict and env is not source
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
        env["PATH"] = "alterado"
        env["NOVA"] = "x"
        assert source == snapshot

    def test_accepts_any_read_only_mapping(self):
        env = ll.lavalink_child_env(None, MappingProxyType(sentinel_environ()))
        assert set(env) == set(COMMON_ALLOWED)

    def test_default_reads_the_current_process_environment_without_changing_it(self, monkeypatch):
        monkeypatch.setenv("SERVER_PORT", "7777")
        monkeypatch.setenv("TOKEN", SECRET_SENTINELS["TOKEN"])
        before = dict(os.environ)
        env = ll.lavalink_child_env(None)
        assert env.get("SERVER_PORT") == "7777" and "TOKEN" not in env
        assert dict(os.environ) == before

    def test_never_prints_or_logs_the_environment_or_the_token(self, capsys, caplog):
        caplog.set_level(0)
        ll.lavalink_child_env(FAKE_TOKEN, sentinel_environ())
        out = capsys.readouterr()
        text = out.out + out.err + "\n".join(f"{r.getMessage()} {r.args!r}" for r in caplog.records)
        if FAKE_TOKEN in text or any(value in text for value in SECRET_SENTINELS.values()):
            fail("lavalink_child_env escreveu ambiente/token em stdout, stderr ou log")


class TestChildEnvOauth:
    @pytest.mark.parametrize("token", [None, "", "   ", "\n\t "])
    def test_without_a_token_none_of_the_oauth_variables_exists_even_if_the_bot_environment_has_them(self, token):
        stale = {name: "valor-antigo" for name in OAUTH_VARS}
        env = ll.lavalink_child_env(token, sentinel_environ(**stale))
        assert [v for v in OAUTH_VARS if v in env] == []

    def test_with_a_token_adds_exactly_the_three_variables(self):
        env = ll.lavalink_child_env(FAKE_TOKEN, sentinel_environ())
        assert env["PLUGINS_YOUTUBE_OAUTH_ENABLED"] == "true"
        assert env["PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN"] == FAKE_TOKEN
        assert env["PLUGINS_YOUTUBE_OAUTH_SKIP_INITIALIZATION"] == "true"
        assert set(env) == set(COMMON_ALLOWED) | set(OAUTH_VARS)

    def test_the_token_is_stripped_of_surrounding_whitespace(self):
        env = ll.lavalink_child_env(f"  {FAKE_TOKEN}\n", {})
        assert env["PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN"] == FAKE_TOKEN

    def test_the_given_token_wins_over_a_stale_value_in_the_bot_environment(self):
        env = ll.lavalink_child_env(FAKE_TOKEN, {"PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN": "velho",
                                                 "PLUGINS_YOUTUBE_OAUTH_ENABLED": "false"})
        assert env["PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN"] == FAKE_TOKEN and env["PLUGINS_YOUTUBE_OAUTH_ENABLED"] == "true"

    def test_the_token_only_exists_in_the_returned_dict(self):
        source = {"PATH": "/bin"}
        ll.lavalink_child_env(FAKE_TOKEN, source)
        assert source == {"PATH": "/bin"} and not [v for v in OAUTH_VARS if v in os.environ]


class TestChildEnvOnWindows:
    @pytest.fixture(autouse=True)
    def _windows(self, monkeypatch):
        pretend_windows(monkeypatch)

    def test_passes_the_common_and_the_windows_allowlist(self):
        source = sentinel_environ(**{n: f"w-{n}" for n in WINDOWS_ONLY_ALLOWED})
        assert set(ll.lavalink_child_env(None, source)) == set(COMMON_ALLOWED) | set(WINDOWS_ONLY_ALLOWED)

    def test_names_are_matched_without_regard_to_case(self):
        source = {"Path": "C:\\bin", "SystemRoot": "C:\\Windows", "ComSpec": "cmd.exe", "PathExt": ".EXE", "Temp": "C:\\t",
                  "TMP": "C:\\t", "AppData": "C:\\a", "LocalAppData": "C:\\l", "ProgramData": "C:\\p", "UserProfile": "C:\\u",
                  "WinDir": "C:\\Windows", "Server_Port": "8123", "Java_Home": "C:\\jdk"}
        env = ll.lavalink_child_env(None, source)
        by_upper = {k.upper(): v for k, v in env.items()}
        assert by_upper == {k.upper(): v for k, v in source.items()}
        assert len(by_upper) == len(env), "sem nomes duplicados que só diferem na caixa"

    def test_two_spellings_of_the_same_name_yield_a_single_entry(self):
        env = ll.lavalink_child_env(None, {"Path": "C:\\um", "PATH": "C:\\dois"})
        assert [k.upper() for k in env] == ["PATH"], "no Windows Path e PATH são a mesma variável: apenas uma entrada"

    def test_names_outside_the_allowlist_are_blocked_in_any_case(self):
        source = {"Token": "t", "mongo": "m", "Java_Tool_Options": "-javaagent:x.jar", "_Java_Options": "-Xevil",
                  "Spring_Application_Json": "{}", "panel_cookie_secret": "s", "Path": "C:\\bin"}
        env = ll.lavalink_child_env(None, source)
        assert {k.upper() for k in env} == {"PATH"}

    def test_oauth_variables_follow_the_same_rules_on_windows(self):
        assert [v for v in OAUTH_VARS if v in ll.lavalink_child_env("  ", {"plugins_youtube_oauth_enabled": "true"})] == []
        env = ll.lavalink_child_env(FAKE_TOKEN, {"Path": "C:\\bin", "plugins_youtube_oauth_enabled": "false"})
        assert env["PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN"] == FAKE_TOKEN
        assert env["PLUGINS_YOUTUBE_OAUTH_ENABLED"] == "true"
        assert "plugins_youtube_oauth_enabled" not in env


# ============================================================================ (2b) o Popen do Lavalink sempre recebe env=

@pytest.fixture
def lavalink_start(monkeypatch, tmp_path):
    """run_lavalink com Java 'instalado' e tudo verificado; registra os kwargs do Popen. Ambiente do bot com segredos fictícios."""
    monkeypatch.chdir(tmp_path)
    jar, yml = b"JAR", b"YML\n"
    plugins = {n: f"plugin {n}".encode() for n in ("youtube-plugin-2be8e542d3f6f178e048dca565892684c2e40177.jar",
                                                   "lavasrc-plugin-4.8.3.jar", "lavalink-2.6.1.jar")}
    monkeypatch.setattr(branding, "LAVALINK_JAR_SHA256", sha(jar))
    monkeypatch.setattr(branding, "LAVALINK_APPLICATION_YML_SHA256", sha(yml))
    monkeypatch.setattr(branding, "LAVALINK_PLUGIN_SHA256", {n: sha(d) for n, d in plugins.items()})
    (tmp_path / "Lavalink.jar").write_bytes(jar)
    (tmp_path / "application.yml").write_bytes(yml)
    (tmp_path / "plugins").mkdir()
    for name, data in plugins.items():
        (tmp_path / "plugins" / name).write_bytes(data)

    def no_network(*args, **kwargs):
        raise AssertionError("rede inesperada")

    monkeypatch.setattr(ll.requests, "get", no_network)
    monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: cmd)
    monkeypatch.setattr(ll.platform, "architecture", lambda *a, **k: ("64bit", "ELF"))
    for name, value in SECRET_SENTINELS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/caminho/do/java")
    monkeypatch.setenv("SERVER_PORT", "8123")
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-javaagent:/tmp/evil.jar")
    for name in OAUTH_VARS:
        monkeypatch.delenv(name, raising=False)
    records = []
    monkeypatch.setattr(ll.subprocess, "Popen", lambda args, **kwargs: records.append((list(args), kwargs)))
    return records


class TestPopenAlwaysGetsTheAllowlistedEnv:
    @pytest.mark.parametrize("token", [None, "", "   ", FAKE_TOKEN])
    def test_env_is_always_passed_explicitly(self, lavalink_start, token):
        ll.run_lavalink(youtube_oauth_refresh_token=token)
        assert len(lavalink_start) == 1
        assert isinstance(lavalink_start[0][1].get("env"), dict), "o Popen do Lavalink precisa SEMPRE receber env="

    @pytest.mark.parametrize("token", [None, FAKE_TOKEN])
    def test_env_equals_the_allowlisted_environment_of_the_moment(self, lavalink_start, token):
        ll.run_lavalink(youtube_oauth_refresh_token=token)
        assert lavalink_start[0][1]["env"] == ll.lavalink_child_env(token, os.environ)

    @pytest.mark.parametrize("token", [None, FAKE_TOKEN])
    def test_no_bot_secret_and_no_java_injection_variable_reaches_the_child(self, lavalink_start, token):
        ll.run_lavalink(youtube_oauth_refresh_token=token)
        env = lavalink_start[0][1]["env"]
        leaked = sorted(k for k in env if k in NEVER_PASSED)
        if leaked:
            fail(f"variáveis fora da allowlist chegaram ao processo do Lavalink: {leaked}")
        if any(value in env.values() for value in SECRET_SENTINELS.values()):
            fail("um valor secreto do bot chegou ao processo do Lavalink")

    @pytest.mark.parametrize("token", [None, FAKE_TOKEN])
    def test_path_and_server_port_reach_the_child(self, lavalink_start, token):
        ll.run_lavalink(youtube_oauth_refresh_token=token)
        env = lavalink_start[0][1]["env"]
        assert env.get("PATH") == "/usr/bin:/bin:/caminho/do/java"
        assert env.get("SERVER_PORT") == "8123", "sem SERVER_PORT o Lavalink sobe numa porta que o bot não usa"

    def test_keys_are_only_allowlisted_names_plus_the_oauth_trio(self, lavalink_start):
        ll.run_lavalink(youtube_oauth_refresh_token=FAKE_TOKEN)
        extra = sorted(set(lavalink_start[0][1]["env"]) - set(COMMON_ALLOWED) - set(OAUTH_VARS))
        if extra:
            fail(f"nomes fora da allowlist no ambiente do Lavalink: {extra}")

    def test_without_a_token_the_oauth_trio_is_absent_even_if_the_bot_has_them(self, lavalink_start, monkeypatch):
        for name in OAUTH_VARS:
            monkeypatch.setenv(name, "valor-do-ambiente-do-bot")
        ll.run_lavalink()
        assert [v for v in OAUTH_VARS if v in lavalink_start[0][1]["env"]] == []

    def test_the_process_environment_of_the_bot_is_never_changed(self, lavalink_start):
        before = dict(os.environ)
        ll.run_lavalink(youtube_oauth_refresh_token=FAKE_TOKEN)
        assert dict(os.environ) == before

    def test_the_token_is_never_on_the_command_line_or_in_other_popen_arguments(self, lavalink_start):
        ll.run_lavalink(youtube_oauth_refresh_token=FAKE_TOKEN)
        args, kwargs = lavalink_start[0]
        assert not any(FAKE_TOKEN in a for a in args)
        assert FAKE_TOKEN not in repr({k: v for k, v in kwargs.items() if k != "env"})

    def test_each_start_reads_the_environment_of_that_moment(self, lavalink_start, monkeypatch):
        ll.run_lavalink()
        monkeypatch.setenv("SERVER_PORT", "9999")
        ll.run_lavalink()
        assert lavalink_start[0][1]["env"]["SERVER_PORT"] == "8123"
        assert lavalink_start[1][1]["env"]["SERVER_PORT"] == "9999"

    def test_nothing_about_the_environment_is_printed_or_logged_on_start(self, lavalink_start, capsys, caplog):
        caplog.set_level(logging.NOTSET)
        ll.run_lavalink(youtube_oauth_refresh_token=FAKE_TOKEN)
        out = capsys.readouterr()
        text = out.out + out.err + "\n".join(f"{r.getMessage()} {r.args!r}" for r in caplog.records)
        if FAKE_TOKEN in text or any(value in text for value in SECRET_SENTINELS.values()):
            fail("o início do Lavalink escreveu ambiente/token em stdout, stderr ou log")

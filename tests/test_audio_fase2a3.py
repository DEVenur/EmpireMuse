"""Fase 2, defeito de atualização achado no reinício real — LAVALINK_FILE_URL antiga/fixa no .env não pode quebrar o bot.

Contrato: BRIEFING-FASE2.md ("Defeito de atualização achado no reinício real"). Interpretações: .qa-fase2a3-interp.txt.
Sem rede, sem Java e sem produção: `requests.get` é um dublê que só atende URLs previstas; tudo roda em tmp_path.

Comportamento exigido de ``prepare_lavalink_files``/``run_lavalink`` (a API não muda):
  - URL vazia/None/só espaços  -> URL oficial ATUAL do branding, hash oficial, sem exigir LAVALINK_FILE_SHA256, sem aviso;
  - URL oficial de versão anterior do espelho (EmpireMuse-LL-binaries 0.0.1/0.0.2/0.0.3 e o nome antigo LL-binaries
    0.0.1/0.0.2) -> baixa da URL oficial ATUAL com o hash oficial ATUAL (ignora o hash configurado) e registra UMA linha de
    aviso (logging.WARNING) sugerindo esvaziar a variável;
  - qualquer outra URL -> segue exigindo HTTPS + LAVALINK_FILE_SHA256, e é baixada exatamente como foi informada.
"""
import hashlib
import re
from pathlib import Path

import pytest

from utils import branding
from utils.music import local_lavalink as ll

ROOT = Path(__file__).resolve().parent.parent

NEW_REPO = "https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download"
OLD_REPO = "https://github.com/DiscordEmpireHub/LL-binaries/releases/download"
UPSTREAM_REPO = "https://github.com/zRitsu/LL-binaries/releases/download"

JAR = b"JAR-OFICIAL-ATUAL"
YML = b"yml atual\n"
PLUGINS = {name: f"plugin {name}".encode() for name in
           ("youtube-plugin-2be8e542d3f6f178e048dca565892684c2e40177.jar", "lavasrc-plugin-4.8.3.jar", "lavalink-2.6.1.jar")}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ============================================================================ (1) .example.env

def _example_env_text() -> str:
    return (ROOT / ".example.env").read_text(encoding="utf-8")


class TestExampleEnv:
    def test_has_exactly_one_active_line_and_it_is_empty(self):
        lines = [l for l in _example_env_text().splitlines() if l.startswith("LAVALINK_FILE_URL=")]
        assert len(lines) == 1, f"deve haver uma linha LAVALINK_FILE_URL= ativa (achou {len(lines)})"
        assert lines[0].split("=", 1)[1].strip().strip("'\"") == ""

    def test_no_active_line_pins_an_official_release_url(self):
        pinned = [l for l in _example_env_text().splitlines()
                  if not l.lstrip().startswith("#") and "LL-binaries/releases/download/" in l]
        assert pinned == [], f"o exemplo não pode fixar versão do espelho: {pinned}"

    def test_the_comment_explains_empty_means_official_and_when_to_fill_it(self):
        lines = _example_env_text().splitlines()
        index = next(i for i, l in enumerate(lines) if l.startswith("LAVALINK_FILE_URL="))
        comment = []
        for line in reversed(lines[:index]):
            if not line.lstrip().startswith("#"):
                break
            comment.append(line)
        text = "\n".join(reversed(comment)).lower()
        assert text, "LAVALINK_FILE_URL precisa de comentário explicativo logo acima"
        assert "vazi" in text, "deve dizer que vazio é o padrão"
        assert "oficial" in text, "deve dizer que vazio = espelho oficial"
        assert "LAVALINK_FILE_SHA256".lower() in text, "deve citar o hash obrigatório para jar próprio"
        assert "https" in text, "deve citar HTTPS para jar próprio"

    def test_default_config_still_resolves_to_the_current_official_url(self):
        import config_loader
        assert config_loader.DEFAULT_CONFIG["LAVALINK_FILE_URL"] in ("", branding.LAVALINK_JAR_URL)


# ============================================================================ fixtures (rede e processo falsos)

class FakeResponse:
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


class Net:
    """Atende só as URLs registradas em ``served``; qualquer outra é uma requisição inesperada (falha o teste)."""

    def __init__(self):
        self.served, self.calls = {}, []

    def get(self, url, *args, **kwargs):
        self.calls.append(url)
        assert url in self.served, f"requisição inesperada: {url}"
        return FakeResponse(self.served[url])


@pytest.fixture
def net(monkeypatch, tmp_path):
    """Só o Lavalink.jar falta em tmp_path: yml e plugins já estão presentes e verificados (hashes substituídos por dublês)."""
    fake = Net()
    fake.served[branding.LAVALINK_JAR_URL] = JAR
    monkeypatch.setattr(ll.requests, "get", fake.get)
    monkeypatch.setattr(branding, "LAVALINK_JAR_SHA256", sha(JAR))
    monkeypatch.setattr(branding, "LAVALINK_APPLICATION_YML_SHA256", sha(YML))
    monkeypatch.setattr(branding, "LAVALINK_PLUGIN_SHA256", {n: sha(d) for n, d in PLUGINS.items()})
    (tmp_path / "application.yml").write_bytes(YML)
    (tmp_path / "plugins").mkdir()
    for name, data in PLUGINS.items():
        (tmp_path / "plugins" / name).write_bytes(data)
    return fake


@pytest.fixture
def popen(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: cmd)
    monkeypatch.setattr(ll.platform, "architecture", lambda *a, **k: ("64bit", "ELF"))
    started = []
    monkeypatch.setattr(ll.subprocess, "Popen", lambda args, **kw: started.append(list(args)))
    return started


def prepare(tmp_path, url, sha256=None):
    ll.prepare_lavalink_files(tmp_path, lavalink_file_url=url, lavalink_file_sha256=sha256)


def warnings_of(caplog):
    return [r for r in caplog.records if r.name == ll.logger.name and r.levelno == 30]


def jar_of(tmp_path):
    path = tmp_path / "Lavalink.jar"
    return path.read_bytes() if path.exists() else None


# ============================================================================ (2) vazio/espaços = oficial atual

EMPTY_VALUES = [None, "", " ", "   ", "\t", "\n", " \t\n "]


class TestEmptyUrlMeansCurrentOfficial:
    @pytest.mark.parametrize("url", EMPTY_VALUES)
    def test_downloads_the_current_official_jar_without_any_configured_hash(self, net, tmp_path, url):
        prepare(tmp_path, url)
        assert jar_of(tmp_path) == JAR
        assert net.calls == [branding.LAVALINK_JAR_URL]

    @pytest.mark.parametrize("url", EMPTY_VALUES)
    def test_no_warning_is_logged(self, net, tmp_path, caplog, url):
        caplog.set_level(0)
        prepare(tmp_path, url)
        assert warnings_of(caplog) == []

    @pytest.mark.parametrize("url", ["", "   "])
    def test_a_stale_configured_hash_is_ignored_for_the_official_jar(self, net, tmp_path, url):
        prepare(tmp_path, url, sha("hash antigo de outro jar".encode()))
        assert jar_of(tmp_path) == JAR

    @pytest.mark.parametrize("url", ["", "   ", None])
    def test_run_lavalink_starts_the_process(self, net, popen, tmp_path, url):
        ll.run_lavalink(lavalink_file_url=url)
        assert len(popen) == 1 and popen[0][-2:] == ["-jar", "Lavalink.jar"]
        assert jar_of(tmp_path) == JAR

    def test_exact_current_official_url_still_works_without_warning(self, net, tmp_path, caplog):
        caplog.set_level(0)
        prepare(tmp_path, branding.LAVALINK_JAR_URL)
        assert jar_of(tmp_path) == JAR and warnings_of(caplog) == []


# ============================================================================ (3) URLs oficiais antigas = oficial atual

ALL_KNOWN_OFFICIAL_URLS = [
    f"{NEW_REPO}/0.0.1/Lavalink.jar",
    f"{NEW_REPO}/0.0.2/Lavalink.jar",
    f"{NEW_REPO}/0.0.3/Lavalink.jar",
    f"{OLD_REPO}/0.0.1/Lavalink.jar",
    f"{OLD_REPO}/0.0.2/Lavalink.jar",
]
# "Antiga" = oficial e DIFERENTE da atual (hoje a 0.0.3 é a atual: fixá-la no .env não é versão antiga, não avisa).
# Calculado contra o branding real, então continua válido quando a atual passar a ser a 0.0.4.
LEGACY_OFFICIAL_URLS = [u for u in ALL_KNOWN_OFFICIAL_URLS if u != branding.LAVALINK_JAR_URL]
PINNED_CURRENT_URLS = [u for u in ALL_KNOWN_OFFICIAL_URLS if u == branding.LAVALINK_JAR_URL]


class TestLegacyOfficialUrlsFollowTheCurrentRelease:
    @pytest.mark.parametrize("url", PINNED_CURRENT_URLS)
    def test_pinning_the_current_release_url_works_and_does_not_warn(self, net, tmp_path, caplog, url):
        caplog.set_level(0)
        prepare(tmp_path, url)
        assert jar_of(tmp_path) == JAR and net.calls == [branding.LAVALINK_JAR_URL] and warnings_of(caplog) == []

    def test_the_known_list_covers_the_current_release_and_at_least_one_older_one(self):
        assert PINNED_CURRENT_URLS and LEGACY_OFFICIAL_URLS

    @pytest.mark.parametrize("url", LEGACY_OFFICIAL_URLS)
    def test_downloads_from_the_current_official_url_with_the_current_hash(self, net, tmp_path, url):
        prepare(tmp_path, url)
        assert jar_of(tmp_path) == JAR
        assert net.calls == [branding.LAVALINK_JAR_URL], "nunca baixa da URL antiga: usa a atual"

    @pytest.mark.parametrize("url", LEGACY_OFFICIAL_URLS)
    def test_logs_exactly_one_single_line_warning_suggesting_to_empty_the_variable(self, net, tmp_path, caplog, url):
        caplog.set_level(0)
        prepare(tmp_path, url)
        found = warnings_of(caplog)
        assert len(found) == 1, f"esperava 1 aviso, houve {len(found)}"
        message = found[0].getMessage()
        assert "\n" not in message.strip(), "o aviso deve ser de uma linha"
        assert "LAVALINK_FILE_URL" in message
        assert re.search(r"vazi|esvazi", message.lower()), "o aviso deve sugerir esvaziar a variável"

    @pytest.mark.parametrize("url", LEGACY_OFFICIAL_URLS)
    def test_a_configured_hash_does_not_override_the_official_one(self, net, tmp_path, url):
        prepare(tmp_path, url, sha("hash antigo de outro jar".encode()))
        assert jar_of(tmp_path) == JAR

    @pytest.mark.parametrize("url", LEGACY_OFFICIAL_URLS)
    def test_surrounding_whitespace_is_ignored(self, net, tmp_path, url):
        prepare(tmp_path, f"  {url}\n")
        assert jar_of(tmp_path) == JAR and net.calls == [branding.LAVALINK_JAR_URL]

    @pytest.mark.parametrize("url", LEGACY_OFFICIAL_URLS)
    def test_run_lavalink_starts_after_updating_the_jar(self, net, popen, tmp_path, url):
        ll.run_lavalink(lavalink_file_url=url)
        assert len(popen) == 1 and jar_of(tmp_path) == JAR

    @pytest.mark.parametrize("url", LEGACY_OFFICIAL_URLS)
    def test_an_old_jar_on_disk_is_replaced_by_the_current_one(self, net, tmp_path, url):
        (tmp_path / "Lavalink.jar").write_bytes(b"jar da versao antiga")
        prepare(tmp_path, url)
        assert jar_of(tmp_path) == JAR

    @pytest.mark.parametrize("url", LEGACY_OFFICIAL_URLS)
    def test_integrity_is_still_enforced_with_the_official_hash(self, net, tmp_path, popen, url):
        net.served[branding.LAVALINK_JAR_URL] = b"conteudo adulterado"
        with pytest.raises(ll.IntegrityError):
            ll.run_lavalink(lavalink_file_url=url)
        assert jar_of(tmp_path) is None and popen == [], "jar adulterado nunca fica no destino nem inicia o processo"


# ============================================================================ (4) outras URLs seguem estritas

NEED_HASH_URLS = [
    "https://example.test/Lavalink.jar",
    f"{UPSTREAM_REPO}/0.0.2/Lavalink.jar",                                                   # upstream zRitsu
    "https://github.com.evil.test/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download/0.0.2/Lavalink.jar",
    "https://evil.test/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download/0.0.2/Lavalink.jar",
    "https://github.com@evil.test/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download/0.0.2/Lavalink.jar",
    "https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries-fork/releases/download/0.0.2/Lavalink.jar",
    "https://github.com/OutraOrg/EmpireMuse-LL-binaries/releases/download/0.0.2/Lavalink.jar",
    f"{NEW_REPO}/0.0.2/application.yml",                                                     # outro arquivo do espelho
    f"{NEW_REPO}/0.0.2/Lavalink.jar?arquivo=outro",                                          # parâmetros mudam a URL
    f"{NEW_REPO}/0.0.2/Lavalink.jar.exe",
]


class TestEveryOtherUrlStaysStrict:
    @pytest.mark.parametrize("url", NEED_HASH_URLS)
    def test_without_a_hash_it_is_refused_before_any_request(self, net, tmp_path, url):
        with pytest.raises(ll.LavalinkDownloadError):
            prepare(tmp_path, url)
        assert net.calls == [] and jar_of(tmp_path) is None

    @pytest.mark.parametrize("url", NEED_HASH_URLS)
    def test_without_a_hash_the_process_never_starts(self, net, popen, url):
        with pytest.raises(ll.LavalinkDownloadError):
            ll.run_lavalink(lavalink_file_url=url)
        assert popen == []

    @pytest.mark.parametrize("url", NEED_HASH_URLS)
    def test_with_a_hash_it_is_downloaded_from_exactly_that_url_never_rewritten(self, net, tmp_path, url):
        net.served[url] = b"JAR-PROPRIO"
        prepare(tmp_path, url, sha(b"JAR-PROPRIO"))
        assert net.calls == [url], "URL não oficial não pode ser trocada pela oficial"
        assert jar_of(tmp_path) == b"JAR-PROPRIO"

    @pytest.mark.parametrize("url", NEED_HASH_URLS)
    def test_with_a_wrong_hash_it_is_refused_after_download_and_discarded(self, net, tmp_path, url):
        net.served[url] = b"JAR-PROPRIO"
        with pytest.raises(ll.IntegrityError):
            prepare(tmp_path, url, sha(b"outro conteudo"))
        assert jar_of(tmp_path) is None

    @pytest.mark.parametrize("url", NEED_HASH_URLS)
    def test_no_legacy_warning_is_logged_for_them(self, net, tmp_path, caplog, url):
        caplog.set_level(0)
        net.served[url] = b"JAR-PROPRIO"
        prepare(tmp_path, url, sha(b"JAR-PROPRIO"))
        assert [r for r in warnings_of(caplog) if "LAVALINK_FILE_URL" in r.getMessage()] == []

    @pytest.mark.parametrize("url", [
        "http://example.test/Lavalink.jar",
        f"http://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download/0.0.2/Lavalink.jar",   # oficial, mas HTTP
        f"http://github.com/DiscordEmpireHub/LL-binaries/releases/download/0.0.1/Lavalink.jar",
        "ftp://example.test/Lavalink.jar",
        "file:///etc/passwd",
        "example.test/Lavalink.jar",
    ])
    @pytest.mark.parametrize("hash_value", [None, "valido"])
    def test_non_https_is_refused_even_with_a_hash_and_even_when_it_looks_official(self, net, tmp_path, url, hash_value):
        configured = sha(JAR) if hash_value else None
        with pytest.raises(ll.LavalinkDownloadError) as info:
            prepare(tmp_path, url, configured)
        assert net.calls == [] and jar_of(tmp_path) is None
        assert "HTTPS" in str(info.value)

    def test_custom_https_url_with_hash_is_still_accepted(self, net, tmp_path):
        net.served["https://example.test/meu/Lavalink.jar"] = JAR
        prepare(tmp_path, "https://example.test/meu/Lavalink.jar", sha(JAR))
        assert jar_of(tmp_path) == JAR

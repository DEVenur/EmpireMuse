"""Fase 2, defeito de atualização achado no reinício real — LAVALINK_FILE_URL antiga/fixa no .env não pode quebrar o bot.

Contrato: BRIEFING-FASE2.md ("Defeito de atualização achado no reinício real"). Interpretações: .qa-fase2a3-interp.txt.
Sem rede, sem Java e sem produção: `requests.get` é um dublê que só atende URLs previstas; tudo roda em tmp_path.

Comportamento exigido de ``prepare_lavalink_files``/``run_lavalink`` (a API não muda):
  - URL vazia/None/só espaços  -> URL oficial ATUAL do branding, hash oficial, sem exigir LAVALINK_FILE_SHA256, sem aviso;
  - URL oficial de versão anterior do espelho (EmpireMuse-LL-binaries 0.0.1/0.0.2/0.0.3/0.0.4 e o nome antigo LL-binaries
    0.0.1/0.0.2) -> baixa da URL oficial ATUAL com o hash oficial ATUAL (ignora o hash configurado) e registra UMA linha de
    aviso (logging.WARNING) sugerindo esvaziar a variável;
  - qualquer outra URL -> segue exigindo HTTPS + LAVALINK_FILE_SHA256, e é baixada exatamente como foi informada.
"""

import hashlib

import pytest

from empiremuse.utils import branding
from empiremuse.utils.music import local_lavalink as ll

NEW_REPO = "https://github.com/EmpireCommunity/EmpireMuse-LL-binaries/releases/download"
OLD_EMPIREMUSE_REPO = "https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download"
OLD_REPO = "https://github.com/DiscordEmpireHub/LL-binaries/releases/download"
UPSTREAM_REPO = "https://github.com/zRitsu/LL-binaries/releases/download"

JAR = b"JAR-OFICIAL-ATUAL"
YML = b"yml atual\n"
PLUGINS = {
    name: f"plugin {name}".encode()
    for name in (
        "youtube-plugin-2be8e542d3f6f178e048dca565892684c2e40177.jar",
        "lavasrc-plugin-4.8.3.jar",
        "lavalink-2.6.1.jar",
    )
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    monkeypatch.setattr(ll, "java_major_version", lambda cmd, debug=False: 25)
    monkeypatch.setattr(ll.platform, "architecture", lambda *a, **k: ("64bit", "ELF"))
    started = []
    monkeypatch.setattr(ll.subprocess, "Popen", lambda args, **kw: started.append(list(args)))
    return started


def prepare(tmp_path, url, sha256=None):
    ll.prepare_lavalink_files(tmp_path, lavalink_file_url=url, lavalink_file_sha256=sha256)


def jar_of(tmp_path):
    path = tmp_path / "Lavalink.jar"
    return path.read_bytes() if path.exists() else None


# ============================================================================ (3) URLs oficiais antigas = oficial atual

ALL_KNOWN_OFFICIAL_URLS = [
    f"{NEW_REPO}/0.0.1/Lavalink.jar",
    f"{NEW_REPO}/0.0.2/Lavalink.jar",
    f"{NEW_REPO}/0.0.3/Lavalink.jar",
    f"{NEW_REPO}/0.0.4/Lavalink.jar",
    f"{OLD_EMPIREMUSE_REPO}/0.0.1/Lavalink.jar",
    f"{OLD_EMPIREMUSE_REPO}/0.0.2/Lavalink.jar",
    f"{OLD_EMPIREMUSE_REPO}/0.0.3/Lavalink.jar",
    f"{OLD_REPO}/0.0.1/Lavalink.jar",
    f"{OLD_REPO}/0.0.2/Lavalink.jar",
]
# "Antiga" = oficial e DIFERENTE da atual (hoje a 0.0.4 é a atual: fixá-la no .env não é versão antiga, não avisa).
# Calculado contra o branding real, então continua válido quando a atual passar a ser a próxima.
LEGACY_OFFICIAL_URLS = [u for u in ALL_KNOWN_OFFICIAL_URLS if u != branding.LAVALINK_JAR_URL]


class TestLegacyOfficialUrlsFollowTheCurrentRelease:
    @pytest.mark.parametrize("url", list(LEGACY_OFFICIAL_URLS)[:2])
    def test_run_lavalink_starts_after_updating_the_jar(self, net, popen, tmp_path, url):
        ll.run_lavalink(lavalink_file_url=url)
        assert len(popen) == 1 and jar_of(tmp_path) == JAR


# ============================================================================ (4) outras URLs seguem estritas

NEED_HASH_URLS = [
    "https://example.test/Lavalink.jar",
    f"{UPSTREAM_REPO}/0.0.2/Lavalink.jar",  # upstream zRitsu
    "https://github.com.evil.test/EmpireCommunity/EmpireMuse-LL-binaries/releases/download/0.0.2/Lavalink.jar",
    "https://evil.test/EmpireCommunity/EmpireMuse-LL-binaries/releases/download/0.0.2/Lavalink.jar",
    "https://github.com@evil.test/EmpireCommunity/EmpireMuse-LL-binaries/releases/download/0.0.2/Lavalink.jar",
    "https://github.com/EmpireCommunity/EmpireMuse-LL-binaries-fork/releases/download/0.0.2/Lavalink.jar",
    "https://github.com/OutraOrg/EmpireMuse-LL-binaries/releases/download/0.0.2/Lavalink.jar",
    f"{NEW_REPO}/0.0.2/application.yml",  # outro arquivo do espelho
    f"{NEW_REPO}/0.0.2/Lavalink.jar?arquivo=outro",  # parâmetros mudam a URL
    f"{NEW_REPO}/0.0.2/Lavalink.jar.exe",
]


class TestEveryOtherUrlStaysStrict:
    @pytest.mark.parametrize("url", list(NEED_HASH_URLS)[:2])
    def test_with_a_wrong_hash_it_is_refused_after_download_and_discarded(self, net, tmp_path, url):
        net.served[url] = b"JAR-PROPRIO"
        with pytest.raises(ll.IntegrityError):
            prepare(tmp_path, url, sha(b"outro conteudo"))
        assert jar_of(tmp_path) is None

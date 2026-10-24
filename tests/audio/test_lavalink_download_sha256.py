"""Fase 2, Trilha A, item 3 — utils/music/local_lavalink.py baixa e VERIFICA (SHA-256) o jar, o application.yml e os 3 plugins.

Contrato: BRIEFING-FASE2.md ("Trilha A — contrato do item 3", "Item 3 ampliado", "Release publicada"). Interpretações:
.qa-fase2a-interp.txt. Nenhum teste usa rede real: `requests.get` é um dublê e tudo roda em tmp_path.

API exigida do Backend (nomes fixados pelos testes):
  utils/branding.py   LAVALINK_JAR_SHA256, LAVALINK_APPLICATION_YML_SHA256, LAVALINK_APPLICATION_YML_KNOWN_SHA256 (frozenset
                      com os hashes oficiais conhecidos, incluindo o da 0.0.1), LAVALINK_PLUGIN_SHA256 (nome canônico -> SHA-256;
                      a URL é LAVALINK_BINARIES_URL + "/" + nome). Lidos em tempo de chamada (os testes os substituem).
  local_lavalink.py   LavalinkDownloadError (base) e IntegrityError (subclasse);
                      download_verified(url, filename, sha256, timeout=...);
                      prepare_lavalink_files(directory=".", *, lavalink_file_url=None, lavalink_file_sha256=None);
                      run_lavalink(..., lavalink_file_sha256=None) chama prepare_lavalink_files no diretório atual.
"""

import hashlib
from pathlib import Path

import pytest

from empiremuse.utils import branding
from empiremuse.utils.music import local_lavalink as ll

pytestmark = pytest.mark.critical

JAR = b"JAR-OFICIAL"
YML = b"lavalink: novo\n"
OLD_YML = b"lavalink: antigo\n"
PLUGINS = {
    "youtube-plugin-2be8e542d3f6f178e048dca565892684c2e40177.jar": b"PLUGIN-YT",
    "lavasrc-plugin-4.8.3.jar": b"PLUGIN-LAVASRC",
    "lavalink-2.6.1.jar": b"PLUGIN-LETRAS",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeResponse:
    def __init__(self, data, path_check=None, fail_midway=False):
        self.data, self.path_check, self.fail_midway = data, path_check, fail_midway
        self.headers = {"content-length": str(len(data))}
        self.status_code = 200

    def iter_content(self, chunk_size=1):
        half = max(len(self.data) // 2, 1)
        yield self.data[:half]
        if self.path_check:
            self.path_check()
        if self.fail_midway:
            import requests

            raise requests.ConnectionError("queda no meio do download")
        yield self.data[half:]

    def raise_for_status(self):
        return None

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeNet:
    """Serve bytes por nome de arquivo (último segmento da URL); URL desconhecida = rede inesperada."""

    def __init__(self, files):
        self.files, self.calls = dict(files), []
        self.fail_midway = False
        self.path_check = None

    def get(self, url, *args, **kwargs):
        self.calls.append((url, kwargs))
        name = url.rsplit("/", 1)[-1]
        assert name in self.files, f"requisição inesperada: {url}"
        return FakeResponse(self.files[name], self.path_check, self.fail_midway)

    def names(self):
        return [url.rsplit("/", 1)[-1] for url, _ in self.calls]


@pytest.fixture
def net(monkeypatch):
    fake = FakeNet({"Lavalink.jar": JAR, "application.yml": YML, **PLUGINS})
    monkeypatch.setattr(ll.requests, "get", fake.get)
    monkeypatch.setattr(branding, "LAVALINK_JAR_SHA256", sha(JAR), raising=False)
    monkeypatch.setattr(branding, "LAVALINK_APPLICATION_YML_SHA256", sha(YML), raising=False)
    monkeypatch.setattr(branding, "LAVALINK_APPLICATION_YML_KNOWN_SHA256", frozenset({sha(OLD_YML)}), raising=False)
    monkeypatch.setattr(branding, "LAVALINK_PLUGIN_SHA256", {n: sha(d) for n, d in PLUGINS.items()}, raising=False)
    return fake


def tree(base: Path):
    return sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())


def plugin_dir(base: Path) -> Path:
    return base / "plugins"


# ============================================================================ download_verified


class TestDownloadVerified:
    def test_good_hash_moves_the_file_into_place_atomically_without_leftovers(self, net, tmp_path):
        dest = tmp_path / "Lavalink.jar"
        seen = []
        net.path_check = lambda: seen.append(dest.exists())
        ll.download_verified("https://example.test/Lavalink.jar", str(dest), sha(JAR))
        assert dest.read_bytes() == JAR
        assert seen == [False], "o destino só pode existir depois da verificação (arquivo temporário antes)"
        assert tree(tmp_path) == ["Lavalink.jar"], "nenhum .tmp sobra"

    def test_every_request_has_a_timeout(self, net, tmp_path):
        ll.download_verified("https://example.test/Lavalink.jar", str(tmp_path / "Lavalink.jar"), sha(JAR))
        ((_, kwargs),) = net.calls
        assert kwargs.get("timeout"), "requests.get sem timeout trava o boot do bot"

    def test_legacy_download_file_for_the_jdk_also_has_a_timeout(self, net, tmp_path):
        net.files["java.zip"] = b"JDK"
        assert ll.download_file("https://example.test/java.zip", str(tmp_path / "java.zip")) is True
        ((_, kwargs),) = net.calls
        assert kwargs.get("timeout")


# ============================================================================ prepare_lavalink_files


class TestIntegrityAborts:
    @pytest.mark.parametrize(
        "attr, name",
        [
            ("LAVALINK_JAR_SHA256", "Lavalink.jar"),
            ("LAVALINK_APPLICATION_YML_SHA256", "application.yml"),
        ],
    )
    def test_wrong_jar_or_yml_hash_aborts_and_leaves_no_file_of_it(self, net, tmp_path, monkeypatch, attr, name):
        monkeypatch.setattr(branding, attr, sha(b"errado"))
        with pytest.raises(ll.IntegrityError):
            ll.prepare_lavalink_files(tmp_path)
        assert not (tmp_path / name).exists()
        assert not [p for p in tree(tmp_path) if p.endswith(".tmp")]


class TestExistingApplicationYml:
    def test_current_official_yml_is_kept_without_download(self, net, tmp_path):
        (tmp_path / "application.yml").write_bytes(YML)
        ll.prepare_lavalink_files(tmp_path)
        assert "application.yml" not in net.names()
        assert (tmp_path / "application.yml").read_bytes() == YML

    def test_customized_yml_is_kept_with_a_log_warning(self, net, tmp_path, capsys, caplog):
        custom = b"server:\n  port: 2333\n# personalizado pelo dono\n"
        (tmp_path / "application.yml").write_bytes(custom)
        with caplog.at_level("DEBUG"):
            ll.prepare_lavalink_files(tmp_path)
        assert (tmp_path / "application.yml").read_bytes() == custom, "configuração do dono nunca é sobrescrita"
        assert "application.yml" not in net.names()
        out = capsys.readouterr()
        text = (out.out + out.err + caplog.text).lower()
        assert "application.yml" in text and "personaliz" in text, "aviso no log: arquivo personalizado mantido"


class TestPlugins:
    def test_stale_plugin_versions_are_removed_when_the_jar_is_refreshed_but_canonical_ones_stay(self, net, tmp_path):
        folder = plugin_dir(tmp_path)
        folder.mkdir()
        (folder / "youtube-plugin-1.0.0.jar").write_bytes(b"velho")
        (tmp_path / "Lavalink.jar").write_bytes(b"jar antigo")
        ll.prepare_lavalink_files(tmp_path)
        assert not (folder / "youtube-plugin-1.0.0.jar").exists(), "jar de plugin fora da lista oficial não é carregado"
        assert sorted(p.name for p in folder.iterdir()) == sorted(PLUGINS)


class TestUserOverriddenUrl:
    URL = "https://example.test/meu/Lavalink.jar"

    def test_custom_url_without_a_hash_aborts_before_any_request(self, net, tmp_path):
        with pytest.raises(ll.LavalinkDownloadError) as info:
            ll.prepare_lavalink_files(tmp_path, lavalink_file_url=self.URL)
        assert net.calls == [] and not (tmp_path / "Lavalink.jar").exists()
        assert "SHA256" in str(info.value) or "SHA-256" in str(info.value)


# ============================================================================ run_lavalink (ponta a ponta, sem Java)


@pytest.fixture
def run(monkeypatch, tmp_path, net):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: cmd)
    monkeypatch.setattr(ll.platform, "architecture", lambda *a, **k: ("64bit", "ELF"))  # platform usa subprocess
    started = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            started.append(args)

    monkeypatch.setattr(ll.subprocess, "Popen", FakePopen)
    return started


class TestRunLavalink:
    def test_integrity_failure_never_starts_the_process(self, run, monkeypatch):
        monkeypatch.setattr(branding, "LAVALINK_JAR_SHA256", sha(b"errado"))
        with pytest.raises(ll.IntegrityError):
            ll.run_lavalink(lavalink_file_url=branding.LAVALINK_JAR_URL)
        assert run == []


# ============================================================================ pedidos do MAESTRO pós-aprovação (observações 1 e 2)


class TestRunLavalinkSignature:
    def test_sha256_is_keyword_only_and_after_all_positional_parameters(self):
        # Fase 2 A2: youtube_oauth_refresh_token também é keyword-only e entra depois; o sha256 deixa de ser o último.
        import inspect

        params = list(inspect.signature(ll.run_lavalink).parameters.values())
        sha_param = next(p for p in params if p.name == "lavalink_file_sha256")
        assert sha_param.kind is inspect.Parameter.KEYWORD_ONLY
        assert sha_param.default in (None, "")
        assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params[params.index(sha_param) :])


class TestOnlyHttpsForUserUrl:
    def test_run_lavalink_refuses_http_and_never_starts_the_process(self, run):
        with pytest.raises(ll.LavalinkDownloadError):
            ll.run_lavalink(lavalink_file_url="http://example.test/Lavalink.jar", lavalink_file_sha256=sha(JAR))
        assert run == []

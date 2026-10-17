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
import re
from pathlib import Path

import pytest

from utils import branding
from utils.music import local_lavalink as ll

ROOT = Path(__file__).resolve().parent.parent
OLD_YML_SHA256 = "f93ce9789fb637dc20bd886857a4ed813ad80870b43d268bc0ce80c11f90bfc3"  # application.yml da release 0.0.1

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


# ============================================================================ constantes reais (release 0.0.2)


class TestOfficialConstants:
    def test_known_yml_hashes_include_the_001_release(self):
        assert OLD_YML_SHA256 in branding.LAVALINK_APPLICATION_YML_KNOWN_SHA256, (
            "o application.yml da 0.0.1 é uma versão oficial conhecida (pode ser substituído)"
        )

    def test_plugin_table_has_exactly_the_three_canonical_names(self):
        assert set(branding.LAVALINK_PLUGIN_SHA256) == set(PLUGINS)
        for value in branding.LAVALINK_PLUGIN_SHA256.values():
            assert re.fullmatch(r"[0-9a-f]{64}", value)


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

    def test_wrong_hash_deletes_everything_and_aborts_with_a_clear_error(self, net, tmp_path):
        dest = tmp_path / "Lavalink.jar"
        with pytest.raises(ll.IntegrityError) as info:
            ll.download_verified("https://example.test/Lavalink.jar", str(dest), sha(b"outro conteudo"))
        assert not dest.exists() and tree(tmp_path) == []
        assert "SHA-256" in str(info.value) and "Lavalink.jar" in str(info.value)

    def test_hash_comparison_is_case_insensitive(self, net, tmp_path):
        dest = tmp_path / "Lavalink.jar"
        ll.download_verified("https://example.test/Lavalink.jar", str(dest), sha(JAR).upper())
        assert dest.read_bytes() == JAR

    def test_connection_dropping_midway_leaves_no_destination_and_no_temp_file(self, net, tmp_path):
        net.fail_midway = True
        dest = tmp_path / "Lavalink.jar"
        with pytest.raises(Exception):
            ll.download_verified("https://example.test/Lavalink.jar", str(dest), sha(JAR))
        assert tree(tmp_path) == []

    def test_final_move_is_os_replace_from_the_temp_file(self, net, tmp_path, monkeypatch):
        moves = []
        real = ll.os.replace
        monkeypatch.setattr(ll.os, "replace", lambda src, dst: (moves.append((str(src), str(dst))), real(src, dst))[1])
        dest = tmp_path / "Lavalink.jar"
        ll.download_verified("https://example.test/Lavalink.jar", str(dest), sha(JAR))
        ((src, dst),) = moves
        assert dst == str(dest) and src != dst and src.startswith(str(dest)), (
            "mover o temporário vizinho do destino (atômico)"
        )

    def test_http_error_and_dropped_connection_become_a_clear_download_error(self, net, tmp_path, monkeypatch):
        import requests

        class Http404(FakeResponse):
            def raise_for_status(self):
                raise requests.HTTPError("404 Not Found")

        monkeypatch.setattr(ll.requests, "get", lambda url, *a, **k: Http404(b"<html>404</html>"))
        with pytest.raises(ll.LavalinkDownloadError):
            ll.download_verified("https://example.test/Lavalink.jar", str(tmp_path / "Lavalink.jar"), sha(JAR))
        assert tree(tmp_path) == []
        net2 = FakeNet({"Lavalink.jar": JAR})
        net2.fail_midway = True
        monkeypatch.setattr(ll.requests, "get", net2.get)
        with pytest.raises(ll.LavalinkDownloadError) as info:
            ll.download_verified("https://example.test/Lavalink.jar", str(tmp_path / "Lavalink.jar"), sha(JAR))
        assert "queda no meio" not in str(info.value) and tree(tmp_path) == []

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


class TestFreshInstall:
    def test_downloads_jar_yml_and_the_three_plugins_with_canonical_names(self, net, tmp_path):
        ll.prepare_lavalink_files(tmp_path)
        assert (tmp_path / "Lavalink.jar").read_bytes() == JAR
        assert (tmp_path / "application.yml").read_bytes() == YML
        for name, data in PLUGINS.items():
            assert (plugin_dir(tmp_path) / name).read_bytes() == data
        assert not [p for p in tree(tmp_path) if p.endswith((".tmp", ".part"))]
        assert all(kwargs.get("timeout") for _, kwargs in net.calls)

    def test_downloads_use_the_official_urls(self, net, tmp_path):
        ll.prepare_lavalink_files(tmp_path)
        urls = {url for url, _ in net.calls}
        assert branding.LAVALINK_JAR_URL in urls and branding.LAVALINK_APPLICATION_YML_URL in urls
        for name in PLUGINS:
            assert f"{branding.LAVALINK_BINARIES_URL}/{name}" in urls

    def test_a_second_run_downloads_nothing(self, net, tmp_path):
        ll.prepare_lavalink_files(tmp_path)
        net.calls.clear()
        ll.prepare_lavalink_files(tmp_path)
        assert net.calls == []


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

    def test_wrong_plugin_hash_aborts_and_the_plugin_is_not_left_in_plugins(self, net, tmp_path, monkeypatch):
        bad = dict(branding.LAVALINK_PLUGIN_SHA256)
        bad["lavasrc-plugin-4.8.3.jar"] = sha(b"errado")
        monkeypatch.setattr(branding, "LAVALINK_PLUGIN_SHA256", bad)
        with pytest.raises(ll.IntegrityError):
            ll.prepare_lavalink_files(tmp_path)
        assert not (plugin_dir(tmp_path) / "lavasrc-plugin-4.8.3.jar").exists()
        assert not [p for p in tree(tmp_path) if p.endswith(".tmp")]


class TestExistingJar:
    def test_valid_existing_jar_is_not_downloaded_again(self, net, tmp_path):
        (tmp_path / "Lavalink.jar").write_bytes(JAR)
        ll.prepare_lavalink_files(tmp_path)
        assert "Lavalink.jar" not in net.names()

    def test_divergent_existing_jar_is_downloaded_again_and_replaced(self, net, tmp_path):
        (tmp_path / "Lavalink.jar").write_bytes(b"jar adulterado ou antigo")
        ll.prepare_lavalink_files(tmp_path)
        assert "Lavalink.jar" in net.names()
        assert (tmp_path / "Lavalink.jar").read_bytes() == JAR


class TestExistingApplicationYml:
    def test_missing_yml_is_downloaded(self, net, tmp_path):
        ll.prepare_lavalink_files(tmp_path)
        assert (tmp_path / "application.yml").read_bytes() == YML

    def test_known_official_old_yml_is_replaced(self, net, tmp_path):
        (tmp_path / "application.yml").write_bytes(OLD_YML)
        ll.prepare_lavalink_files(tmp_path)
        assert (tmp_path / "application.yml").read_bytes() == YML

    def test_current_official_yml_is_kept_without_download(self, net, tmp_path):
        (tmp_path / "application.yml").write_bytes(YML)
        ll.prepare_lavalink_files(tmp_path)
        assert "application.yml" not in net.names()
        assert (tmp_path / "application.yml").read_bytes() == YML

    def test_current_official_yml_is_not_downloaded_even_when_listed_as_known(self, net, tmp_path, monkeypatch):
        monkeypatch.setattr(branding, "LAVALINK_APPLICATION_YML_KNOWN_SHA256", frozenset({sha(OLD_YML), sha(YML)}))
        (tmp_path / "application.yml").write_bytes(YML)
        ll.prepare_lavalink_files(tmp_path)
        assert "application.yml" not in net.names()

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
    def test_valid_existing_plugins_are_not_downloaded_and_divergent_ones_are_replaced(self, net, tmp_path):
        folder = plugin_dir(tmp_path)
        folder.mkdir()
        (folder / "lavasrc-plugin-4.8.3.jar").write_bytes(PLUGINS["lavasrc-plugin-4.8.3.jar"])
        (folder / "lavalink-2.6.1.jar").write_bytes(b"adulterado")
        ll.prepare_lavalink_files(tmp_path)
        assert "lavasrc-plugin-4.8.3.jar" not in net.names()
        assert "lavalink-2.6.1.jar" in net.names()
        assert (folder / "lavalink-2.6.1.jar").read_bytes() == PLUGINS["lavalink-2.6.1.jar"]

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

    def test_custom_url_with_the_matching_hash_is_accepted(self, net, tmp_path):
        net.files["Lavalink.jar"] = b"JAR-PERSONALIZADO"
        ll.prepare_lavalink_files(tmp_path, lavalink_file_url=self.URL, lavalink_file_sha256=sha(b"JAR-PERSONALIZADO"))
        assert (tmp_path / "Lavalink.jar").read_bytes() == b"JAR-PERSONALIZADO"
        assert self.URL in [url for url, _ in net.calls]

    def test_custom_url_with_a_wrong_hash_aborts(self, net, tmp_path):
        with pytest.raises(ll.IntegrityError):
            ll.prepare_lavalink_files(tmp_path, lavalink_file_url=self.URL, lavalink_file_sha256=sha(b"outro"))
        assert not (tmp_path / "Lavalink.jar").exists()

    def test_official_url_needs_no_extra_hash(self, net, tmp_path):
        ll.prepare_lavalink_files(tmp_path, lavalink_file_url=branding.LAVALINK_JAR_URL)
        assert (tmp_path / "Lavalink.jar").read_bytes() == JAR


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
    def test_starts_only_after_everything_is_verified_and_plugins_are_kept(self, run, tmp_path):
        ll.run_lavalink(lavalink_file_url=branding.LAVALINK_JAR_URL)
        assert len(run) == 1 and "Lavalink.jar" in run[0]
        assert sorted(p.name for p in plugin_dir(tmp_path).iterdir()) == sorted(PLUGINS), (
            "a limpeza de plugins/ não pode apagar os plugins verificados"
        )

    def test_plugins_survive_when_the_jar_is_refreshed(self, run, tmp_path):
        ll.run_lavalink(lavalink_file_url=branding.LAVALINK_JAR_URL)
        (tmp_path / "Lavalink.jar").write_bytes(b"jar corrompido")
        ll.run_lavalink(lavalink_file_url=branding.LAVALINK_JAR_URL)
        assert (tmp_path / "Lavalink.jar").read_bytes() == JAR
        assert sorted(p.name for p in plugin_dir(tmp_path).iterdir()) == sorted(PLUGINS)

    def test_integrity_failure_never_starts_the_process(self, run, monkeypatch):
        monkeypatch.setattr(branding, "LAVALINK_JAR_SHA256", sha(b"errado"))
        with pytest.raises(ll.IntegrityError):
            ll.run_lavalink(lavalink_file_url=branding.LAVALINK_JAR_URL)
        assert run == []

    def test_custom_url_without_hash_never_starts_the_process(self, run):
        with pytest.raises(ll.LavalinkDownloadError):
            ll.run_lavalink(lavalink_file_url="https://example.test/x/Lavalink.jar")
        assert run == []

    def test_accepts_the_sha256_parameter(self, run, net, tmp_path):
        net.files["Lavalink.jar"] = b"JAR-PERSONALIZADO"
        ll.run_lavalink(
            lavalink_file_url="https://example.test/x/Lavalink.jar", lavalink_file_sha256=sha(b"JAR-PERSONALIZADO")
        )
        assert len(run) == 1 and (tmp_path / "Lavalink.jar").read_bytes() == b"JAR-PERSONALIZADO"


# ============================================================================ configuração


class TestConfig:
    def test_default_config_has_an_empty_file_sha256_and_example_env_documents_it(self):
        import config_loader

        assert config_loader.DEFAULT_CONFIG.get("LAVALINK_FILE_SHA256") == ""
        example = (ROOT / ".example.env").read_text(encoding="utf-8")
        assert re.search(r"^LAVALINK_FILE_SHA256=", example, re.MULTILINE)

    def test_client_passes_the_configured_sha256_to_run_lavalink(self):
        source = (ROOT / "utils" / "client.py").read_text(encoding="utf-8")
        assert "lavalink_file_sha256=self.config['LAVALINK_FILE_SHA256']" in source.replace('"', "'")


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

    def test_existing_positional_order_is_preserved(self):
        import inspect

        names = [p.name for p in inspect.signature(ll.run_lavalink).parameters.values()]
        assert names[:6] == [
            "lavalink_file_url",
            "lavalink_initial_ram",
            "lavalink_ram_limit",
            "lavalink_additional_sleep",
            "lavalink_cpu_cores",
            "use_jabba",
        ]

    def test_client_still_calls_by_keyword_with_the_sha256(self):
        source = (ROOT / "utils" / "client.py").read_text(encoding="utf-8")
        assert "lavalink_file_sha256=self.config['LAVALINK_FILE_SHA256']" in source.replace('"', "'")


class TestOnlyHttpsForUserUrl:
    @pytest.mark.parametrize(
        "url",
        ["http://example.test/Lavalink.jar", "HTTP://example.test/Lavalink.jar", "  http://example.test/Lavalink.jar"],
    )
    def test_http_url_is_refused_before_any_request_even_with_the_right_hash(self, net, tmp_path, url):
        with pytest.raises(ll.LavalinkDownloadError) as info:
            ll.prepare_lavalink_files(tmp_path, lavalink_file_url=url, lavalink_file_sha256=sha(JAR))
        assert net.calls == [] and tree(tmp_path) == []
        assert "HTTPS" in str(info.value)

    @pytest.mark.parametrize(
        "url", ["ftp://example.test/Lavalink.jar", "file:///etc/passwd", "example.test/Lavalink.jar"]
    )
    def test_other_schemes_are_refused_too(self, net, tmp_path, url):
        with pytest.raises(ll.LavalinkDownloadError):
            ll.prepare_lavalink_files(tmp_path, lavalink_file_url=url, lavalink_file_sha256=sha(JAR))
        assert net.calls == []

    def test_https_url_with_hash_is_still_accepted(self, net, tmp_path):
        ll.prepare_lavalink_files(
            tmp_path, lavalink_file_url="https://example.test/meu/Lavalink.jar", lavalink_file_sha256=sha(JAR)
        )
        assert (tmp_path / "Lavalink.jar").read_bytes() == JAR

    def test_run_lavalink_refuses_http_and_never_starts_the_process(self, run):
        with pytest.raises(ll.LavalinkDownloadError):
            ll.run_lavalink(lavalink_file_url="http://example.test/Lavalink.jar", lavalink_file_sha256=sha(JAR))
        assert run == []

    def test_http_is_refused_even_if_an_official_looking_jar_already_exists(self, net, tmp_path):
        (tmp_path / "Lavalink.jar").write_bytes(JAR)
        with pytest.raises(ll.LavalinkDownloadError):
            ll.prepare_lavalink_files(
                tmp_path, lavalink_file_url="http://example.test/Lavalink.jar", lavalink_file_sha256=sha(JAR)
            )

    def test_official_urls_are_https(self):
        assert branding.LAVALINK_JAR_URL.startswith("https://")
        assert branding.LAVALINK_APPLICATION_YML_URL.startswith("https://")
        assert branding.LAVALINK_BINARIES_URL.startswith("https://")

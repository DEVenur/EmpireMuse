"""Fase 2.1 (achados da validação) — M-1: instalação do JDK no Linux não deixa diretório aproveitável após falha;
B-1: membros '..'/absolutos no 1º componente são RECUSADOS.

Contrato sugerido ao Backend (os testes só observam o comportamento):
  - extrair para um diretório temporário IRMÃO (``.java/<plataforma>.tmp`` ou similar) e ``os.replace`` para o definitivo
    só no sucesso; no erro (inclusive ``BaseException``, como Ctrl+C) o temporário é apagado;
  - um diretório ``.java/<plataforma>`` já existente só é aceito se ``bin/java`` existir, for arquivo e executável;
    caso contrário a instalação é refeita (baixa/verifica de novo) e o conteúdo antigo é substituído por inteiro;
  - membro cujo 1º componente seja ``..`` ou nome absoluto é recusado (erro) antes de qualquer arquivo ficar no destino final.
Sem rede e sem produção: tudo em tmp_path, tar.gz mínimos em memória, requests.get falso.
"""

import hashlib
import os
import shutil
from pathlib import Path

import pytest

from tests.audio.test_jdk_extracao import DIR, FILE, GOOD, SYM, tar_gz
from empiremuse.utils import branding
from empiremuse.utils.music import local_lavalink as ll

PLATFORM_DIR = "Linux-64bit-ELF"
JDK_URL = "https://example.test/jdk-linux.tar.gz"
EVIL_LINK = (SYM, "jdk-21.0.3/bin/abs", "/etc/passwd")  # recusado pelo filtro `data` (só no fim da extração)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def install(monkeypatch, tmp_path):
    """run_lavalink no Linux sem Java: Lavalink.jar/yml/plugins verificados; o JDK vem de ``set_archive``."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JAVA_HOME", raising=False)
    jar, yml = b"JAR", b"YML\n"
    plugins = {
        n: f"plugin {n}".encode()
        for n in (
            "youtube-plugin-2be8e542d3f6f178e048dca565892684c2e40177.jar",
            "lavasrc-plugin-4.8.3.jar",
            "lavalink-2.6.1.jar",
        )
    }
    monkeypatch.setattr(branding, "LAVALINK_JAR_SHA256", sha(jar))
    monkeypatch.setattr(branding, "LAVALINK_APPLICATION_YML_SHA256", sha(yml))
    monkeypatch.setattr(branding, "LAVALINK_PLUGIN_SHA256", {n: sha(d) for n, d in plugins.items()})
    (tmp_path / "Lavalink.jar").write_bytes(jar)
    (tmp_path / "application.yml").write_bytes(yml)
    (tmp_path / "plugins").mkdir()
    for name, data in plugins.items():
        (tmp_path / "plugins" / name).write_bytes(data)

    state = {"archive": b"", "calls": 0}

    class Response:
        def __init__(self, data):
            self.data, self.headers = data, {"content-length": str(len(data))}

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

    def get(url, *args, **kwargs):
        assert url == JDK_URL, f"requisição inesperada: {url}"
        state["calls"] += 1
        return Response(state["archive"])

    def set_archive(members_or_bytes):
        data = members_or_bytes if isinstance(members_or_bytes, bytes) else tar_gz(members_or_bytes)
        state["archive"] = data
        entry = (JDK_URL, sha(data))
        monkeypatch.setattr(
            branding,
            "JDK_DOWNLOADS",
            {"linux-amd64": entry, "linux-i586": entry, "windows-amd64": entry, "windows-i586": entry},
        )

    started = []
    monkeypatch.setattr(ll.requests, "get", get)
    monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: None)
    monkeypatch.setattr(ll.platform, "architecture", lambda *a, **k: ("64bit", "ELF"))
    monkeypatch.setattr(ll.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ll.subprocess, "Popen", lambda args, **kw: started.append(list(args)))

    def java_tree():
        base = tmp_path / ".java"
        return sorted(str(p.relative_to(base)) for p in base.rglob("*")) if base.exists() else []

    set_archive(GOOD)
    return type(
        "Install",
        (),
        {
            "set_archive": staticmethod(set_archive),
            "state": state,
            "started": started,
            "java_dir": tmp_path / ".java" / PLATFORM_DIR,
            "java_tree": staticmethod(java_tree),
            "base": tmp_path,
            "monkeypatch": monkeypatch,
            "archive_file": tmp_path / "java.tar.gz",
        },
    )


def installed_java(install) -> Path:
    return install.java_dir / "bin" / "java"


def make_valid_install(install, content=b"JAVA-JA-INSTALADO"):
    (install.java_dir / "bin").mkdir(parents=True)
    java = installed_java(install)
    java.write_bytes(content)
    java.chmod(0o755)
    return java


# ============================================================================ M-1 — falha não deixa instalação aproveitável


class TestFailedInstallationLeavesNothingUsable:
    def test_once_the_archive_is_fixed_the_next_start_installs_a_complete_jdk(self, install):
        install.set_archive(GOOD + [EVIL_LINK])
        with pytest.raises(Exception):
            ll.run_lavalink()
        install.set_archive(GOOD)
        ll.run_lavalink()
        assert installed_java(install).read_bytes() == b"JAVA" and len(install.started) == 1
        assert install.state["calls"] == 2

    def test_no_temporary_sibling_is_left_after_a_successful_install(self, install):
        ll.run_lavalink()
        assert sorted(p.name for p in (install.base / ".java").iterdir()) == [PLATFORM_DIR]


# ============================================================================ M-1 — o que torna um diretório já instalado aceitável


def build_broken_dir(install, kind):
    java_dir = install.java_dir
    java_dir.mkdir(parents=True)
    (java_dir / "stale.txt").write_bytes(b"resto-da-instalacao-quebrada")
    if kind == "vazio":
        (java_dir / "stale.txt").unlink()
    elif kind == "sem bin/java":
        (java_dir / "bin").mkdir()
    elif kind == "bin/java sem permissão de execução":
        (java_dir / "bin").mkdir()
        (java_dir / "bin" / "java").write_bytes(b"JAVA-NAO-EXECUTAVEL")
        (java_dir / "bin" / "java").chmod(0o644)
    elif kind == "bin/java é diretório":
        (java_dir / "bin" / "java").mkdir(parents=True)
    elif kind == "bin/java é symlink quebrado":
        (java_dir / "bin").mkdir()
        os.symlink("nao-existe", java_dir / "bin" / "java")


BROKEN_KINDS = [
    "vazio",
    "sem bin/java",
    "bin/java sem permissão de execução",
    "bin/java é diretório",
    "bin/java é symlink quebrado",
]


class TestAnExistingDirectoryIsOnlyAcceptedWhenJavaIsUsable:
    @pytest.mark.parametrize("kind", list(BROKEN_KINDS)[:2])
    def test_the_old_content_is_replaced_as_a_whole(self, install, kind):
        build_broken_dir(install, kind)
        ll.run_lavalink()
        assert not (install.java_dir / "stale.txt").exists(), "restos da instalação antiga não podem sobreviver à troca"
        assert sorted(p.name for p in (install.base / ".java").iterdir()) == [PLATFORM_DIR]

    def test_a_valid_directory_survives_when_the_archive_on_the_server_is_unsafe(self, install):
        java = make_valid_install(install)
        install.set_archive(GOOD + [EVIL_LINK])
        ll.run_lavalink()
        assert install.state["calls"] == 0 and java.read_bytes() == b"JAVA-JA-INSTALADO"

    def test_a_valid_directory_is_never_removed_by_a_failed_attempt_elsewhere(self, install):
        """Instalação anterior válida preservada: um outro .java/<plataforma> não é tocado por falha de extração."""
        other = install.base / ".java" / "Linux-32bit-ELF" / "bin"
        other.mkdir(parents=True)
        (other / "java").write_bytes(b"JAVA-DE-OUTRA-PLATAFORMA")
        (other / "java").chmod(0o755)
        install.set_archive(GOOD + [EVIL_LINK])
        with pytest.raises(Exception):
            ll.run_lavalink()
        assert (other / "java").read_bytes() == b"JAVA-DE-OUTRA-PLATAFORMA"
        shutil.rmtree(install.base / ".java")


# ============================================================================ B-1 — '..' / nome absoluto no 1º componente


class TestLegitimateNamesAreStillAccepted:
    """Guardas contra excesso de zelo: nomes que só PARECEM '..', prefixo './' e a pasta raiz comum continuam valendo."""

    @pytest.mark.parametrize("prefix", ["", "./"])
    def test_names_with_a_dot_slash_prefix_extract_normally(self, install, prefix):
        install.set_archive(
            [
                (DIR, f"{prefix}jdk-21.0.3/"),
                (DIR, f"{prefix}jdk-21.0.3/bin"),
                (FILE, f"{prefix}jdk-21.0.3/bin/java", b"JAVA"),
                (FILE, f"{prefix}jdk-21.0.3/release", b"r"),
            ]
        )
        ll.run_lavalink()
        assert installed_java(install).read_bytes() == b"JAVA" and len(install.started) == 1

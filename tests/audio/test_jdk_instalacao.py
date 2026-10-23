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
import tarfile
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


class Interrupted(BaseException):
    """Simula Ctrl+C/kill no meio da extração (não é Exception: ``except Exception`` não a pega)."""


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
    def test_a_refused_extraction_leaves_no_install_and_no_temporary_leftovers(self, install):
        install.set_archive(GOOD + [EVIL_LINK])
        with pytest.raises(Exception):
            ll.run_lavalink()
        assert not install.java_dir.exists(), "o diretório definitivo não pode existir após uma extração recusada"
        assert install.java_tree() == [], f"sobrou algo em .java após a falha: {install.java_tree()}"
        assert install.started == []

    def test_the_next_start_after_a_refusal_downloads_and_verifies_again(self, install):
        install.set_archive(GOOD + [EVIL_LINK])
        for expected_calls in (1, 2):
            with pytest.raises(Exception):
                ll.run_lavalink()
            assert install.state["calls"] == expected_calls, "cada partida precisa baixar/verificar de novo"
        assert install.started == [], "nunca iniciar com o resto de uma extração recusada"

    def test_once_the_archive_is_fixed_the_next_start_installs_a_complete_jdk(self, install):
        install.set_archive(GOOD + [EVIL_LINK])
        with pytest.raises(Exception):
            ll.run_lavalink()
        install.set_archive(GOOD)
        ll.run_lavalink()
        assert installed_java(install).read_bytes() == b"JAVA" and len(install.started) == 1
        assert install.state["calls"] == 2

    def test_an_interrupted_extraction_leaves_nothing_usable_even_for_base_exceptions(self, install):
        hits = []
        real_utime = tarfile.TarFile.utime

        def interrupting_utime(self, tarinfo, targetpath):
            hits.append(tarinfo.name)
            if len(hits) == 2:
                raise Interrupted()
            return real_utime(self, tarinfo, targetpath)

        install.monkeypatch.setattr(tarfile.TarFile, "utime", interrupting_utime)
        with pytest.raises(Interrupted):
            ll.run_lavalink()
        assert len(hits) >= 2, "a interrupção simulada não foi alcançada (a extração não passou por TarFile)"
        assert not installed_java(install).exists() and not install.java_dir.exists()
        assert install.java_tree() == [], f"sobrou algo em .java após a interrupção: {install.java_tree()}"
        assert install.started == []

    def test_the_next_start_after_an_interruption_installs_a_complete_jdk(self, install):
        real_utime = tarfile.TarFile.utime
        calls = []

        def interrupting_utime(self, tarinfo, targetpath):
            calls.append(1)
            if len(calls) == 2:
                raise Interrupted()
            return real_utime(self, tarinfo, targetpath)

        install.monkeypatch.setattr(tarfile.TarFile, "utime", interrupting_utime)
        with pytest.raises(Interrupted):
            ll.run_lavalink()
        install.monkeypatch.setattr(tarfile.TarFile, "utime", real_utime)
        ll.run_lavalink()
        assert installed_java(install).read_bytes() == b"JAVA" and len(install.started) == 1
        assert (install.java_dir / "release").read_bytes() == b"release"

    def test_extraction_never_happens_directly_in_the_final_directory(self, install):
        real_utime = tarfile.TarFile.utime
        seen = []

        def spying_utime(self, tarinfo, targetpath):
            seen.append(install.java_dir.exists())
            return real_utime(self, tarinfo, targetpath)

        install.monkeypatch.setattr(tarfile.TarFile, "utime", spying_utime)
        ll.run_lavalink()
        assert seen, "a extração não passou por TarFile (hook não acionado)"
        assert not any(seen), (
            "o JDK foi extraído direto no diretório definitivo: use um diretório temporário irmão + os.replace"
        )
        assert installed_java(install).read_bytes() == b"JAVA"

    def test_no_temporary_sibling_is_left_after_a_successful_install(self, install):
        ll.run_lavalink()
        assert sorted(p.name for p in (install.base / ".java").iterdir()) == [PLATFORM_DIR]

    def test_the_downloaded_archive_is_removed_after_success(self, install):
        ll.run_lavalink()
        assert not install.archive_file.exists()

    def test_the_downloaded_archive_is_removed_after_a_refusal(self, install):
        install.set_archive(GOOD + [EVIL_LINK])
        with pytest.raises(Exception):
            ll.run_lavalink()
        assert not install.archive_file.exists()

    def test_leftover_temporary_directories_of_a_previous_crash_are_never_used(self, install):
        for name in (f"{PLATFORM_DIR}.tmp", f"{PLATFORM_DIR}.partial", f".{PLATFORM_DIR}.new", "tmp-extract"):
            (install.base / ".java" / name / "bin").mkdir(parents=True)
            fake = install.base / ".java" / name / "bin" / "java"
            fake.write_bytes(b"JAVA-DE-CRASH-ANTERIOR")
            fake.chmod(0o755)
        ll.run_lavalink()
        assert installed_java(install).read_bytes() == b"JAVA", "o JDK final tem de vir do arquivo verificado"
        assert len(install.started) == 1


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
    @pytest.mark.parametrize("kind", BROKEN_KINDS)
    def test_a_broken_directory_triggers_a_fresh_verified_install(self, install, kind):
        build_broken_dir(install, kind)
        ll.run_lavalink()
        assert install.state["calls"] == 1, "diretório sem bin/java executável não pode ser aproveitado"
        assert installed_java(install).read_bytes() == b"JAVA"
        assert os.access(installed_java(install), os.X_OK)
        assert len(install.started) == 1

    @pytest.mark.parametrize("kind", BROKEN_KINDS)
    def test_the_old_content_is_replaced_as_a_whole(self, install, kind):
        build_broken_dir(install, kind)
        ll.run_lavalink()
        assert not (install.java_dir / "stale.txt").exists(), "restos da instalação antiga não podem sobreviver à troca"
        assert sorted(p.name for p in (install.base / ".java").iterdir()) == [PLATFORM_DIR]

    @pytest.mark.parametrize("kind", BROKEN_KINDS)
    def test_a_failed_reinstall_does_not_make_the_broken_directory_trusted(self, install, kind):
        build_broken_dir(install, kind)
        install.set_archive(GOOD + [EVIL_LINK])
        for _ in range(2):
            with pytest.raises(Exception):
                ll.run_lavalink()
        assert install.state["calls"] == 2 and install.started == []

    def test_a_valid_installed_directory_is_reused_without_any_download(self, install):
        java = make_valid_install(install)
        ll.run_lavalink()
        assert install.state["calls"] == 0
        assert java.read_bytes() == b"JAVA-JA-INSTALADO", "uma instalação válida não pode ser tocada"
        assert len(install.started) == 1 and install.started[0][0] == os.path.realpath(java)

    def test_a_valid_symlinked_java_inside_the_directory_is_accepted(self, install):
        (install.java_dir / "bin").mkdir(parents=True)
        (install.java_dir / "lib").mkdir()
        (install.java_dir / "lib" / "java-real").write_bytes(b"JAVA-REAL")
        (install.java_dir / "lib" / "java-real").chmod(0o755)
        os.symlink("../lib/java-real", installed_java(install))
        ll.run_lavalink()
        assert install.state["calls"] == 0 and len(install.started) == 1

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

BAD_FIRST_COMPONENT = [
    "../evil-top.txt",
    "../x/y/evil.txt",
    "..",
    "../jdk-21.0.3/bin/java",
    "/abs-evil.txt",
    "/etc/cron.d/evil",
    "//double-slash-evil",
]


def bad_member(name):
    return (DIR, name) if name == ".." else (FILE, name, b"x")


class TestMembersWithDotDotOrAbsoluteFirstComponentAreRefused:
    @pytest.mark.parametrize("name", BAD_FIRST_COMPONENT)
    def test_the_installation_fails_and_leaves_nothing(self, install, name):
        install.set_archive(GOOD + [bad_member(name)])
        with pytest.raises(Exception):
            ll.run_lavalink()
        assert install.started == [], "o Lavalink não pode iniciar com um JDK recusado"
        assert not install.archive_file.exists(), "o java.tar.gz baixado deve ser removido"
        assert install.java_tree() == [], f"nada pode ficar extraído: {install.java_tree()}"
        assert not Path("/abs-evil.txt").exists() and not Path("/etc/cron.d/evil").exists()
        assert not (install.base / "evil-top.txt").exists() and not (install.base.parent / "evil-top.txt").exists()

    @pytest.mark.parametrize("name", BAD_FIRST_COMPONENT)
    def test_the_unit_function_raises_and_writes_nothing_outside_the_destination(self, tmp_path, name):
        destination = tmp_path / "dest"
        destination.mkdir()
        archive = tmp_path / "java.tar.gz"
        archive.write_bytes(tar_gz(GOOD + [bad_member(name)]))
        with pytest.raises(Exception):
            ll._extract_tar_without_top_dir(str(archive), str(destination))
        outside = [p for p in tmp_path.rglob("*") if destination not in p.parents and p not in (destination, archive)]
        assert outside == [], f"escreveu fora do destino: {outside}"

    @pytest.mark.parametrize("name", BAD_FIRST_COMPONENT)
    def test_even_when_it_is_the_first_member_of_the_archive(self, install, name):
        install.set_archive([bad_member(name)] + GOOD)
        with pytest.raises(Exception):
            ll.run_lavalink()
        assert install.started == [] and install.java_tree() == []


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

    @pytest.mark.parametrize("root", ["..jdk-21", "jdk..21", "...", ".hidden-root"])
    def test_root_directory_names_that_merely_contain_dots_are_fine(self, install, root):
        install.set_archive([(DIR, f"{root}/"), (DIR, f"{root}/bin"), (FILE, f"{root}/bin/java", b"JAVA")])
        ll.run_lavalink()
        assert installed_java(install).read_bytes() == b"JAVA"

    @pytest.mark.parametrize("inner", ["lib/a..b", "lib/..sombra", "lib/.hidden"])
    def test_inner_names_with_dots_are_fine(self, install, inner):
        install.set_archive(GOOD + [(FILE, f"jdk-21.0.3/{inner}", b"ok")])
        ll.run_lavalink()
        assert (install.java_dir / inner).read_bytes() == b"ok"

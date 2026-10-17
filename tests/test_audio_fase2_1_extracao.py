"""Fase 2.1 (validação GREEN) — extração segura do JDK .tar.gz: filtro ``data`` e remoção da pasta raiz.

Complementa tests/test_audio_fase2_1.py. O arquivo já passou pela verificação de SHA-256 (a âncora de confiança), mas a
extração não pode, mesmo assim, escrever fora da pasta de destino nem criar links/arquivos especiais perigosos.
Sem rede e sem produção: tudo em tmp_path, arquivos .tar.gz mínimos gerados em memória.
"""

import hashlib
import io
import os
import stat
import tarfile
from pathlib import Path

import pytest

from utils import branding
from utils.music import local_lavalink as ll

FILE, DIR, SYM, HARD, FIFO = "file", "dir", "sym", "hard", "fifo"


def tar_gz(members) -> bytes:
    """members: tuplas (tipo, nome, extra, modo?)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for member in members:
            kind, name, extra = member[0], member[1], (member[2] if len(member) > 2 else None)
            mode = member[3] if len(member) > 3 else 0o755
            info = tarfile.TarInfo(name)
            info.mode = mode
            if kind == FILE:
                info.size = len(extra)
                archive.addfile(info, io.BytesIO(extra))
            elif kind == DIR:
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            elif kind in (SYM, HARD):
                info.type = tarfile.SYMTYPE if kind == SYM else tarfile.LNKTYPE
                info.linkname = extra
                archive.addfile(info)
            elif kind == FIFO:
                info.type = tarfile.FIFOTYPE
                archive.addfile(info)
    return buffer.getvalue()


GOOD = [
    (DIR, "jdk-21.0.3/"),
    (DIR, "jdk-21.0.3/bin"),
    (FILE, "jdk-21.0.3/bin/java", b"JAVA"),
    (FILE, "jdk-21.0.3/release", b"release", 0o644),
    (HARD, "jdk-21.0.3/bin/java-hard", "jdk-21.0.3/bin/java"),
    (SYM, "jdk-21.0.3/bin/java-sym", "java"),
]


@pytest.fixture
def sandbox(tmp_path):
    """Layout igual ao do bot: <raiz>/java.tar.gz e <raiz>/.java/<plataforma> como destino; tmp_path é vigiado contra escritas."""
    root = tmp_path / "raiz"
    destination = root / ".java" / "Linux-64bit-ELF"
    destination.mkdir(parents=True)

    def extract(members):
        archive = root / "java.tar.gz"
        archive.write_bytes(tar_gz(members))
        ll._extract_tar_without_top_dir(str(archive), str(destination))

    def outside():
        """Tudo que existe em tmp_path fora do destino (e fora do próprio java.tar.gz)."""
        return sorted(
            str(p.relative_to(tmp_path))
            for p in tmp_path.rglob("*")
            if destination not in p.parents
            and p != destination
            and p.name != "java.tar.gz"
            and p not in (root, root / ".java")
        )

    return type(
        "Sandbox",
        (),
        {
            "extract": staticmethod(extract),
            "dest": destination,
            "outside": staticmethod(outside),
            "root": root,
            "tmp": tmp_path,
        },
    )


class TestStripsTheRootDirectory:
    def test_contents_land_directly_under_the_destination(self, sandbox):
        sandbox.extract(GOOD)
        assert (sandbox.dest / "bin" / "java").read_bytes() == b"JAVA"
        assert (sandbox.dest / "release").read_bytes() == b"release"
        assert not (sandbox.dest / "jdk-21.0.3").exists(), "a pasta raiz deve ser removida (--strip-components=1)"

    def test_java_stays_executable(self, sandbox):
        sandbox.extract(GOOD)
        assert os.access(sandbox.dest / "bin" / "java", os.X_OK)

    def test_hard_links_are_resolved_inside_the_stripped_tree(self, sandbox):
        sandbox.extract(GOOD)
        assert (sandbox.dest / "bin" / "java-hard").read_bytes() == b"JAVA"
        # o link continua sendo um hardlink (mesmo inode) de bin/java dentro da árvore sem a pasta raiz
        assert (sandbox.dest / "bin" / "java-hard").stat().st_ino == (sandbox.dest / "bin" / "java").stat().st_ino

    def test_relative_symlinks_inside_the_tree_are_kept(self, sandbox):
        sandbox.extract(GOOD)
        link = sandbox.dest / "bin" / "java-sym"
        assert link.is_symlink() and os.readlink(link) == "java" and link.read_bytes() == b"JAVA"

    def test_nothing_is_written_outside_the_destination_for_a_good_archive(self, sandbox):
        sandbox.extract(GOOD)
        assert sandbox.outside() == []


class TestUnsafeMembersAreRefusedAndNeverEscape:
    @pytest.mark.parametrize(
        "label,bad",
        [
            ("'../' em profundidade", (FILE, "jdk-21.0.3/../../evil-deep.txt", b"x")),
            ("symlink absoluto", (SYM, "jdk-21.0.3/bin/abs", "/etc/passwd")),
            ("symlink relativo que escapa", (SYM, "jdk-21.0.3/bin/esc", "../../../../etc")),
            ("hardlink que escapa", (HARD, "jdk-21.0.3/bin/h-esc", "../../../etc/passwd")),
            ("hardlink absoluto", (HARD, "jdk-21.0.3/bin/h-abs", "/etc/passwd")),
            ("arquivo especial (fifo)", (FIFO, "jdk-21.0.3/bin/pipe")),
        ],
    )
    def test_the_archive_is_refused(self, sandbox, label, bad):
        with pytest.raises(Exception):
            sandbox.extract(GOOD + [bad])
        assert sandbox.outside() == [], f"{label}: escreveu fora do destino"

    def test_writing_through_a_symlink_that_points_outside_is_refused(self, sandbox):
        with pytest.raises(Exception):
            sandbox.extract(GOOD + [(SYM, "jdk-21.0.3/lnk", "../.."), (FILE, "jdk-21.0.3/lnk/pwned.txt", b"x")])
        assert sandbox.outside() == [] and not (sandbox.tmp / "pwned.txt").exists()

    @pytest.mark.parametrize("name", ["../evil-top.txt", "/abs-evil.txt"])
    def test_a_single_leading_dotdot_or_absolute_name_never_leaves_the_destination(self, sandbox, name):
        # A pasta raiz removida neutraliza o 1º componente; o resultado pode ser recusado OU ficar dentro do destino.
        try:
            sandbox.extract(GOOD + [(FILE, name, b"x")])
        except Exception:
            pass
        assert sandbox.outside() == [] and not (sandbox.tmp / "evil-top.txt").exists()
        assert not Path("/abs-evil.txt").exists()

    def test_setuid_and_setgid_bits_are_cleared(self, sandbox):
        sandbox.extract(GOOD + [(FILE, "jdk-21.0.3/bin/suid", b"x", 0o6755)])
        mode = (sandbox.dest / "bin" / "suid").stat().st_mode
        assert not mode & (stat.S_ISUID | stat.S_ISGID)

    def test_group_and_other_write_bits_are_cleared(self, sandbox):
        sandbox.extract(GOOD + [(FILE, "jdk-21.0.3/bin/w", b"x", 0o777)])
        assert not (sandbox.dest / "bin" / "w").stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH)


class TestRunLavalinkRefusesAVerifiedButUnsafeArchive:
    @pytest.fixture
    def env(self, monkeypatch, tmp_path):
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
        monkeypatch.setattr(branding, "LAVALINK_JAR_SHA256", hashlib.sha256(jar).hexdigest())
        monkeypatch.setattr(branding, "LAVALINK_APPLICATION_YML_SHA256", hashlib.sha256(yml).hexdigest())
        monkeypatch.setattr(
            branding, "LAVALINK_PLUGIN_SHA256", {n: hashlib.sha256(d).hexdigest() for n, d in plugins.items()}
        )
        (tmp_path / "Lavalink.jar").write_bytes(jar)
        (tmp_path / "application.yml").write_bytes(yml)
        (tmp_path / "plugins").mkdir()
        for name, data in plugins.items():
            (tmp_path / "plugins" / name).write_bytes(data)
        evil = tar_gz(
            GOOD + [(SYM, "jdk-21.0.3/bin/abs", "/etc/passwd")]
        )  # com SHA-256 CORRETO: só a extração o recusa
        url = "https://example.test/jdk.tar.gz"
        monkeypatch.setattr(
            branding,
            "JDK_DOWNLOADS",
            {
                "linux-amd64": (url, hashlib.sha256(evil).hexdigest()),
                "linux-i586": (url, hashlib.sha256(evil).hexdigest()),
            },
        )

        class Response:
            headers = {"content-length": str(len(evil))}

            def iter_content(self, chunk_size=1):
                yield evil

            def raise_for_status(self):
                return None

            def close(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(ll.requests, "get", lambda *a, **k: Response())
        monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: None)
        monkeypatch.setattr(ll.platform, "architecture", lambda *a, **k: ("64bit", "ELF"))
        monkeypatch.setattr(ll.platform, "system", lambda: "Linux")
        started = []
        monkeypatch.setattr(ll.subprocess, "Popen", lambda args, **kw: started.append(args))
        return started

    def test_the_bot_does_not_start_and_the_downloaded_archive_is_removed(self, env, tmp_path):
        with pytest.raises(Exception):
            ll.run_lavalink()
        assert env == [], "o Lavalink não pode iniciar com um JDK recusado"
        assert not (tmp_path / "java.tar.gz").exists(), "o arquivo baixado não deve ficar no disco"

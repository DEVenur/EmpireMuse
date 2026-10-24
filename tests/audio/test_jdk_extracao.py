"""Fase 2.1 (validação GREEN) — extração segura do JDK .tar.gz: filtro ``data`` e remoção da pasta raiz.

Complementa tests/audio/test_jdk_sha256_e_ambiente.py. O arquivo já passou pela verificação de SHA-256 (a âncora de confiança), mas a
extração não pode, mesmo assim, escrever fora da pasta de destino nem criar links/arquivos especiais perigosos.
Sem rede e sem produção: tudo em tmp_path, arquivos .tar.gz mínimos gerados em memória.
"""

import io
import os
import stat
import tarfile
from pathlib import Path

import pytest

from empiremuse.utils.music import local_lavalink as ll

pytestmark = pytest.mark.critical

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
    def test_java_stays_executable(self, sandbox):
        sandbox.extract(GOOD)
        assert os.access(sandbox.dest / "bin" / "java", os.X_OK)

    def test_relative_symlinks_inside_the_tree_are_kept(self, sandbox):
        sandbox.extract(GOOD)
        link = sandbox.dest / "bin" / "java-sym"
        assert link.is_symlink() and os.readlink(link) == "java" and link.read_bytes() == b"JAVA"


class TestUnsafeMembersAreRefusedAndNeverEscape:
    @pytest.mark.parametrize(
        "label,bad",
        [
            ("'../' em profundidade", (FILE, "jdk-21.0.3/../../evil-deep.txt", b"x")),
            ("arquivo especial (fifo)", (FIFO, "jdk-21.0.3/bin/pipe")),
        ],
    )
    def test_the_archive_is_refused(self, sandbox, label, bad):
        with pytest.raises(Exception):
            sandbox.extract(GOOD + [bad])
        assert sandbox.outside() == [], f"{label}: escreveu fora do destino"

    @pytest.mark.parametrize("name", ["../evil-top.txt", "/abs-evil.txt"])
    def test_a_single_leading_dotdot_or_absolute_name_never_leaves_the_destination(self, sandbox, name):
        # A pasta raiz removida neutraliza o 1º componente; o resultado pode ser recusado OU ficar dentro do destino.
        try:
            sandbox.extract(GOOD + [(FILE, name, b"x")])
        except Exception:
            pass
        assert sandbox.outside() == [] and not (sandbox.tmp / "evil-top.txt").exists()
        assert not Path("/abs-evil.txt").exists()

    def test_group_and_other_write_bits_are_cleared(self, sandbox):
        sandbox.extract(GOOD + [(FILE, "jdk-21.0.3/bin/w", b"x", 0o777)])
        assert not (sandbox.dest / "bin" / "w").stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH)

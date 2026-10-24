"""JDK no Windows: extração em diretório irmão (staging) e troca atômica, como no Linux, sem apagar o ``.java`` inteiro.

Antes, ``_install_jdk_windows`` fazia ``rmtree`` de todo o ``.java`` e extraía direto nele: uma falha deixava o JDK pela
metade e levava junto as instalações de outras plataformas. ``_jdk_is_usable`` também só olhava ``bin/java``.
Sem rede: o download verificado é substituído por um zip gravado no lugar.
"""

import zipfile

import pytest

from empiremuse.utils.music import local_lavalink as ll

PLATAFORMA = "Windows-64bit-WindowsPE"


def gravar_zip(caminho: str, arquivos: dict[str, bytes]) -> None:
    with zipfile.ZipFile(caminho, "w") as zip_ref:
        for nome, dados in arquivos.items():
            zip_ref.writestr(nome, dados)


def gravar_jdk(raiz, plataforma: str, nome_do_java: str, conteudo: bytes) -> None:
    (raiz / ".java" / plataforma / "bin").mkdir(parents=True)
    java = raiz / ".java" / plataforma / "bin" / nome_do_java
    java.write_bytes(conteudo)
    java.chmod(0o755)


@pytest.fixture
def zip_baixado(monkeypatch):
    """Faz o download verificado gravar o zip escolhido pelo teste em ``archive_path``."""
    escolhido = {"arquivos": {"jdk-17/bin/java.exe": b"JAVA-NOVO", "jdk-17/release": b"ok"}}

    def baixar(archive_path, url, sha256):
        gravar_zip(archive_path, escolhido["arquivos"])

    monkeypatch.setattr(ll, "_fetch_verified_jdk", baixar)
    return escolhido


class TestJdkIsUsable:
    def test_diretorio_sem_executavel_nao_serve(self, tmp_path):
        (tmp_path / ".java" / PLATAFORMA / "bin").mkdir(parents=True)

        assert not ll._jdk_is_usable(str(tmp_path / ".java" / PLATAFORMA))


class TestInstalacaoNoWindows:
    def test_instalacao_antiga_quebrada_e_trocada_por_inteiro(self, tmp_path, zip_baixado):
        gravar_jdk(tmp_path, PLATAFORMA, "java.exe", b"JAVA-VELHO")
        (tmp_path / ".java" / PLATAFORMA / "resto.txt").write_text("lixo", encoding="utf-8")

        ll._install_jdk_windows(str(tmp_path), PLATAFORMA, "64bit")

        assert (tmp_path / ".java" / PLATAFORMA / "bin" / "java.exe").read_bytes() == b"JAVA-NOVO"
        assert not (tmp_path / ".java" / PLATAFORMA / "resto.txt").exists()

    def test_zip_sem_java_exe_falha_e_preserva_a_instalacao_anterior(self, tmp_path, zip_baixado):
        gravar_jdk(tmp_path, PLATAFORMA, "java.exe", b"JAVA-ANTERIOR")
        zip_baixado["arquivos"] = {"jdk-17/release": b"sem-java"}

        with pytest.raises(ll.LavalinkDownloadError):
            ll._install_jdk_windows(str(tmp_path), PLATAFORMA, "64bit")

        assert (tmp_path / ".java" / PLATAFORMA / "bin" / "java.exe").read_bytes() == b"JAVA-ANTERIOR"
        assert [p.name for p in (tmp_path / ".java").iterdir()] == [PLATAFORMA], "o staging não foi apagado"
        assert not (tmp_path / "java.zip").exists()

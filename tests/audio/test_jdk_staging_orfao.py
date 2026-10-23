"""Sobras de staging do JDK (~150 MB cada) após ``kill -9`` são limpas na subida, sem tocar no que está em uso.

O ``finally`` de ``_install_extracted_jdk`` não roda num ``kill -9``; o diretório ``<plataforma>.<8 caracteres>.tmp`` ficava
para sempre em ``.java``. A limpeza só apaga diretório real com esse nome e parado há mais de ``JDK_STAGING_MAX_AGE``.
"""

import os
import tempfile
import time

import pytest

from empiremuse.utils.music import local_lavalink as ll

PLATAFORMA = "Linux-64bit-ELF"
IDADE = ll.JDK_STAGING_MAX_AGE


def envelhecer(caminho, segundos: float) -> None:
    """Põe o diretório e tudo que há nele (um nível) como não modificado há ``segundos``."""
    instante = time.time() - segundos
    for alvo in [caminho, *caminho.iterdir()]:
        os.utime(alvo, (instante, instante))


def criar_staging(raiz, nome: str = f"{PLATAFORMA}.ab12cd34.tmp", idade: float = 2 * IDADE):
    staging = raiz / nome
    (staging / "lib").mkdir(parents=True)
    (staging / "lib" / "modules").write_bytes(b"x" * 1024)
    (staging / "bin").mkdir()
    envelhecer(staging, idade)
    return staging


@pytest.fixture
def java_root(tmp_path):
    raiz = tmp_path / ".java"
    raiz.mkdir()
    return raiz


class TestRemoveOrphanJdkStaging:
    def test_apaga_o_staging_antigo(self, java_root):
        staging = criar_staging(java_root)

        assert ll.remove_orphan_jdk_staging(str(java_root)) == 1

        assert not staging.exists()

    def test_nao_apaga_staging_recente_de_outro_processo_em_curso(self, java_root):
        staging = criar_staging(java_root, idade=30)

        assert ll.remove_orphan_jdk_staging(str(java_root)) == 0

        assert staging.exists()

    def test_entrada_nova_dentro_do_staging_antigo_conta_como_atividade(self, java_root):
        staging = criar_staging(java_root)
        (staging / "legal").mkdir()  # criada agora: a extração ainda está escrevendo

        assert ll.remove_orphan_jdk_staging(str(java_root)) == 0

        assert staging.exists()

    def test_nunca_apaga_a_instalacao_valida_mesmo_antiga(self, java_root):
        instalacao = java_root / PLATAFORMA / "bin"
        instalacao.mkdir(parents=True)
        (instalacao / "java").write_bytes(b"JAVA")
        envelhecer(java_root / PLATAFORMA, 10 * IDADE)

        assert ll.remove_orphan_jdk_staging(str(java_root)) == 0

        assert (instalacao / "java").read_bytes() == b"JAVA"

    @pytest.mark.parametrize(
        "nome",
        [f"{PLATAFORMA}.tmp", f"{PLATAFORMA}.partial", f".{PLATAFORMA}.new", "tmp-extract", f"{PLATAFORMA}.curto.tmp"],
    )
    def test_ignora_nomes_que_nao_sao_de_mkdtemp(self, java_root, nome):
        staging = criar_staging(java_root, nome=nome)

        assert ll.remove_orphan_jdk_staging(str(java_root)) == 0

        assert staging.exists()

    def test_nao_segue_link_simbolico_com_nome_de_staging(self, java_root, tmp_path):
        alvo = criar_staging(tmp_path, nome="alvo-fora")
        link = java_root / f"{PLATAFORMA}.ab12cd34.tmp"
        try:
            link.symlink_to(alvo, target_is_directory=True)
        except OSError:
            pytest.skip("sem permissão para criar link simbólico")

        assert ll.remove_orphan_jdk_staging(str(java_root)) == 0

        assert alvo.exists() and (alvo / "lib" / "modules").exists()

    def test_arquivo_com_nome_de_staging_e_ignorado(self, java_root):
        arquivo = java_root / f"{PLATAFORMA}.ab12cd34.tmp"
        arquivo.write_bytes(b"x")
        envelhecer_arquivo = time.time() - 2 * IDADE
        os.utime(arquivo, (envelhecer_arquivo, envelhecer_arquivo))

        assert ll.remove_orphan_jdk_staging(str(java_root)) == 0

        assert arquivo.exists()

    def test_apaga_todos_os_orfaos_e_so_eles(self, java_root):
        velho_a = criar_staging(java_root, nome=f"{PLATAFORMA}.aaaaaaaa.tmp")
        velho_b = criar_staging(java_root, nome="Windows-64bit-WindowsPE.bbbbbbbb.tmp")
        em_curso = criar_staging(java_root, nome=f"{PLATAFORMA}.cccccccc.tmp", idade=5)

        assert ll.remove_orphan_jdk_staging(str(java_root)) == 2

        assert not velho_a.exists() and not velho_b.exists() and em_curso.exists()

    def test_pasta_inexistente_nao_e_erro(self, tmp_path):
        assert ll.remove_orphan_jdk_staging(str(tmp_path / "nao-existe")) == 0

    def test_o_proprio_nome_gerado_pelo_instalador_casa_com_o_padrao(self, java_root):
        gerado = tempfile.mkdtemp(prefix=f"{PLATAFORMA}.", suffix=".tmp", dir=java_root)
        staging = java_root / os.path.basename(gerado)
        envelhecer(staging, 2 * IDADE)

        assert ll.remove_orphan_jdk_staging(str(java_root)) == 1

        assert not staging.exists()


class TestLimpezaNaSubida:
    def test_run_lavalink_limpa_o_orfao_antes_de_procurar_o_java(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        staging = criar_staging(tmp_path / ".java")
        ordem = []

        def procurar(*args, **kwargs):
            ordem.append(("java", staging.exists()))
            raise ll.LavalinkDownloadError("para aqui")

        monkeypatch.setattr(ll, "_find_or_install_java", procurar)

        with pytest.raises(ll.LavalinkDownloadError):
            ll.run_lavalink()

        assert ordem == [("java", False)]

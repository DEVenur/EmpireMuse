"""Sobras de staging do JDK (~150 MB cada) após ``kill -9`` são limpas na subida, sem tocar no que está em uso.

O ``finally`` de ``_install_extracted_jdk`` não roda num ``kill -9``; o diretório ``<plataforma>.<8 caracteres>.tmp`` ficava
para sempre em ``.java``. A limpeza só apaga diretório real com esse nome e parado há mais de ``JDK_STAGING_MAX_AGE``.
"""

import os
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
    def test_entrada_nova_dentro_do_staging_antigo_conta_como_atividade(self, java_root):
        staging = criar_staging(java_root)
        (staging / "legal").mkdir()  # criada agora: a extração ainda está escrevendo

        assert ll.remove_orphan_jdk_staging(str(java_root)) == 0

        assert staging.exists()

    def test_apaga_todos_os_orfaos_e_so_eles(self, java_root):
        velho_a = criar_staging(java_root, nome=f"{PLATAFORMA}.aaaaaaaa.tmp")
        velho_b = criar_staging(java_root, nome="Windows-64bit-WindowsPE.bbbbbbbb.tmp")
        em_curso = criar_staging(java_root, nome=f"{PLATAFORMA}.cccccccc.tmp", idade=5)

        assert ll.remove_orphan_jdk_staging(str(java_root)) == 2

        assert not velho_a.exists() and not velho_b.exists() and em_curso.exists()

    def test_pasta_inexistente_nao_e_erro(self, tmp_path):
        assert ll.remove_orphan_jdk_staging(str(tmp_path / "nao-existe")) == 0

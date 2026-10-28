"""``assets/brand/logo-256.png``: o logo pequeno da interface (painel, página de status, README), derivado do ``avatar.png``.

256x256, menos de 100 KB e sem metadados (nada de texto, EXIF, data ou perfil de cor); a integridade geral vem de ``test_assets_imagens.py``.
"""

import struct

import pytest

from tests.repo.test_assets_imagens import problemas_png
from tests.support.raiz import RAIZ

ARQUIVO = RAIZ / "assets" / "brand" / "logo-256.png"
LIMITE_BYTES = 100 * 1024
BLOCOS_PERMITIDOS = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"}


def blocos(dados: bytes) -> list[bytes]:
    achados, posicao = [], 8
    while posicao + 8 <= len(dados):
        (tamanho,) = struct.unpack(">I", dados[posicao : posicao + 4])
        achados.append(dados[posicao + 4 : posicao + 8])
        posicao += 12 + tamanho
    return achados


@pytest.fixture(scope="module")
def dados() -> bytes:
    assert ARQUIVO.is_file() and not ARQUIVO.is_symlink(), "assets/brand/logo-256.png ainda não existe"
    return ARQUIVO.read_bytes()


def test_it_is_a_valid_png(dados):
    assert problemas_png(dados) == []


def test_it_is_256_by_256(dados):
    assert struct.unpack(">II", dados[16:24]) == (256, 256)


def test_it_weighs_less_than_100_kib(dados):
    assert len(dados) < LIMITE_BYTES


def test_it_carries_no_metadata_chunks(dados):
    assert set(blocos(dados)) <= BLOCOS_PERMITIDOS, sorted(set(blocos(dados)) - BLOCOS_PERMITIDOS)

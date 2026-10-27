"""Toda imagem de ``assets/`` decodifica por inteiro: nenhuma está truncada ou cortada no meio do envio.

Só biblioteca padrão. PNG: assinatura, CRCs de todos os chunks, termina em ``IEND`` sem sobra, e os ``IDAT`` juntos inflam até exatamente
``altura × bytes por linha`` (com o byte de filtro; o entrelaçamento Adam7 é contado por passada). JPEG: começa em ``FFD8`` e termina em
``FFD9``. GIF: cabeçalho ``GIF87a``/``GIF89a`` e termina em ``0x3B``. O verificador tem testes próprios com imagens sintéticas.
"""

import struct
import zlib
from pathlib import Path

import pytest

from tests.support.raiz import RAIZ

pytestmark = pytest.mark.critical

ASSETS = RAIZ / "assets"
ASSINATURA_PNG = b"\x89PNG\r\n\x1a\n"
CANAIS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
ADAM7 = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]


def _bytes_por_linha(largura: int, bits_por_pixel: int) -> int:
    return (largura * bits_por_pixel + 7) // 8


def _tamanho_esperado(largura: int, altura: int, tipo_cor: int, profundidade: int, entrelacado: int) -> int:
    bits = CANAIS[tipo_cor] * profundidade
    if not entrelacado:
        return altura * (1 + _bytes_por_linha(largura, bits))
    total = 0
    for x0, y0, dx, dy in ADAM7:
        larg, alt = -(-(largura - x0) // dx), -(-(altura - y0) // dy)
        if larg > 0 and alt > 0:
            total += alt * (1 + _bytes_por_linha(larg, bits))
    return total


def problemas_png(dados: bytes) -> list[str]:
    if not dados.startswith(ASSINATURA_PNG):
        return ["assinatura PNG ausente"]
    pos, chunks, idat = len(ASSINATURA_PNG), [], bytearray()
    while pos < len(dados):
        if pos + 8 > len(dados):
            return ["chunk cortado no cabeçalho"]
        tamanho, tipo = struct.unpack(">I4s", dados[pos : pos + 8])
        fim = pos + 8 + tamanho + 4
        if fim > len(dados):
            return [f"chunk {tipo.decode('latin1')} cortado (faltam {fim - len(dados)} bytes)"]
        corpo, crc = dados[pos + 8 : pos + 8 + tamanho], struct.unpack(">I", dados[fim - 4 : fim])[0]
        if zlib.crc32(tipo + corpo) != crc:
            return [f"CRC do chunk {tipo.decode('latin1')} não confere"]
        chunks.append((tipo, corpo))
        if tipo == b"IDAT":
            idat += corpo
        pos = fim
        if tipo == b"IEND":
            break
    if not chunks or chunks[0][0] != b"IHDR" or len(chunks[0][1]) != 13:
        return ["IHDR ausente ou inválido"]
    if chunks[-1][0] != b"IEND":
        return ["não termina em IEND"]
    if pos != len(dados):
        return [f"{len(dados) - pos} bytes depois do IEND"]
    largura, altura, profundidade, tipo_cor, _, _, entrelacado = struct.unpack(">IIBBBBB", chunks[0][1])
    if tipo_cor not in CANAIS or largura == 0 or altura == 0:
        return ["IHDR com valores inválidos"]
    try:
        bruto = zlib.decompress(bytes(idat))
    except zlib.error as erro:
        return [f"IDAT não infla: {erro}"]
    esperado = _tamanho_esperado(largura, altura, tipo_cor, profundidade, entrelacado)
    return [] if len(bruto) == esperado else [f"IDAT infla {len(bruto)} bytes, o esperado são {esperado}"]


def problemas_jpeg(dados: bytes) -> list[str]:
    achados = []
    if not dados.startswith(b"\xff\xd8"):
        achados.append("não começa em FFD8")
    if not dados.endswith(b"\xff\xd9"):
        achados.append("não termina em FFD9")
    return achados


def problemas_gif(dados: bytes) -> list[str]:
    achados = []
    if dados[:6] not in (b"GIF87a", b"GIF89a"):
        achados.append("cabeçalho GIF ausente")
    if not dados.endswith(b"\x3b"):
        achados.append("não termina em 0x3B")
    return achados


VERIFICADORES = {".png": problemas_png, ".jpg": problemas_jpeg, ".jpeg": problemas_jpeg, ".gif": problemas_gif}


def imagens() -> list[Path]:
    return sorted(p for p in ASSETS.iterdir() if p.suffix.lower() in VERIFICADORES)


def _chunk(tipo: bytes, corpo: bytes) -> bytes:
    return struct.pack(">I", len(corpo)) + tipo + corpo + struct.pack(">I", zlib.crc32(tipo + corpo))


def png_sintetico(largura=3, altura=2, tipo_cor=2, profundidade=8, entrelacado=0, linhas=None) -> bytes:
    bits = CANAIS[tipo_cor] * profundidade
    esperado = _tamanho_esperado(largura, altura, tipo_cor, profundidade, entrelacado)
    bruto = bytes(esperado) if linhas is None else linhas
    ihdr = struct.pack(">IIBBBBB", largura, altura, profundidade, tipo_cor, 0, 0, entrelacado)
    return ASSINATURA_PNG + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bruto)) + _chunk(b"IEND", b"")


class TestVerificador:
    def test_a_complete_png_has_no_problem(self):
        assert problemas_png(png_sintetico()) == []

    @pytest.mark.parametrize("entrelacado", [0, 1])
    @pytest.mark.parametrize("tipo_cor", [0, 2, 3, 4, 6])
    def test_every_color_type_and_adam7_count_the_rows_right(self, tipo_cor, entrelacado):
        assert problemas_png(png_sintetico(largura=13, altura=9, tipo_cor=tipo_cor, entrelacado=entrelacado)) == []

    def test_a_png_cut_in_the_middle_of_the_idat_is_reported(self):
        dados = png_sintetico(largura=40, altura=40)

        assert problemas_png(dados[: len(dados) - 30])

    def test_a_png_without_the_iend_is_reported(self):
        assert problemas_png(png_sintetico()[:-12]) == ["não termina em IEND"]

    def test_a_png_whose_idat_has_missing_rows_is_reported(self):
        faltando = bytes(1 * (1 + 9))  # 1 linha de 3x2 RGB
        assert problemas_png(png_sintetico(linhas=faltando)) == ["IDAT infla 10 bytes, o esperado são 20"]

    def test_bytes_after_the_iend_are_reported(self):
        assert problemas_png(png_sintetico() + b"x") == ["1 bytes depois do IEND"]

    def test_a_corrupted_chunk_is_reported_by_the_crc(self):
        dados = bytearray(png_sintetico())
        dados[20] ^= 0xFF

        assert "CRC" in problemas_png(bytes(dados))[0]

    def test_not_a_png_is_reported(self):
        assert problemas_png(b"GIF89a") == ["assinatura PNG ausente"]

    def test_jpeg_and_gif_endings(self):
        assert problemas_jpeg(b"\xff\xd8abc\xff\xd9") == [] and problemas_jpeg(b"\xff\xd8abc") == [
            "não termina em FFD9"
        ]
        assert problemas_gif(b"GIF89a....\x3b") == [] and problemas_gif(b"GIF89a....") == ["não termina em 0x3B"]


class TestAssets:
    def test_there_are_images_to_check(self):
        assert len(imagens()) >= 40

    @pytest.mark.parametrize("imagem", imagens(), ids=lambda p: p.name)
    def test_every_image_decodes_completely(self, imagem):
        achados = VERIFICADORES[imagem.suffix.lower()](imagem.read_bytes())

        assert achados == [], f"{imagem.name}: {achados}"

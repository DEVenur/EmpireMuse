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
PROFUNDIDADES = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
ADAM7 = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]


def _bytes_por_linha(largura: int, bits_por_pixel: int) -> int:
    return (largura * bits_por_pixel + 7) // 8


def _passadas(largura: int, altura: int, tipo_cor: int, profundidade: int, entrelacado: int) -> list[tuple[int, int]]:
    """``(linhas, bytes por linha SEM o byte de filtro)`` de cada passada (uma só, ou as até 7 do Adam7)."""
    bits = CANAIS[tipo_cor] * profundidade
    if not entrelacado:
        return [(altura, _bytes_por_linha(largura, bits))]
    passadas = []
    for x0, y0, dx, dy in ADAM7:
        larg, alt = -(-(largura - x0) // dx), -(-(altura - y0) // dy)
        if larg > 0 and alt > 0:
            passadas.append((alt, _bytes_por_linha(larg, bits)))
    return passadas


def _tamanho_esperado(largura: int, altura: int, tipo_cor: int, profundidade: int, entrelacado: int) -> int:
    return sum(
        linhas * (1 + por_linha)
        for linhas, por_linha in _passadas(largura, altura, tipo_cor, profundidade, entrelacado)
    )


def _ihdr_invalido(largura, altura, profundidade, tipo_cor, compressao, filtro, entrelacado) -> str | None:
    if tipo_cor not in CANAIS:
        return f"tipo de cor {tipo_cor} inválido"
    if profundidade not in PROFUNDIDADES[tipo_cor]:
        return f"profundidade {profundidade} inválida para o tipo de cor {tipo_cor}"
    if largura == 0 or altura == 0:
        return "largura ou altura zero"
    if compressao != 0 or filtro != 0:
        return "método de compressão ou de filtro inválido"
    if entrelacado not in (0, 1):
        return f"entrelaçamento {entrelacado} inválido (só 0 ou 1)"
    return None


def _bytes_de_filtro_invalidos(bruto: bytes, passadas: list[tuple[int, int]]) -> int | None:
    """Primeiro byte de filtro fora de 0..4 (ou ``None``); percorre linha a linha, passada a passada."""
    pos = 0
    for linhas, por_linha in passadas:
        for _ in range(linhas):
            if bruto[pos] > 4:
                return bruto[pos]
            pos += 1 + por_linha
    return None


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
    ihdr = struct.unpack(">IIBBBBB", chunks[0][1])
    largura, altura, profundidade, tipo_cor, _, _, entrelacado = ihdr
    if defeito := _ihdr_invalido(*ihdr):
        return [defeito]
    tipos = [tipo for tipo, _ in chunks]
    if b"IDAT" not in tipos:
        return ["IDAT ausente"]
    if tipo_cor == 3:
        if b"PLTE" not in tipos:
            return ["tipo de cor 3 sem PLTE"]
        if tipos.index(b"PLTE") > tipos.index(b"IDAT"):
            return ["PLTE depois do primeiro IDAT"]
        paleta = chunks[tipos.index(b"PLTE")][1]
        if len(paleta) == 0 or len(paleta) % 3 or len(paleta) > 3 * 2**profundidade:
            return [f"PLTE com {len(paleta)} bytes inválida"]
    elif tipo_cor in (0, 4) and b"PLTE" in tipos:
        return [f"PLTE não é permitida no tipo de cor {tipo_cor}"]
    try:
        bruto = zlib.decompress(bytes(idat))
    except zlib.error as erro:
        return [f"IDAT não infla: {erro}"]
    passadas = _passadas(largura, altura, tipo_cor, profundidade, entrelacado)
    esperado = _tamanho_esperado(largura, altura, tipo_cor, profundidade, entrelacado)
    if len(bruto) != esperado:
        return [f"IDAT infla {len(bruto)} bytes, o esperado são {esperado}"]
    if (invalido := _bytes_de_filtro_invalidos(bruto, passadas)) is not None:
        return [f"byte de filtro {invalido} fora de 0..4"]
    return []


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


def _montar_png(
    ihdr: tuple, bruto: bytes, *, paleta: bytes | None = None, paleta_depois: bool = False, com_idat: bool = True
) -> bytes:
    """Monta os bytes de um PNG a partir de ``ihdr`` e do conteúdo cru; os testes negativos estragam UMA coisa por vez por aqui."""
    cabecalho = _chunk(b"IHDR", struct.pack(">IIBBBBB", *ihdr))
    plte = _chunk(b"PLTE", paleta) if paleta is not None else b""
    idat = _chunk(b"IDAT", zlib.compress(bruto)) if com_idat else b""
    meio = idat + plte if paleta_depois else plte + idat
    return ASSINATURA_PNG + cabecalho + meio + _chunk(b"IEND", b"")


def png_sintetico(largura=3, altura=2, tipo_cor=2, profundidade=8, entrelacado=0) -> bytes:
    """Só PNG VÁLIDO: profundidade compatível com o tipo de cor, PLTE no tipo 3, filtro 0 em toda linha."""
    assert profundidade in PROFUNDIDADES[tipo_cor] and entrelacado in (0, 1)
    ihdr = (largura, altura, profundidade, tipo_cor, 0, 0, entrelacado)
    bruto = bytes(_tamanho_esperado(largura, altura, tipo_cor, profundidade, entrelacado))
    paleta = bytes(3 * min(4, 2**profundidade)) if tipo_cor == 3 else None
    return _montar_png(ihdr, bruto, paleta=paleta)


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
        assert problemas_png(_montar_png((3, 2, 8, 2, 0, 0, 0), faltando)) == ["IDAT infla 10 bytes, o esperado são 20"]

    def test_bytes_after_the_iend_are_reported(self):
        assert problemas_png(png_sintetico() + b"x") == ["1 bytes depois do IEND"]

    def test_a_corrupted_chunk_is_reported_by_the_crc(self):
        dados = bytearray(png_sintetico())
        dados[20] ^= 0xFF

        assert "CRC" in problemas_png(bytes(dados))[0]

    @pytest.mark.parametrize("entrelacado", [2, 3, 255])
    def test_an_interlace_method_other_than_0_or_1_is_reported(self, entrelacado):
        dados = _montar_png((3, 2, 8, 2, 0, 0, entrelacado), bytes(20))

        assert problemas_png(dados) == [f"entrelaçamento {entrelacado} inválido (só 0 ou 1)"]

    @pytest.mark.parametrize(
        ("tipo_cor", "profundidade"), [(2, 4), (2, 1), (3, 16), (4, 4), (6, 2), (0, 3), (0, 32)], ids=lambda v: str(v)
    )
    def test_an_invalid_bit_depth_for_the_color_type_is_reported(self, tipo_cor, profundidade):
        dados = _montar_png(
            (3, 2, profundidade, tipo_cor, 0, 0, 0), bytes(40), paleta=bytes(6) if tipo_cor == 3 else None
        )

        assert "inválida para o tipo de cor" in problemas_png(dados)[0]

    def test_an_unknown_color_type_is_reported(self):
        assert "inválido" in problemas_png(_montar_png((3, 2, 8, 5, 0, 0, 0), bytes(20)))[0]

    def test_a_palette_image_without_plte_is_reported(self):
        assert problemas_png(_montar_png((3, 2, 8, 3, 0, 0, 0), bytes(8))) == ["tipo de cor 3 sem PLTE"]

    def test_a_plte_after_the_first_idat_is_reported(self):
        dados = _montar_png((3, 2, 8, 3, 0, 0, 0), bytes(8), paleta=bytes(6), paleta_depois=True)

        assert problemas_png(dados) == ["PLTE depois do primeiro IDAT"]

    @pytest.mark.parametrize(
        "paleta", [b"", bytes(4), bytes(3 * 300)], ids=["vazia", "nao-multipla-de-3", "grande-demais"]
    )
    def test_an_invalid_plte_is_reported(self, paleta):
        assert "PLTE com" in problemas_png(_montar_png((3, 2, 8, 3, 0, 0, 0), bytes(8), paleta=paleta))[0]

    @pytest.mark.parametrize("tipo_cor", [0, 4])
    def test_a_plte_in_a_grayscale_image_is_reported(self, tipo_cor):
        dados = _montar_png(
            (3, 2, 8, tipo_cor, 0, 0, 0), bytes(3 * 2 * (1 + 3 * CANAIS[tipo_cor] // 3)), paleta=bytes(6)
        )

        assert "não é permitida" in problemas_png(dados)[0]

    def test_a_png_without_any_idat_is_reported(self):
        assert problemas_png(_montar_png((3, 2, 8, 2, 0, 0, 0), b"", com_idat=False)) == ["IDAT ausente"]

    @pytest.mark.parametrize("filtro", [5, 6, 255])
    def test_a_filter_byte_outside_0_to_4_is_reported(self, filtro):
        bruto = bytearray(20)  # 3x2 RGB: 2 linhas de 1 + 9 bytes
        bruto[10] = filtro  # byte de filtro da 2ª linha

        assert problemas_png(_montar_png((3, 2, 8, 2, 0, 0, 0), bytes(bruto))) == [
            f"byte de filtro {filtro} fora de 0..4"
        ]

    @pytest.mark.parametrize("filtro", [0, 1, 2, 3, 4])
    def test_every_filter_type_from_0_to_4_is_accepted(self, filtro):
        bruto = bytearray(20)
        bruto[0], bruto[10] = filtro, filtro

        assert problemas_png(_montar_png((3, 2, 8, 2, 0, 0, 0), bytes(bruto))) == []

    def test_a_bad_filter_byte_in_a_later_adam7_pass_is_reported(self):
        largura, altura = 13, 9
        passadas = _passadas(largura, altura, 2, 8, 1)
        bruto = bytearray(_tamanho_esperado(largura, altura, 2, 8, 1))
        bruto[sum(linhas * (1 + por_linha) for linhas, por_linha in passadas[:-1])] = 9  # 1ª linha da última passada

        assert problemas_png(_montar_png((largura, altura, 8, 2, 0, 0, 1), bytes(bruto))) == [
            "byte de filtro 9 fora de 0..4"
        ]

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

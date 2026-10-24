"""KI-27 — caracterização de `empiremuse/utils/music/track_encoder.py` (codificação base64 de faixas para o Lavalink).

Um decodificador mínimo, escrito aqui, lê o binário gerado e confere campo a campo.
"""

import struct
from base64 import b64decode

import pytest

from empiremuse.utils.music import track_encoder as enc

V2 = {
    "title": "Título",
    "author": "Autor",
    "length": 123456,
    "identifier": "abc123",
    "isStream": False,
    "uri": "https://exemplo.test/faixa",
    "sourceName": "http",
    "position": 7,
}
V3 = {**V2, "artworkUrl": "https://exemplo.test/capa.png", "isrc": "BR1234567890"}


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, n):
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return chunk

    def byte(self):
        return self.take(1)[0]

    def short(self):
        return struct.unpack(">H", self.take(2))[0]

    def long(self):
        return struct.unpack(">Q", self.take(8))[0]

    def boolean(self):
        return self.byte() == 1

    def utf(self):
        return self.take(self.short()).decode("utf8")

    def nullable_utf(self):
        return self.utf() if self.boolean() else None


def open_message(encoded: str) -> Reader:
    raw = b64decode(encoded)
    flags = struct.unpack(">i", raw[:4])[0]
    assert flags & (1 << 30), "flag de versão ausente"
    assert flags & ~(1 << 30) == len(raw) - 4, "tamanho declarado diferente do corpo"
    return Reader(raw[4:])


class TestDataWriter:
    def test_utf_longer_than_65535_bytes_overflows(self):
        with pytest.raises(OverflowError):
            enc.DataWriter().write_utf("a" * 65536)


class TestEncodeTrackV2:
    def test_layout(self):
        reader = open_message(enc.encode_track_v2(V2))
        assert reader.byte() == 2
        assert reader.utf() == "Ttulo"  # acentos são removidos do título (ascii, errors=ignore)
        assert reader.utf() == "Autor"
        assert reader.long() == 123456
        assert reader.utf() == "abc123"
        assert reader.boolean() is False
        assert reader.nullable_utf() == "https://exemplo.test/faixa"
        assert reader.utf() == "http"
        assert reader.long() == 7
        assert reader.pos == len(reader.data)


class TestEncodeTrackV3:
    def test_null_isrc_is_absent(self):
        reader = open_message(enc.encode_track_v3({**V3, "isrc": None}))
        reader.byte(), reader.utf(), reader.utf(), reader.long(), reader.utf(), reader.boolean(), reader.nullable_utf()
        reader.nullable_utf()
        assert reader.nullable_utf() is None


class TestEncodeTrack:
    def test_minimal_track_uses_version_2(self):
        version, encoded = enc.encode_track(V2)
        assert version == 2 and encoded == enc.encode_track_v2(V2)

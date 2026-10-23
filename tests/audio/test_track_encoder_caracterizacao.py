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
    def test_primitives_are_big_endian(self):
        writer = enc.DataWriter()
        writer.write_boolean(True)
        writer.write_unsigned_short(0x0102)
        writer.write_int(-2)
        writer.write_long(3)
        body = open_message_from(writer)
        assert body == b"\x01" + b"\x01\x02" + b"\xff\xff\xff\xfe" + (3).to_bytes(8, "big")

    def test_nullable_utf_writes_a_presence_flag(self):
        writer = enc.DataWriter()
        writer.write_nullable_utf(None)
        writer.write_nullable_utf("")
        writer.write_nullable_utf("ok")
        assert open_message_from(writer) == b"\x00" + b"\x00" + b"\x01\x00\x02ok"

    def test_utf_longer_than_65535_bytes_overflows(self):
        with pytest.raises(OverflowError):
            enc.DataWriter().write_utf("a" * 65536)

    def test_utf_exactly_at_the_limit_is_accepted(self):
        writer = enc.DataWriter()
        writer.write_utf("a" * 65535)
        assert len(open_message_from(writer)) == 2 + 65535

    def test_multibyte_text_is_measured_in_bytes(self):
        writer = enc.DataWriter()
        writer.write_utf("é")
        assert open_message_from(writer) == b"\x00\x02" + "é".encode("utf8")

    def test_missing_marker_reports_an_ellipsis(self):
        assert repr(enc.MISSING) == "..."


def open_message_from(writer: enc.DataWriter) -> bytes:
    raw = writer.finish()
    flags = struct.unpack(">i", raw[:4])[0]
    assert flags == (len(raw) - 4) | (1 << 30)
    return raw[4:]


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

    def test_null_uri_is_encoded_as_absent(self):
        reader = open_message(enc.encode_track_v2({**V2, "uri": None}))
        reader.byte(), reader.utf(), reader.utf(), reader.long(), reader.utf(), reader.boolean()
        assert reader.nullable_utf() is None

    def test_source_encoder_is_called_only_for_the_matching_source(self):
        calls = []

        def extra(writer, track):
            calls.append(track["sourceName"])
            writer.write_utf("extra")

        enc.encode_track_v2(V2, {"outra": extra})
        assert calls == []
        reader = open_message(enc.encode_track_v2(V2, {"http": extra}))
        assert calls == ["http"]
        reader.byte(), reader.utf(), reader.utf(), reader.long(), reader.utf(), reader.boolean(), reader.nullable_utf()
        assert reader.utf() == "http" and reader.utf() == "extra" and reader.long() == 7

    def test_requires_the_v2_keys(self):
        with pytest.raises(AssertionError):
            enc.encode_track_v2({"title": "x"})


class TestEncodeTrackV3:
    def test_layout_adds_artwork_and_isrc(self):
        reader = open_message(enc.encode_track_v3(V3))
        assert reader.byte() == 3
        reader.utf(), reader.utf(), reader.long(), reader.utf(), reader.boolean(), reader.nullable_utf()
        assert reader.nullable_utf() == "https://exemplo.test/capa.png"
        assert reader.nullable_utf() == "BR1234567890"
        assert reader.utf() == "http"
        assert reader.long() == 7

    def test_null_isrc_is_absent(self):
        reader = open_message(enc.encode_track_v3({**V3, "isrc": None}))
        reader.byte(), reader.utf(), reader.utf(), reader.long(), reader.utf(), reader.boolean(), reader.nullable_utf()
        reader.nullable_utf()
        assert reader.nullable_utf() is None

    def test_source_encoder_is_applied(self):
        encoded = enc.encode_track_v3(V3, {"http": lambda writer, track: writer.write_utf("extra")})
        assert b"extra" in b64decode(encoded)

    def test_requires_the_v3_keys(self):
        with pytest.raises(AssertionError):
            enc.encode_track_v3(V2)


class TestEncodeTrack:
    def test_full_track_uses_version_3(self):
        version, encoded = enc.encode_track(V3)
        assert version == 3 and encoded == enc.encode_track_v3(V3)

    def test_minimal_track_uses_version_2(self):
        version, encoded = enc.encode_track(V2)
        assert version == 2 and encoded == enc.encode_track_v2(V2)

    def test_partial_v3_keys_fall_back_to_version_2(self):
        version, _ = enc.encode_track({**V2, "artworkUrl": None})
        assert version == 2

    def test_missing_required_keys_are_listed_in_the_error(self):
        track = {k: v for k, v in V2.items() if k not in ("title", "position")}
        with pytest.raises(Exception, match="missing keys") as info:
            enc.encode_track(track)
        assert "title" in str(info.value) and "position" in str(info.value)

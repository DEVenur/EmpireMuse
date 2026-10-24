"""KI-27 — caracterização de `errors.parse_error` e dos auxiliares de código de erro (`empiremuse/utils/music/errors.py`).

Fixa o texto mostrado ao usuário para cada tipo de erro conhecido, o tratamento de `.original` e o contrato de log.
"""

from types import SimpleNamespace

import pytest

from empiremuse.utils.music import errors
from empiremuse.wavelink import WavelinkException

CTX = SimpleNamespace(author=SimpleNamespace(mention="<@1>", voice=None))


def parse(error, ctx=CTX, **kwargs):
    return errors.parse_error(ctx, error, **kwargs)


def text(error, ctx=CTX):
    return parse(error, ctx)[0]


class TestNoPlayer:
    def test_without_voice_uses_the_generic_text(self):
        assert "player inicializado" in text(errors.NoPlayer())


class TestWavelinkErrors:
    @pytest.mark.parametrize(
        ("raw", "fragment"),
        [
            ("Unknown file format", "Não há suporte para o link especificado"),
            ("Who has blocked it in your country on copyright grounds", "região"),
        ],
    )
    def test_known_lavalink_messages(self, raw, fragment):
        assert fragment in text(WavelinkException(raw))

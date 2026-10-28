"""Emojis de aplicação (#130), E1 e E2: o mapa de reserva Unicode e a precedência de ``emoji(bot, nome)``.

Precedência: o ``emojis.json`` do dono (``bot.pool.emoji_data``) > o emoji de aplicação DESTE bot (``bot.app_emojis``) > Unicode. Nunca levanta.
"""

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from empiremuse.utils.music.app_emojis import APP_EMOJIS, emoji
from tests.support.emojis_app import NOMES

pytestmark = pytest.mark.critical

PADRAO_NOME = re.compile(r"^[a-z0-9_]{2,32}$")
ID_A, ID_B = 111111111111111111, 222222222222222222


def bot(app_emojis=None, emoji_data=None, **mais):
    return SimpleNamespace(
        app_emojis=app_emojis if app_emojis is not None else {},
        pool=SimpleNamespace(emoji_data=emoji_data or {}),
        **mais,
    )


class TestMapaDeReserva:
    def test_it_has_exactly_the_25_names(self):
        assert sorted(APP_EMOJIS) == sorted(NOMES) and len(NOMES) == 25

    @pytest.mark.parametrize("nome", NOMES)
    def test_each_name_matches_the_pattern_and_has_a_non_empty_unicode_fallback(self, nome):
        assert PADRAO_NOME.match(nome)
        reserva = APP_EMOJIS[nome]
        assert isinstance(reserva, str) and reserva.strip() and "<" not in reserva

    def test_a_name_outside_the_list_is_a_programming_error(self):
        with pytest.raises(KeyError):
            APP_EMOJIS["nome_que_nao_existe"]


class TestPrecedencia:
    def test_without_an_app_emoji_it_is_the_unicode_fallback(self):
        assert emoji(bot(), "music_queue") == APP_EMOJIS["music_queue"]

    def test_with_an_app_emoji_it_is_the_app_emoji(self):
        assert emoji(bot({"music_queue": f"<:music_queue:{ID_A}>"}), "music_queue") == f"<:music_queue:{ID_A}>"

    def test_an_animated_app_emoji_keeps_its_format(self):
        assert emoji(bot({"play": f"<a:play:{ID_A}>"}), "play") == f"<a:play:{ID_A}>"

    def test_the_owner_emojis_json_beats_both(self):
        dono = {"music_sources": {"youtube": "<:meu_youtube:333333333333333333>"}}

        resultado = emoji(bot({"youtube": f"<:youtube:{ID_A}>"}, dono), "youtube")

        assert resultado == "<:meu_youtube:333333333333333333>"

    def test_the_owner_value_applies_only_to_the_name_it_defines(self):
        dono = {"music_sources": {"youtube": "<:meu_youtube:333333333333333333>"}}

        assert emoji(bot({"spotify": f"<:spotify:{ID_A}>"}, dono), "spotify") == f"<:spotify:{ID_A}>"

    def test_only_this_bots_map_is_used_never_another_bots(self):
        a, b = bot({"stop": f"<:stop:{ID_A}>"}), bot({"stop": f"<:stop:{ID_B}>"})

        assert emoji(a, "stop") == f"<:stop:{ID_A}>" and emoji(b, "stop") == f"<:stop:{ID_B}>"

    def test_a_name_missing_from_this_bots_map_is_the_fallback_even_if_another_bot_has_it(self):
        outro = bot({"skip": f"<:skip:{ID_B}>"})

        assert emoji(bot(), "skip") == APP_EMOJIS["skip"] and outro.app_emojis["skip"]


class TestNuncaLevanta:
    @pytest.mark.parametrize("nome", NOMES)
    def test_a_bot_without_the_attribute_gives_the_fallback(self, nome):
        assert emoji(SimpleNamespace(), nome) == APP_EMOJIS[nome]

    @pytest.mark.parametrize(
        "mapa", [None, [], "texto", 5, {"stop": None}, {"stop": 7}, {"stop": ""}, {"stop": ["x"]}], ids=repr
    )
    def test_a_broken_app_emojis_gives_the_fallback(self, mapa):
        assert (
            emoji(SimpleNamespace(app_emojis=mapa, pool=SimpleNamespace(emoji_data={})), "stop") == APP_EMOJIS["stop"]
        )

    @pytest.mark.parametrize(
        "dados", [None, [], "x", 5, {"music_sources": None}, {"music_sources": []}, {"music_sources": "x"}], ids=repr
    )
    def test_a_broken_emoji_data_gives_the_fallback(self, dados):
        assert (
            emoji(SimpleNamespace(app_emojis={}, pool=SimpleNamespace(emoji_data=dados)), "youtube")
            == APP_EMOJIS["youtube"]
        )

    def test_a_bot_without_pool_gives_the_fallback(self):
        assert emoji(SimpleNamespace(app_emojis={}), "youtube") == APP_EMOJIS["youtube"]

    @pytest.mark.parametrize("nome", NOMES)
    def test_a_mock_bot_still_returns_a_string(self, nome):
        assert isinstance(emoji(MagicMock(), nome), str)

    def test_none_as_the_bot_gives_the_fallback(self):
        assert emoji(None, "stop") == APP_EMOJIS["stop"]


class TestEmojisJsonInvalido:
    """Um valor inválido no ``emojis.json`` cai no Unicode (ou no emoji de aplicação) sem quebrar o envio."""

    INVALIDOS = [123, 1.5, True, None, [], {}, "", "   ", "linha1\nlinha2", "com\rquebra"]

    @pytest.mark.parametrize("valor", INVALIDOS, ids=repr)
    def test_an_invalid_owner_value_falls_back_to_unicode(self, valor):
        resultado = emoji(bot({}, {"music_sources": {"youtube": valor}}), "youtube")

        assert resultado == APP_EMOJIS["youtube"]

    @pytest.mark.parametrize("valor", INVALIDOS, ids=repr)
    def test_an_invalid_owner_value_falls_back_to_the_app_emoji_when_there_is_one(self, valor):
        resultado = emoji(bot({"youtube": f"<:youtube:{ID_A}>"}, {"music_sources": {"youtube": valor}}), "youtube")

        assert resultado == f"<:youtube:{ID_A}>"

    def test_a_valid_unicode_owner_value_is_used(self):
        assert emoji(bot({}, {"music_sources": {"youtube": "🎬"}}), "youtube") == "🎬"

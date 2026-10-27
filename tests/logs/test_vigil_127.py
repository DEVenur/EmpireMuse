"""Item 7 (P3, #127, Vigil) — V-127-1 (código de voz fora da faixa), chave do agregador redigida e ``guild_extra`` que nunca levanta.

V-127-1 (AL5): o ``code`` do ``WebsocketClosed`` vem do JSON de um nó de terceiro; como ``aggregate_key`` só vale ``str(code)`` se for ``int`` (não
``bool``) entre 1000 e 4999; qualquer outra coisa cai na chave ``other``. Chave do agregador: sai de ``redact(sanitize_text(...))`` e o corte em 64
vale DEPOIS da redação. ``guild_extra``: ``'9' * 5000`` estoura o limite do ``int()`` (4300 dígitos) e tem que dar ``{}``.
"""

# ruff: noqa: F811, F401 - fixtures reaproveitadas de outros arquivos de teste

import logging

import empiremuse.wavelink as wavelink

import pytest

from empiremuse.logs.context import guild_extra
from empiremuse.logs.redact import register_secret
from empiremuse.logs.setup import flush_logging
from empiremuse.utils.music.models.player_events import PlayerEventsMixin
from tests.logs.test_integration import agregador_instalado, montar, relogio, textos_da_chave  # noqa: F401 - fixtures reaproveitadas
from tests.logs.test_k16_chave_de_agregacao import Destinos, destinos, fechou, jogador_de_voz  # noqa: F401

pytestmark = pytest.mark.critical

LOG = "empiremuse.wavelink"


# ============================================================================ V-127-1 — o código de voz


@pytest.mark.asyncio
class TestCodigoDeVoz:
    async def disparar(self, codigos, canal=10):
        for codigo in codigos:
            jogador = jogador_de_voz(canal)
            await PlayerEventsMixin.hook(jogador, fechou(codigo, jogador))

    async def test_a_thousand_distinct_out_of_range_codes_give_one_line_and_a_summary_of_999(self, destinos):
        await self.disparar(range(10_000, 11_000))

        for texto in destinos.textos():
            assert texto.count("Erro no canal de voz") == 2 and "repetida 999×" in texto

    @pytest.mark.parametrize(
        "lixo",
        [
            ["abc1", "abc2", "abc3"],
            [1.5, 2.5, 3.5],
            [None, None, None],
            [0, -1, -4006],
            [99_999, 100_000, 7],
            [[1], [2], [3]],
        ],
        ids=repr,
    )
    async def test_non_int_or_out_of_range_codes_all_land_on_the_other_key(self, destinos, lixo):
        await self.disparar(lixo)

        for texto in destinos.textos():
            assert "repetida 2×" in texto

    async def test_a_bool_is_not_an_int_code(self, destinos):
        await self.disparar([True, False, True])

        for texto in destinos.textos():
            assert "repetida 2×" in texto

    @pytest.mark.parametrize(("baixo", "alto"), [(999, 5000), (0, 99_999)], ids=["bordas", "extremos"])
    async def test_the_range_edges_outside_are_other(self, destinos, baixo, alto):
        await self.disparar([baixo, alto])

        for texto in destinos.textos():
            assert "repetida 1×" in texto

    async def test_two_known_codes_keep_their_own_keys(self, destinos):
        await self.disparar([1001, 4021])

        for texto in destinos.textos():
            assert "code 1001" in texto and "code 4021" in texto and "repetida" not in texto

    async def test_a_real_code_and_an_out_of_range_one_are_different_keys(self, destinos):
        await self.disparar([4006, 77_777])

        for texto in destinos.textos():
            assert "code 4006" in texto and "code 77777" in texto and "repetida" not in texto

    async def test_4006_and_4014_still_give_two_lines(self, destinos):
        await self.disparar([4006, 4014])

        for texto in destinos.textos():
            assert "code 4006" in texto and "code 4014" in texto and "repetida" not in texto

    async def test_the_same_code_in_different_channels_still_aggregates(self, destinos):
        for canal in (10, 11, 12):
            await self.disparar([4006], canal=canal)

        for texto in destinos.textos():
            assert "repetida 2×" in texto


# ============================================================================ chave do agregador: redigida, e o corte depois


def avisar(identificador, chave):
    logging.getLogger(LOG).warning("nó %s caiu", identificador, extra={"aggregate_key": chave})


class TestChaveRedigida:
    SEG = "segredo-na-chave-do-agregador-K16-q"

    @pytest.fixture
    def instalado(self, montar):  # noqa: F811
        destinos = montar([])
        register_secret(self.SEG)
        return destinos, agregador_instalado()

    def test_a_registered_secret_never_stays_raw_in_the_bucket_keys(self, instalado):
        destinos, agregador = instalado

        avisar("no-1", f"no-{self.SEG}-fim")

        textos = textos_da_chave(agregador)
        assert textos and all(self.SEG not in texto for texto in textos)

    def test_two_keys_that_differ_only_in_the_registered_secret_aggregate(self, instalado):
        destinos, agregador = instalado
        outro = "outro-segredo-na-chave-K16-w"
        register_secret(outro)

        avisar("no-1", f"no-{self.SEG}-fim")
        avisar("no-2", f"no-{outro}-fim")

        for texto in destinos.ambos():
            assert "nó no-1 caiu" in texto and "nó no-2 caiu" not in texto

    def test_the_cut_at_64_happens_after_the_redaction(self, instalado):
        destinos, agregador = instalado

        avisar("no-1", "x" * 57 + self.SEG + "-cauda")

        for texto in textos_da_chave(agregador):
            assert self.SEG[:5] not in texto and self.SEG[-5:] not in texto

    def test_control_characters_are_still_sanitised_in_the_redacted_key(self, instalado):
        destinos, agregador = instalado

        avisar("no-1", f"a\x1b[2J{self.SEG}\r\nz")

        for texto in textos_da_chave(agregador):
            assert not any(c in texto for c in ("\x1b", "\r", "\n")) and self.SEG not in texto

    def test_a_key_without_secrets_is_unchanged_in_behaviour(self, instalado):
        destinos, agregador = instalado

        avisar("no-1", "chave-normal")
        avisar("no-2", "chave-normal")
        avisar("no-3", "outra-chave")
        flush_logging()

        for texto in destinos.ambos():
            assert "nó no-3 caiu" in texto and "nó no-2 caiu" not in texto and "repetida 1×" in texto

    def test_the_key_never_shows_up_in_the_output_even_with_a_secret(self, instalado):
        destinos, agregador = instalado

        avisar("no-1", f"visivel-{self.SEG}")

        for texto in destinos.ambos():
            assert self.SEG not in texto and "visivel-" not in texto


# ============================================================================ guild_extra nunca levanta


class TestGuildExtra:
    @pytest.mark.parametrize("digitos", [5000, 4301, 4300, 100, 21])
    def test_a_digit_string_longer_than_a_snowflake_gives_nothing_and_never_raises(self, digitos):
        assert guild_extra("9" * digitos) == {}

    @pytest.mark.parametrize("digitos", [1, 15, 18, 19, 20])
    def test_up_to_twenty_ascii_digits_is_an_int(self, digitos):
        valor = "9" * digitos

        resultado = guild_extra(valor)

        assert resultado == {"guild": int(valor)} and type(resultado["guild"]) is int

    @pytest.mark.parametrize(
        "valor",
        [True, False, "-5", "+5", " 12 ", "１２３４５", "12abc", "", "   ", None, 1.5, [1], b"123", object()],
        ids=repr,
    )
    def test_everything_else_stays_empty_and_never_raises(self, valor):
        assert guild_extra(valor) == {}

    def test_a_real_int_is_kept(self):
        assert guild_extra(123456789012345678) == {"guild": 123456789012345678}

    def test_the_giant_string_does_not_slow_down_or_blow_the_int_limit(self):
        assert guild_extra("9" * 1_000_000) == {}


@pytest.mark.asyncio
async def test_a_giant_session_id_does_not_stop_the_resume(console_de_sessao):
    from tests.logs.test_achados_127 import cog_de_sessoes

    cog = cog_de_sessoes(mongo=[{"_id": "9" * 5000}, {"_id": "123456789012345678"}])

    await cog.resume_players()

    assert "Falha ao retomar players" not in console_de_sessao.getvalue()
    assert cog.bot.player_resumed is True


@pytest.fixture
def console_de_sessao():
    import io

    from empiremuse.logs.setup import configure_logging
    from empiremuse.logs.settings import LogSettings
    from tests.logs.apoio import Relogio

    saida = io.StringIO()
    configure_logging(LogSettings(logging.INFO, False, False, frozenset(), 300), [], stream=saida, clock=Relogio())
    return saida


# ============================================================================ V-127-1 (resto): só os códigos CONHECIDOS têm chave própria; a razão é cortada

CODIGOS_CONHECIDOS = [
    *range(1001, 1016),
    *range(4000, 4022),
]  # 1000 e 4022 saem antes do aviso; 1000-1015 (RFC 6455), 4000-4022 (voz)


@pytest.mark.asyncio
class TestSoCodigosConhecidos:
    async def disparar(self, codigos, canal=10):
        for codigo in codigos:
            jogador = jogador_de_voz(canal)
            await PlayerEventsMixin.hook(jogador, fechou(codigo, jogador))

    async def test_a_thousand_distinct_codes_in_the_unassigned_gaps_all_land_on_the_other_key(self, destinos):
        await self.disparar([*range(1016, 1516), *range(4023, 4523)])

        for texto in destinos.textos():
            assert texto.count("Erro no canal de voz") == 2 and "repetida 999×" in texto

    @pytest.mark.parametrize(
        "faixa", [range(1016, 4000), range(4023, 5000), range(5000, 5100)], ids=["1016-3999", "4023-4999", "5000+"]
    )
    async def test_every_integer_outside_the_known_sets_aggregates_together(self, destinos, faixa):
        await self.disparar(list(faixa)[:50])

        for texto in destinos.textos():
            assert "repetida 49×" in texto

    async def test_each_known_code_gets_its_own_line(self, destinos):
        await self.disparar(CODIGOS_CONHECIDOS)

        for texto in destinos.textos():
            assert texto.count("Erro no canal de voz") == len(CODIGOS_CONHECIDOS) and "repetida" not in texto
            assert all(f"code {codigo}," in texto for codigo in CODIGOS_CONHECIDOS)

    async def test_a_known_and_an_unknown_code_are_different_keys(self, destinos):
        await self.disparar([4006, 4023])

        for texto in destinos.textos():
            assert "code 4006" in texto and "code 4023" in texto and "repetida" not in texto

    async def test_4006_and_4014_keep_two_lines_and_non_ints_stay_on_other(self, destinos):
        await self.disparar([4006, 4014, "abc", 1.5, None, True])

        for texto in destinos.textos():
            assert "code 4006" in texto and "code 4014" in texto and "repetida 3×" in texto


def fechou_com(codigo, razao, jogador):
    return wavelink.WebsocketClosed({"player": jogador, "reason": razao, "code": codigo, "guildID": 1})


@pytest.mark.asyncio
class TestRazaoDoNo:
    async def linhas(self, destinos, razao):
        jogador = jogador_de_voz(10)
        await PlayerEventsMixin.hook(jogador, fechou_com(4006, razao, jogador))
        return [linha for texto in destinos.textos() for linha in texto.splitlines() if "Erro no canal de voz" in linha]

    async def test_a_one_megabyte_reason_is_cut_at_a_thousand_characters(self, destinos):
        for linha in await self.linhas(destinos, "R" * 1_000_000):
            assert len(linha) <= 1500 and "R" * 1000 in linha and "R" * 1001 not in linha

    async def test_control_characters_in_the_reason_are_neutralised(self, destinos):
        for linha in await self.linhas(destinos, "ruim\x1b[2Jcom\rcontroles\u202e"):
            assert not any(c in linha for c in ("\x1b", "\r", "\u202e")) and "ruim" in linha

    async def test_a_short_reason_comes_out_whole(self, destinos):
        for linha in await self.linhas(destinos, "motivo curto e inteiro"):
            assert "motivo curto e inteiro" in linha

    async def test_a_reason_that_is_not_text_does_not_break_the_log(self, destinos):
        for linha in await self.linhas(destinos, None):
            assert "Erro no canal de voz" in linha

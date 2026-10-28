"""Item 7 (P3, K16, #127) — ``extra={"aggregate_key": str}``: 7º campo OPCIONAL da chave do agregador.

Só ``str`` não vazia, cortada em 64 caracteres e passada por ``sanitize_value``; qualquer outro tipo (int, None, bytes, list, str vazia) vale como
ausente. Nunca é emitida. Sem o extra nada muda (B7/B8/K8). Os produtores: ``wavelink/node.py`` e ``music_cog/nodes.py`` (``node.identifier``) e
``player_events.py`` (``str(event.code)``): dois nós ou dois códigos diferentes não escondem um ao outro; o mesmo continua agregando.
``configure_logging`` real (console + arquivo), relógio injetado, nada dorme.
"""

import io
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import empiremuse.wavelink as wavelink
from empiremuse.logs.setup import configure_logging, flush_logging
from empiremuse.logs.settings import LogSettings
from empiremuse.music_cog.nodes import NodesMixin
from empiremuse.utils.music.models.player_events import PlayerEventsMixin
from empiremuse.wavelink import node as node_module
from tests.logs.apoio import Relogio
from tests.logs.test_player_events import cog_de_nos, no_fisico
from tests.pool.test_logs_sem_segredo import node_falso

pytestmark = pytest.mark.critical

LOG = "empiremuse.wavelink"


class Destinos:
    def __init__(self, tmp_path) -> None:
        self.console = io.StringIO()
        self.relogio = Relogio()
        configure_logging(
            LogSettings(logging.INFO, False, True, frozenset(), 300),
            [],
            stream=self.console,
            logs_dir=tmp_path / ".logs",
            clock=self.relogio,
        )
        self.arquivo = tmp_path / ".logs" / "disnake.log"

    def textos(self) -> list[str]:
        flush_logging()
        return [self.console.getvalue(), self.arquivo.read_text(encoding="utf-8")]


@pytest.fixture
def destinos(tmp_path):
    return Destinos(tmp_path)


def avisar(identificador, chave=..., nivel=logging.WARNING):
    extra = {} if chave is ... else {"aggregate_key": chave}
    logging.getLogger(LOG).log(nivel, "nó %s caiu", identificador, extra=extra or None)


# ============================================================================ o agregador


class TestChaveOpcional:
    def test_two_different_keys_with_the_same_template_both_come_out_full(self, destinos):
        avisar("no-1", "A")
        avisar("no-2", "B")

        for texto in destinos.textos():
            assert "nó no-1 caiu" in texto and "nó no-2 caiu" in texto and "repetida" not in texto

    def test_the_same_key_a_hundred_times_aggregates(self, destinos):
        for n in range(100):
            avisar(f"no-{n}", "A")

        for texto in destinos.textos():
            assert texto.count("repetida 99×") == 1 and texto.count("nó no-0 caiu") == 2

    def test_without_the_extra_the_aggregation_is_unchanged(self, destinos):
        for n in range(50):
            avisar(f"no-{n}")

        for texto in destinos.textos():
            assert texto.count("repetida 49×") == 1 and "nó no-1 caiu" not in texto

    def test_a_record_with_a_key_and_one_without_are_different_keys(self, destinos):
        avisar("no-1")
        avisar("no-2", "A")

        for texto in destinos.textos():
            assert "nó no-1 caiu" in texto and "nó no-2 caiu" in texto

    @pytest.mark.parametrize("invalida", [7, None, b"bytes", ["lista"], ("t",), "", 3.5, True], ids=repr)
    def test_a_key_that_is_not_a_non_empty_str_is_ignored_like_no_key(self, destinos, invalida):
        avisar("no-1", invalida)
        avisar("no-2", invalida)
        avisar("no-3")

        for texto in destinos.textos():
            assert "nó no-1 caiu" in texto and "nó no-2 caiu" not in texto and "nó no-3 caiu" not in texto
            assert texto.count("repetida 2×") == 1

    def test_an_invalid_key_never_crashes_and_is_never_written(self, destinos):
        for invalida in (7, None, b"bytes-da-chave", ["lista-da-chave"]):
            avisar("no-x", invalida)

        for texto in destinos.textos():
            assert "bytes-da-chave" not in texto and "lista-da-chave" not in texto and "aggregate_key" not in texto

    def test_the_key_is_cut_at_64_characters(self, destinos):
        avisar("no-1", "x" * 64 + "A")
        avisar("no-2", "x" * 64 + "B")  # só difere depois do 64º: a mesma chave
        avisar("no-3", "x" * 63 + "C")  # difere dentro dos 64: outra chave

        for texto in destinos.textos():
            assert "nó no-1 caiu" in texto and "nó no-3 caiu" in texto and "nó no-2 caiu" not in texto

    def test_a_two_hundred_character_key_is_accepted_and_never_shown(self, destinos):
        chave = "k" * 200

        avisar("no-1", chave)
        avisar("no-1", chave)

        for texto in destinos.textos():
            assert "kkkkkkkkkk" not in texto and "repetida 1×" in texto

    def test_control_characters_in_the_key_are_sanitised_and_never_reach_the_output(self, destinos):
        avisar("no-1", "ch\x1b[2Jave\r\nX‮")
        avisar("no-2", "ch\x1b[2Jave\r\nX‮")

        for texto in destinos.textos():
            assert not any(c in texto for c in ("\x1b", "\r", "‮")) and "chave" not in texto
            assert "repetida 1×" in texto

    def test_keys_that_differ_only_by_what_the_sanitiser_unifies_are_the_same_key(self, destinos):
        avisar("no-1", "a\nb")
        avisar("no-2", "a⏎b")

        for texto in destinos.textos():
            assert "nó no-2 caiu" not in texto and "repetida 1×" in texto

    def test_the_key_never_appears_in_the_console_or_the_file(self, destinos):
        avisar("no-1", "SEGREDO-DA-CHAVE-Z9")
        avisar("no-2", "SEGREDO-DA-CHAVE-Z9")

        for texto in destinos.textos():
            assert "SEGREDO-DA-CHAVE-Z9" not in texto

    def test_info_and_debug_with_a_key_are_never_aggregated(self, destinos):
        for _ in range(3):
            avisar("no-1", "A", nivel=logging.INFO)

        for texto in destinos.textos():
            assert texto.count("nó no-1 caiu") == 3 and "repetida" not in texto

    def test_the_key_works_together_with_the_error_code_rule(self, destinos):
        log = logging.getLogger("empiremuse.errors")

        for codigo in ("ERR-000001", "ERR-000002"):
            log.error("Erro inesperado [%s]", codigo, extra={"error_code": codigo, "aggregate_key": "mesmo"})

        for texto in destinos.textos():
            assert "ERR-000001" in texto and "ERR-000002" in texto  # nenhum código some


# ============================================================================ produtores: nós


@pytest.mark.asyncio
class TestProdutoresDeNo:
    async def test_two_different_nodes_dropping_in_a_row_both_log(self, destinos):
        a, b = no_fisico("no-a"), no_fisico("no-b")
        cog = cog_de_nos(a, b)

        await NodesMixin.node_reconnect(cog, a)
        await NodesMixin.node_reconnect(cog, b)

        for texto in destinos.textos():
            assert "no-a" in texto and "no-b" in texto and "repetida" not in texto

    async def test_the_same_node_dropping_again_aggregates(self, destinos):
        node = no_fisico("no-instavel")
        cog = cog_de_nos(node)

        from datetime import datetime, timezone

        for _ in range(6):
            node._retry_dt, node._retry_count = datetime.fromtimestamp(0, timezone.utc), 0
            await NodesMixin.node_reconnect(cog, node)

        for texto in destinos.textos():
            assert "repetida 5×" in texto and texto.count("no-instavel") >= 2

    async def test_connect_failures_of_two_different_nodes_both_show_up(self, destinos, monkeypatch):
        monkeypatch.setattr(node_module.asyncio, "sleep", AsyncMock())
        um, outro = node_falso(), node_falso()
        um.identifier, outro.identifier = "NO-UM", "NO-DOIS"

        await um.connect()
        await outro.connect()

        for texto in destinos.textos():
            assert "[NO-UM]" in texto and "[NO-DOIS]" in texto

    async def test_connect_failures_of_the_same_node_still_aggregate(self, destinos, monkeypatch):
        monkeypatch.setattr(node_module.asyncio, "sleep", AsyncMock())
        node = node_falso()
        node.identifier = "NO-UM"

        for _ in range(5):
            node._is_connecting = False
            await node.connect()

        for texto in destinos.textos():
            assert "repetida" in texto


# ============================================================================ produtor: canal de voz


def jogador_de_voz(canal: int):
    return SimpleNamespace(
        guild=SimpleNamespace(me=SimpleNamespace(voice=None)),
        last_channel=SimpleNamespace(id=canal, mention=f"<#{canal}>"),
        keep_connected=False,
        node=SimpleNamespace(identifier="N1"),
        bot=SimpleNamespace(is_ready=lambda: True),
        is_closing=True,
        destroy=AsyncMock(),
        guild_id=1,
    )


def fechou(codigo: int, jogador):
    return wavelink.WebsocketClosed({"player": jogador, "reason": "motivo", "code": codigo, "guildID": 1})


@pytest.mark.asyncio
class TestProdutorDeVoz:
    async def test_two_different_close_codes_both_log(self, destinos):
        jogador = jogador_de_voz(10)

        await PlayerEventsMixin.hook(jogador, fechou(4006, jogador))
        await PlayerEventsMixin.hook(jogador, fechou(4014, jogador))

        for texto in destinos.textos():
            assert "code 4006" in texto and "code 4014" in texto and "repetida" not in texto

    async def test_the_same_code_in_different_channels_aggregates(self, destinos):
        for canal in (10, 11, 12):
            jogador = jogador_de_voz(canal)
            await PlayerEventsMixin.hook(jogador, fechou(4006, jogador))

        for texto in destinos.textos():
            assert texto.count("code 4006") == 2 and "repetida 2×" in texto  # a 1ª e a linha do resumo

    async def test_the_same_code_five_times_gives_one_line_and_a_summary(self, destinos):
        jogador = jogador_de_voz(10)

        for _ in range(5):
            await PlayerEventsMixin.hook(jogador, fechou(4006, jogador))

        for texto in destinos.textos():
            assert "repetida 4×" in texto

    async def test_the_aggregate_key_of_the_voice_error_is_not_shown(self, destinos):
        jogador = jogador_de_voz(10)

        await PlayerEventsMixin.hook(jogador, fechou(4006, jogador))

        for texto in destinos.textos():
            assert "aggregate_key" not in texto

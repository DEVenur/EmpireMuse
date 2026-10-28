"""2.1.2 — status automático do canal de voz no player (contrato I3): padrão D4 e emoji do bot emissor (VP1/VP2), permissão (VP3), palco (VP4),
``disable_voice_status`` (VP5/VP5b), throttle e bucket (VP7/VP9/VP12), reaplicação (VP10) e texto seguro (V-S1/I-S2 dentro do player).

Os métodos de voz do ``PlayerVoiceMixin`` e o ``process_destroy`` são os de produção (``tests/support/voz_auto.py``); relógio e esperas são falsos.
"""

import asyncio
import datetime
import importlib
import logging
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import disnake
import pytest

from empiremuse.utils.music.app_emojis import APP_EMOJIS
from empiremuse.utils.music.checks import VOICE_STATUS_PERMISSION
from tests.support.voz_auto import (
    ID_DO_CANAL,
    ID_DO_EMOJI,
    REQUISITANTE,
    BotDeVoz,
    JogadorDeVoz,
    RelogioFalso,
    assentar,
    canal_de_voz,
    executar,
    faixa,
    instalar_relogio,
    jogador,
    palco,
    servidor,
)

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]


@pytest.fixture
def relogio(monkeypatch: pytest.MonkeyPatch) -> RelogioFalso:
    return instalar_relogio(monkeypatch)


EMOJI_DO_APP = f"<:spotify:{ID_DO_EMOJI}>"
EMOJI_DO_DONO = "<:spotify_dono:999999999999999999>"
PADRAO_RENDERIZADO = "Tocando: Musica - Artista"


def regras() -> ModuleType:
    return importlib.import_module("empiremuse.rules.voice_status")


def cfg(*, permanente: bool = True, modelo: str | None = None) -> Any:
    r = regras()
    return r.VoiceStatusConfig(permanent=permanente, template=modelo or r.DEFAULT_VOICE_TEMPLATE)


def unidades(texto: str) -> int:
    return len(texto.encode("utf-16-le")) // 2


def com_troca_de_faixa(player: JogadorDeVoz, n: int) -> None:
    player.current = player.last_track = faixa(titulo=f"Musica {n}")


# ============================================================================ VP1 / VP2 — padrão e emoji do bot emissor


class TestPadraoEEmoji:
    async def test_applying_the_default_sends_the_d4_template_with_the_app_emoji_of_the_sending_bot(
        self, relogio: RelogioFalso
    ) -> None:
        player, bot = jogador(template="")
        bot.app_emojis = {"spotify": EMOJI_DO_APP}

        await executar(relogio, player.apply_permanent_voice_status(cfg()))

        assert bot.textos == [f"{EMOJI_DO_APP} {PADRAO_RENDERIZADO}"]
        assert player.stage_title_event is True and player.voice_status_permanent is True
        assert player.stage_title_template == regras().DEFAULT_VOICE_TEMPLATE

    async def test_each_bot_uses_its_own_app_emoji(self, relogio: RelogioFalso) -> None:
        a, bot_a = jogador(template="{track.emoji}")
        b, bot_b = jogador(template="{track.emoji}")
        bot_a.app_emojis = {"spotify": f"<:spotify:{ID_DO_EMOJI}>"}
        bot_b.app_emojis = {"spotify": f"<:spotify:{ID_DO_EMOJI + 1}>"}

        await executar(relogio, a.apply_permanent_voice_status(cfg(modelo="{track.emoji}")))
        await executar(relogio, b.apply_permanent_voice_status(cfg(modelo="{track.emoji}")))

        assert bot_a.textos == [f"<:spotify:{ID_DO_EMOJI}>"] and bot_b.textos == [f"<:spotify:{ID_DO_EMOJI + 1}>"]

    async def test_the_owner_emoji_beats_the_app_emoji(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        bot.pool.emoji_data = {"music_sources": {"spotify": EMOJI_DO_DONO}}
        bot.app_emojis = {"spotify": EMOJI_DO_APP}

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.emoji}")))

        assert bot.textos == [EMOJI_DO_DONO]

    async def test_without_owner_or_app_emoji_it_falls_back_to_unicode(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.emoji}")))

        assert bot.textos == [APP_EMOJIS["spotify"]]

    async def test_an_app_emoji_in_a_wrong_format_is_ignored(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        bot.app_emojis = {"spotify": "<:spotify:not-a-number>"}

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.emoji}")))

        assert bot.textos == [APP_EMOJIS["spotify"]]

    async def test_a_source_without_a_mapped_emoji_uses_the_generic_play_emoji(self, relogio: RelogioFalso) -> None:
        player, bot = jogador(atual=faixa(fonte="fonte-nova"))
        bot.app_emojis = {"play_source": f"<:play_source:{ID_DO_EMOJI}>"}

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.emoji}")))

        assert bot.textos == [f"<:play_source:{ID_DO_EMOJI}>"]


# ============================================================================ apply_permanent_voice_status — o "voltar ao permanente"


class TestAplicarOPermanente:
    async def test_it_turns_the_session_on_with_the_permanent_template_and_forces_a_send(
        self, relogio: RelogioFalso
    ) -> None:
        player, bot = jogador(template="outro modelo {track.title}")

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="Ouvindo {track.title}")))

        assert player.stage_title_template == "Ouvindo {track.title}" and player.stage_title_event is True
        assert bot.textos == ["Ouvindo Musica"] and bot.puts[0].canal == ID_DO_CANAL

    async def test_force_sends_even_when_the_text_equals_the_last_one(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        await relogio.avancar(6)

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))

        assert bot.textos == ["Musica", "Musica"]

    async def test_without_force_an_equal_text_is_not_sent_again(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        await relogio.avancar(6)

        await executar(relogio, player.update_stage_topic())

        assert bot.textos == ["Musica"]

    async def test_a_permanent_that_is_off_disables_and_clears_the_channel(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        await relogio.avancar(6)

        await executar(relogio, player.apply_permanent_voice_status(cfg(permanente=False, modelo="{track.title}")))

        assert player.stage_title_event is False and player.voice_status_permanent is False
        assert [p.status for p in bot.puts] == ["Musica", None] and player.last_stage_title == ""

    async def test_a_permanent_that_is_off_with_nothing_on_the_channel_sends_nothing(
        self, relogio: RelogioFalso
    ) -> None:
        player, bot = jogador()

        await executar(relogio, player.apply_permanent_voice_status(cfg(permanente=False)))

        assert bot.puts == [] and player.stage_title_event is False

    async def test_with_the_jitter_it_waits_up_to_the_resume_window_before_sending(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        tarefa = asyncio.ensure_future(player.apply_permanent_voice_status(cfg(modelo="{track.title}"), jitter=True))
        await assentar()

        await relogio.avancar(regras().VOICE_STATUS_RESUME_JITTER + 1)
        await tarefa

        assert bot.textos == ["Musica"]
        assert all(0 <= p <= regras().VOICE_STATUS_RESUME_JITTER for p in relogio.pedidos[:1])


# ============================================================================ VP3 — sem a permissão


class TestSemPermissao:
    async def test_no_put_one_notice_in_the_player_and_no_log(
        self, relogio: RelogioFalso, caplog: pytest.LogCaptureFixture
    ) -> None:
        player, bot = jogador(canal=canal_de_voz(permitido=False))

        with caplog.at_level(logging.DEBUG):
            await executar(relogio, player.apply_permanent_voice_status(cfg()))

        assert bot.puts == [] and player.stage_title_event is False
        assert len(player.avisos) == 1 and VOICE_STATUS_PERMISSION in player.avisos[0]
        assert [r for r in caplog.records if r.name.startswith("empiremuse")] == []

    async def test_the_notice_is_one_per_session(self, relogio: RelogioFalso) -> None:
        player, bot = jogador(canal=canal_de_voz(permitido=False))

        await executar(relogio, player.apply_permanent_voice_status(cfg()))
        await executar(relogio, player.apply_permanent_voice_status(cfg()))

        assert len(player.avisos) == 1 and bot.puts == []

    async def test_the_permission_is_rechecked_on_each_application(self, relogio: RelogioFalso) -> None:
        canal = canal_de_voz(permitido=False)
        player, bot = jogador(canal=canal)
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        canal.permissions_for.return_value = disnake.Permissions(1 << 48)

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))

        assert player.stage_title_event is True and bot.textos == ["Musica"]

    async def test_a_runtime_403_turns_the_session_off_with_one_notice_and_stops_the_reapplication(
        self, relogio: RelogioFalso
    ) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        bot.erros.append(
            disnake.Forbidden(type("R", (), {"status": 403, "reason": "x"})(), {"code": 50013, "message": "x"})
        )
        await relogio.avancar(regras().VOICE_STATUS_REAPPLY_INTERVAL + 1)

        quantos = len(bot.puts)
        await relogio.avancar(3 * regras().VOICE_STATUS_REAPPLY_INTERVAL)

        assert player.stage_title_event is False and len(bot.puts) == quantos
        assert len([a for a in player.avisos if "falta de permissão" in a]) == 1


# ============================================================================ VP4 — palco


class TestPalco:
    async def test_the_permanent_never_creates_or_edits_a_stage_instance(self, relogio: RelogioFalso) -> None:
        canal = palco()
        player, bot = jogador(canal=canal)

        await executar(relogio, player.apply_permanent_voice_status(cfg()))

        canal.create_instance.assert_not_awaited()
        assert bot.puts == [] and player.stage_title_event is False

    async def test_an_existing_instance_is_not_edited_either(self, relogio: RelogioFalso) -> None:
        canal = palco()
        canal.instance = type("I", (), {"edit": None})()
        canal.instance.edit = _espiao()
        player, bot = jogador(canal=canal)

        await executar(relogio, player.apply_permanent_voice_status(cfg()))

        canal.instance.edit.assert_not_awaited()
        assert bot.puts == []


def _espiao() -> AsyncMock:
    from unittest.mock import AsyncMock

    return AsyncMock()


# ============================================================================ VP5 / VP5b — desligar limpa o canal


class TestDesligar:
    async def test_it_sends_status_none_when_there_was_a_status(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))

        await executar(relogio, player.disable_voice_status())

        assert bot.limpezas and bot.limpezas[0].canal == ID_DO_CANAL
        assert player.stage_title_event is False and player.last_stage_title == ""

    async def test_it_is_idempotent(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        await executar(relogio, player.disable_voice_status())

        await executar(relogio, player.disable_voice_status())
        await executar(relogio, player.disable_voice_status())

        assert len(bot.limpezas) == 1

    async def test_with_nothing_on_the_channel_it_sends_nothing(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()

        await executar(relogio, player.disable_voice_status())

        assert bot.puts == [] and player.stage_title_event is False

    async def test_it_works_even_though_the_flag_is_already_false(self, relogio: RelogioFalso) -> None:
        """O bug de hoje: ``stage_title_event = False`` e só depois ``clear``, que retorna cedo e deixa o último status preso."""
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        player.stage_title_event = False

        await executar(relogio, player.disable_voice_status())

        assert len(bot.limpezas) == 1

    async def test_a_403_on_the_clear_is_swallowed_without_a_notice(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        bot.erros.append(
            disnake.Forbidden(type("R", (), {"status": 403, "reason": "x"})(), {"code": 50013, "message": "x"})
        )

        await executar(relogio, player.disable_voice_status())

        assert [a for a in player.avisos if "falta de permissão" in a] == []

    async def test_a_track_start_during_the_clear_does_not_rewrite_the_status(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        await relogio.avancar(6)
        bot.porta = asyncio.Event()

        limpeza = asyncio.ensure_future(player.disable_voice_status())
        await assentar()
        com_troca_de_faixa(player, 2)
        await executar(relogio, player.update_stage_topic())
        bot.porta.set()
        await limpeza
        await relogio.avancar(60)

        assert bot.textos == ["Musica"] and len(bot.limpezas) == 1

    async def test_a_pending_send_is_cancelled_by_the_clear(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        com_troca_de_faixa(player, 2)
        await executar(relogio, player.update_stage_topic())  # dentro da janela de 5 s: fica pendente

        await executar(relogio, player.disable_voice_status())
        await relogio.avancar(60)

        assert (
            bot.textos == ["Musica"]
            and player.voice_status_pending in (None, False)
            or player.voice_status_pending.done()
        )


# ============================================================================ VP7 / VP12 — throttle de borda por player


class TestThrottle:
    async def test_five_changes_inside_five_seconds_make_at_most_two_puts_and_the_last_text_wins(
        self, relogio: RelogioFalso
    ) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        for n in range(2, 6):
            await relogio.avancar(0.5)
            com_troca_de_faixa(player, n)
            await executar(relogio, player.update_stage_topic())

        await relogio.avancar(10)

        assert len(bot.puts) == 2 and bot.textos == ["Musica", "Musica 5"]

    async def test_the_pending_send_goes_out_at_the_end_of_the_window_not_before(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        com_troca_de_faixa(player, 2)
        await executar(relogio, player.update_stage_topic())

        await relogio.avancar(regras().VOICE_STATUS_MIN_INTERVAL - 0.5)
        assert len(bot.puts) == 1
        await relogio.avancar(1)

        assert bot.textos == ["Musica", "Musica 2"]

    async def test_the_second_send_waits_the_minimum_interval_from_the_last_put_sent(
        self, relogio: RelogioFalso
    ) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        await relogio.avancar(3)
        com_troca_de_faixa(player, 2)
        await executar(relogio, player.update_stage_topic())
        await relogio.avancar(10)

        assert bot.puts[1].quando - bot.puts[0].quando >= regras().VOICE_STATUS_MIN_INTERVAL

    async def test_a_change_after_the_window_goes_out_at_once(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        await relogio.avancar(6)

        com_troca_de_faixa(player, 2)
        await executar(relogio, player.update_stage_topic())

        assert bot.textos == ["Musica", "Musica 2"]

    @pytest.mark.parametrize("espaco", [0.0, 0.5])
    async def test_six_dead_tracks_skipped_in_a_row_plus_autoplay_make_at_most_two_puts(
        self, relogio: RelogioFalso, espaco: float
    ) -> None:
        """VP12: o caminho do #142 pula faixas mortas sem passar pela trava de comandos; só o throttle limita os PUTs."""
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        for n in range(2, 9):  # 6 puladas + a do autoplay
            if espaco:
                await relogio.avancar(espaco)
            com_troca_de_faixa(player, n)
            await executar(relogio, player.update_stage_topic())

        await relogio.avancar(10)

        assert len(bot.puts) <= 2 and bot.textos[-1] == "Musica 8"

    async def test_the_pending_send_rechecks_the_flag_when_it_fires(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        com_troca_de_faixa(player, 2)
        await executar(relogio, player.update_stage_topic())
        player.stage_title_event = False  # desligado por fora enquanto esperava

        await relogio.avancar(10)

        assert bot.textos == ["Musica"]

    async def test_the_destroy_cancels_the_pending_send(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        com_troca_de_faixa(player, 2)
        await executar(relogio, player.update_stage_topic())

        await player.process_destroy()
        await relogio.avancar(60)

        assert bot.textos == ["Musica"]


# ============================================================================ VP9 — bucket por bot


class TestBucketPorBot:
    async def test_many_players_of_one_bot_resuming_together_stay_inside_the_bot_rate(
        self, relogio: RelogioFalso
    ) -> None:
        bot = BotDeVoz()
        players = []
        for i in range(12):
            p = JogadorDeVoz(
                servidor(canal_de_voz(1000 + i), id_=5000 + i), bot, atual=faixa(f"M{i}"), template="{track.title}"
            )
            players.append(p)
        tarefas = [
            asyncio.ensure_future(p.apply_permanent_voice_status(cfg(modelo="{track.title}"), jitter=True))
            for p in players
        ]

        for _ in range(400):  # 40 s de relógio em passos de 0,1 s
            await relogio.avancar(0.1)

        await asyncio.gather(*tarefas)
        assert len(bot.puts) == 12
        quando = sorted(p.quando for p in bot.puts)
        for i, inicio in enumerate(quando):
            na_janela = [t for t in quando[i:] if t < inicio + 1.0]
            assert len(na_janela) <= regras().VOICE_STATUS_BOT_RATE, (
                f"{len(na_janela)} PUTs em 1 s a partir de {inicio}"
            )

    async def test_two_bots_do_not_share_the_bucket(self, relogio: RelogioFalso) -> None:
        a, b = BotDeVoz(id_=1), BotDeVoz(id_=2)
        pa, pb = jogador(bot=a)[0], jogador(bot=b)[0]

        await executar(relogio, pa.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        await executar(relogio, pb.apply_permanent_voice_status(cfg(modelo="{track.title}")))

        assert len(a.puts) == 1 and len(b.puts) == 1 and a.puts[0].quando == b.puts[0].quando


# ============================================================================ VP10 — reaplicação depois de edição manual


class TestReaplicacao:
    async def test_without_a_track_change_it_resends_the_same_text_every_interval(self, relogio: RelogioFalso) -> None:
        intervalo = regras().VOICE_STATUS_REAPPLY_INTERVAL
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))

        await relogio.avancar(intervalo - 1)
        assert len(bot.puts) == 1
        await relogio.avancar(2)
        assert bot.textos == ["Musica", "Musica"]
        await relogio.avancar(intervalo)

        assert bot.textos == ["Musica"] * 3

    async def test_there_is_a_single_background_task_per_player(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        antes = len(asyncio.all_tasks())
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        depois_do_primeiro = len(asyncio.all_tasks())
        for n in range(2, 6):
            com_troca_de_faixa(player, n)
            await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
            await relogio.avancar(6)

        assert len(asyncio.all_tasks()) <= depois_do_primeiro + 1 and depois_do_primeiro - antes <= 2

    async def test_it_stops_at_the_destroy(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))

        await player.process_destroy()
        await relogio.avancar(3 * regras().VOICE_STATUS_REAPPLY_INTERVAL)

        assert bot.textos == ["Musica"]

    async def test_it_stops_when_the_status_is_disabled(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))

        await executar(relogio, player.disable_voice_status())
        await relogio.avancar(3 * regras().VOICE_STATUS_REAPPLY_INTERVAL)

        assert bot.textos == ["Musica"]

    async def test_it_does_not_run_when_the_session_is_not_permanent(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        player.voice_status_permanent = False

        await relogio.avancar(3 * regras().VOICE_STATUS_REAPPLY_INTERVAL)

        assert bot.textos == ["Musica"]

    async def test_it_does_not_resend_an_empty_last_title(self, relogio: RelogioFalso) -> None:
        player, bot = jogador(atual=faixa())
        player.current = player.last_track = None
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        quantos = len(bot.textos)

        await relogio.avancar(3 * regras().VOICE_STATUS_REAPPLY_INTERVAL)

        assert len(bot.textos) == quantos == 0

    async def test_it_reads_the_channel_at_send_time_and_stops_without_a_voice_channel(
        self, relogio: RelogioFalso
    ) -> None:
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        player.guild.me.voice.channel = palco()

        await relogio.avancar(3 * regras().VOICE_STATUS_REAPPLY_INTERVAL)

        assert bot.textos == ["Musica"]

    async def test_the_reapplication_goes_through_the_throttle(self, relogio: RelogioFalso) -> None:
        intervalo = regras().VOICE_STATUS_REAPPLY_INTERVAL
        player, bot = jogador()
        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        await relogio.avancar(intervalo - 1)
        com_troca_de_faixa(player, 2)
        await executar(relogio, player.update_stage_topic())  # troca de faixa já reescreve
        await relogio.avancar(2)

        envios = [p.quando for p in bot.puts]
        assert all(b - a >= regras().VOICE_STATUS_MIN_INTERVAL for a, b in zip(envios, envios[1:]))


# ============================================================================ V-S1 / I-S2 dentro do player


class TestTextoSeguro:
    async def test_a_title_that_looks_like_a_placeholder_does_not_publish_the_requester_id(
        self, relogio: RelogioFalso
    ) -> None:
        player, bot = jogador(atual=faixa(titulo="{requester.id}"))

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title} / {requester.name}")))

        assert bot.textos == ["{requester.id} / Fulano"] and str(REQUISITANTE) not in bot.textos[0]

    async def test_mentions_and_everyone_in_the_title_are_inert(self, relogio: RelogioFalso) -> None:
        player, bot = jogador(atual=faixa(titulo="<@&1> @everyone <:x:1>", autor="@here"))

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.title} - {track.author}")))

        texto = bot.textos[0]
        assert "<" not in texto and "@" not in texto

    async def test_the_emoji_of_the_bot_stays_while_the_title_is_neutralised(self, relogio: RelogioFalso) -> None:
        player, bot = jogador(atual=faixa(titulo="<a:x:2>"))
        bot.app_emojis = {"spotify": EMOJI_DO_APP}

        await executar(relogio, player.apply_permanent_voice_status(cfg()))

        assert bot.textos[0].startswith(EMOJI_DO_APP) and "<a:x:2>" not in bot.textos[0]

    async def test_a_huge_title_is_cut_to_500_utf16_units_without_splitting_the_emoji(
        self, relogio: RelogioFalso
    ) -> None:
        player, bot = jogador(atual=faixa(titulo="😀" * 400))
        bot.app_emojis = {"spotify": EMOJI_DO_APP}

        await executar(relogio, player.apply_permanent_voice_status(cfg()))

        texto = bot.textos[0]
        assert unidades(texto) <= 500 and texto.endswith("...") and texto.startswith(EMOJI_DO_APP)

    async def test_the_cut_never_leaves_half_of_the_bot_emoji(self, relogio: RelogioFalso) -> None:
        player, bot = jogador(atual=faixa(titulo="a" * 600))
        bot.app_emojis = {"spotify": EMOJI_DO_APP}

        await executar(
            relogio, player.apply_permanent_voice_status(cfg(modelo="x" * 470 + " {track.emoji} {track.title}"))
        )

        texto = bot.textos[0]
        assert unidades(texto) <= 500
        assert "<" not in texto.replace(EMOJI_DO_APP, "")


# ============================================================================ VP12b — o balde esgotado não prende quem chama (condição D5 do Vigil)


def jogadores_do_mesmo_bot(n: int, bot: BotDeVoz) -> list[JogadorDeVoz]:
    return [
        JogadorDeVoz(
            servidor(canal_de_voz(1000 + i), id_=5000 + i), bot, atual=faixa(f"M{i}"), template="{track.title}"
        )
        for i in range(n)
    ]


class TestSemEsperaComOBaldeEsgotado:
    async def test_with_the_bucket_exhausted_a_track_change_returns_at_once_and_the_status_goes_out_later(
        self, relogio: RelogioFalso
    ) -> None:
        """O ``_he_track_start`` e o skip/seek só chamam ``update_stage_topic``: se ele esperasse o balde, o player travaria."""
        bot = BotDeVoz()
        jogadores = jogadores_do_mesmo_bot(9, bot)
        for jogador_ in jogadores:
            jogador_.stage_title_event = True
        esgotando = [asyncio.ensure_future(j.update_stage_topic()) for j in jogadores[:8]]
        await assentar()
        enviados = len(bot.puts)
        assert enviados < 8  # o balde (2 por segundo) não deixou todos saírem no mesmo instante
        novo = jogadores[8]
        instante = relogio.agora

        chamada = asyncio.ensure_future(novo.update_stage_topic())
        await assentar()

        assert chamada.done() and relogio.agora == instante, "a chamada esperou o balde em vez de voltar"
        assert "M8" not in bot.textos
        await relogio.avancar(30)
        await asyncio.gather(*esgotando)
        assert sorted(bot.textos) == sorted(f"M{i}" for i in range(9))

    async def test_the_forced_send_also_returns_at_once(self, relogio: RelogioFalso) -> None:
        bot = BotDeVoz()
        jogadores = jogadores_do_mesmo_bot(7, bot)
        for jogador_ in jogadores:
            jogador_.stage_title_event = True
        esgotando = [asyncio.ensure_future(j.update_stage_topic()) for j in jogadores[:6]]
        await assentar()

        chamada = asyncio.ensure_future(jogadores[6].update_stage_topic(force=True))
        await assentar()

        assert chamada.done() and "M6" not in bot.textos
        await relogio.avancar(30)
        await asyncio.gather(*esgotando)
        assert "M6" in bot.textos

    async def test_the_last_text_wins_while_the_bucket_is_exhausted(self, relogio: RelogioFalso) -> None:
        bot = BotDeVoz()
        jogadores = jogadores_do_mesmo_bot(7, bot)
        for jogador_ in jogadores:
            jogador_.stage_title_event = True
        esgotando = [asyncio.ensure_future(j.update_stage_topic()) for j in jogadores[:6]]
        await assentar()
        alvo = jogadores[6]

        for n in range(3):
            com_troca_de_faixa(alvo, n)
            chamada = asyncio.ensure_future(alvo.update_stage_topic())
            await assentar()
            assert chamada.done()
        await relogio.avancar(30)
        await asyncio.gather(*esgotando)

        assert [t for t in bot.textos if t.startswith("Musica")] == ["Musica 2"]

    async def test_after_the_tokens_return_everything_stays_inside_the_bot_rate(self, relogio: RelogioFalso) -> None:
        bot = BotDeVoz()
        jogadores = jogadores_do_mesmo_bot(10, bot)
        for jogador_ in jogadores:
            jogador_.stage_title_event = True
        tarefas = [asyncio.ensure_future(j.update_stage_topic()) for j in jogadores]
        for _ in range(200):
            await relogio.avancar(0.1)
        await asyncio.gather(*tarefas)

        quando = sorted(p.quando for p in bot.puts)
        assert len(quando) == 10
        for i, inicio in enumerate(quando):
            assert len([t for t in quando[i:] if t < inicio + 1.0]) <= regras().VOICE_STATUS_BOT_RATE


# ============================================================================ gate #145 — placeholders de ponta a ponta, destroy durante o jitter, palco em sessão

AGORA_FIXO = datetime.datetime(2026, 11, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)


class TestPlaceholdersNoPlayer:
    async def test_every_placeholder_is_filled_from_the_track(
        self, relogio: RelogioFalso, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(disnake.utils, "utcnow", lambda: AGORA_FIXO)
        player, bot = jogador(atual=faixa(titulo="Faixa", autor="Banda", playlist_name="Minha Lista"))
        player.position = 20_000
        bot.app_emojis = {"spotify": EMOJI_DO_APP}
        modelo = "{track.emoji}|{track.title}|{track.author}|{track.duration}|{track.source}|{track.playlist}|{requester.name}|{requester.id}|{track.timestamp}"

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo=modelo)))

        fim = int((AGORA_FIXO + datetime.timedelta(milliseconds=180_000)).timestamp())
        assert bot.textos == [f"{EMOJI_DO_APP}|Faixa|Banda|03:20|spotify|Minha Lista|Fulano|{REQUISITANTE}|<t:{fim}:R>"]

    async def test_a_track_without_a_playlist_says_so(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.playlist}")))

        assert bot.textos == ["Sem playlist"]

    async def test_a_paused_track_shows_paused_instead_of_a_countdown(
        self, relogio: RelogioFalso, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(disnake.utils, "utcnow", lambda: AGORA_FIXO)
        player, bot = jogador()
        player.auto_pause = player.paused = True

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.timestamp}")))

        assert bot.textos == [f"pausado <t:{int(AGORA_FIXO.timestamp())}:R>"]

    async def test_a_livestream_has_no_countdown_and_says_livestream_as_duration(self, relogio: RelogioFalso) -> None:
        player, bot = jogador(atual=faixa(is_stream=True))

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{track.duration}|{track.timestamp}")))

        assert bot.textos == ["Livestream|"]

    async def test_an_unknown_requester_is_a_neutral_name(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        player.guild.get_member = lambda _uid: None

        await executar(relogio, player.apply_permanent_voice_status(cfg(modelo="{requester.name}")))

        assert bot.textos == ["Membro desconhecido"]


class TestDestroyDuranteOJitter:
    async def test_a_player_closed_while_waiting_the_jitter_sends_nothing(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        tarefa = asyncio.ensure_future(player.apply_permanent_voice_status(cfg(modelo="{track.title}"), jitter=True))
        await assentar()

        player.is_closing = True
        await relogio.avancar(regras().VOICE_STATUS_RESUME_JITTER + 1)
        await tarefa

        assert bot.puts == []

    async def test_a_permanent_turned_off_while_waiting_the_jitter_sends_nothing(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        tarefa = asyncio.ensure_future(player.apply_permanent_voice_status(cfg(modelo="{track.title}"), jitter=True))
        await assentar()

        await executar(relogio, player.apply_permanent_voice_status(cfg(permanente=False)))
        await relogio.avancar(regras().VOICE_STATUS_RESUME_JITTER + 1)
        await tarefa

        assert bot.textos == [] and player.stage_title_event is False


class TestPalcoEmSessao:
    """No palco só vale o modo de sessão, como hoje; o ``render_voice_status`` (V-S1) vale lá também."""

    async def test_the_session_creates_the_instance_with_a_neutralised_text_within_110_chars(
        self, relogio: RelogioFalso
    ) -> None:
        canal = palco()
        player, bot = jogador(canal=canal, atual=faixa(titulo="{requester.id} <@&1> @everyone " + "x" * 200))
        player.stage_title_event = True
        player.stage_title_template = "{track.emoji} {track.title}"

        await executar(relogio, player.update_stage_topic())

        canal.create_instance.assert_awaited_once()
        topico = canal.create_instance.await_args.kwargs["topic"]
        assert (
            len(topico) <= 110 and str(REQUISITANTE) not in topico and "<@" not in topico and "@everyone" not in topico
        )
        assert bot.puts == []  # nada vai ao endpoint de status de voz

    async def test_with_an_instance_it_edits_it_and_not_twice_for_the_same_text(self, relogio: RelogioFalso) -> None:
        canal = palco()
        canal.instance = SimpleNamespace(edit=_espiao())
        player, _bot = jogador(canal=canal)
        player.stage_title_event = True

        await executar(relogio, player.update_stage_topic())
        await executar(relogio, player.update_stage_topic())

        canal.instance.edit.assert_awaited_once()

    async def test_without_manage_guild_the_stage_is_left_alone(self, relogio: RelogioFalso) -> None:
        canal = palco()
        player, _bot = jogador(canal=canal)
        player.stage_title_event = True
        player.guild.me.guild_permissions = disnake.Permissions.none()

        await executar(relogio, player.update_stage_topic())

        canal.create_instance.assert_not_awaited()


# ============================================================================ V-145-1 — desligar ou mover durante o 1º PUT em voo não deixa o status preso


def put_de(bot: BotDeVoz, canal: int) -> list[str | None]:
    return [p.status for p in bot.puts if p.canal == canal]


class TestPutEmVooEDesligar:
    async def test_turning_it_off_while_the_first_put_is_in_flight_clears_the_channel_when_it_lands(
        self, relogio: RelogioFalso
    ) -> None:
        player, bot = jogador()
        bot.reter_canal = ID_DO_CANAL
        envio = asyncio.ensure_future(player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        await assentar()
        assert put_de(bot, ID_DO_CANAL) == ["Musica"] and not envio.done()  # o texto está no ar, preso

        await executar(relogio, player.disable_voice_status())
        bot.porta_texto.set()
        await envio
        await relogio.avancar(10)

        assert put_de(bot, ID_DO_CANAL) == ["Musica", None], "o status ficou preso no canal"
        assert player.last_stage_title == "" and player.stage_title_event is False

    async def test_a_second_disable_after_it_landed_adds_nothing(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        bot.reter_canal = ID_DO_CANAL
        envio = asyncio.ensure_future(player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        await assentar()
        await executar(relogio, player.disable_voice_status())
        bot.porta_texto.set()
        await envio
        await relogio.avancar(10)

        await executar(relogio, player.disable_voice_status())
        await relogio.avancar(10)

        assert put_de(bot, ID_DO_CANAL) == ["Musica", None]

    async def test_without_turning_it_off_the_normal_flow_is_unchanged(self, relogio: RelogioFalso) -> None:
        player, bot = jogador()
        bot.reter_canal = ID_DO_CANAL
        envio = asyncio.ensure_future(player.apply_permanent_voice_status(cfg(modelo="{track.title}")))
        await assentar()

        bot.porta_texto.set()
        await envio
        await relogio.avancar(10)

        assert put_de(bot, ID_DO_CANAL) == ["Musica"]
        assert player.last_stage_title == "Musica" and player.stage_title_event is True

    async def test_turning_it_off_for_a_channel_that_never_got_a_text_sends_nothing(
        self, relogio: RelogioFalso
    ) -> None:
        player, bot = jogador()

        await executar(relogio, player.disable_voice_status())
        await relogio.avancar(10)

        assert bot.puts == []

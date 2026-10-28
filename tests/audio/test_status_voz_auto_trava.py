"""2.1.2 (I7/VP11) — a trava de comandos com o status automático ligado: 5 s em canal de voz (era 30), 120 s no palco (inalterado).

O ``check_stage_topic`` (skip, skipto, back, voteskip, seek…) e o ``check_stage_title`` do forceplay do embed usam UMA função só,
``checks.voice_status_lock_remaining``; o dono do bot é isento e as mensagens continuam as mesmas. O relógio é o ``disnake.utils.utcnow`` congelado.
"""

import asyncio
import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse.music_cog.controller_dispatch import ControllerDispatchMixin
from empiremuse.utils.music import checks
from empiremuse.utils.music.errors import GenericError

pytestmark = pytest.mark.critical

AGORA = datetime.datetime(2026, 11, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
GID = 100


@pytest.fixture(autouse=True)
def _tempo_parado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: AGORA)


def jogador(canal_spec: type, *, decorrido: float, ligado: bool = True) -> SimpleNamespace:
    canal = MagicMock(spec=canal_spec)
    me = SimpleNamespace(voice=SimpleNamespace(channel=canal))
    return SimpleNamespace(
        guild=SimpleNamespace(me=me),
        stage_title_event=ligado,
        start_time=AGORA - datetime.timedelta(seconds=decorrido),
        current=SimpleNamespace(requester=1, info={"sourceName": "youtube"}),
    )


def inter(player: SimpleNamespace, *, dono: bool = False) -> SimpleNamespace:
    bot = SimpleNamespace(
        music=SimpleNamespace(players={GID: player}),
        config={"YOUTUBE_TRACK_COOLDOWN": 10},
        is_owner=AsyncMock(return_value=dono),
    )
    return SimpleNamespace(guild_id=GID, bot=bot, author=SimpleNamespace(id=1, mention="<@1>"))


def comando(player: SimpleNamespace, *, dono: bool = False) -> object:
    """O ``check_stage_topic`` dos comandos; devolve ``True`` ou levanta ``GenericError``."""
    return asyncio.run(checks.check_stage_topic().predicate(inter(player, dono=dono)))


def forceplay(player: SimpleNamespace, *, dono: bool = False) -> None:
    """O ``check_stage_title`` do forceplay do embed; levanta ``GenericError`` ou volta."""
    cog = ControllerDispatchMixin()
    i = inter(player, dono=dono)
    asyncio.run(cog.check_stage_title(i, i.bot, player))


class TestFuncaoUnica:
    @pytest.mark.parametrize(("decorrido", "restante"), [(0, 5), (1, 4), (4, 1)])
    def test_in_a_voice_channel_the_remaining_time_counts_down_from_five(self, decorrido: int, restante: int) -> None:
        assert checks.voice_status_lock_remaining(jogador(disnake.VoiceChannel, decorrido=decorrido)) == restante

    @pytest.mark.parametrize("decorrido", [5, 6, 29, 30, 600])
    def test_in_a_voice_channel_there_is_no_lock_from_five_seconds_on(self, decorrido: int) -> None:
        assert checks.voice_status_lock_remaining(jogador(disnake.VoiceChannel, decorrido=decorrido)) <= 0

    @pytest.mark.parametrize(("decorrido", "restante"), [(0, 120), (60, 60), (119, 1)])
    def test_on_a_stage_the_lock_stays_at_120_seconds(self, decorrido: int, restante: int) -> None:
        assert checks.voice_status_lock_remaining(jogador(disnake.StageChannel, decorrido=decorrido)) == restante

    @pytest.mark.parametrize("decorrido", [120, 121, 600])
    def test_on_a_stage_there_is_no_lock_from_120_seconds_on(self, decorrido: int) -> None:
        assert checks.voice_status_lock_remaining(jogador(disnake.StageChannel, decorrido=decorrido)) <= 0

    @pytest.mark.parametrize("canal", [disnake.VoiceChannel, disnake.StageChannel])
    def test_with_the_status_off_there_is_no_lock(self, canal: type) -> None:
        assert checks.voice_status_lock_remaining(jogador(canal, decorrido=0, ligado=False)) <= 0

    def test_the_numbers_come_from_the_single_rule_function(self) -> None:
        from empiremuse.rules import voice_status

        assert voice_status.control_lock_seconds(False) == 5 and voice_status.control_lock_seconds(True) == 120


class TestComandos:
    @pytest.mark.parametrize("decorrido", [0, 1, 4])
    def test_a_voice_channel_refuses_before_five_seconds_with_the_same_message(self, decorrido: int) -> None:
        with pytest.raises(GenericError, match="aguardar") as erro:
            comando(jogador(disnake.VoiceChannel, decorrido=decorrido))

        assert "status automático do canal ligado" in erro.value.text and "palco" not in erro.value.text

    @pytest.mark.parametrize("decorrido", [5, 6, 10, 29, 30, 600])
    def test_a_voice_channel_accepts_from_five_seconds_on(self, decorrido: int) -> None:
        assert comando(jogador(disnake.VoiceChannel, decorrido=decorrido)) is True

    @pytest.mark.parametrize("decorrido", [0, 30, 119])
    def test_a_stage_refuses_until_120_seconds(self, decorrido: int) -> None:
        with pytest.raises(GenericError, match="aguardar"):
            comando(jogador(disnake.StageChannel, decorrido=decorrido))

    @pytest.mark.parametrize("decorrido", [120, 121])
    def test_a_stage_accepts_from_120_seconds_on(self, decorrido: int) -> None:
        assert comando(jogador(disnake.StageChannel, decorrido=decorrido)) is True

    @pytest.mark.parametrize("canal", [disnake.VoiceChannel, disnake.StageChannel])
    def test_the_bot_owner_is_exempt(self, canal: type) -> None:
        assert comando(jogador(canal, decorrido=0), dono=True) is True

    def test_with_the_status_off_a_voice_channel_has_no_lock(self) -> None:
        assert comando(jogador(disnake.VoiceChannel, decorrido=0, ligado=False)) is True

    def test_the_wait_message_shows_the_remaining_time(self) -> None:
        with pytest.raises(GenericError) as erro:
            comando(jogador(disnake.VoiceChannel, decorrido=2))

        assert "3 segundos" in erro.value.text


class TestForceplayDoEmbed:
    @pytest.mark.parametrize("decorrido", [0, 4])
    def test_a_voice_channel_refuses_before_five_seconds(self, decorrido: int) -> None:
        with pytest.raises(GenericError, match="aguardar"):
            forceplay(jogador(disnake.VoiceChannel, decorrido=decorrido))

    @pytest.mark.parametrize("decorrido", [5, 10, 30])
    def test_a_voice_channel_accepts_from_five_seconds_on(self, decorrido: int) -> None:
        forceplay(jogador(disnake.VoiceChannel, decorrido=decorrido))

    @pytest.mark.parametrize("decorrido", [0, 119])
    def test_a_stage_refuses_until_120_seconds(self, decorrido: int) -> None:
        with pytest.raises(GenericError, match="aguardar"):
            forceplay(jogador(disnake.StageChannel, decorrido=decorrido))

    def test_the_owner_is_exempt(self) -> None:
        forceplay(jogador(disnake.VoiceChannel, decorrido=0), dono=True)

    def test_the_embed_refusal_uses_the_same_text_as_the_commands(self) -> None:
        with pytest.raises(GenericError) as erro:
            forceplay(jogador(disnake.VoiceChannel, decorrido=2))

        assert "Você terá que aguardar 3 segundos para usar essa função" in erro.value.text
        assert "status automático do canal ligado" in erro.value.text and "palco" not in erro.value.text

    def test_both_entry_points_agree_on_every_second_of_the_window(self) -> None:
        for canal in (disnake.VoiceChannel, disnake.StageChannel):
            for decorrido in range(0, 125):
                player = jogador(canal, decorrido=decorrido)
                try:
                    comando(player)
                    recusa_comando = False
                except GenericError:
                    recusa_comando = True
                try:
                    forceplay(player)
                    recusa_embed = False
                except GenericError:
                    recusa_embed = True
                assert recusa_comando == recusa_embed, (canal.__name__, decorrido)

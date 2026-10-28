"""Teste do dono em produção 2.1.1, parte A — status do canal de voz sem a permissão ``Definir status do canal de voz`` (bit 48).

VA1 função pura ``can_set_voice_status`` (sempre sobre ``channel.permissions_for(guild.me)``); VA2 o comando e o modal temporário recusam ANTES de
ligar; VA3 o envio em tempo de execução (definir, ``clear`` e palco) trata o 403 sem traceback e sem subir ao handler; VA4 o modal permanente
salva o modelo e deixa desligados, citando, os players sem a permissão; VA5 os avisos levam só status, código e ids (sem título nem nome).
Sem Discord e sem rede: canais, bots e players são dublês e cada envio ao Discord é um espião.
"""

import asyncio
import logging
import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse.music_cog.voice_status import VoiceStatusMixin
from empiremuse.utils.db import DBModel
from empiremuse.utils.music import checks
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.music.interactions import SetStageTitle
from empiremuse.utils.music.models.player_voice import PlayerVoiceMixin
from tests.support.drivers_de_regras import (
    AUTOR,
    BotDeComandos,
    ContextoDoStatus,
    GuildaFalsa,
    InteracaoFalsa,
)
from tests.support.modais import SERVIDOR_DO_COMANDO as SERVIDOR
from tests.support.voz_auto import assentar

pytestmark = pytest.mark.critical

NOME_DA_PERMISSAO = "Definir status do canal de voz"
BIT_48 = 1 << 48
COM_BIT = disnake.Permissions(BIT_48)
SO_GERENCIAR_CANAIS = disnake.Permissions(manage_channels=True)
TITULO = "Titulo-Secreto-X"
SOLICITANTE = "Solicitante-Y"
CORPO_DO_ERRO = "Corpo-Do-Erro-Z"
ID_DO_CANAL = 555
ID_DO_SERVIDOR = 4242
TEMPO_MAXIMO_DA_ESPERA = 10  # segundos; limite de segurança, não é espera: o evento libera antes


def http_erro(classe, status: int, codigo: int):
    return classe(SimpleNamespace(status=status, reason="motivo"), {"code": codigo, "message": CORPO_DO_ERRO})


def proibido() -> disnake.Forbidden:
    return http_erro(disnake.Forbidden, 403, 50013)


def erro_500(codigo: int = 0) -> disnake.HTTPException:
    return http_erro(disnake.HTTPException, 500, codigo)


# ============================================================================ VA1


class TestCanSetVoiceStatus:
    def test_the_constant_is_bit_48(self):
        assert checks.SET_VOICE_CHANNEL_STATUS == BIT_48

    def test_bit_48_allows(self):
        assert checks.can_set_voice_status(COM_BIT) is True

    def test_administrator_allows(self):
        assert checks.can_set_voice_status(disnake.Permissions(administrator=True)) is True

    def test_only_manage_channels_does_not_allow(self):
        assert checks.can_set_voice_status(SO_GERENCIAR_CANAIS) is False

    def test_no_permission_does_not_allow(self):
        assert checks.can_set_voice_status(disnake.Permissions.none()) is False

    def test_bit_48_together_with_other_bits_allows(self):
        assert checks.can_set_voice_status(disnake.Permissions(BIT_48, manage_channels=True)) is True


# ============================================================================ dublês de canal, servidor e player


def canal_de_voz(id_: int = ID_DO_CANAL, *, permitido: bool = True) -> MagicMock:
    """``permissions_for(bot)`` do CANAL decide; o ``guild_permissions`` do bot (em ``servidor_do_bot``) sempre diz o contrário."""
    canal = MagicMock(spec=disnake.VoiceChannel)
    canal.id = id_
    canal.mention = f"<#{id_}>"
    canal.voice_states = {AUTOR: object()}
    canal.permissions_for.return_value = COM_BIT if permitido else SO_GERENCIAR_CANAIS
    return canal


def servidor_do_bot(canal, *, id_: int = SERVIDOR, permitido: bool) -> SimpleNamespace:
    contrario = SO_GERENCIAR_CANAIS if permitido else COM_BIT
    me = SimpleNamespace(voice=SimpleNamespace(channel=canal), guild_permissions=contrario)
    membro = SimpleNamespace(id=AUTOR, mention=f"<@{AUTOR}>", guild_permissions=SimpleNamespace(manage_guild=True))
    return SimpleNamespace(id=id_, me=me, get_member=lambda _: membro, default_role=SimpleNamespace(id=id_))


def jogador_falso(guilda) -> SimpleNamespace:
    jogador = SimpleNamespace(
        guild=guilda,
        stage_title_event=False,
        stage_title_template="",
        start_time=None,
        update=False,
        update_stage_topic=AsyncMock(),
        process_save_queue=AsyncMock(),
        set_command_log=MagicMock(),
    )

    async def aplicar(cfg: Any, *, jitter: bool = False) -> None:
        """O contrato 2.1.2: o permanente liga o status do player só se o bot pode defini-lo no canal."""
        jogador.stage_title_template = cfg.template
        jogador.stage_title_event = bool(cfg.permanent) and checks.voice_status_blocked_channel(guilda) is None

    jogador.apply_permanent_voice_status = aplicar
    return jogador


# ============================================================================ VA2 — comando


async def chamar_comando(canal, *, permitido: bool, template: str = "{track.title}"):
    guilda = servidor_do_bot(canal, permitido=permitido)
    jogador = jogador_falso(guilda)
    bot = SimpleNamespace(
        music=SimpleNamespace(players={SERVIDOR: jogador}),
        is_owner=AsyncMock(return_value=False),
        edit_voice_channel_status=AsyncMock(),
    )
    autor = SimpleNamespace(
        id=AUTOR, guild_permissions=SimpleNamespace(manage_guild=True), voice=SimpleNamespace(channel=canal)
    )
    guilda.get_member = lambda _: autor
    inter = SimpleNamespace(
        bot=bot,
        guild=guilda,
        guild_id=SERVIDOR,
        author=autor,
        response=SimpleNamespace(defer=AsyncMock()),
        edit_original_message=AsyncMock(),
    )
    try:
        await VoiceStatusMixin.set_voice_status.callback(self=VoiceStatusMixin(), inter=inter, template=template)
    except GenericError as erro:
        return SimpleNamespace(erro=erro.text, jogador=jogador, bot=bot, inter=inter)
    return SimpleNamespace(erro=None, jogador=jogador, bot=bot, inter=inter)


class TestComandoComModelo:
    @pytest.mark.asyncio
    async def test_without_the_permission_it_refuses_naming_the_permission_and_the_channel(self):
        canal = canal_de_voz(permitido=False)

        r = await chamar_comando(canal, permitido=False)

        assert r.erro is not None and NOME_DA_PERMISSAO in r.erro and canal.mention in r.erro

    @pytest.mark.asyncio
    async def test_without_the_permission_nothing_is_turned_on_saved_or_sent(self):
        r = await chamar_comando(canal_de_voz(permitido=False), permitido=False)

        assert r.jogador.stage_title_event is False and r.jogador.stage_title_template == ""
        r.jogador.update_stage_topic.assert_not_awaited()
        r.jogador.process_save_queue.assert_not_awaited()
        r.bot.edit_voice_channel_status.assert_not_awaited()
        r.inter.response.defer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_channel_override_counts_not_the_guild_permissions(self):
        """O bot TEM o bit no cargo (``guild_permissions``) mas o canal o nega: recusa."""
        r = await chamar_comando(canal_de_voz(permitido=False), permitido=False)

        assert r.erro is not None

    @pytest.mark.asyncio
    async def test_with_the_permission_on_the_channel_it_turns_on_even_if_the_role_lacks_it(self):
        r = await chamar_comando(canal_de_voz(permitido=True), permitido=True)

        assert r.erro is None and r.jogador.stage_title_event is True
        r.jogador.update_stage_topic.assert_awaited()

    @pytest.mark.asyncio
    async def test_a_stage_channel_keeps_the_current_rule(self):
        palco = MagicMock(spec=disnake.StageChannel)
        palco.id, palco.mention, palco.voice_states = 9, "<#9>", {AUTOR: object()}
        palco.permissions_for.return_value = disnake.Permissions.none()

        r = await chamar_comando(palco, permitido=False)

        assert r.erro is None and r.jogador.stage_title_event is True


# ============================================================================ VA2 — modal temporário e VA4 — modal permanente


class InteracaoEfemera(InteracaoFalsa):
    """Guarda se cada resposta foi efêmera e quantas vezes houve ``defer``."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.efemeras = []
        self.defers = 0
        defer_original = self.response.defer

        async def defer(**kw):
            self.defers += 1
            await defer_original(**kw)

        self.response.defer = defer

    async def send(self, *args, **kwargs):
        self.efemeras.append(bool(kwargs.get("ephemeral")))
        await super().send(*args, **kwargs)


def bot_adicional(guilda, jogador) -> SimpleNamespace:
    return SimpleNamespace(
        get_guild=lambda _, g=guilda: g,
        music=SimpleNamespace(players={SERVIDOR: jogador}),
    )


def ambiente_de_bots(permissoes: list[bool], *, canais: list[int] | None = None):
    """Um bot principal + os demais, cada um com o SEU servidor e o SEU player; ``permissoes[i]`` vale para o canal do bot ``i``."""
    canais = canais or [100 + i for i in range(len(permissoes))]
    principal = BotDeComandos()
    jogadores, guildas = [], []
    for ligado, id_canal in zip(permissoes, canais, strict=True):
        canal = canal_de_voz(id_canal, permitido=ligado)
        guilda = servidor_do_bot(canal, permitido=ligado)
        guildas.append(guilda)
        jogadores.append(jogador_falso(guilda))
    principal.guilds[SERVIDOR] = guildas[0]
    principal.music.players[SERVIDOR] = jogadores[0]
    outros = [bot_adicional(g, j) for g, j in zip(guildas[1:], jogadores[1:], strict=True)]
    principal.pool.get_guild_bots = lambda _: [principal, *outros]
    return principal, jogadores


@pytest.fixture
def sem_espera_real(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


MODELO = "{track.title} - {track.author}"


async def salvar_permanente(
    permissoes: list[bool], *, canais: list[int] | None = None, texto: str = MODELO, atual: str = ""
):
    bot, jogadores = ambiente_de_bots(permissoes, canais=canais)
    bot.documento("global", DBModel.guilds, SERVIDOR)["voice_channel_status"] = atual
    view = SetStageTitle(ContextoDoStatus(), bot, bot.guilds[SERVIDOR], {"voice_channel_status": atual})
    inter = InteracaoEfemera(guild_id=SERVIDOR, guild=bot.guilds[SERVIDOR], custom_id="status_voice_channel_perm")
    inter.text_values = {"status_voice_value": texto}
    await view.modal_handler(inter)
    await assentar()  # o apply_permanent_voice_status de cada player é uma tarefa: deixa-as rodar
    return SimpleNamespace(bot=bot, jogadores=jogadores, inter=inter)


def ligou(jogador) -> bool:
    return bool(jogador.stage_title_event)


@pytest.mark.usefixtures("sem_espera_real")
class TestModalPermanente:
    @pytest.mark.asyncio
    async def test_the_template_is_saved_even_when_no_player_has_the_permission(self):
        r = await salvar_permanente([False])

        assert r.bot.ultimo_global is not None and r.bot.ultimo_global["voice_channel_status"] == MODELO

    @pytest.mark.asyncio
    async def test_a_player_without_the_permission_stays_off_and_is_named_in_the_answer(self):
        r = await salvar_permanente([False], canais=[321])

        assert not ligou(r.jogadores[0])
        assert "salvo, mas falta a permissão" in r.inter.texto and NOME_DA_PERMISSAO in r.inter.texto
        assert "<#321>" in r.inter.texto

    @pytest.mark.asyncio
    async def test_each_player_is_checked_on_its_own_bot_and_channel(self):
        r = await salvar_permanente([False, True], canais=[11, 22])

        assert not ligou(r.jogadores[0]) and ligou(r.jogadores[1])
        assert "<#11>" in r.inter.texto and "<#22>" not in r.inter.texto

    @pytest.mark.asyncio
    async def test_all_with_the_permission_is_the_plain_success(self):
        r = await salvar_permanente([True, True])

        assert all(ligou(j) for j in r.jogadores)
        assert "falta a permissão" not in r.inter.texto and "salvo" in r.inter.texto

    @pytest.mark.asyncio
    async def test_the_same_channel_is_named_once(self):
        r = await salvar_permanente([False, False], canais=[77, 77])

        assert r.inter.texto.count("<#77>") == 1

    @pytest.mark.asyncio
    async def test_at_most_five_channels_are_named_and_the_rest_is_counted(self):
        r = await salvar_permanente([False] * 7)

        assert len(set(re.findall(r"<#\d+>", r.inter.texto))) == 5 and "e mais 2" in r.inter.texto

    @pytest.mark.asyncio
    async def test_clearing_the_template_still_works_without_the_permission(self):
        r = await salvar_permanente([False], texto="", atual=MODELO)

        assert r.bot.ultimo_global["voice_status_permanent"] is False  # vazio desliga o permanente e MANTÉM o modelo
        assert r.bot.ultimo_global["voice_channel_status"] == MODELO and "desativado" in r.inter.texto
        assert "falta a permissão" not in r.inter.texto


async def usar_modal_temporario(*, permitido: bool):
    canal = canal_de_voz(permitido=permitido)
    guilda = servidor_do_bot(canal, permitido=permitido)
    jogador = jogador_falso(guilda)
    bot = BotDeComandos()
    bot.guilds[SERVIDOR] = guilda
    bot.music.players[SERVIDOR] = jogador
    bot.pool.get_guild_bots = lambda _: [bot]
    view = SetStageTitle(ContextoDoStatus(), bot, guilda, {"voice_channel_status": ""})
    inter = InteracaoEfemera(guild_id=SERVIDOR, guild=guilda, custom_id="status_voice_channel_temp")
    inter.text_values = {"status_voice_value": MODELO}
    await view.modal_handler(inter)
    return SimpleNamespace(jogador=jogador, inter=inter, canal=canal)


class TestModalTemporario:
    @pytest.mark.asyncio
    async def test_without_the_permission_it_answers_privately_before_deferring(self):
        r = await usar_modal_temporario(permitido=False)

        assert NOME_DA_PERMISSAO in r.inter.texto and r.canal.mention in r.inter.texto
        assert r.inter.efemeras == [True] and r.inter.defers == 0

    @pytest.mark.asyncio
    async def test_without_the_permission_nothing_is_turned_on(self):
        r = await usar_modal_temporario(permitido=False)

        assert not ligou(r.jogador) and r.jogador.stage_title_template == ""
        r.jogador.update_stage_topic.assert_not_awaited()
        r.jogador.process_save_queue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_with_the_permission_it_turns_on(self):
        r = await usar_modal_temporario(permitido=True)

        assert ligou(r.jogador) and r.inter.defers == 1
        r.jogador.update_stage_topic.assert_awaited()


# ============================================================================ VA3 e VA5 — envio em tempo de execução


class JogadorDeStatus(PlayerVoiceMixin):
    """``update_stage_topic`` REAL sobre um estado mínimo.

    Estado novo que o fix criar no player (ex.: o conjunto dos avisos já dados) nasce vazio na primeira leitura.
    """

    def __init__(self, canal, bot, *, evento=True, ultimo="anterior"):
        self.guild = SimpleNamespace(
            id=ID_DO_SERVIDOR,
            me=SimpleNamespace(
                voice=SimpleNamespace(channel=canal), guild_permissions=SimpleNamespace(manage_guild=True)
            ),
            get_member=lambda _: SimpleNamespace(display_name=SOLICITANTE),
        )
        self.bot = bot
        self.voice_status_permanent = (
            True  # estado do contrato 2.1.2, já inicializado como o __init__ do player real faz
        )
        self.voice_status_pending = None
        self.stage_title_event = evento
        self.stage_title_template = "{track.title}"
        self.last_stage_title = ultimo
        self.auto_pause = False
        self.paused = False
        self.position = 0
        self.update = False
        self.set_command_log = MagicMock()
        self.current = SimpleNamespace(
            requester=77,
            single_title=TITULO,
            authors_string="Autora",
            duration=180_000,
            is_stream=False,
            info={"sourceName": "youtube"},
            playlist_name=None,
        )

    def __getattr__(self, nome):
        if nome.startswith("__"):
            raise AttributeError(nome)
        valor = set()
        setattr(self, nome, valor)
        return valor


CAMINHOS = ["voz-definir", "voz-limpar", "palco"]


def cenario(caminho: str, erro: Exception) -> JogadorDeStatus:
    bot = SimpleNamespace(edit_voice_channel_status=AsyncMock(side_effect=erro), update_global_data=AsyncMock())
    if caminho == "palco":
        canal = MagicMock(spec=disnake.StageChannel)
        canal.id = ID_DO_CANAL
        canal.instance = SimpleNamespace(edit=AsyncMock(side_effect=erro))
        return JogadorDeStatus(canal, bot)
    canal = canal_de_voz(ID_DO_CANAL)
    return JogadorDeStatus(canal, bot)


async def rodar(jogador: JogadorDeStatus, caminho: str) -> None:
    await jogador.update_stage_topic(clear=(caminho == "voz-limpar"))


def avisos(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def com_traceback(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.exc_info]


@pytest.mark.parametrize("caminho", CAMINHOS)
class TestForbiddenEmTempoDeExecucao:
    @pytest.mark.asyncio
    async def test_it_turns_the_event_off_and_warns_the_player_exactly_once(self, caminho, caplog):
        jogador = cenario(caminho, proibido())

        with caplog.at_level(logging.DEBUG):
            await rodar(jogador, caminho)

        assert jogador.stage_title_event is False
        assert jogador.set_command_log.call_count == 1

    @pytest.mark.asyncio
    async def test_nothing_is_raised_and_no_record_carries_a_traceback(self, caminho, caplog):
        jogador = cenario(caminho, proibido())

        with caplog.at_level(logging.DEBUG):
            await rodar(jogador, caminho)

        assert com_traceback(caplog) == []

    @pytest.mark.asyncio
    async def test_one_warning_line_with_status_code_and_the_ids_and_nothing_private(self, caminho, caplog):
        jogador = cenario(caminho, proibido())

        with caplog.at_level(logging.DEBUG):
            await rodar(jogador, caminho)

        (registro,) = avisos(caplog)
        texto = registro.getMessage()
        assert registro.levelno == logging.WARNING and "50013" in texto and "403" in texto
        assert str(ID_DO_SERVIDOR) in texto and str(ID_DO_CANAL) in texto
        assert TITULO not in caplog.text and SOLICITANTE not in caplog.text and CORPO_DO_ERRO not in caplog.text

    @pytest.mark.asyncio
    async def test_the_permanent_template_is_not_erased_by_the_403(self, caminho, caplog):
        jogador = cenario(caminho, proibido())

        with caplog.at_level(logging.DEBUG):
            await rodar(jogador, caminho)

        jogador.bot.update_global_data.assert_not_awaited()
        assert jogador.stage_title_template == "{track.title}"

    @pytest.mark.asyncio
    async def test_a_second_run_does_not_try_again_nor_warn_again(self, caminho, caplog):
        jogador = cenario(caminho, proibido())

        with caplog.at_level(logging.DEBUG):
            await rodar(jogador, caminho)
            await rodar(jogador, caminho)

        assert jogador.set_command_log.call_count == 1 and len(avisos(caplog)) == 1


@pytest.mark.parametrize("caminho", ["voz-definir", "palco"])
class TestOutrosErrosHttp:
    @pytest.mark.asyncio
    async def test_the_status_stays_on_with_one_warning_without_traceback(self, caminho, caplog):
        jogador = cenario(caminho, erro_500(0))

        with caplog.at_level(logging.DEBUG):
            await rodar(jogador, caminho)

        assert jogador.stage_title_event is True
        assert len(avisos(caplog)) == 1 and com_traceback(caplog) == []
        assert "500" in avisos(caplog)[0].getMessage()

    @pytest.mark.asyncio
    async def test_the_last_title_only_changes_when_the_send_worked(self, caminho, caplog):
        jogador = cenario(caminho, erro_500(0))

        with caplog.at_level(logging.DEBUG):
            await rodar(jogador, caminho)

        assert jogador.last_stage_title == "anterior"

    @pytest.mark.asyncio
    async def test_two_equal_failures_in_a_row_warn_once(self, caminho, caplog):
        jogador = cenario(caminho, erro_500(0))

        with caplog.at_level(logging.DEBUG):
            await rodar(jogador, caminho)
            await rodar(jogador, caminho)

        assert len(avisos(caplog)) == 1

    @pytest.mark.asyncio
    async def test_a_different_code_warns_again(self, caminho, caplog):
        erro = erro_500(0)
        jogador = cenario(caminho, erro)

        with caplog.at_level(logging.DEBUG):
            await rodar(jogador, caminho)
            novo = erro_500(10003)
            jogador.bot.edit_voice_channel_status.side_effect = novo
            if caminho == "palco":
                jogador.guild.me.voice.channel.instance.edit.side_effect = novo
            await rodar(jogador, caminho)

        assert len(avisos(caplog)) == 2

    @pytest.mark.asyncio
    async def test_no_record_carries_the_title_the_requester_or_the_error_body(self, caminho, caplog):
        jogador = cenario(caminho, erro_500(0))

        with caplog.at_level(logging.DEBUG):
            await rodar(jogador, caminho)
            await rodar(jogador, caminho)

        assert TITULO not in caplog.text and SOLICITANTE not in caplog.text and CORPO_DO_ERRO not in caplog.text


class TestComportamentoQueSegue:
    @pytest.mark.asyncio
    async def test_an_unknown_exception_is_still_logged_with_its_traceback_and_not_raised(self, caplog):
        jogador = cenario("voz-definir", RuntimeError("falha-desconhecida"))

        with caplog.at_level(logging.DEBUG):
            await rodar(jogador, "voz-definir")

        assert len(com_traceback(caplog)) == 1

    @pytest.mark.asyncio
    async def test_a_successful_send_updates_the_last_title(self, caplog):
        jogador = cenario("voz-definir", RuntimeError("x"))
        jogador.bot.edit_voice_channel_status = AsyncMock()

        await rodar(jogador, "voz-definir")

        assert jogador.last_stage_title == TITULO and jogador.set_command_log.call_count == 0


# ============================================================================ V-A1 — dois envios simultâneos com 403 lento


@pytest.mark.parametrize("caminho", CAMINHOS)
class TestForbiddenSimultaneo:
    @pytest.mark.asyncio
    async def test_two_runs_waiting_on_a_slow_403_give_one_notice_and_one_warning(self, caminho, caplog):
        jogador = cenario(caminho, proibido())
        portao = asyncio.Event()
        ambos_no_portao = asyncio.Event()
        no_portao = 0

        async def lento(*args, **kwargs):
            nonlocal no_portao
            no_portao += 1
            if no_portao == 2:
                ambos_no_portao.set()
            await portao.wait()
            raise proibido()

        jogador.bot.edit_voice_channel_status = AsyncMock(side_effect=lento)
        if caminho == "palco":
            jogador.guild.me.voice.channel.instance.edit = AsyncMock(side_effect=lento)

        with caplog.at_level(logging.DEBUG):
            execucoes = [asyncio.ensure_future(rodar(jogador, caminho)) for _ in range(2)]
            try:
                await asyncio.wait_for(ambos_no_portao.wait(), TEMPO_MAXIMO_DA_ESPERA)  # só um guarda contra travar
            except BaseException:
                for execucao in execucoes:
                    execucao.cancel()
                raise
            finally:
                portao.set()  # nunca deixa os envios presos, passe ou falhe o teste
            await asyncio.gather(*execucoes)

        assert jogador.stage_title_event is False
        assert jogador.set_command_log.call_count == 1
        assert len(avisos(caplog)) == 1 and com_traceback(caplog) == []

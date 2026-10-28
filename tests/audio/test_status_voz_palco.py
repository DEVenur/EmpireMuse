"""2.1.2 — palco × permanente (contrato I8; VP4b–VP4f): o palco nunca recebe o permanente e uma sessão de palco só muda por comando de sessão.

Funções de produção reais: ``PlayerVoiceMixin.apply_permanent_voice_status``/``disable_voice_status``, ``SetStageTitle.modal_handler``,
``schedule_permanent_voice_status`` (a chamada que o painel faz em cada player), ``player_vc_disconnect`` (mover) e ``resume_player``.
Discord, banco e relógio são dublês. "Nada vai ao palco" = nenhum PUT de status, nenhum ``create_instance`` e nenhum ``instance.edit``.
"""

import asyncio
import copy
from collections.abc import AsyncIterator
import importlib
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from empiremuse.music_cog.player_lifecycle import PlayerLifecycleMixin
from empiremuse.utils.music.models.player_voice import schedule_permanent_voice_status
from tests.audio.test_status_voz_auto_ciclo import retomar_com
from tests.audio.test_status_voz_auto_discord import BotDoPool, documento_global, enviar_modal
from tests.persistence.test_sessao_retomada_sem_voice_state import CANAL_DE_TEXTO, CANAL_DE_VOZ, sessao_gravada
from tests.support.modais import SERVIDOR_DO_COMANDO as SERVIDOR
from tests.support.voz_auto import (
    ID_DO_BOT,
    BotDeVoz,
    JogadorDeVoz,
    RelogioFalso,
    assentar,
    canal_de_voz,
    executar,
    faixa,
    instalar_relogio,
    palco,
    servidor,
)

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

MODELO_DA_SESSAO = "sessão {track.title}"
MODELO_PERMANENTE = "permanente {track.author}"
TOPICO_DA_SESSAO = "Artista - Musica"
SESSAO = (
    "voice_status_pending",
    "voice_status_reapply",
)  # o ``voice_status_apply`` é a tarefa do próprio agendamento do save
CANAL_RESERVA = 1100000000000000077


@pytest.fixture
def relogio(monkeypatch: pytest.MonkeyPatch) -> RelogioFalso:
    return instalar_relogio(monkeypatch)


def regras() -> ModuleType:
    return importlib.import_module("empiremuse.rules.voice_status")


def cfg_de(permanente: bool, modelo: str = MODELO_PERMANENTE) -> Any:
    return regras().VoiceStatusConfig(permanente, modelo)


def canal_de_palco(id_: int = 888) -> Any:
    """O palco com instância: qualquer edição dela ou criação de outra seria um envio do status ao palco."""
    canal = palco(id_)
    canal.instance = SimpleNamespace(edit=AsyncMock())
    return canal


async def pendurada() -> "asyncio.Task[None]":
    """Uma tarefa de fundo viva (presa num Event): a prova de que ninguém a cancelou."""
    return asyncio.ensure_future(asyncio.Event().wait())


class SessaoDePalco:
    """Player real no palco com uma sessão de palco ativa (modelo, flag, último tópico e as três tarefas de fundo)."""

    def __init__(self, bot: BotDeVoz, canal: Any, player: JogadorDeVoz) -> None:
        self.bot, self.canal, self.player = bot, canal, player
        self.tarefas: dict[str, asyncio.Task[None]] = {}

    async def ligar_sessao(self) -> "SessaoDePalco":
        p = self.player
        p.stage_title_event, p.stage_title_template, p.last_stage_title = True, MODELO_DA_SESSAO, TOPICO_DA_SESSAO
        for nome in ("voice_status_pending", "voice_status_reapply", "voice_status_apply"):
            self.tarefas[nome] = await pendurada()
            setattr(p, nome, self.tarefas[nome])
        return self

    def sessao_intacta(self) -> bool:
        p = self.player
        return (
            p.stage_title_event is True
            and p.stage_title_template == MODELO_DA_SESSAO
            and p.last_stage_title == TOPICO_DA_SESSAO
            and all(getattr(p, nome) is t and not t.done() for nome, t in self.tarefas.items() if nome in SESSAO)
        )

    def nada_foi_ao_palco(self) -> bool:
        return (
            self.bot.puts == []
            and not self.canal.create_instance.called
            and not self.canal.instance.edit.called
            and self.canal.instance is not None
        )

    def encerrar(self) -> None:
        for t in self.tarefas.values():
            t.cancel()


@pytest_asyncio.fixture
async def no_palco() -> AsyncIterator[SessaoDePalco]:
    bot, canal = BotDeVoz(), canal_de_palco()
    guilda = servidor(canal)
    sessao = SessaoDePalco(bot, canal, JogadorDeVoz(guilda, bot, atual=faixa(), template="{track.title}"))
    yield sessao
    sessao.encerrar()


# ============================================================================ VP4b — apply fora do canal de voz só grava o flag


CASOS_DO_PERMANENTE = [
    pytest.param(True, MODELO_PERMANENTE, id="liga"),
    pytest.param(False, MODELO_PERMANENTE, id="desliga"),
    pytest.param(True, "outro modelo {track.title}", id="muda-o-modelo"),
]


class TestApplyForaDeVoz:
    @pytest.mark.parametrize(("permanente", "modelo"), CASOS_DO_PERMANENTE)
    async def test_on_a_stage_with_a_session_only_the_permanent_flag_changes(
        self, no_palco: SessaoDePalco, permanente: bool, modelo: str
    ) -> None:
        await no_palco.ligar_sessao()

        await no_palco.player.apply_permanent_voice_status(cfg_de(permanente, modelo))

        assert no_palco.player.voice_status_permanent is permanente
        assert no_palco.sessao_intacta(), "o permanente mexeu na sessão de palco (modelo, flag, tópico ou tarefas)"
        assert no_palco.nada_foi_ao_palco()

    @pytest.mark.parametrize(("permanente", "modelo"), CASOS_DO_PERMANENTE)
    async def test_on_a_stage_without_a_session_the_model_and_the_flag_stay_as_they_were(
        self, no_palco: SessaoDePalco, permanente: bool, modelo: str
    ) -> None:
        jogador = no_palco.player

        await jogador.apply_permanent_voice_status(cfg_de(permanente, modelo))

        assert jogador.voice_status_permanent is permanente
        assert jogador.stage_title_event is False
        assert jogador.stage_title_template == "{track.title}", "o modelo do permanente foi gravado no player do palco"
        assert no_palco.nada_foi_ao_palco()

    async def test_with_the_jitter_the_stage_still_gets_nothing(
        self, no_palco: SessaoDePalco, relogio: RelogioFalso
    ) -> None:
        await no_palco.ligar_sessao()

        await executar(relogio, no_palco.player.apply_permanent_voice_status(cfg_de(True), jitter=True))

        assert no_palco.sessao_intacta() and no_palco.nada_foi_ao_palco()

    async def test_without_a_channel_it_only_stores_the_flag_too(self, no_palco: SessaoDePalco) -> None:
        await no_palco.ligar_sessao()
        no_palco.player.guild.me.voice = None

        await no_palco.player.apply_permanent_voice_status(cfg_de(False))

        assert no_palco.player.voice_status_permanent is False
        assert no_palco.sessao_intacta(), "sem canal, o permanente mexeu na sessão"
        assert no_palco.bot.puts == []

    async def test_in_a_voice_channel_the_same_apply_still_turns_the_status_on(self, relogio: RelogioFalso) -> None:
        bot, canal = BotDeVoz(), canal_de_voz()
        jogador = JogadorDeVoz(servidor(canal), bot, atual=faixa(), template="x")

        await executar(relogio, jogador.apply_permanent_voice_status(cfg_de(True)))

        assert jogador.stage_title_event is True and jogador.stage_title_template == MODELO_PERMANENTE
        assert bot.textos, "o controle: no canal de voz o permanente continua enviando o status"


# ============================================================================ VP4b — salvar o permanente (modal e painel)


def bot_do_modal(sessao: SessaoDePalco) -> BotDoPool:
    bot = BotDoPool({})
    bot.guilds[SERVIDOR] = sessao.player.guild
    bot.music.players[SERVIDOR] = sessao.player
    bot.pool.get_guild_bots = lambda _gid: [bot]
    return bot


class TestSalvarComSessaoDePalco:
    @pytest.mark.parametrize(
        ("antes", "texto"),
        [
            pytest.param(False, MODELO_PERMANENTE, id="liga"),
            pytest.param(True, "", id="desliga"),
            pytest.param(True, "outro {track.title}", id="muda-o-modelo"),
        ],
    )
    async def test_the_modal_saves_the_permanent_and_leaves_the_stage_session_alone(
        self, no_palco: SessaoDePalco, antes: bool, texto: str
    ) -> None:
        await no_palco.ligar_sessao()
        bot = bot_do_modal(no_palco)
        documento_global(bot).update({"voice_status_permanent": antes, "voice_channel_status": MODELO_PERMANENTE})

        await enviar_modal(bot, texto=texto, aberto_com=documento_global(bot))

        assert bot.ultimo_global is not None and bot.ultimo_global["voice_status_permanent"] is bool(texto)
        assert no_palco.player.voice_status_permanent is bool(texto), "o player não registrou o permanente novo"
        assert no_palco.sessao_intacta(), "salvar o permanente pelo modal mexeu na sessão de palco"
        assert no_palco.nada_foi_ao_palco()

    @pytest.mark.parametrize(("permanente", "modelo"), CASOS_DO_PERMANENTE)
    async def test_the_panel_call_leaves_the_stage_session_alone(
        self, no_palco: SessaoDePalco, permanente: bool, modelo: str
    ) -> None:
        """O painel do #146 agenda ``schedule_permanent_voice_status(player, cfg)`` em todo player; é essa chamada que vale aqui.

        Roda na ``main`` de hoje e depois do merge de #146 + I8 (usa só o helper de produção, não o formulário do painel).
        """
        await no_palco.ligar_sessao()

        schedule_permanent_voice_status(no_palco.player, cfg_de(permanente, modelo))
        await assentar()

        assert no_palco.player.voice_status_permanent is permanente
        assert no_palco.nada_foi_ao_palco()
        assert no_palco.player.stage_title_event is True and no_palco.player.stage_title_template == MODELO_DA_SESSAO
        assert no_palco.player.last_stage_title == TOPICO_DA_SESSAO


# ============================================================================ VP4c — mover entre voz e palco


class _Lifecycle(PlayerLifecycleMixin):
    pass


async def mover_entre(
    relogio: RelogioFalso, *, de: Any, para: Any, sessao_ligada: bool, doc: dict[str, Any] | None = None
) -> SimpleNamespace:
    """O bot do player vai de ``de`` para ``para`` (``on_voice_state_update`` REAL); o servidor já mostra o canal novo."""
    bot = BotDeVoz()
    guilda = servidor(para)
    guilda.voice_client = SimpleNamespace(channel=de)
    player = JogadorDeVoz(guilda, bot, atual=faixa(), template="{track.title}")
    player.last_channel = de
    player.start_members_timeout = lambda **_k: None
    if sessao_ligada:
        player.stage_title_event, player.last_stage_title = True, TOPICO_DA_SESSAO
    bot.documentos[SERVIDOR] = copy.deepcopy(
        doc or {"voice_status_permanent": True, "voice_channel_status": MODELO_PERMANENTE}
    )
    bot.music = SimpleNamespace(players={guilda.id: player})
    cog = _Lifecycle()
    cog.bot = bot
    membro = SimpleNamespace(id=ID_DO_BOT, bot=True, guild=guilda)
    await executar(
        relogio, cog.player_vc_disconnect(membro, SimpleNamespace(channel=de), SimpleNamespace(channel=para))
    )
    await assentar()
    return SimpleNamespace(player=player, bot=bot, de=de, para=para)


class TestMoverEntreVozEPalco:
    async def test_moving_from_voice_to_a_stage_never_carries_the_permanent_into_it(
        self, relogio: RelogioFalso
    ) -> None:
        r = await mover_entre(relogio, de=canal_de_voz(1001), para=canal_de_palco(), sessao_ligada=True)
        antes = len(r.bot.puts)

        for _ in range(3):  # trocas de faixa seguintes
            await executar(relogio, r.player.update_stage_topic(force=True))
            await relogio.avancar(10)

        assert r.player.stage_title_event is False
        assert r.bot.textos == [], "o modelo do permanente foi enviado depois do mover para o palco"
        assert len(r.bot.puts) == antes and all(p.canal == 1001 for p in r.bot.puts), "só o canal de voz antigo é limpo"
        assert not r.para.create_instance.called and not r.para.instance.edit.called

    async def test_moving_from_voice_to_a_stage_with_the_permanent_off_also_sends_nothing(
        self, relogio: RelogioFalso
    ) -> None:
        r = await mover_entre(
            relogio,
            de=canal_de_voz(1001),
            para=canal_de_palco(),
            sessao_ligada=True,
            doc={"voice_status_permanent": False},
        )

        assert r.bot.textos == [] and r.player.stage_title_event is False
        assert not r.para.create_instance.called and not r.para.instance.edit.called

    async def test_moving_from_a_stage_to_voice_turns_the_permanent_on_there(self, relogio: RelogioFalso) -> None:
        r = await mover_entre(relogio, de=canal_de_palco(), para=canal_de_voz(1002), sessao_ligada=True)

        assert r.player.stage_title_event is True
        assert r.bot.textos and r.bot.puts[-1].canal == 1002, "o permanente não ligou no canal de voz"


# ============================================================================ VP4d/VP4f — retomada no palco


def sem_conectar(canal: Any) -> Any:
    """O canal sem a permissão de conectar: a retomada cai no ``last_voice_channel_id``."""
    canal.permissions_for = lambda _quem: SimpleNamespace(connect=False, read_message_history=False, mute_members=False)
    return canal


def um_palco(id_: int) -> Any:
    stage = canal_de_palco(id_)
    stage.permissions_for.return_value = SimpleNamespace(connect=True, read_message_history=False, mute_members=False)
    return stage


def um_canal_de_voz(id_: int) -> Any:
    from tests.persistence.test_sessao_retomada_sem_voice_state import canal_de_voz as canal_da_retomada

    return canal_da_retomada(id_)


def canais_com_palco() -> dict[int, Any]:
    return {CANAL_DE_VOZ: um_palco(CANAL_DE_VOZ), CANAL_DE_TEXTO: um_canal_de_voz(CANAL_DE_TEXTO)}


class TestRetomadaNoPalco:
    async def test_a_saved_stage_session_comes_back_with_its_own_model_and_without_touching_the_permanent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dados = await sessao_gravada(stage_title_event=True, stage_title_template=MODELO_DA_SESSAO)

        r = await retomar_com(
            monkeypatch,
            dados,
            {"voice_status_permanent": True, "voice_channel_status": MODELO_PERMANENTE},
            canais=canais_com_palco(),
        )

        assert r.terminou and r.jogador is not None
        assert getattr(r.jogador, "stage_title_event", False) is True, "a sessão de palco salva não foi restaurada"
        assert r.jogador.kwargs["stage_title_template"] == MODELO_DA_SESSAO
        assert r.leituras == [], "a retomada no palco leu o global do servidor"
        assert r.chamadas == [], "agendou o permanente no palco"
        assert getattr(r.jogador, "voice_status_apply", None) is None

    async def test_a_saved_stage_session_that_was_off_stays_off_and_sends_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dados = await sessao_gravada(stage_title_event=False, stage_title_template=MODELO_DA_SESSAO)

        r = await retomar_com(monkeypatch, dados, {"voice_status_permanent": True}, canais=canais_com_palco())

        assert r.terminou and r.jogador is not None
        assert getattr(r.jogador, "stage_title_event", False) is False
        assert r.leituras == [] and r.chamadas == []
        assert getattr(r.jogador, "voice_status_apply", None) is None

    async def test_the_voice_channel_resume_is_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Controle: em canal de voz a retomada lê o global e agenda o permanente com jitter (VP8)."""
        dados = await sessao_gravada(stage_title_event=True, stage_title_template=MODELO_DA_SESSAO)

        r = await retomar_com(
            monkeypatch, dados, {"voice_status_permanent": True, "voice_channel_status": MODELO_PERMANENTE}
        )

        ((cfg, jitter),) = r.chamadas
        assert len(r.leituras) == 1 and cfg.permanent is True and jitter is True

    async def test_a_saved_stage_that_falls_back_to_a_voice_channel_follows_the_voice_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """O canal final é de voz (o palco salvo não deixou conectar): o flag salvo não vale; vale o permanente do servidor."""
        dados = await sessao_gravada(stage_title_event=True, stage_title_template=MODELO_DA_SESSAO)
        dados["last_voice_channel_id"] = CANAL_RESERVA
        canais = {
            CANAL_DE_VOZ: sem_conectar(um_palco(CANAL_DE_VOZ)),
            CANAL_RESERVA: um_canal_de_voz(CANAL_RESERVA),
            CANAL_DE_TEXTO: um_canal_de_voz(CANAL_DE_TEXTO),
        }

        r = await retomar_com(monkeypatch, dados, {"voice_status_permanent": False}, canais=canais)

        assert r.jogador is not None and r.jogador.conexoes == [CANAL_RESERVA]
        assert getattr(r.jogador, "stage_title_event", False) is not True, (
            "o flag salvo do palco ligou o status no canal de voz"
        )
        assert len(r.leituras) == 1, "o caminho de voz lê o permanente"
        ((cfg, jitter),) = r.chamadas
        assert cfg.permanent is False and jitter is True

    async def test_a_voice_session_that_falls_back_to_a_stage_never_becomes_a_stage_topic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VP4f: o canal salvo era de voz e o final é um palco (``last_voice_channel_id``): a sessão de voz não vira tópico de palco."""
        dados = await sessao_gravada(stage_title_event=True, stage_title_template=MODELO_DA_SESSAO)
        dados["last_voice_channel_id"] = CANAL_RESERVA
        canais = {
            CANAL_DE_VOZ: sem_conectar(um_canal_de_voz(CANAL_DE_VOZ)),
            CANAL_RESERVA: um_palco(CANAL_RESERVA),
            CANAL_DE_TEXTO: um_canal_de_voz(CANAL_DE_TEXTO),
        }

        r = await retomar_com(
            monkeypatch,
            dados,
            {"voice_status_permanent": True, "voice_channel_status": MODELO_PERMANENTE},
            canais=canais,
        )

        assert r.jogador is not None and r.jogador.conexoes == [CANAL_RESERVA]
        assert getattr(r.jogador, "stage_title_event", False) is not True, "a sessão de voz virou tópico de palco"
        assert len(r.leituras) == 1, "o caminho de voz lê o permanente (que no palco só grava o flag)"
        ((cfg, jitter),) = r.chamadas
        assert cfg.permanent is True and jitter is True


# ============================================================================ VP4e — desligar no palco


class TestDesligarNoPalco:
    async def test_it_only_clears_the_flag_and_cancels_the_tasks(self, no_palco: SessaoDePalco) -> None:
        await no_palco.ligar_sessao()

        await no_palco.player.disable_voice_status()
        await assentar()

        assert no_palco.player.stage_title_event is False
        assert all(t.cancelled() for t in no_palco.tarefas.values()), "alguma tarefa de fundo seguiu viva"
        assert no_palco.nada_foi_ao_palco(), "o desligar tocou o palco (PUT de voz ou edição da instância)"
        assert no_palco.player.last_stage_title == TOPICO_DA_SESSAO

    async def test_it_is_idempotent_on_a_stage(self, no_palco: SessaoDePalco) -> None:
        await no_palco.ligar_sessao()

        await no_palco.player.disable_voice_status()
        await no_palco.player.disable_voice_status()

        assert no_palco.nada_foi_ao_palco() and no_palco.player.stage_title_event is False

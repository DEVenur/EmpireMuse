"""2.1.2 — palco × permanente (contrato I8; VP4b–VP4f): o palco nunca recebe o permanente e uma sessão de palco só muda por comando de sessão.

Funções de produção reais: ``PlayerVoiceMixin.apply_permanent_voice_status``/``disable_voice_status``, ``SetStageTitle.modal_handler``,
``schedule_permanent_voice_status`` (a chamada que o painel faz em cada player), ``player_vc_disconnect`` (mover) e ``resume_player``.
Discord, banco e relógio são dublês. "Nada vai ao palco" = nenhum PUT de status, nenhum ``create_instance`` e nenhum ``instance.edit``.
"""

import asyncio
import copy
import importlib
from collections.abc import AsyncIterator
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from empiremuse.music_cog.player_lifecycle import PlayerLifecycleMixin
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
    bot.documentos[guilda.id] = copy.deepcopy(
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

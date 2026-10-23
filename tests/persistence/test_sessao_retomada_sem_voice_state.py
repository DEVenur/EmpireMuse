"""F3-6b, etapa 0 — caracterização: retomar o player SEM ``voice_state`` reconecta por ``connect`` (insumo da etapa 5).

A etapa 5 deixa de persistir ``voice_state`` (evento de voz do Discord, efêmero e por conexão) e ``extra_info``: o
``resume_player`` passa a receber a sessão sem esses campos. Estes testes fixam o que já é verdade HOJE com o
``PlayerSession.resume_player`` REAL (dublês de canal, servidor, nó e player) e com o ``LavalinkPlayer._wait_for_new_node``
REAL:

* sem ``voice_state`` (ausente, ``None`` ou ``{}``) o ``resume_player`` reconecta por ``player.connect(voice_channel.id)``,
  no nó v3 e no v4, e o player nasce com ``_voice_state`` ``None``: a reconexão nunca dependeu do campo gravado;
* com ``voice_state`` ou ``extra_info`` na entrada (a etapa 5 não os grava nem lê) o resultado é o mesmo e o player nasce sem eles;
* o código de hoje já descarta o ``voice_state`` quando o canal de voz muda;
* ``_wait_for_new_node`` com ``_voice_state`` falso troca de nó (``change_node``) e, fora da voz, conecta
  (``connect``); só com ``_voice_state`` verdadeiro reenvia a atualização de voz.
"""

from collections import deque
from types import SimpleNamespace

import disnake
import pytest

from empiremuse.cogs import player_resume
from empiremuse.utils.music import models
from empiremuse.utils.music.models import LavalinkPlayer
from tests.support.formatos_reais import (
    CANAL_DE_TEXTO,
    CANAL_DE_VOZ,
    INSTANTE,
    SERVIDOR,
    cog_de_sessoes,
)
from tests.persistence.test_formato_sessao import gravar, jogador_completo

OUTRO_CANAL_DE_VOZ = 1100000000000000099


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)
    monkeypatch.setattr(player_resume, "can_send_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(player_resume, "can_connect", lambda *args, **kwargs: None)


# ============================================================================ dublês do resume_player


class JogadorRetomado:
    """O que ``resume_player`` e ``update_player`` pedem ao player; guarda cada chamada e cada atributo atribuído."""

    def __init__(self, node, **kwargs):
        self.node, self.kwargs = node, kwargs
        self.queue, self.played, self.queue_autoplay = deque(), deque(), deque()
        self.failed_tracks, self.command_log_list = [], deque(maxlen=10)
        self.filters, self.volume, self.controller_mode = {}, 100, True
        self.keep_connected, self.auto_pause, self.current, self.current_encoded = False, False, None, None
        self.guild = kwargs["guild"]
        self.conexoes, self.chamadas = [], []
        self.message = None

    async def connect(self, channel_id, *args, **kwargs):
        self.conexoes.append(channel_id)

    async def update_filters(self):
        self.chamadas.append("update_filters")

    def set_command_log(self, **kwargs):
        self.chamadas.append("set_command_log")

    async def process_next(self, start_position=0):
        self.chamadas.append(("process_next", start_position))

    async def invoke_np(self, **kwargs):
        self.chamadas.append("invoke_np")

    async def set_pause(self, valor):
        self.chamadas.append(("set_pause", valor))

    def start_members_timeout(self, check=True):
        self.chamadas.append("start_members_timeout")


class No:
    def __init__(self, versao):
        self.identifier, self.version, self.atualizacoes = "no-1", versao, []

    async def update_player(self, guild_id, data):
        self.atualizacoes.append((guild_id, data))


async def buscar_mensagem(message_id):
    return SimpleNamespace(id=message_id)


def canal_de_voz(canal_id=CANAL_DE_VOZ):
    membro = SimpleNamespace(bot=False, voice=SimpleNamespace(deaf=False, self_deaf=False))
    permissoes = SimpleNamespace(connect=True, read_message_history=False)
    return SimpleNamespace(
        id=canal_id,
        mention=f"<#{canal_id}>",
        name="voz",
        members=[membro],
        permissions_for=lambda quem: permissoes,
        fetch_message=buscar_mensagem,
    )


def montar(versao_do_no: int, *, canais=None):
    """Cog real com bot, servidor, canais e nó de mentira; devolve ``(cog, nó, jogadores criados)``."""
    cog = cog_de_sessoes()
    servidor = SimpleNamespace(id=SERVIDOR, name="servidor", me=SimpleNamespace(voice=object(), id=1))
    canais = (
        canais if canais is not None else {CANAL_DE_VOZ: canal_de_voz(), CANAL_DE_TEXTO: canal_de_voz(CANAL_DE_TEXTO)}
    )
    for canal in canais.values():
        canal.guild = servidor
    no, criados, jogadores = No(versao_do_no), [], {}

    def get_player(**kwargs):
        jogador = JogadorRetomado(no, **kwargs)
        criados.append(jogador)
        jogadores[kwargs["guild_id"]] = jogador
        return jogador

    async def get_data(*args, **kwargs):
        return {"player_controller": {"channel": None, "message_id": None}}

    cog.bot.user = SimpleNamespace(id=1)
    cog.bot.get_channel = canais.get
    cog.bot.get_guild = lambda guild_id: servidor
    cog.bot.get_data = get_data
    cog.bot.get_color = lambda *args: 0
    cog.bot.music = SimpleNamespace(players=jogadores, get_best_node=lambda: no, get_player=get_player)
    cog.bot.players_resumed = {}
    return cog, no, criados


async def sessao_gravada(**campos) -> dict:
    return await gravar(cog_de_sessoes(), jogador_completo(**campos))


async def retomar(versao_do_no, dados, *, canais=None):
    cog, no, criados = montar(versao_do_no, canais=canais)
    await cog.resume_player(dados, hints=[])
    assert len(criados) == 1, "o resume_player não criou o player"
    return criados[0], no


# ============================================================================ sem voice_state: reconecta por connect


class TestSemVoiceState:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("estado", ["ausente", None, {}], ids=["ausente", "none", "vazio"])
    async def test_no_v4_reconecta_por_connect_e_o_player_nasce_sem_voice_state(self, estado):
        dados = await sessao_gravada()
        dados.pop("voice_state", None)
        if estado != "ausente":
            dados["voice_state"] = estado
        jogador, no = await retomar(4, dados)
        assert jogador.conexoes == [CANAL_DE_VOZ]
        assert not jogador._voice_state and "invoke_np" in jogador.chamadas
        assert len(no.atualizacoes) == 1 and "encodedTrack" in no.atualizacoes[0][1]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("estado", ["ausente", None, {}], ids=["ausente", "none", "vazio"])
    async def test_no_v3_reconecta_por_connect_e_segue_para_a_proxima_faixa(self, estado):
        dados = await sessao_gravada()
        dados.pop("voice_state", None)
        if estado != "ausente":
            dados["voice_state"] = estado
        jogador, no = await retomar(3, dados)
        assert jogador.conexoes == [CANAL_DE_VOZ]
        assert not jogador._voice_state and ("process_next", 45123) in jogador.chamadas
        assert no.atualizacoes == []

    @pytest.mark.asyncio
    async def test_a_sessao_sem_voice_state_restaura_o_resto_igual(self):
        dados = await sessao_gravada()
        dados.pop("voice_state", None)
        jogador, _ = await retomar(4, dados)
        assert jogador.dj == dados["dj"] and jogador.loop == "queue" and jogador.volume == 80
        assert jogador.nightcore is True and jogador.mini_queue_enabled is True
        assert jogador.listen_along_invite == "https://exemplo.invalid/convite"
        assert jogador.current.info["title"] == "Música 0"
        assert [t.info["title"] for t in jogador.queue] == ["Faixa Deezer 1", "Faixa parcial 2", "Música 3", "Música 6"]

    @pytest.mark.asyncio
    async def test_a_retomada_usa_o_canal_de_voz_gravado_e_nao_um_dado_de_voz(self):
        dados = await sessao_gravada()
        dados.pop("voice_state", None)
        dados["voice_channel"] = OUTRO_CANAL_DE_VOZ
        canais = {OUTRO_CANAL_DE_VOZ: canal_de_voz(OUTRO_CANAL_DE_VOZ), CANAL_DE_TEXTO: canal_de_voz(CANAL_DE_TEXTO)}
        jogador, _ = await retomar(4, dados, canais=canais)
        assert jogador.conexoes == [OUTRO_CANAL_DE_VOZ]


# ============================================================================ com voice_state na entrada: é ignorado


class TestVoiceStateNaEntradaEIgnorado:
    """Desde a etapa 5 a sessão não leva ``voice_state`` (não é gravado nem lido); se um dicionário o trouxer mesmo assim, o
    ``resume_player`` o ignora: o player nasce com ``_voice_state`` ``None`` e a reconexão é por ``connect``."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("versao", [3, 4])
    async def test_o_voice_state_que_vier_na_entrada_nao_e_copiado_para_o_player(self, versao):
        dados = await sessao_gravada()
        dados["voice_state"] = {
            "sessionId": "sessao-de-voz",
            "event": {"token": "t", "endpoint": "voz.exemplo.invalid"},
        }
        jogador, _ = await retomar(versao, dados)
        assert jogador._voice_state is None
        assert jogador.conexoes == [CANAL_DE_VOZ]

    @pytest.mark.asyncio
    async def test_a_reconexao_e_a_mesma_com_e_sem_voice_state_na_entrada(self):
        com = await sessao_gravada()
        com["voice_state"] = {"sessionId": "sessao-de-voz", "event": {"token": "t", "endpoint": "e"}}
        sem = await sessao_gravada()
        jogador_com, no_com = await retomar(4, com)
        jogador_sem, no_sem = await retomar(4, sem)
        assert jogador_com.conexoes == jogador_sem.conexoes == [CANAL_DE_VOZ]
        assert no_com.atualizacoes == no_sem.atualizacoes
        assert [c for c in jogador_com.chamadas if not isinstance(c, tuple)] == [
            c for c in jogador_sem.chamadas if not isinstance(c, tuple)
        ]

    @pytest.mark.asyncio
    async def test_o_player_nasce_sem_voice_state_quando_o_canal_de_voz_mudou(self):
        """O ramo de canal alterado (``last_voice_channel_id``) conecta no canal novo, também sem ``voice_state``."""
        dados = await sessao_gravada()
        dados["last_voice_channel_id"] = OUTRO_CANAL_DE_VOZ
        canais = {OUTRO_CANAL_DE_VOZ: canal_de_voz(OUTRO_CANAL_DE_VOZ), CANAL_DE_TEXTO: canal_de_voz(CANAL_DE_TEXTO)}
        jogador, _ = await retomar(4, dados, canais=canais)
        assert jogador.conexoes == [OUTRO_CANAL_DE_VOZ]
        assert not jogador._voice_state


class TestExtraInfo:
    """``extra_info`` não existe mais na sessão (nada o grava; era um segredo OAuth sem uso): o player nasce com ``{}``."""

    @pytest.mark.asyncio
    async def test_extra_info_que_vier_na_entrada_nao_e_restaurado(self):
        dados = await sessao_gravada()
        dados["extra_info"] = {"guild-yt-oauth": ("token-de-teste", 1)}
        jogador, _ = await retomar(4, dados)
        assert jogador.extra_info == {}

    @pytest.mark.asyncio
    async def test_sem_extra_info_o_player_nasce_com_dicionario_vazio(self):
        dados = await sessao_gravada()
        dados.pop("extra_info", None)
        jogador, _ = await retomar(4, dados)
        assert jogador.extra_info == {}


# ============================================================================ _wait_for_new_node com _voice_state falso


class JogadorDeTeste(LavalinkPlayer):
    """``LavalinkPlayer`` real sem ``__init__``; só substitui o que fala com Discord e com o nó."""

    position = 0
    last_channel = SimpleNamespace(id=CANAL_DE_VOZ)

    def set_command_log(self, *args, **kwargs):
        self.registros.append("set_command_log")

    async def change_node(self, identificador):
        self.registros.append(("change_node", identificador))

    async def _dispatch_voice_update(self):
        self.registros.append("_dispatch_voice_update")

    async def connect(self, channel_id, *args, **kwargs):
        self.registros.append(("connect", channel_id))

    async def process_next(self, start_position=0):
        self.registros.append(("process_next", start_position))


def jogador_em_troca_de_no(*, voice_state, na_voz=True) -> JogadorDeTeste:
    no = SimpleNamespace(identifier="no-1", is_available=False, players={SERVIDOR: object()})
    jogador = JogadorDeTeste.__new__(JogadorDeTeste)
    jogador.__dict__.update(
        node=no,
        guild_id=SERVIDOR,
        guild=SimpleNamespace(me=SimpleNamespace(voice=object() if na_voz else None)),
        bot=SimpleNamespace(music=SimpleNamespace(get_best_node=lambda ignore_node=None: no)),
        _voice_state=voice_state,
        locked=False,
        update=False,
        auto_pause=True,
        current=None,
        current_encoded=None,
        queue=deque(),
        auto_skip_track_task=SimpleNamespace(cancel=lambda: None),
        registros=[],
    )
    return jogador


class TestTrocaDeNoSemVoiceState:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("estado", [None, {}], ids=["none", "vazio"])
    async def test_voice_state_falso_troca_de_no_e_nao_reenvia_a_voz(self, estado):
        jogador = jogador_em_troca_de_no(voice_state=estado)
        await jogador._wait_for_new_node()
        assert ("change_node", "no-1") in jogador.registros
        assert "_dispatch_voice_update" not in jogador.registros
        assert ("process_next", 0) in jogador.registros

    @pytest.mark.asyncio
    async def test_voice_state_verdadeiro_no_mesmo_no_reenvia_a_voz_sem_trocar_de_no(self):
        jogador = jogador_em_troca_de_no(voice_state={"sessionId": "s", "event": {"token": "t", "endpoint": "e"}})
        await jogador._wait_for_new_node()
        assert "_dispatch_voice_update" in jogador.registros
        assert not any(isinstance(r, tuple) and r[0] == "change_node" for r in jogador.registros)

    @pytest.mark.asyncio
    async def test_fora_da_voz_e_sem_voice_state_conecta_no_ultimo_canal(self, monkeypatch):
        monkeypatch.setattr(models.player, "can_connect", lambda *args, **kwargs: None)
        jogador = jogador_em_troca_de_no(voice_state=None, na_voz=False)
        await jogador._wait_for_new_node()
        assert ("connect", CANAL_DE_VOZ) in jogador.registros
        assert jogador.registros.index(("change_node", "no-1")) < jogador.registros.index(("connect", CANAL_DE_VOZ))

    @pytest.mark.asyncio
    async def test_no_disponivel_nao_faz_nada(self):
        jogador = jogador_em_troca_de_no(voice_state=None)
        jogador.node.is_available = True
        await jogador._wait_for_new_node()
        assert jogador.registros == []

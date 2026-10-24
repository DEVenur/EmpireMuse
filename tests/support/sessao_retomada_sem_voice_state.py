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

import disnake
import pytest

from empiremuse.cogs import player_resume
from tests.support.formatos_reais import INSTANTE


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


# ============================================================================ _wait_for_new_node com _voice_state falso

"""F3-4 — servidor web/RPC (empiremuse/web_app.py): compatibilidade do protocolo, registro de bots, origem, limites e robustez.

Sem Discord, sem .env real, sem setup() nem Java e sem rede externa: o servidor Tornado real sobe numa porta efêmera em
127.0.0.1 (``TCPServer.listen`` é substituído só para escolher a porta e registrar os argumentos), a ``BotPool`` real é
construída com o ambiente isolado em tmp_path e as opções chegam pelas variáveis de ambiente, como para o operador.
Segredos e IDs são montados em tempo de execução.

Convenção: ``test_guarda_*`` caracterizam o comportamento atual (passam hoje e precisam continuar passando); os demais
falham hoje pelo motivo descrito na docstring. O app desktop (repos/EmpireMuse-RPC-app) é só lido, nunca alterado.
"""

import ast
import asyncio
import copy
import datetime
import json
import logging
import re
import secrets
import time
import traceback
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from tornado.tcpserver import TCPServer
from tornado.testing import bind_unused_port

from empiremuse import rpc_protocol, web_app
from empiremuse.utils.client import BotPool
from empiremuse.utils.music.models import LavalinkPlayer, LavalinkTrack
from empiremuse.web_app import WSClient

ROOT = Path(__file__).resolve().parent.parent
APP_DESKTOP = ROOT / "repos" / "EmpireMuse-RPC-app" / "rpc_client.py"
SO_COM_APP_DESKTOP = pytest.mark.skipif(not APP_DESKTOP.is_file(), reason="repos/EmpireMuse-RPC-app ausente")

VERSAO_APP = "3.0.0"
ESPERA = 2.0  # teto de espera por um evento do servidor
ASSENTAR = 0.15  # tempo para o servidor processar uma mensagem que não tem resposta
LIMITE_CONEXOES = 1000
LIMITE_IDS_BOT = 250
LIMITE_MENSAGENS = 20
TAMANHO_MAXIMO_MENSAGEM = 64 * 1024
AMBIENTE = ("RPC_SERVER_SECRET", "RPC_ALLOWED_ORIGINS", "WEB_BIND_ADDRESS", "ENABLE_RPC_AUTH", "PORT", "SERVER_PORT")

# O que LavalinkPlayer.process_rpc produz (caracterizado nos testes abaixo). A lista repassada ao usuário é a união
# disso, sem ``token`` (nunca repassado) e sem ``auth_enabled`` (hoje descartado pelo servidor; o app não o consome).
CAMPOS_UPDATE = {
    "auth_enabled", "bot_id", "bot_name", "guild", "lastfm_user", "listen_along_invite", "op", "start_time", "thumb",
    "token", "track", "user",
}  # fmt: skip
CAMPOS_IDLE = (CAMPOS_UPDATE - {"start_time"}) | {
    "idle_endtime", "idle_starttime", "invite_permissions", "public", "support_server",
}  # fmt: skip
CAMPOS_CLOSE = {"auth_enabled", "bot_id", "bot_name", "lastfm_user", "op", "thumb", "token", "user"}
CAMPOS_TRACK = {
    "247", "author", "autoplay", "duration", "loop", "paused", "position", "queue", "requester_id", "source", "stream",
    "thumb", "title", "url",
}  # fmt: skip
NUNCA_REPASSADOS = {"token", "auth_enabled"}
CAMPOS_REPASSADOS = {
    "update": CAMPOS_UPDATE - NUNCA_REPASSADOS,
    "idle": CAMPOS_IDLE - NUNCA_REPASSADOS,
    "close": CAMPOS_CLOSE - NUNCA_REPASSADOS,
}
PRODUZIDOS = {"update": CAMPOS_UPDATE, "idle": CAMPOS_IDLE, "close": CAMPOS_CLOSE}
# O que o app desktop lê das mensagens do servidor (conferido na fonte dele em test_guarda_app_desktop_consome_...).
CONSUMIDOS_PELO_APP = {
    "op", "bot_id", "bot_name", "user", "thumb", "track", "guild", "listen_along_invite", "lastfm_user",
    "invite_permissions", "public", "support_server", "idle_starttime", "idle_endtime", "start_time", "message", "reason",
}  # fmt: skip
CAMPOS_USUARIO_PARA_BOT = {"op", "user_ids", "version"}


def _snowflake() -> int:
    return secrets.randbelow(9 * 10**17) + 10**17  # 18 dígitos


def _token_do_app() -> str:
    return secrets.token_hex(25)  # 50 caracteres, como o gerado pelo comando /rich_presence


def _mensagem_usuario(ids: list, token: str = "", **extra) -> dict:
    """O que o app desktop envia ao conectar (rpc_client.py: handle_socket)."""
    return {"op": "rpc_update", "user_ids": ids, "token": token, "version": VERSAO_APP, **extra}


# ---------------------------------------------------------------------------------------------------------------------
# Infraestrutura: servidor real em porta efêmera, sessão HTTP e utilitários de leitura
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class _Servidor:
    pool: BotPool
    porta: int
    escuta: dict

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.porta}"

    @property
    def url_ws(self) -> str:
        return f"ws://127.0.0.1:{self.porta}/ws"


@pytest_asyncio.fixture
async def iniciar_servidor(tmp_path, monkeypatch):
    """Devolve ``iniciar(env)``, que sobe o servidor real com as opções vindas do ambiente (como o operador as define)."""
    for nome in ("home", "cwd"):
        (tmp_path / nome).mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path / "cwd")
    for nome in AMBIENTE:
        monkeypatch.delenv(nome, raising=False)
    web_app.users_ws.clear()
    web_app.bots_ws.clear()
    abertos = []

    def iniciar(env: dict | None = None) -> _Servidor:
        for nome, valor in (env or {}).items():
            monkeypatch.setenv(nome, valor)
        pool = BotPool()
        escuta: dict = {}

        def escutar(self, port, address=None, **kwargs):
            sock, porta = bind_unused_port()
            self.add_sockets([sock])
            escuta.update(port=port, address=address, kwargs=kwargs, porta=porta)
            abertos.append(self)

        monkeypatch.setattr(TCPServer, "listen", escutar)
        web_app.run_app(pool, "")
        return _Servidor(pool=pool, porta=escuta["porta"], escuta=escuta)

    yield iniciar

    for http in abertos:
        http.stop()
        await http.close_all_connections()
    web_app.users_ws.clear()
    web_app.bots_ws.clear()


@pytest_asyncio.fixture
async def sessao():
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as s:
        yield s


@pytest.fixture
def segredo() -> str:
    return secrets.token_hex(16)


async def _conectar(servidor: _Servidor, sessao, *, chave: str | None = None, origem: str | None = None):
    cabecalhos = {}
    if chave is not None:
        cabecalhos["X-RPC-Key"] = chave
    if origem is not None:
        cabecalhos["Origin"] = origem
    return await sessao.ws_connect(servidor.url_ws, headers=cabecalhos)


async def _registrar_bot(servidor: _Servidor, sessao, chave: str | None, ids: list | None = None):
    """Conecta e registra um bot como o WSClient faz (``user_ids`` + ``bot: True``); devolve (ws, ids)."""
    ids = ids or [_snowflake()]
    ws = await _conectar(servidor, sessao, chave=chave)
    await ws.send_json({"user_ids": ids, "bot": True})
    await asyncio.sleep(ASSENTAR)
    return ws, ids


async def _registrar_usuario(servidor: _Servidor, sessao, ids: list, token: str = "", **extra):
    ws = await _conectar(servidor, sessao)
    await ws.send_json(_mensagem_usuario(ids, token, **extra))
    await asyncio.sleep(ASSENTAR)
    return ws


async def _receber(ws, espera: float = ESPERA) -> dict:
    msg = await ws.receive(timeout=espera)
    assert msg.type == aiohttp.WSMsgType.TEXT, f"esperava um texto, veio {msg.type.name} (código {ws.close_code})"
    return json.loads(msg.data)


async def _nada_recebido(ws, espera: float = 0.4) -> bool:
    """True se nenhum TEXTO chegou em ``espera`` s (um fechamento da conexão não é conteúdo)."""
    try:
        msg = await ws.receive(timeout=espera)
    except asyncio.TimeoutError:
        return True
    return msg.type != aiohttp.WSMsgType.TEXT


async def _fechamento(ws, espera: float = ESPERA) -> int | None:
    """Código com que o servidor fechou a conexão (-1 se sem código), ou None se ela continuou aberta."""
    try:
        while True:
            msg = await ws.receive(timeout=espera)
            if msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            ):
                return ws.close_code if ws.close_code is not None else -1
    except asyncio.TimeoutError:
        return None


# ---------------------------------------------------------------------------------------------------------------------
# O que LavalinkPlayer.process_rpc produz (o REAL, com dublês de bot/guild/faixa)
# ---------------------------------------------------------------------------------------------------------------------


class _UsuarioDoBot:
    id = 111111111111111111
    display_avatar = SimpleNamespace(replace=lambda **kwargs: SimpleNamespace(url="https://exemplo.invalid/avatar.png"))

    def __str__(self) -> str:
        return "Bot#0001"


async def _stats(op: str, usuario: int, token_no_banco: str, auth: bool = False) -> dict:
    """Roda o process_rpc real e devolve o dict que ele entrega ao ``ws_client.send`` (op: update, idle ou close)."""
    enviados: list[dict] = []
    jogador = object.__new__(LavalinkPlayer)
    jogador.bot = SimpleNamespace(
        user=_UsuarioDoBot(),
        config={"ENABLE_RPC_AUTH": auth, "INVITE_PERMISSIONS": 3145728, "SUPPORT_SERVER": "https://exemplo.invalid/s"},
        appinfo=SimpleNamespace(bot_public=True),
        loop=asyncio.get_running_loop(),
        get_global_data=AsyncMock(return_value={"token": token_no_banco, "lastfm": {"username": "usuario-fm"}}),
        ws_client=SimpleNamespace(send=AsyncMock(side_effect=lambda d: enviados.append(copy.deepcopy(d)))),
    )
    agora = datetime.datetime.now(datetime.timezone.utc)
    jogador.guild = SimpleNamespace(name="Servidor Falso")
    jogador.is_closing = False
    jogador.listen_along_invite = ""
    jogador.queue = deque()
    jogador.keep_connected = False
    jogador.loop = False
    jogador.start_timestamp = 1700000000.0
    jogador.start_time = agora
    jogador.idle_endtime = agora
    jogador.idle_start_timestamp = 1700000000
    jogador.channel_id = 1
    jogador.paused = False
    jogador.auto_pause = False
    jogador.last_position = 0
    jogador.last_update = time.time() * 1000
    info = {
        "title": "Titulo - Teste", "author": "Autor", "length": 200000, "identifier": "abcdefghijk", "isStream": False,
        "uri": "https://exemplo.invalid/x", "sourceName": "youtube", "position": 0, "artworkUrl": "",
    }  # fmt: skip
    jogador.current = LavalinkTrack(id_="id", info=info, requester=1) if op == "update" else None

    if op == "close":
        await jogador.process_rpc(close=True, users=[usuario], wait=True)
    else:
        await jogador.process_rpc(SimpleNamespace(voice_states={}), users=[usuario], wait=True)
    assert enviados, "o process_rpc não entregou nada ao ws_client"
    return enviados[0]


@pytest.mark.asyncio
async def test_guarda_process_rpc_update_envia_exatamente_estes_campos():
    stats = await _stats("update", _snowflake(), _token_do_app())

    assert stats["op"] == "update"
    assert set(stats) == CAMPOS_UPDATE
    assert set(stats["track"]) == CAMPOS_TRACK


@pytest.mark.asyncio
async def test_guarda_process_rpc_idle_envia_exatamente_estes_campos():
    stats = await _stats("idle", _snowflake(), _token_do_app())

    assert stats["op"] == "idle"
    assert set(stats) == CAMPOS_IDLE


@pytest.mark.asyncio
async def test_guarda_process_rpc_close_envia_exatamente_estes_campos():
    stats = await _stats("close", _snowflake(), _token_do_app())

    assert stats["op"] == "close"
    assert set(stats) == CAMPOS_CLOSE


@pytest.mark.asyncio
async def test_guarda_process_rpc_leva_o_token_do_banco_e_o_estado_da_auth_na_mensagem():
    token = _token_do_app()

    stats = await _stats("update", _snowflake(), token, auth=True)

    assert stats["token"] == token and stats["auth_enabled"] is True


# ---------------------------------------------------------------------------------------------------------------------
# O que o app desktop envia e consome (só leitura da fonte dele)
# ---------------------------------------------------------------------------------------------------------------------


def _dicts_enviados_pelo_app() -> list[set]:
    """Chaves dos dicts literais passados a ``json.dumps`` dentro de ``ws.send_str(...)``."""
    arvore = ast.parse(APP_DESKTOP.read_text("utf-8"))
    achados = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == "send_str":
            for arg in no.args:
                if isinstance(arg, ast.Call) and arg.args and isinstance(arg.args[0], ast.Dict):
                    achados.append({k.value for k in arg.args[0].keys if isinstance(k, ast.Constant)})
    return achados


@SO_COM_APP_DESKTOP
def test_guarda_app_desktop_envia_o_registro_com_estes_campos():
    assert {"op", "user_ids", "token", "version"} in _dicts_enviados_pelo_app()


@SO_COM_APP_DESKTOP
def test_guarda_app_desktop_conecta_sem_cabecalhos_extras():
    """Sem ``headers=`` no ws_connect: o app não manda X-RPC-Key nem Origin (o servidor tem de aceitar isso)."""
    arvore = ast.parse(APP_DESKTOP.read_text("utf-8"))
    chamadas = [
        no for no in ast.walk(arvore)
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == "ws_connect"
    ]  # fmt: skip
    assert chamadas, "o app não chama ws_connect?"
    assert all("headers" not in {k.arg for k in c.keywords} for c in chamadas)


@SO_COM_APP_DESKTOP
@pytest.mark.parametrize("campo", sorted(CONSUMIDOS_PELO_APP))
def test_guarda_app_desktop_consome_este_campo(campo):
    fonte = APP_DESKTOP.read_text("utf-8")
    assert f'"{campo}"' in fonte or f"'{campo}'" in fonte


# ---------------------------------------------------------------------------------------------------------------------
# O que o WSClient (bot) manda no registro e consome (servidor falso em aiohttp, sem o servidor Tornado)
# ---------------------------------------------------------------------------------------------------------------------


@pytest_asyncio.fixture
async def servidor_aiohttp_falso():
    """``montar(roteiro)`` sobe um /ws falso; ``roteiro(ws, request)`` conduz a conversa. Devolve a URL."""
    runners = []

    async def montar(roteiro) -> str:
        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await roteiro(ws, request)
            return ws

        app = web.Application()
        app.router.add_get("/ws", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        runners.append(runner)
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        return f"ws://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/ws"

    yield montar
    for runner in runners:
        await runner.cleanup()


def _bot_falso(bot_id: int, jogadores: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=bot_id),
        wait_until_ready=AsyncMock(),
        music=SimpleNamespace(players=jogadores or {}),
        loop=asyncio.get_running_loop(),
    )


def _wsclient(url: str, bots: list, tmp_path, monkeypatch) -> WSClient:
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    pool = BotPool()
    pool.get_all_bots = lambda: bots
    return WSClient(url, pool)


@pytest.mark.asyncio
async def test_guarda_wsclient_registra_o_bot_com_user_ids_e_bot_true(servidor_aiohttp_falso, tmp_path, monkeypatch):
    recebido = asyncio.get_running_loop().create_future()

    async def roteiro(ws, request):
        recebido.set_result(await ws.receive_json())
        await ws.close()

    bot_id = _snowflake()
    client = _wsclient(await servidor_aiohttp_falso(roteiro), [_bot_falso(bot_id)], tmp_path, monkeypatch)

    await client.connect()
    registro = await asyncio.wait_for(recebido, ESPERA)
    client.clear_tasks()
    await client.session.close()

    assert registro["bot"] is True
    assert registro["user_ids"] == [bot_id]
    assert set(registro) <= {"user_ids", "bot", "auth_enabled"}


def _jogador_na_chamada(usuario: int) -> tuple[SimpleNamespace, SimpleNamespace]:
    canal = SimpleNamespace(voice_states={usuario: object()})
    jogador = SimpleNamespace(
        guild=SimpleNamespace(me=SimpleNamespace(voice=SimpleNamespace(channel=canal))),
        process_rpc=AsyncMock(),
        last_channel=object(),
    )
    return jogador, canal


async def _rodar_ws_loop(servidor_aiohttp_falso, tmp_path, monkeypatch, quadros) -> list[int]:
    """Roda o ws_loop real contra um /ws falso que envia ``quadros(usuarios)`` e fecha.

    Devolve os usuários cujo canal de voz foi atualizado (process_rpc chamado com o canal deles).
    """
    usuarios = [_snowflake(), _snowflake()]
    jogadores, pares = {}, {}
    for i, usuario in enumerate(usuarios):
        jogador, canal = _jogador_na_chamada(usuario)
        jogadores[i] = jogador
        pares[usuario] = (jogador, canal)

    async def roteiro(ws, request):
        await ws.receive_json()  # registro do bot
        for quadro in quadros(usuarios):
            await ws.send_str(quadro)
        await asyncio.sleep(0.2)
        await ws.close()

    url = await servidor_aiohttp_falso(roteiro)
    client = _wsclient(url, [_bot_falso(_snowflake(), jogadores)], tmp_path, monkeypatch)
    try:
        await asyncio.wait_for(client.ws_loop(), 10)
    finally:
        client.clear_tasks()
        if client.session:
            await client.session.close()
    return [
        u
        for u, (jogador, canal) in pares.items()
        if any(c.args == (canal,) for c in jogador.process_rpc.call_args_list)
    ]


def _rpc_update(usuario: int) -> str:
    return json.dumps({"op": "rpc_update", "user_ids": [usuario]})


@pytest.mark.asyncio
async def test_guarda_wsclient_consome_rpc_update_e_atualiza_o_canal_dos_usuarios(
    servidor_aiohttp_falso, tmp_path, monkeypatch
):
    atualizados = await _rodar_ws_loop(
        servidor_aiohttp_falso, tmp_path, monkeypatch, lambda us: [_rpc_update(us[0]), _rpc_update(us[1])]
    )

    assert len(atualizados) == 2


@pytest.mark.asyncio
async def test_guarda_wsclient_ignora_op_diferente_de_rpc_update(servidor_aiohttp_falso, tmp_path, monkeypatch):
    atualizados = await _rodar_ws_loop(
        servidor_aiohttp_falso,
        tmp_path,
        monkeypatch,
        lambda us: [json.dumps({"op": "outra", "user_ids": [us[0]]}), _rpc_update(us[1])],
    )

    assert len(atualizados) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quadro_invalido",
    [
        "isto nao e json",
        "[]",
        "42",
        "null",
        '"texto"',
        "{truncado",
        '{"op": "rpc_update", "user_ids": 5}',
        '{"op": "rpc_update", "user_ids": "abc"}',
    ],
    ids=["texto", "lista", "numero", "nulo", "string-json", "json-truncado", "user-ids-numero", "user-ids-texto"],
)
async def test_ws_loop_do_cliente_ignora_quadro_invalido_e_continua(
    servidor_aiohttp_falso, tmp_path, monkeypatch, quadro_invalido
):
    """Hoje o ``json.loads``/``.get`` do quadro inválido levanta e derruba o ws_loop: o 2º usuário nunca é atualizado."""
    atualizados = await _rodar_ws_loop(
        servidor_aiohttp_falso,
        tmp_path,
        monkeypatch,
        lambda us: [_rpc_update(us[0]), quadro_invalido, _rpc_update(us[1])],
    )

    assert len(atualizados) == 2


# ---------------------------------------------------------------------------------------------------------------------
# Compatibilidade do relé: o que o servidor repassa (servidor real)
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guarda_usuario_registra_e_o_bot_recebe_so_op_user_ids_e_version(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    usuario = _snowflake()

    await _registrar_usuario(servidor, sessao, [usuario], _token_do_app())

    assert await _receber(bot_ws) == {"op": "rpc_update", "user_ids": [usuario], "version": VERSAO_APP}


@pytest.mark.asyncio
async def test_usuario_para_bot_repassa_so_op_user_ids_e_version(iniciar_servidor, sessao, segredo):
    """Campos extras do usuário não chegam ao bot (hoje o dict inteiro, menos token/auth_enabled/bot, é repassado)."""
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)

    await _registrar_usuario(
        servidor, sessao, [_snowflake()], _token_do_app(), campo_extra="x", outro={"a": 1}, user=_snowflake()
    )

    assert set(await _receber(bot_ws)) == CAMPOS_USUARIO_PARA_BOT


async def _usuario_e_bot(servidor, sessao, segredo, token_do_usuario=""):
    """Bot registrado + usuário registrado (o repasse do registro já foi consumido). Devolve (bot_ws, bot_ids, usuario_ws, usuario)."""
    bot_ws, bot_ids = await _registrar_bot(servidor, sessao, segredo)
    usuario = _snowflake()
    usuario_ws = await _registrar_usuario(servidor, sessao, [usuario], token_do_usuario)
    await _receber(bot_ws)
    return bot_ws, bot_ids, usuario_ws, usuario


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["update", "idle", "close"])
async def test_guarda_bot_para_usuario_entrega_o_que_o_app_consome_e_nunca_o_token(
    iniciar_servidor, sessao, segredo, op
):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _, usuario_ws, usuario = await _usuario_e_bot(servidor, sessao, segredo)
    token_do_bot = _token_do_app()
    stats = await _stats(op, usuario, token_do_bot)

    await bot_ws.send_json(stats)
    entregue = await _receber(usuario_ws)

    assert "token" not in entregue and token_do_bot not in json.dumps(entregue)
    assert (CONSUMIDOS_PELO_APP & PRODUZIDOS[op]) <= set(entregue)
    assert entregue["op"] == op and entregue["user"] == usuario
    if op == "update":
        assert entregue["track"] == stats["track"]


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["update", "idle", "close"])
async def test_bot_para_usuario_repassa_exatamente_os_campos_do_process_rpc_sem_o_que_for_extra(
    iniciar_servidor, sessao, segredo, op
):
    """A lista repassada é o que o process_rpc produz (sem token); campo desconhecido do bot não chega ao usuário."""
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _, usuario_ws, usuario = await _usuario_e_bot(servidor, sessao, segredo)
    stats = await _stats(op, usuario, _token_do_app())
    stats.update(campo_extra="x", outro={"a": 1})

    await bot_ws.send_json(stats)
    entregue = await _receber(usuario_ws)

    assert set(entregue) == CAMPOS_REPASSADOS[op]


@pytest.mark.asyncio
async def test_guarda_ao_desconectar_o_bot_os_usuarios_recebem_close_com_os_ids_dele(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, bot_ids, usuario_ws, _ = await _usuario_e_bot(servidor, sessao, segredo)

    await bot_ws.close()

    assert await _receber(usuario_ws) == {"op": "close", "bot_id": bot_ids}


@pytest.mark.asyncio
async def test_guarda_versao_antiga_do_app_recebe_disconnect_e_nao_e_repassada(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    ws = await _conectar(servidor, sessao)

    await ws.send_json(_mensagem_usuario([_snowflake()]) | {"version": "1.0.0"})

    assert (await _receber(ws))["op"] == "disconnect"
    assert await _nada_recebido(bot_ws)


@pytest.mark.asyncio
async def test_guarda_token_com_tamanho_diferente_de_0_ou_50_e_recusado(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    ws = await _conectar(servidor, sessao)

    await ws.send_json(_mensagem_usuario([_snowflake()], "curto"))

    assert (await _receber(ws))["op"] == "disconnect"
    assert await _nada_recebido(bot_ws)


@pytest.mark.asyncio
async def test_guarda_pagina_de_status_responde_e_so_exibe_o_endereco_do_rele(iniciar_servidor, sessao, segredo):
    """A página não abre o /ws: o JS só mostra ``<origem>/ws``. Se um dia abrir, a mesma origem tem de ser aceita."""
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})

    async with sessao.get(servidor.base + "/") as resposta:
        corpo = await resposta.text()

    assert resposta.status == 200
    assert '"/ws"' in corpo and "new WebSocket" not in corpo


@pytest.mark.asyncio
async def test_guarda_conexao_da_mesma_origem_e_aceita(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})

    ws = await _conectar(servidor, sessao, origem=servidor.base)

    assert not ws.closed


# ---------------------------------------------------------------------------------------------------------------------
# Registro de bot autenticado (X-RPC-Key)
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guarda_bot_com_a_chave_configurada_e_aceito_e_recebe_os_registros_de_usuario(
    iniciar_servidor, sessao, segredo
):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)

    await _registrar_usuario(servidor, sessao, [_snowflake()])

    assert (await _receber(bot_ws))["op"] == "rpc_update"


@pytest.mark.asyncio
@pytest.mark.parametrize("tipo", ["ausente", "vazia", "errada", "prefixo", "com-sufixo"])
async def test_registro_de_bot_sem_chave_valida_fecha_com_4401(iniciar_servidor, sessao, segredo, tipo):
    """Hoje qualquer conexão com ``bot: true`` entra em bots_ws e passa a receber os registros dos usuários."""
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    chave = {
        "ausente": None,
        "vazia": "",
        "errada": secrets.token_hex(16),
        "prefixo": segredo[:-1],
        "com-sufixo": segredo + "x",
    }[tipo]
    ws = await _conectar(servidor, sessao, chave=chave)

    await ws.send_json({"user_ids": [_snowflake()], "bot": True})

    assert await _fechamento(ws) == 4401


@pytest.mark.asyncio
@pytest.mark.parametrize("chave", [None, ""], ids=["ausente", "vazia"])
async def test_registro_de_bot_fecha_com_4401_tambem_quando_o_segredo_nao_foi_configurado(
    iniciar_servidor, sessao, chave
):
    """Sem RPC_SERVER_SECRET vale o segredo efêmero do processo: chave ausente ou vazia nunca vale."""
    servidor = iniciar_servidor()
    ws = await _conectar(servidor, sessao, chave=chave)

    await ws.send_json({"user_ids": [_snowflake()], "bot": True})

    assert await _fechamento(ws) == 4401


@pytest.mark.asyncio
async def test_bot_rejeitado_nao_recebe_os_registros_dos_usuarios(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    intruso = await _conectar(servidor, sessao)
    await intruso.send_json({"user_ids": [_snowflake()], "bot": True})
    await asyncio.sleep(ASSENTAR)

    await _registrar_usuario(servidor, sessao, [_snowflake()])

    assert await _nada_recebido(intruso)


@pytest.mark.asyncio
async def test_guarda_usuario_nao_precisa_de_chave(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)

    await _registrar_usuario(servidor, sessao, [_snowflake()])  # sem X-RPC-Key, como o app desktop

    assert (await _receber(bot_ws))["op"] == "rpc_update"


async def _wsclient_interno(servidor: _Servidor) -> WSClient:
    """O WSClient como o BotPool o usa: aponta para o próprio servidor, com a MESMA pool/config, sem segredo à mão."""
    servidor.pool.get_all_bots = lambda: [_bot_falso(_snowflake())]
    client = WSClient(servidor.url_ws, servidor.pool)
    await client.connect()
    await asyncio.sleep(0.4)  # deixa o registro chegar ao servidor
    client.clear_tasks()
    return client


@pytest.mark.asyncio
async def test_guarda_bot_interno_conecta_ao_proprio_servidor_sem_configurar_segredo(iniciar_servidor, sessao):
    """O caso comum (RPC_SERVER=ws://localhost:$PORT/ws, sem RPC_SERVER_SECRET) segue funcionando de fábrica."""
    servidor = iniciar_servidor()
    client = await _wsclient_interno(servidor)
    try:
        await _registrar_usuario(servidor, sessao, [_snowflake()])
        recebido = json.loads((await client.connection.receive(timeout=ESPERA)).data)
    finally:
        await client.connection.close()
        await client.session.close()

    assert recebido["op"] == "rpc_update"


@pytest.mark.asyncio
async def test_guarda_bot_interno_conecta_com_o_segredo_configurado_no_ambiente(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    client = await _wsclient_interno(servidor)
    try:
        await _registrar_usuario(servidor, sessao, [_snowflake()])
        recebido = json.loads((await client.connection.receive(timeout=ESPERA)).data)
    finally:
        await client.connection.close()
        await client.session.close()

    assert recebido["op"] == "rpc_update"


# ---------------------------------------------------------------------------------------------------------------------
# Autenticação por usuário (ENABLE_RPC_AUTH): decidida só pela configuração do servidor
# ---------------------------------------------------------------------------------------------------------------------


async def _entrega(servidor, sessao, segredo, *, token_do_usuario, token_do_bot, auth_no_payload, com_campo=True):
    """Bot envia um ``update`` (do process_rpc real) ao usuário registrado; devolve (primeira mensagem, ws do bot, ws, id)."""
    bot_ws, _, usuario_ws, usuario = await _usuario_e_bot(servidor, sessao, segredo, token_do_usuario)
    stats = await _stats("update", usuario, token_do_bot, auth=auth_no_payload)
    if not com_campo:
        del stats["auth_enabled"]
    await bot_ws.send_json(stats)
    return await _receber(usuario_ws), bot_ws, usuario_ws, usuario


AUTH_LIGADA = {"ENABLE_RPC_AUTH": "true"}


@pytest.mark.asyncio
async def test_guarda_auth_ligada_token_igual_entrega_o_update(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo, **AUTH_LIGADA})
    token = _token_do_app()

    entregue, *_ = await _entrega(
        servidor, sessao, segredo, token_do_usuario=token, token_do_bot=token, auth_no_payload=True
    )

    assert entregue["op"] == "update"


@pytest.mark.asyncio
async def test_guarda_auth_ligada_token_divergente_bloqueia_a_entrega_e_avisa_o_usuario(
    iniciar_servidor, sessao, segredo
):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo, **AUTH_LIGADA})
    token_do_bot = _token_do_app()

    entregue, *_ = await _entrega(
        servidor, sessao, segredo, token_do_usuario=_token_do_app(), token_do_bot=token_do_bot, auth_no_payload=True
    )

    assert entregue["op"] == "exception"
    assert "token" in entregue["message"].lower()
    assert not {"token", "track", "info"} & set(entregue)
    assert token_do_bot not in json.dumps(entregue)


@pytest.mark.asyncio
async def test_guarda_auth_ligada_usuario_bloqueado_nao_recebe_ate_o_token_voltar_a_bater(
    iniciar_servidor, sessao, segredo
):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo, **AUTH_LIGADA})
    token_certo, token_errado = _token_do_app(), _token_do_app()
    _, bot_ws, usuario_ws, usuario = await _entrega(
        servidor, sessao, segredo, token_do_usuario=token_certo, token_do_bot=token_errado, auth_no_payload=True
    )

    await bot_ws.send_json(await _stats("update", usuario, token_errado, auth=True))
    assert await _nada_recebido(usuario_ws), "usuário bloqueado recebeu dados"

    await bot_ws.send_json(await _stats("update", usuario, token_certo, auth=True))
    assert (await _receber(usuario_ws))["op"] == "update"


@pytest.mark.asyncio
async def test_auth_ligada_token_que_volta_a_bater_desbloqueia_e_uma_nova_divergencia_avisa_de_novo(
    iniciar_servidor, sessao, segredo
):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo, **AUTH_LIGADA})
    token_certo, token_errado = _token_do_app(), _token_do_app()
    _, bot_ws, usuario_ws, usuario = await _entrega(
        servidor, sessao, segredo, token_do_usuario=token_certo, token_do_bot=token_errado, auth_no_payload=True
    )
    await bot_ws.send_json(await _stats("update", usuario, token_certo, auth=True))
    assert (await _receber(usuario_ws))["op"] == "update"

    await bot_ws.send_json(await _stats("update", usuario, token_errado, auth=True))

    assert (await _receber(usuario_ws))["op"] == "exception", (
        "o usuário continuou bloqueado após o token voltar a bater"
    )


@pytest.mark.asyncio
async def test_servidor_com_auth_ligada_ignora_auth_enabled_falso_enviado_pelo_bot(iniciar_servidor, sessao, segredo):
    """Hoje o servidor confia no ``auth_enabled`` do payload: com ``false`` a checagem do token é pulada."""
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo, **AUTH_LIGADA})

    entregue, *_ = await _entrega(
        servidor, sessao, segredo, token_do_usuario=_token_do_app(), token_do_bot=_token_do_app(), auth_no_payload=False
    )

    assert entregue["op"] == "exception"


@pytest.mark.asyncio
async def test_servidor_com_auth_ligada_exige_o_token_mesmo_sem_o_campo_auth_enabled(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo, **AUTH_LIGADA})

    entregue, *_ = await _entrega(
        servidor,
        sessao,
        segredo,
        token_do_usuario=_token_do_app(),
        token_do_bot=_token_do_app(),
        auth_no_payload=False,
        com_campo=False,
    )

    assert entregue["op"] == "exception"


@pytest.mark.asyncio
async def test_servidor_com_auth_desligada_ignora_auth_enabled_verdadeiro_enviado_pelo_bot(
    iniciar_servidor, sessao, segredo
):
    """Hoje ``auth_enabled: true`` no payload liga a checagem de token mesmo com o servidor em ENABLE_RPC_AUTH=false."""
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})

    entregue, *_ = await _entrega(
        servidor, sessao, segredo, token_do_usuario=_token_do_app(), token_do_bot=_token_do_app(), auth_no_payload=True
    )

    assert entregue["op"] == "update"


@pytest.mark.asyncio
async def test_guarda_auth_desligada_nao_compara_tokens(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})

    entregue, *_ = await _entrega(
        servidor, sessao, segredo, token_do_usuario="", token_do_bot=_token_do_app(), auth_no_payload=False
    )

    assert entregue["op"] == "update"


# ---------------------------------------------------------------------------------------------------------------------
# Origem do navegador (check_origin)
# ---------------------------------------------------------------------------------------------------------------------

ORIGENS_PERMITIDAS = "https://painel.exemplo.invalid, https://outro.exemplo.invalid"
AMBIENTE_COM_ORIGENS = {"RPC_ALLOWED_ORIGINS": ORIGENS_PERMITIDAS}


@pytest.mark.asyncio
async def test_guarda_origin_ausente_cliente_nativo_e_aceito(iniciar_servidor, sessao):
    servidor = iniciar_servidor()

    ws = await _conectar(servidor, sessao)

    assert not ws.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("origem", ["https://painel.exemplo.invalid", "https://outro.exemplo.invalid"])
async def test_guarda_origin_em_rpc_allowed_origins_e_aceita(iniciar_servidor, sessao, origem):
    servidor = iniciar_servidor(AMBIENTE_COM_ORIGENS)

    ws = await _conectar(servidor, sessao, origem=origem)

    assert not ws.closed


ORIGENS_ESTRANHAS = [
    "https://site-estranho.exemplo.invalid",
    "https://painel.exemplo.invalid.estranho.invalid",
    "http://painel.exemplo.invalid",
    "null",
    "http://localhost:{porta}",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("origem", ORIGENS_ESTRANHAS)
@pytest.mark.parametrize("com_lista", [True, False], ids=["com-lista", "lista-vazia"])
async def test_origin_de_outra_origem_e_rejeitada_com_403(iniciar_servidor, sessao, origem, com_lista):
    """Hoje ``check_origin`` devolve sempre True."""
    servidor = iniciar_servidor(AMBIENTE_COM_ORIGENS if com_lista else {})

    with pytest.raises(aiohttp.WSServerHandshakeError) as erro:
        await _conectar(servidor, sessao, origem=origem.format(porta=servidor.porta))

    assert erro.value.status == 403


# ---------------------------------------------------------------------------------------------------------------------
# Limites: tamanho da mensagem, IDs, número de conexões e taxa
# ---------------------------------------------------------------------------------------------------------------------


def _json_com_tamanho(base: dict, tamanho: int) -> str:
    """JSON de ``base`` com um campo ``pad`` ajustado para o texto ter exatamente ``tamanho`` caracteres ASCII."""
    vazio = len(json.dumps({**base, "pad": ""}))
    texto = json.dumps({**base, "pad": "x" * (tamanho - vazio)})
    assert len(texto) == tamanho
    return texto


@pytest.mark.asyncio
async def test_mensagem_acima_de_64_kib_fecha_a_conexao(iniciar_servidor, sessao):
    """Hoje o limite do Tornado é o padrão (10 MiB): a mensagem de 64 KiB + 1 é processada normalmente."""
    servidor = iniciar_servidor()
    ws = await _conectar(servidor, sessao)

    await ws.send_str(_json_com_tamanho(_mensagem_usuario([_snowflake()]), TAMANHO_MAXIMO_MENSAGEM + 1))

    assert await _fechamento(ws) == 1009


@pytest.mark.asyncio
async def test_guarda_mensagem_de_exatamente_64_kib_e_aceita(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    ws = await _conectar(servidor, sessao)

    await ws.send_str(_json_com_tamanho(_mensagem_usuario([_snowflake()]), TAMANHO_MAXIMO_MENSAGEM))

    assert (await _receber(bot_ws))["op"] == "rpc_update"
    assert not ws.closed


def _fechou_de_proposito(codigo: int | None) -> bool:
    """Fechamento decidido pelo servidor (código de aplicação/política), não queda de conexão nem silêncio."""
    return codigo not in (None, -1, 1006)


IDS_INVALIDOS = {
    "texto": lambda: [str(_snowflake())],
    "negativo": lambda: [-_snowflake()],
    "booleano": lambda: [True],
    "zero": lambda: [0],
    "14-digitos": lambda: [10**13 + secrets.randbelow(9 * 10**13)],
    "21-digitos": lambda: [10**20 + secrets.randbelow(9 * 10**20)],
    "decimal": lambda: [float(_snowflake())],
    "nulo": lambda: [None],
    "lista-aninhada": lambda: [[_snowflake()]],
    "objeto": lambda: [{"id": _snowflake()}],
    "um-valido-e-um-texto": lambda: [_snowflake(), "x"],
}
IDS_VALIDOS = {
    "18-digitos": lambda: [_snowflake()],
    "15-digitos": lambda: [10**14 + secrets.randbelow(9 * 10**14)],
    "20-digitos": lambda: [10**19 + secrets.randbelow(9 * 10**19)],
    "tres-ids": lambda: [_snowflake() for _ in range(3)],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", sorted(IDS_INVALIDOS))
async def test_usuario_com_user_ids_invalidos_e_recusado_e_nao_e_repassado(iniciar_servidor, sessao, segredo, caso):
    """Hoje qualquer valor é aceito como ID (inclusive texto, negativo e booleano) e repassado aos bots."""
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    ws = await _conectar(servidor, sessao)

    await ws.send_json(_mensagem_usuario(IDS_INVALIDOS[caso]()))

    codigo = await _fechamento(ws)
    assert _fechou_de_proposito(codigo), f"o servidor não recusou a conexão (código {codigo})"
    assert await _nada_recebido(bot_ws)


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", sorted(IDS_VALIDOS))
async def test_guarda_usuario_com_user_ids_validos_e_aceito_e_repassado(iniciar_servidor, sessao, segredo, caso):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    ids = IDS_VALIDOS[caso]()

    await _registrar_usuario(servidor, sessao, ids)

    assert (await _receber(bot_ws))["user_ids"] == ids


@pytest.mark.asyncio
async def test_guarda_usuario_com_quatro_ids_e_recusado_e_nao_e_repassado(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    ws = await _conectar(servidor, sessao)

    await ws.send_json(_mensagem_usuario([_snowflake() for _ in range(4)]))

    codigo = await _fechamento(ws)
    assert _fechou_de_proposito(codigo), f"o servidor não recusou a conexão (código {codigo})"
    assert await _nada_recebido(bot_ws)


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", sorted(IDS_INVALIDOS))
async def test_bot_com_user_ids_invalidos_e_recusado(iniciar_servidor, sessao, segredo, caso):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    ws = await _conectar(servidor, sessao, chave=segredo)

    await ws.send_json({"user_ids": IDS_INVALIDOS[caso](), "bot": True})

    codigo = await _fechamento(ws)
    assert _fechou_de_proposito(codigo), f"o servidor não recusou a conexão (código {codigo})"


@pytest.mark.asyncio
async def test_guarda_bot_com_250_ids_e_aceito(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo, [_snowflake() for _ in range(LIMITE_IDS_BOT)])

    await _registrar_usuario(servidor, sessao, [_snowflake()])

    assert (await _receber(bot_ws))["op"] == "rpc_update"


@pytest.mark.asyncio
async def test_bot_com_mais_de_250_ids_e_recusado(iniciar_servidor, sessao, segredo):
    """Hoje o número de IDs de um bot não tem limite."""
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    ws = await _conectar(servidor, sessao, chave=segredo)

    await ws.send_json({"user_ids": [_snowflake() for _ in range(LIMITE_IDS_BOT + 1)], "bot": True})

    codigo = await _fechamento(ws)
    assert _fechou_de_proposito(codigo), f"o servidor não recusou a conexão (código {codigo})"


@pytest.fixture
def muitos_arquivos_abertos():
    """O teste de 1000 conexões usa ~2000 descritores (cliente + servidor): sobe o limite brando ou pula."""
    import resource

    brando, duro = resource.getrlimit(resource.RLIMIT_NOFILE)
    necessario = 4 * LIMITE_CONEXOES
    if brando < necessario:
        if duro != resource.RLIM_INFINITY and duro < necessario:
            pytest.skip(f"limite de arquivos abertos ({duro}) menor que {necessario}")
        resource.setrlimit(resource.RLIMIT_NOFILE, (necessario, duro))
    yield
    resource.setrlimit(resource.RLIMIT_NOFILE, (brando, duro))


async def _abrir_conexoes(servidor, sessao, quantidade: int) -> list:
    abertas = []
    for inicio in range(0, quantidade, 50):
        lote = min(50, quantidade - inicio)
        abertas += await asyncio.gather(*(_conectar(servidor, sessao) for _ in range(lote)))
    return abertas


@pytest.mark.asyncio
async def test_conexao_alem_de_1000_e_fechada_com_1013_e_o_limite_e_liberado_ao_fechar(
    iniciar_servidor, sessao, muitos_arquivos_abertos
):
    """Hoje não há limite de conexões simultâneas."""
    servidor = iniciar_servidor()
    abertas = await _abrir_conexoes(servidor, sessao, LIMITE_CONEXOES)
    await asyncio.sleep(0.3)
    assert not any(ws.closed for ws in abertas), "o servidor fechou conexões dentro do limite"
    assert await _fechamento(abertas[-1], 0.6) is None, "a conexão 1000 (a última dentro do limite) foi recusada"

    excedente = await _conectar(servidor, sessao)
    assert await _fechamento(excedente) == 1013, "a conexão 1001 não foi recusada com 1013"

    await abertas[0].close()
    await asyncio.sleep(0.5)
    de_novo = await _conectar(servidor, sessao)
    assert await _fechamento(de_novo, 0.6) is None, "o limite não foi liberado quando uma conexão fechou"


async def _enviar_usuarios_novos(ws, quantidade: int) -> None:
    """Mensagens de registro válidas, cada uma com um ID novo (não se confundem com sobrescrita de sessão)."""
    for _ in range(quantidade):
        await ws.send_json(_mensagem_usuario([_snowflake()]))


@pytest.mark.asyncio
async def test_guarda_usuario_pode_enviar_20_mensagens_seguidas_sem_ser_fechado(iniciar_servidor, sessao):
    servidor = iniciar_servidor()
    ws = await _conectar(servidor, sessao)

    await _enviar_usuarios_novos(ws, LIMITE_MENSAGENS)

    assert await _fechamento(ws, 0.6) is None


@pytest.mark.asyncio
async def test_usuario_que_passa_de_20_mensagens_em_10_s_e_fechado_com_4429(iniciar_servidor, sessao):
    """Hoje não há limite de taxa."""
    servidor = iniciar_servidor()
    ws = await _conectar(servidor, sessao)

    await _enviar_usuarios_novos(ws, LIMITE_MENSAGENS + 1)

    assert await _fechamento(ws) == 4429


@pytest.mark.asyncio
async def test_guarda_bot_autenticado_nao_tem_limite_de_taxa(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _, usuario_ws, usuario = await _usuario_e_bot(servidor, sessao, segredo)

    for _ in range(3 * LIMITE_MENSAGENS):
        await bot_ws.send_json(await _stats("idle", usuario, _token_do_app()))

    assert await _fechamento(bot_ws, 0.6) is None
    assert (await _receber(usuario_ws))["op"] == "idle"


# ---------------------------------------------------------------------------------------------------------------------
# JSON inválido ou que não é objeto (servidor): 4400 sem derrubar o handler e sem expor o conteúdo no log
# ---------------------------------------------------------------------------------------------------------------------

QUADROS_INVALIDOS = {
    "texto": "isto nao e json",
    "truncado": '{"op": "rpc_update", "user_ids": [',
    "lista": "[]",
    "texto-json": '"texto"',
    "numero": "42",
    "nulo": "null",
    "booleano": "true",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("quem", ["usuario", "bot"])
@pytest.mark.parametrize("quadro", sorted(QUADROS_INVALIDOS))
async def test_json_invalido_ou_que_nao_e_objeto_fecha_com_4400(iniciar_servidor, sessao, segredo, quadro, quem):
    """Hoje o ``json.loads`` ou o ``.get`` levanta dentro do handler e o Tornado derruba a conexão (1006)."""
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    if quem == "bot":
        ws, _ = await _registrar_bot(servidor, sessao, segredo)
    else:
        ws = await _conectar(servidor, sessao)

    await ws.send_str(QUADROS_INVALIDOS[quadro])

    assert await _fechamento(ws) == 4400


@pytest.mark.asyncio
async def test_guarda_servidor_segue_atendendo_depois_de_uma_mensagem_invalida(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    ruim = await _conectar(servidor, sessao)
    await ruim.send_str(QUADROS_INVALIDOS["texto"])
    await _fechamento(ruim)

    await _registrar_usuario(servidor, sessao, [_snowflake()])

    assert (await _receber(bot_ws))["op"] == "rpc_update"


@pytest.mark.asyncio
async def test_json_invalido_loga_so_o_nome_da_excecao(iniciar_servidor, sessao, segredo, caplog, capsys):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    sensivel = secrets.token_hex(12)
    ws = await _conectar(servidor, sessao)

    with caplog.at_level(logging.DEBUG):
        await ws.send_str('{"token": "' + sensivel)  # truncado: o conteúdo nunca pode ir para o log
        codigo = await _fechamento(ws)

    saida = capsys.readouterr()
    assert codigo == 4400
    assert sensivel not in caplog.text + saida.out + saida.err
    avisos = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("JSONDecodeError" in a or "ValueError" in a for a in avisos), avisos


# ---------------------------------------------------------------------------------------------------------------------
# KI-25: fechar uma conexão que nunca foi registrada como bot
# ---------------------------------------------------------------------------------------------------------------------


def _value_error_do_servidor(caplog) -> list[str]:
    """Registros (de qualquer nível) com um ValueError cujo traceback passa por web_app.py.

    O Tornado captura o ValueError de ``on_close`` e o registra em DEBUG ("Malformed WebSocket request received").
    """
    achados = []
    for registro in caplog.records:
        if registro.exc_info and registro.exc_info[0] is ValueError:
            texto = "".join(traceback.format_exception(*registro.exc_info))
            if "web_app.py" in texto:
                achados.append(texto.strip().splitlines()[-1])
    return achados


async def _fechar_e_observar(servidor, sessao, caplog, como: str) -> list[str]:
    """Abre uma conexão, faz ``como`` e a fecha; devolve os ValueError do servidor vistos no log."""
    with caplog.at_level(logging.DEBUG):
        ws = await _conectar(servidor, sessao)
        if como == "bot-rejeitado":
            await ws.send_json({"user_ids": [_snowflake()], "bot": True})
        elif como == "usuario-registrado":
            await ws.send_json(_mensagem_usuario([_snowflake()]))
        elif como == "mensagem-sem-ids":
            await ws.send_json({"op": "rpc_update"})
        await asyncio.sleep(ASSENTAR)
        await ws.close()
        await asyncio.sleep(0.4)
    return _value_error_do_servidor(caplog)


@pytest.mark.asyncio
@pytest.mark.parametrize("como", ["sem-enviar-nada", "mensagem-sem-ids"])
async def test_fechar_conexao_nunca_registrada_nao_gera_value_error(iniciar_servidor, sessao, segredo, caplog, como):
    """Hoje ``bots_ws.remove(self)`` roda para qualquer conexão que não era usuário: ``ValueError: x not in list``."""
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})

    assert await _fechar_e_observar(servidor, sessao, caplog, como) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("como", ["usuario-registrado", "bot-rejeitado"])
async def test_guarda_fechar_usuario_registrado_ou_bot_recusado_nao_gera_value_error(
    iniciar_servidor, sessao, segredo, caplog, como
):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})

    assert await _fechar_e_observar(servidor, sessao, caplog, como) == []


@pytest.mark.asyncio
async def test_guarda_fechar_o_bot_registrado_nao_gera_erro(iniciar_servidor, sessao, segredo, caplog):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    with caplog.at_level(logging.DEBUG):
        bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
        await bot_ws.close()
        await asyncio.sleep(0.4)

    assert _value_error_do_servidor(caplog) == []
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


# ---------------------------------------------------------------------------------------------------------------------
# Endereço de escuta (WEB_BIND_ADDRESS) e aviso quando a auth está desligada e o bind é público
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bind_padrao_e_0_0_0_0(iniciar_servidor):
    """Hoje o ``listen`` não recebe endereço (``None``)."""
    assert iniciar_servidor().escuta["address"] == "0.0.0.0"


@pytest.mark.asyncio
async def test_bind_vazio_na_configuracao_volta_ao_padrao_0_0_0_0(iniciar_servidor):
    servidor = iniciar_servidor()
    servidor.pool.config["WEB_BIND_ADDRESS"] = ""
    web_app.run_app(servidor.pool, "")

    assert servidor.escuta["address"] == "0.0.0.0"


@pytest.mark.asyncio
@pytest.mark.parametrize("endereco", ["127.0.0.1", "192.0.2.10", "::1"])
async def test_web_bind_address_e_repassado_ao_listen(iniciar_servidor, endereco):
    assert iniciar_servidor({"WEB_BIND_ADDRESS": endereco}).escuta["address"] == endereco


@pytest.mark.asyncio
async def test_guarda_a_porta_continua_vindo_da_configuracao(iniciar_servidor):
    assert iniciar_servidor({"PORT": "9000"}).escuta["port"] == 9000


def _avisou_sobre_a_auth(caplog, capsys) -> bool:
    textos = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    saida = capsys.readouterr()
    textos += [saida.out, saida.err]
    return any(re.search(r"ENABLE_RPC_AUTH|autentica", t, re.IGNORECASE) for t in textos)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "env", [{}, {"WEB_BIND_ADDRESS": "0.0.0.0"}, {"WEB_BIND_ADDRESS": "::"}], ids=["padrao", "0.0.0.0", "ipv6"]
)
async def test_aviso_na_inicializacao_quando_a_auth_esta_desligada_e_o_bind_e_publico(
    iniciar_servidor, caplog, capsys, env
):
    """Hoje nada é avisado."""
    with caplog.at_level(logging.WARNING):
        iniciar_servidor(env)

    assert _avisou_sobre_a_auth(caplog, capsys)


@pytest.mark.asyncio
async def test_guarda_sem_aviso_quando_a_auth_esta_ligada(iniciar_servidor, caplog, capsys):
    with caplog.at_level(logging.WARNING):
        iniciar_servidor(AUTH_LIGADA)

    assert not _avisou_sobre_a_auth(caplog, capsys)


@pytest.mark.asyncio
async def test_guarda_sem_aviso_quando_o_bind_e_local(iniciar_servidor, caplog, capsys):
    with caplog.at_level(logging.WARNING):
        iniciar_servidor({"WEB_BIND_ADDRESS": "127.0.0.1"})

    assert not _avisou_sobre_a_auth(caplog, capsys)


# ---------------------------------------------------------------------------------------------------------------------
# Quem pode enviar mensagens bot -> usuário: só uma conexão autenticada E registrada como bot
# ---------------------------------------------------------------------------------------------------------------------

REMETENTES_NAO_AUTORIZADOS = [
    "anonima",
    "chave-errada",
    "chave-valida-sem-registro",
    "usuario-registrado",
    "bot-rejeitado",
]
AMBIENTES_DE_AUTH = {"auth-desligada": {}, "auth-ligada": AUTH_LIGADA}


async def _remetente(servidor, sessao, segredo: str, tipo: str):
    if tipo == "anonima":
        return await _conectar(servidor, sessao)
    if tipo == "chave-errada":
        return await _conectar(servidor, sessao, chave=secrets.token_hex(16))
    if tipo == "chave-valida-sem-registro":
        return await _conectar(servidor, sessao, chave=segredo)  # autenticada, mas nunca registrada com bot: true
    if tipo == "usuario-registrado":
        return await _registrar_usuario(servidor, sessao, [_snowflake()])
    ws = await _conectar(servidor, sessao, chave=secrets.token_hex(16))  # bot-rejeitado: registro com chave errada
    await ws.send_json({"user_ids": [_snowflake()], "bot": True})
    await asyncio.sleep(ASSENTAR)
    return ws


async def _tentar_enviar(ws, payload: dict) -> None:
    """Envia, aceitando que o servidor já possa ter fechado a conexão (o que é o esperado para quem não é bot)."""
    try:
        await ws.send_json(payload)
    except (ConnectionError, aiohttp.ClientError, RuntimeError):
        pass


def _mensagens_para_usuario(usuario: int, bot_id: int) -> dict:
    """Formas de mensagem bot -> usuário (sem ``user_ids``), incluindo as que o servidor também gera."""
    return {
        "minimo": {"op": "update", "bot_id": bot_id, "user": usuario},
        "so-user": {"op": "update", "user": usuario},
        "exception": {"op": "exception", "message": "mensagem forjada", "bot_id": bot_id, "user": usuario},
        "close": {"op": "close", "bot_id": bot_id, "user": usuario},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("auth", sorted(AMBIENTES_DE_AUTH))
@pytest.mark.parametrize("tipo", REMETENTES_NAO_AUTORIZADOS)
async def test_so_conexao_autenticada_como_bot_pode_enviar_dados_ao_usuario(
    iniciar_servidor, sessao, segredo, tipo, auth
):
    """Hoje qualquer conexão que mande ``bot_id`` + ``user`` entrega o conteúdo ao usuário conectado."""
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo, **AMBIENTES_DE_AUTH[auth]})
    token = _token_do_app()  # o mesmo token na mensagem: a recusa tem de vir do remetente, não da comparação do token
    usuario = _snowflake()
    usuario_ws = await _registrar_usuario(servidor, sessao, [usuario], token)
    remetente = await _remetente(servidor, sessao, segredo, tipo)

    await _tentar_enviar(remetente, await _stats("update", usuario, token, auth=(auth == "auth-ligada")))

    assert await _nada_recebido(usuario_ws), "o usuário recebeu dados de uma conexão que não é um bot autenticado"
    assert await _fechamento(remetente) == 4401


@pytest.mark.asyncio
@pytest.mark.parametrize("forma", sorted(_mensagens_para_usuario(0, 0)))
async def test_mensagem_bot_para_usuario_de_conexao_anonima_e_recusada_em_qualquer_forma(
    iniciar_servidor, sessao, segredo, forma
):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    usuario = _snowflake()
    usuario_ws = await _registrar_usuario(servidor, sessao, [usuario])
    anonima = await _conectar(servidor, sessao)

    await _tentar_enviar(anonima, _mensagens_para_usuario(usuario, _snowflake())[forma])

    assert await _nada_recebido(usuario_ws), "o usuário recebeu uma mensagem de uma conexão anônima"
    assert await _fechamento(anonima) == 4401


@pytest.mark.asyncio
@pytest.mark.parametrize("auth", sorted(AMBIENTES_DE_AUTH))
async def test_guarda_bot_autenticado_continua_entregando_ao_usuario(iniciar_servidor, sessao, segredo, auth):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo, **AMBIENTES_DE_AUTH[auth]})
    token = _token_do_app()
    bot_ws, _, usuario_ws, usuario = await _usuario_e_bot(servidor, sessao, segredo, token)

    await bot_ws.send_json(await _stats("update", usuario, token, auth=(auth == "auth-ligada")))

    assert (await _receber(usuario_ws))["op"] == "update"
    assert not bot_ws.closed


@pytest.mark.asyncio
async def test_guarda_bot_autenticado_entrega_update_idle_e_close_em_sequencia(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _, usuario_ws, usuario = await _usuario_e_bot(servidor, sessao, segredo)

    for op in ("update", "idle", "close"):
        await bot_ws.send_json(await _stats(op, usuario, _token_do_app()))
        assert (await _receber(usuario_ws))["op"] == op
    assert not bot_ws.closed


@pytest.mark.asyncio
async def test_guarda_bot_interno_via_wsclient_entrega_dados_ao_usuario_sem_segredo_configurado(
    iniciar_servidor, sessao
):
    """O fluxo real do bot: WSClient registra e depois envia pelo ``send`` (o mesmo caminho do ``_send_rpc_data``)."""
    servidor = iniciar_servidor()
    usuario = _snowflake()
    usuario_ws = await _registrar_usuario(servidor, sessao, [usuario])
    client = await _wsclient_interno(servidor)
    try:
        await client.send(await _stats("update", usuario, _token_do_app()))
        entregue = await _receber(usuario_ws)
    finally:
        await client.connection.close()
        await client.session.close()

    assert entregue["op"] == "update" and entregue["user"] == usuario


# ---------------------------------------------------------------------------------------------------------------------
# Complementos da validação: o bot autenticado só entrega ops conhecidas; sessões; versão e token; WSClient
# ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["disconnect", "exception", "rpc_update", "qualquer-coisa", None, 5])
async def test_bot_autenticado_so_entrega_as_ops_update_idle_e_close(iniciar_servidor, sessao, segredo, op):
    """Um ``disconnect`` ou ``exception`` vindo do bot faria o app do usuário se desconectar ou exibir erro alheio."""
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _, usuario_ws, usuario = await _usuario_e_bot(servidor, sessao, segredo)

    await bot_ws.send_json({"op": op, "bot_id": _snowflake(), "user": usuario, "message": "x", "reason": "x"})

    assert await _nada_recebido(usuario_ws), "o usuário recebeu uma op que o bot não pode enviar"
    assert not bot_ws.closed


@pytest.mark.asyncio
async def test_bot_registrado_que_registra_de_novo_e_fechado_com_4400(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)

    await bot_ws.send_json({"user_ids": [_snowflake()], "bot": True})

    assert await _fechamento(bot_ws) == 4400


@pytest.mark.asyncio
async def test_sessao_nova_do_mesmo_usuario_substitui_a_antiga_e_nao_e_removida_quando_a_antiga_fecha(
    iniciar_servidor, sessao, segredo
):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    usuario = _snowflake()
    antiga = await _registrar_usuario(servidor, sessao, [usuario])
    nova = await _registrar_usuario(servidor, sessao, [usuario])

    assert (await _receber(antiga))["op"] == "disconnect"
    assert await _fechamento(antiga) == 4200
    await asyncio.sleep(0.3)  # o on_close da sessão antiga já rodou
    await bot_ws.send_json(await _stats("update", usuario, _token_do_app()))

    assert (await _receber(nova))["op"] == "update"


@pytest.mark.asyncio
async def test_re_registro_na_mesma_conexao_esquece_os_ids_antigos(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    antigo, novo = _snowflake(), _snowflake()
    ws = await _registrar_usuario(servidor, sessao, [antigo])
    await ws.send_json(_mensagem_usuario([novo]))
    await asyncio.sleep(ASSENTAR)

    await bot_ws.send_json(await _stats("update", antigo, _token_do_app()))
    assert await _nada_recebido(ws), "o id antigo ainda é entregue depois do re-registro"

    await bot_ws.send_json(await _stats("update", novo, _token_do_app()))
    assert (await _receber(ws))["user"] == novo


@pytest.mark.asyncio
async def test_guarda_usuario_bloqueado_por_token_nao_recebe_o_close_do_bot(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo, **AUTH_LIGADA})
    _, bot_ws, usuario_ws, _ = await _entrega(
        servidor, sessao, segredo, token_do_usuario=_token_do_app(), token_do_bot=_token_do_app(), auth_no_payload=True
    )

    await bot_ws.close()

    assert await _nada_recebido(usuario_ws), "usuário bloqueado recebeu o close do bot"


@pytest.mark.asyncio
async def test_mensagem_enviada_logo_depois_de_uma_recusa_nao_e_processada(iniciar_servidor, sessao, segredo):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    ws = await _conectar(servidor, sessao)

    await ws.send_json(_mensagem_usuario(["id-invalido"]))
    await ws.send_json(_mensagem_usuario([_snowflake()]))  # válida, mas já na conexão recusada

    assert await _nada_recebido(bot_ws)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("versao", "aceita"),
    [("2.6.1", True), ("2.6.2", True), ("3.0.0", True), ("2.6.0", False), ("1.0.0", False), ("abc", False)],
)
async def test_versao_minima_do_app_e_2_6_1(iniciar_servidor, sessao, segredo, versao, aceita):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    ws = await _conectar(servidor, sessao)

    await ws.send_json(_mensagem_usuario([_snowflake()]) | {"version": versao})

    if aceita:
        assert (await _receber(bot_ws))["version"] == versao
    else:
        assert (await _receber(ws))["op"] == "disconnect"
        assert await _nada_recebido(bot_ws)


@pytest.mark.asyncio
@pytest.mark.parametrize("versao", [None, 3, ["3.0.0"], "9" * 40], ids=["ausente", "numero", "lista", "longa"])
async def test_versao_ausente_ou_com_formato_invalido_e_recusada(iniciar_servidor, sessao, segredo, versao):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    ws = await _conectar(servidor, sessao)
    mensagem = _mensagem_usuario([_snowflake()])
    mensagem["version"] = versao

    await ws.send_json(mensagem)

    assert (await _receber(ws))["op"] == "disconnect"
    assert await _nada_recebido(bot_ws)


@pytest.mark.asyncio
@pytest.mark.parametrize("tamanho", [1, 49, 51, 100])
async def test_token_de_usuario_so_pode_ter_0_ou_50_caracteres(iniciar_servidor, sessao, segredo, tamanho):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    ws = await _conectar(servidor, sessao)

    await ws.send_json(_mensagem_usuario([_snowflake()], "t" * tamanho))

    assert (await _receber(ws))["op"] == "disconnect"
    assert await _nada_recebido(bot_ws)


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [123, ["a"], {"a": 1}, True], ids=["numero", "lista", "objeto", "booleano"])
async def test_token_de_usuario_que_nao_e_texto_e_recusado(iniciar_servidor, sessao, segredo, token):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    ws = await _conectar(servidor, sessao)

    await ws.send_json(_mensagem_usuario([_snowflake()]) | {"token": token})

    codigo = await _fechamento(ws)
    assert _fechou_de_proposito(codigo), f"o servidor não recusou o token (código {codigo})"
    assert await _nada_recebido(bot_ws)


@pytest.mark.asyncio
@pytest.mark.parametrize("quem", ["usuario", "bot"])
async def test_lista_vazia_de_user_ids_e_recusada(iniciar_servidor, sessao, segredo, quem):
    servidor = iniciar_servidor({"RPC_SERVER_SECRET": segredo})
    bot_ws, _ = await _registrar_bot(servidor, sessao, segredo)
    ws = await _conectar(servidor, sessao, chave=segredo if quem == "bot" else None)

    await ws.send_json({**_mensagem_usuario([]), **({"bot": True} if quem == "bot" else {})})

    codigo = await _fechamento(ws)
    assert _fechou_de_proposito(codigo), f"o servidor não recusou a lista vazia (código {codigo})"
    assert await _nada_recebido(bot_ws)


@pytest.mark.asyncio
async def test_origem_da_lista_e_comparada_sem_diferenca_de_caixa_barra_final_e_espacos(iniciar_servidor, sessao):
    servidor = iniciar_servidor(
        {"RPC_ALLOWED_ORIGINS": " HTTPS://Painel.Exemplo.Invalid/ ,, https://outro.exemplo.invalid "}
    )

    for origem in ("https://painel.exemplo.invalid", "https://outro.exemplo.invalid"):
        ws = await _conectar(servidor, sessao, origem=origem)
        assert not ws.closed


@pytest.mark.asyncio
async def test_origin_vazio_nao_e_aceito_por_causa_de_entradas_vazias_na_lista(iniciar_servidor, sessao):
    servidor = iniciar_servidor({"RPC_ALLOWED_ORIGINS": ",, ,https://painel.exemplo.invalid,"})

    with pytest.raises(aiohttp.WSServerHandshakeError) as erro:
        await _conectar(servidor, sessao, origem="")

    assert erro.value.status == 403


# --- WSClient: nada é enviado antes do registro; a sincronização depois dele reenvia o estado --------------------------


class _Conversas:
    """Servidor aiohttp falso que guarda, por conexão, os quadros recebidos (JSON) e a ordem dos eventos."""

    def __init__(self):
        self.por_conexao: list[list[dict]] = []
        self.eventos: list[str] = []

    async def roteiro(self, ws, request):
        quadros: list[dict] = []
        self.por_conexao.append(quadros)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                quadros.append(json.loads(msg.data))
                if quadros[-1].get("bot") is True:
                    self.eventos.append("registro")


def _bot_que_espera(bot_id: int, liberar: asyncio.Event, jogadores: dict | None = None) -> SimpleNamespace:
    async def esperar():
        await liberar.wait()

    bot = _bot_falso(bot_id, jogadores)
    bot.wait_until_ready = AsyncMock(side_effect=esperar)
    return bot


@pytest.mark.asyncio
async def test_wsclient_descarta_dados_enviados_antes_do_registro(servidor_aiohttp_falso, tmp_path, monkeypatch):
    conversas, liberar = _Conversas(), asyncio.Event()
    url = await servidor_aiohttp_falso(conversas.roteiro)
    client = _wsclient(url, [_bot_que_espera(_snowflake(), liberar)], tmp_path, monkeypatch)
    try:
        await client.connect()
        await client.send({"op": "update", "marcador": "antes-do-registro"})
        await asyncio.sleep(0.3)
        assert conversas.por_conexao[0] == [], "dados foram enviados antes do registro"

        liberar.set()
        await asyncio.sleep(0.3)
        await client.send({"op": "update", "marcador": "depois-do-registro"})
        await asyncio.sleep(0.3)
    finally:
        client.clear_tasks()
        await client.session.close()

    quadros = conversas.por_conexao[0]
    assert quadros[0]["bot"] is True
    assert [q.get("marcador") for q in quadros[1:]] == ["depois-do-registro"]


@pytest.mark.asyncio
async def test_wsclient_descarta_dados_enquanto_o_registro_ainda_esta_sendo_enviado(
    servidor_aiohttp_falso, tmp_path, monkeypatch
):
    conversas = _Conversas()
    url = await servidor_aiohttp_falso(conversas.roteiro)
    client = _wsclient(url, [_bot_falso(_snowflake())], tmp_path, monkeypatch)
    no_envio, liberar_envio, enviados = asyncio.Event(), asyncio.Event(), []

    async def envio_lento(data):
        enviados.append(data)
        no_envio.set()
        await liberar_envio.wait()

    monkeypatch.setattr(client, "_send_json", envio_lento)
    try:
        await client.connect()
        await asyncio.wait_for(no_envio.wait(), ESPERA)
        await asyncio.wait_for(client.send({"op": "update", "marcador": "durante-o-registro"}), ESPERA)
    finally:
        liberar_envio.set()
        client.clear_tasks()
        await client.session.close()

    assert [d.get("marcador") for d in enviados] == [None], "dados saíram antes de o registro ser concluído"
    assert enviados[0]["bot"] is True


@pytest.mark.asyncio
async def test_wsclient_volta_a_descartar_dados_ao_reconectar_ate_o_novo_registro(
    servidor_aiohttp_falso, tmp_path, monkeypatch
):
    conversas = _Conversas()
    url = await servidor_aiohttp_falso(conversas.roteiro)
    primeira_vez = {"feita": False}
    segunda_liberada = asyncio.Event()

    async def esperar():
        if primeira_vez["feita"]:
            await segunda_liberada.wait()
        primeira_vez["feita"] = True

    bot = _bot_falso(_snowflake())
    bot.wait_until_ready = AsyncMock(side_effect=esperar)
    client = _wsclient(url, [bot], tmp_path, monkeypatch)
    try:
        await client.connect()
        await asyncio.sleep(0.3)  # 1ª conexão registrada
        await client.connect()  # reconexão: o registro novo ainda não saiu
        await client.send({"op": "update", "marcador": "na-reconexao"})
        await asyncio.sleep(0.3)
        assert conversas.por_conexao[1] == [], "dados foram enviados antes do novo registro"
    finally:
        segunda_liberada.set()
        client.clear_tasks()
        await client.session.close()


@pytest.mark.asyncio
async def test_wsclient_apos_o_registro_pede_aos_jogadores_em_chamada_que_reenviem_o_estado(
    servidor_aiohttp_falso, tmp_path, monkeypatch
):
    conversas = _Conversas()

    def jogador(*, na_chamada: bool, com_ouvintes: bool):
        canal = SimpleNamespace(voice_states={_snowflake(): object()} if com_ouvintes else {})
        voz = SimpleNamespace(channel=canal) if na_chamada else None
        j = SimpleNamespace(
            guild=SimpleNamespace(me=SimpleNamespace(voice=voz)),
            last_channel=object(),
            process_rpc=AsyncMock(side_effect=lambda canal_: conversas.eventos.append("sincronizacao")),
        )
        return j

    com_estado = jogador(na_chamada=True, com_ouvintes=True)
    fora_da_chamada = jogador(na_chamada=False, com_ouvintes=True)
    sem_ouvintes = jogador(na_chamada=True, com_ouvintes=False)
    jogadores = {1: com_estado, 2: fora_da_chamada, 3: sem_ouvintes}
    url = await servidor_aiohttp_falso(conversas.roteiro)
    client = _wsclient(url, [_bot_falso(_snowflake(), jogadores)], tmp_path, monkeypatch)
    try:
        await client.connect()
        await asyncio.wait(client.connect_task, timeout=5)  # inclui a pausa de 1 s antes da sincronização
        await asyncio.sleep(0.1)
    finally:
        await client.session.close()

    assert conversas.eventos == ["registro", "sincronizacao"], "a sincronização tem de vir depois do registro"
    com_estado.process_rpc.assert_called_once_with(com_estado.last_channel)
    fora_da_chamada.process_rpc.assert_not_called()
    sem_ouvintes.process_rpc.assert_not_called()


# --- protocolo puro (empiremuse/rpc_protocol.py) -----------------------------------------------------------------------


def test_same_secret_so_confere_texto_nao_vazio_e_igual():
    assert rpc_protocol.same_secret("abc", "abc") is True
    for fornecido, esperado in [
        ("abd", "abc"),
        ("abc ", "abc"),
        ("", "abc"),
        ("", ""),
        ("abc", ""),
        (None, "abc"),
        (123, "123"),
    ]:
        assert rpc_protocol.same_secret(fornecido, esperado) is False, (fornecido, esperado)


def test_get_rpc_secret_usa_o_configurado_sem_espacos_e_senao_um_efemero_estavel_e_longo():
    assert rpc_protocol.get_rpc_secret({"RPC_SERVER_SECRET": "  abc  "}) == "abc"
    efemero = rpc_protocol.get_rpc_secret({})
    assert efemero == rpc_protocol.get_rpc_secret({"RPC_SERVER_SECRET": "   "}) == rpc_protocol.get_rpc_secret({})
    assert len(efemero) >= 64 and efemero != "abc"


def test_is_valid_id_limites_exatos():
    assert rpc_protocol.is_valid_id(10**14) is True
    assert rpc_protocol.is_valid_id(10**20 - 1) is True
    for invalido in (10**14 - 1, 10**20, 0, -(10**15), True, 1e17, float(10**17), "100000000000000000", None):
        assert rpc_protocol.is_valid_id(invalido) is False, invalido


def test_is_valid_id_list_exige_lista_nao_vazia_e_respeita_o_limite():
    ids = [10**15 + i for i in range(3)]
    assert rpc_protocol.is_valid_id_list(ids) is True
    assert rpc_protocol.is_valid_id_list(ids, 3) is True
    assert rpc_protocol.is_valid_id_list(ids, 2) is False
    for invalida in ([], (10**15,), "x", None, [10**15, "x"], {10**15: 1}):
        assert rpc_protocol.is_valid_id_list(invalida) is False, invalida


def test_normalize_origin_e_parse_allowed_origins():
    assert rpc_protocol.normalize_origin("  HTTPS://Ex.Invalid/ ") == "https://ex.invalid"
    assert rpc_protocol.parse_allowed_origins(" A.invalid/ , ,B.INVALID,,") == frozenset({"a.invalid", "b.invalid"})
    assert rpc_protocol.parse_allowed_origins("") == frozenset()
    assert rpc_protocol.parse_allowed_origins(None) == frozenset()


def test_pick_fields_so_devolve_os_permitidos_presentes():
    assert rpc_protocol.pick_fields({"a": 1, "b": 2, "c": 3}, ("a", "c", "z")) == {"a": 1, "c": 3}


def test_same_token_trata_ausente_como_vazio_e_compara_exatamente():
    assert rpc_protocol.same_token("", "") is True
    assert rpc_protocol.same_token(None, "") is True
    assert rpc_protocol.same_token("abc", "abc") is True
    assert rpc_protocol.same_token("abc", "abd") is False
    assert rpc_protocol.same_token("abc", None) is False


def test_parse_app_version_ausente_ou_invalida_vale_zero():
    zero = rpc_protocol.parse_app_version("0")
    assert str(rpc_protocol.parse_app_version("3.0.0")) == "3.0.0"
    for invalida in (None, 3, ["3.0.0"], "abc", "9" * 33, ""):
        assert rpc_protocol.parse_app_version(invalida) == zero, invalida
    assert str(rpc_protocol.parse_app_version("9" * 32)) == "9" * 32


def test_rate_limiter_janela_deslizante(monkeypatch):
    agora = {"t": 1000.0}
    monkeypatch.setattr(rpc_protocol.time, "monotonic", lambda: agora["t"])
    limitador = rpc_protocol.RateLimiter(limit=3, window=10.0)

    assert [limitador.allow() for _ in range(4)] == [True, True, True, False]
    agora["t"] += 9.99
    assert limitador.allow() is False
    agora["t"] += 0.01  # exatamente 10 s depois das primeiras mensagens
    assert limitador.allow() is True

"""F3-2 — testes RED de config, pool e itens correlatos (KI-06, KI-07, KI-08, KI-10, KI-11, KI-12, KI-13, KI-31, caches).

Sem rede, sem Discord, sem Java e sem o .env real (o conftest já neutraliza o ``dotenv_values`` real). Tudo roda em ``tmp_path``
com ``EMPIREMUSE_HOME`` isolado e cwd diferente dele. Testes marcados como GUARDA descrevem comportamento que já funciona hoje e
não pode regredir; os demais falham hoje pelo motivo descrito no nome/mensagem.

Decisões (MAESTRO): KI-06 booleanos aceitam qualquer caixa, inválido continua dando erro citando a chave; KI-07 retries 1..4
são respeitados, 0 = sem limite, negativo = erro claro; KI-08 falha ao ler o .env vira logger.warning (tipo do erro e caminho,
sem conteúdo) e o bot segue; KI-10 falha de gravação levanta e não toca o cache; KI-11 guild novo é acrescentado ao dict;
KI-12 reset_useragent devolve o user-agent; KI-13 com KILL_ON_429=false propaga o erro original; KI-31 sem utcnow() e com
datetimes cientes de fuso; caches relativos (.ytdl_cache, .lastfm_cache, GIT_DIR) ficam sob paths.RUNTIME_DIR.
"""

import ast
import asyncio
import datetime
import json
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse import config_loader
from empiremuse.cogs.music import Music
from empiremuse.utils import client
from empiremuse.utils.client import BotPool
from empiremuse.utils.db import DBModel, LocalDatabase
from tests.support.api_publica import arvore_da_familia
from tests.support.laco_do_pool import encerrar_laco
from tests.support.raiz import RAIZ

pytestmark = pytest.mark.regression

ROOT = RAIZ
PACOTE = ROOT / "empiremuse"
TOKEN_FALSO = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAx.GabcDE.abcdefghijklmnopqrstuvwxyz1"  # só o formato; não é um token real


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    """Garante "sem rede": qualquer tentativa de abrir conexão (download de jar/JDK, API, DNS) quebra o teste na hora."""

    def proibido(*args, **kwargs):
        raise AssertionError("tentativa de acesso à rede num teste que não pode usar rede")

    monkeypatch.setattr(socket.socket, "connect", proibido)
    monkeypatch.setattr(socket, "create_connection", proibido)
    monkeypatch.setattr(socket, "getaddrinfo", proibido)


@pytest.fixture
def runtime(monkeypatch, tmp_path) -> Path:
    """RUNTIME_DIR isolado (EMPIREMUSE_HOME) e cwd em outra pasta, para pegar qualquer caminho relativo."""
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(home))
    monkeypatch.chdir(cwd)
    return home


def carregar(monkeypatch, **ambiente) -> dict:
    for chave, valor in ambiente.items():
        monkeypatch.setenv(chave, valor)
    return config_loader.load_config()


# ============================================================================ KI-06 — booleanos em qualquer caixa


class TestKI06Booleanos:
    def test_false_em_maiusculas_desliga_uma_flag_que_vem_ligada_por_padrao(self, runtime, monkeypatch):
        assert config_loader.DEFAULT_CONFIG["AUTO_SYNC_COMMANDS"] is True
        assert carregar(monkeypatch, AUTO_SYNC_COMMANDS="FALSE")["AUTO_SYNC_COMMANDS"] is False

    def test_vazio_continua_usando_o_padrao(self, runtime, monkeypatch):
        """GUARDA."""
        assert carregar(monkeypatch, ENABLE_LOGGER="")["ENABLE_LOGGER"] is config_loader.DEFAULT_CONFIG["ENABLE_LOGGER"]


# ============================================================================ KI-07 — LAVALINK_RECONNECT_RETRIES


class TestKI07TentativasDeReconexao:
    @pytest.mark.parametrize("texto", ["-1", "-30"])
    def test_negativo_e_erro_claro_citando_a_chave(self, runtime, monkeypatch, texto):
        with pytest.raises(Exception, match="LAVALINK_RECONNECT_RETRIES"):
            carregar(monkeypatch, LAVALINK_RECONNECT_RETRIES=texto)


# ============================================================================ KI-08 — falha ao ler o .env não é silenciosa


class TestKI08FalhaAoLerODotenv:
    def test_o_bot_segue_com_o_ambiente_apos_a_falha(self, runtime, monkeypatch):
        def quebrar(*args, **kwargs):
            raise OSError("disco com defeito")

        monkeypatch.setattr(config_loader, "dotenv_values", quebrar)
        monkeypatch.setenv("DEFAULT_PREFIX", "??")

        assert config_loader.load_config()["DEFAULT_PREFIX"] == "??"

    def test_nao_ha_except_nu_no_config_loader(self):
        """O ``except:`` nu também engole KeyboardInterrupt/SystemExit; a regra do projeto proíbe."""
        arvore = ast.parse((PACOTE / "config_loader.py").read_text(encoding="utf-8"))
        nus = [n.lineno for n in ast.walk(arvore) if isinstance(n, ast.ExceptHandler) and n.type is None]
        assert not nus, f"except: nu em config_loader.py nas linhas {nus}"


# ============================================================================ KI-10 — LocalDatabase.update_data


class TestKI10UpdateDataComFalhaDeGravacao:
    @pytest.fixture
    def banco(self, tmp_path):
        return LocalDatabase(dir_=str(tmp_path / "banco"))

    @pytest.mark.asyncio
    async def test_falha_do_insert_one_levanta_e_nao_atualiza_o_cache(self, banco, monkeypatch):
        from tinymongo import TinyMongoCollection

        monkeypatch.setattr(TinyMongoCollection, "update_one", lambda self, *a, **k: SimpleNamespace(raw_result=False))

        def quebrar(self, *args, **kwargs):
            raise OSError("sem permissão (simulado)")

        monkeypatch.setattr(TinyMongoCollection, "insert_one", quebrar)

        with pytest.raises(OSError, match="sem permissão"):
            await banco.update_data("2", {"ver": 1.0}, db_name=DBModel.guilds, collection="c")

        assert "c:guilds:2" not in banco.cache

    @pytest.mark.asyncio
    async def test_a_falha_nao_substitui_o_dado_que_ja_estava_no_cache(self, banco, monkeypatch):
        from tinymongo import TinyMongoCollection

        await banco.update_data("3", {"ver": 1.0, "valor": "antigo"}, db_name=DBModel.guilds, collection="c")

        def quebrar(self, *args, **kwargs):
            raise OSError("x")

        monkeypatch.setattr(TinyMongoCollection, "update_one", quebrar)

        with pytest.raises(OSError):
            await banco.update_data("3", {"ver": 1.0, "valor": "novo"}, db_name=DBModel.guilds, collection="c")

        assert banco.cache["c:guilds:3"]["valor"] == "antigo"


# ============================================================================ KI-12 — user-agent


class TestKI12UserAgent:
    def test_reset_useragent_devolve_o_novo_user_agent(self, runtime, monkeypatch):
        valores = iter(["UA-init", "UA-um"])
        monkeypatch.setattr(client, "generate_user_agent", lambda: next(valores))
        pool = BotPool()

        devolvido = pool.reset_useragent()

        assert devolvido is not None, "KI-12: reset_useragent não devolve nada"
        assert devolvido == pool.current_useragent == "UA-um"


# ============================================================================ KI-13 — rate limit com KILL_ON_429=false


def _erro_http(status: int, texto: str = "") -> disnake.HTTPException:
    return disnake.HTTPException(SimpleNamespace(status=status, reason="Too Many Requests"), texto)


class TestKI13RateLimitSemMatarOProcesso:
    @pytest.fixture
    def pool(self, runtime, monkeypatch):
        pool = BotPool()
        pool.config["KILL_ON_429"] = False
        pool.shutdown = AsyncMock()
        monkeypatch.setattr(client.asyncio, "sleep", AsyncMock())  # sem esperar os 10 s de verdade
        return pool

    @staticmethod
    def _bot(erro: BaseException):
        return SimpleNamespace(http=SimpleNamespace(token="t"), start=AsyncMock(side_effect=erro), identifier="bot1")

    @pytest.mark.asyncio
    async def test_status_429_propaga_o_erro_original_e_nao_typeerror(self, pool):
        erro = _erro_http(429, "rate limited")

        with pytest.raises(disnake.HTTPException) as capturado:
            await pool.start_bot(self._bot(erro))

        assert capturado.value is erro, "KI-13: o erro original deveria ser propagado"

    @pytest.mark.asyncio
    async def test_segunda_chamada_durante_o_ratelimit_retorna_sem_erro(self, pool):
        """GUARDA: o segundo bot a tomar 429 não repete a espera nem levanta."""
        pool.killing_state = "ratelimit"

        assert await pool.start_bot(self._bot(_erro_http(429))) is None

    @pytest.mark.asyncio
    async def test_com_kill_on_429_o_processo_e_encerrado_ordenadamente(self, pool):
        """GUARDA."""
        pool.config["KILL_ON_429"] = True

        await pool.start_bot(self._bot(_erro_http(429)))

        pool.shutdown.assert_awaited_once_with(1)


# ============================================================================ KI-11 — guild_bots


@pytest.fixture
def pool_com_bots_falsos(runtime, monkeypatch):
    """Roda o BotPool.setup REAL com BotCore dublado e o loop principal neutralizado; o guild_bots.json fica no RUNTIME_DIR."""
    monkeypatch.setenv("RUN_LOCAL_LAVALINK", "false")  # sem Java: o setup não pode subir o Lavalink local
    monkeypatch.setenv("RUN_RPC_SERVER", "false")  # o padrão (True) sobe um servidor tornado na porta do painel
    monkeypatch.setenv("TOKEN", TOKEN_FALSO)  # o setup só reconhece valores com FORMATO de token do Discord
    pool = BotPool()

    def bot_falso(**kwargs):
        bot = MagicMock(identifier=kwargs["identifier"])
        bot.loop.create_task.side_effect = lambda corotina: corotina.close()  # sem "coroutine never awaited"
        return bot

    monkeypatch.setattr(client, "BotCore", bot_falso)
    for nome in ("run_bots", "setup_pool_extras", "cache_updater", "connect_rpc_ws"):
        setattr(pool, nome, AsyncMock())
    pool.node_check = MagicMock()
    pool.start_lavalink = AsyncMock()  # nada de subir Java nem baixar jar/JDK
    yield pool
    encerrar_laco(pool.loop)  # cancela o que o setup deixou (tarefas dubladas e a da versão nova) e fecha o laço
    asyncio.set_event_loop(None)


class TestKI11GuildBots:
    def test_get_guild_bots_enxerga_os_bots_exclusivos_de_cada_servidor(self, pool_com_bots_falsos, runtime):
        (runtime / "guild_bots.json").write_text(json.dumps({"111": ["tokA"], "222": ["tokB"]}))

        pool_com_bots_falsos.setup()

        def ids(guild):
            return [b.identifier for b in pool_com_bots_falsos.get_guild_bots(guild)]

        assert "111_0" in ids(111) and "222_0" in ids(222)
        assert "222_0" not in ids(111)


# ============================================================================ KI-31 — sem utcnow(), datetimes cientes de fuso


def _chamadas_utcnow_naive() -> list[str]:
    achados = []
    for arquivo in sorted(PACOTE.rglob("*.py")):
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == "utcnow":
                dono = ast.unparse(no.func.value)
                if dono in (
                    "datetime",
                    "datetime.datetime",
                    "dt",
                    "dt.datetime",
                ):  # disnake.utils.utcnow() é ciente de fuso
                    achados.append(f"{arquivo.relative_to(ROOT)}:{no.lineno}")
    return achados


class TestKI31DatetimesCientesDeFuso:
    def test_nenhum_datetime_utcnow_naive_no_pacote(self):
        achados = _chamadas_utcnow_naive()
        assert not achados, f"datetime.utcnow() (obsoleto e naive) em: {achados}"

    @pytest.mark.asyncio
    async def test_node_reconnect_conta_falhas_consecutivas_com_datetimes_cientes(self):
        no = SimpleNamespace(
            _retry_dt=datetime.datetime.now(datetime.timezone.utc),
            _retry_count=0,
            is_available=True,
            identifier="node1",
            version=4,
            players={},
        )
        cog = SimpleNamespace(bot=SimpleNamespace(user="bot#0000"))

        await Music.node_reconnect(cog, no)

        assert no._retry_count == 1, "duas quedas em menos de 7 s devem contar como consecutivas"

    def test_o_node_nasce_com_retry_dt_ciente_de_fuso(self):
        arvore = ast.parse((PACOTE / "wavelink" / "node.py").read_text(encoding="utf-8"))
        atribuicoes = [
            n
            for n in ast.walk(arvore)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Attribute) and t.attr == "_retry_dt" for t in n.targets)
        ]
        assert atribuicoes, "Node não inicializa _retry_dt"
        for atribuicao in atribuicoes:
            texto = ast.unparse(atribuicao.value)
            assert "UTC" in texto or "timezone.utc" in texto, f"_retry_dt precisa ser ciente de fuso (UTC): {texto}"


# ============================================================================ caches relativos -> paths.RUNTIME_DIR


class TestCachesSobOutroDiretorio:
    def test_cachedir_do_ytdl_aponta_para_o_runtime_dir(self):
        arvore = arvore_da_familia("music")
        valores = [
            ast.unparse(valor)
            for no in ast.walk(arvore)
            if isinstance(no, ast.Dict)
            for chave, valor in zip(no.keys, no.values)
            if isinstance(chave, ast.Constant)
            and chave.value == "cachedir"
            and not (isinstance(valor, ast.Constant) and valor.value is False)  # False = cache desligado, não é caminho
        ]
        assert valores, "nenhum 'cachedir' com caminho encontrado: o cache do yt-dlp mudou? ajuste este teste"
        assert all("RUNTIME_DIR" in valor for valor in valores), valores

    def test_nenhum_literal_de_caminho_oculto_relativo_no_pacote(self):
        """Qualquer ``"./.algo"`` (cache, git, estado) depende do cwd. A única exceção é o padrão sentinela do GIT_DIR, que o
        ``load_config`` troca por RUNTIME_DIR/.git."""
        permitido = ("empiremuse/config_loader.py", "./.git")
        achados = []
        for arquivo in sorted(PACOTE.rglob("*.py")):
            for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
                if isinstance(no, ast.Constant) and isinstance(no.value, str) and no.value.startswith("./."):
                    if (arquivo.relative_to(ROOT).as_posix(), no.value) != permitido:
                        achados.append(f"{arquivo.relative_to(ROOT)}:{no.lineno} {no.value!r}")
        assert not achados, f"caminhos ocultos relativos ao cwd: {achados}"

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
import logging
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse import config_loader, paths
from empiremuse.cogs.music import Music
from empiremuse.utils import client
from empiremuse.utils.client import BotPool
from empiremuse.utils.db import DBModel, LocalDatabase
from empiremuse.utils.music import lastfm_tools

ROOT = Path(__file__).resolve().parent.parent
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
    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [("True", True), ("TRUE", True), ("tRuE", True), ("False", False), ("FALSE", False), ("fAlSe", False)],
    )
    def test_booleano_do_ambiente_aceita_qualquer_caixa(self, runtime, monkeypatch, texto, esperado):
        assert carregar(monkeypatch, ENABLE_LOGGER=texto)["ENABLE_LOGGER"] is esperado

    def test_false_em_maiusculas_desliga_uma_flag_que_vem_ligada_por_padrao(self, runtime, monkeypatch):
        assert config_loader.DEFAULT_CONFIG["AUTO_SYNC_COMMANDS"] is True
        assert carregar(monkeypatch, AUTO_SYNC_COMMANDS="FALSE")["AUTO_SYNC_COMMANDS"] is False

    def test_booleano_vindo_do_dotenv_tambem_aceita_qualquer_caixa(self, runtime, monkeypatch):
        monkeypatch.setattr(config_loader, "dotenv_values", lambda *a, **k: {"ENABLE_LOGGER": "True"})
        assert config_loader.load_config()["ENABLE_LOGGER"] is True

    @pytest.mark.parametrize("texto", ["talvez", "sim", "1", "verdadeiro"])
    def test_valor_invalido_continua_dando_erro_claro_citando_a_chave(self, runtime, monkeypatch, texto):
        """GUARDA: o erro claro por valor inválido já existe e não pode ser perdido."""
        with pytest.raises(Exception, match="ENABLE_LOGGER"):
            carregar(monkeypatch, ENABLE_LOGGER=texto)

    @pytest.mark.parametrize(("texto", "esperado"), [("true", True), ("false", False)])
    def test_minusculas_continuam_funcionando(self, runtime, monkeypatch, texto, esperado):
        """GUARDA."""
        assert carregar(monkeypatch, ENABLE_LOGGER=texto)["ENABLE_LOGGER"] is esperado

    def test_vazio_continua_usando_o_padrao(self, runtime, monkeypatch):
        """GUARDA."""
        assert carregar(monkeypatch, ENABLE_LOGGER="")["ENABLE_LOGGER"] is config_loader.DEFAULT_CONFIG["ENABLE_LOGGER"]


# ============================================================================ KI-07 — LAVALINK_RECONNECT_RETRIES


class TestKI07TentativasDeReconexao:
    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 30])
    def test_valor_configurado_e_respeitado(self, runtime, monkeypatch, n):
        assert carregar(monkeypatch, LAVALINK_RECONNECT_RETRIES=str(n))["LAVALINK_RECONNECT_RETRIES"] == n

    def test_zero_continua_significando_sem_limite(self, runtime, monkeypatch):
        """GUARDA."""
        assert carregar(monkeypatch, LAVALINK_RECONNECT_RETRIES="0")["LAVALINK_RECONNECT_RETRIES"] == 0

    @pytest.mark.parametrize("texto", ["-1", "-30"])
    def test_negativo_e_erro_claro_citando_a_chave(self, runtime, monkeypatch, texto):
        with pytest.raises(Exception, match="LAVALINK_RECONNECT_RETRIES"):
            carregar(monkeypatch, LAVALINK_RECONNECT_RETRIES=texto)

    def test_texto_nao_numerico_continua_dando_erro_claro(self, runtime, monkeypatch):
        """GUARDA."""
        with pytest.raises(Exception, match="LAVALINK_RECONNECT_RETRIES"):
            carregar(monkeypatch, LAVALINK_RECONNECT_RETRIES="muitas")

    def test_o_padrao_do_projeto_nao_muda(self, runtime, monkeypatch):
        """GUARDA."""
        monkeypatch.delenv("LAVALINK_RECONNECT_RETRIES", raising=False)
        assert config_loader.load_config()["LAVALINK_RECONNECT_RETRIES"] == 30


# ============================================================================ KI-08 — falha ao ler o .env não é silenciosa


class TestKI08FalhaAoLerODotenv:
    def test_falha_vira_warning_com_tipo_e_caminho_sem_conteudo(self, runtime, monkeypatch, caplog):
        def quebrar(*args, **kwargs):
            raise PermissionError("conteudo-secreto-do-env TOKEN=abc.def.ghi")

        monkeypatch.setattr(config_loader, "dotenv_values", quebrar)

        with caplog.at_level(logging.WARNING, logger="empiremuse.config_loader"):
            config_loader.load_config()

        avisos = [r for r in caplog.records if r.levelno == logging.WARNING and r.name == "empiremuse.config_loader"]
        assert avisos, "KI-08: a falha ao ler o .env foi engolida em silêncio"
        texto = " ".join(r.getMessage() for r in avisos)
        assert "PermissionError" in texto, "o warning precisa citar o TIPO do erro"
        assert str(paths.RUNTIME_DIR / ".env") in texto, "o warning precisa citar o caminho do .env"
        assert "conteudo-secreto-do-env" not in caplog.text and "abc.def.ghi" not in caplog.text

    def test_o_bot_segue_com_o_ambiente_apos_a_falha(self, runtime, monkeypatch):
        def quebrar(*args, **kwargs):
            raise OSError("disco com defeito")

        monkeypatch.setattr(config_loader, "dotenv_values", quebrar)
        monkeypatch.setenv("DEFAULT_PREFIX", "??")

        assert config_loader.load_config()["DEFAULT_PREFIX"] == "??"

    def test_dotenv_ausente_nao_gera_warning(self, runtime, caplog):
        """GUARDA: sem .env o dotenv_values devolve {} e isso é normal (ambiente de container/painel)."""
        with caplog.at_level(logging.WARNING, logger="empiremuse.config_loader"):
            config_loader.load_config()

        assert not [r for r in caplog.records if r.name == "empiremuse.config_loader"]

    def test_dotenv_valido_continua_sendo_aplicado(self, runtime, monkeypatch):
        """GUARDA."""
        monkeypatch.setattr(config_loader, "dotenv_values", lambda *a, **k: {"DEFAULT_PREFIX": "##"})
        assert config_loader.load_config()["DEFAULT_PREFIX"] == "##"

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
    async def test_falha_do_update_one_levanta_e_nao_atualiza_o_cache(self, banco, monkeypatch):
        from tinymongo import TinyMongoCollection

        def quebrar(self, *args, **kwargs):
            raise OSError("disco cheio (simulado)")

        monkeypatch.setattr(TinyMongoCollection, "update_one", quebrar)

        with pytest.raises(OSError, match="disco cheio"):
            await banco.update_data("1", {"ver": 1.0, "x": 1}, db_name=DBModel.guilds, collection="c")

        assert "c:guilds:1" not in banco.cache, "KI-10: o cache foi atualizado como se a gravação tivesse dado certo"

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

    @pytest.mark.asyncio
    async def test_gravacao_bem_sucedida_atualiza_banco_e_cache(self, banco):
        """GUARDA: documento que já existe no banco é atualizado no disco e no cache."""
        banco._connect["c"][DBModel.guilds].insert_one({"_id": "4", "ver": 1.0, "valor": "antes"})

        await banco.update_data("4", {"ver": 1.0, "valor": "ok"}, db_name=DBModel.guilds, collection="c")

        assert banco.cache["c:guilds:4"]["valor"] == "ok"
        assert LocalDatabase(dir_=banco.dir)._connect["c"][DBModel.guilds].find_one({"_id": "4"})["valor"] == "ok"

    @pytest.mark.asyncio
    async def test_achado_extra_update_data_de_documento_novo_persiste_no_disco(self, banco):
        """ACHADO EXTRA (fora do backlog): update_one num _id inexistente devolve raw_result={'n': 0, 'updatedExisting': False}
        (truthy), então o insert_one NUNCA roda e o documento novo só existe no cache — o mesmo sintoma do KI-10 ("o dado some
        após o cache expirar"). O MongoDatabase usa upsert=True; o LocalDatabase deve ter a mesma semântica."""
        await banco.update_data("5", {"ver": 1.0, "valor": "novo"}, db_name=DBModel.guilds, collection="c")

        gravado = LocalDatabase(dir_=banco.dir)._connect["c"][DBModel.guilds].find_one({"_id": "5"})
        assert gravado is not None and gravado["valor"] == "novo", "o documento novo não foi gravado no disco"


# ============================================================================ KI-12 — user-agent


class TestKI12UserAgent:
    def test_reset_useragent_devolve_o_novo_user_agent(self, runtime, monkeypatch):
        valores = iter(["UA-init", "UA-um"])
        monkeypatch.setattr(client, "generate_user_agent", lambda: next(valores))
        pool = BotPool()

        devolvido = pool.reset_useragent()

        assert devolvido is not None, "KI-12: reset_useragent não devolve nada"
        assert devolvido == pool.current_useragent == "UA-um"

    def test_current_useragent_nao_fica_none_apos_o_init(self, runtime):
        pool = BotPool()

        assert isinstance(pool.current_useragent, str) and pool.current_useragent.strip()

    def test_cada_reset_troca_o_user_agent_guardado(self, runtime, monkeypatch):
        valores = iter(["UA-init", "UA-1", "UA-2"])
        monkeypatch.setattr(client, "generate_user_agent", lambda: next(valores))
        pool = BotPool()

        assert pool.reset_useragent() == "UA-1" and pool.current_useragent == "UA-1"
        assert pool.reset_useragent() == "UA-2" and pool.current_useragent == "UA-2"


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
    async def test_429_reconhecido_pelo_texto_da_mensagem_tambem_propaga(self, pool):
        """A condição usava str(e) (e=None) em vez do erro recebido; o texto '429 Too Many Requests' precisa valer."""
        erro = _erro_http(503, "429 Too Many Requests")

        with pytest.raises(disnake.HTTPException) as capturado:
            await pool.start_bot(self._bot(erro))

        assert capturado.value is erro

    @pytest.mark.asyncio
    async def test_sem_kill_o_processo_nao_e_encerrado(self, pool):
        with pytest.raises(disnake.HTTPException):
            await pool.start_bot(self._bot(_erro_http(429)))

        pool.shutdown.assert_not_awaited()

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
    """Roda o BotPool.setup REAL com BotCore dublado e o loop principal neutralizado; o guild_bots.json fica no cwd."""
    # bots/guild_bots são atributos de CLASSE (compartilhados entre instâncias): isola cada teste e restaura no fim
    monkeypatch.setattr(BotPool, "bots", [])
    monkeypatch.setattr(BotPool, "guild_bots", {})
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
    if pool.loop is not None and not pool.loop.is_closed():
        pool.loop.run_until_complete(asyncio.sleep(0))  # deixa as tasks dubladas terminarem
        pool.loop.close()
    asyncio.set_event_loop(None)


class TestKI11GuildBots:
    def test_varios_servidores_do_guild_bots_json_ficam_todos_registrados(self, pool_com_bots_falsos):
        Path("guild_bots.json").write_text(json.dumps({"111": ["tokA"], "222": ["tokB"], "333": ["tokC"]}))

        pool_com_bots_falsos.setup()

        assert set(pool_com_bots_falsos.guild_bots) == {"111", "222", "333"}, (
            "KI-11: cada novo servidor substituiu o dicionário inteiro"
        )
        assert all(len(bots) == 1 for bots in pool_com_bots_falsos.guild_bots.values())

    def test_varios_tokens_do_mesmo_servidor_acumulam(self, pool_com_bots_falsos):
        Path("guild_bots.json").write_text(json.dumps({"111": ["tokA", "tokB"], "222": ["tokC"]}))

        pool_com_bots_falsos.setup()

        assert [b.identifier for b in pool_com_bots_falsos.guild_bots["111"]] == ["111_0", "111_1"]
        assert [b.identifier for b in pool_com_bots_falsos.guild_bots["222"]] == ["222_0"]

    def test_get_guild_bots_enxerga_os_bots_exclusivos_de_cada_servidor(self, pool_com_bots_falsos):
        Path("guild_bots.json").write_text(json.dumps({"111": ["tokA"], "222": ["tokB"]}))

        pool_com_bots_falsos.setup()

        def ids(guild):
            return [b.identifier for b in pool_com_bots_falsos.get_guild_bots(guild)]

        assert "111_0" in ids(111) and "222_0" in ids(222)
        assert "222_0" not in ids(111)

    def test_o_dicionario_nao_e_substituido_pela_atribuicao_no_setup(self):
        """Estrutura: nada em BotPool.setup pode fazer ``self.guild_bots = ...`` (a causa do KI-11)."""
        arvore = ast.parse((PACOTE / "utils" / "client.py").read_text(encoding="utf-8"))
        pool_cls = next(n for n in ast.walk(arvore) if isinstance(n, ast.ClassDef) and n.name == "BotPool")
        setup = next(n for n in pool_cls.body if isinstance(n, ast.FunctionDef) and n.name == "setup")
        reatribuicoes = [
            n.lineno
            for n in ast.walk(setup)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Attribute) and t.attr == "guild_bots" for t in n.targets)
        ]
        assert not reatribuicoes, f"BotPool.setup reatribui self.guild_bots nas linhas {reatribuicoes}"

    def test_achado_extra_bots_e_guild_bots_nao_sao_compartilhados_entre_instancias(self, runtime):
        """ACHADO EXTRA (fora do backlog): ``bots`` e ``guild_bots`` são atributos de CLASSE mutáveis; ``self.bots.append`` e o
        futuro ``self.guild_bots.setdefault(...)`` alteram o estado de TODOS os BotPool. Cada instância deve ter os seus."""
        a, b = BotPool(), BotPool()

        assert a.guild_bots is not b.guild_bots, "guild_bots é um dict de classe compartilhado"
        assert a.bots is not b.bots, "bots é uma lista de classe compartilhada"

    def test_sem_guild_bots_json_so_o_bot_principal_e_carregado(self, pool_com_bots_falsos):
        """GUARDA."""
        pool_com_bots_falsos.setup()

        assert not pool_com_bots_falsos.guild_bots
        assert len(pool_com_bots_falsos.bots) == 1


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
    async def test_node_reconnect_aceita_o_retry_dt_ciente_de_fuso(self):
        """O Node passa a guardar um datetime ciente (UTC); a comparação do node_reconnect não pode estourar TypeError."""
        agora = datetime.datetime.now(datetime.timezone.utc)
        no = SimpleNamespace(
            _retry_dt=agora - datetime.timedelta(seconds=60),
            _retry_count=0,
            is_available=True,
            identifier="node1",
            version=4,
            players={},
        )
        cog = SimpleNamespace(bot=SimpleNamespace(user="bot#0000"))

        await Music.node_reconnect(cog, no)

        assert no._retry_count == 0, "uma falha há 60 s não conta como falha consecutiva"
        assert no._retry_dt.tzinfo is not None, "o _retry_dt atualizado precisa continuar ciente de fuso"
        assert no._retry_dt > agora - datetime.timedelta(seconds=1)

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

    def test_datetimes_salvos_pelo_banco_local_voltam_sem_fuso(self, tmp_path):
        """GUARDA de caracterização: o TinyMongo grava '%Y-%m-%dT%H:%M:%S' (sem fuso). Quem compara com um valor lido do banco
        precisa normalizar (naive x aware dá TypeError) — por isso o utcnow() não pode ser trocado às cegas nesses pontos."""
        banco = LocalDatabase(dir_=str(tmp_path / "banco"))
        momento = datetime.datetime(2026, 1, 2, 3, 4, 5)
        banco._connect["c"]["guilds"].insert_one({"_id": "1", "quando": momento})

        lido = banco._connect["c"]["guilds"].find_one({"_id": "1"})["quando"]

        assert lido == momento and lido.tzinfo is None


# ============================================================================ caches relativos -> paths.RUNTIME_DIR


class TestCachesSobOutroDiretorio:
    def test_cachedir_do_ytdl_nao_e_caminho_relativo(self):
        arvore = ast.parse((PACOTE / "cogs" / "music.py").read_text(encoding="utf-8"))
        relativos = []
        for no in ast.walk(arvore):
            if isinstance(no, ast.Dict):
                for chave, valor in zip(no.keys, no.values):
                    if isinstance(chave, ast.Constant) and chave.value == "cachedir":
                        if (
                            isinstance(valor, ast.Constant)
                            and isinstance(valor.value, str)
                            and not Path(valor.value).is_absolute()
                        ):
                            relativos.append(f"linha {valor.lineno}: {valor.value!r}")
        assert not relativos, f"'cachedir' do yt-dlp relativo ao cwd: {relativos} (use paths.RUNTIME_DIR)"

    def test_cachedir_do_ytdl_aponta_para_o_runtime_dir(self):
        arvore = ast.parse((PACOTE / "cogs" / "music.py").read_text(encoding="utf-8"))
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

    def test_cache_do_lastfm_grava_sob_o_runtime_dir_e_nunca_no_cwd(self, runtime):
        """GUARDA: as funções do LastFM já usam RUNTIME_DIR."""
        lastfm = lastfm_tools.LastFM("chave", "segredo")
        lastfm.cache["k"] = "v"

        lastfm.scrobble_save_cache()

        assert (runtime / ".lastfm_cache").is_file()
        assert not (Path.cwd() / ".lastfm_cache").exists()

    def test_constante_legada_do_lastfm_nao_e_um_caminho_relativo(self):
        legado = getattr(lastfm_tools, "cache_file", None)
        assert legado is None or Path(str(legado)).is_absolute(), (
            f"lastfm_tools.cache_file = {legado!r} é relativo ao cwd; remova-o ou use paths.RUNTIME_DIR"
        )

    def test_git_dir_padrao_fica_sob_o_runtime_dir(self, runtime, monkeypatch):
        monkeypatch.delenv("GIT_DIR", raising=False)

        assert config_loader.load_config()["GIT_DIR"] == str(runtime / ".git")

    def test_git_dir_configurado_pelo_usuario_e_respeitado(self, runtime, monkeypatch):
        """GUARDA."""
        assert carregar(monkeypatch, GIT_DIR="/opt/meu/repo/.git")["GIT_DIR"] == "/opt/meu/repo/.git"

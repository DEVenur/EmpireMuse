"""D-08 (bloco D2) — testes RED do Lavalink pré-instalado no container.

Sem rede, sem Java real e sem Discord: ``subprocess.Popen``, os downloads e o processo Java são dublês e tudo roda em
``tmp_path``. Interface decidida pelo MAESTRO, com os nomes que estes testes fixam para o Backend:

  config_loader.DEFAULT_CONFIG   LAVALINK_JAVA_PATH (str, ""), LAVALINK_HOME (str, "" = RUNTIME_DIR),
                                 LAVALINK_OFFLINE (bool, False; convertido como os demais booleanos).
  local_lavalink.run_lavalink    parâmetros nomeados novos: ``lavalink_java_path``, ``lavalink_home``, ``lavalink_offline``.
                                 Com o Java configurado não há download/instalação de JDK; o Popen roda em ``lavalink_home``
                                 (vazio = RUNTIME_DIR) e recebe o caminho do Java como UM argumento (mesmo com espaços).
  local_lavalink.prepare_lavalink_files(directory, *, ..., lavalink_offline=False)
                                 offline: zero download; confere o SHA-256 do jar, do yml e dos plugins (branding.py).
                                 Divergente => IntegrityError; ausente => LavalinkDownloadError citando o arquivo.
  local_lavalink.lavalink_child_env   sempre devolve SERVER_ADDRESS=127.0.0.1, seja qual for o ambiente do bot.
  local_lavalink.watch_lavalink_process(process, on_exit)
                                 função síncrona feita para rodar numa thread: detecta a saída do processo (poll/wait) e
                                 chama ``on_exit(returncode)`` uma única vez. Não decide sobre "esperado/inesperado":
                                 isso é do callback do pool.
  BotPool.start_lavalink         repassa as 3 chaves novas ao run_lavalink e passa a vigiar o processo; a queda do Java
                                 chama ``shutdown(1)`` (a menos que o encerramento já esteja em curso, ou que o processo
                                 vigiado seja o antigo, morto por um reinício).
"""

import asyncio
import hashlib
import subprocess
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from empiremuse import config_loader, paths
from empiremuse.utils import branding
from empiremuse.utils.music import local_lavalink as ll

NOVAS_CHAVES = ("LAVALINK_JAVA_PATH", "LAVALINK_HOME", "LAVALINK_OFFLINE")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ============================================================================ infraestrutura


def instalar_binarios(directory: Path, monkeypatch) -> dict:
    """Cria jar, yml e plugins fictícios em ``directory`` e aponta o branding para os hashes deles."""
    directory.mkdir(parents=True, exist_ok=True)
    arquivos = {"Lavalink.jar": b"JAR-D08", "application.yml": b"YML-D08\n"}
    nomes_plugins = list(branding.LAVALINK_PLUGIN_SHA256)
    arquivos.update({f"plugins/{nome}": f"plugin {nome}".encode() for nome in nomes_plugins})
    monkeypatch.setattr(branding, "LAVALINK_JAR_SHA256", sha(arquivos["Lavalink.jar"]))
    monkeypatch.setattr(branding, "LAVALINK_APPLICATION_YML_SHA256", sha(arquivos["application.yml"]))
    monkeypatch.setattr(branding, "LAVALINK_PLUGIN_SHA256", {n: sha(arquivos[f"plugins/{n}"]) for n in nomes_plugins})
    (directory / "plugins").mkdir(exist_ok=True)
    for relativo, dados in arquivos.items():
        (directory / relativo).write_bytes(dados)
    return arquivos


def criar_java(base: Path, pasta="jdk", modo=0o755) -> Path:
    bin_dir = base / pasta / "bin"
    bin_dir.mkdir(parents=True)
    java = bin_dir / "java"
    java.write_text("#!/bin/sh\nexit 0\n")
    java.chmod(modo)
    return java


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    """RUNTIME_DIR isolado (EMPIREMUSE_HOME), cwd diferente dele e ambiente sem Java/OAuth/endereço do dono."""
    home = tmp_path / "runtime"
    home.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(home))
    monkeypatch.chdir(cwd)
    for var in ("JAVA_HOME", "SERVER_ADDRESS", "PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(ll.platform, "architecture", lambda *a, **k: ("64bit", "ELF"))
    return home


@pytest.fixture
def popen(monkeypatch):
    registros = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            registros.append((list(args), kwargs))

    monkeypatch.setattr(ll.subprocess, "Popen", FakePopen)
    return registros


@pytest.fixture
def proibidos(monkeypatch):
    """Armadilhas: qualquer download, instalação de JDK, jabba ou extração é registrada e falha na hora."""
    chamadas = []

    def armadilha(nome):
        def _chamada(*args, **kwargs):
            chamadas.append(nome)
            raise AssertionError(f"{nome} não deveria ser chamado")

        return _chamada

    monkeypatch.setattr(ll.requests, "get", armadilha("requests.get"))
    for nome in (
        "download_file",
        "download_verified",
        "_fetch_verified_jdk",
        "_install_jdk_linux",
        "_install_jdk_windows",
    ):
        monkeypatch.setattr(ll, nome, armadilha(nome))
    monkeypatch.setattr(ll.subprocess, "call", armadilha("subprocess.call"))
    monkeypatch.setattr(ll.tarfile, "open", armadilha("tarfile.open"))
    monkeypatch.setattr(ll.zipfile, "ZipFile", armadilha("zipfile.ZipFile"))
    return chamadas


def com_java_do_sistema(monkeypatch):
    monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: cmd)


class FakeJava:
    """Processo Java falso: ``poll``/``wait`` como o Popen; ``die`` simula a morte; kill/terminate matam de verdade."""

    def __init__(self):
        self.returncode = None
        self.pid = 4242
        self.sinais = []
        self._morto = threading.Event()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if not self._morto.wait(timeout):
            raise subprocess.TimeoutExpired("java", timeout)
        return self.returncode

    def die(self, code):
        self.returncode = code
        self._morto.set()

    def terminate(self):
        self.sinais.append("terminate")
        self.die(-15)

    def kill(self):
        self.sinais.append("kill")
        self.die(-9)


# ============================================================================ (1) configuração


class TestConfiguracao:
    @pytest.fixture
    def carregar(self, monkeypatch, tmp_path):
        """load_config() com RUNTIME_DIR vazio (sem config.json) e o .env real já neutralizado pelo conftest."""
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        for chave in NOVAS_CHAVES:
            monkeypatch.delenv(chave, raising=False)
        return config_loader.load_config

    def test_lavalink_offline_invalido_falha_alto_como_os_outros_booleanos(self, carregar, monkeypatch):
        monkeypatch.setenv("LAVALINK_OFFLINE", "talvez")
        with pytest.raises(Exception, match="LAVALINK_OFFLINE"):
            carregar()


# ============================================================================ (2) Java configurado


class TestJavaConfigurado:
    def test_o_java_configurado_vence_o_java_do_sistema(self, runtime, popen, proibidos, monkeypatch):
        instalar_binarios(runtime, monkeypatch)
        java = criar_java(runtime.parent, "java-do-container")
        com_java_do_sistema(monkeypatch)  # existe um "java" no PATH, mas o configurado manda

        ll.run_lavalink(lavalink_java_path=str(java))

        assert popen[0][0][0] == str(java)


# ============================================================================ (3) modo offline


@pytest.fixture
def pasta_pronta(tmp_path, monkeypatch):
    destino = tmp_path / "pre-instalado"
    return destino, instalar_binarios(destino, monkeypatch)


NOMES_PLUGINS = list(branding.LAVALINK_PLUGIN_SHA256)
ARQUIVOS_CONFERIDOS = ["Lavalink.jar", "application.yml", *[f"plugins/{nome}" for nome in NOMES_PLUGINS]]


class TestOffline:
    @pytest.mark.parametrize("relativo", list(ARQUIVOS_CONFERIDOS)[:2])
    def test_hash_divergente_levanta_integrity_error_e_nao_toca_no_arquivo(self, pasta_pronta, proibidos, relativo):
        destino, _ = pasta_pronta
        adulterado = b"CONTEUDO-ADULTERADO"
        (destino / relativo).write_bytes(adulterado)

        with pytest.raises(ll.IntegrityError) as erro:
            ll.prepare_lavalink_files(str(destino), lavalink_offline=True)

        assert Path(relativo).name in str(erro.value)
        assert proibidos == []
        assert (destino / relativo).read_bytes() == adulterado, "imagem pré-instalada pode ser somente leitura"


class TestOfflineNoRunLavalink:
    def test_plugin_adulterado_impede_a_partida(self, runtime, popen, proibidos, monkeypatch):
        instalar_binarios(runtime, monkeypatch)
        (runtime / "plugins" / NOMES_PLUGINS[0]).write_bytes(b"ADULTERADO")
        com_java_do_sistema(monkeypatch)

        with pytest.raises(ll.IntegrityError):
            ll.run_lavalink(lavalink_offline=True)

        assert popen == [] and proibidos == []


# ============================================================================ (4) SERVER_ADDRESS


class TestServerAddress:
    def test_presente_mesmo_quando_o_ambiente_do_bot_nao_define(self):
        assert ll.lavalink_child_env(None, {"PATH": "/bin"})["SERVER_ADDRESS"] == "127.0.0.1"
        assert ll.lavalink_child_env(None, {})["SERVER_ADDRESS"] == "127.0.0.1"


# ============================================================================ (5) encerramento


def pool_para_shutdown(*bots):
    from empiremuse.utils.client import BotPool

    pool = BotPool.__new__(BotPool)
    pool.exit_code = 0
    pool.killing_state = False
    pool.lavalink_instance = FakeJava()
    pool.bots = list(bots)
    pool.guild_bots = {}
    return pool


def bot_falho(identificador="bot_x"):
    bot = AsyncMock()
    bot.identifier = identificador
    bot.is_closed = MagicMock(return_value=False)
    bot.close.side_effect = RuntimeError("falha ao fechar")
    return bot


class TestEncerramento:
    """Caracterização (passa hoje, entregue na D1): o Java morre mesmo quando fechar um bot falha."""

    @pytest.mark.asyncio
    async def test_falha_ao_fechar_um_bot_nao_impede_de_encerrar_o_java(self):
        pool = pool_para_shutdown(bot_falho())

        await pool.shutdown(1)

        assert pool.lavalink_instance.sinais, "terminate ou kill precisa ter sido chamado no processo Java"
        assert pool.lavalink_instance.returncode is not None


# ============================================================================ (6) queda do Java


# ============================================================================ (6) integração com o pool


def config_do_pool(**extras):
    config = {
        "LAVALINK_FILE_URL": "",
        "LAVALINK_FILE_SHA256": "",
        "YOUTUBE_OAUTH_REFRESH_TOKEN": "",
        "LAVALINK_INITIAL_RAM": 30,
        "LAVALINK_RAM_LIMIT": 120,
        "LAVALINK_ADDITIONAL_SLEEP": 0,
        "LAVALINK_CPU_CORES": 2,
        "LAVALINK_JAVA_PATH": "",
        "LAVALINK_HOME": "",
        "LAVALINK_OFFLINE": False,
    }
    config.update(extras)
    return config


@pytest.fixture
def fabrica_de_pool(monkeypatch):
    """Cria BotPool com ``run_lavalink`` dublado (devolve FakeJava) e libera tudo ao final sem disparar shutdown."""
    criados = []

    def criar(*processos, **config_extra):
        from empiremuse.utils import client
        from empiremuse.utils.client import BotPool

        pool = BotPool.__new__(BotPool)
        pool.exit_code = 0
        pool.killing_state = False
        pool.lavalink_instance = None
        pool.bots = []
        pool.guild_bots = {}
        pool.loop = asyncio.get_running_loop()
        pool.config = config_do_pool(**config_extra)
        pool.shutdown = AsyncMock()
        run = MagicMock(side_effect=list(processos))
        monkeypatch.setattr(client, "run_lavalink", run)
        criados.append((pool, processos))
        return pool, run

    yield criar
    for pool, processos in criados:
        pool.killing_state = True  # a queda forçada abaixo não pode acionar nada
        for processo in processos:
            processo.die(0) if processo.returncode is None else None


class TestPoolVigiaOJava:
    @pytest.mark.asyncio
    async def test_start_lavalink_repassa_as_tres_chaves_novas_ao_run_lavalink(self, fabrica_de_pool):
        pool, run = fabrica_de_pool(
            FakeJava(), LAVALINK_JAVA_PATH="/opt/java/bin/java", LAVALINK_HOME="/opt/lavalink", LAVALINK_OFFLINE=True
        )

        await pool.start_lavalink()

        kwargs = run.call_args.kwargs
        assert kwargs["lavalink_java_path"] == "/opt/java/bin/java"
        assert kwargs["lavalink_home"] == "/opt/lavalink"
        assert kwargs["lavalink_offline"] is True


# ============================================================================ (8) guarda dos comandos de owner pela config


@pytest.fixture
def owner_com_pool(runtime, monkeypatch):
    """Cog Owner com pool dublado: ``start_lavalink``/``stop_lavalink`` só registram a chamada (sem Java, sem espera)."""
    from types import SimpleNamespace

    from empiremuse.cogs import legacy_cmds

    assert paths.RUNTIME_DIR.resolve() == runtime.resolve(), "o updatelavalink apaga o jar: só no runtime isolado"
    monkeypatch.setattr(legacy_cmds, "asyncio", SimpleNamespace(sleep=AsyncMock()))

    def criar(*, run_local, instancia):
        pool = MagicMock()
        pool.lavalink_instance = instancia
        pool.start_lavalink = AsyncMock()
        cog = legacy_cmds.Owner.__new__(legacy_cmds.Owner)
        cog.bot = MagicMock()
        cog.bot.pool = pool
        cog.bot.config = {"RUN_LOCAL_LAVALINK": run_local}
        cog.bot.get_color.return_value = 0
        ctx = MagicMock()
        ctx.command.extras = legacy_cmds.Owner.updatelavalink.extras
        ctx.send = AsyncMock()
        return cog, ctx, pool

    return criar


def comando(nome):
    from empiremuse.cogs import legacy_cmds

    return getattr(legacy_cmds.Owner, nome).callback


class TestGuardaDosComandosDeOwner:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome, argumentos", [("restartlavalink", ()), ("updatelavalink", ("",))])
    async def test_com_run_local_ligado_e_sem_instancia_tenta_subir_o_lavalink(self, owner_com_pool, nome, argumentos):
        """Depois de uma falha no reinício (instância None) o dono precisa conseguir tentar de novo."""
        cog, ctx, pool = owner_com_pool(run_local=True, instancia=None)

        await comando(nome)(cog, ctx, *argumentos)

        pool.start_lavalink.assert_awaited_once()


# ============================================================================ (9) D-11: sem consulta ao Maven na partida


OVERRIDE_RELATIVO = Path(".lavalink") / "plugins-override.yml"


class TestSemConsultaAoMaven:
    """O Lavalink consulta o Maven a cada partida por plugin do application.yml; sem rede isso derruba o boot."""

    def test_arquivo_correto_nao_e_reescrito(self, runtime, popen, proibidos, monkeypatch):
        instalar_binarios(runtime, monkeypatch)
        com_java_do_sistema(monkeypatch)
        ll.run_lavalink(lavalink_offline=True)
        alvo = runtime / OVERRIDE_RELATIVO
        antes = alvo.stat().st_mtime_ns

        ll.run_lavalink(lavalink_offline=True)

        assert alvo.stat().st_mtime_ns == antes

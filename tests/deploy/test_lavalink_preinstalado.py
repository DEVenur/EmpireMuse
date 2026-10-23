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
import inspect
import re
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from empiremuse import config_loader, paths
from empiremuse.utils import branding
from empiremuse.utils.music import local_lavalink as ll
from tests.support.raiz import RAIZ

ROOT = RAIZ
NOVAS_CHAVES = ("LAVALINK_JAVA_PATH", "LAVALINK_HOME", "LAVALINK_OFFLINE")
JANELA_DE_OBSERVACAO = 2.5  # segundos observando que algo NÃO acontece (cobre um polling de ~1 s do vigia)
LIMITE_DE_ESPERA = 6.0  # segundos esperando que algo aconteça


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


def sem_java_no_sistema(monkeypatch):
    """ "java" não existe no PATH, mas um caminho explícito é aceito (como seria com um Java de verdade)."""
    monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: None if cmd == "java" else cmd)


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
    def test_default_config_traz_as_tres_chaves_com_os_padroes_decididos(self):
        padroes = config_loader.DEFAULT_CONFIG
        assert padroes["LAVALINK_JAVA_PATH"] == ""
        assert padroes["LAVALINK_HOME"] == ""
        assert padroes["LAVALINK_OFFLINE"] is False

    @pytest.fixture
    def carregar(self, monkeypatch, tmp_path):
        """load_config() com RUNTIME_DIR vazio (sem config.json) e o .env real já neutralizado pelo conftest."""
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        for chave in NOVAS_CHAVES:
            monkeypatch.delenv(chave, raising=False)
        return config_loader.load_config

    @pytest.mark.parametrize("texto, esperado", [("true", True), ("false", False), ("", False)])
    def test_lavalink_offline_e_convertido_como_os_demais_booleanos(self, carregar, monkeypatch, texto, esperado):
        monkeypatch.setenv("LAVALINK_OFFLINE", texto)
        assert carregar()["LAVALINK_OFFLINE"] is esperado

    def test_lavalink_offline_sem_variavel_fica_falso(self, carregar):
        assert carregar()["LAVALINK_OFFLINE"] is False

    def test_lavalink_offline_invalido_falha_alto_como_os_outros_booleanos(self, carregar, monkeypatch):
        monkeypatch.setenv("LAVALINK_OFFLINE", "talvez")
        with pytest.raises(Exception, match="LAVALINK_OFFLINE"):
            carregar()

    def test_caminhos_chegam_como_texto_sem_alteracao(self, carregar, monkeypatch):
        monkeypatch.setenv("LAVALINK_JAVA_PATH", "/opt/java com espaço/bin/java")
        monkeypatch.setenv("LAVALINK_HOME", "/opt/lavalink")
        config = carregar()
        assert config["LAVALINK_JAVA_PATH"] == "/opt/java com espaço/bin/java"
        assert config["LAVALINK_HOME"] == "/opt/lavalink"

    def test_example_env_documenta_as_tres_chaves_com_valores_seguros(self):
        texto = (ROOT / ".example.env").read_text(encoding="utf-8")
        assert re.search(r"^LAVALINK_JAVA_PATH=$", texto, re.M)
        assert re.search(r"^LAVALINK_HOME=$", texto, re.M)
        assert re.search(r"^LAVALINK_OFFLINE=false$", texto, re.M)


# ============================================================================ (2) Java configurado


class TestAssinatura:
    def test_run_lavalink_aceita_os_tres_parametros_nomeados(self):
        parametros = inspect.signature(ll.run_lavalink).parameters
        for nome in ("lavalink_java_path", "lavalink_home", "lavalink_offline"):
            assert nome in parametros, f"run_lavalink precisa do parâmetro {nome}"
            assert parametros[nome].kind is inspect.Parameter.KEYWORD_ONLY

    def test_prepare_lavalink_files_aceita_lavalink_offline_nomeado(self):
        parametro = inspect.signature(ll.prepare_lavalink_files).parameters.get("lavalink_offline")
        assert parametro is not None and parametro.kind is inspect.Parameter.KEYWORD_ONLY
        assert parametro.default is False


class TestJavaConfigurado:
    def test_usa_o_java_configurado_sem_baixar_nem_instalar_nada(self, runtime, popen, proibidos, monkeypatch):
        home = runtime
        instalar_binarios(home, monkeypatch)
        java = criar_java(runtime.parent, "java-do-container")
        sem_java_no_sistema(monkeypatch)

        ll.run_lavalink(lavalink_java_path=str(java))

        assert proibidos == []
        ((args, _),) = popen
        assert args[0] == str(java)
        assert args[-2:] == ["-jar", "Lavalink.jar"]

    def test_o_java_configurado_vence_o_java_do_sistema(self, runtime, popen, proibidos, monkeypatch):
        instalar_binarios(runtime, monkeypatch)
        java = criar_java(runtime.parent, "java-do-container")
        com_java_do_sistema(monkeypatch)  # existe um "java" no PATH, mas o configurado manda

        ll.run_lavalink(lavalink_java_path=str(java))

        assert popen[0][0][0] == str(java)

    def test_caminho_do_java_com_espacos_chega_inteiro_ao_popen(self, runtime, popen, proibidos, monkeypatch):
        instalar_binarios(runtime, monkeypatch)
        java = criar_java(runtime.parent, "java com espaço")
        sem_java_no_sistema(monkeypatch)

        ll.run_lavalink(lavalink_java_path=str(java), lavalink_cpu_cores=2, lavalink_ram_limit=256)

        args = popen[0][0]
        assert args[0] == str(java), "o caminho com espaços não pode ser cortado em vários argumentos"
        assert "-XX:ActiveProcessorCount=2" in args and "-Xmx256m" in args

    @pytest.mark.parametrize("cenario", ["inexistente", "sem_permissao", "diretorio"])
    def test_java_invalido_levanta_erro_claro_citando_a_variavel(self, runtime, popen, proibidos, monkeypatch, cenario):
        instalar_binarios(runtime, monkeypatch)
        com_java_do_sistema(monkeypatch)  # mesmo com Java no sistema: caminho configurado inválido é erro, não fallback
        alvo = {
            "inexistente": runtime.parent / "nao-existe" / "bin" / "java",
            "sem_permissao": criar_java(runtime.parent, "sem-x", modo=0o644),
            "diretorio": runtime.parent,
        }[cenario]

        with pytest.raises(ll.LavalinkDownloadError) as erro:
            ll.run_lavalink(lavalink_java_path=str(alvo))

        mensagem = str(erro.value)
        assert "LAVALINK_JAVA_PATH" in mensagem
        assert any(palavra in mensagem.lower() for palavra in ("não", "executável", "encontrad", "existe"))
        assert popen == [] and proibidos == []

    def test_sem_java_configurado_e_sem_java_no_sistema_o_jdk_continua_sendo_instalado(
        self, runtime, popen, monkeypatch
    ):
        """Caracterização: fora do container nada muda — sem LAVALINK_JAVA_PATH o JDK é instalado como hoje."""
        instalar_binarios(runtime, monkeypatch)
        java = criar_java(runtime.parent, "jdk-instalado")
        monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: None)
        instalacoes = []
        monkeypatch.setattr(ll, "_install_jdk_linux", lambda *a, **k: instalacoes.append(a) or str(java))
        monkeypatch.setattr(ll.requests, "get", MagicMock(side_effect=AssertionError("rede inesperada")))

        ll.run_lavalink()

        assert len(instalacoes) == 1
        assert popen[0][0][0] == str(java)


# ============================================================================ (3) modo offline


@pytest.fixture
def pasta_pronta(tmp_path, monkeypatch):
    destino = tmp_path / "pre-instalado"
    return destino, instalar_binarios(destino, monkeypatch)


NOMES_PLUGINS = list(branding.LAVALINK_PLUGIN_SHA256)
ARQUIVOS_CONFERIDOS = ["Lavalink.jar", "application.yml", *[f"plugins/{nome}" for nome in NOMES_PLUGINS]]


class TestOffline:
    def test_com_tudo_presente_e_correto_nao_faz_nenhum_download(self, pasta_pronta, proibidos):
        destino, _ = pasta_pronta

        ll.prepare_lavalink_files(str(destino), lavalink_offline=True)

        assert proibidos == []

    @pytest.mark.parametrize("relativo", ARQUIVOS_CONFERIDOS)
    def test_arquivo_ausente_levanta_erro_claro_que_cita_o_arquivo_sem_baixar(self, pasta_pronta, proibidos, relativo):
        destino, _ = pasta_pronta
        (destino / relativo).unlink()

        with pytest.raises(ll.LavalinkDownloadError) as erro:
            ll.prepare_lavalink_files(str(destino), lavalink_offline=True)

        assert not isinstance(erro.value, ll.IntegrityError)
        assert Path(relativo).name in str(erro.value)
        assert proibidos == []
        assert not (destino / relativo).exists(), "o modo offline não cria nem baixa nada"

    @pytest.mark.parametrize("relativo", ARQUIVOS_CONFERIDOS)
    def test_hash_divergente_levanta_integrity_error_e_nao_toca_no_arquivo(self, pasta_pronta, proibidos, relativo):
        destino, _ = pasta_pronta
        adulterado = b"CONTEUDO-ADULTERADO"
        (destino / relativo).write_bytes(adulterado)

        with pytest.raises(ll.IntegrityError) as erro:
            ll.prepare_lavalink_files(str(destino), lavalink_offline=True)

        assert Path(relativo).name in str(erro.value)
        assert proibidos == []
        assert (destino / relativo).read_bytes() == adulterado, "imagem pré-instalada pode ser somente leitura"

    def test_pasta_vazia_levanta_erro_sem_criar_nada(self, tmp_path, proibidos):
        vazia = tmp_path / "vazia"
        vazia.mkdir()

        with pytest.raises(ll.LavalinkDownloadError):
            ll.prepare_lavalink_files(str(vazia), lavalink_offline=True)

        assert list(vazia.iterdir()) == []
        assert proibidos == []

    def test_sem_offline_continua_baixando_o_que_faltar(self, tmp_path, monkeypatch):
        """Caracterização (passa hoje): o comportamento online não muda."""
        baixados = []
        monkeypatch.setattr(
            ll, "download_verified", lambda url, filename, sha256, **k: baixados.append(Path(filename).name)
        )

        ll.prepare_lavalink_files(str(tmp_path))

        assert sorted(baixados) == sorted(["Lavalink.jar", "application.yml", *NOMES_PLUGINS])

    def test_com_offline_falso_explicito_tambem_baixa_o_que_faltar(self, tmp_path, monkeypatch):
        baixados = []
        monkeypatch.setattr(
            ll, "download_verified", lambda url, filename, sha256, **k: baixados.append(Path(filename).name)
        )

        ll.prepare_lavalink_files(str(tmp_path), lavalink_offline=False)

        assert sorted(baixados) == sorted(["Lavalink.jar", "application.yml", *NOMES_PLUGINS])


class TestOfflineNoRunLavalink:
    def test_arquivos_corretos_iniciam_o_java_sem_nenhum_download(self, runtime, popen, proibidos, monkeypatch):
        instalar_binarios(runtime, monkeypatch)
        com_java_do_sistema(monkeypatch)

        ll.run_lavalink(lavalink_offline=True)

        assert proibidos == []
        assert len(popen) == 1

    def test_arquivo_ausente_impede_a_partida_e_nao_baixa(self, runtime, popen, proibidos, monkeypatch):
        instalar_binarios(runtime, monkeypatch)
        (runtime / "Lavalink.jar").unlink()
        com_java_do_sistema(monkeypatch)

        with pytest.raises(ll.LavalinkDownloadError, match="Lavalink.jar"):
            ll.run_lavalink(lavalink_offline=True)

        assert popen == [] and proibidos == []

    def test_plugin_adulterado_impede_a_partida(self, runtime, popen, proibidos, monkeypatch):
        instalar_binarios(runtime, monkeypatch)
        (runtime / "plugins" / NOMES_PLUGINS[0]).write_bytes(b"ADULTERADO")
        com_java_do_sistema(monkeypatch)

        with pytest.raises(ll.IntegrityError):
            ll.run_lavalink(lavalink_offline=True)

        assert popen == [] and proibidos == []

    def test_offline_com_java_configurado_nao_baixa_jdk_nem_arquivos(self, runtime, popen, proibidos, monkeypatch):
        """O cenário do container: tudo pré-instalado em LAVALINK_HOME + Java configurado + offline."""
        pre_instalado = runtime.parent / "opt-lavalink"
        instalar_binarios(pre_instalado, monkeypatch)
        java = criar_java(runtime.parent, "opt-java")
        sem_java_no_sistema(monkeypatch)

        ll.run_lavalink(lavalink_java_path=str(java), lavalink_home=str(pre_instalado), lavalink_offline=True)

        assert proibidos == []
        args, kwargs = popen[0]
        assert args[0] == str(java)
        assert Path(kwargs["cwd"]).resolve() == pre_instalado.resolve()


# ============================================================================ LAVALINK_HOME


class TestLavalinkHome:
    def test_arquivos_sao_preparados_e_o_processo_roda_em_lavalink_home(self, runtime, popen, proibidos, monkeypatch):
        outra_pasta = runtime.parent / "outra-pasta"
        instalar_binarios(outra_pasta, monkeypatch)  # RUNTIME_DIR continua vazio: só LAVALINK_HOME tem os arquivos
        com_java_do_sistema(monkeypatch)

        ll.run_lavalink(lavalink_home=str(outra_pasta))

        assert proibidos == []
        assert Path(popen[0][1]["cwd"]).resolve() == outra_pasta.resolve()

    def test_home_vazio_significa_runtime_dir(self, runtime, popen, proibidos, monkeypatch):
        instalar_binarios(runtime, monkeypatch)
        com_java_do_sistema(monkeypatch)

        ll.run_lavalink(lavalink_home="")

        assert Path(popen[0][1]["cwd"]).resolve() == paths.RUNTIME_DIR.resolve()

    def test_sem_nenhuma_variavel_nova_o_comportamento_atual_nao_muda(self, runtime, popen, proibidos, monkeypatch):
        """Caracterização (passa hoje): java do sistema, jar no RUNTIME_DIR, Popen em RUNTIME_DIR."""
        instalar_binarios(runtime, monkeypatch)
        com_java_do_sistema(monkeypatch)

        ll.run_lavalink()

        args, kwargs = popen[0]
        assert args[0] == "java" and args[-2:] == ["-jar", "Lavalink.jar"]
        assert Path(kwargs["cwd"]).resolve() == runtime.resolve()
        assert proibidos == []


# ============================================================================ (4) SERVER_ADDRESS


class TestServerAddress:
    def test_sempre_127_0_0_1_mesmo_com_outro_valor_no_ambiente_do_bot(self):
        assert ll.lavalink_child_env(None, {"SERVER_ADDRESS": "0.0.0.0"})["SERVER_ADDRESS"] == "127.0.0.1"

    def test_presente_mesmo_quando_o_ambiente_do_bot_nao_define(self):
        assert ll.lavalink_child_env(None, {"PATH": "/bin"})["SERVER_ADDRESS"] == "127.0.0.1"
        assert ll.lavalink_child_env(None, {})["SERVER_ADDRESS"] == "127.0.0.1"

    def test_com_token_tambem_e_127_0_0_1(self):
        env = ll.lavalink_child_env("tok", {"SERVER_ADDRESS": "192.168.1.10"})
        assert env["SERVER_ADDRESS"] == "127.0.0.1"
        assert env["PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN"] == "tok"

    def test_variante_em_minusculas_do_ambiente_nao_vira_um_segundo_endereco(self):
        env = ll.lavalink_child_env(None, {"server_address": "0.0.0.0", "Server_Address": "::"})
        enderecos = {valor for chave, valor in env.items() if chave.upper() == "SERVER_ADDRESS"}
        assert enderecos == {"127.0.0.1"}
        assert len([chave for chave in env if chave.upper() == "SERVER_ADDRESS"]) == 1

    def test_o_ambiente_de_entrada_nao_e_alterado(self):
        entrada = {"SERVER_ADDRESS": "0.0.0.0", "PATH": "/bin"}
        ll.lavalink_child_env(None, entrada)
        assert entrada == {"SERVER_ADDRESS": "0.0.0.0", "PATH": "/bin"}

    def test_o_popen_recebe_127_0_0_1_mesmo_se_o_ambiente_do_bot_expoe_o_lavalink(
        self, runtime, popen, proibidos, monkeypatch
    ):
        instalar_binarios(runtime, monkeypatch)
        com_java_do_sistema(monkeypatch)
        monkeypatch.setenv("SERVER_ADDRESS", "0.0.0.0")

        ll.run_lavalink()

        assert popen[0][1]["env"]["SERVER_ADDRESS"] == "127.0.0.1"

    def test_a_porta_continua_passando_como_hoje(self):
        """Caracterização (passa hoje): SERVER_PORT segue na allowlist."""
        assert ll.lavalink_child_env(None, {"SERVER_PORT": "9001"})["SERVER_PORT"] == "9001"


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

    @pytest.mark.asyncio
    async def test_os_outros_bots_sao_fechados_e_o_java_encerrado_apos_uma_falha(self):
        saudavel = AsyncMock()
        saudavel.is_closed = MagicMock(return_value=False)
        pool = pool_para_shutdown(bot_falho(), saudavel)

        await pool.shutdown(42)

        saudavel.close.assert_awaited_once()
        assert pool.exit_code == 42
        assert pool.lavalink_instance.sinais


# ============================================================================ (6) queda do Java


def vigiar(java, chamadas, avisado):
    def ao_sair(codigo):
        chamadas.append(codigo)
        avisado.set()

    thread = threading.Thread(target=ll.watch_lavalink_process, args=(java, ao_sair), daemon=True)
    thread.start()
    return thread


class TestVigiaDoProcesso:
    @pytest.fixture
    def java(self):
        processo = FakeJava()
        yield processo
        processo.die(0) if processo.returncode is None else None  # libera a thread do vigia ao final do teste

    def test_a_funcao_existe_e_e_chamavel(self):
        assert callable(getattr(ll, "watch_lavalink_process", None))

    @pytest.mark.parametrize("codigo", [0, 1, 3, 137, -9])
    def test_chama_o_callback_com_o_codigo_de_saida(self, java, codigo):
        chamadas, avisado = [], threading.Event()
        vigiar(java, chamadas, avisado)

        java.die(codigo)

        assert avisado.wait(LIMITE_DE_ESPERA), "o vigia não percebeu a saída do processo"
        assert chamadas == [codigo]

    def test_nao_chama_o_callback_enquanto_o_processo_esta_vivo(self, java):
        chamadas, avisado = [], threading.Event()
        vigiar(java, chamadas, avisado)

        assert not avisado.wait(0.5)
        assert chamadas == []

    def test_chama_o_callback_uma_unica_vez(self, java):
        chamadas, avisado = [], threading.Event()
        vigiar(java, chamadas, avisado)
        java.die(7)
        assert avisado.wait(LIMITE_DE_ESPERA)

        time.sleep(JANELA_DE_OBSERVACAO)

        assert chamadas == [7]

    def test_processo_que_ja_tinha_morrido_tambem_e_reportado(self, java):
        java.die(1)
        chamadas, avisado = [], threading.Event()

        vigiar(java, chamadas, avisado)

        assert avisado.wait(LIMITE_DE_ESPERA)
        assert chamadas == [1]


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

    @pytest.mark.asyncio
    async def test_queda_inesperada_do_java_aciona_shutdown_com_codigo_1(self, fabrica_de_pool):
        java = FakeJava()
        pool, _ = fabrica_de_pool(java)
        await pool.start_lavalink()

        java.die(3)

        assert await _aguardar_async(lambda: pool.shutdown.await_count >= 1), "shutdown não foi acionado"
        args, kwargs = pool.shutdown.await_args
        assert kwargs.get("exit_code", args[0] if args else 1) == 1
        await asyncio.sleep(0.3)
        assert pool.shutdown.await_count == 1

    @pytest.mark.asyncio
    async def test_saida_do_java_durante_o_encerramento_nao_sobrescreve_o_exit_code(self, fabrica_de_pool):
        """shutdown(42) mata o Java; a morte dele não pode virar um novo shutdown(1) que troque o exit_code."""
        assert callable(getattr(ll, "watch_lavalink_process", None))
        java = FakeJava()
        pool, _ = fabrica_de_pool(java)
        from empiremuse.utils.client import BotPool

        pool.shutdown = BotPool.shutdown.__get__(pool)  # shutdown de verdade, não o dublê
        await pool.start_lavalink()

        await pool.shutdown(42)
        await asyncio.sleep(JANELA_DE_OBSERVACAO)

        assert java.sinais, "o shutdown precisa ter encerrado o Java"
        assert pool.exit_code == 42

    @pytest.mark.asyncio
    async def test_reiniciar_o_lavalink_nao_e_tratado_como_queda(self, fabrica_de_pool):
        """start_lavalink mata a instância antiga ao reiniciar (!restartll): a morte dela não derruba o bot."""
        assert callable(getattr(ll, "watch_lavalink_process", None))
        antigo, novo = FakeJava(), FakeJava()
        pool, _ = fabrica_de_pool(antigo, novo)
        await pool.start_lavalink()

        await pool.start_lavalink()
        await asyncio.sleep(JANELA_DE_OBSERVACAO)

        assert antigo.sinais, "o reinício precisa ter encerrado a instância antiga"
        assert pool.lavalink_instance is novo and novo.returncode is None
        pool.shutdown.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_queda_do_java_novo_apos_reinicio_ainda_aciona_shutdown(self, fabrica_de_pool):
        antigo, novo = FakeJava(), FakeJava()
        pool, _ = fabrica_de_pool(antigo, novo)
        await pool.start_lavalink()
        await pool.start_lavalink()

        novo.die(1)

        assert await _aguardar_async(lambda: pool.shutdown.await_count >= 1), "a queda do Java novo precisa ser vigiada"


async def _aguardar_async(condicao, limite=LIMITE_DE_ESPERA):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if condicao():
            return True
        await asyncio.sleep(0.02)
    return condicao()


# ============================================================================ (7) acréscimos da D-09 (decididos pelo MAESTRO)


class TestLogsComLavalinkHome:
    """application.yml tem SHA-256 fixo: o destino dos logs vai pela linha de comando do Java."""

    def test_com_lavalink_home_fora_do_runtime_dir_os_logs_vao_para_o_volume_gravavel(
        self, runtime, popen, proibidos, monkeypatch
    ):
        somente_leitura = runtime.parent / "opt-lavalink"
        instalar_binarios(somente_leitura, monkeypatch)
        com_java_do_sistema(monkeypatch)

        ll.run_lavalink(lavalink_home=str(somente_leitura), lavalink_offline=True)

        args = popen[0][0]
        esperado = f"-Dlogging.file.path={paths.RUNTIME_DIR / '.logs' / 'lavalink'}"
        assert esperado in args
        assert args.index(esperado) < args.index("-jar"), "a propriedade precisa vir antes do -jar"
        assert (runtime / ".logs" / "lavalink").is_dir()

    @pytest.mark.parametrize("home", ["", "igual_ao_runtime"])
    def test_sem_lavalink_home_diferente_do_runtime_dir_nada_muda(self, runtime, popen, proibidos, monkeypatch, home):
        instalar_binarios(runtime, monkeypatch)
        com_java_do_sistema(monkeypatch)

        ll.run_lavalink(lavalink_home=str(runtime) if home else "")

        assert not [arg for arg in popen[0][0] if arg.startswith("-Dlogging")]
        assert not (runtime / ".logs").exists()


class TestValidateJavaComTimeout:
    def test_usa_timeout_e_trata_a_expiracao_como_java_invalido(self, monkeypatch):
        chamadas = []

        def check_output_falso(args, **kwargs):
            chamadas.append((args, kwargs))
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])

        monkeypatch.setattr(ll.subprocess, "check_output", check_output_falso)

        assert ll.validate_java("/opt/java com espaço/bin/java") is None

        ((args, kwargs),) = chamadas
        assert args == ["/opt/java com espaço/bin/java", "-version"], "sem shell: o caminho é UM argumento"
        assert 0 < kwargs["timeout"] <= 30


class TestStopLavalink:
    @pytest.mark.asyncio
    async def test_mata_o_java_zera_a_instancia_e_nao_aciona_shutdown(self, fabrica_de_pool):
        java = FakeJava()
        pool, _ = fabrica_de_pool(java)
        await pool.start_lavalink()

        pool.stop_lavalink()
        await asyncio.sleep(JANELA_DE_OBSERVACAO)

        assert java.sinais == ["kill"]
        assert pool.lavalink_instance is None
        pool.shutdown.assert_not_awaited()

    def test_sem_instancia_nao_faz_nada(self, fabrica_de_pool):
        pool = type("PoolSemJava", (), {})()
        pool.lavalink_instance = None
        from empiremuse.utils.client import BotPool

        BotPool.stop_lavalink(pool)

        assert pool.lavalink_instance is None

    @pytest.mark.asyncio
    async def test_updatelavalink_mata_o_java_pelo_stop_lavalink_sem_derrubar_o_bot(
        self, fabrica_de_pool, runtime, monkeypatch
    ):
        """O comando mata o Java, espera e sobe outro: a morte do antigo não pode virar shutdown(1)."""
        from types import SimpleNamespace

        from empiremuse.cogs import legacy_cmds

        antigo, novo = FakeJava(), FakeJava()
        pool, _ = fabrica_de_pool(antigo, novo)
        await pool.start_lavalink()
        assert paths.RUNTIME_DIR.resolve() == runtime.resolve(), (
            "o comando apaga o jar: só pode agir no runtime isolado"
        )
        monkeypatch.setattr(legacy_cmds, "asyncio", SimpleNamespace(sleep=AsyncMock()))
        cog = legacy_cmds.Owner.__new__(legacy_cmds.Owner)
        cog.bot = MagicMock()
        cog.bot.pool = pool
        cog.bot.get_color.return_value = 0
        ctx = MagicMock()
        ctx.command.extras = legacy_cmds.Owner.updatelavalink.extras
        ctx.send = AsyncMock()

        await legacy_cmds.Owner.updatelavalink.callback(cog, ctx, "")
        await asyncio.sleep(JANELA_DE_OBSERVACAO)

        assert antigo.sinais == ["kill"]
        assert pool.lavalink_instance is novo and novo.returncode is None
        pool.shutdown.assert_not_awaited()


# ============================================================================ (8) guarda dos comandos de owner pela config


NAO_ESTA_SENDO_USADO = "não está sendo usado"


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

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome, argumentos", [("restartlavalink", ()), ("updatelavalink", ("",))])
    async def test_com_run_local_desligado_e_sem_instancia_continua_respondendo_que_nao_esta_em_uso(
        self, owner_com_pool, nome, argumentos
    ):
        from empiremuse.utils.music.errors import GenericError

        cog, ctx, pool = owner_com_pool(run_local=False, instancia=None)

        with pytest.raises(GenericError, match=NAO_ESTA_SENDO_USADO):
            await comando(nome)(cog, ctx, *argumentos)

        pool.start_lavalink.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome, argumentos", [("restartlavalink", ()), ("updatelavalink", ("",))])
    async def test_java_local_em_execucao_sem_run_local_na_config_continua_reiniciavel(
        self, owner_com_pool, nome, argumentos
    ):
        """O boot também sobe o Lavalink local quando a lista de servidores está vazia, mesmo com RUN_LOCAL=false."""
        cog, ctx, pool = owner_com_pool(run_local=False, instancia=FakeJava())

        await comando(nome)(cog, ctx, *argumentos)

        pool.start_lavalink.assert_awaited_once()


# ============================================================================ (9) D-11: sem consulta ao Maven na partida


OVERRIDE_RELATIVO = Path(".lavalink") / "plugins-override.yml"
PREFIXO_OVERRIDE = "-Dspring.config.additional-location="


def carregar_yaml_seguro(caminho: Path):
    from ruamel.yaml import YAML

    return YAML(typ="safe").load(caminho.read_text(encoding="utf-8"))


def arvore(raiz: Path) -> dict:
    return {str(p.relative_to(raiz)): (p.stat().st_size if p.is_file() else None) for p in sorted(raiz.rglob("*"))}


class TestSemConsultaAoMaven:
    """O Lavalink consulta o Maven a cada partida por plugin do application.yml; sem rede isso derruba o boot."""

    @pytest.mark.parametrize("offline", [False, True], ids=["online", "offline"])
    def test_o_java_recebe_o_override_com_caminho_absoluto_em_runtime_dir_antes_do_jar(
        self, runtime, popen, proibidos, monkeypatch, offline
    ):
        instalar_binarios(runtime, monkeypatch)
        com_java_do_sistema(monkeypatch)

        ll.run_lavalink(lavalink_offline=offline)

        args = popen[0][0]
        esperado = f"{PREFIXO_OVERRIDE}{(runtime / OVERRIDE_RELATIVO).resolve().as_uri()}"
        assert esperado in args
        assert args.index(esperado) < args.index("-jar"), "a propriedade precisa vir antes do -jar"
        assert esperado.removeprefix(PREFIXO_OVERRIDE).startswith("file:///")

    def test_o_arquivo_tem_exatamente_a_lista_de_plugins_vazia(self, runtime, popen, proibidos, monkeypatch):
        instalar_binarios(runtime, monkeypatch)
        com_java_do_sistema(monkeypatch)

        ll.run_lavalink(lavalink_offline=True)

        assert carregar_yaml_seguro(runtime / OVERRIDE_RELATIVO) == {"lavalink": {"plugins": []}}

    def test_arquivo_divergente_e_reescrito_e_nao_sobra_temporario(self, runtime, popen, proibidos, monkeypatch):
        instalar_binarios(runtime, monkeypatch)
        com_java_do_sistema(monkeypatch)
        alvo = runtime / OVERRIDE_RELATIVO
        alvo.parent.mkdir(parents=True)
        alvo.write_text("lavalink:\n  plugins:\n    - dependency: com.exemplo:plugin:1.0\n", encoding="utf-8")

        ll.run_lavalink(lavalink_offline=True)

        assert carregar_yaml_seguro(alvo) == {"lavalink": {"plugins": []}}
        assert sorted(p.name for p in alvo.parent.iterdir()) == [alvo.name]

    def test_arquivo_correto_nao_e_reescrito(self, runtime, popen, proibidos, monkeypatch):
        instalar_binarios(runtime, monkeypatch)
        com_java_do_sistema(monkeypatch)
        ll.run_lavalink(lavalink_offline=True)
        alvo = runtime / OVERRIDE_RELATIVO
        antes = alvo.stat().st_mtime_ns

        ll.run_lavalink(lavalink_offline=True)

        assert alvo.stat().st_mtime_ns == antes

    def test_com_lavalink_home_somente_leitura_nada_e_escrito_nele(self, runtime, popen, proibidos, monkeypatch):
        pre_instalado = runtime.parent / "opt-lavalink"
        instalar_binarios(pre_instalado, monkeypatch)
        com_java_do_sistema(monkeypatch)
        antes = arvore(pre_instalado)
        pre_instalado.chmod(0o555)
        try:
            ll.run_lavalink(lavalink_home=str(pre_instalado), lavalink_offline=True)
        finally:
            pre_instalado.chmod(0o755)

        assert arvore(pre_instalado) == antes
        assert (runtime / OVERRIDE_RELATIVO).is_file(), "o override mora em RUNTIME_DIR, nunca em LAVALINK_HOME"
        args = popen[0][0]
        assert f"{PREFIXO_OVERRIDE}{(runtime / OVERRIDE_RELATIVO).resolve().as_uri()}" in args

    def test_falha_ao_gravar_o_override_e_erro_claro_citando_o_arquivo(self, runtime, popen, proibidos, monkeypatch):
        instalar_binarios(runtime, monkeypatch)
        com_java_do_sistema(monkeypatch)
        (runtime / ".lavalink").write_text("é um arquivo, não uma pasta")

        with pytest.raises(ll.LavalinkDownloadError, match="plugins-override.yml"):
            ll.run_lavalink(lavalink_offline=True)

        assert popen == []

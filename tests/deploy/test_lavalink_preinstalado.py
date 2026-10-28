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
import time
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
    monkeypatch.setattr(ll, "java_major_version", lambda cmd, debug=False: 25)

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

    @pytest.mark.parametrize("cenario", ["inexistente", "diretorio"])
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


# ============================================================================ (4) SERVER_ADDRESS


# ============================================================================ (5) encerramento


# ============================================================================ (6) queda do Java


# ============================================================================ (6) integração com o pool


# ============================================================================ (7) acréscimos da D-09 (decididos pelo MAESTRO)


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


# ============================================================================ (9) D-11: sem consulta ao Maven na partida


OVERRIDE_RELATIVO = Path(".lavalink") / "plugins-override.yml"
PREFIXO_OVERRIDE = "-Dspring.config.additional-location="


def arvore(raiz: Path) -> dict:
    return {str(p.relative_to(raiz)): (p.stat().st_size if p.is_file() else None) for p in sorted(raiz.rglob("*"))}


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

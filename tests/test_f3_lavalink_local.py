"""F3-2 — testes RED do Lavalink local (KI-14, KI-24 e o override do Spring como URI). Sem rede, sem Java real, sem Discord.

KI-14  ``LAVALINK_CPU_CORES`` chega ao ``run_lavalink`` (o ``BotPool.start_lavalink`` não o repassava), e a linha de comando
       usa ``-Xms`` = LAVALINK_INITIAL_RAM e ``-Xmx`` = LAVALINK_RAM_LIMIT (``-Xms`` recebia o limite).
KI-24  ``JAVA_HOME`` vira ``os.path.join(JAVA_HOME, "bin", "java")``: a concatenação de strings sem separador nunca achava o Java.
URI    o ``-Dspring.config.additional-location`` usa o caminho como URI (``Path.as_uri()``): o Spring trata a vírgula como
       separador de lista de locais e o espaço quebra o caminho cru; com o URI ambos funcionam.

Testes marcados GUARDA descrevem comportamento que já funciona e não pode regredir.
"""

import asyncio
import socket
import threading
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import unquote, urlparse

import pytest

from empiremuse import paths
from empiremuse.utils import client
from empiremuse.utils.client import BotPool
from empiremuse.utils.music import local_lavalink as ll

OVERRIDE_ARG = "-Dspring.config.additional-location="
OVERRIDE_CONTEUDO = "lavalink:\n  plugins: []\n"


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("tentativa de acesso à rede num teste que não pode usar rede")

    monkeypatch.setattr(socket.socket, "connect", proibido)
    monkeypatch.setattr(socket, "create_connection", proibido)
    monkeypatch.setattr(socket, "getaddrinfo", proibido)


def preparar_runtime(monkeypatch, tmp_path: Path, nome: str = "home") -> Path:
    home, cwd = tmp_path / nome, tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir(exist_ok=True)
    monkeypatch.setenv("EMPIREMUSE_HOME", str(home))
    monkeypatch.chdir(cwd)
    return home


@pytest.fixture
def runtime(monkeypatch, tmp_path) -> Path:
    return preparar_runtime(monkeypatch, tmp_path)


def linha_de_comando(**sobrescritas) -> list[str]:
    parametros = {"home": str(paths.RUNTIME_DIR), "cpu_cores": 1, "ram_limit": 256, "initial_ram": 64}
    parametros.update(sobrescritas)
    return ll._java_command("/opt/java/bin/java", **parametros)


# ============================================================================ KI-14 — CPU e RAM do Lavalink local


class FakeJava:
    def __init__(self):
        self.returncode = None
        self.pid = 4242
        self._morto = threading.Event()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self._morto.wait(timeout)
        return self.returncode

    def die(self, code=0):
        self.returncode = code
        self._morto.set()

    terminate = kill = die


class TestKI14CpuERam:
    @pytest.mark.asyncio
    async def test_o_pool_repassa_lavalink_cpu_cores_ao_run_lavalink(self, runtime, monkeypatch):
        pool = BotPool()
        pool.config["LAVALINK_CPU_CORES"] = 3
        pool.loop = asyncio.get_running_loop()
        java = FakeJava()
        run = MagicMock(return_value=java)
        monkeypatch.setattr(client, "run_lavalink", run)

        try:
            await pool.start_lavalink()
        finally:
            pool.killing_state = True  # o vigia não pode acionar shutdown ao liberar o fake
            java.die()

        assert run.call_args.kwargs.get("lavalink_cpu_cores") == 3, (
            "KI-14: LAVALINK_CPU_CORES não chega ao run_lavalink"
        )

    @pytest.mark.asyncio
    async def test_o_pool_continua_repassando_as_memorias(self, runtime, monkeypatch):
        """GUARDA."""
        pool = BotPool()
        pool.config.update({"LAVALINK_INITIAL_RAM": 48, "LAVALINK_RAM_LIMIT": 200})
        pool.loop = asyncio.get_running_loop()
        java = FakeJava()
        run = MagicMock(return_value=java)
        monkeypatch.setattr(client, "run_lavalink", run)

        try:
            await pool.start_lavalink()
        finally:
            pool.killing_state = True
            java.die()

        assert run.call_args.kwargs["lavalink_initial_ram"] == 48
        assert run.call_args.kwargs["lavalink_ram_limit"] == 200

    def test_xms_usa_a_ram_inicial_e_xmx_o_limite(self, runtime):
        args = linha_de_comando(initial_ram=64, ram_limit=256)

        assert "-Xms64m" in args, f"KI-14: -Xms deveria ser a RAM inicial: {[a for a in args if a.startswith('-Xm')]}"
        assert "-Xmx256m" in args
        assert "-Xms256m" not in args

    def test_cpu_cores_vira_activeprocessorcount(self, runtime):
        """GUARDA."""
        assert "-XX:ActiveProcessorCount=4" in linha_de_comando(cpu_cores=4)

    @pytest.mark.parametrize("inicial", [0, 256, 300])
    def test_sem_xms_quando_a_ram_inicial_nao_cabe_no_limite(self, runtime, inicial):
        """GUARDA: -Xms maior ou igual a -Xmx é rejeitado pela JVM; hoje já não é emitido."""
        args = linha_de_comando(initial_ram=inicial, ram_limit=256)

        assert not [a for a in args if a.startswith("-Xms")]

    def test_limite_muito_baixo_nao_emite_xmx(self, runtime):
        """GUARDA."""
        assert not [a for a in linha_de_comando(ram_limit=10, initial_ram=0) if a.startswith("-Xmx")]

    def test_o_jar_vem_por_ultimo(self, runtime):
        """GUARDA."""
        assert linha_de_comando()[-2:] == ["-jar", "Lavalink.jar"]


# ============================================================================ KI-24 — JAVA_HOME


class TestKI24JavaHome:
    @staticmethod
    def _procurar(monkeypatch, java_home: str, aceito: str):
        monkeypatch.setenv("JAVA_HOME", java_home)
        monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: cmd if cmd == aceito else None)
        return ll._find_or_install_java(
            "/tmp/sem-uso", "Linux-64bit-ELF", "64bit", use_jabba=False, allow_install=False
        )

    def test_java_home_sem_barra_final_aponta_para_bin_java(self, runtime, monkeypatch, tmp_path):
        jdk = tmp_path / "jdk-17"

        achado = self._procurar(monkeypatch, str(jdk), aceito=str(jdk / "bin" / "java"))

        assert achado == str(jdk / "bin" / "java"), (
            "KI-24: JAVA_HOME + 'bin/java' sem separador nunca é um caminho válido"
        )

    def test_java_home_com_barra_final_continua_funcionando(self, runtime, monkeypatch, tmp_path):
        """GUARDA: com a barra final a concatenação antiga dava certo por acaso."""
        jdk = tmp_path / "jdk-17"

        achado = self._procurar(monkeypatch, f"{jdk}/", aceito=str(jdk / "bin" / "java"))

        assert Path(achado) == jdk / "bin" / "java"

    def test_o_candidato_testado_e_exatamente_o_join_de_tres_partes(self, runtime, monkeypatch, tmp_path):
        jdk = tmp_path / "jdk-21"
        candidatos = []

        def validar(cmd, debug=False):
            candidatos.append(cmd)
            return cmd if cmd == str(jdk / "bin" / "java") else None

        monkeypatch.setenv("JAVA_HOME", str(jdk))
        monkeypatch.setattr(ll, "validate_java", validar)

        ll._find_or_install_java("/tmp/sem-uso", "Linux-64bit-ELF", "64bit", use_jabba=False, allow_install=False)

        assert str(jdk / "bin" / "java") in candidatos, f"candidatos testados: {candidatos}"
        assert f"{jdk}bin/java" not in candidatos

    def test_java_home_invalido_sem_instalacao_permitida_continua_dando_erro_claro(
        self, runtime, monkeypatch, tmp_path
    ):
        """GUARDA: no modo offline, nenhum Java válido => erro claro, nunca download."""
        monkeypatch.setenv("JAVA_HOME", str(tmp_path / "nao-existe"))
        monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: None)

        with pytest.raises(ll.LavalinkDownloadError, match="LAVALINK_JAVA_PATH"):
            ll._find_or_install_java("/tmp/sem-uso", "Linux-64bit-ELF", "64bit", use_jabba=False, allow_install=False)

    def test_o_java_do_path_continua_tendo_prioridade(self, runtime, monkeypatch, tmp_path):
        """GUARDA."""
        monkeypatch.setenv("JAVA_HOME", str(tmp_path / "jdk"))
        monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: cmd if cmd == "java" else None)

        assert (
            ll._find_or_install_java("/tmp/x", "Linux-64bit-ELF", "64bit", use_jabba=False, allow_install=False)
            == "java"
        )


# ============================================================================ override do Spring como URI


class TestOverrideComoUri:
    @pytest.fixture
    def runtime_dificil(self, monkeypatch, tmp_path) -> Path:
        """RUNTIME_DIR com espaço e vírgula: o Spring separa os locais por vírgula e o espaço quebra o caminho cru."""
        return preparar_runtime(monkeypatch, tmp_path, nome="dir com espaco, e virgula")

    @staticmethod
    def _argumento(args: list[str]) -> str:
        return next(a for a in args if a.startswith(OVERRIDE_ARG))

    def test_o_argumento_e_o_uri_do_arquivo(self, runtime_dificil):
        arquivo = paths.RUNTIME_DIR / ".lavalink" / "plugins-override.yml"

        argumento = self._argumento(linha_de_comando())

        assert argumento == OVERRIDE_ARG + arquivo.as_uri(), f"KI: o caminho cru não é um URI seguro: {argumento}"

    def test_espaco_e_virgula_chegam_codificados(self, runtime_dificil):
        valor = self._argumento(linha_de_comando()).removeprefix(OVERRIDE_ARG)

        assert " " not in valor and "," not in valor, f"espaço/vírgula crus no local do Spring: {valor}"
        assert "%20" in valor and "%2C" in valor

    def test_o_uri_decodifica_de_volta_para_o_arquivo_que_existe(self, runtime_dificil):
        """GUARDA: o valor decodificado aponta para o arquivo real (vale hoje com o caminho cru e tem de valer com o URI)."""
        valor = self._argumento(linha_de_comando()).removeprefix(OVERRIDE_ARG)

        decodificado = Path(unquote(urlparse(valor).path))

        assert urlparse(valor).scheme == "file"
        assert decodificado == paths.RUNTIME_DIR / ".lavalink" / "plugins-override.yml"
        assert decodificado.read_text(encoding="utf-8") == OVERRIDE_CONTEUDO

    def test_o_override_e_uma_unica_entrada_da_lista_de_locais(self, runtime_dificil):
        """Uma vírgula crua partiria o valor em dois locais; com o URI só há UM item na lista separada por vírgulas."""
        valor = self._argumento(linha_de_comando()).removeprefix(OVERRIDE_ARG)

        assert len(valor.split(",")) == 1

    def test_o_argumento_vem_antes_do_jar_e_sem_split_do_caminho(self, runtime_dificil):
        """GUARDA."""
        args = linha_de_comando()

        assert args.index(self._argumento(args)) == len(args) - 3
        assert args[-2:] == ["-jar", "Lavalink.jar"]

    def test_runtime_comum_continua_gerando_um_argumento_file(self, runtime):
        """GUARDA: continua sendo ``file:`` e o conteúdo do override não muda."""
        valor = self._argumento(linha_de_comando()).removeprefix(OVERRIDE_ARG)

        assert valor.startswith("file:")
        assert Path(unquote(urlparse(valor).path)).read_text(encoding="utf-8") == OVERRIDE_CONTEUDO

    def test_o_override_nunca_e_gravado_fora_do_runtime_dir(self, runtime, tmp_path):
        """GUARDA."""
        linha_de_comando(home=str(tmp_path / "lavalink-somente-leitura"))

        assert (runtime / ".lavalink" / "plugins-override.yml").is_file()
        assert not (tmp_path / "lavalink-somente-leitura").exists()

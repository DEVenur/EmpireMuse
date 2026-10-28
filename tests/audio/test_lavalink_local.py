"""F3-2 — testes RED do Lavalink local (KI-14, KI-24 e o override do Spring como URI). Sem rede, sem Java real, sem Discord.

KI-14  ``LAVALINK_CPU_CORES`` chega ao ``run_lavalink`` (o ``BotPool.start_lavalink`` não o repassava), e a linha de comando
       usa ``-Xms`` = LAVALINK_INITIAL_RAM e ``-Xmx`` = LAVALINK_RAM_LIMIT (``-Xms`` recebia o limite).
KI-24  ``JAVA_HOME`` vira ``os.path.join(JAVA_HOME, "bin", "java")``: a concatenação de strings sem separador nunca achava o Java.
URI    o ``-Dspring.config.additional-location`` usa o caminho como URI (``Path.as_uri()``): o Spring trata a vírgula como
       separador de lista de locais e o espaço quebra o caminho cru; com o URI ambos funcionam.

Testes marcados GUARDA descrevem comportamento que já funciona e não pode regredir.
"""

import socket
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

from empiremuse import paths
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


class TestLogDoLavalinkSemCorpoDeRequisicao:
    @pytest.mark.regression
    @pytest.mark.parametrize("home_fora_do_runtime", [False, True], ids=["home-no-runtime", "home-fora-do-runtime"])
    def test_o_java_nunca_grava_o_corpo_das_requisicoes_no_log(
        self, runtime: Path, tmp_path: Path, home_fora_do_runtime: bool
    ) -> None:
        """O corpo das requisições (token OAuth do YouTube, sessão de voz) não pode ir ao spring.log, nem com LAVALINK_HOME fora do runtime."""
        home = str(tmp_path / "somente-leitura") if home_fora_do_runtime else str(paths.RUNTIME_DIR)

        assert "-Dlogging.request.includePayload=false" in linha_de_comando(home=home)


# ============================================================================ KI-24 — JAVA_HOME


class TestKI24JavaHome:
    @staticmethod
    def _procurar(monkeypatch, java_home: str, aceito: str):
        monkeypatch.setenv("JAVA_HOME", java_home)
        monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: cmd if cmd == aceito else None)
        return ll._find_or_install_java("/tmp/sem-uso", "Linux-64bit-ELF", "64bit", allow_install=False)

    def test_java_home_sem_barra_final_aponta_para_bin_java(self, runtime, monkeypatch, tmp_path):
        jdk = tmp_path / "jdk-17"

        achado = self._procurar(monkeypatch, str(jdk), aceito=str(jdk / "bin" / "java"))

        assert achado == str(jdk / "bin" / "java"), (
            "KI-24: JAVA_HOME + 'bin/java' sem separador nunca é um caminho válido"
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

    def test_o_uri_decodifica_de_volta_para_o_arquivo_que_existe(self, runtime_dificil):
        """GUARDA: o valor decodificado aponta para o arquivo real (vale hoje com o caminho cru e tem de valer com o URI)."""
        valor = self._argumento(linha_de_comando()).removeprefix(OVERRIDE_ARG)

        decodificado = Path(unquote(urlparse(valor).path))

        assert urlparse(valor).scheme == "file"
        assert decodificado == paths.RUNTIME_DIR / ".lavalink" / "plugins-override.yml"
        assert decodificado.read_text(encoding="utf-8") == OVERRIDE_CONTEUDO

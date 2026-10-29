"""S1 (Java 25) — contrato com o Lavalink: o major do Java lido de ``java -version`` e a linha de comando da JVM.

Sem Java real e sem rede: ``subprocess.check_output`` é falso e o RUNTIME_DIR fica em ``tmp_path``.

* A7 ``java_major_version``: lê o major da linha ``version "…"`` (não da primeira linha) e devolve ``None`` quando a saída é
  ilegível, o processo falha ou estoura o tempo.
* A8/A9 ``_java_command``: as duas flags de acesso só existem para 24 <= major <= 25 (nunca com major desconhecido); o GC é
  Serial com 1 core e G1 nos demais casos; nenhum MaxRAMPercentage/ZGC/AOTCache; toda opção da JVM vem antes de ``-jar``.
"""

import subprocess

import pytest

from empiremuse.utils.music import local_lavalink as ll

ACCESS_FLAGS = ("--enable-native-access=ALL-UNNAMED", "--sun-misc-unsafe-memory-access=allow")


def _saida(linha_de_versao: str, antes: str = "") -> str:
    return f"{antes}{linha_de_versao}\nOpenJDK Runtime Environment (build x)\nOpenJDK 64-Bit Server VM (build y, mixed mode)\n"


class TestJavaMajorVersion:
    @pytest.mark.parametrize(
        ("versao", "major"),
        [
            ("25.0.4.1", 25),
            ("21.0.12.1", 21),
            ("17.0.13", 17),
            ("25-ea", 25),
            ("1.8.0_402", 1),
        ],
    )
    def test_le_o_major_da_linha_version(self, monkeypatch, versao, major):
        monkeypatch.setattr(
            subprocess, "check_output", lambda *a, **k: _saida(f'openjdk version "{versao}" 2026-10-21')
        )

        assert ll.java_major_version("java") == major

    def test_ignora_a_linha_picked_up_antes_da_linha_version(self, monkeypatch):
        saida = _saida(
            'openjdk version "25.0.4.1" 2026-10-21', antes="Picked up JAVA_TOOL_OPTIONS: -Dfile.encoding=UTF-8\n"
        )
        monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: saida)

        assert ll.java_major_version("java") == 25

    @pytest.mark.parametrize("saida", ["", "isto não é java\n", 'openjdk version "abc"\n'])
    def test_saida_ilegivel_devolve_none(self, monkeypatch, saida):
        monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: saida)

        assert ll.java_major_version("java") is None

    @pytest.mark.parametrize(
        "erro",
        [OSError("sem o binário"), subprocess.TimeoutExpired("java", 1), subprocess.CalledProcessError(1, "java")],
    )
    def test_falha_do_processo_devolve_none(self, monkeypatch, erro):
        def falhar(*args, **kwargs):
            raise erro

        monkeypatch.setattr(subprocess, "check_output", falhar)

        assert ll.java_major_version("java") is None


@pytest.fixture
def comando(monkeypatch, tmp_path):
    """Monta a linha de comando com o RUNTIME_DIR isolado (o ``_java_command`` grava o tmpdir e o YAML de override nele)."""
    home = tmp_path / "runtime"
    home.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(home))
    monkeypatch.chdir(tmp_path)

    def montar(java_major, cpu_cores=2):
        return ll._java_command(
            "/opt/java/bin/java",
            home=str(home),
            cpu_cores=cpu_cores,
            ram_limit=512,
            initial_ram=256,
            java_major=java_major,
        )

    return montar


class TestJavaCommand:
    @pytest.mark.parametrize(
        ("java_major", "com_flags"),
        [(24, True), (25, True), (21, False), (23, False), (26, False), (None, False)],
    )
    def test_flags_de_acesso_so_na_faixa_24_a_25(self, comando, java_major, com_flags):
        args = comando(java_major)

        presentes = [flag in args for flag in ACCESS_FLAGS]
        assert presentes == [com_flags, com_flags]

    @pytest.mark.parametrize("java_major", [21, 25, None])
    @pytest.mark.parametrize("cpu_cores", [1, 2])
    def test_toda_opcao_da_jvm_vem_antes_de_jar_e_o_jar_fecha_a_lista(self, comando, java_major, cpu_cores):
        args = comando(java_major, cpu_cores=cpu_cores)

        assert args[-2:] == ["-jar", "Lavalink.jar"]
        assert args[0] == "/opt/java/bin/java"
        assert all(a.startswith("-") for a in args[1:-2]), "só opções da JVM entre o java e o -jar"

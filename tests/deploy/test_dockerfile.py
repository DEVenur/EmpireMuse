"""D-11 — verificações estáticas do Dockerfile e do .dockerignore (só leitura de texto; sem docker, rede ou Java).

Garantias: toda imagem base fixada por digest; usuário final não-root numérico; tini como ENTRYPOINT; os binários do
Lavalink conferidos por ``sha256sum -c`` com os MESMOS SHA-256 de ``branding.py`` (se um for atualizado e o outro
esquecido, o teste quebra); ambiente do container (offline, Java e home do Lavalink, EMPIREMUSE_HOME); só a porta 6000
exposta; e o .dockerignore barrando segredos e dados locais.
"""

import fnmatch
import re
from pathlib import Path

import pytest

from empiremuse.utils import branding
from tests.support.raiz import RAIZ

ROOT = RAIZ
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _logical_lines(text: str) -> list[str]:
    """Junta as linhas continuadas por ``\\`` e descarta comentários e linhas vazias."""
    lines, buffer = [], ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if not buffer and (not stripped or stripped.startswith("#")):
            continue
        if stripped.endswith("\\"):
            buffer += stripped[:-1].strip() + " "
            continue
        lines.append((buffer + stripped).strip())
        buffer = ""
    return lines


@pytest.fixture(scope="module")
def dockerfile() -> list[str]:
    return _logical_lines((ROOT / "Dockerfile").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def args(dockerfile) -> dict[str, str]:
    resolved = {}
    for line in dockerfile:
        match = re.match(r"ARG\s+(\w+)=(?:\"([^\"]*)\"|(\S*))$", line)
        if match:
            resolved[match.group(1)] = match.group(2) if match.group(2) is not None else match.group(3)
    return resolved


@pytest.fixture(scope="module")
def stages(dockerfile) -> list[list[str]]:
    """Instruções agrupadas por estágio (cada ``FROM`` abre um)."""
    grupos: list[list[str]] = []
    for line in dockerfile:
        if line.upper().startswith("FROM "):
            grupos.append([line])
        elif grupos:
            grupos[-1].append(line)
    return grupos


def _env_of(stage: list[str]) -> dict[str, str]:
    env = {}
    for line in stage:
        if line.upper().startswith("ENV "):
            for chave, valor in re.findall(r"(\w+)=(\"[^\"]*\"|\S+)", line[4:]):
                env[chave] = valor.strip('"')
    return env


class TestImagensBase:
    def test_todo_from_usa_imagem_externa_com_digest_sha256(self, dockerfile, args):
        aliases = set()
        externas = []
        for line in dockerfile:
            if not line.upper().startswith("FROM "):
                continue
            match = re.match(r"FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?$", line, re.I)
            assert match, f"FROM não reconhecido: {line}"
            imagem = re.sub(r"\$\{(\w+)\}", lambda m: args.get(m.group(1), m.group(0)), match.group(1))
            if imagem not in aliases:  # referência a um estágio anterior não conta
                externas.append(imagem)
            if match.group(2):
                aliases.add(match.group(2))
        assert externas, "nenhuma imagem base encontrada"
        for imagem in externas:
            assert "${" not in imagem, f"ARG de imagem sem valor padrão: {imagem}"
            assert DIGEST.search(imagem), f"imagem base sem digest @sha256: {imagem}"

    def test_nenhuma_imagem_usa_latest_nem_scratch(self, dockerfile):
        for line in dockerfile:
            if line.upper().startswith("FROM "):
                assert ":latest" not in line and "scratch" not in line.lower()

    def test_os_args_de_imagem_tambem_trazem_digest(self, args):
        imagens = {nome: valor for nome, valor in args.items() if nome.endswith("_IMAGE")}
        assert imagens
        for nome, valor in imagens.items():
            assert DIGEST.search(valor), f"{nome} sem digest: {valor}"


class TestUsuarioEEntrypoint:
    def test_estagio_final_roda_com_usuario_numerico_nao_root(self, stages):
        final = stages[-1]
        usuarios = [line.split(None, 1)[1] for line in final if line.upper().startswith("USER ")]
        assert usuarios, "o estágio final precisa de USER"
        ultimo = usuarios[-1]
        assert re.fullmatch(r"\d+(:\d+)?", ultimo), f"USER precisa ser numérico (uid[:gid]): {ultimo}"
        assert int(ultimo.split(":")[0]) > 0, "USER não pode ser root"
        if ":" in ultimo:
            assert int(ultimo.split(":")[1]) > 0, "GID não pode ser root"

    def test_o_usuario_nao_root_nao_e_trocado_de_volta_para_root_depois(self, stages):
        usuarios = [line.split(None, 1)[1] for line in stages[-1] if line.upper().startswith("USER ")]
        assert all(not re.fullmatch(r"(root|0)(:\S+)?", usuario) for usuario in usuarios)

    def test_entrypoint_em_forma_exec_usa_tini(self, stages):
        entrypoints = [line for line in stages[-1] if line.upper().startswith("ENTRYPOINT ")]
        assert len(entrypoints) == 1
        assert re.match(r'ENTRYPOINT\s+\[\s*"(?:/usr/bin/)?tini"', entrypoints[0]), entrypoints[0]

    def test_tini_e_instalado_na_imagem_final(self, stages):
        instalacoes = " ".join(line for line in stages[-1] if "apt-get install" in line)
        assert re.search(r"\btini\b", instalacoes)


class TestBinariosDoLavalink:
    def test_sha256sum_confere_os_binarios(self, dockerfile):
        assert any("sha256sum -c" in line for line in dockerfile), "falta 'sha256sum -c' no Dockerfile"

    def test_url_de_download_e_a_do_branding(self, args):
        assert args["LL_BINARIES_URL"] == branding.LAVALINK_BINARIES_URL

    def test_downloads_so_por_https_tls12(self, dockerfile):
        for line in dockerfile:
            if re.search(r"\bcurl\b", line) and "apt-get" not in line:
                total = len(re.findall(r"\bcurl\b", line))
                seguros = len(re.findall(r"\bcurl\s+--proto '=https' --tlsv1\.2\b", line))
                assert seguros == total, f"{total - seguros} de {total} chamadas curl sem --proto '=https' --tlsv1.2"

    def test_hash_do_jar_e_do_yml_sao_os_do_branding(self, args):
        assert args["LAVALINK_JAR_SHA256"] == branding.LAVALINK_JAR_SHA256
        assert args["LAVALINK_APPLICATION_YML_SHA256"] == branding.LAVALINK_APPLICATION_YML_SHA256

    def test_plugins_nome_e_hash_coincidem_com_o_branding(self, args):
        nomes = {chave[: -len("_NAME")]: valor for chave, valor in args.items() if chave.endswith("_PLUGIN_NAME")}
        hashes = {chave[: -len("_SHA256")]: valor for chave, valor in args.items() if chave.endswith("_PLUGIN_SHA256")}
        assert nomes and nomes.keys() == hashes.keys()
        assert {nomes[chave]: hashes[chave] for chave in nomes} == dict(branding.LAVALINK_PLUGIN_SHA256)

    def test_todos_os_hashes_do_dockerfile_tem_formato_valido(self, args):
        for chave, valor in args.items():
            if chave.endswith("_SHA256"):
                assert SHA256.match(valor), f"{chave} não é SHA-256 em 64 hex minúsculos"

    def test_cada_hash_e_cada_arquivo_entram_no_arquivo_de_checksums(self, dockerfile, args):
        bloco = next(line for line in dockerfile if "sha256sum -c" in line)
        for chave in (c for c in args if c.endswith("_SHA256")):
            assert f"${{{chave}}}" in bloco, f"{chave} não é usado no checksums.txt conferido por sha256sum -c"
        for chave in (c for c in args if c.endswith("_PLUGIN_NAME")):
            assert f"${{{chave}}}" in bloco
        assert "/opt/lavalink/Lavalink.jar" in bloco and "/opt/lavalink/application.yml" in bloco

    def test_baixar_e_conferir_acontecem_no_mesmo_run(self, dockerfile):
        run = next(line for line in dockerfile if "sha256sum -c" in line)
        assert "curl" in run, "download e verificação em RUN separados deixariam uma camada sem verificação"
        assert run.index("curl") < run.index("sha256sum -c")

    def test_a_falha_do_sha256sum_derruba_o_build(self, dockerfile):
        run = next(line for line in dockerfile if "sha256sum -c" in line)
        trecho = run[run.index("sha256sum -c") :]
        assert not re.match(r"sha256sum -c \S+\s*(\|\||;)", trecho), "sha256sum não pode ter a falha ignorada"


class TestAmbienteDoContainer:
    @pytest.fixture
    def env(self, stages):
        return _env_of(stages[-1])

    def test_offline_ligado(self, env):
        assert env["LAVALINK_OFFLINE"] == "true"

    def test_lavalink_roda_do_diretorio_pre_instalado(self, env):
        assert env["LAVALINK_HOME"] == "/opt/lavalink"

    def test_java_configurado_e_absoluto_e_fica_no_jre_copiado(self, env, stages):
        assert env["LAVALINK_JAVA_PATH"].startswith("/") and env["LAVALINK_JAVA_PATH"].endswith("/bin/java")
        copiados = [line for line in stages[-1] if line.upper().startswith("COPY") and "--from=jre" in line]
        assert any(env["LAVALINK_JAVA_PATH"].startswith(line.split()[-1]) for line in copiados)

    def test_dados_de_execucao_no_volume_data(self, env, stages):
        assert env["EMPIREMUSE_HOME"] == "/data"
        assert any(re.match(r"VOLUME\s+\[\s*\"/data\"\s*\]", line) for line in stages[-1])

    def test_o_lavalink_local_e_ligado_no_container(self, env):
        assert env["RUN_LOCAL_LAVALINK"] == "true"

    def test_expose_somente_6000(self, stages):
        portas = [porta for line in stages[-1] if line.upper().startswith("EXPOSE ") for porta in line.split()[1:]]
        assert portas == ["6000"], f"portas expostas: {portas}"

    def test_nenhum_segredo_em_env_arg_ou_label(self, dockerfile):
        proibido = re.compile(r"(TOKEN|MONGO|SECRET|PASSWORD|API_KEY|REFRESH)", re.I)
        for line in dockerfile:
            if re.match(r"(ENV|ARG|LABEL)\s", line, re.I):
                assert not proibido.search(line), f"nome sensível em instrução de build: {line[:60]}"


class TestHigieneDoBuild:
    def test_codigo_do_bot_e_copiado_por_caminhos_explicitos(self, dockerfile):
        for line in dockerfile:
            if line.upper().startswith("COPY ") and "--from" not in line:
                origem = line.split()[1:-1]
                assert not any(item in (".", "./", "*") for item in origem), f"COPY amplo demais: {line}"

    def test_sem_curl_pipe_shell_e_sem_add_remoto(self, dockerfile):
        for line in dockerfile:
            assert not re.search(r"\|\s*(ba)?sh\b", line), f"download executado direto: {line[:60]}"
            assert not re.match(r"ADD\s+https?://", line, re.I)


class TestCreditosGpl:
    """A GPL-2.0 pede levar a licença e os créditos do upstream junto com o que é distribuído na imagem."""

    @staticmethod
    def _copia_para_app(stage: list[str], arquivo: str) -> bool:
        """True se um COPY do contexto (sem --from) leva ``arquivo`` para /app, direto ou via WORKDIR /app."""
        workdir = "/"
        for line in stage:
            if line.upper().startswith("WORKDIR "):
                workdir = line.split(None, 1)[1].strip()
            elif line.upper().startswith("COPY ") and "--from" not in line:
                *origens, destino = line.split()[1:]
                if arquivo in origens and (destino.startswith("/app") or (workdir == "/app" and destino[0] != "/")):
                    return True
        return False

    @pytest.mark.parametrize("arquivo", ["LICENSE", "CREDITS.md"])
    def test_licenca_e_creditos_vao_para_app_na_imagem_final(self, stages, arquivo):
        assert self._copia_para_app(stages[-1], arquivo), f"o estágio final não copia {arquivo} para /app"

    @pytest.mark.parametrize("arquivo", ["LICENSE", "CREDITS.md"])
    def test_os_arquivos_existem_e_o_dockerignore_nao_os_barra(self, arquivo):
        assert (ROOT / arquivo).is_file()
        texto = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        for linha in texto.splitlines():
            padrao = linha.strip().strip("/")
            if padrao and not padrao.startswith(("#", "!")):
                assert not fnmatch.fnmatch(arquivo, padrao), f".dockerignore ({linha.strip()}) barra {arquivo}"

    @pytest.fixture
    def labels(self, stages) -> dict[str, str]:
        return {
            chave: valor
            for line in stages[-1]
            if line.upper().startswith("LABEL ")
            for chave, valor in re.findall(r'([\w.\-]+)="([^"]*)"', line)
        }

    def test_label_de_autoria_nao_cita_o_upstream(self, labels):
        autores = labels["org.opencontainers.image.authors"]
        assert autores.strip()
        assert not re.search(r"zritsu|museheart", autores, re.I), f"authors cita o upstream: {autores}"

    def test_labels_apontam_para_o_repositorio_a_licenca_e_os_creditos(self, labels):
        assert labels["org.opencontainers.image.source"] == branding.REPO_URL
        assert labels["org.opencontainers.image.licenses"] == "GPL-2.0-only"
        assert labels["org.opencontainers.image.documentation"] == f"{branding.REPO_URL}/blob/main/CREDITS.md"


class TestDockerignore:
    @pytest.fixture
    def padroes(self):
        texto = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        return {linha.strip() for linha in texto.splitlines() if linha.strip() and not linha.strip().startswith("#")}

    @pytest.mark.parametrize(
        "alternativas",
        [
            (".env*",),
            ("config.json",),
            (".git", ".git/"),
            ("local_database", "local_database/"),
            (".local", ".local/"),
            (".arquivo", ".arquivo/"),
            ("repos", "repos/"),
            ("worktrees", "worktrees/"),
        ],
    )
    def test_barra_segredos_e_dados_locais(self, padroes, alternativas):
        assert padroes & set(alternativas), f"falta no .dockerignore: {alternativas[0]}"

    def test_nao_reabre_nada_com_excecao(self, padroes):
        assert not [padrao for padrao in padroes if padrao.startswith("!")], "exceções (!) podem reabrir segredos"

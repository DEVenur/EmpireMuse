"""D-15 — verificações estáticas do docker-compose.yml (só leitura de texto/YAML; sem docker, rede ou .env real).

Especificação (MAESTRO): serviço ``bot`` (build local + imagem parametrizada, ``env_file: .env``, volume nomeado em /data,
endurecimento read_only/tmpfs/no-new-privileges/cap_drop ALL, sem ``init`` porque a imagem já usa tini) e serviço
opcional ``mongo`` (profile ``mongo``, imagem 8.x fixada por digest, sem ports, credenciais só por
``env_file: [{path: .env.mongo, required: true}]``).
Teste principal do aceite: a ÚNICA porta publicada no arquivo inteiro é a do painel (container 8080); nem o Lavalink
(2333/8090) nem o Mongo (27017) são publicados, e nenhum segredo aparece literal.

Por que as credenciais do Mongo NÃO usam ``${VAR:?}`` em ``environment``: o Compose interpola o arquivo inteiro mesmo
com o profile desligado, então quem não usa Mongo (``.env`` sem essas variáveis) não conseguiria subir o bot. O
``env_file`` com ``required: true`` só é lido com o profile ativo e falha cedo se o arquivo faltar. Por isso o arquivo
não pode ter nenhuma interpolação obrigatória (``:?``) e o ``.env.mongo`` precisa estar fora do git e da imagem.
"""

import fnmatch
import re
import subprocess
from pathlib import Path

import pytest
from ruamel.yaml import YAML
from tests.support.raiz import RAIZ

ROOT = RAIZ
COMPOSE = ROOT / "docker-compose.yml"

PORTA_DO_PAINEL = "${EMPIREMUSE_PORT:-8080}:8080"
VOLUME_NOMEADO = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
NOME_SENSIVEL = re.compile(r"(PASS|TOKEN|SECRET|KEY|MONGO|CREDENTIAL|AUTH)", re.I)
INTERPOLACAO = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(:?[-?+][^}]*)?\}$")
TOKEN_DISCORD = re.compile(r"[MNO][A-Za-z\d_-]{23,25}\.[\w-]{6}\.[\w-]{27,}")


# ============================================================================ leitura e normalização


@pytest.fixture(scope="module")
def raw() -> str:
    assert COMPOSE.is_file(), "docker-compose.yml não existe na raiz do repositório"
    return COMPOSE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compose(raw) -> dict:
    dados = YAML(typ="safe").load(raw)  # carregador seguro; chave duplicada levanta erro
    assert isinstance(dados, dict), "o compose precisa ser um mapeamento YAML"
    return dados


@pytest.fixture(scope="module")
def servicos(compose) -> dict:
    return compose["services"]


@pytest.fixture(scope="module")
def bot(servicos) -> dict:
    return servicos["bot"]


@pytest.fixture(scope="module")
def mongo(servicos) -> dict:
    return servicos["mongo"]


def _lista(valor) -> list:
    if valor is None:
        return []
    return list(valor) if isinstance(valor, (list, tuple)) else [valor]


def _volumes(servico: dict) -> list[str]:
    """Volumes em forma curta ``origem:destino[:modo]``; a forma longa é convertida (bind vira ``bind:origem:destino``)."""
    saida = []
    for item in _lista(servico.get("volumes")):
        if isinstance(item, dict):
            prefixo = "bind:" if item.get("type") == "bind" else ""
            saida.append(f"{prefixo}{item.get('source', '')}:{item.get('target', '')}")
        else:
            saida.append(str(item))
    return saida


def _portas(servico: dict) -> list[str]:
    """Portas publicadas em forma curta ``[host_ip:]publicada:container``; a forma longa é convertida."""
    saida = []
    for item in _lista(servico.get("ports")):
        if isinstance(item, dict):
            partes = [item.get("host_ip"), item.get("published"), item.get("target")]
            saida.append(":".join(str(parte) for parte in partes if parte not in (None, "")))
        else:
            saida.append(str(item))
    return saida


def _porta_do_container(porta: str) -> str:
    return porta.rsplit(":", 1)[-1].split("/")[0]


def _env(servico: dict) -> dict[str, str | None]:
    """``environment`` (mapeamento ou lista KEY=VALOR); ``KEY`` sozinha (herdada do ambiente) vira None."""
    bruto = servico.get("environment") or {}
    if isinstance(bruto, dict):
        return {str(k): (None if v is None else str(v)) for k, v in bruto.items()}
    saida = {}
    for item in bruto:
        chave, separador, valor = str(item).partition("=")
        saida[chave] = valor if separador else None
    return saida


def _env_files(servico: dict) -> list[str]:
    return [item["path"] if isinstance(item, dict) else str(item) for item in _lista(servico.get("env_file"))]


def _env_file_entries(servico: dict) -> list:
    """``env_file`` como está no YAML (str ou mapeamento), para conferir a FORMA e o ``required``."""
    return [dict(item) if isinstance(item, dict) else item for item in _lista(servico.get("env_file"))]


def _git(*args: str) -> subprocess.CompletedProcess:
    """git no repositório; se não houver git ou repositório (ex.: árvore exportada), o teste é pulado."""
    try:
        resultado = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git indisponível")
    if resultado.returncode not in (0, 1):
        pytest.skip(f"não é um repositório git ({resultado.stderr.strip()[:80]})")
    return resultado


def _contexto_do_build(servico: dict) -> str:
    build = servico.get("build")
    return str(build.get("context")) if isinstance(build, dict) else str(build)


def _todas_as_strings(no):
    if isinstance(no, dict):
        for chave, valor in no.items():
            yield str(chave)
            yield from _todas_as_strings(valor)
    elif isinstance(no, (list, tuple)):
        for item in no:
            yield from _todas_as_strings(item)
    elif no is not None:
        yield str(no)


# ============================================================================ estrutura


class TestEstrutura:
    def test_o_arquivo_existe_na_raiz_e_e_yaml_valido(self, compose):
        assert "services" in compose

    def test_somente_os_servicos_bot_e_mongo(self, servicos):
        assert set(servicos) == {"bot", "mongo"}, f"serviços: {sorted(servicos)}"

    def test_chaves_de_topo_conhecidas(self, compose):
        permitidas = {"name", "services", "volumes"}
        extras = {chave for chave in compose if chave not in permitidas and not str(chave).startswith("x-")}
        assert not extras, f"chaves de topo inesperadas: {sorted(extras)}"

    def test_volumes_nomeados_declarados_sao_exatamente_dois(self, compose):
        assert set(compose.get("volumes") or {}) == {"empiremuse-data", "empiremuse-mongo"}

    @pytest.mark.parametrize("nome", ["empiremuse-data", "empiremuse-mongo"])
    def test_volume_nomeado_usa_driver_local_sem_bind_escondido(self, compose, nome):
        definicao = (compose["volumes"] or {}).get(nome) or {}
        assert definicao.get("driver", "local") == "local"
        assert "driver_opts" not in definicao, "driver_opts pode transformar o volume nomeado em bind de host"
        assert not definicao.get("external"), "volume externo escaparia da gestão do compose"

    def test_todo_volume_usado_esta_declarado_e_todo_declarado_e_usado(self, compose, servicos):
        usados = set()
        for servico in servicos.values():
            for spec in _volumes(servico):
                origem = spec.split(":")[0]
                if VOLUME_NOMEADO.match(origem):
                    usados.add(origem)
        assert usados == set(compose.get("volumes") or {})


# ============================================================================ serviço bot


class TestServicoBot:
    def test_build_do_diretorio_atual(self, bot):
        assert _contexto_do_build(bot) == "."
        build = bot["build"]
        assert not isinstance(build, dict) or "dockerfile" not in build, "o build deve usar o Dockerfile da raiz"

    def test_imagem_parametrizada_com_padrao_local(self, bot):
        assert bot["image"] == "${EMPIREMUSE_IMAGE:-or4cu1o/empiremuse:local}"

    def test_env_file_e_somente_o_dotenv(self, bot):
        assert _env_files(bot) == [".env"]

    def test_reinicia_a_menos_que_parado(self, bot):
        assert bot["restart"] == "unless-stopped"

    def test_limite_de_memoria_parametrizado(self, bot):
        assert bot["mem_limit"] == "${EMPIREMUSE_MEM_LIMIT:-768m}"

    def test_unico_volume_e_o_nomeado_em_data(self, bot):
        assert _volumes(bot) == ["empiremuse-data:/data"]

    def test_publica_somente_a_porta_do_painel(self, bot):
        assert _portas(bot) == [PORTA_DO_PAINEL]

    def test_sem_init_porque_a_imagem_ja_usa_tini(self, bot):
        assert not bot.get("init"), "init: true duplicaria o tini da imagem"

    def test_sistema_de_arquivos_somente_leitura(self, bot):
        assert bot["read_only"] is True

    def test_tmp_em_tmpfs(self, bot):
        assert _lista(bot.get("tmpfs")) == ["/tmp"]

    def test_sem_novos_privilegios(self, bot):
        assert _lista(bot.get("security_opt")) == ["no-new-privileges:true"]

    def test_todas_as_capabilities_removidas_e_nenhuma_devolvida(self, bot):
        assert _lista(bot.get("cap_drop")) == ["ALL"]
        assert not bot.get("cap_add")

    def test_nao_depende_do_mongo_que_e_opcional(self, bot):
        dependencias = bot.get("depends_on") or []
        nomes = list(dependencias) if isinstance(dependencias, (list, dict)) else [dependencias]
        assert "mongo" not in nomes, "depends_on: mongo quebraria o start sem o profile mongo"


# ============================================================================ serviço mongo


class TestServicoMongo:
    def test_e_opcional_so_no_profile_mongo(self, mongo):
        assert _lista(mongo.get("profiles")) == ["mongo"]

    def test_imagem_8x_fixada_por_digest(self, mongo):
        assert re.fullmatch(r"mongo:8\.\d+(\.\d+)?(-[a-z0-9]+)?@sha256:[0-9a-f]{64}", mongo["image"]), mongo["image"]

    def test_sem_ports(self, mongo):
        assert "ports" not in mongo

    def test_volume_nomeado_em_data_db(self, mongo):
        assert _volumes(mongo) == ["empiremuse-mongo:/data/db"]

    def test_reinicia_a_menos_que_parado(self, mongo):
        assert mongo["restart"] == "unless-stopped"

    def test_credenciais_por_env_file_env_mongo_obrigatorio_na_forma_longa(self, mongo):
        entradas = _env_file_entries(mongo)
        assert entradas == [{"path": ".env.mongo", "required": True}], (
            f"env_file do mongo precisa ser exatamente [{{path: .env.mongo, required: true}}]: {entradas!r}"
        )
        assert entradas[0]["required"] is True, "required precisa ser o booleano true, não texto"

    def test_nao_recebe_o_env_file_do_bot(self, mongo):
        assert ".env" not in _env_files(mongo), "o .env do bot entregaria o TOKEN do Discord ao banco"

    @pytest.mark.parametrize("variavel", ["MONGO_INITDB_ROOT_USERNAME", "MONGO_INITDB_ROOT_PASSWORD"])
    def test_credencial_nao_fica_em_environment(self, mongo, variavel):
        assert variavel not in _env(mongo), f"{variavel} em environment seria interpolada mesmo sem o profile mongo"

    def test_nenhuma_variavel_sensivel_em_environment_do_mongo(self, mongo):
        sensiveis = [chave for chave in _env(mongo) if NOME_SENSIVEL.search(chave)]
        assert not sensiveis, f"credenciais do mongo só pelo .env.mongo: {sensiveis}"

    def test_outras_variaveis_do_mongo_nao_tem_segredo_literal(self, mongo):
        for chave, valor in _env(mongo).items():
            if NOME_SENSIVEL.search(chave) or chave.endswith("USERNAME"):
                assert valor is None or INTERPOLACAO.match(valor), f"{chave} com valor literal"


# ============================================================================ aceite: portas


class TestPortasPublicadas:
    def test_a_unica_porta_publicada_do_arquivo_inteiro_e_a_do_painel(self, servicos):
        publicadas = [(nome, porta) for nome, servico in servicos.items() for porta in _portas(servico)]
        assert publicadas == [("bot", PORTA_DO_PAINEL)], f"portas publicadas: {publicadas}"

    def test_a_porta_do_container_publicada_e_8080(self, servicos):
        containers = {_porta_do_container(porta) for servico in servicos.values() for porta in _portas(servico)}
        assert containers == {"8080"}

    @pytest.mark.parametrize("porta", ["2333", "8090", "27017"])
    def test_lavalink_e_mongo_nunca_aparecem_em_ports_ou_expose(self, servicos, porta):
        for nome, servico in servicos.items():
            alvos = _portas(servico) + [str(item) for item in _lista(servico.get("expose"))]
            assert not [alvo for alvo in alvos if porta in re.split(r"[:/]", alvo)], f"{nome} expõe a porta {porta}"

    def test_o_mongo_nao_expoe_nenhuma_porta(self, mongo):
        assert not _lista(mongo.get("ports")) and not _lista(mongo.get("expose"))

    @pytest.mark.parametrize("chave", ["network_mode", "pid", "ipc", "userns_mode"])
    def test_nenhum_servico_compartilha_o_namespace_do_host(self, servicos, chave):
        for nome, servico in servicos.items():
            assert servico.get(chave) != "host", f"{nome}: {chave}: host publicaria/expor tudo do host"


# ============================================================================ segredos e privilégios


class TestSegredosEPrivilegios:
    def test_nenhum_servico_pede_privilegios_extras(self, servicos):
        for nome, servico in servicos.items():
            assert not servico.get("privileged"), f"{nome}: privileged"
            assert not servico.get("devices"), f"{nome}: devices"
            assert not servico.get("cap_add"), f"{nome}: cap_add"

    def test_nenhum_bind_mount_de_host_nem_docker_sock(self, servicos):
        for nome, servico in servicos.items():
            for spec in _volumes(servico):
                origem = spec.split(":")[0]
                assert VOLUME_NOMEADO.match(origem), f"{nome}: volume que não é nomeado: {spec}"
                assert "docker.sock" not in spec

    def test_variaveis_sensiveis_so_por_interpolacao_nunca_literais(self, servicos):
        for nome, servico in servicos.items():
            for chave, valor in _env(servico).items():
                if NOME_SENSIVEL.search(chave):
                    assert valor is None or INTERPOLACAO.match(valor), f"{nome}: {chave} com valor literal"

    def test_o_bot_nao_repete_segredos_em_environment(self, bot):
        sensiveis = [chave for chave in _env(bot) if NOME_SENSIVEL.search(chave)]
        assert not sensiveis, f"segredos devem vir só do env_file .env: {sensiveis}"

    def test_nenhuma_string_do_arquivo_tem_uri_mongodb_com_senha_literal(self, compose):
        for texto in _todas_as_strings(compose):
            achado = re.search(r"mongodb(\+srv)?://[^/\s:@]+:([^/\s@]+)@", texto)
            assert not achado or achado.group(2).startswith("$"), "URI do Mongo com senha literal"

    def test_nenhum_token_do_discord_no_texto(self, raw):
        assert not TOKEN_DISCORD.search(raw)

    def test_imagem_do_bot_nao_usa_latest(self, bot):
        assert ":latest" not in bot["image"]

    def test_nenhuma_variavel_obrigatoria_no_arquivo_inteiro(self, raw):
        """``${VAR:?}`` / ``${VAR?}`` é interpolado com ou sem o profile: sem a variável, nem o bot sobe."""
        assert ":?" not in raw, "':?' no compose exige a variável mesmo com o profile mongo desligado"
        assert not re.search(r"\$\{[^}]*\?", raw), "'${VAR?...}' também exige a variável"

    def test_nenhuma_interpolacao_obrigatoria_nas_strings_carregadas(self, compose):
        for texto in _todas_as_strings(compose):
            assert not re.search(r"\$\{[^}]*\?", texto), f"variável obrigatória em: {texto[:60]}"


# ============================================================================ .env.mongo fora do git e da imagem


class TestEnvMongoNaoVaza:
    ARQUIVO = ".env.mongo"

    def test_ignorado_pelo_gitignore_do_repositorio(self):
        resultado = _git("check-ignore", "-v", self.ARQUIVO)
        assert resultado.returncode == 0, f"{self.ARQUIVO} NÃO está ignorado pelo git"
        origem = resultado.stdout.split(":", 1)[0]
        assert Path(origem).name == ".gitignore" and not Path(origem).is_absolute(), (
            f"{self.ARQUIVO} só está ignorado por uma regra local/global ({origem}); precisa de um .gitignore versionado"
        )

    def test_nao_esta_versionado(self):
        resultado = _git("ls-files", "--", self.ARQUIVO)
        assert resultado.stdout.strip() == "", f"{self.ARQUIVO} está no índice do git"

    def test_barrado_pelo_dockerignore(self):
        padroes = [
            linha.strip().strip("/")
            for linha in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
            if linha.strip() and not linha.strip().startswith("#")
        ]
        assert [p for p in padroes if not p.startswith("!") and fnmatch.fnmatch(self.ARQUIVO, p)], (
            f"{self.ARQUIVO} não é barrado pelo .dockerignore"
        )
        assert not [p for p in padroes if p.startswith("!") and fnmatch.fnmatch(self.ARQUIVO, p[1:])], (
            f"uma exceção '!' do .dockerignore reabre {self.ARQUIVO}"
        )

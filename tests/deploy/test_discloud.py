"""D-28 — verificações estáticas do deploy na Discloud: ``discloud.config`` e ``.discloudignore`` (só leitura; sem rede,
sem Discloud e sem ``.env`` real).

``discloud.config``: chaves conhecidas e sem repetição, ``TYPE=bot``, ``MAIN=main.py`` (existente), ``RAM=1024`` (plano
pago; o gratuito não é suportado), ``AUTORESTART=true``, avatar da marca e ``VERSION`` latest ou 3.11 (a Discloud não oferece 3.13), sem segredo.

``.discloudignore``: o pacote enviado NÃO leva dados locais, segredos auxiliares (``.env.*``), binários do Lavalink,
testes, docs nem arquivos de container/outras plataformas, mas LEVA o ``.env`` (a Discloud lê o ``.env`` do zip), o
``lavalink.ini`` (nós remotos), o código, os assets, os dados e a licença/créditos (GPL). Não há biblioteca de gitignore
no projeto, então o casamento mínimo (``dir/``, nomes soltos, ``*``/``?``/``[...]``, ``!``) é implementado aqui e
também testado.
"""

import os
import re
from pathlib import Path, PurePosixPath

import pytest

from empiremuse.utils import branding
from tests.support.raiz import RAIZ

ROOT = RAIZ
CONFIG = ROOT / "discloud.config"
IGNORE = ROOT / ".discloudignore"

CHAVES_CONHECIDAS = {"ID", "TYPE", "MAIN", "NAME", "AVATAR", "RAM", "VERSION", "AUTORESTART", "APT", "START", "BUILD"}
CHAVES_OBRIGATORIAS = {"NAME", "AVATAR", "TYPE", "MAIN", "RAM", "AUTORESTART", "VERSION"}
# Na Discloud, Python só oferece "latest" (recomendado) e as versões fixas 3.11, 3.10 e 3.9; "3.13" NÃO é valor válido.
# O código passa a suíte inteira em 3.11, 3.12 e 3.13, então "latest" e "3.11" são seguros.
VERSOES_VALIDAS = {"latest", "3.11"}

# (caminho, é_diretório): tudo isto TEM de ficar fora do zip enviado.
IGNORADOS = [
    ("worktrees", True),
    ("worktrees/feat/x.py", False),
    ("repos", True),
    ("repos/EmpireMuse-LL-binaries/README.md", False),
    (".arquivo", True),
    (".arquivo/velho.txt", False),
    (".local", True),
    (".local/estado.json", False),
    (".venv", True),
    (".venv/bin/python", False),
    (".java", True),
    (".java/Linux-64bit-ELF/bin/java", False),
    (".logs", True),
    (".logs/lavalink/spring.log", False),
    ("tests", True),
    ("tests/test_x.py", False),
    ("docs", True),
    ("docs/guides/discloud.md", False),
    (".git", True),
    (".git/config", False),
    (".claude", True),
    (".claude/settings.json", False),
    (".agents", True),
    (".agents/skills/x.md", False),
    (".maestri", True),
    (".maestri/canvas.json", False),
    ("local_database", True),
    ("local_database/db.json", False),
    ("estado.pkl", False),
    ("empiremuse/cache/sessao.pkl", False),
    (".tempjar", True),
    (".tempjar/undertow-docbase.80/x", False),
    (".ytdl_cache", True),
    (".ytdl_cache/video.json", False),
    ("Lavalink.jar", False),
    ("plugins", True),
    ("plugins/lavalink-2.6.1.jar", False),
    ("application.yml", False),
    ("auto_lavalink.ini", False),
    ("Dockerfile", False),
    ("docker-compose.yml", False),
    ("deploy", True),
    ("deploy/pterodactyl/egg-empiremuse.json", False),
    (".env.mongo", False),
    (".env.bak", False),
    (".env.example", False),
    (".env.producao", False),
    (".env.local", False),
]

# Tudo isto TEM de ir no zip.
ENVIADOS = [
    (".env", False),  # a Discloud lê o .env do zip: ignorá-lo deixaria o bot sem token
    ("lavalink.ini", False),  # nós Lavalink remotos
    ("main.py", False),
    ("requirements.txt", False),
    ("empiremuse", True),
    ("empiremuse/__main__.py", False),
    ("empiremuse/cogs/music.py", False),
    ("empiremuse/utils/music/local_lavalink.py", False),
    ("assets", True),
    ("assets/brand/avatar.png", False),
    ("data", True),
    ("data/lavalink_servers.ini", False),
    ("discloud.config", False),
    ("LICENSE", False),
    ("CREDITS.md", False),
]

# Arquivos da raiz que o pacote precisa levar e que têm de existir no repositório.
RAIZ_OBRIGATORIA = ["main.py", "requirements.txt", "discloud.config", "LICENSE", "CREDITS.md"]


# ============================================================================ casamento estilo gitignore (mínimo)


def _glob_para_regex(glob: str) -> re.Pattern:
    saida, i = "", 0
    while i < len(glob):
        c = glob[i]
        if glob.startswith("**", i):
            saida, i = saida + ".*", i + 2
        elif c == "*":
            saida, i = saida + "[^/]*", i + 1
        elif c == "?":
            saida, i = saida + "[^/]", i + 1
        elif c == "[" and "]" in glob[i + 1 :]:
            fim = glob.index("]", i + 1)
            saida, i = saida + "[" + glob[i + 1 : fim].replace("\\", "\\\\") + "]", fim + 1
        elif c == "\\" and i + 1 < len(glob):
            saida, i = saida + re.escape(glob[i + 1]), i + 2
        else:
            saida, i = saida + re.escape(c), i + 1
    return re.compile(saida)


class _Padrao:
    def __init__(self, linha: str):
        self.negado = linha.startswith("!")
        texto = linha[1:] if self.negado else linha
        self.so_diretorio = texto.endswith("/")
        texto = texto.rstrip("/")
        self.ancorado = "/" in texto
        self.regex = _glob_para_regex(texto.lstrip("/"))

    def casa(self, prefixo: str, e_diretorio: bool) -> bool:
        if self.so_diretorio and not e_diretorio:
            return False
        alvo = prefixo if self.ancorado else prefixo.rsplit("/", 1)[-1]
        return bool(self.regex.fullmatch(alvo))


class Ignore:
    """Subconjunto do .gitignore: o último padrão que casa decide por nível; diretório ignorado ignora tudo abaixo."""

    def __init__(self, texto: str):
        linhas = [linha.rstrip() for linha in texto.splitlines()]
        self.padroes = [_Padrao(linha) for linha in linhas if linha and not linha.startswith("#")]

    def ignora(self, caminho: str, e_diretorio: bool = False) -> bool:
        partes = PurePosixPath(caminho).parts
        for i in range(1, len(partes) + 1):
            prefixo, e_dir = "/".join(partes[:i]), (i < len(partes)) or e_diretorio
            decisao = None
            for padrao in self.padroes:
                if padrao.casa(prefixo, e_dir):
                    decisao = not padrao.negado
            if decisao:
                return True
        return False


# ============================================================================ leitura


@pytest.fixture(scope="module")
def config_bruto() -> str:
    assert CONFIG.is_file(), "discloud.config não existe na raiz"
    # bytes -> texto SEM tradução de quebra de linha (read_text esconderia o CRLF)
    return CONFIG.read_bytes().decode("utf-8")


@pytest.fixture(scope="module")
def linhas_da_config(config_bruto) -> list[tuple[str, str]]:
    """Pares (chave, valor) na ordem do arquivo; comentários e linhas em branco são descartados."""
    pares = []
    for linha in config_bruto.splitlines():
        if linha.strip() and not linha.lstrip().startswith("#"):
            chave, _, valor = linha.partition("=")
            pares.append((chave, valor))
    return pares


@pytest.fixture(scope="module")
def config(linhas_da_config) -> dict[str, str]:
    return dict(linhas_da_config)


@pytest.fixture(scope="module")
def ignore() -> Ignore:
    assert IGNORE.is_file(), ".discloudignore não existe na raiz"
    return Ignore(IGNORE.read_text(encoding="utf-8"))


# ============================================================================ discloud.config


class TestDiscloudConfig:
    def test_formato_chave_igual_valor_sem_espacos_nem_crlf(self, config_bruto):
        assert "\r" not in config_bruto, "CRLF pode quebrar a leitura do discloud.config"
        assert not config_bruto.startswith("\ufeff"), "BOM no início do arquivo"
        for linha in config_bruto.splitlines():
            if linha.strip() and not linha.lstrip().startswith("#"):
                assert re.fullmatch(r"[A-Z_]+=\S.*", linha), f"linha fora do padrão CHAVE=valor: {linha!r}"
                assert linha == linha.strip(), f"espaços nas pontas: {linha!r}"

    def test_so_chaves_conhecidas(self, config):
        desconhecidas = sorted(set(config) - CHAVES_CONHECIDAS)
        assert not desconhecidas, f"chaves desconhecidas do discloud.config: {desconhecidas}"

    def test_sem_chaves_repetidas(self, linhas_da_config):
        chaves = [chave for chave, _ in linhas_da_config]
        repetidas = sorted({chave for chave in chaves if chaves.count(chave) > 1})
        assert not repetidas, f"chaves repetidas: {repetidas}"

    def test_todas_as_chaves_obrigatorias_presentes(self, config):
        assert not CHAVES_OBRIGATORIAS - set(config), f"faltam: {sorted(CHAVES_OBRIGATORIAS - set(config))}"

    def test_nome_nao_vazio(self, config):
        assert config["NAME"].strip()

    def test_tipo_bot(self, config):
        assert config["TYPE"] == "bot"

    def test_main_e_o_main_py_e_o_arquivo_existe(self, config):
        assert config["MAIN"] == "main.py"
        assert (ROOT / config["MAIN"]).is_file()

    def test_ram_1024_plano_pago(self, config):
        assert config["RAM"] == "1024", "o plano gratuito da Discloud não é suportado: RAM precisa ser 1024"

    def test_reinicio_automatico_ligado(self, config):
        assert config["AUTORESTART"] == "true"

    def test_avatar_e_o_da_marca_no_repositorio(self, config):
        assert config["AVATAR"] == branding.ASSETS_BASE_URL + "/brand/avatar.png"

    def test_o_arquivo_do_avatar_existe_e_e_png(self, config):
        relativo = config["AVATAR"].removeprefix(branding.ASSETS_BASE_URL + "/")
        arquivo = ROOT / "assets" / relativo
        assert arquivo.is_file(), f"avatar ausente no repositório: {arquivo.relative_to(ROOT)}"
        assert arquivo.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "o avatar não é um PNG válido"

    def test_versao_do_python(self, config):
        assert config.get("VERSION") in VERSOES_VALIDAS, (
            f"VERSION precisa ser latest ou 3.11: {config.get('VERSION')!r}"
        )

    def test_sem_segredo_no_arquivo(self, config_bruto, config):
        nomes = [chave for chave in config if re.search(r"TOKEN|SECRET|PASSWORD|MONGO|KEY|CREDENTIAL", chave)]
        assert not nomes, f"chave com cara de segredo: {nomes}"
        assert not re.search(r"[MNO][A-Za-z\d_-]{23,25}\.[\w-]{6}\.[\w-]{27,}", config_bruto), "token do Discord"
        assert not re.search(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", config_bruto), "URL com usuário:senha"
        assert not re.search(r"discord(app)?\.com/api/webhooks/", config_bruto), "webhook do Discord"


# ============================================================================ .discloudignore


class TestDiscloudIgnore:
    @pytest.mark.parametrize(("caminho", "e_dir"), IGNORADOS, ids=[c for c, _ in IGNORADOS])
    def test_fica_fora_do_zip(self, ignore, caminho, e_dir):
        assert ignore.ignora(caminho, e_dir), f"{caminho} deveria ser IGNORADO (não ir no zip)"

    @pytest.mark.parametrize(("caminho", "e_dir"), ENVIADOS, ids=[c for c, _ in ENVIADOS])
    def test_vai_no_zip(self, ignore, caminho, e_dir):
        assert not ignore.ignora(caminho, e_dir), f"{caminho} NÃO pode ser ignorado (precisa ir no zip)"

    def test_o_dotenv_nao_e_ignorado_mas_todo_dotenv_ponto_algo_e(self, ignore):
        assert not ignore.ignora(".env")
        assert all(ignore.ignora(nome) for nome in (".env.mongo", ".env.bak", ".env.x", ".env.prod.old"))

    def test_nenhum_arquivo_do_runtime_e_ignorado_por_engano(self, ignore):
        """Percorre empiremuse/, assets/ e data/ de verdade: padrões soltos (plugins/, tests/, *.zip...) não podem comê-los."""
        ignorados = []
        for pasta in ("empiremuse", "assets", "data"):
            for base, diretorios, arquivos in os.walk(ROOT / pasta):
                diretorios[:] = [d for d in diretorios if d != "__pycache__"]
                for arquivo in arquivos:
                    if arquivo.endswith((".pyc", ".pyo", ".pyd")):
                        continue
                    relativo = (Path(base) / arquivo).relative_to(ROOT).as_posix()
                    if ignore.ignora(relativo):
                        ignorados.append(relativo)
        assert not ignorados, f"{len(ignorados)} arquivos do runtime seriam ignorados: {ignorados[:10]}"

    @pytest.mark.parametrize("nome", RAIZ_OBRIGATORIA)
    def test_arquivos_da_raiz_existem_e_vao_no_zip(self, ignore, nome):
        assert (ROOT / nome).is_file(), f"{nome} não existe"
        assert not ignore.ignora(nome)

    def test_nao_ha_excecao_que_reabra_segredos(self):
        negados = [
            linha.strip()
            for linha in IGNORE.read_text(encoding="utf-8").splitlines()
            if linha.strip().startswith("!") and ".env" in linha
        ]
        assert not negados, f"exceção '!' reabre arquivos de ambiente: {negados}"


class TestCasamentoDoTeste:
    """O casamento é uma implementação mínima do próprio teste: estes casos garantem que ele se comporta como o git."""

    def test_diretorio_com_barra_so_casa_diretorio(self):
        ignore = Ignore("build/\n")
        assert ignore.ignora("build", True) and ignore.ignora("build/a.txt")
        assert not ignore.ignora("build", False), "'build/' não casa um ARQUIVO chamado build"

    def test_nome_solto_casa_em_qualquer_profundidade(self):
        ignore = Ignore("plugins/\nLavalink.jar\n")
        assert ignore.ignora("a/b/plugins/x.jar") and ignore.ignora("sub/Lavalink.jar")
        assert not ignore.ignora("a/plugins.py")

    def test_curingas(self):
        ignore = Ignore("*.pkl\n*.py[cod]\n.env.*\n")
        assert ignore.ignora("a/b/c.pkl") and ignore.ignora("m.pyc") and ignore.ignora(".env.x")
        assert not ignore.ignora("m.py") and not ignore.ignora(".env") and not ignore.ignora("env.x")

    def test_negacao_reabre_apenas_o_que_nao_esta_em_diretorio_ignorado(self):
        ignore = Ignore("*.log\n!keep.log\ndir/\n!dir/x.txt\n")
        assert ignore.ignora("a.log") and not ignore.ignora("keep.log")
        assert ignore.ignora("dir/x.txt"), "arquivo dentro de diretório ignorado continua ignorado"

    def test_padrao_ancorado_so_casa_da_raiz(self):
        ignore = Ignore("/build\nsrc/gen\n")
        assert ignore.ignora("build/x") and not ignore.ignora("a/build/x")
        assert ignore.ignora("src/gen/x") and not ignore.ignora("a/src/gen/x")

    def test_comentarios_e_linhas_em_branco_sao_ignorados(self):
        assert not Ignore("# docs/\n\n  \n").ignora("docs/a.md")

    def test_ponto_nao_e_curinga(self):
        assert not Ignore("lavalink.ini\n").ignora("lavalinkXini")
        assert not Ignore("lavalink.ini\n").ignora("lavalink_servers.ini")

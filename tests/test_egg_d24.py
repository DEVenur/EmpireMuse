"""D-24 — verificações estáticas do egg do Pterodactyl (só leitura de JSON/texto; sem rede, docker ou .env real).

Lê apenas ``deploy/pterodactyl/egg-empiremuse.json``, ``.example.env`` (o modelo versionado, nunca o ``.env`` real) e o
código-fonte do bot. Aceite do plano: toda chave ATIVA do ``.example.env`` está mapeada para uma variável do egg ou
consta na lista explícita ``NAO_SE_APLICA`` (com o motivo), nenhum padrão contém segredo, e uma chave nova no
``.example.env`` que não esteja em nenhum dos dois lugares QUEBRA o teste de cobertura.
"""

import json
import re
from pathlib import Path

import pytest

from empiremuse import config_loader

ROOT = Path(__file__).resolve().parent.parent
EGG = ROOT / "deploy" / "pterodactyl" / "egg-empiremuse.json"
EXAMPLE_ENV = ROOT / ".example.env"
PACKAGE = ROOT / "empiremuse"

IMAGENS = {"EmpireMuse 0.1": "or4cu1o/empiremuse:0.1", "EmpireMuse latest": "or4cu1o/empiremuse:latest"}
STARTUP = "python -m empiremuse"

# Ambiente fixo do Pterodactyl, entregue como variável não editável (o startup do egg fica só com o comando).
# O Wings cria o container sem Cmd e sem WorkingDir: o bot muda o cwd para EMPIREMUSE_HOME (o /data da imagem não é
# gravável pelo usuário do nó).
FIXAS = {"EMPIREMUSE_HOME": "/home/container"}

# Variáveis que NÃO podem existir no egg. O Wings entrega o valor das variáveis LITERALMENTE (não interpola
# ``{{SERVER_PORT}}``), e já exporta SERVER_PORT/SERVER_IP/P_SERVER_* por conta própria; o bot usa SERVER_PORT quando
# PORT não existe. Uma variável PORT chegaria ao bot como o texto ``{{SERVER_PORT}}``.
PROIBIDAS_NO_EGG = {"PORT": "o Wings não interpola o default; o bot usa o SERVER_PORT que o próprio Wings exporta"}

# Chaves que vêm do ENV da imagem: uma variável do egg (mesmo vazia) seria exportada pelo Wings e SOBRESCREVERIA o ENV.
DA_IMAGEM = {"LAVALINK_OFFLINE", "LAVALINK_HOME", "LAVALINK_JAVA_PATH"}
LAVALINK_EXPOSTAS = {"RUN_LOCAL_LAVALINK", "LAVALINK_RAM_LIMIT"}

# Chaves ATIVAS do .example.env que NÃO viram variável do egg, cada uma com o motivo. A lista é explícita de propósito:
# se alguém a deixar velha (chave que sumiu do .example.env, ou que virou variável), os testes de coerência quebram.
NAO_SE_APLICA = {
    "LAVALINK_OFFLINE": "vem do ENV da imagem (true): o jar, o yml e os plugins são pré-instalados e verificados",
    "LAVALINK_HOME": "vem do ENV da imagem (/opt/lavalink): variável vazia no egg sobrescreveria o ENV da imagem",
    "LAVALINK_JAVA_PATH": "vem do ENV da imagem (JRE 21 em /opt/java/openjdk): vazia, o bot tentaria instalar um JDK",
    "LAVALINK_FILE_URL": "o Lavalink.jar vem na imagem; em modo offline não há download, então a URL não tem efeito",
    "LAVALINK_FILE_SHA256": "par da LAVALINK_FILE_URL: sem download de jar próprio, o hash não tem uso",
    "USE_JABBA": "instalaria o Java por um script baixado (jabba); a imagem já traz o JRE e roda offline",
    "GIT_DIR": "só serve a comandos de git; o container não tem repositório e a atualização por git foi removida (D1)",
}

SEGREDOS_EXPLICITOS = {
    "TOKEN",
    "MONGO",
    "SPOTIFY_CLIENT_SECRET",
    "LASTFM_KEY",
    "LASTFM_SECRET",
    "PANEL_OAUTH_CLIENT_SECRET",
    "PANEL_COOKIE_SECRET",
    "YOUTUBE_OAUTH_REFRESH_TOKEN",
    "BOT_ADD_REMOVE_LOG",
    "ERROR_REPORT_WEBHOOK",
    "AUTO_ERROR_REPORT_WEBHOOK",
}
# Cuidado com falsos positivos: WEBHOOKS_INTENT e PANEL_INSECURE_COOKIES são booleanos comuns, não segredos.
NOME_DE_SEGREDO = re.compile(r"(TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY|_KEY$|^MONGO$|(^|_)WEBHOOK$)", re.I)
PREFIXOS_DINAMICOS = ("token_bot_", "test_guilds_", "lavalink_node_")  # config_loader.load_config os aceita
RESERVADAS_DO_PTERODACTYL = {"STARTUP", "SERVER_MEMORY", "SERVER_IP", "SERVER_PORT"}

CAMPOS_DA_VARIAVEL = {"name", "description", "env_variable", "default_value", "user_viewable", "user_editable", "rules"}
PALAVRAS_PT = set(
    "de do da dos das para o a os as que em um uma com não nao ou por no na nos nas ao se é mais seu sua ser quando "
    "cada entre antes sem usar e ids id padrão".split()
)
PALAVRAS_EN = set("the of to and is for with your this when that are will can be if or on in".split())


# ============================================================================ leitura


def _sem_chave_duplicada(pares):
    chaves = [chave for chave, _ in pares]
    repetidas = {chave for chave in chaves if chaves.count(chave) > 1}
    assert not repetidas, f"chave JSON duplicada: {sorted(repetidas)}"
    return dict(pares)


@pytest.fixture(scope="module")
def raw() -> str:
    assert EGG.is_file(), "deploy/pterodactyl/egg-empiremuse.json não existe"
    return EGG.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def egg(raw) -> dict:
    dados = json.loads(raw, object_pairs_hook=_sem_chave_duplicada)
    assert isinstance(dados, dict), "o egg precisa ser um objeto JSON"
    return dados


@pytest.fixture(scope="module")
def variaveis(egg) -> list[dict]:
    assert isinstance(egg["variables"], list)
    return egg["variables"]


@pytest.fixture(scope="module")
def por_env(variaveis) -> dict[str, dict]:
    return {variavel["env_variable"]: variavel for variavel in variaveis}


@pytest.fixture(scope="module")
def chaves_ativas() -> dict[str, str]:
    """Chaves NÃO comentadas do .example.env -> valor (sem aspas)."""
    ativas = {}
    for linha in EXAMPLE_ENV.read_text(encoding="utf-8").splitlines():
        achado = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", linha)
        if achado:
            valor = achado.group(2).strip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "'\"":
                valor = valor[1:-1]
            ativas[achado.group(1)] = valor
    assert ativas, ".example.env sem nenhuma chave ativa"
    return ativas


@pytest.fixture(scope="module")
def instalacao(egg) -> dict:
    assert "installation" in egg.get("scripts", {}), "scripts.installation ausente no egg"
    return egg["scripts"]["installation"]


def _e_segredo(env_variable: str) -> bool:
    return env_variable in SEGREDOS_EXPLICITOS or bool(NOME_DE_SEGREDO.search(env_variable))


def _regras(variavel: dict) -> list[str]:
    return variavel["rules"].split("|")


# ============================================================================ formato do egg


class TestFormato:
    def test_arquivo_existe_e_e_json_valido_sem_chave_duplicada(self, egg):
        assert egg

    def test_formato_oficial_ptdl_v2(self, egg):
        assert egg["meta"]["version"] == "PTDL_v2"

    def test_campos_obrigatorios_de_topo(self, egg):
        faltando = {
            "name",
            "author",
            "description",
            "docker_images",
            "startup",
            "config",
            "scripts",
            "variables",
        } - set(egg)
        assert not faltando, f"campos de topo ausentes: {sorted(faltando)}"
        assert isinstance(egg["file_denylist"], list)
        assert egg.get("features") is None or isinstance(egg["features"], list)

    @pytest.mark.parametrize("campo", ["name", "author", "description"])
    def test_textos_de_apresentacao_nao_vazios(self, egg, campo):
        assert isinstance(egg[campo], str) and egg[campo].strip()

    def test_descricao_do_egg_em_pt_br(self, egg):
        assert not _parece_ingles(egg["description"]), egg["description"]

    def test_imagens_docker_exatamente_as_duas_da_especificacao(self, egg):
        assert egg["docker_images"] == IMAGENS

    def test_imagens_sem_digest_e_com_versao_alem_do_latest(self, egg):
        imagens = list(egg["docker_images"].values())
        assert all("@sha256" not in imagem for imagem in imagens), "o egg acompanha correções: sem digest"
        assert any(not imagem.endswith(":latest") for imagem in imagens), "latest não pode ser a única opção"

    def test_comando_de_inicio(self, egg):
        assert egg["startup"] == STARTUP

    def test_config_tem_as_quatro_chaves_em_texto(self, egg):
        config = egg["config"]
        assert set(config) == {"files", "startup", "logs", "stop"}
        assert all(isinstance(valor, str) for valor in config.values())

    @pytest.mark.parametrize("chave", ["files", "startup", "logs"])
    def test_config_em_json_dentro_de_texto(self, egg, chave):
        assert isinstance(json.loads(egg["config"][chave]), dict)

    def test_parada_com_ctrl_c(self, egg):
        assert egg["config"]["stop"] == "^C"

    def test_done_e_uma_linha_que_o_bot_realmente_imprime(self, egg):
        done = json.loads(egg["config"]["startup"]).get("done")
        assert isinstance(done, str) and len(done.strip()) >= 6, f"done curto/genérico demais: {done!r}"
        assert any(done in trecho for trecho in _trechos_impressos()), f"nenhum print/log do bot contém {done!r}"


# ============================================================================ variáveis


class TestVariaveis:
    def test_formato_de_cada_variavel(self, variaveis):
        assert variaveis, "o egg precisa de variáveis"
        for variavel in variaveis:
            nome = variavel.get("env_variable", "?")
            assert CAMPOS_DA_VARIAVEL <= set(variavel), f"{nome}: faltam {sorted(CAMPOS_DA_VARIAVEL - set(variavel))}"
            assert set(variavel) <= CAMPOS_DA_VARIAVEL | {"field_type"}, f"{nome}: campo desconhecido"
            for campo in ("name", "description", "env_variable", "rules"):
                assert isinstance(variavel[campo], str) and variavel[campo].strip(), f"{nome}: {campo} vazio"
            assert isinstance(variavel["default_value"], str), f"{nome}: default_value precisa ser texto ('' se vazio)"
            assert isinstance(variavel["user_viewable"], bool), f"{nome}: user_viewable"
            assert isinstance(variavel["user_editable"], bool), f"{nome}: user_editable"

    def test_nomes_de_ambiente_validos_unicos_e_nao_reservados(self, variaveis):
        nomes = [variavel["env_variable"] for variavel in variaveis]
        assert len(nomes) == len(set(nomes)), "env_variable repetida"
        for nome in nomes:
            assert re.fullmatch(r"[A-Z][A-Z0-9_]*", nome), f"env_variable inválida: {nome}"
            assert nome not in RESERVADAS_DO_PTERODACTYL and not nome.startswith("P_SERVER_"), f"{nome} é reservada"

    def test_nomes_de_exibicao_unicos(self, variaveis):
        nomes = [variavel["name"] for variavel in variaveis]
        assert len(nomes) == len(set(nomes))

    def test_nome_e_descricao_em_pt_br(self, variaveis):
        for variavel in variaveis:
            texto = f"{variavel['name']} {variavel['description']}"
            assert not _parece_ingles(texto), f"{variavel['env_variable']}: texto em inglês: {texto[:70]}"

    def test_todo_env_variable_e_uma_configuracao_real_do_bot(self, variaveis):
        validas = set(config_loader.DEFAULT_CONFIG) | {"TOKEN", "MONGO"} | set(FIXAS)
        for variavel in variaveis:
            nome = variavel["env_variable"]
            assert nome in validas or nome.lower().startswith(PREFIXOS_DINAMICOS), (
                f"{nome} não é lida pelo bot (erro de digitação?)"
            )

    def test_toda_variavel_tem_validador_de_tipo_nas_regras(self, variaveis):
        for variavel in variaveis:
            tipos = [
                regra
                for regra in _regras(variavel)
                if regra in ("string", "integer", "numeric") or regra.startswith("in:")
            ]
            assert tipos, f"{variavel['env_variable']}: rules sem tipo: {variavel['rules']!r}"

    def test_default_vazio_nunca_com_required(self, variaveis):
        """No Pterodactyl, 'required' rejeita valor vazio: um padrão vazio com required impediria criar o servidor."""
        for variavel in variaveis:
            if variavel["default_value"] == "" and variavel["env_variable"] != "TOKEN":
                assert "required" not in _regras(variavel), f"{variavel['env_variable']}: vazio com required"


class TestCoberturaDoExampleEnv:
    def test_toda_chave_ativa_esta_no_egg_ou_na_lista_de_nao_se_aplica(self, chaves_ativas, por_env):
        sem_destino = sorted(set(chaves_ativas) - set(por_env) - set(NAO_SE_APLICA))
        assert not sem_destino, (
            f"chaves ativas do .example.env sem variável no egg e fora de NAO_SE_APLICA: {sem_destino}"
        )

    def test_a_lista_de_nao_se_aplica_nao_esta_velha(self, chaves_ativas, por_env):
        sumiram = sorted(set(NAO_SE_APLICA) - set(chaves_ativas))
        duplicadas = sorted(set(NAO_SE_APLICA) & set(por_env))
        assert not sumiram, f"NAO_SE_APLICA cita chaves que não estão mais ativas no .example.env: {sumiram}"
        assert not duplicadas, f"chaves ao mesmo tempo no egg e em NAO_SE_APLICA: {duplicadas}"

    @pytest.mark.parametrize("chave", sorted(DA_IMAGEM))
    def test_chaves_da_imagem_nao_viram_variavel(self, por_env, chave):
        assert chave not in por_env, f"{chave} no egg sobrescreveria o ENV da imagem"

    @pytest.mark.parametrize("chave", sorted(LAVALINK_EXPOSTAS))
    def test_do_lavalink_o_egg_expoe_run_local_e_ram_limit(self, por_env, chave):
        assert chave in por_env

    def test_ambiente_fixo_do_pterodactyl(self, por_env):
        for chave, valor in FIXAS.items():
            assert chave in por_env, f"falta a variável fixa {chave}"
            assert por_env[chave]["default_value"] == valor
            assert por_env[chave]["user_editable"] is False, f"{chave} não pode ser editável pelo usuário"

    @pytest.mark.parametrize("chave", sorted(PROIBIDAS_NO_EGG))
    def test_variaveis_proibidas_no_egg(self, por_env, chave):
        assert chave not in por_env, f"{chave} não pode ser variável do egg: {PROIBIDAS_NO_EGG[chave]}"

    def test_nenhum_default_value_depende_de_interpolacao_do_painel(self, variaveis):
        """O Wings exporta o default_value como está: '{{...}}' chegaria ao bot como texto literal."""
        com_chaves = [v["env_variable"] for v in variaveis if "{{" in v["default_value"] or "}}" in v["default_value"]]
        assert not com_chaves, f"default_value com interpolação '{{{{...}}}}' (não resolvida pelo Wings): {com_chaves}"


class TestRegrasPorTipo:
    def test_token_obrigatorio_e_texto(self, por_env):
        assert por_env["TOKEN"]["rules"] == "required|string"

    def test_booleanos_aceitam_so_true_ou_false(self, chaves_ativas, por_env):
        achados = [c for c, v in chaves_ativas.items() if v in ("true", "false") and c in por_env]
        assert len(achados) >= 20, "o .example.env deveria ter vários booleanos"
        for chave in achados:
            variavel = por_env[chave]
            assert variavel["rules"] == "required|in:true,false", f"{chave}: rules {variavel['rules']!r}"
            assert variavel["default_value"] in ("true", "false"), f"{chave}: default {variavel['default_value']!r}"

    def test_numeros_usam_integer(self, chaves_ativas, por_env):
        achados = [c for c, v in chaves_ativas.items() if re.fullmatch(r"\d+", v) and c in por_env]
        assert len(achados) >= 15, "o .example.env deveria ter vários inteiros"
        for chave in achados:
            variavel = por_env[chave]
            assert "integer" in _regras(variavel), f"{chave}: rules {variavel['rules']!r}"
            assert re.fullmatch(r"\d+", variavel["default_value"]), f"{chave}: default {variavel['default_value']!r}"


# ============================================================================ segredos


class TestSegredos:
    def test_toda_variavel_de_segredo_tem_padrao_vazio(self, variaveis):
        secretas = [variavel for variavel in variaveis if _e_segredo(variavel["env_variable"])]
        assert {v["env_variable"] for v in secretas} >= {"TOKEN", "MONGO", "SPOTIFY_CLIENT_SECRET", "LASTFM_KEY"}
        for variavel in secretas:
            assert variavel["default_value"] == "", f"{variavel['env_variable']}: segredo com valor padrão"

    @pytest.mark.parametrize("chave", sorted(SEGREDOS_EXPLICITOS))
    def test_cada_segredo_conhecido_que_esta_no_egg_tem_padrao_vazio(self, por_env, chave):
        if chave in por_env:
            assert por_env[chave]["default_value"] == ""

    def test_segredos_opcionais_aceitam_vazio(self, variaveis):
        for variavel in variaveis:
            if _e_segredo(variavel["env_variable"]) and variavel["env_variable"] != "TOKEN":
                assert "required" not in _regras(variavel), (
                    f"{variavel['env_variable']}: opcional não pode ser required"
                )

    def test_nenhum_padrao_do_egg_parece_segredo(self, variaveis):
        for variavel in variaveis:
            valor = variavel["default_value"]
            assert not _PADROES_DE_SEGREDO.search(valor), f"{variavel['env_variable']}: padrão com cara de segredo"
            assert not _URL_COM_CREDENCIAL.search(valor), f"{variavel['env_variable']}: URL com credencial no padrão"

    def test_json_inteiro_sem_segredo_nem_url_com_credencial(self, raw):
        assert not _PADROES_DE_SEGREDO.search(raw), "texto com cara de token/chave no egg"
        assert not _URL_COM_CREDENCIAL.search(raw), "URL com usuário:senha no egg"


# ============================================================================ instalação


class TestInstalacao:
    def test_container_do_instalador_com_versao_fixa(self, instalacao):
        imagem = instalacao["container"]
        assert isinstance(imagem, str) and ":" in imagem, f"instalador sem tag: {imagem!r}"
        assert not imagem.endswith((":latest", ":alpine", ":debian", ":stable")), f"tag flutuante: {imagem}"
        assert re.search(r":\d+(\.\d+)*(-[\w.]+)?$", imagem) or re.search(r"@sha256:[0-9a-f]{64}$", imagem), (
            f"o instalador precisa de versão numérica ou digest: {imagem}"
        )

    def test_entrypoint_do_instalador(self, instalacao):
        assert instalacao["entrypoint"] in ("sh", "ash", "bash")

    def test_script_em_sh_com_shebang_e_set_eu(self, instalacao):
        linhas = [linha.strip() for linha in instalacao["script"].splitlines() if linha.strip()]
        assert re.fullmatch(r"#!/bin/(sh|ash|bash)", linhas[0]), f"1ª linha: {linhas[0]!r}"
        assert re.search(r"^set -eu\b", instalacao["script"], re.M), "falta 'set -eu'"

    def test_script_curto(self, instalacao):
        linhas = [
            linha for linha in instalacao["script"].splitlines() if linha.strip() and not linha.strip().startswith("#")
        ]
        assert len(linhas) <= 25, f"script com {len(linhas)} linhas úteis: o instalador só prepara pastas"

    def test_script_prepara_pastas_em_mnt_server(self, instalacao):
        script = instalacao["script"]
        assert "/mnt/server" in script and re.search(r"\bmkdir\b", script)

    def test_script_so_toca_caminhos_dentro_de_mnt_server(self, instalacao):
        corpo = "\n".join(instalacao["script"].splitlines()[1:])  # sem o shebang
        fora = [
            caminho
            for caminho in re.findall(r"(?<![\w$.{])/[\w./{}$-]+", corpo)
            if not caminho.startswith("/mnt/server") and caminho != "/dev/null"
        ]
        assert not fora, f"caminhos fora de /mnt/server: {fora}"

    @pytest.mark.parametrize(
        "proibido",
        [
            r"\bcurl\b",
            r"\bwget\b",
            r"\bgit\b",
            r"\bapk\b",
            r"\bapt(-get)?\b",
            r"\bpip3?\b",
            r"\bnpm\b",
            r"\bdocker\b",
            r"https?://",
            r"\|\s*(ba|a)?sh\b",
            r"\beval\b",
            r"\bchmod\s+(-R\s+)?0?777\b",
            r"\bsudo\b",
        ],
        ids=[
            "curl",
            "wget",
            "git",
            "apk",
            "apt",
            "pip",
            "npm",
            "docker",
            "url",
            "pipe-para-shell",
            "eval",
            "chmod-777",
            "sudo",
        ],
    )
    def test_script_nao_baixa_nem_instala_nada(self, instalacao, proibido):
        assert not re.search(proibido, instalacao["script"]), f"o script não pode usar {proibido}"

    def test_script_nao_imprime_o_ambiente(self, instalacao):
        assert not re.search(r"\bprintenv\b|(^|[;&|]\s*)env(\s|$)|\bset\s+-\w*x", instalacao["script"], re.M)


# ============================================================================ auxiliares dos testes


_PADROES_DE_SEGREDO = re.compile(
    r"([MNO][A-Za-z\d_-]{23,25}\.[\w-]{6}\.[\w-]{27,})"  # token do Discord
    r"|(discord(app)?\.com/api/webhooks/)"
    r"|(gh[pousr]_[A-Za-z0-9]{20,})|(AKIA[0-9A-Z]{16})|(eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,})"
    r"|(-----BEGIN [A-Z ]*PRIVATE KEY-----)|(Bearer\s+[\w.-]{16,})|(sk-[A-Za-z0-9]{20,})"
)
_URL_COM_CREDENCIAL = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@\"]+:[^/\s@\"]+@", re.I)


def _parece_ingles(texto: str) -> bool:
    """Só reprova texto claramente em inglês: ao menos 2 palavras funcionais inglesas e nenhuma marca de português."""
    palavras = re.findall(r"[a-zà-ú]+", texto.lower())
    ingles = [palavra for palavra in palavras if palavra in PALAVRAS_EN]
    portugues = [palavra for palavra in palavras if palavra in PALAVRAS_PT]
    acentuado = bool(re.search(r"[à-úç]", texto.lower()))
    return len(ingles) >= 2 and not portugues and not acentuado


def _trechos_impressos() -> list[str]:
    """Trechos ESTÁTICOS (fora de ``{...}`` de f-strings) dos literais de ``print(``/``logger.*(`` do pacote do bot."""
    trechos = []
    for arquivo in PACKAGE.rglob("*.py"):
        for linha in arquivo.read_text(encoding="utf-8", errors="replace").splitlines():
            if not re.search(r"\b(print|logger\.\w+|logging\.\w+)\(", linha):
                continue
            for literal in re.findall(r"""f?(?:"([^"\\]*(?:\\.[^"\\]*)*)"|'([^'\\]*(?:\\.[^'\\]*)*)')""", linha):
                texto = literal[0] or literal[1]
                trechos.extend(re.split(r"\{[^{}]*\}", texto))
    return trechos

"""F3-6 — KI-33: ``BotPool.setup`` extrai a URL do remote da saída de ``git remote -v`` por fatiamento fixo.

Hoje o código faz ``.split("\\n")[0][7:].replace(".git", "").replace(" (fetch)", "")``: assume que a 1ª linha é do remote
``origin`` (7 caracteres: ``origin\\t``), arranca TODA ocorrência de ``.git`` (inclusive o de ``.github``), não entende o
formato ssh e deixa credenciais na URL. Esperado: *parsing* por campos (nome, URL, tipo), preferindo o remote ``origin``
e senão o 1º remote de ``fetch``, devolvendo a URL WEB do repositório (a que vira ``<url>/commit/<sha>``): sem o sufixo
``.git``, em https, sem usuário/senha nem porta, e sem barra final. Saída vazia, ilegível ou de remote local cai na
configuração ``SOURCE_REPO``, sem erro.

A função está dentro de ``BotPool.setup`` (não é testável isolada sem mexer em produção), então o teste roda o ``setup``
REAL como em ``test_f3_config_pool`` (BotCore dublado, sem Java, sem rede) e troca ``client.check_output`` por um dublê
que devolve a saída pronta: o ``git`` de verdade nunca roda.
"""

import asyncio
import subprocess
from unittest.mock import AsyncMock, MagicMock

import pytest

from empiremuse.utils import client
from empiremuse.utils.client import BotPool

TOKEN_FALSO = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAx.GabcDE.abcdefghijklmnopqrstuvwxyz1"  # só o formato; não é um token real
SHA = "0123456789abcdef0123456789abcdef01234567"
FALLBACK = "https://exemplo.invalid/fallback/Repo"  # SOURCE_REPO do teste: nunca igual ao repositório dos casos


@pytest.fixture
def pool(monkeypatch, tmp_path):
    """``BotPool.setup`` real, com BotCore dublado e o loop principal neutralizado (como em test_f3_config_pool)."""
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(home))
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("RUN_LOCAL_LAVALINK", "false")
    monkeypatch.setenv("RUN_RPC_SERVER", "false")
    monkeypatch.setenv("SOURCE_REPO", FALLBACK + ".git")  # diferente do repositório dos casos: o oráculo do fallback
    monkeypatch.setenv("TOKEN", TOKEN_FALSO)
    pool = BotPool()

    def bot_falso(**kwargs):
        bot = MagicMock(identifier=kwargs["identifier"])
        bot.loop.create_task.side_effect = lambda corotina: corotina.close()
        return bot

    monkeypatch.setattr(client, "BotCore", bot_falso)
    for nome in ("run_bots", "setup_pool_extras", "cache_updater", "connect_rpc_ws"):
        setattr(pool, nome, AsyncMock())
    pool.node_check = MagicMock()
    pool.start_lavalink = AsyncMock()
    yield pool
    if pool.loop is not None and not pool.loop.is_closed():
        pool.loop.run_until_complete(asyncio.sleep(0))
        pool.loop.close()
    asyncio.set_event_loop(None)


def com_saida_do_git(monkeypatch, pool, saida):
    """Dublê de ``check_output``: ``saida`` é o texto de ``git remote -v`` (ou uma exceção a levantar)."""
    chamadas = []

    def falso(comando, *args, **kwargs):
        chamadas.append(list(comando))
        if comando[:2] == ["git", "rev-parse"]:
            return SHA.encode()
        if comando[:3] == ["git", "remote", "-v"]:
            if isinstance(saida, BaseException):
                raise saida
            return saida.encode()
        raise AssertionError(f"comando inesperado no setup: {comando}")

    monkeypatch.setattr(client, "check_output", falso)
    pool.setup()
    assert ["git", "remote", "-v"] in chamadas, "o setup deveria consultar o remote"
    return pool.remote_git_url


def remote(nome, url, *, push=True):
    linhas = [f"{nome}\t{url} (fetch)"]
    if push:
        linhas.append(f"{nome}\t{url} (push)")
    return "\n".join(linhas) + "\n"


WEB = "https://github.com/DiscordEmpireHub/EmpireMuse"


class TestGuardaDoFormatoAtual:
    """GUARDA: o caso que já funciona (remote ``origin`` em https com ``.git``) não pode regredir."""

    def test_origin_https_com_sufixo_git(self, monkeypatch, pool):
        assert com_saida_do_git(monkeypatch, pool, remote("origin", f"{WEB}.git")) == WEB

    def test_origin_https_sem_sufixo_git(self, monkeypatch, pool):
        assert com_saida_do_git(monkeypatch, pool, remote("origin", WEB)) == WEB

    def test_nunca_roda_o_git_de_verdade(self, monkeypatch, pool):
        def real(*args, **kwargs):
            raise AssertionError("subprocess real")

        monkeypatch.setattr(subprocess, "Popen", real)
        assert com_saida_do_git(monkeypatch, pool, remote("origin", WEB)) == WEB


class TestRemoteComOutroNome:
    def test_unico_remote_chamado_upstream(self, monkeypatch, pool):
        assert com_saida_do_git(monkeypatch, pool, remote("upstream", f"{WEB}.git")) == WEB

    @pytest.mark.parametrize("nome", ["fork", "gitlab-espelho", "o", "um_nome_bem_longo_de_remote"])
    def test_o_tamanho_do_nome_do_remote_nao_importa(self, monkeypatch, pool, nome):
        """O fatiamento fixo ``[7:]`` só acerta quando o nome tem exatamente 6 caracteres (``origin``)."""
        assert com_saida_do_git(monkeypatch, pool, remote(nome, f"{WEB}.git")) == WEB

    def test_prefere_o_origin_mesmo_que_nao_seja_o_primeiro(self, monkeypatch, pool):
        saida = remote("fork", "https://github.com/alguem/Fork.git") + remote("origin", f"{WEB}.git")
        assert com_saida_do_git(monkeypatch, pool, saida) == WEB

    def test_sem_origin_usa_o_primeiro_remote(self, monkeypatch, pool):
        saida = remote("beta", "https://github.com/org/Beta.git") + remote("alfa", "https://github.com/org/Alfa.git")
        assert com_saida_do_git(monkeypatch, pool, saida) == "https://github.com/org/Beta"

    def test_so_as_linhas_de_fetch_valem_e_a_ordem_de_fetch_e_push_nao_importa(self, monkeypatch, pool):
        saida = f"origin\t{WEB}.git (push)\norigin\t{WEB}.git (fetch)\n"
        assert com_saida_do_git(monkeypatch, pool, saida) == WEB

    def test_remote_so_com_push_cai_no_padrao(self, monkeypatch, pool):
        saida = f"origin\t{WEB}.git (push)\n"
        esperado = pool.config["SOURCE_REPO"].removesuffix(".git")
        assert com_saida_do_git(monkeypatch, pool, saida) == esperado

    def test_separador_por_espacos_em_vez_de_tabulacao(self, monkeypatch, pool):
        assert com_saida_do_git(monkeypatch, pool, f"origin   {WEB}.git (fetch)\n") == WEB


class TestFormatosDeUrl:
    @pytest.mark.parametrize(
        ("url", "esperado"),
        [
            ("git@github.com:DiscordEmpireHub/EmpireMuse.git", WEB),
            ("git@github.com:DiscordEmpireHub/EmpireMuse", WEB),
            ("ssh://git@github.com/DiscordEmpireHub/EmpireMuse.git", WEB),
            ("ssh://git@github.com:22/DiscordEmpireHub/EmpireMuse.git", WEB),
            ("git@gitlab.com:grupo/sub/projeto.git", "https://gitlab.com/grupo/sub/projeto"),
            ("git://github.com/DiscordEmpireHub/EmpireMuse.git", WEB),
        ],
        ids=["scp_com_git", "scp_sem_git", "ssh_url", "ssh_com_porta", "gitlab_subgrupo", "protocolo_git"],
    )
    def test_formatos_ssh_viram_a_url_web_https(self, monkeypatch, pool, url, esperado):
        assert com_saida_do_git(monkeypatch, pool, remote("origin", url)) == esperado

    def test_so_o_sufixo_git_e_removido_nao_o_que_aparece_no_meio(self, monkeypatch, pool):
        """``.replace(".git", "")`` mutilava ``.github`` e qualquer ``.git`` no meio do caminho."""
        url = "https://github.com/org/org.github.io.git"
        assert com_saida_do_git(monkeypatch, pool, remote("origin", url)) == "https://github.com/org/org.github.io"

    def test_repositorio_chamado_dot_github_sem_sufixo_git(self, monkeypatch, pool):
        url = "https://github.com/org/.github"
        assert com_saida_do_git(monkeypatch, pool, remote("origin", url)) == url

    @pytest.mark.parametrize(
        "url",
        [
            "https://usuario:ghp_segredo123@github.com/DiscordEmpireHub/EmpireMuse.git",
            "https://token@github.com/DiscordEmpireHub/EmpireMuse.git",
        ],
        ids=["usuario_e_senha", "so_token"],
    )
    def test_credenciais_na_url_nao_vazam_para_o_link_do_commit(self, monkeypatch, pool, url):
        resultado = com_saida_do_git(monkeypatch, pool, remote("origin", url))
        assert resultado == WEB
        assert "@" not in resultado and "segredo" not in resultado and "token" not in resultado

    @pytest.mark.parametrize("url", [f"{WEB}/", f"{WEB}.git/", f"{WEB}//"], ids=["barra", "git_barra", "duas_barras"])
    def test_barra_final_e_removida(self, monkeypatch, pool, url):
        assert com_saida_do_git(monkeypatch, pool, remote("origin", url)) == WEB

    def test_url_com_porta_http_e_mantida_so_sem_credenciais(self, monkeypatch, pool):
        url = "https://git.exemplo.invalid:8443/equipe/projeto.git"
        assert (
            com_saida_do_git(monkeypatch, pool, remote("origin", url))
            == "https://git.exemplo.invalid:8443/equipe/projeto"
        )

    @pytest.mark.parametrize(
        ("url", "esperado"),
        [
            ("http://git.exemplo.invalid/equipe/projeto.git", "http://git.exemplo.invalid/equipe/projeto"),
            ("https://[::1]:8443/equipe/projeto.git", "https://[::1]:8443/equipe/projeto"),
            ("ssh://git@[2001:db8::1]/equipe/projeto.git", "https://[2001:db8::1]/equipe/projeto"),
            ("github.com:DiscordEmpireHub/EmpireMuse.git", WEB),
            ("git+ssh://git@github.com/DiscordEmpireHub/EmpireMuse.git", WEB),
        ],
        ids=["http_mantido", "ipv6_http_com_porta", "ipv6_ssh", "scp_sem_usuario", "git_mais_ssh"],
    )
    def test_outras_formas_de_endereco(self, monkeypatch, pool, url, esperado):
        assert com_saida_do_git(monkeypatch, pool, remote("origin", url)) == esperado

    @pytest.mark.parametrize("saida", [f"  origin\t{WEB}.git (fetch)\n", f"origin\t{WEB}.git (fetch)\r\n"], ids=repr)
    def test_espacos_e_quebra_de_linha_do_windows_nas_pontas_da_linha(self, monkeypatch, pool, saida):
        assert com_saida_do_git(monkeypatch, pool, saida) == WEB


class TestSaidaSemRemoteUtil:
    """Vazia, ilegível, remote local ou falha do git: cai em ``SOURCE_REPO`` sem levantar erro."""

    @pytest.mark.parametrize(
        "saida",
        [
            "",
            "\n",
            "   \n\n",
            "fatal: not a git repository (or any of the parent directories): .git\n",
            "origin\n",
            "origin (fetch)\n",
            "origin\t(fetch)\n",
            "esta linha não tem formato nenhum\n",
            "origin\t/srv/git/projeto.git (fetch)\n",
            "origin\t../projeto (fetch)\n",
            "origin\tfile:///srv/git/projeto.git (fetch)\n",
            "origin\thttps://exemplo.invalid (fetch)\n",
            "origin\thttps://exemplo.invalid/ (fetch)\n",
            "origin\tgit@github.com: (fetch)\n",
            "origin\thttps://[::1/projeto (fetch)\n",
            "origin\tftp://exemplo.invalid/org/projeto.git (fetch)\n",
        ],
        ids=lambda saida: repr(saida)[:40],
    )
    def test_cai_na_configuracao_sem_erro(self, monkeypatch, pool, saida):
        esperado = pool.config["SOURCE_REPO"].removesuffix(".git")
        assert com_saida_do_git(monkeypatch, pool, saida) == esperado

    @pytest.mark.parametrize(
        "erro",
        [FileNotFoundError("git"), subprocess.CalledProcessError(128, ["git", "remote", "-v"])],
        ids=["git_ausente", "codigo_128"],
    )
    def test_guarda_falha_ao_rodar_o_git_cai_na_configuracao(self, monkeypatch, pool, erro):
        esperado = pool.config["SOURCE_REPO"].removesuffix(".git")
        assert com_saida_do_git(monkeypatch, pool, erro) == esperado

    def test_saida_nao_utf8_nao_derruba_o_setup(self, monkeypatch, pool):
        """O código atual decodifica como ascii; um remote com acento não pode quebrar o setup."""
        chamadas = []

        def falso(comando, *args, **kwargs):
            chamadas.append(comando)
            if comando[:2] == ["git", "rev-parse"]:
                return SHA.encode()
            return "origin\thttps://github.com/org/Repositório.git (fetch)\n".encode("utf-8")

        monkeypatch.setattr(client, "check_output", falso)
        pool.setup()
        assert pool.remote_git_url in {
            "https://github.com/org/Repositório",
            pool.config["SOURCE_REPO"].removesuffix(".git"),
        }

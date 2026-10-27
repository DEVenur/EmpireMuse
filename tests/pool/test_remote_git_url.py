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
from tests.support.laco_do_pool import encerrar_laco

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
    encerrar_laco(
        pool.loop
    )  # cancela o que o setup deixou (logs_task, version_check_task, dublês) antes de fechar o laço
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


WEB = "https://github.com/EmpireCommunity/EmpireMuse"


class TestGuardaDoFormatoAtual:
    """GUARDA: o caso que já funciona (remote ``origin`` em https com ``.git``) não pode regredir."""

    @pytest.mark.smoke
    def test_origin_https_sem_sufixo_git(self, monkeypatch, pool):
        assert com_saida_do_git(monkeypatch, pool, remote("origin", WEB)) == WEB


class TestRemoteComOutroNome:
    def test_prefere_o_origin_mesmo_que_nao_seja_o_primeiro(self, monkeypatch, pool):
        saida = remote("fork", "https://github.com/alguem/Fork.git") + remote("origin", f"{WEB}.git")
        assert com_saida_do_git(monkeypatch, pool, saida) == WEB

    def test_separador_por_espacos_em_vez_de_tabulacao(self, monkeypatch, pool):
        assert com_saida_do_git(monkeypatch, pool, f"origin   {WEB}.git (fetch)\n") == WEB


class TestFormatosDeUrl:
    @pytest.mark.parametrize(
        ("url", "esperado"),
        [
            ("git@github.com:EmpireCommunity/EmpireMuse.git", WEB),
            ("git://github.com/EmpireCommunity/EmpireMuse.git", WEB),
        ],
        ids=["scp_com_git", "protocolo_git"],
    )
    def test_formatos_ssh_viram_a_url_web_https(self, monkeypatch, pool, url, esperado):
        assert com_saida_do_git(monkeypatch, pool, remote("origin", url)) == esperado

    @pytest.mark.parametrize(
        "url",
        [
            "https://usuario:ghp_segredo123@github.com/EmpireCommunity/EmpireMuse.git",
            "https://token@github.com/EmpireCommunity/EmpireMuse.git",
        ],
        ids=["usuario_e_senha", "so_token"],
    )
    def test_credenciais_na_url_nao_vazam_para_o_link_do_commit(self, monkeypatch, pool, url):
        resultado = com_saida_do_git(monkeypatch, pool, remote("origin", url))
        assert resultado == WEB
        assert "@" not in resultado and "segredo" not in resultado and "token" not in resultado

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
            "origin\tgit@github.com:/ (fetch)\n",
            "origin\tgit@github.com:.git (fetch)\n",
            "origin\thttps://[::1/projeto (fetch)\n",
            "origin\tftp://exemplo.invalid/org/projeto.git (fetch)\n",
        ],
        ids=lambda saida: repr(saida)[:40],
    )
    def test_cai_na_configuracao_sem_erro(self, monkeypatch, pool, saida):
        esperado = pool.config["SOURCE_REPO"].removesuffix(".git")
        assert com_saida_do_git(monkeypatch, pool, saida) == esperado


class TestGitSemRuidoNoConsole:
    """Fora de um repositório (modo .runtime) o git escreveria "fatal: not a git repository" no stderr do bot."""

    def test_as_duas_consultas_ao_git_descartam_o_stderr(self, monkeypatch, pool):
        stderrs = {}

        def falso(comando, *args, **kwargs):
            stderrs[tuple(comando[:2])] = kwargs.get("stderr")
            raise subprocess.CalledProcessError(128, comando)

        monkeypatch.setattr(client, "check_output", falso)
        pool.setup()

        assert stderrs == {("git", "rev-parse"): subprocess.DEVNULL, ("git", "remote"): subprocess.DEVNULL}

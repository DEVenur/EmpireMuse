"""Teste do dono em produção 2.1.1, partes C2 e D (o "sobre" e o ``/lastfm``) — RAM do sistema, contadores com ponto e versão do EmpireMuse.

VC1 o "sobre" diz "processo Java inteiro" e mostra o RSS em MiB; VD1 nenhum contador sai com vírgula de milhar (nem no "sobre" nem no ``/lastfm``);
VD2 a linha "Versão do EmpireMuse" depende de ``EMPIREMUSE_VERSION`` (versão → link da tag; ``dev`` → ``dev``; ausente → sem linha). Sem Discord e sem
processo de verdade: ``psutil``, bots, usuários e a consulta do last.fm são dublês.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import empiremuse.cogs.misc as misc
from empiremuse.utils import branding

pytestmark = pytest.mark.critical

RSS_PYTHON = 130_023_424  # 124,0 MiB
RSS_LAVALINK = 126_353_408  # 120,5 MiB
USUARIOS = 1035
SERVIDORES = 2345


# ============================================================================ o "sobre"


class ProcessoFalso:
    rss_por_pid = {111: RSS_PYTHON, 222: RSS_LAVALINK}

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def memory_info(self) -> SimpleNamespace:
        return SimpleNamespace(rss=self.rss_por_pid[self.pid])


def membros(quantidade: int, *, base: int = 1_000) -> list:
    return [SimpleNamespace(id=base + i, bot=False) for i in range(quantidade)]


def bot_do_sobre(*, usuarios: int = USUARIOS, servidores: int = SERVIDORES) -> SimpleNamespace:
    dono = SimpleNamespace(
        id=5, avatar=SimpleNamespace(with_static_format=lambda f: SimpleNamespace(url="https://exemplo.invalid/o.png"))
    )
    bot = SimpleNamespace(
        guilds=[SimpleNamespace(id=i) for i in range(servidores)],
        users=membros(usuarios),
        user=SimpleNamespace(id=7),
        music=SimpleNamespace(nodes={}, players={}),
        appinfo=SimpleNamespace(bot_public=True, team=SimpleNamespace(owner=dono), owner=dono),
        get_color=lambda *a: 0,
        get_guild=lambda _: None,
        latency=0.05,
        uptime=misc.disnake.utils.utcnow(),
        config={"INTERACTION_COMMAND_ONLY": True, "SUPPORT_SERVER": ""},
        pool=None,
        is_owner=AsyncMock(return_value=False),
    )
    bot.pool = SimpleNamespace(
        get_all_bots=lambda: [bot],
        bots=[bot],
        lavalink_instance=SimpleNamespace(pid=222),
        commit="",
        remote_git_url="https://exemplo.invalid/repo",
    )
    return bot


class InteracaoDoSobre:
    def __init__(self) -> None:
        self.guild_id = 31
        self.guild = SimpleNamespace(me=SimpleNamespace())
        self.author = SimpleNamespace(id=900)
        self.response = SimpleNamespace(defer=AsyncMock())
        self.embeds = []

    async def edit_original_message(self, **kwargs: object) -> None:
        self.embeds.append(kwargs["embed"])


async def descricao_do_sobre(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bot: SimpleNamespace | None = None,
    versao: str | None = None,
    com_lavalink: bool = True,
) -> str:
    bot = bot or bot_do_sobre()
    if not com_lavalink:
        bot.pool.lavalink_instance = None
    inter = InteracaoDoSobre()

    async def escolher(interaction: InteracaoDoSobre, **kwargs: object) -> tuple[InteracaoDoSobre, SimpleNamespace]:
        return interaction, bot

    monkeypatch.setattr(misc, "select_bot_pool", escolher)
    monkeypatch.setattr(misc, "psutil", SimpleNamespace(Process=ProcessoFalso))
    monkeypatch.setattr(misc, "getpid", lambda: 111)
    if versao is None:
        monkeypatch.delenv("EMPIREMUSE_VERSION", raising=False)
    else:
        monkeypatch.setenv("EMPIREMUSE_VERSION", versao)
    bot.loop = MagicMock()
    bot.loop.create_task.side_effect = lambda corotina: corotina.close()
    cog = misc.Misc(bot)
    await misc.Misc.about.callback(self=cog, interaction=inter)
    return inter.embeds[0].description


class TestRamNoSobre:
    @pytest.mark.asyncio
    async def test_the_labels_name_the_process_and_the_sizes_are_in_mib(self, monkeypatch: pytest.MonkeyPatch) -> None:
        descricao = await descricao_do_sobre(monkeypatch)

        assert "RAM do bot (processo Python)" in descricao and "`124,0 MiB`" in descricao
        assert "RAM do Lavalink (processo Java inteiro)" in descricao and "`120,5 MiB`" in descricao
        assert "RAM total (bot + Lavalink)" in descricao and "`244,5 MiB`" in descricao


class TestContadoresDoSobre:
    @pytest.mark.asyncio
    async def test_the_counters_use_a_dot_for_thousands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        descricao = await descricao_do_sobre(monkeypatch)

        assert "`1.035`" in descricao and "`2.345`" in descricao


class TestVersaoNoSobre:
    @pytest.mark.asyncio
    async def test_with_a_version_it_links_the_release_tag_just_before_python(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        descricao = await descricao_do_sobre(monkeypatch, versao="2.1.1")

        linhas = descricao.splitlines()
        (posicao,) = [i for i, x in enumerate(linhas) if "Versão do EmpireMuse" in x]
        assert "2.1.1" in linhas[posicao] and f"{branding.REPO_URL}/releases/tag/v2.1.1" in linhas[posicao]
        assert "Versão do Python" in linhas[posicao + 1]

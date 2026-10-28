"""Teste do dono em produção 2.1.1, partes C2 e D (o "sobre" e o ``/lastfm``) — RAM do sistema, contadores com ponto e versão do EmpireMuse.

VC1 o "sobre" diz "processo Java inteiro" e mostra o RSS em MiB; VD1 nenhum contador sai com vírgula de milhar (nem no "sobre" nem no ``/lastfm``);
VD2 a linha "Versão do EmpireMuse" depende de ``EMPIREMUSE_VERSION`` (versão → link da tag; ``dev`` → ``dev``; ausente → sem linha). Sem Discord e sem
processo de verdade: ``psutil``, bots, usuários e a consulta do last.fm são dublês.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import empiremuse.cogs.lastfm as lastfm
import empiremuse.cogs.misc as misc
from empiremuse.utils import branding

pytestmark = pytest.mark.critical

MIB = 1 << 20
RSS_PYTHON = 130_023_424  # 124,0 MiB
RSS_LAVALINK = 126_353_408  # 120,5 MiB
USUARIOS = 1035
SERVIDORES = 2345


# ============================================================================ o "sobre"


class ProcessoFalso:
    rss_por_pid = {111: RSS_PYTHON, 222: RSS_LAVALINK}

    def __init__(self, pid):
        self.pid = pid

    def memory_info(self):
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
    def __init__(self):
        self.guild_id = 31
        self.guild = SimpleNamespace(me=SimpleNamespace())
        self.author = SimpleNamespace(id=900)
        self.response = SimpleNamespace(defer=AsyncMock())
        self.embeds = []

    async def edit_original_message(self, **kwargs):
        self.embeds.append(kwargs["embed"])


async def descricao_do_sobre(monkeypatch, *, bot=None, versao=None, com_lavalink: bool = True) -> str:
    bot = bot or bot_do_sobre()
    if not com_lavalink:
        bot.pool.lavalink_instance = None
    inter = InteracaoDoSobre()

    async def escolher(interaction, **kwargs):
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
    async def test_the_labels_name_the_process_and_the_sizes_are_in_mib(self, monkeypatch):
        descricao = await descricao_do_sobre(monkeypatch)

        assert "RAM do bot (processo Python)" in descricao and "`124,0 MiB`" in descricao
        assert "RAM do Lavalink (processo Java inteiro)" in descricao and "`120,5 MiB`" in descricao
        assert "RAM total (bot + Lavalink)" in descricao and "`244,5 MiB`" in descricao

    @pytest.mark.asyncio
    async def test_the_old_labels_and_decimal_units_are_gone(self, monkeypatch):
        descricao = await descricao_do_sobre(monkeypatch)

        assert "Uso de RAM" not in descricao and " MB" not in descricao

    @pytest.mark.asyncio
    async def test_without_the_lavalink_process_only_the_bot_line_remains(self, monkeypatch):
        descricao = await descricao_do_sobre(monkeypatch, com_lavalink=False)

        assert "RAM do bot (processo Python)" in descricao
        assert "RAM do Lavalink" not in descricao and "RAM total" not in descricao


class TestContadoresDoSobre:
    @pytest.mark.asyncio
    async def test_the_counters_use_a_dot_for_thousands(self, monkeypatch):
        descricao = await descricao_do_sobre(monkeypatch)

        assert "`1.035`" in descricao and "`2.345`" in descricao

    @pytest.mark.asyncio
    async def test_no_counter_uses_a_comma_for_thousands(self, monkeypatch):
        descricao = await descricao_do_sobre(monkeypatch)

        assert "1,035" not in descricao and "2,345" not in descricao

    @pytest.mark.asyncio
    async def test_a_small_count_stays_plain(self, monkeypatch):
        descricao = await descricao_do_sobre(monkeypatch, bot=bot_do_sobre(usuarios=7, servidores=3))

        assert "`7`" in descricao and "`3`" in descricao


class TestVersaoNoSobre:
    @pytest.mark.asyncio
    async def test_with_a_version_it_links_the_release_tag_just_before_python(self, monkeypatch):
        descricao = await descricao_do_sobre(monkeypatch, versao="2.1.1")

        linhas = descricao.splitlines()
        (posicao,) = [i for i, x in enumerate(linhas) if "Versão do EmpireMuse" in x]
        assert "2.1.1" in linhas[posicao] and f"{branding.REPO_URL}/releases/tag/v2.1.1" in linhas[posicao]
        assert "Versão do Python" in linhas[posicao + 1]

    @pytest.mark.asyncio
    async def test_an_image_without_a_version_shows_dev(self, monkeypatch):
        descricao = await descricao_do_sobre(monkeypatch, versao="dev")

        (linha,) = [x for x in descricao.splitlines() if "Versão do EmpireMuse" in x]
        assert "`dev`" in linha and "releases/tag" not in linha

    @pytest.mark.asyncio
    async def test_outside_the_image_there_is_no_line(self, monkeypatch):
        descricao = await descricao_do_sobre(monkeypatch, versao=None)

        assert "Versão do EmpireMuse" not in descricao


# ============================================================================ /lastfm


def usuario_lastfm() -> dict:
    return {
        "realname": "Ana",
        "name": "ana",
        "url": "https://www.last.fm/user/ana",
        "registered": {"#text": 1_600_000_000},
        "country": "",
        "playcount": "1035",
        "playlists": "0",
        "track_count": "1234567",
        "artist_count": "1035",
        "album_count": "2050",
        "image": [{"#text": "https://exemplo.invalid/a.jpg"}],
    }


def top(chave_extra: dict | None = None) -> list:
    item = {
        "name": "Nome",
        "url": "https://www.last.fm/music/x",
        "playcount": "2050",
        "artist": {"name": "Art", "url": "https://www.last.fm/music/art"},
        "image": [{"#text": "https://exemplo.invalid/t.jpg"}],
        **(chave_extra or {}),
    }
    return [item]


async def textos_do_lastfm(monkeypatch) -> str:
    visao = SimpleNamespace(
        wait=AsyncMock(), children=[], session_key="", clear_session=False, error=None, scrobble_enabled=True
    )
    monkeypatch.setattr(lastfm, "LastFMView", MagicMock(return_value=visao))
    bot = SimpleNamespace(
        get_cog=lambda _: None,
        get_color=lambda *a: 0,
        get_global_data=AsyncMock(return_value={"lastfm": {"sessionkey": "k", "username": "ana", "scrobble": True}}),
        update_global_data=AsyncMock(),
        get_global_command_named=lambda *a, **k: SimpleNamespace(id=1),
        last_fm=SimpleNamespace(
            user_info=AsyncMock(return_value=usuario_lastfm()),
            user_top_tracks=AsyncMock(return_value=top()),
            user_top_artists=AsyncMock(return_value=top()),
            user_top_albums=AsyncMock(return_value=top({"album": {"#text": "Alb"}})),
        ),
    )
    inter = SimpleNamespace(
        author=SimpleNamespace(id=900),
        response=SimpleNamespace(defer=AsyncMock()),
        edit_original_message=AsyncMock(),
    )
    cog = lastfm.LastFmCog(bot)
    await lastfm.LastFmCog.lastfm.callback(self=cog, inter=inter)
    embeds = inter.edit_original_message.await_args_list[0].kwargs["embeds"]
    return "\n".join(f"{e.description}\n{e.author.name if e.author else ''}" for e in embeds)


class TestContadoresDoLastfm:
    @pytest.mark.asyncio
    async def test_every_counter_uses_a_dot_for_thousands(self, monkeypatch):
        texto = await textos_do_lastfm(monkeypatch)

        for esperado in ("1.035", "1.234.567", "2.050"):
            assert esperado in texto

    @pytest.mark.asyncio
    async def test_no_counter_uses_a_comma_for_thousands(self, monkeypatch):
        texto = await textos_do_lastfm(monkeypatch)

        for proibido in ("1,035", "1,234,567", "2,050"):
            assert proibido not in texto

"""S-31, Baixos do gate — valores de terceiros que vão a um code span ou a um bloco de código saem escapados.

* região do nó (``nodeinfo``) e ``sourceName`` do relatório de erro do player: passam por ``md_code``;
* nome do servidor dentro do bloco de código (aviso de entrada em ``misc.send_hook`` e painel do ``server_manager``): passa por ``fix_characters``.
Entradas "com marcas" de ``tests/support/marcas_md.py``; nenhum texto dos testes descreve o vetor.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from tests.support.marcas_md import NOME_COM_MARCAS, links_alheios, marcas_soltas

pytestmark = pytest.mark.critical

TRES_CRASES = "`" * 3
NOME_COM_BLOCO = "".join(["alfa", TRES_CRASES, "\n**Dono:** `outro`"])


def linha_com(texto: str, prefixo: str) -> str:
    return next(linha for linha in texto.splitlines() if linha.startswith(prefixo))


@pytest.mark.asyncio
class TestRegiaoDoNo:
    async def descricao_do_no(self, monkeypatch, regiao: str, cpu_cores: object = 2, versao: object = 4) -> str:
        from empiremuse.cogs import music_settings
        from empiremuse.cogs.music_settings import MusicSettings

        enviado: dict = {}

        async def enviar(**kwargs):
            enviado.update(kwargs)

        stats = SimpleNamespace(
            memory_used=1,
            memory_allocated=3,
            memory_free=2,
            memory_reservable=4,
            cpu_cores=2,
            lavalink_load=0.1,
            players=0,
            playing_players=0,
            uptime=1000,
        )
        no = SimpleNamespace(
            identifier="no-1",
            stats=stats,
            is_available=True,
            players={},
            region=regiao,
            region_label=regiao,
            version=versao,
            website=None,
        )
        bot = MagicMock()
        bot.music.nodes = {"no-1": no}
        bot.get_guild.return_value = None
        bot.get_color.return_value = 0
        bot.user.display_avatar.with_format.return_value.url = "https://cdn.exemplo/a.png"
        inter = MagicMock(spec=disnake.ApplicationCommandInteraction)
        inter.guild_id = 1
        inter.send = AsyncMock(side_effect=lambda **kw: enviar(**kw))
        monkeypatch.setattr(music_settings, "select_bot_pool", AsyncMock(return_value=(inter, bot)))
        cog = MusicSettings.__new__(MusicSettings)

        await MusicSettings.nodeinfo.callback(cog, inter)

        embed = inter.send.await_args.kwargs["embed"]
        return "\n".join(f"{campo.value}" for campo in embed.fields)

    async def test_a_node_region_with_marks_stays_inside_one_code_span(self, monkeypatch):
        texto = await self.descricao_do_no(monkeypatch, NOME_COM_MARCAS)

        linha = linha_com(texto, "Região:")
        assert linha.count("`") == 2 and links_alheios(linha) == [] and marcas_soltas(linha) == 0

    async def test_cpu_cores_from_the_node_json_stays_inside_one_code_span(self, monkeypatch):
        texto = await self.descricao_do_no(monkeypatch, "frankfurt", cpu_cores=NOME_COM_MARCAS)

        linha = linha_com(texto, "CPU Cores:")
        assert linha.count("`") == 2 and links_alheios(linha) == [] and marcas_soltas(linha) == 0

    async def test_the_node_version_stays_inside_one_code_span(self, monkeypatch):
        texto = await self.descricao_do_no(monkeypatch, "frankfurt", versao=NOME_COM_MARCAS)

        linha = linha_com(texto, "Versão do Lavalink:")
        assert linha.count("`") == 2 and links_alheios(linha) == [] and marcas_soltas(linha) == 0

    async def test_ordinary_cores_and_version_are_unchanged(self, monkeypatch):
        texto = await self.descricao_do_no(monkeypatch, "frankfurt")

        assert linha_com(texto, "CPU Cores:") == "CPU Cores: `2`"
        assert linha_com(texto, "Versão do Lavalink:") == "Versão do Lavalink: `v4`"

    async def test_an_ordinary_region_shows_the_owner_text_as_written(self, monkeypatch):
        texto = await self.descricao_do_no(monkeypatch, "frankfurt")

        assert linha_com(texto, "Região:") == "Região: `frankfurt`"


@pytest.mark.asyncio
class TestFonteDoRelatorio:
    async def descricao(self, fonte: str, servidor_nome: str = "Servidor", canal_nome: str | None = None) -> str:
        from empiremuse.utils.music.models.player import LavalinkPlayer

        fila: asyncio.Queue = asyncio.Queue()
        voz = SimpleNamespace(channel=SimpleNamespace(name=canal_nome, id=2)) if canal_nome is not None else None
        eu = SimpleNamespace(voice=voz)
        servidor = SimpleNamespace(name=servidor_nome, id=1, me=eu, icon=None)
        dono = SimpleNamespace(
            bot=SimpleNamespace(get_cog=lambda nome: SimpleNamespace(error_report_queue=fila)), guild=servidor
        )
        faixa = SimpleNamespace(info={"sourceName": fonte})
        embed = disnake.Embed(description="falha")

        await LavalinkPlayer.report_error(dono, embed, faixa)

        return fila.get_nowait()["embed"].description

    async def test_a_source_name_with_marks_stays_inside_one_code_span(self):
        texto = await self.descricao(NOME_COM_MARCAS)

        linha = linha_com(texto, "**Fonte:**")
        assert linha.count("`") == 2 and links_alheios(linha) == [] and marcas_soltas(linha) == 0

    async def test_a_guild_name_with_marks_cannot_close_the_code_span_or_make_a_link(self):
        texto = await self.descricao("youtube", servidor_nome=NOME_COM_MARCAS)

        linha = linha_com(texto, "**Servidor:**")
        assert "](" not in linha and links_alheios(linha) == [] and linha.count("`") % 2 == 0

    async def test_a_voice_channel_name_with_marks_cannot_close_the_code_span_or_make_a_link(self):
        texto = await self.descricao("youtube", canal_nome=NOME_COM_MARCAS)

        linha = linha_com(texto, "**Canal:**")
        assert "](" not in linha and links_alheios(linha) == [] and linha.count("`") % 2 == 0

    async def test_ordinary_guild_and_channel_names_are_kept(self):
        texto = await self.descricao("youtube", servidor_nome="Servidor Comum", canal_nome="Geral")

        assert "Servidor Comum" in linha_com(texto, "**Servidor:**") and "Geral" in linha_com(texto, "**Canal:**")

    async def test_an_ordinary_source_name_is_unchanged(self):
        assert linha_com(await self.descricao("youtube"), "**Fonte:**") == "**Fonte:** `youtube`"


def painel_com(nome: str):
    from empiremuse.cogs.server_manager import ServerManagerView

    painel = ServerManagerView.__new__(ServerManagerView)
    servidor = servidor_com_nome(nome)
    painel.bot = SimpleNamespace(
        get_color=lambda *a: 0,
        user=SimpleNamespace(id=2),
        guild_placeholder=None,
    )
    painel.bot.user.__str__ = lambda self: "bot"
    painel.bot.user.display_avatar = SimpleNamespace(url="https://cdn.exemplo/a.png")
    painel.current_guild, painel.pages, painel.current_page = servidor, [[servidor]], 0
    painel.current_guild.me.joined_at = datetime(2024, 1, 2, tzinfo=timezone.utc)
    return painel


OUTRA_INTERACAO = SimpleNamespace(guild=SimpleNamespace(id=999), bot=SimpleNamespace(user=SimpleNamespace(id=1)))


def servidor_com_nome(nome: str) -> SimpleNamespace:
    membro = SimpleNamespace(bot=False)
    return SimpleNamespace(
        name=nome,
        id=11,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        owner=SimpleNamespace(id=7),
        verification_level=None,
        members=[membro],
        icon=None,
        me=SimpleNamespace(joined_at=datetime(2024, 1, 2, tzinfo=timezone.utc)),
    )


@pytest.mark.asyncio
class TestNomeDoServidorNoBloco:
    async def test_the_join_notice_keeps_the_guild_name_inside_one_code_block(self):
        from empiremuse.cogs.misc import GuildLog

        canal = MagicMock()
        canal.permissions_for.return_value.send_messages = True
        canal.send = AsyncMock()
        dono = SimpleNamespace(
            bot=SimpleNamespace(
                get_channel=lambda _id: canal,
                config={"BOT_ADD_REMOVE_LOG_CHANNEL_ID": 1},
                owner_ids=[1],
                owner=SimpleNamespace(mention="<@1>"),
            )
        )

        await GuildLog.send_hook(dono, servidor_com_nome(NOME_COM_BLOCO), "Título", disnake.Color.green())

        descricao = canal.send.await_args.kwargs["embed"].description
        assert descricao.count(TRES_CRASES) == 2 and "alfa" in descricao

    async def test_the_server_manager_panel_keeps_the_guild_name_inside_one_code_block(self):
        embed = painel_com(NOME_COM_BLOCO).build_embed(OUTRA_INTERACAO)[0]

        assert embed.description.count(TRES_CRASES) == 2 and "alfa" in embed.description

    async def test_an_ordinary_guild_name_is_unchanged_in_the_panel(self):
        embed = painel_com("Servidor Comum").build_embed(OUTRA_INTERACAO)[0]

        assert embed.description.startswith(f"{TRES_CRASES}Servidor Comum{TRES_CRASES}\n")

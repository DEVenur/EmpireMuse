"""S-31, achados do CodeRabbit no #130 — o link do aviso de remoção de favorito/integração e o título sem URL da skin estática ``embed_link``.

* ``fav_menu.remove_callback``: o favorito do usuário é uma ``str`` (URL), o do servidor é ``{url, description}`` e a integração é ``{url, avatar}``;
  o ``md_link`` recebe sempre a URL (``str``), nunca o dicionário, senão o aviso perde o link.
* ``skins/static_player/embed_link.py``: título sem URI sai por ``md_link`` só com o rótulo (uma linha, sem marcas), não só por ``fix_characters``.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse.utils.music.interactions.common import ViewMode
from empiremuse.utils.music.interactions.fav_menu import FavMenuView
from empiremuse.utils.music.skins.static_player.embed_link import EmbedLinkStaticSkin
from tests.audio.test_skins_caracterizacao import make_player, make_track
from tests.support.marcas_md import NOME_COM_MARCAS, destinos, links_alheios, marcas_soltas, textos_da_saida

pytestmark = pytest.mark.critical

URL = "https://ok.exemplo/favorito"


def visao(modo: str, nome: str, valor, onde: str):
    """``FavMenuView`` sem Discord: ``valor`` entra em ``data`` (usuário/integração) ou em ``guild_data`` (servidor), sob o nome ``nome``."""
    v = FavMenuView.__new__(FavMenuView)
    v.mode, v.current, v.log = modo, nome, ""
    v.build_txt = lambda: ""
    guild = SimpleNamespace(me=SimpleNamespace())
    v.bot = SimpleNamespace(
        update_global_data=AsyncMock(),
        update_data=AsyncMock(),
        get_guild=lambda _id: guild,
        get_color=lambda *a: 0,
        pool=SimpleNamespace(get_guild_bots=lambda _id: []),
    )
    v.data = {"fav_links": {}, "integration_links": {}}
    v.guild_data = {"player_controller": {"fav_links": {}}}
    v.bot.get_global_data = AsyncMock(side_effect=lambda *a, **k: v.data)
    v.bot.get_data = AsyncMock(side_effect=lambda *a, **k: v.guild_data)
    if onde == "usuario":
        v.data["fav_links"][nome] = valor
    elif onde == "servidor":
        v.guild_data["player_controller"]["fav_links"][nome] = valor
    else:
        v.data["integration_links"][nome] = valor
    return v


def interacao() -> MagicMock:
    inter = MagicMock(spec=disnake.MessageInteraction)
    inter.response = SimpleNamespace(defer=AsyncMock())
    inter.edit_original_message, inter.send = AsyncMock(), AsyncMock()
    inter.author = SimpleNamespace(id=7)
    inter.guild_id = 1
    return inter


CASOS = [
    pytest.param(ViewMode.fav_manager, URL, "usuario", id="favorito-do-usuario"),
    pytest.param(ViewMode.guild_fav_manager, {"url": URL, "description": "d"}, "servidor", id="favorito-do-servidor"),
    pytest.param(
        ViewMode.integrations_manager, {"url": URL, "avatar": "https://ok.exemplo/a.png"}, "integracao", id="integracao"
    ),
]


@pytest.mark.asyncio
class TestAvisoDeRemocao:
    @pytest.mark.parametrize(("modo", "valor", "onde"), CASOS)
    async def test_the_removal_notice_keeps_the_link_with_the_url_string(self, modo, valor, onde):
        v = visao(modo, "meu favorito", valor, onde)

        await v.remove_callback(interacao())

        assert destinos(v.log) == [URL] and "meu favorito" in v.log

    @pytest.mark.parametrize(("modo", "valor", "onde"), CASOS)
    async def test_the_entry_is_removed_and_the_data_saved(self, modo, valor, onde):
        v = visao(modo, "meu favorito", valor, onde)

        await v.remove_callback(interacao())

        restantes = (
            v.data["fav_links"]
            if onde == "usuario"
            else v.guild_data["player_controller"]["fav_links"]
            if onde == "servidor"
            else v.data["integration_links"]
        )
        assert "meu favorito" not in restantes
        assert v.bot.update_global_data.await_count + v.bot.update_data.await_count == 1

    @pytest.mark.parametrize(("modo", "valor", "onde"), CASOS)
    async def test_a_name_with_marks_cannot_add_a_link_to_the_notice(self, modo, valor, onde):
        v = visao(modo, NOME_COM_MARCAS, valor, onde)

        await v.remove_callback(interacao())

        assert destinos(v.log) == [URL] and links_alheios(v.log) == [] and marcas_soltas(v.log) == 0

    async def test_a_name_that_is_not_in_the_list_gives_the_not_found_message(self):
        v = visao(ViewMode.fav_manager, "outro", URL, "usuario")
        v.current = "nao existe"
        inter = interacao()

        await v.remove_callback(inter)

        inter.edit_original_message.assert_awaited_once()
        assert "Não há favorito" in inter.edit_original_message.await_args.args[0]


class TestTituloSemUriDaSkinEstatica:
    def texto(self, titulo: str, uri: str = "", **mais) -> str:
        jogador = make_player(current=make_track(title=titulo, uri=uri, **mais))
        return "\n".join(textos_da_saida(EmbedLinkStaticSkin().load(jogador)))

    def linha_do_titulo(self, texto: str) -> str:
        return next(linha for linha in texto.splitlines() if "Tocando Agora" in linha)

    def test_a_title_with_marks_cannot_make_a_link_or_break_the_line(self):
        texto = self.texto(NOME_COM_MARCAS)

        assert links_alheios(texto) == [] and marcas_soltas(texto) == 0

    def test_a_line_break_in_the_title_cannot_split_the_title_line(self):
        linha = self.linha_do_titulo(self.texto("primeira\nsegunda"))

        assert "primeira" in linha and "segunda" in linha

    def test_markdown_in_a_title_without_url_is_escaped_like_the_linked_title(self):
        linha = self.linha_do_titulo(self.texto("x~~riscado~~ y||spoiler||"))

        assert "~~" not in linha.replace("\\~", "") and "||" not in linha.replace("\\|", "")

    def test_the_title_with_a_url_still_becomes_a_masked_link(self):
        linha = self.linha_do_titulo(self.texto("Titulo Normal", uri="https://ok.exemplo/faixa"))

        assert destinos(linha) == ["https://ok.exemplo/faixa"] and "Titulo Normal" in linha

    def test_the_title_without_url_is_plain_text_never_a_link(self):
        linha = self.linha_do_titulo(self.texto("Titulo Normal"))

        assert destinos(linha) == [] and "Titulo Normal" in linha

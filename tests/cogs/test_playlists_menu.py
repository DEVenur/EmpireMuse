"""Menu ``/fav_manager`` no modo servidor (item 17, A6): quem não gerencia é negado em TODO botão e modal, inclusive o modal enviado
depois de a pessoa ser rebaixada, e nada chega ao store. O aviso de remoção só leva links do código (``md_link``)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse.rules.playlists import Playlist
from empiremuse.utils.music.interactions import fav_menu_playlists as playlists_ui
from empiremuse.utils.music.interactions.common import ViewMode
from empiremuse.utils.music.interactions.fav_menu import FavMenuView
from empiremuse.utils.music.interactions.fav_menu_playlists import PlaylistImportModal, PlaylistModal
from tests.support.marcas_md import NOME_COM_MARCAS, destinos, links_alheios, marcas_soltas

pytestmark = pytest.mark.critical

GID, OWNER_ID = 1, 99
URL = "https://ok.exemplo/favorito"


def member(*, administrator=False, manage_guild=False):
    return MagicMock(
        spec=disnake.Member,
        id=7,
        guild_permissions=SimpleNamespace(administrator=administrator, manage_guild=manage_guild),
    )


def make_inter(author):
    inter = MagicMock(spec=disnake.MessageInteraction)
    inter.author, inter.guild, inter.guild_id = author, SimpleNamespace(owner_id=OWNER_ID), GID
    inter.response = SimpleNamespace(defer=AsyncMock(), send_modal=AsyncMock())
    inter.edit_original_message, inter.send = AsyncMock(), AsyncMock()
    inter.text_values = {}
    return inter


def make_view(playlist=None):
    store = SimpleNamespace(
        add=AsyncMock(),
        edit=AsyncMock(),
        remove=AsyncMock(return_value=playlist),
        clear=AsyncMock(),
        import_file=AsyncMock(),
        export_bytes=AsyncMock(return_value=b'{"playlists": [{}]}'),
        list=AsyncMock(return_value=()),
    )
    view = FavMenuView.__new__(FavMenuView)
    view.mode, view.current, view.log = ViewMode.guild_fav_manager, "Rock", ""
    view.build_txt = lambda: ""
    view.load_playlists, view._redraw = AsyncMock(), AsyncMock()
    view.bot = SimpleNamespace(pool=SimpleNamespace(servers=SimpleNamespace(playlists=store)), get_cog=MagicMock())
    return view, store


def assert_store_untouched(store):
    for method in ("add", "edit", "remove", "clear", "import_file", "export_bytes"):
        getattr(store, method).assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "callback",
    ["add_callback", "edit_callback", "remove_callback", "clear_callback", "import_callback", "export_callback"],
)
async def test_a_plain_member_is_denied_in_every_server_menu_button(callback):
    view, store = make_view()
    inter = make_inter(member())

    await getattr(view, callback)(inter)

    inter.send.assert_awaited_once()
    assert inter.send.await_args.args[0] == playlists_ui.MSG_DENIED
    assert inter.send.await_args.kwargs["ephemeral"] is True
    inter.response.send_modal.assert_not_awaited()
    assert_store_untouched(store)


@pytest.mark.asyncio
@pytest.mark.parametrize("modal", ["edit", "import"])
async def test_a_modal_submitted_after_the_admin_was_demoted_is_denied(modal):  # A6: rebaixado com o menu aberto
    view, store = make_view()
    inter = make_inter(member())  # quando abriu o modal era admin; ao enviar já não é
    if modal == "edit":
        inter.text_values = {"pl_name": "Rock", "pl_url": URL, "pl_order": "", "pl_description": "", "pl_genres": ""}
        await PlaylistModal.callback(PlaylistModal(view), inter)
    else:
        inter.text_values = {"json_data": '{"playlists": [{"name": "Rock", "url": "' + URL + '"}]}'}
        await PlaylistImportModal.callback(PlaylistImportModal(view), inter)

    assert inter.send.await_args.args[0] == playlists_ui.MSG_DENIED
    assert_store_untouched(store)


@pytest.mark.asyncio
async def test_a_manager_can_remove_and_the_notice_only_links_what_the_code_builds():
    view, store = make_view(Playlist(1, NOME_COM_MARCAS, "d", (), URL, None))
    inter = make_inter(member(manage_guild=True))

    await view.remove_callback(inter)

    store.remove.assert_awaited_once_with(GID, "Rock")  # o nome vem do menu, o servidor de inter.guild_id
    assert destinos(view.log) == [URL] and links_alheios(view.log) == [] and marcas_soltas(view.log) == 0


@pytest.mark.regression
@pytest.mark.asyncio
async def test_a_genre_named_like_the_all_option_is_a_real_genre_not_the_reset():
    from empiremuse.music_cog.play_guild_menu import ALL_GENRES, GuildPlaylistSelect

    def playlist(name, genre):
        return Playlist(0, name, "", (genre,), f"https://ok.exemplo/{name.lower()}", None)

    bot = SimpleNamespace(pool=SimpleNamespace(), music=None)
    view = GuildPlaylistSelect(
        SimpleNamespace(id=1), bot, (playlist("Rock", "Rock"), playlist("Todos", ALL_GENRES)), timeout=5
    )
    assert ALL_GENRES in view.genres  # o gênero existe e é filtrável
    interaction = SimpleNamespace(
        data=SimpleNamespace(values=[str(view.genres.index(ALL_GENRES))]),
        response=SimpleNamespace(edit_message=AsyncMock(), defer=AsyncMock()),
    )

    await view.genre_callback(interaction)

    assert view.genre == ALL_GENRES  # filtrou por ele, não voltou para "Todos"
    assert [o.label for o in view.item_pages[0]] == ["Todos"]


def clearing_world(*, send_fails=False, conflict=False):
    """Um servidor com 2 playlists na versão 7; ``calls`` registra a ordem entre enviar o backup e limpar."""
    from empiremuse.utils.servers import ServerConfigConflict

    calls = []
    view, store = make_view()
    items = (
        Playlist(1, "Rock", "", (), "https://ok.exemplo/rock", None),
        Playlist(2, "Pop", "", (), "https://ok.exemplo/pop", None),
    )
    store.snapshot = AsyncMock(return_value=(items, 7))

    async def clear(gid, expected_rev=None):
        calls.append(("clear", expected_rev))
        if conflict:
            raise ServerConfigConflict()
        return 2

    async def followup(*args, **kwargs):
        calls.append(("backup", kwargs["file"].filename))
        if send_fails:
            raise disnake.HTTPException(SimpleNamespace(status=500, reason="x"), "boom")

    store.clear = AsyncMock(side_effect=clear)
    inter = make_inter(member(manage_guild=True))
    inter.followup = SimpleNamespace(send=AsyncMock(side_effect=followup))
    return view, store, inter, calls


@pytest.mark.regression
@pytest.mark.asyncio
async def test_clearing_sends_the_backup_first_and_only_clears_the_version_that_became_the_backup():
    view, store, inter, calls = clearing_world()

    assert await playlists_ui.clear_all(view, inter) is True

    assert calls == [("backup", f"playlists-{GID}.json"), ("clear", 7)]  # backup antes; limpeza presa à versão 7


@pytest.mark.regression
@pytest.mark.asyncio
async def test_a_backup_that_cannot_be_sent_means_nothing_is_cleared():
    view, store, inter, calls = clearing_world(send_fails=True)

    assert await playlists_ui.clear_all(view, inter) is False

    store.clear.assert_not_awaited()
    assert "não apaguei nada" in inter.edit_original_message.await_args.args[0]


@pytest.mark.regression
@pytest.mark.asyncio
async def test_a_list_that_changed_after_the_backup_is_not_cleared_and_the_user_is_told():
    view, store, inter, calls = clearing_world(conflict=True)

    assert await playlists_ui.clear_all(view, inter) is False

    assert [name for name, _ in calls] == ["backup", "clear"]
    assert "backup já foi enviado" in inter.edit_original_message.await_args.args[0]

"""S-31, S2/S3/S3b/S5/S6 — escape de markdown por FONTE de nome externo, por renderizador alcançável, nos placeholders de skin e nas menções.

* S2: ``authors_md`` das faixas (``LavalinkTrack``/``PartialTrack``) e dos construtores do Spotify com nome E URL "com marcas".
* S3: embeds de ``event_steps`` (falha de faixa e faixa sem resultado). Os demais renderizadores têm o teste-guarda de AST (S4).
* S3b: ``skin_utils.replaces`` (placeholders de texto passam por ``fix_characters``, os de URL por ``md_url``).
* S5: o ``BotCore`` nasce sem menção a ``@everyone``/cargos.
* S6: a INGESTÃO não escapa nada (o texto cru continua indo para busca e scrobble); o escape é só na exibição.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import disnake
import pytest
from disnake.ext import commands

from empiremuse.utils.music.models import event_steps
from empiremuse.utils.music.models.tracks import LavalinkTrack, PartialTrack
from empiremuse.utils.music.skin_utils import replaces
from tests.audio.test_spotify_authors_md import bot_falso, cliente, faixa as faixa_spotify
from tests.logs.test_player_events import excecao, jogador
from tests.support.marcas_md import (
    NOME_COM_CRASES,
    NOME_COM_MARCAS,
    URL_COM_MAIOR,
    URL_COM_PARENTESE,
    URLS_FORA_DO_PADRAO,
    links_alheios,
    marcas_soltas,
    sem_link_alheio,
)

pytestmark = pytest.mark.critical


def faixa_lavalink(plugin=None, **info):
    """``LavalinkTrack`` como o Lavalink a entrega: o ``pluginInfo`` vai à parte do ``info`` (kwarg), não dentro dele."""
    return LavalinkTrack(id_="x", info=info_lavalink(**info), requester=1, pluginInfo=plugin or {})


def info_lavalink(**mais):
    base = {
        "title": "Titulo",
        "author": "Artista",
        "uri": "https://ok.exemplo/faixa",
        "length": 200_000,
        "identifier": "id1",
        "isStream": False,
        "sourceName": "soundcloud",
        "position": 0,
        "artworkUrl": "https://ok.exemplo/capa.png",
    }
    base.update(mais)
    return base


# ============================================================================ S2 — authors_md das faixas


class TestAutoresDasFaixas:
    @pytest.mark.parametrize(
        "autor", [NOME_COM_MARCAS, NOME_COM_CRASES, "Nome [x](u)"], ids=["marcas", "crases", "link"]
    )
    def test_a_lavalink_track_author_with_marks_cannot_make_an_extra_link(self, autor):
        faixa = faixa_lavalink({"artistUrl": "https://ok.exemplo/artista"}, author=autor)

        md = faixa.authors_md

        assert links_alheios(md) == [] and marcas_soltas(md) == 0
        assert md.count("](") == 1 and md.count("[`") == 1 and md.count("`") == 2

    @pytest.mark.parametrize("url", [URL_COM_PARENTESE, URL_COM_MAIOR], ids=["parentese", "maior"])
    def test_an_artist_url_with_marks_cannot_leave_the_angle_brackets(self, url):
        faixa = faixa_lavalink({"artistUrl": url})

        md = faixa.authors_md

        assert links_alheios(md) == [] and marcas_soltas(md) == 0 and md.count("](") == 1

    @pytest.mark.parametrize("url", URLS_FORA_DO_PADRAO[:5], ids=lambda u: u[:12])
    def test_an_artist_url_that_is_not_http_gives_only_the_name(self, url):
        faixa = faixa_lavalink({"artistUrl": url})

        assert faixa.authors_md == "`Artista`"

    def test_without_an_artist_url_a_hostile_author_is_one_single_code_span(self):
        faixa = faixa_lavalink(author=NOME_COM_MARCAS)

        md = faixa.authors_md

        assert md.count("`") == 2 and md.startswith("`") and md.endswith("`") and links_alheios(md) == []

    def test_a_normal_author_keeps_the_intended_link(self):
        faixa = faixa_lavalink({"artistUrl": "https://ok.exemplo/artista"})

        assert faixa.authors_md == "[`Artista`](<https://ok.exemplo/artista>)"

    @pytest.mark.parametrize("autor", [NOME_COM_MARCAS, NOME_COM_CRASES])
    def test_a_partial_track_author_with_marks_gives_one_code_span(self, autor):
        faixa = PartialTrack(uri="https://ok.exemplo/f", author=autor, title="T", source_name="spotify")

        md = faixa.authors_md

        assert md.count("`") == 2 and links_alheios(md) == [] and marcas_soltas(md) == 0


class TestConstrutoresDoSpotifyComUrlHostil:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", [URL_COM_PARENTESE, URL_COM_MAIOR], ids=["parentese", "maior"])
    async def test_the_search_builder_encodes_the_artist_url(self, url):
        item = faixa_spotify(["Normal", "Outro"])
        for artista in item["artists"]:
            artista["external_urls"]["spotify"] = url
        c = cliente()
        c.track_search = MagicMock(return_value=_pronto({"tracks": {"items": [item]}}))

        (t,) = await c.get_tracks(bot_falso(), 7, "Normal Musica")

        md = t.info["extra"]["authors_md"]
        assert links_alheios(md) == [] and marcas_soltas(md) == 0 and md.count("](") == 2

    @pytest.mark.asyncio
    async def test_the_track_link_builder_encodes_the_artist_url(self):
        item = faixa_spotify(["Normal"])
        item["artists"][0]["external_urls"]["spotify"] = URL_COM_PARENTESE
        c = cliente()
        c.get_track_info = MagicMock(return_value=_pronto(item))

        (t,) = await c.get_tracks(bot_falso(), 7, "https://open.spotify.com/track/t1")

        md = t.info["extra"]["authors_md"]
        assert links_alheios(md) == [] and marcas_soltas(md) == 0

    @pytest.mark.asyncio
    async def test_a_non_http_artist_url_gives_only_the_name(self):
        item = faixa_spotify(["Normal"])
        item["artists"][0]["external_urls"]["spotify"] = "javascript:alert(1)"
        c = cliente()
        c.get_track_info = MagicMock(return_value=_pronto(item))

        (t,) = await c.get_tracks(bot_falso(), 7, "https://open.spotify.com/track/t1")

        assert "javascript" not in t.info["extra"]["authors_md"]


def _pronto(valor):
    futuro = asyncio.get_event_loop().create_future()
    futuro.set_result(valor)
    return futuro


# ============================================================================ S3 — embeds de event_steps


class TestEmbedsDeEventSteps:
    def trocar(self, jogador_, **campos):
        for chave, valor in campos.items():
            setattr(jogador_.current, chave, valor)
        return jogador_.current

    def test_the_track_failure_embed_escapes_the_title_and_the_url(self):
        player = jogador(1)
        faixa = self.trocar(player, title=NOME_COM_MARCAS, uri=URL_COM_PARENTESE, search_uri=URL_COM_MAIOR)

        embed, _ = event_steps._he_exception_embed(player, excecao(player), faixa)

        assert sem_link_alheio([embed.description]) == [] and marcas_soltas(embed.description) == 0

    @pytest.mark.parametrize("url", [URL_COM_PARENTESE, URL_COM_MAIOR], ids=["parentese", "maior"])
    def test_the_no_result_embed_escapes_the_title_and_the_url(self, url):
        player = jogador(1)
        faixa = self.trocar(player, title=NOME_COM_MARCAS, url=url, thumb="https://ok.exemplo/t.png")
        player.bot.get_color = lambda *a: 0

        embed = event_steps._he_mirror_not_found_embed(player, faixa)

        assert sem_link_alheio([embed.description]) == [] and marcas_soltas(embed.description) == 0

    def test_ordinary_titles_keep_the_intended_link(self):
        player = jogador(1)
        faixa = self.trocar(player, title="Titulo Normal", uri="https://ok.exemplo/faixa")

        embed, _ = event_steps._he_exception_embed(player, excecao(player), faixa)

        assert "Titulo Normal" in embed.description and "https://ok.exemplo/faixa" in embed.description


# ============================================================================ S3b — placeholders de skin personalizada


def jogador_de_skin(**faixa):
    atual = SimpleNamespace(
        autoplay=False,
        requester=1,
        title="Titulo Normal",
        author="Autor Normal",
        uri="https://ok.exemplo/faixa",
        duration=185_000,
        is_stream=False,
        thumb="https://ok.exemplo/t.png",
        playlist_name="Lista Normal",
        playlist_url="https://ok.exemplo/lista",
    )
    for chave, valor in faixa.items():
        setattr(atual, chave, valor)
    return SimpleNamespace(
        current=atual,
        loop=False,
        queue=[],
        queue_autoplay=[],
        volume=100,
        autoplay=False,
        nightcore=False,
        current_hint="",
        command_log="",
        command_log_emoji="",
        controller_link="https://discord.com/channels/1/2",
    )


def servidor():
    guild = SimpleNamespace(
        me=SimpleNamespace(color=SimpleNamespace(value=0x123456), display_avatar=None),
        icon=None,
        name="Servidor",
        id=1,
    )

    def sem_membro(_id):
        raise LookupError

    guild.get_member = sem_membro
    return guild


def aplicar(modelo, **faixa):
    return replaces(modelo, {}, None, jogador_de_skin(**faixa), "", {}, servidor())


class TestPlaceholdersDeSkin:
    def test_a_title_with_marks_cannot_make_a_new_link_in_the_default_title_template(self):
        saida = aplicar("[{track.title}]({track.url})", title=NOME_COM_MARCAS, uri="https://ok.exemplo/faixa")

        assert links_alheios(saida) == [] and marcas_soltas(saida) == 0

    @pytest.mark.parametrize("url", [URL_COM_PARENTESE, URL_COM_MAIOR], ids=["parentese", "maior"])
    def test_a_url_with_marks_cannot_leave_the_parentheses(self, url):
        saida = aplicar("[{track.title}]({track.url})", uri=url)

        assert links_alheios(saida) == [] and marcas_soltas(saida) == 0

    @pytest.mark.parametrize("url", URLS_FORA_DO_PADRAO[:5], ids=lambda u: u[:12])
    def test_a_url_that_is_not_http_becomes_empty_and_the_link_disappears_not_the_template(self, url):
        saida = aplicar("a [{track.title}]({track.url}) b", uri=url)

        assert url not in saida and saida.startswith("a [") and saida.endswith(") b")

    def test_the_author_placeholder_cannot_inject_markup(self):
        saida = aplicar("**{track.author}**", author=NOME_COM_MARCAS)

        assert "](" not in saida and "`" not in saida and saida.startswith("**") and saida.endswith("**")

    def test_the_playlist_name_and_url_placeholders_are_escaped_too(self):
        saida = aplicar(
            "[{playlist.name}]({playlist.url})", playlist_name=NOME_COM_MARCAS, playlist_url=URL_COM_PARENTESE
        )

        assert links_alheios(saida) == [] and marcas_soltas(saida) == 0

    def test_the_title_variants_are_escaped(self):
        saida = aplicar("{track.title_25}|{track.title_42}|{track.title_58}", title=NOME_COM_MARCAS)

        assert "](" not in saida and "`" not in saida

    def test_the_thumb_placeholder_goes_through_the_url_rule(self):
        saida = aplicar("{track.thumb}", thumb="javascript:alert(1)")

        assert "javascript" not in saida

    def test_ordinary_values_are_unchanged(self):
        saida = aplicar("[{track.title}]({track.url}) por {track.author} em {playlist.name}")

        assert saida == "[Titulo Normal](https://ok.exemplo/faixa) por Autor Normal em Lista Normal"


# ============================================================================ S5 — menções


class TestMencoes:
    @pytest.mark.asyncio
    async def test_the_bot_starts_without_everyone_or_role_mentions(self):
        from empiremuse.utils.client import BotCore

        bot = BotCore(
            command_prefix=commands.when_mentioned,
            intents=disnake.Intents.none(),
            pool=SimpleNamespace(config={"OWNER_IDS": ""}, loop=None),
            identifier="teste",
        )

        permitidas = bot.allowed_mentions
        assert permitidas is not None and permitidas.everyone is False and permitidas.roles is False
        assert permitidas.users is True and permitidas.replied_user is True


# ============================================================================ S6 — a ingestão não escapa nada


class TestIngestaoContinuaCrua:
    def test_the_partial_track_title_is_stored_raw_for_search_and_scrobble(self):
        faixa = PartialTrack(uri="https://ok.exemplo/f", author="A", title="a*b_c [x] `y`", source_name="spotify")

        assert faixa.info["title"] == "a*b_c [x] `y`"

    def test_the_lavalink_track_author_is_stored_raw(self):
        faixa = faixa_lavalink(author=NOME_COM_MARCAS)

        assert faixa.author == NOME_COM_MARCAS and faixa.info["author"] == NOME_COM_MARCAS

    def test_the_playlist_and_album_names_are_stored_raw(self):
        faixa = faixa_lavalink({"albumName": "Album [x]", "albumUrl": "https://ok.exemplo/al"})

        assert faixa.album_url == "https://ok.exemplo/al"

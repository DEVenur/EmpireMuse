"""F3-5b, etapa 0 — A4: os botões "favoritar" do player (``Music.player_controller``), em VERDE.

Não existem no painel e escrevem em ``fav_links`` sem a regra dos modais: o botão do embed soma a quantidade de
favoritos com ela mesma (2n) e não valida o nome; o seletor trunca o NOME com o limite de URL e conta uma
sobrescrita como vaga. Chama o ``player_controller`` REAL com dublês. ``# MUDA (etapa N, A4)`` marca o que muda.
"""

from types import SimpleNamespace

import disnake
import pytest

from empiremuse.cogs.music import Music
from empiremuse.utils.others import PlayerControls
from tests.helpers_f3_5b import AUTOR, BotDeComandos, InteracaoFalsa

URL = "https://exemplo.invalid/musica"
SERVIDOR = 5000


class BotDoPlayer(BotDeComandos):
    """``BotDeComandos`` com o que o ``player_controller`` pede antes de chegar nos botões de favoritar."""

    bot_ready = True

    def __init__(self, *, favs=10, dono=False, url_max=90, favoritos=None):
        super().__init__(dono=dono)
        self.config.update({"MAX_USER_FAVS": favs, "USER_FAV_MAX_URL_LENGTH": url_max})
        self.pool.add_fav_embed_cooldown = SimpleNamespace(
            get_bucket=lambda inter: SimpleNamespace(update_rate_limit=lambda: None)
        )
        self.eventos = []
        self.documento("global", "users", AUTOR)["fav_links"].update(favoritos or {})

    def dispatch(self, nome, *args):
        self.eventos.append(nome)

    @property
    def favoritos(self):
        return self.documento("global", "users", AUTOR)["fav_links"]


class MusicaFalsa:
    """O ``self`` de ``Music.player_controller``: só o bot, os nomes dos comandos de prefixo e a trava de concorrência."""

    def __init__(self, bot):
        self.bot = bot
        self.play_legacy = SimpleNamespace(name="play")
        self.fav_manager_legacy = SimpleNamespace(name="fav_manager")
        self.player_interaction_concurrency = SimpleNamespace(acquire=self._nada, release=self._nada)

    @staticmethod
    async def _nada(*args, **kwargs):
        return None


def interacao(guild):
    inter = InteracaoFalsa(guild_id=SERVIDOR, guild=guild)
    inter.message = SimpleNamespace(
        embeds=[], flags=SimpleNamespace(ephemeral=True), edit=inter._nada, content=str(AUTOR)
    )
    return inter


async def favoritar_pelo_embed(bot, titulo, url=URL):
    """Clica em "Favoritar" no embed da música (``PlayerControls.embed_add_fav``); o nome é o autor do embed sem o 1º char."""
    guild = SimpleNamespace(me=SimpleNamespace())
    inter = interacao(guild)
    inter.message.embeds = [disnake.Embed(description="x").set_author(name=f"⠂{titulo}", url=url)]
    await Music.player_controller(MusicaFalsa(bot), inter, PlayerControls.embed_add_fav)
    return inter


async def favoritar_pelo_seletor(bot, titulo, url=URL):
    """Clica em "Favoritar" no player da música atual (``PlayerControls.add_favorite``) com um único item para escolher."""
    canal = SimpleNamespace(id=77)
    guild = SimpleNamespace(me=SimpleNamespace(voice=SimpleNamespace(channel=canal)))
    inter = interacao(guild)
    inter.author.voice = SimpleNamespace(channel=canal)
    player = SimpleNamespace(
        message=inter.message,
        interaction_cooldown=False,
        guild=guild,
        current=SimpleNamespace(
            uri=url, title=titulo, album_url=None, album_name=None, playlist_url=None, playlist_name=None
        ),
    )
    bot.music.players[SERVIDOR] = player
    await Music.player_controller(MusicaFalsa(bot), inter, PlayerControls.add_favorite)
    return inter


def gravou(bot):
    return bool(bot.gravacoes)


class TestA4BotaoDoEmbed:
    @pytest.mark.asyncio
    async def test_guarda_grava_o_favorito_abaixo_do_limite_com_o_nome_do_autor_do_embed(self):
        bot = BotDoPlayer(favoritos={f"f{i}": URL for i in range(3)})
        await favoritar_pelo_embed(bot, "Minha musica")
        assert bot.ultimo_global["fav_links"]["Minha musica"] == URL

    @pytest.mark.asyncio
    async def test_a_cota_soma_a_quantidade_com_ela_mesma_e_trava_com_6_favoritos(self):  # MUDA (etapa 2, A4): até 10
        com_cinco = BotDoPlayer(favs=10, favoritos={f"f{i}": URL for i in range(5)})
        await favoritar_pelo_embed(com_cinco, "Sexto")
        assert "Sexto" in com_cinco.ultimo_global["fav_links"]
        com_seis = BotDoPlayer(favs=10, favoritos={f"f{i}": URL for i in range(6)})
        inter = await favoritar_pelo_embed(com_seis, "Setimo")
        assert not gravou(com_seis) and "espaço suficiente" in inter.texto

    @pytest.mark.asyncio
    async def test_o_nome_nao_e_validado_nem_truncado(self):  # MUDA (etapa 3, A4/D3): trunca em 25 e limpa
        titulo = "t" * 60 + "​"
        bot = BotDoPlayer()
        await favoritar_pelo_embed(bot, titulo)
        assert list(bot.ultimo_global["fav_links"]) == [titulo]

    @pytest.mark.asyncio
    async def test_a_url_nao_e_validada(self):  # MUDA (etapa 4, A4): usa a regra de URL
        bot = BotDoPlayer()
        url = "https://exemplo.invalid/" + "x" * 300
        await favoritar_pelo_embed(bot, "Longa", url)
        assert bot.ultimo_global["fav_links"]["Longa"] == url

    @pytest.mark.asyncio
    async def test_sobrescrever_um_nome_existente_tambem_soma_na_cota(self):  # MUDA (etapa 2, A4)
        bot = BotDoPlayer(favs=10, favoritos={f"f{i}": URL for i in range(6)})
        inter = await favoritar_pelo_embed(bot, "f0", "https://exemplo.invalid/outra")
        assert not gravou(bot) and "espaço suficiente" in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("favs", "dono"), [(0, False), (3, True)], ids=["sem_limite", "dono_isento"])
    async def test_guarda_zero_e_dono_ignoram_o_limite(self, favs, dono):
        bot = BotDoPlayer(favs=favs, dono=dono, favoritos={f"f{i}": URL for i in range(8)})
        await favoritar_pelo_embed(bot, "Mais um")
        assert "Mais um" in bot.ultimo_global["fav_links"]

    @pytest.mark.asyncio
    async def test_guarda_sem_embed_a_mensagem_foi_removida(self):
        bot = BotDoPlayer()
        inter = interacao(SimpleNamespace(me=SimpleNamespace()))
        await Music.player_controller(MusicaFalsa(bot), inter, PlayerControls.embed_add_fav)
        assert not gravou(bot) and "embed da mensagem foi removida" in inter.texto


class TestA4SeletorDoPlayer:
    @pytest.mark.asyncio
    async def test_guarda_grava_o_favorito_abaixo_do_limite(self):
        bot = BotDoPlayer(favoritos={"f0": URL})
        await favoritar_pelo_seletor(bot, "Minha musica")
        assert bot.ultimo_global["fav_links"]["Minha musica"] == URL and bot.eventos == ["fav_add"]

    @pytest.mark.asyncio
    async def test_o_nome_e_truncado_com_o_limite_de_url_e_ganha_reticencias(self):  # MUDA (etapa 3, A4/D3): 25
        bot = BotDoPlayer(url_max=90)
        titulo = "t" * 120
        await favoritar_pelo_seletor(bot, titulo)
        assert list(bot.ultimo_global["fav_links"]) == ["t" * 90 + "..."]

    @pytest.mark.asyncio
    async def test_o_limite_de_url_da_configuracao_vira_o_limite_do_nome(self):  # MUDA (etapa 3, A4/D3)
        bot = BotDoPlayer(url_max=40)
        await favoritar_pelo_seletor(bot, "t" * 60)
        assert list(bot.ultimo_global["fav_links"]) == ["t" * 40 + "..."]

    @pytest.mark.asyncio
    async def test_sobrescrever_um_nome_existente_com_a_lista_cheia_e_recusado(self):  # MUDA (etapa 2, A4)
        bot = BotDoPlayer(favs=3, favoritos={"f0": URL, "f1": URL, "f2": URL})
        inter = await favoritar_pelo_seletor(bot, "f0", "https://exemplo.invalid/outra")
        assert not gravou(bot) and "espaço suficiente" in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_a_cota_do_seletor_e_exata_ao_contrario_do_botao_do_embed(self):
        cabe = BotDoPlayer(favs=10, favoritos={f"f{i}": URL for i in range(9)})
        await favoritar_pelo_seletor(cabe, "Décimo")
        assert "Décimo" in cabe.ultimo_global["fav_links"]
        cheio = BotDoPlayer(favs=10, favoritos={f"f{i}": URL for i in range(10)})
        await favoritar_pelo_seletor(cheio, "Décimo primeiro")
        assert not gravou(cheio)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("favs", "dono"), [(0, False), (3, True)], ids=["sem_limite", "dono_isento"])
    async def test_guarda_zero_e_dono_ignoram_o_limite(self, favs, dono):
        bot = BotDoPlayer(favs=favs, dono=dono, favoritos={f"f{i}": URL for i in range(8)})
        await favoritar_pelo_seletor(bot, "Mais um")
        assert "Mais um" in bot.ultimo_global["fav_links"]

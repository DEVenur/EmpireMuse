"""2.1.2 (E) — o ``change_skin`` REAL usa as funções novas: a embed do seletor é a ``skin_selector_description`` das skins embutidas de verdade
e as linhas do resumo pós-seleção (Normal, Song Request, Global) levam o mesmo link embutido; nomes hostis não quebram o link.

As skins são as dos módulos reais (``normal_player``/``static_player``); só o Discord, o banco e a tela de escolha são dublês.
"""

import os
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from empiremuse.cogs import music_settings
from empiremuse.cogs.music_settings import MusicSettings
from tests.persistence.test_formato_skin import BotDeSkins, Jogador
from tests.support.formatos_reais import SERVIDOR

pytestmark = pytest.mark.critical

LIMITE_DA_DESCRICAO = 4096  # embed do Discord
PASTA_DAS_SKINS = Path(music_settings.__file__).resolve().parent.parent / "utils" / "music" / "skins"


def skins_reais(pasta: str) -> dict[str, Any]:
    carregadas = {}
    for arquivo in sorted(os.listdir(PASTA_DAS_SKINS / pasta)):
        if arquivo.endswith(".py"):
            nome = arquivo[:-3]
            carregadas[nome] = import_module(f"empiremuse.utils.music.skins.{pasta}.{nome}").load()
    return carregadas


NORMAIS = skins_reais("normal_player")
FIXAS = skins_reais("static_player")


def esperado(skins: dict[str, Any], nome: str) -> str:
    return music_settings.skin_link(skins, nome)


async def rodar(
    *, nova: str, nova_fixa: str, atual: str = "classic", atual_fixa: str = "classic", global_: bool = False
) -> SimpleNamespace:
    """Roda o ``change_skin`` com a escolha feita; devolve a embed mostrada e os textos enviados depois."""
    jogador = Jogador(skin=atual, skin_static=atual_fixa)
    bot = BotDeSkins(
        {
            "custom_skins": {},
            "custom_skins_static": {},
            "global_skin": False,
            "player_skin": "",
            "player_skin_static": "",
        },
        [jogador],
    )
    jogador.bot = bot
    bot.player_skins, bot.player_static_skins = dict(NORMAIS), dict(FIXAS)
    bot.pool.default_skin = bot.pool.default_static_skin = "classic"
    bot.config["IGNORE_STATIC_SKINS"] = ""
    guild_data = {"player_controller": {"skin": atual, "static_skin": atual_fixa}}

    async def get_data(*_a: Any, **_k: Any) -> dict[str, Any]:
        return guild_data

    async def update_data(*_a: Any, **_k: Any) -> None:
        return None

    bot.get_data, bot.update_data = get_data, update_data
    bot.get_guild = lambda guild_id: SimpleNamespace(id=guild_id, me=SimpleNamespace())
    bot.user.display_avatar = SimpleNamespace(
        with_format=lambda _f: SimpleNamespace(url="https://exemplo.invalid/b.png"), url="https://exemplo.invalid/b.png"
    )
    resultado = SimpleNamespace(embed_inicial=None, textos=[])

    async def registrar(conteudo: object = None, **kwargs: Any) -> None:
        embed = kwargs.get("embed")
        resultado.textos.append(str(embed.description if embed is not None else conteudo or ""))

    async def aguardar(*_a: Any, **_k: Any) -> None:
        return None

    class TelaDeEscolha:
        def __init__(self, _inter: Any, embed: Any, *_resto: Any, **_k: Any) -> None:
            resultado.embed_inicial = embed
            self.skin_selected, self.static_skin_selected, self.global_mode = nova, nova_fixa, global_
            self.interaction = SimpleNamespace(
                guild_id=SERVIDOR,
                response=SimpleNamespace(defer=aguardar, is_done=lambda: True),
                author=SimpleNamespace(mention="<@900>"),
                edit_original_message=registrar,
                send=registrar,
            )
            self.children = []

        async def wait(self) -> None:
            return None

    async def selecionar_bot(interaction: Any, return_new: bool = False) -> tuple[Any, Any]:
        return interaction, bot

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(music_settings, "SkinSelector", TelaDeEscolha)
        mp.setattr(music_settings, "select_bot_pool", selecionar_bot)
        mp.setattr(music_settings, "update_inter", lambda *_a, **_k: None)
        mp.setattr(music_settings, "asyncio", SimpleNamespace(sleep=aguardar))
        cog = MusicSettings.__new__(MusicSettings)
        cog.bot = bot
        interaction = SimpleNamespace(
            guild_id=SERVIDOR,
            guild=SimpleNamespace(id=SERVIDOR),
            author=SimpleNamespace(mention="<@900>"),
            response=SimpleNamespace(defer=aguardar, is_done=lambda: True),
            edit_original_message=registrar,
            send=registrar,
        )
        await MusicSettings.change_skin.callback(cog, interaction)
    resultado.resumo = "\n".join(resultado.textos)
    return resultado


class TestAsSkinsReais:
    def test_there_are_ten_normal_and_five_static_built_in_skins(self) -> None:
        assert len(NORMAIS) == 10 and len(FIXAS) == 5

    def test_the_real_description_fits_the_embed_limit(self) -> None:
        texto = music_settings.skin_selector_description(NORMAIS, list(NORMAIS), FIXAS, list(FIXAS))

        assert len(texto) <= LIMITE_DA_DESCRICAO

    def test_every_real_row_is_short_and_every_real_skin_is_a_link(self) -> None:
        texto = music_settings.skin_selector_description(NORMAIS, list(NORMAIS), FIXAS, list(FIXAS))

        for linha in texto.splitlines():
            assert len(linha) <= 600 and linha.count("](<") <= music_settings.SKIN_LINKS_PER_ROW
        for nome in NORMAIS:
            assert esperado(NORMAIS, nome) in texto
        for nome in FIXAS:
            assert esperado(FIXAS, nome) in texto


class TestEmbedDoSeletor:
    @pytest.mark.asyncio
    async def test_the_selector_embed_is_the_new_description_of_the_built_in_skins(self) -> None:
        r = await rodar(nova="classic", nova_fixa="classic")

        assert r.embed_inicial.description == music_settings.skin_selector_description(
            NORMAIS, list(NORMAIS), FIXAS, list(FIXAS)
        )
        assert "```" not in r.embed_inicial.description and len(r.embed_inicial.description) <= LIMITE_DA_DESCRICAO


class TestResumoPosSelecao:
    @pytest.mark.asyncio
    async def test_the_normal_and_song_request_lines_carry_the_same_embedded_link(self) -> None:
        r = await rodar(nova="mini", nova_fixa="embed_link")

        assert f"Modo Normal: {esperado(NORMAIS, 'mini')}\n" in r.resumo
        assert f"Song Request: {esperado(FIXAS, 'embed_link')}\n" in r.resumo
        assert "`" not in r.textos[-1]

    @pytest.mark.asyncio
    async def test_the_global_lines_carry_the_same_embedded_link(self) -> None:
        r = await rodar(nova="lite", nova_fixa="default", global_=True)

        assert f"Global - Modo Normal: {esperado(NORMAIS, 'lite')}\n" in r.resumo
        assert f"Global - Song Request: {esperado(FIXAS, 'default')}\n" in r.resumo

    @pytest.mark.asyncio
    async def test_an_unchanged_skin_has_no_line(self) -> None:
        r = await rodar(nova="classic", nova_fixa="default", atual="classic", atual_fixa="classic")

        resumo = r.textos[-1]
        assert "Modo Normal:" not in resumo and f"Song Request: {esperado(FIXAS, 'default')}" in resumo


class TestNomeHostil:
    @pytest.mark.parametrize(
        "nome", ["a](<https://x.invalid>)b", "**x**", "@everyone", "<@1>", "[y]", "_u_", "||s||", "`c`", "~~r~~"]
    )
    def test_the_label_cannot_close_the_link_or_inject_markdown(self, nome: str) -> None:
        link = music_settings.skin_link({nome: SimpleNamespace(preview="https://ok.invalid/p.png")}, nome)

        assert link.endswith("](<https://ok.invalid/p.png>)") and link.startswith("[")
        rotulo = link[1 : link.rindex("](<")]
        assert "](" not in rotulo and "`" not in link
        assert link.count("](<") == 1

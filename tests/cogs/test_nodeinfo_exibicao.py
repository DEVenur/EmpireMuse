"""Teste do dono em produção 2.1.1, partes B e C (``!nodeinfo``) — região do nó e heap da JVM.

VB1 o LOCAL exibe "Local" e perde a chave ``region`` (o padrão ``us_central`` segue dentro do nó); um remoto com ``region`` exibe o texto do dono,
sem ``.title()``, e sem ``region`` não tem a linha. VB2 (V-T4) ``region_label`` só é ``str`` e o campo limita a região; VC1 os rótulos falam de "Heap Java"
e nunca só "RAM", em MiB. Sem Discord, rede ou Lavalink: nós, bot e interação são dublês.
"""

import re
from types import SimpleNamespace

import pytest

import empiremuse.cogs.music_settings as music_settings
from tests.support.drivers_de_regras import InteracaoFalsa

pytestmark = pytest.mark.critical

SERVIDOR = 31


# ============================================================================ nós e bot


def estatisticas() -> SimpleNamespace:
    return SimpleNamespace(
        memory_used=52_428_800,  # 50,0 MiB
        memory_free=73_924_608,  # 70,5 MiB
        memory_allocated=126_353_408,  # 120,5 MiB
        memory_reservable=536_870_912,  # 512,0 MiB
        cpu_cores=4,
        lavalink_load=0.1,
        players=0,
        playing_players=0,
        uptime=3_600_000,
    )


def no(identificador: str, *, regiao: str = "us_central", rotulo: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        identifier=identificador,
        stats=estatisticas(),
        is_available=True,
        players={},
        version="4.0.8",
        website="",
        region=regiao,
        region_label=rotulo,
    )


class InteracaoDoNodeinfo(InteracaoFalsa):
    def __init__(self) -> None:
        super().__init__(guild_id=SERVIDOR)
        self.embeds = []

    async def send(self, *args: object, **kwargs: object) -> None:
        if kwargs.get("embed") is not None:
            self.embeds.append(kwargs["embed"])
        await super().send(*args, **kwargs)


async def campos_do_nodeinfo(monkeypatch: pytest.MonkeyPatch, *nos: SimpleNamespace) -> list:
    bot = SimpleNamespace(
        get_guild=lambda _: None,
        get_color=lambda *a: 0,
        music=SimpleNamespace(nodes={n.identifier: n for n in nos}),
        user=SimpleNamespace(
            id=7,
            display_avatar=SimpleNamespace(with_format=lambda f: SimpleNamespace(url="https://exemplo.invalid/a.png")),
        ),
    )
    inter = InteracaoDoNodeinfo()

    async def escolher(interaction: InteracaoFalsa, **kwargs: object) -> tuple[InteracaoFalsa, SimpleNamespace]:
        return interaction, bot

    monkeypatch.setattr(music_settings, "select_bot_pool", escolher)
    cog = music_settings.MusicSettings(bot)
    await music_settings.MusicSettings.nodeinfo.callback(self=cog, interaction=inter)
    return [f for embed in inter.embeds for f in embed.fields]


def valor_do_no(campos: list, identificador: str) -> str:
    return next(f.value for f in campos if f.name.startswith(f"**{identificador}**"))


# ============================================================================ VB1 — exibição da região


class TestRegiaoNoNodeinfo:
    @pytest.mark.asyncio
    async def test_the_local_node_shows_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        campos = await campos_do_nodeinfo(monkeypatch, no("LOCAL"))

        valor = valor_do_no(campos, "LOCAL")
        assert "Região: `Local`" in valor and "us_central" not in valor.lower()


class TestRegiaoGigante:
    """V-T4 — a ``region`` também vem da lista externa (``LAVALINK_SERVER_LIST``)."""

    @pytest.mark.asyncio
    async def test_backticks_in_the_region_cannot_close_the_code_span(self, monkeypatch: pytest.MonkeyPatch) -> None:
        campos = await campos_do_nodeinfo(monkeypatch, no("CRASES", regiao="x", rotulo="a`b**c"))

        (conteudo,) = re.findall(r"Região: `([^`]*)`\n", valor_do_no(campos, "CRASES"))
        assert conteudo.startswith("a") and conteudo.endswith("c")

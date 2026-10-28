"""Teste do dono em produção 2.1.1, partes B e C (``!nodeinfo``) — região do nó e heap da JVM.

VB1 o LOCAL exibe "Local" e perde a chave ``region`` (o padrão ``us_central`` segue dentro do nó); um remoto com ``region`` exibe o texto do dono,
sem ``.title()``, e sem ``region`` não tem a linha. VB2 (V-T4) ``region_label`` só é ``str`` e o campo limita a região; VC1 os rótulos falam de "Heap Java"
e nunca só "RAM", em MiB. Sem Discord, rede ou Lavalink: nós, bot e interação são dublês.
"""

import re
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import empiremuse.cogs.music_settings as music_settings
from empiremuse.music_cog.nodes import NodesMixin
from empiremuse.utils.client import BotPool
from tests.support.drivers_de_regras import InteracaoFalsa

pytestmark = pytest.mark.critical

SERVIDOR = 31
REGIAO_GIGANTE = "r" * 2000
LIMITE_DO_CAMPO = 1024
LIMITE_DA_REGIAO = 32 + len(
    "..."
)  # ``md_code(..., limit=32)``: o corte de 32 mais as reticências do ``fix_characters``


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

    @pytest.mark.asyncio
    async def test_a_remote_node_shows_the_owner_text_without_title_case(self, monkeypatch: pytest.MonkeyPatch) -> None:
        campos = await campos_do_nodeinfo(monkeypatch, no("REMOTO", regiao="brazil", rotulo="brazil"))

        assert "Região: `brazil`" in valor_do_no(campos, "REMOTO")

    @pytest.mark.asyncio
    async def test_a_remote_node_without_a_region_has_no_region_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        campos = await campos_do_nodeinfo(monkeypatch, no("SEMREGIAO"))

        assert "Região" not in valor_do_no(campos, "SEMREGIAO")


class TestRegiaoGigante:
    """V-T4 — a ``region`` também vem da lista externa (``LAVALINK_SERVER_LIST``)."""

    @pytest.mark.asyncio
    async def test_the_region_is_cut_in_the_field_and_the_field_stays_within_1024(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        campos = await campos_do_nodeinfo(monkeypatch, no("GIGANTE", regiao="x", rotulo=REGIAO_GIGANTE))

        valor = valor_do_no(campos, "GIGANTE")
        (conteudo,) = re.findall(r"Região: `([^`]*)`", valor)
        assert conteudo.startswith("r" * 32) and len(conteudo) <= LIMITE_DA_REGIAO and len(valor) <= LIMITE_DO_CAMPO
        assert REGIAO_GIGANTE not in valor

    @pytest.mark.asyncio
    async def test_backticks_in_the_region_cannot_close_the_code_span(self, monkeypatch: pytest.MonkeyPatch) -> None:
        campos = await campos_do_nodeinfo(monkeypatch, no("CRASES", regiao="x", rotulo="a`b**c"))

        (conteudo,) = re.findall(r"Região: `([^`]*)`\n", valor_do_no(campos, "CRASES"))
        assert conteudo.startswith("a") and conteudo.endswith("c")


# ============================================================================ VB1/VB2 — o que o nó recebe


def pool_de_nos() -> BotPool:
    pool = BotPool.__new__(BotPool)
    pool.config = {
        "PREFER_YOUTUBE_NATIVE_PLAYBACK": False,
        "ONLY_USE_NATIVE_SEARCH_PROVIDERS": False,
        "SEARCH_PROVIDERS": "",
    }
    pool.loop = MagicMock()
    pool.loop.create_task.side_effect = lambda corotina: corotina.close()
    pool.check_node = MagicMock(return_value=MagicMock())
    return pool


def dados_dos_nos(pool: BotPool) -> dict:
    return {c.args[0]["identifier"]: c.args[0] for c in pool.check_node.call_args_list}


class TestNoLocalNaoTemRegiao:
    def test_the_embedded_local_node_has_no_region_key(self) -> None:
        pool = pool_de_nos()

        pool.node_check({}, start_local=True)

        assert "region" not in dados_dos_nos(pool)["LOCAL"]

    def test_a_remote_node_from_the_server_list_keeps_its_region(self) -> None:
        pool = pool_de_nos()
        remoto = {"identifier": "R1", "host": "h", "port": 1, "password": "p", "region": "brazil"}

        pool.node_check({"R1": remoto}, start_local=False)

        assert dados_dos_nos(pool)["R1"]["region"] == "brazil"


class Servidor:
    """O que o ``connect_node`` pede ao ``bot.music``: devolve o nó que ``initiate_node`` criaria."""

    def __init__(self) -> None:
        self.no = SimpleNamespace(connect=AsyncMock())
        self.initiate_node = AsyncMock(return_value=self.no)
        self.nodes = {}


async def conectar(**dados: object) -> Servidor:
    servidor = Servidor()
    cog = SimpleNamespace(bot=SimpleNamespace(music=servidor))
    base = {"identifier": "N1", "host": "h", "port": 1, "password": "p", "info": {}}
    await NodesMixin.connect_node(cog, deepcopy({**base, **dados}))
    return servidor


class TestRotuloDaRegiaoNoNo:
    @pytest.mark.asyncio
    async def test_the_owner_text_goes_to_the_label_and_the_internal_region_is_unchanged(self) -> None:
        servidor = await conectar(region="brazil")

        assert servidor.no.region_label == "brazil"
        assert servidor.initiate_node.await_args.kwargs["region"] == "brazil"

    @pytest.mark.asyncio
    async def test_without_a_region_the_label_is_none_and_the_internal_default_stays(self) -> None:
        servidor = await conectar()

        assert servidor.no.region_label is None
        assert servidor.initiate_node.await_args.kwargs["region"] == "us_central"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "regiao", [123, ["brazil"], {"a": 1}, None, 1.5], ids=["int", "lista", "dict", "none", "float"]
    )
    async def test_a_region_that_is_not_a_string_gives_no_label(self, regiao: object) -> None:
        servidor = await conectar(region=regiao)

        assert servidor.no.region_label is None

    @pytest.mark.asyncio
    async def test_a_2000_character_region_is_kept_as_text_for_the_display_to_cut(self) -> None:
        servidor = await conectar(region=REGIAO_GIGANTE)

        assert isinstance(servidor.no.region_label, str)


# ============================================================================ VC1 — heap da JVM


class TestHeapNoNodeinfo:
    @pytest.mark.asyncio
    async def test_the_labels_say_heap_java_with_binary_sizes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        campos = await campos_do_nodeinfo(monkeypatch, no("N1", rotulo="brazil"))

        valor = valor_do_no(campos, "N1")
        assert "Heap Java (usado/livre): `50,0 MiB / 70,5 MiB`" in valor
        assert "Heap Java alocado: `120,5 MiB`" in valor
        assert "Heap Java máximo: `512,0 MiB`" in valor

    @pytest.mark.asyncio
    async def test_no_line_says_only_ram_and_no_size_is_decimal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        campos = await campos_do_nodeinfo(monkeypatch, no("N1", rotulo="brazil"))

        valor = valor_do_no(campos, "N1")
        assert "RAM" not in valor and " MB" not in valor and "GB" not in valor

    @pytest.mark.asyncio
    async def test_the_other_lines_stay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        campos = await campos_do_nodeinfo(monkeypatch, no("N1"))

        valor = valor_do_no(campos, "N1")
        assert "CPU Cores" in valor and "Uso de CPU" in valor and "Versão do Lavalink" in valor and "Uptime" in valor

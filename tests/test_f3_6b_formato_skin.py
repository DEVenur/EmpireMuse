"""F3-6b, etapa 0 — caracterização das skins personalizadas do servidor no formato ATUAL (sem produção alterada).

Uma skin é o dicionário do editor (``message_data``). Hoje fica no documento global do servidor como TEXTO
(``base64`` de ``pickle``, sem ``zlib``) em ``custom_skins`` (modo normal) e ``custom_skins_static`` (song-request).
Os leitores (``SkinEditorMenu.load_skin``, o laço depois de salvar no ``SkinEditorMenu.modal_handler``,
``MusicSettings.change_skin`` e ``Music.create_player``) só convertem o texto em dicionário na memória e já aceitam o
dicionário pronto; o gravador é o ``modal_handler`` do botão de salvar.

* o que continua valendo depois da migração: os leitores entregam ao player o MESMO dicionário, venha o dado como
  texto legado (protocolos 4 e 5; os mais antigos viram recusa, em ``tests/test_f3_6b_etapa2b_pontos.py``) ou como dicionário (``TestLeitores``, ``TestEditorSalvaESegue``);
* a etapa 3 troca o formato GRAVADO (texto → dicionário): os testes dela estão em ``tests/test_f3_6b_etapa3_*.py``.
"""

import base64
import copy
import pickle
from types import SimpleNamespace

import pytest

from empiremuse.cogs import music_settings
from empiremuse.cogs.music import Music
from empiremuse.cogs.music_settings import MusicSettings
from empiremuse.utils.music import interactions
from empiremuse.utils.music.interactions import SkinEditorMenu, base_skin
from tests.helpers_f3_6b import SERVIDOR


def skin_realista(**mudancas) -> dict:
    """A skin padrão do editor mais um embed montado pelo editor (campos, autor, rodapé, imagem, miniatura, cor)."""
    skin = copy.deepcopy(base_skin)
    skin["content"] = "Tocando agora: {track.title}"
    skin["controller_enabled"] = False
    skin["embeds"].append(
        {
            "title": "Título do embed",
            "description": "Descrição com **negrito** e `código`",
            "color": "ff0000",
            "fields": [
                {"name": "Campo 1", "value": "Valor 1", "inline": True},
                {"name": "Campo 2", "value": "Valor 2"},
            ],
            "author": {"name": "Autor", "icon_url": "https://exemplo.invalid/a.png"},
            "footer": {"text": "Rodapé", "icon_url": "https://exemplo.invalid/r.png"},
            "image": {"url": "{track.thumb}"},
            "thumbnail": {"url": "https://exemplo.invalid/t.png"},
        }
    )
    skin.update(mudancas)
    return skin


def texto_legado(skin: dict, protocolo: int = 4) -> str:
    """O que o gravador de hoje põe no documento: ``base64`` de ``pickle`` (sem ``zlib``)."""
    return base64.b64encode(pickle.dumps(skin, protocol=protocolo)).decode("utf-8")


class Jogador:
    """Só o que os leitores de skin pedem ao ``LavalinkPlayer`` depois de converter as skins."""

    def __init__(self, *, estatico=False, skin="default", skin_static="default"):
        self.static, self.skin, self.skin_static = estatico, skin, skin_static
        self.custom_skin_data, self.custom_skin_static_data = None, None
        self.controller_mode = False
        self.guild = SimpleNamespace(me=SimpleNamespace(voice=None))
        self.chamadas = []

    def setup_features(self):
        self.chamadas.append("setup_features")

    def setup_hints(self):
        self.chamadas.append("setup_hints")

    def process_hint(self):
        self.chamadas.append("process_hint")

    def set_command_log(self, **kwargs):
        self.chamadas.append("set_command_log")

    async def destroy_message(self):
        self.chamadas.append("destroy_message")

    async def invoke_np(self, **kwargs):
        self.chamadas.append("invoke_np")


class BotDeSkins:
    def __init__(self, global_data, jogadores=()):
        self.global_data = global_data  # o cache do banco: ``get_global_data`` devolve esta MESMA referência
        self.salvos = []  # uma cópia de cada documento gravado
        self.escritas = []  # ``(id_, db_name)`` de cada gravação
        self.banco = None  # o que foi persistido na última gravação (cópia): é o que sobrevive a um reinício
        self.music = SimpleNamespace(players={SERVIDOR: jogador for jogador in list(jogadores)[:1]})
        self.pool = SimpleNamespace(get_guild_bots=lambda guild_id: [self], guild_prefix_cache={})
        self.config = {"DEFAULT_PREFIX": "!!", "IGNORE_SKINS": "", "IGNORE_STATIC_SKINS": ""}
        self.user = SimpleNamespace(
            id=1,
            display_avatar=SimpleNamespace(
                with_format=lambda formato: SimpleNamespace(url="https://exemplo.invalid/b.png")
            ),
        )

    async def get_global_data(self, id_, *, db_name):
        return self.global_data

    async def update_global_data(self, id_, data, *, db_name):
        self.escritas.append((id_, db_name))
        self.banco = copy.deepcopy(data)
        self.global_data = (
            data  # ``empiremuse/utils/db.py`` faz ``cache[chave] = data``: o cache passa a ser o objeto gravado
        )
        self.salvos.append(copy.deepcopy(data))

    def get_global_command_named(self, *args, **kwargs):
        return None

    def get_color(self, *args):
        return 0


def dados_globais(normais=None, estaticas=None):
    return {"custom_skins": dict(normais or {}), "custom_skins_static": dict(estaticas or {})}


# ============================================================================ o editor (gravador e leitor da skin escolhida)


class InteracaoDoEditor:
    author = SimpleNamespace(
        id=900
    )  # o editor guarda a última interação como ``ctx`` e o botão de salvar lê ``ctx.author``

    def __init__(self, **text_values):
        self.text_values = text_values
        self.custom_id = "skin_editor_save"
        self.guild_id = SERVIDOR
        self.enviados = []
        self.response = SimpleNamespace(defer=self._defer, is_done=lambda: True)

    async def _defer(self, **kwargs):
        return None

    async def send(self, content=None, **kwargs):
        self.enviados.append(content)

    async def edit_original_message(self, content=None, **kwargs):
        self.enviados.append(content)


class ContextoDoEditor(InteracaoDoEditor):
    author = SimpleNamespace(id=900)


class BotaoDeModo:
    """Substitui o ``SkinSettingsButton``: o dono escolhe o modo de imediato e sem passar pela tela."""

    modo = "custom_skins"

    def __init__(self, user, *args, **kwargs):
        self.mode, self.inter, self.controller_enabled = type(self).modo, None, True

    async def wait(self):
        return None


@pytest.fixture
def editor_sem_tela(monkeypatch):
    """Editor REAL (``SkinEditorMenu``) sem as partes de tela que não importam aqui (escolha de modo e reenvio)."""

    async def atualizar(self, inter):
        return None

    monkeypatch.setattr(interactions, "SkinSettingsButton", BotaoDeModo)
    monkeypatch.setattr(SkinEditorMenu, "update_message", atualizar)
    monkeypatch.setattr(SkinEditorMenu, "build_embeds", lambda self: {"embed": None})

    def montar(global_data, jogadores=()):
        bot = BotDeSkins(global_data, jogadores)
        contexto = ContextoDoEditor()
        servidor = SimpleNamespace(id=SERVIDOR, me=SimpleNamespace(color=SimpleNamespace(value=0)))
        return SkinEditorMenu(contexto, bot, servidor, global_data), bot, contexto

    return montar


class TestEditorSalvaESegue:
    @pytest.mark.asyncio
    async def test_salvar_grava_a_skin_no_modo_escolhido_e_no_banco(self, editor_sem_tela):
        dados = dados_globais(estaticas={"Fixa": texto_legado(skin_realista())})
        menu, bot, _ = editor_sem_tela(dados)
        menu.message_data = skin_realista(content="Outro texto")
        BotaoDeModo.modo = "custom_skins"
        await menu.modal_handler(InteracaoDoEditor(skin_name="  Minha skin  "))
        assert 1 <= len(bot.salvos) <= 2  # a migração da skin legada pode gravar antes da skin salva
        assert list(bot.salvos[-1]["custom_skins"]) == ["Minha skin"]
        assert list(bot.salvos[-1]["custom_skins_static"]) == ["Fixa"]

    @pytest.mark.asyncio
    async def test_a_skin_gravada_volta_igual_pelo_leitor_do_editor(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = skin_realista()
        BotaoDeModo.modo = "custom_skins_static"
        await menu.modal_handler(InteracaoDoEditor(skin_name="Fixa"))
        novo, _, _ = editor_sem_tela(bot.salvos[-1])
        await novo.load_skin(SimpleNamespace(values=["> css: Fixa"]))
        assert novo.message_data == skin_realista()

    @pytest.mark.asyncio
    async def test_renomear_remove_o_nome_antigo(self, editor_sem_tela):
        dados = dados_globais(normais={"Antiga": texto_legado(skin_realista()), "Outra": texto_legado(skin_realista())})
        menu, bot, _ = editor_sem_tela(dados)
        menu.message_data, menu.skin_selected = skin_realista(), "> cs: Antiga"
        BotaoDeModo.modo = "custom_skins"
        await menu.modal_handler(InteracaoDoEditor(skin_name="Nova"))
        assert sorted(bot.salvos[-1]["custom_skins"]) == ["Nova", "Outra"]

    @pytest.mark.asyncio
    async def test_o_player_ativo_recebe_as_skins_como_dicionarios_inclusive_as_legadas(self, editor_sem_tela):
        legada = skin_realista(content="legada")
        dados = dados_globais(normais={"Velha": texto_legado(legada, 4)})
        jogador = Jogador()
        menu, _, _ = editor_sem_tela(dados, [jogador])
        menu.message_data = skin_realista(content="nova")
        BotaoDeModo.modo = "custom_skins"
        await menu.modal_handler(InteracaoDoEditor(skin_name="Nova"))
        assert jogador.custom_skin_data["Velha"] == legada
        assert jogador.custom_skin_data["Nova"] == skin_realista(content="nova")
        assert jogador.custom_skin_static_data == {}
        assert jogador.chamadas == ["setup_features", "setup_hints", "process_hint"]


class TestEditorConverteTambemAsSkinsDoSongRequest:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [4, 5])
    async def test_o_player_ativo_recebe_as_skins_legadas_do_song_request_como_dicionarios(
        self, editor_sem_tela, protocolo
    ):
        fixa = skin_realista(content="fixa legada")
        dados = dados_globais(estaticas={"Fixa": texto_legado(fixa, protocolo)})
        jogador = Jogador()
        menu, _, _ = editor_sem_tela(dados, [jogador])
        menu.message_data = skin_realista(content="nova")
        BotaoDeModo.modo = "custom_skins"
        await menu.modal_handler(InteracaoDoEditor(skin_name="Nova"))
        assert jogador.custom_skin_static_data == {"Fixa": fixa}
        assert list(jogador.custom_skin_data) == ["Nova"]


# ============================================================================ os leitores


class TestLeitores:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [4, 5])
    @pytest.mark.parametrize(("prefixo", "campo"), [("> cs: ", "custom_skins"), ("> css: ", "custom_skins_static")])
    async def test_load_skin_converte_o_texto_legado_nos_protocolos_4_e_5(
        self, editor_sem_tela, protocolo, prefixo, campo
    ):
        skin = skin_realista()
        dados = dados_globais(
            **{"normais" if campo == "custom_skins" else "estaticas": {"Minha": texto_legado(skin, protocolo)}}
        )
        menu, _, _ = editor_sem_tela(dados)
        await menu.load_skin(SimpleNamespace(values=[f"{prefixo}Minha"]))
        assert menu.message_data == skin and menu.mode == "editor" and menu.skin_selected == f"{prefixo}Minha"

    @pytest.mark.asyncio
    async def test_load_skin_aceita_o_dicionario_pronto(self, editor_sem_tela):
        skin = skin_realista()
        menu, _, _ = editor_sem_tela(dados_globais(normais={"Minha": skin}))
        await menu.load_skin(SimpleNamespace(values=["> cs: Minha"]))
        assert menu.message_data == skin

    @pytest.mark.asyncio
    @pytest.mark.parametrize("vazia", [{}, None, ""], ids=["dict", "none", "texto-vazio"])
    async def test_load_skin_de_skin_vazia_usa_a_skin_padrao_do_editor(self, editor_sem_tela, vazia):
        menu, _, _ = editor_sem_tela(dados_globais(normais={"Vazia": vazia}))
        await menu.load_skin(SimpleNamespace(values=["> cs: Vazia"]))
        assert menu.message_data == base_skin and menu.message_data is not base_skin

    @pytest.mark.asyncio
    async def test_load_skin_sem_prefixo_conhecido_comeca_da_skin_padrao(self, editor_sem_tela):
        menu, _, _ = editor_sem_tela(dados_globais())
        await menu.load_skin(SimpleNamespace(values=["default"]))
        assert menu.message_data == base_skin

    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [4, 5])
    async def test_create_player_entrega_as_skins_como_dicionarios(self, protocolo):
        normal, fixa = skin_realista(content="normal"), skin_realista(content="fixa")
        dados = {
            "custom_skins": {"N": texto_legado(normal, protocolo), "D": skin_realista(content="dict")},
            "custom_skins_static": {"F": texto_legado(fixa, protocolo)},
            "global_skin": False,
            "listen_along_invites": {},
            "prefix": "",
            "voice_channel_status": "",
        }
        recebidos = await chamar_create_player(dados)
        assert recebidos["custom_skin_data"] == {"N": normal, "D": skin_realista(content="dict")}
        assert recebidos["custom_skin_static_data"] == {"F": fixa}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [4, 5])
    async def test_change_skin_entrega_as_skins_como_dicionarios_ao_player_ativo(self, monkeypatch, protocolo):
        normal, fixa = skin_realista(content="normal"), skin_realista(content="fixa")
        dados = {
            "custom_skins": {"N": texto_legado(normal, protocolo)},
            "custom_skins_static": {"F": texto_legado(fixa, protocolo)},
            "global_skin": False,
            "player_skin": "",
            "player_skin_static": "",
        }
        jogador = await chamar_change_skin(monkeypatch, dados, nova_skin="> custom_skin: N")
        assert jogador.custom_skin_data == {"N": normal} and jogador.custom_skin_static_data == {"F": fixa}
        assert jogador.skin == "> custom_skin: N" and "invoke_np" in jogador.chamadas

    @pytest.mark.asyncio
    async def test_change_skin_nao_mexe_no_player_que_ja_usa_a_skin_escolhida(self, monkeypatch):
        dados = {
            "custom_skins": {"N": texto_legado(skin_realista())},
            "custom_skins_static": {},
            "global_skin": False,
            "player_skin": "",
            "player_skin_static": "",
        }
        jogador = await chamar_change_skin(
            monkeypatch, dados, nova_skin="> custom_skin: N", skin_atual="> custom_skin: N"
        )
        assert jogador.custom_skin_data is None and jogador.chamadas == []


# ============================================================================ os dublês de create_player e change_skin


class Parou(Exception):
    def __init__(self, argumentos):
        self.argumentos = argumentos


async def chamar_create_player(global_data, escritas: list | None = None) -> dict:
    """Roda o ``Music.create_player`` REAL até o ``get_player`` e devolve o que ele recebeu.

    ``escritas`` (opcional) recebe ``(id_, cópia do documento, db_name)`` de cada ``update_global_data``.
    """

    def get_player(**kwargs):
        raise Parou(kwargs)

    guild_data = {
        "player_controller": {"skin": "default", "static_skin": "default", "channel": None, "message_id": None},
        "enable_restrict_mode": False,
        "autoplay": False,
        "default_player_volume": 100,
    }

    async def get_global_data(*args, **kwargs):
        return global_data

    async def update_global_data(id_=None, data=None, *, db_name=None, **kwargs):
        if escritas is not None:
            escritas.append((id_, copy.deepcopy(data), db_name))

    bot = SimpleNamespace(
        music=SimpleNamespace(players={}, get_player=get_player),
        pool=SimpleNamespace(check_skin=lambda skin: skin, check_static_skin=lambda skin: skin),
        get_global_data=get_global_data,
        update_global_data=update_global_data,
        default_prefix="!!",
    )
    cog = Music.__new__(Music)
    cog.bot, cog.extra_hints = bot, []
    inter = SimpleNamespace(
        guild_id=SERVIDOR, author=SimpleNamespace(id=900, voice=None), guild=SimpleNamespace(id=SERVIDOR)
    )
    guild = SimpleNamespace(id=SERVIDOR, me=SimpleNamespace())
    node = SimpleNamespace(identifier="no")
    with pytest.raises(Parou) as parada:
        await cog.create_player(inter, bot, guild, None, guild_data=guild_data, node=node)
    return parada.value.argumentos


async def chamar_change_skin(monkeypatch, global_data, *, nova_skin, skin_atual="default") -> Jogador:
    """Roda o ``MusicSettings.change_skin`` REAL com a escolha da tela já feita; devolve o player ativo.

    Tudo que o comando diz ao dono (texto e embeds, enviados ou editados) fica em ``jogador.mensagens``.
    """
    jogador = Jogador(skin=skin_atual)
    jogador.mensagens = mensagens = []

    async def registrar(conteudo=None, **kwargs):
        mensagens.append(str(conteudo or ""))
        embed = kwargs.get("embed")
        if embed is not None:
            mensagens.append(str(embed.description or ""))

    bot = BotDeSkins(global_data, [jogador])
    jogador.bot = bot
    bot.player_skins = {"default": SimpleNamespace(preview="https://exemplo.invalid/p")}
    bot.player_static_skins = {"default": SimpleNamespace(preview="https://exemplo.invalid/p")}
    bot.pool.default_skin = bot.pool.default_static_skin = "default"
    guild_data = {"player_controller": {"skin": skin_atual, "static_skin": "default"}}

    async def get_data(*args, **kwargs):
        return guild_data

    async def update_data(*args, **kwargs):
        return None

    bot.get_data, bot.update_data = get_data, update_data
    bot.get_guild = lambda guild_id: SimpleNamespace(id=guild_id, me=SimpleNamespace())

    class TelaDeEscolha:
        def __init__(self, *args, **kwargs):
            self.skin_selected, self.static_skin_selected = nova_skin, "default"
            self.global_mode = False
            self.interaction = SimpleNamespace(
                guild_id=SERVIDOR,
                response=SimpleNamespace(defer=_aguardar, is_done=lambda: True),
                author=SimpleNamespace(mention="<@900>"),
                edit_original_message=registrar,
                send=registrar,
            )
            self.children = []

        async def wait(self):
            return None

    async def selecionar_bot(interaction, return_new=False):
        return interaction, bot

    monkeypatch.setattr(music_settings, "SkinSelector", TelaDeEscolha)
    monkeypatch.setattr(music_settings, "select_bot_pool", selecionar_bot)
    monkeypatch.setattr(music_settings, "update_inter", lambda *args, **kwargs: None)
    monkeypatch.setattr(music_settings, "asyncio", SimpleNamespace(sleep=_aguardar))
    cog = MusicSettings.__new__(MusicSettings)
    cog.bot = bot
    interaction = SimpleNamespace(
        guild_id=SERVIDOR,
        guild=SimpleNamespace(id=SERVIDOR),
        author=SimpleNamespace(mention="<@900>"),
        response=SimpleNamespace(defer=_aguardar, is_done=lambda: True),
        edit_original_message=registrar,
        send=registrar,
    )
    await MusicSettings.change_skin.callback(cog, interaction)
    return jogador


async def _aguardar(*args, **kwargs):
    return None

"""Drivers de COMPORTAMENTO das regras de comandos e painel (rede de segurança da F3-5b, etapa 0).

Nada aqui lê o texto do código-fonte: cada driver chama o ``callback`` real do comando, do modal ou da view com
dublês de disnake e devolve o que o usuário veria e o que foi gravado. Sem Discord real, sem rede e sem ``.env``.
Os valores falsos são montados em tempo de execução.
"""

import copy
import json
from types import SimpleNamespace

import pytest

import empiremuse.cogs.legacy_cmds as legacy_cmds
from empiremuse.panel.services.account_base import AccountContext
from empiremuse.panel.services.account_links import FavoritesSection, IntegrationsSection
from empiremuse.panel.services.links import LinksForm
from empiremuse.utils.db import DBModel, db_models, global_db_models
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.music.interactions import FavModalAdd, ViewMode
from tests.helpers_modais import SERVIDOR_DO_COMANDO, ModalBot, ModalInteraction, gravados, importar, modal_view

AUTOR = 900


class BotDeComandos:
    """Bot mínimo dos comandos de prefixo, cargos de DJ, skins, volume, status de voz e RPC.

    Os documentos nascem dos modelos REAIS (``db_models``/``global_db_models``) e são o mesmo dict a cada leitura,
    como no ``BaseDB``; cada gravação fica em ``gravacoes`` como ``(escopo, id, cópia)``.
    """

    def __init__(self, *, config=None, dono=False):
        self.config = {
            "EXTRA_HINTS": "",
            "IGNORE_SKINS": "",
            "IGNORE_STATIC_SKINS": "",
            "ENABLE_RPC_COMMAND": True,
            "ENABLE_RPC_AUTH": True,
            "RPC_PUBLIC_URL": "wss://rpc.exemplo.invalid",
            "RPC_SERVER": "",
            **(config or {}),
        }
        self.dono = dono
        self.docs = {}
        self.gravacoes = []
        self.pool = SimpleNamespace(
            guild_prefix_cache={},
            user_prefix_cache={},
            default_skin="classic",
            default_static_skin="simple",
            get_guild_bots=lambda guild_id: [self],
        )
        self.music = SimpleNamespace(players={})
        self.user = SimpleNamespace(id=7, name="Bot", display_name="Bot", mention="<@7>")
        self.default_prefix = "!!"
        self.player_skins = {}
        self.player_static_skins = {}
        self.guilds = {}
        self.cogs = {}

    def _doc(self, id_, db_name, *, escopo):
        modelos = global_db_models if escopo == "global" else db_models
        chave = (escopo, db_name, str(id_))
        if chave not in self.docs:
            self.docs[chave] = copy.deepcopy(modelos[db_name])
        return self.docs[chave]

    def documento(self, escopo, db_name, id_):
        return self._doc(id_, db_name, escopo=escopo)

    async def get_global_data(self, id_, *, db_name):
        return self._doc(id_, db_name, escopo="global")

    async def update_global_data(self, id_, data, *, db_name):
        self.gravacoes.append(("global", str(id_), copy.deepcopy(data)))

    async def get_data(self, id_, *, db_name):
        return self._doc(id_, db_name, escopo="bot")

    async def update_data(self, id_, data, *, db_name):
        self.gravacoes.append(("bot", str(id_), copy.deepcopy(data)))

    async def is_owner(self, user):
        return self.dono

    def get_color(self, *args):
        return 0

    def get_guild(self, guild_id):
        return self.guilds.get(guild_id)

    def get_cog(self, nome):
        return self.cogs.get(nome)

    def get_global_command_named(self, name, cmd_type=None):
        return SimpleNamespace(id=1)

    def is_ready(self):
        return True

    @property
    def ultimo_global(self):
        return next((copia for escopo, _, copia in reversed(self.gravacoes) if escopo == "global"), None)

    @property
    def ultimo_do_bot(self):
        return next((copia for escopo, _, copia in reversed(self.gravacoes) if escopo == "bot"), None)


class ContextoDeComando:
    """``ctx`` de um comando de prefixo: guarda o que foi enviado ao usuário."""

    def __init__(self, bot, *, servidor=SERVIDOR_DO_COMANDO, autor=AUTOR):
        self.bot = bot
        self.guild = SimpleNamespace(id=servidor, me=SimpleNamespace(), name="origem")
        self.guild_id = servidor
        self.author = SimpleNamespace(id=autor, mention=f"<@{autor}>")
        self.enviados = []

    async def send(self, *args, **kwargs):
        embed = kwargs.get("embed")
        self.enviados.append(" ".join(str(a) for a in args) + ((embed.description or "") if embed else ""))

    @property
    def texto(self):
        return "\n".join(self.enviados)


class Resultado(SimpleNamespace):
    """O que o usuário vê (``texto`` ou ``erro``) e o bot que guardou as gravações."""

    @property
    def recusado(self):
        return self.erro is not None


async def executar(bot, comando, *args, servidor=SERVIDOR_DO_COMANDO, autor=AUTOR, **kwargs):
    """Roda ``comando.callback`` do ``legacy_cmds.Owner``; ``GenericError`` vira ``Resultado.erro`` (texto)."""
    ctx = ContextoDeComando(bot, servidor=servidor, autor=autor)
    cog = legacy_cmds.Owner(bot)
    erro = None
    try:
        await comando.callback(cog, ctx, *args, **kwargs)
    except GenericError as falha:
        erro = falha.text
    return Resultado(erro=erro, texto=ctx.texto, bot=bot, ctx=ctx)


# ============================================================================ interações genéricas


class RespostaFalsa:
    def __init__(self, inter):
        self.inter = inter
        self.feita = False
        self.modais = []

    async def defer(self, **kwargs):
        self.feita = True

    def is_done(self):
        return self.feita

    async def send_message(self, *args, **kwargs):
        self.feita = True
        self.inter.enviados.append(self.inter.texto_de(args, kwargs))

    async def send_modal(self, *args, **kwargs):
        self.feita = True
        self.modais.append(kwargs.get("modal") or (args[0] if args else None))

    async def edit_message(self, *args, **kwargs):
        self.feita = True
        self.inter.enviados.append(self.inter.texto_de(args, kwargs))


class InteracaoFalsa:
    """Interação de comando ou componente: registra o texto enviado e os modais abertos."""

    def __init__(self, *, autor=AUTOR, guild_id=SERVIDOR_DO_COMANDO, guild=None, custom_id="", valores=None):
        self.author = SimpleNamespace(id=autor, mention=f"<@{autor}>", display_name="Ana", discriminator="0")
        self.user = self.author
        self.guild_id = guild_id
        self.guild = guild
        self.id = 1234
        self.enviados = []
        self.response = RespostaFalsa(self)
        self.data = SimpleNamespace(custom_id=custom_id, values=valores or [])
        self.text_values = {}
        self.channel = SimpleNamespace(id=11)
        self.message = SimpleNamespace(flags=SimpleNamespace(ephemeral=True), embeds=[], edit=self._nada)

    async def _nada(self, *args, **kwargs):
        return None

    @staticmethod
    def texto_de(args, kwargs):
        embed = kwargs.get("embed")
        partes = [str(a) for a in args] + ([str(kwargs["content"])] if kwargs.get("content") else [])
        if embed is not None:
            partes.append(embed.description or "")
        return "\n".join(partes)

    async def send(self, *args, **kwargs):
        self.response.feita = True
        self.enviados.append(self.texto_de(args, kwargs))

    async def edit_original_message(self, *args, **kwargs):
        self.enviados.append(self.texto_de(args, kwargs))

    edit_original_response = edit_original_message

    @property
    def texto(self):
        return "\n".join(self.enviados)


# ============================================================================ painel: drivers diretos dos serviços


class BotDoPainel:
    """Só a configuração e o dono do bot que as seções de favoritos, integrações e links pedem."""

    def __init__(self, *, favs=10, integracoes=10, nome_max=35, url_max=90, dono=False):
        self.config = {
            "MAX_USER_FAVS": favs,
            "MAX_USER_INTEGRATIONS": integracoes,
            "USER_FAV_MAX_NAME_LENGTH": nome_max,
            "USER_FAV_MAX_URL_LENGTH": url_max,
        }
        self.dono = dono

    async def is_owner(self, user):
        return self.dono


def contexto_conta(bot):
    return AccountContext(pool=SimpleNamespace(), bot=bot, user_id=AUTOR)


def args_de(**campos):
    return {nome: [valor] for nome, valor in campos.items()}


def json_de(conteudo):
    return conteudo if isinstance(conteudo, str) else json.dumps(conteudo)


async def painel_favoritos(bot, acao, favs, **campos):
    """``Parsed`` da seção de favoritos do painel para a ação (``favorito_adicionar``, ``favoritos_importar``…)."""
    return await FavoritesSection().parse(contexto_conta(bot), {"fav_links": dict(favs)}, acao, args_de(**campos))


async def painel_integracoes(bot, acao, integracoes, **campos):
    documento = {"integration_links": dict(integracoes)}
    return await IntegrationsSection().parse(contexto_conta(bot), documento, acao, args_de(**campos))


def painel_links(bot, acao, links, *, canal=True, **campos):
    """``ParseResult`` do formulário de links fixos do servidor (``acao`` = adicionar, editar, remover, importar)."""
    atual = {"fav_links": dict(links), "canal_configurado": canal}
    return LinksForm().parse(SimpleNamespace(bot=bot), atual, args_de(acao=acao, **campos))


async def importar_no_painel(modo, conteudo, *, bot=None, existentes=None):
    """``(entradas guardadas, erros)`` da importação do painel no modo; ``None`` no lugar das entradas se recusou."""
    bot = bot or BotDoPainel()
    existentes = existentes or {}
    if modo == ViewMode.fav_manager:
        resultado = await painel_favoritos(bot, "favoritos_importar", existentes, dados=json_de(conteudo))
        chave = "fav_links"
    elif modo == ViewMode.integrations_manager:
        resultado = await painel_integracoes(bot, "integracoes_importar", existentes, dados=json_de(conteudo))
        chave = "integration_links"
    else:
        resultado = painel_links(bot, "importar", existentes, dados=json_de(conteudo))
        chave = "fav_links"
    return (None if resultado.errors else resultado.new[chave]), resultado.errors


# ============================================================================ bot: importadores e modais


async def importar_no_bot(modo, conteudo, *, bot=None, existentes=None):
    """``(entradas guardadas, texto mostrado)`` da importação do bot no modo; ``None`` no lugar se nada foi gravado."""
    bot = bot or ModalBot(nome_max=35, url_max=90)
    if existentes:
        if modo == ViewMode.fav_manager:
            bot.user_data["fav_links"] = dict(existentes)
        elif modo == ViewMode.integrations_manager:
            bot.user_data["integration_links"] = dict(existentes)
        else:
            bot.guild_data["player_controller"]["fav_links"] = dict(existentes)
    inter = await importar(bot, modo, conteudo)
    gravou = bool(bot.salvos_usuario or bot.salvos_servidor)
    return (gravados(bot, modo) if gravou else None), inter.texto


async def adicionar_link_do_servidor(bot, nome, url, descricao="descrição", *, editando=None):
    """Roda o modal REAL de link fixo do servidor (``FavModalAdd`` no modo ``guild_fav_manager``)."""
    view = modal_view(bot, ViewMode.guild_fav_manager)
    inter = ModalInteraction(guild_fav_name=nome, guild_fav_description=descricao, guild_fav_url=url)
    await FavModalAdd(editando, None, view).callback(inter)
    return inter


def campos_do_modal(modo, nome=None, url=None, **kwargs):
    """Os ``TextInput`` do modal REAL de adicionar/editar do modo, por ``custom_id`` (limites que o Discord aplica)."""
    modal = FavModalAdd(nome, url, SimpleNamespace(mode=modo), **kwargs)
    return {campo.custom_id: campo for linha in modal.components for campo in linha.children}


# ============================================================================ cargos de DJ, skins, volume e status de voz


class CargoFalso:
    def __init__(self, id_):
        self.id = id_
        self.name = f"cargo{id_}"
        self.mention = f"<@&{id_}>"


class GuildaFalsa:
    """Servidor com cargos: ``default_role`` é o ``@everyone`` e ``get_role`` acha por id."""

    def __init__(self, cargos=(), *, id_=SERVIDOR_DO_COMANDO):
        self.id = id_
        self.default_role = CargoFalso(id_)
        self.roles = [self.default_role, *cargos]
        self.me = SimpleNamespace(voice=None)
        self.features = []

    def get_role(self, id_):
        return next((cargo for cargo in self.roles if cargo.id == id_), None)

    def get_member(self, id_):
        return SimpleNamespace(id=id_, mention=f"<@{id_}>", guild_permissions=SimpleNamespace(manage_guild=True))


def cargos(quantidade, *, inicio=1000):
    return [CargoFalso(inicio + i) for i in range(quantidade)]


async def comando_de_dj(monkeypatch, nome_do_comando, bot, guilda, cargo):
    """Roda ``add_dj_role`` ou ``remove_dj_role`` REAIS da ``MusicSettings``; devolve a interação (texto enviado)."""
    import empiremuse.cogs.music_settings as music_settings

    inter = InteracaoFalsa(guild_id=guilda.id, guild=guilda)
    bot.guilds[guilda.id] = guilda

    async def escolher(interaction, **kwargs):
        return interaction, bot

    monkeypatch.setattr(music_settings, "select_bot_pool", escolher)
    comando = getattr(music_settings.MusicSettings, nome_do_comando)
    await comando.callback(self=music_settings.MusicSettings(bot), interaction=inter, role=cargo)
    return inter


class SkinsLidas(Exception):
    """Levantada pelo espião do ``SkinSelector`` para encerrar o ``change_skin`` depois de montar as opções."""


async def opcoes_do_change_skin(monkeypatch, bot, guilda):
    """Os valores das 4 listas que o ``change_skin`` REAL oferece: (normal, estático, global, global estático)."""
    import empiremuse.cogs.music_settings as music_settings

    lidas = {}

    class EspiaoDoSeletor:
        def __init__(self, ctx, embed, normal, estatico, globais, globais_estaticas, global_mode):
            lidas["listas"] = tuple(
                [[o.value for o in lista] for lista in (normal, estatico, globais, globais_estaticas)]
            )

        async def wait(self):
            raise SkinsLidas

    async def escolher(interaction, **kwargs):
        return interaction, bot

    monkeypatch.setattr(music_settings, "select_bot_pool", escolher)
    monkeypatch.setattr(music_settings, "SkinSelector", EspiaoDoSeletor)
    bot.guilds[guilda.id] = guilda
    inter = InteracaoFalsa(guild_id=guilda.id, guild=guilda)
    cog = music_settings.MusicSettings(bot)
    with pytest.raises(SkinsLidas):
        await music_settings.MusicSettings.change_skin.callback(self=cog, interaction=inter)
    return lidas["listas"]


def skins_do_bot(bot, normais, estaticas, *, personalizadas=(), personalizadas_estaticas=()):
    bot.player_skins = {nome: SimpleNamespace(preview=f"https://exemplo.invalid/{nome}.png") for nome in normais}
    bot.player_static_skins = {
        nome: SimpleNamespace(preview=f"https://exemplo.invalid/{nome}.png") for nome in estaticas
    }
    documento = bot.documento("global", DBModel.guilds, SERVIDOR_DO_COMANDO)
    documento["custom_skins"] = {nome: "blob" for nome in personalizadas}
    documento["custom_skins_static"] = {nome: "blob" for nome in personalizadas_estaticas}

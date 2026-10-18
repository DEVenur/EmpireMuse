"""F3-5a — bugs de cogs × painel (KI-36 … KI-43): testes RED e guardas.

Cada classe cobre um item de ``docs/known-issues.md``. Os testes ``test_guarda_*`` passam hoje e continuam passando
depois da correção (protegem o comportamento que a correção não pode mudar); os demais são RED e falham pelo defeito
descrito no docstring da classe. Sem Discord real, sem rede, sem ``.env`` e sem ``setup()``: canais, mensagens e
interações são dublês (``tests/helpers_request_channel.py``) e os valores falsos são montados em tempo de execução.
"""

import copy
import json
import logging
from types import SimpleNamespace

import disnake
import pytest

import empiremuse.cogs.legacy_cmds as legacy_cmds
from empiremuse.utils.db import DBModel, LocalDatabase, db_models
from empiremuse.utils.music import interactions, request_channel
from empiremuse.utils.music.converters import perms_translations
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.music.interactions import FavMenuView, FavModalAdd, FavModalImport, ViewMode
from tests.helpers_request_channel import (
    BOT_MENTION,
    FULL_TEXT,
    GUILD_ID,
    FakeBot,
    FakeDB,
    FakeForum,
    FakeGuild,
    FakePlayer,
    FakeStage,
    FakeText,
    FakeVoice,
    Journal,
    perms,
)
from tests.test_request_channel_characterization import Scenario, configured, modal_answer
from tests.test_request_channel_permissions import exact, without


@pytest.fixture
def world(monkeypatch):
    return Scenario(monkeypatch)


def forbidden() -> disnake.Forbidden:
    return disnake.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Access")


def run_reset(world, **kwargs):
    """Executa o ``/reset`` e devolve a exceção levantada (ou ``None``): o teste decide o que esperar dela."""
    try:
        world.reset(**kwargs)
    except Exception as erro:  # noqa: BLE001 — o contrato da falha é justamente o que os testes medem
        return erro
    return None


# ============================================================================ KI-36 — /reset × falha no Discord


class TestKI36ResetFalhaNoDiscord:
    """Hoje o ``/reset`` limpa o banco ANTES de mexer no Discord: se a edição da mensagem ou a exclusão do canal
    falha, o canal continua de pé e o banco fica desconfigurado (e o aviso diz que o reset "foi feito na base")."""

    def forum_com_post(self, world):
        post = world.forum.add_post(900, "post de pedidos")
        world.bot.channels[900] = post
        world.db.doc["player_controller"].update({"channel": "900", "message_id": "900"})
        return post

    # ---- guardas: o caminho feliz e as chamadas ao Discord não podem mudar

    def test_guarda_reset_sem_exclusao_limpa_o_banco_e_arquiva_a_mensagem(self, world):
        configured(world)
        assert run_reset(world) is None
        assert (world.saved["channel"], world.saved["message_id"]) == (None, None)
        (edicao,) = world.j.of("message.edit")
        assert edicao[1] == 555 and edicao[2]["embed"] is None
        assert edicao[2]["content"].startswith("Canal de pedir música foi resetado pelo membro")
        (arquivar,) = world.j.of("thread.edit")
        assert arquivar[2] == {"archived": True, "reason": "Player resetado por Autor#0001."}
        assert world.j.of("channel.delete") == []

    def test_guarda_reset_com_exclusao_apaga_o_canal_e_nao_toca_na_mensagem(self, world):
        configured(world)
        assert run_reset(world, delete="sim") is None
        assert (world.saved["channel"], world.saved["message_id"]) == (None, None)
        assert world.j.of("channel.delete") == [("channel.delete", "#pedidos", "Player resetado por: Autor#0001")]
        assert world.j.of("message.edit") == [] and world.j.of("thread.edit") == []

    def test_guarda_reset_de_forum_apaga_o_post_e_limpa_o_banco(self, world):
        self.forum_com_post(world)
        assert run_reset(world) is None
        assert (world.saved["channel"], world.saved["message_id"]) == (None, None)
        assert world.j.of("channel.delete") == [("channel.delete", "#post de pedidos", "9000 resetou player")]

    def test_guarda_reset_so_altera_canal_e_message_id_no_banco(self, world):
        configured(world)
        restante = {k: v for k, v in world.db.doc.items() if k != "player_controller"}
        restante_pc = {k: v for k, v in world.saved.items() if k not in ("channel", "message_id")}
        assert run_reset(world, delete="sim") is None
        assert {k: v for k, v in world.db.doc.items() if k != "player_controller"} == restante
        assert {k: v for k, v in world.saved.items() if k not in ("channel", "message_id")} == restante_pc

    @pytest.mark.parametrize("falha", ["editar_mensagem", "apagar_canal"])
    def test_guarda_falha_no_discord_continua_levantando_generic_error(self, world, falha):
        mensagem = configured(world)
        if falha == "editar_mensagem":
            mensagem.fail_edit = RuntimeError("falha simulada")
        else:
            world.text.fail_delete = forbidden()
        erro = run_reset(world, delete="sim" if falha == "apagar_canal" else None)
        assert isinstance(erro, GenericError), f"o usuário precisa receber um GenericError, veio {erro!r}"

    # ---- RED: a falha no Discord preserva a configuração

    def test_falha_ao_editar_a_mensagem_preserva_a_configuracao_no_banco(self, world):
        configured(world).fail_edit = RuntimeError("falha simulada")
        run_reset(world)
        assert (world.saved["channel"], world.saved["message_id"]) == ("22", "555"), (
            "KI-36: o Discord falhou, o canal continua de pé e o banco foi desconfigurado"
        )

    def test_falha_ao_apagar_o_canal_preserva_a_configuracao_no_banco(self, world):
        configured(world)
        world.text.fail_delete = forbidden()
        run_reset(world, delete="sim")
        assert (world.saved["channel"], world.saved["message_id"]) == ("22", "555"), (
            "KI-36: a exclusão do canal falhou, o canal continua de pé e o banco foi desconfigurado"
        )

    def test_falha_ao_apagar_o_post_do_forum_preserva_a_configuracao_no_banco(self, world):
        post = self.forum_com_post(world)
        post.fail_delete = forbidden()
        run_reset(world)
        assert (world.saved["channel"], world.saved["message_id"]) == ("900", "900"), (
            "KI-36: a exclusão do post falhou, o post continua de pé e o banco foi desconfigurado"
        )

    def test_falha_ao_apagar_o_post_do_forum_vira_erro_claro_para_o_usuario(self, world):
        self.forum_com_post(world).fail_delete = forbidden()
        erro = run_reset(world)
        assert isinstance(erro, GenericError), f"KI-36: a exceção crua do Discord escapou para o usuário: {erro!r}"

    @pytest.mark.parametrize("falha", ["editar_mensagem", "apagar_canal"])
    def test_a_mensagem_de_erro_nao_diz_que_o_reset_foi_feito_na_base(self, world, falha):
        mensagem = configured(world)
        if falha == "editar_mensagem":
            mensagem.fail_edit = RuntimeError("falha simulada")
        else:
            world.text.fail_delete = forbidden()
        erro = run_reset(world, delete="sim" if falha == "apagar_canal" else None)
        assert isinstance(erro, GenericError)
        assert "resetado da base de dados" not in erro.text, (
            "KI-36: a mensagem afirma que o banco foi resetado, mas a configuração tem de ficar preservada"
        )

    # ---- RED: ordem definida (Discord, banco, aviso, player), erro genérico e detalhe só no log

    def provocar(self, world, falha):
        """Configura a falha pedida e devolve o ``delete`` do ``/reset`` que a exercita."""
        if falha == "apagar_post":
            self.forum_com_post(world).fail_delete = RuntimeError("falha simulada")
            return None
        mensagem = configured(world)
        if falha == "editar_mensagem":
            mensagem.fail_edit = RuntimeError("falha simulada")
            return None
        world.text.fail_delete = RuntimeError("falha simulada")
        return "sim"

    FALHAS = ["editar_mensagem", "apagar_canal", "apagar_post"]

    @pytest.mark.parametrize("falha", FALHAS)
    def test_a_mensagem_de_erro_e_generica_sem_detalhe_interno(self, world, falha):
        erro = run_reset(world, delete=self.provocar(world, falha))
        assert isinstance(erro, GenericError)
        for vazado in ("falha simulada", "RuntimeError", "```", "traceback"):
            assert vazado not in erro.text, f"KI-36: a mensagem ao usuário traz detalhe interno ({vazado!r})"

    @pytest.mark.parametrize("falha", FALHAS)
    def test_o_detalhe_da_falha_vai_para_o_log(self, world, caplog, falha):
        caplog.set_level(logging.ERROR)
        run_reset(world, delete=self.provocar(world, falha))
        registrado = " ".join(
            f"{r.getMessage()} {r.exc_info[1] if r.exc_info else ''}" for r in caplog.records if r.levelno >= 40
        )
        assert "falha simulada" in registrado, "KI-36: o detalhe da falha precisa ir para o log do servidor"

    @pytest.mark.parametrize("falha", FALHAS)
    def test_falha_no_discord_nao_avisa_sucesso_nem_reseta_o_player(self, world, falha):
        player = FakePlayer(world.j, world.guild, world.text, static=True, message=object())
        world.bot.music.players[GUILD_ID] = player
        run_reset(world, delete=self.provocar(world, falha))
        assert world.j.of("player.process_hint") == [] and world.j.of("player.invoke_np") == []
        assert (player.static, player.text_channel) == (True, world.text), "o player não pode ser desligado do canal"
        assert world.j.of("inter.edit_original_message") == [], "KI-36: não se avisa sucesso de um reset que falhou"

    def test_guarda_falha_ao_gravar_o_banco_nao_avisa_sucesso_nem_reseta_o_player(self, world):
        configured(world)
        player = FakePlayer(world.j, world.guild, world.text, static=True, message=object())
        world.bot.music.players[GUILD_ID] = player

        async def gravar_falha(data):
            raise RuntimeError("banco indisponível")

        world.db.update = gravar_falha
        assert run_reset(world) is not None
        assert world.j.of("player.process_hint") == [] and world.j.of("inter.edit_original_message") == []

    def test_o_post_do_forum_e_apagado_antes_de_gravar_o_banco(self, world):
        self.forum_com_post(world)
        assert run_reset(world) is None
        nomes = world.j.names()
        assert nomes.index("channel.delete") < nomes.index("db.update"), "KI-36: Discord primeiro, banco depois"


# ============================================================================ KI-37 — /setup de fórum × post.edit() vazio


class TestKI37SetupDeForumSemEditVazio:
    """Depois do embed ocioso o setup chama ``edit()`` no post com ``channel_kwargs`` já limpo (``{}``): uma
    requisição inútil à API do Discord."""

    def preparar(self, world, cenario):
        if cenario == "aberto":
            world.forum.add_post(802, "meu post")
        elif cenario == "arquivado":
            world.forum.add_post(803, "meu post antigo", archived=True)
        modal_answer(world, "Pedidos do bot")

    CENARIOS = ["novo", "aberto", "arquivado"]

    @pytest.mark.parametrize("cenario", CENARIOS)
    def test_nenhuma_edicao_vazia_no_post_nem_no_forum(self, world, cenario):
        self.preparar(world, cenario)
        world.setup(target=world.forum)
        vazias = [e for e in world.j if e[0] in ("thread.edit", "channel.edit") and not e[2]]
        assert vazias == [], f"KI-37: edit() sem argumentos: {vazias}"

    @pytest.mark.parametrize("cenario", CENARIOS)
    def test_guarda_o_setup_grava_post_e_mensagem_e_nao_edita_o_forum(self, world, cenario):
        self.preparar(world, cenario)
        world.setup(target=world.forum)
        assert world.saved["channel"] is not None and world.saved["message_id"] is not None
        assert world.saved["channel"] == world.saved["message_id"], "no fórum o post e a mensagem têm o mesmo id"
        assert world.j.of("send_idle_embed"), "o embed ocioso continua sendo enviado ao post"
        assert world.j.of("channel.edit") == [], "o fórum em si nunca é editado"

    def test_guarda_post_arquivado_e_reaberto_pelo_setup(self, world):
        self.preparar(world, "arquivado")
        world.setup(target=world.forum)
        assert {"archived": False} in [e[2] for e in world.j.of("thread.edit")]

    def test_guarda_post_travado_e_destravado_com_gerenciar_topicos(self, world):
        world.forum.add_post(802, "meu post", locked=True)
        modal_answer(world, "Pedidos do bot")
        world.setup(target=world.forum)
        assert {"locked": False, "archived": False} in [e[2] for e in world.j.of("thread.edit")]


# ============================================================================ KI-38 — validate_request_target × view_channel


class SpyPermissions(disnake.Permissions):
    """``Permissions`` real que registra cada leitura de ``view_channel`` (por iteração ou pelo atributo/alias)."""

    def __init__(self, value, log):
        super().__init__(value)
        object.__setattr__(self, "_log", log)

    def __getattribute__(self, name):
        if name in ("view_channel", "read_messages"):
            object.__getattribute__(self, "_log").append(("atributo", name))
        return super().__getattribute__(name)

    def __iter__(self):
        object.__getattribute__(self, "_log").append(("iteracao",))
        return iter(disnake.Permissions(self.value))


def validar(kind, canal_perms, *, existing_channel=True, admin=False):
    """Roda ``validate_request_target`` e devolve ``(nome da exceção, texto)``; ``("ok", "")`` se passou."""
    j = Journal()
    guild = FakeGuild(j, perms(manage_channels=True, administrator=admin))
    bot = FakeBot(j, guild, FakeDB(j))
    canal = kind(j, 22, "pedidos", guild, canal_perms)
    try:
        request_channel.validate_request_target(bot, guild, canal, existing_channel=existing_channel)
    except GenericError as erro:
        return type(erro).__name__, erro.text, canal
    return "ok", "", canal


class TestKI38ValidacaoDeViewChannel:
    """``view_channel`` é conferido por ``check_channel_perm`` e de novo, no fim, por ``read_messages`` (o mesmo bit)."""

    KINDS = [FakeText, FakeVoice, FakeStage]

    # ---- guardas: o resultado da validação não muda, qualquer que seja a combinação de permissões

    @pytest.mark.parametrize("kind", KINDS)
    def test_guarda_canal_com_todas_as_permissoes_passa(self, kind):
        assert validar(kind, perms(**FULL_TEXT))[:2] == ("ok", "")

    @pytest.mark.parametrize("kind", KINDS)
    def test_guarda_sem_view_channel_lista_a_permissao_traduzida(self, kind):
        nome, texto, canal = validar(kind, without("view_channel"))
        assert nome == "GenericError"
        assert texto == exact(canal, ("view_channel",))
        assert perms_translations["view_channel"] in texto

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("faltando", ["send_messages", "embed_links"])
    def test_guarda_sem_outras_permissoes_do_canal_lista_cada_uma(self, kind, faltando):
        nome, texto, canal = validar(kind, without(faltando))
        assert (nome, texto) == ("GenericError", exact(canal, (faltando,)))

    @pytest.mark.parametrize("kind", KINDS)
    def test_guarda_sem_gerenciar_permissoes_em_canal_existente_exige_admin(self, kind):
        assert validar(kind, without("manage_permissions"))[0] == "MissingManagePermissions"

    @pytest.mark.parametrize("kind", KINDS)
    def test_guarda_sem_gerenciar_permissoes_passa_em_canal_novo_ou_com_admin(self, kind):
        assert validar(kind, without("manage_permissions"), existing_channel=False)[:2] == ("ok", "")
        assert validar(kind, without("manage_permissions"), admin=True)[:2] == ("ok", "")

    @pytest.mark.parametrize("kind", KINDS)
    def test_guarda_a_checagem_de_permissoes_do_canal_vem_antes_de_gerenciar_permissoes(self, kind):
        nome, texto, canal = validar(kind, without("view_channel", "manage_permissions"))
        assert (nome, texto) == ("GenericError", exact(canal, ("view_channel",)))

    def test_guarda_forum_sem_view_channel_lista_a_permissao_traduzida(self):
        j = Journal()
        guild = FakeGuild(j, perms(manage_channels=True))
        forum = FakeForum(j, 55, "fórum", guild, without("view_channel"))
        bot = FakeBot(j, guild, FakeDB(j))
        with pytest.raises(GenericError) as erro:
            request_channel.validate_request_target(bot, guild, forum)
        assert erro.value.text == exact(forum, ("view_channel",))

    # ---- RED: view_channel é conferido uma vez só

    @pytest.mark.parametrize("existing_channel", [True, False])
    @pytest.mark.parametrize("kind", KINDS)
    def test_view_channel_e_conferido_uma_vez_so_em_canal_de_texto_voz_e_palco(self, kind, existing_channel):
        leituras = []
        espiao = SpyPermissions(perms(**FULL_TEXT).value, leituras)
        assert validar(kind, espiao, existing_channel=existing_channel)[:2] == ("ok", "")
        assert len(leituras) == 1, f"KI-38: view_channel conferido {len(leituras)}x: {leituras}"

    def test_guarda_view_channel_e_conferido_uma_vez_so_no_forum(self):
        leituras = []
        j = Journal()
        guild = FakeGuild(j, perms(manage_channels=True))
        forum = FakeForum(j, 55, "fórum", guild, SpyPermissions(perms(**FULL_TEXT).value, leituras))
        request_channel.validate_request_target(FakeBot(j, guild, FakeDB(j)), guild, forum)
        assert len(leituras) == 1, f"view_channel conferido {len(leituras)}x: {leituras}"


# ============================================================================ KI-39 / KI-40 / KI-41 — modais de favoritos e integrações

SERVIDOR = 5000
URL_BASE = "https://exemplo.invalid"


class FakeMusicCog:
    fav_import_export_cd = SimpleNamespace(
        get_bucket=lambda inter: SimpleNamespace(update_rate_limit=lambda: None),
    )
    fav_manager = SimpleNamespace(name="fav_manager")


class ModalBot:
    """Só o que os modais de ``interactions.py`` pedem ao bot; os dados são o MESMO dict (como no BaseDB)."""

    def __init__(self, *, favs=10, integracoes=10, dono=False, fav_links=None, integration_links=None):
        self.config = {
            "MAX_USER_FAVS": favs,
            "MAX_USER_INTEGRATIONS": integracoes,
            "USER_FAV_MAX_URL_LENGTH": 200,
            "USER_FAV_MAX_NAME_LENGTH": 25,
        }
        self.dono = dono
        self.user_data = {"fav_links": dict(fav_links or {}), "integration_links": dict(integration_links or {})}
        self.guild_data = {"player_controller": {"channel": "22", "message_id": "555", "fav_links": {}}}
        self.salvos_usuario, self.salvos_servidor = [], []
        self.spotify = None
        self.deezer = SimpleNamespace(get_user_info=self._deezer_user)

    async def _deezer_user(self, user_id):
        return {"name": "Ana", "link": f"https://www.deezer.com/br/profile/{user_id}", "picture": f"{URL_BASE}/ana.png"}

    def get_cog(self, nome):
        return FakeMusicCog

    async def is_owner(self, user):
        return self.dono

    async def get_global_data(self, id_, *, db_name):
        return self.user_data

    async def update_global_data(self, id_, data, *, db_name):
        self.salvos_usuario.append(copy.deepcopy(data))

    async def get_data(self, id_, *, db_name):
        return self.guild_data

    async def update_data(self, id_, data, *, db_name):
        self.salvos_servidor.append(copy.deepcopy(data))

    def get_channel(self, cid):
        return object()

    def get_guild(self, gid):
        return SimpleNamespace(id=gid, me=SimpleNamespace())

    def get_color(self, *args):
        return 0

    def get_global_command_named(self, name, cmd_type=None):
        return SimpleNamespace(id=1)


class ModalContext:
    async def edit_original_message(self, **kwargs):
        return None


def modal_view(bot, mode):
    return SimpleNamespace(
        mode=mode,
        bot=bot,
        data=None,
        guild_data=None,
        ctx=ModalContext(),
        message=None,
        log="",
        build_txt=lambda: "",
        build_embed=lambda: None,
    )


class ModalInteraction:
    def __init__(self, *, estrito=False, **text_values):
        self.estrito, self.respondida, self.arquivos = estrito, False, []
        self.text_values = text_values
        self.author = SimpleNamespace(id=900)
        self.guild = None
        self.guild_id = SERVIDOR
        self.enviados = []
        self.response = SimpleNamespace(defer=self._defer)

    async def _defer(self, **kwargs):
        self.respondida = True

    async def send(self, content=None, **kwargs):
        self.respondida = True
        if kwargs.get("file") is not None:
            self.arquivos.append(kwargs["file"].fp.read().decode())
        self.enviados.append(self._texto(content, kwargs))

    async def edit_original_message(self, content=None, **kwargs):
        if self.estrito and not self.respondida:
            raise RuntimeError("edit_original_message antes de a interação ser respondida (o Discord recusa)")
        self.enviados.append(self._texto(content, kwargs))

    @staticmethod
    def _texto(content, kwargs):
        embed = kwargs.get("embed")
        return f"{content or ''}{embed.description if embed is not None else ''}"

    @property
    def texto(self):
        return "\n".join(self.enviados)


@pytest.fixture(autouse=True)
def _sem_idle_embed(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    monkeypatch.setattr(interactions, "process_idle_embed", nada)


async def adicionar_favorito(bot, nome="novo", url=f"{URL_BASE}/musica", *, editando=None):
    view = modal_view(bot, ViewMode.fav_manager)
    inter = ModalInteraction(user_fav_name=nome, user_fav_url=url)
    await FavModalAdd(editando, None, view).callback(inter)
    return inter


async def adicionar_integracao(bot, url="https://www.deezer.com/br/profile/123456"):
    view = modal_view(bot, ViewMode.integrations_manager)
    inter = ModalInteraction(user_integration_url=url)
    await FavModalAdd(None, None, view).callback(inter)
    return inter


async def importar(bot, modo, conteudo, *, estrito=False):
    view = modal_view(bot, modo)
    texto = conteudo if isinstance(conteudo, str) else json.dumps(conteudo, indent=4)
    inter = ModalInteraction(json_data=texto, estrito=estrito)
    await FavModalImport(view).callback(inter)
    return inter


async def exportar_integracoes(bot):
    """Roda o exportador REAL (``FavMenuView.export_callback``) e devolve o texto do arquivo enviado ao usuário."""
    inter = ModalInteraction()
    espelho = SimpleNamespace(bot=bot, mode=ViewMode.integrations_manager, data=bot.user_data)
    await FavMenuView.export_callback(espelho, inter)
    assert inter.arquivos, f"o exportador não enviou arquivo: {inter.texto!r}"
    return inter.arquivos[-1]


def favs_cheios(quantidade):
    return {f"fav{i}": f"{URL_BASE}/{i}" for i in range(quantidade)}


def integracoes_cheias(quantidade):
    return {f"【DZ】: Antiga {i}": {"url": f"{URL_BASE}/{i}"} for i in range(quantidade)}


class TestKI39ModalDeFavorito:
    """O modal de adicionar favorito compara com ``MAX_USER_FAVS`` sem as exceções do comando (``> 0`` e isenção do
    dono do bot)."""

    @pytest.mark.asyncio
    async def test_sem_limite_max_user_favs_zero_aceita_novo_favorito(self):
        bot = ModalBot(favs=0, fav_links=favs_cheios(3))
        await adicionar_favorito(bot)
        assert bot.salvos_usuario and "novo" in bot.salvos_usuario[-1]["fav_links"], (
            "KI-39: MAX_USER_FAVS=0 significa sem limite, mas o modal recusou o favorito"
        )

    @pytest.mark.asyncio
    async def test_dono_do_bot_nao_e_limitado_pelo_maximo_de_favoritos(self):
        bot = ModalBot(favs=2, dono=True, fav_links=favs_cheios(2))
        await adicionar_favorito(bot)
        assert bot.salvos_usuario and "novo" in bot.salvos_usuario[-1]["fav_links"], (
            "KI-39: o dono do bot é isento do limite no comando, mas o modal recusou o favorito"
        )

    @pytest.mark.asyncio
    async def test_guarda_usuario_comum_no_limite_e_barrado_com_aviso(self):
        bot = ModalBot(favs=2, fav_links=favs_cheios(2))
        inter = await adicionar_favorito(bot)
        assert bot.salvos_usuario == [] and "Não há espaço disponível" in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_usuario_comum_abaixo_do_limite_salva(self):
        bot = ModalBot(favs=3, fav_links=favs_cheios(2))
        await adicionar_favorito(bot)
        assert "novo" in bot.salvos_usuario[-1]["fav_links"]

    @pytest.mark.asyncio
    async def test_guarda_editar_um_favorito_existente_no_limite_continua_permitido(self):
        bot = ModalBot(favs=2, fav_links=favs_cheios(2))
        await adicionar_favorito(bot, nome="renomeado", editando="fav0")
        salvo = bot.salvos_usuario[-1]["fav_links"]
        assert "renomeado" in salvo and "fav0" not in salvo and len(salvo) == 2

    @pytest.mark.asyncio
    async def test_guarda_o_modal_grava_so_o_link_valido_do_texto(self):
        bot = ModalBot()
        await adicionar_favorito(bot, url=f"  {URL_BASE}/faixa  ")
        assert bot.salvos_usuario[-1]["fav_links"]["novo"] == f"{URL_BASE}/faixa"


class TestKI39ModalDeIntegracao:
    """O modal de adicionar integração compara com ``MAX_USER_FAVS`` em vez de ``MAX_USER_INTEGRATIONS``."""

    def integracao_salva(self, bot):
        return bool(bot.salvos_usuario) and "【DZ】: Ana" in bot.salvos_usuario[-1]["integration_links"]

    @pytest.mark.asyncio
    async def test_o_limite_de_favoritos_nao_barra_integracoes(self):
        bot = ModalBot(favs=1, integracoes=5, integration_links=integracoes_cheias(1))
        await adicionar_integracao(bot)
        assert self.integracao_salva(bot), "KI-39: a integração foi barrada pela cota de FAVORITOS (MAX_USER_FAVS)"

    @pytest.mark.asyncio
    async def test_o_limite_de_integracoes_barra_mesmo_com_cota_de_favoritos_sobrando(self):
        bot = ModalBot(favs=10, integracoes=1, integration_links=integracoes_cheias(1))
        inter = await adicionar_integracao(bot)
        assert bot.salvos_usuario == [], "KI-39: MAX_USER_INTEGRATIONS=1 não foi respeitado"
        assert "Não há espaço disponível" in inter.texto

    @pytest.mark.asyncio
    async def test_sem_limite_de_integracoes_aceita_nova_integracao(self):
        bot = ModalBot(favs=1, integracoes=0, integration_links=integracoes_cheias(3))
        await adicionar_integracao(bot)
        assert self.integracao_salva(bot), "KI-39: MAX_USER_INTEGRATIONS=0 significa sem limite"

    @pytest.mark.asyncio
    async def test_dono_do_bot_nao_e_limitado_pelo_maximo_de_integracoes(self):
        bot = ModalBot(favs=1, integracoes=1, dono=True, integration_links=integracoes_cheias(1))
        await adicionar_integracao(bot)
        assert self.integracao_salva(bot), "KI-39: o dono do bot é isento dos limites de cota"

    @pytest.mark.asyncio
    async def test_guarda_integracao_abaixo_dos_dois_limites_e_salva_com_url_e_avatar(self):
        bot = ModalBot(favs=10, integracoes=10)
        await adicionar_integracao(bot)
        entrada = bot.salvos_usuario[-1]["integration_links"]["【DZ】: Ana"]
        assert entrada == {"url": "https://www.deezer.com/br/profile/123456", "avatar": f"{URL_BASE}/ana.png"}

    @pytest.mark.asyncio
    async def test_guarda_nos_dois_limites_cheios_a_integracao_e_barrada(self):
        bot = ModalBot(favs=2, integracoes=2, integration_links=integracoes_cheias(2))
        inter = await adicionar_integracao(bot)
        assert bot.salvos_usuario == [] and "Não há espaço disponível" in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_link_sem_suporte_nao_grava_nada(self):
        bot = ModalBot()
        inter = await adicionar_integracao(bot, url=f"{URL_BASE}/qualquer")
        assert bot.salvos_usuario == [] and "não é suportado" in inter.texto


def url_guardada(valor):
    """O importador novo pode guardar texto-URL (legado) ou ``{"url": ...}`` (formato do exportador)."""
    return valor if isinstance(valor, str) else valor["url"]


class TestKI40ImportadorDeIntegracoes:
    """O exportador grava ``{"titulo": {"url": ..., "avatar": ...}}``; o importador do comando só aceita texto-URL."""

    def exportado(self):
        return {
            "【DZ】: Ana": {"url": "https://www.deezer.com/br/profile/123456", "avatar": f"{URL_BASE}/ana.png"},
            "【YT】: Canal": {"url": "https://www.youtube.com/@canal"},
        }

    @pytest.mark.asyncio
    async def test_aceita_o_json_gerado_pelo_proprio_exportador(self):
        bot = ModalBot()
        exportado = self.exportado()
        inter = await importar(bot, ViewMode.integrations_manager, json.dumps(exportado, indent=4))
        assert bot.salvos_usuario, f"KI-40: o JSON do exportador foi recusado: {inter.texto!r}"
        salvo = bot.salvos_usuario[-1]["integration_links"]
        assert salvo["【DZ】: Ana"] == exportado["【DZ】: Ana"], "a URL e o avatar precisam sobreviver ao ciclo"
        assert url_guardada(salvo["【YT】: Canal"]) == exportado["【YT】: Canal"]["url"]

    @pytest.mark.asyncio
    async def test_ida_e_volta_do_que_o_modal_de_adicionar_grava(self):
        origem = ModalBot()
        await adicionar_integracao(origem)
        gravado = origem.salvos_usuario[-1]["integration_links"]
        origem.user_data["integration_links"] = gravado
        arquivo = await exportar_integracoes(origem)  # formato REAL do exportador, não um JSON montado à mão
        assert json.loads(arquivo) == gravado
        destino = ModalBot()
        await importar(destino, ViewMode.integrations_manager, arquivo)
        assert destino.salvos_usuario and destino.salvos_usuario[-1]["integration_links"] == gravado

    @pytest.mark.asyncio
    async def test_guarda_formato_antigo_de_texto_simples_continua_aceito(self):
        bot = ModalBot()
        antigo = {"【YT】: Canal": "https://www.youtube.com/@canal", "【SC】: Ana": "https://soundcloud.com/ana/sets"}
        await importar(bot, ViewMode.integrations_manager, antigo)
        salvo = bot.salvos_usuario[-1]["integration_links"]
        assert {nome: url_guardada(valor) for nome, valor in salvo.items()} == antigo

    @pytest.mark.asyncio
    async def test_guarda_texto_com_url_invalida_e_recusado(self):
        bot = ModalBot()
        inter = await importar(bot, ViewMode.integrations_manager, {"【YT】: Canal": "isto-nao-e-url"})
        assert bot.salvos_usuario == [] and "link inválido" in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_objeto_com_url_invalida_e_recusado(self):
        bot = ModalBot()
        inter = await importar(bot, ViewMode.integrations_manager, {"【YT】: Canal": {"url": "isto-nao-e-url"}})
        assert bot.salvos_usuario == [] and "link inválido" in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_o_limite_de_integracoes_vale_para_o_importador(self):
        bot = ModalBot(integracoes=1, integration_links=integracoes_cheias(1))
        inter = await importar(bot, ViewMode.integrations_manager, {"【YT】: Canal": "https://www.youtube.com/@canal"})
        assert bot.salvos_usuario == [] and "não possui espaço suficiente" in inter.texto


class TestKI41ImportadorDeLinksRapidosDoServidor:
    """Itens com ``> fav:`` no nome pulam a validação da URL (``continue``) e mesmo assim são gravados."""

    def item(self, url, descricao="descrição"):
        return {"url": url, "description": descricao}

    URLS_INVALIDAS = ["isto-nao-e-url", "ftp://exemplo.invalid/musica", "javascript:alert(1)", "https://", ""]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", URLS_INVALIDAS)
    @pytest.mark.parametrize("nome", ["> fav: Antigo", "> FAV: Antigo"])
    async def test_item_fav_com_url_invalida_e_rejeitado(self, nome, url):
        bot = ModalBot()
        await importar(bot, ViewMode.guild_fav_manager, {nome: self.item(url)})
        assert bot.salvos_servidor == [], f"KI-41: o item {nome!r} com URL {url!r} foi gravado sem validação"

    @pytest.mark.asyncio
    async def test_item_fav_invalido_derruba_a_importacao_inteira(self):
        bot = ModalBot()
        conteudo = {"Bom": self.item(f"{URL_BASE}/bom"), "> fav: Ruim": self.item("isto-nao-e-url")}
        inter = await importar(bot, ViewMode.guild_fav_manager, conteudo)
        assert bot.salvos_servidor == [], "KI-41: nada do arquivo pode ser gravado se um item é inválido"
        assert "link inválido" in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_item_fav_com_url_valida_continua_aceito(self):
        bot = ModalBot()
        await importar(bot, ViewMode.guild_fav_manager, {"> fav: Antigo": self.item(f"{URL_BASE}/musica")})
        assert bot.salvos_servidor[-1]["player_controller"]["fav_links"]["> fav: Antigo"]["url"] == (
            f"{URL_BASE}/musica"
        )

    @pytest.mark.asyncio
    async def test_guarda_item_comum_com_url_invalida_e_rejeitado_com_aviso(self):
        bot = ModalBot()
        inter = await importar(bot, ViewMode.guild_fav_manager, {"Comum": self.item("isto-nao-e-url")})
        assert bot.salvos_servidor == [] and "link inválido" in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_itens_validos_sao_gravados_com_url_e_descricao(self):
        bot = ModalBot()
        conteudo = {"Um": self.item(f"{URL_BASE}/1", "primeiro"), "Dois": self.item(f"{URL_BASE}/2", "segundo")}
        await importar(bot, ViewMode.guild_fav_manager, conteudo)
        assert bot.salvos_servidor[-1]["player_controller"]["fav_links"] == conteudo

    @pytest.mark.asyncio
    async def test_guarda_mais_de_25_itens_e_recusado(self):
        bot = ModalBot()
        conteudo = {f"Item {i}": self.item(f"{URL_BASE}/{i}") for i in range(26)}
        inter = await importar(bot, ViewMode.guild_fav_manager, conteudo)
        assert bot.salvos_servidor == [] and "máxima permitida (25)" in inter.texto


class TestKI41AmpliadoImportadoresDoUsuario:
    """Os importadores de favoritos do USUÁRIO (``> fav:``) e de integrações (``> itg:``) têm o mesmo ``continue``."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", TestKI41ImportadorDeLinksRapidosDoServidor.URLS_INVALIDAS)
    async def test_favorito_do_usuario_com_nome_fav_e_url_invalida_e_recusado(self, url):
        bot = ModalBot()
        await importar(bot, ViewMode.fav_manager, {"> fav: Antigo": url})
        assert bot.salvos_usuario == [], f"KI-41: o favorito '> fav:' com URL {url!r} foi gravado sem validação"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", TestKI41ImportadorDeLinksRapidosDoServidor.URLS_INVALIDAS)
    async def test_integracao_com_nome_itg_e_url_invalida_e_recusada(self, url):
        bot = ModalBot()
        await importar(bot, ViewMode.integrations_manager, {"> itg: Antiga": url})
        assert bot.salvos_usuario == [], f"KI-41: a integração '> itg:' com URL {url!r} foi gravada sem validação"

    @pytest.mark.asyncio
    async def test_integracao_itg_em_objeto_com_url_invalida_e_recusada(self):
        bot = ModalBot()
        await importar(bot, ViewMode.integrations_manager, {"> itg: Antiga": {"url": "isto-nao-e-url"}})
        assert bot.salvos_usuario == []

    @pytest.mark.asyncio
    async def test_guarda_favorito_do_usuario_fav_com_url_valida_continua_aceito(self):
        bot = ModalBot()
        await importar(bot, ViewMode.fav_manager, {"> fav: Antigo": f"{URL_BASE}/musica"})
        assert bot.salvos_usuario[-1]["fav_links"]["> fav: Antigo"] == f"{URL_BASE}/musica"

    @pytest.mark.asyncio
    async def test_guarda_favorito_comum_do_usuario_com_url_invalida_e_recusado(self):
        bot = ModalBot()
        inter = await importar(bot, ViewMode.fav_manager, {"Comum": "isto-nao-e-url"})
        assert bot.salvos_usuario == [] and "link inválido" in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_integracao_itg_com_url_valida_continua_aceita(self):
        bot = ModalBot()
        await importar(bot, ViewMode.integrations_manager, {"> itg: Antiga": f"{URL_BASE}/sets"})
        assert url_guardada(bot.salvos_usuario[-1]["integration_links"]["> itg: Antiga"]) == f"{URL_BASE}/sets"


class TestKI46ErrosDoImportadorDeIntegracoes:
    """Antes do ``defer`` o Discord só aceita ``send``/``defer``: ``edit_original_message`` falha (modo ``estrito``)."""

    CASOS = {
        "texto_invalido": {"【YT】: Canal": "isto-nao-e-url"},
        "objeto_invalido": {"【YT】: Canal": {"url": "isto-nao-e-url"}},
        "url_longa_demais": {"【YT】: Canal": f"{URL_BASE}/" + "a" * 200},
    }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caso", CASOS)
    async def test_erro_de_validacao_responde_por_um_caminho_valido_antes_do_defer(self, caso):
        bot = ModalBot()
        try:
            inter = await importar(bot, ViewMode.integrations_manager, self.CASOS[caso], estrito=True)
        except RuntimeError as erro:
            pytest.fail(f"KI-46: {erro}")
        assert bot.salvos_usuario == [] and inter.texto, "o usuário precisa receber o motivo da recusa"

    @pytest.mark.asyncio
    async def test_guarda_importacao_valida_nao_depende_do_caminho_de_erro(self):
        bot = ModalBot()
        await importar(bot, ViewMode.integrations_manager, {"【YT】: Canal": f"{URL_BASE}/c"}, estrito=True)
        assert bot.salvos_usuario


class TestKI47ItensMalFormadosNoImportadorDoServidor:
    """Item que não é objeto, ou sem ``url``/``description``, levanta KeyError/TypeError sem aviso ao usuário."""

    ITENS = {
        "texto": "https://exemplo.invalid/a",
        "lista": ["https://exemplo.invalid/a"],
        "numero": 42,
        "nulo": None,
        "sem_url": {"description": "d"},
        "sem_description": {"url": "https://exemplo.invalid/a"},
        "url_nao_texto": {"url": 123, "description": "d"},
        "description_nao_texto": {"url": "https://exemplo.invalid/a", "description": 5},
    }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("item", ITENS)
    async def test_item_mal_formado_e_recusado_com_mensagem_clara(self, item):
        bot = ModalBot()
        try:
            inter = await importar(bot, ViewMode.guild_fav_manager, {"Item": self.ITENS[item]})
        except (KeyError, TypeError) as erro:
            pytest.fail(f"KI-47: {type(erro).__name__} escapou do importador: {erro}")
        assert bot.salvos_servidor == [] and inter.texto, "o usuário precisa receber o motivo da recusa"

    @pytest.mark.asyncio
    async def test_item_mal_formado_com_nome_fav_tambem_e_recusado(self):
        bot = ModalBot()
        try:
            inter = await importar(bot, ViewMode.guild_fav_manager, {"> fav: Item": "https://exemplo.invalid/a"})
        except (KeyError, TypeError) as erro:
            pytest.fail(f"KI-47: {type(erro).__name__} escapou do importador: {erro}")
        assert bot.salvos_servidor == [] and inter.texto

    @pytest.mark.asyncio
    async def test_mensagem_do_limite_de_descricao_cita_o_limite_certo(self):
        bot = ModalBot()
        conteudo = {"Item": {"url": f"{URL_BASE}/a", "description": "d" * 51}}
        inter = await importar(bot, ViewMode.guild_fav_manager, conteudo)
        assert bot.salvos_servidor == [] and "50" in inter.texto, "KI-47: o limite de descrição é 50"
        assert str(bot.config["USER_FAV_MAX_URL_LENGTH"]) not in inter.texto, "KI-47: citou o limite da URL"

    @pytest.mark.asyncio
    async def test_guarda_descricao_com_exatamente_50_caracteres_e_aceita(self):
        bot = ModalBot()
        conteudo = {"Item": {"url": f"{URL_BASE}/a", "description": "d" * 50}}
        await importar(bot, ViewMode.guild_fav_manager, conteudo)
        assert bot.salvos_servidor[-1]["player_controller"]["fav_links"] == conteudo


# ============================================================================ KI-43 — setguildprefix e enable_prefixed_commands

SERVIDOR_DO_COMANDO = 7001
SERVIDOR_ALVO = 123456789012345678  # 18 dígitos: passa a checagem de tamanho do comando


class OwnerBot:
    def __init__(self):
        self.config = {"EXTRA_HINTS": ""}
        self.pool = SimpleNamespace(guild_prefix_cache={})
        self.gravados = []

    async def get_global_data(self, id_, *, db_name):
        return {"prefix": ""}

    async def update_global_data(self, id_, data, *, db_name):
        self.gravados.append((id_, copy.deepcopy(data)))

    def get_color(self, *args):
        return 0


def owner_com_contexto():
    bot = OwnerBot()
    enviados = []

    async def enviar(*args, **kwargs):
        enviados.append(kwargs)

    ctx = SimpleNamespace(
        bot=bot, guild=SimpleNamespace(id=SERVIDOR_DO_COMANDO, me=SimpleNamespace(), name="origem"), send=enviar
    )
    return legacy_cmds.Owner(bot), ctx, bot


class TestKI43PrefixoDoServidor:
    """``setguildprefix`` grava o cache em ``ctx.guild.id`` (servidor onde o dono digitou) em vez de ``server_id``
    (o servidor alterado), e o prefixo do servidor errado passa a valer."""

    @pytest.mark.asyncio
    async def test_prefixo_novo_fica_no_cache_do_servidor_alvo_ou_o_cache_dele_e_invalidado(self):
        cog, ctx, bot = owner_com_contexto()
        cache = bot.pool.guild_prefix_cache
        cache[SERVIDOR_ALVO] = "velho"
        await legacy_cmds.Owner.setguildprefix.callback(cog, ctx, SERVIDOR_ALVO, ">>")
        assert cache.get(SERVIDOR_ALVO, ">>") == ">>", "KI-43: o cache do servidor alterado ficou com o prefixo velho"

    @pytest.mark.asyncio
    async def test_prefixo_removido_zera_ou_invalida_o_cache_do_servidor_alvo(self):
        cog, ctx, bot = owner_com_contexto()
        cache = bot.pool.guild_prefix_cache
        cache[SERVIDOR_ALVO] = ">>"
        await legacy_cmds.Owner.setguildprefix.callback(cog, ctx, SERVIDOR_ALVO, "   ")
        assert cache.get(SERVIDOR_ALVO, "") == "", "KI-43: o prefixo foi removido, mas o cache ainda tem o antigo"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("prefixo", [">>", "   "])
    async def test_o_cache_do_servidor_onde_o_comando_foi_usado_nao_e_tocado(self, prefixo):
        cog, ctx, bot = owner_com_contexto()
        cache = bot.pool.guild_prefix_cache
        cache[SERVIDOR_DO_COMANDO] = "?"
        await legacy_cmds.Owner.setguildprefix.callback(cog, ctx, SERVIDOR_ALVO, prefixo)
        assert cache[SERVIDOR_DO_COMANDO] == "?", "KI-43: o prefixo de OUTRO servidor foi parar no cache deste"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("prefixo", "esperado"), [(">>", ">>"), ("   ", "")])
    async def test_guarda_o_banco_recebe_o_prefixo_no_id_do_servidor_alvo(self, prefixo, esperado):
        cog, ctx, bot = owner_com_contexto()
        await legacy_cmds.Owner.setguildprefix.callback(cog, ctx, SERVIDOR_ALVO, prefixo)
        assert bot.gravados == [(SERVIDOR_ALVO, {"prefix": esperado})]

    @pytest.mark.asyncio
    async def test_ki45_sem_prefixo_remove_o_prefixo_personalizado_sem_erro(self):
        """KI-45: ``setguildprefix <id>`` sem prefixo é o uso documentado para remover (``prefix=None``)."""
        cog, ctx, bot = owner_com_contexto()
        try:
            await legacy_cmds.Owner.setguildprefix.callback(cog, ctx, SERVIDOR_ALVO)
        except AttributeError as erro:
            pytest.fail(f"KI-45: {erro}")
        assert bot.gravados == [(SERVIDOR_ALVO, {"prefix": ""})]

    @pytest.mark.asyncio
    async def test_ki45_sem_prefixo_zera_o_cache_do_servidor_alvo_e_nao_toca_no_do_comando(self):
        cog, ctx, bot = owner_com_contexto()
        cache = bot.pool.guild_prefix_cache
        cache.update({SERVIDOR_ALVO: ">>", SERVIDOR_DO_COMANDO: "?"})
        try:
            await legacy_cmds.Owner.setguildprefix.callback(cog, ctx, SERVIDOR_ALVO)
        except AttributeError as erro:
            pytest.fail(f"KI-45: {erro}")
        assert cache.get(SERVIDOR_ALVO, "") == "" and cache[SERVIDOR_DO_COMANDO] == "?"

    @pytest.mark.asyncio
    async def test_guarda_setprefix_e_resetprefix_usam_o_cache_do_proprio_servidor(self):
        cog, ctx, bot = owner_com_contexto()
        cache = bot.pool.guild_prefix_cache
        ctx.guild.id = SERVIDOR_ALVO
        await legacy_cmds.Owner.setprefix.callback(cog, ctx, ">>")
        assert cache == {SERVIDOR_ALVO: ">>"}


VER_DO_MODELO_COM_O_CAMPO_ORFAO = 1.10


class TestKI43CampoOrfaoEnablePrefixedCommands:
    """``enable_prefixed_commands`` está no modelo do servidor, mas nenhum código lê ou grava o campo."""

    def test_o_campo_orfao_nao_esta_mais_no_modelo_do_servidor(self):
        assert "enable_prefixed_commands" not in db_models[DBModel.guilds], "KI-43: campo órfão ainda no modelo"

    def test_a_versao_do_modelo_do_servidor_foi_incrementada(self):
        """Regra do projeto: mudou o formato do documento, incrementa ``ver`` (era 1.10 com o campo órfão)."""
        assert db_models[DBModel.guilds]["ver"] > VER_DO_MODELO_COM_O_CAMPO_ORFAO

    @pytest.mark.asyncio
    async def test_guarda_documento_antigo_com_o_campo_e_lido_sem_quebrar_e_sem_perder_dados(self, tmp_path):
        pasta = str(tmp_path / "banco")
        antigo = {
            "_id": "900",
            "ver": 1.0,
            "autoplay": True,
            "djroles": [111, 222],
            "enable_prefixed_commands": False,
            "player_controller": {"channel": 123, "message_id": 456, "fav_links": {}},
        }
        LocalDatabase(dir_=pasta)._connect["bot1"][DBModel.guilds].insert_one(copy.deepcopy(antigo))

        dados = await LocalDatabase(dir_=pasta).get_data("900", db_name=DBModel.guilds, collection="bot1")

        assert dados["enable_prefixed_commands"] is False, "o valor salvo do documento antigo deve ser preservado"
        assert dados["djroles"] == [111, 222] and dados["autoplay"] is True
        assert dados["player_controller"]["channel"] == 123
        assert dados["ver"] == db_models[DBModel.guilds]["ver"] and dados["_id"] == "900"

    @pytest.mark.asyncio
    async def test_guarda_documento_antigo_sem_o_campo_e_lido_e_migrado(self, tmp_path):
        pasta = str(tmp_path / "banco")
        antigo = {"_id": "901", "ver": 1.0, "djroles": [5], "player_controller": {"channel": 1, "fav_links": {}}}
        LocalDatabase(dir_=pasta)._connect["bot1"][DBModel.guilds].insert_one(copy.deepcopy(antigo))

        dados = await LocalDatabase(dir_=pasta).get_data("901", db_name=DBModel.guilds, collection="bot1")

        assert dados["djroles"] == [5] and dados["ver"] == db_models[DBModel.guilds]["ver"]
        assert dados["enable_restrict_mode"] is False, "as demais chaves novas do modelo continuam recebendo o padrão"


# ============================================================================ reforço pós-mutação (sobreviventes)


class TestResetComRegistroDeMensagemIncompleto:
    """O reset não pode depender de a mensagem ter thread nem de o ``message_id`` do banco ser válido."""

    def test_guarda_mensagem_sem_thread_e_arquivada_sem_erro(self, world):
        configured(world, thread=False)
        assert run_reset(world) is None
        assert (world.saved["channel"], world.saved["message_id"]) == (None, None)
        assert len(world.j.of("message.edit")) == 1 and world.j.of("thread.edit") == []

    @pytest.mark.parametrize("message_id", [None, "abc", ""])
    def test_guarda_message_id_ausente_ou_invalido_nao_impede_o_reset(self, world, message_id):
        configured(world)
        world.db.doc["player_controller"]["message_id"] = message_id
        assert run_reset(world) is None, "o canal continua configurado: o reset precisa limpar o registro"
        assert (world.saved["channel"], world.saved["message_id"]) == (None, None)
        assert world.j.of("message.edit") == []


def url_com_tamanho(prefixo, tamanho):
    return prefixo + "a" * (tamanho - len(prefixo))


class TestImportadorDeIntegracoesAvatarELimites:
    """O avatar do objeto ``{url, avatar}`` é validado (URL, texto, até 250 caracteres) e a URL vai até 150."""

    PREFIXO = "https://avatar.invalid/"

    async def importar_com_avatar(self, avatar):
        bot = ModalBot()
        inter = await importar(
            bot,
            ViewMode.integrations_manager,
            {"【YT】: Canal": {"url": f"{URL_BASE}/c", "avatar": avatar}},
            estrito=True,
        )
        return bot, inter

    @pytest.mark.asyncio
    @pytest.mark.parametrize("avatar", ["isto-nao-e-url", "ftp://exemplo.invalid/a.png", 123, ["x"], {"u": 1}, True])
    async def test_avatar_invalido_derruba_a_importacao(self, avatar):
        bot, inter = await self.importar_com_avatar(avatar)
        assert bot.salvos_usuario == [] and "link inválido" in inter.texto

    @pytest.mark.asyncio
    async def test_avatar_com_250_caracteres_e_aceito_e_com_251_e_recusado(self):
        aceito, _ = await self.importar_com_avatar(url_com_tamanho(self.PREFIXO, 250))
        assert aceito.salvos_usuario, "250 caracteres é o limite do avatar"
        recusado, inter = await self.importar_com_avatar(url_com_tamanho(self.PREFIXO, 251))
        assert recusado.salvos_usuario == [] and "link inválido" in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize("avatar", [None, ""])
    async def test_avatar_ausente_ou_vazio_e_aceito(self, avatar):
        bot, _ = await self.importar_com_avatar(avatar)
        assert url_guardada(bot.salvos_usuario[-1]["integration_links"]["【YT】: Canal"]) == f"{URL_BASE}/c"

    @pytest.mark.asyncio
    async def test_url_com_150_caracteres_e_aceita_e_com_151_e_recusada(self):
        for tamanho, aceita in ((150, True), (151, False)):
            bot = ModalBot()
            nome = {"【YT】: Canal": url_com_tamanho(f"{URL_BASE}/", tamanho)}
            inter = await importar(bot, ViewMode.integrations_manager, nome, estrito=True)
            assert bool(bot.salvos_usuario) is aceita, f"{tamanho} caracteres: {inter.texto!r}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("valor", [5, None, ["https://exemplo.invalid/a"], {"url": 5}, {"url": None}, {}])
    async def test_valor_que_nao_e_texto_nem_objeto_com_url_e_recusado_antes_do_defer(self, valor):
        bot = ModalBot()
        try:
            inter = await importar(bot, ViewMode.integrations_manager, {"【YT】: Canal": valor}, estrito=True)
        except (RuntimeError, TypeError, AttributeError) as erro:
            pytest.fail(f"KI-46: {type(erro).__name__}: {erro}")
        assert bot.salvos_usuario == [] and "link inválido" in inter.texto


class TestImportadoresGravamSoOsCamposEsperados:
    @pytest.mark.asyncio
    async def test_servidor_grava_so_url_e_description(self):
        bot = ModalBot()
        item = {"url": f"{URL_BASE}/a", "description": "d", "extra": "x", "outro": 1}
        await importar(bot, ViewMode.guild_fav_manager, {"Item": item})
        assert bot.salvos_servidor[-1]["player_controller"]["fav_links"]["Item"] == {
            "url": f"{URL_BASE}/a",
            "description": "d",
        }

    @pytest.mark.asyncio
    async def test_integracao_grava_so_url_e_avatar(self):
        bot = ModalBot()
        item = {"url": f"{URL_BASE}/c", "avatar": f"{URL_BASE}/a.png", "title": "t", "extra": 1}
        await importar(bot, ViewMode.integrations_manager, {"【YT】: Canal": item})
        assert bot.salvos_usuario[-1]["integration_links"]["【YT】: Canal"] == {
            "url": f"{URL_BASE}/c",
            "avatar": f"{URL_BASE}/a.png",
        }

    @pytest.mark.asyncio
    async def test_integracao_sem_avatar_nao_ganha_a_chave(self):
        bot = ModalBot()
        await importar(bot, ViewMode.integrations_manager, {"【YT】: Canal": {"url": f"{URL_BASE}/c", "extra": 1}})
        assert bot.salvos_usuario[-1]["integration_links"]["【YT】: Canal"] == {"url": f"{URL_BASE}/c"}


class TestImportadoresRecusamJsonQueNaoEObjetoOuEVazio:
    """Lista, texto, número, ``null`` e ``{}`` são recusados com mensagem, nos três modos, sem gravar nada."""

    MODOS = [ViewMode.fav_manager, ViewMode.guild_fav_manager, ViewMode.integrations_manager]
    CONTEUDOS = ["[]", '"texto"', "5", "null", "{}", '[{"url": "https://exemplo.invalid/a"}]']

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS)
    @pytest.mark.parametrize("conteudo", CONTEUDOS)
    async def test_recusa_com_mensagem_e_sem_gravar(self, modo, conteudo):
        bot = ModalBot()
        inter = await importar(bot, modo, conteudo, estrito=True)
        assert bot.salvos_usuario == [] and bot.salvos_servidor == []
        assert "objeto json" in inter.texto, f"o usuário precisa receber o motivo: {inter.texto!r}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("valor", [5, None, ["https://exemplo.invalid/a"], {"url": "https://exemplo.invalid/a"}])
    async def test_favorito_do_usuario_que_nao_e_texto_e_recusado_sem_excecao(self, valor):
        bot = ModalBot()
        try:
            inter = await importar(bot, ViewMode.fav_manager, {"Item": valor}, estrito=True)
        except (TypeError, AttributeError) as erro:
            pytest.fail(f"{type(erro).__name__} escapou do importador: {erro}")
        assert bot.salvos_usuario == [] and "link inválido" in inter.texto

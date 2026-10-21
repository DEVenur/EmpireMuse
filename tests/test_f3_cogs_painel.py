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
from empiremuse.utils.music.converters import perms_translations, time_format
from empiremuse.rules.limits import FAV_NAME_MAX, FAV_NAME_MIN, ITG_TITLE_MAX
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.others import CustomContext
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
from tests.helpers_modais import (
    SERVIDOR_ALVO,
    SERVIDOR_DO_COMANDO,
    URL_BASE,
    ModalBot,
    ModalInteraction,
    adicionar_favorito,
    adicionar_integracao,
    arquivo_com,
    exportar_integracoes,
    favs_cheios,
    gravados,
    importar,
    integracoes_cheias,
    modal_view,
    owner_com_contexto,
    url_de,
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


@pytest.fixture(autouse=True)
def _sem_idle_embed(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    monkeypatch.setattr(interactions, "process_idle_embed", nada)


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
        "sem_url": {"description": "ddd"},
        "sem_description": {"url": "https://exemplo.invalid/a"},
        "url_nao_texto": {"url": 123, "description": "ddd"},
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
        conteudo = {"Item": {"url": f"{URL_BASE}/a", "description": "d" * 101}}
        inter = await importar(bot, ViewMode.guild_fav_manager, conteudo)
        assert bot.salvos_servidor == [] and "100" in inter.texto, "KI-47: o limite de descrição é 100"
        assert str(bot.config["USER_FAV_MAX_URL_LENGTH"]) not in inter.texto, "KI-47: citou o limite da URL"

    @pytest.mark.asyncio
    async def test_guarda_descricao_com_exatamente_50_caracteres_e_aceita(self):
        bot = ModalBot()
        conteudo = {"Item": {"url": f"{URL_BASE}/a", "description": "d" * 50}}
        await importar(bot, ViewMode.guild_fav_manager, conteudo)
        assert bot.salvos_servidor[-1]["player_controller"]["fav_links"] == conteudo


# ============================================================================ KI-43 — setguildprefix e enable_prefixed_commands


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
    """O avatar do objeto ``{url, avatar}`` é validado (URL, texto, até 250 caracteres) e a URL vai até 200 (Etapa 5 da F3-5b, D4; antes 150)."""

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
    async def test_url_com_200_caracteres_e_aceita_e_com_201_e_recusada(self):
        for tamanho, aceita in ((200, True), (201, False)):
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
        item = {"url": f"{URL_BASE}/a", "description": "ddd", "extra": "x", "outro": 1}
        await importar(bot, ViewMode.guild_fav_manager, {"Item": item})
        assert bot.salvos_servidor[-1]["player_controller"]["fav_links"]["Item"] == {
            "url": f"{URL_BASE}/a",
            "description": "ddd",
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


# ============================================================================ endurecimento dos importadores (KI-49 … KI-54)

MODOS_DE_IMPORTACAO = [
    pytest.param(ViewMode.fav_manager, id="favoritos"),
    pytest.param(ViewMode.guild_fav_manager, id="servidor"),
    pytest.param(ViewMode.integrations_manager, id="integracoes"),
]


def assert_url_gravada_e_limpa(url):
    assert isinstance(url, str) and url.startswith("http"), f"URL gravada inesperada: {url!r}"
    assert not any(c.isspace() for c in url), f"KI-49: espaço/quebra de linha gravado na URL: {url!r}"
    assert "@everyone" not in url, f"KI-49: texto extra gravado na URL: {url!r}"
    assert "](" not in url and ")[" not in url, f"KI-49: markdown de link sobrou na URL: {url!r}"


class TestKI49UrlInteiraENormalizada:
    """Os importadores só olham o PREFIXO da URL (``URL_REG.match``) e gravam o texto inteiro, com o que vier depois."""

    SUJAS = {
        "quebra_de_linha_e_everyone": "https://a.com/x\n@everyone",
        "espaco_e_everyone": "https://a.com/x @everyone",
        "markdown_de_link": "https://a.com/x)[x](https://evil.invalid/p)",
    }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    @pytest.mark.parametrize("caso", SUJAS)
    async def test_texto_extra_na_url_nunca_e_gravado(self, modo, caso):
        bot = ModalBot()
        await importar(bot, modo, arquivo_com(modo, "Musica", self.SUJAS[caso]))
        for valor in gravados(bot, modo).values():
            assert_url_gravada_e_limpa(url_de(valor))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "avatar", ["https://a.com/a.png\n@everyone", "https://a.com/a.png)[x](https://evil.invalid)"]
    )
    async def test_texto_extra_no_avatar_nunca_e_gravado(self, avatar):
        bot = ModalBot()
        modo = ViewMode.integrations_manager
        await importar(bot, modo, arquivo_com(modo, "Canal", f"{URL_BASE}/c", avatar=avatar))
        for valor in gravados(bot, modo).values():
            assert_url_gravada_e_limpa(valor.get("avatar", "https://ausente.invalid"))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("avatar", ["", None])
    async def test_avatar_vazio_vale_como_ausente_e_nao_grava_a_chave(self, avatar):
        bot = ModalBot()
        modo = ViewMode.integrations_manager
        await importar(bot, modo, arquivo_com(modo, "Canal", f"{URL_BASE}/c", avatar=avatar))
        assert gravados(bot, modo) == {"Canal": {"url": f"{URL_BASE}/c"}}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    async def test_guarda_url_limpa_e_gravada_como_veio(self, modo):
        bot = ModalBot()
        await importar(bot, modo, arquivo_com(modo, "Musica", f"{URL_BASE}/faixa?x=1&y=2"))
        assert url_de(gravados(bot, modo)["Musica"]) == f"{URL_BASE}/faixa?x=1&y=2"


class TestKI50NomesDasEntradas:
    """O nome segue o limite do painel (``account_links``): favoritos e links do servidor 2–25; integrações 1–90."""

    LIMITES = {
        ViewMode.fav_manager: (FAV_NAME_MIN, FAV_NAME_MAX),
        ViewMode.guild_fav_manager: (FAV_NAME_MIN, FAV_NAME_MAX),
        ViewMode.integrations_manager: (1, ITG_TITLE_MAX),
    }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    @pytest.mark.parametrize("nome", ["", "   "])
    async def test_nome_vazio_e_recusado_com_mensagem(self, modo, nome):
        bot = ModalBot()
        inter = await importar(bot, modo, arquivo_com(modo, nome, f"{URL_BASE}/a"))
        assert gravados(bot, modo) == {}, "KI-50: entrada sem nome foi gravada"
        assert inter.texto, "o usuário precisa receber o motivo da recusa"

    @pytest.mark.asyncio
    async def test_nome_de_um_caractere_e_recusado_em_favoritos_e_links_do_servidor(self):
        for modo in (ViewMode.fav_manager, ViewMode.guild_fav_manager):
            bot = ModalBot()
            inter = await importar(bot, modo, arquivo_com(modo, "a", f"{URL_BASE}/a"))
            assert gravados(bot, modo) == {} and inter.texto, f"KI-50: nome de 1 caractere aceito no modo {modo!r}"

    @pytest.mark.asyncio
    async def test_titulo_de_integracao_com_mais_de_90_caracteres_e_recusado(self):
        bot = ModalBot()
        modo = ViewMode.integrations_manager
        inter = await importar(bot, modo, arquivo_com(modo, "t" * (ITG_TITLE_MAX + 1), f"{URL_BASE}/a"))
        assert gravados(bot, modo) == {} and inter.texto, "KI-50: título de 91 caracteres gravado"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", [ViewMode.fav_manager, ViewMode.guild_fav_manager])
    async def test_guarda_nome_de_26_caracteres_e_recusado(self, modo):
        bot = ModalBot()
        inter = await importar(bot, modo, arquivo_com(modo, "n" * (FAV_NAME_MAX + 1), f"{URL_BASE}/a"))
        assert gravados(bot, modo) == {} and inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    async def test_guarda_nomes_nos_limites_exatos_sao_aceitos(self, modo):
        minimo, maximo = self.LIMITES[modo]
        for nome in ("n" * minimo, "n" * maximo):
            bot = ModalBot()
            await importar(bot, modo, arquivo_com(modo, nome, f"{URL_BASE}/a"))
            assert list(gravados(bot, modo)) == [nome]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    async def test_nome_e_gravado_sem_os_espacos_das_pontas(self, modo):
        bot = ModalBot()
        await importar(bot, modo, arquivo_com(modo, "  Rock  ", f"{URL_BASE}/a"))
        assert list(gravados(bot, modo)) == ["Rock"], "KI-50: o nome gravado precisa ser o normalizado"

    @pytest.mark.asyncio
    async def test_reimportar_o_mesmo_nome_com_maiuscula_no_limite_sobrescreve_sem_ocupar_vaga_nos_favoritos(self):
        bot = ModalBot(favs=2, fav_links={"Rock": f"{URL_BASE}/velho", "Pop": f"{URL_BASE}/pop"})
        inter = await importar(bot, ViewMode.fav_manager, {"Rock": f"{URL_BASE}/novo"})
        assert gravados(bot, ViewMode.fav_manager) == {"Rock": f"{URL_BASE}/novo", "Pop": f"{URL_BASE}/pop"}, (
            f"KI-50: a remoção procura outro nome que o gravado: {inter.texto!r}"
        )

    @pytest.mark.asyncio
    async def test_reimportar_o_mesmo_titulo_com_maiuscula_no_limite_sobrescreve_sem_ocupar_vaga_nas_integracoes(self):
        antigas = {"Canal": {"url": f"{URL_BASE}/velho"}, "Outro": {"url": f"{URL_BASE}/o"}}
        bot = ModalBot(integracoes=2, integration_links=antigas)
        inter = await importar(bot, ViewMode.integrations_manager, {"Canal": f"{URL_BASE}/novo"})
        assert list(gravados(bot, ViewMode.integrations_manager)) == ["Canal", "Outro"] or set(
            gravados(bot, ViewMode.integrations_manager)
        ) == {"Canal", "Outro"}, f"KI-50: a remoção procura outro título que o gravado: {inter.texto!r}"

    @pytest.mark.asyncio
    async def test_guarda_links_do_servidor_reimportar_o_mesmo_nome_no_limite_de_25_sobrescreve(self):
        bot = ModalBot()
        existentes = {f"Item{i}": {"url": f"{URL_BASE}/{i}", "description": "ddd"} for i in range(24)}
        existentes["Rock"] = {"url": f"{URL_BASE}/velho", "description": "ddd"}
        bot.guild_data["player_controller"]["fav_links"] = existentes
        await importar(
            bot, ViewMode.guild_fav_manager, arquivo_com(ViewMode.guild_fav_manager, "Rock", f"{URL_BASE}/n")
        )
        salvos = gravados(bot, ViewMode.guild_fav_manager)
        assert len(salvos) == 25 and salvos["Rock"]["url"] == f"{URL_BASE}/n"


class TestKI51RecusaNaoMudaOCache:
    """``get_data`` devolve o MESMO objeto de cache (como o ``MongoDatabase``): remover entradas antes de recusar
    deixa a memória diferente do banco."""

    URL = f"{URL_BASE}/a"

    def cenarios(self):
        itens_servidor = {f"item{i}": {"url": self.URL, "description": "ddd"} for i in range(26)}
        return {
            "favoritos_acima_da_cota": (
                ViewMode.fav_manager,
                dict(favs=3, fav_links=favs_cheios(3)),
                {"fav0": self.URL, "n1": self.URL, "n2": self.URL, "n3": self.URL},
            ),
            "favoritos_sem_espaco_para_os_novos": (
                ViewMode.fav_manager,
                dict(favs=3, fav_links=favs_cheios(3)),
                {"fav0": self.URL, "d": self.URL, "e": self.URL},
            ),
            "favoritos_com_nome_longo_demais": (
                ViewMode.fav_manager,
                dict(favs=10, fav_links=favs_cheios(3)),
                {"fav0": self.URL, "n" * 26: self.URL},
            ),
            "integracoes_sem_espaco": (
                ViewMode.integrations_manager,
                dict(integracoes=2, integration_links={"antiga0": {"url": self.URL}, "antiga1": {"url": self.URL}}),
                {"antiga0": self.URL, "n1": self.URL, "n2": self.URL},
            ),
            "servidor_acima_de_25": (
                ViewMode.guild_fav_manager,
                dict(),
                itens_servidor,
            ),
            "servidor_com_nome_longo_demais": (
                ViewMode.guild_fav_manager,
                dict(),
                {"item0": {"url": self.URL, "description": "ddd"}, "n" * 26: {"url": self.URL, "description": "ddd"}},
            ),
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "caso",
        [
            "favoritos_acima_da_cota",
            "favoritos_sem_espaco_para_os_novos",
            "favoritos_com_nome_longo_demais",
            "integracoes_sem_espaco",
            "servidor_acima_de_25",
            "servidor_com_nome_longo_demais",
        ],
    )
    async def test_importacao_recusada_deixa_o_documento_em_cache_intacto(self, caso):
        modo, config, arquivo = self.cenarios()[caso]
        bot = ModalBot(**config)
        bot.guild_data["player_controller"]["fav_links"] = {
            "item0": {"url": self.URL, "description": "ddd"},
            "item1": {"url": self.URL, "description": "ddd"},
            "item2": {"url": self.URL, "description": "ddd"},
        }
        antes = copy.deepcopy((bot.user_data, bot.guild_data))
        inter = await importar(bot, modo, arquivo)
        assert inter.texto, "a importação precisa ter sido recusada com mensagem"
        assert bot.salvos_usuario == [] and bot.salvos_servidor == []
        assert (bot.user_data, bot.guild_data) == antes, "KI-51: entradas foram removidas da memória antes da recusa"

    @pytest.mark.asyncio
    async def test_guarda_importacao_aceita_sobrescreve_e_grava_o_documento_inteiro(self):
        bot = ModalBot(favs=5, fav_links=favs_cheios(3))
        await importar(bot, ViewMode.fav_manager, {"fav0": f"{URL_BASE}/novo", "extra": self.URL})
        assert gravados(bot, ViewMode.fav_manager) == {
            "fav1": f"{URL_BASE}/1",
            "fav2": f"{URL_BASE}/2",
            "fav0": f"{URL_BASE}/novo",
            "extra": self.URL,
        }


class TestKI52TrechoEcoadoNasMensagensDeErro:
    """Cada mensagem ao usuário fica abaixo de 2000 caracteres e um ``` do valor não fecha o bloco de código."""

    GIGANTE = 5000

    def casos(self):
        gigante = "x" * self.GIGANTE
        url_gigante = "https://exemplo.invalid/" + "a" * self.GIGANTE
        return {
            "favorito_url_longa": (ViewMode.fav_manager, {"Item": url_gigante}),
            "favorito_invalido_gigante": (ViewMode.fav_manager, {"Item": gigante}),
            "favorito_com_crases": (ViewMode.fav_manager, {"Item": "nao```@everyone"}),
            "favorito_nome_gigante": (ViewMode.fav_manager, {"n" * self.GIGANTE: f"{URL_BASE}/a"}),
            "favorito_nao_texto_gigante": (ViewMode.fav_manager, {"Item": ["a" * self.GIGANTE]}),
            "servidor_url_longa": (ViewMode.guild_fav_manager, {"Item": {"url": url_gigante, "description": "ddd"}}),
            "servidor_descricao_gigante": (
                ViewMode.guild_fav_manager,
                {"Item": {"url": f"{URL_BASE}/a", "description": "d" * self.GIGANTE}},
            ),
            "servidor_url_com_crases": (
                ViewMode.guild_fav_manager,
                {"Item": {"url": "nao```@everyone", "description": "ddd"}},
            ),
            "servidor_nome_gigante": (
                ViewMode.guild_fav_manager,
                {"n" * self.GIGANTE: {"url": f"{URL_BASE}/a", "description": "ddd"}},
            ),
            "integracao_url_longa": (ViewMode.integrations_manager, {"Canal": url_gigante}),
            "integracao_com_crases": (ViewMode.integrations_manager, {"Canal": "nao```@everyone"}),
            "integracao_url_objeto_gigante": (
                ViewMode.integrations_manager,
                {"Canal": {"url": ["a" * self.GIGANTE]}},
            ),
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "caso",
        [
            "favorito_url_longa",
            "favorito_invalido_gigante",
            "favorito_com_crases",
            "favorito_nome_gigante",
            "favorito_nao_texto_gigante",
            "servidor_url_longa",
            "servidor_descricao_gigante",
            "servidor_url_com_crases",
            "servidor_nome_gigante",
            "integracao_url_longa",
            "integracao_com_crases",
            "integracao_url_objeto_gigante",
        ],
    )
    async def test_mensagem_de_erro_cabe_no_discord_e_nao_quebra_o_bloco(self, caso):
        modo, arquivo = self.casos()[caso]
        bot = ModalBot()
        inter = await importar(bot, modo, arquivo)
        assert inter.enviados, "o usuário precisa receber o motivo da recusa"
        for mensagem in inter.enviados:
            assert len(mensagem) < 2000, (
                f"KI-52: mensagem de {len(mensagem)} caracteres (o Discord recusa acima de 2000)"
            )
            assert mensagem.count("```") <= 2, f"KI-52: o valor do usuário fechou/abriu o bloco: {mensagem[:120]!r}"

    @pytest.mark.asyncio
    async def test_guarda_mensagem_curta_continua_mostrando_o_valor_recusado(self):
        bot = ModalBot()
        inter = await importar(bot, ViewMode.fav_manager, {"Item": "isto-nao-e-url"})
        assert "isto-nao-e-url" in inter.texto and "link inválido" in inter.texto


class TestKI53RefreshDepoisDaImportacao:
    """O refresh final chama ``view.build_embed()``, que a ``FavMenuView`` não tem (só ``build_txt``)."""

    ARQUIVOS = {
        ViewMode.fav_manager: {"Rock": f"{URL_BASE}/a"},
        ViewMode.guild_fav_manager: {"Rock": {"url": f"{URL_BASE}/a", "description": "ddd"}},
        ViewMode.integrations_manager: {"Canal": f"{URL_BASE}/a"},
    }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    async def test_importacao_pelo_slash_atualiza_o_menu_sem_erro(self, modo):
        bot = ModalBot()
        view = modal_view(bot, modo, real=True)
        try:
            inter = await importar(bot, modo, self.ARQUIVOS[modo], view=view)
        except AttributeError as erro:
            pytest.fail(f"KI-53: o usuário veria um erro depois de importar com sucesso: {erro}")
        assert gravados(bot, modo), "a importação em si funcionou"
        assert view.ctx.atualizacoes, "o menu precisa ser atualizado depois de importar"
        assert "Traceback" not in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    async def test_importacao_pelo_comando_com_prefixo_atualiza_a_mensagem_do_menu_sem_erro(self, modo):
        bot = ModalBot()
        view = modal_view(bot, modo, real=True, prefixo=True)
        try:
            await importar(bot, modo, self.ARQUIVOS[modo], view=view)
        except AttributeError as erro:
            pytest.fail(f"KI-53: o usuário veria um erro depois de importar com sucesso: {erro}")
        assert view.message.atualizacoes, "a mensagem do menu precisa ser atualizada depois de importar"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    async def test_guarda_importacao_recusada_nao_atualiza_o_menu(self, modo):
        bot = ModalBot()
        view = modal_view(bot, modo, real=True)
        await importar(bot, modo, "[]", view=view)
        assert view.ctx.atualizacoes == [] and gravados(bot, modo) == {}


class TestKI54CotaNoModalDeFavorito:
    """No caminho de edição (``name == self.name``) com a entrada já removida em outra tela, a cota não era checada."""

    @pytest.mark.asyncio
    async def test_editar_entrada_removida_com_a_cota_cheia_e_recusado(self):
        bot = ModalBot(favs=2, fav_links=favs_cheios(2))
        inter = await adicionar_favorito(bot, nome="removido", editando="removido")
        assert bot.salvos_usuario == [], "KI-54: a cota foi ultrapassada pelo caminho de edição"
        assert "Não há espaço disponível" in inter.texto

    @pytest.mark.asyncio
    async def test_adicionar_nome_que_ja_existe_e_recusado_e_nao_sobrescreve(self):
        """Etapa 3 (F3-5b, A6): adicionar à mão com um nome que já existe não sobrescreve mais (antes sobrescrevia sem
        ocupar vaga); recusa e não grava. Editar a própria entrada com a cota cheia segue permitido (guarda abaixo)."""
        bot = ModalBot(favs=2, fav_links=favs_cheios(2))
        inter = await adicionar_favorito(bot, nome="fav0", url=f"{URL_BASE}/novo")
        assert bot.salvos_usuario == [] and "já" in inter.texto.lower()
        assert bot.user_data["fav_links"] == favs_cheios(2)

    @pytest.mark.asyncio
    async def test_guarda_editar_entrada_existente_com_a_cota_cheia_continua_permitido(self):
        bot = ModalBot(favs=2, fav_links=favs_cheios(2))
        await adicionar_favorito(bot, nome="fav0", url=f"{URL_BASE}/novo", editando="fav0")
        assert bot.salvos_usuario[-1]["fav_links"]["fav0"] == f"{URL_BASE}/novo"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("config", [dict(favs=0), dict(favs=2, dono=True)], ids=["sem_limite", "dono_do_bot"])
    async def test_guarda_dono_e_sem_limite_continuam_isentos_no_caminho_de_edicao(self, config):
        bot = ModalBot(fav_links=favs_cheios(2), **config)
        await adicionar_favorito(bot, nome="removido", editando="removido")
        assert "removido" in bot.salvos_usuario[-1]["fav_links"]

    @pytest.mark.asyncio
    async def test_guarda_renomear_entrada_existente_com_a_cota_cheia_continua_permitido(self):
        bot = ModalBot(favs=2, fav_links=favs_cheios(2))
        await adicionar_favorito(bot, nome="renomeado", editando="fav0")
        salvo = bot.salvos_usuario[-1]["fav_links"]
        assert "renomeado" in salvo and "fav0" not in salvo and len(salvo) == 2

    @pytest.mark.asyncio
    async def test_guarda_renomear_entrada_removida_com_a_cota_cheia_e_recusado(self):
        bot = ModalBot(favs=2, fav_links=favs_cheios(2))
        inter = await adicionar_favorito(bot, nome="renomeado", editando="removido")
        assert bot.salvos_usuario == [] and "Não há espaço disponível" in inter.texto


# ============================================================================ KI-51 — resíduo na view depois da recusa


class TestKI51ResiduoNaView:
    """A recusa deixava a cópia já podada em ``view.data``/``view.guild_data``; o ``remove_callback`` seguinte
    persistia esse documento e apagava dos dados os itens que o arquivo só ia sobrescrever."""

    URL = f"{URL_BASE}/a"

    def cenario(self, modo):
        """(bot, arquivo recusado, nome do item que o usuário remove depois, atributo da view com os dados)."""
        if modo == ViewMode.guild_fav_manager:
            bot = ModalBot()
            bot.guild_data["player_controller"]["fav_links"] = {
                f"item{i}": {"url": self.URL, "description": "ddd"} for i in range(24)
            }
            arquivo = {
                "item0": {"url": self.URL, "description": "novo"},
                "item1": {"url": self.URL, "description": "novo"},
                "novo1": {"url": self.URL, "description": "ddd"},
                "novo2": {"url": self.URL, "description": "ddd"},
                "novo3": {"url": self.URL, "description": "ddd"},
            }
            return bot, arquivo, "item5", "guild_data"
        if modo == ViewMode.fav_manager:
            bot = ModalBot(favs=5, fav_links=favs_cheios(4))
            arquivo = {"fav0": self.URL, "novo1": self.URL, "novo2": self.URL, "novo3": self.URL}
            return bot, arquivo, "fav2", "data"
        bot = ModalBot(integracoes=5, integration_links={f"canal{i}": {"url": self.URL} for i in range(4)})
        arquivo = {"canal0": self.URL, "novo1": self.URL, "novo2": self.URL, "novo3": self.URL}
        return bot, arquivo, "canal2", "data"

    @staticmethod
    def documento(bot, modo):
        if modo == ViewMode.guild_fav_manager:
            return bot.guild_data
        return bot.user_data

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    async def test_depois_da_recusa_os_dados_da_view_ficam_como_antes(self, modo):
        bot, arquivo, _, atributo = self.cenario(modo)
        view = modal_view(bot, modo)
        setattr(view, atributo, self.documento(bot, modo))  # o que a tela já tinha carregado
        antes = copy.deepcopy(getattr(view, atributo))
        inter = await importar(bot, modo, arquivo, view=view)
        assert inter.texto and bot.salvos_usuario == [] and bot.salvos_servidor == [], (
            "a importação deveria ser recusada"
        )
        assert getattr(view, atributo) == antes, f"KI-51: a recusa deixou a view com dados alterados ({atributo})"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    async def test_remover_um_item_depois_da_recusa_nao_persiste_um_documento_podado(self, modo):
        bot, arquivo, alvo, atributo = self.cenario(modo)
        view = modal_view(bot, modo)
        setattr(view, atributo, self.documento(bot, modo))
        antes = copy.deepcopy(self.documento(bot, modo))
        await importar(bot, modo, arquivo, view=view)

        view.current = alvo
        remocao = ModalInteraction()
        await FavMenuView.remove_callback(view, remocao)

        if modo == ViewMode.guild_fav_manager:
            esperado = copy.deepcopy(antes)
            del esperado["player_controller"]["fav_links"][alvo]
            persistido = bot.salvos_servidor[-1]
        else:
            esperado = copy.deepcopy(antes)
            del esperado["fav_links" if modo == ViewMode.fav_manager else "integration_links"][alvo]
            persistido = bot.salvos_usuario[-1]
        assert persistido == esperado, (
            "KI-51: a remoção persistiu um documento sem os itens que o arquivo sobrescreveria"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    async def test_guarda_importacao_aceita_atualiza_a_view_e_a_remocao_seguinte_enxerga_o_novo_item(self, modo):
        bot, arquivo, alvo, atributo = self.cenario(modo)
        if modo == ViewMode.guild_fav_manager:
            arquivo = {k: arquivo[k] for k in ("item0", "novo1")}
        elif modo == ViewMode.fav_manager:
            arquivo = {k: arquivo[k] for k in ("fav0", "novo1")}
        else:
            arquivo = {k: arquivo[k] for k in ("canal0", "novo1")}
        view = modal_view(bot, modo)
        await importar(bot, modo, arquivo, view=view)
        assert "novo1" in json.dumps(getattr(view, atributo)), "a view precisa refletir o que foi importado"


# ============================================================================ sobreviventes da mutação do endurecimento


def url_com(modo, url, **extra):
    return arquivo_com(modo, "Musica", url, **extra)


class TestUrlDosImportadoresRigorosa:
    """URL INTEIRA validada: texto depois, colchetes e menções em massa são recusados; as pontas são aparadas."""

    TEXTO_DEPOIS = ["https://a.com/x texto extra", "https://a.com/x\ntexto", "https://a.com/x\tfim"]
    COLCHETES = ["https://a.com/x[y", "https://a.com/x]y"]
    MENCOES = ["https://a.com/x@everyone", "https://a.com/x@here", "https://a.com/x@EVERYONE", "https://a.com/x@Here"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    @pytest.mark.parametrize("url", TEXTO_DEPOIS + COLCHETES + MENCOES)
    async def test_url_suja_e_recusada_com_mensagem_e_nada_e_gravado(self, modo, url):
        bot = ModalBot()
        inter = await importar(bot, modo, url_com(modo, url))
        assert gravados(bot, modo) == {}, f"URL suja gravada: {url!r}"
        assert "link inválido" in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize("avatar", TEXTO_DEPOIS + COLCHETES + MENCOES)
    async def test_avatar_sujo_e_recusado_com_mensagem(self, avatar):
        bot = ModalBot()
        modo = ViewMode.integrations_manager
        inter = await importar(bot, modo, url_com(modo, f"{URL_BASE}/c", avatar=avatar))
        assert gravados(bot, modo) == {}
        assert "link inválido" in inter.texto

    @pytest.mark.asyncio
    async def test_mensagem_do_avatar_invalido_cita_o_avatar_e_nao_a_url(self):
        bot = ModalBot()
        modo = ViewMode.integrations_manager
        inter = await importar(bot, modo, url_com(modo, f"{URL_BASE}/boa", avatar="avatar-invalido-123"))
        assert "avatar-invalido-123" in inter.texto and "/boa" not in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    async def test_espacos_nas_pontas_da_url_sao_removidos_ao_gravar(self, modo):
        bot = ModalBot()
        await importar(bot, modo, url_com(modo, "  https://a.com/x  "))
        assert url_de(gravados(bot, modo)["Musica"]) == "https://a.com/x"

    @pytest.mark.asyncio
    async def test_espacos_nas_pontas_do_avatar_sao_removidos_ao_gravar(self):
        bot = ModalBot()
        modo = ViewMode.integrations_manager
        await importar(bot, modo, url_com(modo, f"{URL_BASE}/c", avatar="  https://a.com/a.png  "))
        assert gravados(bot, modo)["Musica"] == {"url": f"{URL_BASE}/c", "avatar": "https://a.com/a.png"}


class TestNomesRepetidosEConfiguracao:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    @pytest.mark.parametrize(
        "repetido", [("Rock", "rock"), ("Rock", " Rock "), ("Rock", "ROCK")], ids=["caixa", "espaco", "maiusculas"]
    )
    async def test_nomes_repetidos_no_proprio_arquivo_sao_recusados(self, modo, repetido):
        bot = ModalBot()
        arquivo = {**arquivo_com(modo, repetido[0], f"{URL_BASE}/1"), **arquivo_com(modo, repetido[1], f"{URL_BASE}/2")}
        inter = await importar(bot, modo, arquivo)
        assert gravados(bot, modo) == {} and inter.texto, (
            "o nome repetido (sem diferenciar caixa) deve recusar o arquivo"
        )

    @pytest.mark.asyncio
    async def test_nome_de_favorito_tem_no_maximo_25_mesmo_com_configuracao_maior(self):
        bot = ModalBot(nome_max=40)
        inter = await importar(bot, ViewMode.fav_manager, {"n" * 26: f"{URL_BASE}/a"})
        assert gravados(bot, ViewMode.fav_manager) == {} and inter.texto

    @pytest.mark.asyncio
    async def test_a_configuracao_menor_que_25_continua_valendo_no_importador_de_favoritos(self):
        recusado = ModalBot(nome_max=10)
        inter = await importar(recusado, ViewMode.fav_manager, {"n" * 11: f"{URL_BASE}/a"})
        assert gravados(recusado, ViewMode.fav_manager) == {} and inter.texto
        aceito = ModalBot(nome_max=10)
        await importar(aceito, ViewMode.fav_manager, {"n" * 10: f"{URL_BASE}/a"})
        assert list(gravados(aceito, ViewMode.fav_manager)) == ["n" * 10]


class TestLimiteDeTaxaDosImportadores:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS_DE_IMPORTACAO)
    @pytest.mark.parametrize(("espera", "segundos"), [(0.4, 1), (7.9, 7)])
    async def test_importacao_dentro_do_limite_de_taxa_avisa_quanto_esperar_e_nao_grava(self, modo, espera, segundos):
        bot = ModalBot(retry_after=espera)
        inter = await importar(bot, modo, arquivo_com(modo, "Musica", f"{URL_BASE}/a"))
        assert gravados(bot, modo) == {}
        assert "aguardar" in inter.texto and time_format(segundos * 1000, use_names=True) in inter.texto


class TestKI52MensagensDeItemMalFormado:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome", ["n" * 5000, "a```b" + "n" * 500])
    async def test_item_mal_formado_com_nome_gigante_ou_com_crases_cabe_no_discord(self, nome):
        bot = ModalBot()
        inter = await importar(bot, ViewMode.guild_fav_manager, {nome: "texto"})
        assert inter.enviados and bot.salvos_servidor == []
        for mensagem in inter.enviados:
            assert len(mensagem) < 2000 and mensagem.count("```") <= 2


class TestModalDeFavoritoNaoAlteraOCacheNemAOrdem:
    @pytest.mark.asyncio
    async def test_recusa_por_cota_ja_estourada_deixa_o_cache_e_a_view_intactos(self):
        """Com o limite diminuído depois (4 favoritos, limite 2), renomear libera 1 vaga mas ainda não cabe."""
        bot = ModalBot(favs=2, fav_links=favs_cheios(4))
        view = modal_view(bot, ViewMode.fav_manager)
        view.data = bot.user_data
        antes = copy.deepcopy(bot.user_data)
        inter = ModalInteraction(user_fav_name="novo", user_fav_url=f"{URL_BASE}/novo")
        await FavModalAdd("fav0", None, view).callback(inter)
        assert bot.salvos_usuario == [] and "Não há espaço disponível" in inter.texto
        assert bot.user_data == antes, "KI-51: a recusa do modal removeu o favorito da memória"
        assert view.data == antes

    @pytest.mark.asyncio
    async def test_editar_a_url_de_um_favorito_mantem_a_posicao_dele_na_lista(self):
        bot = ModalBot(favs=5, fav_links=favs_cheios(3))
        await adicionar_favorito(bot, nome="fav1", url=f"{URL_BASE}/novo", editando="fav1")
        assert list(bot.salvos_usuario[-1]["fav_links"]) == ["fav0", "fav1", "fav2"]

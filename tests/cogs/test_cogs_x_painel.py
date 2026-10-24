"""F3-5a — bugs de cogs × painel (KI-36 … KI-43): testes RED e guardas.

Cada classe cobre um item de ``docs/known-issues.md``. Os testes ``test_guarda_*`` passam hoje e continuam passando
depois da correção (protegem o comportamento que a correção não pode mudar); os demais são RED e falham pelo defeito
descrito no docstring da classe. Sem Discord real, sem rede, sem ``.env`` e sem ``setup()``: canais, mensagens e
interações são dublês (``tests/support/canal_de_pedidos.py``) e os valores falsos são montados em tempo de execução.
"""

import copy

import disnake
import pytest

import empiremuse.cogs.legacy_cmds as legacy_cmds
from empiremuse.utils.music import request_channel
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.music.interactions import FavMenuView, ViewMode
from tests.support.canal_de_pedidos import (
    FULL_TEXT,
    FakeBot,
    FakeDB,
    FakeGuild,
    FakeStage,
    FakeText,
    FakeVoice,
    Journal,
    perms,
)
from tests.support.modais import (
    trocar_process_idle_embed,
    SERVIDOR_ALVO,
    URL_BASE,
    ModalBot,
    ModalInteraction,
    adicionar_favorito,
    adicionar_integracao,
    arquivo_com,
    favs_cheios,
    gravados,
    importar,
    integracoes_cheias,
    modal_view,
    owner_com_contexto,
    url_de,
)
from tests.cogs.test_canal_de_pedidos_setup_reset import Scenario, configured, modal_answer

pytestmark = pytest.mark.regression


@pytest.fixture
def world(monkeypatch):
    return Scenario(monkeypatch)


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

    # ---- RED: a falha no Discord preserva a configuração

    def test_falha_ao_editar_a_mensagem_preserva_a_configuracao_no_banco(self, world):
        configured(world).fail_edit = RuntimeError("falha simulada")
        run_reset(world)
        assert (world.saved["channel"], world.saved["message_id"]) == ("22", "555"), (
            "KI-36: o Discord falhou, o canal continua de pé e o banco foi desconfigurado"
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
    def test_guarda_o_setup_grava_post_e_mensagem_e_nao_edita_o_forum(self, world, cenario):
        self.preparar(world, cenario)
        world.setup(target=world.forum)
        assert world.saved["channel"] is not None and world.saved["message_id"] is not None
        assert world.saved["channel"] == world.saved["message_id"], "no fórum o post e a mensagem têm o mesmo id"
        assert world.j.of("send_idle_embed"), "o embed ocioso continua sendo enviado ao post"
        assert world.j.of("channel.edit") == [], "o fórum em si nunca é editado"


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

    # ---- RED: view_channel é conferido uma vez só

    @pytest.mark.parametrize("existing_channel", [True, False])
    @pytest.mark.parametrize("kind", KINDS)
    def test_view_channel_e_conferido_uma_vez_so_em_canal_de_texto_voz_e_palco(self, kind, existing_channel):
        leituras = []
        espiao = SpyPermissions(perms(**FULL_TEXT).value, leituras)
        assert validar(kind, espiao, existing_channel=existing_channel)[:2] == ("ok", "")
        assert len(leituras) == 1, f"KI-38: view_channel conferido {len(leituras)}x: {leituras}"


# ============================================================================ KI-39 / KI-40 / KI-41 — modais de favoritos e integrações


@pytest.fixture(autouse=True)
def _sem_idle_embed(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    trocar_process_idle_embed(monkeypatch, nada)


class TestKI39ModalDeIntegracao:
    """O modal de adicionar integração compara com ``MAX_USER_FAVS`` em vez de ``MAX_USER_INTEGRATIONS``."""

    def integracao_salva(self, bot):
        return bool(bot.salvos_usuario) and "【DZ】: Ana" in bot.salvos_usuario[-1]["integration_links"]

    @pytest.mark.asyncio
    async def test_dono_do_bot_nao_e_limitado_pelo_maximo_de_integracoes(self):
        bot = ModalBot(favs=1, integracoes=1, dono=True, integration_links=integracoes_cheias(1))
        await adicionar_integracao(bot)
        assert self.integracao_salva(bot), "KI-39: o dono do bot é isento dos limites de cota"


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
    async def test_guarda_formato_antigo_de_texto_simples_continua_aceito(self):
        bot = ModalBot()
        antigo = {"【YT】: Canal": "https://www.youtube.com/@canal", "【SC】: Ana": "https://soundcloud.com/ana/sets"}
        await importar(bot, ViewMode.integrations_manager, antigo)
        salvo = bot.salvos_usuario[-1]["integration_links"]
        assert {nome: url_guardada(valor) for nome, valor in salvo.items()} == antigo

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
    async def test_item_fav_invalido_derruba_a_importacao_inteira(self):
        bot = ModalBot()
        conteudo = {"Bom": self.item(f"{URL_BASE}/bom"), "> fav: Ruim": self.item("isto-nao-e-url")}
        inter = await importar(bot, ViewMode.guild_fav_manager, conteudo)
        assert bot.salvos_servidor == [], "KI-41: nada do arquivo pode ser gravado se um item é inválido"
        assert "link inválido" in inter.texto


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
    async def test_item_mal_formado_com_nome_fav_tambem_e_recusado(self):
        bot = ModalBot()
        try:
            inter = await importar(bot, ViewMode.guild_fav_manager, {"> fav: Item": "https://exemplo.invalid/a"})
        except (KeyError, TypeError) as erro:
            pytest.fail(f"KI-47: {type(erro).__name__} escapou do importador: {erro}")
        assert bot.salvos_servidor == [] and inter.texto


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
    async def test_ki45_sem_prefixo_remove_o_prefixo_personalizado_sem_erro(self):
        """KI-45: ``setguildprefix <id>`` sem prefixo é o uso documentado para remover (``prefix=None``)."""
        cog, ctx, bot = owner_com_contexto()
        try:
            await legacy_cmds.Owner.setguildprefix.callback(cog, ctx, SERVIDOR_ALVO)
        except AttributeError as erro:
            pytest.fail(f"KI-45: {erro}")
        assert bot.gravados == [(SERVIDOR_ALVO, {"prefix": ""})]


# ============================================================================ reforço pós-mutação (sobreviventes)


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
    @pytest.mark.parametrize("avatar", [None, ""])
    async def test_avatar_ausente_ou_vazio_e_aceito(self, avatar):
        bot, _ = await self.importar_com_avatar(avatar)
        assert url_guardada(bot.salvos_usuario[-1]["integration_links"]["【YT】: Canal"]) == f"{URL_BASE}/c"


class TestImportadoresRecusamJsonQueNaoEObjetoOuEVazio:
    """Lista, texto, número, ``null`` e ``{}`` são recusados com mensagem, nos três modos, sem gravar nada."""

    MODOS = [ViewMode.fav_manager, ViewMode.guild_fav_manager, ViewMode.integrations_manager]
    CONTEUDOS = ["[]", '"texto"', "5", "null", "{}", '[{"url": "https://exemplo.invalid/a"}]']

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", list(MODOS)[:2])
    @pytest.mark.parametrize("conteudo", CONTEUDOS)
    async def test_recusa_com_mensagem_e_sem_gravar(self, modo, conteudo):
        bot = ModalBot()
        inter = await importar(bot, modo, conteudo, estrito=True)
        assert bot.salvos_usuario == [] and bot.salvos_servidor == []
        assert "objeto json" in inter.texto, f"o usuário precisa receber o motivo: {inter.texto!r}"


# ============================================================================ endurecimento dos importadores (KI-49 … KI-54)

MODOS_DE_IMPORTACAO = [
    pytest.param(ViewMode.fav_manager, id="favoritos"),
    pytest.param(ViewMode.guild_fav_manager, id="servidor"),
    pytest.param(ViewMode.integrations_manager, id="integracoes"),
]


class TestKI49UrlInteiraENormalizada:
    """Os importadores só olham o PREFIXO da URL (``URL_REG.match``) e gravam o texto inteiro, com o que vier depois."""

    SUJAS = {
        "quebra_de_linha_e_everyone": "https://a.com/x\n@everyone",
        "espaco_e_everyone": "https://a.com/x @everyone",
        "markdown_de_link": "https://a.com/x)[x](https://evil.invalid/p)",
    }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", list(MODOS_DE_IMPORTACAO)[:2])
    async def test_guarda_url_limpa_e_gravada_como_veio(self, modo):
        bot = ModalBot()
        await importar(bot, modo, arquivo_com(modo, "Musica", f"{URL_BASE}/faixa?x=1&y=2"))
        assert url_de(gravados(bot, modo)["Musica"]) == f"{URL_BASE}/faixa?x=1&y=2"


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


class TestKI53RefreshDepoisDaImportacao:
    """O refresh final chama ``view.build_embed()``, que a ``FavMenuView`` não tem (só ``build_txt``)."""

    ARQUIVOS = {
        ViewMode.fav_manager: {"Rock": f"{URL_BASE}/a"},
        ViewMode.guild_fav_manager: {"Rock": {"url": f"{URL_BASE}/a", "description": "ddd"}},
        ViewMode.integrations_manager: {"Canal": f"{URL_BASE}/a"},
    }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", list(MODOS_DE_IMPORTACAO)[:2])
    async def test_importacao_pelo_comando_com_prefixo_atualiza_a_mensagem_do_menu_sem_erro(self, modo):
        bot = ModalBot()
        view = modal_view(bot, modo, real=True, prefixo=True)
        try:
            await importar(bot, modo, self.ARQUIVOS[modo], view=view)
        except AttributeError as erro:
            pytest.fail(f"KI-53: o usuário veria um erro depois de importar com sucesso: {erro}")
        assert view.message.atualizacoes, "a mensagem do menu precisa ser atualizada depois de importar"


class TestKI54CotaNoModalDeFavorito:
    """No caminho de edição (``name == self.name``) com a entrada já removida em outra tela, a cota não era checada."""

    @pytest.mark.asyncio
    async def test_guarda_renomear_entrada_existente_com_a_cota_cheia_continua_permitido(self):
        bot = ModalBot(favs=2, fav_links=favs_cheios(2))
        await adicionar_favorito(bot, nome="renomeado", editando="fav0")
        salvo = bot.salvos_usuario[-1]["fav_links"]
        assert "renomeado" in salvo and "fav0" not in salvo and len(salvo) == 2


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


# ============================================================================ sobreviventes da mutação do endurecimento


class TestNomesRepetidosEConfiguracao:
    @pytest.mark.asyncio
    async def test_nome_de_favorito_tem_no_maximo_25_mesmo_com_configuracao_maior(self):
        bot = ModalBot(nome_max=40)
        inter = await importar(bot, ViewMode.fav_manager, {"n" * 26: f"{URL_BASE}/a"})
        assert gravados(bot, ViewMode.fav_manager) == {} and inter.texto

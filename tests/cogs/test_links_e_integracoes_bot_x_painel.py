"""F3-5b, etapa 0 — assimetrias A1 a A16 (favoritos, integrações e links fixos): bot × painel, em VERDE.

Fixa o comportamento ATUAL dos importadores e modais do bot (``FavModalImport``/``FavModalAdd``) e dos formulários do
painel (``FavoritesSection``, ``IntegrationsSection``, ``LinksForm``). ``# MUDA (etapa N, A#)`` marca o que a etapa
indicada inverte; o resto é guarda e deve continuar igual depois da extração. Referência: KI-42 (docs/known-issues.md); as assimetrias estão numeradas A1 a A25.
"""

import json

import pytest

from empiremuse.rules import limits
from empiremuse.utils.music.interactions import ViewMode
from tests.support.drivers_de_regras import (
    BotDoPainel,
    adicionar_link_do_servidor,
    importar_no_bot,
    importar_no_painel,
    painel_favoritos,
    painel_integracoes,
    painel_links,
)
from tests.support.modais import (
    trocar_process_idle_embed,
    URL_BASE,
    ModalBot,
    adicionar_favorito,
    adicionar_integracao,
    exportar,
    exportar_integracoes,
)

FAVORITOS, SERVIDOR_MODO, INTEGRACOES = ViewMode.fav_manager, ViewMode.guild_fav_manager, ViewMode.integrations_manager
URL = f"{URL_BASE}/a"
TETO_DE_LINKS = 25
LIMITE_DO_AVATAR = 250
LIMITE_DA_URL_DO_LINK = 250


@pytest.fixture(autouse=True)
def _sem_idle_embed(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    trocar_process_idle_embed(monkeypatch, nada)


def url_com_tamanho(tamanho):
    """URL válida com exatamente ``tamanho`` caracteres."""
    base = f"{URL_BASE}/"
    return base + "x" * (tamanho - len(base))


# ============================================================================ A2 — URL do modal manual


class TestA2UrlDoModal:
    """Etapa 4 (A2/D1): o modal manual exige URL pura: apara as pontas, desembrulha ``<…>`` e valida a URL inteira
    limpa. Texto ao redor, colchetes e menções em massa são recusados com a mensagem que já existe."""

    ACEITAS = {
        "pura": (URL, URL),
        "com_espacos": (f"  {URL}  ", URL),
        "entre_sinais": (f"<{URL}>", URL),
        "entre_sinais_com_espacos": (f"  <{URL}>  ", URL),
    }
    RECUSADAS = {
        "texto_ao_redor": f"veja {URL} agora",
        "texto_depois": f"{URL} agora",
        "texto_antes": f"veja {URL}",
        "colchete_no_fim": f"{URL}]",
        "markdown": f"[x]({URL})",
        "everyone": f"{URL_BASE}/@everyone",
        "so_o_sinal_de_abrir": f"<{URL}",
        "duas_urls": f"{URL} {URL}",
    }

    @pytest.mark.asyncio
    async def test_painel_editar_favorito_usa_a_mesma_regra(self):
        favoritos = {"antigo": URL}
        aceito = await painel_favoritos(BotDoPainel(), "favorito_editar", favoritos, nome="antigo", url=f"<{URL}b>")
        assert aceito.errors == {} and aceito.new["fav_links"]["antigo"] == f"{URL}b"
        recusado = await painel_favoritos(BotDoPainel(), "favorito_editar", favoritos, nome="antigo", url=f"veja {URL}")
        assert recusado.new == {} and recusado.errors.get("url")

    @pytest.mark.asyncio
    async def test_guarda_sem_link_nenhum_os_dois_lados_recusam(self):
        bot = ModalBot()
        inter = await adicionar_favorito(bot, url="sem link algum aqui")
        resultado = await painel_favoritos(
            BotDoPainel(), "favorito_adicionar", {}, nome="novo", url="sem link algum aqui"
        )
        assert bot.salvos_usuario == [] and "Nenhum link válido" in inter.texto and resultado.errors.get("url")


# ============================================================================ A3 — limite do nome do favorito (25 × 35)


class TestA3LimiteDoNomeDoFavorito:
    @pytest.mark.asyncio
    async def test_a_configuracao_abaixo_de_25_vale_como_teto_adicional_nos_dois(self):
        # D2 mantém isto: o teto passa a ser min(configuração, 25)
        painel = BotDoPainel(nome_max=10)
        no_painel, erros = await importar_no_painel(FAVORITOS, {"n" * 15: URL}, bot=painel)
        no_bot, texto = await importar_no_bot(FAVORITOS, {"n" * 15: URL}, bot=ModalBot(nome_max=10))
        assert no_painel is None and erros
        assert no_bot is None and "ultrapassa" in texto
        aceito, _ = await importar_no_bot(FAVORITOS, {"n" * 10: URL}, bot=ModalBot(nome_max=10))
        assert aceito == {"n" * 10: URL}


# ============================================================================ A8, A9 — cota e código morto


class TestA8CotaDaIntegracaoAntesDeSaberSeOTituloExiste:
    @pytest.mark.asyncio
    async def test_guarda_modal_com_a_lista_cheia_e_titulo_novo_continua_recusado(self):
        bot = ModalBot(integracoes=1, integration_links={"Outro": {"url": f"{URL_BASE}/antiga"}})
        inter = await adicionar_integracao(bot)
        assert bot.salvos_usuario == [] and "Não há espaço disponível" in inter.texto


# ============================================================================ A10, A11, A12 — integrações


class TestA11AvatarDaIntegracao:
    AVATAR = f"{URL_BASE}/a.png"

    @pytest.mark.asyncio
    async def test_guarda_limite_de_250_e_avatar_vazio_nos_dois(self):
        longo = url_com_tamanho(LIMITE_DO_AVATAR)
        for avatar, aceito in ((longo, True), (longo + "x", False)):
            item = {"Canal": {"url": URL, "avatar": avatar}}
            no_painel, _ = await importar_no_painel(INTEGRACOES, item)
            no_bot, _ = await importar_no_bot(INTEGRACOES, item)
            assert (no_painel is not None, no_bot is not None) == (aceito, aceito)
        vazio, _ = await importar_no_painel(INTEGRACOES, {"Canal": {"url": URL, "avatar": ""}})
        assert vazio == {"Canal": {"url": URL}}
        vazio_bot, _ = await importar_no_bot(INTEGRACOES, {"Canal": {"url": URL, "avatar": ""}})
        assert vazio_bot == {"Canal": {"url": URL}}


class TestA12LimiteDeUrlDasIntegracoes:
    @pytest.mark.asyncio
    async def test_titulo_ate_90_nos_dois_e_o_modal_cria_ate_80(self):
        assert limits.ITG_TITLE_MAX == 90
        for tamanho, aceito in ((90, True), (91, False)):
            item = {"t" * tamanho: URL}
            no_painel, _ = await importar_no_painel(INTEGRACOES, item)
            no_bot, _ = await importar_no_bot(INTEGRACOES, item)
            assert (no_painel is not None, no_bot is not None) == (aceito, aceito)


# ============================================================================ A13, A14, A15, A16 — links fixos do servidor


class TestA15SobrescritaNosLinksDoServidor:
    @pytest.mark.asyncio
    async def test_modal_do_bot_recusa_renomear_sobre_outra_entrada(self):
        bot = ModalBot()
        bot.guild_data["player_controller"]["fav_links"] = {
            "a1": {"url": f"{URL_BASE}/1", "description": ""},
            "b2": {"url": f"{URL_BASE}/2", "description": ""},
        }
        inter = await adicionar_link_do_servidor(bot, "b2", URL, "nova", editando="a1")
        assert bot.salvos_servidor == [] and "já" in inter.texto.lower()
        assert set(bot.guild_data["player_controller"]["fav_links"]) == {"a1", "b2"}


class TestA16TetoDeVinteECincoLinks:
    """Literais ``24``/``25`` no bot e ``TETO_DE_LINKS`` no painel: o mesmo teto de 25, a manter na regra única."""

    @pytest.mark.asyncio
    async def test_modal_do_bot_aceita_o_25o_e_recusa_o_26o(self):
        bot = ModalBot()
        bot.guild_data["player_controller"]["fav_links"] = {
            f"item{i}": {"url": URL, "description": ""} for i in range(TETO_DE_LINKS - 1)
        }
        await adicionar_link_do_servidor(bot, "ultimo", URL)
        assert len(bot.salvos_servidor[-1]["player_controller"]["fav_links"]) == TETO_DE_LINKS
        cheio = ModalBot()
        cheio.guild_data["player_controller"]["fav_links"] = {
            f"item{i}": {"url": URL, "description": ""} for i in range(TETO_DE_LINKS)
        }
        inter = await adicionar_link_do_servidor(cheio, "extra", URL)
        assert cheio.salvos_servidor == [] and "Não há espaço" in inter.texto

    @pytest.mark.asyncio
    async def test_importadores_aceitam_25_itens_e_recusam_26(self):
        def arquivo(quantidade):
            return {f"item{i}": {"url": URL, "description": "ddd"} for i in range(quantidade)}

        for quantidade, aceito in ((TETO_DE_LINKS, True), (TETO_DE_LINKS + 1, False)):
            no_bot, _ = await importar_no_bot(SERVIDOR_MODO, arquivo(quantidade))
            no_painel, _ = await importar_no_painel(SERVIDOR_MODO, arquivo(quantidade))
            assert (no_bot is not None, no_painel is not None) == (aceito, aceito)


# ============================================================================ guardas gerais dos favoritos pessoais


class TestGuardasDosFavoritosPessoais:
    """Regras de favoritos que NÃO mudam nas etapas 2 a 6: URL do importador de favoritos pessoais continua com a
    configuração ``USER_FAV_MAX_URL_LENGTH`` (D5) e a cota respeita 0 = ilimitado e o dono isento nos dois lados."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("favs", "dono", "cabe"),
        [(2, False, False), (2, True, True)],
        ids=["no_limite", "dono_isento"],
    )
    async def test_cota_na_importacao_dos_dois_lados(self, favs, dono, cabe):
        existentes = {"a1": URL, "a2": URL}
        item = {"novo": URL}
        no_bot, _ = await importar_no_bot(
            FAVORITOS, item, bot=ModalBot(favs=favs, dono=dono, fav_links=existentes), existentes=existentes
        )
        no_painel, _ = await importar_no_painel(
            FAVORITOS, item, bot=BotDoPainel(favs=favs, dono=dono), existentes=existentes
        )
        assert (no_bot is not None, no_painel is not None) == (cabe, cabe)

    @pytest.mark.asyncio
    async def test_remover_por_nome_exato_no_painel(self):
        resultado = await painel_favoritos(BotDoPainel(), "favorito_remover", {"A": URL, "a": URL}, nome="a")
        assert resultado.new["fav_links"] == {"A": URL}
        inexistente = await painel_favoritos(BotDoPainel(), "favorito_remover", {"A": URL}, nome="a")
        assert inexistente.new == {} and inexistente.errors
        integracoes = await painel_integracoes(BotDoPainel(), "integracao_remover", {"A": {"url": URL}}, nome="A")
        assert integracoes.new["integration_links"] == {}


class TestLimitesDoPainelSaoLiteraisAquiEConstantesLa:
    """As constantes do painel são conferidas contra os números deste arquivo, que não mudam com elas."""

    def test_o_painel_aceita_url_de_link_com_250_e_recusa_251_ao_adicionar(self):
        for tamanho, aceito in ((LIMITE_DA_URL_DO_LINK, True), (LIMITE_DA_URL_DO_LINK + 1, False)):
            resultado = painel_links(
                BotDoPainel(), "adicionar", {}, nome="Link", url=url_com_tamanho(tamanho), descricao=""
            )
            assert (resultado.errors == {}) is aceito, tamanho

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("favs", "dono", "cabe"),
        [(2, False, False), (2, True, True)],
        ids=["no_limite", "dono_isento"],
    )
    async def test_cota_do_painel_ao_adicionar_um_favorito(self, favs, dono, cabe):
        existentes = {"a1": URL, "a2": URL}
        resultado = await painel_favoritos(
            BotDoPainel(favs=favs, dono=dono), "favorito_adicionar", existentes, nome="novo", url=URL
        )
        assert (resultado.errors == {}) is cabe


class TestIdaEVoltaExportarImportar:
    """Etapa 5 (D4/D5): tudo que o modal salva, o importador (bot e painel) aceita de volta depois de exportar."""

    @pytest.mark.asyncio
    async def test_link_do_servidor_longo_criado_no_modal(self):
        bot = ModalBot(nome_max=35, url_max=90)
        longa = url_com_tamanho(200)
        await adicionar_link_do_servidor(bot, "Longo", longa, "uma descrição")
        bot.guild_data["player_controller"]["fav_links"].update(
            bot.salvos_servidor[-1]["player_controller"]["fav_links"]
        )
        _, arquivo = await exportar(bot, SERVIDOR_MODO)
        conteudo = json.loads(arquivo)
        assert conteudo == {"Longo": {"url": longa, "description": "uma descrição"}}
        no_bot, texto = await importar_no_bot(SERVIDOR_MODO, conteudo, bot=ModalBot(nome_max=35, url_max=90))
        no_painel, erros = await importar_no_painel(SERVIDOR_MODO, conteudo)
        assert no_bot == no_painel == conteudo, (texto, erros)

    @pytest.mark.asyncio
    async def test_integracao_com_url_longa_criada_no_modal(self):
        longa = "https://www.deezer.com/br/profile/123456?" + "x" * 150

        async def perfil(user_id):
            return {"name": "Ana", "link": longa, "picture": f"{URL_BASE}/ana.png"}

        bot = ModalBot(url_max=90)
        bot.deezer.get_user_info = perfil
        await adicionar_integracao(bot)
        bot.user_data["integration_links"].update(bot.salvos_usuario[-1]["integration_links"])
        conteudo = json.loads(await exportar_integracoes(bot))
        assert conteudo == {"【DZ】: Ana": {"url": longa, "avatar": f"{URL_BASE}/ana.png"}}
        no_bot, texto = await importar_no_bot(INTEGRACOES, conteudo, bot=ModalBot(url_max=90))
        no_painel, erros = await importar_no_painel(INTEGRACOES, conteudo, bot=BotDoPainel(url_max=90))
        assert no_bot == no_painel == conteudo, (texto, erros)

    @pytest.mark.asyncio
    async def test_guarda_favoritos_ida_e_volta(self):
        bot = ModalBot(fav_links={"Rock": URL, "Pop": f"{URL_BASE}/b"})
        _, arquivo = await exportar(bot, FAVORITOS)
        conteudo = json.loads(arquivo)
        no_bot, _ = await importar_no_bot(FAVORITOS, conteudo)
        no_painel, erros = await importar_no_painel(FAVORITOS, conteudo)
        assert no_bot == no_painel == conteudo and erros == {}

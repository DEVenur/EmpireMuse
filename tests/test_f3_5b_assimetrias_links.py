"""F3-5b, etapa 0 — assimetrias A1 a A16 (favoritos, integrações e links fixos): bot × painel, em VERDE.

Fixa o comportamento ATUAL dos importadores e modais do bot (``FavModalImport``/``FavModalAdd``) e dos formulários do
painel (``FavoritesSection``, ``IntegrationsSection``, ``LinksForm``). ``# MUDA (etapa N, A#)`` marca o que a etapa
indicada inverte; o resto é guarda e deve continuar igual depois da extração. Plano: ``.local/F3-5b-plano.md``.
"""

import pytest

from empiremuse.panel.services import account_links, links
from empiremuse.utils.music import interactions
from empiremuse.utils.music.interactions import ViewMode
from tests.helpers_f3_5b import (
    BotDoPainel,
    adicionar_link_do_servidor,
    campos_do_modal,
    importar_no_bot,
    importar_no_painel,
    painel_favoritos,
    painel_integracoes,
    painel_links,
)
from tests.helpers_modais import (
    URL_BASE,
    ModalBot,
    adicionar_favorito,
    adicionar_integracao,
    arquivo_com,
    exportar_integracoes,
    url_de,
)

FAVORITOS, SERVIDOR_MODO, INTEGRACOES = ViewMode.fav_manager, ViewMode.guild_fav_manager, ViewMode.integrations_manager
MODOS = [
    pytest.param(FAVORITOS, id="favoritos"),
    pytest.param(SERVIDOR_MODO, id="servidor"),
    pytest.param(INTEGRACOES, id="integracoes"),
]
URL = f"{URL_BASE}/a"
TETO_DE_LINKS = 25
LIMITE_DO_AVATAR = 250
LIMITE_DA_URL_DO_LINK = 250


@pytest.fixture(autouse=True)
def _sem_idle_embed(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    monkeypatch.setattr(interactions, "process_idle_embed", nada)


def url_com_tamanho(tamanho):
    """URL válida com exatamente ``tamanho`` caracteres."""
    base = f"{URL_BASE}/"
    return base + "x" * (tamanho - len(base))


def arquivo_do_modo(modo, nome, url, **extra):
    return arquivo_com(modo, nome, url, **extra)


# ============================================================================ A1 — URL do importador (painel × bot)


class TestA1UrlDoImportador:
    """O painel guarda só o PREFIXO que casa com ``URL_REG`` (corta o resto, aceita ``]`` e ``@everyone``); o bot exige
    a URL inteira limpa e recusa o arquivo."""

    SUJAS = {
        "texto_depois": (f"{URL} texto extra", URL),
        "colchete": (f"{URL}]b", f"{URL}]b"),
        "arroba_everyone": (f"{URL_BASE}/@everyone", f"{URL_BASE}/@everyone"),
    }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS)
    @pytest.mark.parametrize("caso", list(SUJAS))
    async def test_painel_grava_o_prefixo_sem_recusar(self, modo, caso):  # MUDA (etapa 4, A1): o painel recusa
        entrada, esperado = self.SUJAS[caso]
        guardado, erros = await importar_no_painel(modo, arquivo_do_modo(modo, "Musica", entrada))
        assert erros == {} and url_de(guardado["Musica"]) == esperado

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS)
    @pytest.mark.parametrize("caso", list(SUJAS))
    async def test_bot_recusa_o_arquivo_inteiro(self, modo, caso):
        entrada, _ = self.SUJAS[caso]
        guardado, texto = await importar_no_bot(modo, arquivo_do_modo(modo, "Musica", entrada))
        assert guardado is None and "link inválido" in texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS)
    async def test_guarda_url_limpa_e_aceita_pelos_dois(self, modo):
        no_painel, erros = await importar_no_painel(modo, arquivo_do_modo(modo, "Musica", URL))
        no_bot, _ = await importar_no_bot(modo, arquivo_do_modo(modo, "Musica", URL))
        assert erros == {} and url_de(no_painel["Musica"]) == url_de(no_bot["Musica"]) == URL


# ============================================================================ A2 — URL do modal manual


class TestA2UrlDoModal:
    """O modal manual usa ``URL_REG.findall(texto)[0]``: aceita texto ao redor e deixa o ``>`` de ``<url>`` colado."""

    # MUDA (etapa 4, A2/D1): URL pura (strip e desembrulho de <…>); texto ao redor passa a ser recusado
    CASOS = {
        "texto_ao_redor": (f"veja {URL} agora", URL),
        "entre_sinais": (f"<{URL}>", f"{URL}>"),
        "colchete_no_fim": (f"{URL}]", f"{URL}]"),
    }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caso", list(CASOS))
    async def test_modal_de_favorito(self, caso):
        entrada, esperado = self.CASOS[caso]
        bot = ModalBot()
        await adicionar_favorito(bot, url=entrada)
        assert bot.salvos_usuario[-1]["fav_links"]["novo"] == esperado

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caso", list(CASOS))
    async def test_modal_de_link_do_servidor(self, caso):
        entrada, esperado = self.CASOS[caso]
        bot = ModalBot()
        await adicionar_link_do_servidor(bot, "Link", entrada)
        assert bot.salvos_servidor[-1]["player_controller"]["fav_links"]["Link"]["url"] == esperado

    @pytest.mark.asyncio
    async def test_modal_de_integracao_aceita_texto_ao_redor_do_perfil(self):
        bot = ModalBot()
        await adicionar_integracao(bot, url="veja https://www.deezer.com/br/profile/123456 agora")
        assert bot.salvos_usuario[-1]["integration_links"]["【DZ】: Ana"]["url"].endswith("/profile/123456")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caso", list(CASOS))
    async def test_painel_adicionar_favorito(self, caso):
        entrada, esperado = self.CASOS[caso]
        resultado = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {}, nome="novo", url=entrada)
        assert resultado.errors == {} and resultado.new["fav_links"]["novo"] == esperado

    @pytest.mark.parametrize("caso", list(CASOS))
    def test_painel_adicionar_link_do_servidor(self, caso):
        entrada, esperado = self.CASOS[caso]
        resultado = painel_links(BotDoPainel(), "adicionar", {}, nome="Link", url=entrada, descricao="")
        assert resultado.errors == {} and resultado.new["fav_links"]["Link"]["url"] == esperado

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
    async def test_painel_importa_nomes_de_26_a_35_caracteres(self):  # MUDA (etapa 3, A3/D2): teto 25
        nome = "n" * 30
        guardado, erros = await importar_no_painel(FAVORITOS, {nome: URL})
        assert erros == {} and guardado == {nome: URL}

    @pytest.mark.asyncio
    async def test_painel_recusa_acima_do_teto_da_configuracao(self):
        guardado, erros = await importar_no_painel(FAVORITOS, {"n" * 36: URL})
        assert guardado is None and erros

    @pytest.mark.asyncio
    async def test_bot_importa_ate_25_e_recusa_26_mesmo_com_configuracao_35(self):
        guardado, _ = await importar_no_bot(FAVORITOS, {"n" * 25: URL})
        assert guardado == {"n" * 25: URL}
        recusado, texto = await importar_no_bot(FAVORITOS, {"n" * 26: URL})
        assert recusado is None and "inválido" in texto

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

    def test_o_modal_do_discord_limita_o_nome_em_25(self):
        campos = campos_do_modal(FAVORITOS)
        assert account_links.FAV_NAME_MAX == 25
        assert (campos["user_fav_name"].min_length, campos["user_fav_name"].max_length) == (2, 25)

    @pytest.mark.asyncio
    async def test_painel_recusa_26_ao_adicionar(self):
        resultado = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {}, nome="n" * 26, url=URL)
        assert resultado.errors.get("nome")
        aceito = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {}, nome="n" * 25, url=URL)
        assert aceito.errors == {}


# ============================================================================ A5 — nomes que só diferem na caixa


class TestA5NomesQueSoDiferemNaCaixa:
    """Importador do bot: ``casefold`` (o novo substitui o antigo; repetido dentro do arquivo é recusado). Painel e
    modal manual: comparação EXATA, então ``Rock`` e ``rock`` coexistem."""

    ANTIGO = "Rock"
    NOVO = "rock"

    @staticmethod
    def existentes(modo, url):
        if modo == SERVIDOR_MODO:
            return {"Rock": {"url": url, "description": "antiga"}}
        if modo == INTEGRACOES:
            return {"Rock": {"url": url}}
        return {"Rock": url}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", [FAVORITOS, INTEGRACOES], ids=["favoritos", "integracoes"])
    async def test_importador_do_bot_substitui_o_nome_que_so_difere_na_caixa(self, modo):
        antigas = self.existentes(modo, f"{URL_BASE}/antiga")
        guardado, _ = await importar_no_bot(modo, arquivo_do_modo(modo, "rock", URL), existentes=antigas)
        assert list(guardado) == ["rock"]

    @pytest.mark.asyncio
    async def test_importador_de_links_do_servidor_so_substitui_o_nome_exato(self):  # MUDA (etapa 5, A5/A15)
        antigas = self.existentes(SERVIDOR_MODO, f"{URL_BASE}/antiga")
        guardado, _ = await importar_no_bot(
            SERVIDOR_MODO, arquivo_do_modo(SERVIDOR_MODO, "rock", URL), existentes=antigas
        )
        assert sorted(guardado) == ["Rock", "rock"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS)
    async def test_painel_mantem_os_dois_nomes(self, modo):  # MUDA (etapa 3, A5): casefold também no painel
        antigas = self.existentes(modo, f"{URL_BASE}/antiga")
        guardado, erros = await importar_no_painel(modo, arquivo_do_modo(modo, "rock", URL), existentes=antigas)
        assert erros == {} and sorted(guardado) == ["Rock", "rock"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS)
    async def test_arquivo_com_o_mesmo_nome_em_caixas_diferentes(self, modo):
        um = arquivo_do_modo(modo, "Rock", URL)
        outro = arquivo_do_modo(modo, "rock", URL)
        arquivo = {**um, **outro}
        no_bot, texto = await importar_no_bot(modo, arquivo)
        assert no_bot is None and "repetir nomes" in texto
        no_painel, erros = await importar_no_painel(modo, arquivo)  # MUDA (etapa 3, A5): o painel também recusa
        assert erros == {} and sorted(no_painel) == ["Rock", "rock"]

    @pytest.mark.asyncio
    async def test_modal_do_bot_e_painel_deixam_rock_e_rock_coexistirem(self):  # MUDA (etapa 3, A5)
        bot = ModalBot(fav_links={"Rock": URL})
        await adicionar_favorito(bot, nome="rock")
        assert sorted(bot.salvos_usuario[-1]["fav_links"]) == ["Rock", "rock"]
        resultado = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {"Rock": URL}, nome="rock", url=URL)
        assert resultado.errors == {} and sorted(resultado.new["fav_links"]) == ["Rock", "rock"]


# ============================================================================ A6, A7 — renomear e sanitizar no modal


class TestA6RenomearSobrescreveEmSilencio:
    @pytest.mark.asyncio
    async def test_modal_do_bot_renomeando_sobre_outra_entrada_apaga_a_outra(self):  # MUDA (etapa 3, A6): recusa
        bot = ModalBot(fav_links={"antigo": f"{URL_BASE}/1", "outro": f"{URL_BASE}/2"})
        await adicionar_favorito(bot, nome="outro", url=f"{URL_BASE}/novo", editando="antigo")
        assert bot.salvos_usuario[-1]["fav_links"] == {"outro": f"{URL_BASE}/novo"}

    @pytest.mark.asyncio
    async def test_painel_recusa_adicionar_nome_existente(self):
        resultado = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {"outro": URL}, nome="outro", url=URL)
        assert resultado.new == {} and resultado.errors.get("nome")

    @pytest.mark.asyncio
    async def test_painel_editar_nunca_renomeia(self):
        favoritos = {"antigo": f"{URL_BASE}/1", "outro": f"{URL_BASE}/2"}
        resultado = await painel_favoritos(BotDoPainel(), "favorito_editar", favoritos, nome="antigo", url=URL)
        assert list(resultado.new["fav_links"]) == ["antigo", "outro"] and resultado.new["fav_links"]["antigo"] == URL

    @pytest.mark.asyncio
    async def test_guarda_modal_do_bot_editar_sem_renomear_troca_so_a_url(self):
        bot = ModalBot(fav_links={"antigo": f"{URL_BASE}/1"})
        await adicionar_favorito(bot, nome="antigo", url=f"{URL_BASE}/novo", editando="antigo")
        assert bot.salvos_usuario[-1]["fav_links"] == {"antigo": f"{URL_BASE}/novo"}


class TestA7NomeSemSanitizacaoNoModal:
    """O modal do bot só aplica ``strip``; o painel revalida depois (2 a 25 caracteres, sem ``Cc``/``Cf``)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome", [" a", "ab​", "a\x07b"])  # MUDA (etapa 3, A7): o modal recusa como o painel
    async def test_modal_do_bot_grava_o_nome_apos_o_strip(self, nome):
        bot = ModalBot()
        await adicionar_favorito(bot, nome=nome)
        assert list(bot.salvos_usuario[-1]["fav_links"]) == [nome.strip()]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome", [" a", "ab​", "a\x07b", "a"])
    async def test_painel_recusa(self, nome):
        resultado = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {}, nome=nome, url=URL)
        assert resultado.new == {} and resultado.errors.get("nome")


# ============================================================================ A8, A9 — cota e código morto


class TestA8CotaDaIntegracaoAntesDeSaberSeOTituloExiste:
    @pytest.mark.asyncio
    async def test_modal_recusa_reeditar_integracao_existente_com_a_lista_cheia(self):  # MUDA (etapa 2, A8)
        bot = ModalBot(integracoes=1, integration_links={"【DZ】: Ana": {"url": f"{URL_BASE}/antiga"}})
        inter = await adicionar_integracao(bot)
        assert bot.salvos_usuario == [] and "Não há espaço disponível" in inter.texto

    @pytest.mark.asyncio
    async def test_importador_do_bot_sobrescreve_com_a_lista_cheia(self):
        bot = ModalBot(integracoes=1, integration_links={"Canal": {"url": f"{URL_BASE}/antiga"}})
        guardado, _ = await importar_no_bot(INTEGRACOES, {"Canal": URL}, bot=bot)
        assert guardado == {"Canal": URL}

    @pytest.mark.asyncio
    async def test_importador_do_painel_sobrescreve_com_a_lista_cheia(self):
        guardado, erros = await importar_no_painel(
            INTEGRACOES, {"Canal": URL}, bot=BotDoPainel(integracoes=1), existentes={"Canal": {"url": "x"}}
        )
        assert erros == {} and guardado == {"Canal": {"url": URL}}

    @pytest.mark.asyncio
    async def test_guarda_favorito_existente_com_a_lista_cheia_continua_editavel_no_modal(self):
        bot = ModalBot(favs=1, fav_links={"a1": f"{URL_BASE}/1"})
        await adicionar_favorito(bot, nome="a1", url=f"{URL_BASE}/2", editando="a1")
        assert bot.salvos_usuario[-1]["fav_links"] == {"a1": f"{URL_BASE}/2"}


class TestA9CodigoMortoDoImportador:
    """O laço ``len(nome) > USER_FAV_MAX_NAME_LENGTH`` só age com a configuração abaixo de 25, e a remoção da chave
    antiga ``nome.lower()[:90]`` já é feita pelo ``casefold``: as duas linhas podem sair sem mudar nada."""

    @pytest.mark.asyncio
    async def test_com_a_configuracao_padrao_o_laco_de_nome_nao_recusa_nada(self):
        guardado, _ = await importar_no_bot(FAVORITOS, {"n" * 25: URL}, bot=ModalBot(nome_max=35))
        assert guardado == {"n" * 25: URL}

    @pytest.mark.asyncio
    async def test_a_chave_antiga_minuscula_e_truncada_e_substituida(self):
        antiga = {("canal " + "x" * 120).lower()[:90]: {"url": f"{URL_BASE}/antiga"}}
        titulo = ("Canal " + "x" * 120)[:90]
        guardado, _ = await importar_no_bot(INTEGRACOES, {titulo: URL}, existentes=antiga)
        assert list(guardado) == [titulo]


# ============================================================================ A10, A11, A12 — integrações


class TestA10FormaGravadaDasIntegracoes:
    @pytest.mark.asyncio
    async def test_importador_do_bot_guarda_texto_se_o_item_veio_em_texto(self):  # MUDA (etapa 5, A10): sempre objeto
        guardado, _ = await importar_no_bot(INTEGRACOES, {"Canal": URL})
        assert guardado == {"Canal": URL}

    @pytest.mark.asyncio
    async def test_importador_do_bot_guarda_objeto_se_o_item_veio_em_objeto(self):
        guardado, _ = await importar_no_bot(INTEGRACOES, {"Canal": {"url": URL, "avatar": f"{URL_BASE}/a.png"}})
        assert guardado == {"Canal": {"url": URL, "avatar": f"{URL_BASE}/a.png"}}
        sem_avatar, _ = await importar_no_bot(INTEGRACOES, {"Canal": {"url": URL}})
        assert sem_avatar == {"Canal": {"url": URL}}

    @pytest.mark.asyncio
    async def test_painel_guarda_sempre_objeto(self):
        do_texto, _ = await importar_no_painel(INTEGRACOES, {"Canal": URL})
        do_objeto, _ = await importar_no_painel(INTEGRACOES, {"Canal": {"url": URL, "avatar": f"{URL_BASE}/a.png"}})
        assert do_texto == {"Canal": {"url": URL}}
        assert do_objeto == {"Canal": {"url": URL, "avatar": f"{URL_BASE}/a.png"}}

    @pytest.mark.asyncio
    async def test_guarda_modal_guarda_objeto_e_o_exportador_devolve_o_que_esta_gravado(self):
        bot = ModalBot()
        await adicionar_integracao(bot)
        bot.user_data["integration_links"].update(bot.salvos_usuario[-1]["integration_links"])
        exportado = await exportar_integracoes(bot)
        assert '"avatar"' in exportado and '"url"' in exportado


class TestA11AvatarDaIntegracao:
    AVATAR = f"{URL_BASE}/a.png"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("avatar", "esperado"),
        [(f"{AVATAR} lixo", AVATAR), (f"{AVATAR}]x", f"{AVATAR}]x")],
    )
    async def test_painel_grava_o_prefixo_do_avatar(self, avatar, esperado):  # MUDA (etapa 4, A11): recusa
        guardado, erros = await importar_no_painel(INTEGRACOES, {"Canal": {"url": URL, "avatar": avatar}})
        assert erros == {} and guardado["Canal"]["avatar"] == esperado

    @pytest.mark.asyncio
    @pytest.mark.parametrize("avatar", [f"{AVATAR} lixo", f"{AVATAR}]x"])
    async def test_bot_recusa_o_avatar_sujo(self, avatar):
        guardado, texto = await importar_no_bot(INTEGRACOES, {"Canal": {"url": URL, "avatar": avatar}})
        assert guardado is None and "link inválido" in texto

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
    async def test_150_aceita_e_151_recusa_nos_dois_sem_depender_da_configuracao(self):  # MUDA (etapa 5, D4): 200
        assert account_links.ITG_URL_MAX == 150
        for tamanho, aceito in ((150, True), (151, False)):
            item = {"Canal": url_com_tamanho(tamanho)}
            no_painel, _ = await importar_no_painel(INTEGRACOES, item, bot=BotDoPainel(url_max=90))
            no_bot, _ = await importar_no_bot(INTEGRACOES, item, bot=ModalBot(url_max=90))
            assert (no_painel is not None, no_bot is not None) == (aceito, aceito)

    def test_o_modal_manual_aceita_ate_200(self):
        assert campos_do_modal(INTEGRACOES)["user_integration_url"].max_length == 200

    @pytest.mark.asyncio
    async def test_titulo_ate_90_nos_dois_e_o_modal_cria_ate_80(self):
        assert account_links.ITG_TITLE_MAX == 90
        for tamanho, aceito in ((90, True), (91, False)):
            item = {"t" * tamanho: URL}
            no_painel, _ = await importar_no_painel(INTEGRACOES, item)
            no_bot, _ = await importar_no_bot(INTEGRACOES, item)
            assert (no_painel is not None, no_bot is not None) == (aceito, aceito)


class TestA12TituloCriadoPeloModal:
    @pytest.mark.asyncio
    async def test_o_modal_corta_o_titulo_em_80_e_o_importador_aceita_ate_90(self):
        async def perfil_longo(user_id):
            return {
                "name": "n" * 100,
                "link": f"https://www.deezer.com/br/profile/{user_id}",
                "picture": f"{URL_BASE}/a.png",
            }

        bot = ModalBot()
        bot.deezer.get_user_info = perfil_longo
        await adicionar_integracao(bot)
        titulo = next(iter(bot.salvos_usuario[-1]["integration_links"]))
        assert len(titulo) == 83 and titulo.endswith("..."), "80 caracteres e reticências"
        assert account_links.ITG_TITLE_MAX == 90


# ============================================================================ A13, A14, A15, A16 — links fixos do servidor


class TestA13LimiteDeUrlDosLinksDoServidor:
    """O importador (bot e painel) usa ``USER_FAV_MAX_URL_LENGTH`` (config dos favoritos pessoais, 90 por padrão),
    mas o modal aceita até 250: um link de 120 caracteres criado no modal não reimporta."""

    @pytest.mark.asyncio
    async def test_importador_usa_a_configuracao_dos_favoritos_pessoais(self):  # MUDA (etapa 5, A13/D5): 250 próprio
        for tamanho, aceito in ((90, True), (91, False)):
            item = arquivo_do_modo(SERVIDOR_MODO, "Link", url_com_tamanho(tamanho))
            no_painel, _ = await importar_no_painel(SERVIDOR_MODO, item, bot=BotDoPainel(url_max=90))
            no_bot, _ = await importar_no_bot(SERVIDOR_MODO, item, bot=ModalBot(url_max=90))
            assert (no_painel is not None, no_bot is not None) == (aceito, aceito)

    @pytest.mark.asyncio
    async def test_mudar_a_configuracao_muda_o_limite_dos_links_do_servidor(self):  # MUDA (etapa 5, A13/D5)
        item = arquivo_do_modo(SERVIDOR_MODO, "Link", url_com_tamanho(120))
        no_painel, _ = await importar_no_painel(SERVIDOR_MODO, item, bot=BotDoPainel(url_max=200))
        no_bot, _ = await importar_no_bot(SERVIDOR_MODO, item, bot=ModalBot(url_max=200))
        assert no_painel is not None and no_bot is not None

    def test_o_modal_do_bot_aceita_ate_250(self):
        assert campos_do_modal(SERVIDOR_MODO)["guild_fav_url"].max_length == 250

    @pytest.mark.asyncio
    async def test_link_de_120_criado_no_modal_e_no_painel_nao_reimporta_com_a_configuracao_padrao(self):
        # MUDA (etapa 5, A13/D5)
        longa = url_com_tamanho(120)
        bot = ModalBot(nome_max=35, url_max=90)
        await adicionar_link_do_servidor(bot, "Longo", longa)
        guardado = bot.salvos_servidor[-1]["player_controller"]["fav_links"]
        assert guardado["Longo"]["url"] == longa
        de_volta, texto = await importar_no_bot(SERVIDOR_MODO, guardado, bot=ModalBot(nome_max=35, url_max=90))
        assert de_volta is None and "ultrapassa" in texto
        criado = painel_links(BotDoPainel(), "adicionar", {}, nome="Longo", url=longa, descricao="")
        assert criado.errors == {}
        no_painel, erros = await importar_no_painel(SERVIDOR_MODO, criado.new["fav_links"])
        assert no_painel is None and erros


class TestA14DescricaoDoLinkDoServidor:
    """O importador (bot e painel) só confere ``<= 50``; o modal e a adição do painel exigem vazia ou 3–50."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("descricao", ["a", "ab"])
    async def test_importadores_aceitam_descricao_de_1_ou_2_caracteres(self, descricao):  # MUDA (etapa 5, A14)
        item = {"Link": {"url": URL, "description": descricao}}
        no_painel, erros = await importar_no_painel(SERVIDOR_MODO, item)
        no_bot, _ = await importar_no_bot(SERVIDOR_MODO, item)
        assert erros == {} and no_painel["Link"]["description"] == no_bot["Link"]["description"] == descricao

    @pytest.mark.asyncio
    async def test_guarda_importadores_recusam_mais_de_50(self):
        item = {"Link": {"url": URL, "description": "d" * 51}}
        no_painel, erros = await importar_no_painel(SERVIDOR_MODO, item)
        no_bot, texto = await importar_no_bot(SERVIDOR_MODO, item)
        assert no_painel is None and erros and no_bot is None and "ultrapassa" in texto

    def test_o_modal_do_bot_pede_de_3_a_50_e_a_descricao_e_opcional(self):
        campo = campos_do_modal(SERVIDOR_MODO)["guild_fav_description"]
        assert (campo.min_length, campo.max_length, campo.required) == (3, 50, False)

    def test_o_painel_recusa_descricao_de_2_caracteres_ao_adicionar(self):
        recusado = painel_links(BotDoPainel(), "adicionar", {}, nome="Link", url=URL, descricao="ab")
        aceito = painel_links(BotDoPainel(), "adicionar", {}, nome="Link", url=URL, descricao="abc")
        assert recusado.errors.get("descricao") and aceito.errors == {}


class TestA15SobrescritaNosLinksDoServidor:
    @pytest.mark.asyncio
    async def test_modal_do_bot_sobrescreve_nome_existente_sem_avisar(self):  # MUDA (etapa 5, A15): recusa
        bot = ModalBot()
        bot.guild_data["player_controller"]["fav_links"] = {"Link": {"url": f"{URL_BASE}/1", "description": "antiga"}}
        await adicionar_link_do_servidor(bot, "Link", URL, "nova")
        assert bot.salvos_servidor[-1]["player_controller"]["fav_links"]["Link"] == {"url": URL, "description": "nova"}

    def test_painel_recusa_nome_existente(self):
        existentes = {"Link": {"url": URL, "description": ""}}
        resultado = painel_links(BotDoPainel(), "adicionar", existentes, nome="Link", url=URL, descricao="")
        assert resultado.new == {} and resultado.errors.get("nome")

    @pytest.mark.asyncio
    async def test_modal_do_bot_com_25_itens_recusa_ate_a_sobrescrita(self):  # MUDA (etapa 5, A15)
        bot = ModalBot()
        bot.guild_data["player_controller"]["fav_links"] = {
            f"item{i}": {"url": URL, "description": ""} for i in range(TETO_DE_LINKS)
        }
        inter = await adicionar_link_do_servidor(bot, "item3", URL, "nova")
        assert bot.salvos_servidor == [] and "Não há espaço disponível" in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_importadores_sobrescrever_nao_ocupa_vaga_com_25_itens(self):
        existentes = {f"item{i}": {"url": URL, "description": "d"} for i in range(TETO_DE_LINKS)}
        item = {"item3": {"url": f"{URL_BASE}/nova", "description": "nova"}}
        no_bot, _ = await importar_no_bot(SERVIDOR_MODO, item, existentes=existentes)
        no_painel, erros = await importar_no_painel(SERVIDOR_MODO, item, existentes=existentes)
        assert erros == {} and len(no_bot) == len(no_painel) == TETO_DE_LINKS
        assert no_bot["item3"]["description"] == no_painel["item3"]["description"] == "nova"


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

    def test_painel_aceita_o_25o_e_recusa_o_26o(self):
        quase = {f"item{i}": {"url": URL, "description": ""} for i in range(TETO_DE_LINKS - 1)}
        aceito = painel_links(BotDoPainel(), "adicionar", quase, nome="ultimo", url=URL, descricao="")
        assert aceito.errors == {}
        cheio = {**quase, "ultimo": {"url": URL, "description": ""}}
        recusado = painel_links(BotDoPainel(), "adicionar", cheio, nome="extra", url=URL, descricao="")
        assert recusado.new == {} and recusado.errors.get("nome")

    @pytest.mark.asyncio
    async def test_importadores_aceitam_25_itens_e_recusam_26(self):
        def arquivo(quantidade):
            return {f"item{i}": {"url": URL, "description": "d"} for i in range(quantidade)}

        for quantidade, aceito in ((TETO_DE_LINKS, True), (TETO_DE_LINKS + 1, False)):
            no_bot, _ = await importar_no_bot(SERVIDOR_MODO, arquivo(quantidade))
            no_painel, _ = await importar_no_painel(SERVIDOR_MODO, arquivo(quantidade))
            assert (no_bot is not None, no_painel is not None) == (aceito, aceito)


# ============================================================================ guardas gerais dos favoritos pessoais


class TestGuardasDosFavoritosPessoais:
    """Regras de favoritos que NÃO mudam nas etapas 2 a 6: URL do importador de favoritos pessoais continua com a
    configuração ``USER_FAV_MAX_URL_LENGTH`` (D5) e a cota respeita 0 = ilimitado e o dono isento nos dois lados."""

    @pytest.mark.asyncio
    async def test_url_dos_favoritos_pessoais_segue_a_configuracao(self):
        for tamanho, aceito in ((90, True), (91, False)):
            item = {"Musica": url_com_tamanho(tamanho)}
            no_painel, _ = await importar_no_painel(FAVORITOS, item, bot=BotDoPainel(url_max=90))
            no_bot, _ = await importar_no_bot(FAVORITOS, item, bot=ModalBot(url_max=90))
            assert (no_painel is not None, no_bot is not None) == (aceito, aceito)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("favs", "dono", "cabe"),
        [(2, False, False), (0, False, True), (2, True, True)],
        ids=["no_limite", "sem_limite", "dono_isento"],
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


class TestA16MensagensDoTetoNoImportadorDoBot:
    """O bot tem duas checagens do teto (arquivo grande demais; arquivo + o que já existe): cada uma com sua mensagem."""

    @pytest.mark.asyncio
    async def test_arquivo_com_26_itens_diz_que_excede_o_maximo(self):
        arquivo = {f"item{i}": {"url": URL, "description": "d"} for i in range(TETO_DE_LINKS + 1)}
        guardado, texto = await importar_no_bot(SERVIDOR_MODO, arquivo)
        assert guardado is None and "excede a quantidade máxima permitida (25)" in texto

    @pytest.mark.asyncio
    async def test_arquivo_pequeno_mais_o_que_ja_existe_diz_que_nao_ha_espaco(self):
        existentes = {f"item{i}": {"url": URL, "description": "d"} for i in range(TETO_DE_LINKS)}
        guardado, texto = await importar_no_bot(
            SERVIDOR_MODO, {"novo": {"url": URL, "description": "d"}}, existentes=existentes
        )
        assert guardado is None and "não possui espaço suficiente" in texto and "Limite atual: 25" in texto


class TestLimitesDoPainelSaoLiteraisAquiEConstantesLa:
    """As constantes do painel são conferidas contra os números deste arquivo, que não mudam com elas."""

    def test_constantes(self):
        assert (account_links.FAV_NAME_MIN, account_links.FAV_NAME_MAX) == (2, 25)
        assert (account_links.ITG_TITLE_MAX, account_links.ITG_URL_MAX, account_links.ITG_AVATAR_MAX) == (90, 150, 250)
        assert links.MAX_LINKS == TETO_DE_LINKS and (links.URL_MIN, links.URL_MAX) == (10, LIMITE_DA_URL_DO_LINK)
        assert (links.NAME_MIN, links.NAME_MAX, links.DESCRIPTION_MIN, links.DESCRIPTION_MAX) == (2, 25, 3, 50)

    def test_o_painel_aceita_url_de_link_com_250_e_recusa_251_ao_adicionar(self):
        for tamanho, aceito in ((LIMITE_DA_URL_DO_LINK, True), (LIMITE_DA_URL_DO_LINK + 1, False)):
            resultado = painel_links(
                BotDoPainel(), "adicionar", {}, nome="Link", url=url_com_tamanho(tamanho), descricao=""
            )
            assert (resultado.errors == {}) is aceito, tamanho

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("favs", "dono", "cabe"),
        [(2, False, False), (3, False, True), (0, False, True), (2, True, True)],
        ids=["no_limite", "abaixo", "sem_limite", "dono_isento"],
    )
    async def test_cota_do_painel_ao_adicionar_um_favorito(self, favs, dono, cabe):
        existentes = {"a1": URL, "a2": URL}
        resultado = await painel_favoritos(
            BotDoPainel(favs=favs, dono=dono), "favorito_adicionar", existentes, nome="novo", url=URL
        )
        assert (resultado.errors == {}) is cabe

    @pytest.mark.asyncio
    async def test_nome_com_espacos_nas_pontas_no_arquivo_e_aparado_nos_dois_importadores(self):
        no_painel, _ = await importar_no_painel(FAVORITOS, {"  Rock  ": URL})
        no_bot, _ = await importar_no_bot(FAVORITOS, {"  Rock  ": URL})
        assert list(no_painel) == list(no_bot) == ["Rock"]
        itg_painel, _ = await importar_no_painel(INTEGRACOES, {" Canal ": URL})
        itg_bot, _ = await importar_no_bot(INTEGRACOES, {" Canal ": URL})
        assert list(itg_painel) == list(itg_bot) == ["Canal"]

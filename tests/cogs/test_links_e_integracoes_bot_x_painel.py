"""F3-5b, etapa 0 — assimetrias A1 a A16 (favoritos, integrações e links fixos): bot × painel, em VERDE.

Fixa o comportamento ATUAL dos importadores e modais do bot (``FavModalImport``/``FavModalAdd``) e dos formulários do
painel (``FavoritesSection``, ``IntegrationsSection``, ``LinksForm``). ``# MUDA (etapa N, A#)`` marca o que a etapa
indicada inverte; o resto é guarda e deve continuar igual depois da extração. Referência: KI-42 (docs/known-issues.md); as assimetrias estão numeradas A1 a A25.
"""

import json

import pytest

from empiremuse.rules import limits
from empiremuse.utils.music import interactions
from empiremuse.utils.music.interactions import ViewMode
from tests.support.drivers_de_regras import (
    BotDoPainel,
    adicionar_link_do_servidor,
    campos_do_modal,
    importar_no_bot,
    importar_no_painel,
    painel_favoritos,
    painel_integracoes,
    painel_links,
)
from tests.support.modais import (
    URL_BASE,
    ModalBot,
    adicionar_favorito,
    adicionar_integracao,
    arquivo_com,
    exportar,
    exportar_integracoes,
    importar,
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
    """Etapa 4 (A1): o painel exige a URL INTEIRA limpa, como o bot, e recusa o arquivo em vez de guardar só o
    prefixo (antes cortava ``texto extra`` e aceitava ``]`` e ``@everyone``)."""

    SUJAS = {
        "texto_depois": f"{URL} texto extra",
        "http_com_lixo": "http://a.com lixo",
        "colchete": f"{URL}]b",
        "arroba_everyone": f"{URL_BASE}/@everyone",
        "arroba_here": f"{URL_BASE}/@here",
        "quebra_de_linha": f"{URL}\ntexto",
        "markdown": f"{URL})[x](https://evil.invalid/p)",
    }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS)
    @pytest.mark.parametrize("caso", list(SUJAS))
    async def test_painel_recusa_o_arquivo_inteiro(self, modo, caso):
        guardado, erros = await importar_no_painel(modo, arquivo_do_modo(modo, "Musica", self.SUJAS[caso]))
        assert guardado is None and erros, f"{self.SUJAS[caso]!r} deveria ser recusada"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS)
    @pytest.mark.parametrize("caso", list(SUJAS))
    async def test_bot_recusa_o_arquivo_inteiro(self, modo, caso):
        guardado, texto = await importar_no_bot(modo, arquivo_do_modo(modo, "Musica", self.SUJAS[caso]))
        assert guardado is None and "link inválido" in texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS)
    async def test_painel_apara_as_pontas_da_url_como_o_bot(self, modo):
        no_painel, erros = await importar_no_painel(modo, arquivo_do_modo(modo, "Musica", f"  {URL}  "))
        no_bot, _ = await importar_no_bot(modo, arquivo_do_modo(modo, "Musica", f"  {URL}  "))
        assert erros == {} and url_de(no_painel["Musica"]) == url_de(no_bot["Musica"]) == URL

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS)
    async def test_guarda_url_limpa_e_aceita_pelos_dois(self, modo):
        no_painel, erros = await importar_no_painel(modo, arquivo_do_modo(modo, "Musica", URL))
        no_bot, _ = await importar_no_bot(modo, arquivo_do_modo(modo, "Musica", URL))
        assert erros == {} and url_de(no_painel["Musica"]) == url_de(no_bot["Musica"]) == URL

    @pytest.mark.asyncio
    async def test_recusa_de_um_item_no_painel_nao_grava_os_outros(self):
        guardado, erros = await importar_no_painel(FAVORITOS, {"Boa": URL, "Ruim": f"{URL} lixo"})
        assert guardado is None and erros


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
    @pytest.mark.parametrize("caso", list(ACEITAS))
    async def test_modal_de_favorito_aceita(self, caso):
        entrada, esperado = self.ACEITAS[caso]
        bot = ModalBot()
        await adicionar_favorito(bot, url=entrada)
        assert bot.salvos_usuario[-1]["fav_links"]["novo"] == esperado

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caso", list(RECUSADAS))
    async def test_modal_de_favorito_recusa(self, caso):
        bot = ModalBot()
        inter = await adicionar_favorito(bot, url=self.RECUSADAS[caso])
        assert bot.salvos_usuario == [] and "Nenhum link válido" in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caso", list(ACEITAS))
    async def test_modal_de_link_do_servidor_aceita(self, caso):
        entrada, esperado = self.ACEITAS[caso]
        bot = ModalBot()
        await adicionar_link_do_servidor(bot, "Link", entrada)
        assert bot.salvos_servidor[-1]["player_controller"]["fav_links"]["Link"]["url"] == esperado

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caso", list(RECUSADAS))
    async def test_modal_de_link_do_servidor_recusa(self, caso):
        bot = ModalBot()
        inter = await adicionar_link_do_servidor(bot, "Link", self.RECUSADAS[caso])
        assert bot.salvos_servidor == [] and "Nenhum link válido" in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "entrada", ["https://www.deezer.com/br/profile/123456", " <https://www.deezer.com/br/profile/123456> "]
    )
    async def test_modal_de_integracao_aceita_a_url_pura_e_desembrulha(self, entrada):
        bot = ModalBot()
        await adicionar_integracao(bot, url=entrada)
        assert bot.salvos_usuario[-1]["integration_links"]["【DZ】: Ana"]["url"].endswith("/profile/123456")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "entrada",
        ["veja https://www.deezer.com/br/profile/123456 agora", "https://www.deezer.com/br/profile/123456]"],
        ids=["texto_ao_redor", "colchete"],
    )
    async def test_modal_de_integracao_recusa_texto_ao_redor(self, entrada):
        bot = ModalBot()
        inter = await adicionar_integracao(bot, url=entrada)
        assert bot.salvos_usuario == [] and "Nenhum link válido" in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caso", list(ACEITAS))
    async def test_painel_adicionar_favorito_aceita(self, caso):
        entrada, esperado = self.ACEITAS[caso]
        resultado = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {}, nome="novo", url=entrada)
        assert resultado.errors == {} and resultado.new["fav_links"]["novo"] == esperado

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caso", list(RECUSADAS))
    async def test_painel_adicionar_favorito_recusa(self, caso):
        resultado = await painel_favoritos(
            BotDoPainel(), "favorito_adicionar", {}, nome="novo", url=self.RECUSADAS[caso]
        )
        assert resultado.new == {} and resultado.errors.get("url")

    @pytest.mark.asyncio
    async def test_painel_editar_favorito_usa_a_mesma_regra(self):
        favoritos = {"antigo": URL}
        aceito = await painel_favoritos(BotDoPainel(), "favorito_editar", favoritos, nome="antigo", url=f"<{URL}b>")
        assert aceito.errors == {} and aceito.new["fav_links"]["antigo"] == f"{URL}b"
        recusado = await painel_favoritos(BotDoPainel(), "favorito_editar", favoritos, nome="antigo", url=f"veja {URL}")
        assert recusado.new == {} and recusado.errors.get("url")

    @pytest.mark.parametrize("caso", list(ACEITAS))
    def test_painel_adicionar_link_do_servidor_aceita(self, caso):
        entrada, esperado = self.ACEITAS[caso]
        resultado = painel_links(BotDoPainel(), "adicionar", {}, nome="Link", url=entrada, descricao="")
        assert resultado.errors == {} and resultado.new["fav_links"]["Link"]["url"] == esperado

    @pytest.mark.parametrize("caso", list(RECUSADAS))
    def test_painel_adicionar_link_do_servidor_recusa(self, caso):
        resultado = painel_links(BotDoPainel(), "adicionar", {}, nome="Link", url=self.RECUSADAS[caso], descricao="")
        assert resultado.new == {} and resultado.errors.get("url")

    def test_painel_editar_link_do_servidor_usa_a_mesma_regra(self):
        links = {"Link": {"url": URL, "description": ""}}
        aceito = painel_links(BotDoPainel(), "editar", links, nome="Link", url=f"<{URL}b>", descricao="")
        assert aceito.errors == {} and aceito.new["fav_links"]["Link"]["url"] == f"{URL}b"
        recusado = painel_links(BotDoPainel(), "editar", links, nome="Link", url=f"veja {URL}", descricao="")
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
    async def test_painel_importa_ate_25_e_recusa_de_26_a_35_com_a_configuracao_padrao(self):
        """Etapa 3 (A3/D2): o teto é min(configuração, 25); o padrão 35 deixa de valer para nomes de 26 a 35."""
        aceito, erros = await importar_no_painel(FAVORITOS, {"n" * 25: URL})
        assert erros == {} and aceito == {"n" * 25: URL}
        for tamanho in (26, 30, 35):
            guardado, erros = await importar_no_painel(FAVORITOS, {"n" * tamanho: URL}, bot=BotDoPainel(nome_max=35))
            assert guardado is None and erros, f"nome de {tamanho} caracteres deveria ser recusado"

    @pytest.mark.asyncio
    async def test_configuracao_intermediaria_vale_como_teto_nos_dois_lados(self):
        """D2: com USER_FAV_MAX_NAME_LENGTH = 20 o teto é 20, no painel e no bot."""
        for tamanho, aceito in ((20, True), (21, False)):
            no_painel, _ = await importar_no_painel(FAVORITOS, {"n" * tamanho: URL}, bot=BotDoPainel(nome_max=20))
            no_bot, _ = await importar_no_bot(FAVORITOS, {"n" * tamanho: URL}, bot=ModalBot(nome_max=20))
            assert (no_painel is not None, no_bot is not None) == (aceito, aceito), tamanho

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
        assert limits.FAV_NAME_MAX == 25
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
    async def test_importador_de_links_do_servidor_substitui_sem_diferenciar_a_caixa(self):
        """Etapa 5 (A5/A15): antes o importador do servidor só substituía o nome EXATO e deixava ``Rock`` e ``rock``."""
        antigas = self.existentes(SERVIDOR_MODO, f"{URL_BASE}/antiga")
        guardado, _ = await importar_no_bot(
            SERVIDOR_MODO, arquivo_do_modo(SERVIDOR_MODO, "rock", URL), existentes=antigas
        )
        assert list(guardado) == ["rock"]

    @pytest.mark.asyncio
    async def test_painel_substitui_o_link_do_servidor_que_so_difere_na_caixa(self):
        antigas = self.existentes(SERVIDOR_MODO, f"{URL_BASE}/antiga")
        guardado, erros = await importar_no_painel(
            SERVIDOR_MODO, arquivo_do_modo(SERVIDOR_MODO, "rock", URL), existentes=antigas
        )
        assert erros == {} and list(guardado) == ["rock"]

    @pytest.mark.asyncio
    async def test_painel_recusa_arquivo_do_servidor_com_o_mesmo_nome_em_caixas_diferentes(self):
        arquivo = {**arquivo_do_modo(SERVIDOR_MODO, "Rock", URL), **arquivo_do_modo(SERVIDOR_MODO, "rock", URL)}
        guardado, erros = await importar_no_painel(SERVIDOR_MODO, arquivo)
        assert guardado is None and erros

    @pytest.mark.asyncio
    @pytest.mark.parametrize("onde", ["bot", "painel"])
    async def test_substituir_pela_caixa_nao_ocupa_vaga_com_25_links(self, onde):
        existentes = {f"item{i}": {"url": URL, "description": "ddd"} for i in range(TETO_DE_LINKS)}
        existentes["Rock"] = existentes.pop("item0")
        item = {"rock": {"url": f"{URL_BASE}/nova", "description": "nova"}}
        if onde == "bot":
            guardado, texto = await importar_no_bot(SERVIDOR_MODO, item, existentes=existentes)
        else:
            guardado, texto = await importar_no_painel(SERVIDOR_MODO, item, existentes=existentes)
        assert guardado is not None, texto
        assert len(guardado) == TETO_DE_LINKS and "rock" in guardado and "Rock" not in guardado

    @pytest.mark.asyncio
    async def test_modal_do_servidor_recusa_adicionar_nome_que_so_difere_na_caixa(self):
        bot = ModalBot()
        bot.guild_data["player_controller"]["fav_links"] = {"Rock": {"url": URL, "description": "antiga"}}
        inter = await adicionar_link_do_servidor(bot, "rock", f"{URL_BASE}/b", "nova")
        assert bot.salvos_servidor == [] and "já" in inter.texto.lower()

    def test_painel_recusa_adicionar_link_do_servidor_que_so_difere_na_caixa(self):
        existentes = {"Rock": {"url": URL, "description": ""}}
        resultado = painel_links(BotDoPainel(), "adicionar", existentes, nome="rock", url=URL, descricao="")
        assert resultado.new == {} and resultado.errors.get("nome")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", [FAVORITOS, INTEGRACOES], ids=["favoritos", "integracoes"])
    async def test_painel_substitui_o_nome_que_so_difere_na_caixa(self, modo):
        """Etapa 3 (A5): o painel também compara sem diferenciar a caixa (importar substitui o existente)."""
        antigas = self.existentes(modo, f"{URL_BASE}/antiga")
        guardado, erros = await importar_no_painel(modo, arquivo_do_modo(modo, "rock", URL), existentes=antigas)
        assert erros == {} and list(guardado) == ["rock"]

    @pytest.mark.asyncio
    async def test_importar_substituindo_pela_caixa_nao_ocupa_vaga_no_painel(self):
        guardado, erros = await importar_no_painel(
            FAVORITOS, {"rock": URL}, bot=BotDoPainel(favs=1), existentes={"Rock": f"{URL_BASE}/antiga"}
        )
        assert erros == {} and guardado == {"rock": URL}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", [FAVORITOS, INTEGRACOES], ids=["favoritos", "integracoes"])
    async def test_arquivo_com_o_mesmo_nome_em_caixas_diferentes_e_recusado_nos_dois_lados(self, modo):
        arquivo = {**arquivo_do_modo(modo, "Rock", URL), **arquivo_do_modo(modo, "rock", URL)}
        no_bot, texto = await importar_no_bot(modo, arquivo)
        assert no_bot is None and "repetir nomes" in texto
        no_painel, erros = await importar_no_painel(modo, arquivo)  # Etapa 3 (A5): o painel também recusa
        assert no_painel is None and erros

    @pytest.mark.asyncio
    async def test_guarda_arquivo_do_servidor_com_o_mesmo_nome_em_caixas_diferentes_o_bot_recusa(self):
        arquivo = {**arquivo_do_modo(SERVIDOR_MODO, "Rock", URL), **arquivo_do_modo(SERVIDOR_MODO, "rock", URL)}
        no_bot, texto = await importar_no_bot(SERVIDOR_MODO, arquivo)
        assert no_bot is None and "repetir nomes" in texto

    @pytest.mark.asyncio
    async def test_modal_do_bot_recusa_adicionar_nome_que_so_difere_na_caixa(self):
        """Etapa 3 (A5): adicionar à mão recusa o nome que colide (sem diferenciar a caixa) com OUTRA entrada."""
        bot = ModalBot(fav_links={"Rock": URL})
        inter = await adicionar_favorito(bot, nome="rock")
        assert bot.salvos_usuario == [] and "já" in inter.texto.lower() and "nome" in inter.texto

    @pytest.mark.asyncio
    async def test_painel_recusa_adicionar_nome_que_so_difere_na_caixa(self):
        resultado = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {"Rock": URL}, nome="rock", url=URL)
        assert resultado.new == {} and resultado.errors.get("nome")

    @pytest.mark.asyncio
    async def test_modal_do_bot_edita_para_outra_caixa_do_proprio_nome(self):
        """Renomear ``rock`` para ``Rock`` é permitido: a colisão é com OUTRA entrada, não consigo mesma."""
        bot = ModalBot(fav_links={"rock": URL, "pop": URL})
        await adicionar_favorito(bot, nome="Rock", url=f"{URL_BASE}/b", editando="rock")
        assert bot.salvos_usuario[-1]["fav_links"] == {"Rock": f"{URL_BASE}/b", "pop": URL}

    @pytest.mark.asyncio
    async def test_modal_do_bot_recusa_editar_para_o_nome_de_outra_entrada_em_outra_caixa(self):
        bot = ModalBot(fav_links={"antigo": URL, "Pop": URL})
        inter = await adicionar_favorito(bot, nome="pop", url=f"{URL_BASE}/b", editando="antigo")
        assert bot.salvos_usuario == [] and "já" in inter.texto.lower()

    @pytest.mark.asyncio
    async def test_guarda_editar_sem_renomear_funciona_mesmo_com_um_par_antigo_rock_e_rock(self):
        bot = ModalBot(fav_links={"Rock": URL, "rock": URL})
        await adicionar_favorito(bot, nome="Rock", url=f"{URL_BASE}/b", editando="Rock")
        assert bot.salvos_usuario[-1]["fav_links"] == {"Rock": f"{URL_BASE}/b", "rock": URL}


# ============================================================================ A6, A7 — renomear e sanitizar no modal


class TestA6RenomearSobrescreveEmSilencio:
    @pytest.mark.asyncio
    async def test_modal_do_bot_recusa_renomear_sobre_outra_entrada(self):
        """Etapa 3 (A6): antes o modal apagava em silêncio a entrada ``outro``; agora recusa e não grava nada."""
        bot = ModalBot(fav_links={"antigo": f"{URL_BASE}/1", "outro": f"{URL_BASE}/2"})
        inter = await adicionar_favorito(bot, nome="outro", url=f"{URL_BASE}/novo", editando="antigo")
        assert bot.salvos_usuario == [], "nada pode ser gravado quando a renomeação colide"
        assert "já" in inter.texto.lower() and "nome" in inter.texto
        assert bot.user_data["fav_links"] == {"antigo": f"{URL_BASE}/1", "outro": f"{URL_BASE}/2"}

    @pytest.mark.asyncio
    async def test_modal_do_bot_renomear_para_um_nome_livre_move_a_entrada(self):
        bot = ModalBot(fav_links={"antigo": f"{URL_BASE}/1", "outro": f"{URL_BASE}/2"})
        await adicionar_favorito(bot, nome="novo", url=f"{URL_BASE}/novo", editando="antigo")
        assert bot.salvos_usuario[-1]["fav_links"] == {"outro": f"{URL_BASE}/2", "novo": f"{URL_BASE}/novo"}

    @pytest.mark.asyncio
    async def test_modal_do_bot_recusa_adicionar_nome_exato_que_ja_existe(self):
        bot = ModalBot(fav_links={"outro": f"{URL_BASE}/2"})
        inter = await adicionar_favorito(bot, nome="outro", url=f"{URL_BASE}/novo")
        assert bot.salvos_usuario == [] and "já" in inter.texto.lower()

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


class TestA7NomeSanitizadoNoModal:
    """Etapa 3 (A7): o modal do bot revalida o nome depois do ``strip`` (2 a 25 caracteres, sem ``Cc``/``Cf``), como o
    painel."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome", [" a", "a ", "ab\u200b", "a\x07b", "\u200bab"], ids=lambda n: repr(n))
    async def test_modal_do_bot_recusa_o_nome_invalido_e_nao_grava(self, nome):
        bot = ModalBot()
        inter = await adicionar_favorito(bot, nome=nome)
        assert bot.salvos_usuario == [], f"{nome!r} não pode ser gravado"
        assert "nome" in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_modal_do_bot_apara_as_pontas_de_um_nome_valido(self):
        bot = ModalBot()
        await adicionar_favorito(bot, nome="  Rock  ")
        assert list(bot.salvos_usuario[-1]["fav_links"]) == ["Rock"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome", [" a", "ab\u200b", "a\x07b", "a"])
    async def test_painel_recusa(self, nome):
        resultado = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {}, nome=nome, url=URL)
        assert resultado.new == {} and resultado.errors.get("nome")


# ============================================================================ A8, A9 — cota e código morto


class TestA8CotaDaIntegracaoAntesDeSaberSeOTituloExiste:
    @pytest.mark.asyncio
    async def test_modal_salva_reeditar_integracao_existente_com_a_lista_cheia(self):
        """Etapa 2 (A8): a cota só vale para título NOVO; reeditar um existente não ocupa vaga."""
        bot = ModalBot(
            integracoes=1, integration_links={"【DZ】: Ana": {"url": "https://www.deezer.com/profile/123456"}}
        )
        await adicionar_integracao(bot)
        salvo = bot.salvos_usuario[-1]["integration_links"]
        assert list(salvo) == ["【DZ】: Ana"] and salvo["【DZ】: Ana"]["url"].endswith("/profile/123456")

    @pytest.mark.asyncio
    async def test_guarda_modal_com_a_lista_cheia_e_titulo_novo_continua_recusado(self):
        bot = ModalBot(integracoes=1, integration_links={"Outro": {"url": f"{URL_BASE}/antiga"}})
        inter = await adicionar_integracao(bot)
        assert bot.salvos_usuario == [] and "Não há espaço disponível" in inter.texto

    @pytest.mark.asyncio
    async def test_importador_do_bot_sobrescreve_com_a_lista_cheia(self):
        bot = ModalBot(integracoes=1, integration_links={"Canal": {"url": f"{URL_BASE}/antiga"}})
        guardado, _ = await importar_no_bot(INTEGRACOES, {"Canal": URL}, bot=bot)
        assert guardado == {"Canal": {"url": URL}}  # Etapa 5 (A10): o texto-URL é gravado como objeto

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
    async def test_importador_do_bot_guarda_sempre_um_objeto(self):
        """Etapa 5 (A10): o texto-URL do formato antigo vira ``{"url": ...}`` (antes era gravado como texto puro)."""
        guardado, _ = await importar_no_bot(INTEGRACOES, {"Canal": URL, "Outro": {"url": f"{URL_BASE}/b"}})
        assert guardado == {"Canal": {"url": URL}, "Outro": {"url": f"{URL_BASE}/b"}}

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
    @pytest.mark.parametrize("avatar", [f"{AVATAR} lixo", f"{AVATAR}]x", f"{URL_BASE}/@everyone", f"{AVATAR}\nx"])
    async def test_painel_recusa_o_avatar_sujo(self, avatar):
        """Etapa 4 (A11): como a URL, o avatar do painel é a URL inteira limpa (antes guardava só o prefixo)."""
        guardado, erros = await importar_no_painel(INTEGRACOES, {"Canal": {"url": URL, "avatar": avatar}})
        assert guardado is None and erros

    @pytest.mark.asyncio
    async def test_painel_apara_as_pontas_do_avatar_como_o_bot(self):
        item = {"Canal": {"url": URL, "avatar": f"  {self.AVATAR}  "}}
        no_painel, erros = await importar_no_painel(INTEGRACOES, item)
        no_bot, _ = await importar_no_bot(INTEGRACOES, item)
        assert erros == {} and no_painel["Canal"]["avatar"] == no_bot["Canal"]["avatar"] == self.AVATAR

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
    async def test_200_aceita_e_201_recusa_nos_dois_sem_depender_da_configuracao(self):
        """Etapa 5 (A12/D4): o importador aceita até 200, o mesmo teto do modal (antes 150)."""
        for tamanho, aceito in ((150, True), (151, True), (200, True), (201, False)):
            item = {"Canal": url_com_tamanho(tamanho)}
            no_painel, _ = await importar_no_painel(INTEGRACOES, item, bot=BotDoPainel(url_max=90))
            no_bot, _ = await importar_no_bot(INTEGRACOES, item, bot=ModalBot(url_max=90))
            assert (no_painel is not None, no_bot is not None) == (aceito, aceito), tamanho

    def test_o_modal_manual_aceita_ate_200(self):
        assert campos_do_modal(INTEGRACOES)["user_integration_url"].max_length == 200

    @pytest.mark.asyncio
    async def test_titulo_ate_90_nos_dois_e_o_modal_cria_ate_80(self):
        assert limits.ITG_TITLE_MAX == 90
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
        assert limits.ITG_TITLE_MAX == 90


# ============================================================================ A13, A14, A15, A16 — links fixos do servidor


class TestA13LimiteDeUrlDosLinksDoServidor:
    """Etapa 5 (A13/D5): os links do servidor têm limite PRÓPRIO de 250 (o mesmo do modal) e deixam de usar
    ``USER_FAV_MAX_URL_LENGTH``, que continua valendo só para os favoritos pessoais."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url_max", [40, 90, 200])
    async def test_importador_aceita_ate_250_e_recusa_251_qualquer_que_seja_a_configuracao(self, url_max):
        for tamanho, aceito in ((90, True), (120, True), (250, True), (251, False)):
            item = arquivo_do_modo(SERVIDOR_MODO, "Link", url_com_tamanho(tamanho))
            no_painel, _ = await importar_no_painel(SERVIDOR_MODO, item, bot=BotDoPainel(url_max=url_max))
            no_bot, _ = await importar_no_bot(SERVIDOR_MODO, item, bot=ModalBot(url_max=url_max))
            assert (no_painel is not None, no_bot is not None) == (aceito, aceito), (url_max, tamanho)

    def test_o_modal_do_bot_aceita_ate_250(self):
        assert campos_do_modal(SERVIDOR_MODO)["guild_fav_url"].max_length == 250

    @pytest.mark.asyncio
    async def test_link_de_120_criado_no_modal_e_no_painel_reimporta_com_a_configuracao_padrao(self):
        longa = url_com_tamanho(120)
        bot = ModalBot(nome_max=35, url_max=90)
        await adicionar_link_do_servidor(bot, "Longo", longa)
        guardado = bot.salvos_servidor[-1]["player_controller"]["fav_links"]
        assert guardado["Longo"]["url"] == longa
        de_volta, texto = await importar_no_bot(SERVIDOR_MODO, guardado, bot=ModalBot(nome_max=35, url_max=90))
        assert de_volta is not None, texto
        criado = painel_links(BotDoPainel(), "adicionar", {}, nome="Longo", url=longa, descricao="")
        assert criado.errors == {}
        no_painel, erros = await importar_no_painel(SERVIDOR_MODO, criado.new["fav_links"])
        assert erros == {} and no_painel["Longo"]["url"] == longa

    @pytest.mark.asyncio
    async def test_guarda_favoritos_pessoais_seguem_a_configuracao_de_url(self):
        for tamanho, aceito in ((90, True), (91, False)):
            item = {"Musica": url_com_tamanho(tamanho)}
            no_painel, _ = await importar_no_painel(FAVORITOS, item, bot=BotDoPainel(url_max=90))
            no_bot, _ = await importar_no_bot(FAVORITOS, item, bot=ModalBot(url_max=90))
            assert (no_painel is not None, no_bot is not None) == (aceito, aceito)


class TestA14DescricaoDoLinkDoServidor:
    """O importador (bot e painel) só confere ``<= 100``; o modal e a adição do painel exigem vazia ou 3–100."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("descricao", ["a", "ab", "  ab  "])
    async def test_importadores_recusam_descricao_de_1_ou_2_caracteres(self, descricao):
        """Etapa 5 (A14): a descrição é vazia ou tem 3 a 100 caracteres também na importação (antes aceitava 1 a 2)."""
        item = {"Link": {"url": URL, "description": descricao}}
        no_painel, erros = await importar_no_painel(SERVIDOR_MODO, item)
        no_bot, texto = await importar_no_bot(SERVIDOR_MODO, item)
        assert no_painel is None and erros
        assert no_bot is None and texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("descricao", "esperada"), [("", ""), ("abc", "abc"), ("d" * 100, "d" * 100), ("  abc  ", "abc")]
    )
    async def test_importadores_aceitam_descricao_vazia_ou_de_3_a_50_e_apara_as_pontas(self, descricao, esperada):
        item = {"Link": {"url": URL, "description": descricao}}
        no_painel, erros = await importar_no_painel(SERVIDOR_MODO, item)
        no_bot, _ = await importar_no_bot(SERVIDOR_MODO, item)
        assert erros == {} and no_painel["Link"]["description"] == no_bot["Link"]["description"] == esperada

    @pytest.mark.asyncio
    async def test_guarda_importadores_recusam_mais_de_100(self):
        item = {"Link": {"url": URL, "description": "d" * 101}}
        no_painel, erros = await importar_no_painel(SERVIDOR_MODO, item)
        no_bot, texto = await importar_no_bot(SERVIDOR_MODO, item)
        assert no_painel is None and erros and no_bot is None and "ultrapassa" in texto

    def test_o_modal_do_bot_pede_de_3_a_100_e_a_descricao_e_opcional(self):
        campo = campos_do_modal(SERVIDOR_MODO)["guild_fav_description"]
        assert (campo.min_length, campo.max_length, campo.required) == (3, 100, False)

    def test_o_painel_recusa_descricao_de_2_caracteres_ao_adicionar(self):
        recusado = painel_links(BotDoPainel(), "adicionar", {}, nome="Link", url=URL, descricao="ab")
        aceito = painel_links(BotDoPainel(), "adicionar", {}, nome="Link", url=URL, descricao="abc")
        assert recusado.errors.get("descricao") and aceito.errors == {}


class TestA15SobrescritaNosLinksDoServidor:
    @pytest.mark.asyncio
    async def test_modal_do_bot_recusa_adicionar_nome_existente_e_nao_sobrescreve(self):
        """Etapa 5 (A15): adicionar um nome que já existe é recusado (antes sobrescrevia sem avisar)."""
        bot = ModalBot()
        original = {"Link": {"url": f"{URL_BASE}/1", "description": "antiga"}}
        bot.guild_data["player_controller"]["fav_links"] = dict(original)
        inter = await adicionar_link_do_servidor(bot, "Link", URL, "nova")
        assert bot.salvos_servidor == [] and "já" in inter.texto.lower()
        assert bot.guild_data["player_controller"]["fav_links"] == original

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

    @pytest.mark.asyncio
    async def test_modal_do_bot_editar_a_propria_entrada_funciona(self):
        bot = ModalBot()
        bot.guild_data["player_controller"]["fav_links"] = {"a1": {"url": f"{URL_BASE}/1", "description": ""}}
        await adicionar_link_do_servidor(bot, "a1", URL, "nova", editando="a1")
        assert bot.salvos_servidor[-1]["player_controller"]["fav_links"] == {"a1": {"url": URL, "description": "nova"}}

    def test_painel_recusa_nome_existente(self):
        existentes = {"Link": {"url": URL, "description": ""}}
        resultado = painel_links(BotDoPainel(), "adicionar", existentes, nome="Link", url=URL, descricao="")
        assert resultado.new == {} and resultado.errors.get("nome")

    @pytest.mark.asyncio
    async def test_modal_do_bot_com_25_itens_edita_a_propria_entrada_e_recusa_a_nova(self):
        """Guarda (A15): com 25 itens, editar uma entrada existente salva (não ocupa vaga); um nome novo é recusado."""
        bot = ModalBot()
        bot.guild_data["player_controller"]["fav_links"] = {
            f"item{i}": {"url": URL, "description": ""} for i in range(TETO_DE_LINKS)
        }
        await adicionar_link_do_servidor(bot, "item3", URL, "nova", editando="item3")
        assert bot.salvos_servidor[-1]["player_controller"]["fav_links"]["item3"]["description"] == "nova"
        bot.salvos_servidor.clear()
        inter = await adicionar_link_do_servidor(bot, "novo", URL, "nova")
        assert bot.salvos_servidor == [] and "Não há espaço disponível" in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_importadores_sobrescrever_nao_ocupa_vaga_com_25_itens(self):
        existentes = {f"item{i}": {"url": URL, "description": "ddd"} for i in range(TETO_DE_LINKS)}
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
        arquivo = {f"item{i}": {"url": URL, "description": "ddd"} for i in range(TETO_DE_LINKS + 1)}
        guardado, texto = await importar_no_bot(SERVIDOR_MODO, arquivo)
        assert guardado is None and "excede a quantidade máxima permitida (25)" in texto

    @pytest.mark.asyncio
    async def test_arquivo_pequeno_mais_o_que_ja_existe_diz_que_nao_ha_espaco(self):
        existentes = {f"item{i}": {"url": URL, "description": "ddd"} for i in range(TETO_DE_LINKS)}
        guardado, texto = await importar_no_bot(
            SERVIDOR_MODO, {"novo": {"url": URL, "description": "ddd"}}, existentes=existentes
        )
        assert guardado is None and "não possui espaço suficiente" in texto and "Limite atual: 25" in texto


class TestLimitesDoPainelSaoLiteraisAquiEConstantesLa:
    """As constantes do painel são conferidas contra os números deste arquivo, que não mudam com elas."""

    def test_constantes(self):
        assert (limits.FAV_NAME_MIN, limits.FAV_NAME_MAX) == (2, 25)
        assert (limits.ITG_TITLE_MAX, limits.ITG_URL_MAX, limits.ITG_AVATAR_MAX) == (90, 200, 250)
        assert limits.MAX_GUILD_LINKS == TETO_DE_LINKS and (limits.GUILD_LINK_URL_MIN, limits.GUILD_LINK_URL_MAX) == (
            10,
            LIMITE_DA_URL_DO_LINK,
        )
        assert (
            limits.GUILD_LINK_NAME_MIN,
            limits.GUILD_LINK_NAME_MAX,
            limits.GUILD_LINK_DESCRIPTION_MIN,
            limits.GUILD_LINK_DESCRIPTION_MAX,
        ) == (2, 25, 3, 100)

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
    async def test_integracao_importada_em_texto_volta_como_objeto(self):
        bot = ModalBot()
        await importar(bot, INTEGRACOES, {"Canal": URL})
        bot.user_data["integration_links"].update(bot.salvos_usuario[-1]["integration_links"])
        assert json.loads(await exportar_integracoes(bot)) == {"Canal": {"url": URL}}

    @pytest.mark.asyncio
    async def test_guarda_favoritos_ida_e_volta(self):
        bot = ModalBot(fav_links={"Rock": URL, "Pop": f"{URL_BASE}/b"})
        _, arquivo = await exportar(bot, FAVORITOS)
        conteudo = json.loads(arquivo)
        no_bot, _ = await importar_no_bot(FAVORITOS, conteudo)
        no_painel, erros = await importar_no_painel(FAVORITOS, conteudo)
        assert no_bot == no_painel == conteudo and erros == {}

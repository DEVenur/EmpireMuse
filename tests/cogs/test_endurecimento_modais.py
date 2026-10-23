"""F3-5b, endurecimento do PR 2 (auditoria AppSec A-1, A-2, A-3, I-1, I-3 e I-6).

Escrito pelo Backend por exceção do MAESTRO (o QA estava sem sessão); o QA revisa e faz a mutação depois.

* A-1 + I-1: a URL não pode ter ``usuário[:senha]@`` antes do 1º ``/`` depois de ``://`` nem ``<``, ``>``, ``)`` ou ``\\``
  dentro dela; o ``@`` no caminho e na consulta continua valendo (``youtube.com/@canal``).
* A-2: descrição do link do servidor e status de voz recusam ``Cc``/``Cf`` (mesma regra de ``clean_title``) depois de aparar.
* A-3: o modal de integração só consulta Spotify/Deezer/yt-dlp depois do cooldown por membro (1 a cada 15 s, mesma mensagem
  do importador) e, com a lista cheia e um perfil que ainda não está salvo, recusa ANTES da consulta externa.
* I-3: URL e avatar devolvidos pelos serviços externos passam por ``check_url``/``clean_avatar`` antes de gravar.
* I-6: o título externo passa pela limpeza de nomes (sem ``Cc``/``Cf``) e a cota compara sem diferenciar a caixa.

Sem rede, sem Discord e sem ``.env``: as consultas externas são dublês que registram cada chamada.
"""

from types import SimpleNamespace

import pytest

from empiremuse.rules import guild_links, settings, urls
from empiremuse.rules.errors import RuleError
from empiremuse.utils.music import interactions
from empiremuse.utils.music.interactions import ViewMode
from tests.support.drivers_de_regras import (
    BotDeComandos,
    BotDoPainel,
    adicionar_link_do_servidor,
    importar_no_bot,
    importar_no_painel,
    painel_favoritos,
    painel_links,
    status_no_comando,
)
from tests.support.modais import (
    URL_BASE,
    ModalBot,
    adicionar_favorito,
    adicionar_integracao,
    arquivo_com,
    importar,
    trocar_process_idle_embed,
)

FAVORITOS, SERVIDOR, INTEGRACOES = ViewMode.fav_manager, ViewMode.guild_fav_manager, ViewMode.integrations_manager
MODOS = [
    pytest.param(FAVORITOS, id="favoritos"),
    pytest.param(SERVIDOR, id="servidor"),
    pytest.param(INTEGRACOES, id="integracoes"),
]
URL = f"{URL_BASE}/a"
PERFIL_DEEZER = "https://www.deezer.com/br/profile/123456"
PERFIL_SPOTIFY = "https://open.spotify.com/user/abc123"
CANAL_YOUTUBE = "https://www.youtube.com/@canal"


@pytest.fixture(autouse=True)
def _sem_idle_embed(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    trocar_process_idle_embed(monkeypatch, nada)


# ============================================================================ A-1 e I-1 — userinfo e caracteres perigosos


class TestA1UserinfoNaUrl:
    COM_USERINFO = [
        "https://usuario:senha@host.exemplo/x",
        "https://token@host.exemplo/x",
        "https://youtube.com@dominio.exemplo/x",
        "http://u:p@host.exemplo",
        "https://host.exemplo:8443@outro.exemplo/x",
        "https://@host.exemplo/x",
    ]
    SEM_USERINFO = [
        "https://www.youtube.com/@canal",
        "https://www.youtube.com/@canal/playlists",
        "https://host.exemplo/x@y",
        "https://host.exemplo/x?email=fulano@exemplo.com",
        "https://host.exemplo?email=fulano@exemplo.com",
        "https://host.exemplo:8443/x",
        "https://open.spotify.com/user/abc123",
    ]
    PERIGOSAS = [
        "https://host.exemplo/x)<@123456789012345678>",
        "https://host.exemplo/x<y",
        "https://host.exemplo/x>y",
        "https://host.exemplo/x)y",
        "https://host.exemplo/x\\y",
    ]

    @pytest.mark.parametrize("url", COM_USERINFO)
    def test_is_clean_url_e_check_url_recusam_usuario_e_senha_antes_do_caminho(self, url):
        assert not urls.is_clean_url(url)
        assert isinstance(urls.check_url(url, 200), RuleError) and urls.clean_url(url, 200) is None

    @pytest.mark.parametrize("url", SEM_USERINFO)
    def test_o_arroba_no_caminho_e_na_consulta_continua_valendo(self, url):
        assert urls.is_clean_url(url) and urls.clean_url(url, 200) == url

    @pytest.mark.parametrize("url", PERIGOSAS)
    def test_menor_maior_parentese_de_fechar_e_barra_invertida_dentro_da_url_sao_recusados(self, url):
        assert not urls.is_clean_url(url) and urls.clean_url(url, 200) is None

    def test_o_desembrulho_de_sinais_de_menor_e_maior_continua_valendo_so_nas_pontas(self):
        assert urls.clean_url("  <https://host.exemplo/x>  ", 200) == "https://host.exemplo/x"
        assert urls.clean_url("<https://host.exemplo/x)>", 200) is None

    def test_o_avatar_tem_a_mesma_regra(self):
        assert urls.clean_avatar("https://usuario:senha@host.exemplo/a.png") is None
        assert urls.clean_avatar("https://host.exemplo/a.png)") is None
        assert urls.clean_avatar("https://host.exemplo/@a/a.png") == "https://host.exemplo/@a/a.png"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", [*COM_USERINFO, *PERIGOSAS])
    async def test_modais_de_favorito_e_de_link_do_servidor_recusam(self, url):
        bot = ModalBot()
        inter = await adicionar_favorito(bot, url=url)
        assert bot.salvos_usuario == [] and "Nenhum link válido" in inter.texto
        inter = await adicionar_link_do_servidor(bot, "Link", url)
        assert bot.salvos_servidor == [] and "Nenhum link válido" in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", [COM_USERINFO[0], COM_USERINFO[2], PERIGOSAS[0]])
    async def test_modal_de_integracao_recusa_antes_de_qualquer_consulta(self, url):
        bot = BotEspiao()
        inter = await adicionar_integracao(bot, url=url)
        assert bot.salvos_usuario == [] and bot.consultas == [] and "Nenhum link válido" in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS)
    @pytest.mark.parametrize("url", [COM_USERINFO[0], COM_USERINFO[2], PERIGOSAS[0], PERIGOSAS[4]])
    async def test_importadores_do_bot_e_do_painel_recusam_o_arquivo_inteiro(self, modo, url):
        arquivo = arquivo_com(modo, "Musica", url)
        no_bot, texto = await importar_no_bot(modo, arquivo)
        no_painel, erros = await importar_no_painel(modo, arquivo)
        assert no_bot is None and "link inválido" in texto
        assert no_painel is None and erros

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", MODOS)
    async def test_importadores_aceitam_o_arroba_do_canal_do_youtube(self, modo):
        arquivo = arquivo_com(modo, "Canal", "https://www.youtube.com/@canal")
        no_bot, _ = await importar_no_bot(modo, arquivo)
        no_painel, erros = await importar_no_painel(modo, arquivo)
        assert no_bot is not None and erros == {} and no_painel is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", COM_USERINFO[:3])
    async def test_painel_recusa_ao_adicionar_favorito_e_link_do_servidor(self, url):
        favorito = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {}, nome="novo", url=url)
        assert favorito.new == {} and favorito.errors.get("url")
        link = painel_links(BotDoPainel(), "adicionar", {}, nome="Link", url=url, descricao="")
        assert link.new == {} and link.errors.get("url")


# ============================================================================ A-2 — controle e formatação em descrição e status


class TestA2ControleNaDescricaoEnoStatus:
    COM_CONTROLE = ["ab\ncd", "ab\x00cd", "\x00\x00\x00", "abc\u202edef", "abc\u200bdef", "ab\tcd", "ab\u2066cd"]

    @pytest.mark.parametrize("texto", COM_CONTROLE, ids=repr)
    def test_check_description_recusa_cc_e_cf_depois_de_aparar(self, texto):
        assert isinstance(guild_links.check_description(texto), RuleError)
        assert isinstance(guild_links.check_description(f"  {texto}  "), RuleError)

    @pytest.mark.parametrize("texto", ["", "   ", "uma descrição normal", "Música — ao vivo", "a" * 50])
    def test_check_description_segue_aceitando_texto_comum(self, texto):
        assert guild_links.check_description(texto) == texto.strip()

    def test_reenviar_a_descricao_ja_gravada_nao_revalida_o_dado_legado(self):
        legado = "gravada\x00antes"
        assert guild_links.check_description(legado, legado) == legado

    @pytest.mark.asyncio
    @pytest.mark.parametrize("texto", ["ab\x00cd", "abc\u202edef", "\x00\x00\x00"], ids=repr)
    async def test_importadores_do_bot_e_do_painel_recusam_a_descricao(self, texto):
        item = {"Link": {"url": URL, "description": texto}}
        no_bot, mensagem = await importar_no_bot(SERVIDOR, item)
        no_painel, erros = await importar_no_painel(SERVIDOR, item)
        assert no_bot is None and mensagem and no_painel is None and erros

    @pytest.mark.asyncio
    @pytest.mark.parametrize("texto", ["ab\x00cd", "abc\u202edef"], ids=repr)
    async def test_modal_e_painel_recusam_a_descricao_ao_adicionar(self, texto):
        bot = ModalBot()
        inter = await adicionar_link_do_servidor(bot, "Link", URL, texto)
        assert bot.salvos_servidor == [] and inter.texto
        painel = painel_links(BotDoPainel(), "adicionar", {}, nome="Link", url=URL, descricao=texto)
        assert painel.new == {} and painel.errors.get("descricao")

    @pytest.mark.parametrize(
        "texto", ["{track.title}\x00", "{track.title}\u202e", "{track.title}\u200b x", "x\ty {track.title}"]
    )
    def test_validate_voice_status_recusa_cc_e_cf(self, texto):
        assert isinstance(settings.validate_voice_status(texto), RuleError)

    def test_a_quebra_de_linha_continua_virando_espaco_e_nao_conta_como_controle(self):
        assert settings.validate_voice_status("a\r\n{track.title}\nb") == "a {track.title} b"
        assert settings.validate_voice_status("") == ""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("texto", ["{track.title}\x00", "{track.title}\u202e"], ids=repr)
    async def test_comando_de_status_de_voz_recusa_com_mensagem_de_caracteres(self, texto):
        salvo, mensagem = await status_no_comando(BotDeComandos(), texto)
        assert salvo is None and "caracteres" in mensagem and "placeholder" not in mensagem.lower()

    @pytest.mark.parametrize("texto", ["{track.title}\x00", "{track.title}\u202e"], ids=repr)
    def test_painel_de_status_de_voz_recusa(self, texto):
        from empiremuse.panel.services.general import VoiceStatusForm

        resultado = VoiceStatusForm().parse(
            SimpleNamespace(), {"voice_channel_status": ""}, {"voice_channel_status": [texto]}
        )
        assert resultado.new == {} and resultado.errors.get("voice_channel_status")


# ============================================================================ A-3, I-3 e I-6 — modal de integração


class BotEspiao(ModalBot):
    """``ModalBot`` com Spotify, Deezer e yt-dlp falsos que registram cada consulta e com o balde do cooldown contado."""

    def __init__(self, *, deezer=None, spotify=None, youtube=None, **kwargs):
        super().__init__(**kwargs)
        self.consultas, self.baldes = [], 0
        perfil_deezer = {
            "name": "Ana",
            "link": "https://www.deezer.com/profile/123456",
            "picture": f"{URL_BASE}/ana.png",
        }
        perfil_spotify = {
            "display_name": "Ana",
            "external_urls": {"spotify": PERFIL_SPOTIFY},
            "images": [{"url": f"{URL_BASE}/ana.png"}],
        }
        canal = {"title": "Canal", "original_url": f"{CANAL_YOUTUBE}/playlists", "entries": [1]}

        async def consulta_deezer(user_id):
            self.consultas.append(("deezer", user_id))
            return {**perfil_deezer, **(deezer or {})}

        async def consulta_spotify(user_id):
            self.consultas.append(("spotify", user_id))
            return {**perfil_spotify, **(spotify or {})}

        def consulta_ytdl(base_url, download=False):
            self.consultas.append(("ytdl", base_url))
            return {**canal, **(youtube or {})}

        self.deezer = SimpleNamespace(get_user_info=consulta_deezer)
        self.spotify = SimpleNamespace(get_user_info=consulta_spotify)
        self.pool = SimpleNamespace(ytdl=SimpleNamespace(extract_info=consulta_ytdl))

    def get_cog(self, nome):
        def baldes(inter):
            self.baldes += 1
            return SimpleNamespace(update_rate_limit=lambda: self.retry_after)

        return SimpleNamespace(
            fav_import_export_cd=SimpleNamespace(get_bucket=baldes), fav_manager=SimpleNamespace(name="fav_manager")
        )


FONTES = [
    pytest.param(PERFIL_DEEZER, "deezer", id="deezer"),
    pytest.param(PERFIL_SPOTIFY, "spotify", id="spotify"),
    pytest.param(CANAL_YOUTUBE, "ytdl", id="youtube"),
]


class TestA3CooldownAntesDaConsultaExterna:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("url", "fonte"), FONTES)
    async def test_com_o_balde_cheio_nao_consulta_nada_e_pede_para_aguardar(self, url, fonte):
        bot = BotEspiao(retry_after=7.2)
        inter = await adicionar_integracao(bot, url=url)
        assert bot.consultas == [] and bot.salvos_usuario == []
        assert "Aguarde" in inter.texto

    @pytest.mark.asyncio
    async def test_a_mensagem_de_espera_do_modal_e_neutra_e_diz_o_tempo(self):
        """Ao ADICIONAR uma integração a espera não fala em importar (o balde é o mesmo, a mensagem não)."""
        bot = BotEspiao(retry_after=7.2)
        inter = await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert inter.texto == "**Aguarde 7 segundos antes de tentar novamente.**"
        assert "importar" not in inter.texto and "exportar" not in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_a_mensagem_do_importador_continua_falando_em_importar(self):
        inter = await importar(ModalBot(retry_after=7.2), INTEGRACOES, {"Canal": URL})
        assert inter.texto == "**Você deve aguardar 7 segundos para importar.**"

    @pytest.mark.asyncio
    async def test_guarda_a_mensagem_do_exportador_continua_falando_em_exportar(self):
        from types import SimpleNamespace as Espelho

        from empiremuse.utils.music.interactions import FavMenuView
        from tests.support.modais import ModalInteraction

        bot = ModalBot(retry_after=7.2)
        inter = ModalInteraction()
        espelho = Espelho(bot=bot, mode=FAVORITOS, data=bot.user_data, guild_data=bot.guild_data)
        await FavMenuView.export_callback(espelho, inter)
        assert "para exportar" in inter.texto and "aguardar" in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("url", "fonte"), FONTES)
    async def test_guarda_com_o_balde_livre_consulta_uma_vez_e_grava(self, url, fonte):
        bot = BotEspiao()
        await adicionar_integracao(bot, url=url)
        assert [consulta[0] for consulta in bot.consultas] == [fonte] and bot.baldes == 1
        assert len(bot.salvos_usuario) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", ["https://exemplo.invalid/x", f"{URL_BASE}/user/abc", "sem link"])
    async def test_link_invalido_ou_de_fonte_nao_suportada_nao_gasta_o_balde(self, url):
        bot = BotEspiao(retry_after=7.2)
        inter = await adicionar_integracao(bot, url=url)
        assert bot.baldes == 0 and bot.consultas == [] and bot.salvos_usuario == []
        assert "Aguarde" not in inter.texto


class TestA3ListaCheiaRecusaAntesDaConsulta:
    CHEIA = {"Outra": {"url": f"{URL_BASE}/antiga"}}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("url", "fonte"), FONTES)
    async def test_perfil_novo_com_a_lista_cheia_e_recusado_sem_consultar(self, url, fonte):
        bot = BotEspiao(integracoes=1, integration_links=self.CHEIA)
        inter = await adicionar_integracao(bot, url=url)
        assert bot.consultas == [] and bot.salvos_usuario == []
        assert "Não há espaço disponível" in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("url", "salva", "fonte"),
        [
            (PERFIL_DEEZER, "https://www.deezer.com/profile/123456", "deezer"),
            (PERFIL_SPOTIFY + "?si=abc", PERFIL_SPOTIFY, "spotify"),
            (CANAL_YOUTUBE, f"{CANAL_YOUTUBE}/playlists", "ytdl"),
        ],
        ids=["deezer", "spotify", "youtube"],
    )
    async def test_perfil_que_ja_esta_salvo_consulta_e_sobrescreve_mesmo_com_a_lista_cheia(self, url, salva, fonte):
        titulo = {"deezer": "【DZ】: Ana", "spotify": "【SP】: Ana", "ytdl": "【YT】: Canal"}[fonte]
        bot = BotEspiao(integracoes=1, integration_links={titulo: {"url": salva}})
        await adicionar_integracao(bot, url=url)
        assert [consulta[0] for consulta in bot.consultas] == [fonte]
        assert len(bot.salvos_usuario[-1]["integration_links"]) == 1

    @pytest.mark.asyncio
    async def test_lista_cheia_do_dono_ou_sem_limite_nao_recusa_antes(self):
        for kwargs in ({"dono": True}, {"integracoes": 0}):
            bot = BotEspiao(**{"integracoes": 1, "integration_links": self.CHEIA, **kwargs})
            await adicionar_integracao(bot, url=PERFIL_DEEZER)
            assert len(bot.consultas) == 1 and len(bot.salvos_usuario[-1]["integration_links"]) == 2

    @pytest.mark.asyncio
    async def test_lista_com_vaga_consulta_normalmente(self):
        bot = BotEspiao(integracoes=2, integration_links=self.CHEIA)
        await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert len(bot.consultas) == 1 and len(bot.salvos_usuario[-1]["integration_links"]) == 2

    @pytest.mark.asyncio
    async def test_o_cooldown_vem_antes_da_recusa_por_lista_cheia(self):
        bot = BotEspiao(integracoes=1, integration_links=self.CHEIA, retry_after=3)
        inter = await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert bot.consultas == [] and "Aguarde" in inter.texto


class TestI3DadosExternosPassamPelaValidacao:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "link",
        [
            "javascript:alert(1)",
            "https://www.deezer.com/profile/1 texto",
            "https://usuario:senha@www.deezer.com/profile/1",
            "https://www.deezer.com/profile/1]",
            "https://www.deezer.com/profile/" + "1" * 300,
            "",
            None,
        ],
        ids=["javascript", "texto", "userinfo", "colchete", "longo", "vazio", "nulo"],
    )
    async def test_url_invalida_devolvida_pelo_deezer_nao_e_gravada(self, link):
        bot = BotEspiao(deezer={"link": link})
        inter = await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert bot.salvos_usuario == [] and inter.texto
        assert "javascript" not in inter.texto and "senha" not in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", ["https://open.spotify.com/user/a b", "ftp://open.spotify.com/user/a", "x" * 300])
    async def test_url_invalida_devolvida_pelo_spotify_nao_e_gravada(self, url):
        bot = BotEspiao(spotify={"external_urls": {"spotify": url}})
        await adicionar_integracao(bot, url=PERFIL_SPOTIFY)
        assert bot.salvos_usuario == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("original", ["javascript:alert(1)", "https://www.youtube.com/@canal/x y", None])
    async def test_url_invalida_devolvida_pelo_ytdlp_nao_e_gravada(self, original):
        bot = BotEspiao(youtube={"original_url": original})
        await adicionar_integracao(bot, url=CANAL_YOUTUBE)
        assert bot.salvos_usuario == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "avatar", ["javascript:alert(1)", "https://x.exemplo/a b.png", "https://u:p@x.exemplo/a.png", None, 5, ""]
    )
    async def test_avatar_invalido_e_descartado_e_a_integracao_e_gravada_sem_ele(self, avatar):
        bot = BotEspiao(deezer={"picture": avatar})
        await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert bot.salvos_usuario[-1]["integration_links"] == {
            "【DZ】: Ana": {"url": "https://www.deezer.com/profile/123456"}
        }

    @pytest.mark.asyncio
    async def test_guarda_url_e_avatar_validos_sao_gravados_aparados(self):
        bot = BotEspiao(deezer={"link": " https://www.deezer.com/profile/123456 ", "picture": f" {URL_BASE}/ana.png "})
        await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert bot.salvos_usuario[-1]["integration_links"] == {
            "【DZ】: Ana": {"url": "https://www.deezer.com/profile/123456", "avatar": f"{URL_BASE}/ana.png"}
        }


class TestI6TituloExterno:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("nome", "esperado"),
        [("An\u202ea", "【DZ】: Ana"), ("A\x00na", "【DZ】: Ana"), ("A\u200bna", "【DZ】: Ana")],
        ids=["u202e", "nul", "u200b"],
    )
    async def test_titulo_sem_controle_nem_formatacao(self, nome, esperado):
        bot = BotEspiao(deezer={"name": nome})
        await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert list(bot.salvos_usuario[-1]["integration_links"]) == [esperado]

    @pytest.mark.asyncio
    async def test_variante_de_caixa_sobrescreve_a_existente_em_vez_de_duplicar(self):
        bot = BotEspiao(integracoes=5, integration_links={"【dz】: ana": {"url": f"{URL_BASE}/antiga"}})
        await adicionar_integracao(bot, url=PERFIL_DEEZER)
        salvo = bot.salvos_usuario[-1]["integration_links"]
        assert len(salvo) == 1 and next(iter(salvo.values()))["url"].endswith("/profile/123456")

    @pytest.mark.asyncio
    async def test_variante_de_caixa_nao_ocupa_vaga_com_a_lista_cheia(self):
        bot = BotEspiao(
            integracoes=1, integration_links={"【dz】: ana": {"url": "https://www.deezer.com/profile/123456"}}
        )
        await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert len(bot.salvos_usuario[-1]["integration_links"]) == 1

    @pytest.mark.asyncio
    async def test_titulo_novo_com_a_lista_cheia_continua_recusado_no_fim(self):
        """A conferência final da cota continua valendo (corrida entre o cooldown e a gravação)."""
        bot = BotEspiao(integracoes=1, integration_links={"Outra": {"url": "https://www.deezer.com/profile/123456"}})
        inter = await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert bot.salvos_usuario == [] and "Não há espaço disponível" in inter.texto


# ============================================================================ regras antigas sem uso


class TestRegrasAntigasForamRemovidas:
    def test_extract_url_legacy_e_url_prefix_legacy_sairam_de_rules_urls(self):
        assert not hasattr(urls, "extract_url_legacy") and not hasattr(urls, "url_prefix_legacy")

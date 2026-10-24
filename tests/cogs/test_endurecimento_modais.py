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
from empiremuse.utils.music.interactions import ViewMode
from tests.support.modais import URL_BASE, ModalBot, adicionar_integracao, trocar_process_idle_embed

pytestmark = pytest.mark.critical

FAVORITOS, SERVIDOR, INTEGRACOES = ViewMode.fav_manager, ViewMode.guild_fav_manager, ViewMode.integrations_manager
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

    @pytest.mark.parametrize("url", PERIGOSAS)
    def test_menor_maior_parentese_de_fechar_e_barra_invertida_dentro_da_url_sao_recusados(self, url):
        assert not urls.is_clean_url(url) and urls.clean_url(url, 200) is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", [COM_USERINFO[0], PERIGOSAS[0]])
    async def test_modal_de_integracao_recusa_antes_de_qualquer_consulta(self, url):
        bot = BotEspiao()
        inter = await adicionar_integracao(bot, url=url)
        assert bot.salvos_usuario == [] and bot.consultas == [] and "Nenhum link válido" in inter.texto


# ============================================================================ A-2 — controle e formatação em descrição e status


class TestA2ControleNaDescricaoEnoStatus:
    COM_CONTROLE = ["ab\ncd", "ab\x00cd", "\x00\x00\x00", "abc\u202edef", "abc\u200bdef", "ab\tcd", "ab\u2066cd"]

    @pytest.mark.parametrize("texto", ["", "a" * 50])
    def test_check_description_segue_aceitando_texto_comum(self, texto):
        assert guild_links.check_description(texto) == texto.strip()

    @pytest.mark.parametrize("texto", ["{track.title}\x00", "x\ty {track.title}"])
    def test_validate_voice_status_recusa_cc_e_cf(self, texto):
        assert isinstance(settings.validate_voice_status(texto), RuleError)


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


class TestA3CooldownAntesDaConsultaExterna:
    @pytest.mark.asyncio
    async def test_a_mensagem_de_espera_do_modal_e_neutra_e_diz_o_tempo(self):
        """Ao ADICIONAR uma integração a espera não fala em importar (o balde é o mesmo, a mensagem não)."""
        bot = BotEspiao(retry_after=7.2)
        inter = await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert inter.texto == "**Aguarde 7 segundos antes de tentar novamente.**"
        assert "importar" not in inter.texto and "exportar" not in inter.texto

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", ["https://exemplo.invalid/x", "sem link"])
    async def test_link_invalido_ou_de_fonte_nao_suportada_nao_gasta_o_balde(self, url):
        bot = BotEspiao(retry_after=7.2)
        inter = await adicionar_integracao(bot, url=url)
        assert bot.baldes == 0 and bot.consultas == [] and bot.salvos_usuario == []
        assert "Aguarde" not in inter.texto


class TestA3ListaCheiaRecusaAntesDaConsulta:
    CHEIA = {"Outra": {"url": f"{URL_BASE}/antiga"}}

    @pytest.mark.asyncio
    async def test_lista_com_vaga_consulta_normalmente(self):
        bot = BotEspiao(integracoes=2, integration_links=self.CHEIA)
        await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert len(bot.consultas) == 1 and len(bot.salvos_usuario[-1]["integration_links"]) == 2


class TestI3DadosExternosPassamPelaValidacao:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("avatar", ["javascript:alert(1)", ""])
    async def test_avatar_invalido_e_descartado_e_a_integracao_e_gravada_sem_ele(self, avatar):
        bot = BotEspiao(deezer={"picture": avatar})
        await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert bot.salvos_usuario[-1]["integration_links"] == {
            "【DZ】: Ana": {"url": "https://www.deezer.com/profile/123456"}
        }


class TestI6TituloExterno:
    @pytest.mark.asyncio
    async def test_variante_de_caixa_nao_ocupa_vaga_com_a_lista_cheia(self):
        bot = BotEspiao(
            integracoes=1, integration_links={"【dz】: ana": {"url": "https://www.deezer.com/profile/123456"}}
        )
        await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert len(bot.salvos_usuario[-1]["integration_links"]) == 1

"""F3-5b, endurecimento do PR 2 — testes que fecham os sobreviventes da mutação de 2816fc6a, 513de49f e 9d96ebd4.

Cada teste mata um mutante que passava nos testes de ``test_f3_5b_endurecimento``: o contrato já valia, só não estava
fixado. Os comentários dizem o que o mutante fazia. Referência: KI-42 (docs/known-issues.md).
"""

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empiremuse.panel.services.general import VoiceStatusForm
from empiremuse.rules.errors import NAME_INVALID, STATUS_CHARS, URL_TOO_LONG, RuleError
from empiremuse.rules.integrations import save_external
from empiremuse.rules.limits import ITG_TITLE_MAX, ITG_URL_MAX
from empiremuse.rules.settings import validate_voice_status
from empiremuse.utils.music import interactions
from empiremuse.utils.music.interactions import FavModalAdd, ViewMode
from tests.helpers_f3_5b import adicionar_link_do_servidor, importar_no_bot
from tests.helpers_modais import URL_BASE, ModalBot, ModalInteraction, adicionar_integracao, modal_view
from tests.test_f3_5b_endurecimento import CANAL_YOUTUBE, PERFIL_DEEZER, PERFIL_SPOTIFY, BotEspiao

URL = f"{URL_BASE}/a"
PERFIL_DEEZER_SALVO = "https://www.deezer.com/profile/123456"


@pytest.fixture(autouse=True)
def _sem_idle_embed(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    monkeypatch.setattr(interactions, "process_idle_embed", nada)


def url_com_tamanho(tamanho, base="https://exemplo.invalid/"):
    """URL válida com exatamente ``tamanho`` caracteres."""
    return base + "x" * (tamanho - len(base))


# ============================================================================ A-2 — mensagens de controle e formatação


class TestMensagensDeControle:
    def test_status_com_controle_e_sem_placeholder_acusa_o_controle(self):
        """O controle vale antes do placeholder (mutante: a ordem das duas checagens trocada)."""
        erro = validate_voice_status("sem nenhum placeholder\x00")
        assert isinstance(erro, RuleError) and erro.code == STATUS_CHARS

    def test_painel_diz_que_o_status_nao_pode_ter_controle(self):
        resultado = VoiceStatusForm().parse(
            SimpleNamespace(), {"voice_channel_status": ""}, {"voice_channel_status": ["{track.title}\x00"]}
        )
        mensagem = resultado.errors["voice_channel_status"]
        assert "controle" in mensagem and "placeholder" not in mensagem.lower()

    @pytest.mark.asyncio
    async def test_modal_do_servidor_diz_que_a_descricao_nao_pode_ter_controle(self):
        inter = await adicionar_link_do_servidor(ModalBot(), "Link", URL, "ab\x00cd")
        assert "controle" in inter.texto

    @pytest.mark.asyncio
    async def test_importador_diz_que_a_descricao_nao_pode_ter_controle(self):
        _, texto = await importar_no_bot(ViewMode.guild_fav_manager, {"Link": {"url": URL, "description": "ab\x00cd"}})
        assert "controle" in texto


# ============================================================================ I-3 e I-6 — dados externos


class TestSaveExternal:
    def test_url_ate_200_vale_e_201_nao(self):
        assert ITG_URL_MAX == 200
        aceito = save_external({}, "Ana", url_com_tamanho(200), None, limit=0)
        assert not isinstance(aceito, RuleError) and aceito.url == url_com_tamanho(200)
        recusado = save_external({}, "Ana", url_com_tamanho(201), None, limit=0)
        assert isinstance(recusado, RuleError) and (recusado.code, recusado.limit) == (URL_TOO_LONG, 200)

    def test_titulo_e_cortado_em_90(self):
        assert ITG_TITLE_MAX == 90
        salvo = save_external({}, "t" * 100, URL, None, limit=0)
        assert not isinstance(salvo, RuleError) and salvo.name == "t" * 90
        assert save_external({}, "t" * 90, URL, None, limit=0).name == "t" * 90

    def test_titulo_de_um_caractere_vale_e_vazio_nao(self):
        assert save_external({}, "A", URL, None, limit=0).name == "A"
        for vazio in ("", "   ", "\u200b", None):
            erro = save_external({}, vazio, URL, None, limit=0)
            assert isinstance(erro, RuleError) and erro.code == NAME_INVALID


class TestModalDeIntegracao:
    @pytest.mark.asyncio
    async def test_dado_externo_invalido_nao_diz_que_falta_espaco(self):
        bot = BotEspiao(deezer={"link": "javascript:alert(1)"})
        inter = await adicionar_integracao(bot, url=PERFIL_DEEZER)
        assert bot.salvos_usuario == [] and "serviço" in inter.texto and "espaço" not in inter.texto

    @pytest.mark.asyncio
    async def test_falha_ao_gravar_nao_altera_os_dados_em_memoria(self):
        """O modal trabalha numa cópia: se o banco falha, o que o bot guarda em memória continua como estava."""

        class BotQueFalha(BotEspiao):
            async def update_global_data(self, id_, data, *, db_name):
                raise RuntimeError("banco fora do ar")

        bot = BotQueFalha(integration_links={"Outra": {"url": URL}})
        antes = copy.deepcopy(bot.user_data)
        try:
            await adicionar_integracao(bot, url=PERFIL_DEEZER)
        except RuntimeError:
            pass
        assert bot.user_data == antes

    @pytest.mark.asyncio
    async def test_o_log_da_tela_diz_o_que_foi_adicionado(self):
        bot = BotEspiao()
        view = modal_view(bot, ViewMode.integrations_manager)
        await FavModalAdd(None, None, view).callback(ModalInteraction(user_integration_url=PERFIL_DEEZER))
        assert "【DZ】: Ana" in view.log and PERFIL_DEEZER_SALVO in view.log


class TestConsultasExternas:
    @pytest.mark.asyncio
    async def test_spotify_indisponivel_recusa_sem_consultar(self):
        bot = BotEspiao()
        bot.spotify = None
        inter = await adicionar_integracao(bot, url=PERFIL_SPOTIFY)
        assert "suporte ao spotify" in inter.texto and bot.salvos_usuario == [] and bot.consultas == []

    @pytest.mark.asyncio
    async def test_link_do_spotify_que_nao_e_de_usuario_recusa_sem_consultar(self):
        bot = BotEspiao()
        inter = await adicionar_integracao(bot, url="https://open.spotify.com/playlist/xyz")
        assert "perfil de usuário do spotify" in inter.texto and bot.consultas == [] and bot.salvos_usuario == []

    @pytest.mark.asyncio
    async def test_link_do_deezer_que_nao_e_de_perfil_recusa_sem_consultar(self):
        bot = BotEspiao()
        inter = await adicionar_integracao(bot, url="https://www.deezer.com/br/playlist/99")
        assert "perfil de usuário do deezer" in inter.texto and bot.consultas == [] and bot.salvos_usuario == []

    @pytest.mark.asyncio
    async def test_spotify_sem_resultado(self):
        bot = BotEspiao()
        bot.spotify = SimpleNamespace(get_user_info=AsyncMock(return_value=None))
        inter = await adicionar_integracao(bot, url=PERFIL_SPOTIFY)
        assert "não possui playlists públicas" in inter.texto and bot.salvos_usuario == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("url", "nota"),
        [(CANAL_YOUTUBE, True), ("https://soundcloud.com/artista", False)],
        ids=["youtube", "soundcloud"],
    )
    async def test_ytdlp_sem_informacao_diz_que_nao_existe(self, url, nota):
        bot = BotEspiao()
        bot.pool.ytdl.extract_info = lambda *args, **kwargs: None
        inter = await adicionar_integracao(bot, url=url)
        assert "não existe" in inter.texto and bot.salvos_usuario == []
        assert ("@ytchannel" in inter.texto) is nota

    @pytest.mark.asyncio
    async def test_ytdlp_sem_playlists_publicas(self):
        bot = BotEspiao(youtube={"entries": []})
        inter = await adicionar_integracao(bot, url=CANAL_YOUTUBE)
        assert "não possui playlists públicas" in inter.texto and bot.salvos_usuario == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("url", "base"),
        [
            (CANAL_YOUTUBE, f"{CANAL_YOUTUBE}/playlists"),
            ("https://soundcloud.com/artista", "https://soundcloud.com/artista/sets"),
        ],
        ids=["youtube", "soundcloud"],
    )
    async def test_ytdlp_consulta_a_pagina_de_playlists_do_perfil(self, url, base):
        bot = BotEspiao()
        await adicionar_integracao(bot, url=url)
        assert bot.consultas == [("ytdl", base)]


# ============================================================================ I-3 — o mesmo perfil, por fonte e id


class TestPerfilJaSalvo:
    @pytest.mark.parametrize(
        ("url", "mesmo", "outro"),
        [
            (
                "https://open.spotify.com/user/abc123",
                "https://open.spotify.com/user/abc123?si=x",
                "https://open.spotify.com/user/zzz",
            ),
            (
                "https://www.deezer.com/br/profile/123456",
                "https://www.deezer.com/profile/123456",
                "https://www.deezer.com/profile/999",
            ),
            (
                "https://www.youtube.com/@Canal",
                "https://www.youtube.com/@canal/playlists",
                "https://www.youtube.com/@outro",
            ),
            ("https://soundcloud.com/Artista", "https://soundcloud.com/artista/sets", "https://soundcloud.com/outra"),
        ],
        ids=["spotify", "deezer", "youtube", "soundcloud"],
    )
    def test_mesmo_perfil_sem_diferenciar_forma_nem_caixa_e_perfil_diferente_nao(self, url, mesmo, outro):
        chave = interactions._profile_key(url)
        assert chave is not None and chave == interactions._profile_key(mesmo)
        assert chave != interactions._profile_key(outro)
        assert interactions._profile_saved({"Nome": {"url": mesmo}}, url) is True
        assert interactions._profile_saved({"Nome": {"url": outro}}, url) is False

    def test_a_fonte_faz_parte_da_chave(self):
        """Um usuário do Spotify de id ``123456`` não é o perfil ``123456`` do Deezer."""
        assert interactions._profile_key("https://open.spotify.com/user/123456") != interactions._profile_key(
            "https://www.deezer.com/profile/123456"
        )

    def test_entrada_gravada_como_texto_simples_tambem_conta(self):
        """Dados antigos guardam só a URL (sem objeto): continuam valendo para saber se o perfil já está salvo."""
        assert interactions._profile_saved({"Nome": PERFIL_DEEZER_SALVO}, PERFIL_DEEZER) is True

    def test_entradas_sem_perfil_reconhecivel_nunca_casam_com_nada(self):
        entradas = {"Um": {"url": "https://exemplo.invalid/x"}, "Dois": {"sem_url": 1}, "Tres": 5}
        assert interactions._profile_saved(entradas, "https://exemplo.invalid/y") is False
        assert interactions._profile_saved({}, PERFIL_DEEZER) is False
        assert interactions._profile_key(None) is None and interactions._profile_key(5) is None

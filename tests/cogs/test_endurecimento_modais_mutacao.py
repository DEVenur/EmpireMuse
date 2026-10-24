"""F3-5b, endurecimento do PR 2 — testes que fecham os sobreviventes da mutação de 2816fc6a, 513de49f e 9d96ebd4.

Cada teste mata um mutante que passava nos testes de ``test_f3_5b_endurecimento``: o contrato já valia, só não estava
fixado. Os comentários dizem o que o mutante fazia. Referência: KI-42 (docs/known-issues.md).
"""

import pytest

from empiremuse.rules.errors import NAME_INVALID, RuleError
from empiremuse.rules.integrations import save_external
from empiremuse.utils.music import interactions
from empiremuse.utils.music.interactions import ViewMode
from tests.support.drivers_de_regras import adicionar_link_do_servidor, importar_no_bot
from tests.support.modais import URL_BASE, ModalBot, adicionar_integracao, trocar_process_idle_embed
from tests.cogs.test_endurecimento_modais import CANAL_YOUTUBE, PERFIL_DEEZER, PERFIL_SPOTIFY, BotEspiao

URL = f"{URL_BASE}/a"


@pytest.fixture(autouse=True)
def _sem_idle_embed(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    trocar_process_idle_embed(monkeypatch, nada)


# ============================================================================ A-2 — mensagens de controle e formatação


class TestMensagensDeControle:
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
            ("https://soundcloud.com/Artista", "https://soundcloud.com/artista/sets", "https://soundcloud.com/outra"),
        ],
        ids=["spotify", "soundcloud"],
    )
    def test_mesmo_perfil_sem_diferenciar_forma_nem_caixa_e_perfil_diferente_nao(self, url, mesmo, outro):
        chave = interactions._profile_key(url)
        assert chave is not None and chave == interactions._profile_key(mesmo)
        assert chave != interactions._profile_key(outro)
        assert interactions._profile_saved({"Nome": {"url": mesmo}}, url) is True
        assert interactions._profile_saved({"Nome": {"url": outro}}, url) is False

    def test_entradas_sem_perfil_reconhecivel_nunca_casam_com_nada(self):
        entradas = {"Um": {"url": "https://exemplo.invalid/x"}, "Dois": {"sem_url": 1}, "Tres": 5}
        assert interactions._profile_saved(entradas, "https://exemplo.invalid/y") is False
        assert interactions._profile_saved({}, PERFIL_DEEZER) is False
        assert interactions._profile_key(None) is None and interactions._profile_key(5) is None

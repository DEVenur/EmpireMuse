"""F3-5b, etapas 2 a 6 — testes que fecham os sobreviventes da mutação das regras de ``empiremuse.rules``.

Cada teste mata um mutante que passava nos testes das etapas: o contrato já valia, só não estava fixado. Os
comentários dizem o que o mutante fazia. Referência: KI-42 (docs/known-issues.md).
"""

import pytest

from empiremuse.rules.entries import save_entry
from empiremuse.rules.errors import NAME_INVALID, PREFIX_LENGTH, URL_TOO_LONG, RuleError
from empiremuse.rules.favorites import name_limit
from empiremuse.rules.guild_links import check_description
from empiremuse.rules.limits import PREFIX_MAX_LENGTH
from empiremuse.rules.settings import check_dj_roles, validate_prefix
from empiremuse.rules.text import clean_track_name
from empiremuse.rules.urls import check_url
from empiremuse.utils.music.user_limits import track_fav_error_text
from tests.support.drivers_de_regras import BotDoPainel, adicionar_link_do_servidor, painel_favoritos
from tests.support.modais import trocar_process_idle_embed, URL_BASE, ModalBot, adicionar_integracao

URL = f"{URL_BASE}/a"
SEM_LINK_VALIDO = "Nenhum link válido"


@pytest.fixture(autouse=True)
def _sem_idle_embed(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    trocar_process_idle_embed(monkeypatch, nada)


def url_com_tamanho(tamanho, base=f"{URL_BASE}/"):
    """URL válida com exatamente ``tamanho`` caracteres."""
    return base + "x" * (tamanho - len(base))


# ============================================================================ nome vindo do título da faixa


class TestNomeDaFaixa:
    def test_limpa_controle_e_formatacao_antes_de_cortar(self):
        """O corte vale para o texto já limpo (D3): 20 letras separadas por invisíveis continuam 20 (mutante: cortar
        o texto bruto e só então limpar, que devolveria 13)."""
        titulo = "a\u200b" * 20
        assert clean_track_name(titulo, 2, 25) == "a" * 20


# ============================================================================ URL pura


class TestUrlPura:
    class ComTexto:
        """Objeto não textual cujo ``str()`` seria uma URL válida."""

        def __str__(self):
            return URL

        def __repr__(self):  # id estável no parametrize (sem o endereço de memória do objeto)
            return "ComTexto()"

    def test_url_longa_tem_codigo_proprio_e_traz_o_limite(self):
        erro = check_url(url_com_tamanho(201), 200)
        assert isinstance(erro, RuleError)
        assert (erro.code, erro.limit) == (URL_TOO_LONG, 200)
        assert erro.value == url_com_tamanho(201)


# ============================================================================ salvar entrada e mesclar importação


class TestOrdemDasEntradas:
    ENTRADAS = {"aa": "1", "bb": "2", "cc": "3"}
    REGRAS = dict(name_min=2, name_max=25, limit=0)

    def test_editar_sem_renomear_mantem_a_posicao(self):
        salvo = save_entry(self.ENTRADAS, "bb", "bb", "9", **self.REGRAS)
        assert list(salvo.items()) == [("aa", "1"), ("bb", "9"), ("cc", "3")]


# ============================================================================ favoritos: teto do nome e faixa tocando


class TestFavoritos:
    @pytest.mark.parametrize(("configurado", "esperado"), [(10, 10), ("12", 12)])
    def test_teto_do_nome_e_o_menor_entre_a_configuracao_e_25(self, configurado, esperado):
        assert name_limit(configurado) == esperado

    def test_mensagem_do_botao_para_nome_curto_nao_fala_de_espaco(self):
        texto = track_fav_error_text(RuleError(NAME_INVALID, value="x"))
        assert "nome" in texto and "espaço" not in texto and "Limite" not in texto


# ============================================================================ descrição do link do servidor


class TestDescricaoDoLink:
    @pytest.mark.parametrize("vazia", ["", "\t "])
    def test_vazia_e_valida(self, vazia):
        assert check_description(vazia) == ""

    @pytest.mark.parametrize(("descricao", "gravada"), [("", ""), (" " + "a" * 100 + " ", "a" * 100)])
    @pytest.mark.asyncio
    async def test_modal_do_servidor_aceita_vazia_ou_de_3_a_100_aparada(self, descricao, gravada):
        bot = ModalBot()
        await adicionar_link_do_servidor(bot, "Link", URL, descricao)
        assert bot.salvos_servidor[-1]["player_controller"]["fav_links"]["Link"]["description"] == gravada


# ============================================================================ limites de URL nos modais


class TestLimiteDeUrlNosModais:
    """O ``max_length`` do campo é do Discord; o callback aplica o mesmo limite sozinho (defesa em profundidade)."""

    @pytest.mark.asyncio
    async def test_integracao_recusa_201(self):
        url = url_com_tamanho(201, base="https://www.deezer.com/br/profile/123456?")
        bot = ModalBot()
        recusado = await adicionar_integracao(bot, url)
        assert SEM_LINK_VALIDO in recusado.texto and bot.salvos_usuario == []


# ============================================================================ mensagens que dizem o número ao usuário


class TestMensagensComNumeros:
    @pytest.mark.asyncio
    async def test_painel_diz_que_o_nome_ja_existe_quando_so_a_caixa_difere(self):
        resultado = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {"Rock": URL}, nome="rock", url=URL)
        assert "já" in resultado.errors["nome"].lower()


# ============================================================================ prefixo


class TestPrefixo:
    def test_acima_de_cinco_tem_codigo_de_tamanho_e_traz_o_limite(self):
        erro = validate_prefix("a" * (PREFIX_MAX_LENGTH + 1))
        assert isinstance(erro, RuleError) and (erro.code, erro.limit) == (PREFIX_LENGTH, PREFIX_MAX_LENGTH)


# ============================================================================ cargos de DJ


class TestCargosDeDj:
    def test_ids_numericos_que_existem_passam(self):
        assert check_dj_roles(["1", "9" * 20], {"1", "9" * 20}) is None

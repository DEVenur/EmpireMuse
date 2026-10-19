"""F3-5b, etapas 2 a 6 — testes que fecham os sobreviventes da mutação das regras de ``empiremuse.rules``.

Cada teste mata um mutante que passava nos testes das etapas: o contrato já valia, só não estava fixado. Os
comentários dizem o que o mutante fazia. Referência: KI-42 (docs/known-issues.md).
"""

import re
from types import SimpleNamespace

import pytest

from empiremuse.panel.services.base import FormContext
from empiremuse.panel.services.general import PrefixForm
from empiremuse.panel.services.player import DjForm
from empiremuse.rules.entries import merge_import, save_entry
from empiremuse.rules.errors import (
    DESCRIPTION_INVALID,
    NAME_INVALID,
    PREFIX_CHARS,
    PREFIX_EMPTY,
    PREFIX_LENGTH,
    QUOTA_FULL,
    ROLE_INVALID,
    URL_INVALID,
    URL_TOO_LONG,
    RuleError,
)
from empiremuse.rules.favorites import name_limit, save_track
from empiremuse.rules.guild_links import check_description, import_entry
from empiremuse.rules.limits import MAX_DJ_ROLES, PREFIX_MAX_LENGTH, VOICE_STATUS_MAX_LENGTH
from empiremuse.rules.settings import check_dj_roles, validate_prefix
from empiremuse.rules.text import clean_track_name
from empiremuse.rules.urls import check_url
from empiremuse.utils.music import interactions
from empiremuse.utils.music.interactions import ViewMode
from empiremuse.utils.music.user_limits import track_fav_error_text
from tests.helpers_f3_5b import (
    BotDeComandos,
    BotDoPainel,
    GuildaFalsa,
    adicionar_link_do_servidor,
    cargos,
    painel_favoritos,
    status_no_comando,
)
from tests.helpers_modais import (
    URL_BASE,
    ModalBot,
    adicionar_favorito,
    adicionar_integracao,
    arquivo_com,
    favs_cheios,
    importar,
)

URL = f"{URL_BASE}/a"
SEM_LINK_VALIDO = "Nenhum link válido"


@pytest.fixture(autouse=True)
def _sem_idle_embed(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    monkeypatch.setattr(interactions, "process_idle_embed", nada)


def url_com_tamanho(tamanho, base=f"{URL_BASE}/"):
    """URL válida com exatamente ``tamanho`` caracteres."""
    return base + "x" * (tamanho - len(base))


# ============================================================================ nome vindo do título da faixa


class TestNomeDaFaixa:
    def test_apara_antes_de_cortar(self):
        """Os espaços das pontas não gastam o teto de 25 caracteres (mutante: cortar sem aparar antes)."""
        assert clean_track_name("     " + "a" * 30, 2, 25) == "a" * 25

    def test_limpa_controle_e_formatacao_antes_de_cortar(self):
        """O corte vale para o texto já limpo (D3): 20 letras separadas por invisíveis continuam 20 (mutante: cortar
        o texto bruto e só então limpar, que devolveria 13)."""
        titulo = "a\u200b" * 20
        assert clean_track_name(titulo, 2, 25) == "a" * 20

    def test_corta_em_25_e_apara_de_novo(self):
        assert clean_track_name("a" * 24 + " " + "b" * 10, 2, 25) == "a" * 24

    @pytest.mark.parametrize("valor", [None, 12345, b"abcde", ["abc"], {"nome": "abc"}], ids=repr)
    def test_so_aceita_texto(self, valor):
        """Mutante: ``str(valor)`` virava nome (``12345`` passaria como favorito)."""
        assert clean_track_name(valor, 2, 25) is None


# ============================================================================ URL pura


class TestUrlPura:
    class ComTexto:
        """Objeto não textual cujo ``str()`` seria uma URL válida."""

        def __str__(self):
            return URL

        def __repr__(self):  # id estável no parametrize (sem o endereço de memória do objeto)
            return "ComTexto()"

    @pytest.mark.parametrize("valor", [ComTexto(), 12345, None, b"https://exemplo.invalid/a"], ids=repr)
    def test_recusa_o_que_nao_e_texto_mesmo_que_o_str_seja_uma_url(self, valor):
        erro = check_url(valor, 200)
        assert isinstance(erro, RuleError) and erro.code == URL_INVALID

    def test_url_longa_tem_codigo_proprio_e_traz_o_limite(self):
        erro = check_url(url_com_tamanho(201), 200)
        assert isinstance(erro, RuleError)
        assert (erro.code, erro.limit) == (URL_TOO_LONG, 200)
        assert erro.value == url_com_tamanho(201)

    def test_url_longa_e_url_invalida_nao_se_confundem(self):
        erro = check_url("veja " + url_com_tamanho(300), 200)
        assert isinstance(erro, RuleError) and erro.code == URL_TOO_LONG  # o tamanho vale antes do formato
        assert check_url("veja " + URL, 200).code == URL_INVALID

    def test_desembrulha_e_apara_o_que_sobra_dentro_dos_sinais(self):
        """``<  url  >`` vale como ``url``: depois de tirar o ``<``/``>`` as pontas são aparadas de novo."""
        assert check_url(f"<  {URL}  >", 200) == URL
        assert check_url(f"  < {URL} >  ", 200) == URL


# ============================================================================ salvar entrada e mesclar importação


class TestOrdemDasEntradas:
    ENTRADAS = {"aa": "1", "bb": "2", "cc": "3"}
    REGRAS = dict(name_min=2, name_max=25, limit=0)

    def test_renomear_leva_a_entrada_para_o_fim(self):
        salvo = save_entry(self.ENTRADAS, "aa", "zz", "9", **self.REGRAS)
        assert list(salvo.items()) == [("bb", "2"), ("cc", "3"), ("zz", "9")]

    def test_editar_sem_renomear_mantem_a_posicao(self):
        salvo = save_entry(self.ENTRADAS, "bb", "bb", "9", **self.REGRAS)
        assert list(salvo.items()) == [("aa", "1"), ("bb", "9"), ("cc", "3")]

    def test_importar_deixa_o_que_ja_existia_antes_do_que_veio_do_arquivo(self):
        mesclado = merge_import({"aa": "1", "bb": "2"}, {"cc": "3", "dd": "4"}, 0)
        assert list(mesclado) == ["aa", "bb", "cc", "dd"]

    def test_importar_substituindo_leva_o_nome_do_arquivo_para_o_fim(self):
        mesclado = merge_import({"aa": "1", "bb": "2", "cc": "3"}, {"AA": "9"}, 0)
        assert list(mesclado.items()) == [("bb", "2"), ("cc", "3"), ("AA", "9")]


# ============================================================================ favoritos: teto do nome e faixa tocando


class TestFavoritos:
    @pytest.mark.parametrize(("configurado", "esperado"), [(10, 10), (25, 25), (26, 25), (90, 25), ("12", 12)])
    def test_teto_do_nome_e_o_menor_entre_a_configuracao_e_25(self, configurado, esperado):
        assert name_limit(configurado) == esperado

    def test_favoritar_faixa_sobrescreve_o_de_mesmo_nome_sem_diferenciar_a_caixa(self):
        gravado = save_track({"rock": "https://exemplo.invalid/velho"}, "ROCK", URL, limit=0)
        assert not isinstance(gravado, RuleError)
        assert gravado.entries == {"rock": URL} and gravado.name == "rock"

    def test_favoritar_faixa_com_a_lista_cheia_so_sobrescreve_quando_o_nome_ja_existe(self):
        cheio = {"rock": "https://exemplo.invalid/velho", "pop": "https://exemplo.invalid/pop"}
        assert save_track(cheio, "Rock", URL, limit=2).entries == {**cheio, "rock": URL}
        erro = save_track(cheio, "Jazz", URL, limit=2)
        assert isinstance(erro, RuleError) and erro.code == QUOTA_FULL

    @pytest.mark.asyncio
    async def test_modal_do_bot_usa_o_teto_do_nome_da_configuracao(self):
        """Mutante: o modal usava sempre 25 e ignorava ``USER_FAV_MAX_NAME_LENGTH`` abaixo disso."""
        bot = ModalBot(nome_max=10)
        recusado = await adicionar_favorito(bot, nome="a" * 11)
        assert bot.salvos_usuario == [] and "10" in recusado.texto
        await adicionar_favorito(bot, nome="a" * 10)
        assert list(bot.salvos_usuario[-1]["fav_links"]) == ["a" * 10]

    def test_mensagem_do_botao_para_nome_curto_nao_fala_de_espaco(self):
        texto = track_fav_error_text(RuleError(NAME_INVALID, value="x"))
        assert "nome" in texto and "espaço" not in texto and "Limite" not in texto

    @pytest.mark.parametrize("codigo", [URL_INVALID, URL_TOO_LONG])
    def test_mensagem_do_botao_para_link_ruim_cita_o_link_e_os_200_caracteres(self, codigo):
        texto = track_fav_error_text(RuleError(codigo, value="x", limit=200))
        assert "link" in texto and "200" in texto and "espaço" not in texto and "Limite" not in texto

    def test_mensagem_do_botao_para_lista_cheia_cita_o_limite(self):
        texto = track_fav_error_text(RuleError(QUOTA_FULL, limit=7))
        assert "espaço" in texto and "Limite atual: 7" in texto


# ============================================================================ descrição do link do servidor


class TestDescricaoDoLink:
    @pytest.mark.parametrize("valor", [12345, 123, None, b"abcd", ["abcd"]], ids=repr)
    def test_so_aceita_texto(self, valor):
        """Mutante: ``str(valor)`` com 3 a 50 caracteres virava descrição."""
        erro = check_description(valor)
        assert isinstance(erro, RuleError) and erro.code == DESCRIPTION_INVALID

    @pytest.mark.parametrize("vazia", ["", "   ", "\t "])
    def test_vazia_e_valida(self, vazia):
        assert check_description(vazia) == ""

    def test_item_do_arquivo_com_descricao_vazia_vale(self):
        assert import_entry({"url": URL, "description": ""}) == {"url": URL, "description": ""}
        assert import_entry({"url": URL, "description": "   "}) == {"url": URL, "description": ""}

    @pytest.mark.parametrize("descricao", ["a", "ab", "a" * 51])
    @pytest.mark.asyncio
    async def test_modal_do_servidor_recusa_descricao_fora_de_3_a_50(self, descricao):
        """Mutante: o modal só aparava a descrição e deixava passar 1, 2 ou 51 caracteres."""
        bot = ModalBot()
        await adicionar_link_do_servidor(bot, "Link", URL, descricao)
        assert bot.salvos_servidor == []

    @pytest.mark.parametrize(("descricao", "gravada"), [("", ""), ("abc", "abc"), (" " + "a" * 50 + " ", "a" * 50)])
    @pytest.mark.asyncio
    async def test_modal_do_servidor_aceita_vazia_ou_de_3_a_50_aparada(self, descricao, gravada):
        bot = ModalBot()
        await adicionar_link_do_servidor(bot, "Link", URL, descricao)
        assert bot.salvos_servidor[-1]["player_controller"]["fav_links"]["Link"]["description"] == gravada


# ============================================================================ limites de URL nos modais


class TestLimiteDeUrlNosModais:
    """O ``max_length`` do campo é do Discord; o callback aplica o mesmo limite sozinho (defesa em profundidade)."""

    @pytest.mark.asyncio
    async def test_favorito_aceita_200_e_recusa_201(self):
        bot = ModalBot()
        aceito = await adicionar_favorito(bot, url=url_com_tamanho(200))
        assert SEM_LINK_VALIDO not in aceito.texto and len(bot.salvos_usuario) == 1
        recusado = await adicionar_favorito(bot, nome="outro", url=url_com_tamanho(201))
        assert SEM_LINK_VALIDO in recusado.texto and len(bot.salvos_usuario) == 1

    @pytest.mark.asyncio
    async def test_link_do_servidor_aceita_250_e_recusa_251(self):
        bot = ModalBot()
        await adicionar_link_do_servidor(bot, "Link", url_com_tamanho(250))
        assert len(bot.salvos_servidor) == 1
        recusado = await adicionar_link_do_servidor(bot, "Outro", url_com_tamanho(251))
        assert SEM_LINK_VALIDO in recusado.texto and len(bot.salvos_servidor) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tamanho", [160, 200])
    async def test_integracao_aceita_ate_200(self, tamanho):
        url = url_com_tamanho(tamanho, base="https://www.deezer.com/br/profile/123456?")
        aceito = await adicionar_integracao(ModalBot(), url)
        assert SEM_LINK_VALIDO not in aceito.texto

    @pytest.mark.asyncio
    async def test_integracao_recusa_201(self):
        url = url_com_tamanho(201, base="https://www.deezer.com/br/profile/123456?")
        bot = ModalBot()
        recusado = await adicionar_integracao(bot, url)
        assert SEM_LINK_VALIDO in recusado.texto and bot.salvos_usuario == []


# ============================================================================ mensagens que dizem o número ao usuário


class TestMensagensComNumeros:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", [ViewMode.fav_manager, ViewMode.guild_fav_manager])
    async def test_url_longa_no_arquivo_cita_o_limite_e_nao_diz_que_o_link_e_invalido(self, modo):
        bot = ModalBot(url_max=90)
        limite = 90 if modo == ViewMode.fav_manager else 250
        url = "https://exemplo.invalid/" + "a" * (limite + 20 - len("https://exemplo.invalid/"))
        inter = await importar(bot, modo, arquivo_com(modo, "nome", url))
        assert bot.salvos_usuario == [] and bot.salvos_servidor == []
        assert "ultrapassa" in inter.texto and str(limite) in inter.texto
        assert "link inválido" not in inter.texto

    @pytest.mark.asyncio
    async def test_cota_estourada_diz_quantos_itens_faltam(self):
        """3 salvos + 4 no arquivo com limite 5: o usuário precisa de 2 vagas (mutante: contava 7)."""
        bot = ModalBot(favs=5, fav_links=favs_cheios(3))
        novos = {f"novo{i}": f"{URL_BASE}/n{i}" for i in range(4)}
        inter = await importar(bot, ViewMode.fav_manager, novos)
        assert bot.salvos_usuario == []
        assert re.search(r"precisa de:\s*2\b", inter.texto), inter.texto
        assert "Limite atual: 5" in inter.texto

    @pytest.mark.asyncio
    async def test_painel_diz_que_o_nome_ja_existe_quando_so_a_caixa_difere(self):
        resultado = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {"Rock": URL}, nome="rock", url=URL)
        assert "já" in resultado.errors["nome"].lower()

    @pytest.mark.asyncio
    async def test_status_de_voz_longo_diz_o_maximo_e_sem_placeholder_pede_um(self):
        longo = "x" * (VOICE_STATUS_MAX_LENGTH + 1)
        gravado, texto = await status_no_comando(BotDeComandos(), longo)
        assert gravado is None and str(VOICE_STATUS_MAX_LENGTH) in texto
        gravado, texto = await status_no_comando(BotDeComandos(), "sem nenhum placeholder")
        assert gravado is None and "placeholder" in texto and str(VOICE_STATUS_MAX_LENGTH) not in texto


# ============================================================================ prefixo


class TestPrefixo:
    @pytest.mark.parametrize("valor", [None, 123, b">>", [">>"]], ids=repr)
    def test_so_aceita_texto(self, valor):
        """Mutante: sem o ``isinstance``, um valor que não é texto levantava ``AttributeError`` em vez de recusar."""
        erro = validate_prefix(valor)
        assert isinstance(erro, RuleError) and erro.code == PREFIX_EMPTY

    @pytest.mark.parametrize("valor", ["a b", "a\tb", "a\u200bb", "a\x07b"], ids=repr)
    def test_espaco_interno_e_invisivel_tem_codigo_de_caracteres(self, valor):
        erro = validate_prefix(valor)
        assert isinstance(erro, RuleError) and erro.code == PREFIX_CHARS

    def test_acima_de_cinco_tem_codigo_de_tamanho_e_traz_o_limite(self):
        erro = validate_prefix("a" * (PREFIX_MAX_LENGTH + 1))
        assert isinstance(erro, RuleError) and (erro.code, erro.limit) == (PREFIX_LENGTH, PREFIX_MAX_LENGTH)

    def test_o_tamanho_vale_antes_dos_caracteres(self):
        assert validate_prefix("a b c d e f").code == PREFIX_LENGTH

    def test_painel_diz_o_motivo_certo(self):
        def erro_do_painel(texto):
            return PrefixForm().parse(SimpleNamespace(), {"prefix": ""}, {"prefix": [texto]}).errors["prefix"]

        assert "espaço" in erro_do_painel("a b") and str(PREFIX_MAX_LENGTH) not in erro_do_painel("a b")
        assert str(PREFIX_MAX_LENGTH) in erro_do_painel("a" * (PREFIX_MAX_LENGTH + 1))


# ============================================================================ cargos de DJ


class TestCargosDeDj:
    @pytest.mark.parametrize("id_", ["abc", "123abc", "-1", "1.5", "1" * 21, "１２３", ""], ids=repr)
    def test_id_que_nao_e_numero_de_ate_20_digitos_e_invalido_mesmo_que_exista_na_lista(self, id_):
        """Mutantes: a checagem do formato sumia ou virava ``match`` (aceitaria o prefixo numérico)."""
        erro = check_dj_roles([id_], {id_})
        assert isinstance(erro, RuleError) and erro.code == ROLE_INVALID

    def test_ids_numericos_que_existem_passam(self):
        assert check_dj_roles(["1", "9" * 20], {"1", "9" * 20}) is None

    def test_painel_diz_o_motivo_de_cada_recusa(self):
        existentes = cargos(MAX_DJ_ROLES + 1)
        guilda = GuildaFalsa(existentes)
        ctx = FormContext(pool=SimpleNamespace(), bot=SimpleNamespace(), guild=guilda, guild_id=guilda.id, user_id="1")
        ids = [str(cargo.id) for cargo in existentes]

        def erro(enviado):
            return DjForm().parse(ctx, {"djroles": []}, {"djroles": enviado}).errors["djroles"]

        no_limite, repetido, inexistente = erro(ids), erro([ids[0], ids[0]]), erro(["999999"])
        assert str(MAX_DJ_ROLES) in no_limite
        assert "repetidos" in repetido
        assert "existem" in inexistente
        assert len({no_limite, repetido, inexistente}) == 3

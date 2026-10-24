"""F3-6b, etapa 3 — achado do AppSec: as URLs de embed da skin passam pela régua de ``rules/urls.py``.

Campos: ``footer.icon_url``, ``author.url``, ``author.icon_url``, ``image.url`` e ``thumbnail.url``. Vale ``""`` (o editor grava
campo vazio), um placeholder de URL que o ``skin_converter`` substitui (``{guild.icon}`` e companhia, o texto inteiro) ou uma URL
que passa no ``check_url`` (com os placeholders trocados por texto neutro, para ``https://cdn/{guild.id}.png``). Na migração do
texto legado, URL inválida recusa a skin (fica como texto e a padrão assume), como qualquer outro campo.
"""

import ast
import logging

import pytest

from tests.support.formatos_reais import SERVIDOR
from tests.support.chave_de_corte import log_sem_o_conteudo, registrou
from tests.support.leitor_legado import SEGREDO
from tests.support.serializacao_nucleo import falha
from tests.support.skins import carregar_helper, com_embed, valida
from tests.persistence.test_skin_leitura import documento, rodar
from tests.persistence.test_formato_skin import skin_realista, texto_legado
from tests.support.raiz import RAIZ

pytestmark = pytest.mark.critical

PACOTE = RAIZ / "empiremuse"

CAMPOS = {
    "image.url": (lambda t: com_embed(image={"url": t}), "embeds[0].image.url"),
    "thumbnail.url": (lambda t: com_embed(thumbnail={"url": t}), "embeds[0].thumbnail.url"),
    "footer.icon_url": (lambda t: com_embed(footer={"text": "t", "icon_url": t}), "embeds[0].footer.icon_url"),
    "author.url": (lambda t: com_embed(author={"name": "a", "url": t}), "embeds[0].author.url"),
    "author.icon_url": (lambda t: com_embed(author={"name": "a", "icon_url": t}), "embeds[0].author.icon_url"),
}
PLACEHOLDERS_DE_URL = ["{track.thumb}", "{track.url}", "{playlist.url}", "{requester.avatar}", "{guild.icon}"]
VALIDAS = [
    "",
    "https://exemplo.invalid/a.png",
    "http://exemplo.invalid/a.png?x=1&y=2",
    "https://cdn.exemplo.invalid/{guild.id}/icone.png",
    "https://exemplo.invalid/{track.thumb}",
    *PLACEHOLDERS_DE_URL,
]


class TestURLsDeEmbed:
    @pytest.mark.parametrize("campo", list(sorted(CAMPOS))[:2])
    @pytest.mark.parametrize("url", list(VALIDAS)[:2], ids=lambda v: v[:30] or "vazia")
    def test_url_valida_passa_sem_mudar(self, campo, url):
        monta, _ = CAMPOS[campo]
        skin = monta(url)
        assert valida(skin) == skin

    @pytest.mark.parametrize("campo", list(sorted(CAMPOS))[:2])
    def test_o_valor_nunca_vai_no_erro(self, campo):
        monta, _ = CAMPOS[campo]
        erro = falha(valida, monta(f"{SEGREDO} nao e url"))
        assert SEGREDO not in str(erro) and SEGREDO not in repr(erro) and SEGREDO not in erro.path

    def test_a_regua_so_vale_nos_campos_de_url_nao_nos_textos(self):
        skin = com_embed(title="https://nao-e-url", description="texto solto {guild.icon}", footer={"text": "x"})
        assert valida(skin) == skin

    def test_o_link_do_embed_nao_e_campo_conhecido_e_continua_descartado(self):
        assert valida(com_embed(url="javascript:alert(1)", description="d")) == com_embed(description="d")


class TestSkinsConhecidasContinuamValendo:
    def test_a_skin_realista_do_editor_passa(self):
        assert valida(skin_realista()) == skin_realista()

    def test_as_skins_embutidas_sao_codigo_python_e_nao_dicionarios(self):
        """As 15 skins de ``utils/music/skins/`` são módulos com ``load(player)``: não passam por ``validate_skin``."""
        modulos = [
            m
            for pasta in ("normal_player", "static_player")
            for m in (PACOTE / "utils/music/skins" / pasta).glob("*.py")
        ]
        assert len(modulos) == 15
        for modulo in modulos:
            funcoes = {
                n.name for n in ast.parse(modulo.read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef)
            }
            assert "load" in funcoes, modulo.name


class TestPlaceholdersDeURLSaoOsQueOConversorSubstitui:
    def test_cada_placeholder_de_url_e_substituido_pelo_skin_converter(self):
        arvore = ast.parse((PACOTE / "utils/music/skin_utils.py").read_text(encoding="utf-8"))
        substituidos = {
            no.args[0].value
            for no in ast.walk(arvore)
            if isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr == "replace"
            and no.args
            and isinstance(no.args[0], ast.Constant)
            and isinstance(no.args[0].value, str)
        }
        assert set(PLACEHOLDERS_DE_URL) <= substituidos


class TestMigracaoDoTextoLegado:
    @pytest.fixture
    def helper(self):
        return carregar_helper()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("campo", list(sorted(CAMPOS))[:2])
    async def test_url_invalida_recusa_a_skin_que_fica_como_texto(self, helper, caplog, capsys, campo):
        monta, _ = CAMPOS[campo]
        texto = texto_legado(monta("javascript:alert(1)"))
        dados = documento(normais={"Ruim": texto, "Boa": texto_legado(skin_realista())})
        with caplog.at_level(logging.DEBUG):
            await rodar(helper, dados)
        assert dados["custom_skins"]["Ruim"] == texto and dados["custom_skins"]["Boa"] == skin_realista()
        assert registrou(caplog, SERVIDOR, "pattern") and log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    async def test_dicionario_ja_gravado_com_url_invalida_nao_chega_ao_player(self, helper, caplog):
        dados = documento(normais={"Ruim": com_embed(image={"url": "ftp://x"}), "Boa": skin_realista()})
        antes = {k: dict(v) if isinstance(v, dict) else v for k, v in dados.items()}
        with caplog.at_level(logging.DEBUG):
            bot = await rodar(helper, dados)
        assert bot.escritas == [] and dados["custom_skins"]["Ruim"] == antes["custom_skins"]["Ruim"]
        assert registrou(caplog, SERVIDOR, "pattern")

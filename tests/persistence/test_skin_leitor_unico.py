"""F3-6b, etapa 3 (RED) — arquitetura por ``ast``: um helper único lê a skin e os 4 pontos só o chamam.

* ``load_custom_skins`` existe uma vez, no nível do módulo, é corrotina e NÃO mora em ``serialization/`` (usa o bot; o pacote
  é só biblioteca padrão mais ``rules``);
* ``Music.create_player``, ``MusicSettings.change_skin``, ``SkinEditorMenu.load_skin`` e ``SkinEditorMenu.modal_handler`` o chamam
  e deixaram de falar de ``load_legacy``, ``b64decode``, ``b64encode`` e ``pickle``;
* o único módulo do produto (fora do leitor legado) que lê skin com ``load_legacy(..., "skin")`` é o do helper;
* ``serialization/skins.py`` existe, define ``validate_skin`` e só importa biblioteca padrão e o próprio pacote.
"""

import ast
import sys

import pytest

from tests.support.skins import NOME_DO_HELPER, PACOTE, definicoes_do_helper
from tests.persistence.test_chave_de_corte_load_legacy import funcao_do_ponto, kind_da_chamada, nome_chamado

PONTOS_DE_SKIN = [
    ("music_cog/player_lifecycle.py", "PlayerLifecycleMixin.create_player"),
    ("cogs/music_settings.py", "MusicSettings.change_skin"),
    ("utils/music/interactions", "SkinEditorMenu.load_skin"),
    ("utils/music/interactions", "SkinEditorMenu.modal_handler"),
]
PROIBIDOS_NOS_PONTOS = {"load_legacy", "b64decode", "b64encode", "pickle", "_pickle"}


def nomes_usados(no: ast.AST) -> set[str]:
    achados = set()
    for filho in ast.walk(no):
        if isinstance(filho, ast.Name):
            achados.add(filho.id)
        elif isinstance(filho, ast.Attribute):
            achados.add(filho.attr)
    return achados


class TestHelperUnico:
    def test_existe_uma_definicao_no_nivel_do_modulo_e_e_corrotina(self):
        achados = definicoes_do_helper()
        assert len(achados) == 1
        assert isinstance(achados[0][1], ast.AsyncFunctionDef)

    def test_nao_mora_em_serialization(self):
        ((arquivo, _),) = definicoes_do_helper()
        assert "serialization" not in arquivo.relative_to(PACOTE).parts

    def test_assinatura_bot_guild_id_global_data(self):
        ((_, no),) = definicoes_do_helper()
        assert [a.arg for a in no.args.args][:3] == ["bot", "guild_id", "global_data"]

    @pytest.mark.parametrize(("arquivo", "funcao"), PONTOS_DE_SKIN, ids=lambda v: str(v).split("/")[-1])
    def test_cada_ponto_chama_o_helper(self, arquivo, funcao):
        no = funcao_do_ponto(arquivo, funcao)
        chamados = {nome_chamado(c) for c in ast.walk(no) if isinstance(c, ast.Call)}
        assert NOME_DO_HELPER in chamados

    @pytest.mark.parametrize(("arquivo", "funcao"), PONTOS_DE_SKIN, ids=lambda v: str(v).split("/")[-1])
    def test_nenhum_ponto_fala_mais_de_texto_legado_nem_de_pickle(self, arquivo, funcao):
        no = funcao_do_ponto(arquivo, funcao)
        assert not nomes_usados(no) & PROIBIDOS_NOS_PONTOS, sorted(nomes_usados(no) & PROIBIDOS_NOS_PONTOS)

    def test_so_o_modulo_do_helper_le_skin_com_load_legacy(self):
        ((arquivo_do_helper, _),) = definicoes_do_helper()
        leem_skin = set()
        for arquivo in sorted(PACOTE.rglob("*.py")):
            if "__pycache__" in arquivo.parts or arquivo.name == "legacy_pickle.py":
                continue
            for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
                if isinstance(no, ast.Call) and nome_chamado(no) == "load_legacy" and kind_da_chamada(no) == "skin":
                    leem_skin.add(arquivo)
        assert leem_skin == {arquivo_do_helper}


class TestModuloDoEsquema:
    ARQUIVO = PACOTE / "serialization" / "skins.py"

    def test_define_validate_skin(self):
        arvore = ast.parse(self.ARQUIVO.read_text(encoding="utf-8"))
        assert "validate_skin" in {n.name for n in arvore.body if isinstance(n, ast.FunctionDef)}

    def test_so_importa_biblioteca_padrao_e_o_proprio_pacote(self):
        permitidos = set(sys.stdlib_module_names) | {"empiremuse"}
        for no in ast.walk(ast.parse(self.ARQUIVO.read_text(encoding="utf-8"))):
            modulos = []
            if isinstance(no, ast.Import):
                modulos = [a.name for a in no.names]
            elif isinstance(no, ast.ImportFrom) and no.level == 0:
                modulos = [no.module or ""]
            for modulo in modulos:
                raiz = modulo.split(".")[0]
                assert raiz in permitidos, modulo
                if raiz == "empiremuse":
                    assert modulo.startswith(("empiremuse.serialization", "empiremuse.rules")), modulo

    def test_nao_importa_pickle(self):
        for no in ast.walk(ast.parse(self.ARQUIVO.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Import):
                assert not {a.name.split(".")[0] for a in no.names} & {"pickle", "_pickle", "marshal", "shelve"}

"""F3-6b, etapa 0 — teste de arquitetura por ``ast`` do pacote ``empiremuse/serialization/``.

* ``empiremuse/serialization/**`` só importa a biblioteca padrão, ``empiremuse.rules`` e o próprio pacote: sem
  ``disnake``, ``tornado``, ``motor``, ``cachetools`` nem outro módulo do projeto.
* ``pickle`` só pode ser importado em ``empiremuse/serialization/legacy_pickle.py`` (o único leitor do formato antigo).

Os dois testes sobre o código de verdade nasceram ``xfail(strict=True)`` e viram verdes quando a etapa correspondente termina: o de
``serialization`` já passou e o de IMPORT do pickle passa na etapa 5 (a marca saiu no RED da etapa 5, que o deixa vermelho de verdade).
O resto: o varredor, provado com código e pastas sintéticos, e a proibição dos demais formatos binários executáveis.

Conta qualquer ``import``, inclusive dentro de função e de ``if TYPE_CHECKING``, resolve importação relativa e pega
``__import__("x")`` e ``importlib.import_module("x")`` com nome literal; import dinâmico de nome não literal, dentro de
``serialization/``, é apontado (não dá para saber o que carrega).
"""

import ast
from pathlib import Path

import pytest

from tests.test_f3_5b_arquitetura import BIBLIOTECA_PADRAO, importados

PACOTE = Path(__file__).resolve().parents[1] / "empiremuse"
LEGADO = "serialization/legacy_pickle.py"
MODULOS_PICKLE = frozenset({"pickle", "_pickle", "cPickle"})
OUTROS_FORMATOS_EXECUTAVEIS = frozenset({"marshal", "shelve", "dill", "jsonpickle", "cloudpickle"})
PERMITIDOS_NA_SERIALIZACAO = ("empiremuse.rules", "empiremuse.serialization")


def nome_do_modulo(arquivo: Path, raiz: Path) -> str:
    """``raiz/utils/x.py`` -> ``empiremuse.utils.x`` (``__init__`` vira o nome do pacote); ``raiz`` é a pasta do pacote."""
    partes = [raiz.name, *arquivo.relative_to(raiz).with_suffix("").parts]
    if partes[-1] == "__init__":
        partes.pop()
    return ".".join(partes)


def arquivos(pasta: Path) -> list[Path]:
    return sorted(arquivo for arquivo in pasta.rglob("*.py") if "__pycache__" not in arquivo.parts)


def importacoes_dinamicas(codigo: str) -> list[tuple[str | None, int]]:
    """``__import__(...)`` e ``import_module(...)`` como ``(nome literal ou None, linha)``; ``None`` = não é literal."""
    achadas = []
    for no in ast.walk(ast.parse(codigo)):
        if not isinstance(no, ast.Call):
            continue
        funcao = no.func
        nome = funcao.id if isinstance(funcao, ast.Name) else funcao.attr if isinstance(funcao, ast.Attribute) else ""
        if nome not in {"__import__", "import_module"}:
            continue
        primeiro = no.args[0] if no.args else None
        literal = primeiro.value if isinstance(primeiro, ast.Constant) and isinstance(primeiro.value, str) else None
        achadas.append((literal, no.lineno))
    return achadas


def modulos_importados(arquivo: Path, raiz: Path) -> list[tuple[str, int]]:
    """Importações estáticas e dinâmicas de nome literal de ``arquivo`` como ``(nome absoluto, linha)``."""
    codigo = arquivo.read_text(encoding="utf-8")
    modulo = nome_do_modulo(arquivo, raiz)
    achados = importados(codigo, modulo, eh_pacote=arquivo.name == "__init__.py")
    achados.extend((nome, linha) for nome, linha in importacoes_dinamicas(codigo) if nome is not None)
    return achados


def eh_modulo_do_grupo(nome: str, grupo) -> bool:
    return nome.split(".")[0] in grupo


def permitido_na_serializacao(nome: str) -> bool:
    """Biblioteca padrão, ``empiremuse.rules``, o próprio pacote e a raiz ``empiremuse`` (que só nomeia o pacote)."""
    if nome == "empiremuse":
        return True
    if any(nome == base or nome.startswith(base + ".") for base in PERMITIDOS_NA_SERIALIZACAO):
        return True
    return nome.split(".")[0] in BIBLIOTECA_PADRAO


def violacoes_da_serializacao(raiz: Path) -> list[str]:
    achadas = []
    for arquivo in arquivos(raiz / "serialization"):
        rotulo = arquivo.relative_to(raiz.parent).as_posix()
        for nome, linha in modulos_importados(arquivo, raiz):
            if not permitido_na_serializacao(nome):
                achadas.append(f"{rotulo}:{linha} importa {nome}")
        achadas.extend(
            f"{rotulo}:{linha} importa módulo de nome não literal (não dá para verificar)"
            for nome, linha in importacoes_dinamicas(arquivo.read_text(encoding="utf-8"))
            if nome is None
        )
    return achadas


def violacoes_de_formatos(raiz: Path, grupo, *, excecao: str | None = None) -> list[str]:
    """Importações de módulos do ``grupo`` em ``raiz``, exceto no arquivo ``excecao`` (caminho relativo a ``raiz``)."""
    achadas = []
    for arquivo in arquivos(raiz):
        relativo = arquivo.relative_to(raiz).as_posix()
        if relativo == excecao:
            continue
        achadas.extend(
            f"{raiz.name}/{relativo}:{linha} importa {nome}"
            for nome, linha in modulos_importados(arquivo, raiz)
            if eh_modulo_do_grupo(nome, grupo)
        )
    return achadas


# ============================================================================ as regras da arquitetura (nascem vermelhas)


def test_pickle_so_e_importado_em_legacy_pickle():
    """Passa quando a etapa 5 troca as duas últimas gravações (``save_session_*``): é teste de IMPORT."""
    assert violacoes_de_formatos(PACOTE, MODULOS_PICKLE, excecao=LEGADO) == []


def test_serializacao_so_importa_a_biblioteca_padrao_e_as_regras():
    pasta = PACOTE / "serialization"
    assert pasta.is_dir(), "empiremuse/serialization/ precisa existir"
    assert arquivos(pasta), "empiremuse/serialization/ precisa ter módulos"
    assert violacoes_da_serializacao(PACOTE) == []


# ============================================================================ o que já vale hoje


def test_nenhum_pickle_load_loads_ou_unpickler_fora_do_legacy_pickle():
    """Teste de LEITURA (e não de import): depois da 2b, ler pickle só é possível por ``legacy_pickle``.

    As gravações (``pickle.dumps``/``dump``) seguem até as etapas 3 a 6 e por isso o teste de import acima continua xfail.
    """
    from tests.test_f3_6b_inventario_pickle import CHAMADAS_DE_LEITURA, referencias_ao_pickle

    achadas = []
    for arquivo in arquivos(PACOTE):
        relativo = arquivo.relative_to(PACOTE).as_posix()
        if relativo == LEGADO:
            continue
        achadas.extend(
            f"{relativo}::{funcao or '<modulo>'} usa pickle.{atributo}"
            for funcao, atributo, _linha in referencias_ao_pickle(arquivo.read_text(encoding="utf-8"))
            if atributo in CHAMADAS_DE_LEITURA | {"_load", "_loads"}
        )
    assert achadas == []


def test_nenhum_outro_formato_executavel_e_importado():
    """Segue a regra de persistência do projeto: ``marshal``, ``shelve``, ``dill``, ``jsonpickle`` e similares, nunca."""
    assert violacoes_de_formatos(PACOTE, OUTROS_FORMATOS_EXECUTAVEIS) == []


def test_o_varredor_enxerga_os_arquivos_de_verdade():
    """Sem a exceção, o varredor acha o ``pickle`` do próprio leitor legado (senão o teste de import passaria à toa)."""
    achados = violacoes_de_formatos(PACOTE, MODULOS_PICKLE)
    assert any("serialization/legacy_pickle.py" in achado and "importa pickle" in achado for achado in achados)


# ============================================================================ o detector, provado com código sintético


class TestDetectorDeImportacoes:
    def nomes(self, codigo, modulo="empiremuse.serialization.x"):
        achados = importados(codigo, modulo) + [(n, ln) for n, ln in importacoes_dinamicas(codigo) if n]
        return {nome for nome, _ in achados}

    @pytest.mark.parametrize(
        "codigo",
        [
            "import pickle",
            "import pickle as p",
            "from pickle import loads",
            "from pickle import *",
            "import _pickle",
            "import cPickle",
            "def f():\n    import pickle",
            "try:\n    import pickle\nexcept ImportError:\n    pass",
            "x = __import__('pickle')",
            "import importlib\nx = importlib.import_module('pickle')",
            "from importlib import import_module\nx = import_module('_pickle')",
            "import pickle.x",
        ],
    )
    def test_acha_o_pickle(self, codigo):
        assert any(eh_modulo_do_grupo(nome, MODULOS_PICKLE) for nome in self.nomes(codigo))

    @pytest.mark.parametrize(
        "codigo",
        [
            "import pickletools",
            "import picklefoo",
            "from picklesque import x",
            "import json\nfrom pathlib import Path",
            "# import pickle\nx = 'pickle'",
            "x = __import__('json')",
            "from empiremuse.serialization import pickle_like",
        ],
    )
    def test_nao_confunde_com_nomes_parecidos_nem_com_texto(self, codigo):
        assert not any(eh_modulo_do_grupo(nome, MODULOS_PICKLE) for nome in self.nomes(codigo))

    def test_o_pickletools_nao_conta_como_pickle(self):
        """Só o ``pickle`` (e o módulo em C) são restritos; ``pickletools`` apenas lê opcodes e não executa nada."""
        assert not eh_modulo_do_grupo("pickletools", MODULOS_PICKLE)

    @pytest.mark.parametrize("nome", sorted(OUTROS_FORMATOS_EXECUTAVEIS))
    def test_acha_os_outros_formatos_executaveis(self, nome):
        assert eh_modulo_do_grupo(nome, OUTROS_FORMATOS_EXECUTAVEIS)
        assert eh_modulo_do_grupo(f"{nome}.sub", OUTROS_FORMATOS_EXECUTAVEIS)

    def test_importacao_dinamica_de_nome_nao_literal_e_marcada(self):
        achados = importacoes_dinamicas("import importlib\nx = importlib.import_module(nome)\ny = __import__(f'a{b}')")
        assert [nome for nome, _ in achados] == [None, None]

    def test_importacao_dinamica_sem_argumento_e_marcada(self):
        assert [nome for nome, _ in importacoes_dinamicas("x = __import__()")] == [None]

    @pytest.mark.parametrize(
        ("nome", "permitido"),
        [
            ("json", True),
            ("zlib", True),
            ("pickletools", True),
            ("pickle", True),  # é da biblioteca padrão; o confinamento do pickle é outra regra
            ("empiremuse.rules", True),
            ("empiremuse.rules.urls", True),
            ("empiremuse.serialization.schema", True),
            ("empiremuse", True),
            ("empiremuse.rulesx", False),
            ("empiremuse.utils", False),
            ("empiremuse.utils.db", False),
            ("empiremuse.panel.services", False),
            ("empiremuse.paths", False),
            ("disnake", False),
            ("tornado.web", False),
            ("cachetools", False),
            ("motor.motor_asyncio", False),
            ("aiofiles", False),
        ],
    )
    def test_o_que_a_serializacao_pode_importar(self, nome, permitido):
        assert permitido_na_serializacao(nome) is permitido


# ============================================================================ a varredura de pastas, em pacote sintético


class TestVarreduraDePastas:
    @pytest.fixture
    def raiz(self, tmp_path):
        pacote = tmp_path / "empiremuse"
        (pacote / "serialization").mkdir(parents=True)
        (pacote / "utils").mkdir()
        (pacote / "serialization" / "__init__.py").write_text("", encoding="utf-8")
        return pacote

    def escrever(self, raiz, caminho, codigo):
        alvo = raiz / caminho
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(codigo, encoding="utf-8")

    def test_pacote_limpo_nao_tem_violacao(self, raiz):
        self.escrever(raiz, "serialization/schema.py", "import json\nimport zlib\nfrom .codec import dumps\n")
        self.escrever(raiz, "serialization/session.py", "from empiremuse.rules import urls\nfrom . import schema\n")
        self.escrever(raiz, "serialization/legacy_pickle.py", "import pickle\nimport pickletools\nimport io\n")
        assert violacoes_da_serializacao(raiz) == []

    def test_import_de_terceiro_ou_do_projeto_e_apontado(self, raiz):
        self.escrever(raiz, "serialization/a.py", "import disnake\n")
        self.escrever(raiz, "serialization/b.py", "def f():\n    from empiremuse.utils.db import DBModel\n")
        self.escrever(raiz, "serialization/c.py", "from ..cogs import music\n")
        self.escrever(raiz, "serialization/d.py", "from cachetools import TTLCache\n")
        achadas = violacoes_da_serializacao(raiz)
        assert any("a.py:1 importa disnake" in achada for achada in achadas)
        assert any("b.py:2" in achada and "empiremuse.utils.db" in achada for achada in achadas)
        assert any("c.py:1" in achada and "empiremuse.cogs" in achada for achada in achadas)
        assert any("d.py:1 importa cachetools" in achada for achada in achadas)

    def test_import_relativo_para_fora_do_pacote_e_apontado(self, raiz):
        self.escrever(raiz, "serialization/a.py", "from .. import utils\n")
        assert any("a.py:1" in achada and "empiremuse.utils" in achada for achada in violacoes_da_serializacao(raiz))

    def test_import_relativo_para_as_regras_vale(self, raiz):
        self.escrever(raiz, "serialization/a.py", "from .. import rules\nfrom ..rules import urls\n")
        assert violacoes_da_serializacao(raiz) == []

    def test_subpacote_de_serializacao_tambem_e_varrido(self, raiz):
        self.escrever(raiz, "serialization/interno/x.py", "import tornado\n")
        assert any("interno/x.py:1 importa tornado" in achada for achada in violacoes_da_serializacao(raiz))

    def test_import_dinamico_de_terceiro_e_de_nome_nao_literal_sao_apontados(self, raiz):
        self.escrever(raiz, "serialization/a.py", "x = __import__('disnake')\n")
        self.escrever(raiz, "serialization/b.py", "import importlib\nx = importlib.import_module(nome)\n")
        achadas = violacoes_da_serializacao(raiz)
        assert any("a.py:1 importa disnake" in achada for achada in achadas)
        assert any("b.py:2" in achada and "não literal" in achada for achada in achadas)

    def test_so_o_legacy_pickle_pode_importar_o_pickle(self, raiz):
        self.escrever(raiz, "serialization/legacy_pickle.py", "import pickle\n")
        assert violacoes_de_formatos(raiz, MODULOS_PICKLE, excecao=LEGADO) == []

    @pytest.mark.parametrize(
        "caminho",
        [
            "serialization/session.py",
            "serialization/interno/legacy_pickle.py",
            "utils/legacy_pickle.py",
            "utils/client.py",
            "legacy_pickle.py",
        ],
    )
    def test_o_pickle_fora_do_legacy_pickle_e_apontado(self, raiz, caminho):
        self.escrever(raiz, caminho, "import pickle\n")
        achadas = violacoes_de_formatos(raiz, MODULOS_PICKLE, excecao=LEGADO)
        assert len(achadas) == 1 and caminho in achadas[0]

    def test_pickle_dinamico_fora_do_legado_tambem_e_apontado(self, raiz):
        self.escrever(raiz, "utils/x.py", "import importlib\nm = importlib.import_module('pickle')\n")
        assert len(violacoes_de_formatos(raiz, MODULOS_PICKLE, excecao=LEGADO)) == 1

    def test_o_legado_nao_isenta_outras_regras(self, raiz):
        """O ``legacy_pickle.py`` pode importar o ``pickle``, mas continua só com stdlib e regras."""
        self.escrever(raiz, "serialization/legacy_pickle.py", "import pickle\nimport disnake\n")
        assert violacoes_de_formatos(raiz, MODULOS_PICKLE, excecao=LEGADO) == []
        assert any("legacy_pickle.py:2 importa disnake" in achada for achada in violacoes_da_serializacao(raiz))

    def test_outros_formatos_executaveis_nao_tem_excecao(self, raiz):
        self.escrever(raiz, "serialization/legacy_pickle.py", "import marshal\n")
        assert violacoes_de_formatos(raiz, OUTROS_FORMATOS_EXECUTAVEIS) != []

    def test_nome_do_modulo_resolve_pacote_e_modulo(self, raiz):
        assert nome_do_modulo(raiz / "serialization" / "__init__.py", raiz) == "empiremuse.serialization"
        assert nome_do_modulo(raiz / "serialization" / "schema.py", raiz) == "empiremuse.serialization.schema"

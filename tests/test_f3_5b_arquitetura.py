"""F3-5b — teste de arquitetura por ``ast``: a direção das dependências entre as camadas.

* ``empiremuse/rules/**`` só importa a biblioteca padrão (e os próprios módulos de ``empiremuse.rules``): sem
  ``disnake``, ``tornado``, ``motor`` nem qualquer outro módulo do projeto.
* ``empiremuse/utils/**`` e ``empiremuse/cogs/**`` não importam ``empiremuse.panel`` (o painel pode importar o bot, o
  bot não pode importar o painel).

Conta qualquer ``import``, inclusive dentro de função e de ``if TYPE_CHECKING``, e resolve importações relativas.
Os dois testes de regra nascem com ``xfail(strict=True)``: ``empiremuse/rules/`` ainda não existe e ``interactions.py``
importa do painel hoje. Ficam verdes na etapa 1 (extração); aí o ``xfail`` estrito vira falha e o marcador sai.
O detector é provado à parte, com código sintético, e esses testes passam hoje.
"""

import ast
import sys
from pathlib import Path

import pytest

PACOTE = Path(__file__).resolve().parents[1] / "empiremuse"
REGRAS = PACOTE / "rules"
PAINEL = "empiremuse.panel"
BIBLIOTECA_PADRAO = set(sys.stdlib_module_names) | {"__future__"}


def nome_do_modulo(arquivo: Path) -> str:
    """``empiremuse/utils/music/x.py`` -> ``empiremuse.utils.music.x`` (``__init__`` vira o nome do pacote)."""
    partes = list(arquivo.relative_to(PACOTE.parent).with_suffix("").parts)
    if partes[-1] == "__init__":
        partes.pop()
    return ".".join(partes)


def importados(codigo: str, modulo: str, *, eh_pacote: bool = False) -> list[tuple[str, int]]:
    """Todos os módulos importados em ``codigo`` como ``(nome absoluto, linha)``; ``from a import b`` conta ``a.b``.

    ``from a import b`` devolve ``a`` E ``a.b``: ``b`` pode ser um submódulo (``from empiremuse import panel``).
    """
    base = modulo.split(".") if eh_pacote else modulo.split(".")[:-1]
    achados: list[tuple[str, int]] = []
    for no in ast.walk(ast.parse(codigo)):
        if isinstance(no, ast.Import):
            achados.extend((alias.name, no.lineno) for alias in no.names)
        elif isinstance(no, ast.ImportFrom):
            if no.level:
                pai = base[: len(base) - (no.level - 1)]
                origem = ".".join([*pai, *([no.module] if no.module else [])])
            else:
                origem = no.module or ""
            achados.append((origem, no.lineno))
            achados.extend((f"{origem}.{alias.name}", no.lineno) for alias in no.names if alias.name != "*")
    return achados


def importa_o_painel(nome: str) -> bool:
    return nome == PAINEL or nome.startswith(PAINEL + ".")


def fora_da_biblioteca_padrao(nome: str) -> bool:
    """``True`` se ``nome`` não é da biblioteca padrão nem de ``empiremuse.rules``."""
    if nome == "empiremuse.rules" or nome.startswith("empiremuse.rules."):
        return False
    return nome.split(".")[0] not in BIBLIOTECA_PADRAO


def arquivos(pasta: Path) -> list[Path]:
    return sorted(arquivo for arquivo in pasta.rglob("*.py") if "__pycache__" not in arquivo.parts)


def violacoes_do_painel(pasta: Path) -> list[str]:
    achadas = []
    for arquivo in arquivos(pasta):
        codigo = arquivo.read_text(encoding="utf-8")
        modulo = nome_do_modulo(arquivo)
        for nome, linha in importados(codigo, modulo, eh_pacote=arquivo.name == "__init__.py"):
            if importa_o_painel(nome):
                achadas.append(f"{arquivo.relative_to(PACOTE.parent)}:{linha} importa {nome}")
    return achadas


def violacoes_das_regras() -> list[str]:
    achadas = []
    for arquivo in arquivos(REGRAS):
        codigo = arquivo.read_text(encoding="utf-8")
        modulo = nome_do_modulo(arquivo)
        for nome, linha in importados(codigo, modulo, eh_pacote=arquivo.name == "__init__.py"):
            if fora_da_biblioteca_padrao(nome):
                achadas.append(f"{arquivo.relative_to(PACOTE.parent)}:{linha} importa {nome}")
    return achadas


# ============================================================================ as regras da arquitetura (RED até a etapa 1)

ETAPA_1 = "fica verde na etapa 1 da F3-5b (extração das regras para empiremuse/rules e fim do bot -> painel)"


@pytest.mark.xfail(strict=True, reason=f"empiremuse/rules/ ainda não existe; {ETAPA_1}")
def test_rules_so_importa_a_biblioteca_padrao():
    assert REGRAS.is_dir(), "empiremuse/rules/ precisa existir"
    assert arquivos(REGRAS), "empiremuse/rules/ precisa ter módulos"
    assert violacoes_das_regras() == []


@pytest.mark.xfail(strict=True, reason=f"interactions.py ainda importa empiremuse.panel; {ETAPA_1}")
def test_utils_nao_importa_o_painel():
    assert violacoes_do_painel(PACOTE / "utils") == []


def test_cogs_nao_importa_o_painel():
    """Já vale hoje (guarda): só ``utils/music/interactions.py`` importa o painel."""
    assert violacoes_do_painel(PACOTE / "cogs") == []


# ============================================================================ o detector (verde hoje)


class TestDetectorDeImportacoes:
    def nomes(self, codigo, modulo="empiremuse.utils.x", **kwargs):
        return {nome for nome, _ in importados(codigo, modulo, **kwargs)}

    @pytest.mark.parametrize(
        "codigo",
        [
            "import empiremuse.panel",
            "import empiremuse.panel.services.base as base",
            "from empiremuse.panel.services.base import clean_title",
            "from empiremuse.panel import build_panel_app",
            "from empiremuse import panel",
            "def f():\n    from empiremuse.panel.services import tasks",
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from empiremuse.panel.settings import X",
            "try:\n    import empiremuse.panel.services\nexcept ImportError:\n    pass",
        ],
    )
    def test_acha_a_importacao_do_painel(self, codigo):
        assert any(importa_o_painel(nome) for nome in self.nomes(codigo))

    @pytest.mark.parametrize(
        "codigo",
        [
            "from empiremuse.utils.owner_panel import PanelView",
            "import empiremuse.utils.music.interactions",
            "from empiremuse.paneis import x",
            "import json\nfrom pathlib import Path",
            "# from empiremuse.panel import x\nx = 'empiremuse.panel'",
        ],
    )
    def test_nao_confunde_com_nomes_parecidos_nem_com_texto(self, codigo):
        assert not any(importa_o_painel(nome) for nome in self.nomes(codigo))

    def test_resolve_importacao_relativa(self):
        assert importa_o_painel_em("from ..panel import x", "empiremuse.utils.x")
        assert importa_o_painel_em("from ...panel.services import x", "empiremuse.utils.music.x")
        assert importa_o_painel_em("from .. import panel", "empiremuse.cogs.x")
        assert not importa_o_painel_em("from . import interactions", "empiremuse.utils.music.x")
        assert importa_o_painel_em("from .. import panel", "empiremuse.utils", eh_pacote=True)

    @pytest.mark.parametrize(
        ("codigo", "fora"),
        [
            ("import json, re\nfrom pathlib import Path\nfrom __future__ import annotations", False),
            ("import disnake", True),
            ("from tornado import web", True),
            ("from motor.motor_asyncio import AsyncIOMotorClient", True),
            ("from empiremuse.utils.db import DBModel", True),
            ("from empiremuse.panel.services.base import clean_title", True),
            ("from empiremuse.rules.limits import X\nimport empiremuse.rules.text", False),
            ("from .limits import X\nfrom . import text", False),
            ("from .. import utils", True),
        ],
    )
    def test_biblioteca_padrao_e_o_proprio_pacote_de_regras(self, codigo, fora):
        achados = importados(codigo, "empiremuse.rules.urls")
        assert any(fora_da_biblioteca_padrao(nome) for nome, _ in achados) is fora

    def test_pacote_init_resolve_relativas_a_partir_do_proprio_pacote(self):
        achados = {nome for nome, _ in importados("from .limits import X", "empiremuse.rules", eh_pacote=True)}
        assert "empiremuse.rules.limits" in achados

    def test_o_scanner_enxerga_o_estado_atual_da_main(self):
        """Prova de que o varredor lê os arquivos de verdade: hoje o ``interactions.py`` importa o painel."""
        achadas = violacoes_do_painel(PACOTE / "utils")
        assert any("utils/music/interactions.py" in achada for achada in achadas)
        assert not any("owner_panel" in achada for achada in achadas), "owner_panel não é empiremuse.panel"


def importa_o_painel_em(codigo, modulo, **kwargs):
    return any(importa_o_painel(nome) for nome, _ in importados(codigo, modulo, **kwargs))


class TestVarreduraDePastas:
    """O caminho completo (arquivos -> importações -> violações) sobre um pacote sintético em ``tmp_path``."""

    @pytest.fixture
    def pacote(self, tmp_path, monkeypatch):
        raiz = tmp_path / "empiremuse"
        (raiz / "rules").mkdir(parents=True)
        (raiz / "utils").mkdir()
        monkeypatch.setattr(sys.modules[__name__], "PACOTE", raiz)
        monkeypatch.setattr(sys.modules[__name__], "REGRAS", raiz / "rules")
        return raiz

    def test_regras_limpas_nao_tem_violacao(self, pacote):
        (pacote / "rules" / "__init__.py").write_text("", encoding="utf-8")
        (pacote / "rules" / "limits.py").write_text("import re\nFAV = 25\n", encoding="utf-8")
        (pacote / "rules" / "text.py").write_text("from .limits import FAV\nimport unicodedata\n", encoding="utf-8")
        assert violacoes_das_regras() == []

    def test_regras_que_importam_disnake_ou_o_projeto_sao_apontadas(self, pacote):
        (pacote / "rules" / "a.py").write_text("import disnake\n", encoding="utf-8")
        (pacote / "rules" / "b.py").write_text(
            "def f():\n    from empiremuse.utils.db import DBModel\n", encoding="utf-8"
        )
        achadas = violacoes_das_regras()
        assert any("a.py:1 importa disnake" in achada for achada in achadas)
        assert any("b.py:2" in achada and "empiremuse.utils.db" in achada for achada in achadas)

    def test_utils_que_importa_o_painel_e_apontado_inclusive_no_que_e_lazy(self, pacote):
        (pacote / "utils" / "ok.py").write_text("from empiremuse.rules import limits\n", encoding="utf-8")
        (pacote / "utils" / "ruim.py").write_text(
            "def f():\n    from empiremuse.panel.services import base\n", encoding="utf-8"
        )
        achadas = violacoes_do_painel(pacote / "utils")
        assert achadas and all("ruim.py" in achada for achada in achadas)

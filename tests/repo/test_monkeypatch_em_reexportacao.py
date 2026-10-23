"""KI-29 — guarda contra ``monkeypatch.setattr`` numa REEXPORTAÇÃO.

Depois da divisão de ``music.py``, ``models.py`` e ``interactions.py``, um nome importado de volta no módulo antigo só
existe para quem importa por ele. Trocar esse nome com ``monkeypatch.setattr(modulo, "nome", falso)`` "funciona" (o
atributo existe), mas o código que usa o nome agora mora em outro módulo e continua chamando o original: o teste passa
a testar o código de verdade sem avisar. A guarda varre ``tests/`` atrás de ``setattr`` em um desses módulos e exige que
o nome seja DEFINIDO ou USADO no próprio arquivo do módulo (não só importado ou reexportado).
"""

import ast
import importlib.util
from pathlib import Path

import pytest

from tests.support.api_publica import FAMILIAS
from tests.support.raiz import RAIZ

MODULOS_ALVO = {modulo for modulo, _ in FAMILIAS.values()}


def apelidos_dos_modulos(arvore: ast.AST) -> dict[str, str]:
    """``{apelido local: módulo completo}`` para os módulos-alvo importados no arquivo de teste."""
    apelidos: dict[str, str] = {}
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.module:
            for alias in no.names:
                completo = f"{no.module}.{alias.name}"
                if completo in MODULOS_ALVO:
                    apelidos[alias.asname or alias.name] = completo
        elif isinstance(no, ast.Import):
            for alias in no.names:
                if alias.name in MODULOS_ALVO and alias.asname:
                    apelidos[alias.asname] = alias.name
    return apelidos


def pares_modificados(codigo: str) -> set[tuple[str, str]]:
    """``(módulo-alvo, nome)`` de cada ``<x>.setattr(...)`` do código, nas formas objeto+nome e caminho com pontos."""
    arvore = ast.parse(codigo)
    apelidos = apelidos_dos_modulos(arvore)
    achados: set[tuple[str, str]] = set()
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == "setattr"):
            continue
        if len(no.args) >= 2 and isinstance(no.args[0], ast.Name) and no.args[0].id in apelidos:
            nome = no.args[1]
            if isinstance(nome, ast.Constant) and isinstance(nome.value, str):
                achados.add((apelidos[no.args[0].id], nome.value))
        elif no.args and isinstance(no.args[0], ast.Constant) and isinstance(no.args[0].value, str):
            modulo, _, nome = no.args[0].value.rpartition(".")
            if modulo in MODULOS_ALVO:
                achados.add((modulo, nome))
    return achados


def definido_ou_usado(codigo_do_modulo: str, nome: str) -> bool:
    """O nome é definido no nível superior do arquivo ou lido (``Name`` em ``Load``) por código dele, não só importado."""
    arvore = ast.parse(codigo_do_modulo)
    for no in arvore.body:
        if isinstance(no, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and no.name == nome:
            return True
        if isinstance(no, ast.Assign) and any(isinstance(t, ast.Name) and t.id == nome for t in no.targets):
            return True
        if isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name) and no.target.id == nome:
            return True
    return any(isinstance(no, ast.Name) and no.id == nome and isinstance(no.ctx, ast.Load) for no in ast.walk(arvore))


def arquivo_do_modulo(modulo: str) -> Path:
    return Path(importlib.util.find_spec(modulo).origin)


def pares_dos_testes() -> list[tuple[str, str, str]]:
    achados = []
    for arquivo in sorted((RAIZ / "tests").rglob("*.py")):
        if arquivo.name == Path(__file__).name or "__pycache__" in arquivo.parts:
            continue
        for modulo, nome in sorted(pares_modificados(arquivo.read_text(encoding="utf-8"))):
            achados.append((str(arquivo.relative_to(RAIZ)), modulo, nome))
    return achados


@pytest.mark.parametrize(("teste", "modulo", "nome"), pares_dos_testes(), ids=lambda v: str(v).split("/")[-1])
def test_o_nome_trocado_e_usado_no_proprio_arquivo_do_modulo(teste, modulo, nome):
    codigo = arquivo_do_modulo(modulo).read_text(encoding="utf-8")
    assert definido_ou_usado(codigo, nome), (
        f"{teste}: monkeypatch de {modulo}.{nome}, mas esse arquivo só importa/reexporta o nome; "
        "troque o alvo para o módulo onde o código que o usa mora"
    )


class TestDetector:
    """O detector, provado com código sintético (a varredura acima só roda sobre o que existe hoje)."""

    TESTE = (
        "from empiremuse.utils.music import interactions as ui\n"
        "from empiremuse.cogs import music\n"
        "def t(monkeypatch):\n"
        "    monkeypatch.setattr(ui, 'process_idle_embed', 1)\n"
        "    monkeypatch.setattr('empiremuse.cogs.music.string_to_file', 2)\n"
        "    monkeypatch.setattr(outro, 'x', 3)\n"
        "    monkeypatch.setattr(music.asyncio, 'sleep', 4)\n"
    )

    def test_acha_objeto_mais_nome_e_caminho_com_pontos(self):
        assert pares_modificados(self.TESTE) == {
            ("empiremuse.utils.music.interactions", "process_idle_embed"),
            ("empiremuse.cogs.music", "string_to_file"),
        }

    @pytest.mark.parametrize(
        ("modulo", "usado"),
        [
            ("from x import f\nf()\n", True),
            ("from x import f\n", False),
            ("from x import f\n__all__ = ['f']\n", False),
            ("def f(): ...\n", True),
            ("f = 1\n", True),
            ("class f: ...\n", True),
            ("from x import f as g\ng()\n", False),
        ],
    )
    def test_reexportar_nao_conta_como_uso(self, modulo, usado):
        assert definido_ou_usado(modulo, "f") is usado

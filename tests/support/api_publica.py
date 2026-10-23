"""KI-29 — extratores das guardas de equivalência da divisão de ``music.py``, ``models.py`` e ``interactions.py``.

A divisão desses três arquivos é só movimentação de código. As guardas comparam o estado atual com listas douradas
geradas do ``main`` ANTES de qualquer movimentação (``tests/repo/golden/``):

* ``nomes.json``: nomes de nível superior (classes, funções e constantes) de cada módulo, que seguem acessíveis por
  ``getattr(modulo, nome)`` (reexportação) depois da divisão;
* ``custom_ids.json``: todos os literais ``custom_id=`` do código da família, com repetição;
* ``comandos_music.json``: o que o ``disnake`` registra para a Cog ``Music`` (comandos, opções, cooldowns, checks,
  autocompletes, listeners e membros).

Cada "família" é o arquivo original MAIS o que ele virar (``cogs/music.py`` + ``music_cog/``; ``models.py`` ou
``models/``; ``interactions.py`` ou ``interactions/``), então os extratores valem antes e depois da divisão.

Regerar (só se o comportamento mudar de propósito, nunca em PR de movimentação)::

    python -m tests.support.api_publica
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
from pathlib import Path

from tests.support.raiz import RAIZ

PACOTE = RAIZ / "empiremuse"
GOLDEN = RAIZ / "tests" / "repo" / "golden"

# Família -> (módulo importável, arquivos que formam o código dela, relativos a ``empiremuse/``).
FAMILIAS: dict[str, tuple[str, tuple[str, ...]]] = {
    "music": ("empiremuse.cogs.music", ("cogs/music.py", "music_cog")),
    "models": ("empiremuse.utils.music.models", ("utils/music/models.py", "utils/music/models")),
    "interactions": (
        "empiremuse.utils.music.interactions",
        ("utils/music/interactions.py", "utils/music/interactions"),
    ),
}

# ``logger = logging.getLogger(__name__)`` existe em cada módulo; o nome do logger acompanha o módulo que o define.
NOMES_IGNORADOS = frozenset({"logger"})


def arquivos_da_familia(familia: str) -> list[Path]:
    """Os ``.py`` da família que existem hoje (o arquivo único ou a pasta do pacote), em ordem estável."""
    achados: list[Path] = []
    for relativo in FAMILIAS[familia][1]:
        caminho = PACOTE / relativo
        if caminho.is_file():
            achados.append(caminho)
        elif caminho.is_dir():
            achados.extend(p for p in caminho.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(achados)


def fonte_da_familia(familia: str) -> str:
    """O texto de TODOS os arquivos da família, concatenado.

    Os testes que leem o código-fonte (``Path(modulo.__file__).read_text()``) passam a ler só o ``__init__`` fino depois
    da divisão: uma asserção negativa ("não há ``repr(e)``") passaria no vazio. Eles devem ler a família inteira.
    """
    return "\n".join(arquivo.read_text(encoding="utf-8") for arquivo in arquivos_da_familia(familia))


def arvore_da_familia(familia: str) -> ast.Module:
    """Um ``ast.Module`` com o corpo de todos os arquivos da família (para ``ast.walk`` sobre a família toda)."""
    corpo: list[ast.stmt] = []
    for arquivo in arquivos_da_familia(familia):
        corpo.extend(ast.parse(arquivo.read_text(encoding="utf-8")).body)
    return ast.Module(body=corpo, type_ignores=[])


def _alvos(no: ast.stmt) -> list[str]:
    if isinstance(no, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return [no.name]
    if isinstance(no, ast.Assign):
        return [alvo.id for alvo in no.targets if isinstance(alvo, ast.Name)]
    if isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name):
        return [no.target.id]
    return []


def nomes_definidos(arquivo: Path) -> set[str]:
    """Nomes definidos no nível superior de ``arquivo`` (não conta ``import``)."""
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    return {nome for no in arvore.body for nome in _alvos(no)}


def nomes_da_familia(familia: str) -> list[str]:
    """Todos os nomes de nível superior que a família define, menos os de ``__init__`` (que só reexportam)."""
    nomes: set[str] = set()
    for arquivo in arquivos_da_familia(familia):
        if arquivo.name != "__init__.py":
            nomes |= nomes_definidos(arquivo)
    return sorted(nomes - NOMES_IGNORADOS)


def custom_ids_da_familia(familia: str) -> list[str]:
    """Os ``custom_id=`` literais (``str`` ou f-string, como texto) do código da família, ordenados e com repetição."""
    achados: list[str] = []
    for arquivo in arquivos_da_familia(familia):
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            if not isinstance(no, ast.keyword) or no.arg != "custom_id":
                continue
            valor = no.value
            if isinstance(valor, ast.Constant) and isinstance(valor.value, str):
                achados.append(valor.value)
            elif isinstance(valor, ast.JoinedStr):
                achados.append(ast.unparse(valor))
    return sorted(achados)


# ============================================================================ comandos da Cog Music


def _cooldown(comando) -> list | None:
    buckets = getattr(comando, "_buckets", None)
    cooldown = getattr(buckets, "_cooldown", None)
    if cooldown is None:
        return None
    return [cooldown.rate, cooldown.per, buckets._type.name]


def _concorrencia(comando) -> list | None:
    mc = getattr(comando, "_max_concurrency", None)
    return None if mc is None else [mc.number, mc.per.name, mc.wait]


def _opcoes(comando) -> list:
    corpo = getattr(comando, "body", None)
    opcoes = getattr(corpo, "options", None) or []
    return [
        [o.name, o.type.name, bool(o.required), sorted((str(c.name), str(c.value)) for c in (o.choices or []))]
        for o in opcoes
    ]


def _extra(valor) -> str:
    """``repr`` do valor de ``extras``; o parser de flags vira a lista dos seus argumentos (o ``repr`` traz o ``argv[0]``)."""
    if isinstance(valor, argparse.ArgumentParser):
        return "argparse:" + ",".join(sorted("/".join(a.option_strings) or a.dest for a in valor._actions))
    return repr(valor)


def descreve_comando(comando) -> dict:
    corpo = getattr(comando, "body", None)
    return {
        "tipo": type(comando).__name__,
        "nome": comando.qualified_name,
        "descricao": str(getattr(corpo, "description", None) or getattr(comando, "description", "") or ""),
        "opcoes": _opcoes(comando),
        "extras": {chave: _extra(valor) for chave, valor in sorted(dict(getattr(comando, "extras", {}) or {}).items())},
        "aliases": sorted(getattr(comando, "aliases", None) or []),
        "cooldown": _cooldown(comando),
        "concorrencia": _concorrencia(comando),
        "checks": len(getattr(comando, "checks", None) or []),
        "autocompletes": sorted(getattr(comando, "autocompleters", None) or {}),
        "filhos": sorted(getattr(comando, "children", None) or {}),
    }


def snapshot_music(modulo=None) -> dict:
    """O que o ``disnake`` registra para ``Music`` no nível da classe (antes de qualquer instância)."""
    from disnake.ext import commands

    modulo = modulo or importlib.import_module(FAMILIAS["music"][0])
    music = modulo.Music
    comandos: dict[str, dict] = {}
    for comando in [*music.__cog_app_commands__, *music.__cog_commands__]:
        retratos = [comando, *(getattr(comando, "children", None) or {}).values()]
        for retrato in retratos:
            comandos[f"{type(retrato).__name__}:{retrato.qualified_name}"] = descreve_comando(retrato)
    retrato = {
        "comandos": dict(sorted(comandos.items())),
        "listeners": sorted([list(par) for par in music.__cog_listeners__]),
        "membros": sorted(set(dir(music)) - set(dir(commands.Cog))),
    }
    return json.loads(json.dumps(retrato))  # tuplas viram listas, igual ao que o arquivo dourado guarda


def gerar() -> None:
    GOLDEN.mkdir(parents=True, exist_ok=True)

    def escrever(nome: str, dados: dict) -> None:
        texto = json.dumps(dados, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
        (GOLDEN / nome).write_text(texto, encoding="utf-8")

    escrever("nomes.json", {familia: nomes_da_familia(familia) for familia in FAMILIAS})
    escrever("custom_ids.json", {familia: custom_ids_da_familia(familia) for familia in FAMILIAS})
    escrever("comandos_music.json", snapshot_music())


if __name__ == "__main__":
    gerar()

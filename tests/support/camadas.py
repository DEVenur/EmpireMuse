"""F3-5b — teste de arquitetura por ``ast``: a direção das dependências entre as camadas.

* ``empiremuse/rules/**`` só importa a biblioteca padrão (e os próprios módulos de ``empiremuse.rules``): sem
  ``disnake``, ``tornado``, ``pymongo`` nem qualquer outro módulo do projeto.
* ``empiremuse/utils/**`` e ``empiremuse/cogs/**`` não importam ``empiremuse.panel`` (o painel pode importar o bot, o
  bot não pode importar o painel).

Conta qualquer ``import``, inclusive dentro de função e de ``if TYPE_CHECKING``, e resolve importações relativas.
São guardas desde a etapa 1 da F3-5b (extração para ``empiremuse/rules``, bot sem importar o painel). O detector é
provado à parte, com código e pastas sintéticos. Um teste em subprocesso confere o efeito real: importar o bot não
carrega nenhum módulo ``empiremuse.panel*``.
"""

import ast
import sys

from tests.support.raiz import RAIZ

PACOTE = RAIZ / "empiremuse"
BIBLIOTECA_PADRAO = set(sys.stdlib_module_names) | {"__future__"}


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


# ============================================================================ o detector


# ============================================================================ o efeito real: sys.modules em um processo limpo

RAIZ = PACOTE.parent

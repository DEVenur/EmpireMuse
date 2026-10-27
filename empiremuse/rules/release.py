"""Versões de release do EmpireMuse: só ``X.Y.Z`` estrito, comparável por número.

Sem pré-release, sem build metadata, sem espaços e sem zero à esquerda; cada componente tem até 4 dígitos ASCII. O
``fullmatch`` e o ``[0-9]`` valem de propósito: ``$`` aceitaria uma quebra de linha no fim e ``\\d`` aceitaria dígitos
de outros alfabetos. Funções puras, só stdlib.
"""

from __future__ import annotations

import re
from typing import NamedTuple

_COMPONENT = r"(0|[1-9][0-9]{0,3})"
_VERSION = re.compile(rf"{_COMPONENT}\.{_COMPONENT}\.{_COMPONENT}")
TAG_PREFIX = "v"


class Version(NamedTuple):
    """Versão ``major.minor.patch``; a ordenação é a da tupla (numérica, não textual)."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_version(text: str) -> Version | None:
    """``X.Y.Z`` estrito → ``Version``; qualquer outra coisa → ``None``."""
    match = _VERSION.fullmatch(text)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return Version(major, minor, patch)


def parse_tag(name: str) -> Version | None:
    """``vX.Y.Z`` estrito (prefixo ``v`` obrigatório) → ``Version``; qualquer outra coisa → ``None``."""
    if not name.startswith(TAG_PREFIX):
        return None
    return parse_version(name[len(TAG_PREFIX) :])

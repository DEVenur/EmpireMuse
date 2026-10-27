"""Versão do bot quando ele roda numa imagem Docker: o build grava ``EMPIREMUSE_VERSION`` (``ARG`` do Dockerfile).

Fora da imagem (checkout git, desenvolvimento) a variável não existe. Na imagem montada sem ``--build-arg`` ela vale
``dev``, que não é uma versão: ``image_version`` devolve ``None`` e ``running_from_image`` segue verdadeiro.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from empiremuse.rules.release import Version, parse_version

VERSION_ENV = "EMPIREMUSE_VERSION"


def image_version(environ: Mapping[str, str] = os.environ) -> Version | None:
    """Versão gravada na imagem; ``None`` quando a variável falta, é ``dev``, vazia ou inválida."""
    value = environ.get(VERSION_ENV)
    if value is None:
        return None
    return parse_version(value)


def running_from_image(environ: Mapping[str, str] = os.environ) -> bool:
    """Verdadeiro quando ``EMPIREMUSE_VERSION`` existe, qualquer que seja o valor."""
    return VERSION_ENV in environ

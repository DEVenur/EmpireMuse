"""Versões de release do EmpireMuse e as regras puras do update: alvos são só ``X.Y.Z`` estrito; a versão atual da
imagem pode ser ``X.Y.Z-rc.N`` (``parse_current_version``, D13), com ``X.Y.Z-rc.N < X.Y.Z`` e ordenação numérica.

Sem outros pré-releases, sem build metadata, sem espaços e sem zero à esquerda; cada componente tem até 4 dígitos ASCII.
O ``fullmatch`` e o ``[0-9]`` valem de propósito: ``$`` aceitaria uma quebra de linha no fim e ``\\d`` aceitaria dígitos
de outros alfabetos. Funções puras, só stdlib.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import NamedTuple

_COMPONENT = r"(0|[1-9][0-9]{0,3})"
_VERSION = re.compile(rf"{_COMPONENT}\.{_COMPONENT}\.{_COMPONENT}")
_CURRENT_VERSION = re.compile(rf"{_COMPONENT}\.{_COMPONENT}\.{_COMPONENT}(?:-rc\.{_COMPONENT})?")
TAG_PREFIX = "v"
STABLE_RC = 10_000


class Version(NamedTuple):
    """Versão ``major.minor.patch`` (ou ``major.minor.patch-rc.N`` quando ``rc != STABLE_RC``); a ordenação é a da tupla."""

    major: int
    minor: int
    patch: int
    rc: int = STABLE_RC

    @property
    def is_prerelease(self) -> bool:
        return self.rc != STABLE_RC

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-rc.{self.rc}" if self.is_prerelease else base


def parse_version(text: str) -> Version | None:
    """``X.Y.Z`` estrito → ``Version``; qualquer outra coisa → ``None``."""
    match = _VERSION.fullmatch(text)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return Version(major, minor, patch)


def parse_current_version(text: str) -> Version | None:
    """``X.Y.Z`` ou ``X.Y.Z-rc.N`` estrito (versão atual da imagem, D13) → ``Version``; qualquer outra coisa → ``None``."""
    match = _CURRENT_VERSION.fullmatch(text)
    if match is None:
        return None
    major, minor, patch, rc = match.groups()
    return Version(int(major), int(minor), int(patch), STABLE_RC if rc is None else int(rc))


def parse_tag(name: str) -> Version | None:
    """``vX.Y.Z`` estrito (prefixo ``v`` obrigatório) → ``Version``; qualquer outra coisa → ``None``."""
    if not name.startswith(TAG_PREFIX):
        return None
    return parse_version(name[len(TAG_PREFIX) :])


# --------------------------------------------------------------------------- escolha da tag e "o que mudou"

_SHA1 = re.compile(r"[0-9a-f]{40}")
_UPDATE_TARGET = re.compile(r"([0-9.]+)@(sha256:[0-9a-f]{64})")
_SECTION_HEADER = re.compile(r"## \[([^\]]*)\]")
_LINK_REFERENCE = re.compile(r"\[[^\]]+\]: ")
TAGS_PREFIX = "refs/tags/"
PEELED_SUFFIX = "^{}"
ELLIPSIS = "…"


def parse_ls_remote_annotated(output: str) -> dict[Version, str]:
    """Tag ``vX.Y.Z`` estrita → SHA do objeto da tag, só para as anotadas (as que têm a linha ``^{}`` do ``ls-remote``).

    Tags leves, pré-release e qualquer nome fora de ``vX.Y.Z`` ficam de fora.
    """
    objects: dict[Version, str] = {}
    peeled: set[Version] = set()
    for line in output.split("\n"):
        sha, tab, ref = line.partition("\t")
        if not tab or not _SHA1.fullmatch(sha) or not ref.startswith(TAGS_PREFIX):
            continue
        name = ref[len(TAGS_PREFIX) :]
        if name.endswith(PEELED_SUFFIX):
            if (version := parse_tag(name.removesuffix(PEELED_SUFFIX))) is not None:
                peeled.add(version)
        elif (version := parse_tag(name)) is not None:
            objects[version] = sha
    return {version: sha for version, sha in objects.items() if version in peeled}


def pick_target(current: Version, candidates: Iterable[Version]) -> Version | None:
    """A maior versão estritamente maior que ``current``; ``None`` se não houver."""
    return max((version for version in candidates if version > current), default=None)


def _changelog_blocks(text: str) -> list[tuple[Version, str]]:
    """Seções ``## [A.B.C]`` do changelog (``[Unreleased]`` e títulos que não são versão ficam de fora), sem as referências de link."""
    blocks: list[tuple[Version, str]] = []
    version: Version | None = None
    body: list[str] = []

    def close() -> None:
        if version is not None:
            blocks.append((version, "\n".join(body).strip()))

    for line in text.split("\n"):
        if line.startswith("## "):
            close()
            header = _SECTION_HEADER.match(line)
            version = parse_version(header.group(1)) if header else None
            body = [line]
        elif version is not None and not _LINK_REFERENCE.match(line):
            body.append(line)
    close()
    return blocks


def changelog_sections(text: str, current: Version, target: Version, max_chars: int) -> str:
    """Seções do changelog com ``current < versão <= target``, da mais nova para a mais velha.

    Acima de ``max_chars`` o texto é cortado e termina com ``…``. Sem nenhuma seção devolve ``""``.
    """
    chosen = sorted((block for block in _changelog_blocks(text) if current < block[0] <= target), reverse=True)
    result = "\n\n".join(body for _, body in chosen)
    if len(result) > max_chars:
        return result[: max(max_chars - 1, 0)].rstrip() + ELLIPSIS
    return result


def changelog_section(text: str, version: Version, max_chars: int) -> str:
    """O bloco da ``version`` no changelog (``""`` se não houver), cortado em fim de linha com ``…`` acima de ``max_chars``."""
    body = next((block for found, block in _changelog_blocks(text) if found == version), "")
    if len(body) <= max_chars:
        return body
    if max_chars <= len(ELLIPSIS):
        return ELLIPSIS[:max_chars]
    kept = body[: max_chars - len(ELLIPSIS)]
    if body[len(kept)] != "\n":
        kept = kept.rpartition("\n")[0]
    return kept.rstrip() + ELLIPSIS


def parse_update_target(text: str) -> tuple[Version, str] | None:
    """``X.Y.Z@sha256:<64hex>`` estrito → ``(versão, digest)``; qualquer outra coisa → ``None``."""
    match = _UPDATE_TARGET.fullmatch(text)
    if match is None:
        return None
    version = parse_version(match.group(1))
    return None if version is None else (version, match.group(2))

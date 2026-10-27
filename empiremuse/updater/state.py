"""Estado da atualização em disco, em ``RUNTIME_DIR``: o pedido em andamento e as tags já vistas.

``update-pending.json`` (0600, escrita atômica) existe enquanto há uma atualização em andamento: com ele presente, um
segundo ``update`` é recusado. Tudo que vem do arquivo é validado campo a campo na leitura (versões, SHAs, digest e ids);
um arquivo inválido, de esquema diferente ou com mais de 24 h é apagado com um aviso sem o conteúdo.
``update-state.json`` guarda tag → SHA do objeto da tag já vista (fluxo git): uma tag que muda de SHA aborta o update.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from empiremuse.rules.release import Version, parse_tag, parse_version

logger = logging.getLogger(__name__)

PENDING_FILE = "update-pending.json"
SEEN_TAGS_FILE = "update-state.json"
PENDING_VERSION = 1
PENDING_MAX_AGE_SECONDS = 24 * 3600
MAX_FILE_BYTES = 64 * 1024
MAX_BOOTS = 1000
FLOWS = ("git", "docker")
STATUSES = ("pending", "rolled_back")

_SHA1 = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_COMMON_KEYS = frozenset(
    {"v", "flow", "from_version", "to_version", "bot_id", "channel_id", "requested_by", "created_at", "boots", "status"}
)
_KEYS_BY_FLOW = {"git": _COMMON_KEYS | {"prev_sha"}, "docker": _COMMON_KEYS | {"digest"}}


@dataclasses.dataclass(frozen=True)
class UpdateRequest:
    """Quem pediu o update e onde: montado pelo comando ``update`` e copiado para o pendente."""

    bot_id: int
    channel_id: int
    requested_by: int


@dataclasses.dataclass(frozen=True)
class PendingUpdate:
    """Atualização em andamento; ``prev_sha`` vale no fluxo git e ``digest`` no fluxo Docker (o outro fica ``None``)."""

    flow: str
    from_version: Version
    to_version: Version
    bot_id: int
    channel_id: int
    requested_by: int
    created_at: float
    prev_sha: str | None = None
    digest: str | None = None
    boots: int = 0
    status: str = "pending"
    v: int = PENDING_VERSION

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "v": self.v,
            "flow": self.flow,
            "from_version": str(self.from_version),
            "to_version": str(self.to_version),
            "bot_id": self.bot_id,
            "channel_id": self.channel_id,
            "requested_by": self.requested_by,
            "created_at": self.created_at,
            "boots": self.boots,
            "status": self.status,
        }
        if self.flow == "git":
            data["prev_sha"] = self.prev_sha
        else:
            data["digest"] = self.digest
        return data


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def parse_pending(data: object) -> PendingUpdate | None:
    """``PendingUpdate`` do JSON já lido, ou ``None`` se qualquer campo estiver fora do esquema."""
    if not isinstance(data, dict):
        return None
    flow = data.get("flow")
    if flow not in FLOWS or set(data) != _KEYS_BY_FLOW[flow]:
        return None
    from_version = parse_version(data["from_version"]) if isinstance(data["from_version"], str) else None
    to_version = parse_version(data["to_version"]) if isinstance(data["to_version"], str) else None
    created_at = data["created_at"]
    boots = data["boots"]
    valid = (
        data["v"] == PENDING_VERSION
        and not isinstance(data["v"], bool)
        and from_version is not None
        and to_version is not None
        and all(_positive_int(data[key]) for key in ("bot_id", "channel_id", "requested_by"))
        and isinstance(created_at, int | float)
        and not isinstance(created_at, bool)
        and math.isfinite(created_at)
        and isinstance(boots, int)
        and not isinstance(boots, bool)
        and 0 <= boots <= MAX_BOOTS
        and data["status"] in STATUSES
    )
    if not valid:
        return None
    prev_sha = data.get("prev_sha")
    digest = data.get("digest")
    if flow == "git" and not (isinstance(prev_sha, str) and _SHA1.fullmatch(prev_sha)):
        return None
    if flow == "docker" and not (isinstance(digest, str) and _DIGEST.fullmatch(digest)):
        return None
    assert from_version is not None and to_version is not None
    return PendingUpdate(
        flow=flow,
        from_version=from_version,
        to_version=to_version,
        bot_id=data["bot_id"],
        channel_id=data["channel_id"],
        requested_by=data["requested_by"],
        created_at=float(created_at),
        prev_sha=prev_sha if flow == "git" else None,
        digest=digest if flow == "docker" else None,
        boots=boots,
        status=data["status"],
    )


def _write_json_atomic(path: Path, data: object) -> None:
    """Grava ``data`` em JSON, 0600, por arquivo temporário no mesmo diretório + ``os.replace``."""
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(data, file)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> object:
    """JSON do arquivo (até ``MAX_FILE_BYTES``); levanta ``OSError``/``ValueError`` se ausente, grande demais ou inválido."""
    with open(path, "rb") as file:
        raw = file.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("arquivo grande demais")
    return json.loads(raw.decode("utf-8"))


def pending_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / PENDING_FILE


def write_pending(runtime_dir: Path, pending: PendingUpdate) -> None:
    _write_json_atomic(pending_path(runtime_dir), pending.to_json())


def clear_pending(runtime_dir: Path) -> None:
    pending_path(runtime_dir).unlink(missing_ok=True)


def read_pending(runtime_dir: Path, now: float) -> PendingUpdate | None:
    """O pendente em disco, ou ``None``. Inválido, de outro esquema ou com mais de 24 h é apagado (aviso sem o conteúdo)."""
    path = pending_path(runtime_dir)
    try:
        data = _read_json(path)
    except FileNotFoundError:
        return None
    except OSError, ValueError, RecursionError:
        pending = None
    else:
        pending = parse_pending(data)
    if pending is None:
        logger.warning("Arquivo de atualização pendente inválido; descartado.")
        clear_pending(runtime_dir)
        return None
    if now - pending.created_at > PENDING_MAX_AGE_SECONDS:
        logger.warning("Arquivo de atualização pendente com mais de 24 h; descartado.")
        clear_pending(runtime_dir)
        return None
    return pending


def read_seen_tags(runtime_dir: Path) -> dict[str, str]:
    """Tag → SHA do objeto da tag já vistas; arquivo ausente ou inválido vale como vazio (nada foi visto)."""
    try:
        data = _read_json(Path(runtime_dir) / SEEN_TAGS_FILE)
    except OSError, ValueError, RecursionError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        tag: sha
        for tag, sha in data.items()
        if isinstance(tag, str) and parse_tag(tag) is not None and isinstance(sha, str) and _SHA1.fullmatch(sha)
    }


def write_seen_tags(runtime_dir: Path, seen: dict[str, str]) -> None:
    _write_json_atomic(Path(runtime_dir) / SEEN_TAGS_FILE, seen)

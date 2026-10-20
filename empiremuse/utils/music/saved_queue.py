"""Fila salva do usuário: caminhos, gravação em JSON, leitura (com migração do ``.pkl`` antigo) e migração na inicialização.

O formato novo é ``local_database/saved_queues_json/users/<id>.json`` (ver ``empiremuse.serialization.queue``). O ``.pkl`` de
``saved_queues_v1/users/`` só é LIDO, pelo ``load_legacy``, e é apagado depois que o JSON equivalente foi gravado, relido e
validado. Fila ilegível vira ``GenericError`` ("incompatível") e o arquivo é mantido; nada do conteúdo vai ao log.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import aiofiles

from empiremuse import paths
from empiremuse.serialization.files import write_private_atomic
from empiremuse.serialization.legacy_pickle import MAX_RAW, LegacyFormatError, load_legacy
from empiremuse.serialization.queue import MAX_BYTES, decode_saved_queue, encode_saved_queue, normalize_legacy_queue
from empiremuse.serialization.schema import TOO_BIG, SchemaError
from empiremuse.utils.music.errors import GenericError

logger = logging.getLogger(__name__)

LEGACY_NAME = re.compile(r"[0-9]{1,20}\.pkl")


def _users_dir(folder: str) -> Path:
    return paths.RUNTIME_DIR / "local_database" / folder / "users"


def saved_queue_path(user_id: Union[int, str]) -> Path:
    return _users_dir("saved_queues_json") / f"{int(user_id)}.json"


def legacy_saved_queue_path(user_id: Union[int, str]) -> Path:
    return _users_dir("saved_queues_v1") / f"{int(user_id)}.pkl"


def has_saved_queue(user_id: Union[int, str]) -> bool:
    return saved_queue_path(user_id).is_file() or legacy_saved_queue_path(user_id).is_file()


def _incompatible() -> GenericError:
    return GenericError(
        "**A sua fila salva está em um formato incompatível e não pôde ser carregada.**\n"
        "O arquivo foi mantido; salve a fila de novo para substituí-la."
    )


async def _read_limited(path: Path, limit: int) -> Optional[bytes]:
    """Até ``limit + 1`` bytes do arquivo (o excedente acusa tamanho acima do teto sem ler o arquivo todo), ou ``None``."""
    try:
        async with aiofiles.open(path, "rb") as file:
            return await file.read(limit + 1)
    except FileNotFoundError:
        return None


def _read_capped(path: Path, limit: int) -> bytes:
    """Até ``limit`` bytes do arquivo; maior que o teto é ``SchemaError`` (``too_big``), sem ler o arquivo todo.

    Regra para toda leitura de arquivo de dados: conferir o tamanho (``lstat``) ANTES de ler e nunca pedir mais que
    ``limit + 1`` bytes. O ``open`` segue link simbólico; quem fecha o caso é o teto no ``read``, e a migração nem chega aqui
    com link (``migrate_saved_queues`` ignora entradas que não são arquivos comuns).
    """
    if path.lstat().st_size > limit:
        raise SchemaError("", TOO_BIG)
    with open(path, "rb") as file:
        raw = file.read(limit + 1)
    if len(raw) > limit:
        raise SchemaError("", TOO_BIG)
    return raw


def _write_and_verify(path: Path, raw: bytes) -> None:
    write_private_atomic(path, raw)
    decode_saved_queue(_read_capped(path, MAX_BYTES))


async def _migrate_after_read(user_id: Union[int, str], data: dict) -> None:
    """Grava o JSON da fila lida do ``.pkl``, confere e só então apaga o ``.pkl``; falhar não impede a reprodução."""
    try:
        raw = encode_saved_queue(data["tracks"], data["created_at"], data["guild_id"])
        await asyncio.get_running_loop().run_in_executor(None, _write_and_verify, saved_queue_path(user_id), raw)
        legacy_saved_queue_path(user_id).unlink()
    except (OSError, SchemaError) as error:
        logger.warning("Fila salva lida do formato antigo, mas não migrada: %s", type(error).__name__)


async def load_saved_queue(user_id: Union[int, str], guild_id: Union[int, str]) -> dict:
    """``{"tracks": [info...], "created_at", "guild_id"}`` da fila salva do usuário, ou ``GenericError``."""
    loop = asyncio.get_running_loop()
    raw = await _read_limited(saved_queue_path(user_id), MAX_BYTES)
    if raw is not None:
        try:
            return await loop.run_in_executor(None, decode_saved_queue, raw)
        except SchemaError as error:
            logger.warning("Fila salva ignorada (formato incompatível): servidor %s, motivo %s", guild_id, error.code)
            raise _incompatible() from None

    raw = await _read_limited(legacy_saved_queue_path(user_id), MAX_RAW["queue"])
    if raw is None:
        raise GenericError("**A sua fila salva já foi excluída...**")
    try:
        document = await loop.run_in_executor(None, lambda: load_legacy(raw, "queue"))
        data = normalize_legacy_queue(document)
    except SchemaError as error:  # inclui LegacyFormatError
        logger.warning("Fila salva ignorada (formato incompatível): servidor %s, motivo %s", guild_id, error.code)
        raise _incompatible() from None
    await _migrate_after_read(user_id, data)
    return data


async def store_saved_queue(user_id: Union[int, str], tracks: list, guild_id: int, created_at: datetime) -> None:
    """Grava a fila em JSON (atômico, 0600) e apaga o ``.pkl`` antigo do mesmo usuário."""
    try:
        raw = encode_saved_queue(tracks, created_at, guild_id)
    except SchemaError as error:
        logger.warning(
            "Fila não salva (dados incompatíveis): servidor %s, campo %s, motivo %s", guild_id, error.path, error.code
        )
        raise GenericError(
            "**Não foi possível salvar a fila: alguma música tem dados incompatíveis com o formato de armazenamento.**"
        ) from None
    try:
        await asyncio.get_running_loop().run_in_executor(None, write_private_atomic, saved_queue_path(user_id), raw)
    except OSError as error:
        logger.warning("Fila não salva (falha ao gravar): servidor %s, motivo %s", guild_id, type(error).__name__)
        raise GenericError("**Não foi possível salvar a fila agora. Tente novamente em instantes.**") from None
    try:
        legacy_saved_queue_path(user_id).unlink()
    except OSError:
        pass


# ============================================================================ migração na inicialização


def _json_is_valid(path: Path) -> bool:
    try:
        decode_saved_queue(_read_capped(path, MAX_BYTES))
    except (OSError, SchemaError):
        return False
    return True


def _migrate_file(legacy: Path, target: Path) -> bool:
    """Converte um ``.pkl`` em JSON. ``True`` se gravou o JSON novo; o ``.pkl`` só sai depois do JSON relido e válido."""
    if target.is_file() and _json_is_valid(target) and legacy.stat().st_mtime <= target.stat().st_mtime:
        legacy.unlink()  # o JSON é mais novo: o ``.pkl`` é só resto
        return False
    document = load_legacy(_read_capped(legacy, MAX_RAW["queue"]), "queue")
    data = normalize_legacy_queue(document)
    _write_and_verify(target, encode_saved_queue(data["tracks"], data["created_at"], data["guild_id"]))
    legacy.unlink()
    return True


def migrate_saved_queues() -> int:
    """Converte os ``.pkl`` de ``saved_queues_v1/users/`` (nome só de dígitos) em JSON; devolve quantos converteu.

    O que não converte (protocolo antigo, esquema, nome fora do padrão, link simbólico) fica onde está.
    """
    try:
        with os.scandir(_users_dir("saved_queues_v1")) as scanner:
            entries = sorted(scanner, key=lambda entry: entry.name)
    except OSError:
        return 0
    converted = 0
    for entry in entries:
        if not LEGACY_NAME.fullmatch(entry.name) or not entry.is_file(follow_symlinks=False):
            continue
        user_id = entry.name[:-4]
        try:
            if _migrate_file(Path(entry.path), saved_queue_path(user_id)):
                converted += 1
        except (OSError, SchemaError) as error:  # inclui LegacyFormatError
            logger.warning(
                "Fila salva antiga não migrada (usuário %s): %s", user_id, getattr(error, "code", type(error).__name__)
            )
    return converted

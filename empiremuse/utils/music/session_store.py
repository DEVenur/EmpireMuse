"""Armazenamento das sessões do player: disco e Mongo em JSON.

Formatos (ver ``empiremuse.serialization.session``):

* disco: ``local_database/player_sessions_json/<bot>/<servidor>.json`` (atômico, 0600) e a cópia ``<servidor>.json.bak``;
* Mongo: coleção ``player_sessions_json`` do banco do bot, um documento ``{_id, v, data}`` por servidor, com ``data`` =
  ``base64(zlib(JSON))``.

A leitura só devolve dicionários do JSON validado e confere o ``_id`` do conteúdo contra o do nome/documento. O que falhar fica
onde está, com um aviso só com o servidor e o motivo (nunca o conteúdo). As sessões do formato antigo (``player_sessions/``
e a coleção ``player_sessions``) não são lidas nem apagadas aqui; o aviso da subida está em ``legacy_notice``.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import re
from contextlib import aclosing
from pathlib import Path
from typing import Any

from empiremuse import paths
from empiremuse.serialization.codec import pack, unpack
from empiremuse.serialization.files import read_capped, write_private_atomic
from empiremuse.serialization import session as session_codec
from empiremuse.serialization.schema import DEPTH, PATTERN, VERSION, SchemaError
from empiremuse.serialization.session import MAX_BYTES, decode_session

logger = logging.getLogger(__name__)

NEW_COLLECTION = "player_sessions_json"
DOCUMENT_VERSION = 1
MAX_PACKED = 12 * 1024 * 1024  # texto base64 do Mongo (8 MiB de JSON comprimido e em base64 cabem folgados)

GUILD_ID = re.compile(r"[0-9]{1,20}")
JSON_NAME = re.compile(r"[0-9]{1,20}\.json")


def sessions_dir(bot_id: int | str) -> Path:
    return paths.RUNTIME_DIR / "local_database" / "player_sessions_json" / str(bot_id)


def _reason(error: Exception) -> str:
    """O motivo que vai ao log: o código do esquema ou o tipo da falha, nunca a mensagem (pode ter dado de fora)."""
    return getattr(error, "code", type(error).__name__)


# ============================================================================ cópia e codificação (fora do laço)


def snapshot(data: dict) -> dict:
    """Cópia dos dados do player, tirada NO laço antes de a codificação ir para a thread.

    O player continua mudando o ``info`` das faixas e as filas; a thread só lê a cópia. Custa ~0,1 s no teto (a validação
    e a codificação, que custam ~0,9 s, é que saem do laço).
    """
    try:
        return copy.deepcopy(data)
    except RecursionError:
        raise SchemaError("", DEPTH) from None


def encode_for_mongo(copy_of_data: dict) -> dict:
    """O documento da coleção nova a partir da cópia dos dados (tudo numa thread)."""
    return new_document(session_codec.encode_session(copy_of_data))


def encode_for_disk(bot_id: int | str, guild_id: int | str, copy_of_data: dict) -> None:
    """Codifica e grava o arquivo da sessão (tudo numa thread); ``SchemaError`` se os dados não valem, ``OSError`` se não gravou."""
    write_session_file(bot_id, guild_id, session_codec.encode_session(copy_of_data))


# ============================================================================ disco


def write_session_file(bot_id: int | str, guild_id: int | str, raw: bytes) -> None:
    """Grava o JSON da sessão e a cópia ``.bak``; falha ao gravar o JSON levanta ``OSError`` e deixa o antigo."""
    path = sessions_dir(bot_id) / f"{int(guild_id)}.json"
    write_private_atomic(path, raw)
    try:
        write_private_atomic(path.with_name(f"{path.name}.bak"), raw)
    except OSError as error:
        logger.warning("Cópia da sessão não gravada: servidor %s, motivo %s", guild_id, _reason(error))


def read_local_sessions(bot_id: int | str) -> list[dict]:
    """As sessões válidas de ``player_sessions_json/<bot>/``; arquivo ruim é pulado e mantido."""
    try:
        with os.scandir(sessions_dir(bot_id)) as scanner:
            entries = sorted(scanner, key=lambda entry: entry.name)
    except OSError:
        return []
    sessions = []
    for entry in entries:
        try:
            if not JSON_NAME.fullmatch(entry.name) or not entry.is_file(follow_symlinks=False):
                continue
            guild_id = int(entry.name[:-5])
            sessions.append(decode_session(read_capped(Path(entry.path), MAX_BYTES), expected_id=guild_id))
        except (OSError, SchemaError) as error:
            logger.warning("Sessão do player ignorada: arquivo %s, motivo %s", entry.name[:25], _reason(error))
    return sessions


def delete_local_session(bot_id: int | str, guild_id: int | str) -> None:
    """Remove o JSON e a cópia do servidor; o que não existe é ignorado."""
    guild = int(guild_id)
    targets = (
        sessions_dir(bot_id) / f"{guild}.json",
        sessions_dir(bot_id) / f"{guild}.json.bak",
    )
    for path in targets:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as error:
            logger.warning("Sessão do player não removida: servidor %s, motivo %s", guild, _reason(error))


# ============================================================================ Mongo


def _document_guild(document: dict) -> int:
    identifier = document.get("_id")
    if type(identifier) is not str or not GUILD_ID.fullmatch(identifier):
        raise SchemaError("_id", PATTERN)
    return int(identifier)


def _label(document: dict) -> str:
    """O ``_id`` do documento para o log, só se parecer um servidor (o resto pode ser qualquer texto)."""
    identifier = document.get("_id")
    return identifier if type(identifier) is str and GUILD_ID.fullmatch(identifier) else "inválido"


def new_document(raw: bytes) -> dict:
    return {"v": DOCUMENT_VERSION, "data": pack(raw)}


def decode_document(document: dict) -> dict:
    """A sessão de um documento da coleção nova (versão, tamanho, envelope, esquema e ``_id``) ou ``SchemaError``."""
    guild_id = _document_guild(document)
    version = document.get("v")
    if type(version) is not int or version != DOCUMENT_VERSION:
        raise SchemaError("v", VERSION)
    raw = unpack(document.get("data"), max_packed=MAX_PACKED, max_unpacked=MAX_BYTES)
    return decode_session(raw, expected_id=guild_id)


async def read_mongo_sessions(database: Any, db_name: str) -> list[dict]:
    """As sessões válidas da coleção nova, lidas por cursor; documento ruim é pulado e mantido."""
    loop = asyncio.get_running_loop()
    sessions = []
    async with aclosing(database.iter_data(db_name=db_name, collection=NEW_COLLECTION)) as cursor:
        async for document in cursor:
            try:
                sessions.append(await loop.run_in_executor(None, decode_document, document))
            except SchemaError as error:
                logger.warning("Sessão do player ignorada: servidor %s, motivo %s", _label(document), error.code)
    return sessions


async def delete_mongo_session(database: Any, db_name: str, guild_id: int | str) -> None:
    """Remove o documento do servidor."""
    await database.delete_data(id_=str(guild_id), db_name=db_name, collection=NEW_COLLECTION)

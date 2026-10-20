"""Armazenamento das sessões do player: disco e Mongo em JSON, e a migração do legado em ``pickle``.

Formatos (ver ``empiremuse.serialization.session``):

* disco: ``local_database/player_sessions_json/<bot>/<servidor>.json`` (atômico, 0600) e a cópia ``<servidor>.json.bak``;
* Mongo: coleção ``player_sessions_json`` do banco do bot, um documento ``{_id, v, data}`` por servidor, com ``data`` =
  ``base64(zlib(JSON))``.

A leitura só devolve dicionários do JSON validado e confere o ``_id`` do conteúdo contra o do nome/documento. O que falhar fica
onde está, com um aviso só com o servidor e o motivo (nunca o conteúdo). O legado (``player_sessions/<bot>/*.pkl|*.bak`` e a
coleção ``player_sessions``) só é lido pela migração, pelo ``load_legacy``: grava o JSON, relê, valida e só então apaga o antigo.
O que não converte por defeito do próprio dado (esquema, protocolo, tamanho, ``_id``) é apagado depois de 48 h; erro transitório
(disco, rede) nunca grava marca nem apaga.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import math
import os
import re
import stat
import time
from contextlib import aclosing, suppress
from pathlib import Path
from typing import Any

from empiremuse import paths
from empiremuse.serialization.codec import pack, unpack
from empiremuse.serialization.files import read_capped, write_private_atomic
from empiremuse.serialization.legacy_pickle import MAX_RAW, load_legacy
from empiremuse.serialization import session as session_codec
from empiremuse.serialization.schema import DEPTH, PATTERN, TYPE, VERSION, SchemaError
from empiremuse.serialization.session import MAX_BYTES, decode_session, validate_session

logger = logging.getLogger(__name__)

NEW_COLLECTION = "player_sessions_json"
LEGACY_COLLECTION = "player_sessions"
DOCUMENT_VERSION = 1
MAX_PACKED = 12 * 1024 * 1024  # texto base64 do Mongo (8 MiB de JSON comprimido e em base64 cabem folgados)

FAILED_WINDOW = 48 * 3600  # segundos até o legado que não converte ser apagado
MIGRATION_BATCH = 10
MIGRATION_PAUSE = 0.5  # segundos ENTRE lotes, para não competir com a subida do bot
MIGRATION_CAP = 500  # documentos do Mongo olhados por subida (as falhas também contam)

GUILD_ID = re.compile(r"[0-9]{1,20}")
JSON_NAME = re.compile(r"[0-9]{1,20}\.json")
LEGACY_NAME = re.compile(r"(?P<id>[0-9]{1,20})\.(?P<ext>pkl|bak)")


def sessions_dir(bot_id: int | str) -> Path:
    return paths.RUNTIME_DIR / "local_database" / "player_sessions_json" / str(bot_id)


def legacy_dir(bot_id: int | str) -> Path:
    return paths.RUNTIME_DIR / "local_database" / "player_sessions" / str(bot_id)


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
    """Remove o JSON, a cópia e os restos do legado (``.pkl`` e ``.bak``) do servidor; o que não existe é ignorado."""
    guild = int(guild_id)
    targets = (
        sessions_dir(bot_id) / f"{guild}.json",
        sessions_dir(bot_id) / f"{guild}.json.bak",
        legacy_dir(bot_id) / f"{guild}.pkl",
        legacy_dir(bot_id) / f"{guild}.bak",
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
    """Remove o documento do servidor dos dois formatos (o legado também, se ainda estiver lá)."""
    for collection in (NEW_COLLECTION, LEGACY_COLLECTION):
        await database.delete_data(id_=str(guild_id), db_name=db_name, collection=collection)


# ============================================================================ migração do disco


def _remove_all(files: list[Path], guild_id: int) -> None:
    for path in files:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as error:
            logger.warning("Resto da sessão antiga não removido: servidor %s, motivo %s", guild_id, _reason(error))


def _json_supersedes(target: Path, guild_id: int, legacy_files: list[Path]) -> bool:
    """O JSON já existe, vale e não é mais velho que o legado: o legado é só resto."""
    try:
        if not stat.S_ISREG(target.lstat().st_mode):
            return False
        decode_session(read_capped(target, MAX_BYTES), expected_id=guild_id)
        newest = max(path.lstat().st_mtime for path in legacy_files)
        return newest <= target.lstat().st_mtime
    except (OSError, SchemaError):
        return False


def _convert_legacy_file(path: Path, guild_id: int) -> bytes:
    """O JSON da sessão do ``.pkl``/``.bak``; ``SchemaError`` (inclui o legado) se o dado não vale, ``OSError`` se não leu."""
    document = load_legacy(read_capped(path, MAX_RAW["session"]), "session")
    return session_codec.encode_session(validate_session(document, expected_id=guild_id))


def _write_and_verify(target: Path, raw: bytes, guild_id: int) -> None:
    write_private_atomic(target, raw)
    try:
        decode_session(read_capped(target, MAX_BYTES), expected_id=guild_id)
    except SchemaError:
        with suppress(OSError):
            target.unlink()  # a saída é nossa e saiu ruim: o legado continua sendo a fonte
        raise


def _on_permanent_failure(path: Path, guild_id: int, error: SchemaError) -> None:
    logger.warning("Sessão antiga não migrada: servidor %s, motivo %s", guild_id, error.code)
    try:
        if time.time() - path.lstat().st_mtime > FAILED_WINDOW:
            path.unlink()
            logger.info("Sessão antiga descartada (mais de 48 h sem converter): servidor %s", guild_id)
    except OSError as failure:
        logger.warning("Sessão antiga não descartada: servidor %s, motivo %s", guild_id, _reason(failure))


def _migrate_guild(bot_id: int | str, guild_id: int, files: dict[str, Path]) -> None:
    target = sessions_dir(bot_id) / f"{guild_id}.json"
    ordered = [files[ext] for ext in ("pkl", "bak") if ext in files]
    if _json_supersedes(target, guild_id, ordered):
        _remove_all(ordered, guild_id)
        return
    for path in ordered:
        try:
            raw = _convert_legacy_file(path, guild_id)
        except SchemaError as error:
            _on_permanent_failure(path, guild_id, error)
            continue
        except OSError as error:
            logger.warning("Sessão antiga não lida: servidor %s, motivo %s", guild_id, _reason(error))
            return
        try:
            _write_and_verify(target, raw, guild_id)
        except (OSError, SchemaError) as error:
            logger.warning("Sessão antiga não migrada (gravação): servidor %s, motivo %s", guild_id, _reason(error))
            return
        _remove_all(ordered, guild_id)
        return


def _legacy_files(bot_id: int | str) -> dict[int, dict[str, Path]]:
    """``{servidor: {"pkl": caminho, "bak": caminho}}`` só com arquivos comuns de nome ``<dígitos>.pkl|bak``."""
    try:
        with os.scandir(legacy_dir(bot_id)) as scanner:
            entries = list(scanner)
    except OSError:
        return {}
    grouped: dict[int, dict[str, Path]] = {}
    for entry in entries:
        match = LEGACY_NAME.fullmatch(entry.name)
        try:
            if match and entry.is_file(follow_symlinks=False):
                grouped.setdefault(int(match["id"]), {})[match["ext"]] = Path(entry.path)
        except OSError as error:
            logger.warning("Sessão antiga ignorada: motivo %s", _reason(error))
    return dict(sorted(grouped.items()))


def migrate_disk(bot_id: int | str) -> None:
    """Converte os ``.pkl``/``.bak`` de ``player_sessions/<bot>/`` em JSON (bloqueante: rode num executor)."""
    for guild_id, files in _legacy_files(bot_id).items():
        try:
            _migrate_guild(bot_id, guild_id, files)
        except Exception as error:  # arquivo de fora: defeito de um servidor não derruba a subida nem os outros
            logger.warning("Sessão antiga não migrada: servidor %s, motivo %s", guild_id, _reason(error))


# ============================================================================ migração do Mongo


def _is_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _convert_legacy_document(document: dict, guild_id: int) -> dict:
    """O documento novo da sessão do legado; ``SchemaError`` (inclui o legado) se o dado não vale."""
    text = document.get("data")
    if type(text) is not str:
        raise SchemaError("data", TYPE)
    clean = validate_session(load_legacy(text, "session"), expected_id=guild_id)
    return new_document(session_codec.encode_session(clean))


async def _on_document_failure(database: Any, db_name: str, document: dict, error: SchemaError) -> None:
    """Marca ``failed_at`` uma vez; passadas 48 h dele, apaga o documento. Falha do banco não derruba a migração."""
    logger.warning("Sessão antiga do Mongo não migrada: servidor %s, motivo %s", _label(document), error.code)
    failed_at = document.get("failed_at")
    try:
        if not _is_number(failed_at):
            data = {"failed_at": time.time()}
            await database.update_data(id_=document["_id"], data=data, db_name=db_name, collection=LEGACY_COLLECTION)
        elif time.time() - failed_at > FAILED_WINDOW:
            await database.delete_data(id_=document["_id"], db_name=db_name, collection=LEGACY_COLLECTION)
            logger.info("Sessão antiga do Mongo descartada (mais de 48 h sem converter): servidor %s", _label(document))
    except Exception as failure:  # erro de rede: tenta de novo na próxima subida
        logger.warning("Sessão antiga do Mongo não marcada: servidor %s, motivo %s", _label(document), _reason(failure))


async def _store_verify_and_delete(database: Any, db_name: str, document: dict, packed: dict) -> None:
    identifier = document["_id"]
    await database.update_data(id_=identifier, data=packed, db_name=db_name, collection=NEW_COLLECTION)
    async with aclosing(
        database.iter_data(db_name=db_name, collection=NEW_COLLECTION, filter={"_id": identifier})
    ) as cursor:
        stored = await anext(cursor, None)
    if stored is None:
        raise SchemaError("_id", "missing")
    await asyncio.get_running_loop().run_in_executor(None, decode_document, stored)
    await database.delete_data(id_=identifier, db_name=db_name, collection=LEGACY_COLLECTION)


async def _migrate_document(database: Any, db_name: str, document: dict) -> None:
    try:
        guild_id = _document_guild(document)
        packed = await asyncio.get_running_loop().run_in_executor(None, _convert_legacy_document, document, guild_id)
    except SchemaError as error:
        await _on_document_failure(database, db_name, document, error)
        return
    try:
        await _store_verify_and_delete(database, db_name, document, packed)
    except Exception as error:  # banco/rede ou releitura que não conferiu: o legado fica, sem marca
        logger.warning("Sessão antiga do Mongo não migrada: servidor %s, motivo %s", guild_id, _reason(error))


async def migrate_mongo(database: Any, db_name: str) -> None:
    """Converte os documentos de ``player_sessions`` lidos por cursor: lotes de 10, pausa entre lotes e teto por subida."""
    seen = 0
    try:
        async with aclosing(database.iter_data(db_name=db_name, collection=LEGACY_COLLECTION)) as cursor:
            async for document in cursor:
                if seen >= MIGRATION_CAP:
                    logger.info(
                        "Migração das sessões limitada a %s documentos por subida; o resto fica para a próxima",
                        MIGRATION_CAP,
                    )
                    break
                if seen and seen % MIGRATION_BATCH == 0:
                    await asyncio.sleep(MIGRATION_PAUSE)
                seen += 1
                await _migrate_document(database, db_name, document)
    except Exception as error:  # banco fora do ar: a subida segue sem migrar
        logger.warning("Migração das sessões do Mongo interrompida: motivo %s", _reason(error))

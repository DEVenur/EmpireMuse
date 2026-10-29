"""Regras puras do documento único por servidor (item 11, P1): modelo, validação, migração do principal e a visão no formato antigo.

O documento fica na coleção ``servers`` do banco global (``_id = str(gid)``). Aqui só há dados e decisões; o banco e a trava são do
``utils/servers``. A migração de ``settings`` copia só o documento antigo do bot principal (os das reservas são ignorados) e todo
valor inválido cai no padrão (contrato §2).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from empiremuse.rules.limits import CUSTOM_SKIN_PREFIX, MAX_DJ_ROLES, VOLUMES

DOC_VERSION = 1.0
SECTION_SETTINGS = "settings"
MIGRATED_SECTIONS = ("settings", "request", "playlists")

SETTINGS_FIELDS = (
    "djroles",
    "default_player_volume",
    "autoplay",
    "enable_restrict_mode",
    "check_other_bots_in_vc",
    "skin",
    "static_skin",
)
FLAG_FIELDS = ("autoplay", "enable_restrict_mode", "check_other_bots_in_vc")
SKIN_MAX_LENGTH = 100
MAIN_IDENTIFIERS = ("TOKEN", "TOKEN_1")  # o principal é o token principal, nunca o primeiro por ordem (contrato §3)

_ROLE_ID = re.compile(r"[0-9]{1,20}")
_LEGACY_CONTROLLER_KEYS = {"skin": "skin", "static_skin": "static_skin"}


class SettingError(ValueError):
    """Campo desconhecido ou valor inválido numa alteração de ``settings`` (erro de programação, nunca texto do usuário)."""


@dataclass(frozen=True)
class Allowed:
    """O que existe no mundo no momento: skins e ids de cargos do servidor."""

    skins: frozenset[str] = frozenset()
    static_skins: frozenset[str] = frozenset()
    role_ids: frozenset[str] = frozenset()


# ---------------------------------------------------------------------- modelo


def default_settings() -> dict[str, Any]:
    return {
        "djroles": [],
        "default_player_volume": 100,
        "autoplay": False,
        "enable_restrict_mode": False,
        "check_other_bots_in_vc": False,
        "skin": None,
        "static_skin": None,
    }


def new_doc() -> dict[str, Any]:
    return {
        "ver": DOC_VERSION,
        "rev": 0,
        "settings": default_settings(),
        "request": {"channel": None, "message_id": None, "panel_bot_id": None},
        "playlists": [],
        "migrated": {section: False for section in MIGRATED_SECTIONS},
    }


def is_main_identifier(identifier: object) -> bool:
    return identifier in MAIN_IDENTIFIERS


# ---------------------------------------------------------------------- validação


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def normalize_role_ids(raw: object) -> list[str]:
    """Lista de ids de cargo como texto, na ordem; levanta ``SettingError`` se não for lista de ids, tiver repetido ou passar de 25."""
    if not isinstance(raw, (list, tuple)):
        raise SettingError("djroles deve ser uma lista")
    ids: list[str] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, str)) or not _ROLE_ID.fullmatch(str(item)):
            raise SettingError("djroles tem um id de cargo inválido")
        if str(item) in ids:
            raise SettingError("djroles tem cargos repetidos")
        ids.append(str(item))
    if len(ids) > MAX_DJ_ROLES:
        raise SettingError(f"djroles passa de {MAX_DJ_ROLES} cargos")
    return ids


def clean_role_ids(raw: object, role_ids: Collection[str] | None = None) -> list[str]:
    """Versão tolerante para dados antigos: descarta o que não é id, o repetido, o cargo que não existe mais (se ``role_ids``) e o excedente."""
    ids: list[str] = []
    for item in raw if isinstance(raw, (list, tuple)) else ():
        text = str(item)
        if isinstance(item, bool) or not isinstance(item, (int, str)) or not _ROLE_ID.fullmatch(text):
            continue
        if text in ids or (role_ids is not None and text not in role_ids):
            continue
        ids.append(text)
    return ids[:MAX_DJ_ROLES]


def valid_skin(value: object, known: Collection[str]) -> bool:
    """``None`` (padrão), uma skin existente ou uma skin própria do servidor (prefixo fixo) de tamanho razoável."""
    if value is None:
        return True
    if not isinstance(value, str) or not value or len(value) > SKIN_MAX_LENGTH:
        return False
    return value in known or value.startswith(CUSTOM_SKIN_PREFIX)


def _field_error(name: str, value: object, allowed: Allowed) -> str | None:
    if name == "default_player_volume":
        return None if _is_int(value) and value in VOLUMES else "volume fora da lista"
    if name in FLAG_FIELDS:
        return None if isinstance(value, bool) else f"{name} deve ser booleano"
    if name == "skin":
        return None if valid_skin(value, allowed.skins) else "skin inexistente"
    if name == "static_skin":
        return None if valid_skin(value, allowed.static_skins) else "skin estática inexistente"
    return None


def validate_changes(changes: Mapping[str, Any], allowed: Allowed) -> dict[str, Any]:
    """As alterações de ``settings`` validadas e normalizadas; levanta ``SettingError`` no primeiro campo desconhecido ou inválido."""
    clean: dict[str, Any] = {}
    for name, value in changes.items():
        if name not in SETTINGS_FIELDS:
            raise SettingError(f"campo desconhecido: {name}")
        if name == "djroles":
            clean[name] = normalize_role_ids(value)
        elif (error := _field_error(name, value, allowed)) is not None:
            raise SettingError(error)
        else:
            clean[name] = value
    return clean


# ---------------------------------------------------------------------- formato antigo


def _legacy_value(name: str, flat: Mapping[str, Any]) -> tuple[bool, Any]:
    source = (flat.get("player_controller") or {}) if name in _LEGACY_CONTROLLER_KEYS else flat
    key = _LEGACY_CONTROLLER_KEYS.get(name, name)
    return (True, source[key]) if key in source else (False, None)


def settings_from_legacy(flat: Mapping[str, Any]) -> dict[str, Any]:
    """Os campos de ``settings`` de um documento no formato antigo (ausente = padrão; ``djroles`` sempre como texto)."""
    settings = default_settings()
    for name in SETTINGS_FIELDS:
        found, value = _legacy_value(name, flat)
        if found:
            settings[name] = deepcopy(value)
    settings["djroles"] = [str(role_id) for role_id in settings["djroles"] or []]
    return settings


def to_legacy(base: Mapping[str, Any], settings: Mapping[str, Any]) -> dict[str, Any]:
    """O documento no formato antigo: ``base`` (o documento por bot, com canal/mensagem/favoritos) com ``settings`` por cima."""
    flat = deepcopy(dict(base))
    controller = flat.setdefault("player_controller", {})
    for name in SETTINGS_FIELDS:
        value = deepcopy(settings[name])
        if name in _LEGACY_CONTROLLER_KEYS:
            controller[_LEGACY_CONTROLLER_KEYS[name]] = value
        else:
            flat[name] = value
    return flat


def changed_settings(flat: Mapping[str, Any], seen: Mapping[str, Any]) -> dict[str, Any]:
    """Os campos de ``settings`` do documento antigo que diferem do que o escritor leu (vazio = ele não mexeu em ``settings``)."""
    now = settings_from_legacy(flat)
    return {name: now[name] for name in SETTINGS_FIELDS if now[name] != seen.get(name)}


# ---------------------------------------------------------------------- migração


def migrate_settings(legacy: Mapping[str, Any] | None, allowed: Allowed) -> dict[str, Any]:
    """``settings`` a partir do documento antigo do principal (``None`` = ele não tinha). Campo ausente ou inválido fica no padrão,
    EXCETO ``enable_restrict_mode`` presente e inválido, que vira ligado (falha fechada, S-V12); ``djroles`` perde só os ids ruins
    (malformados, repetidos ou de cargo que não existe mais)."""
    settings = default_settings()
    if legacy is None:
        return settings
    for name in SETTINGS_FIELDS:
        found, value = _legacy_value(name, legacy)
        if not found:
            continue
        if name == "djroles":
            settings[name] = clean_role_ids(value, allowed.role_ids)
        elif _field_error(name, value, allowed) is None:
            settings[name] = deepcopy(value)
        elif name == "enable_restrict_mode":
            settings[name] = True
    return settings

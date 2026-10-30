"""Erro de regra: um código estável e os dados que a camada precisa para escrever a mensagem dela.

As regras nunca montam texto para o usuário: o Discord (com negrito e crases) e o painel (texto simples) traduzem o
código cada um do seu jeito.
"""

from __future__ import annotations

from typing import Any, NamedTuple

NAME_INVALID = "name_invalid"
NAME_TAKEN = "name_taken"
NAME_TOO_LONG = "name_too_long"
URL_INVALID = "url_invalid"
URL_TOO_LONG = "url_too_long"
AVATAR_INVALID = "avatar_invalid"
DESCRIPTION_INVALID = "description_invalid"
DESCRIPTION_TOO_LONG = "description_too_long"
ITEM_FORMAT = "item_format"
QUOTA_FULL = "quota_full"
FILE_TOO_LARGE = "file_too_large"
NO_SPACE = "no_space"
PREFIX_EMPTY = "prefix_empty"
PREFIX_LENGTH = "prefix_length"
PREFIX_CHARS = "prefix_chars"
STATUS_TOO_LONG = "status_too_long"
STATUS_CHARS = "status_chars"
STATUS_NO_PLACEHOLDER = "status_no_placeholder"
ROLE_LIMIT = "role_limit"
ROLE_DUPLICATE = "role_duplicate"
ROLE_INVALID = "role_invalid"
URL_TAKEN = "url_taken"
PLAYLIST_NOT_FOUND = "playlist_not_found"
FILE_FORMAT = "file_format"
FILE_TOO_MANY = "file_too_many"
GENRES_INVALID = "genres_invalid"
ORDER_INVALID = "order_invalid"
IMPORT_URL_REFUSED = "import_url_refused"
IMPORT_FETCH_FAILED = "import_fetch_failed"


class RuleError(NamedTuple):
    """``code`` diz o que falhou; ``key`` é o nome do item do arquivo; ``value`` é o valor recusado; ``limit`` o limite."""

    code: str
    key: str = ""
    value: Any = None
    limit: int = 0

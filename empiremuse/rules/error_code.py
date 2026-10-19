"""Código curto de erro (``ERR-7F3A2C``) para cruzar o relato do usuário com o log e o webhook.

Aleatório puro de ``secrets``: não deriva de ID, token, hora nem do texto do erro, então não vaza nada. Colisão é aceitável
(o log tem data, servidor e origem; o código só desempata).
"""

from __future__ import annotations

import logging
import re
import secrets

logger = logging.getLogger(__name__)

ERROR_CODE_PREFIX = "ERR-"
ERROR_CODE_BYTES = 3  # 3 bytes = 6 hexadecimais = 24 bits
ERROR_CODE_RE = re.compile(r"ERR-[0-9A-F]{6}")


def new_error_code() -> str:
    """Um código novo, por exemplo ``ERR-7F3A2C``."""
    return ERROR_CODE_PREFIX + secrets.token_hex(ERROR_CODE_BYTES).upper()


def safe_error_code() -> str:
    """Como ``new_error_code``, mas devolve ``""`` se não der para gerar: o tratamento de erro nunca pode falhar por isso."""
    try:
        return new_error_code()
    except Exception as exc:  # noqa: BLE001 - qualquer falha aqui cai na mensagem genérica sem código
        logger.warning("Não foi possível gerar o código de erro (%s).", type(exc).__name__)
        return ""

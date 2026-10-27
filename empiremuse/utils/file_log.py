"""Log em arquivo do bot (``.logs/disnake.log``): rotativo, em append, sem segredos e só para o dono do processo."""

from __future__ import annotations

import logging
import logging.handlers
import os
from contextlib import suppress
from pathlib import Path

from empiremuse.logs.console import FileFormatter, report_emit_failure
from empiremuse.logs.redact import REDACTED, SanitizeAndRedact

LOG_FILE_NAME = "disnake.log"
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024
LOG_FILE_BACKUPS = 3
LOG_DIR_MODE = 0o700
LOG_FILE_MODE = 0o600

__all__ = [
    "LOG_FILE_NAME",
    "REDACTED",
    "PrivateRotatingFileHandler",
    "RedactWebhookTokens",
    "build_file_log_handler",
    "ensure_private_logs_dir",
]

# Nome antigo do filtro de redação: hoje é o redator único do pacote ``logs`` (webhooks, tokens, credenciais e controles).
RedactWebhookTokens = SanitizeAndRedact


class PrivateRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """``RotatingFileHandler`` cujo arquivo (inclusive o recriado a cada rotação) é aberto com modo 0o600 onde o SO permite."""

    def _open(self):
        with suppress(OSError):  # Windows ignora o modo; qualquer falha não pode impedir o log
            os.close(os.open(self.baseFilename, os.O_CREAT | os.O_APPEND | os.O_WRONLY, LOG_FILE_MODE))
            os.chmod(self.baseFilename, LOG_FILE_MODE)
        return super()._open()

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 (nome da API do logging)
        report_emit_failure()


def ensure_private_logs_dir(logs_dir: Path) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True, mode=LOG_DIR_MODE)
    with suppress(OSError):
        os.chmod(logs_dir, LOG_DIR_MODE)


def build_file_log_handler(logs_dir: Path) -> logging.Handler:
    """Log em arquivo com rotação (5 MB x 3) e em append: os códigos ERR-... sobrevivem a um reinício.

    Sozinho já é seguro (redator e formatter próprios). O ``configure_logging`` troca essa cadeia pela dele, compartilhada com o
    console, para o redator e o agregador valerem uma vez só por destino.
    """
    ensure_private_logs_dir(logs_dir)
    handler = PrivateRotatingFileHandler(
        filename=str(logs_dir / LOG_FILE_NAME),
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUPS,
        encoding="utf-8",
        errors="backslashreplace",  # surrogate solto (vem de json.loads) vira \udXXX em vez de derrubar o registro do arquivo
    )
    handler.addFilter(SanitizeAndRedact())
    handler.setFormatter(FileFormatter())
    return handler

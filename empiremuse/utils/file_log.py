"""Log em arquivo do bot (``.logs/disnake.log``): rotativo, em append, sem token de webhook e só para o dono do processo."""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
from contextlib import suppress
from pathlib import Path

LOG_FILE_NAME = "disnake.log"
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024
LOG_FILE_BACKUPS = 3
LOG_DIR_MODE = 0o700
LOG_FILE_MODE = 0o600

REDACTED = "***"
# .../api[/vN]/webhooks/<id>/<token>: cobre discord.com, discordapp.com, ptb., canary. (e a URL sem o host, como o disnake a loga).
_WEBHOOK_TOKEN = re.compile(r"(/api(?:/v\d+)?/webhooks/\d+/)[A-Za-z0-9._~-]+")


def redact_webhook_tokens(text: str) -> str:
    return _WEBHOOK_TOKEN.sub(rf"\1{REDACTED}", text)


class RedactWebhookTokens(logging.Filter):
    """Troca o <token> das URLs de webhook por ``***`` na mensagem já formatada (args inclusos) e no traceback.

    Nunca descarta um registro: se a redação falhar, a mensagem original é substituída por um aviso.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            if "/webhooks/" in message:
                record.msg, record.args = redact_webhook_tokens(message), None
            if record.exc_info and not record.exc_text:
                record.exc_text = redact_webhook_tokens(logging.Formatter().formatException(record.exc_info))
            elif record.exc_text:
                record.exc_text = redact_webhook_tokens(record.exc_text)
            if record.stack_info:
                record.stack_info = redact_webhook_tokens(record.stack_info)
        except Exception:
            record.msg, record.args, record.exc_info, record.exc_text = (
                "[registro omitido: falha ao redigir]",
                None,
                None,
                None,
            )
        return True


class PrivateRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """``RotatingFileHandler`` cujo arquivo (inclusive o recriado a cada rotação) é aberto com modo 0o600 onde o SO permite."""

    def _open(self):
        with suppress(OSError):  # Windows ignora o modo; qualquer falha não pode impedir o log
            os.close(os.open(self.baseFilename, os.O_CREAT | os.O_APPEND | os.O_WRONLY, LOG_FILE_MODE))
            os.chmod(self.baseFilename, LOG_FILE_MODE)
        return super()._open()


def ensure_private_logs_dir(logs_dir: Path) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True, mode=LOG_DIR_MODE)
    with suppress(OSError):
        os.chmod(logs_dir, LOG_DIR_MODE)


def build_file_log_handler(logs_dir: Path) -> logging.Handler:
    """Log em arquivo com rotação (5 MB x 3) e em append: os códigos ERR-... sobrevivem a um reinício."""
    ensure_private_logs_dir(logs_dir)
    handler = PrivateRotatingFileHandler(
        filename=str(logs_dir / LOG_FILE_NAME),
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUPS,
        encoding="utf-8",
    )
    handler.addFilter(RedactWebhookTokens())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    return handler

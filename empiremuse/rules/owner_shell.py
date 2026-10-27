"""Regras puras dos comandos de owner que executam shell: ambiente mínimo e mascaramento da saída.

``build_shell_env`` devolve só as variáveis de uma allowlist explícita, para que o ``.env`` carregado no processo não
fique visível ao comando. ``collect_secret_values`` reúne os valores de segredo conhecidos (configuração e ambiente) e
``mask_secrets`` os troca por um marcador antes de a saída ou o comando seguirem para o Discord ou para o log.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

SHELL_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "GIT_DIR")
SHELL_ENV_ALLOWLIST_WINDOWS = ("SystemRoot", "COMSPEC")

# Abaixo disso o valor vira falso positivo (um "true" ou um "0" no meio de qualquer saída).
MIN_SECRET_LENGTH = 6
MASK = "***"

# Nomes de variável cujo valor é segredo (ver .claude/rules/empiremuse/security.md, seção 1).
_SECRET_NAME = re.compile(
    r"TOKEN|SECRET|PASS|KEY|MONGO|WEBHOOK|COOKIE|CREDENTIAL|AUTH|REFRESH|LAVALINK_NODE|SPOTIFY_CLIENT|LASTFM",
    re.IGNORECASE,
)


def is_secret_name(name: str) -> bool:
    """Se o NOME de uma variável, chave ou parâmetro é de segredo (o valor nunca deve ir a log nem a relatório)."""
    return bool(_SECRET_NAME.search(str(name)))


def build_shell_env(environ: Mapping[str, str], *, windows: bool = False) -> dict[str, str]:
    """Cópia de ``environ`` só com as variáveis da allowlist (no Windows os nomes não diferenciam maiúsculas)."""
    allowed = SHELL_ENV_ALLOWLIST + (SHELL_ENV_ALLOWLIST_WINDOWS if windows else ())
    if windows:
        wanted = {name.casefold() for name in allowed}
        return {key: value for key, value in environ.items() if key.casefold() in wanted}
    return {name: environ[name] for name in allowed if name in environ}


def collect_secret_values(*sources: Mapping[str, object]) -> frozenset[str]:
    """Valores textuais de segredo (pelo nome da chave) das fontes dadas, sem os vazios nem os curtos demais."""
    values: set[str] = set()
    for source in sources:
        for key, value in source.items():
            if isinstance(value, str) and len(value) >= MIN_SECRET_LENGTH and _SECRET_NAME.search(str(key)):
                values.add(value)
    return frozenset(values)


def mask_secrets(text: str, secrets: Iterable[str]) -> str:
    """Troca cada valor de ``secrets`` em ``text`` por ``MASK``, do mais longo para o mais curto."""
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            text = text.replace(secret, MASK)
    return text

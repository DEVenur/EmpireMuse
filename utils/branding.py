"""Identidade centralizada do EmpireMuse (nome, URLs, assets e créditos).

Obra derivada de MuseHeart-MusicBot (zRitsu), licenciada sob GPL-2.0: os créditos
ao projeto original são preservados em ``UPSTREAM_*``, em ``CREDITS.md`` e em ``LICENSE``.
"""
from functools import lru_cache
from pathlib import Path

BOT_NAME = "EmpireMuse"
REPO_URL = "https://github.com/DiscordEmpireHub/EmpireMuse"
SOURCE_REPO_GIT = REPO_URL + ".git"
RAW_BASE_URL = "https://raw.githubusercontent.com/DiscordEmpireHub/EmpireMuse/main"
ASSETS_BASE_URL = RAW_BASE_URL + "/assets"
LICENSE_URL = REPO_URL + "/blob/main/LICENSE"
GUIDES_URL = REPO_URL + "/blob/main/docs/guides"
RPC_APP_URL = "https://github.com/DiscordEmpireHub/EmpireMuse-RPC-app"
RPC_APP_RELEASES_URL = RPC_APP_URL + "/releases"
LAVALINK_BINARIES_URL = "https://github.com/DiscordEmpireHub/LL-binaries/releases/download/0.0.1"
LAVALINK_JAR_URL = LAVALINK_BINARIES_URL + "/Lavalink.jar"
LAVALINK_APPLICATION_YML_URL = LAVALINK_BINARIES_URL + "/application.yml"
LAVALINK_SERVER_LIST_URL = RAW_BASE_URL + "/data/lavalink_servers.ini"
SUPPORT_SERVER_URL = "https://discord.gg/KgtyNg9U6H"
EMBED_COLOR_HEX = "8B5CF6"  # violeta da paleta Nebulosa
UPSTREAM_NAME = "MuseHeart-MusicBot"
UPSTREAM_AUTHOR = "zRitsu"
UPSTREAM_URL = "https://github.com/zRitsu/MuseHeart-MusicBot"

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


@lru_cache(maxsize=None)
def _ensure_asset_exists(name: str) -> None:
    """Valida a existência de ``assets/<name>``; só chamadas bem-sucedidas entram no cache (exceções não)."""
    if not (_ASSETS_DIR / name).is_file():
        raise ValueError(f"Asset inexistente em assets/: {name!r}")


def asset_url(name: str) -> str:
    """Retorna a URL pública de um arquivo em ``assets/``.

    Levanta ``ValueError`` se ``name`` for vazio, contiver separador de caminho
    (``/`` ou ``\\``) ou ``..``, ou se ``assets/<name>`` não existir no repositório.
    """
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"Nome de asset inválido: {name!r}")
    _ensure_asset_exists(name)
    return f"{ASSETS_BASE_URL}/{name}"

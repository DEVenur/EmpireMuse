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
LAVALINK_BINARIES_URL = "https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download/0.0.3"
LAVALINK_JAR_URL = LAVALINK_BINARIES_URL + "/Lavalink.jar"
LAVALINK_APPLICATION_YML_URL = LAVALINK_BINARIES_URL + "/application.yml"
# SHA-256 fixos dos binários da release 0.0.3 (conferem com o SHA256SUMS publicado); lidos em tempo de chamada.
LAVALINK_JAR_SHA256 = "8cb801e591072c3689fafd71ccf571a95a4ead3cc35dfc045e157d763d89119a"
LAVALINK_APPLICATION_YML_SHA256 = "a342d5575fac9c394faaaecaae17df1c8fc759dc8a8937ff839aeabb07cb6b95"
# URLs do Lavalink.jar de versões oficiais do espelho (inclusive sob o nome antigo do repositório). Quem as mantém no
# .env (copiado de um .example.env antigo) é atualizado sozinho para a URL e o hash atuais; ver prepare_lavalink_files.
LAVALINK_JAR_OFFICIAL_URLS = frozenset({
    "https://github.com/DiscordEmpireHub/LL-binaries/releases/download/0.0.1/Lavalink.jar",
    "https://github.com/DiscordEmpireHub/LL-binaries/releases/download/0.0.2/Lavalink.jar",
    "https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download/0.0.1/Lavalink.jar",
    "https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download/0.0.2/Lavalink.jar",
    "https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download/0.0.3/Lavalink.jar",
})
# Versões oficiais do application.yml que o bot pode substituir (a 0.0.1, a 0.0.2 e a atual); qualquer outra é do dono.
LAVALINK_APPLICATION_YML_KNOWN_SHA256 = frozenset({
    "f93ce9789fb637dc20bd886857a4ed813ad80870b43d268bc0ce80c11f90bfc3",
    "0d17d65f3b7d7a889f2b23f2719bd8a1e1aac77b90e0b77e9dacdbd35ce94801",
    LAVALINK_APPLICATION_YML_SHA256,
})
# JDK baixado quando não há Java 17+ no sistema: plataforma -> (URL oficial da BellSoft, SHA-256 fixo do arquivo).
# Para atualizar: baixe o arquivo novo, confira o SHA-1 que a BellSoft publica e só então calcule o SHA-256.
JDK_DOWNLOADS = {
    "windows-amd64": (
        "https://download.bell-sw.com/java/17.0.13+12/bellsoft-jdk17.0.13+12-windows-amd64.zip",
        "91b442a2952dc0e83b40406345a138b44c60ef41eed66afd80ae43d97ca155de",
    ),
    "windows-i586": (
        "https://download.bell-sw.com/java/17.0.13+12/bellsoft-jdk17.0.13+12-windows-i586.zip",
        "2cfe28ed102436dc7a03e71495ddd7ae2348de686e42d05b6bdf7b62b15684ed",
    ),
    "linux-amd64": (
        "https://download.bell-sw.com/java/21.0.3+12/bellsoft-jdk21.0.3+12-linux-amd64-lite.tar.gz",
        "525aa7ffea39e09f33ffd6eafb56322d614b315c51664170985dd1384579e2d1",
    ),
    "linux-i586": (
        "https://download.bell-sw.com/java/21.0.3+12/bellsoft-jdk21.0.3+12-linux-i586-lite.tar.gz",
        "d9de6f59b82db53894b03aa33675f20489844f9893bd6b75553145f43a05b0cd",
    ),
}
# Plugins do Lavalink (nome canônico em plugins/ -> SHA-256); a URL é LAVALINK_BINARIES_URL + "/" + nome.
LAVALINK_PLUGIN_SHA256 = {
    "youtube-plugin-2be8e542d3f6f178e048dca565892684c2e40177.jar":
        "b062effdda6abeaa46913dfd1b5d5600120b65f239ce88f30948c7213a3ca1c0",
    "lavasrc-plugin-4.8.3.jar": "4ec389bdae64fd381ee62fcdb902e15d9402823b1ad0b982bd5633619a07c1b3",
    "lavalink-2.6.1.jar": "1fc300ec80d4b1705eff0a3b2b4dae21177467c95a7f1e393ecf018c10f2aaf3",
}
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

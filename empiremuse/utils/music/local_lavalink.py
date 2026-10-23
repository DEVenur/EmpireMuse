# -*- coding: utf-8 -*-
import hashlib
import logging
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Mapping, Optional, Tuple

import requests

from empiremuse import paths
from empiremuse.utils import branding

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = (15, 60)  # (conexão, leitura) em segundos: sem isso um servidor parado trava o boot
HASH_CHUNK_SIZE = 1024 * 1024
PLUGINS_DIR = "plugins"
VALIDATE_JAVA_TIMEOUT = 15  # segundos: um "java -version" que não responde não pode travar o boot
JDK_STAGING_MAX_AGE = 3600  # segundos sem mudança para um staging do JDK ser tido como órfão (extração leva segundos)
JDK_STAGING_NAME = re.compile(r"[\w-]+\.\w{8}\.tmp")  # <plataforma>.<8 caracteres do mkdtemp>.tmp, nunca a pasta final
JDK_EXECUTABLES = ("java", "java.exe")  # bin/<nome> de um JDK instalado (Linux e Windows)
LAVALINK_LOGS_SUBDIR = ".logs/lavalink"
PLUGINS_OVERRIDE_RELATIVE = ".lavalink/plugins-override.yml"
PLUGINS_OVERRIDE_CONTENT = "lavalink:\n  plugins: []\n"  # constante: sem hash, é regravada se divergir


class LavalinkDownloadError(Exception):
    """Falha ao baixar ou preparar os arquivos do Lavalink local (mensagem em pt-BR, sem segredos)."""


class IntegrityError(LavalinkDownloadError):
    """O SHA-256 do arquivo baixado não confere com o esperado."""


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(url: str, filename: str, sha256: str, timeout=DOWNLOAD_TIMEOUT) -> None:
    """Baixa ``url`` para um arquivo temporário, confere o SHA-256 e só então move para ``filename`` (atômico).

    Qualquer falha (rede, hash) apaga o temporário e não deixa nada no destino.
    """
    expected = (sha256 or "").strip().lower()
    name = os.path.basename(filename)
    temp_name = f"{filename}.tmp"
    digest = hashlib.sha256()
    try:
        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with open(temp_name, "wb") as f:
                for chunk in response.iter_content(chunk_size=HASH_CHUNK_SIZE):
                    digest.update(chunk)
                    f.write(chunk)
        if digest.hexdigest() != expected:
            raise IntegrityError(f"O SHA-256 de {name} baixado não confere com o esperado; o arquivo foi descartado.")
        os.replace(temp_name, filename)
    except requests.RequestException as e:
        raise LavalinkDownloadError(f"Falha ao baixar {name}: {type(e).__name__}") from e
    finally:
        with suppress(FileNotFoundError):
            os.remove(temp_name)


def download_file(url, filename):
    if os.path.isfile(filename):
        return

    r = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT)
    total_size = int(r.headers.get("content-length", 0))
    bytes_downloaded = 0
    previows_progress = 0
    start_time = time.time()

    if total_size >= 1024 * 1024:
        total_txt = f"{total_size / (1024 * 1024):.2f} MB"
    else:
        total_txt = f"{total_size / 1024:.2f} KB"

    with open(f"{filename}.tmp", "wb") as f:
        for data in r.iter_content(chunk_size=2500 * 1024):
            f.write(data)
            bytes_downloaded += len(data)
            try:
                current_progress = int((bytes_downloaded / total_size) * 100)
            except ZeroDivisionError:
                current_progress = 0

            if current_progress != previows_progress:
                previows_progress = current_progress
                time_elapsed = time.time() - start_time
                try:
                    download_speed = bytes_downloaded / time_elapsed / 1024
                    if download_speed >= 1:
                        download_speed = (download_speed or 1) / 1024
                        speed_txt = "MB/s"
                    else:
                        speed_txt = "KB/s"
                    print(
                        f"Download do arquivo {filename} {current_progress}% concluído ({download_speed:.2f} {speed_txt} / {total_txt})"
                    )
                except:
                    print(f"Download do arquivo {filename} {current_progress}% concluído")

    r.close()

    os.rename(f"{filename}.tmp", filename)

    return True


def validate_java(cmd: str, debug: bool = False):
    """Devolve ``cmd`` se for um Java 17+ executável; senão ``None``. Sem shell: o caminho vira UM argumento."""
    try:
        java_info = subprocess.check_output(
            [cmd, "-version"], stderr=subprocess.STDOUT, text=True, timeout=VALIDATE_JAVA_TIMEOUT
        )
        if int(java_info.splitlines()[0].split()[2].strip('"').split(".")[0]) >= 17:
            return cmd
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as e:
        if debug:
            print(f"\nFalha ao obter versão do java...\nPath: {cmd} | Erro: {repr(e)}\n")


def _matches(path: str, sha256: str) -> bool:
    return os.path.isfile(path) and file_sha256(path) == sha256.lower()


def _resolve_jar_source(url: Optional[str], configured_sha256: Optional[str]) -> Tuple[str, str]:
    """Devolve ``(url, sha256)`` do jar a baixar.

    Vazio ou URL oficial (atual ou de versão anterior do espelho) usa a URL e o hash fixos do projeto, ignorando o hash
    configurado; as anteriores geram um aviso. Qualquer outro endereço exige HTTPS e ``LAVALINK_FILE_SHA256``.
    """
    url = (url or "").strip()
    if not url or url == branding.LAVALINK_JAR_URL:
        return branding.LAVALINK_JAR_URL, branding.LAVALINK_JAR_SHA256
    if url in branding.LAVALINK_JAR_OFFICIAL_URLS:
        logger.warning(
            "LAVALINK_FILE_URL aponta para uma versão antiga do espelho oficial; usando a versão atual. "
            "Esvazie a variável LAVALINK_FILE_URL para seguir sempre o espelho oficial."
        )
        return branding.LAVALINK_JAR_URL, branding.LAVALINK_JAR_SHA256
    if not url.lower().startswith("https://"):
        raise LavalinkDownloadError("LAVALINK_FILE_URL precisa usar HTTPS (https://); outros esquemas são recusados.")
    if not (configured_sha256 or "").strip():
        raise LavalinkDownloadError(
            "LAVALINK_FILE_URL aponta para um endereço diferente do oficial: defina também LAVALINK_FILE_SHA256 "
            "(SHA-256 do Lavalink.jar) para permitir o download."
        )
    return url, configured_sha256.strip()


def _prepare_yml(directory: str) -> None:
    path = os.path.join(directory, "application.yml")
    if os.path.isfile(path):
        current = file_sha256(path)
        if current == branding.LAVALINK_APPLICATION_YML_SHA256.lower():
            return
        if current not in {h.lower() for h in branding.LAVALINK_APPLICATION_YML_KNOWN_SHA256}:
            logger.warning("O application.yml existente é personalizado e foi mantido (não será substituído).")
            return
    download_verified(branding.LAVALINK_APPLICATION_YML_URL, path, branding.LAVALINK_APPLICATION_YML_SHA256)


def _remove_unlisted_plugins(plugins_dir: str) -> None:
    """Todo .jar em plugins/ é carregado pelo Lavalink: ao renovar o jar, só os plugins oficiais permanecem."""
    if not os.path.isdir(plugins_dir):
        return
    for entry in os.listdir(plugins_dir):
        if entry.endswith(".jar") and entry not in branding.LAVALINK_PLUGIN_SHA256:
            with suppress(OSError):
                os.remove(os.path.join(plugins_dir, entry))


def _prepare_plugins(directory: str) -> None:
    plugins_dir = os.path.join(directory, PLUGINS_DIR)
    os.makedirs(plugins_dir, exist_ok=True)
    for name, sha256 in branding.LAVALINK_PLUGIN_SHA256.items():
        path = os.path.join(plugins_dir, name)
        if not _matches(path, sha256):
            download_verified(f"{branding.LAVALINK_BINARIES_URL}/{name}", path, sha256)


def _offline_jar_sha256(url: Optional[str], configured_sha256: Optional[str]) -> str:
    """SHA-256 esperado do jar pré-instalado: o oficial, ou o ``LAVALINK_FILE_SHA256`` se o dono usa um jar próprio."""
    url = (url or "").strip()
    if not url or url == branding.LAVALINK_JAR_URL or url in branding.LAVALINK_JAR_OFFICIAL_URLS:
        return branding.LAVALINK_JAR_SHA256
    if not (configured_sha256 or "").strip():
        raise LavalinkDownloadError(
            "LAVALINK_OFFLINE=true com LAVALINK_FILE_URL diferente do oficial: defina também LAVALINK_FILE_SHA256 "
            "(SHA-256 do Lavalink.jar pré-instalado) ou esvazie LAVALINK_FILE_URL."
        )
    return configured_sha256.strip()


def _verify_preinstalled(path: str, sha256: str) -> None:
    """Confere um arquivo pré-instalado sem tocar nele: ausente => LavalinkDownloadError; hash errado => IntegrityError."""
    name = os.path.basename(path)
    if not os.path.isfile(path):
        raise LavalinkDownloadError(
            f"LAVALINK_OFFLINE=true: o arquivo {name} não foi encontrado em {os.path.dirname(path)}; "
            "nada é baixado no modo offline."
        )
    try:
        current = file_sha256(path)
    except OSError as e:
        raise LavalinkDownloadError(f"LAVALINK_OFFLINE=true: não foi possível ler {name}: {type(e).__name__}") from e
    if current != sha256.lower():
        raise IntegrityError(
            f"LAVALINK_OFFLINE=true: o SHA-256 de {name} não confere com o esperado; o arquivo foi recusado."
        )


def _verify_preinstalled_files(directory: str, url: Optional[str], configured_sha256: Optional[str]) -> None:
    """Modo offline: zero download e zero escrita; a pasta (talvez somente leitura) só é lida e verificada."""
    _verify_preinstalled(os.path.join(directory, "Lavalink.jar"), _offline_jar_sha256(url, configured_sha256))
    _verify_preinstalled(os.path.join(directory, "application.yml"), branding.LAVALINK_APPLICATION_YML_SHA256)
    for name, sha256 in branding.LAVALINK_PLUGIN_SHA256.items():
        _verify_preinstalled(os.path.join(directory, PLUGINS_DIR, name), sha256)


def prepare_lavalink_files(
    directory: Optional[str] = None,
    *,
    lavalink_file_url: str = None,
    lavalink_file_sha256: str = None,
    lavalink_offline: bool = False,
) -> None:
    """Garante ``Lavalink.jar``, ``application.yml`` e os plugins oficiais em ``directory`` (padrão: o RUNTIME_DIR).

    Todos verificados (SHA-256).

    Levanta ``LavalinkDownloadError`` (``IntegrityError`` se o hash não confere) antes de qualquer processo iniciar.
    Com ``lavalink_offline`` nada é baixado nem criado: os arquivos pré-instalados só são conferidos.
    """
    directory = str(paths.RUNTIME_DIR if directory is None else directory)
    if lavalink_offline:
        _verify_preinstalled_files(directory, lavalink_file_url, lavalink_file_sha256)
        return
    url, jar_sha256 = _resolve_jar_source(lavalink_file_url, lavalink_file_sha256)
    jar_path = os.path.join(directory, "Lavalink.jar")
    if not _matches(jar_path, jar_sha256):
        download_verified(url, jar_path, jar_sha256)
        _remove_unlisted_plugins(os.path.join(directory, PLUGINS_DIR))
    _prepare_yml(directory)
    _prepare_plugins(directory)


# Variáveis (relaxed binding do Spring) que ligam o OAuth do plugin do YouTube; o token só viaja pelo ambiente do Popen.
YOUTUBE_OAUTH_ENV_ENABLED = "PLUGINS_YOUTUBE_OAUTH_ENABLED"
YOUTUBE_OAUTH_ENV_REFRESH_TOKEN = "PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN"
YOUTUBE_OAUTH_ENV_SKIP_INITIALIZATION = "PLUGINS_YOUTUBE_OAUTH_SKIP_INITIALIZATION"

# Únicas variáveis do ambiente do bot que o processo do Lavalink herda (o resto, como TOKEN, MONGO e *_SECRET, não).
# SERVER_PORT é obrigatória: o bot fala com o Lavalink local nessa porta e o Spring a lê por relaxed binding.
CHILD_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TMPDIR",
        "TEMP",
        "TMP",
        "JAVA_HOME",
        "SERVER_PORT",
    }
)
CHILD_ENV_ALLOWLIST_WINDOWS = frozenset(
    {
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
    }
)

# O Lavalink local só atende o próprio bot: o endereço é forçado, nunca herdado (o ambiente do bot pode expô-lo em 0.0.0.0).
LAVALINK_ENV_SERVER_ADDRESS = "SERVER_ADDRESS"
LAVALINK_LOCAL_ADDRESS = "127.0.0.1"


def lavalink_child_env(refresh_token: Optional[str], environ: Mapping[str, str] = os.environ) -> Dict[str, str]:
    """Ambiente do processo do Lavalink: só a allowlist (nomes sem distinguir caixa no Windows) e, com token, o OAuth.

    Função pura: devolve um dict novo, não altera ``environ`` e nunca registra o ambiente nem o token. Sem token, as
    variáveis ``PLUGINS_YOUTUBE_OAUTH_*`` não existem no resultado, mesmo que estejam no ambiente do bot.
    """
    is_windows = os.name == "nt"
    allowed = CHILD_ENV_ALLOWLIST | CHILD_ENV_ALLOWLIST_WINDOWS if is_windows else CHILD_ENV_ALLOWLIST
    child_env: Dict[str, str] = {}
    seen = set()
    for name, value in environ.items():
        key = name.upper() if is_windows else name
        if key in allowed and key not in seen:
            seen.add(key)
            child_env[name] = value

    child_env[LAVALINK_ENV_SERVER_ADDRESS] = LAVALINK_LOCAL_ADDRESS

    token = (refresh_token or "").strip()
    if token:
        child_env[YOUTUBE_OAUTH_ENV_ENABLED] = "true"
        child_env[YOUTUBE_OAUTH_ENV_REFRESH_TOKEN] = token
        child_env[YOUTUBE_OAUTH_ENV_SKIP_INITIALIZATION] = "true"
    return child_env


def watch_lavalink_process(process: subprocess.Popen, on_exit: Callable[[int], None]) -> None:
    """Bloqueia (feita para rodar numa thread) até o processo sair e chama ``on_exit(returncode)`` uma única vez.

    Não decide se a saída era esperada: isso é do callback de quem vigia (o ``BotPool``).
    """
    on_exit(process.wait())


def _fetch_verified_jdk(archive_path: str, url: str, sha256: str) -> None:
    """Garante em ``archive_path`` o arquivo do JDK com o SHA-256 fixo; um arquivo já existente só vale se conferir."""
    if os.path.isfile(archive_path):
        if file_sha256(archive_path) == sha256.lower():
            return
        os.remove(archive_path)
    download_verified(url, archive_path, sha256)


def _jdk_download(system: str, arch: str) -> Tuple[str, str]:
    return branding.JDK_DOWNLOADS[f"{system}-{'amd64' if arch == '64bit' else 'i586'}"]


def _strip_top_dir(members):
    """Membros do tar sem a pasta raiz (equivale a --strip-components=1).

    Antes de devolver qualquer membro, recusa o arquivo inteiro se algum tiver nome absoluto ou ``..`` como primeiro
    componente (a raiz sumiria no strip e o resto do caminho escaparia da validação óbvia); nada é extraído nesse caso.
    """
    stripped = []
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or member.name.startswith("/") or (path.parts and path.parts[0] == ".."):
            raise LavalinkDownloadError("O arquivo do JDK contém um caminho inseguro e foi recusado.")
        changes = {"name": "/".join(path.parts[1:])}
        if member.islnk():
            changes["linkname"] = "/".join(PurePosixPath(member.linkname).parts[1:])
        if changes["name"]:
            stripped.append(member.replace(**changes, deep=False))
    return stripped


def _extract_tar_without_top_dir(archive_path: str, destination: str) -> None:
    """Extrai o .tar.gz (já verificado) sem a pasta raiz, com o filtro seguro ``data``."""
    with tarfile.open(archive_path, "r:gz") as archive:
        members = _strip_top_dir(archive.getmembers())
        archive.extractall(destination, members=members, filter="data")


def _jdk_is_usable(java_dir: str) -> bool:
    """Um JDK instalado só vale se ``bin/java`` (ou ``bin/java.exe``) existir, for arquivo (symlink válido serve) e executável."""
    for name in JDK_EXECUTABLES:
        java = os.path.join(java_dir, "bin", name)
        if os.path.isfile(java) and os.access(java, os.X_OK):
            return True
    return False


def _extract_zip_without_top_dir(archive_path: str, destination: str) -> None:
    """Extrai o .zip (já verificado) em ``destination`` e sobe o conteúdo da pasta raiz do JDK (a que tem ``bin/java.exe``)."""
    with zipfile.ZipFile(archive_path, "r") as zip_ref:
        zip_ref.extractall(destination)

    roots = [d for d in os.listdir(destination) if os.path.isfile(os.path.join(destination, d, "bin", "java.exe"))]
    if len(roots) != 1:
        raise LavalinkDownloadError("O arquivo do JDK não contém uma única pasta com bin/java.exe.")

    root = os.path.join(destination, roots[0])
    for item in os.listdir(root):
        os.rename(os.path.join(root, item), os.path.join(destination, item))
    os.rmdir(root)


def _install_jdk_windows(tmp_dir: str, jdk_platform: str, arch: str) -> str:
    java_dir = f"{tmp_dir}/.java/{jdk_platform}"
    url, sha256 = _jdk_download("windows", arch)
    archive_path = f"{tmp_dir}/java.zip"
    _fetch_verified_jdk(archive_path, url, sha256)
    try:
        _install_extracted_jdk(
            archive_path, f"{tmp_dir}/.java", java_dir, jdk_platform, extract=_extract_zip_without_top_dir
        )
    finally:
        with suppress(FileNotFoundError):
            os.remove(archive_path)

    return os.path.realpath(f"{java_dir}/bin/java")


def _install_jdk_linux(tmp_dir: str, jdk_platform: str, arch: str) -> str:
    java_dir = f"{tmp_dir}/.java/{jdk_platform}"

    if not _jdk_is_usable(java_dir):
        url, sha256 = _jdk_download("linux", arch)
        archive_path = f"{tmp_dir}/java.tar.gz"
        _fetch_verified_jdk(archive_path, url, sha256)
        try:
            _install_extracted_jdk(archive_path, f"{tmp_dir}/.java", java_dir, jdk_platform)
        finally:
            with suppress(FileNotFoundError):
                os.remove(archive_path)

    return os.path.realpath(f"{java_dir}/bin/java")


def _install_extracted_jdk(
    archive_path: str,
    java_root: str,
    java_dir: str,
    jdk_platform: str,
    extract: Optional[Callable[[str, str], None]] = None,
) -> None:
    """Extrai num diretório temporário irmão e só o promove a ``java_dir`` (os.replace) se tudo deu certo.

    Qualquer falha (inclusive Ctrl+C) apaga o temporário e não mexe em outras instalações de ``java_root``. Um ``kill -9``
    não passa pelo ``finally``: a sobra é apagada na próxima subida por ``remove_orphan_jdk_staging``.
    """
    extract = extract or _extract_tar_without_top_dir
    os.makedirs(java_root, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=f"{jdk_platform}.", suffix=".tmp", dir=java_root)
    try:
        os.chmod(staging, 0o755)
        extract(archive_path, staging)
        shutil.rmtree(java_dir, ignore_errors=True)  # instalação quebrada: é trocada por inteiro
        os.replace(staging, java_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _newest_mtime(directory: str) -> float:
    """Última modificação do diretório ou de qualquer entrada direta dele (a extração cria entradas em sequência)."""
    newest = os.stat(directory).st_mtime
    with os.scandir(directory) as entries:
        for entry in entries:
            newest = max(newest, entry.stat(follow_symlinks=False).st_mtime)
    return newest


def remove_orphan_jdk_staging(java_root: str, max_age: float = JDK_STAGING_MAX_AGE, now: Optional[float] = None) -> int:
    """Apaga os staging do JDK que sobraram de um processo morto no meio da extração (cerca de 150 MB cada).

    Só apaga diretório real (nunca link) cujo nome é o do ``mkdtemp`` de ``_install_extracted_jdk`` e que não muda há mais
    de ``max_age`` segundos: a instalação válida (``<plataforma>`` sem ``.tmp``) e uma extração em curso em outro processo
    ficam intactas. Falhas de leitura ou de remoção não derrubam a subida. Devolve quantos foram apagados.
    """
    now = time.time() if now is None else now
    removed = 0
    try:
        names = os.listdir(java_root)
    except OSError:
        return 0
    for name in names:
        path = os.path.join(java_root, name)
        if not JDK_STAGING_NAME.fullmatch(name) or os.path.islink(path) or not os.path.isdir(path):
            continue
        try:
            idle = now - _newest_mtime(path)
        except OSError:
            continue
        if idle < max_age:
            continue
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            removed += 1
    if removed:
        logger.info("Removidos %d diretório(s) temporário(s) órfão(s) de instalação do JDK em %s.", removed, java_root)
    return removed


def _configured_java(java_path: str) -> str:
    """Java escolhido em LAVALINK_JAVA_PATH: se não servir é erro claro, nunca um fallback silencioso para outro Java."""
    if not os.path.isfile(java_path) or not os.access(java_path, os.X_OK):
        raise LavalinkDownloadError(
            f"LAVALINK_JAVA_PATH ({java_path}) não aponta para um executável do Java: o arquivo não existe, "
            "não é um arquivo ou não tem permissão de execução."
        )
    if not validate_java(java_path):
        raise LavalinkDownloadError(
            f"LAVALINK_JAVA_PATH ({java_path}) não é um Java 17 ou superior (ou não respondeu a '-version')."
        )
    return java_path


def _lavalink_home(configured: Optional[str]) -> str:
    """Pasta do Lavalink: LAVALINK_HOME, ou a pasta de dados do bot quando vazio."""
    configured = (configured or "").strip()
    if not configured:
        return str(paths.RUNTIME_DIR)
    if not os.path.isdir(configured):
        raise LavalinkDownloadError(f"LAVALINK_HOME ({configured}) não é uma pasta existente.")
    return configured


def _find_or_install_java(tmp_dir: str, jdk_platform: str, arch: str, allow_install: bool) -> str:
    """Java 17+ do sistema, de JAVA_HOME ou já instalado pelo bot; só instala o JDK se ``allow_install``."""
    if java_cmd := validate_java("java"):
        return java_cmd

    dirs = []

    try:
        dirs.append(os.path.join(os.environ["JAVA_HOME"], "bin", "java"))
    except KeyError:
        pass

    if os.name == "nt":
        dirs.append(f"{tmp_dir}/.java/{jdk_platform}/bin/java")
    else:
        dirs.append(os.path.realpath(f"{tmp_dir}/.java/{jdk_platform}/bin/java"))
    shutil.rmtree(str(paths.RUNTIME_DIR / ".jabba"), ignore_errors=True)  # resto de instalação antiga (jabba removido)

    for cmd in dirs:
        if validate_java(cmd):
            return cmd

    if not allow_install:
        raise LavalinkDownloadError(
            "LAVALINK_OFFLINE=true: nenhum Java 17+ foi encontrado e o JDK não será baixado no modo offline; "
            "defina LAVALINK_JAVA_PATH com o executável do Java instalado."
        )
    return _install_jdk(tmp_dir, jdk_platform, arch)


def _install_jdk(tmp_dir: str, jdk_platform: str, arch: str) -> str:
    if os.name == "nt":
        return _install_jdk_windows(tmp_dir, jdk_platform, arch)
    return _install_jdk_linux(tmp_dir, jdk_platform, arch)


def _has_override_content(path: str) -> bool:
    """Ausente, ilegível ou divergente => False (o arquivo é então regravado)."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read() == PLUGINS_OVERRIDE_CONTENT
    except (OSError, UnicodeDecodeError):
        return False


def _ensure_plugins_override() -> str:
    """Grava (de forma atômica, só se divergir) o YAML que zera ``lavalink.plugins`` e devolve o caminho absoluto.

    O Lavalink consulta o Maven a cada partida por plugin com ``dependency`` no application.yml (que tem SHA-256 fixo e
    não pode mudar); sem rede isso é fatal. Os jars continuam vindo de ``plugins/``, verificados por SHA-256.
    Fica sempre em RUNTIME_DIR (volume gravável), nunca em LAVALINK_HOME.
    """
    path = os.path.abspath(paths.RUNTIME_DIR / PLUGINS_OVERRIDE_RELATIVE)
    if _has_override_content(path):
        return path

    temp_path = f"{path}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(PLUGINS_OVERRIDE_CONTENT)
        os.replace(temp_path, path)
    except OSError as e:
        with suppress(OSError):  # limpeza do temporário: não pode mascarar o erro original
            os.remove(temp_path)
        raise LavalinkDownloadError(
            f"Não foi possível gravar {os.path.basename(path)} em {os.path.dirname(path)} (RUNTIME_DIR): "
            f"{type(e).__name__}"
        ) from e
    return path


def _logging_args(home: str) -> List[str]:
    """Com LAVALINK_HOME fora de RUNTIME_DIR (talvez somente leitura) os logs do Lavalink vão para o volume gravável.

    Vai pela linha de comando porque o application.yml tem SHA-256 fixo e o ambiente do Java é uma allowlist.
    """
    if Path(home).resolve() == paths.RUNTIME_DIR.resolve():
        return []
    logs_dir = paths.RUNTIME_DIR / LAVALINK_LOGS_SUBDIR
    logs_dir.mkdir(parents=True, exist_ok=True)
    return [f"-Dlogging.file.path={logs_dir}"]


def _java_command(java_cmd: str, *, home: str, cpu_cores: int, ram_limit: int, initial_ram: int) -> List[str]:
    """Linha de comando do Java como lista: o caminho do Java (mesmo com espaços) é sempre UM argumento."""
    args = [java_cmd]

    if cpu_cores >= 1:
        args.append(f"-XX:ActiveProcessorCount={cpu_cores}")

    if ram_limit > 10:
        args.append(f"-Xmx{ram_limit}m")

    if 0 < initial_ram < ram_limit:
        args.append(f"-Xms{initial_ram}m")

    if os.name != "nt":
        # O tmpdir fica sempre em RUNTIME_DIR (volume gravável), mesmo quando LAVALINK_HOME é somente leitura.
        tempjar_dir = paths.RUNTIME_DIR / ".tempjar"
        if tempjar_dir.is_dir():
            shutil.rmtree(tempjar_dir)

        undertow_dir = tempjar_dir / "undertow-docbase.80.2258596138812103750"
        undertow_dir.mkdir(parents=True, exist_ok=True)

        args.append(f"-Djava.io.tmpdir={tempjar_dir}")

    # URI (e não o caminho cru): o Spring separa os locais por vírgula e o espaço quebraria o caminho
    override_arg = f"-Dspring.config.additional-location={Path(_ensure_plugins_override()).as_uri()}"
    return [*args, *_logging_args(home), override_arg, "-jar", "Lavalink.jar"]


def run_lavalink(
    lavalink_file_url: str = None,
    lavalink_initial_ram: int = 30,
    lavalink_ram_limit: int = 100,
    lavalink_additional_sleep: int = 0,
    lavalink_cpu_cores: int = 1,
    *,
    lavalink_file_sha256: str = None,
    youtube_oauth_refresh_token: str = None,
    lavalink_java_path: str = "",
    lavalink_home: str = "",
    lavalink_offline: bool = False,
):
    arch, osname = platform.architecture()
    jdk_platform = f"{platform.system()}-{arch}-{osname}"

    tmp_dir = tempfile.gettempdir() if os.name == "nt" else str(paths.RUNTIME_DIR)

    remove_orphan_jdk_staging(f"{tmp_dir}/.java")

    home = _lavalink_home(lavalink_home)

    if configured_java := (lavalink_java_path or "").strip():
        java_cmd = _configured_java(configured_java)
    else:
        java_cmd = _find_or_install_java(tmp_dir, jdk_platform, arch, allow_install=not lavalink_offline)

    prepare_lavalink_files(
        home,
        lavalink_file_url=lavalink_file_url,
        lavalink_file_sha256=lavalink_file_sha256,
        lavalink_offline=lavalink_offline,
    )

    java_args = _java_command(
        java_cmd,
        home=home,
        cpu_cores=lavalink_cpu_cores,
        ram_limit=lavalink_ram_limit,
        initial_ram=lavalink_initial_ram,
    )

    print(
        "🌋 - Iniciando o servidor Lavalink (dependendo da hospedagem o lavalink pode demorar iniciar, "
        "o que pode ocorrer falhas em algumas tentativas de conexão até ele iniciar totalmente)."
    )

    lavalink_process = subprocess.Popen(
        java_args,
        stdout=subprocess.DEVNULL,
        env=lavalink_child_env(youtube_oauth_refresh_token),
        cwd=home,
    )

    if lavalink_additional_sleep:
        print(f"🕙 - Aguarde {lavalink_additional_sleep} segundos...")
        time.sleep(lavalink_additional_sleep)

    return lavalink_process


if __name__ == "__main__":
    run_lavalink()
    time.sleep(1200)

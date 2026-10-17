# -*- coding: utf-8 -*-
import hashlib
import logging
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from contextlib import suppress
from pathlib import PurePosixPath
from typing import Dict, Mapping, Optional, Tuple

import requests

from empiremuse.utils import branding

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = (15, 60)  # (conexão, leitura) em segundos: sem isso um servidor parado trava o boot
HASH_CHUNK_SIZE = 1024 * 1024
PLUGINS_DIR = "plugins"


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
    try:
        java_info = subprocess.check_output(f"{cmd} -version", stderr=subprocess.STDOUT, text=True, shell=True)
        if int(java_info.splitlines()[0].split()[2].strip('"').split(".")[0]) >= 17:
            return cmd
    except Exception as e:
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


def prepare_lavalink_files(
    directory: str = ".", *, lavalink_file_url: str = None, lavalink_file_sha256: str = None
) -> None:
    """Garante ``Lavalink.jar``, ``application.yml`` e os plugins oficiais em ``directory``, todos verificados (SHA-256).

    Levanta ``LavalinkDownloadError`` (``IntegrityError`` se o hash não confere) antes de qualquer processo iniciar.
    """
    directory = str(directory)
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

    token = (refresh_token or "").strip()
    if token:
        child_env[YOUTUBE_OAUTH_ENV_ENABLED] = "true"
        child_env[YOUTUBE_OAUTH_ENV_REFRESH_TOKEN] = token
        child_env[YOUTUBE_OAUTH_ENV_SKIP_INITIALIZATION] = "true"
    return child_env


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
    """Um JDK instalado só vale se ``bin/java`` existir, for arquivo (symlink válido serve) e executável."""
    java = os.path.join(java_dir, "bin", "java")
    return os.path.isfile(java) and os.access(java, os.X_OK)


def _install_jdk_windows(tmp_dir: str, jdk_platform: str, arch: str) -> str:
    url, sha256 = _jdk_download("windows", arch)
    archive_path = f"{tmp_dir}/java.zip"
    _fetch_verified_jdk(archive_path, url, sha256)

    shutil.rmtree(f"{tmp_dir}/.java", ignore_errors=True)
    os.makedirs(f"{tmp_dir}/.java/{jdk_platform}", exist_ok=True)

    try:
        with zipfile.ZipFile(archive_path, "r") as zip_ref:
            zip_ref.extractall(f"{tmp_dir}/.java")
    finally:
        with suppress(FileNotFoundError):
            os.remove(archive_path)

    extracted_folder = None
    java_dirs = os.listdir(f"{tmp_dir}/.java")

    for d in java_dirs:
        if d != jdk_platform and os.path.isfile(f"{tmp_dir}/.java/{d}/bin/java.exe"):
            extracted_folder = f"{tmp_dir}/.java/{d}"

    if not extracted_folder:
        raise Exception(f"JDK não encontrando no diretório: {tmp_dir}/.java\n" + "\n".join(java_dirs))

    for item in os.listdir(extracted_folder):
        os.rename(os.path.join(extracted_folder, item), os.path.join(f"{tmp_dir}/.java/{jdk_platform}", item))

    shutil.rmtree(extracted_folder, ignore_errors=True)

    return os.path.realpath(f"{tmp_dir}/.java/{jdk_platform}/bin/java")


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


def _install_extracted_jdk(archive_path: str, java_root: str, java_dir: str, jdk_platform: str) -> None:
    """Extrai num diretório temporário irmão e só o promove a ``java_dir`` (os.replace) se tudo deu certo.

    Qualquer falha (inclusive Ctrl+C) apaga o temporário e não mexe em outras instalações de ``java_root``.
    """
    os.makedirs(java_root, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=f"{jdk_platform}.", suffix=".tmp", dir=java_root)
    try:
        os.chmod(staging, 0o755)
        _extract_tar_without_top_dir(archive_path, staging)
        shutil.rmtree(java_dir, ignore_errors=True)  # instalação quebrada: é trocada por inteiro
        os.replace(staging, java_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def run_lavalink(
    lavalink_file_url: str = None,
    lavalink_initial_ram: int = 30,
    lavalink_ram_limit: int = 100,
    lavalink_additional_sleep: int = 0,
    lavalink_cpu_cores: int = 1,
    use_jabba: bool = False,
    *,
    lavalink_file_sha256: str = None,
    youtube_oauth_refresh_token: str = None,
):
    arch, osname = platform.architecture()
    jdk_platform = f"{platform.system()}-{arch}-{osname}"

    tmp_dir = tempfile.gettempdir() if os.name == "nt" else "."

    if not (java_cmd := validate_java("java")):
        dirs = []

        try:
            dirs.append(os.path.join(os.environ["JAVA_HOME"] + "bin/java"))
        except KeyError:
            pass

        if os.name == "nt":
            dirs.append(f"{tmp_dir}/.java/{jdk_platform}/bin/java")
            try:
                shutil.rmtree("./.jabba")
            except:
                pass

        else:
            if use_jabba:
                dirs.extend(
                    [
                        os.path.realpath("./.jabba/jdk/zulu@1.17.0-0/bin/java"),
                        os.path.expanduser("./.jabba/jdk/zulu@1.17.0-0/bin/java"),
                    ]
                )
                try:
                    shutil.rmtree(f"{tmp_dir}/.java")
                except:
                    pass

            else:
                dirs.append(os.path.realpath(f"{tmp_dir}/.java/{jdk_platform}/bin/java"))
                try:
                    shutil.rmtree("./.jabba")
                except:
                    pass

        for cmd in dirs:
            if validate_java(cmd):
                java_cmd = cmd
                break

        if not java_cmd:
            if os.name == "nt":
                java_cmd = _install_jdk_windows(tmp_dir, jdk_platform, arch)

            elif use_jabba:
                try:
                    shutil.rmtree("./.jabba/jdk/zulu@1.17.0-0")
                except:
                    pass

                download_file("https://raw.githubusercontent.com/shyiko/jabba/master/install.sh", "install_jabba.sh")
                subprocess.call("bash install_jabba.sh", shell=True)
                subprocess.call("./.jabba/bin/jabba install zulu@1.17.0-0", shell=True)
                os.remove("install_jabba.sh")

                java_cmd = os.path.expanduser("./.jabba/jdk/zulu@1.17.0-0/bin/java")

            else:
                java_cmd = _install_jdk_linux(tmp_dir, jdk_platform, arch)

    prepare_lavalink_files(".", lavalink_file_url=lavalink_file_url, lavalink_file_sha256=lavalink_file_sha256)

    if lavalink_cpu_cores >= 1:
        java_cmd += f" -XX:ActiveProcessorCount={lavalink_cpu_cores}"

    if lavalink_ram_limit > 10:
        java_cmd += f" -Xmx{lavalink_ram_limit}m"

    if 0 < lavalink_initial_ram < lavalink_ram_limit:
        java_cmd += f" -Xms{lavalink_ram_limit}m"

    if os.name != "nt":
        if os.path.isdir("./.tempjar"):
            shutil.rmtree("./.tempjar")

        os.makedirs("./.tempjar/undertow-docbase.80.2258596138812103750")

        java_cmd += f" -Djava.io.tmpdir={os.getcwd()}/.tempjar"

    java_cmd += " -jar Lavalink.jar"

    print(
        "🌋 - Iniciando o servidor Lavalink (dependendo da hospedagem o lavalink pode demorar iniciar, "
        "o que pode ocorrer falhas em algumas tentativas de conexão até ele iniciar totalmente)."
    )

    lavalink_process = subprocess.Popen(
        java_cmd.split(), stdout=subprocess.DEVNULL, env=lavalink_child_env(youtube_oauth_refresh_token)
    )

    if lavalink_additional_sleep:
        print(f"🕙 - Aguarde {lavalink_additional_sleep} segundos...")
        time.sleep(lavalink_additional_sleep)

    return lavalink_process


if __name__ == "__main__":
    run_lavalink()
    time.sleep(1200)

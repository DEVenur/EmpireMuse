# -*- coding: utf-8 -*-
import os
import sys
import time
from platform import python_version
from typing import Any

from empiremuse import paths
from empiremuse.updater import boot_guard


ORIGIN_HOME = "EMPIREMUSE_HOME"
ORIGIN_DEV_RUNTIME = ".runtime de desenvolvimento"
ORIGIN_CWD = "pasta atual"


def _announce_runtime_dir(runtime_dir, origin: str) -> None:
    """Uma linha na subida com o diretório escolhido e de onde ele veio; nunca o conteúdo de arquivo algum."""
    print(f"📂 - Pasta de execução: {runtime_dir} (origem: {origin})")


def enter_runtime_dir() -> None:
    """Muda o cwd para o `RUNTIME_DIR`, onde o bot grava dados e caches relativos ao diretório de trabalho.

    Plataformas como o Pterodactyl criam o container sem `WorkingDir`, e o cwd da imagem não é gravável pelo
    usuário do nó, então vale o `EMPIREMUSE_HOME`. Em desenvolvimento, sem a variável, vale a `.runtime/` do
    projeto quando ela existe. Sem nenhum dos dois nada muda (o `RUNTIME_DIR` já é o cwd).
    """
    home_is_set = bool(os.environ.get("EMPIREMUSE_HOME"))
    runtime_dir = paths.get_runtime_dir()

    if not home_is_set and paths.dev_runtime_dir() is None:
        _announce_runtime_dir(runtime_dir, ORIGIN_CWD)
        return

    try:
        os.chdir(runtime_dir)
    except OSError as e:
        if home_is_set:
            message = (
                f"Não foi possível entrar no diretório indicado por EMPIREMUSE_HOME ({runtime_dir}): {e.strerror}. "
                "Crie a pasta ou corrija a variável EMPIREMUSE_HOME."
            )
        else:
            message = (
                f"Não foi possível entrar na pasta de execução de desenvolvimento ({runtime_dir}): {e.strerror}. "
                "Ajuste as permissões da pasta .runtime ou remova-a para o bot usar o diretório atual."
            )
        raise SystemExit(message) from e

    if home_is_set:
        # Se EMPIREMUSE_HOME era relativo, o valor passaria a apontar para outro lugar depois do chdir.
        os.environ["EMPIREMUSE_HOME"] = str(runtime_dir)

    _announce_runtime_dir(runtime_dir, ORIGIN_HOME if home_is_set else ORIGIN_DEV_RUNTIME)


def __getattr__(name: str) -> Any:
    """``BotPool`` só é importado quando preciso: o ``boot_guard`` roda antes de o código do bot carregar."""
    if name == "BotPool":
        from empiremuse.utils.client import BotPool

        return BotPool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main():
    enter_runtime_dir()
    # Antes de importar o bot: um erro de import no código recém-atualizado não pode impedir a volta ao commit anterior.
    boot_guard.run(paths.get_runtime_dir(), paths.PROJECT_DIR, time.time())
    print(f"🐍 - Versão do python: {python_version()}")
    pool_class = globals().get("BotPool") or __getattr__("BotPool")
    pool = pool_class()
    pool.setup()
    sys.exit(pool.exit_code)


if __name__ == "__main__":
    main()

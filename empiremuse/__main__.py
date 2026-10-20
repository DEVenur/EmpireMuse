# -*- coding: utf-8 -*-
import os
import sys
from platform import python_version

from empiremuse import paths
from empiremuse.utils.client import BotPool


def enter_runtime_dir() -> None:
    """Muda o cwd para o `RUNTIME_DIR`, onde o bot grava dados e caches relativos ao diretório de trabalho.

    Plataformas como o Pterodactyl criam o container sem `WorkingDir`, e o cwd da imagem não é gravável pelo
    usuário do nó, então vale o `EMPIREMUSE_HOME`. Em desenvolvimento, sem a variável, vale a `.runtime/` do
    projeto quando ela existe. Sem nenhum dos dois nada muda (o `RUNTIME_DIR` já é o cwd).
    """
    home_is_set = bool(os.environ.get("EMPIREMUSE_HOME"))
    if not home_is_set and paths.dev_runtime_dir() is None:
        return

    runtime_dir = paths.get_runtime_dir()
    try:
        os.chdir(runtime_dir)
    except OSError as e:
        origin = "indicado por EMPIREMUSE_HOME" if home_is_set else "de desenvolvimento (.runtime)"
        raise SystemExit(
            f"Não foi possível entrar no diretório {origin} ({runtime_dir}): {e.strerror}. "
            "Crie a pasta ou corrija a variável EMPIREMUSE_HOME."
        ) from e

    if home_is_set:
        # Se EMPIREMUSE_HOME era relativo, o valor passaria a apontar para outro lugar depois do chdir.
        os.environ["EMPIREMUSE_HOME"] = str(runtime_dir)


def main():
    enter_runtime_dir()
    print(f"🐍 - Versão do python: {python_version()}")
    pool = BotPool()
    pool.setup()
    sys.exit(pool.exit_code)


if __name__ == "__main__":
    main()

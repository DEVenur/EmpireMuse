# -*- coding: utf-8 -*-
import sys
from platform import python_version

from empiremuse.utils.client import BotPool


def main():
    print(f"🐍 - Versão do python: {python_version()}")
    pool = BotPool()
    pool.setup()
    sys.exit(pool.exit_code)


if __name__ == "__main__":
    main()

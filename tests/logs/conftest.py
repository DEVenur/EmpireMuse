"""Isolamento do item 7: o ``configure_logging`` mexe no root, em loggers de bibliotecas e nos ganchos globais de exceção.

Cada teste termina com o root, os loggers de biblioteca, ``sys.excepthook`` e ``threading.excepthook`` como estavam, e com o
redator sem o conjunto base de segredos (o que veio de ``register_secret`` fica: use valores próprios por teste).
"""

import logging
import sys
import threading

import pytest

BIBLIOTECAS = ("disnake", "aiohttp", "asyncio", "tornado", "urllib3", "pymongo", "motor", "websockets", "PIL")


@pytest.fixture(autouse=True)
def isolar_logging():
    from empiremuse.logs import setup as _setup

    raiz = logging.getLogger()
    handlers, nivel = list(raiz.handlers), raiz.level
    niveis = {nome: logging.getLogger(nome).level for nome in BIBLIOTECAS}
    ganchos = (sys.excepthook, threading.excepthook)
    guildas = _setup._debug_guilds
    try:
        from empiremuse.logs.redact import configure_secrets

        configure_secrets([])
    except ImportError:  # o pacote ainda não existe: cada teste falha pelo próprio import
        pass
    yield
    for handler in list(raiz.handlers):
        if handler not in handlers and not type(handler).__module__.startswith("_pytest"):
            raiz.removeHandler(handler)
            handler.close()
    raiz.setLevel(nivel)
    for nome, valor in niveis.items():
        logging.getLogger(nome).setLevel(valor)
    sys.excepthook, threading.excepthook = ganchos
    _setup._debug_guilds = guildas

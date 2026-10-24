"""Apoio dos testes de persistência: o que o log pode e não pode ter.

* leitura recusada (sessão, fila, skin): aviso ``WARNING`` só com o ``guild_id`` e o ``code`` da falha, nada do conteúdo.
"""

import logging

from tests.support.serializacao_nucleo import SEGREDO


def avisos(caplog) -> list[str]:
    return [registro.getMessage() for registro in caplog.records if registro.levelno >= logging.WARNING]


def registrou(caplog, guild_id, codigo) -> bool:
    """Há um aviso com o ``guild_id`` e o ``code`` da falha? (``codigo`` pode ser um texto ou vários aceitos)"""
    codigos = (codigo,) if isinstance(codigo, str) else tuple(codigo)
    return any(str(guild_id) in mensagem and any(c in mensagem for c in codigos) for mensagem in avisos(caplog))


def log_sem_o_conteudo(caplog, capsys) -> bool:
    """Nenhum registro (de qualquer nível), nenhum argumento e nenhuma saída padrão leva o ``SEGREDO``."""
    saida = capsys.readouterr()
    registros = all(
        SEGREDO not in registro.getMessage() and SEGREDO not in repr(registro.args) for registro in caplog.records
    )
    return registros and SEGREDO not in saida.out and SEGREDO not in saida.err

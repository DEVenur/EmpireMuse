"""Encerramento do laço que o ``BotPool.setup()`` real cria nos testes.

O ``setup()`` deixa tarefas penduradas nesse laço (por exemplo a ``version_check_task``). Fechar o laço sem cancelá-las faz o GC destruí-las depois,
quando o asyncio loga ``Task was destroyed but it is pending!`` pelo logging que OUTRO teste configurou: o ERRO aparece no console dele.
"""

import asyncio
import gc


def encerrar_laco(loop: asyncio.AbstractEventLoop | None) -> None:
    """Cancela o que restou no laço, deixa o cancelamento correr, fecha o laço e coleta o lixo (nada é destruído mais tarde, no teste dos outros)."""
    if loop is None or loop.is_closed():
        return
    pendentes = [tarefa for tarefa in asyncio.all_tasks(loop) if not tarefa.done()]
    for tarefa in pendentes:
        tarefa.cancel()

    async def esperar_o_cancelamento() -> None:
        await asyncio.gather(*pendentes, return_exceptions=True)
        await asyncio.sleep(0)

    loop.run_until_complete(esperar_o_cancelamento())
    loop.close()
    gc.collect()

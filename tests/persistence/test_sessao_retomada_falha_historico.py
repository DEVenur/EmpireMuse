"""F3-6b, etapa 5 — falha ao ler o histórico do canal na retomada: a sessão segue e o aviso não leva dado nenhum.

O aviso antigo era um ``print`` que citava ``data['message']`` (chave que não existe: o ``KeyError`` derrubava a retomada) e o
``repr`` da exceção. Agora é um log só com o servidor e o tipo da falha.
"""

import logging

import pytest

from tests.support.formatos_reais import CANAL_DE_TEXTO, CANAL_DE_VOZ
from tests.support.leitor_legado import SEGREDO
from tests.persistence.test_sessao_retomada import _ambiente, montar, proprio, retomar, sessao  # noqa: F401


class HistoricoQuebrado(Exception):
    pass


def canal_com_historico_quebrado(canal_id):
    canal = proprio(canal_id)

    def history(**kwargs):
        raise HistoricoQuebrado(SEGREDO)

    canal.history = history
    return canal


@pytest.mark.asyncio
async def test_falha_ao_ler_o_historico_nao_derruba_a_retomada():
    dados = await sessao()
    dados["message_id"] = None
    texto = canal_com_historico_quebrado(CANAL_DE_TEXTO)
    cog, _, criados = montar(canais={CANAL_DE_VOZ: proprio(CANAL_DE_VOZ), CANAL_DE_TEXTO: texto})
    await retomar(cog, dados)
    assert len(criados) == 1 and criados[0].conexoes == [CANAL_DE_VOZ]


@pytest.mark.asyncio
async def test_o_aviso_leva_o_servidor_e_o_tipo_e_nada_do_conteudo(caplog, capsys):
    dados = await sessao()
    dados["message_id"] = None
    cog, _, _ = montar(
        canais={CANAL_DE_VOZ: proprio(CANAL_DE_VOZ), CANAL_DE_TEXTO: canal_com_historico_quebrado(CANAL_DE_TEXTO)}
    )
    with caplog.at_level(logging.DEBUG):
        await retomar(cog, dados)
    avisos = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("HistoricoQuebrado" in m for m in avisos)
    saida = capsys.readouterr()
    assert SEGREDO not in saida.out + saida.err and all(SEGREDO not in m for m in avisos)
    assert "KeyError" not in saida.out + saida.err

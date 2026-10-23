"""F3-6b, etapa 5 — a validação e a codificação da sessão não rodam na thread do laço de eventos.

Uma sessão perto dos tetos leva cerca de 0,9 s para validar e codificar; no laço isso trava o bot a cada gravação. O trabalho vai
para um executor, e a cópia dos dados do player é tirada ANTES, no laço, para a thread não ler o que o laço continua mudando.
"""

import asyncio
import json
import threading

import disnake
import pytest

from empiremuse.serialization import session as codec
from tests.support.formatos_reais import INSTANTE, SERVIDOR, cog_de_sessoes
from tests.support.sessoes import MongoDeSessoes, faixa_info, pasta_json, sessao_minima


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


@pytest.fixture
def espiao(monkeypatch):
    """Registra a thread e o argumento de cada ``encode_session`` e ``validate_session`` (chama as funções de verdade)."""
    registro = {"encode": [], "validate": []}

    def espionar(nome):
        original = getattr(codec, f"{nome}_session")

        def passa(dados, *args, **kwargs):
            registro[nome].append((threading.get_ident(), dados))
            return original(dados, *args, **kwargs)

        monkeypatch.setattr(codec, f"{nome}_session", passa)

    espionar("encode")
    espionar("validate")
    return registro


def cog_do_mongo():
    mongo = MongoDeSessoes()
    return cog_de_sessoes(mongo=mongo), mongo


async def salvar(cog, dados):
    if cog.bot.config["PLAYER_SESSIONS_MONGODB"]:
        await cog.save_session_mongo(SERVIDOR, dados)
    else:
        await cog.save_session_local(SERVIDOR, dados)


@pytest.mark.asyncio
@pytest.mark.parametrize("destino", ["disco", "mongo"])
async def test_encode_e_validate_nao_rodam_na_thread_do_laco(espiao, destino):
    cog = cog_do_mongo()[0] if destino == "mongo" else cog_de_sessoes()
    await salvar(cog, sessao_minima(queue=[faixa_info(0)]))
    laco = threading.get_ident()
    assert espiao["encode"] and espiao["validate"]
    assert all(thread != laco for thread, _ in espiao["encode"] + espiao["validate"])


@pytest.mark.asyncio
@pytest.mark.parametrize("destino", ["disco", "mongo"])
async def test_o_que_a_thread_recebe_e_uma_copia_dos_dados_do_player(espiao, destino):
    cog = cog_do_mongo()[0] if destino == "mongo" else cog_de_sessoes()
    dados = sessao_minima(queue=[faixa_info(0)], played=[faixa_info(1)])
    await salvar(cog, dados)
    (_, recebido), *_ = espiao["encode"]
    assert recebido is not dados
    assert recebido["queue"] is not dados["queue"] and recebido["queue"][0] is not dados["queue"][0]
    assert recebido["played"][0] is not dados["played"][0]


@pytest.mark.asyncio
async def test_mudanca_no_player_depois_da_chamada_nao_entra_na_sessao_gravada(tmp_path):
    cog = cog_de_sessoes()
    dados = sessao_minima(queue=[faixa_info(0)])
    titulo = dados["queue"][0]["title"]
    tarefa = asyncio.create_task(cog.save_session_local(SERVIDOR, dados))
    await asyncio.sleep(0)  # a gravação começa e tira a cópia; o resto roda na thread
    dados["queue"][0]["title"] = "mudou depois"
    dados["queue"].append(faixa_info(5))
    await tarefa
    gravado = json.loads((pasta_json(tmp_path) / f"{SERVIDOR}.json").read_bytes())
    assert [f["title"] for f in gravado["queue"]] == [titulo]


@pytest.mark.asyncio
async def test_o_conteudo_gravado_e_o_mesmo_de_antes(tmp_path):
    cog = cog_de_sessoes()
    dados = sessao_minima(queue=[faixa_info(0), faixa_info(1)])
    await cog.save_session_local(SERVIDOR, dados)
    assert (pasta_json(tmp_path) / f"{SERVIDOR}.json").read_bytes() == codec.encode_session(dados)

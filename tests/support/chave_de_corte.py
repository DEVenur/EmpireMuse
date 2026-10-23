"""Apoio dos testes da etapa 2b da F3-6b (a "chave de corte"): os pontos de leitura passam por ``load_legacy``.

DECISÕES DE COMPORTAMENTO da 2b (para inverter uma, troque aqui e na implementação):
* sessão (disco e Mongo): a sessão recusada é PULADA (as outras são lidas) e fica onde está (arquivo/documento); um aviso
  ``WARNING`` leva o ``guild_id`` e o ``code`` da falha, nada do conteúdo;
* fila salva: ``GenericError`` em português com a palavra "incompatível" e o arquivo FICA; o mesmo aviso no log (com o
  ``guild_id`` da interação);
* skin: o texto legado PERMANECE no documento e a skin recusada NÃO chega ao player (que cai na skin padrão); aviso no log
  com ``guild_id`` e ``code``; no ``load_skin`` o editor não entra em modo de edição e o usuário recebe mensagem com
  "incompatível"; no ``change_skin`` o dono recebe mensagem com "incompatível"; skin ``""`` vale como sem skin (igual a
  ``{}`` e ``None``: sem erro, sem aviso, ``load_skin`` abre a skin padrão do editor);
* caches (``playlist_cache.pkl``, ``partial_track_cache.pkl``, ``.lyric_cache_data``, ``.lastfm_cache``): o arquivo é
  APAGADO sem ser aberto; o cache recomeça vazio; nenhum outro arquivo é tocado.
"""

import logging
import os
import pickle
import posix
import subprocess
import sys

from tests.support.leitor_legado import (
    SEGREDO,
    chamada,
    comprimido,
    dicionario,
    em_base64,
    legacy_pickle,
    lista,
    pickle_de,
    texto,
)


class Armadilhas:
    """Sentinela criado por qualquer carga EXECUTADA e espiões que impedem os comandos de rodar de verdade."""

    def __init__(self, alvo, chamadas):
        self.alvo, self.chamadas = alvo, chamadas

    def intacto(self) -> bool:
        return not self.alvo.exists() and not self.chamadas


def criar_armadilhas(tmp_path, monkeypatch) -> Armadilhas:
    chamadas = []

    def espiao(nome):
        def registrar(*args, **kwargs):
            chamadas.append(nome)
            raise AssertionError(f"{nome} foi chamado")

        return registrar

    monkeypatch.setattr(os, "system", espiao("os.system"))
    monkeypatch.setattr(posix, "system", espiao("posix.system"))
    monkeypatch.setattr(subprocess, "Popen", espiao("subprocess.Popen"))
    return Armadilhas(tmp_path / "executou", chamadas)


def cargas_hostis(armadilhas: Armadilhas) -> dict[str, tuple[bytes, str]]:
    """``{nome: (pickle montado, code esperado)}``: nenhuma é executada; todas têm de ser recusadas por ``load_legacy``."""
    comando = texto(f"touch {armadilhas.alvo}")
    return {
        "execucao": (pickle_de(chamada("posix", "system", comando)), "global"),
        "segredo-no-global": (pickle_de(chamada(SEGREDO, SEGREDO, texto(SEGREDO))), "global"),
        "protocolo-3": (pickle.dumps({SEGREDO: {1, 2}}, protocol=3), "protocol"),
        "truncada": (pickle_de(dicionario((texto(SEGREDO), texto(SEGREDO))), parar=False), "corrupt"),
        "raiz-nao-dicionario": (pickle_de(lista(texto(SEGREDO))), "type"),
    }


def como_sessao_no_disco(dados: bytes) -> bytes:
    return comprimido(dados)


def como_sessao_no_mongo(dados: bytes) -> str:
    return em_base64(comprimido(dados))


def como_fila(dados: bytes) -> bytes:
    return comprimido(dados)


def como_skin(dados: bytes) -> str:
    return em_base64(dados)


# ============================================================================ o espião do load_legacy


def espionar_load_legacy(monkeypatch) -> list[tuple[str, str]]:
    """Troca ``load_legacy`` em todo módulo do projeto que o tenha importado; devolve ``[(kind, tipo do raw)]``.

    Funciona seja qual for o jeito de importar (``from ... import load_legacy`` ou ``legacy_pickle.load_legacy``) e chama a
    função de verdade, para o teste ver o efeito completo.
    """
    original = legacy_pickle.load_legacy
    chamadas: list[tuple[str, str]] = []

    def espiao(raw, kind):
        chamadas.append((kind, type(raw).__name__))
        return original(raw, kind)

    for nome, modulo in list(sys.modules.items()):
        if nome.startswith("empiremuse") and getattr(modulo, "load_legacy", None) is original:
            monkeypatch.setattr(modulo, "load_legacy", espiao)
    return chamadas


# ============================================================================ o que o log pode e não pode ter


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

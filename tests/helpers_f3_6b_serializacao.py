"""Apoio dos testes da etapa 1 da F3-6b: o núcleo de ``empiremuse/serialization/`` (``schema`` e ``codec``).

Os módulos novos são importados SOB DEMANDA (``schema`` e ``codec`` abaixo são proxies): sem a pasta ``serialization/`` cada
teste falha de verdade com ``ModuleNotFoundError`` no corpo (nenhum erro de coleta derruba a suíte). Por isso os casos
parametrizados guardam funções que recebem o módulo, e nunca montam um ``Str(...)`` na hora da coleta.

Todas as DECISÕES DE ASSINATURA que o plano deixou em aberto estão neste arquivo (códigos de erro, formato do caminho,
limites padrão): para inverter uma decisão, troque o valor aqui e na implementação.
"""

import importlib

import pytest

# ============================================================================ decisões de assinatura (fáceis de inverter)

# Códigos de ``SchemaError.code``: texto curto e estável, sem o valor do dado.
TYPE = "type"  # tipo errado (inclui ``bool`` onde se pede inteiro e subclasses de ``str``/``int``)
RANGE = "range"  # inteiro ou número fora da faixa do campo
LENGTH = "length"  # texto ou lista fora do tamanho do campo
PATTERN = "pattern"  # texto que não casa (``fullmatch``) com o padrão do campo
MISSING = "missing"  # campo obrigatório ausente
UNKNOWN_FIELD = "unknown_field"  # campo desconhecido com ``extra="error"``
KEY_NOT_TEXT = "key_not_text"  # chave de dicionário que não é ``str``
DUPLICATE_KEY = "duplicate_key"  # chave repetida no JSON
SURROGATE = "surrogate"  # texto com surrogate solto
CONTROL = "control"  # texto com caractere de controle (Cc) ou de formatação (Cf)
NOT_FINITE = "not_finite"  # NaN, Infinity ou número que estoura para infinito (1e999)
DEPTH = "depth"  # aninhamento acima do teto
NODES = "nodes"  # visitas acima do teto de nós
TOO_BIG = "too_big"  # tamanho bruto ou descomprimido acima do teto
SYNTAX = "syntax"  # JSON mal formado
ENCODING = "encoding"  # bytes que não são UTF-8
ENVELOPE = "envelope"  # base64/zlib inválido, truncado ou com sobra
NUMBER = "number"  # literal numérico que o Python não converte (milhares de dígitos)
VERSION = "version"  # campo ``v`` ausente, de tipo errado ou maior que o suportado

# Limites padrão (DE-4): campo livre conta A PARTIR DO VALOR DO CAMPO; o validador estrutural conta DA RAIZ.
FIELD_DEPTH = 8
FIELD_NODES = 5_000
STRUCTURE_DEPTH = 12
STRUCTURE_NODES = 2_000_000
SNOWFLAKE_MAX = 2**63 - 1

LOGGER = "empiremuse.serialization.schema"  # onde os campos desconhecidos descartados avisam (sem nomes nem valores)
LIMITE_DE_TEMPO = 8.0  # segundos que um caso hostil pode levar (sem o teto levaria horas ou esgotaria a memória)
PAR_DE_SURROGATES = chr(0xD83D) + chr(0xDE00)  # dois surrogates soltos (NÃO é o emoji, que é um só caractere)
SEGREDO = "SEGREDO-do-usuario-7f3a"  # marcador que NUNCA pode aparecer em mensagem, caminho ou log


# ============================================================================ importação sob demanda


class _Modulo:
    def __init__(self, nome: str):
        self._nome = nome

    def __getattr__(self, atributo: str):
        return getattr(importlib.import_module(self._nome), atributo)


schema = _Modulo("empiremuse.serialization.schema")
codec = _Modulo("empiremuse.serialization.codec")


# ============================================================================ construtores de casos


def falha(funcao, *args, **kwargs):
    """Chama ``funcao`` esperando ``SchemaError`` e devolve o erro."""
    with pytest.raises(schema.SchemaError) as info:
        funcao(*args, **kwargs)
    return info.value


def aninhado(niveis: int, folha=0):
    """``niveis`` listas encaixadas (iterativo): ``aninhado(3)`` é ``[[[0]]]``; a profundidade medida é ``niveis``."""
    valor = folha
    for _ in range(niveis):
        valor = [valor]
    return valor


def aninhado_em_dicionarios(niveis: int, folha=0):
    valor = folha
    for _ in range(niveis):
        valor = {"a": valor}
    return valor


def bomba_de_compartilhamento(niveis: int, largura: int):
    """Poucos objetos, muitas visitas: cada nível repete ``largura`` vezes a MESMA referência (``largura**niveis`` nós)."""
    valor = [0]
    for _ in range(niveis - 1):
        valor = [valor] * largura
    return valor


def vazamentos(erro, segredo: str = SEGREDO) -> list[str]:
    """Onde o ``segredo`` aparece no erro (mensagem, representação, caminho, argumentos); lista vazia = sem vazamento."""
    achados = []
    for rotulo, texto in (
        ("str", str(erro)),
        ("repr", repr(erro)),
        ("path", str(erro.path)),
        ("args", repr(erro.args)),
    ):
        if segredo in texto:
            achados.append(rotulo)
    return achados

"""Apoio dos testes das skins personalizadas (dicionário JSON; o texto do formato antigo não é mais lido).

DECISÕES DA ETAPA 3 (para inverter uma, troque aqui e na implementação):
* o esquema vive em ``empiremuse/serialization/skins.py`` (``validate_skin(dict) -> dict``, só biblioteca padrão); devolve um
  dicionário NOVO e limpo, sem o ``"v"`` (P5), levanta ``SchemaError(path, code)`` sem o valor e NÃO acrescenta chave que a
  entrada não tinha (o ``skin_converter`` trata chave ausente de um jeito e ``None`` de outro);
* o helper ``load_custom_skins(bot, guild_id, global_data)`` é uma corrotina, mora FORA de ``serialization/`` (usa o bot) e é a
  única porta de leitura da skin: valida cada dicionário, ignora o texto do formato antigo e nunca grava o documento; o que for
  recusado (formato antigo ou esquema) continua como está no documento, com um WARNING só com ``guild_id`` (e ``code``);
* ``""``, ``{}`` e ``None`` valem como sem skin: ficam como estão no documento (sem escrita, sem aviso) e o player não os recebe;
* texto livre da skin: sem surrogate solto e sem controle ``Cc`` (menos ``\\n``, ``\\r`` e ``\\t``); ``Cf`` PASSA (``U+200D`` dos
  emojis compostos e ``U+200B``, o truque de campo "em branco" do embed, são comuns em skins reais). Nome da skin: 1 a 64
  caracteres, sem ``Cc``/``Cf``, sem ``.`` nem ``$`` (vale ao SALVAR; um nome antigo já gravado não é mexido na leitura);
* ao salvar: skin inválida não grava nada (mensagem ao dono, log só com ``guild_id`` e ``code``); o que é gravado é a cópia
  validada, nunca o objeto do editor (achado D: o editor segue aberto e continua editando); no máximo 25 skins por modo.
"""

import ast
import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

from tests.support.serializacao_nucleo import _Modulo
from tests.support.raiz import RAIZ

esquema_de_skins = _Modulo("empiremuse.serialization.skins")

LIMITES = SimpleNamespace(
    queue_max_entries=25,
    queue_format=500,
    content=4000,
    embeds=10,
    title=256,
    description=4096,
    fields=25,
    field_name=256,
    field_value=1024,
    footer_text=2048,
    author_name=256,
    url=2048,
    color_texto=64,
    color_numero=0xFFFFFF,
    skin_bytes=100 * 1024,
    skins_por_modo=25,
    nome=64,
)

ZWJ = "\u200d"  # junta emojis (Cf)
ZWSP = "\u200b"  # campo de embed "em branco" (Cf)
FAMILIA = "👨" + ZWJ + "👩" + ZWJ + "👧"


def valida(skin):
    return esquema_de_skins.validate_skin(skin)


def com_embed(**campos) -> dict:
    """Uma skin com um embed só."""
    return {"embeds": [campos]}


def com_campos(quantidade: int) -> dict:
    return com_embed(fields=[{"name": f"n{i}", "value": f"v{i}"} for i in range(quantidade)])


def tamanho_em_bytes(skin) -> int:
    return len(json.dumps(skin, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def skin_com_tamanho_minimo(bytes_alvo: int) -> dict:
    """Skin válida em CADA campo cuja soma (JSON compacto) chega a ``bytes_alvo``: embeds cheios de campos de 1 KiB."""
    embed = {
        "description": "d" * LIMITES.description,
        "fields": [{"name": "n" * 100, "value": "v" * LIMITES.field_value} for _ in range(LIMITES.fields)],
    }
    skin = {"embeds": []}
    while tamanho_em_bytes(skin) < bytes_alvo and len(skin["embeds"]) < LIMITES.embeds:
        skin["embeds"].append(copy.deepcopy(embed))
    return skin


def tipos_do_documento(documento: dict) -> dict:
    """``{modo: {nome: nome do tipo}}`` das skins de um documento global (o formato em que memória ou banco as guarda)."""
    return {
        modo: {nome: type(valor).__name__ for nome, valor in documento[modo].items()}
        for modo in ("custom_skins", "custom_skins_static")
    }


# ============================================================================ o helper único (achado por ``ast``)

PACOTE = RAIZ / "empiremuse"
NOME_DO_HELPER = "load_custom_skins"


def definicoes_do_helper() -> list[tuple[Path, ast.AST]]:
    """Toda definição de nível de módulo de ``load_custom_skins`` em ``empiremuse/`` (arquivo, nó)."""
    achados = []
    for arquivo in sorted(PACOTE.rglob("*.py")):
        if "__pycache__" in arquivo.parts:
            continue
        for no in ast.parse(arquivo.read_text(encoding="utf-8")).body:
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) and no.name == NOME_DO_HELPER:
                achados.append((arquivo, no))
    return achados


def carregar_helper():
    """A corrotina ``load_custom_skins(bot, guild_id, global_data)``, onde quer que o Backend a tenha posto."""
    achados = definicoes_do_helper()
    assert len(achados) == 1, f"esperada 1 definição de {NOME_DO_HELPER}, achadas {len(achados)}"
    arquivo, _ = achados[0]
    modulo = ".".join(("empiremuse", *arquivo.relative_to(PACOTE).with_suffix("").parts))
    return getattr(importlib.import_module(modulo), NOME_DO_HELPER)

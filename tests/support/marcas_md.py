"""Apoio dos testes de escape de markdown em nomes externos (S-31): entradas "difíceis" e um conferidor da saída.

As entradas são montadas aqui, em um lugar só; os testes e seus comentários falam apenas em "nome com marcas" e "URL com marcas". O conferidor
lê o markdown de uma saída (mensagem ou embed) e devolve os destinos dos links: nenhum deles pode apontar para o domínio ``alheio.exemplo``, que
só aparece como parte do TEXTO dos dados de entrada, nunca como destino pretendido.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

CRASE = "`"
ALHEIO = "alheio.exemplo"

# nomes com marcas de markdown no meio
NOME_COM_MARCAS = f"Nome{CRASE}](https://{ALHEIO}/p) [{CRASE}x"
NOME_COM_COLCHETES = f"[rotulo](https://{ALHEIO}/q)"
NOME_COM_CRASES = f"{CRASE}{CRASE}cod{CRASE} e *negrito* e _it_"

# URLs com marcas no meio do caminho
URL_COM_PARENTESE = f"https://ok.exemplo/x)[z](https://{ALHEIO}"
URL_COM_MAIOR = f"https://ok.exemplo/x>[z](https://{ALHEIO}"
URL_COM_CRASE = f"https://ok.exemplo/x{CRASE}y"
URL_COM_BARRA = "https://ok.exemplo/x\\y"
URL_COM_ESPACO = "https://ok.exemplo/a b"
URL_COM_CONTROLE = "https://ok.exemplo/a\tb\nc"

# a mesma URL como o helper deve devolver (percent-encode só do necessário)
URL_COM_PARENTESE_CODIFICADA = f"https://ok.exemplo/x%29[z]%28https://{ALHEIO}"
URL_COM_MAIOR_CODIFICADA = f"https://ok.exemplo/x%3E[z]%28https://{ALHEIO}"

URLS_FORA_DO_PADRAO = [
    "javascript:alert(1)",
    "data:text/html,x",
    "file:///etc/hosts",
    "ftp://ok.exemplo/x",
    "//ok.exemplo/x",
    "http:///sem-host",
    "ok.exemplo/sem-esquema",
    "",
    "   ",
]

_LINK = re.compile(r"\[([^\]]*)\]\((<[^>]*>|[^)\s]*)\)")


def destinos(texto: str) -> list[str]:
    """Destino de cada link ``[rótulo](destino)`` / ``[rótulo](<destino>)`` do texto."""
    return [d[1:-1] if d.startswith("<") and d.endswith(">") else d for _, d in _LINK.findall(texto)]


def aponta_para_o_alheio(destino: str) -> bool:
    return (
        urlsplit(destino).hostname == ALHEIO
        or destino.startswith(f"https://{ALHEIO}")
        or destino.startswith(f"http://{ALHEIO}")
    )


def links_alheios(texto: str) -> list[str]:
    return [d for d in destinos(texto) if aponta_para_o_alheio(d)]


def marcas_soltas(texto: str) -> int:
    """Quantos ``](`` há no texto além dos que formam um link bem-formado (um ``](`` solto é um link quebrado ou um link a mais)."""
    return texto.count("](") - len(destinos(texto))

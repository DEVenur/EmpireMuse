"""``client_ip_from_headers``: o IP do visitante vem de ``CF-Connecting-IP`` só com proxy confiável e só se for um IP válido."""

import pytest

from empiremuse.rules.client_ip import client_ip_from_headers

pytestmark = pytest.mark.regression

BORDA = "172.70.1.1"  # o IP que o proxy da frente enxerga: a borda da Cloudflare, igual para todos os visitantes


@pytest.mark.parametrize(
    ("enviado", "esperado"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("  203.0.113.7  ", "203.0.113.7"),
        ("2001:db8::1", "2001:db8::1"),
        ("2001:0DB8:0:0:0:0:0:1", "2001:db8::1"),
    ],
    ids=["ipv4", "ipv4-com-espacos", "ipv6", "ipv6-canonico"],
)
def test_ip_valido_do_cabecalho_e_usado_com_proxy_confiavel(enviado: str, esperado: str) -> None:
    assert client_ip_from_headers({"CF-Connecting-IP": enviado}, True, BORDA) == esperado


@pytest.mark.parametrize(
    "enviado",
    ["", "abc", "999.1.1.1", "203.0.113.7, 198.51.100.1", "203.0.113.7:443", "fe80::1%eth0", "<script>"],
    ids=["vazio", "texto", "fora-da-faixa", "lista", "com-porta", "com-escopo", "marcacao"],
)
def test_valor_invalido_e_ignorado_e_vale_o_ip_ja_resolvido(enviado: str) -> None:
    assert client_ip_from_headers({"CF-Connecting-IP": enviado}, True, BORDA) == BORDA


def test_sem_proxy_confiavel_o_cabecalho_e_ignorado_mesmo_valido() -> None:
    """Um cliente que chega direto poderia forjar o cabeçalho."""
    assert client_ip_from_headers({"CF-Connecting-IP": "203.0.113.7"}, False, "198.51.100.9") == "198.51.100.9"


def test_cabecalho_ausente_mantem_o_ip_ja_resolvido() -> None:
    assert client_ip_from_headers({"X-Real-IP": "10.0.0.1"}, True, BORDA) == BORDA
    assert client_ip_from_headers({}, True, None) is None


def test_nome_do_cabecalho_nao_diferencia_maiusculas() -> None:
    assert client_ip_from_headers({"cf-connecting-ip": "203.0.113.7"}, True, BORDA) == "203.0.113.7"

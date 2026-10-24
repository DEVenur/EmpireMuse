"""``ClientIpRouter``: um só ponto define ``request.remote_ip`` para o painel, a página de status e o relé ``/ws``."""

from typing import Any

import pytest
import tornado.httputil
import tornado.routing

from empiremuse.web_app import ClientIpRouter

pytestmark = pytest.mark.regression

BORDA = "172.70.1.1"  # o IP que o Tornado enxerga atrás do proxy: a borda da Cloudflare, igual para todos os visitantes
VISITANTE = "203.0.113.7"


class Interno(tornado.routing.Router):
    """O roteador de baixo: guarda o IP que recebeu e devolve um marcador no lugar do handler."""

    def __init__(self) -> None:
        self.ips: list[str | None] = []

    def find_handler(self, request: tornado.httputil.HTTPServerRequest, **kwargs: Any) -> Any:
        self.ips.append(request.remote_ip)
        return "handler"


def passar_pelo_roteador(trust_proxy: bool, cabecalhos: dict[str, str]) -> tuple[str | None, Any]:
    interno = Interno()
    requisicao = tornado.httputil.HTTPServerRequest(
        method="GET", uri="/painel/login", headers=tornado.httputil.HTTPHeaders(cabecalhos)
    )
    requisicao.remote_ip = BORDA  # já resolvido pelo servidor (xheaders), antes do roteamento
    delegate = ClientIpRouter(interno, trust_proxy).find_handler(requisicao)
    return interno.ips[0], delegate


def test_com_proxy_confiavel_o_ip_do_visitante_chega_ao_painel_e_ao_rele() -> None:
    ip, delegate = passar_pelo_roteador(True, {"CF-Connecting-IP": VISITANTE, "X-Real-IP": BORDA})
    assert ip == VISITANTE and delegate == "handler"


@pytest.mark.parametrize(
    "cabecalhos",
    [{}, {"CF-Connecting-IP": "não é um ip"}, {"CF-Connecting-IP": f"{VISITANTE}, 198.51.100.1"}],
    ids=["ausente", "invalido", "lista"],
)
def test_sem_cabecalho_valido_vale_o_ip_ja_resolvido_pelo_servidor(cabecalhos: dict[str, str]) -> None:
    assert passar_pelo_roteador(True, cabecalhos)[0] == BORDA


def test_sem_proxy_confiavel_o_cabecalho_forjado_e_ignorado() -> None:
    assert passar_pelo_roteador(False, {"CF-Connecting-IP": VISITANTE})[0] == BORDA

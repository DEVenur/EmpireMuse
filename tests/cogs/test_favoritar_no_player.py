"""F3-5b, etapa 0 — A4: os botões "favoritar" do player (``Music.player_controller``), em VERDE.

Não existem no painel e escrevem em ``fav_links`` sem a regra dos modais: o botão do embed soma a quantidade de
favoritos com ela mesma (2n) e não valida o nome; o seletor trunca o NOME com o limite de URL e conta uma
sobrescrita como vaga. Chama o ``player_controller`` REAL com dublês. ``# MUDA (etapa N, A4)`` marca o que muda.
"""

import pytest

from tests.support.drivers_de_regras import (
    BotDoPlayer,
    favoritar_pelo_embed,
    favoritar_pelo_seletor,
    gravou,
)

BOTOES = [
    pytest.param(favoritar_pelo_embed, id="botao_do_embed"),
    pytest.param(favoritar_pelo_seletor, id="seletor_do_player"),
]


class TestA4NomeVindoDaFaixa:
    """Etapa 3 (A4/D3): o nome vem do título da faixa, não de quem digita. É truncado em 25 caracteres e limpo
    (sem controle/formatação, sem espaços nas pontas); só é recusado se sobrar menos de 2 caracteres. O limite de URL
    da configuração (antes usado por engano no seletor) não interfere."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("favoritar", list(BOTOES)[:2])
    @pytest.mark.parametrize("titulo", ["a", "", "   ", "a\u200b", "\u200b\u200b"], ids=repr)
    async def test_nome_com_menos_de_2_caracteres_depois_de_limpo_e_recusado(self, favoritar, titulo):
        bot = BotDoPlayer()
        inter = await favoritar(bot, titulo)
        assert not gravou(bot) and inter.texto, "recusa com uma mensagem ao usuário"


def url_com_tamanho(tamanho):
    base = "https://exemplo.invalid/"
    return base + "x" * (tamanho - len(base))


class TestA4UrlVindaDaFaixa:
    """Etapa 4 (A4): a URL da faixa passa pela regra de URL dos favoritos (URL inteira limpa, até 200 caracteres) em vez
    de ser gravada sem validação."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("favoritar", list(BOTOES)[:2])
    @pytest.mark.parametrize(
        "url",
        [
            url_com_tamanho(201),
            "https://exemplo.invalid/" + "x" * 300,
            "https://exemplo.invalid/a]b",
            "https://exemplo.invalid/@everyone",
            "https://exemplo.invalid/a texto",
            "https://exemplo.invalid/a\ntexto",
        ],
        ids=["201", "300", "colchete", "everyone", "espaco", "quebra_de_linha"],
    )
    async def test_url_invalida_ou_longa_demais_e_recusada(self, favoritar, url):
        bot = BotDoPlayer()
        inter = await favoritar(bot, "Faixa", url)
        assert not gravou(bot) and inter.texto, "recusa com uma mensagem ao usuário"

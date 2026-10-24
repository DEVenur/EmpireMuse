"""F3-5b, etapa 0 — A4: os botões "favoritar" do player (``Music.player_controller``), em VERDE.

Não existem no painel e escrevem em ``fav_links`` sem a regra dos modais: o botão do embed soma a quantidade de
favoritos com ela mesma (2n) e não valida o nome; o seletor trunca o NOME com o limite de URL e conta uma
sobrescrita como vaga. Chama o ``player_controller`` REAL com dublês. ``# MUDA (etapa N, A4)`` marca o que muda.
"""

from types import SimpleNamespace

import pytest

from empiremuse.cogs.music import Music
from empiremuse.utils.others import PlayerControls
from tests.support.drivers_de_regras import (
    BotDoPlayer,
    MusicaFalsa,
    favoritar_pelo_embed,
    favoritar_pelo_seletor,
    gravou,
    interacao,
)

URL = "https://exemplo.invalid/musica"


def salvos(bot):
    """Os favoritos gravados pelo botão; falha com uma mensagem clara se NADA foi gravado."""
    assert gravou(bot), "nada foi gravado (o favorito foi recusado)"
    return bot.ultimo_global["fav_links"]


class TestA4BotaoDoEmbed:
    @pytest.mark.asyncio
    async def test_a_cota_e_exata_e_vai_ate_o_decimo_favorito(self):
        """Etapa 2 (A4): a cota conta os favoritos UMA vez (antes somava a quantidade com ela mesma e travava em 6)."""
        for existentes in (5, 6, 9):
            bot = BotDoPlayer(favs=10, favoritos={f"f{i}": URL for i in range(existentes)})
            await favoritar_pelo_embed(bot, "Novo")
            assert "Novo" in salvos(bot), f"com {existentes} favoritos e limite 10 deveria salvar"
            assert len(salvos(bot)) == existentes + 1

    @pytest.mark.asyncio
    async def test_guarda_com_10_favoritos_e_limite_10_um_nome_novo_e_recusado(self):
        bot = BotDoPlayer(favs=10, favoritos={f"f{i}": URL for i in range(10)})
        inter = await favoritar_pelo_embed(bot, "Novo")
        assert not gravou(bot) and "espaço suficiente" in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_sem_embed_a_mensagem_foi_removida(self):
        bot = BotDoPlayer()
        inter = interacao(SimpleNamespace(me=SimpleNamespace()))
        await Music.player_controller(MusicaFalsa(bot), inter, PlayerControls.embed_add_fav)
        assert not gravou(bot) and "embed da mensagem foi removida" in inter.texto


class TestA4SeletorDoPlayer:
    @pytest.mark.asyncio
    async def test_guarda_a_cota_do_seletor_e_exata_ao_contrario_do_botao_do_embed(self):
        cabe = BotDoPlayer(favs=10, favoritos={f"f{i}": URL for i in range(9)})
        await favoritar_pelo_seletor(cabe, "Décimo")
        assert "Décimo" in salvos(cabe)
        cheio = BotDoPlayer(favs=10, favoritos={f"f{i}": URL for i in range(10)})
        await favoritar_pelo_seletor(cheio, "Décimo primeiro")
        assert not gravou(cheio)


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

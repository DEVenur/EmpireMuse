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
    async def test_guarda_grava_o_favorito_abaixo_do_limite_com_o_nome_do_autor_do_embed(self):
        bot = BotDoPlayer(favoritos={f"f{i}": URL for i in range(3)})
        await favoritar_pelo_embed(bot, "Minha musica")
        assert salvos(bot)["Minha musica"] == URL

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
    @pytest.mark.parametrize("existentes", [6, 10], ids=["lista_com_folga", "lista_cheia"])
    async def test_sobrescrever_um_nome_existente_nao_ocupa_vaga(self, existentes):
        """Etapa 2 (A4): trocar a URL de um favorito que já existe funciona mesmo com a lista cheia."""
        bot = BotDoPlayer(favs=10, favoritos={f"f{i}": URL for i in range(existentes)})
        await favoritar_pelo_embed(bot, "f0", "https://exemplo.invalid/outra")
        gravados = salvos(bot)
        assert gravados["f0"] == "https://exemplo.invalid/outra" and len(gravados) == existentes

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("favs", "dono"), [(0, False), (3, True)], ids=["sem_limite", "dono_isento"])
    async def test_guarda_zero_e_dono_ignoram_o_limite(self, favs, dono):
        bot = BotDoPlayer(favs=favs, dono=dono, favoritos={f"f{i}": URL for i in range(8)})
        await favoritar_pelo_embed(bot, "Mais um")
        assert "Mais um" in salvos(bot)

    @pytest.mark.asyncio
    async def test_guarda_sem_embed_a_mensagem_foi_removida(self):
        bot = BotDoPlayer()
        inter = interacao(SimpleNamespace(me=SimpleNamespace()))
        await Music.player_controller(MusicaFalsa(bot), inter, PlayerControls.embed_add_fav)
        assert not gravou(bot) and "embed da mensagem foi removida" in inter.texto


class TestA4SeletorDoPlayer:
    @pytest.mark.asyncio
    async def test_guarda_grava_o_favorito_abaixo_do_limite(self):
        bot = BotDoPlayer(favoritos={"f0": URL})
        await favoritar_pelo_seletor(bot, "Minha musica")
        assert salvos(bot)["Minha musica"] == URL and bot.eventos == ["fav_add"]

    @pytest.mark.asyncio
    async def test_sobrescrever_um_nome_existente_com_a_lista_cheia_salva(self):
        """Etapa 2 (A4): sobrescrever não ocupa vaga (antes o seletor recusava com a lista cheia)."""
        bot = BotDoPlayer(favs=3, favoritos={"f0": URL, "f1": URL, "f2": URL})
        await favoritar_pelo_seletor(bot, "f0", "https://exemplo.invalid/outra")
        assert salvos(bot) == {
            "f0": "https://exemplo.invalid/outra",
            "f1": URL,
            "f2": URL,
        }

    @pytest.mark.asyncio
    async def test_guarda_a_cota_do_seletor_e_exata_ao_contrario_do_botao_do_embed(self):
        cabe = BotDoPlayer(favs=10, favoritos={f"f{i}": URL for i in range(9)})
        await favoritar_pelo_seletor(cabe, "Décimo")
        assert "Décimo" in salvos(cabe)
        cheio = BotDoPlayer(favs=10, favoritos={f"f{i}": URL for i in range(10)})
        await favoritar_pelo_seletor(cheio, "Décimo primeiro")
        assert not gravou(cheio)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("favs", "dono"), [(0, False), (3, True)], ids=["sem_limite", "dono_isento"])
    async def test_guarda_zero_e_dono_ignoram_o_limite(self, favs, dono):
        bot = BotDoPlayer(favs=favs, dono=dono, favoritos={f"f{i}": URL for i in range(8)})
        await favoritar_pelo_seletor(bot, "Mais um")
        assert "Mais um" in salvos(bot)


BOTOES = [
    pytest.param(favoritar_pelo_embed, id="botao_do_embed"),
    pytest.param(favoritar_pelo_seletor, id="seletor_do_player"),
]


class TestA4NomeVindoDaFaixa:
    """Etapa 3 (A4/D3): o nome vem do título da faixa, não de quem digita. É truncado em 25 caracteres e limpo
    (sem controle/formatação, sem espaços nas pontas); só é recusado se sobrar menos de 2 caracteres. O limite de URL
    da configuração (antes usado por engano no seletor) não interfere."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("favoritar", BOTOES)
    @pytest.mark.parametrize(
        ("titulo", "esperado"),
        [
            ("t" * 60, "t" * 25),
            ("t" * 25, "t" * 25),
            ("t" * 60 + "\u200b", "t" * 25),
            ("  Minha música  ", "Minha música"),
            ("ab\u200bcd", "abcd"),
            ("a\x07bc", "abc"),
            ("x" * 24 + " " + "y" * 10, "x" * 24),
            ("ab", "ab"),
        ],
        ids=[
            "longo",
            "no_limite",
            "longo_com_cf_no_fim",
            "pontas",
            "cf_no_meio",
            "controle",
            "corte_em_espaco",
            "dois",
        ],
    )
    async def test_nome_truncado_e_limpo(self, favoritar, titulo, esperado):
        bot = BotDoPlayer(url_max=90)
        await favoritar(bot, titulo)
        assert list(salvos(bot)) == [esperado]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("favoritar", BOTOES)
    @pytest.mark.parametrize("titulo", ["a", "", "   ", "a\u200b", "\u200b\u200b"], ids=repr)
    async def test_nome_com_menos_de_2_caracteres_depois_de_limpo_e_recusado(self, favoritar, titulo):
        bot = BotDoPlayer()
        inter = await favoritar(bot, titulo)
        assert not gravou(bot) and inter.texto, "recusa com uma mensagem ao usuário"

    @pytest.mark.asyncio
    async def test_o_limite_de_url_da_configuracao_nao_vira_o_limite_do_nome(self):
        bot = BotDoPlayer(url_max=40)
        await favoritar_pelo_seletor(bot, "t" * 60)
        assert list(salvos(bot)) == ["t" * 25]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("favoritar", BOTOES)
    async def test_sobrescrever_acontece_pelo_nome_ja_truncado(self, favoritar):
        """Duas faixas de títulos longos que começam igual caem no mesmo nome de 25 caracteres: a 2ª sobrescreve."""
        bot = BotDoPlayer(favs=1, favoritos={"t" * 25: URL})
        await favoritar(bot, "t" * 60, "https://exemplo.invalid/outra")
        assert salvos(bot) == {"t" * 25: "https://exemplo.invalid/outra"}


def url_com_tamanho(tamanho):
    base = "https://exemplo.invalid/"
    return base + "x" * (tamanho - len(base))


class TestA4UrlVindaDaFaixa:
    """Etapa 4 (A4): a URL da faixa passa pela regra de URL dos favoritos (URL inteira limpa, até 200 caracteres) em vez
    de ser gravada sem validação."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("favoritar", BOTOES)
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

    @pytest.mark.asyncio
    @pytest.mark.parametrize("favoritar", BOTOES)
    async def test_url_valida_ate_200_e_gravada(self, favoritar):
        bot = BotDoPlayer()
        url = url_com_tamanho(200)
        await favoritar(bot, "Faixa", url)
        assert salvos(bot) == {"Faixa": url}

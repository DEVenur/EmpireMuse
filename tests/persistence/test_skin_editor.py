"""F3-6b, etapa 3 (RED) — o editor de skin grava DICIONÁRIO validado (``SkinEditorMenu.modal_handler``, botão de salvar).

* a skin salva é a CÓPIA validada por ``validate_skin`` (nunca o objeto do editor), sem texto e sem ``"v"``;
* skin inválida (também a que chegou pela importação de JSON) não grava nada e o dono recebe uma mensagem;
* nome da skin: 1 a 64 caracteres sem ``Cc``/``Cf``, sem ``.`` nem ``$``; no máximo 25 skins por modo;
* achado D (cópia rasa): memória (o cache do banco) e banco ficam no MESMO formato depois de salvar, e continuar editando não
  mexe em nada que já foi salvo, nem no que o player usa;
* downgrade seguro: o que é gravado é JSON puro e a versão antiga, que só converte texto, entrega o mesmo embed.
"""

import copy
import json
import logging
from types import SimpleNamespace

import pytest

from empiremuse.utils.music.skin_utils import skin_converter
from tests.support.chave_de_corte import log_sem_o_conteudo
from tests.support.leitor_legado import SEGREDO
from tests.support.serializacao_nucleo import PAR_DE_SURROGATES
from tests.support.skins import FAMILIA, LIMITES, ZWSP, skin_com_tamanho_minimo, tipos_do_documento, valida
from tests.persistence.test_formato_skin import (
    BotaoDeModo,
    InteracaoDoEditor,
    Jogador,
    dados_globais,
    skin_realista,
    texto_legado,
)
from tests.persistence.test_formato_skin import editor_sem_tela as _base_do_editor


@pytest.fixture
def editor_sem_tela(request):
    """O editor de ``tests/test_f3_6b_formato_skin.py`` já aberto em modo ``editor`` (só nele se salva ou importa skin)."""

    base = request.getfixturevalue("_base_do_editor")

    def montar(*args, **kwargs):
        menu, bot, contexto = base(*args, **kwargs)
        menu.mode = "editor"
        return menu, bot, contexto

    return montar


async def salvar(menu, nome="Minha", modo="custom_skins"):
    BotaoDeModo.modo = modo
    interacao = InteracaoDoEditor(skin_name=nome)
    await menu.modal_handler(interacao)
    return interacao


async def passo(menu, custom_id, **textos):
    interacao = InteracaoDoEditor(**textos)
    interacao.custom_id = custom_id
    await menu.modal_handler(interacao)
    return interacao


def escolha(valor: str) -> InteracaoDoEditor:
    """A interação do select de skins (``values``) no formato que o editor guarda como ``ctx``."""
    interacao = InteracaoDoEditor()
    interacao.values = [valor]
    return interacao


def mensagens_ao_dono(interacao) -> list[str]:
    """O que o dono leu além do pedido de modo e do aviso de sucesso."""
    return [m for m in interacao.enviados if m and "Selecione" not in m and "sucesso" not in m]


def salvo_com_sucesso(interacao) -> bool:
    return any("sucesso" in (m or "") for m in interacao.enviados)


def esperada(skin: dict) -> dict:
    """O que o editor grava: a skin, com ``controller_enabled`` ligado quando ela não o traz (o botão de modo parte do dela)."""
    return valida({"controller_enabled": True, **skin})


# ============================================================================ o que é gravado


class TestSalvaDicionario:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", ["custom_skins", "custom_skins_static"])
    async def test_grava_a_copia_validada_como_dicionario(self, editor_sem_tela, modo):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = skin_realista()
        await salvar(menu, "Minha", modo)
        gravada = bot.banco[modo]["Minha"]
        assert type(gravada) is dict and gravada == esperada(skin_realista())
        assert "v" not in gravada

    @pytest.mark.asyncio
    async def test_o_gravado_e_json_puro(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = skin_realista()
        await salvar(menu)
        assert json.loads(json.dumps(bot.banco)) == bot.banco

    @pytest.mark.asyncio
    async def test_a_gravacao_nao_e_o_objeto_do_editor(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = skin_realista()
        await salvar(menu)
        for documento in (bot.global_data, bot.banco):
            gravada = documento["custom_skins"]["Minha"]
            assert gravada is not menu.message_data and gravada["embeds"] is not menu.message_data["embeds"]
            assert gravada["embeds"][2]["fields"] is not menu.message_data["embeds"][2]["fields"]

    @pytest.mark.asyncio
    async def test_nenhuma_skin_do_documento_gravado_e_texto_nem_as_legadas(self, editor_sem_tela):
        dados = dados_globais(
            normais={"Velha": texto_legado(skin_realista(content="velha"))},
            estaticas={"Fixa": texto_legado(skin_realista(content="fixa"))},
        )
        menu, bot, _ = editor_sem_tela(dados)
        menu.message_data = skin_realista()
        await salvar(menu)
        assert tipos_do_documento(bot.banco) == {
            "custom_skins": {"Velha": "dict", "Minha": "dict"},
            "custom_skins_static": {"Fixa": "dict"},
        }
        assert bot.banco["custom_skins"]["Velha"] == skin_realista(content="velha")

    @pytest.mark.asyncio
    async def test_renomear_remove_o_nome_antigo(self, editor_sem_tela):
        dados = dados_globais(normais={"Antiga": skin_realista(), "Outra": skin_realista(content="o")})
        menu, bot, _ = editor_sem_tela(dados)
        menu.message_data, menu.skin_selected = skin_realista(), "> cs: Antiga"
        await salvar(menu, "Nova")
        assert sorted(bot.banco["custom_skins"]) == ["Nova", "Outra"]
        assert bot.banco["custom_skins"]["Outra"] == skin_realista(content="o")

    @pytest.mark.asyncio
    async def test_salvar_num_modo_nao_mexe_no_outro(self, editor_sem_tela):
        dados = dados_globais(normais={"N": skin_realista(content="n")}, estaticas={"F": skin_realista(content="f")})
        menu, bot, _ = editor_sem_tela(dados)
        menu.message_data = skin_realista()
        await salvar(menu, "Nova", "custom_skins_static")
        assert bot.banco["custom_skins"] == {"N": skin_realista(content="n")}
        assert sorted(bot.banco["custom_skins_static"]) == ["F", "Nova"]

    @pytest.mark.asyncio
    async def test_texto_com_emoji_composto_e_campo_em_branco_e_salvo(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = {
            "embeds": [
                {"description": f"{FAMILIA}\nlinha 2", "fields": [{"name": ZWSP, "value": ZWSP}]},
            ]
        }
        interacao = await salvar(menu)
        assert salvo_com_sucesso(interacao)
        assert bot.banco["custom_skins"]["Minha"]["embeds"][0]["fields"] == [{"name": ZWSP, "value": ZWSP}]


# ============================================================================ o que não é gravado


def skin_com(**campos) -> dict:
    return {**skin_realista(), **campos}


INVALIDAS = [
    ("descricao-longa", lambda s: skin_com(embeds=[{"description": s + "d" * LIMITES.description}])),
    ("embeds-demais", lambda s: skin_com(embeds=[{"description": s}] * (LIMITES.embeds + 1))),
    ("campo-sem-valor", lambda s: skin_com(embeds=[{"fields": [{"name": s}]}])),
    ("fila-fora-da-faixa", lambda s: skin_com(content=s, queue_max_entries=LIMITES.queue_max_entries + 1)),
    ("surrogate-solto", lambda s: skin_com(content=s + PAR_DE_SURROGATES)),
    ("controle", lambda s: skin_com(content=s + "\x00")),
    ("tipo-errado", lambda s: skin_com(embeds=s)),
    ("tamanho-total", lambda s: skin_com(embeds=skin_com_tamanho_minimo(120 * 1024)["embeds"], content=s)),
]


class TestSalvarRecusaSkinInvalida:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("nome", "monta"), INVALIDAS, ids=[i[0] for i in INVALIDAS])
    async def test_nao_grava_nada_e_o_dono_e_avisado(self, editor_sem_tela, caplog, capsys, nome, monta):
        dados = dados_globais(normais={"Antiga": skin_realista()})
        antes = copy.deepcopy(dados)
        menu, bot, _ = editor_sem_tela(dados, [Jogador()])
        menu.message_data = monta(SEGREDO)
        with caplog.at_level(logging.DEBUG):
            interacao = await salvar(menu)
        assert bot.escritas == [] and bot.global_data == antes
        assert mensagens_ao_dono(interacao) and not salvo_com_sucesso(interacao)
        assert all(SEGREDO not in (m or "") for m in interacao.enviados)
        assert log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    async def test_o_player_ativo_nao_e_mexido_quando_a_skin_e_recusada(self, editor_sem_tela):
        jogador = Jogador()
        menu, _, _ = editor_sem_tela(dados_globais(), [jogador])
        menu.message_data = skin_com(content="c" * (LIMITES.content + 1))
        await salvar(menu)
        assert jogador.custom_skin_data is None and jogador.chamadas == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "importada",
        [
            {"embeds": [{"description": "d"}] * (LIMITES.embeds + 1)},
            {"embeds": [{"description": "d" * (LIMITES.description + 1)}]},
            {"embeds": [{"description": "\ud800"}]},
            {"content": "c" * (LIMITES.content + 1)},
        ],
        ids=["embeds-demais", "descricao-longa", "surrogate-solto", "content-longo"],
    )
    async def test_json_importado_hostil_e_recusado_ao_salvar(self, editor_sem_tela, importada):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = copy.deepcopy(skin_realista())
        await passo(menu, "skin_editor_import_skin", skin=json.dumps(importada))
        interacao = await salvar(menu)
        assert bot.escritas == [] and mensagens_ao_dono(interacao) and not salvo_com_sucesso(interacao)

    @pytest.mark.asyncio
    async def test_json_importado_valido_e_salvo_como_dicionario(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(dados_globais())
        importada = {"embeds": [{"title": "Importada", "description": "{queue_format}", "color": "{guild.color}"}]}
        await passo(menu, "skin_editor_import_skin", skin=json.dumps(importada))
        assert salvo_com_sucesso(await salvar(menu))
        assert bot.banco["custom_skins"]["Minha"]["embeds"] == importada["embeds"]


# ============================================================================ nome e quantidade


class TestNomeEQuantidade:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "nome",
        [
            "",
            "   ",
            "a" * (LIMITES.nome + 1),
            "a.b",
            "$ab",
            "a$b",
            "a\x00b",
            "a\nb",
            "a\u200bb",
            "a\u202eb",
            "a\ud800b",
        ],
        ids=[
            "vazio",
            "so-espacos",
            "longo",
            "ponto",
            "cifrao-no-inicio",
            "cifrao",
            "nul",
            "quebra",
            "zwsp",
            "bidi",
            "surrogate",
        ],
    )
    async def test_nome_invalido_nao_grava_nada(self, editor_sem_tela, nome):
        menu, bot, _ = editor_sem_tela(dados_globais(normais={"Antiga": skin_realista()}))
        menu.message_data = skin_realista()
        interacao = await salvar(menu, nome)
        assert bot.escritas == [] and mensagens_ao_dono(interacao) and not salvo_com_sucesso(interacao)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "nome",
        ["a" * LIMITES.nome, "Minha skin 2", "Skin: 🎵 (ação)", "ü-ñ_x", "  com espaços nas pontas  "],
        ids=["no-limite", "espaco", "emoji-e-acentos", "acentos", "espacos-nas-pontas"],
    )
    async def test_nome_valido_e_salvo(self, editor_sem_tela, nome):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = skin_realista()
        assert salvo_com_sucesso(await salvar(menu, nome))
        assert list(bot.banco["custom_skins"]) == [nome.strip()]

    @staticmethod
    def cheio(modo="custom_skins"):
        return dados_globais(
            **{
                ("normais" if modo == "custom_skins" else "estaticas"): {
                    f"s{i}": skin_realista(content=f"s{i}") for i in range(LIMITES.skins_por_modo)
                }
            }
        )

    @pytest.mark.asyncio
    async def test_a_vigesima_sexta_skin_do_modo_e_recusada(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(self.cheio())
        menu.message_data = skin_realista()
        interacao = await salvar(menu, "Nova")
        assert bot.escritas == [] and mensagens_ao_dono(interacao) and not salvo_com_sucesso(interacao)

    @pytest.mark.asyncio
    async def test_modo_cheio_nao_impede_salvar_no_outro_modo(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(self.cheio())
        menu.message_data = skin_realista()
        assert salvo_com_sucesso(await salvar(menu, "Nova", "custom_skins_static"))
        assert len(bot.banco["custom_skins"]) == LIMITES.skins_por_modo

    @pytest.mark.asyncio
    async def test_sobrescrever_no_modo_cheio_e_permitido(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(self.cheio())
        menu.message_data, menu.skin_selected = skin_realista(content="nova"), "> cs: s0"
        assert salvo_com_sucesso(await salvar(menu, "s0"))
        assert bot.banco["custom_skins"]["s0"]["content"] == "nova"

    @pytest.mark.asyncio
    async def test_renomear_no_modo_cheio_e_permitido(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(self.cheio())
        menu.message_data, menu.skin_selected = skin_realista(), "> cs: s0"
        assert salvo_com_sucesso(await salvar(menu, "Renomeada"))
        assert len(bot.banco["custom_skins"]) == LIMITES.skins_por_modo and "s0" not in bot.banco["custom_skins"]

    @pytest.mark.asyncio
    async def test_skin_legada_recusada_tambem_conta_no_limite(self, editor_sem_tela):
        dados = self.cheio()
        dados["custom_skins"]["s0"] = "!!!isto-nao-e-base64!!!"
        menu, bot, _ = editor_sem_tela(dados)
        menu.message_data = skin_realista()
        interacao = await salvar(menu, "Nova")
        assert bot.escritas == [] and not salvo_com_sucesso(interacao)


# ============================================================================ achado D: memória e banco no mesmo formato


class TestMemoriaEBancoNoMesmoFormato:
    @pytest.mark.asyncio
    async def test_cache_e_banco_ficam_iguais_e_so_com_dicionarios_depois_de_salvar(self, editor_sem_tela):
        dados = dados_globais(
            normais={"Velha": texto_legado(skin_realista(content="velha"))},
            estaticas={"Fixa": texto_legado(skin_realista(content="fixa"))},
        )
        menu, bot, _ = editor_sem_tela(dados, [Jogador()])
        menu.message_data = skin_realista(content="nova")
        await salvar(menu, "Nova")
        assert bot.global_data == bot.banco
        assert tipos_do_documento(bot.global_data) == tipos_do_documento(bot.banco)
        assert {t for modo in tipos_do_documento(bot.banco).values() for t in modo.values()} == {"dict"}

    @pytest.mark.asyncio
    async def test_o_player_recebe_o_mesmo_que_o_banco(self, editor_sem_tela):
        dados = dados_globais(
            normais={"Velha": texto_legado(skin_realista(content="velha"))},
            estaticas={"Fixa": texto_legado(skin_realista(content="fixa"))},
        )
        jogador = Jogador()
        menu, bot, _ = editor_sem_tela(dados, [jogador])
        menu.message_data = skin_realista(content="nova")
        await salvar(menu, "Nova")
        assert jogador.custom_skin_data == bot.banco["custom_skins"]
        assert jogador.custom_skin_static_data == bot.banco["custom_skins_static"]

    @pytest.mark.asyncio
    async def test_continuar_editando_depois_de_salvar_nao_mexe_no_que_foi_salvo(self, editor_sem_tela):
        jogador = Jogador()
        menu, bot, _ = editor_sem_tela(dados_globais(), [jogador])
        menu.message_data = skin_realista()
        await salvar(menu)
        cache, banco, player = (copy.deepcopy(x) for x in (bot.global_data, bot.banco, jogador.custom_skin_data))
        menu.message_data["content"] = "editado depois, sem salvar"
        menu.message_data["embeds"][0]["title"] = "mudou"
        menu.message_data["embeds"][2]["fields"].append({"name": "x", "value": "y"})
        assert bot.global_data == cache and bot.banco == banco and jogador.custom_skin_data == player

    @pytest.mark.asyncio
    @pytest.mark.parametrize("como_esta", ["dicionario", "texto-legado"])
    async def test_load_skin_entrega_uma_copia_ao_editor(self, editor_sem_tela, como_esta):
        skin = skin_realista()
        guardada = skin if como_esta == "dicionario" else texto_legado(skin)
        dados = dados_globais(normais={"Minha": guardada})
        menu, bot, _ = editor_sem_tela(dados)
        await menu.load_skin(SimpleNamespace(values=["> cs: Minha"]))
        assert menu.message_data == skin_realista()
        antes = copy.deepcopy(bot.global_data)
        menu.message_data["content"] = "editado sem salvar"
        menu.message_data["embeds"][2]["fields"][0]["name"] = "mudou"
        assert bot.global_data == antes and bot.global_data["custom_skins"]["Minha"] == skin_realista()
        assert menu.message_data is not bot.global_data["custom_skins"]["Minha"]

    @pytest.mark.asyncio
    async def test_editar_a_skin_aberta_e_salvar_atualiza_cache_e_banco_juntos(self, editor_sem_tela):
        dados = dados_globais(normais={"Minha": skin_realista()})
        menu, bot, _ = editor_sem_tela(dados, [Jogador()])
        await menu.load_skin(escolha("> cs: Minha"))
        menu.message_data["content"] = "novo conteudo"
        await salvar(menu, "Minha")
        assert bot.global_data == bot.banco and bot.banco["custom_skins"]["Minha"]["content"] == "novo conteudo"


# ============================================================================ downgrade seguro


def renderizar(skin: dict) -> dict:
    """O que a versão ANTIGA faz com a skin: ``skin_converter`` direto sobre o dicionário (ela só convertia texto)."""
    avatar = SimpleNamespace(with_static_format=lambda formato: SimpleNamespace(url="https://exemplo.invalid/a.png"))
    servidor = SimpleNamespace(me=SimpleNamespace(color=SimpleNamespace(value=255)), name="srv", id=1, icon=None)
    contexto = SimpleNamespace(
        bot=SimpleNamespace(get_color=lambda membro: 255),
        author=SimpleNamespace(mention="<@1>", display_name="x", global_name="x", display_avatar=avatar),
    )
    saida = skin_converter(skin, guild=servidor, ctx=contexto)
    return {"content": saida.get("content"), "embeds": [embed.to_dict() for embed in saida["embeds"]]}


class TestDowngradeSeguro:
    @pytest.mark.asyncio
    async def test_a_versao_antiga_nao_tem_texto_a_converter_e_entrega_o_mesmo_embed(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = skin_realista()
        await salvar(menu)
        gravada = bot.banco["custom_skins"]["Minha"]
        assert not any(isinstance(skin, str) for skin in bot.banco["custom_skins"].values())  # o laço antigo é um no-op
        assert renderizar(gravada) == renderizar(esperada(skin_realista()))


# ============================================================================ skins montadas pelo próprio editor


PASSOS_COMPLETOS = [
    (
        "skin_editor_add_embed",
        dict(
            skin_embed_title="Título 🎵",
            skin_embed_description="Descrição\nlinha 2",
            image_url="https://exemplo.invalid/i.png",
            thumbnail_url="https://exemplo.invalid/t.png",
            skin_embed_color="#00ff00",
        ),
    ),
    ("skin_editor_add_field", dict(add_field_name="Campo", add_field_value="Valor")),
    ("skin_editor_edit_field", dict(edit_field_name="Campo 2", edit_field_value=ZWSP)),
    (
        "skin_editor_set_authorfooter",
        dict(
            footer_text="Rodapé",
            footer_icon_url="https://exemplo.invalid/r.png",
            set_author_name="Autor",
            set_author_url="https://exemplo.invalid/a",
            set_author_icon="https://exemplo.invalid/ai.png",
        ),
    ),
    ("skin_editor_setup_queue", dict(queue_format="{track.number}) {track.title}", queue_max_entries="10")),
    ("skin_editor_message_content", dict(message_content=f"Olá {FAMILIA} {{requester.mention}}")),
]
PASSOS_VAZIOS = [
    (
        "skin_editor_add_embed",
        dict(skin_embed_title="", skin_embed_description="", image_url="", thumbnail_url="", skin_embed_color=""),
    ),
    (
        "skin_editor_set_authorfooter",
        dict(footer_text="", footer_icon_url="", set_author_name="", set_author_url="", set_author_icon=""),
    ),
    ("skin_editor_message_content", dict(message_content="")),
]
PASSOS_COM_EDICAO = [
    PASSOS_COMPLETOS[0],
    (
        "skin_editor_edit_embed",
        dict(
            skin_embed_title="Outro",
            skin_embed_description="",
            image_url="",
            thumbnail_url="",
            skin_embed_color="ff0000",
        ),
    ),
]


class TestSkinMontadaPeloEditorPassaNoEsquema:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "passos", [PASSOS_COMPLETOS, PASSOS_VAZIOS, PASSOS_COM_EDICAO], ids=["completa", "tudo-vazio", "edita-e-limpa"]
    )
    async def test_o_que_o_editor_monta_e_valido_e_e_salvo_sem_perder_campo(self, editor_sem_tela, passos):
        menu, bot, _ = editor_sem_tela(dados_globais())
        await menu.new_skin(InteracaoDoEditor())
        for custom_id, textos in passos:
            await passo(menu, custom_id, **textos)
        montada = copy.deepcopy(menu.message_data)
        limpa = valida(montada)  # nenhuma exceção: o editor nunca monta o que o esquema recusa
        for chave, valor in limpa.items():
            assert valor == _sem_o_type(montada)[chave]
        assert set(_sem_o_type(montada)) == set(limpa)
        assert salvo_com_sucesso(await salvar(menu))
        assert bot.banco["custom_skins"]["Minha"] == esperada(montada)


def _sem_o_type(skin: dict) -> dict:
    """A skin sem o ``type: rich`` que ``Embed.to_dict()`` põe (o esquema o descarta)."""
    saida = copy.deepcopy(skin)
    for embed in saida.get("embeds", []):
        embed.pop("type", None)
    return saida

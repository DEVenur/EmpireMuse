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
from types import SimpleNamespace

import pytest

from empiremuse.utils.music.skin_utils import skin_converter
from tests.support.skins import FAMILIA, LIMITES, ZWSP, tipos_do_documento, valida
from tests.persistence.test_formato_skin import (
    BotaoDeModo,
    InteracaoDoEditor,
    Jogador,
    dados_globais,
    skin_realista,
    texto_legado,
)


@pytest.fixture
def editor_sem_tela(request):
    """O editor de ``tests/persistence/test_formato_skin.py`` já aberto em modo ``editor`` (só nele se salva ou importa skin)."""

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
    async def test_o_gravado_e_json_puro(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = skin_realista()
        await salvar(menu)
        assert json.loads(json.dumps(bot.banco)) == bot.banco

    @pytest.mark.asyncio
    async def test_renomear_remove_o_nome_antigo(self, editor_sem_tela):
        dados = dados_globais(normais={"Antiga": skin_realista(), "Outra": skin_realista(content="o")})
        menu, bot, _ = editor_sem_tela(dados)
        menu.message_data, menu.skin_selected = skin_realista(), "> cs: Antiga"
        await salvar(menu, "Nova")
        assert sorted(bot.banco["custom_skins"]) == ["Nova", "Outra"]
        assert bot.banco["custom_skins"]["Outra"] == skin_realista(content="o")

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


class TestSalvarRecusaSkinInvalida:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "importada",
        [
            {"embeds": [{"description": "d"}] * (LIMITES.embeds + 1)},
            {"content": "c" * (LIMITES.content + 1)},
        ],
        ids=["embeds-demais", "content-longo"],
    )
    async def test_json_importado_hostil_e_recusado_ao_salvar(self, editor_sem_tela, importada):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = copy.deepcopy(skin_realista())
        await passo(menu, "skin_editor_import_skin", skin=json.dumps(importada))
        interacao = await salvar(menu)
        assert bot.escritas == [] and mensagens_ao_dono(interacao) and not salvo_com_sucesso(interacao)


# ============================================================================ nome e quantidade


class TestNomeEQuantidade:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "nome",
        ["a" * LIMITES.nome, "  com espaços nas pontas  "],
        ids=["no-limite", "espacos-nas-pontas"],
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
    async def test_sobrescrever_no_modo_cheio_e_permitido(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(self.cheio())
        menu.message_data, menu.skin_selected = skin_realista(content="nova"), "> cs: s0"
        assert salvo_com_sucesso(await salvar(menu, "s0"))
        assert bot.banco["custom_skins"]["s0"]["content"] == "nova"


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

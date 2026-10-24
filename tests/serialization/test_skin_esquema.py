"""F3-6b, etapa 3 (RED) — o esquema da skin: ``empiremuse.serialization.skins.validate_skin``.

Uma skin é o dicionário do editor (``queue_max_entries``, ``queue_format``, ``content``, ``controller_enabled``, ``embeds``).
O validador é a porta de TUDO que vira dicionário no documento: o que o editor salva e o que a migração lê do texto legado.
As decisões (tetos, ``Cf`` liberado nos textos livres, nenhuma chave nova) estão em ``tests/support/skins.py``.

* aceita as skins reais: a padrão do editor, as que o editor monta (campos vazios, ``type: rich`` do ``Embed.to_dict``,
  emojis compostos, campo "em branco") e cada teto no limite exato;
* recusa por campo, com ``path`` e ``code`` precisos e SEM o valor (nem na mensagem, nem na representação, nem no log);
* nunca devolve o objeto da entrada, nunca altera a entrada e nunca acrescenta chave que a entrada não tinha;
* hostil: aninhamento enorme, listas enormes, textos enormes e bytes acima do teto não derrubam nem demoram.
"""

import logging
import time

import pytest

from tests.support.serializacao_nucleo import (
    CONTROL,
    KEY_NOT_TEXT,
    LENGTH,
    LIMITE_DE_TEMPO,
    MISSING,
    PAR_DE_SURROGATES,
    RANGE,
    SEGREDO,
    SURROGATE,
    TOO_BIG,
    TYPE,
    aninhado,
    aninhado_em_dicionarios,
    falha,
    schema,
)
from tests.support.skins import LIMITES, com_campos, com_embed, skin_com_tamanho_minimo, tamanho_em_bytes, valida
from tests.persistence.test_formato_skin import skin_realista

pytestmark = pytest.mark.critical

# ============================================================================ onde cada texto mora na skin

# nome -> (monta a skin com o texto no lugar, caminho do erro)
LOCAIS = {
    "content": (lambda t: {"content": t}, "content"),
    "queue_format": (lambda t: {"queue_format": t}, "queue_format"),
    "title": (lambda t: com_embed(title=t), "embeds[0].title"),
    "description": (lambda t: com_embed(description=t), "embeds[0].description"),
    "field-name": (lambda t: com_embed(fields=[{"name": t, "value": "v"}]), "embeds[0].fields[0].name"),
    "field-value": (lambda t: com_embed(fields=[{"name": "n", "value": t}]), "embeds[0].fields[0].value"),
    "footer-text": (lambda t: com_embed(footer={"text": t}), "embeds[0].footer.text"),
    "author-name": (lambda t: com_embed(author={"name": t}), "embeds[0].author.name"),
    "image-url": (lambda t: com_embed(image={"url": t}), "embeds[0].image.url"),
    "thumbnail-url": (lambda t: com_embed(thumbnail={"url": t}), "embeds[0].thumbnail.url"),
    "footer-icon": (lambda t: com_embed(footer={"text": "t", "icon_url": t}), "embeds[0].footer.icon_url"),
    "author-url": (lambda t: com_embed(author={"name": "a", "url": t}), "embeds[0].author.url"),
    "author-icon": (lambda t: com_embed(author={"name": "a", "icon_url": t}), "embeds[0].author.icon_url"),
    "color": (lambda t: com_embed(color=t), "embeds[0].color"),
}
COM_QUEBRA_DE_LINHA = ["content", "queue_format", "description", "field-value", "footer-text"]


# ============================================================================ o que passa


class TestAceita:
    @pytest.mark.smoke
    def test_devolve_um_objeto_novo_e_independente_da_entrada(self):
        skin = skin_realista()
        limpa = valida(skin)
        assert limpa is not skin and limpa["embeds"] is not skin["embeds"]
        assert limpa["embeds"][2]["fields"] is not skin["embeds"][2]["fields"]
        limpa["embeds"][0]["title"] = "mudou"
        limpa["embeds"][2]["fields"].append({"name": "x", "value": "y"})
        assert skin == skin_realista()

    def test_nao_acrescenta_chave_que_a_entrada_nao_tinha(self):
        """``None`` no lugar de chave ausente mudaria o ``skin_converter`` (``controller_enabled=None`` desliga o controle)."""
        skin = {"embeds": [{"description": "x", "footer": {"text": "t"}, "author": {"name": "a"}}]}
        limpa = valida(skin)
        assert limpa == skin
        assert "controller_enabled" not in limpa and "content" not in limpa and "queue_format" not in limpa
        assert set(limpa["embeds"][0]) == {"description", "footer", "author"}
        assert set(limpa["embeds"][0]["footer"]) == {"text"}

    def test_os_placeholders_passam_sem_mudar(self):
        skin = com_embed(
            description="{queue_format} {track.title} {requester.mention}",
            color="{guild.color}",
            image={"url": "{track.thumb}"},
            footer={"text": "Músicas: {player.queue.size}", "icon_url": "{guild.icon}"},
        )
        assert valida(skin) == skin

    def test_campo_inline_booleano_fica(self):
        skin = com_embed(
            fields=[{"name": "n", "value": "v", "inline": True}, {"name": "m", "value": "w", "inline": False}]
        )
        assert valida(skin) == skin

    @pytest.mark.parametrize(
        "skin",
        [
            {"queue_max_entries": 0},
            com_campos(LIMITES.fields),
        ],
        ids=["fila-0", "campos-no-teto"],
    )
    def test_contagens_no_teto_exato_passam(self, skin):
        assert valida(skin) == skin

    @pytest.mark.parametrize("local", list(COM_QUEBRA_DE_LINHA)[:2])
    def test_quebra_de_linha_e_tabulacao_passam(self, local):
        monta, _ = LOCAIS[local]
        skin = monta("linha 1\nlinha 2\r\n\tlinha 3")
        assert valida(skin) == skin

    def test_skin_ate_o_teto_de_bytes_passa(self):
        skin = skin_com_tamanho_minimo(50 * 1024)
        assert tamanho_em_bytes(skin) < LIMITES.skin_bytes
        assert valida(skin) == skin


# ============================================================================ campos desconhecidos


class TestDescartaOQueNaoConhece:
    def test_o_descarte_nao_vai_ao_log_com_nome_nem_valor(self, caplog):
        skin = {SEGREDO: SEGREDO, "embeds": [{SEGREDO: SEGREDO}]}
        with caplog.at_level(logging.DEBUG):
            assert valida(skin) == {"embeds": [{}]}
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)


# ============================================================================ o que não passa

RECUSAS = [
    ("raiz-lista", [], "", TYPE),
    ("raiz-texto", "x", "", TYPE),
    ("raiz-none", None, "", TYPE),
    ("raiz-numero", 3, "", TYPE),
    ("queue_max_entries-bool", {"queue_max_entries": True}, "queue_max_entries", TYPE),
    ("queue_max_entries-texto", {"queue_max_entries": "7"}, "queue_max_entries", TYPE),
    ("queue_max_entries-float", {"queue_max_entries": 7.0}, "queue_max_entries", TYPE),
    ("queue_max_entries-negativo", {"queue_max_entries": -1}, "queue_max_entries", RANGE),
    ("queue_max_entries-acima", {"queue_max_entries": LIMITES.queue_max_entries + 1}, "queue_max_entries", RANGE),
    ("queue_format-numero", {"queue_format": 3}, "queue_format", TYPE),
    ("content-lista", {"content": ["x"]}, "content", TYPE),
    ("controller_enabled-inteiro", {"controller_enabled": 1}, "controller_enabled", TYPE),
    ("controller_enabled-texto", {"controller_enabled": "true"}, "controller_enabled", TYPE),
    ("embeds-dicionario", {"embeds": {}}, "embeds", TYPE),
    ("embeds-texto", {"embeds": "x"}, "embeds", TYPE),
    ("embeds-demais", {"embeds": [{} for _ in range(LIMITES.embeds + 1)]}, "embeds", LENGTH),
    ("embed-texto", {"embeds": ["x"]}, "embeds[0]", TYPE),
    ("embed-lista", {"embeds": [{}, []]}, "embeds[1]", TYPE),
    ("title-numero", com_embed(title=1), "embeds[0].title", TYPE),
    ("fields-demais", com_campos(LIMITES.fields + 1), "embeds[0].fields", LENGTH),
    ("fields-dicionario", com_embed(fields={}), "embeds[0].fields", TYPE),
    ("field-texto", com_embed(fields=["x"]), "embeds[0].fields[0]", TYPE),
    ("field-sem-name", com_embed(fields=[{"value": "v"}]), "embeds[0].fields[0].name", MISSING),
    ("field-sem-value", com_embed(fields=[{"name": "n"}]), "embeds[0].fields[0].value", MISSING),
    (
        "field-inline-inteiro",
        com_embed(fields=[{"name": "n", "value": "v", "inline": 1}]),
        "embeds[0].fields[0].inline",
        TYPE,
    ),
    ("footer-texto", com_embed(footer="x"), "embeds[0].footer", TYPE),
    ("author-lista", com_embed(author=["a"]), "embeds[0].author", TYPE),
    ("image-texto", com_embed(image="https://exemplo.invalid/a.png"), "embeds[0].image", TYPE),
    ("image-url-numero", com_embed(image={"url": 1}), "embeds[0].image.url", TYPE),
    ("thumbnail-texto", com_embed(thumbnail="x"), "embeds[0].thumbnail", TYPE),
    ("color-booleano", com_embed(color=True), "embeds[0].color", TYPE),
    ("color-lista", com_embed(color=[1]), "embeds[0].color", TYPE),
    ("color-dicionario", com_embed(color={}), "embeds[0].color", TYPE),
    ("color-float", com_embed(color=1.5), "embeds[0].color", TYPE),
    ("color-negativo", com_embed(color=-1), "embeds[0].color", RANGE),
    ("color-acima", com_embed(color=LIMITES.color_numero + 1), "embeds[0].color", RANGE),
    ("chave-nao-texto-na-raiz", {1: "x"}, "", KEY_NOT_TEXT),
    ("chave-nao-texto-no-embed", {"embeds": [{1: "x"}]}, "embeds[0]", KEY_NOT_TEXT),
]


class TestRecusa:
    @pytest.mark.parametrize(
        ("skin", "caminho", "codigo"), list([r[1:] for r in RECUSAS])[:2], ids=[r[0] for r in RECUSAS]
    )
    def test_recusa_no_campo_certo_com_o_codigo_certo(self, skin, caminho, codigo):
        erro = falha(valida, skin)
        assert (erro.path, erro.code) == (caminho, codigo)

    @pytest.mark.parametrize("local", list(sorted(LOCAIS))[:2])
    @pytest.mark.parametrize(
        ("texto", "codigo"),
        [(PAR_DE_SURROGATES, SURROGATE), ("\x7f", CONTROL)],
        ids=["surrogate-solto", "del"],
    )
    def test_surrogate_e_controle_sao_recusados_em_todo_texto(self, local, texto, codigo):
        monta, caminho = LOCAIS[local]
        erro = falha(valida, monta(texto))
        assert (erro.path, erro.code) == (caminho, codigo)

    def test_o_erro_e_do_tipo_do_nucleo_de_serializacao(self):
        assert isinstance(falha(valida, []), schema.SchemaError)


# ============================================================================ tamanho total


class TestTamanhoTotal:
    def test_skin_acima_de_100_kib_e_recusada_mesmo_com_cada_campo_valido(self):
        skin = skin_com_tamanho_minimo(120 * 1024)
        assert tamanho_em_bytes(skin) > LIMITES.skin_bytes
        assert falha(valida, skin).code in {TOO_BIG, LENGTH}


# ============================================================================ hostil


def com_limite_de_tempo(funcao, *args):
    return funcao(*args)


class TestHostil:
    def test_aninhamento_enorme_em_chave_desconhecida_nao_estoura_a_pilha(self):
        skin = {"desconhecida": aninhado(200_000), "embeds": [{"x": aninhado_em_dicionarios(200_000)}]}
        assert com_limite_de_tempo(valida, skin) == {"embeds": [{}]}

    def test_milhoes_de_chaves_desconhecidas_nao_demoram(self):
        skin = {f"k{i}": 0 for i in range(1_000_000)} | {"content": "ok"}
        assert com_limite_de_tempo(valida, skin) == {"content": "ok"}

    def test_lista_gigante_de_campos_e_recusada_antes_de_validar_os_itens(self):
        erro = falha(com_limite_de_tempo, valida, com_embed(fields=[{"name": "n", "value": "v"}] * 5_000_000))
        assert (erro.path, erro.code) == ("embeds[0].fields", LENGTH)

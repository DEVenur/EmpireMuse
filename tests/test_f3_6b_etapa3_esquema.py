"""F3-6b, etapa 3 (RED) — o esquema da skin: ``empiremuse.serialization.skins.validate_skin``.

Uma skin é o dicionário do editor (``queue_max_entries``, ``queue_format``, ``content``, ``controller_enabled``, ``embeds``).
O validador é a porta de TUDO que vira dicionário no documento: o que o editor salva e o que a migração lê do texto legado.
As decisões (tetos, ``Cf`` liberado nos textos livres, nenhuma chave nova) estão em ``tests/helpers_f3_6b_skins.py``.

* aceita as skins reais: a padrão do editor, as que o editor monta (campos vazios, ``type: rich`` do ``Embed.to_dict``,
  emojis compostos, campo "em branco") e cada teto no limite exato;
* recusa por campo, com ``path`` e ``code`` precisos e SEM o valor (nem na mensagem, nem na representação, nem no log);
* nunca devolve o objeto da entrada, nunca altera a entrada e nunca acrescenta chave que a entrada não tinha;
* hostil: aninhamento enorme, listas enormes, textos enormes e bytes acima do teto não derrubam nem demoram.
"""

import copy
import json
import logging
import time

import pytest

from empiremuse.utils.music.interactions import base_skin
from tests.helpers_f3_6b_serializacao import (
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
    vazamentos,
)
from tests.helpers_f3_6b_skins import (
    FAMILIA,
    LIMITES,
    ZWJ,
    ZWSP,
    com_campos,
    com_embed,
    skin_com_tamanho_minimo,
    tamanho_em_bytes,
    valida,
)
from tests.test_f3_6b_formato_skin import skin_realista

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
TEXTOS_HUMANOS = [
    "content",
    "queue_format",
    "title",
    "description",
    "field-name",
    "field-value",
    "footer-text",
    "author-name",
]
COM_QUEBRA_DE_LINHA = ["content", "queue_format", "description", "field-value", "footer-text"]

URLS = {"image-url", "thumbnail-url", "footer-icon", "author-url", "author-icon"}  # a régua de rules/urls.py vale nelas


def texto_no_teto(local: str) -> str:
    """O texto de tamanho exato do teto; nos campos de URL, uma URL válida desse tamanho (a régua da URL vale)."""
    if local in URLS:
        prefixo = "https://exemplo.invalid/"
        return prefixo + "x" * (TETO_DE_TEXTO[local] - len(prefixo))
    return "x" * TETO_DE_TEXTO[local]


TETO_DE_TEXTO = {
    "content": LIMITES.content,
    "queue_format": LIMITES.queue_format,
    "title": LIMITES.title,
    "description": LIMITES.description,
    "field-name": LIMITES.field_name,
    "field-value": LIMITES.field_value,
    "footer-text": LIMITES.footer_text,
    "author-name": LIMITES.author_name,
    "image-url": LIMITES.url,
    "thumbnail-url": LIMITES.url,
    "footer-icon": LIMITES.url,
    "author-url": LIMITES.url,
    "author-icon": LIMITES.url,
    "color": LIMITES.color_texto,
}


# ============================================================================ o que passa


class TestAceita:
    @pytest.mark.parametrize(
        "skin",
        [
            {},
            copy.deepcopy(base_skin),
            skin_realista(),
            {"embeds": []},
            {"content": "só texto", "controller_enabled": True},
            {"queue_format": "{track.number}) {track.title}", "queue_max_entries": 7},
            {"embeds": [{"description": "x"}]},
            {"controller_enabled": False, "embeds": [{"title": "t", "color": "ff0000"}]},
        ],
        ids=[
            "vazia",
            "padrao-do-editor",
            "realista",
            "sem-embeds",
            "so-content",
            "so-fila",
            "so-descricao",
            "sem-fila",
        ],
    )
    def test_skin_valida_volta_igual(self, skin):
        original = copy.deepcopy(skin)
        limpa = valida(skin)
        assert limpa == original and skin == original

    def test_devolve_um_objeto_novo_e_independente_da_entrada(self):
        skin = skin_realista()
        limpa = valida(skin)
        assert limpa is not skin and limpa["embeds"] is not skin["embeds"]
        assert limpa["embeds"][2]["fields"] is not skin["embeds"][2]["fields"]
        limpa["embeds"][0]["title"] = "mudou"
        limpa["embeds"][2]["fields"].append({"name": "x", "value": "y"})
        assert skin == skin_realista()

    def test_so_tipos_simples_do_json(self):
        limpa = valida(skin_realista())
        assert type(limpa) is dict and type(limpa["embeds"]) is list and type(limpa["embeds"][0]) is dict
        assert json.loads(json.dumps(limpa)) == limpa

    def test_nao_acrescenta_chave_que_a_entrada_nao_tinha(self):
        """``None`` no lugar de chave ausente mudaria o ``skin_converter`` (``controller_enabled=None`` desliga o controle)."""
        skin = {"embeds": [{"description": "x", "footer": {"text": "t"}, "author": {"name": "a"}}]}
        limpa = valida(skin)
        assert limpa == skin
        assert "controller_enabled" not in limpa and "content" not in limpa and "queue_format" not in limpa
        assert set(limpa["embeds"][0]) == {"description", "footer", "author"}
        assert set(limpa["embeds"][0]["footer"]) == {"text"}

    def test_valida_duas_vezes_da_o_mesmo(self):
        uma = valida(skin_realista())
        assert valida(uma) == uma

    def test_os_placeholders_passam_sem_mudar(self):
        skin = com_embed(
            description="{queue_format} {track.title} {requester.mention}",
            color="{guild.color}",
            image={"url": "{track.thumb}"},
            footer={"text": "Músicas: {player.queue.size}", "icon_url": "{guild.icon}"},
        )
        assert valida(skin) == skin

    @pytest.mark.parametrize(
        "cor", ["", "ff0000", "#ff0000", "{guild.color}", 0, 255, 0xFFFFFF, "f" * LIMITES.color_texto]
    )
    def test_cores_aceitas(self, cor):
        assert valida(com_embed(color=cor)) == com_embed(color=cor)

    def test_campo_inline_booleano_fica(self):
        skin = com_embed(
            fields=[{"name": "n", "value": "v", "inline": True}, {"name": "m", "value": "w", "inline": False}]
        )
        assert valida(skin) == skin

    @pytest.mark.parametrize("local", sorted(LOCAIS))
    def test_cada_texto_no_teto_exato_passa(self, local):
        monta, _ = LOCAIS[local]
        skin = monta(texto_no_teto(local))
        assert valida(skin) == skin

    @pytest.mark.parametrize(
        "skin",
        [
            {"queue_max_entries": 0},
            {"queue_max_entries": LIMITES.queue_max_entries},
            {"embeds": [{} for _ in range(LIMITES.embeds)]},
            com_campos(LIMITES.fields),
        ],
        ids=["fila-0", "fila-no-teto", "embeds-no-teto", "campos-no-teto"],
    )
    def test_contagens_no_teto_exato_passam(self, skin):
        assert valida(skin) == skin

    @pytest.mark.parametrize("local", TEXTOS_HUMANOS)
    @pytest.mark.parametrize(
        "texto",
        [FAMILIA, ZWSP, "a" + ZWJ + "b", "ação ü ñ 日本語 😀", "️"],
        ids=["emoji-composto", "campo-em-branco", "zwj", "acentos-cjk-emoji", "seletor-de-variacao"],
    )
    def test_texto_humano_com_emoji_composto_e_invisiveis_passa(self, local, texto):
        monta, _ = LOCAIS[local]
        skin = monta(texto)
        assert valida(skin) == skin

    @pytest.mark.parametrize("local", COM_QUEBRA_DE_LINHA)
    def test_quebra_de_linha_e_tabulacao_passam(self, local):
        monta, _ = LOCAIS[local]
        skin = monta("linha 1\nlinha 2\r\n\tlinha 3")
        assert valida(skin) == skin

    def test_embed_so_com_o_type_do_editor_vira_embed_vazio(self):
        """``Embed.to_dict()`` de um embed sem nada devolve só ``{"type": "rich"}``: o editor consegue gravar isso."""
        assert valida({"embeds": [{"type": "rich"}]}) == {"embeds": [{}]}

    def test_skin_ate_o_teto_de_bytes_passa(self):
        skin = skin_com_tamanho_minimo(50 * 1024)
        assert tamanho_em_bytes(skin) < LIMITES.skin_bytes
        assert valida(skin) == skin


# ============================================================================ campos desconhecidos


class TestDescartaOQueNaoConhece:
    def test_chaves_desconhecidas_da_raiz_e_do_embed_saem_e_o_v_nunca_entra(self):
        skin = {
            "v": 1,
            "foo": {"x": 1},
            "queue_max_entries": 7,
            "embeds": [
                {
                    "type": "rich",
                    "video": {"url": "u"},
                    "provider": {"name": "p"},
                    "description": "d",
                    "footer": {"text": "t", "proxy_icon_url": "u"},
                    "image": {"url": "u", "width": 1, "height": 2},
                    "fields": [{"name": "n", "value": "v", "extra": 1}],
                }
            ],
        }
        assert valida(skin) == {
            "queue_max_entries": 7,
            "embeds": [
                {
                    "description": "d",
                    "footer": {"text": "t"},
                    "image": {"url": "u"},
                    "fields": [{"name": "n", "value": "v"}],
                }
            ],
        }

    def test_o_descarte_nao_vai_ao_log_com_nome_nem_valor(self, caplog):
        skin = {SEGREDO: SEGREDO, "embeds": [{SEGREDO: SEGREDO}]}
        with caplog.at_level(logging.DEBUG):
            assert valida(skin) == {"embeds": [{}]}
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)

    def test_url_e_timestamp_do_embed_do_discord_nao_derrubam(self):
        skin = com_embed(url="https://exemplo.invalid/a", timestamp="2026-10-19T12:00:00+00:00", description="d")
        limpa = valida(skin)
        assert limpa["embeds"][0]["description"] == "d"
        assert set(limpa["embeds"][0]) <= {"url", "timestamp", "description"}


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
    @pytest.mark.parametrize(("skin", "caminho", "codigo"), [r[1:] for r in RECUSAS], ids=[r[0] for r in RECUSAS])
    def test_recusa_no_campo_certo_com_o_codigo_certo(self, skin, caminho, codigo):
        erro = falha(valida, skin)
        assert (erro.path, erro.code) == (caminho, codigo)

    @pytest.mark.parametrize("local", sorted(LOCAIS))
    def test_um_caractere_acima_do_teto_de_cada_texto(self, local):
        monta, caminho = LOCAIS[local]
        erro = falha(valida, monta("x" * (TETO_DE_TEXTO[local] + 1)))
        assert (erro.path, erro.code) == (caminho, LENGTH)

    @pytest.mark.parametrize("local", sorted(LOCAIS))
    @pytest.mark.parametrize(
        ("texto", "codigo"),
        [(PAR_DE_SURROGATES, SURROGATE), ("\x00", CONTROL), ("a\x1b[31mb", CONTROL), ("\x7f", CONTROL)],
        ids=["surrogate-solto", "nul", "escape-ansi", "del"],
    )
    def test_surrogate_e_controle_sao_recusados_em_todo_texto(self, local, texto, codigo):
        monta, caminho = LOCAIS[local]
        erro = falha(valida, monta(texto))
        assert (erro.path, erro.code) == (caminho, codigo)

    @pytest.mark.parametrize("local", sorted(LOCAIS))
    @pytest.mark.parametrize(
        "ruim",
        [("longo", "x" * 10_000), ("surrogate", PAR_DE_SURROGATES), ("controle", "\x00")],
        ids=lambda v: v[0] if isinstance(v, tuple) else str(v),
    )
    def test_o_erro_nunca_leva_o_valor(self, local, ruim):
        monta, _ = LOCAIS[local]
        erro = falha(valida, monta(SEGREDO + ruim[1]))
        assert vazamentos(erro) == []

    def test_o_erro_e_do_tipo_do_nucleo_de_serializacao(self):
        assert isinstance(falha(valida, []), schema.SchemaError)

    def test_a_entrada_recusada_nao_e_alterada(self):
        skin = skin_realista()
        skin["embeds"][1]["title"] = "t" * (LIMITES.title + 1)
        original = copy.deepcopy(skin)
        falha(valida, skin)
        assert skin == original


# ============================================================================ tamanho total


class TestTamanhoTotal:
    def test_skin_acima_de_100_kib_e_recusada_mesmo_com_cada_campo_valido(self):
        skin = skin_com_tamanho_minimo(120 * 1024)
        assert tamanho_em_bytes(skin) > LIMITES.skin_bytes
        assert falha(valida, skin).code in {TOO_BIG, LENGTH}

    def test_o_teto_conta_bytes_e_nao_caracteres(self):
        """10 descrições de 4096 emojis: 40 960 caracteres, mas 163 840 bytes em UTF-8."""
        skin = {"embeds": [{"description": "😀" * LIMITES.description} for _ in range(LIMITES.embeds)]}
        assert len(json.dumps(skin, ensure_ascii=False)) < LIMITES.skin_bytes < tamanho_em_bytes(skin)
        assert falha(valida, skin).code in {TOO_BIG, LENGTH}


# ============================================================================ hostil


def com_limite_de_tempo(funcao, *args):
    inicio = time.perf_counter()
    try:
        return funcao(*args)
    finally:
        assert time.perf_counter() - inicio < LIMITE_DE_TEMPO


class TestHostil:
    def test_aninhamento_enorme_em_chave_desconhecida_nao_estoura_a_pilha(self):
        skin = {"desconhecida": aninhado(200_000), "embeds": [{"x": aninhado_em_dicionarios(200_000)}]}
        assert com_limite_de_tempo(valida, skin) == {"embeds": [{}]}

    @pytest.mark.parametrize(
        ("skin", "caminho"),
        [
            ({"embeds": [aninhado(200_000)]}, "embeds[0]"),
            ({"embeds": aninhado(200_000)}, "embeds[0]"),
            (com_embed(image=aninhado(200_000)), "embeds[0].image"),
            (com_embed(image={"url": aninhado(200_000)}), "embeds[0].image.url"),
            (com_embed(fields=aninhado(200_000)), "embeds[0].fields[0]"),
            ({"content": aninhado(200_000)}, "content"),
        ],
        ids=["embed-lista", "embeds-lista", "image-lista", "image-url-lista", "fields-lista", "content-lista"],
    )
    def test_aninhamento_enorme_em_campo_conhecido_e_recusado_sem_recursao(self, skin, caminho):
        erro = falha(com_limite_de_tempo, valida, skin)
        assert (erro.path, erro.code) == (caminho, TYPE)

    def test_milhoes_de_chaves_desconhecidas_nao_demoram(self):
        skin = {f"k{i}": 0 for i in range(1_000_000)} | {"content": "ok"}
        assert com_limite_de_tempo(valida, skin) == {"content": "ok"}

    def test_lista_gigante_de_embeds_e_recusada_antes_de_validar_os_itens(self):
        erro = falha(com_limite_de_tempo, valida, {"embeds": [{}] * 5_000_000})
        assert (erro.path, erro.code) == ("embeds", LENGTH)

    def test_lista_gigante_de_campos_e_recusada_antes_de_validar_os_itens(self):
        erro = falha(com_limite_de_tempo, valida, com_embed(fields=[{"name": "n", "value": "v"}] * 5_000_000))
        assert (erro.path, erro.code) == ("embeds[0].fields", LENGTH)

    def test_texto_de_50_mib_e_recusado_pelo_tamanho(self):
        erro = falha(com_limite_de_tempo, valida, {"content": "a" * (50 * 1024 * 1024)})
        assert (erro.path, erro.code) == ("content", LENGTH)

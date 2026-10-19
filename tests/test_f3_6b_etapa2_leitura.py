"""F3-6b, etapa 2 (RED) — ``legacy_pickle.load_legacy``: o que o gravador real gera é lido; e só o ``Unpickler`` restrito lê.

* o que os gravadores REAIS (``save_info`` no disco e no Mongo, ``save_queue``, o editor de skin) deixam é lido IGUAL ao que
  ``pickle.loads`` devolve hoje (mesmos tipos: ``datetime`` UTC, ``set``, ``deque(maxlen=10)``, tupla), nos protocolos 4 e 5;
* o que ``load_legacy`` aceita como ``raw`` em cada ``kind``;
* ``check_structure`` (teto 12 da raiz, tipos, chaves, ``NaN``, surrogate) é aplicado ao resultado;
* NENHUM ``pickle.load``/``loads`` (nem ``marshal``) é chamado: espião com zero chamadas;
* o código-fonte de ``legacy_pickle.py`` (por ``ast``): ``fix_imports=False``, ``persistent_load`` que levanta, ``find_class`` por
  comparação exata (sem ``split``/``startswith``), nada de ``eval``/``exec``/``__import__``;
* nenhuma mensagem, caminho, exceção encadeada, log ou ``print`` leva o conteúdo do dado.
"""

import ast
import base64
import importlib.util
import logging
import pickle
import zlib
from collections import deque
from datetime import datetime, timedelta, timezone

import _pickle
import pytest
import pytest_asyncio

from empiremuse.utils.music.interactions import base_skin
from tests.helpers_f3_6b import BOT_ID, SERVIDOR, MongoEmMemoria, cog_de_sessoes
from tests.helpers_f3_6b_serializacao import schema
from tests.helpers_f3_6b_legado import (
    CORRUPT,
    DEPTH,
    ENVELOPE,
    GLOBAL,
    KEY_NOT_TEXT,
    KINDS,
    NOT_FINITE,
    OPCODE,
    PROTOCOL,
    SEGREDO,
    SURROGATE,
    TYPE,
    bruto,
    chamada,
    comprimido,
    dicionario,
    em_base64,
    envelope,
    global_,
    inteiro,
    legacy_pickle,
    medir,
    pickle_de,
    recusado,
    texto,
    vazamentos,
)
from tests.test_f3_6b_formato_fila_salva import caminho_da_fila, salvar, tres_faixas
from tests.test_f3_6b_formato_sessao import gravar, jogador_completo, pasta_das_sessoes
from tests.test_f3_6b_formato_skin import BotaoDeModo, InteracaoDoEditor, dados_globais, skin_realista, texto_legado
from tests.test_f3_6b_formato_skin import editor_sem_tela as _editor_sem_tela
from tests.test_f3_6b_profundidade_de4 import letras_palavra_a_palavra

editor_sem_tela = _editor_sem_tela  # a fixture do editor de skin, reaproveitada de tests/test_f3_6b_formato_skin.py
UTC = timezone.utc


def carregar(raw, kind="session"):
    return legacy_pickle.load_legacy(raw, kind)


def igual_ao_pickle_de_hoje(raw_comprimido: bytes, kind: str):
    """``load_legacy`` e ``pickle.loads`` (que o produto usa hoje) devolvem o mesmo dado, com os mesmos tipos."""
    esperado = pickle.loads(zlib.decompress(raw_comprimido))  # a fixture é do próprio teste
    lido = carregar(raw_comprimido, kind)
    assert lido == esperado
    return lido, esperado


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


# ============================================================================ o erro


class TestLegacyFormatError:
    def test_e_um_schema_error_e_um_value_error(self):
        assert issubclass(legacy_pickle.LegacyFormatError, ValueError)
        assert issubclass(legacy_pickle.LegacyFormatError, schema.SchemaError)

    def test_tem_a_mesma_assinatura_do_schema_error(self):
        erro = legacy_pickle.LegacyFormatError("", CORRUPT)
        assert erro.path == "" and erro.code == CORRUPT

    def test_o_erro_levantado_e_capturavel_como_schema_error(self):
        with pytest.raises(schema.SchemaError):
            carregar(b"", "session")


# ============================================================================ o que os gravadores reais geram


class TestSessaoReal:
    @pytest_asyncio.fixture
    async def sessao(self):
        return await gravar(cog_de_sessoes(), jogador_completo())

    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [4, 5])
    async def test_sessao_do_save_info_e_lida_igual_ao_pickle_loads(self, sessao, protocolo):
        raw = comprimido(pickle.dumps(sessao, protocol=protocolo))
        lido, _ = igual_ao_pickle_de_hoje(raw, "session")
        assert type(lido["dj"]) is set and lido["time"] == sessao["time"] and lido["time"].utcoffset() == timedelta(0)
        assert isinstance(lido["command_log_list"], deque) and lido["command_log_list"].maxlen == 10
        assert type(lido["extra_info"]) is dict and lido["queue"] == sessao["queue"]

    @pytest.mark.asyncio
    async def test_extra_info_com_tupla_passa(self):
        sessao = await gravar(cog_de_sessoes(), jogador_completo(extra_info={"guild-yt-oauth": ("token-de-teste", 1)}))
        lido, _ = igual_ao_pickle_de_hoje(comprimido(pickle.dumps(sessao, protocol=4)), "session")
        assert lido["extra_info"]["guild-yt-oauth"] == ("token-de-teste", 1)

    @pytest.mark.asyncio
    async def test_sessao_com_skin_personalizada_passa(self):
        skin = skin_realista()
        sessao = await gravar(
            cog_de_sessoes(), jogador_completo(skin="> custom_skin: Minha", custom_skin_data={"Minha": skin})
        )
        lido, _ = igual_ao_pickle_de_hoje(comprimido(pickle.dumps(sessao, protocol=5)), "session")
        assert lido["custom_skin_data"] == {"Minha": skin}

    @pytest.mark.asyncio
    async def test_o_pior_caso_plausivel_de_letras_chega_a_10_niveis_e_passa(self, sessao):
        pior = dict(sessao, queue=[{"extra": {"lyrics": letras_palavra_a_palavra()}}])
        lido, _ = igual_ao_pickle_de_hoje(comprimido(pickle.dumps(pior, protocol=4)), "session")
        assert lido["queue"][0]["extra"]["lyrics"]["lines"][0]["plugin"]["words"]

    @pytest.mark.asyncio
    async def test_o_arquivo_gravado_pelo_save_info_no_disco_e_lido(self, tmp_path):
        cog = cog_de_sessoes()
        await cog.save_info(jogador_completo())
        raw = (pasta_das_sessoes(tmp_path) / f"{SERVIDOR}.pkl").read_bytes()
        lido, esperado = igual_ao_pickle_de_hoje(raw, "session")
        assert lido["_id"] == SERVIDOR and type(lido["dj"]) is set
        assert (pasta_das_sessoes(tmp_path) / f"{SERVIDOR}.bak").read_bytes() == raw

    @pytest.mark.asyncio
    async def test_o_documento_gravado_no_mongo_e_lido_como_texto(self):
        mongo = MongoEmMemoria()
        await cog_de_sessoes(mongo=mongo).save_info(jogador_completo())
        documento = mongo.colecao(BOT_ID, "player_sessions")[str(SERVIDOR)]
        lido = carregar(documento["data"], "session")
        esperado = pickle.loads(zlib.decompress(base64.b64decode(documento["data"])))
        assert lido == esperado and type(lido["dj"]) is set

    @pytest.mark.asyncio
    async def test_bytes_e_texto_da_mesma_sessao_dao_o_mesmo_resultado(self, sessao):
        raw = comprimido(pickle.dumps(sessao, protocol=4))
        assert carregar(raw, "session") == carregar(em_base64(raw), "session")

    @pytest.mark.asyncio
    async def test_cada_chamada_devolve_objetos_novos(self, sessao):
        raw = comprimido(pickle.dumps(sessao, protocol=4))
        primeiro, segundo = carregar(raw), carregar(raw)
        assert primeiro == segundo and primeiro is not segundo and primeiro["queue"] is not segundo["queue"]
        primeiro["queue"].clear()
        assert len(carregar(raw)["queue"]) == len(sessao["queue"])


class TestFilaReal:
    @pytest.mark.asyncio
    async def test_a_fila_no_formato_que_o_save_queue_gravava_e_lida_igual_ao_pickle_loads(self, tmp_path):
        """Desde a etapa 4 o ``save_queue`` grava JSON; o ``.pkl`` que ele gravava antes é montado aqui com o mesmo conteúdo."""
        from tests.helpers_f3_6b import INSTANTE, SERVIDOR
        from tests.test_f3_6b_formato_fila_salva import infos

        faixas = tres_faixas()
        conteudo = {"tracks": infos(faixas), "created_at": INSTANTE, "guild_id": SERVIDOR}
        raw = comprimido(pickle.dumps(conteudo))
        lido, _ = igual_ao_pickle_de_hoje(raw, "queue")
        assert set(lido) == {"tracks", "created_at", "guild_id"} and len(lido["tracks"]) == 3
        assert isinstance(lido["created_at"], datetime) and lido["created_at"].utcoffset() == timedelta(0)

    @pytest.mark.parametrize("protocolo", [4, 5])
    def test_fila_nos_dois_protocolos(self, protocolo):
        conteudo = {
            "tracks": [{"title": "x", "extra": {"requester": 1}}] * 3,
            "created_at": datetime.now(UTC),
            "guild_id": 7,
        }
        igual_ao_pickle_de_hoje(comprimido(pickle.dumps(conteudo, protocol=protocolo)), "queue")

    def test_a_fila_e_so_bytes(self):
        raw = comprimido(pickle.dumps({"tracks": []}, protocol=4))
        assert carregar(raw, "queue") == {"tracks": []}
        recusado(medir(carregar, em_base64(raw), "queue"), TYPE)


class TestSkinReal:
    @pytest.mark.asyncio
    async def test_a_skin_gravada_pelo_editor_e_lida_igual(self, editor_sem_tela):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = skin_realista()
        BotaoDeModo.modo = "custom_skins"
        await menu.modal_handler(InteracaoDoEditor(skin_name="Minha"))
        gravada = bot.salvos[0]["custom_skins"]["Minha"]
        assert isinstance(gravada, str)
        assert carregar(gravada, "skin") == skin_realista()

    @pytest.mark.parametrize("protocolo", [4, 5])
    def test_skin_nos_dois_protocolos(self, protocolo):
        assert carregar(texto_legado(skin_realista(), protocolo), "skin") == skin_realista()

    def test_skin_padrao_do_editor(self):
        assert carregar(texto_legado(base_skin), "skin") == base_skin

    @pytest.mark.parametrize("protocolo", [0, 1, 2, 3])
    def test_skin_em_protocolo_antigo_e_recusada(self, protocolo):
        recusado(medir(carregar, texto_legado(skin_realista(), protocolo), "skin"), PROTOCOL)

    def test_skin_com_zlib_no_meio_nao_e_o_formato_do_editor(self):
        recusado(
            medir(carregar, em_base64(comprimido(pickle.dumps(skin_realista(), protocol=4))), "skin"),
            {PROTOCOL, CORRUPT},
        )


# ============================================================================ o que vale como raw


class TestTipoDoRaw:
    def valido(self):
        return pickle_de(dicionario((texto("a"), inteiro(1))))

    def test_sessao_aceita_bytes_e_texto(self):
        assert carregar(envelope(self.valido()), "session") == {"a": 1}
        assert carregar(envelope(self.valido(), como_texto=True), "session") == {"a": 1}

    def test_fila_so_aceita_bytes(self):
        assert carregar(envelope(self.valido()), "queue") == {"a": 1}
        recusado(medir(carregar, envelope(self.valido(), como_texto=True), "queue"), TYPE)

    def test_skin_so_aceita_texto(self):
        assert carregar(envelope(self.valido(), "skin"), "skin") == {"a": 1}
        recusado(medir(carregar, self.valido(), "skin"), TYPE)
        recusado(medir(carregar, comprimido(self.valido()), "skin"), TYPE)

    @pytest.mark.parametrize(
        "raw",
        [None, 1, 1.5, ["a"], {"a": 1}, bytearray(b"x"), memoryview(b"x"), object(), True],
        ids=lambda v: type(v).__name__,
    )
    @pytest.mark.parametrize("kind", KINDS)
    def test_qualquer_outro_tipo_e_recusado(self, raw, kind):
        recusado(medir(carregar, raw, kind), TYPE)

    def test_subclasse_de_bytes_e_de_str_e_recusada(self):
        class Dados(bytes):
            pass

        class Texto(str):
            pass

        recusado(medir(carregar, Dados(envelope(self.valido())), "session"), TYPE)
        recusado(medir(carregar, Texto(em_base64(self.valido())), "skin"), TYPE)


class TestBase64Estrito:
    """O texto do Mongo (sessão) e da skin é ``base64`` PADRÃO e estrito: nada de espaço, quebra de linha ou lixo."""

    def textos_validos(self):
        dados = pickle_de(dicionario((texto("a"), inteiro(1))))
        return {"skin": em_base64(dados), "session": em_base64(comprimido(dados))}

    @pytest.mark.parametrize("kind", ["skin", "session"])
    def test_o_texto_exato_passa(self, kind):
        assert carregar(self.textos_validos()[kind], kind) == {"a": 1}

    @pytest.mark.parametrize(
        "adulterar",
        [
            lambda t: t[:8] + "\n" + t[8:],
            lambda t: t + "\n",
            lambda t: " " + t,
            lambda t: t[:8] + " " + t[8:],
            lambda t: t + "!!!",
            lambda t: t[:-1],
            lambda t: t + "=",
            lambda t: t + "é",
            lambda t: t.replace("A", "-", 1) if "A" in t else t + "-",
            lambda t: t.replace("A", "_", 1) if "A" in t else t + "_",
            lambda t: t[:4] + "\x00" + t[4:],
        ],
        ids=range(11),
    )
    @pytest.mark.parametrize("kind", ["skin", "session"])
    def test_texto_fora_do_base64_padrao_e_envelope(self, kind, adulterar):
        recusado(medir(carregar, adulterar(self.textos_validos()[kind]), kind), ENVELOPE)


# ============================================================================ check_structure aplicado ao resultado


class TestValidacaoEstrutural:
    def lido(self, objeto, kind="session"):
        return carregar(envelope(pickle.dumps(objeto, protocol=4), kind), kind)

    def recusa(self, objeto, codigo, kind="session"):
        recusado(medir(carregar, envelope(pickle.dumps(objeto, protocol=4), kind), kind), codigo)

    def test_12_niveis_da_raiz_passam_e_13_nao(self):
        def encaixar(niveis):
            valor = 0
            for _ in range(niveis):
                valor = [valor]
            return valor

        assert self.lido({"a": encaixar(11)}) == {"a": encaixar(11)}
        self.recusa({"a": encaixar(12)}, DEPTH)

    def test_o_mesmo_teto_vale_para_os_tres_kinds(self):
        profundo = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": {"k": {"l": {}}}}}}}}}}}}}
        for kind in KINDS:
            self.recusa(profundo, DEPTH, kind)

    @pytest.mark.parametrize(
        ("valor", "codigo"),
        [
            (b"bytes", TYPE),
            (float("nan"), NOT_FINITE),
            (float("inf"), NOT_FINITE),
            (float("-inf"), NOT_FINITE),
            ("a\ud800b", SURROGATE),
        ],
        ids=["bytes", "nan", "inf", "-inf", "surrogate"],
    )
    def test_tipo_ou_valor_recusado_pelo_validador(self, valor, codigo):
        for embrulho in (lambda v: {"a": v}, lambda v: {"a": [v]}, lambda v: {"a": {"b": (v,)}}):
            self.recusa(embrulho(valor), codigo)

    def test_surrogate_na_chave_e_recusado(self):
        self.recusa({"a\udfff": 1}, SURROGATE)

    @pytest.mark.parametrize("chave", [1, b"k", None, (1, 2), 1.5, True], ids=lambda v: type(v).__name__)
    def test_chave_que_nao_e_texto_e_recusada(self, chave):
        self.recusa({chave: 1}, KEY_NOT_TEXT)
        self.recusa({"a": {chave: 1}}, KEY_NOT_TEXT)

    def test_bytearray_pelo_reduce_cai_na_allowlist(self):
        recusado(medir(carregar, comprimido(pickle.dumps({"a": bytearray(b"x")}, protocol=4))), GLOBAL)

    def test_datetime_ingenuo_e_com_fuso_passam_na_validacao(self):
        assert self.lido({"a": datetime(2026, 1, 1), "b": datetime(2026, 1, 1, tzinfo=UTC)})["a"].tzinfo is None

    def test_estrutura_vazia_e_dicionario_vazio_passam(self):
        assert self.lido({}) == {}
        assert self.lido({"a": [], "b": {}, "c": (), "d": set()}) == {"a": [], "b": {}, "c": (), "d": set()}

    def test_a_validacao_roda_depois_do_unpickler_e_nao_deixa_passar_dado_parcial(self):
        """Dado com a raiz boa e uma folha ruim é recusado inteiro: nada de devolver só a parte válida."""
        self.recusa({"ok": [1, 2, 3], "ruim": {"x": float("nan")}}, NOT_FINITE)


# ============================================================================ nenhum pickle.load(s) fora do Unpickler restrito


class TestZeroPickleLoads:
    CHAMADOS = [
        (pickle, "load"),
        (pickle, "loads"),
        (pickle, "_load"),
        (pickle, "_loads"),
        (_pickle, "load"),
        (_pickle, "loads"),
    ]

    @pytest.mark.asyncio
    async def test_leitura_valida_e_recusas_nao_chamam_pickle_load_nem_loads(self, monkeypatch):
        sessao = await gravar(cog_de_sessoes(), jogador_completo())
        validos = [
            (comprimido(pickle.dumps(sessao, protocol=4)), "session"),
            (em_base64(comprimido(pickle.dumps(sessao, protocol=5))), "session"),
            (comprimido(pickle.dumps({"tracks": [], "created_at": datetime.now(UTC)}, protocol=4)), "queue"),
            (texto_legado(skin_realista()), "skin"),
        ]
        hostis = [
            (envelope(pickle_de(chamada("pickle", "loads", bruto(pickle_de(pickle.NONE)))), "session"), "session"),
            (envelope(pickle_de(chamada("_pickle", "loads", bruto(pickle_de(pickle.NONE)))), "queue"), "queue"),
            (envelope(pickle_de(chamada("marshal", "loads", bruto(b"x"))), "skin"), "skin"),
            (comprimido(pickle.dumps({"a": 1}, protocol=3)), "session"),
            (b"", "session"),
            (comprimido(b"\x80\x04N"), "queue"),
        ]
        chamadas = []

        def espiao(modulo, nome):
            def registrar(*args, **kwargs):
                chamadas.append(f"{modulo.__name__}.{nome}")
                raise AssertionError(f"{modulo.__name__}.{nome} foi chamado")

            return registrar

        for modulo, nome in self.CHAMADOS:
            monkeypatch.setattr(modulo, nome, espiao(modulo, nome))
        for raw, kind in validos:
            carregar(raw, kind)
        for raw, kind in hostis:
            assert medir(carregar, raw, kind).erro is not None
        assert chamadas == []


# ============================================================================ o código-fonte (ast)


def arvore_do_leitor() -> ast.Module:
    spec = importlib.util.find_spec("empiremuse.serialization.legacy_pickle")
    assert spec is not None and spec.origin, "falta empiremuse/serialization/legacy_pickle.py"
    with open(spec.origin, encoding="utf-8") as arquivo:
        return ast.parse(arquivo.read())


def classes_que_herdam_do_unpickler(arvore):
    achadas = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.ClassDef):
            for base in no.bases:
                nome = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                if nome == "Unpickler":
                    achadas.append(no)
    return achadas


def metodo(classe: ast.ClassDef, nome: str):
    return next((no for no in classe.body if isinstance(no, ast.FunctionDef) and no.name == nome), None)


METODOS_DE_TEXTO = {
    "split",
    "rsplit",
    "partition",
    "rpartition",
    "startswith",
    "endswith",
    "removeprefix",
    "removesuffix",
    "lower",
    "upper",
    "casefold",
    "strip",
    "lstrip",
    "rstrip",
    "find",
    "index",
    "count",
    "replace",
    "encode",
    "decode",
}


class TestCodigoFonte:
    def test_o_unpickler_restrito_existe_e_e_um_so(self):
        assert len(classes_que_herdam_do_unpickler(arvore_do_leitor())) == 1

    def test_fix_imports_e_sempre_false(self):
        valores = [
            no.value.value
            for no in ast.walk(arvore_do_leitor())
            if isinstance(no, ast.keyword) and no.arg == "fix_imports" and isinstance(no.value, ast.Constant)
        ]
        assert valores and all(valor is False for valor in valores)

    def test_codificacao_ascii_e_estrita(self):
        pares = {
            no.arg: no.value.value
            for no in ast.walk(arvore_do_leitor())
            if isinstance(no, ast.keyword) and no.arg in {"encoding", "errors"} and isinstance(no.value, ast.Constant)
        }
        assert pares.get("encoding") == "ascii" and pares.get("errors") == "strict"

    def test_persistent_load_levanta(self):
        (classe,) = classes_que_herdam_do_unpickler(arvore_do_leitor())
        alvo = metodo(classe, "persistent_load")
        assert alvo is not None, "o Unpickler restrito precisa definir persistent_load"
        assert any(isinstance(no, ast.Raise) for no in ast.walk(alvo))
        assert not any(isinstance(no, ast.Return) and no.value is not None for no in ast.walk(alvo))

    def test_find_class_compara_o_par_exato_sem_metodos_de_texto(self):
        (classe,) = classes_que_herdam_do_unpickler(arvore_do_leitor())
        alvo = metodo(classe, "find_class")
        assert alvo is not None, "o Unpickler restrito precisa definir find_class"
        usados = {
            no.func.attr for no in ast.walk(alvo) if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
        }
        assert not usados & METODOS_DE_TEXTO, sorted(usados & METODOS_DE_TEXTO)
        assert any(isinstance(no, ast.Raise) for no in ast.walk(alvo))

    def test_find_class_nao_importa_nem_chama_o_find_class_do_pai_antes_de_recusar(self):
        (classe,) = classes_que_herdam_do_unpickler(arvore_do_leitor())
        alvo = metodo(classe, "find_class")
        nomes = {no.id for no in ast.walk(alvo) if isinstance(no, ast.Name)} | {
            no.attr for no in ast.walk(alvo) if isinstance(no, ast.Attribute)
        }
        assert not nomes & {"import_module", "__import__", "importlib", "getattr", "eval", "exec"}

    def test_nenhum_pickle_load_ou_loads_no_modulo(self):
        usados = {
            no.attr
            for no in ast.walk(arvore_do_leitor())
            if isinstance(no, ast.Attribute) and isinstance(no.value, ast.Name) and no.value.id in {"pickle", "_pickle"}
        }
        assert not usados & {"load", "loads", "_load", "_loads"}

    def test_nada_de_eval_exec_compile_import_dinamico_nem_outros_formatos(self):
        arvore = arvore_do_leitor()
        proibidos = {"eval", "exec", "compile", "__import__", "globals", "locals"}
        chamados = {no.func.id for no in ast.walk(arvore) if isinstance(no, ast.Call) and isinstance(no.func, ast.Name)}
        assert not chamados & proibidos
        importados = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                importados.update(alias.name.split(".")[0] for alias in no.names)
            elif isinstance(no, ast.ImportFrom):
                importados.add((no.module or "").split(".")[0])
        assert not importados & {"marshal", "shelve", "dill", "jsonpickle", "importlib", "subprocess"}


# ============================================================================ nada do conteúdo vaza (mensagem, caminho, contexto, log, saída)


def cenarios_de_vazamento():
    """``(descrição, raw, kind)``: cada um tem o SEGREDO em algum ponto do pickle e tem de ser recusado."""
    segredo_em_dicionario = dicionario((texto(SEGREDO), texto(SEGREDO)))
    return {
        "global-modulo-e-nome": (envelope(pickle_de(global_(SEGREDO, SEGREDO))), "session"),
        "global-so-no-nome": (envelope(pickle_de(chamada("os", SEGREDO))), "session"),
        "global-so-no-modulo": (envelope(pickle_de(chamada(SEGREDO, "system"))), "queue"),
        "global-na-skin": (envelope(pickle_de(global_(SEGREDO, SEGREDO)), "skin"), "skin"),
        "bytes-no-valor": (envelope(pickle_de(dicionario((texto("a"), bruto(SEGREDO.encode()))))), "session"),
        "chave-nao-texto": (envelope(pickle.dumps({1: SEGREDO}, protocol=4)), "session"),
        "surrogate": (envelope(pickle.dumps({"a": SEGREDO + "\ud800"}, protocol=4)), "session"),
        "nan-ao-lado-do-segredo": (envelope(pickle.dumps({SEGREDO: float("nan")}, protocol=4)), "queue"),
        "truncado": (envelope(pickle_de(segredo_em_dicionario, parar=False)), "session"),
        "sobra-depois-do-stop": (envelope(pickle_de(segredo_em_dicionario) + SEGREDO.encode()), "session"),
        "utf8-invalido": (
            envelope(
                pickle_de(pickle.BINUNICODE + len(SEGREDO).to_bytes(4, "little") + SEGREDO.encode()[:-1] + b"\xff")
            ),
            "session",
        ),
        "opcode-global-de-texto": (envelope(pickle_de(b"c" + SEGREDO.encode() + b"\nx\n")), "session"),
        "protocolo-3": (envelope(pickle.dumps({SEGREDO: {1}}, protocol=3)), "session"),
        "datetime-com-argumento-ruim": (
            envelope(pickle_de(chamada("datetime", "datetime", texto(SEGREDO)))),
            "session",
        ),
        "deque-com-argumento-ruim": (
            envelope(pickle_de(chamada("collections", "deque", texto(SEGREDO), texto(SEGREDO)))),
            "session",
        ),
        "texto-base64-invalido": (SEGREDO + "!!!", "skin"),
        "texto-base64-do-mongo-invalido": (SEGREDO + "!!!", "session"),
        "zlib-invalido": (SEGREDO.encode() * 10, "session"),
        "raiz-nao-dicionario": (envelope(pickle_de(lista_de(SEGREDO))), "session"),
        "profundo": (envelope(pickle.dumps({SEGREDO: [[[[[[[[[[[[[[SEGREDO]]]]]]]]]]]]]]}, protocol=4)), "session"),
    }


def lista_de(texto_: str) -> bytes:
    return pickle.EMPTY_LIST + pickle.MARK + texto(texto_) + pickle.APPENDS


@pytest.mark.parametrize("nome", sorted(cenarios_de_vazamento()))
class TestSemVazamento:
    def recusar(self, nome):
        raw, kind = cenarios_de_vazamento()[nome]
        with pytest.raises(legacy_pickle.LegacyFormatError) as info:
            carregar(raw, kind)
        return info.value

    def test_mensagem_caminho_e_argumentos_nao_levam_o_conteudo(self, nome):
        erro = self.recusar(nome)
        assert vazamentos(erro) == [], f"{nome}: o dado apareceu em {vazamentos(erro)}"

    def test_a_excecao_original_do_pickle_nao_fica_encadeada(self, nome):
        erro = self.recusar(nome)
        assert erro.__cause__ is None
        assert erro.__context__ is None or erro.__suppress_context__

    def test_nada_vai_para_o_log_nem_para_a_saida(self, nome, caplog, capsys):
        with caplog.at_level(logging.DEBUG):
            self.recusar(nome)
        assert all(
            SEGREDO not in registro.getMessage() and SEGREDO not in repr(registro.args) for registro in caplog.records
        )
        saida = capsys.readouterr()
        assert SEGREDO not in saida.out and SEGREDO not in saida.err

    def test_o_erro_nao_guarda_o_valor(self, nome):
        erro = self.recusar(nome)
        assert SEGREDO not in repr(vars(erro))


class TestLeituraBemSucedidaNaoAvisa:
    def test_leitura_valida_nao_gera_aviso_nem_saida(self, caplog, capsys):
        with caplog.at_level(logging.WARNING):
            assert carregar(envelope(pickle_de(dicionario((texto("a"), inteiro(1))))), "session") == {"a": 1}
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
        saida = capsys.readouterr()
        assert saida.out == "" and saida.err == ""

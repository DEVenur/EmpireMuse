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
import importlib.util
import pickle
import zlib
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from tests.support.formatos_reais import cog_de_sessoes
from tests.support.leitor_legado import (
    CORRUPT,
    ENVELOPE,
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
)
from tests.support.formato_sessao import gravar, jogador_completo
from tests.persistence.test_formato_skin import skin_realista, texto_legado

pytestmark = pytest.mark.critical

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
    def test_tem_a_mesma_assinatura_do_schema_error(self):
        erro = legacy_pickle.LegacyFormatError("", CORRUPT)
        assert erro.path == "" and erro.code == CORRUPT


# ============================================================================ o que os gravadores reais geram


class TestSessaoReal:
    @pytest_asyncio.fixture
    async def sessao(self):
        """A sessão como a versão ANTIGA a gravava: o ``save_info`` de hoje já não leva ``voice_state`` nem ``extra_info``."""
        dados = await gravar(cog_de_sessoes(), jogador_completo())
        return {**dados, "voice_state": {"sessionId": "sessao-de-voz"}, "extra_info": {}}

    @pytest.mark.asyncio
    async def test_sessao_com_skin_personalizada_passa(self):
        skin = skin_realista()
        sessao = await gravar(
            cog_de_sessoes(), jogador_completo(skin="> custom_skin: Minha", custom_skin_data={"Minha": skin})
        )
        lido, _ = igual_ao_pickle_de_hoje(comprimido(pickle.dumps(sessao, protocol=5)), "session")
        assert lido["custom_skin_data"] == {"Minha": skin}

    @pytest.mark.asyncio
    async def test_bytes_e_texto_da_mesma_sessao_dao_o_mesmo_resultado(self, sessao):
        raw = comprimido(pickle.dumps(sessao, protocol=4))
        assert carregar(raw, "session") == carregar(em_base64(raw), "session")


class TestFilaReal:
    @pytest.mark.parametrize("protocolo", [4, 5])
    def test_fila_nos_dois_protocolos(self, protocolo):
        conteudo = {
            "tracks": [{"title": "x", "extra": {"requester": 1}}] * 3,
            "created_at": datetime.now(UTC),
            "guild_id": 7,
        }
        igual_ao_pickle_de_hoje(comprimido(pickle.dumps(conteudo, protocol=protocolo)), "queue")


class TestSkinReal:
    @pytest.mark.parametrize("protocolo", [0, 3])
    def test_skin_em_protocolo_antigo_e_recusada(self, protocolo):
        recusado(medir(carregar, texto_legado(skin_realista(), protocolo), "skin"), PROTOCOL)


# ============================================================================ o que vale como raw


class TestTipoDoRaw:
    def valido(self):
        return pickle_de(dicionario((texto("a"), inteiro(1))))

    def test_skin_so_aceita_texto(self):
        assert carregar(envelope(self.valido(), "skin"), "skin") == {"a": 1}
        recusado(medir(carregar, self.valido(), "skin"), TYPE)
        recusado(medir(carregar, comprimido(self.valido()), "skin"), TYPE)


class TestBase64Estrito:
    """O texto do Mongo (sessão) e da skin é ``base64`` PADRÃO e estrito: nada de espaço, quebra de linha ou lixo."""

    def textos_validos(self):
        dados = pickle_de(dicionario((texto("a"), inteiro(1))))
        return {"skin": em_base64(dados), "session": em_base64(comprimido(dados))}

    @pytest.mark.parametrize(
        "adulterar",
        [
            lambda t: t[:8] + "\n" + t[8:],
            lambda t: t[:4] + "\x00" + t[4:],
        ],
        ids=range(2),
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

    @pytest.mark.parametrize(
        ("valor", "codigo"),
        [
            (b"bytes", TYPE),
            ("a\ud800b", SURROGATE),
        ],
        ids=["bytes", "surrogate"],
    )
    def test_tipo_ou_valor_recusado_pelo_validador(self, valor, codigo):
        for embrulho in (lambda v: {"a": v}, lambda v: {"a": [v]}, lambda v: {"a": {"b": (v,)}}):
            self.recusa(embrulho(valor), codigo)

    def test_datetime_ingenuo_e_com_fuso_passam_na_validacao(self):
        assert self.lido({"a": datetime(2026, 1, 1), "b": datetime(2026, 1, 1, tzinfo=UTC)})["a"].tzinfo is None


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


class TestCodigoFonte:
    def test_o_unpickler_restrito_existe_e_e_um_so(self):
        assert len(classes_que_herdam_do_unpickler(arvore_do_leitor())) == 1

    def test_persistent_load_levanta(self):
        (classe,) = classes_que_herdam_do_unpickler(arvore_do_leitor())
        alvo = metodo(classe, "persistent_load")
        assert alvo is not None, "o Unpickler restrito precisa definir persistent_load"
        assert any(isinstance(no, ast.Raise) for no in ast.walk(alvo))
        assert not any(isinstance(no, ast.Return) and no.value is not None for no in ast.walk(alvo))

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

    def test_o_erro_nao_guarda_o_valor(self, nome):
        erro = self.recusar(nome)
        assert SEGREDO not in repr(vars(erro))

"""F3-6b, etapa 5 — complemento do QA depois da mutação do núcleo REAL (59c02147): sobreviventes que não eram equivalentes.

* nome da skin da sessão com 256 caracteres passa e com 257 faz a skin virar ``{}`` (a sessão segue);
* URL válida maior que 2048 caracteres vira ``""`` e a faixa fica (e não derruba a faixa pelo teto do campo de texto);
* URL com espaço nas pontas ou entre ``<>`` não é "consertada": vira ``""``;
* chave de URL em ``pluginInfo`` com valor vazio é mantida;
* ``dj`` com repetição no JSON volta sem repetição e ordenado;
* a redução por tamanho tira o histórico (``played``) do mais ANTIGO para o mais novo;
* os tetos de texto da faixa (título, fonte, ISRC) e ``position``/``length`` negativos descartam a faixa;
* ``deque`` dentro da faixa (``extra``) e fila entregue como ``deque`` são aceitos e viram lista.
"""

import copy
from collections import deque

import pytest

from tests.support.sessoes import bruto, decodificar, faixa_info, session, sessao_minima
from tests.serialization.test_sessao_faixas import gravada_info, lida_info
from tests.serialization.test_sessao_tamanho import com_plugin, ida_e_volta, normais, titulos

LEITORES = pytest.mark.parametrize("ler", [lida_info, gravada_info], ids=["leitura", "gravacao"])
SKIN = {"queue_max_entries": 7, "content": "Tocando"}


class TestNomeDaSkinNaSessao:
    @pytest.mark.parametrize("campo", ["custom_skin_data", "custom_skin_static_data"])
    def test_256_caracteres_passam_e_257_viram_dicionario_vazio(self, campo):
        no_teto = session.decode_session(
            session.encode_session(sessao_minima(**{campo: {"n" * 256: copy.deepcopy(SKIN)}}))
        )
        assert list(no_teto[campo]) == ["n" * 256]
        acima = decodificar(bruto(**{campo: {"n" * 257: copy.deepcopy(SKIN)}}))
        assert acima[campo] == {} and acima["_id"]


class TestUrlLongaEMalFormada:
    @LEITORES
    def test_url_valida_mas_maior_que_2048_vira_vazio_e_a_faixa_fica(self, ler):
        longa = "https://exemplo.invalid/" + "x" * 3000
        faixa = ler(faixa_info(0, uri=longa, artworkUrl=longa, sourceName="deezer"))
        assert faixa["uri"] == "" and faixa["artworkUrl"] == "" and faixa["title"] == "Música 0"

    @LEITORES
    def test_url_de_exatamente_2048_caracteres_passa(self, ler):
        exata = "https://exemplo.invalid/" + "x" * (2048 - len("https://exemplo.invalid/"))
        assert len(exata) == 2048 and ler(faixa_info(0, uri=exata))["uri"] == exata

    @LEITORES
    @pytest.mark.parametrize(
        "url",
        [
            " https://exemplo.invalid/x",
            "https://exemplo.invalid/x ",
            "\thttps://exemplo.invalid/x",
            "<https://exemplo.invalid/x>",
        ],
    )
    def test_nao_conserta_a_url_por_aparar_ou_desembrulhar(self, ler, url):
        assert ler(faixa_info(0, uri=url))["uri"] == ""

    @LEITORES
    def test_chave_de_url_vazia_em_plugin_info_e_mantida(self, ler):
        faixa = ler(faixa_info(0, pluginInfo={"artistUrl": "", "albumUrl": None}))
        assert faixa["pluginInfo"] == {"artistUrl": "", "albumUrl": None}


class TestDj:
    def test_repeticao_no_json_volta_sem_repeticao_e_ordenada(self):
        assert decodificar(bruto(dj=[5, 5, 3, 9, 3]))["dj"] == [3, 5, 9]


class TestReducaoMantemOMaisNovoDoHistorico:
    def test_played_perde_primeiro_as_faixas_mais_antigas(self):
        originais = [com_plugin(n, "h") for n in range(40, 65)]  # ~10 MiB de histórico
        lidos = ida_e_volta(queue=normais(0, 2), played=originais)
        mantidos = len(lidos["played"])
        assert 0 <= mantidos < 25
        assert titulos(lidos["played"]) == titulos(originais)[len(originais) - mantidos :]


class TestTetosDaFaixa:
    @pytest.mark.parametrize(("campo", "teto"), [("title", 2048), ("sourceName", 256), ("isrc", 64)])
    def test_o_teto_exato_passa_e_um_a_mais_descarta_a_faixa(self, campo, teto):
        ok = faixa_info(0, **{campo: "x" * teto})
        ruim = faixa_info(1, **{campo: "x" * (teto + 1)})
        lidas = decodificar(bruto(queue=[ok, ruim, faixa_info(2)]))["queue"]
        assert len(lidas) == 2 and lidas[0][campo] == "x" * teto

    @pytest.mark.parametrize("campo", ["position", "length"])
    def test_numero_negativo_descarta_a_faixa(self, campo):
        lidas = decodificar(bruto(queue=[faixa_info(0), faixa_info(1, **{campo: -1}), faixa_info(2)]))["queue"]
        assert [f["title"] for f in lidas] == ["Música 0", "Música 2"]


class TestDequeEmFaixa:
    def test_deque_dentro_do_extra_vira_lista(self):
        info = faixa_info(0)
        info["extra"]["fila"] = deque([1, (2, 3)])
        lida = session.decode_session(session.encode_session(sessao_minima(queue=[info])))
        assert lida["queue"][0]["extra"]["fila"] == [1, [2, 3]]

    def test_fila_entregue_como_deque_e_aceita(self):
        lida = session.decode_session(
            session.encode_session(sessao_minima(queue=deque([faixa_info(0), faixa_info(1)])))
        )
        assert [f["title"] for f in lida["queue"]] == ["Música 0", "Música 1"]

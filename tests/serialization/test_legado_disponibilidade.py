"""F3-6b, etapa 2 (RED) — ``legacy_pickle.load_legacy``: DISPONIBILIDADE. Cada caso tem limite de tempo e de memória.

Um pickle hostil não precisa executar nada para derrubar o bot: basta pedir memória ou tempo demais. Aqui cada vetor da
tabela de DoS do plano vira um caso que ``load_legacy`` tem de recusar (``LegacyFormatError``, nunca outra exceção) rápido e
sem alocar o que o dado promete: memo de 9 bytes que pede 2³¹ posições, ``set`` de hash colidente (quadrático), aninhamento
de 10⁵ a 5·10⁶ níveis, bomba de compartilhamento de memo (poucos bytes, 10²⁰ ou 10³⁹ visitas), bomba de zlib,
``FRAME``/``BINUNICODE8``/``BINUNICODE`` gigantes sobre poucos bytes e arquivo vazio ou truncado.

Os tetos (opcodes, ``MARK``, itens de ``set``, tamanho) têm caso de BORDA: o teto exato passa e um a mais é recusado.
"""

import os
import pickle
import pickletools
import struct

import pytest
import pytest_asyncio

from tests.support.leitor_legado import (
    CORRUPT,
    DEPTH,
    ENVELOPE,
    MARK_LIMIT,
    MAX_MARK_DEPTH,
    MAX_OPCODES,
    MAX_RAW,
    MAX_SET_ITEMS,
    MIB,
    NODES,
    OPCODE,
    OPCODE_LIMIT,
    PROTOCOL,
    SET_LIMIT,
    TOO_BIG,
    TYPE,
    aninhado_em_listas,
    bruto,
    comprimido,
    conjunto_colidente,
    dicionario,
    em_base64,
    envelope,
    inteiro,
    legacy_pickle,
    medir,
    teto_de_tempo,
    pickle_de,
    pickle_de_n_opcodes,
    pickle_de_tamanho,
    proto,
    recusado,
    texto,
)
from tests.persistence.test_formato_sessao import gravar, jogador_completo


def carregar(raw, kind="session"):
    return legacy_pickle.load_legacy(raw, kind)


def rapido(medida, codigos, pico=8 * MIB):
    recusado(medida, codigos, segundos=1.0, pico=pico)


# ============================================================================ memo de 9 bytes


class TestMemoGigante:
    @pytest.mark.parametrize(
        "pedido",
        [
            pickle.LONG_BINPUT + struct.pack("<I", 2**31 - 1),
            pickle.LONG_BINPUT + struct.pack("<I", 2**32 - 1),
            pickle.BINPUT + b"\xff",
            b"p2147483647\n",
        ],
        ids=["long-2**31", "long-2**32", "binput", "put-texto"],
    )
    @pytest.mark.parametrize("kind", ["session", "queue", "skin"])
    def test_pedido_de_posicao_de_memo_e_recusado_sem_alocar(self, pedido, kind):
        dados = pickle_de(pickle.NONE, pedido)
        assert len(dados) <= 16
        rapido(medir(carregar, envelope(dados, kind), kind), OPCODE)

    def test_o_pickle_de_9_bytes_do_plano(self):
        dados = pickle_de(pickle.NONE, pickle.LONG_BINPUT + struct.pack("<I", 2**31 - 1), parar=False)
        assert len(dados) == 2 + 1 + 5
        rapido(medir(carregar, envelope(dados + pickle.STOP)), OPCODE)

    def test_memo_normal_por_memoize_funciona(self):
        esperado = {"a": [1, 2], "b": "x"}
        assert carregar(comprimido(pickle.dumps(esperado, protocol=4))) == esperado

    def test_leitura_de_posicao_de_memo_gigante_e_corrupcao_tratada(self):
        for pedido in (pickle.LONG_BINGET + struct.pack("<I", 2**31 - 1), pickle.BINGET + b"\xff"):
            rapido(medir(carregar, envelope(pickle_de(pedido))), CORRUPT)


# ============================================================================ set de hash colidente


class TestSetColidente:
    def test_o_teto_e_de_mil_itens(self):
        assert legacy_pickle.MAX_SET_ITEMS == MAX_SET_ITEMS == 1000

    @pytest.mark.parametrize("itens", [20_000, 60_000])
    def test_set_colidente_enorme_e_recusado_sem_o_custo_quadratico(self, itens):
        dados = conjunto_colidente(itens)
        recusado(medir(carregar, envelope(dados)), SET_LIMIT, segundos=2.0, pico=32 * MIB)

    def test_mil_itens_colidentes_passam_rapido(self):
        medida = medir(carregar, envelope(conjunto_colidente(1000)))
        assert medida.erro is None and medida.segundos < teto_de_tempo(2.0)
        assert len(medida.resultado["s0"]) == 1000

    def test_mil_e_um_itens_sao_recusados(self):
        recusado(medir(carregar, envelope(conjunto_colidente(1001))), SET_LIMIT, segundos=2.0)

    def test_o_teto_e_do_documento_inteiro_e_nao_de_cada_set(self):
        assert len(carregar(envelope(conjunto_colidente(100, conjuntos=10)))) == 10
        recusado(medir(carregar, envelope(conjunto_colidente(100, conjuntos=11))), SET_LIMIT, segundos=2.0)

    def test_varios_lotes_de_additems_somam(self):
        recusado(medir(carregar, envelope(conjunto_colidente(3000))), SET_LIMIT, segundos=2.0)

    def test_set_sem_colisao_tambem_respeita_o_teto(self):
        dados = pickle_de(
            dicionario(
                (
                    texto("s"),
                    pickle.EMPTY_SET + pickle.MARK + b"".join(inteiro(n) for n in range(1001)) + pickle.ADDITEMS,
                )
            )
        )
        recusado(medir(carregar, envelope(dados)), SET_LIMIT)

    def test_item_composto_conta_como_um_item_e_nao_como_varios_opcodes(self):
        itens = [inteiro(n) + pickle.TUPLE1 for n in range(400)]
        dados = pickle_de(dicionario((texto("s"), pickle.EMPTY_SET + pickle.MARK + b"".join(itens) + pickle.ADDITEMS)))
        assert len(carregar(envelope(dados))["s"]) == 400

    def test_set_real_do_dj_passa(self):
        assert carregar(comprimido(pickle.dumps({"dj": set(range(100, 160))}, protocol=4))) == {
            "dj": set(range(100, 160))
        }

    def test_set_dentro_da_skin_tambem_conta(self):
        """A skin não tem classes, mas o ``set`` (opcodes próprios) segue o mesmo teto."""
        recusado(medir(carregar, em_base64(conjunto_colidente(5000)), "skin"), SET_LIMIT, segundos=2.0)


# ============================================================================ aninhamento profundo


class TestAninhamentoProfundo:
    def test_100_mil_niveis_sem_mark_carregam_e_a_estrutura_recusa_sem_recursionerror(self):
        recusado(medir(carregar, envelope(aninhado_em_listas(100_000))), DEPTH, segundos=4.0, pico=128 * MIB)

    def test_1_milhao_de_niveis_passa_do_teto_de_opcodes(self):
        assert 2 * 1_000_000 > MAX_OPCODES["session"]
        recusado(medir(carregar, envelope(aninhado_em_listas(1_000_000)), memoria=False), OPCODE_LIMIT, segundos=8.0)

    def test_5_milhoes_de_niveis_sao_recusados_sem_ler_tudo(self):
        dados = aninhado_em_listas(5_000_000)
        assert len(dados) > MAX_RAW["session"]
        recusado(medir(carregar, envelope(dados), memoria=False), {TOO_BIG, OPCODE_LIMIT}, segundos=8.0)

    def test_5_milhoes_de_niveis_na_skin_e_na_fila(self):
        dados = aninhado_em_listas(5_000_000)
        recusado(
            medir(carregar, envelope(dados, "queue"), "queue", memoria=False), {TOO_BIG, OPCODE_LIMIT}, segundos=8.0
        )
        recusado(medir(carregar, envelope(dados, "skin"), "skin", memoria=False), {TOO_BIG, OPCODE_LIMIT}, segundos=8.0)

    def test_no_teto_de_opcodes_a_pre_varredura_passa_e_a_estrutura_recusa(self):
        """O aninhamento que cabe nos 1,5 milhão de opcodes é lido e liberado; quem recusa é o teto de profundidade."""
        dados = aninhado_em_listas(749_990)
        assert sum(1 for _ in pickletools.genops(dados)) <= MAX_OPCODES["session"]
        recusado(medir(carregar, envelope(dados), memoria=False), DEPTH, segundos=8.0)

    def test_mark_aninhado_65_e_recusado_pela_pre_varredura(self):
        recusado(medir(carregar, envelope(mark_aninhado(65))), MARK_LIMIT, segundos=1.0)

    def test_mark_aninhado_64_passa_a_pre_varredura_e_a_estrutura_recusa_pela_profundidade(self):
        assert MAX_MARK_DEPTH == 64 == legacy_pickle.MAX_MARK_DEPTH
        recusado(medir(carregar, envelope(mark_aninhado(64))), DEPTH, segundos=1.0)

    def test_mark_aninhado_gigante_e_recusado_sem_alocar_um_metastack(self):
        recusado(
            medir(carregar, envelope(mark_aninhado(200_000), "session"), memoria=True),
            {MARK_LIMIT, TOO_BIG, OPCODE_LIMIT},
            segundos=2.0,
            pico=16 * MIB,
        )

    def test_aninhamento_modesto_dentro_do_teto_e_lido(self):
        niveis = {"a": {"b": [{"c": [1, 2, {"d": "x"}]}]}}
        assert carregar(comprimido(pickle.dumps(niveis, protocol=4))) == niveis


def mark_aninhado(niveis: int) -> bytes:
    """``niveis`` listas encaixadas, cada uma aberta com seu próprio ``MARK`` (fechada por ``APPENDS``)."""
    abre = pickle.EMPTY_LIST + pickle.MARK
    fecha = pickle.APPENDS
    return pickle_de(pickle.EMPTY_DICT, texto("a"), abre * niveis, pickle.NONE, fecha * niveis, pickle.SETITEM)


# ============================================================================ tetos de opcodes: a borda


class TestTetoDeOpcodes:
    def test_os_tetos_sao_os_do_plano(self):
        assert legacy_pickle.MAX_OPCODES == MAX_OPCODES == {"session": 1_500_000, "queue": 600_000, "skin": 50_000}

    @pytest.mark.parametrize("kind", ["skin", "queue", "session"])
    def test_o_teto_exato_passa_e_um_a_mais_e_recusado(self, kind):
        teto = MAX_OPCODES[kind]
        dados = pickle_de_n_opcodes(teto)
        assert sum(1 for _ in pickletools.genops(dados)) == teto
        passou = medir(carregar, envelope(dados, kind), kind, memoria=False)
        assert passou.erro is None and passou.segundos < teto_de_tempo(8.0) and passou.resultado == {"a": None}
        a_mais = pickle_de_n_opcodes(teto + 1)
        assert sum(1 for _ in pickletools.genops(a_mais)) == teto + 1
        recusado(medir(carregar, envelope(a_mais, kind), kind, memoria=False), OPCODE_LIMIT, segundos=8.0)

    def test_o_teto_conta_todos_os_opcodes_e_nao_so_os_do_dado(self):
        """O preenchimento por ``MEMOIZE`` (que não muda o dado) também conta."""
        recusado(medir(carregar, envelope(pickle_de_n_opcodes(50_001), "skin"), "skin"), OPCODE_LIMIT)

    @pytest.mark.parametrize(("kind", "total"), [("skin", 90_000), ("queue", 700_000), ("session", 2_000_000)])
    def test_acima_do_teto_a_recusa_nao_percorre_o_arquivo_inteiro(self, kind, total):
        """Um byte por opcode (``MEMOIZE``): cabe no teto de tamanho e estoura o de opcodes."""
        dados = pickle_de(pickle.EMPTY_DICT, pickle.MEMOIZE * total)
        assert len(dados) <= MAX_RAW[kind] and total > MAX_OPCODES[kind]
        recusado(medir(carregar, envelope(dados, kind), kind, memoria=False), OPCODE_LIMIT, segundos=8.0)


# ============================================================================ tamanho: bruto e descomprimido


class TestTamanho:
    def test_os_tetos_de_tamanho_sao_os_do_plano(self):
        assert legacy_pickle.MAX_RAW == MAX_RAW == {"session": 8 * MIB, "queue": 4 * MIB, "skin": 100 * 1024}

    @pytest.mark.parametrize("kind", ["session", "queue", "skin"])
    def test_descomprimido_no_teto_passa_e_um_byte_a_mais_e_recusado(self, kind):
        teto = MAX_RAW[kind]
        assert carregar(envelope(pickle_de_tamanho(teto), kind), kind)["c"].startswith("aaa")
        recusado(
            medir(carregar, envelope(pickle_de_tamanho(teto + 1), kind), kind, memoria=False), TOO_BIG, segundos=4.0
        )

    def test_bomba_de_zlib_e_recusada_sem_alocar_o_descomprimido(self):
        bomba = comprimido(bytes(64 * MIB))
        assert len(bomba) < 100_000
        for kind in ("session", "queue"):
            recusado(medir(carregar, bomba, kind), TOO_BIG, segundos=3.0, pico=3 * MAX_RAW[kind])

    def test_bomba_de_zlib_vinda_do_mongo_em_base64(self):
        texto_b64 = em_base64(comprimido(bytes(64 * MIB)))
        recusado(medir(carregar, texto_b64, "session"), TOO_BIG, segundos=3.0, pico=3 * MAX_RAW["session"])

    def test_bomba_com_pickle_valido_dentro(self):
        """Um pickle legítimo seguido de milhões de zeros (o ``zlib`` encolhe tudo) também estoura o teto.

        A memória admitida é a do próprio teto (o descompressor precisa chegar até ele para saber que passou), com folga.
        """
        dados = pickle_de(dicionario((texto("a"), inteiro(1)))) + bytes(32 * MIB)
        recusado(medir(carregar, comprimido(dados)), TOO_BIG, segundos=3.0, pico=3 * MAX_RAW["session"])

    @pytest.mark.parametrize("kind", ["session", "queue"])
    def test_bruto_acima_do_teto_e_recusado_antes_de_descomprimir(self, kind):
        lixo = os.urandom(MAX_RAW[kind] + 1)
        recusado(medir(carregar, lixo, kind), TOO_BIG, segundos=1.0, pico=4 * MIB)

    def test_texto_do_mongo_acima_do_teto_e_recusado_antes_de_decodificar(self):
        recusado(medir(carregar, "A" * (MAX_RAW["session"] * 2), "session"), TOO_BIG, segundos=1.0, pico=4 * MIB)

    def test_texto_de_skin_acima_do_teto_e_recusado_antes_de_decodificar(self):
        recusado(medir(carregar, "A" * (10 * MIB), "skin"), TOO_BIG, segundos=1.0, pico=4 * MIB)

    def test_skin_de_100_kib_vinda_do_editor_cabe_no_teto_de_texto(self):
        """O base64 de um pickle de exatamente 100 KiB não pode ser recusado por causa do tamanho do TEXTO."""
        assert carregar(em_base64(pickle_de_tamanho(MAX_RAW["skin"])), "skin")["c"]


# ============================================================================ FRAME, BINUNICODE8 e outros comprimentos gigantes


class TestComprimentosGigantes:
    @pytest.mark.parametrize(
        "trecho",
        [
            pickle.FRAME + struct.pack("<Q", 2**40) + pickle.NONE,
            pickle.FRAME + struct.pack("<Q", 2**63 - 1) + pickle.NONE,
            pickle.FRAME + struct.pack("<Q", 2**64 - 1),
            pickle.BINUNICODE + struct.pack("<I", 2**32 - 1) + b"abc",
            pickle.BINUNICODE + struct.pack("<I", 2**31) + b"abc",
            pickle.BINBYTES + struct.pack("<I", 2**32 - 1) + b"abc",
            pickle.SHORT_BINUNICODE + b"\xff" + b"abc",
            pickle.SHORT_BINBYTES + b"\xff" + b"abc",
            pickle.LONG1 + b"\xff" + b"\x01\x02",
            b"\x8d" + struct.pack("<Q", 2**40) + b"abc",  # BINUNICODE8
            b"\x8e" + struct.pack("<Q", 2**40) + b"abc",  # BINBYTES8
            b"\x96" + struct.pack("<Q", 2**40) + b"abc",  # BYTEARRAY8
            b"\x8b" + struct.pack("<I", 2**31 - 1) + b"\x01",  # LONG4
        ],
        ids=[
            "frame-2**40",
            "frame-2**63",
            "frame-2**64",
            "binunicode-4GB",
            "binunicode-2GB",
            "binbytes-4GB",
            "short-unicode-truncado",
            "short-bytes-truncado",
            "long1-truncado",
            "binunicode8",
            "binbytes8",
            "bytearray8",
            "long4",
        ],
    )
    @pytest.mark.parametrize("kind", ["session", "skin"])
    def test_comprimento_gigante_sobre_poucos_bytes_e_recusado_sem_alocar(self, trecho, kind):
        dados = pickle_de(trecho)
        assert len(dados) < 32
        rapido(medir(carregar, envelope(dados, kind), kind), {OPCODE, CORRUPT, TOO_BIG})

    def test_frame_com_tamanho_diferente_do_real_nao_atravessa_a_validacao(self):
        corpo = dicionario((texto("a"), inteiro(1))) + pickle.STOP
        for declarado in (0, 1, len(corpo) - 1, len(corpo) + 1, 10**6):
            dados = proto() + pickle.FRAME + struct.pack("<Q", declarado) + corpo
            medida = medir(carregar, envelope(dados))
            if medida.erro is None:
                assert medida.resultado == {"a": 1}
            else:
                rapido(medida, {CORRUPT, OPCODE})

    def test_pickle_real_com_frame_do_pickle_dumps_passa(self):
        assert pickle.dumps({"a": 1}, protocol=4)[2:3] == pickle.FRAME
        assert carregar(comprimido(pickle.dumps({"a": 1}, protocol=4))) == {"a": 1}

    def test_texto_enorme_dentro_do_teto_passa(self):
        grande = {"a": "x" * 1_000_000}
        assert carregar(comprimido(pickle.dumps(grande, protocol=4))) == grande

    def test_bytes_grande_dentro_de_dicionario_e_recusado_pelo_tipo(self):
        recusado(medir(carregar, comprimido(pickle_de(dicionario((texto("a"), bruto(b"x" * 1000)))))), TYPE)


# ============================================================================ arquivo vazio e truncado


class TestVazioETruncado:
    @pytest_asyncio.fixture
    async def sessao_em_pickle(self):
        from tests.support.formatos_reais import cog_de_sessoes

        dados = await gravar(cog_de_sessoes(), jogador_completo())
        return pickle.dumps(dados, protocol=4)

    @pytest.mark.parametrize("kind", ["session", "queue"])
    def test_arquivo_vazio_e_recusado(self, kind):
        rapido(medir(carregar, b"", kind), ENVELOPE)

    def test_texto_vazio_do_mongo_e_recusado(self):
        rapido(medir(carregar, "", "session"), ENVELOPE)

    @pytest.mark.parametrize("kind", ["session", "queue"])
    def test_zlib_de_nada_e_recusado(self, kind):
        rapido(medir(carregar, comprimido(b""), kind), {CORRUPT, PROTOCOL})

    @pytest.mark.parametrize("kind", ["session", "queue"])
    def test_lixo_que_nao_e_zlib_e_recusado(self, kind):
        for lixo in (b"\x00" * 100, b"abc", b"x\x9c", b"\x78\x9c" + b"\x00" * 50, os.urandom(500)):
            rapido(medir(carregar, lixo, kind), ENVELOPE)

    def test_pickle_sem_zlib_nao_e_aceito(self):
        """Sem o antigo "se não for zlib, lê assim mesmo": um pickle válido sem o envelope é recusado."""
        valido = pickle_de(dicionario((texto("a"), inteiro(1))))
        for kind in ("session", "queue"):
            rapido(medir(carregar, valido, kind), ENVELOPE)
        rapido(medir(carregar, em_base64(valido), "session"), ENVELOPE)

    def test_dois_fluxos_zlib_ou_sobra_depois_do_fluxo_sao_recusados(self):
        valido = comprimido(pickle_de(dicionario((texto("a"), inteiro(1)))))
        for dados in (valido + valido, valido + b"lixo", valido + b"\x00"):
            rapido(medir(carregar, dados), ENVELOPE)

    @pytest.mark.asyncio
    async def test_toda_truncagem_da_sessao_real_e_recusada_e_nunca_escapa_crua(self, sessao_em_pickle):
        total = len(sessao_em_pickle)
        cortes = sorted(
            set(list(range(0, 80)) + list(range(80, total, max(total // 60, 1))) + [total - 3, total - 2, total - 1])
        )
        for corte in cortes:
            medida = medir(carregar, comprimido(sessao_em_pickle[:corte]), memoria=False)
            assert medida.erro is not None, f"truncado em {corte} foi aceito"
            assert isinstance(medida.erro, legacy_pickle.LegacyFormatError), (
                f"corte {corte}: {type(medida.erro).__name__}"
            )
            assert medida.erro.code in {CORRUPT, PROTOCOL}, f"corte {corte}: {medida.erro.code}"

    @pytest.mark.asyncio
    async def test_truncagem_do_proprio_zlib_e_recusada(self, sessao_em_pickle):
        todo = comprimido(sessao_em_pickle)
        for corte in sorted(set(list(range(0, 40)) + [len(todo) // 2, len(todo) - 5, len(todo) - 1])):
            rapido(medir(carregar, todo[:corte]), ENVELOPE)

    @pytest.mark.asyncio
    async def test_um_byte_trocado_nunca_escapa_cru(self, sessao_em_pickle):
        base = bytearray(sessao_em_pickle)
        for posicao in range(0, len(base), max(len(base) // 80, 1)):
            adulterado = bytearray(base)
            adulterado[posicao] ^= 0xFF
            medida = medir(carregar, comprimido(bytes(adulterado)), memoria=False)
            if medida.erro is not None:
                assert isinstance(medida.erro, legacy_pickle.LegacyFormatError), (
                    f"{posicao}: {type(medida.erro).__name__}"
                )

    def test_skin_truncada_ou_vazia_de_pickle(self):
        valido = pickle.dumps({"content": "x", "embeds": [{"title": "t"}]}, protocol=4)
        for corte in range(1, len(valido)):
            medida = medir(carregar, em_base64(valido[:corte]), "skin", memoria=False)
            assert isinstance(medida.erro, legacy_pickle.LegacyFormatError), f"corte {corte}"
            assert medida.erro.code in {CORRUPT, PROTOCOL}


# ============================================================================ bomba de compartilhamento do memo


def bomba_de_memo(niveis: int, largura: int) -> bytes:
    """Poucos bytes e ``largura**niveis`` visitas: cada lista repete ``largura`` vezes a anterior (pelo memo).

    Tudo o que cada nível deixa na pilha vira item da lista do campo ``"a"`` (``MARK`` ... ``APPENDS``), então a profundidade
    medida da raiz é ``niveis + 3`` (dicionário, lista do campo e as ``niveis + 1`` listas encaixadas).
    """
    partes = [pickle.EMPTY_LIST, pickle.MEMOIZE]
    for nivel in range(1, niveis + 1):
        referencias = (pickle.BINGET + bytes([nivel - 1])) * largura
        partes += [pickle.EMPTY_LIST, pickle.MEMOIZE, pickle.MARK, referencias, pickle.APPENDS]
    return pickle_de(
        pickle.EMPTY_DICT, texto("a"), pickle.EMPTY_LIST, pickle.MARK, *partes, pickle.APPENDS, pickle.SETITEM
    )


def bomba_binaria(niveis: int) -> bytes:
    """``2**niveis`` visitas lógicas em centenas de bytes: cada nível é uma tupla de duas referências ao nível anterior."""
    partes = [pickle.NONE, pickle.MEMOIZE]
    for nivel in range(1, niveis + 1):
        partes += [pickle.BINGET + bytes([nivel - 1])] * 2 + [pickle.TUPLE2, pickle.MEMOIZE]
    return pickle_de(
        pickle.EMPTY_DICT, texto("a"), pickle.EMPTY_LIST, pickle.MARK, *partes, pickle.APPENDS, pickle.SETITEM
    )


class TestBombaDeMemo:
    def test_poucos_bytes_muitas_visitas_e_recusada_no_teto_de_nos(self):
        dados = bomba_de_memo(niveis=9, largura=100)
        assert len(dados) < 2_000
        recusado(medir(carregar, envelope(dados), memoria=False), NODES, segundos=8.0)

    def test_a_bomba_binaria_de_130_niveis_e_recusada_sem_percorrer(self):
        dados = bomba_binaria(130)
        assert len(dados) < 1_500
        recusado(medir(carregar, envelope(dados)), {DEPTH, NODES}, segundos=2.0, pico=16 * MIB)

    def test_a_bomba_binaria_rasa_dentro_dos_tetos_e_lida(self):
        lido = carregar(envelope(bomba_binaria(8)))  # 2**8 visitas e 10 níveis: cabe nos dois tetos
        assert len(lido["a"]) == 9

    def test_compartilhamento_legitimo_e_lido(self):
        compartilhado = ["x", "y"]
        esperado = {"a": compartilhado, "b": compartilhado, "c": [compartilhado, compartilhado]}
        lido = carregar(comprimido(pickle.dumps(esperado, protocol=4)))
        assert lido == esperado

    def test_a_bomba_na_skin_e_na_fila(self):
        dados = bomba_de_memo(niveis=9, largura=100)
        recusado(medir(carregar, envelope(dados, "queue"), "queue", memoria=False), NODES, segundos=8.0)
        recusado(medir(carregar, envelope(dados, "skin"), "skin", memoria=False), NODES, segundos=8.0)

    def test_nenhum_json_dumps_nem_repr_nem_comparacao_toca_o_objeto_antes_da_validacao(self):
        """Se o leitor fizesse ``==``, ``repr`` ou ``json.dumps`` na bomba, o teste não terminaria no tempo."""
        dados = bomba_de_memo(niveis=9, largura=100)
        assert medir(carregar, envelope(dados), memoria=False).segundos < teto_de_tempo(8.0)


# ============================================================================ o que o gravador real gera cabe nos tetos, com folga


class TestFolgaDoQueECorreto:
    def test_sessao_de_5000_faixas_cabe_nos_tetos_e_e_rapida(self):
        faixa = {
            "identifier": "yt0",
            "title": "Música",
            "author": "Canal",
            "length": 180000,
            "isStream": False,
            "uri": "https://www.youtube.com/watch?v=yt0",
            "sourceName": "youtube",
            "extra": {
                "requester": 1,
                "track_loops": 0,
                "authors": ["A"],
                "album": {"name": "x", "url": "https://e.invalid/a"},
            },
            "id": "QAAAcodificado",
        }
        sessao = {"_id": 1, "queue": [dict(faixa, identifier=f"yt{n}") for n in range(5000)], "dj": {1, 2}}
        bruto_ = comprimido(pickle.dumps(sessao, protocol=4))
        medida = medir(carregar, bruto_, memoria=False)
        assert medida.erro is None and medida.segundos < teto_de_tempo(3.0)
        assert medida.resultado == sessao

    def test_pre_varredura_de_um_milhao_e_meio_de_opcodes_leva_poucos_segundos(self):
        """Poucos segundos E custo linear: o tempo de 1/10 dos opcodes, medido nas mesmas condições, calibra o limite.

        Sob ``coverage`` a varredura (Python puro) leva ~5x o normal; um teto absoluto mediria o tracing. Um custo
        quadrático daria ~100x o tempo de 1/10, muito acima de ``folga_linear`` (o custo linear dá ~10x).
        """
        folga_linear = 15
        total = MAX_OPCODES["session"]
        calibracao = medir(carregar, envelope(pickle_de_n_opcodes(total // 10)), memoria=False)
        assert calibracao.erro is None, calibracao.erro
        medida = medir(carregar, envelope(pickle_de_n_opcodes(total)), memoria=False)
        assert medida.erro is None and medida.segundos < max(teto_de_tempo(8.0), folga_linear * calibracao.segundos)

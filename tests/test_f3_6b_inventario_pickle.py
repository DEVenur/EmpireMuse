"""F3-6b, etapa 0 — inventário por ``ast`` dos pontos que leem e gravam ``pickle`` em ``empiremuse/``.

O ``legacy_pickle.py`` fica FORA do inventário (é o único leitor autorizado).

Os testes de inventário (``test_pontos_de_leitura_sao_os_do_inventario`` e
``test_pontos_de_gravacao_sao_os_do_inventario``) comparam o que o código tem com as tabelas ``LEITURAS`` e ``GRAVACOES``
abaixo. Quando um ponto some (ou aparece), o teste falha e a mensagem lista EXATAMENTE o que sumiu e o que apareceu: a
etapa que mexeu no ponto remove a linha da tabela no mesmo commit, e as tabelas encolhem até esvaziar.

Conta pontos de CHAMADA (``pickle.load``, ``loads``, ``dump``, ``dumps``) e, à parte, as demais referências ao módulo
(por exemplo ``pickle.UnpicklingError`` nos ``except``). Resolve ``import pickle as p`` e ``from pickle import loads``;
referência sem chamada (``leitor = pickle.loads``) também conta.
"""

import ast
from collections import Counter
from pathlib import Path

import pytest

PACOTE = Path(__file__).resolve().parents[1] / "empiremuse"
MODULOS_PICKLE = frozenset({"pickle", "_pickle", "cPickle"})
CHAMADAS_DE_LEITURA = frozenset({"load", "loads", "Unpickler"})
CHAMADAS_DE_GRAVACAO = frozenset({"dump", "dumps", "Pickler"})

# (arquivo relativo a empiremuse/, função, chamada, linhas, dado, pontos, etapa que remove).
# ``dado`` = família do dado; ``pontos`` = pontos lógicos (o par ``custom_skins``/``custom_skins_static`` conta um só,
# cada um dos 3 caches de ``load_cache`` conta um); a última coluna é a etapa que remove o ponto.
LEGADO = "serialization/legacy_pickle.py"  # o único leitor autorizado: fora do inventário do produto

# As 11 leituras de ANTES da etapa 2b (documentam os números do plano). Depois da 2b o produto não lê pickle sozinho.
LEITURAS_ANTES_DA_2B = [
    ("cogs/player_resume.py", "PlayerSession.get_player_sessions_mongo", "loads", 1, "sessao", 1, "2b"),
    ("cogs/player_resume.py", "PlayerSession.get_player_sessions_local", "loads", 1, "sessao", 1, "2b"),
    ("cogs/music.py", "Music.play", "loads", 1, "fila", 1, "2b"),
    ("cogs/music.py", "Music.create_player", "loads", 2, "skin", 1, "2b"),
    ("cogs/music_settings.py", "MusicSettings.change_skin", "loads", 2, "skin", 1, "2b"),
    ("utils/music/interactions.py", "SkinEditorMenu.load_skin", "loads", 1, "skin", 1, "2b"),
    ("utils/music/interactions.py", "SkinEditorMenu.modal_handler", "loads", 2, "skin", 1, "2b"),
    ("utils/client.py", "BotPool.load_cache", "load", 3, "cache", 3, "2b"),
    ("utils/music/lastfm_tools.py", "LastFM.scrobble_load_cache", "load", 1, "cache", 1, "2b"),
]
# Estado atual (depois da 2b): nenhuma leitura. Quem ler pickle passa por ``legacy_pickle.load_legacy``.
LEITURAS: list = []
GRAVACOES = [
    ("cogs/player_resume.py", "PlayerSession.save_session_mongo", "dumps", 1, "sessao", 1, "5"),
    ("cogs/player_resume.py", "PlayerSession.save_session_local", "dumps", 1, "sessao", 1, "5"),
    ("utils/music/interactions.py", "SkinEditorMenu.modal_handler", "dumps", 1, "skin", 1, "3"),
]
# Referências que não são chamada de leitura nem de gravação (hoje: as classes de erro dos ``except`` dos caches).
OUTRAS_REFERENCIAS: list = []  # antes da 2b: o ``pickle.UnpicklingError`` dos ``except`` dos caches (4 referências)
# Arquivos que fazem ``import pickle`` depois da 2b (só para gravar; ``music_settings.py`` só lia e deixa de importar).
IMPORTADORES = [
    "cogs/player_resume.py",
    "utils/music/interactions.py",
]


# ============================================================================ o varredor


def referencias_ao_pickle(codigo: str) -> list[tuple[str, str, int]]:
    """Todas as referências ao módulo ``pickle`` em ``codigo`` como ``(função qualificada, atributo, linha)``.

    A função qualificada junta classes e funções que envolvem a referência (``Classe.metodo``); fora de função é ``""``.
    """
    arvore = ast.parse(codigo)
    modulos, nomes = set(), {}
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            modulos.update(alias.asname or alias.name for alias in no.names if alias.name in MODULOS_PICKLE)
        elif isinstance(no, ast.ImportFrom) and no.module in MODULOS_PICKLE:
            nomes.update({alias.asname or alias.name: alias.name for alias in no.names})
    achadas: list[tuple[str, str, int]] = []

    def visitar(no: ast.AST, pilha: tuple[str, ...]) -> None:
        for filho in ast.iter_child_nodes(no):
            if isinstance(filho, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                visitar(filho, (*pilha, filho.name))
                continue
            if isinstance(filho, ast.Attribute) and isinstance(filho.value, ast.Name) and filho.value.id in modulos:
                achadas.append((".".join(pilha), filho.attr, filho.lineno))
            elif isinstance(filho, ast.Name) and filho.id in nomes and isinstance(filho.ctx, ast.Load):
                achadas.append((".".join(pilha), nomes[filho.id], filho.lineno))
            visitar(filho, pilha)

    visitar(arvore, ())
    return achadas


def inventario_do_pacote() -> dict[str, list[tuple[str, str, int]]]:
    """``{arquivo relativo a empiremuse/: referências ao pickle}``, só dos arquivos que têm alguma."""
    achado = {}
    for arquivo in sorted(PACOTE.rglob("*.py")):
        if "__pycache__" in arquivo.parts or arquivo.relative_to(PACOTE).as_posix() == LEGADO:
            continue
        codigo = arquivo.read_text(encoding="utf-8")
        if "pickle" not in codigo.lower():
            continue
        referencias = referencias_ao_pickle(codigo)
        if referencias:
            achado[arquivo.relative_to(PACOTE).as_posix()] = referencias
    return achado


def contar(inventario, atributos) -> Counter:
    """``Counter`` de ``(arquivo, função, chamada)``: cada linha achada conta uma vez."""
    contagem = Counter()
    for arquivo, referencias in inventario.items():
        for funcao, atributo, _linha in referencias:
            if atributo in atributos:
                contagem[(arquivo, funcao, atributo)] += 1
    return contagem


def esperado(tabela) -> Counter:
    return Counter({(arquivo, funcao, chamada): linhas for arquivo, funcao, chamada, linhas, *_ in tabela})


def diferenca(rotulo: str, previsto: Counter, achado: Counter) -> str:
    """Mensagem que lista exatamente o que sumiu e o que apareceu em relação à tabela do inventário."""
    sumiram = sorted((previsto - achado).elements())
    apareceram = sorted((achado - previsto).elements())
    linhas = [f"o inventário de {rotulo} mudou: atualize a tabela do teste no mesmo commit da mudança."]
    linhas += [f"  SUMIU:    {arquivo} :: {funcao} :: pickle.{chamada}" for arquivo, funcao, chamada in sumiram]
    linhas += [f"  APARECEU: {arquivo} :: {funcao} :: pickle.{chamada}" for arquivo, funcao, chamada in apareceram]
    return "\n".join(linhas)


# ============================================================================ o inventário do código de verdade


@pytest.fixture(scope="module")
def inventario():
    return inventario_do_pacote()


def test_pontos_de_leitura_sao_os_do_inventario(inventario):
    achado, previsto = contar(inventario, CHAMADAS_DE_LEITURA), esperado(LEITURAS)
    assert achado == previsto, diferenca("leitura", previsto, achado)


def test_pontos_de_gravacao_sao_os_do_inventario(inventario):
    achado, previsto = contar(inventario, CHAMADAS_DE_GRAVACAO), esperado(GRAVACOES)
    assert achado == previsto, diferenca("gravação", previsto, achado)


def test_outras_referencias_ao_pickle_sao_as_do_inventario(inventario):
    conhecidas = CHAMADAS_DE_LEITURA | CHAMADAS_DE_GRAVACAO
    achado = Counter()
    for arquivo, referencias in inventario.items():
        for funcao, atributo, _linha in referencias:
            if atributo not in conhecidas:
                achado[(arquivo, funcao, atributo)] += 1
    previsto = Counter({(a, f, c): n for a, f, c, n in OUTRAS_REFERENCIAS})
    assert achado == previsto, diferenca("outras referências", previsto, achado)


def test_arquivos_que_importam_o_pickle_sao_os_do_inventario():
    achado = set()
    for arquivo in PACOTE.rglob("*.py"):
        if "__pycache__" in arquivo.parts or arquivo.relative_to(PACOTE).as_posix() == LEGADO:
            continue
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            nomes = []
            if isinstance(no, ast.Import):
                nomes = [alias.name for alias in no.names]
            elif isinstance(no, ast.ImportFrom):
                nomes = [no.module or ""]
            if any(nome.split(".")[0] in MODULOS_PICKLE for nome in nomes):
                achado.add(arquivo.relative_to(PACOTE).as_posix())
    assert sorted(achado) == sorted(IMPORTADORES), (
        f"sumiram: {sorted(set(IMPORTADORES) - achado)}; apareceram: {sorted(achado - set(IMPORTADORES))}"
    )


def test_nenhuma_referencia_ao_pickle_fica_fora_de_funcao(inventario):
    """Referência no nível do módulo escaparia do inventário por função: não pode existir."""
    soltas = [
        (arquivo, atributo, linha)
        for arquivo, referencias in inventario.items()
        for funcao, atributo, linha in referencias
        if not funcao
    ]
    assert soltas == []


# ============================================================================ os números do plano (11 / 14 / 9 / 6)


class TestNumerosDoInventario:
    """Os números do plano (11 / 14 / 9 / 6) e o que a 2b muda: as 11 leituras somem e as 6 gravações ficam."""

    def test_antes_da_2b_eram_11_pontos_14_linhas_e_9_funcoes(self):
        assert sum(pontos for *_, pontos, _ in LEITURAS_ANTES_DA_2B) == 11
        assert sum(linhas for _, _, _, linhas, *_ in LEITURAS_ANTES_DA_2B) == 14
        assert len({(arquivo, funcao) for arquivo, funcao, *_ in LEITURAS_ANTES_DA_2B}) == 9

    def test_antes_da_2b_as_leituras_por_familia_de_dado(self):
        """A 2b troca por ``load_legacy`` os 7 pontos de sessão (2), fila (1) e skin (4), e remove os 4 de cache."""
        pontos, linhas = Counter(), Counter()
        for _, _, _, n_linhas, dado, n_pontos, _ in LEITURAS_ANTES_DA_2B:
            pontos[dado] += n_pontos
            linhas[dado] += n_linhas
        assert dict(pontos) == {"sessao": 2, "fila": 1, "skin": 4, "cache": 4}
        assert linhas["skin"] == 7

    def test_toda_leitura_antiga_saiu_na_2b(self):
        assert {etapa for *_, etapa in LEITURAS_ANTES_DA_2B} == {"2b"}

    def test_depois_da_2b_nao_ha_leitura_nem_referencia_solta_ao_pickle(self):
        assert LEITURAS == [] and OUTRAS_REFERENCIAS == []

    def test_gravacoes_sao_3_depois_das_etapas_4_e_6_e_saem_nas_etapas_3_e_5(self):
        assert sum(pontos for *_, pontos, _ in GRAVACOES) == 3
        assert sum(linhas for _, _, _, linhas, *_ in GRAVACOES) == 3
        assert {etapa for *_, etapa in GRAVACOES} == {"3", "5"}

    def test_as_tabelas_nao_repetem_chaves(self):
        for tabela in (LEITURAS_ANTES_DA_2B, GRAVACOES):
            chaves = [(arquivo, funcao, chamada) for arquivo, funcao, chamada, *_ in tabela]
            assert len(chaves) == len(set(chaves))


# ============================================================================ o varredor, provado com código sintético


class TestVarredorDeReferencias:
    def referencias(self, codigo):
        return [(funcao, atributo) for funcao, atributo, _ in referencias_ao_pickle(codigo)]

    def test_resolve_classe_e_metodo(self):
        codigo = "import pickle\nclass A:\n    async def f(self):\n        return pickle.loads(b'')\n"
        assert self.referencias(codigo) == [("A.f", "loads")]

    def test_conta_cada_linha_uma_vez(self):
        codigo = "import pickle\ndef f():\n    a = pickle.loads(x)\n    b = pickle.loads(y)\n    pickle.dumps(z)\n"
        assert self.referencias(codigo) == [("f", "loads"), ("f", "loads"), ("f", "dumps")]

    def test_resolve_apelido_do_modulo(self):
        assert self.referencias("import pickle as pk\ndef f():\n    return pk.loads(b'')\n") == [("f", "loads")]

    def test_resolve_importacao_de_nome(self):
        codigo = "from pickle import loads as ler, dumps\ndef f():\n    ler(b'')\n    dumps(1)\n"
        assert self.referencias(codigo) == [("f", "loads"), ("f", "dumps")]

    def test_o_modulo_c_tambem_conta(self):
        assert self.referencias("import _pickle\ndef f():\n    _pickle.loads(b'')\n") == [("f", "loads")]

    def test_referencia_sem_chamada_conta(self):
        codigo = "import pickle\ndef f():\n    leitor = pickle.loads\n    return leitor\n"
        assert self.referencias(codigo) == [("f", "loads")]

    def test_funcao_aninhada_leva_o_caminho_completo(self):
        codigo = "import pickle\ndef f():\n    def g():\n        pickle.load(h)\n"
        assert self.referencias(codigo) == [("f.g", "load")]

    def test_nivel_de_modulo_fica_com_funcao_vazia(self):
        assert self.referencias("import pickle\nDADOS = pickle.loads(b'')\n") == [("", "loads")]

    def test_texto_e_comentario_nao_contam(self):
        assert self.referencias("# pickle.loads(x)\nT = 'pickle.loads(x)'\n") == []

    def test_outro_objeto_com_o_mesmo_nome_de_metodo_nao_conta(self):
        assert self.referencias("import json\ndef f():\n    json.loads('1')\n    cache.loads(x)\n") == []

    def test_sem_importar_o_pickle_nada_conta(self):
        assert self.referencias("def f():\n    pickle.loads(x)\n") == []

    def test_diferenca_lista_o_que_sumiu_e_o_que_apareceu(self):
        previsto = Counter({("a.py", "f", "loads"): 2})
        achado = Counter({("a.py", "f", "loads"): 1, ("b.py", "g", "load"): 1})
        mensagem = diferenca("leitura", previsto, achado)
        assert "SUMIU:    a.py :: f :: pickle.loads" in mensagem
        assert "APARECEU: b.py :: g :: pickle.load" in mensagem
        assert mensagem.count("SUMIU") == 1 and mensagem.count("APARECEU") == 1

"""F3-6b, etapa 5 (commit próprio de ``utils/db.py``) — ``query_data`` passa a respeitar o ``limit`` e nasce ``iter_data`` (cursor).

Hoje ``MongoDatabase.query_data`` faz ``[d async for d in colecao.find(filtro)]`` e IGNORA o ``limit`` (a coleção inteira vai para a
memória) e ``LocalDatabase.query_data`` devolve o cursor do TinyMongo, também sem ``limit``. A migração das sessões (R3, decisão
do MAESTRO) precisa de um CURSOR que entregue os documentos aos poucos: ``iter_data(db_name, collection, filter=None)``, gerador
assíncrono nos dois bancos (``async for documento in banco.iter_data(...)``).

* caracterização dos chamadores atuais (passa hoje e tem de continuar passando): sem ``limit`` EXPLÍCITO a consulta devolve tudo
  (nenhum teto escondido de 100 ou 500), o ``filter`` filtra, e ``misc.fixfavs`` passa o ``limit`` que queria (300 e 500);
* RED: com ``limit=n`` devolve no máximo ``n`` e puxa do cursor no máximo ``n`` (+1) documentos; ``iter_data`` entrega preguiçosamente.
"""

import ast
from pathlib import Path

import pytest

from empiremuse.utils.db import LocalDatabase, MongoDatabase

RAIZ = Path(__file__).resolve().parents[1]


class CursorFalso:
    """O cursor assíncrono do motor: ``limit()`` encadeável e contagem do que foi realmente puxado."""

    def __init__(self, documentos):
        self.documentos, self.teto, self.puxados = list(documentos), None, 0

    def limit(self, n):
        self.teto = n
        return self

    def __aiter__(self):
        return self._gerar()

    async def _gerar(self):
        for indice, documento in enumerate(self.documentos):
            if self.teto is not None and indice >= self.teto:
                return
            self.puxados += 1
            yield dict(documento)


class ColecaoFalsa:
    def __init__(self, documentos):
        self.documentos, self.ultimo_cursor, self.filtros = documentos, None, []

    def find(self, filtro=None):
        self.filtros.append(filtro)
        selecionados = [d for d in self.documentos if all(d.get(k) == v for k, v in (filtro or {}).items())]
        self.ultimo_cursor = CursorFalso(selecionados)
        return self.ultimo_cursor


def mongo_com(documentos) -> tuple[MongoDatabase, ColecaoFalsa]:
    colecao = ColecaoFalsa(documentos)
    banco = MongoDatabase.__new__(MongoDatabase)
    banco._connect = {"global": {"guilds": colecao}}
    return banco, colecao


def docs(quantos: int) -> list[dict]:
    return [{"_id": str(n), "par": n % 2 == 0} for n in range(quantos)]


# ============================================================================ caracterização: o que os chamadores de hoje esperam


class TestChamadoresDeHoje:
    @pytest.mark.asyncio
    async def test_mongo_sem_limit_devolve_a_colecao_inteira(self):
        banco, _ = mongo_com(docs(150))
        assert len(list(await banco.query_data(db_name="guilds", collection="global"))) == 150

    @pytest.mark.asyncio
    async def test_mongo_o_filtro_filtra(self):
        banco, _ = mongo_com(docs(10))
        achados = list(await banco.query_data(db_name="guilds", collection="global", filter={"par": True}))
        assert sorted(d["_id"] for d in achados) == ["0", "2", "4", "6", "8"]

    @pytest.mark.asyncio
    async def test_mongo_devolve_dicionarios(self):
        banco, _ = mongo_com(docs(3))
        assert all(isinstance(d, dict) for d in await banco.query_data(db_name="guilds", collection="global"))

    @pytest.mark.asyncio
    async def test_local_sem_limit_devolve_tudo_e_o_filtro_filtra(self, tmp_path):
        banco = LocalDatabase(dir_=str(tmp_path))
        for n in range(150):
            await banco.update_data(id_=n, data={"par": n % 2 == 0}, db_name="guilds", collection="global")
        todos = list(await banco.query_data(db_name="guilds", collection="global"))
        assert len(todos) == 150
        pares = list(await banco.query_data(db_name="guilds", collection="global", filter={"par": True}))
        assert len(pares) == 75

    def test_o_fixfavs_passa_o_limit_que_queria(self):
        arvore = ast.parse((RAIZ / "empiremuse" / "cogs" / "misc.py").read_text(encoding="utf-8"))
        limites = []
        for no in ast.walk(arvore):
            if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr == "query_data":
                limites.append(
                    {k.arg: k.value.value for k in no.keywords if isinstance(k.value, ast.Constant)}.get("limit")
                )
        assert sorted(limites) == [300, 500]


# ============================================================================ RED: o limit passa a valer


class TestLimit:
    @pytest.mark.asyncio
    async def test_mongo_com_limit_devolve_no_maximo_o_limit_e_nao_puxa_o_resto(self):
        banco, colecao = mongo_com(docs(150))
        achados = list(await banco.query_data(db_name="guilds", collection="global", limit=7))
        assert len(achados) == 7 and colecao.ultimo_cursor.puxados <= 8

    @pytest.mark.asyncio
    async def test_mongo_limit_maior_que_a_colecao_devolve_tudo(self):
        banco, _ = mongo_com(docs(5))
        assert len(list(await banco.query_data(db_name="guilds", collection="global", limit=500))) == 5

    @pytest.mark.asyncio
    async def test_mongo_limit_com_filtro(self):
        banco, _ = mongo_com(docs(20))
        achados = list(await banco.query_data(db_name="guilds", collection="global", filter={"par": True}, limit=3))
        assert len(achados) == 3 and all(d["par"] for d in achados)

    @pytest.mark.asyncio
    async def test_local_com_limit_devolve_no_maximo_o_limit(self, tmp_path):
        banco = LocalDatabase(dir_=str(tmp_path))
        for n in range(30):
            await banco.update_data(id_=n, data={"n": n}, db_name="guilds", collection="global")
        assert len(list(await banco.query_data(db_name="guilds", collection="global", limit=4))) == 4


# ============================================================================ RED: iter_data, o cursor preguiçoso


class TestIterData:
    @pytest.mark.asyncio
    async def test_mongo_entrega_aos_poucos(self):
        banco, colecao = mongo_com(docs(100))
        vistos = []
        async for documento in banco.iter_data(db_name="guilds", collection="global"):
            vistos.append(documento["_id"])
            if len(vistos) == 3:
                break
        assert vistos == ["0", "1", "2"] and colecao.ultimo_cursor.puxados <= 4

    @pytest.mark.asyncio
    async def test_mongo_percorre_tudo_e_aplica_o_filtro(self):
        banco, _ = mongo_com(docs(10))
        todos = [d async for d in banco.iter_data(db_name="guilds", collection="global")]
        pares = [d async for d in banco.iter_data(db_name="guilds", collection="global", filter={"par": True})]
        assert len(todos) == 10 and len(pares) == 5

    @pytest.mark.asyncio
    async def test_mongo_nao_monta_a_lista_da_colecao(self):
        banco, colecao = mongo_com(docs(1000))
        async for _ in banco.iter_data(db_name="guilds", collection="global"):
            break
        assert colecao.ultimo_cursor.puxados <= 2

    @pytest.mark.asyncio
    async def test_local_tambem_tem_iter_data(self, tmp_path):
        banco = LocalDatabase(dir_=str(tmp_path))
        for n in range(12):
            await banco.update_data(id_=n, data={"n": n}, db_name="guilds", collection="global")
        assert len([d async for d in banco.iter_data(db_name="guilds", collection="global")]) == 12

    @pytest.mark.asyncio
    async def test_iter_data_nao_grava_nem_apaga_nada(self):
        banco, colecao = mongo_com(docs(5))
        _ = [d async for d in banco.iter_data(db_name="guilds", collection="global")]
        assert len(colecao.documentos) == 5

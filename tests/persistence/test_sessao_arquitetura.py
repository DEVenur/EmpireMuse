"""F3-6b, etapa 5 (RED, commit 2) — arquitetura por ``ast`` do armazenamento das sessões.

* ``empiremuse/utils/music/session_store.py`` existe (caminhos, leitura, gravação, remoção e migração), lê arquivo só com teto
  (nunca ``read_bytes()``/``read_text()``/``read()`` sem argumento), não importa ``pickle`` e não usa o ``query_data`` do Mongo (que
  ignora o ``limit``): a leitura das sessões e da migração é por cursor (``iter_data``);
* a leitura de ``kind`` ``session`` pelo ``load_legacy`` fica na migração (``session_store.py`` ou ``legacy_reader.py``), nunca em
  ``player_resume.py``;
* ``PlayerSession`` expõe ``migrate_legacy_sessions`` (corrotina) e as camadas finas de sempre (``save_session_*``,
  ``get_player_sessions_*``, ``delete_data_*``).
"""

import ast
from pathlib import Path

import pytest

from tests.persistence.test_chave_de_corte_load_legacy import kind_da_chamada, nome_chamado
from tests.support.raiz import RAIZ

PACOTE = RAIZ / "empiremuse"
STORE = PACOTE / "utils" / "music" / "session_store.py"
LEITORES_AUTORIZADOS = {"utils/music/session_store.py", "utils/music/legacy_reader.py"}


def arvore(caminho: Path) -> ast.AST:
    return ast.parse(caminho.read_text(encoding="utf-8"))


def chamadas_sem_limite(no: ast.AST) -> list[tuple[str, int]]:
    achadas = []
    for chamada in ast.walk(no):
        if isinstance(chamada, ast.Call) and isinstance(chamada.func, ast.Attribute):
            nome = chamada.func.attr
            if nome in {"read_bytes", "read_text"} or (nome == "read" and not chamada.args and not chamada.keywords):
                achadas.append((nome, chamada.lineno))
    return achadas


class TestSessionStore:
    def test_o_modulo_existe(self):
        assert STORE.is_file()

    def test_nenhuma_leitura_de_arquivo_sem_limite(self):
        assert chamadas_sem_limite(arvore(STORE)) == []

    def test_nao_importa_pickle(self):
        importados = {
            a.name.split(".")[0] for n in ast.walk(arvore(STORE)) if isinstance(n, ast.Import) for a in n.names
        }
        deles = {n.module.split(".")[0] for n in ast.walk(arvore(STORE)) if isinstance(n, ast.ImportFrom) and n.module}
        assert not (importados | deles) & {"pickle", "_pickle", "marshal", "shelve"}

    def test_nao_usa_o_query_data_que_ignora_o_limit(self):
        usados = {
            chamada.func.attr
            for chamada in ast.walk(arvore(STORE))
            if isinstance(chamada, ast.Call) and isinstance(chamada.func, ast.Attribute)
        }
        assert "query_data" not in usados and "iter_data" in usados

    def test_a_pausa_entre_lotes_e_asyncio_sleep_de_meio_segundo(self):
        sleeps = [
            chamada
            for chamada in ast.walk(arvore(STORE))
            if isinstance(chamada, ast.Call)
            and isinstance(chamada.func, ast.Attribute)
            and chamada.func.attr == "sleep"
            and isinstance(chamada.func.value, ast.Name)
            and chamada.func.value.id == "asyncio"
        ]
        assert sleeps, "a migração do Mongo precisa de asyncio.sleep entre os lotes (patchável pelos testes)"


class TestLeituraDoLegado:
    def test_so_os_modulos_da_migracao_chamam_load_legacy_com_kind_session(self):
        leem_sessao = set()
        for arquivo in sorted(PACOTE.rglob("*.py")):
            if "__pycache__" in arquivo.parts or arquivo.name == "legacy_pickle.py":
                continue
            for no in ast.walk(arvore(arquivo)):
                if isinstance(no, ast.Call) and nome_chamado(no) == "load_legacy" and kind_da_chamada(no) == "session":
                    leem_sessao.add(arquivo.relative_to(PACOTE).as_posix())
        assert leem_sessao and leem_sessao <= LEITORES_AUTORIZADOS

    def test_player_resume_nao_chama_load_legacy(self):
        chamadas = {
            nome_chamado(n) for n in ast.walk(arvore(PACOTE / "cogs" / "player_resume.py")) if isinstance(n, ast.Call)
        }
        assert "load_legacy" not in chamadas and "read_legacy_session" not in chamadas


class TestSuperficieDoCog:
    @pytest.mark.parametrize(
        "nome",
        [
            "migrate_legacy_sessions",
            "save_session_local",
            "save_session_mongo",
            "get_player_sessions_local",
            "get_player_sessions_mongo",
            "delete_data_local",
            "delete_data_mongo",
            "delete_data",
        ],
    )
    def test_o_cog_tem_o_metodo(self, nome):
        from empiremuse.cogs.player_resume import PlayerSession

        assert callable(getattr(PlayerSession, nome))

    def test_migrate_legacy_sessions_e_corrotina(self):
        import inspect

        from empiremuse.cogs.player_resume import PlayerSession

        assert inspect.iscoroutinefunction(PlayerSession.migrate_legacy_sessions)

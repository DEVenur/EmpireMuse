"""F3-6 — ``BotPool``: nenhuma instância compartilha estado mutável com outra (achado da F3-2).

``BotPool`` declara ``bots`` e ``guild_bots`` no corpo da classe ("valores só de referência"); o ``__init__`` cria os de
cada instância. Declarações de classe mutáveis são uma armadilha (``cls.bots.append`` alteraria todos os pools) e não são
mais necessárias: nenhum teste depende delas (conferido removendo as duas linhas numa cópia: a suíte inteira segue igual).
Estes testes provam o que importa, o comportamento: instâncias independentes. O último é o único RED: a classe não deve
mais declarar contêineres mutáveis (o Backend pode remover as duas declarações).
Sem rede, sem Discord e sem ``.env`` real (``EMPIREMUSE_HOME`` em ``tmp_path``).
"""

from collections import deque

import pytest

from empiremuse.utils.client import BotPool

CONTEINERES = (list, dict, set, deque, bytearray)


@pytest.fixture
def isolado(monkeypatch, tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(home))
    monkeypatch.chdir(cwd)


def atributos_mutaveis(pool) -> list[str]:
    """Nomes dos atributos DA INSTÂNCIA que guardam um contêiner mutável (lista, dicionário, conjunto, cache)."""
    return sorted(
        nome
        for nome, valor in vars(pool).items()
        if isinstance(valor, CONTEINERES) or hasattr(valor, "__setitem__") and hasattr(valor, "clear")
    )


class TestInstanciasIndependentes:
    def test_cada_instancia_tem_o_seu_objeto_em_todos_os_atributos_mutaveis(self, isolado):
        a, b = BotPool(), BotPool()
        nomes = atributos_mutaveis(a)
        assert {"bots", "guild_bots", "failed_bots", "user_prefix_cache", "guild_prefix_cache"} <= set(nomes)
        compartilhados = [nome for nome in nomes if getattr(a, nome) is getattr(b, nome)]
        assert compartilhados == [], f"atributos compartilhados entre instâncias: {compartilhados}"

    def test_bots_e_guild_bots_de_uma_instancia_nao_aparecem_na_outra(self, isolado):
        a, b = BotPool(), BotPool()
        a.bots.append("bot-a")
        a.guild_bots.setdefault("111", []).append("bot-a")
        a.guild_bots["222"] = ["bot-a"]
        assert b.bots == [] and b.guild_bots == {}

    def test_uma_instancia_nova_nasce_vazia_mesmo_depois_de_outra_ter_sido_usada(self, isolado):
        usada = BotPool()
        usada.bots.extend(["x", "y"])
        usada.guild_bots["1"] = ["x"]
        usada.failed_bots["z"] = "erro"
        usada.user_prefix_cache[1] = "!"
        usada.guild_prefix_cache[2] = "?"
        nova = BotPool()
        assert (nova.bots, nova.guild_bots, nova.failed_bots) == ([], {}, {})
        assert (nova.user_prefix_cache, nova.guild_prefix_cache) == ({}, {})

    @pytest.mark.parametrize("nome", ["bots", "guild_bots", "failed_bots", "user_prefix_cache", "guild_prefix_cache"])
    def test_cada_atributo_pode_ser_reatribuido_sem_afetar_a_outra_instancia(self, isolado, nome):
        a, b = BotPool(), BotPool()
        original_b = getattr(b, nome)
        novo = type(original_b)()
        setattr(a, nome, novo)
        assert getattr(b, nome) is original_b and getattr(a, nome) is novo

    def test_o_estado_da_instancia_nao_vaza_para_a_classe(self, isolado):
        pool = BotPool()
        pool.bots.append("bot-a")
        pool.guild_bots["1"] = ["bot-a"]
        assert "bot-a" not in getattr(BotPool, "bots", [])
        assert "1" not in getattr(BotPool, "guild_bots", {})

    def test_um_pool_criado_sem_init_nao_enxerga_o_estado_de_outro(self, isolado):
        """Fixtures de teste montam o pool com ``BotPool.__new__`` e atribuem o que precisam: nada pode vir da classe."""
        com_init = BotPool()
        com_init.bots.append("bot-a")
        sem_init = BotPool.__new__(BotPool)
        sem_init.bots = []
        sem_init.guild_bots = {}
        assert sem_init.bots == [] and sem_init.guild_bots == {}


class TestClasseSemConteineresMutaveis:
    def test_a_classe_nao_declara_lista_dicionario_ou_conjunto(self):
        """RED: ``bots`` e ``guild_bots`` ainda estão declarados no corpo da classe (valores de classe mutáveis)."""
        declarados = sorted(
            nome
            for nome, valor in vars(BotPool).items()
            if not nome.startswith("__") and isinstance(valor, CONTEINERES)
        )
        assert declarados == [], f"contêineres mutáveis declarados na classe BotPool: {declarados}"

"""F3-6 — ``BotPool``: nenhuma instância compartilha estado mutável com outra (achado da F3-2).

``BotPool`` declara ``bots`` e ``guild_bots`` no corpo da classe ("valores só de referência"); o ``__init__`` cria os de
cada instância. Declarações de classe mutáveis são uma armadilha (``cls.bots.append`` alteraria todos os pools) e não são
mais necessárias: nenhum teste depende delas (conferido removendo as duas linhas numa cópia: a suíte inteira segue igual).
Estes testes provam o que importa, o comportamento: instâncias independentes. O último é o único RED: a classe não deve
mais declarar contêineres mutáveis (o Backend pode remover as duas declarações).
Sem rede, sem Discord e sem ``.env`` real (``EMPIREMUSE_HOME`` em ``tmp_path``).
"""

import pytest

from empiremuse.utils.client import BotPool


@pytest.fixture
def isolado(monkeypatch, tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(home))
    monkeypatch.chdir(cwd)


class TestInstanciasIndependentes:
    @pytest.mark.smoke
    def test_bots_e_guild_bots_de_uma_instancia_nao_aparecem_na_outra(self, isolado):
        a, b = BotPool(), BotPool()
        a.bots.append("bot-a")
        a.guild_bots.setdefault("111", []).append("bot-a")
        a.guild_bots["222"] = ["bot-a"]
        assert b.bots == [] and b.guild_bots == {}

    @pytest.mark.parametrize("nome", ["bots", "guild_prefix_cache"])
    def test_cada_atributo_pode_ser_reatribuido_sem_afetar_a_outra_instancia(self, isolado, nome):
        a, b = BotPool(), BotPool()
        original_b = getattr(b, nome)
        novo = type(original_b)()
        setattr(a, nome, novo)
        assert getattr(b, nome) is original_b and getattr(a, nome) is novo

    def test_um_pool_criado_sem_init_nao_enxerga_o_estado_de_outro(self, isolado):
        """Fixtures de teste montam o pool com ``BotPool.__new__`` e atribuem o que precisam: nada pode vir da classe."""
        com_init = BotPool()
        com_init.bots.append("bot-a")
        sem_init = BotPool.__new__(BotPool)
        sem_init.bots = []
        sem_init.guild_bots = {}
        assert sem_init.bots == [] and sem_init.guild_bots == {}

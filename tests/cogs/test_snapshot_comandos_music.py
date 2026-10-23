"""KI-29 — guarda do que o ``disnake`` registra para a Cog ``Music`` e do estado de classe por bot.

* Snapshot (``tests/repo/golden/comandos_music.json``, gerado do ``main`` antes da divisão): nome, tipo, descrição,
  opções, ``extras``, aliases, cooldown, concorrência máxima, quantidade de checks, autocompletes, subcomandos,
  listeners e membros da Cog. Dividir ``Music`` em mixins não pode mudar nada disso.
* Estado por bot: o ``disnake`` carrega cada extensão com ``module_from_spec`` + ``exec_module`` (sem o cache de
  ``sys.modules``), então o corpo da classe ``Music`` roda uma vez por bot e cada bot tem os próprios
  ``CooldownMapping``/``MaxConcurrency``. A divisão em módulos não pode fazer os bots passarem a dividi-los.
"""

import importlib
import importlib.util
import json
import sys

import pytest

from tests.support.api_publica import GOLDEN, descreve_comando, snapshot_music

NOME_DA_EXTENSAO = "empiremuse.cogs.music"
PREFIXO_DOS_MIXINS = "empiremuse.music_cog"


def dourado() -> dict:
    return json.loads((GOLDEN / "comandos_music.json").read_text(encoding="utf-8"))


class TestSnapshotDosComandos:
    def test_mesmos_comandos(self):
        atual, esperado = snapshot_music()["comandos"], dourado()["comandos"]
        assert sorted(atual) == sorted(esperado), (
            f"sumiram {sorted(set(esperado) - set(atual))}, apareceram {sorted(set(atual) - set(esperado))}"
        )

    def test_cada_comando_tem_a_mesma_descricao(self):
        atual, esperado = snapshot_music()["comandos"], dourado()["comandos"]
        diferentes = {
            nome: (esperado[nome], atual[nome]) for nome in esperado if nome in atual and esperado[nome] != atual[nome]
        }
        assert not diferentes, json.dumps(diferentes, ensure_ascii=False, indent=1, default=str)[:3000]

    def test_mesmos_listeners(self):
        assert snapshot_music()["listeners"] == dourado()["listeners"]

    def test_mesmos_membros_da_cog(self):
        atual, esperado = set(snapshot_music()["membros"]), set(dourado()["membros"])
        assert atual == esperado, f"sumiram {sorted(esperado - atual)}, apareceram {sorted(atual - esperado)}"

    def test_o_dourado_cobre_os_comandos_conhecidos(self):
        comandos = dourado()["comandos"]
        assert len(comandos) >= 60
        for nome in ("InvokableSlashCommand:play", "SubCommand:queue clear", "PoolCommand:setvoicestatus"):
            assert nome in comandos


# ============================================================================ estado de classe por bot


def carregar_como_extensao() -> object:
    """Faz o que ``CommonBotBase._load_from_module_spec`` faz: módulo novo, executado do zero, sem o cache."""
    spec = importlib.util.find_spec(NOME_DA_EXTENSAO)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[NOME_DA_EXTENSAO] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def duas_cargas():
    """Duas cargas da extensão (dois bots do pool) e restauração do ``sys.modules`` ao final."""
    importlib.import_module(NOME_DA_EXTENSAO)
    guardados = {
        nome: modulo
        for nome, modulo in sys.modules.items()
        if nome == NOME_DA_EXTENSAO or nome.startswith(PREFIXO_DOS_MIXINS + ".")
    }
    try:
        yield carregar_como_extensao(), carregar_como_extensao()
    finally:
        for nome in [n for n in sys.modules if n == NOME_DA_EXTENSAO or n.startswith(PREFIXO_DOS_MIXINS + ".")]:
            del sys.modules[nome]
        sys.modules.update(guardados)


def todos_os_comandos(modulo) -> dict:
    achados = {}
    for comando in [*modulo.Music.__cog_app_commands__, *modulo.Music.__cog_commands__]:
        for item in [comando, *(getattr(comando, "children", None) or {}).values()]:
            achados[f"{type(item).__name__}:{item.qualified_name}"] = item
    return achados


def grupos_que_compartilham(comandos: dict, atributo: str) -> list:
    """Conjuntos (com 2 ou mais comandos) que usam o MESMO objeto em ``atributo``, por nome de comando."""
    por_objeto: dict[int, list[str]] = {}
    for nome, comando in comandos.items():
        objeto = getattr(comando, atributo, None)
        if objeto is not None:
            por_objeto.setdefault(id(objeto), []).append(nome)
    return sorted(tuple(sorted(nomes)) for nomes in por_objeto.values() if len(nomes) > 1)


class TestEstadoPorBot:
    def test_cooldown_e_concorrencia_sao_objetos_diferentes_em_cada_carga(self, duas_cargas):
        primeira, segunda = (todos_os_comandos(modulo) for modulo in duas_cargas)
        assert sorted(primeira) == sorted(segunda)
        compartilhados = []
        for nome in primeira:
            for atributo in ("_buckets", "_max_concurrency"):
                a, b = getattr(primeira[nome], atributo, None), getattr(segunda[nome], atributo, None)
                if a is not None and a is b:
                    compartilhados.append(f"{nome}.{atributo}")
        assert not compartilhados, f"estado compartilhado entre bots: {compartilhados}"

    def test_o_proprio_corpo_da_classe_foi_reexecutado(self, duas_cargas):
        primeira, segunda = duas_cargas
        assert primeira.Music is not segunda.Music
        assert primeira.Music.play is not segunda.Music.play

    def test_comandos_que_dividem_o_mesmo_cooldown_continuam_dividindo_dentro_da_carga(self, duas_cargas):
        """O que hoje é um objeto só dentro de um bot (``play_cd`` em play/search, ``skip_back_cd`` em skip/back…)."""
        primeira, segunda = (todos_os_comandos(modulo) for modulo in duas_cargas)
        for comandos in (primeira, segunda):
            grupos = grupos_que_compartilham(comandos, "_buckets")
            assert any({"InvokableSlashCommand:play", "InvokableSlashCommand:search"} <= set(g) for g in grupos)
            assert any({"InvokableSlashCommand:skip", "InvokableSlashCommand:back"} <= set(g) for g in grupos)
        assert grupos_que_compartilham(primeira, "_buckets") == grupos_que_compartilham(segunda, "_buckets")
        assert grupos_que_compartilham(primeira, "_max_concurrency") == grupos_que_compartilham(
            segunda, "_max_concurrency"
        )

    def test_a_descricao_dos_comandos_nao_muda_de_uma_carga_para_outra(self, duas_cargas):
        primeira, segunda = (todos_os_comandos(modulo) for modulo in duas_cargas)
        assert {n: descreve_comando(c) for n, c in primeira.items()} == {
            n: descreve_comando(c) for n, c in segunda.items()
        }

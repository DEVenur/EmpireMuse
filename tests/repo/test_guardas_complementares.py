"""Guardas COMPLEMENTARES das de ``test_api_publica_e_custom_ids``, ``test_snapshot_comandos_music`` e
``test_monkeypatch_em_reexportacao``, para a divisão de ``music.py``, ``models.py`` e ``interactions.py``.

Cada teste fecha uma lacuna provada por mutação (um erro plantado que as guardas anteriores deixavam passar):

* G1  payload completo registrado no disnake (``body.to_dict()``) e identidade dos checks de cada comando;
* G2  estado de classe por bot de TODO ``CooldownMapping``/``MaxConcurrency`` da Cog, ligado a comando ou não;
* G3  corpos de função e atributos de classe como multiconjunto ``(nome, hash do ast)``, onde quer que morem;
* G4  cada módulo importa sozinho, em processo novo (ciclos que a ordem de import do pytest esconde);
* G5  monkeypatch na fachada: sem outro consumidor do nome fora dela, e formas de patch além de ``setattr``;
* G6  nenhum nome de nível superior definido duas vezes na família;
* G7  os leitores de fonte enxergam a família inteira (``fonte_da_familia``) e provam que leram o que importa.

Os dourados (``tests/repo/golden/payload_comandos_music.json`` e ``corpos_da_familia.json``) descrevem o estado ANTES da
divisão. Regerar só se o comportamento mudar de propósito, nunca em PR de movimentação::

    python -m tests.repo.test_guardas_complementares
"""

import ast
import collections
import hashlib
import importlib
import json
import pkgutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from disnake.ext import commands

from tests.cogs.test_snapshot_comandos_music import duas_cargas, todos_os_comandos  # noqa: F401  (fixture e extrator)
from tests.repo.test_monkeypatch_em_reexportacao import (
    MODULOS_ALVO,
    apelidos_dos_modulos,
    arquivo_do_modulo,
    pares_dos_testes,
)
from tests.support.api_publica import (
    FAMILIAS,
    GOLDEN,
    PACOTE,
    arquivos_da_familia,
    arvore_da_familia,
    fonte_da_familia,
    nomes_da_familia,
    nomes_definidos,
)
from tests.support.raiz import RAIZ

PAYLOAD = GOLDEN / "payload_comandos_music.json"
CORPOS = GOLDEN / "corpos_da_familia.json"


# ============================================================================ G1 — payload completo


def _nome_do_check(check) -> str:
    return getattr(check, "__qualname__", None) or type(check).__name__


def _estavel(valor):
    """``channel_types`` vem de um conjunto: a ordem muda com ``PYTHONHASHSEED``; o dourado guarda a lista ordenada."""
    if isinstance(valor, dict):
        return {k: sorted(v) if k == "channel_types" and isinstance(v, list) else _estavel(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_estavel(v) for v in valor]
    return valor


def payload_dos_comandos(modulo=None) -> dict:
    """O que o disnake envia ao Discord por comando (``body.to_dict()``) e a identidade dos checks, por nome qualificado."""
    modulo = modulo or importlib.import_module(FAMILIAS["music"][0])
    retrato = {}
    for chave, comando in todos_os_comandos(modulo).items():
        corpo = getattr(comando, "body", None)
        retrato[chave] = {
            "payload": _estavel(corpo.to_dict()) if hasattr(corpo, "to_dict") else None,
            "checks": [_nome_do_check(c) for c in getattr(comando, "checks", None) or []],
        }
    return json.loads(json.dumps(retrato, default=str))


def test_g1_payload_e_checks_de_cada_comando_sao_os_mesmos():
    atual, esperado = payload_dos_comandos(), json.loads(PAYLOAD.read_text(encoding="utf-8"))
    assert sorted(atual) == sorted(esperado)
    diferentes = [nome for nome in esperado if atual[nome] != esperado[nome]]
    assert not diferentes, f"payload/checks mudaram em: {diferentes[:15]}"


# ============================================================================ G2 — estado por bot, sem exceção


def estado_de_classe(modulo) -> dict:
    """Todo ``CooldownMapping``/``MaxConcurrency`` visível na Cog (inclusive herdado de mixin), ligado a comando ou não."""
    return {
        nome: getattr(modulo.Music, nome)
        for nome in dir(modulo.Music)
        if isinstance(getattr(modulo.Music, nome, None), (commands.CooldownMapping, commands.MaxConcurrency))
    }


def test_g2_todo_cooldown_e_concorrencia_da_cog_e_por_bot(duas_cargas):  # noqa: F811
    primeira, segunda = (estado_de_classe(modulo) for modulo in duas_cargas)
    assert sorted(primeira) == sorted(segunda) and len(primeira) >= 25
    compartilhados = sorted(nome for nome in primeira if primeira[nome] is segunda[nome])
    assert not compartilhados, f"estado de classe compartilhado entre bots: {compartilhados}"


# ============================================================================ G3 — corpos como multiconjunto


def _hash(no: ast.AST) -> str:
    return hashlib.sha1(ast.dump(no).encode()).hexdigest()[:12]


def _alvos(filho: ast.stmt) -> list[str]:
    candidatos = getattr(filho, "targets", None) or [getattr(filho, "target", None)]
    return [a.id for a in candidatos if isinstance(a, ast.Name)]


def _entradas(arvore: ast.AST) -> list[str]:
    entradas = []
    for no in ast.walk(arvore):
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entradas.append(f"def {no.name}:{_hash(no)}")  # decoradores, parâmetros e corpo
        if isinstance(no, (ast.Module, ast.ClassDef)):
            for filho in no.body:  # atributos de módulo e de classe (cooldowns, flags, constantes)
                if isinstance(filho, (ast.Assign, ast.AnnAssign)) and filho.value is not None and _alvos(filho):
                    entradas.append(f"= {','.join(_alvos(filho))}:{_hash(filho.value)}")
    return entradas


def corpos_da_familia(familia: str) -> dict[str, int]:
    contagem: collections.Counter = collections.Counter()
    for arquivo in arquivos_da_familia(familia):
        contagem.update(_entradas(ast.parse(arquivo.read_text(encoding="utf-8"))))
    return dict(sorted(contagem.items()))


@pytest.mark.parametrize("familia", sorted(FAMILIAS))
def test_g3_cada_funcao_e_atributo_segue_identico_onde_quer_que_more(familia):
    atual, esperado = corpos_da_familia(familia), json.loads(CORPOS.read_text(encoding="utf-8"))[familia]
    alterados = sorted(set(esperado.items()) ^ set(atual.items()))
    assert not alterados, f"{familia}: {len(alterados)} entradas diferem, ex.: {alterados[:6]}"


# ============================================================================ G4 — imports em processo novo


def modulos_para_importar_isolados() -> list[str]:
    musica = importlib.import_module("empiremuse.utils.music")
    nomes = [m.name for m in pkgutil.walk_packages(musica.__path__, "empiremuse.utils.music.")]
    nomes += sorted(f"empiremuse.cogs.{p.stem}" for p in (PACOTE / "cogs").glob("*.py") if not p.name.startswith("__"))
    if (PACOTE / "music_cog").is_dir():
        nomes += [m.name for m in pkgutil.walk_packages([str(PACOTE / "music_cog")], "empiremuse.music_cog.")]
    return nomes


def _importar_em_processo_novo(nome: str) -> tuple[str, str]:
    r = subprocess.run([sys.executable, "-c", f"import {nome}"], cwd=RAIZ, capture_output=True, text=True, timeout=180)
    return nome, ((r.stderr.strip().splitlines() or [""])[-1] if r.returncode else "")


def test_g4_cada_modulo_importa_sozinho_em_processo_novo():
    with ThreadPoolExecutor(max_workers=8) as pool:
        falhas = [
            (n, erro) for n, erro in pool.map(_importar_em_processo_novo, modulos_para_importar_isolados()) if erro
        ]
    assert not falhas, f"não importam sozinhos (ciclo de import?): {falhas[:5]}"


# ============================================================================ G5 — monkeypatch na fachada


def consumidores_fora_da_fachada(modulo: str, nome: str) -> list[str]:
    """Arquivos da família, que não são a fachada nem a definem, que importam ou leem ``nome`` por conta própria.

    Trocar ``nome`` na fachada não alcança esses arquivos (cada um tem a própria ligação): o teste passaria a testar o
    código de verdade só em parte, sem avisar.
    """
    familia = next(f for f, (m, _) in FAMILIAS.items() if m == modulo)
    fachada, achados = arquivo_do_modulo(modulo), []
    for arquivo in arquivos_da_familia(familia):
        if arquivo == fachada or nome in nomes_definidos(arquivo):
            continue
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        importa = any(isinstance(n, ast.ImportFrom) and any(a.name == nome for a in n.names) for n in ast.walk(arvore))
        le = any(isinstance(n, ast.Name) and n.id == nome and isinstance(n.ctx, ast.Load) for n in ast.walk(arvore))
        if importa or le:
            achados.append(str(arquivo.relative_to(RAIZ)))
    return achados


@pytest.mark.parametrize(("teste", "modulo", "nome"), pares_dos_testes(), ids=lambda v: str(v).split("/")[-1])
def test_g5_o_nome_trocado_na_fachada_nao_tem_outro_consumidor(teste, modulo, nome):
    outros = consumidores_fora_da_fachada(modulo, nome)
    assert not outros, (
        f"{teste}: monkeypatch de {modulo}.{nome}, mas outros arquivos da família ligam o nome por conta própria: "
        f"{outros}; troque o alvo (ou o auxiliar) para cada módulo de uso"
    )


def pares_modificados_ampliado(codigo: str) -> set[tuple[str, str]]:
    """Como ``pares_modificados``, mais ``patch``/``mock.patch``/``patch.object``, módulo sem apelido e nome dinâmico."""
    arvore, achados = ast.parse(codigo), set()
    apelidos = apelidos_dos_modulos(arvore)
    apelidos.update({m: m for m in MODULOS_ALVO})  # ``import a.b.c`` sem apelido e ``monkeypatch.setattr(a.b.c, ...)``

    def modulo_de(no: ast.expr):
        return apelidos.get(no.id) if isinstance(no, ast.Name) else apelidos.get(ast.unparse(no))

    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        funcao = no.func.attr if isinstance(no.func, ast.Attribute) else getattr(no.func, "id", "")
        args = no.args
        if funcao in {"setattr", "object"} and len(args) >= 2 and modulo_de(args[0]):
            nome = args[1]
            achados.add((modulo_de(args[0]), nome.value if isinstance(nome, ast.Constant) else "<nome dinâmico>"))
        elif (
            funcao in {"setattr", "patch"}
            and args
            and isinstance(args[0], ast.Constant)
            and isinstance(args[0].value, str)
        ):
            modulo, _, nome = args[0].value.rpartition(".")  # caminho com pontos: "pacote.modulo.nome"
            if modulo in MODULOS_ALVO:
                achados.add((modulo, nome))
    return achados


class TestDetectorAmpliado:
    CAB = "from empiremuse.cogs import music\nimport empiremuse.cogs.music\nfrom unittest import mock\nfrom unittest.mock import patch\n"

    @pytest.mark.parametrize(
        "codigo",
        [
            "def t(monkeypatch):\n monkeypatch.setattr(music, 'x', 1)\n",
            "def t():\n with mock.patch('empiremuse.cogs.music.x'):\n  pass\n",
            "def t():\n with patch('empiremuse.cogs.music.x'):\n  pass\n",
            "def t():\n with patch.object(music, 'x'):\n  pass\n",
            "def t(monkeypatch):\n monkeypatch.setattr(empiremuse.cogs.music, 'x', 1)\n",
        ],
    )
    def test_acha_a_forma(self, codigo):
        assert pares_modificados_ampliado(self.CAB + codigo) == {("empiremuse.cogs.music", "x")}

    def test_nome_dinamico_e_reportado_para_falhar_alto(self):
        achados = pares_modificados_ampliado(self.CAB + "def t(monkeypatch, n):\n monkeypatch.setattr(music, n, 1)\n")
        assert achados == {("empiremuse.cogs.music", "<nome dinâmico>")}

    def test_o_conjunto_ampliado_cobre_o_que_a_varredura_atual_ja_acha(self):
        from tests.repo.test_monkeypatch_em_reexportacao import TestDetector, pares_modificados

        assert pares_modificados(TestDetector.TESTE) <= pares_modificados_ampliado(TestDetector.TESTE)


def test_g5_nenhum_teste_usa_forma_de_patch_que_a_varredura_nao_resolve():
    sem_resolver = []
    for arquivo in sorted((RAIZ / "tests").rglob("*.py")):
        if arquivo.name == "test_guardas_complementares.py" or "__pycache__" in arquivo.parts:
            continue
        for modulo, nome in pares_modificados_ampliado(arquivo.read_text(encoding="utf-8")):
            if nome == "<nome dinâmico>":
                sem_resolver.append((str(arquivo.relative_to(RAIZ)), modulo))
    assert not sem_resolver, f"setattr com nome dinâmico em módulo da família: {sem_resolver}"


# ============================================================================ G6 — nome definido uma vez só


@pytest.mark.parametrize("familia", sorted(FAMILIAS))
def test_g6_nenhum_nome_de_nivel_superior_e_definido_duas_vezes(familia):
    contagem: collections.Counter = collections.Counter()
    for arquivo in arquivos_da_familia(familia):
        contagem.update(nomes_definidos(arquivo))
    duplicados = sorted(nome for nome in nomes_da_familia(familia) if contagem[nome] > 1)
    assert not duplicados, f"{familia}: definido em mais de um arquivo (cópia no lugar de movimentação?): {duplicados}"


# ============================================================================ G7 — leitores de fonte enxergam a família


@pytest.mark.parametrize(
    ("familia", "sentinela"),
    [("music", "class Music"), ("models", "class LavalinkPlayer"), ("interactions", "class FavMenuView")],
)
def test_g7_fonte_e_arvore_da_familia_trazem_o_codigo_de_verdade(familia, sentinela):
    """Quem lê o fonte para uma guarda NEGATIVA precisa provar que leu o código: a sentinela vem do núcleo da família."""
    assert sentinela in fonte_da_familia(familia)
    nomes = {no.name for no in arvore_da_familia(familia).body if isinstance(no, ast.ClassDef)}
    assert sentinela.removeprefix("class ") in nomes


@pytest.mark.parametrize("familia", sorted(FAMILIAS))
def test_g7_fonte_da_familia_e_a_soma_dos_arquivos(familia):
    arquivos = arquivos_da_familia(familia)
    assert arquivos and fonte_da_familia(familia).count("\n") >= sum(
        a.read_text(encoding="utf-8").count("\n") for a in arquivos
    )


def test_g7_nenhum_teste_le_o_arquivo_de_uma_familia_pelo_file_do_modulo():
    """``Path(modulo.__file__).read_text()`` lê só a fachada: depois da divisão, uma guarda negativa passa no vazio."""
    proibidos = {"models", "music", "interactions"}
    achados = []
    for arquivo in sorted((RAIZ / "tests").rglob("*.py")):
        if arquivo.name == "test_guardas_complementares.py" or "__pycache__" in arquivo.parts:
            continue
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Attribute) and no.attr == "__file__" and isinstance(no.value, ast.Name):
                if no.value.id in proibidos:
                    achados.append(f"{arquivo.relative_to(RAIZ)}:{no.lineno}")
    assert not achados, f"use fonte_da_familia/arvore_da_familia em vez de <modulo>.__file__: {achados}"


# ============================================================================ regeração dos dourados


def gerar() -> None:
    PAYLOAD.write_text(
        json.dumps(payload_dos_comandos(), ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    CORPOS.write_text(
        json.dumps({f: corpos_da_familia(f) for f in FAMILIAS}, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    gerar()

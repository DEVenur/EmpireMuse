"""Item 7 (P1) — achados do Vigil no ``redact`` e no agregador: V-P1-0 (ReDoS, ALTO) e os Baixos do Gambit.

ReDoS sem tempo real: o ``redact`` roda num SUBPROCESSO com entradas patológicas (N = 5000 repetições de cada unidade ambígua atrás de cada
prefixo de padrão). Linear, termina em milissegundos; backtracking exponencial nunca termina, e o ``timeout`` (só um limite contra a suíte
pendurar, não uma medida) vira falha. Nada que use a entrada patológica roda no processo do pytest (travaria). Os demais testes são de comportamento puro.
"""

import gc
import json
import logging
import os
import subprocess
import sys
import tracemalloc

import pytest

from empiremuse.logs.aggregate import RepeatAggregator
from empiremuse.logs.redact import REDACTED, configure_secrets, redact, register_secret, scrub
from tests.logs.apoio import Relogio, registro
from tests.support.raiz import RAIZ

pytestmark = pytest.mark.critical

LIMITE_DO_SUBPROCESSO = 60  # só impede a suíte de pendurar; o que se verifica é ter terminado

SCRIPT_REDOS = r"""
import sys
from empiremuse.logs.redact import configure_secrets, redact, scrub

N = 5000
PREFIXOS = [
    '', 'ytsearch:"key": "', "ytsearch:'sk': '", '{"password":"', "{'refresh_token': '", '"sessionKey" : "', "'Authorization': '",
    '?token=', '&api_key=', 'key=', 'Authorization: ', 'Authorization: Bot ', 'authorization:', '://', '://u:', 'mongodb+srv://u:',
    '/api/v10/webhooks/1/', '/api/webhooks/123456789012345678/', 'a' * 25 + '.', 'a' * 25 + '.' + 'b' * 6 + '.',
]
UNIDADES = ['\\', '\\\\', '\\"', "\\'", '"', "'", 'a', '@', ':', ' ', '/', '=', '-', '.', '&', '?', '://', 'a:', '"a', "'a", '\\a']
for prefixo in PREFIXOS:
    for unidade in UNIDADES:
        entrada = prefixo + unidade * N
        redact(entrada)
        scrub(entrada, 8192)
configure_secrets(["segredo-depois-do-ataque-1"])
assert redact('ytsearch:"key": "' + "\\" * N + " segredo-depois-do-ataque-1").endswith("***")
print("ok")
"""


def test_redact_terminates_on_pathological_input_for_every_pattern():
    ambiente = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(RAIZ), "HOME": os.environ.get("HOME", "")}
    try:
        resultado = subprocess.run(
            [sys.executable, "-c", SCRIPT_REDOS],
            cwd=str(RAIZ),
            env=ambiente,
            capture_output=True,
            text=True,
            timeout=LIMITE_DO_SUBPROCESSO,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("redact()/scrub() não terminaram: backtracking exponencial (ReDoS) em algum padrão")

    assert resultado.returncode == 0, resultado.stderr[-500:]
    assert resultado.stdout.strip() == "ok"


# ============================================================================ segredo com caracteres especiais em repr/json

COM_ESPECIAIS = "linha1\nlinha2\r\"aspas\"'simples'\\barra-final-Z9"


class TestSegredoComCaracteresEspeciais:
    @pytest.fixture(autouse=True)
    def registrado(self):
        register_secret(COM_ESPECIAIS)

    @pytest.mark.parametrize(
        "forma",
        [
            pytest.param(lambda s: s, id="cru"),
            pytest.param(repr, id="repr"),
            pytest.param(json.dumps, id="json"),
            pytest.param(lambda s: repr({"k": s}), id="repr-de-dict"),
            pytest.param(lambda s: str([s]), id="lista"),
            pytest.param(lambda s: json.dumps({"k": s}), id="json-de-dict"),
            pytest.param(lambda s: json.dumps({"k": s}, ensure_ascii=False), id="json-sem-ascii"),
        ],
    )
    def test_every_textual_form_of_the_secret_is_masked(self, forma):
        saida = redact(f"falhou com {forma(COM_ESPECIAIS)} no fim")

        assert "linha1" not in saida and "barra-final-Z9" not in saida and "simples" not in saida
        assert REDACTED in saida and saida.startswith("falhou com") and saida.endswith("no fim")

    def test_through_the_scrub_the_secret_in_a_repr_is_masked_too(self):
        assert "barra-final-Z9" not in scrub(repr(COM_ESPECIAIS), 8192)


# ============================================================================ userinfo com dois '@'


class TestUserinfoComDoisArrobas:
    @pytest.mark.parametrize(
        ("url", "esperada"),
        [
            ("https://user:p@ss@host/x", "https://***@host/x"),
            ("mongodb://u:pa@ss@h:27017/db", "mongodb://***@h:27017/db"),
            ("mongodb+srv://u:a@b@c@cluster0.exemplo.net/db", "mongodb+srv://***@cluster0.exemplo.net/db"),
            ("redis://default:senha@com@arroba@cache:6379/0", "redis://***@cache:6379/0"),
        ],
    )
    def test_the_whole_password_is_masked_up_to_the_last_at_sign_of_the_authority(self, url, esperada):
        assert redact(f"conectando em {url} agora") == f"conectando em {esperada} agora"

    def test_a_path_with_an_at_sign_is_not_taken_for_the_password(self):
        assert redact("GET https://exemplo.org/u/@ana/perfil") == "GET https://exemplo.org/u/@ana/perfil"


# ============================================================================ surrogate solto no quote()


class TestSurrogateSolto:
    def test_register_secret_with_a_lone_surrogate_does_not_raise_and_masks_the_plain_form(self):
        valor = "abc\ud800def-segredo-sur1"

        assert register_secret(valor) is None

        assert redact(f"x {valor} y") == f"x {REDACTED} y"


# ============================================================================ agregador: chave limitada, sem guardar a exceção


def com_template(template: str, mensagem: str = "curto", **campos) -> logging.LogRecord:
    record = registro(mensagem, nivel=logging.WARNING, nome="empiremuse.wavelink")
    record.empiremuse_template = template
    record.empiremuse_exc_type = None
    record.empiremuse_redacted = True
    for chave, valor in campos.items():
        setattr(record, chave, valor)
    return record


class TestAgregadorSemRetencao:
    def test_the_aggregator_does_not_keep_the_exception_of_a_record(self):
        import weakref

        class Marca:
            pass

        agregador = RepeatAggregator(lambda r: None, clock=Relogio())

        def alimentar():
            marca = Marca()
            try:
                raise ValueError(marca)
            except ValueError:
                info = sys.exc_info()
            primeiro = com_template("falha %s", exc_info=info)
            agregador.filter(primeiro)
            agregador.filter(com_template("falha %s"))
            return weakref.ref(marca)

        referencia = alimentar()
        gc.collect()

        assert referencia() is None, "o agregador segura a exceção (e os frames dela) do primeiro registro"

    def test_a_huge_template_is_not_kept_whole_in_the_aggregator(self):
        agregador = RepeatAggregator(lambda r: None, clock=Relogio())
        tracemalloc.start()
        try:
            for n in range(30):
                agregador.filter(com_template("t" * 1_000_000 + str(n)))
            gc.collect()
            retido, _ = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert retido < 5_000_000, (
            f"{retido} bytes retidos para 30 chaves: o template inteiro está na chave ou no registro guardado"
        )

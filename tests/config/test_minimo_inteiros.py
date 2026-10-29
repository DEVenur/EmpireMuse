"""F3-6 (AppSec F-1, I-1, I-2) — chaves inteiras que quebram ou abrem uma proteção com 0 ou negativo ganham mínimo 1.

Depois da correção do ``0`` do ``config.json`` (``test_f3_6_config_zero``), ``0`` e negativos chegam às chaves como o
operador escreveu. Para estas cinco, esse valor não tem significado válido e é perigoso:

* ``VOTE_SKIP_AMOUNT``: com 0 o primeiro voto já pula a música (anula a proteção do voteskip);
* ``HINT_RATE``: com 0 ``random.choice([])`` levanta ``IndexError`` a cada atualização do player;
* ``DBCACHE_SIZE`` e ``PLAYLIST_CACHE_SIZE``: ``TTLCache(maxsize=0)`` levanta ``ValueError`` na primeira gravação;
* ``MONGO_TIMEOUT``: 0 vira ``connectTimeoutMS=0`` (conexão sem timeout) e negativo é recusado pelo driver.

O mínimo vale igual para ``config.json``, ambiente e ``.env``; valores a partir de 1 (inclusive o padrão) ficam como estão.
Sem rede, sem ``.env`` real (o ``conftest`` neutraliza o ``dotenv_values``) e com ``EMPIREMUSE_HOME`` em ``tmp_path``.
"""

import json
import re

import pytest

from empiremuse import config_loader
from tests.support.raiz import RAIZ

pytestmark = pytest.mark.critical

CHAVES_COM_MINIMO_1 = ["VOTE_SKIP_AMOUNT", "HINT_RATE", "DBCACHE_SIZE", "PLAYLIST_CACHE_SIZE", "MONGO_TIMEOUT"]
EXAMPLE_ENV = RAIZ / ".example.env"


@pytest.fixture
def home(monkeypatch, tmp_path):
    pasta, cwd = tmp_path / "home", tmp_path / "cwd"
    pasta.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(pasta))
    monkeypatch.chdir(cwd)
    return pasta


def pelo_config_json(home, chave, valor):
    (home / "config.json").write_text(json.dumps({chave: valor}), encoding="utf-8")
    return config_loader.load_config()[chave]


def pelo_dotenv(monkeypatch, chave, texto):
    monkeypatch.setattr(config_loader, "dotenv_values", lambda *args, **kwargs: {chave: texto})
    return config_loader.load_config()[chave]


class TestMinimoUm:
    @pytest.mark.parametrize("chave", list(CHAVES_COM_MINIMO_1)[:2])
    @pytest.mark.parametrize("valor", [0, "-3"], ids=repr)
    def test_zero_ou_negativo_no_config_json_vira_1(self, home, chave, valor):
        assert pelo_config_json(home, chave, valor) == 1

    @pytest.mark.parametrize("chave", list(CHAVES_COM_MINIMO_1)[:2])
    @pytest.mark.parametrize("texto", ["0", "-50"])
    def test_zero_ou_negativo_no_dotenv_vira_1(self, home, monkeypatch, chave, texto):
        assert pelo_dotenv(monkeypatch, chave, texto) == 1


class TestValoresValidosIntactos:
    """GUARDA: do mínimo para cima nada muda, e o padrão continua sendo o padrão."""

    @pytest.mark.smoke
    @pytest.mark.parametrize("chave", list(CHAVES_COM_MINIMO_1)[:2])
    @pytest.mark.parametrize("valor", [1, 100], ids=repr)
    def test_a_partir_de_1_o_valor_e_respeitado(self, home, chave, valor):
        assert pelo_config_json(home, chave, valor) == int(valor)

    def test_outras_chaves_continuam_aceitando_zero(self, home):
        """0 segue com o seu significado nas chaves documentadas (sem limite) e nas que já têm o seu mínimo."""
        (home / "config.json").write_text(
            json.dumps({"MAX_USER_FAVS": 0, "MAX_USER_INTEGRATIONS": 0, "QUEUE_MAX_ENTRIES": 0}), encoding="utf-8"
        )
        config = config_loader.load_config()
        assert (config["MAX_USER_FAVS"], config["MAX_USER_INTEGRATIONS"], config["QUEUE_MAX_ENTRIES"]) == (0, 0, 0)

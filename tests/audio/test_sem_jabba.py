"""S-27 — o caminho do jabba (script ``install.sh`` baixado do ``master`` e executado) deixou de existir.

O JDK vem só do pacote com SHA-256 fixo (``_install_jdk_linux``/``_install_jdk_windows``). A chave ``USE_JABBA``, se
ainda estiver no ``.env``, é ignorada sem erro.
"""

from empiremuse import config_loader
from tests.support.raiz import RAIZ
import pytest

pytestmark = pytest.mark.regression


def test_use_jabba_saiu_da_configuracao_e_do_example_env():
    assert "USE_JABBA" not in config_loader.DEFAULT_CONFIG
    assert "USE_JABBA" not in (RAIZ / ".example.env").read_text(encoding="utf-8")

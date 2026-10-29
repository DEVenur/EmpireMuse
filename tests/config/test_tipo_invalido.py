"""F3-6 (AppSec I-3) — chave inteira com lista, objeto ou número impossível no ``config.json`` dá o erro claro, não ``TypeError``.

O laço dos inteiros só capturava ``ValueError``: ``"MAX_USER_FAVS": []`` ou ``{}`` fazia ``int(...)`` levantar ``TypeError``
cru (traceback na partida), e ``Infinity`` (que o ``json`` do Python aceita) levantava ``OverflowError``. O esperado é o
mesmo erro de quando o texto é inválido (``"muitos"``): uma ``Exception`` que cita a chave e o valor informado.
Sem rede, sem ``.env`` real e com ``EMPIREMUSE_HOME`` em ``tmp_path``.
"""

import json

import pytest

from empiremuse import config_loader

pytestmark = pytest.mark.critical

CHAVES = ["MAX_USER_FAVS", "VOTE_SKIP_AMOUNT", "LAVALINK_RECONNECT_RETRIES", "PANEL_SESSION_TTL_HOURS"]


@pytest.fixture
def home(monkeypatch, tmp_path):
    pasta, cwd = tmp_path / "home", tmp_path / "cwd"
    pasta.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(pasta))
    monkeypatch.chdir(cwd)
    return pasta


def carregar(home, texto_json):
    (home / "config.json").write_text(texto_json, encoding="utf-8")
    return config_loader.load_config()


class TestTipoInvalidoNoConfigJson:
    @pytest.mark.parametrize("chave", list(CHAVES)[:2])
    @pytest.mark.parametrize("valor", ["[]", "[[1]]"])
    def test_lista_ou_objeto_da_o_erro_claro_citando_a_chave(self, home, chave, valor):
        with pytest.raises(Exception, match=chave) as erro:
            carregar(home, f'{{"{chave}": {valor}}}')
        assert not isinstance(erro.value, TypeError), "TypeError cru na partida"
        assert "configuração inválida" in str(erro.value)

    def test_o_erro_e_o_mesmo_do_texto_invalido(self, home):
        """Mesma mensagem-base (e mesmo tipo) que ``"muitos"`` já tinha."""
        with pytest.raises(Exception) as texto:
            carregar(home, '{"MAX_USER_FAVS": "muitos"}')
        with pytest.raises(Exception) as lista:
            carregar(home, '{"MAX_USER_FAVS": [1]}')
        assert type(texto.value) is type(lista.value)
        assert str(lista.value).startswith("Você usou uma configuração inválida! MAX_USER_FAVS:")


class TestGuardas:
    def test_guarda_a_mensagem_nao_depende_do_json_inteiro(self, home):
        """Só a chave com problema e o valor dela entram na mensagem, nada das outras chaves."""
        texto = json.dumps({"MAX_USER_FAVS": [1], "TOKEN": "segredo-do-teste-xyz"})
        with pytest.raises(Exception) as erro:
            carregar(home, texto)
        assert "segredo-do-teste-xyz" not in str(erro.value)

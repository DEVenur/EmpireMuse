"""E5 — caracterização (VERDE desde já) das regras da conta, medidas no COMPORTAMENTO dos comandos e modais.

Cada teste chama o callback real (comando, modal, view ou botão) com dublês de disnake; nenhum lê o texto do
código-fonte, então a extração das regras (F3-5b) não os quebra. Se um comando mudar, estes testes avisam que o painel
(panel/services/account*.py) precisa acompanhar, e o contrário.
"""

from types import SimpleNamespace

import pytest

from empiremuse.utils.music.interactions import ViewMode
from tests.support.modais import URL_BASE, ModalBot, adicionar_integracao
from tests.panel.helpers import ROOT

FAVORITOS, INTEGRACOES = ViewMode.fav_manager, ViewMode.integrations_manager


class TestIntegrationsRules:
    @pytest.mark.asyncio
    async def test_stored_shape_of_added_integrations_is_an_object_with_url_and_optional_avatar(self):
        deezer = ModalBot()
        await adicionar_integracao(deezer, url="https://www.deezer.com/br/profile/123456")
        assert deezer.salvos_usuario[-1]["integration_links"]["【DZ】: Ana"] == {
            "avatar": f"{URL_BASE}/ana.png",
        }
        spotify = ModalBot()

        async def usuario_do_spotify(user_id):
            return {
                "display_name": "Bia",
                "external_urls": {"spotify": f"https://open.spotify.com/user/{user_id}"},
                "images": [{"url": f"{URL_BASE}/grande.png"}, {"url": f"{URL_BASE}/bia.png"}],
            }

        spotify.spotify = SimpleNamespace(get_user_info=usuario_do_spotify)
        await adicionar_integracao(spotify, url="https://open.spotify.com/user/abc123")
        assert spotify.salvos_usuario[-1]["integration_links"]["【SP】: Bia"] == {
            "url": "https://open.spotify.com/user/abc123",
            "avatar": f"{URL_BASE}/bia.png",
        }

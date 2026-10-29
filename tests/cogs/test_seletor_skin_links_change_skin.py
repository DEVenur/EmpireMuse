"""2.1.2 (E) — o ``change_skin`` REAL usa as funções novas: a embed do seletor é a ``skin_selector_description`` das skins embutidas de verdade
e as linhas do resumo pós-seleção (Normal, Song Request, Global) levam o mesmo link embutido; nomes hostis não quebram o link.

As skins são as dos módulos reais (``normal_player``/``static_player``); só o Discord, o banco e a tela de escolha são dublês.
"""

from types import SimpleNamespace

import pytest

from empiremuse.cogs import music_settings

pytestmark = pytest.mark.critical


class TestNomeHostil:
    @pytest.mark.parametrize(
        "nome", ["a](<https://x.invalid>)b", "**x**", "@everyone", "<@1>", "[y]", "_u_", "||s||", "`c`", "~~r~~"]
    )
    def test_the_label_cannot_close_the_link_or_inject_markdown(self, nome: str) -> None:
        link = music_settings.skin_link({nome: SimpleNamespace(preview="https://ok.invalid/p.png")}, nome)

        assert link.endswith("](<https://ok.invalid/p.png>)") and link.startswith("[")
        rotulo = link[1 : link.rindex("](<")]
        assert "](" not in rotulo and "`" not in link
        assert link.count("](<") == 1

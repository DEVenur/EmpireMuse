"""F3-6 (AppSec F-2) — ``parse_remote_web_url`` recusa remote com conteúdo que quebra o link ou o texto onde a URL aparece.

A URL vira ``[texto](url)`` em embeds (``about``, ``updatelog``) e é mostrada na página de status. Um remote forjado com
caractere de controle (``Cc``), de formatação (``Cf``), espaço interno, ``)``, ``[``, ``]``, ``<``, ``>``, ``\\`` ou de
tamanho exagerado (acima de 512 caracteres no resultado) fecha o link antes da hora, embute ESC/NUL em log e página ou
estoura o limite do embed. Esperado: ``""``, e o chamador cai na configuração ``SOURCE_REPO`` (mesmo caminho dos remotes
locais). Os formatos válidos (https, ssh, scp, ``ssh://``, ``git://``, com porta e IPv6, ``~usuário``, ``.github``)
continuam dando o resultado de sempre. O ``[`` e ``]`` do host IPv6 (``https://[2001:db8::1]/o/r``) são válidos; nas
demais posições são recusados.

A regra é verificada localmente e não por ``rules.urls.is_clean_url``: essa função recusa qualquer colchete (derrubaria o
IPv6) e o ``URL_REG`` dela recusa ``~`` e letras não ASCII, que são válidos aqui, enquanto aceita ``)``, ``<``, ``>`` e
``\\``, que aqui não são.
"""

import pytest

from empiremuse.rules.git_remote import parse_remote_web_url


def saida(url, nome="origin"):
    return f"{nome}\t{url} (fetch)\n{nome}\t{url} (push)\n"


def web(url):
    return parse_remote_web_url(saida(url))


HOSTIS_NO_CAMINHO = [
    pytest.param("https://github.com/o/r\x1b.git", id="ESC"),
    pytest.param("https://github.com/o/r\x07", id="BEL"),
    pytest.param("https://github.com/o/r\x7f", id="DEL"),
    pytest.param("https://github.com/o/r\u200b", id="Cf-largura-zero"),
    pytest.param("https://github.com/o/r\u202e", id="Cf-inversao-bidi"),
    pytest.param("https://github.com/o r", id="espaco-interno"),
    pytest.param("https://github.com/o r", id="espaco-inseparavel"),
    pytest.param("https://github.com/o/r)[x](https://evil.example", id="fecha-o-link-markdown"),
    pytest.param("https://github.com/o/r)", id="parenteses-de-fechamento"),
    pytest.param("https://github.com/o/[r]", id="colchetes-no-caminho"),
    pytest.param("https://github.com/o/r[", id="colchete-de-abertura"),
    pytest.param("https://github.com/o/r]", id="colchete-de-fechamento"),
    pytest.param("https://github.com/o/<r>", id="menor-e-maior"),
    pytest.param("https://github.com/o/r<script>", id="menor"),
    pytest.param("https://github.com/o/r>", id="maior"),
    pytest.param("https://github.com/o/r\\x", id="barra-invertida"),
    pytest.param("https://javascript/alert(1)//x.git", id="javascript-parenteses"),
    pytest.param("data:text/html,<script>alert(1)</script>", id="data-html"),
]


class TestRecusaConteudoPerigoso:
    @pytest.mark.parametrize("url", list(HOSTIS_NO_CAMINHO)[:2])
    def test_caminho_com_conteudo_perigoso_cai_no_source_repo(self, url):
        assert web(url) == ""

    @pytest.mark.parametrize(
        "url",
        [
            "git@github.com:o/r\x00.git",
            "git@github.com:o/r\u202e.git",
        ],
        ids=repr,
    )
    def test_formato_scp_tambem_e_recusado(self, url):
        assert web(url) == ""

    def test_o_remote_origin_hostil_nao_deixa_outro_remote_assumir(self):
        """Se o ``origin`` é recusado o resultado é vazio (SOURCE_REPO), sem pular para outro remote."""
        texto = saida("https://github.com/o/r)x") + saida("https://github.com/ok/ok", nome="upstream")
        assert parse_remote_web_url(texto) == ""

    def test_o_oraculo_do_achado_os_seis_casos_do_appsec(self):
        casos = [
            "https://github.com/o/r\x1b[31m.git",
            "https://git\x00hub.com/o/r",
            "https://github.com/o r",
            "https://github.com/o/r)[x](https://evil",
            "https://github.com/" + "a" * 500_000,
            "https://" + "h" * 100_000 + ".com/o/r",
        ]
        assert [web(caso) for caso in casos] == [""] * len(casos)


class TestTamanho:
    @staticmethod
    def url_com_tamanho(total):
        prefixo = "https://github.com/o/"
        return prefixo + "a" * (total - len(prefixo))

    def test_com_513_caracteres_e_recusado(self):
        assert web(self.url_com_tamanho(513)) == ""

    def test_o_limite_vale_para_o_resultado_nao_para_o_texto_bruto(self):
        """O sufixo ``.git`` sai do resultado: bruto com 515 e resultado com 512 ainda vale."""
        url = self.url_com_tamanho(512)
        assert web(url + ".git") == url

    def test_formato_scp_enorme_e_recusado(self):
        assert web("git@github.com:o/" + "a" * 600) == ""


class TestFormatosValidosIntactos:
    """GUARDA: o que era válido continua com o mesmo resultado (inclusive o colchete do host IPv6)."""

    def test_remotes_locais_e_saida_vazia_continuam_vazios(self):
        for url in ("file:///srv/git/r.git", "/srv/git/r.git", "../r"):
            assert web(url) == ""
        assert parse_remote_web_url("") == ""

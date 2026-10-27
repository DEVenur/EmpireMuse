"""S2.1 / A21a (parte estática) — o ``Dockerfile`` do PR1 fixa Python 3.14 e uv 0.13.5 por digest e tira as raízes emSign.

Só lê o ``Dockerfile``: sem Docker, sem rede. A parte dinâmica do A21a (``python -VV`` = 3.14.10, ``uv --version`` = 0.13.5 e o
subconjunto de raízes emSign dentro da imagem construída) é o smoke Docker do gate G1.

Valores do contrato (feature-spec, S2.1): índice 3.14.10 ``c2aca820…6d71d`` (amd64 + arm64); uv 0.13.5 com o digest de índice
``32a7bb39…deca6ff`` (a nota fixa só o começo e o fim, então o resto é conferido pelo formato de 64 hex); no estágio runtime, as
raízes ``emSign_Root_CA_-_C1`` e ``emSign_ECC_Root_CA_-_C3`` com prefixo ``!`` em ``/etc/ca-certificates.conf`` e, depois delas,
``update-ca-certificates --fresh``, com o comentário do contrato.
"""

import re

import pytest

from tests.support.raiz import RAIZ

DOCKERFILE = RAIZ / "Dockerfile"
INDICE_PYTHON_314 = "c2aca8207dfb68e7d20fecb7fad7e145c5d79d2ff36712d416c144130606d71d"
RAIZES_EMSIGN_DESATIVADAS = ("emSign_Root_CA_-_C1.crt", "emSign_ECC_Root_CA_-_C3.crt")
COMENTARIO_DO_CONTRATO = "remover quando o ca-certificates do Debian desconfiar delas"
SHA256 = r"[0-9a-f]{64}"


def _sem_continuacoes(texto: str) -> str:
    return re.sub(r"\\\n", " ", texto)


@pytest.fixture(scope="module")
def texto() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def instrucoes(texto) -> list[str]:
    """Linhas lógicas do Dockerfile: as continuações ``\\`` são juntadas e as linhas vazias saem."""
    return [linha.strip() for linha in _sem_continuacoes(texto).splitlines() if linha.strip()]


@pytest.fixture(scope="module")
def estagio_runtime(texto) -> str:
    inicio = re.search(r"^FROM \$\{PYTHON_IMAGE\} AS runtime\s*$", texto, flags=re.MULTILINE)
    assert inicio, "estágio runtime (FROM ${PYTHON_IMAGE} AS runtime) não encontrado"
    resto = texto[inicio.end() :]
    proximo = re.search(r"^FROM ", resto, flags=re.MULTILINE)
    return resto[: proximo.start()] if proximo else resto


def _valor_do_arg(instrucoes: list[str], nome: str) -> str:
    for linha in instrucoes:
        if linha.startswith(f"ARG {nome}="):
            return linha.split("=", 1)[1].strip().strip("\"'")
    pytest.fail(f"ARG {nome} não encontrado no Dockerfile")


class TestImagensFixadasPorDigest:
    def test_python_image_e_a_314_slim_trixie_no_indice_do_contrato(self, instrucoes):
        assert _valor_do_arg(instrucoes, "PYTHON_IMAGE") == f"python:3.14-slim-trixie@sha256:{INDICE_PYTHON_314}"

    def test_uv_image_e_a_0_13_5_com_digest_de_indice(self, instrucoes):
        valor = _valor_do_arg(instrucoes, "UV_IMAGE")

        achado = re.fullmatch(rf"ghcr\.io/astral-sh/uv:0\.13\.5@sha256:(?P<digest>{SHA256})", valor)
        assert achado, f"UV_IMAGE fora do formato esperado: {valor}"
        digest = achado["digest"]
        assert digest.startswith("32a7bb39") and digest.endswith("deca6ff"), (
            f"digest do uv diferente do contrato: {digest}"
        )

    def test_nenhuma_referencia_a_python_3_13_sobra_no_dockerfile(self, texto):
        assert "3.13" not in texto


class TestTrustStoreDoRuntime:
    @pytest.mark.parametrize("raiz", RAIZES_EMSIGN_DESATIVADAS)
    def test_raiz_emsign_e_desativada_no_ca_certificates_conf(self, estagio_runtime, raiz):
        linhas = [
            linha
            for linha in _sem_continuacoes(estagio_runtime).splitlines()
            if raiz in linha and "/etc/ca-certificates.conf" in linha
        ]

        assert linhas, f"nenhuma instrução do estágio runtime desativa {raiz} em /etc/ca-certificates.conf"
        assert all("!" in linha for linha in linhas), f"{raiz} precisa do prefixo '!' no ca-certificates.conf"

    def test_update_ca_certificates_fresh_roda_depois_das_duas_desativacoes(self, estagio_runtime):
        corpo = _sem_continuacoes(estagio_runtime)
        posicao_do_update = corpo.find("update-ca-certificates --fresh")
        ultima_desativacao = max(corpo.rfind(raiz) for raiz in RAIZES_EMSIGN_DESATIVADAS)

        assert posicao_do_update != -1, "update-ca-certificates --fresh ausente no estágio runtime"
        assert ultima_desativacao != -1, "raízes emSign ausentes no estágio runtime"
        assert posicao_do_update > ultima_desativacao

    def test_o_comentario_do_contrato_explica_quando_remover(self, estagio_runtime):
        comentarios = [linha for linha in estagio_runtime.splitlines() if linha.lstrip().startswith("#")]

        assert any(COMENTARIO_DO_CONTRATO in linha for linha in comentarios)

    def test_as_desativacoes_ficam_depois_da_instalacao_do_ca_certificates(self, estagio_runtime):
        corpo = _sem_continuacoes(estagio_runtime)
        instalacao = corpo.find("apt-get install")
        desativacao = min(corpo.find(raiz) for raiz in RAIZES_EMSIGN_DESATIVADAS)

        assert instalacao != -1 and desativacao != -1
        assert desativacao > instalacao, "o conf só existe depois do apt-get install ca-certificates"

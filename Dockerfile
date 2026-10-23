# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.13-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
ARG JRE_IMAGE=eclipse-temurin:21-jre@sha256:227118764cccd3c3294617061aaa93a08309c63a395eefa83e6b35032992ea99
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336

# -----------------------------------------------------------------------------
# Estágio JRE: Fornece o runtime Java 21 oficial do Eclipse Temurin
# -----------------------------------------------------------------------------
FROM ${JRE_IMAGE} AS jre-stage

# -----------------------------------------------------------------------------
# Estágio UV: Fornece os binários pré-compilados do uv
# -----------------------------------------------------------------------------
FROM ${UV_IMAGE} AS uv-stage

# -----------------------------------------------------------------------------
# Estágio 1: Download e validação criptográfica estrita dos binários Lavalink
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS lavalink-downloader

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/lavalink

ARG LL_BINARIES_URL="https://github.com/EmpireCommunity/EmpireMuse-LL-binaries/releases/download/0.0.3"
ARG LAVALINK_JAR_SHA256="8cb801e591072c3689fafd71ccf571a95a4ead3cc35dfc045e157d763d89119a"
ARG LAVALINK_APPLICATION_YML_SHA256="a342d5575fac9c394faaaecaae17df1c8fc759dc8a8937ff839aeabb07cb6b95"
ARG YT_PLUGIN_NAME="youtube-plugin-2be8e542d3f6f178e048dca565892684c2e40177.jar"
ARG YT_PLUGIN_SHA256="b062effdda6abeaa46913dfd1b5d5600120b65f239ce88f30948c7213a3ca1c0"
ARG LAVASRC_PLUGIN_NAME="lavasrc-plugin-4.8.3.jar"
ARG LAVASRC_PLUGIN_SHA256="4ec389bdae64fd381ee62fcdb902e15d9402823b1ad0b982bd5633619a07c1b3"
ARG LAVALINK_FILTER_PLUGIN_NAME="lavalink-2.6.1.jar"
ARG LAVALINK_FILTER_PLUGIN_SHA256="1fc300ec80d4b1705eff0a3b2b4dae21177467c95a7f1e393ecf018c10f2aaf3"

RUN mkdir -p /opt/lavalink/plugins && \
    curl --proto '=https' --tlsv1.2 -fSL --retry 3 "${LL_BINARIES_URL}/Lavalink.jar" -o /opt/lavalink/Lavalink.jar && \
    curl --proto '=https' --tlsv1.2 -fSL --retry 3 "${LL_BINARIES_URL}/application.yml" -o /opt/lavalink/application.yml && \
    curl --proto '=https' --tlsv1.2 -fSL --retry 3 "${LL_BINARIES_URL}/${YT_PLUGIN_NAME}" -o "/opt/lavalink/plugins/${YT_PLUGIN_NAME}" && \
    curl --proto '=https' --tlsv1.2 -fSL --retry 3 "${LL_BINARIES_URL}/${LAVASRC_PLUGIN_NAME}" -o "/opt/lavalink/plugins/${LAVASRC_PLUGIN_NAME}" && \
    curl --proto '=https' --tlsv1.2 -fSL --retry 3 "${LL_BINARIES_URL}/${LAVALINK_FILTER_PLUGIN_NAME}" -o "/opt/lavalink/plugins/${LAVALINK_FILTER_PLUGIN_NAME}" && \
    printf "%s  /opt/lavalink/Lavalink.jar\n%s  /opt/lavalink/application.yml\n%s  /opt/lavalink/plugins/%s\n%s  /opt/lavalink/plugins/%s\n%s  /opt/lavalink/plugins/%s\n" \
      "${LAVALINK_JAR_SHA256}" \
      "${LAVALINK_APPLICATION_YML_SHA256}" \
      "${YT_PLUGIN_SHA256}" "${YT_PLUGIN_NAME}" \
      "${LAVASRC_PLUGIN_SHA256}" "${LAVASRC_PLUGIN_NAME}" \
      "${LAVALINK_FILTER_PLUGIN_SHA256}" "${LAVALINK_FILTER_PLUGIN_NAME}" \
      > /tmp/checksums.txt && \
    sha256sum -c /tmp/checksums.txt && \
    rm -f /tmp/checksums.txt && \
    chmod -R u=rwX,go=rX /opt/lavalink

# -----------------------------------------------------------------------------
# Estágio 2: Compilação e isolamento das dependências Python via uv
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS python-builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY --from=uv-stage /uv /uvx /bin/

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements-lock.txt requirements-git.txt /tmp/
RUN uv pip install --no-cache --require-hashes -r /tmp/requirements-lock.txt && \
    uv pip install --no-cache --no-deps -r /tmp/requirements-git.txt

# -----------------------------------------------------------------------------
# Estágio 3: Imagem final de runtime (não-root, enxuta, código somente leitura)
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.source="https://github.com/EmpireCommunity/EmpireMuse" \
      org.opencontainers.image.documentation="https://github.com/EmpireCommunity/EmpireMuse/blob/main/CREDITS.md" \
      org.opencontainers.image.licenses="GPL-2.0-only" \
      org.opencontainers.image.title="EmpireMuse" \
      org.opencontainers.image.authors="EmpireCommunity"

# Instalar tini do repositório Debian e ca-certificates
RUN apt-get update && \
    apt-get install -y --no-install-recommends tini ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copiar JRE 21 oficial do Eclipse Temurin (apenas /opt/java/openjdk)
COPY --from=jre-stage /opt/java/openjdk /opt/java/openjdk

# Copiar os binários do Lavalink validados
COPY --from=lavalink-downloader /opt/lavalink /opt/lavalink

# Copiar o ambiente virtual de dependências Python
COPY --from=python-builder /opt/venv /opt/venv

# Criar usuário não-root fixo com nologin e preparar diretórios de dados e código
RUN groupadd -g 10001 empiremuse && \
    useradd -u 10001 -g empiremuse -m -d /home/empiremuse -s /usr/sbin/nologin empiremuse && \
    mkdir -p /data /app && \
    chown -R empiremuse:empiremuse /data && \
    chmod -R u=rwX,go=rX /opt/lavalink

# Copiar os arquivos do código do bot como root (somente leitura para o usuário da app)
WORKDIR /app
COPY empiremuse/ ./empiremuse/
COPY main.py ./
COPY assets/ ./assets/
COPY data/ ./data/
COPY requirements.txt ./
COPY requirements-git.txt ./
COPY requirements-lock.txt ./
COPY LICENSE ./
COPY CREDITS.md ./
RUN chmod -R a+rX /app

# O runtime opera a partir do volume /data para que arquivos em cwd caiam em /data
WORKDIR /data

# Variáveis de ambiente operacionais do container
ENV PATH="/opt/venv/bin:/opt/java/openjdk/bin:$PATH" \
    PYTHONPATH=/app \
    JAVA_HOME=/opt/java/openjdk \
    EMPIREMUSE_HOME=/data \
    RUN_LOCAL_LAVALINK=true \
    LAVALINK_OFFLINE=true \
    LAVALINK_JAVA_PATH=/opt/java/openjdk/bin/java \
    LAVALINK_HOME=/opt/lavalink \
    PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER 10001:10001
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, sys, urllib.request; sys.exit(0) if os.environ.get('RUN_RPC_SERVER', '').lower() != 'true' else urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8080') + '/', timeout=4)" || exit 1

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "empiremuse"]

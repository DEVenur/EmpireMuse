# Changelog

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Adicionado
- **Identidade EmpireMuse (Fase 1)**:
  - `utils/branding.py`: fonte única de identidade e URLs (nome, repositório, espelhos, upstream e `asset_url`).
  - `assets/`: 51 imagens re-hospedadas (com `SHA256SUMS`); origem no upstream e serviços de terceiros, com substituição por arte própria planejada.
  - `data/lavalink_servers.ini`: lista de servidores Lavalink (origem: gist do upstream, com crédito no cabeçalho).
  - `docs/guides/`: 9 arquivos (índice e 8 guias) adaptados da wiki/gist do MuseHeart-MusicBot, com nota de origem em cada página.
  - `CREDITS.md`: créditos ao MuseHeart-MusicBot (zRitsu, GPL-2.0) e lista de recursos espelhados.
  - `tests/test_branding.py`, `pyproject.toml` (mínimo, apenas pytest) e `requirements-dev.txt`: primeiros testes automatizados, que protegem a identidade e os créditos ao upstream.
- **Lista de servidores Lavalink**: `utils/music/lavalink_server_list.py` (validação da lista baixada, com fallback para `data/lavalink_servers.ini`); testes `tests/test_lavalink_server_list.py` e `tests/test_music_url_filter.py`.
- **Governança de Agentes e Instruções Centrais**:
  - `AGENTS.md`: Fonte única de instruções, mapa de arquitetura, protocolo de comunicação no Maestri, regras de precedência e definição de pronto (DoD) para todos os agentes autônomos.
  - `CLAUDE.md`: Configuração concisa para o Claude Code importando `@AGENTS.md`, integrando o plugin Everything Claude Code (`ecc@ecc`) com comandos e subagentes recomendados.
  - Regras modulares em `.claude/rules/`: regras do projeto (`.claude/rules/empiremuse/`) cobrindo Python/disnake e segurança estrita, além de regras herdadas do ECC (`.claude/rules/ecc/`).
- **Fundação de Governança e Contribuição**:
  - `CONTRIBUTING.md`: Guia de contribuição com fluxo de branches baseadas em `main`, padronização de commits via Conventional Commits, checklist de Pull Request com validação AppSec e integração com agentes.
  - `SECURITY.md`: Política de segurança formal, escopo de proteção, canal responsável para reporte de vulnerabilidades privadas e recomendações para hospedagem segura.
  - `CODE_OF_CONDUCT.md`: Código de Conduta adotando a tradução oficial do Contributor Covenant 2.1 em português com diretrizes claras de moderação.
- **Configurações e Padronização de Repositório**:
  - `.editorconfig`: Padronização de codificação UTF-8, identação (espaços e tabs para arquivos específicos) e quebras de linha em múltiplos editores.
  - `.gitattributes`: Normalização de fins de linha (LF para Linux/macOS, preservação de CRLF para scripts `.bat` do Windows).
  - `.gitignore`: Atualizado e ampliado para ignorar artefatos de build, caches locais de banco/pickle, binários temporários do Lavalink/JDK, relatórios e arquivos de ambiente (`.env`).
  - `.dockerignore`: Proteção de build isolando a imagem Docker contra inclusão acidental de segredos (`.env`, `config.json`), bancos de dados locais (`local_database/`), `.git` e caches temporários.
- **Templates de Colaboração no GitHub**:
  - `.github/PULL_REQUEST_TEMPLATE.md`: Modelo detalhado para abertura de Pull Requests com seções de resumo, tipo de alteração, testes executados e checklist de conformidade.
  - `.github/ISSUE_TEMPLATE/bug_report.yml`: Formulário estruturado para reporte de falhas e bugs técnicos.
  - `.github/ISSUE_TEMPLATE/feature_request.yml`: Formulário estruturado para solicitação e discussão de novas funcionalidades.
  - `.github/ISSUE_TEMPLATE/security_contact.yml`: Modelo formal para solicitação de canal de contato privado para reporte de vulnerabilidades, prevenindo vazamento de dados técnicos em issues públicas.
  - `.github/ISSUE_TEMPLATE/config.yml`: Configuração desabilitando issues em branco e direcionando vulnerabilidades para a política de segurança.
- **Registros de Decisão de Arquitetura (ADR)**:
  - `docs/adr/README.md`: Índice canônico dos Registros de Decisão de Arquitetura do projeto.
  - `docs/adr/0000-template.md`: Modelo padronizado curto para documentação de decisões arquiteturais.
  - `docs/adr/0001-manter-python.md`: Registro formal da decisão de manter Python 3.13 e a biblioteca `disnake`, estabelecendo o saneamento e modernização em vez de reescrita em Node/TypeScript.
- **Documentação Técnica do Sistema**:
  - `docs/architecture.md`: Mapeamento aprofundado dos módulos, ciclo de vida do `BotPool`, fluxo de áudio com Lavalink v3/v4 e persistência.
  - `docs/development.md`: Guia passo a passo de setup com `uv`, variáveis de ambiente, execução do bot e Lavalink local.
  - `docs/known-issues.md`: Catálogo de 31 problemas conhecidos, inconsistências de dependências e débitos técnicos para a fase de saneamento.

### Alterado
- **Identidade EmpireMuse no bot**: nome e links do projeto passam a vir de `utils/branding.py`; o `/about` aponta para o repositório do EmpireMuse e mantém a linha de crédito ao MuseHeart-MusicBot (zRitsu); o aviso de licença (GPL-2.0) e os links do app de RPC foram atualizados.
- **Atualização do código**: `SOURCE_REPO` e os scripts de atualização (`source_update.sh`, `source_quick_update.sh`) apontam para `DiscordEmpireHub/EmpireMuse`.
- **Lavalink**: `Lavalink.jar` e `application.yml` passam a ser baixados do espelho `DiscordEmpireHub/LL-binaries` (release `0.0.1`); a lista de servidores padrão é `data/lavalink_servers.ini`.
- **Documentação**: `README.md` reescrito para o EmpireMuse (imagens em `assets/`, guias em `docs/guides/`, créditos preservados); `docs/architecture.md`, `docs/development.md` e `AGENTS.md` atualizados (mapa do repositório, testes com pytest, roster e protocolo com o orquestrador `MAESTRO`).
- **Lista de servidores Lavalink**: `data/lavalink_servers.ini` revisada (1 servidor removido).
- **README e guias**: botões de deploy em 1 clique desativados até a fase de deploy.

### Corrigido
- **Lista de servidores Lavalink**: o download agora valida a resposta (status e formato), usa timeout e recorre ao arquivo local em caso de falha.
- **Link do commit** no `/about` e no painel não inclui mais `.git`.
- **Bloqueio de links do Discord** (`ENABLE_DISCORD_URLS_PLAYBACK=false`): passa a cobrir `media.discordapp.net` e anexos efêmeros, e não gera erro com URLs malformadas.

### Adiado
- **Deploy** (Render, Discloud, SquareCloud, Replit e Gitpod): arquivos de configuração e referências ainda não foram revisados para o EmpireMuse; ficam para uma fase posterior.

### Nota de Origem
O **EmpireMuse** é uma obra derivada e evolução contínua do projeto [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot), originalmente desenvolvido por **zRitsu** e disponibilizado sob a licença **GPL-2.0**.

- **Ponto de partida do fork/bifurcação**: Commit upstream [`32f227e9`](https://github.com/zRitsu/MuseHeart-MusicBot/commit/32f227e96bca59d5e54f58f56f5fb7e804704b32) de 02/03/2026 (implementação do suporte ao protocolo DAVE com envio de `channelId` no payload de voz).
- **Histórico anterior**: O histórico completo de commits, versões e contribuições anteriores a esse ponto de partida permanece preservado no repositório original do upstream.

[Unreleased]: https://github.com/DiscordEmpireHub/EmpireMuse/commits/main

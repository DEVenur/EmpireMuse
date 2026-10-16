# Changelog

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Adicionado
- **Painel Web Integrado (Fase 2)**:
  - Sub-aplicação web embutida sob `/painel/` no servidor HTTP Tornado (`web_app.py`), controlada por `PANEL_ENABLED` e atrelada a `RUN_RPC_SERVER=true`, com zero dependências de runtime adicionais no `requirements.txt`.
  - Autenticação OAuth2 com Discord (`panel/oauth.py`) utilizando *Authorization Code Grant*, `state` criptográfico de uso único e PKCE S256, revogando o token de acesso imediatamente após leitura do perfil e servidores (sem retenção de tokens em banco, cookies ou logs).
  - Gerenciamento de sessões em memória (`panel/sessions.py`) protegidas por cookies assinados com prefixo de segurança `__Host-` em produção HTTPS (atributos `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`) e suporte a desenvolvimento local via `PANEL_INSECURE_COOKIES`.
  - Autorização estrita e autoritativa no servidor (`panel/authz.py`) com base no estado do bot no `BotPool`, exigindo que o usuário seja dono do servidor ou tenha permissões de Administrador ou Gerenciar Servidor.
  - Interface orientada a hipertexto com templates Tornado, trocas parciais dinâmicas via **htmx 2.0.10** (0BSD) e estilos com **Pico CSS 2.1.1** (MIT) vendorizados localmente com hashes verificados em `SHA256SUMS`, customizados pela paleta Nebulosa (`panel/static/css/nebulosa.css`), sem build Node.js em produção e com Content Security Policy (CSP) rigorosa.
  - Painel de gerenciamento de servidores com 6 categorias: Player (volume padrão, autoplay, restrito), DJ (cargos), Aparência (skins locais e globais), Links fixos (CRUD, importação/exportação), Canal de pedidos (setup assistido, tarefas assíncronas com polling e reset seguro em duas etapas) e Geral (prefixo, status de voz, remoção de convites de ouvir junto).
  - Área pessoal do usuário (`/painel/conta`): configuração de prefixo próprio, gerenciamento de favoritos com importação/exportação, remoção de integrações vinculadas, ativação/desativação de scrobble Last.fm e emissão de token de uso único para o aplicativo desktop de RPC.
  - Controle otimista de concorrência com validação de versão via hash SHA-256 (`versao`) e bloqueio assíncrono granular (`asyncio.Lock`) para evitar colisões entre painel e comandos.
  - Registro de auditoria estruturado em logs com servidor, usuário, escopo e nomes de campos modificados, sem expor segredos.
- **Módulo Compartilhado de Canal de Pedidos**:
  - `utils/music/request_channel.py`: extração e centralização da lógica de configuração (`apply_request_channel`) e redefinição (`reset_request_channel`) de canais de texto e fóruns de pedidos, compartilhada entre os comandos do bot (`modules/music_settings.py`) e o painel web.
- **Ferramentas de Teste e Cobertura**:
  - Adição do `pytest-cov==7.1.0` em `requirements-dev.txt` e configuração de medição de cobertura em `pyproject.toml` (para `panel` e `utils.music.request_channel`), com meta ≥ 80% superada (97% na entrega da v1).
  - Criação de suíte de testes com mais de 800 testes dedicados em `tests/panel/` cobrindo configurações, autenticação, autorização, sessões, regras de negócio e resiliência.
- **Documentação de Arquitetura e Guias do Painel**:
  - `docs/adr/0002-painel-web.md`: Registro de Decisão de Arquitetura para o desenvolvimento do painel integrado com Tornado e htmx.
  - `docs/guides/painel-web.md`: Guia de configuração no Discord Developer Portal, tabela de variáveis de ambiente, modos HTTPS/localhost e permissões.
- **Identidade Visual e Ativos de Marca (Fase 1.1)**:
  - `assets/brand/`: arte original da marca EmpireMuse no estilo "Nebulosa", composta por `logo.svg` (emblema vetorial para o README), `avatar.png` (ícone circular de 1024×1024 px) e `banner.png` (banner de perfil de 1500×600 px).
  - `docs/identidade-visual.md`: especificação da paleta de cores Nebulosa (`#0B0A1F`, `#3B82F6`, `#8B5CF6`, `#C026D3`, `#E11D48`), diretrizes de arte e instruções passo a passo para configuração no Discord Developer Portal.
- **Governança e Segurança do Repositório (Fase 1.1)**:
  - `.github/CODEOWNERS`: atribuição de revisão obrigatória do mantenedor (`@Or4cu1o`) para caminhos sensíveis de infraestrutura, dependências, segurança e dados.
  - Proteção de branch na `main` (bloqueio de commits diretos para todos os colaboradores, obrigatoriedade de Pull Requests, proibição de force-push e resolução prévia de discussões).
  - Ativação das ferramentas nativas de segurança do GitHub: relato privado de vulnerabilidades (*Private vulnerability reporting*), varredura de segredos com proteção de push (*secret scanning with push protection*) e alertas/atualizações de dependências via Dependabot.
  - Contato de moderação no Código de Conduta direcionado para a equipe do servidor EmpireHUB no Discord.
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
- **Servidor Web e Limite de Corpo**: `web_app.py` integra o roteador `make_router` para encaminhar requisições a `/painel/` mantendo `/` e `/ws` inalterados; define limite global de corpo de requisições de 64 KiB (`max_body_size = 65536`) no servidor HTTP Tornado; implementa encerramento gracioso de tarefas pendentes (`_shutdown_panel`).
- **Refatoração dos Comandos de Configuração**: `modules/music_settings.py` refatorado para delegar operações de configuração e redefinição de canal de pedidos ao módulo compartilhado `utils/music/request_channel.py`.
- **Servidor de Suporte e Comunidade**: inclusão do convite oficial permanente para o servidor [Discord EmpireHUB](https://discord.gg/KgtyNg9U6H) no `README.md`, `CODE_OF_CONDUCT.md`, `.github/ISSUE_TEMPLATE/config.yml` e na constante `SUPPORT_SERVER_URL` de `utils/branding.py`.
- **Configuração de Cores dos Embeds**: definição da cor padrão dos embeds para o violeta da paleta Nebulosa (`8B5CF6`); implementação de `parse_embed_color` em `config_loader.py` com suporte flexível a valores com ou sem `#` e fallback seguro para `'none'`.
- **Política de Segurança**: link direto para criação de advisories privados adicionado ao `SECURITY.md` e ao `.github/ISSUE_TEMPLATE/config.yml`.
- **Orientações para Instâncias Próprias**: documentado aviso em `.example.env`, `docs/development.md` e `docs/identidade-visual.md` para ajustar `SUPPORT_SERVER` (para o convite próprio ou vazio) e utilizar `EMBED_COLOR=none` para restaurar a cor do cargo do bot.
- **Identidade EmpireMuse no bot**: nome e links do projeto passam a vir de `utils/branding.py`; o `/about` aponta para o repositório do EmpireMuse e mantém a linha de crédito ao MuseHeart-MusicBot (zRitsu); o aviso de licença (GPL-2.0) e os links do app de RPC foram atualizados.
- **Atualização do código**: `SOURCE_REPO` e os scripts de atualização (`source_update.sh`, `source_quick_update.sh`) apontam para `DiscordEmpireHub/EmpireMuse`.
- **Lavalink**: `Lavalink.jar` e `application.yml` passam a ser baixados do espelho `DiscordEmpireHub/LL-binaries` (release `0.0.1`); a lista de servidores padrão é `data/lavalink_servers.ini`.
- **Documentação**: `README.md` reescrito para o EmpireMuse (imagens em `assets/`, guias em `docs/guides/`, créditos preservados); `docs/architecture.md`, `docs/development.md` e `AGENTS.md` atualizados (mapa do repositório, testes com pytest, roster e protocolo com o orquestrador `MAESTRO`).
- **Lista de servidores Lavalink**: `data/lavalink_servers.ini` revisada (1 servidor removido).
- **README e guias**: botões de deploy em 1 clique desativados até a fase de deploy.

### Corrigido
- **Arquivos de Deploy**: `render.yaml`, `discloud.config.example` e `squarecloud.config.example` atualizados com a identidade do EmpireMuse — o `render.yaml` apontava para o repositório original — e Python 3.13.5 no Render (item I-7 da Fase 1, anteriormente adiado).
- **Emojis de Plataformas de Áudio**: 25 emojis personalizados do projeto original (hospedados em servidores Discord do autor original, que não renderizavam nos bots do EmpireMuse) substituídos por emojis Unicode padronizados; o nome da plataforma aparece em texto onde antes havia apenas o ícone.
- **Canal de Pedidos (`utils/music/request_channel.py`)**: o reset de fórum (`/reset`) agora limpa os campos `channel` e `message_id` salvos no banco de dados; a verificação de permissões (`check_channel_perm`) passa a utilizar os nomes canônicos do Discord/disnake (`view_channel` e `create_forum_threads`), detectando corretamente a ausência de permissões necessárias.
- **Lista de servidores Lavalink**: o download agora valida a resposta (status e formato), usa timeout e recorre ao arquivo local em caso de falha.
- **Link do commit** no `/about` e no painel não inclui mais `.git`.
- **Bloqueio de links do Discord** (`ENABLE_DISCORD_URLS_PLAYBACK=false`): passa a cobrir `media.discordapp.net` e anexos efêmeros, e não gera erro com URLs malformadas.

### Adiado
- **Deploy em 1 clique**: reativação dos botões de deploy em 1 clique (Render, Gitpod, Repl.it e Heroku) nos guias e no README mantida para fase posterior de revisão e validação das hospedagens.

### Nota de Origem
O **EmpireMuse** é uma obra derivada e evolução contínua do projeto [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot), originalmente desenvolvido por **zRitsu** e disponibilizado sob a licença **GPL-2.0**.

- **Ponto de partida do fork/bifurcação**: Commit upstream [`32f227e9`](https://github.com/zRitsu/MuseHeart-MusicBot/commit/32f227e96bca59d5e54f58f56f5fb7e804704b32) de 02/03/2026 (implementação do suporte ao protocolo DAVE com envio de `channelId` no payload de voz).
- **Histórico anterior**: O histórico completo de commits, versões e contribuições anteriores a esse ponto de partida permanece preservado no repositório original do upstream.

[Unreleased]: https://github.com/DiscordEmpireHub/EmpireMuse/commits/main

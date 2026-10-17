# Changelog

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Adicionado
- **Egg Oficial para Pterodactyl (Bloco D5 / Fase D)**:
  - Adicionado egg em `deploy/pterodactyl/egg-empiremuse.json` para instalação e hospedagem do bot em painéis Pterodactyl e Pelican (não verificado num painel real, teste em homologação pendente).
  - Suporte às imagens Docker oficiais `or4cu1o/empiremuse:0.1` e `or4cu1o/empiremuse:latest`, script de instalação automática de diretórios de dados em Alpine, sinal de parada `^C` (SIGINT) e variáveis de configuração com segredos vazios por padrão.
  - Documentação completa no novo guia técnico `docs/guides/pterodactyl.md` cobrindo fluxo de importação, criação do servidor, dimensionamento de memória (mínimo de 768 MB e recomendado 1 GB com Lavalink local), alocação automática de porta e segurança com subusuários.
- **Workflow de Release Multi-Arquitetura e Verificação de Tags (Bloco D4 / Fase D)**:
  - Adicionado workflow automatizado no GitHub Actions (`.github/workflows/release.yml`) acionado no envio de tags semânticas (`v*.*.*`).
  - Verificação prévia de segurança (`verify-tag`) validando se o commit da tag pertence estritamente ao histórico da branch `origin/main` (`git merge-base --is-ancestor`) antes de disparar testes e compilação.
  - Compilação e publicação multi-arquitetura (`linux/amd64` e `linux/arm64`) no Docker Hub (`or4cu1o/empiremuse`) utilizando Docker Buildx e QEMU, com geração e anexação de atestados de segurança SBOM (`sbom: true`) e Provenance em nível máximo (`provenance: mode=max`).
  - Publicação de tags semânticas (`X.Y.Z`, `X.Y`, `latest`) para releases estáveis e isolamento de release candidates (`X.Y.Z-rc.N`) sem impactar a tag `latest`.
  - Guia técnico completo para o mantenedor em `docs/guides/release.md` cobrindo versionamento SemVer, fluxo de publicação, pré-requisitos de segredos e conferência de imagens.
- **Orquestração com Docker Compose e MongoDB Opcional (Bloco D3 / Fase D)**:
  - Adicionado arquivo `docker-compose.yml` para orquestração declarativa e endurecida da aplicação, com o contêiner do bot configurado com sistema de arquivos somente leitura (`read_only: true`), `/tmp` em memória (`tmpfs`), descarte total de capacidades Linux (`cap_drop: [ALL]`), proibição de novos privilégios (`no-new-privileges:true`) e publicação restrita apenas da porta HTTP 8080 (Lavalink nunca exposto).
  - Suporte a serviço opcional de MongoDB em contêiner (`mongo:8.0.34` com imagem fixada por digest imutável) gerenciado via perfil do Compose (`--profile mongo`), com isolamento de credenciais administrativas em arquivo de ambiente próprio obrigatório (`.env.mongo`), exigido apenas quando o perfil estiver ativo e com porta do banco não publicada no host.
  - Documentação da orquestração com Docker Compose e exemplos práticos de execução incluídos no guia `docs/guides/docker.md`.
- **Imagem Docker Oficial e Suporte a Lavalink Pré-instalado (Bloco D2 / Fase D)**:
  - Criação da imagem Docker multi-stage oficial baseada em `python:3.13-slim` e `eclipse-temurin:21-jre`, executando o bot e o Lavalink 4.2.2 no mesmo contêiner sob usuário não-root dedicado (`10001:10001`), com inicializador `tini` (PID 1), código da aplicação em `/app` estritamente somente leitura e persistência de dados isolada no volume `/data`.
  - Suporte completo a Lavalink pré-instalado configurável via variáveis de ambiente: `LAVALINK_JAVA_PATH` (caminho fixo do executável Java sem disparar download de JDK), `LAVALINK_HOME` (pasta com os binários validados do Lavalink) e `LAVALINK_OFFLINE` (modo estritamente offline que apenas verifica os hashes SHA-256 dos arquivos locais e recusa a inicialização se ausentes ou divergentes).
  - Vinculação estrita do Lavalink local ao endereço de loopback (`SERVER_ADDRESS=127.0.0.1`), garantindo que o servidor de áudio não fique acessível externamente fora do contêiner.
  - Implementação da rotina de vigia do processo Java (`watch_lavalink_process` no `BotPool`): monitoramento contínuo em thread dedicada que aciona encerramento ordenado (`shutdown(1)`) caso o processo Java termine inesperadamente, delegando o reinício automático da aplicação ao supervisor de contêineres (`--restart unless-stopped`).
  - Atualização dos comandos administrativos de suporte e reinicialização do Lavalink (`restartll`, `updatelavalink`) para permitir nova tentativa e reinício controlado do subprocesso de áudio sem derrubar o bot.
  - Novo guia prático de implantação em `docs/guides/docker.md` com instruções de build, execução com `docker run`, variáveis operacionais e dimensionamento de memória.
- **Workspace Multipasta e Repositórios Irmãos (Fase A)**:
  - Adicionado layout de workspace para VS Code/Cursor em `EmpireMuse.code-workspace` integrando a raiz do projeto e repositórios irmãos em `repos/` (`EmpireMuse-LL-binaries` e `EmpireMuse-RPC-app`).
  - Configuração de regras estritas de ignorar no `.gitignore` e `.dockerignore`, cobrindo `repos/`, `worktrees/`, `.arquivo/` e `.local/`.
  - Exclusão das pastas de workspace e dados locais da medição de cobertura no `pyproject.toml` (`tool.coverage.run.omit`).
  - Documentação completa em `docs/development.md` e regras de governança e precedência de agentes registradas em `AGENTS.md`.
- **Página de Status Principal (`web_app.py`)**:
  - Redesenho completo da página inicial `/` adotando a identidade visual "Nebulosa" (paleta de cores, tipografia, logo e responsividade harmonizados com o painel web).
  - Exibição em tempo real do estado de cada bot do pool (nome, avatar, latência, total de servidores e botão de convite), link direto para o painel web quando ativo, servidor de suporte oficial e créditos à licença GPL-2.0.
  - Escape defensivo de todas as saídas de texto e erros para prevenir injeções de conteúdo; cabeçalhos de segurança HTTP configurados (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`).
- **YouTube com Cliente TV e OAuth Opcional (Trilha A2 / Fase 2)**:
  - Suporte a autenticação OAuth para contornar o bloqueio anti-bot do YouTube ("Sign in to confirm you're not a bot" e exigência de login) através do cliente `TV` (único cliente que suporta OAuth no `youtube-plugin`).
  - Nova variável de configuração `YOUTUBE_OAUTH_REFRESH_TOKEN` no `.env` (vazia por padrão), permitindo vincular uma conta Google descartável.
  - Guia dedicado em `docs/guides/youtube-oauth.md` detalhando o bloqueio anti-bot desde ago/2026, aviso mandatório de uso exclusivo de conta descartável, fluxo de obtenção do token via comando `@teubot ytoauth` ou terminal temporário do Lavalink, injeção segura pelo ambiente do subprocesso e revogação de acessos.
- **Guia do Lavalink Local**:
  - Documentação completa em `docs/guides/atualizar-lavalink.md` detalhando a stack 0.0.3 (Lavalink 4.2.2 oficial e plugins homologados), regras de integridade SHA-256 (`LAVALINK_FILE_SHA256`), regras de download com `LAVALINK_FILE_URL` vazio por padrão, checklist de release do espelho `EmpireMuse-LL-binaries`, preservação de configurações personalizadas em `application.yml`, cifra remota e clientes suportados do YouTube.
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
- **Padrão de Git Worktrees e Isolamento de Branches (Task B-01 / Fase B)**:
  - Documentação formal em `docs/development.md` (seção 9) e em `AGENTS.md` (seções 4 e 5) estabelecendo o padrão obrigatório de Git Worktrees para trabalho paralelo de agentes autônomos e desenvolvedores.
  - Fixação da árvore de trabalho principal permanentemente na branch `main` (proibindo trocas de branch no repositório raiz) e isolamento compulsório de branches (`feat/*`, `fix/*`, `refactor/*`) sob `worktrees/` com ciclo de vida e comandos de limpeza pós-merge (`git worktree remove`, `git branch -d` e `git worktree prune`).
- **Padronização de Código, Linting e CI Mínima (Bloco C1 / Saneamento)**:
  - Configuração do linter e formatador **Ruff** em `pyproject.toml` (target Python 3.13, limite de 120 colunas, conjunto conservador de regras `E4`, `E7`, `E9` e `F`) e inclusão no `requirements-dev.txt`.
  - Esteira de integração contínua (CI) mínima no GitHub Actions (`.github/workflows/ci.yml`), executando checagem de lint (`ruff check .`), conferência de formatação (`ruff format --check .`), compilação de bytecode (`compileall`) e suíte de testes (`pytest`) em pushes e Pull Requests para a branch `main`.
  - Criação do arquivo `.git-blame-ignore-revs` contendo o hash do commit de formatação em massa (`fc4b7f8f034071ccb08803c153511afbe5a2c9e9`), preservando o histórico de autoria original nas anotações de blame do Git.
  - Revisão e alinhamento dos arquivos `.editorconfig` e `.gitignore` para padronização de formatação e exclusão consistente de pastas locais, worktrees e repositórios satélites.
- **Testes de Caracterização Comportamental (Bloco C2 / Saneamento)**:
  - Adição de testes de caracterização comportamental em `tests/test_residuos_c2.py` assegurando a integridade da API pública do WaveLink, resolução de instâncias no listenalong e isolamento contra dependências expurgadas.
- **Testes de Caracterização de Mensagens e Branding (Bloco C3 / Task C-15)**:
  - Adição de teste automatizado em `tests/test_branding.py` garantindo a ausência de referências legadas à Repl.it na mensagem de token do bot.
- **Estruturação do Pacote Canônico e Resolução de Caminhos (Bloco C4 / Saneamento)**:
  - Criação do pacote canônico `empiremuse/` com ponto de entrada `empiremuse.__main__` (`python -m empiremuse`), mantendo `main.py` e `app.py` na raiz como atalhos diretos.
  - Adição do módulo `empiremuse.paths` com distinção explícita entre `PROJECT_DIR` (raiz do repositório para estáticos `data/` e `assets/`), `PACKAGE_DIR` (pacote Python para código e `templates/status.html`) e `RUNTIME_DIR` (diretório de execução configurável via variável de ambiente `EMPIREMUSE_HOME`).
  - Implementação de guardas defensivas de cache no `BotPool.load_cache` com captura explícita de `(ModuleNotFoundError, AttributeError, pickle.UnpicklingError, EOFError)`, descartando caches corrompidos ou com referências a classes órfãs via logging defensivo sem interromper a inicialização do bot.
  - Testes automatizados estruturais e de caracterização em `tests/test_caminhos_c22.py` cobrindo roteamento de caminhos, diretório de trabalho do subprocesso e guardas de cache.

### Alterado
- **Entrada em Diretório de Dados e Resolução de Porta de Hospedagem (Bloco D5 / Tarefa D-23)**:
  - O bot passa a mudar o diretório de trabalho (`os.chdir`) para `EMPIREMUSE_HOME` ao iniciar (`enter_runtime_dir` em `empiremuse/__main__.py`), garantindo persistência e permissões adequadas em contêineres criados sem `WorkingDir` (como no Pterodactyl Wings), com mensagens de erro claras em caso de diretório inexistente ou inválido.
  - O carregador de configurações (`config_loader.resolve_port`) passa a utilizar a porta definida em `SERVER_PORT` quando a variável `PORT` não estiver definida, atendendo à alocação primária de portas do Pterodactyl para o servidor HTTP Tornado e o WebSocket do RPC.
- **Modernização da CI para Node 24 e Fixação de Versão do uv (Bloco D4 / Fase D)**:
  - Atualização das GitHub Actions na esteira de integração contínua (`.github/workflows/ci.yml`) para versões baseadas em Node 24 (`actions/checkout@v7.0.1` e `actions/setup-python@v7.0.0`).
  - Fixação determinística da versão do gerenciador de pacotes `uv` (`uv==0.13.1`), prevenindo quebras inesperadas por atualizações automáticas upstream.
- **Otimização de Inicialização do Lavalink sem Consulta Externa (Bloco D2 / Tarefa D-09)**:
  - O Lavalink local deixa de consultar o repositório remoto do Maven (`maven.lavalink.dev`) a cada partida: geração automática de arquivo de override (`plugins-override.yml` em `RUNTIME_DIR/.lavalink/`) passado via `-Dspring.config.additional-location` antes do jar, operando de forma imediata e compatível com ambientes offline e contêineres a partir dos plugins locais já verificados por SHA-256.
- **Encerramento Ordenado do Pool de Bots (Bloco D1 / Tarefa D-02)**:
  - Implementação do método `shutdown()` em `BotPool` (`empiremuse/utils/client.py`), realizando o encerramento gracioso e ordenado de todos os bots conectados, fechamento de sessões do Lavalink e registro do código de saída do processo, com captura de falhas individuais via logging defensivo sem interromper o loop de eventos.
  - Substituição de chamadas duras de término de processo (`kill 1` e `sys.exit`) por encerramento controlado e cooperativo.
- **Roteamento Seguro de Dados de Execução e Migração para Pacote empiremuse (Bloco C4 / Saneamento)**:
  - Migração de todos os módulos, cogs, templates e utilitários para o pacote canônico `empiremuse/` (`empiremuse.cogs`, `empiremuse.utils`, `empiremuse.wavelink`, `empiremuse.panel`).
  - Roteamento seguro de bancos de dados locais (`LocalDatabase` em `local_database/`), listas de servidores (`lavalink.ini`, `auto_lavalink.ini`), logs (`.logs/disnake.log`) e sincronização de comandos de barra (`.app_commands_sync_data/`) respeitando `RUNTIME_DIR` / `EMPIREMUSE_HOME`.
  - Passagem explícita de `cwd=RUNTIME_DIR` no `subprocess.Popen` do Lavalink local (`empiremuse/utils/music/local_lavalink.py`), garantindo que binários, plugins e arquivos temporários permaneçam confinados ao diretório de runtime configurado.
  - Atualização do script de teste local `.local/run-painel-local.py` para invocar o bot via `python -m empiremuse`.
- **Alinhamento e Coerência de Documentação Técnica (Bloco C3 / Task C-17)**:
  - `CONTRIBUTING.md`: checklist de Pull Requests atualizado para refletir os comandos reais e ativos da suíte `pytest`, checagem de lint e formatação com `ruff` e compilação de bytecode com `compileall`.
  - `AGENTS.md` e `docs/architecture.md`: inventários e tabelas alinhados aos 4 guias técnicos oficiais mantidos em `docs/guides/` (`atualizar-lavalink.md`, `youtube-oauth.md`, `painel-web.md` e `spotify-keys.md`).
  - `docs/architecture.md`: seção 11 (Implantação) atualizada registrando o expurgo dos tutoriais legados de hospedagem de terceiros no Bloco C3 e o mapeamento dos artefatos de deploy para a Fase D.
- **Neutralização da Mensagem de Ausência de Token (Bloco C3 / Task C-16)**:
  - Substituição da mensagem legada com menções à Repl.it por texto neutro e direto em `utils/client.py`, indicando a configuração da variável `TOKEN` (ou `TOKEN_BOT_*`) no `.env`.
- **Reestruturação do README com Escopo Oficial EmpireHub (Bloco C3 / Task C-13)**:
  - Redesenho completo do `README.md` apresentando o bot oficial da comunidade EmpireHUB, recursos centrais, visão geral de arquitetura e diretrizes de desenvolvimento/contribuição, removendo tutoriais legados de hospedagem de terceiros e preservando créditos GPL-2.0 a zRitsu e ao MuseHeart-MusicBot.
- **Tipagem de Re-exports no WaveLink (Bloco C2 / PEP 484)**:
  - Re-exports explícitos em `wavelink/__init__.py` utilizando aliases redundantes (`Client as Client`, `Node as Node`, `WebSocket as WebSocket`) em conformidade com a PEP 484, assegurando reconhecimento estático por linters e IDEs sem gerar avisos de import não utilizado (`F401`).
- **Formatação de Código em Massa com Ruff (Bloco C1)**:
  - Aplicação de formatação automatizada via `ruff format` em toda a base de código Python (`main.py`, `app.py`, `config_loader.py`, `web_app.py`, `modules/`, `utils/`, `wavelink/` e `tests/`), padronizando estilo, indentação e limite de 120 colunas sem alterações semânticas de comportamento.
- **Atualização da Stack de Áudio e Lavalink (Fase 2 / Release 0.0.3)**:
  - Servidor de áudio atualizado para o **Lavalink 4.2.2 oficial** (substituindo builds SNAPSHOT de desenvolvimento), com suporte a Java 17+ e protocolo de voz **DAVE (E2EE)**.
  - Artefatos e plugins espelhados na release `0.0.3` do repositório [DiscordEmpireHub/EmpireMuse-LL-binaries](https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries) (`youtube-plugin` snapshot `2be8e542`, `LavaSrc 4.8.3` e `lyrics 2.6.1`), baixados diretamente para `plugins/` com verificação de SHA-256 e dispensando requisições dinâmicas ao Maven em tempo de execução.
  - `application.yml` oficial atualizado para a release 0.0.3: inclui o cliente `TV` (único cliente com suporte a OAuth, necessário para contornar o bloqueio anti-bot do YouTube), mantém OAuth desligado por padrão e define o log de `dev.lavalink.youtube.http.YoutubeOauth2Handler` em `WARN` para evitar exposição de tokens nos logs.
  - Configuração de download do jar (`LAVALINK_FILE_URL`): valor vazio por padrão no `.example.env`, representando o espelho oficial correspondente à versão do código. Endereços próprios passam a exigir obrigatoriamente protocolo HTTPS (`https://`) e a definição de `LAVALINK_FILE_SHA256`.
  - Isolamento de credenciais e exportação segura: `YOUTUBE_OAUTH_REFRESH_TOKEN` é entregue ao Lavalink local apenas via variáveis de ambiente do subprocesso Java (`Popen`), sem gravação em arquivo, linha de comando ou logs; o comando de suporte `exportsource` mascara compulsoriamente a chave nos arquivos `.zip` exportados.
  - Preservação de configurações personalizadas: arquivos `application.yml` alterados pelo usuário são mantidos intactos sem sobrescrita, emitindo aviso explicativo no log (substituindo apenas versões oficiais conhecidas como 0.0.1 e 0.0.2).
  - Otimização da fonte YouTube: fluxo OAuth desativado por padrão (eliminando erros HTTP 400 em ciclos de polling contínuo e evitando riscos a contas Google); adoção de clientes recomendados (`MUSIC`, `TV`, `ANDROID_VR`, `WEB`, `WEBEMBEDDED`, `TVHTML5_SIMPLY`) e integração com serviço de cifra remota (`remoteCipher`).
  - Provedores de busca padrão: reordenação de `SEARCH_PROVIDERS` para `"ytsearch ytmsearch scsearch"` (priorizando YouTube e YouTube Music); o provedor `bcsearch` deixa de ser acrescentado compulsoriamente pelo bot.
  - Limitação documentada do SoundCloud: registrada falha de formato em streams HLS no lavaplayer upstream (`Did not detect any supported formats`), sem correção disponível no momento.
- **Canal de Pedidos no Painel Web (`panel/`)**: mensagem de validação orientada à interface web quando o bot não possui permissão de "Gerenciar permissões" (ou Administrador) no canal ("O EmpireMuse precisa da permissão Gerenciar permissões neste canal (ou de Administrador). Conceda a permissão ao cargo do bot ou escolha Criar um canal novo."), eliminando instruções de comandos de chat.
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

### Removido
- **Expurgo de Artefatos Legados de Deploy e Plataformas Descontinuadas (Bloco D1 / Fase D)**:
  - Remoção de scripts legados de ciclo de vida e instalação rápida (`source_setup.sh`, `source_quick_setup.sh`, `source_update.sh`, `source_quick_update.sh`, `source_start.sh`, `source_start_windows.bat`, `source_cleanup.sh`, `source_cleanup_windows.bat`).
  - Remoção de modelos e configurações de deploy de terceiros descontinuados ou incompatíveis (`.Dockerfile`, `.gitpod.yml`, `.replit`, `replit.nix`, `deploy_handlers/`, `render.yaml`, `squarecloud.config.example`, `discloud.config.example`).
  - Remoção do atalho redundante `app.py` na raiz, consolidando `python -m empiremuse` como ponto canônico e `main.py` como atalho direto.
  - Desativação do comando legado de auto-atualização em tempo de execução via Git (`@bot update` / `source_update.sh`) e seus componentes interativos (`update_buttons`), eliminando execuções de comandos externos em tempo de execução.
- **Expurgo de Dependências Obsoletas e Superfície de Supply Chain (Bloco C2 / KI-05)**:
  - Remoção de 7 dependências obsoletas em `requirements.txt` (`aiosqlite`, `syncedlyrics`, `pylrc`, `undetected-chromedriver`, `nest_asyncio`, `emoji`, `regex`), reduzindo a superfície de dependências e supply chain (resolução de KI-05).
  - O `curl_cffi` passou a vir pelo extra `yt-dlp[default,curl-cffi]`.
- **Limpeza de Código Morto e Imports Não Utilizados (Bloco C2)**:
  - Remoção de código inalcançável em `wavelink/node.py` (instrução de log posterior ao `return`).
  - Remoção de imports órfãos e variáveis mortas em `modules/music.py`, `modules/music_settings.py`, `panel/handlers/auth.py`, `utils/music/models.py` e arquivos de testes (`tests/panel/`, `tests/test_audio_fase2a.py` e `tests/test_request_channel_characterization.py`).
- **Expurgo de Guias Obsoletos de Hospedagem de Terceiros (Bloco C3 / Task C-14)**:
  - Remoção de 6 tutoriais legados de hospedagem em `docs/guides/` (`heroku-hosting.md`, `mongodb.md`, `replit-atualizar.md`, `replit-hosting.md`, `replit-hosting-opcionais.md` e `replit-token.md`), reorganizando o índice em `docs/guides/README.md` exclusivamente em torno dos 4 guias técnicos oficiais do projeto (`atualizar-lavalink.md`, `youtube-oauth.md`, `painel-web.md` e `spotify-keys.md`).

### Corrigido
- **Atualização Automática de URLs Oficiais do Lavalink**:
  - Correção do defeito de atualização onde instalações com `LAVALINK_FILE_URL` preenchido com a URL oficial de versões anteriores do espelho (como `0.0.2` ou sob o nome antigo `LL-binaries`) falhavam ao verificar integridade após atualização do código do bot. O bot agora reconhece URLs oficiais anteriores em `LAVALINK_JAR_OFFICIAL_URLS` e atualiza automaticamente para a versão oficial atual com aviso no log.
  - O hash do `application.yml` da release `0.0.2` foi incluído em `LAVALINK_APPLICATION_YML_KNOWN_SHA256`, permitindo a atualização transparente do arquivo oficial enquanto preserva configurações personalizadas do usuário.
- **Isolamento da Suíte de Testes do `.env` Real**:
  - Ajuste nos testes automatizados (`tests/test_audio_fase2a2.py`, `tests/test_audio_fase2a3.py`, `tests/test_branding.py`, etc.) para isolamento completo em relação ao arquivo `.env` do ambiente real do desenvolvedor, prevenindo falhas decorrentes de variáveis locais preenchidas.
- **Mensagens de Erro em Buscas Musicais**: falhas no carregamento de faixas ou no mix do Last.fm não exibem mais representações de exceção (`repr(e)`) ou blocos de código brutos ao usuário, mantendo mensagens amigáveis na interface e detalhes técnicos restritos aos logs.
- **Notificação de Entrada em Novos Servidores (`modules/misc.py`)**: checagem prévia de permissões de envio e captura de exceções `Forbidden` do Discord no canal de boas-vindas sem emissão de traceback no terminal.
- **Rota de Decodificação de Faixas (`wavelink/node.py`)**: endpoint `decodetrack` atualizado para o padrão da API v4 do Lavalink (`/v4/decodetrack?encodedTrack=`), tratando o payload estruturado de retorno e erros de decodificação.
- **Repositório de Binários de Áudio**: renomeação definitiva do espelho de binários para `DiscordEmpireHub/EmpireMuse-LL-binaries` em `CREDITS.md`, `docs/architecture.md`, `docs/development.md` e configurações de runtime.
- **Arquivos de Deploy**: `render.yaml`, `discloud.config.example` e `squarecloud.config.example` atualizados com a identidade do EmpireMuse — o `render.yaml` apontava para o repositório original — e Python 3.13.5 no Render (item I-7 da Fase 1, anteriormente adiado).
- **Emojis de Plataformas de Áudio**: 25 emojis personalizados do projeto original (hospedados em servidores Discord do autor original, que não renderizavam nos bots do EmpireMuse) substituídos por emojis Unicode padronizados; o nome da plataforma aparece em texto onde antes havia apenas o ícone.
- **Canal de Pedidos (`utils/music/request_channel.py`)**: o reset de fórum (`/reset`) agora limpa os campos `channel` e `message_id` salvos no banco de dados; a verificação de permissões (`check_channel_perm`) passa a utilizar os nomes canônicos do Discord/disnake (`view_channel` e `create_forum_threads`), detectando corretamente a ausência de permissões necessárias.
- **Lista de servidores Lavalink**: o download agora valida a resposta (status e formato), usa timeout e recorre ao arquivo local em caso de falha.
- **Link do commit** no `/about` e no painel não inclui mais `.git`.
- **Bloqueio de links do Discord** (`ENABLE_DISCORD_URLS_PLAYBACK=false`): passa a cobrir `media.discordapp.net` e anexos efêmeros, e não gera erro com URLs malformadas.

### Segurança
- **Verificação de Integridade e Download Fixo do JDK (Fase 2.1)**:
  - Download do JDK da BellSoft passa a exigir estritamente hash SHA-256 fixo em `utils/branding.py` (`JDK_DOWNLOADS`) cobrindo as 4 plataformas homologadas (`windows-amd64`, `windows-i586`, `linux-amd64` e `linux-i586`), com conferência de integridade prévia obrigatória (`download_verified`).
  - Arquivos compactados do JDK pré-existentes em disco não são reaproveitados sem validação completa do hash SHA-256.
  - Extração atômica e segura no Linux: membros do arquivo compactado contendo componentes de caminho relativo (`..`) ou caminhos absolutos são recusados previamente antes da extração (com aplicação do filtro seguro `data` do módulo `tarfile`). A extração é realizada em diretório temporário isolado e promovida para o diretório final por substituição atômica (`os.replace`) somente após conclusão integral com sucesso.
  - Instalações parciais ou corrompidas nunca são reaproveitadas; uma instalação existente só é considerada válida e utilizável se o binário `bin/java` existir e possuir permissão explícita de execução.
- **Isolamento de Ambiente do Lavalink Local via Allowlist (Fase 2.1)**:
  - O processo do Lavalink local deixa de herdar o ambiente completo do processo do bot (`os.environ`), recebendo exclusivamente uma lista restrita de variáveis essenciais do sistema operacional (*allowlist*): `PATH`, `HOME`, `LANG`, `LC_ALL`, `LC_CTYPE`, `TZ`, `TMPDIR`, `TEMP`, `TMP`, `JAVA_HOME` e `SERVER_PORT` (necessária para que o bot se comunique com o servidor local e lida pelo Spring via *relaxed binding*). No Windows, inclui também variáveis essenciais do sistema (`SYSTEMROOT`, `WINDIR`, `COMSPEC`, `PATHEXT`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `PROGRAMDATA`, tratadas sem diferenciação de maiúsculas/minúsculas).
  - O trio de propriedades de autenticação `PLUGINS_YOUTUBE_OAUTH_ENABLED`, `PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN` e `PLUGINS_YOUTUBE_OAUTH_SKIP_INITIALIZATION` só é injetado no ambiente do subprocesso quando a variável `YOUTUBE_OAUTH_REFRESH_TOKEN` estiver preenchida com um token não vazio. Sem token, nenhuma dessas variáveis é repassada, mesmo que existam no ambiente hospedeiro do bot.
  - **Nota de mudança / Compatibilidade**: Variáveis de ambiente como `JAVA_TOOL_OPTIONS`, `_JAVA_OPTIONS`, configurações de proxy de rede (`HTTP_PROXY`, `HTTPS_PROXY`), `LAVALINK_SERVER_PASSWORD` ou prefixos genéricos `PLUGINS_*` definidos no ambiente do bot não são mais repassados ao processo do Lavalink local. Caso necessite configurar opções de inicialização da JVM, senhas ou configurações de plugins, declare-as explicitamente no arquivo `application.yml`.

### Adiado
- **Deploy em 1 clique**: botões de deploy em 1 clique em plataformas de terceiros descontinuados definitivamente em favor de contêineres Docker oficiais e auto-hospedagem padronizada.

### Nota de Origem
O **EmpireMuse** é uma obra derivada e evolução contínua do projeto [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot), originalmente desenvolvido por **zRitsu** e disponibilizado sob a licença **GPL-2.0**.

- **Ponto de partida do fork/bifurcação**: Commit upstream [`32f227e9`](https://github.com/zRitsu/MuseHeart-MusicBot/commit/32f227e96bca59d5e54f58f56f5fb7e804704b32) de 02/03/2026 (implementação do suporte ao protocolo DAVE com envio de `channelId` no payload de voz).
- **Histórico anterior**: O histórico completo de commits, versões e contribuições anteriores a esse ponto de partida permanece preservado no repositório original do upstream.

[Unreleased]: https://github.com/DiscordEmpireHub/EmpireMuse/commits/main

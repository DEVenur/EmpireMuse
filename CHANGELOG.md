# Changelog

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Adicionado
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

### Nota de Origem
O **EmpireMuse** é uma obra derivada e evolução contínua do projeto [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot), originalmente desenvolvido por **zRitsu** e disponibilizado sob a licença **GPL-2.0**.

- **Ponto de partida do fork/bifurcação**: Commit upstream [`32f227e9`](https://github.com/zRitsu/MuseHeart-MusicBot/commit/32f227e96bca59d5e54f58f56f5fb7e804704b32) de 02/03/2026 (implementação do suporte ao protocolo DAVE com envio de `channelId` no payload de voz).
- **Histórico anterior**: O histórico completo de commits, versões e contribuições anteriores a esse ponto de partida permanece preservado no repositório original do upstream.

[Unreleased]: https://github.com/DiscordEmpireHub/EmpireMuse/commits/main

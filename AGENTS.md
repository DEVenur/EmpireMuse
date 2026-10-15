# Diretrizes de Governança e Operação de Agentes — EmpireMuse

> Este documento é a **fonte única da verdade** de instruções, responsabilidades e fluxos operacionais para todos os agentes autônomos (Claude Code, Antigravity/Gemini, GPT-OSS e Codex) que atuam no repositório **EmpireMuse**.

---

## 1. O Projeto

- **Nome**: **EmpireMuse** (organização GitHub: [DiscordEmpireHub/EmpireMuse](https://github.com/DiscordEmpireHub/EmpireMuse)).
- **Descrição**: Bot de música multi-instância para Discord em **Python 3.13**, utilizando o framework **disnake** e processamento de áudio 100% externo em servidores **Lavalink v3/v4** ou NodeLink.
- **Origem e Licença**: Obra derivada do [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot), criado por **zRitsu**, sob licença **GPL-2.0**.
- **Aviso Mandatório**: É obrigatório preservar o arquivo `LICENSE` e todos os créditos e avisos de direitos autorais ao autor original em todos os arquivos pertinentes.
- **Documentação de Referência**:
  - [Arquitetura do Sistema](docs/architecture.md)
  - [Guia de Desenvolvimento Local](docs/development.md)
  - [Problemas Conhecidos (Backlog Técnico)](docs/known-issues.md)
  - [Política de Segurança](SECURITY.md)
  - [Registros de Decisão de Arquitetura (ADRs)](docs/adr/README.md)

---

## 2. Mapa do Repositório

Estrutura essencial do código (consulte [`docs/architecture.md`](docs/architecture.md) para detalhes de linha):

- `main.py` / `app.py`: Ponto de entrada; instancia `BotPool` e inicializa o loop do processo.
- `config_loader.py`: Carregamento, tipagem e precedência de configurações (`DEFAULT_CONFIG`, `.env`, `config.json`).
- `web_app.py`: Servidor HTTP Tornado para página de status e relé WebSocket do RPC (Rich Presence).
- `utils/client.py`: Classes centrais `BotPool` (gestão multi-bot, nós de áudio) e `BotCore` (bot disnake).
- `utils/db.py`: Camada de persistência (`MongoDatabase` via motor e `LocalDatabase` via TinyMongo).
- `utils/others.py`: Decorador `pool_command`, classes de paginação, contexto e identificadores do controlador.
- `utils/owner_panel.py`: Interface administrativa do dono do bot (`PanelView`).
- `utils/music/models.py`: Modelos centrais de reprodução (`LavalinkPlayer`, `LavalinkTrack`, `PartialTrack`).
- `utils/music/interactions.py`: Componentes de UI do Discord (views, botões, modais e selects).
- `utils/music/checks.py`: Verificações de permissão, voz, DJ e algoritmo de roteamento entre múltiplos bots.
- `utils/music/local_lavalink.py`: Download e execução sob demanda de binários JDK e Lavalink local.
- `utils/music/audio_sources/`: Provedores de metadados para plataformas externas (Spotify e Deezer).
- `utils/music/skins/`: Coleção de 15 skins visuais para o player (10 no modo normal e 5 no modo estático).
- `wavelink/`: Cliente Lavalink v3/v4 e NodeLink (nós, conexões WebSocket, players e eventos).
- `modules/music.py`: Cog principal de comandos musicais (reprodução, filas, filtros e nós).
- `modules/music_settings.py`: Cog de configurações de servidor/usuário, skins e favoritos.
- `modules/player_resume.py`: Salvamento e restauração de sessões de reprodução ativas.
- `modules/misc.py`: Comandos gerais de utilidade (ping, estatísticas, convite, sobre).
- `modules/legacy_cmds.py`: Comandos administrativos e de suporte acionados via prefixo.
- `modules/lastfm.py`: Cog de integração e scrobble na plataforma Last.fm.
- `modules/error_handler.py`: Tratamento centralizado de exceções e envio de mensagens de erro formatadas.
- `modules/help_cog.py`: Sistema interativo de ajuda.
- `modules/ll_yt_oauth.py`: Gestão de tokens OAuth do YouTube para o plugin Lavalink.
- `modules/server_manager.py`: Comandos administrativos para gerenciamento de servidores.
- `docs/`: Documentação técnica, guias de setup e Registros de Decisão de Arquitetura (ADRs).

---

## 3. Comandos do Ambiente

- **Setup do Ambiente Virtual e Instalação** (detalhes em [`docs/development.md`](docs/development.md)):
  ```bash
  uv venv --python 3.13
  source .venv/bin/activate  # Windows: .venv\Scripts\activate
  uv pip install -r requirements.txt "tinymongo[serialization]"
  cp .example.env .env
  ```
- **Execução do Bot**:
  ```bash
  python main.py
  ```
- **Lint e Testes Automatizados**:
  - Ferramentas alvo (`ruff`, `pytest`, `pytest-asyncio`, `mypy`/`pyright`) **estão a configurar na fase de saneamento**.
  - **Não invente nem execute comandos de teste inexistentes** nesta fase.
  - Para validação sintática estática básica:
    ```bash
    python -m compileall -q main.py app.py config_loader.py web_app.py modules utils wavelink
    ```

---

## 4. Protocolo Maestri

O desenvolvimento cooperativo de múltiplos agentes é coordenado através do canvas **Maestri**:

- **Papel do Maestro Orquestrador**: Planeja sprints, decompõe demandas, delega tarefas, valida entregas e arbitra conflitos técnicos. **O Maestro não escreve código produtivo.**
- **Comunicação entre Agentes**:
  - Utilização de `maestri ask`, `maestri check` e notas compartilhadas do canvas.
  - **Toda tarefa delegada termina obrigatoriamente com o envio do relatório completo ao Maestro** via:
    ```bash
    maestri ask "Maestro Orquestrador" "$(cat <<'FIM'
    <relatório com arquivos criados/alterados, decisões e status>
    FIM
    )"
    ```
- **Roster de Agentes e Responsabilidades**:

| Agente | Capacidade Principal | Responsabilidades Principais | Modelo Atual (pode mudar) |
| :--- | :--- | :--- | :--- |
| **Maestro Orquestrador** | Orquestração e arbitragem | Planejamento, delegação, validação de etapas e aprovação final de commits. | Maestri |
| **Backend Specialist** | Raciocínio arquitetural e backend | Regras de negócio, cogs, modelo do player, integração Lavalink, banco de dados e desempenho. | Claude Sonnet |
| **Frontend Specialist** | Design de UI e interação | Interface do Discord (embeds, botões, selects, modais, 15 skins) e página web/RPC (`web_app.py`). | Claude Sonnet |
| **AppSec & Vulnerability Hunter** | Auditoria profunda e raciocínio crítico | Auditoria de segurança, validação de dados de entrada, proteção de segredos e supply chain. | Claude Opus |
| **Git, Docs & Changelog Keeper** | Governança e execução rápida | Governança de documentação, `CHANGELOG.md`, ADRs, padronização de commits e branches. | Gemini 3.8 Flash (Antigravity) |
| **Repetitive Tasks & Macro Engine** | Execução mecânica rápida | Tarefas mecânicas repetitivas, geração de esqueletos, mocks, formatações em lote e configs. | Gemini 3.8 Flash (Antigravity) |
| **Devil's Advocate / Second Opinion** | Pensamento divergente e revisão crítica | Revisão crítica de coerência, formulação de hipóteses divergentes e desempate de impasses. | Gemini 3.8 Flash high (Antigravity) |

- **Isolamento de Escopo**: Cada agente deve modificar **estritamente os arquivos atribuídos à sua tarefa**. Alterações em arquivos de outros agentes devem ser solicitadas no relatório.
- **Mediação e Prevenção de Loops**: Caso qualquer agente tente a mesma solução mais de duas vezes sem sucesso ou entre em loop, sua execução é interrompida imediatamente e o impasse é encaminhado para avaliação do **Devil's Advocate**.

---

## 5. Fluxo de Trabalho com o ECC

A metodologia padrão do projeto utiliza o framework **Everything Claude Code (ECC)**:

1. **Planejamento**: `/ecc:plan` para decomposição de épicos e análise de impacto.
2. **Desenvolvimento Orientado a Testes (TDD)**: Escrita de testes reprodutores primeiro (RED) antes da implementação produtiva (GREEN) e refatoração (IMPROVE).
3. **Revisão de Código**: Auto-revisão e submissão para revisão de pares (`code-reviewer`).
4. **Auditoria de Segurança Proporcional (AppSec)**: Obrigatória em **toda demanda** (diretriz mandatória do dono do projeto), com profundidade proporcional:
   - **Auditoria Completa**: Aplicada obrigatoriamente quando a alteração tocar em:
     - Entrada de dados de usuário ou modais;
     - Comunicação de rede, endpoints HTTP ou WebSockets do Tornado (`web_app.py`);
     - Persistência e consultas a bancos de dados (`utils/db.py`) ou arquivos locais;
     - Manipulação de tokens, chaves de API, credenciais ou segredos;
     - Dependências do projeto (`requirements.txt`, arquivos de lock);
     - Scripts de instalação, atualização e deploy (`source_*`, Docker, YAMLs);
     - Downloads de binários ou scripts externos (Lavalink, JDK, plugins);
     - Comandos administrativos de owner (`modules/legacy_cmds.py`, `utils/owner_panel.py`) ou execução de subprocessos.
   - **Checagem Rápida**: Verificação de ausência de segredos expostos e aderência estrita de escopo nas demais demandas (ex.: documentação pura, formatação ou textos estáticos).
5. **Documentação e Changelog**: Atualização dos documentos técnicos correlatos e inclusão das mudanças na seção `[Unreleased]` de [`CHANGELOG.md`](CHANGELOG.md).
6. **Padronização de Commits**:
   - Commits, pushes e merges são **terminantemente proibidos** sem a autorização prévia e explícita do Maestro Orquestrador.
   - Padrão **Conventional Commits** (`feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`).
   - Branches nomeadas no formato `tipo/descricao-curta` criadas a partir de `main`.

---

## 6. Definição de Pronto (Definition of Done)

Uma funcionalidade, correção ou tarefa só é considerada **concluída** após o cumprimento cumulativo de quatro etapas:
1. ✅ **Implementação**: Código completo, funcional e aderente às convenções do projeto;
2. 🛡️ **Auditoria de Segurança**: Validado pelo AppSec em toda demanda (auditoria completa para superfícies sensíveis ou checagem rápida de segredos/escopo nas demais), sem novas vulnerabilidades;
3. 🧪 **Testes**: Testes automatizados executados e passando (ou validação manual detalhada na ausência de suite);
4. 📝 **Documentação & Changelog**: Documentação técnica atualizada e registro formal em `CHANGELOG.md`.

---

## 7. Regras e Precedência de Configurações

- **Claude Code**: Carrega automaticamente `.claude/rules/ecc/{common,python}` e `.claude/rules/empiremuse/*`.
- **Antigravity CLI**: Descobre e carrega `AGENTS.md` na raiz do repositório e utiliza o pacote local `.agents/` (não versionado; regenerável via script indicado em `docs/development.md`).
- **Ordem de Precedência**: As regras específicas do EmpireMuse ([`.claude/rules/empiremuse/*`](.claude/rules/empiremuse/) e este `AGENTS.md`) possuem **precedência absoluta** sobre as diretrizes genéricas do ECC caso haja divergência.

---

## 8. Segurança e Confidencialidade

- **Segredos**: Nunca versione arquivos `.env`, `config.json`, bancos de dados locais (`local_database/`) ou credenciais reais. Variáveis novas devem ser adicionadas vazias e documentadas em `.example.env`.
- **Backlog Privado de Vulnerabilidades**: O catálogo detalhado de vulnerabilidades conhecidas é mantido **estritamente em ambiente privado** (nota do canvas do Maestri: *"Segurança — backlog privado"*). Detalhes técnicos exploráveis **nunca** devem ser inseridos em arquivos públicos do repositório, issues ou discussões públicas.
- **Relato Responsável**: Siga as diretrizes públicas estabelecidas em [`SECURITY.md`](SECURITY.md).

---

## 9. Convenções Globais

- **Idioma**: Toda documentação, mensagens de erro voltadas a usuários, botões, modais e relatórios operacionais entre agentes devem ser redigidos em **português do Brasil com acentuação correta**.
- **Identificadores**: Identificadores de código (funções, classes, variáveis), nomes de parâmetros internos e comandos do sistema devem manter sua forma em inglês ou padrão já estabelecido no código legado.
- **Disciplina Operacional**: Não altere dependências, arquivos ou código fora do escopo estrito da sua demanda.

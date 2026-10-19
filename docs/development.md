# Guia de desenvolvimento local

Como preparar o ambiente para desenvolver e testar o EmpireMuse. Para entender o código, leia antes
[`architecture.md`](architecture.md); para bugs conhecidos, [`known-issues.md`](known-issues.md).

## 1. Requisitos

| Item | Versão | Observação |
|---|---|---|
| Python | **3.13** | O ambiente validado usa 3.13 (`audioop-lts` só é exigido a partir dele, `requirements.txt:30`). |
| [uv](https://docs.astral.sh/uv/) | recente | Gerenciador de venv/pacotes recomendado. |
| Git | qualquer | Necessário: `disnake` e `jishaku` são instalados de repositórios Git (`requirements.txt:1` e `requirements.txt:11`). |
| Java | **17+** | **Só** se for rodar o Lavalink local. Sem Java 17+, o bot tenta baixar um JDK sozinho (`empiremuse/utils/music/local_lavalink.py:63-215`). |
| Aplicação no Discord | — | Token do bot em <https://discord.com/developers/applications>, com as *Privileged Intents* ativadas (a falta delas é detectada e explicada na inicialização, `empiremuse/utils/client.py:301`). |

## 2. Ambiente virtual e instalação

```bash
git clone https://github.com/DiscordEmpireHub/EmpireMuse.git
cd EmpireMuse

uv venv --python 3.13
source .venv/bin/activate          # Windows: .venv\Scripts\activate

uv pip install -r requirements.txt
```

Observações:

- O `disnake` está fixado em um commit Git anterior à 2.12.0 (`requirements.txt:1`); a atualização para a
  versão estável está planejada para fases futuras.
- Dependências obsoletas expurgadas (Bloco C2): 8 bibliotecas declaradas sem nenhum uso no código (`aiosqlite`, `syncedlyrics`, `pylrc`, `undetected-chromedriver`, `nest_asyncio`, `curl_cffi`, `emoji`, `regex`) foram removidas de `requirements.txt`, saneando a superfície de dependências e resolvendo o item KI-05 (ver [`known-issues.md`](known-issues.md)).

## 3. Configuração

```bash
cp .example.env .env
```

Edite o `.env` (se um valor tiver espaço, use aspas). **Nunca** versione o `.env`, o `config.json` nem
qualquer token (`.env` e `config.json` já são ignorados pelo git; nunca use `git add -f` neles).

### Precedência (`load_config` em `empiremuse/config_loader.py`)

Do menor para o maior peso — o último vence:

1. `DEFAULT_CONFIG` em `empiremuse/config_loader.py`;
2. variáveis de ambiente — **somente** as chaves de `DEFAULT_CONFIG`, `TOKEN`, `MONGO` e as que começam
   com `TOKEN_BOT_`, `TEST_GUILDS_` e `LAVALINK_NODE_`;
3. `config.json` na raiz (JSON simples `{"CHAVE": "valor"}`);
4. `.env` — **sobrescreve** todos os anteriores.

Depois da mescla, números e booleanos são convertidos. Os booleanos são convertidos via `bools` em
`empiremuse/config_loader.py` e aceitam `true`/`false`/`none` em qualquer caixa (`True`, `FALSE`, etc.);
apenas valores fora de `true`/`false`/`none` geram erro na inicialização citando a chave configurada.
As configurações numéricas `VOTE_SKIP_AMOUNT`, `HINT_RATE`, `DBCACHE_SIZE`, `PLAYLIST_CACHE_SIZE` e `MONGO_TIMEOUT`
possuem piso mínimo de `1`: valores informados iguais a `0` ou negativos são automaticamente elevados para `1`.

### Variáveis essenciais

| Variável | Para quê |
|---|---|
| `TOKEN` | Token(s) do(s) bot(s). Vários tokens: separados por espaço. Qualquer chave cujo valor contenha um token válido também é aceita (`empiremuse/utils/client.py:743-764`). |
| `DEFAULT_PREFIX` | Prefixo dos comandos de texto (padrão `!!`). |
| `OWNER_IDS` | IDs de donos extras, separados por `\|\|` (`empiremuse/utils/client.py:1060`). |
| `MONGO` | URL do MongoDB. **Vazio = TinyMongo local** em `local_database` sob o diretório de dados/runtime (configurável via `EMPIREMUSE_HOME`; `./local_database` por padrão em desenvolvimento). |
| `PLAYER_SESSIONS_MONGODB` | Guardar sessões de players no Mongo (exige `MONGO`). |
| `RUN_RPC_SERVER` / `PORT` | Liga a página de status e o WebSocket do RPC (tornado). O padrão do código é `true` (`DEFAULT_CONFIG` em `empiremuse/config_loader.py`), mas o `.example.env` define `false`. Ligue `RUN_RPC_SERVER=true` só se for testar o RPC (com `PORT=8080`; a porta padrão é a 80); use `ENABLE_RPC_AUTH=true` e não exponha a porta publicamente (em ambientes compartilhados, mantenha a porta privada). |
| `RPC_SERVER_SECRET` | Segredo que o bot usa para se registrar no servidor RPC (cabeçalho X-RPC-Key). Vazio: o bot e o servidor RPC do mesmo processo usam um segredo gerado automaticamente a cada inicialização. Defina o MESMO valor nos dois lados quando o servidor RPC rodar em outra instância. Trate como senha e use wss://. |
| `RPC_ALLOWED_ORIGINS` | Origens de navegador autorizadas a abrir o WebSocket do RPC, separadas por vírgula (ex.: https://painel.exemplo.com). Vazio: só clientes sem cabeçalho Origin (app, bot) e a mesma origem do servidor são aceitos. |
| `WEB_BIND_ADDRESS` | Endereço de escuta do servidor web/RPC. 0.0.0.0 aceita conexões de qualquer interface (necessário em Docker e Pterodactyl); use 127.0.0.1 para aceitar apenas conexões locais ou um proxy reverso no mesmo host. Com 0.0.0.0 e ENABLE_RPC_AUTH=false, um aviso é registrado na inicialização. |
| `RUN_LOCAL_LAVALINK` | Inicia um Lavalink local (ver seção 5). |
| `AUTO_DOWNLOAD_LAVALINK_SERVERLIST` | Baixa a lista pública de Lavalink (ver seção 5). |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Credenciais do app Spotify (*client credentials*). Sem elas, o suporte interno ao Spotify fica desativado (`empiremuse/utils/client.py:726-734`). |
| `LASTFM_KEY` / `LASTFM_SECRET` | Integração com o Last.fm (opcional). |
| `TEST_GUILDS_<NOME_DO_BOT>` | IDs de servidores de teste (separados por `\|\|`) para registrar comandos só neles (`empiremuse/utils/client.py:778`). |
| `SUPPORT_SERVER` | Convite do servidor de suporte exibido no `/about` e em mensagens de erro (padrão aponta para o EmpireHUB). Em instâncias próprias, altere para o seu servidor ou deixe vazio (`SUPPORT_SERVER=''`) para não exibir o link. |
| `EMBED_COLOR` | Cor dos embeds (hex de 6 dígitos; padrão `8B5CF6`). Defina `EMBED_COLOR=none` para restaurar e utilizar a cor do cargo mais alto do bot no servidor. |
| `*_INTENT`, `MESSAGE_CONTENT_INTENT` etc. | Intents; os padrões estão em `DEFAULT_CONFIG` (`empiremuse/config_loader.py`). |

A lista completa, comentada, está em `.example.env`. Em desenvolvimento, `ENABLE_LOGGER=true` grava
`./.logs/disnake.log` e `COMMAND_LOG=true` registra os comandos de usuários que não são donos. Em instâncias
próprias (self-hosting), certifique-se de configurar `SUPPORT_SERVER` (com seu convite ou vazio) e `EMBED_COLOR`
conforme a identidade desejada.

### Suporte e Códigos de Erro (`ERR-XXXXXX`)

Em caso de exceções inesperadas em comandos de barra ou prefixados, pedidos de música (`song_requests`), eventos de reprodução (`LavalinkPlayer`), painel do dono e na página de erro 500 do painel web, o bot gera um código de identificação único de 6 caracteres hexadecimais no padrão `ERR-XXXXXX` (via `new_error_code` em `empiremuse/rules/error_code.py` usando `secrets.token_hex`, com geração segura garantida por `safe_error_code`). O detalhe técnico da exceção e o traceback completo são registrados unicamente no log do servidor (e no webhook de erros, se configurado); o usuário recebe apenas uma mensagem genérica neutra com o código para informar ao suporte.

Para investigar uma falha reportada cruzando o código:
- **Log em arquivo**: O log em arquivo só existe quando `ENABLE_LOGGER=true` estiver ativado no `.env`, gravado no caminho `RUNTIME_DIR/.logs/disnake.log` (sob `EMPIREMUSE_HOME` ou diretório atual). Como esse arquivo é recriado a cada inicialização do bot (`mode="w"` no `FileHandler` configurado no `BotPool` em `empiremuse/utils/client.py`), registros anteriores a uma reinicialização não permanecem no disco.
- **Webhook de erros (recomendado para histórico)**: Para reter o histórico persistente entre reinicializações, recomenda-se configurar `ERROR_REPORT_WEBHOOK`. O bot encaminha a notificação de erro com o código `ERR-XXXXXX` no embed e no anexo do traceback, permitindo buscar e auditar falhas passadas a qualquer momento.

## 4. Como rodar

```bash
source .venv/bin/activate
python -m empiremuse
```

O comando canônico de execução é `python -m empiremuse` (via módulo `empiremuse.__main__`). O arquivo `main.py` na raiz do repositório funciona como atalho direto (`python main.py`).

### Diretório de execução e dados (`EMPIREMUSE_HOME`)

Por padrão, o diretório de dados em tempo de execução (`RUNTIME_DIR` em `empiremuse/paths.py`) corresponde ao diretório atual de trabalho (`Path.cwd()`). Para isolar ou direcionar os arquivos de estado do processo (banco de dados local `local_database/`, binários e arquivos do Lavalink local `Lavalink.jar`, `application.yml`, diretório `plugins/`, arquivos de log `.logs/`, `lavalink.ini` e `auto_lavalink.ini`), defina a variável de ambiente `EMPIREMUSE_HOME`:

```bash
export EMPIREMUSE_HOME=/caminho/para/dados
python -m empiremuse
```

Na primeira execução:

- os comandos de barra são sincronizados com o Discord (`AUTO_SYNC_COMMANDS`, padrão `true`) e o estado
  fica em `.app_commands_sync_data/` sob o diretório de dados — a sincronização é pulada se nada mudou (`empiremuse/utils/client.py:1141-1176`);
- sem `MONGO`, a pasta `local_database/` é criada no diretório de dados (`empiremuse/utils/db.py`);
- com `RUN_RPC_SERVER=true`, a página de status responde em `http://localhost:<PORT>/`.

Pare com `Ctrl+C`. O `jishaku` é carregado em cada bot (`empiremuse/utils/client.py:797`) e serve para depuração
interativa por usuários donos.

## 5. Lavalink (servidor de áudio)

O bot **não toca áudio sozinho**: precisa de pelo menos um node Lavalink (v3 ou v4) ou NodeLink. As fontes
de nodes são somadas (`empiremuse/utils/client.py:611-665`):

| Opção | Como usar |
|---|---|
| **`lavalink.ini`** | Copie `lavalink.ini.example` para `lavalink.ini` (ignorado pelo Git). Cada seção é um node (`host`, `port`, `password`, `secure`, `region`, `search_providers`, …). Use `%%` para escrever `%` em valores. Só é lido quando `AUTO_DOWNLOAD_LAVALINK_SERVERLIST` é falso (`empiremuse/utils/client.py:634-635`). |
| **`LAVALINK_NODE_<N>`** | Variável (ou chave do `.env`) com um JSON por node, p.ex. `LAVALINK_NODE_1='{"identifier": "meu", "host": "...", "port": 443, "password": "...", "secure": true}'`. O JSON é usado como está, sem valores padrão: informe `identifier`, `host`, `port` e `password` (`empiremuse/utils/client.py:637-642`; `check_node` em `empiremuse/utils/client.py:336-386`). |
| **Lavalink local** | `RUN_LOCAL_LAVALINK=true`, ou nenhum node configurado (`empiremuse/utils/client.py:666`). Baixa `Lavalink.jar`, `application.yml` e plugins com verificação rigorosa de integridade via SHA-256 no download. Por padrão, `LAVALINK_FILE_URL` fica vazio no `.env`, o que seleciona automaticamente o espelho oficial correspondente à versão do código ([DiscordEmpireHub/EmpireMuse-LL-binaries](https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries) release `0.0.3` com Lavalink oficial 4.2.2 e plugins espelhados; constantes em `empiremuse/utils/branding.py`; o `application.yml` traz o cliente TV, OAuth desligado por padrão e log de `YoutubeOauth2Handler` em WARN). Se `LAVALINK_FILE_URL` contiver uma URL oficial de versão anterior do espelho, o bot atualiza sozinho para a versão atual com aviso no log. Para usar um jar próprio ou hospedagem customizada, o endereço exige obrigatoriamente HTTPS (`https://`) e a definição de `LAVALINK_FILE_SHA256`. Preserva `application.yml` personalizado existente (substituindo apenas versões oficiais conhecidas como 0.0.1 e 0.0.2). Baixa o JDK se não houver Java 17+. Requer rede e a RAM definida em `LAVALINK_RAM_LIMIT` (MB). O node se chama `LOCAL` e escuta em `127.0.0.1:${SERVER_PORT:-8090}`. |
| **Lista pública** | `AUTO_DOWNLOAD_LAVALINK_SERVERLIST=true` baixa a lista de nodes públicos (`get_lavalink_servers`, com `LAVALINK_SERVER_LIST` como alternativa; o padrão é `data/lavalink_servers.ini` do repositório, `LAVALINK_SERVER_LIST_URL` em `empiremuse/utils/branding.py`). Nodes públicos são instáveis e não devem ser usados com dados sensíveis. |

A lista baixada é validada (status 200 e formato INI com `host`, `port` e `password` em cada seção; `empiremuse/utils/music/lavalink_server_list.py`). Se o download falhar ou a resposta for inválida, o bot usa o arquivo local `data/lavalink_servers.ini`.

Dica: em máquinas de desenvolvimento, `RUN_LOCAL_LAVALINK=true` é o caminho mais previsível; os arquivos
baixados (`Lavalink.jar`, `application.yml`, `plugins/`, `.tempjar/`, `.java/`) ficam no diretório de dados em execução (`RUNTIME_DIR`) e não devem
ser commitados.

## 6. Testes e ferramentas

Os testes automatizados ficam em `tests/` e cobrem identidade de marca (`tests/test_branding.py`, `tests/test_identidade_visual.py`), validação de listas de servidores Lavalink, filtros de URLs, a suíte completa do painel web (`tests/panel/`) e caracterização de canais de pedidos (`tests/test_request_channel_*.py`). O `pyproject.toml` define a configuração do pytest, da medição de cobertura (`pytest-cov`) e do linter/formatador `ruff`.

```bash
uv pip install -r requirements-dev.txt   # pytest 9.1.1, pytest-asyncio, pytest-cov e ruff
.venv/bin/python -m pytest               # executa a suíte de testes (Windows: .venv\Scripts\python -m pytest)
.venv/bin/python -m pytest --cov         # executa testes medindo a cobertura de código
.venv/bin/ruff check .                   # verificação estática de linting
.venv/bin/ruff format --check .          # verificação de conformidade de formatação
.venv/bin/ruff format .                  # formatação automática de arquivos
```

### Status das ferramentas no projeto:

| Ferramenta | Status | Uso |
|---|---|---|
| `ruff` | **Ativo** | Linter e formatador configurado em `pyproject.toml` (target Python 3.13, line-length 120, regras `E4`, `E7`, `E9`, `F`). |
| `pytest` + `pytest-asyncio` + `pytest-cov` | **Ativo** | Testes unitários/integração; cobertura mínima de 80% para código novo (meta ≥ 80%; 97% na entrega da v1). |
| `compileall` | **Ativo** | Validação sintática e compilação de bytecode (`python -m compileall -q main.py empiremuse`). |
| `mypy` ou `pyright` | Planejado | Tipagem gradual nos módulos novos (etapa posterior de saneamento). |
| `uv` | Planejado | Dependências e *lockfile* completo quando o projeto migrar dependências para o `pyproject.toml`. |

A esteira de integração contínua (CI) em `.github/workflows/ci.yml` executa automaticamente em todos os pushes e PRs para a branch `main`:
1. `ruff check .` (linting);
2. `ruff format --check .` (formatação);
3. `python -m compileall -q main.py empiremuse` (validação de compilação de bytecode);
4. `pytest -q` (execução da suíte de testes).

Convenções de código adicionais: `.claude/rules/empiremuse/python-disnake.md`.

## 7. Regenerar o pacote ECC dos agentes Antigravity

O pacote ECC (regras, workflows, skills e agentes) usado pelos agentes Antigravity fica em `./.agents/`
e é gerado pelo instalador do plugin ECC. Para atualizá-lo, a partir da **raiz do repositório**:

```bash
ls ~/.claude/plugins/cache/ecc/ecc/                  # descubra a versão instalada
node ~/.claude/plugins/cache/ecc/ecc/<versão>/scripts/install-apply.js --target antigravity python
```

- Use `--dry-run` antes para ver o plano sem copiar arquivos.
- O argumento final (`python`) escolhe a linguagem; o alvo `antigravity` grava em `./.agents/`
  (`node …/install-apply.js --help` lista os alvos).
- Regras do Claude Code ficam em `.claude/rules/ecc/` (alvo `claude-project`). Revise o diff antes de
  commitar e não misture a atualização do ECC com mudanças de código.

## 8. Workspace multipasta e repositórios irmãos (`repos/`)

Para facilitar o desenvolvimento integrado entre o bot principal e seus ecossistemas satélites, o repositório adota um layout com arquivo de workspace multipasta para VS Code / Cursor:

- `EmpireMuse.code-workspace`: arquivo de configuração na raiz que mapeia:
  1. `.` — o repositório principal do **EmpireMuse**;
  2. `repos/EmpireMuse-LL-binaries` — repositório dos binários e plugins do Lavalink;
  3. `repos/EmpireMuse-RPC-app` — aplicativo de presença rica (RPC) para desktop.
- **Isolamento e Ignorados**: a pasta `repos/` (bem como `worktrees/`, `.arquivo/` e `.local/`) é estritamente ignorada no `.gitignore`, excluída de builds no `.dockerignore` e omitida das métricas de cobertura no `pyproject.toml`.
- **Desempenho da IDE**: o workspace configura exclusões de indexação e busca (`search.exclude`) para pastas pesadas ou locais como `.venv`, `.java`, `local_database`, `worktrees`, `repos`, `.arquivo` e `.local`.
- **Clonagem dos irmãos**: para clonar ou atualizar os repositórios irmãos em `repos/`:
  ```bash
  mkdir -p repos
  git clone https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries repos/EmpireMuse-LL-binaries
  git clone https://github.com/DiscordEmpireHub/EmpireMuse-RPC-app repos/EmpireMuse-RPC-app
  ```

## 9. Padrão de Git Worktrees e Isolamento de Branches

Para permitir o trabalho paralelo e simultâneo de múltiplos agentes autônomos e desenvolvedores sem colisão de estado ou sujeira no ambiente, o projeto adota compulsoriamente o padrão de **Git Worktrees**:

### Diretrizes de Isolamento
- **Árvore principal intocável**: A árvore de trabalho principal (`/home/admin/projects/EmpireMuse`) permanece **permanentemente na branch `main`**. Desenvolvedores e agentes **NUNCA** devem trocar de branch na raiz da árvore principal (`git checkout <branch>` ou `git switch <branch>`).
- **Diretório `worktrees/`**: Todas as branches de novas funcionalidades (`feat/*`), correções (`fix/*`), refatorações (`refactor/*`) ou tarefas paralelas devem ser desenvolvidas em worktrees dedicadas criadas dentro de `worktrees/` (exemplo: `worktrees/fix-nome-da-tarefa`). Esse diretório é estritamente ignorado no `.gitignore`, no `.dockerignore` e nas métricas de cobertura.

### Ciclo Operacional

1. **Criar a worktree a partir da `main` atualizada**:
   ```bash
   git fetch origin main
   git worktree add worktrees/<nome-da-branch> -b <nome-da-branch> origin/main
   ```

2. **Desenvolvimento e testes**:
   Navegue até a worktree correspondente (`cd worktrees/<nome-da-branch>`). Todo o desenvolvimento, execução de testes e commits acontecem exclusivamente dentro da pasta da worktree. O ambiente virtual `.venv` da raiz pode ser utilizado diretamente (`../../.venv/bin/python -m pytest`).

3. **Limpeza pós-merge**:
   Após o término da demanda, abertura do Pull Request e conclusão do merge na `main` pelo MAESTRO, remova a worktree e sincronize o repositório a partir da raiz:
   ```bash
   git worktree remove worktrees/<nome-da-branch>
   git branch -d <nome-da-branch>
   git worktree prune
   ```



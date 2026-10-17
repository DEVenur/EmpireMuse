# Guia de desenvolvimento local

Como preparar o ambiente para desenvolver e testar o EmpireMuse. Para entender o código, leia antes
[`architecture.md`](architecture.md); para bugs conhecidos, [`known-issues.md`](known-issues.md).

## 1. Requisitos

| Item | Versão | Observação |
|---|---|---|
| Python | **3.13** | O ambiente validado usa 3.13 (`audioop-lts` só é exigido a partir dele, `requirements.txt:30`). |
| [uv](https://docs.astral.sh/uv/) | recente | Gerenciador de venv/pacotes recomendado. |
| Git | qualquer | Necessário: `disnake` e `jishaku` são instalados de repositórios Git (`requirements.txt:1` e `requirements.txt:11`). |
| Java | **17+** | **Só** se for rodar o Lavalink local. Sem Java 17+, o bot tenta baixar um JDK sozinho (`utils/music/local_lavalink.py:63-215`). |
| Aplicação no Discord | — | Token do bot em <https://discord.com/developers/applications>, com as *Privileged Intents* ativadas (a falta delas é detectada e explicada na inicialização, `utils/client.py:278`). |

## 2. Ambiente virtual e instalação

```bash
git clone https://github.com/DiscordEmpireHub/EmpireMuse.git
cd EmpireMuse

uv venv --python 3.13
source .venv/bin/activate          # Windows: .venv\Scripts\activate

uv pip install -r requirements.txt "tinymongo[serialization]"
```

> **Bug conhecido — `requirements.txt:7`:** a linha declara `tinymongo` sem o extra `serialization`, mas
> `utils/db.py:18` importa `tinydb_serialization`. Numa instalação limpa, sem o contorno acima o bot falha
> ao importar `utils.db`. O contorno (`"tinymongo[serialization]"` na linha de comando) vale **até a
> correção do arquivo**, que está fora do escopo da fase de documentação.

Observações:

- Os scripts `source_setup.sh`/`source_quick_setup.sh` do projeto original usam `pip` e a pasta `venv/`;
  nada neles é necessário se você usar `uv`. Eles também sofrem do bug acima.
- O `disnake` está fixado em um commit Git anterior à 2.12.0 (`requirements.txt:1`); a atualização para a
  versão estável está planejada para fases futuras.
- Dependências declaradas e não usadas (candidatas à remoção): `syncedlyrics`, `pylrc`, `curl_cffi`,
  `undetected-chromedriver`, `aiosqlite`, `nest_asyncio` — ver [`known-issues.md`](known-issues.md).

## 3. Configuração

```bash
cp .example.env .env
```

Edite o `.env` (se um valor tiver espaço, use aspas). **Nunca** versione o `.env`, o `config.json` nem
qualquer token (`.env` e `config.json` já são ignorados pelo git; nunca use `git add -f` neles).

### Precedência (`config_loader.py:160-183`)

Do menor para o maior peso — o último vence:

1. `DEFAULT_CONFIG` (`config_loader.py:14`);
2. variáveis de ambiente — **somente** as chaves de `DEFAULT_CONFIG`, `TOKEN`, `MONGO` e as que começam
   com `TOKEN_BOT_`, `TEST_GUILDS_` e `LAVALINK_NODE_`;
3. `config.json` na raiz (JSON simples `{"CHAVE": "valor"}`);
4. `.env` — **sobrescreve** todos os anteriores.

Depois da mescla, números e booleanos são convertidos. Atenção: os booleanos aceitam apenas
`true`/`false`/`none` em **minúsculas** (`config_loader.py:8-12`, `283`); `True` ou `FALSE` causam erro
na inicialização (bug listado em `known-issues.md`).

### Variáveis essenciais

| Variável | Para quê |
|---|---|
| `TOKEN` | Token(s) do(s) bot(s). Vários tokens: separados por espaço. Qualquer chave cujo valor contenha um token válido também é aceita (`utils/client.py:695-716`). |
| `DEFAULT_PREFIX` | Prefixo dos comandos de texto (padrão `!!`). |
| `OWNER_IDS` | IDs de donos extras, separados por `\|\|` (`utils/client.py:1012`). |
| `MONGO` | URL do MongoDB. **Vazio = TinyMongo local** em `./local_database` (recomendado em desenvolvimento). |
| `PLAYER_SESSIONS_MONGODB` | Guardar sessões de players no Mongo (exige `MONGO`). |
| `RUN_RPC_SERVER` / `PORT` | Liga a página de status e o WebSocket do RPC (tornado). O padrão do código é `true` (`config_loader.py:86`), mas o `.example.env` define `false`. Ligue `RUN_RPC_SERVER=true` só se for testar o RPC (com `PORT=8080`; a porta padrão é a 80); use `ENABLE_RPC_AUTH=true` e não exponha a porta publicamente (no Gitpod, mantenha a porta privada). |
| `RUN_LOCAL_LAVALINK` | Inicia um Lavalink local (ver seção 5). |
| `AUTO_DOWNLOAD_LAVALINK_SERVERLIST` | Baixa a lista pública de Lavalink (ver seção 5). |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Credenciais do app Spotify (*client credentials*). Sem elas, o suporte interno ao Spotify fica desativado (`utils/client.py:680-688`). |
| `LASTFM_KEY` / `LASTFM_SECRET` | Integração com o Last.fm (opcional). |
| `TEST_GUILDS_<NOME_DO_BOT>` | IDs de servidores de teste (separados por `\|\|`) para registrar comandos só neles (`utils/client.py:730`). |
| `SUPPORT_SERVER` | Convite do servidor de suporte exibido no `/about` e em mensagens de erro (padrão aponta para o EmpireHUB). Em instâncias próprias, altere para o seu servidor ou deixe vazio (`SUPPORT_SERVER=''`) para não exibir o link. |
| `EMBED_COLOR` | Cor dos embeds (hex de 6 dígitos; padrão `8B5CF6`). Defina `EMBED_COLOR=none` para restaurar e utilizar a cor do cargo mais alto do bot no servidor. |
| `*_INTENT`, `MESSAGE_CONTENT_INTENT` etc. | Intents; os padrões estão em `config_loader.py:124-147`. |

A lista completa, comentada, está em `.example.env`. Em desenvolvimento, `ENABLE_LOGGER=true` grava
`./.logs/disnake.log` e `COMMAND_LOG=true` registra os comandos de usuários que não são donos. Em instâncias
próprias (self-hosting), certifique-se de configurar `SUPPORT_SERVER` (com seu convite ou vazio) e `EMBED_COLOR`
conforme a identidade desejada.

## 4. Como rodar

```bash
source .venv/bin/activate
python main.py
```

`main.py` cria o `BotPool` e inicia todos os bots (`main.py:8-10`). Na primeira execução:

- os comandos de barra são sincronizados com o Discord (`AUTO_SYNC_COMMANDS`, padrão `true`) e o estado
  fica em `./.app_commands_sync_data/` — a sincronização é pulada se nada mudou (`utils/client.py:1093-1111`);
- sem `MONGO`, a pasta `./local_database/` é criada (`utils/db.py:161-162`);
- com `RUN_RPC_SERVER=true`, a página de status responde em `http://localhost:<PORT>/`.

Pare com `Ctrl+C`. O `jishaku` é carregado em cada bot (`utils/client.py:749`) e serve para depuração
interativa por usuários donos.

## 5. Lavalink (servidor de áudio)

O bot **não toca áudio sozinho**: precisa de pelo menos um node Lavalink (v3 ou v4) ou NodeLink. As fontes
de nodes são somadas (`utils/client.py:582-628`):

| Opção | Como usar |
|---|---|
| **`lavalink.ini`** | Copie `lavalink.ini.example` para `lavalink.ini` (ignorado pelo Git). Cada seção é um node (`host`, `port`, `password`, `secure`, `region`, `search_providers`, …). Use `%%` para escrever `%` em valores. Só é lido quando `AUTO_DOWNLOAD_LAVALINK_SERVERLIST` é falso (`utils/client.py:600-601`). |
| **`LAVALINK_NODE_<N>`** | Variável (ou chave do `.env`) com um JSON por node, p.ex. `LAVALINK_NODE_1='{"identifier": "meu", "host": "...", "port": 443, "password": "...", "secure": true}'`. O JSON é usado como está, sem valores padrão: informe `identifier`, `host`, `port` e `password` (`utils/client.py:603-609`; `check_node` em `utils/client.py:321-371`). |
| **Lavalink local** | `RUN_LOCAL_LAVALINK=true`, ou nenhum node configurado (`utils/client.py:630`). Baixa `Lavalink.jar`, `application.yml` e plugins com verificação rigorosa de integridade via SHA-256 no download. Por padrão, `LAVALINK_FILE_URL` fica vazio no `.env`, o que seleciona automaticamente o espelho oficial correspondente à versão do código ([DiscordEmpireHub/EmpireMuse-LL-binaries](https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries) release `0.0.3` com Lavalink oficial 4.2.2 e plugins espelhados; constantes em `utils/branding.py`; o `application.yml` traz o cliente TV, OAuth desligado por padrão e log de `YoutubeOauth2Handler` em WARN). Se `LAVALINK_FILE_URL` contiver uma URL oficial de versão anterior do espelho, o bot atualiza sozinho para a versão atual com aviso no log. Para usar um jar próprio ou hospedagem customizada, o endereço exige obrigatoriamente HTTPS (`https://`) e a definição de `LAVALINK_FILE_SHA256`. Preserva `application.yml` personalizado existente (substituindo apenas versões oficiais conhecidas como 0.0.1 e 0.0.2). Baixa o JDK se não houver Java 17+. Requer rede e a RAM definida em `LAVALINK_RAM_LIMIT` (MB). O node se chama `LOCAL` e escuta em `127.0.0.1:${SERVER_PORT:-8090}`. |
| **Lista pública** | `AUTO_DOWNLOAD_LAVALINK_SERVERLIST=true` baixa a lista de nodes públicos (`get_lavalink_servers`, com `LAVALINK_SERVER_LIST` como alternativa; o padrão é `data/lavalink_servers.ini` do repositório, `LAVALINK_SERVER_LIST_URL` em `utils/branding.py`). Nodes públicos são instáveis e não devem ser usados com dados sensíveis. |

A lista baixada é validada (status 200 e formato INI com `host`, `port` e `password` em cada seção; `utils/music/lavalink_server_list.py`). Se o download falhar ou a resposta for inválida, o bot usa o arquivo local `data/lavalink_servers.ini`.

Dica: em máquinas de desenvolvimento, `RUN_LOCAL_LAVALINK=true` é o caminho mais previsível; os arquivos
baixados (`Lavalink.jar`, `application.yml`, `plugins/`, `.tempjar/`, `.java/`) ficam na raiz e não devem
ser commitados.

## 6. Testes e ferramentas

Os testes automatizados ficam em `tests/` e cobrem identidade de marca (`tests/test_branding.py`, `tests/test_identidade_visual.py`), validação de listas de servidores Lavalink, filtros de URLs, a suíte completa do painel web (`tests/panel/`) e caracterização de canais de pedidos (`tests/test_request_channel_*.py`). O `pyproject.toml` define a configuração do pytest e da medição de cobertura (`pytest-cov`).

```bash
uv pip install -r requirements-dev.txt   # pytest 9.1.1, pytest-asyncio e pytest-cov
.venv/bin/python -m pytest               # executa a suíte de testes (Windows: .venv\Scripts\python -m pytest)
.venv/bin/python -m pytest --cov         # executa testes medindo a cobertura de código
```

Padrão alvo da refatoração (demais ferramentas ainda **não** configuradas):

| Ferramenta | Uso |
|---|---|
| `ruff` | Lint e formatação (`ruff check .`, `ruff format .`), com regra para proibir `except:` nu (`E722`). |
| `pytest` + `pytest-asyncio` + `pytest-cov` | Testes unitários/integração; cobertura mínima de 80% para código novo (meta ≥ 80%; 97% na entrega da v1). |
| `mypy` ou `pyright` | Tipagem gradual nos módulos novos. |
| `uv` | Dependências e *lockfile* quando o projeto migrar para `pyproject.toml`. |

Além dos testes, valide mudanças com `python -m compileall -q .` e testes manuais com um bot de teste em um
servidor de teste (`TEST_GUILDS_*`). Convenções de código: `.claude/rules/empiremuse/python-disnake.md`.

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


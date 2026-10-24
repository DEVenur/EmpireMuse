# Painel Web — Pesquisa de Backend (etapa P-0)

> Autor: Backend Specialist · Data: 2026-10-15 · Branch: `feat/painel-web` (base `main` b71c1168)
> Escopo: inventário das configurações, arquitetura, OAuth2/sessão/CSRF/autorização, integração com `BotPool`/DB,
> variáveis de ambiente e contrato de API. **Sem código de produção.**
> A pesquisa externa (projetos prontos, bibliotecas, UI kits) é do agente **DeepSearch Researcher**
> (`docs/painel/pesquisa-externa.md`); aqui só há a seção de achados preliminares (§ 5).
> Referências de linha são da `main` (b71c1168) e podem se deslocar.

## Resumo executivo

1. **Inventário:** 18 opções de **servidor** (G-01…G-16, G-18, G-19; G-17 removido na versão 1.11 do modelo), 6 de **usuário** (U-01…U-06), **101 chaves** de configuração
   do **dono** (`DEFAULT_CONFIG`, só leitura no painel v1) e 7 itens de ação do dono. Total inventariado: **132 itens**.
2. **Recomendação de arquitetura: (A)** — sub-aplicação Tornado montada no `web_app.py`, no **mesmo processo, loop e porta**
   (`/painel/…`), em um pacote novo `panel/`. O DB (TinyMongo em arquivo ou Mongo) e os caches TTL são do processo do bot;
   (B) e (C) criariam uma segunda porta/processo e incoerência de cache/arquivo.
3. **Autorização:** OAuth2 *authorization code* com `state`, escopos `identify guilds`; o OAuth só **pré-filtra**.
   A decisão de acesso a um servidor é tomada **no servidor**, com os dados do próprio bot (`Guild.fetch_member` → `guild_permissions`).
4. **Riscos já encontrados que bloqueiam partes do escopo:** as skins personalizadas usam um formato de armazenamento
   legado inseguro (G-14, **fora da v1** até migrar para JSON validado; rastreado em privado, S-04); o `/ws` atual tem
   endurecimento pendente (rastreado em privado, S-02; o painel fica isolado dele); `update_values` apaga listas ao migrar
   versão (KI-09); o cache de membros pode estar incompleto (o bot força `intents.members = True`, mas servidores grandes e o
   pós-boot exigem `fetch_member` como fallback).
5. **Dúvidas para o dono:** ver § 9.

---

## 1. Como as configurações são guardadas (base para tudo)

### 1.1 Camadas de dados (`BotCore.get_data`/`BotCore.update_data` e `BotCore.get_global_data`/`BotCore.update_global_data` em `empiremuse/utils/client.py`, `empiremuse/utils/db.py`)

| Camada | API no bot | Coleção no DB | Escopo real | Modelo (`utils/db.py`) |
|---|---|---|---|---|
| **Por bot × servidor** | `bot.get_data/update_data(id, db_name=DBModel.guilds)` | `str(bot.user.id)` | cada bot do pool tem a **sua** cópia | `db_models[guilds]` `ver 1.11` |
| **Por bot × usuário** | `bot.get_data(…, DBModel.users)` | `str(bot.user.id)` | idem | `db_models[users]` `ver 1.0` (só `fav_links`, legado) |
| **Global × servidor** | `bot.get_global_data/update_global_data(id, DBModel.guilds)` | `"global"` | **compartilhado por todos os bots** | `global_db_models[guilds]` `ver 1.4` |
| **Global × usuário** | `bot.get_global_data(…, DBModel.users)` | `"global"` | compartilhado | `global_db_models[users]` `ver 1.6` |

Consequência para o painel: uma tela de servidor mistura campos **por bot** (volume, DJ, skin, canal do player…) e campos
**globais** (prefixo, status do canal de voz, skin global, convites "ouvir junto"). Quando há vários bots no mesmo servidor,
o painel precisa de um **seletor de bot** para os campos por bot (hoje o bot faz isso com `select_bot_pool`,
`utils/others.py`). Os campos globais não dependem do bot escolhido.

### 1.2 Pontos de atenção do DB que afetam o painel

- **Cache TTL compartilhado** (`BaseDB.cache`, 300 s por padrão): `get_data` devolve o **mesmo dict mutável** do cache.
  Como o painel rodará no mesmo processo e usará as mesmas funções, a coerência é automática — **desde que o painel nunca
  grave direto no TinyMongo/Mongo** (a regra do projeto já proíbe) e sempre passe por `bot.update_data/update_global_data`.
- **Atualização de documento inteiro** (`$set` do dict todo): duas escritas concorrentes (comando no Discord × painel) podem
  sobrescrever uma à outra (*lost update*). Mitigação: ler-modificar-gravar **sem `await` no meio** quando o dado vem do
  cache, ou um `asyncio.Lock` por `(coleção, id)` no serviço do painel; alterar **só o campo** do formulário.
- **KI-09** (`update_values` em `empiremuse/utils/db.py`): `update_values` descarta listas ao migrar `ver`. O painel **não deve subir `ver`**;
  um teste de caracterização deve acompanhar qualquer mudança de modelo (`djroles`, `last_tracks` são listas).
- **`MongoDatabase.get_data` não grava** o documento padrão quando inexistente (devolve cópia do modelo) e o
  `LocalDatabase.get_data` **grava** (insert). O painel não deve depender dessa diferença; use sempre `update_data`.
- **Skins personalizadas usam formato de armazenamento legado inseguro** (campos `custom_skins`/`custom_skins_static` da
  coleção global de servidores; rastreado em privado, S-04). O painel **não lê nem grava** esses campos; G-14 fica fora da v1
  até a migração para JSON validado. Ver G-14.

### 1.3 Efeitos colaterais que o painel precisa reproduzir

Gravar no banco não basta. Hoje cada comando também atualiza estado em memória:

| Mudança | Efeito em memória a reproduzir |
|---|---|
| Prefixo do servidor | `bot.pool.guild_prefix_cache[guild_id] = prefix` (`Owner.setprefix` e `Owner.resetprefix` em `empiremuse/cogs/legacy_cmds.py`) |
| Prefixo do usuário | `bot.pool.user_prefix_cache[user_id] = prefix` (`Owner.setuserprefix` e `Owner.resetuserprefix` em `empiremuse/cogs/legacy_cmds.py`) |
| Configurações do player (G-01…G-04) | `player.process_save_queue()` se houver player ativo (`PlayerSettings.save_data` em `empiremuse/cogs/music_settings.py`) |
| Status do canal de voz (G-13) | atualizar o modelo e o status nos players ativos (`SetStageTitle` em `empiremuse/utils/music/interactions/stage_title.py`) |
| Convite "ouvir junto" (G-15) | `p.listen_along_invite = url; p.process_rpc(); p.process_save_queue()` (`MusicSettings.listen_along_modal` em `empiremuse/cogs/music_settings.py`) |
| Skin (G-08…G-11) | recarregar skin do player ativo (`MusicSettings.change_skin` em `empiremuse/cogs/music_settings.py`) |
| Canal do player (G-06) | criar/mover mensagem, thread, `player.static`, etc. (`MusicSettings.setup` em `empiremuse/cogs/music_settings.py` e `empiremuse/utils/music/request_channel.py`) |

Recomendação: criar uma **camada de serviço** (`panel/services/*.py`) que extrai a regra de cada comando para funções
testáveis (a regra de projeto já pede isso), chamada pelo comando **e** pelo painel — evita duas implementações divergentes.

---

## 2. Inventário completo de configurações

Convenções: **Escopo** = Servidor (S), Usuário (U), Dono do bot (D). **Camada** = bot×servidor (`b`), global (`g`).
**Perm.** = permissão exigida hoje. Linhas referem-se à `main`. "Ação" = tem efeito no Discord além do campo no banco.

### 2.1 Servidor (S) — 18 opções

| ID | Opção | Origem (símbolo e arquivo) | Campo no banco | Tipo / valores válidos | Camada | Perm. hoje | Notas para o painel |
|---|---|---|---|---|---|---|---|
| G-01 | Volume padrão do player | `PlayerSettings`, `MusicSettings.player_settings` e `MusicSettings.player_settings_legacy` em `empiremuse/cogs/music_settings.py` | `default_player_volume` | int; `5…100` passo 5 e `110…150` passo 10 (>100 degrada o áudio) | b | `manage_guild` | validar contra o conjunto exato; aplicar em `process_save_queue` |
| G-02 | Autoplay | idem | `autoplay` | bool | b | `manage_guild` | idem |
| G-03 | Não conectar com bots incompatíveis | idem | `check_other_bots_in_vc` | bool | b | `manage_guild` | lido em `Music.play` (`empiremuse/music_cog/play_command.py`) e `Music.player_controller` (`empiremuse/music_cog/player_controller.py`) |
| G-04 | Modo restrito | idem | `enable_restrict_mode` | bool | b | `manage_guild` | lido em `Music.player_controller` em `empiremuse/music_cog/player_controller.py` |
| G-05 | Cargos de DJ | `MusicSettings.add_dj_role` e `MusicSettings.remove_dj_role` (e legados) em `empiremuse/cogs/music_settings.py` | `djroles` | lista de `str(role_id)`; proibido `@everyone` (`default_role`); sem duplicata | b | `manage_guild` | validar que o cargo existe no servidor; sem limite de quantidade no código atual (definir um) |
| G-06 | Canal de pedir música (song request) — **setup** | `MusicSettings.setup` e `MusicSettings.setup_legacy` em `empiremuse/cogs/music_settings.py` | `player_controller.channel`, `player_controller.message_id` | `str(channel_id)` de TextChannel/VoiceChannel/ForumChannel/StageChannel; opção "limpar mensagens" (yes/no); fórum pede título 4-30 caracteres | b | `manage_guild` | **Ação:** cria canal/mensagem/thread, permissões do bot, conecta player. Exige o bot no servidor com `manage_channels`, `manage_messages`, etc. |
| G-07 | Resetar canal do player — **reset** | `MusicSettings.reset` em `empiremuse/cogs/music_settings.py` | `player_controller.channel/message_id` → `None` | opção `deletar_canal` sim/não | b | `manage_guild` (bot precisa de `manage_threads`) | **Ação destrutiva** (pode apagar canal/post). Confirmação dupla |
| G-08 | Skin do player (modo normal) | `MusicSettings.change_skin` em `empiremuse/cogs/music_settings.py` | `player_controller.skin` | nome de skin existente em `bot.player_skins` (menos `IGNORE_SKINS`) **ou** `> custom_skin: <nome>` | b | `manage_guild` | custom skin só se G-14 for liberado |
| G-09 | Skin do player (modo song-request) | idem | `player_controller.static_skin` | `bot.player_static_skins` (menos `IGNORE_STATIC_SKINS`) | b | `manage_guild` | idem |
| G-10 | Skin global ligada | idem | `global_skin` (g) | bool | g | `manage_guild` | quando `true`, vale `player_skin`/`player_skin_static` para **todos** os bots |
| G-11 | Skin global (normal / song-request) | idem | `player_skin`, `player_skin_static` (g) | nomes de skin; `None` = padrão do pool | g | `manage_guild` | idem |
| G-12 | Prefixo do servidor | `Owner.setprefix` e `Owner.resetprefix` (dono: `Owner.setguildprefix`) em `empiremuse/cogs/legacy_cmds.py` | `prefix` (g) | str, sem espaços, 1-5 caracteres; vazio = `DEFAULT_PREFIX` | g | `manage_guild` | atualizar `guild_prefix_cache`; **bug existente**: `setguildprefix` grava o cache com `ctx.guild.id` em vez de `server_id` (`Owner.setguildprefix` em `empiremuse/cogs/legacy_cmds.py`) — não replicar |
| G-13 | Status automático do canal de voz | `Music.set_voice_status` em `empiremuse/music_cog/voice_status.py`, `SetStageTitle` em `empiremuse/utils/music/interactions/stage_title.py` | `voice_channel_status` (g) | str com placeholders (`{track.title}` etc.); vazio = desligado; variante "temporária" não persiste | g | `manage_guild` (ou dono) | validar tamanho (limite do status de canal do Discord — **a confirmar na doc oficial**) e placeholders permitidos |
| G-14 | Skins personalizadas (editor) | `MusicSettings.custom_skin` em `empiremuse/cogs/music_settings.py`, `SkinEditorMenu` em `empiremuse/utils/music/interactions/skin_editor.py` | `custom_skins`, `custom_skins_static` (g) | dict `{nome: <formato legado>}` | g | **`administrator`** | **FORA DA v1** (formato de armazenamento legado inseguro; rastreado em privado, S-04). Reabrir só após migrar para JSON validado (tarefa própria, regra `security.md` §2) |
| G-15 | Convites "ouvir junto" (RPC) | `MusicSettings.listenalong` e `MusicSettings.listen_along_modal` em `empiremuse/cogs/music_settings.py` | `listen_along_invites` (g) | dict `{str(voice_channel_id): invite_url}`; máx. **5**; convite sem limite de usos e não restrito a um usuário; canal de voz | g | `manage_channels` + estar em voz | painel pode **listar/remover**; **adicionar** exige `fetch_invite` (chamada externa) e checagens. Cooldown de 45 s por servidor |
| G-16 | Links fixos do servidor (favoritos do servidor) | `FavMenuView` (modo `guild_fav_manager`) em `empiremuse/utils/music/interactions/fav_menu.py`; `Music.fav_manager` em `empiremuse/music_cog/favorites.py` | `player_controller.fav_links` | dict `{nome: {"url": str, "description": str}}`; máx. **25**; só com canal de player configurado; URL via `URL_REG`; nome ≤ `USER_FAV_MAX_NAME_LENGTH` | b | `manage_guild` (ou dono) | importação/exportação JSON existe no bot (`FavModalImport`); no painel, CRUD + import com os mesmos limites |
| G-17 | *(Removido)* | `empiremuse/utils/db.py` (`db_models`) | — | — | b | — | **campo removido**: antigo campo órfão de prefixo excluído na versão 1.11 (KI-43). Sem tela. |
| G-18 | Escolha do bot (multi-bot) | `select_bot_pool` em `empiremuse/utils/others.py`; `MusicSettings.player_settings`, `MusicSettings.setup`, `MusicSettings.reset` e `MusicSettings.change_skin` em `empiremuse/cogs/music_settings.py` | — | id de um bot do `pool.get_guild_bots(guild_id)` | — | — | afeta G-01…G-11 e G-16. Contrato: parâmetro `bot_id` |
| G-19 | Adicionar mais bots ao servidor | botão `bot_invite` (`music.py`, `music_settings.py`) e `Misc.invite` / `Misc.invite_button` em `empiremuse/cogs/misc.py` | — | link de convite por bot | — | qualquer um | tela "adicionar bot"; usa `INVITE_PERMISSIONS` (config). Gerar o link a partir do `client_id` de cada bot do pool |

### 2.2 Usuário (U) — 6 opções

| ID | Opção | Origem | Campo | Tipo / limites | Camada | Perm. | Notas |
|---|---|---|---|---|---|---|---|
| U-01 | Prefixo pessoal | `Owner.setuserprefix` e `Owner.resetuserprefix` em `empiremuse/cogs/legacy_cmds.py` | `custom_prefix` (g, users) | str 1-5 caracteres, sem espaços | g | qualquer usuário | atualizar `user_prefix_cache` |
| U-02 | Favoritos pessoais | `FavMenuView` (modo `fav_manager`) em `empiremuse/utils/music/interactions/fav_menu.py`; `Music.fav_manager` (e legados `favs…`) em `empiremuse/music_cog/favorites.py` | `fav_links` (g, users) | dict `{nome: url}`; máx. `MAX_USER_FAVS` (padrão 10; 0 = ilimitado; dono isento); nome ≤ `USER_FAV_MAX_NAME_LENGTH` (35); URL ≤ `USER_FAV_MAX_URL_LENGTH` (90) e `URL_REG` | g | qualquer usuário | os limites são **config do dono**: o painel deve lê-los de `bot.config` |
| U-03 | Integrações (canais/perfis para playlists) | `FavModalImport` e `FavModalAdd` (modo `integrations_manager`) em `empiremuse/utils/music/interactions/fav_modals.py`; `Music.fav_manager` em `empiremuse/music_cog/favorites.py` | `integration_links` (g, users) | dict `{título[:90]: {"url": str, "avatar"?: str}}`; máx. `MAX_USER_INTEGRATIONS` (10) | g | qualquer usuário | **adicionar** faz requisição externa (SSRF/abuso): manter a validação existente; no painel v1 só **listar/remover/importar JSON** |
| U-04 | Scrobble Last.fm (liga/desliga) | `LastFMView.scrobble_enable` (botão) e `LastFmCog.lastfm` (`/lastfm`) em `empiremuse/cogs/lastfm.py` | `lastfm.scrobble` (g, users) | bool; cooldown no botão | g | qualquer usuário | exige conta vinculada (`lastfm.username`, `sessionkey` = **segredo**). Painel: mostrar status + toggle; **vincular** conta continua no Discord |
| U-05 | Token do app de RPC | `MusicSettings.rpc_create_modal` (modal `rpc_token_create`) e `RPCCog.rich_presence` (`/rich_presence`) em `empiremuse/cogs/music_settings.py` | `token` (g, users) | str (segredo de pareamento) | g | `ENABLE_RPC_COMMAND` ou dono | **segredo**: nunca devolver o valor ao navegador; painel pode "gerar novo" e mostrar **uma vez**. Decidir com o dono (D-4) |
| U-06 | Histórico de faixas | `global_db_models` em `empiremuse/utils/db.py` | `last_tracks` | lista | g | — | **somente leitura** (se alguma tela precisar); lista sofre KI-09 |

### 2.3 Dono do bot (D) — configuração de ambiente (`DEFAULT_CONFIG` em `empiremuse/config_loader.py`)

São **101 chaves** (contagem feita importando `config_loader.DEFAULT_CONFIG`) lidas de `os.environ`/`.env`/`config.json`
**uma vez** na inicialização (`load_config` em `empiremuse/config_loader.py`) e só mudam com reinício ou `Owner.reloadconfig` em `empiremuse/cogs/legacy_cmds.py`.
**Não são persistidas pelo DB**; editá-las exigiria escrever em `.env`. Além delas, `load_config` aceita chaves dinâmicas
`TOKEN`, `TOKEN_BOT_*`, `TEST_GUILDS_*` e `LAVALINK_NODE_*` (não contadas).
Recomendação v1: **somente leitura** (diagnóstico), com **máscara** nos segredos. Agrupamento:

| Grupo | Chaves (resumo) | Tipo | Sensível |
|---|---|---|---|
| Identidade/geral | `DEFAULT_PREFIX`, `OWNER_IDS`, `SUPPORT_SERVER`, `SOURCE_REPO`, `EMBED_COLOR`, `INTERACTION_COMMAND_ONLY`, `AUTO_SYNC_COMMANDS`, `COMMAND_LOG`, `ENABLE_COMMANDS_COOLDOWN`, `PREFIXED_POOL_TIMEOUT`, `PRESENCE_INTERVAL`, `GIT_DIR`, `ADDITIONAL_BOT_IDS`, `INVITE_PERMISSIONS`, `ENABLE_LOGGER`, `KILL_ON_429`, `SILENT_PUBLICBOT_WARNING` | str/int/bool | não |
| Webhooks/log | `BOT_ADD_REMOVE_LOG`, `BOT_ADD_REMOVE_LOG_CHANNEL_ID`, `ERROR_REPORT_WEBHOOK`, `AUTO_ERROR_REPORT_WEBHOOK` | str | **sim** (URL de webhook) |
| Banco | `MONGO`, `MONGO_TIMEOUT`, `DBCACHE_SIZE`, `DBCACHE_TTL`, `SENSITIVE_INFO_WARN` | str/int/bool | **`MONGO` sim** |
| Música/player | `DEFAULT_SKIN`, `DEFAULT_STATIC_SKIN`, `DEFAULT_IDLING_SKIN`, `IGNORE_SKINS`, `IGNORE_STATIC_SKINS`, `VOTE_SKIP_AMOUNT`, `IDLE_TIMEOUT`, `WAIT_FOR_MEMBERS_TIMEOUT`, `MAX_USER_FAVS`, `USER_FAV_MAX_NAME_LENGTH`, `USER_FAV_MAX_URL_LENGTH`, `MAX_USER_INTEGRATIONS`, `EXTRA_HINTS`, `HINT_RATE`, `GUILD_DEAFEN_WARN`, `ENABLE_DISCORD_URLS_PLAYBACK`, `QUEUE_MAX_ENTRIES`, `ENABLE_DEFER_TYPING`, `VOICE_CHANNEL_LATENCY_RECONNECT`, `PLAYLIST_CACHE_SIZE`, `PLAYLIST_CACHE_TTL`, `USE_YTM_TRACKINFO_SCROBBLE`, `ENABLE_SONGREQUEST_MENTION`, `YOUTUBE_TRACK_COOLDOWN`, `FORCE_USE_DEEZER_CLIENT` | int/bool/str | não |
| Sessões do player | `PLAYER_INFO_BACKUP_INTERVAL`, `PLAYER_INFO_BACKUP_INTERVAL_MONGO`, `PLAYER_SESSIONS_MONGODB` | int/bool | não |
| Lavalink | `AUTO_DOWNLOAD_LAVALINK_SERVERLIST`, `LAVALINK_SERVER_LIST`, `LAVALINK_RECONNECT_RETRIES`, `RUN_LOCAL_LAVALINK`, `CONNECT_LOCAL_LAVALINK`, `LAVALINK_ADDITIONAL_SLEEP`, `LAVALINK_INITIAL_RAM`, `LAVALINK_RAM_LIMIT`, `LAVALINK_CPU_CORES`, `LAVALINK_FILE_URL`, `SEARCH_PROVIDERS`, `PREFER_YOUTUBE_NATIVE_PLAYBACK`, `ONLY_USE_NATIVE_SEARCH_PROVIDERS` (+ dinâmicas `LAVALINK_NODE_*`) | str/int/bool | `LAVALINK_NODE_*` **sim** (senha do nó) |
| Spotify/Last.fm | `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_PLAYLIST_EXTRA_PAGE_LIMIT`, `LASTFM_KEY`, `LASTFM_SECRET` | str/int | **secrets sim** |
| RPC/web | `RUN_RPC_SERVER`, `RPC_SERVER`, `PORT`, `RPC_PUBLIC_URL`, `ENABLE_RPC_COMMAND`, `ENABLE_RPC_AUTH` | str/int/bool | não |
| Presenças | `LISTENING_PRESENCES`, `WATCHING_PRESENCES`, `PLAYING_PRESENCES`, `STREAMING_PRESENCES`, `CUSTOM_STATUS_PRESENCES` | str (lista) | não |
| Intents | `*_INTENT` (BANS, DM_MESSAGES, DM_REACTIONS, DM_TYPING, GUILD_MESSAGES, GUILD_REACTIONS, GUILD_SCHEDULED_EVENTS, GUILD_TYPING, EMOJIS_AND_STICKERS, GUILDS, INTEGRATIONS, INVITES, VOICE_STATES, WEBHOOKS, MEMBERS, PRESENCES, MESSAGE_CONTENT) | bool | não — **exigem reinício** |

#### Ações do dono hoje (comandos/botões)

| ID | Ação | Origem | Perm. | Risco | Painel v1 |
|---|---|---|---|---|---|
| O-1 | Recarregar configs | `Owner.reloadconfig` em `empiremuse/cogs/legacy_cmds.py` | dono | baixo | **sim** (botão) |
| O-2 | Recarregar skins | `Owner.reloadskins` em `empiremuse/cogs/legacy_cmds.py` | dono | baixo | **sim** |
| O-3 | Recarregar módulos | `Owner.reload` em `empiremuse/cogs/legacy_cmds.py` | dono | médio | opcional (lista fechada de módulos) |
| O-4 | Atualizar bot via git | `Owner.update` em `empiremuse/cogs/legacy_cmds.py` | dono | **alto** (executa git/pip, reinicia) | **não** |
| O-5 | Exportar source | `Owner.exportsource` em `empiremuse/cogs/legacy_cmds.py` | dono | **alto** (inclui `.env`) | **não** |
| O-6 | `shell`, `cleardm`, `setbanner`, `setavatar`, `getlavaservers`, `restartlavalink`, `updatelavalink`, `setguildprefix` | `Owner` em `empiremuse/cogs/legacy_cmds.py` | dono | alto/médio | **não** na v1 (shell/eval nunca na web); `setguildprefix` coberto por G-12 com perfil dono |
| O-7 | Lista de servidores / gestão de servidores | `modules/server_manager.py` (`ServerManagerView`) | dono | médio | candidata a v2 (somente leitura) |

### 2.4 Contagem

- **Servidor:** 18 linhas ativas/planejadas (G-01…G-16, G-18, G-19; G-17 removido na versão 1.11 do modelo). Editáveis no painel v1: G-01…G-13, G-15 (listar/remover), G-16; G-19 é link;
  G-14 **adiado**, G-18 é meta (seletor de bot).
- **Usuário:** 6 (U-01…U-06). Editáveis v1: U-01, U-02, U-03 (listar/remover/importar), U-04 (toggle), U-05 (condicional a D-4).
- **Dono:** 101 chaves (leitura) + 7 itens de ação (O-1 e O-2 liberados; O-3 opcional; O-4/O-5/O-6 vetados; O-7 v2).
- **Total inventariado: 18 + 6 + 101 + 7 = 132 itens.**

---

## 3. Arquitetura

### 3.1 Situação atual

`run_app` em `empiremuse/web_app.py` cria um `tornado.web.Application` com duas rotas (`/` e `/ws`) e chama `app.listen(PORT)`.
O `start()` roda no **mesmo loop asyncio dos bots** (`BotPool.setup` em `empiremuse/utils/client.py`, `pool.loop`), então handlers Tornado podem
`await` diretamente funções do bot. O endurecimento do `/ws` está rastreado em privado (S-02) e fora do escopo; **o painel fica isolado dele**
(sub-aplicação própria, sem compartilhar cookies nem configurações com `/ws`).
`requirements.txt` já tem `tornado>=6.4.2`; `aiohttp` vem junto com o disnake.

### 3.2 Opções

| | (A) Handlers Tornado no `web_app.py` (sub-aplicação) | (B) App ASGI separado no mesmo loop | (C) Projeto/processo externo |
|---|---|---|---|
| Porta | **mesma** (`PORT`) | outra porta (uvicorn/hypercorn); não há adaptador ASGI↔Tornado na stdlib | outra porta/host |
| Processo / loop | mesmo | mesmo loop (servidor ASGI `serve()` como task) | outro processo; comunicação por IPC/HTTP/DB |
| Acesso ao `BotPool`, DB e cache | direto | direto | só via API/IPC — **duplica** regras |
| DB | o mesmo objeto, cache coerente | o mesmo | `LocalDatabase` (TinyMongo em arquivo) **não é seguro com 2 processos**; Mongo: cache do bot fica velho até 300 s |
| Dependências novas | **nenhuma** (Tornado já é dependência) | framework ASGI (Starlette/Quart/FastAPI) + servidor + libs de OAuth | stack própria + canal de IPC |
| Deploy "junto com o bot" | trivial (uma porta, um processo) | 2º listener (hospedagens de porta única, como Render/Replit/Discloud, quebram) | 2 serviços |
| Superfície de segurança | menor (sem nova stack), mas compartilha processo com `/ws` | maior | maior (IPC autenticado) |
| Testabilidade | `tornado.testing.AsyncHTTPTestCase` | `httpx`/`TestClient` | e2e |
| Reaproveitamento de lib pronta | `tornado.auth.OAuth2Mixin`, `set_secure_cookie`, `xsrf_cookies` | libs Quart/FastAPI (ver § 5) | dashboards completos em outras linguagens |
| Risco de bloquear o loop | existe (qualquer código síncrono) — mesma regra do projeto | idem | não afeta o bot |

**Recomendação: (A), como sub-aplicação isolada.** Em vez de acrescentar rotas ao `Application` atual (que passaria a
herdar `xsrf_cookies`/`cookie_secret` e afetaria `/` e `/ws`), montar uma `PainelApplication` própria e registrá-la sob
`/painel` via `tornado.routing` (`Rule(PathMatches(r"/painel/.*"), painel_app)`). Isso mantém `cookie_secret`, `xsrf_cookies`,
`static_path`, `template_path` e `log_function` **apenas** no painel. O `web_app.py` muda em ~5 linhas (montagem condicional
por `PANEL_ENABLED`); todo o código novo fica no pacote `panel/`. (Verificar na implementação que o roteamento aninhado do
Tornado 6.4 aceita `Application` como alvo de `Rule` — está documentado em `tornado.routing`.)

(B) só se o dono aceitar uma segunda porta; (C) descartada (coerência de cache/arquivo, deploy duplicado).

### 3.3 Estrutura de pacote proposta (para o plano; não criar agora)

```
panel/
  __init__.py          # build_panel_app(pool, config) -> tornado.web.Application | None
  settings.py          # leitura/validação das variáveis PANEL_* (falha rápido se faltar segredo)
  oauth.py             # fluxo authorization code do Discord (state, troca de code, revogação)
  sessions.py          # SessionStore (memória + expiração), cookies, rotação do id
  authz.py             # autorização por servidor/usuário (dados do bot), cache curto
  csrf.py / ratelimit.py
  handlers/            # auth, guilds, guild_settings, user_settings, owner, health
  services/            # regras compartilhadas com os comandos (G-xx, U-xx)
  schemas.py           # validação de entrada (um schema por recurso; limites vindos de bot.config)
  templates/ static/   # Frontend
tests/panel/           # QA (RED primeiro)
```

---

## 4. Segurança e desenho de autenticação/autorização

### 4.1 OAuth2 (authorization code)

1. `GET /painel/login`: gera `state` (32 bytes aleatórios, `secrets.token_urlsafe`), guarda em cookie curto
   `__Host-em_oauth_state` (HttpOnly, Secure, SameSite=Lax, `Max-Age=600`) **e** no servidor (`pending[state] = {criado_em, next}`);
   redireciona para `https://discord.com/oauth2/authorize?response_type=code&client_id=…&scope=identify%20guilds&state=…&redirect_uri=…&prompt=none`.
   Escopos mínimos: **apenas `identify guilds`**; nada de `email`, `guilds.join`, `bot`.
2. `GET /painel/callback?code=…&state=…`: valida `state` com `hmac.compare_digest` contra cookie **e** servidor
   (uso único, expira em 10 min); rejeita se `error=` ou parâmetros ausentes; troca o `code` em
   `POST https://discord.com/api/oauth2/token` (form `grant_type=authorization_code`, `redirect_uri` idêntico,
   `client_id/client_secret`) com `timeout` explícito; busca `GET /users/@me` e `GET /users/@me/guilds` **uma única vez por
   login** (`limit` máx. 200; o campo `permissions` vem como **string**, converter para inteiro). O `OAuth2Mixin` do Tornado
   **não gera nem valida `state`**: essa parte é nossa (itens 1 e 2).
   Redirect URI **fixa por configuração** (nunca derivada de `Host`/`X-Forwarded-*`), HTTPS obrigatório em produção.
3. **Logo após ler usuário e guildas, revoga o token** (`POST https://discord.com/api/oauth2/token/revoke`, que revoga todos
   os tokens da autorização) e **descarta `code`, `access_token` e `refresh_token`**: nada disso fica em sessão, cookie, log
   ou banco. A sessão guarda só a identidade e a lista de guildas obtidas no login (pré-filtro); atualizar essa lista = novo login.
   Se a revogação falhar, registrar o evento (sem o token) e seguir.
4. PKCE (S256): suportado pelo Discord, mas descrito fora da página genérica de OAuth2; para cliente confidencial (com
   `client_secret`, caso do painel) é **opcional**. Proposta: `state` + `client_secret` na v1, PKCE como defesa em profundidade
   se o dono quiser (testar contra o Discord real). Fonte e detalhes: `pesquisa-externa.md`.
5. Respeitar o *rate limit*: ler `X-RateLimit-*` e `Retry-After` do 429 (limites da rota `guilds` não são documentados) e **nunca
   repetir** chamadas com token inválido — 10.000 respostas 401/403/429 em 10 minutos geram bloqueio temporário do IP, o que
   importa em hospedagem de IP compartilhado.

### 4.2 Sessão no servidor

- Cookie `__Host-em_session` com **apenas um id opaco** (`token_urlsafe(32)`), assinado por `set_secure_cookie`
  (`cookie_secret` ≥ 32 bytes aleatórios, vindo de `PANEL_COOKIE_SECRET`): `Secure`, `HttpOnly`, `SameSite=Lax`
  (Lax é necessário para o retorno do OAuth por GET; não usar `Strict`), `Path=/`, sem `Domain` (prefixo `__Host-`).
  Em desenvolvimento HTTP local o prefixo `__Host-`/`Secure` não funciona: variável `PANEL_INSECURE_COOKIES=true` só aceita
  com `PANEL_BASE_URL` em `localhost`.
- Dados da sessão no servidor: `user_id`, nome/avatar, lista de servidores obtida no login (id, nome, ícone, flags
  `owner`/`permissions`), `criado_em`, `ultimo_uso`. **Sem tokens OAuth** (revogados no callback, § 4.1). **TTL absoluto** (padrão 12 h) e **ociosidade** (60 min);
  **rotação do id** após login. Armazenamento: dicionário em memória com limpeza periódica (sessões somem no restart — aceitável e
  mais seguro); persistir em DB só se o dono preferir sessões entre reinícios (D-3).
- Limite de sessões por usuário (ex.: 5) e de sessões totais (contra exaustão de memória).

### 4.3 CSRF e demais proteções web

- `xsrf_cookies=True` **na sub-aplicação**; formulários enviam `_xsrf`, chamadas `fetch` enviam o cabeçalho `X-XSRFToken`.
  Além disso, em todo método não seguro: verificar `Origin` (ou `Referer`) == origem de `PANEL_BASE_URL`; rejeitar `Origin: null`.
- Métodos mutáveis **só** `POST/PUT/PATCH/DELETE`; `GET` nunca altera estado (inclui logout).
- Cabeçalhos: `Content-Security-Policy` restritiva (sem `unsafe-inline`; com *nonce* se houver script inline), `frame-ancestors 'none'`
  / `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `Strict-Transport-Security`
  (quando HTTPS), `Cache-Control: no-store` nas respostas autenticadas.
- Entrada: corpo JSON com `Content-Type: application/json`, tamanho máximo (ex.: 64 KB), esquema estrito
  (campos desconhecidos rejeitados), limites iguais aos dos comandos (§ 2). Texto do usuário reexibido é **escapado** (autoescape do
  template) e, ao enviar para o Discord, com `AllowedMentions.none()`.
- Rate limit por IP+sessão (balde em memória): login/callback (ex.: 10/min), leitura (60/min), escrita (20/min), operações de
  ação (G-06/G-07: 3/min). Respeitar também o limite da API do Discord (§ 4.1, item 5).
- CSP sem inline/eval (`script-src 'self'`; *nonce* só se for inevitável); assets (JS/CSS) **vendorizados** em `/painel/static/`,
  sem CDN; registrar a licença de cada asset vendorizado em `CREDITS.md`.
- Erros: mensagens genéricas ao cliente (`{"erro": {"codigo": "...", "mensagem": "..."}}`), detalhes só no log; **nunca** logar `code`,
  tokens, cookies ou `client_secret`.
- Atrás de proxy: `PANEL_TRUST_PROXY=true` habilita `X-Forwarded-For/Proto` apenas se o dono declarar; senão ignora esses
  cabeçalhos (Tornado `xheaders=False`).

### 4.4 Autorização por servidor — verificada no servidor

A lista `guilds` do OAuth traz `owner` e `permissions`, mas é **dado do momento do login**; serve só como
**pré-filtro** (mostrar a lista). Para **cada requisição** a `/api/v1/servidores/{gid}/…`:

1. A sessão é válida e `gid` é um *snowflake* inteiro (17-20 dígitos).
2. Existe ao menos um bot do pool no servidor: `bots = pool.get_guild_bots(gid)` filtrado por `bot.get_guild(gid)`.
   Sem bot → `404` (não revelar existência).
3. Obter o membro **com dados do bot**. O bot força `intents.members = True` (`BotPool.setup` em `empiremuse/utils/client.py`, depois de montar os
   intents pela config, então `MEMBERS_INTENT` de `DEFAULT_CONFIG` em `empiremuse/config_loader.py` é ignorado ali), portanto o cache de membros é
   mantido por eventos do gateway. Estratégia: `guild.get_member(uid)` primeiro (cache, sem custo); se vier `None` (membro
   fora do cache, guilda ainda não carregada), cair em `await guild.fetch_member(uid)` (REST) com cache curto de 30-60 s por
   `(gid, uid)` e *rate limit*. Se ambos falharem, negar (`403`). O cache pode estar incompleto em servidores grandes ou
   logo após o boot, por isso o fallback é obrigatório. `Member.guild_permissions` já considera cargos e dono (`owner_id`).
   Observação: o *intent* privilegiado de membros precisa estar habilitado no portal do Discord para cada bot; sem isso o
   gateway recusa a conexão (comportamento atual do projeto, não do painel).
4. Aceitar quando: `guild.owner_id == uid` **ou** `administrator` **ou** `manage_guild` — a mesma barra dos comandos
   (`default_member_permissions=Permissions(manage_guild=True)`; G-14 exige `administrator`; G-15 `manage_channels`). Dono do bot
   (`await bot.is_owner(user)`, `OWNER_IDS`) passa em tudo (como hoje, `FavMenuView.interaction_check` em `empiremuse/utils/music/interactions/fav_menu.py`).
5. Re-verificar a cada requisição de escrita (cache curto) — revogação de cargo vale em ≤ 1 min.
6. Registrar auditoria (quem, servidor, campo, valor anterior/novo **sem segredos**, horário) em log.
7. Áreas de **dono** (`/api/v1/dono/*`) só quando `await bot.is_owner(user)`; CSRF + reconfirmação de sessão recente (< 15 min).

Autorização de **usuário** (`/api/v1/eu/*`): apenas sobre o próprio `user_id` da sessão — o `user_id` **nunca** vem do cliente.
Proteção contra IDOR: nenhum identificador do corpo/URL substitui o contexto da sessão. Além disso, **todo ID de canal, cargo
ou `bot_id` recebido do cliente é validado contra o servidor autorizado** (`guild.get_channel(id)`/`guild.get_role(id)` do
próprio `gid`, e `bot_id` ∈ bots do pool presentes em `gid`); IDs de outro servidor, inexistentes ou do tipo errado →
`422 invalido` sem revelar se existem em outro lugar.

### 4.5 Integração com `BotPool` e DB (multi-bot)

- O painel recebe o `pool` (como `IndexHandler`). Acesso a dados **somente** por `bot.get_data/update_data` e
  `bot.get_global_data/update_global_data` (regra do projeto), via os serviços de § 1.3; nada de `AsyncIOMotorClient`/TinyMongo.
- Campos **por bot** (b) exigem `bot_id` na rota; padrão = primeiro bot de `get_guild_bots` que esteja `is_ready()`.
  Campos **globais** (g) usam qualquer bot do pool como "porta de entrada" (a coleção `global` é a mesma).
- Aplicar efeitos em memória (§ 1.3) em cada serviço; **sem** `asyncio.create_task` solto sem referência (regra do projeto).
- Operações pesadas ou com efeitos no Discord (G-06/G-07/G-15 adicionar) executam como tarefas *async* com retorno de status
  (`202` + polling) ou diretamente com `timeout`; nada de código bloqueante no loop (regra asyncio do projeto).
- Qual bot representa o OAuth: o *client_id/secret* é de **uma** aplicação Discord; padrão = a do primeiro bot do pool
  (`PANEL_OAUTH_CLIENT_ID` vazio → id do bot principal), mas o `client_secret` **não** existe hoje na config: variável nova.

### 4.6 Novas variáveis de ambiente (todas entram em `.example.env` **vazias/seguras**, `config_loader.DEFAULT_CONFIG` e tipagem)

| Variável | Padrão seguro | Descrição |
|---|---|---|
| `PANEL_ENABLED` | `false` | liga o painel (desligado por padrão) |
| `PANEL_BASE_URL` | `""` | URL pública (ex.: `https://bot.exemplo.com`); define redirect `…/painel/callback` e a origem permitida; obrigatória se ligado |
| `PANEL_OAUTH_CLIENT_ID` | `""` | id da aplicação Discord do login (vazio = bot principal) |
| `PANEL_OAUTH_CLIENT_SECRET` | `""` | **segredo**; obrigatório se ligado; nunca em log |
| `PANEL_COOKIE_SECRET` | `""` | **segredo** ≥ 32 bytes; se vazio, gerar aleatório no boot e avisar (sessões não sobrevivem ao restart) |
| `PANEL_SESSION_TTL_HOURS` | `12` | validade absoluta |
| `PANEL_SESSION_IDLE_MINUTES` | `60` | ociosidade máxima |
| `PANEL_TRUST_PROXY` | `false` | confiar em `X-Forwarded-*` |
| `PANEL_INSECURE_COOKIES` | `false` | só dev local em HTTP; recusado se `PANEL_BASE_URL` não for `localhost` |
| `PANEL_ALLOWED_OWNER_IDS` | `""` | opcional: restringe a área de dono (padrão = `OWNER_IDS`) |

Falhar na inicialização (mensagem clara, sem segredo) se `PANEL_ENABLED=true` e faltar `PANEL_BASE_URL` ou
`PANEL_OAUTH_CLIENT_SECRET`. A URL de redirect precisa ser cadastrada no portal do Discord (instrução para `docs/`).

---

## 5. Achados preliminares (pesquisa externa interrompida — repasse ao DeepSearch)

> **Superado por `docs/painel/pesquisa-externa.md`** (DeepSearch Researcher), que confirmou as conclusões: nenhum dashboard pronto
> compatível; adotar Tornado nativo (`OAuth2Mixin` não gera nem valida `state`; `set_secure_cookie`; `xsrf_cookies`) e escrever o
> fluxo OAuth internamente. Tabela mantida só como registro histórico dos meus achados iniciais (via `gh api`, 2026-10-15; nada
> foi clonado, instalado ou executado). Em caso de divergência, vale o `pesquisa-externa.md`.

| Projeto | URL | Licença | Último push | Estrelas | Encaixe (Tornado / mesmo processo) | Observação | Veredito provisório |
|---|---|---|---|---|---|---|---|
| Flask-Discord | https://github.com/weibeu/Flask-Discord | MIT | 2024-09-04 | 177 | não (Flask/WSGI; usa discord.py) | **arquivado** | só inspiração |
| quartcord | https://github.com/Sn1F3rt/quartcord | MIT | 2023-12-30 | 2 | não (Quart/ASGI; discord.py) | fork do Quart-Discord, parado | só inspiração |
| Quart-Nextcord | https://github.com/InvalidLenni/Quart-Nextcord | MIT | 2023-07-08 | 2 | não | nextcord | descartar |
| fastapi-discord | https://github.com/Tert0/fastapi-discord | MIT | 2026-08-04 | 77 | parcial (precisa ASGI = opção B) | ativo | só inspiração / adaptar o fluxo |
| discord-oauth2.py | https://github.com/treeben77/discord-oauth2.py | MIT | 2026-01-12 | 52 | a verificar (wrapper OAuth2 assíncrono?) | ativo; não inspecionei o código | candidata a **adaptar** (ou escrever ~100 linhas) |
| Red-Dashboard | https://github.com/Cog-Creators/Red-Dashboard | **AGPL-3.0** | 2025-03-02 | 77 | não | **arquivado**; AGPL incompatível com incorporação em GPL-2.0 | só inspiração (não copiar) |
| discord-ext-ipc | https://github.com/Ext-Creators/discord-ext-ipc | Apache-2.0 (sinalizar) | 2021-08-28 | 91 | desnecessário (mesmo processo) | **arquivado** | descartar |
| discord-ext-ipcx | https://github.com/No767/discord-ext-ipcx | Apache-2.0 (sinalizar) | 2026-10-15 | 16 | desnecessário | fork mantido | descartar |
| Discord-Bot-Web-Panel | https://github.com/AdarshSudo/Discord-Bot-Web-Panel | **GPL-3.0** (sinalizar) | 2024-05-17 | 1 | — | 1 estrela | descartar |
| tutorial-dashboard | https://github.com/tibue99/tutorial-dashboard | **sem licença** | 2024-04-17 | 19 | não (tutorial) | sem licença = todos os direitos reservados | só leitura/inspiração |
| Authlib | https://github.com/authlib/authlib | BSD-3-Clause | 2026-10-15 | 5433 | a verificar (cliente OAuth2 assíncrono) | candidata a dependência | avaliar vs. escrever à mão |
| requests-oauthlib | https://github.com/requests/requests-oauthlib | ISC | 2025-06-18 | 1772 | usa `requests` (síncrono) | bloquearia o loop | descartar |
| Tornado `auth.OAuth2Mixin` + cookies seguros | https://github.com/tornadoweb/tornado | Apache-2.0 | 2026-10-15 | 22165 | **nativo** (já é dependência) | `authorize_redirect`, `oauth2_request`, `set_secure_cookie`, `xsrf_cookies` (conferido via Context7) | **adotar** (como parte do Tornado) |

Conclusões provisórias:

- **Não há dashboard genérico de bot em Python/disnake/Tornado, mantido e com licença compatível** que possa ser adotado; os
  resultados web foram helpers OAuth2 (Flask/Quart/FastAPI) e tutoriais (um deles com *client secret* hardcoded — não copiar).
- O fluxo OAuth2 do Discord é pequeno (autorizar → trocar código → `/users/@me` e `/users/@me/guilds`); com `aiohttp`/Tornado
  fica em poucas dezenas de linhas testáveis, sem trazer outro framework. **Recomendação: escrever internamente** (usando
  `OAuth2Mixin` de referência), em vez de depender de bibliotecas de terceiros para a superfície mais crítica.
- Pendências que eu havia listado (documentação oficial, PKCE, limites da rota `guilds`, tamanho do status de voz) foram
  **resolvidas pelo DeepSearch** e incorporadas ao § 4 e ao § 6.1. Licenças de qualquer asset vendorizado devem ser conferidas no
  `LICENSE` real antes do reuso (Pico CSS: repositório arquivado em 2026-10-04, versão 2.1.1 final; plano B Simple.css).

---

## 6. Contrato de API (proposta)

Base: `/painel` (páginas) e `/painel/api/v1` (JSON). Todas as respostas `application/json; charset=utf-8`; erros:
`{"erro": {"codigo": "string_estavel", "mensagem": "texto em pt-BR"}}`. Mutáveis exigem cabeçalho `X-XSRFToken` e `Origin` válido.
`G` = autorização de servidor (§ 4.4), `U` = próprio usuário, `D` = dono do bot. Nas tabelas abaixo, as rotas omitem o prefixo
`/painel/api/v1`.

### Autenticação e sessão

| Método e rota | Auth | Descrição |
|---|---|---|
| `GET /painel/login` | — | inicia OAuth (`state`); aceita `?next=` (somente caminho relativo, validado) |
| `GET /painel/callback` | — | conclui OAuth, cria sessão, redireciona |
| `POST /painel/logout` | sessão | revoga token, destrói sessão |
| `GET /sessao` | sessão | `{usuario:{id,nome,avatar}, e_dono:bool, expira_em}` |
| `GET /saude` | — | `{"ok": true}` (sem dados internos) |

### Servidores

| Método e rota | Auth | Descrição |
|---|---|---|
| `GET /servidores` | sessão | servidores do usuário **onde ele é gestor** e **onde há bot**; os demais gestores aparecem com `bot_presente:false` + links de convite (G-19) |
| `GET /servidores/{gid}` | G | resumo: nome, ícone, bots presentes `[ {id,nome,avatar} ]`, estado do player (`ativo`, `canal`) |
| `GET /servidores/{gid}/recursos` | G | listas auxiliares: cargos, canais (texto/voz/fórum/palco), skins disponíveis (normal/static), limites vindos de `bot.config` |
| `GET /servidores/{gid}/config` | G | todas as opções do servidor (G-01…G-16 editáveis) num só objeto; query `?bot_id=` |
| `PATCH /servidores/{gid}/player` | G | G-01…G-04 `{volume_padrao, autoplay, evitar_outros_bots, modo_restrito}` (`bot_id`) |
| `PUT /servidores/{gid}/dj-cargos` | G | G-05 `{cargos:[id…]}` (substitui a lista; valida existência) |
| `PATCH /servidores/{gid}/skins` | G | G-08…G-11 `{normal, song_request, global_ativa, global_normal, global_song_request}` |
| `PATCH /servidores/{gid}/prefixo` | G | G-12 `{prefixo: "…"|""}` |
| `PUT /servidores/{gid}/status-voz` | G | G-13 `{modelo: "…"|""}` |
| `GET/POST /servidores/{gid}/links` · `PUT/DELETE …/links/{nome}` · `POST …/links:importar` | G | G-16 CRUD (máx. 25; precisa de player configurado) |
| `GET /servidores/{gid}/ouvir-junto` · `DELETE …/ouvir-junto/{canal}` | G | G-15 listar/remover (adicionar: v1.1, exige `fetch_invite`) |
| `POST /servidores/{gid}/canal-player` | G | G-06 setup `{canal_id|null (criar), limpar_mensagens, titulo_forum?}` → `202` + `{tarefa_id}` |
| `DELETE /servidores/{gid}/canal-player` | G | G-07 reset `{deletar_canal:bool}` (confirmação no cliente + `?confirmar=1`) |
| `GET /tarefas/{id}` | sessão (dono da tarefa) | status das ações longas |

### Usuário

| Método e rota | Auth | Descrição |
|---|---|---|
| `GET /eu/config` | U | U-01…U-05 (segredos mascarados) |
| `PATCH /eu/prefixo` | U | U-01 |
| `GET/POST /eu/favoritos` · `PUT/DELETE …/{nome}` · `POST …:importar` | U | U-02 (limites do dono) |
| `GET /eu/integracoes` · `DELETE …/{titulo}` · `POST …:importar` | U | U-03 (adicionar por URL: fase posterior) |
| `PATCH /eu/lastfm` | U | U-04 `{scrobble:bool}` (requer conta vinculada) |
| `POST /eu/rpc-token:regenerar` | U | U-05 devolve o valor **uma única vez** (decisão D-4) |

### Dono

| Método e rota | Auth | Descrição |
|---|---|---|
| `GET /dono/config` | D | as 101 chaves com segredos **mascarados** (`configurado:true`) |
| `GET /dono/bots` | D | bots do pool: id, nome, servidores, latência, Lavalink |
| `POST /dono/acoes/{recarregar-config\|recarregar-skins}` | D | O-1, O-2 (lista fechada; sem `shell`/`update`/`exportsource`) |

Convenções: IDs de Discord como **string** no JSON (evita perda de precisão); paginação onde houver listas longas;
`ETag`/`If-Match` nos `GET/PATCH` de `config` para detectar edição concorrente (resposta `412` + valor atual).

### 6.1 Extensões acordadas com o Frontend (ver `pesquisa-frontend.md` §3.8)

Todas aceitas; a forma final dos corpos é esta (campos em pt-BR, IDs Discord como string):

| # | Pedido | Decisão |
|---|---|---|
| a | `GET /servidores/{gid}/config` agrupado | **Aceito:** `{"por_bot": {…G-01..G-11 (campos b), G-16…}, "globais": {prefixo, status_voz, skin_global…, ouvir_junto}, "bot_id": "…", "etag": "…"}`. O `ETag` também vai no cabeçalho; `PATCH` usa `If-Match` (`412` = recarregar). Um `etag` por grupo (`por_bot` por `bot_id`, `globais`) para não invalidar tudo |
| b | `recursos.permissoes_bot` | **Aceito:** `{gerenciar_canais, gerenciar_mensagens, gerenciar_threads}` (bool) lidos de `guild.me.guild_permissions` do bot selecionado — só informativo; o servidor revalida na ação |
| c | `recursos.skins` | **Aceito:** `[{id, nome, modo: "normal"\|"song_request", preview_url}]`, já filtradas por `IGNORE_SKINS`/`IGNORE_STATIC_SKINS`; `preview_url` vem de `bot.player_skins[s].preview` (a ser migrado para `asset_url` pela Fase 1); skins `> custom_skin:` **não** são listadas (G-14 fora da v1) |
| d | `recursos.status_voz` | **Aceito:** `{placeholders: [{token, descricao}], tamanho_max: 500}`; `placeholders` extraídos do texto de ajuda do `SetStageTitle`/`music.py`; 500 é o limite do Discord para o status de canal de voz (confirmado pelo DeepSearch). Como o modelo tem variáveis, o servidor valida o tamanho **após expandir** com valores de exemplo e limita o modelo de forma conservadora (o limite aplicado hoje no modal não foi conferido) |
| e | `GET /tarefas/{id}` | **Aceito:** `{estado: "pendente"\|"executando"\|"ok"\|"erro", etapa?, total_etapas?, mensagem?}`; só o usuário que criou a tarefa a lê; tarefas expiram em 15 min; estado em memória (some no restart) |
| f | `GET /servidores` | **Aceito:** `[{id, nome, icone, bot_presente, bots: [{id, nome, convite_url}]}]`; `convite_url` montado como `https://discord.com/oauth2/authorize?client_id=<id>&scope=bot%20applications.commands&permissions=<INVITE_PERMISSIONS>&guild_id=<gid>&disable_guild_select=true` (formato confirmado pelo DeepSearch; `guild_id` chega ao retorno só como dica); só para servidores em que o usuário é gestor |
| g | `erro.campo` | **Aceito:** `{"erro": {"codigo", "mensagem", "campo"?}}`; códigos estáveis: `nao_autenticado` (401), `sem_permissao` (403), `nao_encontrado` (404), `conflito_versao` (412), `invalido` (422, com `campo`), `limite_taxa` (429, com `Retry-After`), `indisponivel` (503) |
| h | `recursos.limites` | **Aceito:** `{links:{max:25}, ouvir_junto:{max:5}, prefixo:{min:1,max:5}, favoritos:{max}, integracoes:{max}, nome:{max}, url:{max}}` lidos de `bot.config` (`MAX_USER_FAVS`, `MAX_USER_INTEGRATIONS`, `USER_FAV_MAX_NAME_LENGTH`, `USER_FAV_MAX_URL_LENGTH`); valor `0` do bot ("ilimitado") é enviado como `null` |
| i | `ouvir-junto` com `canal_nome` | **Aceito:** `[{canal_id, canal_nome, convite_url}]`; canal que não existe mais vem com `canal_nome: null` e `existe: false` |

Rotas de página alinhadas (Tornado): `/painel/login`, `/painel/callback`, `/painel/logout`, `/painel/servidores/{gid}/{categoria}`
(`player`, `canal`, `dj`, `aparencia`, `links`, `global`), `/painel/conta`, `/painel/dono`. As páginas renderizam usando a **mesma
camada de serviços** da API (sem chamar a própria API por HTTP). Requisitos de segurança desta decisão: `<meta name="xsrf-token">`
na página, CSP `script-src 'self'` sem inline/eval, módulo JS próprio servido de `/painel/static/` (sem CDN).

---

## 7. Plano de testes sugerido (para o QA, RED primeiro)

1. **Unidade (sem rede/Discord):** serviços G-01…G-16/U-01…U-04 com `LocalDatabase` em `tmp_path` e dublês de `BotCore`; limites e
   erros idênticos aos dos comandos; teste de **caracterização** do KI-09 (listas) e do cache de prefixo.
2. **OAuth:** `state` inválido/expirado/reutilizado, `redirect_uri` fixo, `error=access_denied`, troca de código com `aiohttp`
   simulado, token nunca em log, revogação no logout.
3. **Autorização:** matriz usuário × servidor × permissão (dono do servidor, admin, `manage_guild`, membro comum, sem bot, ID de
   outro servidor, IDOR em `/eu/*`); revogação de cargo entre duas requisições.
4. **Web:** CSRF (sem token, `Origin` errado), cabeçalhos de segurança, cookies (`Secure/HttpOnly/SameSite`, `__Host-`),
   limite de tamanho, esquema estrito, rate limit, erros genéricos.
5. **Integração:** `AsyncHTTPTestCase` montando `PainelApplication` + `web_app.run_app` (rotas `/`, `/ws` inalteradas).
6. **Segurança estática:** nenhum `pickle`, `eval`, `shell=True`; `bandit` no pacote `panel/`.

---

## 8. Riscos e decisões de projeto

| # | Risco / decisão | Mitigação |
|---|---|---|
| R1 | Escrita concorrente painel × comando (documento inteiro) | alterar só o campo; trava por `(coleção,id)`; ETag |
| R2 | Formato legado inseguro das skins personalizadas (S-04, privado) | G-14 fora da v1; migração própria para JSON validado |
| R3 | KI-09 apaga listas ao subir `ver` | painel nunca sobe `ver`; corrigir KI-09 antes de qualquer migração |
| R4 | Cache de membros incompleto (servidor grande, pós-boot) | `get_member` (cache) → fallback `fetch_member` (REST) com cache curto; negar se ambos falharem |
| R5 | Painel e `/ws` na mesma porta | sub-aplicação isolada; cookies `__Host-`; endurecimento do `/ws` rastreado em privado (S-02) |
| R6 | Bloqueio do loop por código síncrono | regra do projeto; `run_in_executor` quando inevitável |
| R7 | Segredos (`client_secret`, `cookie_secret`) | só variáveis de ambiente; validação no boot; nunca em log; `.example.env` vazio |
| R8 | Hospedagens de porta única (Render/Replit/Discloud) | opção (A) atende; (B) não |
| R9 | Mensagens e menções reenviadas | `AllowedMentions.none()`; escape de markdown |
| R10 | Antigo campo órfão de prefixo | campo removido do modelo na versão 1.11 (KI-43) |
| R11 | `setguildprefix` usa `ctx.guild.id` no cache (bug) | não replicar; abrir item de backlog |

---

## 9. Dúvidas para o dono

1. **Hospedagem:** o painel pode ficar sob a `PORT` do bot em `/painel` (recomendado) ou o dono prefere outra porta/domínio? Há
   domínio HTTPS (proxy reverso) disponível? Sem HTTPS, não há como ligar cookies `Secure`/OAuth em produção.
2. **Qual aplicação Discord faz o login** (e guarda o `client_secret`)? Padrão proposto: a do bot principal. O redirect
   `https://<domínio>/painel/callback` precisa ser cadastrado no portal.
3. **Sessões:** aceitar que sumam quando o bot reinicia (mais seguro, mais simples) ou persistir no DB?
4. **Token de RPC (U-05):** o painel pode *gerar novo token* (mostrando uma vez) ou prefere manter esse fluxo só no Discord?
5. **Skins personalizadas (G-14):** ficam fora da v1 até migrar o armazenamento legado para JSON validado (S-04, privado) — de acordo?
6. **Área de dono:** v1 apenas leitura (+ recarregar configs/skins) — ou o dono quer editar `.env` pela web (não recomendado)?
7. **Múltiplos bots:** na tela de servidor, mostrar um seletor de bot para os campos por bot, ou aplicar ao "bot ativo" do servidor?
8. **Idiomas:** só pt-BR na v1?
9. **PKCE:** manter só `state` + `client_secret` na v1 (suficiente para cliente confidencial) ou adicionar PKCE como defesa em profundidade?

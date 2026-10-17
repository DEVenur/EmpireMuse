# Problemas conhecidos (backlog técnico)

Lista de bugs e riscos **não corrigidos**, verificados no código em 2026-10-14. Cada item traz o local
(`arquivo:linha`), o impacto e a severidade. Os números de linha mudam com o código: confirme antes de
corrigir. Escopo: esta fase é só documentação — nada aqui foi alterado.

**Severidade:** *crítico* (quebra o uso básico/perde dados de forma geral) · *alto* (recurso importante
quebrado ou perda de dados em cenário comum) · *médio* (comportamento incorreto com contorno) · *baixo*
(qualidade, desperdício ou risco futuro).

> **Itens de segurança:** ver `SECURITY.md` (rastreados em privado). Não são listados aqui.

## Resumo

| Área | Itens | Mais grave |
|---|---|---|
| Instalação e implantação | KI-01 … KI-05 | alto |
| Configuração | KI-06 … KI-08 | médio |
| Banco de dados | KI-09 … KI-10 | alto |
| Pool de bots e inicialização | KI-11 … KI-14 | médio |
| Spotify | KI-15 … KI-20 | alto |
| Player e busca de faixas | KI-21 … KI-22 | médio |
| Cliente Lavalink (`empiremuse/wavelink/`) e Lavalink local | KI-23 … KI-24 | médio |
| Servidor web / RPC (robustez) | KI-25 … KI-26 | médio |
| Qualidade, testes e modernização | KI-27 … KI-31 | alto |
| Identidade, guias e testes de marca (Fase 1) | KI-32 … KI-35 | baixo |
| Painel web e comandos relacionados (saneamento) | KI-36 … KI-43 | médio |

## Instalação e implantação

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-01 | `requirements.txt` (`tinymongo`), `empiremuse/utils/db.py` (import de `tinydb_serialization`) | [Resolvido] `tinymongo` sem o extra `serialization`, mas `empiremuse/utils/db.py` importa `tinydb_serialization`. | Resolvido na Fase 3 (F3-1): o `requirements.txt` declara o extra `serialization`. | alto |
| KI-02 | `.Dockerfile` | [Resolvido] Imagem com `python:3.10-slim` e OpenJDK 11, desatualizada e incompatível com o runtime Python 3.13 e Lavalink atual. | Resolvido no Bloco D1 (remoção do `.Dockerfile` legado e artefatos de deploy obsoletos; padronização com Dockerfile moderno na Fase D). | baixo |
| KI-03 | `render.yaml` | [Resolvido] Arquivo de deploy de terceiros legado. | Resolvido no Bloco D1 (remoção completa de artefatos legados de plataformas como Render, Replit, Gitpod e scripts `source_*`). | baixo |
| KI-04 | `BotPool.shutdown` (`empiremuse/utils/client.py`), `empiremuse/cogs/error_handler.py` | [Resolvido] O reinício do processo é feito com `kill 1` (PID 1 do contêiner). | Resolvido no Bloco D1: reinício por encerramento ordenado do pool e saída com código de retorno, deixando o supervisor (Docker/systemd) reiniciar o processo. | baixo |
| KI-05 | `requirements.txt` | [Resolvido] Dependências declaradas e **sem nenhum `import`** no código: `aiosqlite`, `syncedlyrics`, `pylrc`, `undetected-chromedriver`, `nest_asyncio`, `curl_cffi`, `emoji`, `regex`. (`nodriver` é usado em `empiremuse/utils/music/youtube_trusted_session_generator.py`.) | Resolvido no Bloco C2 (expurgo de 8 dependências obsoletas em `requirements.txt`). | baixo |

## Configuração

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-06 | `empiremuse/config_loader.py` (`bools`, `load_config`) | A tabela de booleanos só tem chaves em minúsculas; `bools[CONFIG[i]]` não normaliza o valor. | `FLAG=True` ou `FLAG=FALSE` aborta a inicialização com "configuração inválida". | médio |
| KI-07 | `empiremuse/config_loader.py` (`load_config`), `empiremuse/cogs/music.py` (`Music.node_reconnect`) | `LAVALINK_RECONNECT_RETRIES < 5` vira `0`, e `0` é tratado como "sem limite" em `Music.node_reconnect`. | Quem configura 1–4 tentativas obtém tentativas **infinitas**. | médio |
| KI-08 | `empiremuse/config_loader.py` (`load_config`) | `except:` nu ao ler o `.env`. | Erros de leitura do `.env` são engolidos silenciosamente. | baixo |

## Banco de dados

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-09 | `empiremuse/utils/db.py` (`update_values`) | [Resolvido] `update_values` ignora valores do tipo lista (`elif not isinstance(v, list)`) ao migrar a versão do esquema. | Resolvido na Fase 3 (F3-1): a migração preserva listas e chaves do usuário. | alto |
| KI-10 | `empiremuse/utils/db.py` (`LocalDatabase.update_data`) | `LocalDatabase.update_data` captura qualquer exceção, imprime e segue, atualizando o cache como se tivesse gravado. | Falha de gravação no TinyMongo fica invisível; o dado some após o cache expirar. | médio |

## Pool de bots e inicialização

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-11 | `empiremuse/utils/client.py` (`BotPool.setup`) | No `except KeyError`, `self.guild_bots = {guild_id: [bot]}` **substitui** o dicionário inteiro. | Com `guild_bots.json` com vários servidores, só o último continua registrado (os demais perdem seus bots exclusivos em `get_guild_bots`). | médio |
| KI-12 | `empiremuse/utils/client.py` (`BotPool.__init__`, `BotPool.reset_useragent`) | `reset_useragent` atribui a `self.current_useragent` mas **não retorna** nada; `__init__` reatribui o resultado (`None`). | `current_useragent` fica `None` na inicialização. Hoje o uso está comentado em `empiremuse/cogs/music.py`. | baixo |
| KI-13 | `empiremuse/utils/client.py` (`BotPool.start_bot`) | A condição usa `str(e)` com `e = None` (deveria ser `error`), e `raise e` levanta `TypeError` quando `e` é `None`. | Com `KILL_ON_429=false`, o tratamento de rate limit do Discord falha com `TypeError` em vez de propagar o erro original. | médio |
| KI-14 | `empiremuse/utils/client.py` (`BotPool.start_lavalink`); `empiremuse/utils/music/local_lavalink.py` (`_java_command`, `run_lavalink`) | `LAVALINK_CPU_CORES` nunca é repassado a `run_lavalink` (usa o padrão `1`), e `-Xms` recebe `lavalink_ram_limit` em vez de `lavalink_initial_ram`. | Configurações de CPU e RAM inicial do Lavalink local não têm efeito. | baixo |

## Spotify (`empiremuse/utils/music/audio_sources/spotify.py`)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-15 | `empiremuse/utils/music/audio_sources/spotify.py` (`SpotifyClient.get_access_token`) | [Resolvido] Em erro de token, `get_access_token` zera as credenciais e chama a si mesma, mas `token_refresh` ainda é `True`: a chamada entra no laço `while self.token_refresh` e **espera para sempre**. | Resolvido na Fase 3 (F3-1): credenciais inválidas do Spotify geram erro claro, sem travar. | alto |
| KI-16 | `empiremuse/utils/music/audio_sources/spotify.py` (`SpotifyClient.get_playlist_info`) | Páginas extras começam em `offset = 101`; a primeira página já traz os itens 0–99. | A 101ª faixa (índice 100) de playlists grandes é pulada. | médio |
| KI-17 | `empiremuse/utils/music/audio_sources/spotify.py` (`SpotifyClient.get_playlist_info`) | Condição `page_count <= playlist_extra_page_limit` (deveria ser `<`). | Carrega uma página extra além do limite configurado. | baixo |
| KI-18 | `empiremuse/utils/music/audio_sources/spotify.py` (`SpotifyClient.track_search`) | `quote(query)` é aplicado antes de passar `params=` ao aiohttp, que codifica de novo. | Buscas com espaços/acentos/símbolos são enviadas com dupla codificação e retornam resultado ruim. | médio |
| KI-19 | `empiremuse/utils/music/audio_sources/spotify.py` (`SpotifyClient.get_valid_access_token`, `SpotifyClient.get_access_token`) | `get_valid_access_token` lê `spotify_cache["expires_at"]` sem checar; com cache vazio dá `KeyError`. Além disso, a chave é gravada como `"tyoe"` (typo de `"type"`). | Falha na primeira requisição se o token ainda não foi obtido; chave com nome errado no cache. | médio |
| KI-20 | `empiremuse/utils/music/audio_sources/spotify.py` (`SpotifyClient.get_playlist_info`) | Importação de playlist usa `playlists/{id}` e `playlists/{id}/tracks`. Segundo o briefing (mudança da API do Spotify em fev/2026), playlists de terceiros podem não ser mais acessíveis com *client credentials*. **Ainda não testado com credenciais reais.** | Importação de playlists públicas pode estar quebrada. | a confirmar (pendente de teste com credenciais reais) |

## Player e busca de faixas (`empiremuse/utils/music/models.py`)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-21 | `empiremuse/utils/music/models.py` (`LavalinkPlayer._process_next`, `LavalinkPlayer.get_autoqueue_tracks`) | `if not [i in titulo for i in exclude_tags]:` testa uma lista (sempre "verdadeira" se houver tags), então a condição nunca é satisfeita e o filtro por tags não executa. | Resultados com "remix", "edit", "mashup" etc. não são deprioritizados ao resolver faixas do Spotify/Deezer. | médio |
| KI-22 | `empiremuse/utils/music/models.py` (`LavalinkPlayer._process_next`) | `A or not B and C` é lido como `A or ((not B) and C)`: o filtro só descarta quando a duração está fora da faixa **e** o título é diferente. | Aceita faixa com duração correta e título errado, e faixa com título parecido e duração errada. | médio |

## Cliente Lavalink e Lavalink local

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-23 | `empiremuse/wavelink/player.py` (`Player.change_node`) | `node.is_available` é lido antes de checar `if not node`. | `AttributeError` ao trocar para um identificador de node inexistente, em vez da mensagem amigável. | médio |
| KI-24 | `empiremuse/utils/music/local_lavalink.py` (`_find_or_install_java`) | `os.environ["JAVA_HOME"] + "bin/java"` sem separador. | `JAVA_HOME` nunca é aproveitado (caminho inválido); o bot cai no download de um JDK. | médio |

## Servidor web e RPC (robustez)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-25 | `empiremuse/web_app.py` (`WebSocketHandler.on_close`) | `bots_ws.remove(self)` executa para conexões que nunca entraram em `bots_ws`. | `ValueError` no fechamento de conexões anônimas (ruído de log). | baixo |
| KI-26 | `empiremuse/web_app.py` (`WebSocketHandler.on_message`) | `json.loads(message)` sem `try`/`except`. | Mensagem malformada gera exceção não tratada no handler do WebSocket. | médio |

## Qualidade, testes e modernização

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-27 | `tests/` | **Cobertura mínima de testes**: existem apenas testes de identidade/guarda de marca (`tests/test_branding.py`), do filtro de URLs do Discord e do carregador da lista Lavalink. Faltam testes de caracterização do núcleo (player, filas, comandos, banco) em ~34,5 mil linhas de Python; planejados para a fase de saneamento. | Refatorações do núcleo continuam sem rede de proteção. | alto |
| KI-28 | `empiremuse/` (`cogs/`, `utils/`, `wavelink/`, `web_app.py`, `config_loader.py`) | ~365 ocorrências de `except:` nu. | Erros reais são engolidos; inclui `KeyboardInterrupt`/cancelamentos de tasks. | médio |
| KI-29 | `empiremuse/cogs/music.py` (8.688 linhas), `empiremuse/utils/music/models.py` (4.018), `empiremuse/utils/music/interactions.py` (3.534) | Arquivos muito grandes e com muitas responsabilidades. | Revisão e teste difíceis. | médio |
| KI-30 | `requirements.txt` (`disnake`, `jishaku`) | `disnake` e `jishaku` fixados em commits Git (o `disnake` é anterior à 2.12.0; há 2.12.2 estável). Demais pacotes sem versão fixa e sem *lockfile*. | Builds não reproduzíveis e dependência de repositórios Git externos. | médio |
| KI-31 | `empiremuse/utils/client.py` (`BotPool.setup`) | Uso de `datetime.datetime.utcnow()` (obsoleto desde o Python 3.12). | Avisos de depreciação e remoção futura. | baixo |

## Identidade, guias e testes de marca (Fase 1)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-32 | `docs/guides/*.md` | Os guias ainda usam capturas de tela hospedadas no CDN do Discord e no GitHub do upstream. | As imagens podem expirar ou sumir. Migrar para `assets/` ou arte própria. | baixo |
| KI-33 | `empiremuse/utils/client.py` (`BotPool.setup`) | A URL do remote é extraída por fatiamento fixo da saída de `git remote -v` (assume o remote `origin`). | Resultado incorreto com outro nome de remote ou formato de saída. Trocar por *parsing* por campos. | baixo |
| KI-34 | `tests/test_branding.py` | As varreduras estáticas dependem de `git ls-files` (exigem `.git`) e usam correspondência por substring. | Falham fora de um clone Git e podem gerar falsos positivos/negativos. Revisar no saneamento. | baixo |
| KI-35 | `empiremuse/utils/branding.py`, `assets/`, `data/lavalink_servers.ini` | Assets e a lista de servidores Lavalink são servidos via `raw.githubusercontent.com` da branch `main`. | Forks de terceiros continuam apontando para a DiscordEmpireHub até ajustarem `empiremuse/utils/branding.py` (informativo). | baixo |

## Painel web e comandos relacionados (saneamento)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-36 | `empiremuse/utils/music/request_channel.py` (e `empiremuse/cogs/music_settings.py`) | `/reset`: limpa o banco de dados antes de executar as exclusões no Discord. | Se ocorrer falha no Discord durante o reset com opção de deletar canal, o banco é desconfigurado mas o canal permanece, gerando estado parcial inconsistente. | médio |
| KI-37 | `empiremuse/utils/music/request_channel.py` (e `empiremuse/cogs/music_settings.py`) | `/setup` de fórum: chamada a `post.edit()` sem nenhum argumento. | Gera requisição inútil à API do Discord sem efetuar nenhuma alteração de estado no post. | baixo |
| KI-38 | `empiremuse/utils/music/request_channel.py` | `validate_request_target`: checagem redundante de permissão de leitura de mensagens (`view_channel`). | Verificação repetida da mesma permissão em etapas sucessivas da validação de destino. | baixo |
| KI-39 | `empiremuse/utils/music/interactions.py` | Modal de adicionar favorito não replica as exceções de `MAX_USER_FAVS=0` e isenção do dono; modal de adicionar integração usa indevidamente o limite de favoritos. | Donos do bot e instâncias sem limite são impedidos de adicionar favoritos via modal; cadastro de integrações é limitado pela cota de favoritos em vez de `MAX_USER_INTEGRATIONS`. | médio |
| KI-40 | `empiremuse/cogs/music_settings.py`, `empiremuse/utils/music/interactions.py` | Importador de integrações do comando não aceita o formato JSON gerado pelo próprio exportador. | O exportador gera objetos com `url` e `avatar`, enquanto o importador do comando só aceita strings simples, quebrando a restauração de backups via comando. | médio |
| KI-41 | `empiremuse/cogs/music_settings.py`, `empiremuse/utils/music/interactions.py` | Importador de links rápidos do servidor aceita itens `> fav:` sem validar a URL. | Permite a persistência de links com URLs inválidas ou malformadas no banco de dados através da importação de arquivo. | baixo |
| KI-42 | `empiremuse/cogs/music_settings.py`, `empiremuse/cogs/music.py` | Cogs ainda possuem implementações próprias de regras em vez de utilizarem `empiremuse/panel/services/`. | Duplicação de código de regras de negócio entre comandos slash e interface web, dificultando manutenção e gerando risco de assimetrias. | médio |
| KI-43 | `empiremuse/cogs/legacy_cmds.py` (`Owner.setguildprefix`), `empiremuse/utils/client.py` (`BotPool.guild_prefix_cache`), `empiremuse/utils/db.py` (`default_model`) | `setguildprefix` grava o cache com identificador incorreto; campo de configuração órfão `enable_prefixed_commands`. | Invalidação falha no cache em memória de prefixos do pool ao usar o comando legado; presença de campo de configuração sem nenhuma utilidade no código. | baixo |

## Como usar este backlog

1. Antes de corrigir, escreva um teste que reproduza o problema (TDD) — ver
   `.claude/rules/empiremuse/python-disnake.md`.
2. Referencie o ID (`KI-xx`) na mensagem de commit/PR e no `CHANGELOG.md`.
3. Ao concluir, remova o item daqui (ou marque-o como corrigido, com o commit).

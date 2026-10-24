# Problemas conhecidos (backlog técnico)

Lista de bugs e riscos **não corrigidos**, verificados no código em 2026-10-14. Cada item traz o local
(`arquivo:linha`), o impacto e a severidade. Os números de linha mudam com o código: confirme antes de
corrigir. Escopo: esta fase é só documentação — nada aqui foi alterado.

**Severidade:** *crítico* (quebra o uso básico/perde dados de forma geral) · *alto* (recurso importante
quebrado ou perda de dados em cenário comum) · *médio* (comportamento incorreto com contorno) · *baixo*
(qualidade, desperdício ou risco futuro).

> **Itens de segurança:** ver [`.github/SECURITY.md`](../.github/SECURITY.md) (rastreados em privado). Não são listados aqui.

## Resumo

| Área | Itens | Mais grave |
|---|---|---|
| Instalação e implantação | KI-01 … KI-05 | alto |
| Configuração | KI-06 … KI-08, KI-55 | médio |
| Banco de dados | KI-09 … KI-10, KI-57 … KI-58 | alto |
| Pool de bots e inicialização | KI-11 … KI-14 | médio |
| Spotify | KI-15 … KI-20, KI-56 | alto |
| Player e busca de faixas | KI-21 … KI-22, KI-44 | médio |
| Cliente Lavalink (`empiremuse/wavelink/`) e Lavalink local | KI-23 … KI-24 | médio |
| Servidor web / RPC (robustez) | KI-25 … KI-26 | médio |
| Qualidade, testes e modernização | KI-27 … KI-31, KI-29b | alto |
| Identidade, guias e testes de marca (Fase 1) | KI-32 … KI-35 | baixo |
| Painel web e comandos relacionados (saneamento) | KI-36 … KI-43, KI-45 … KI-54 | médio |

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
| KI-06 | `empiremuse/config_loader.py` (`bools`, `load_config`) | [Resolvido] A tabela de booleanos só tem chaves em minúsculas; `bools[CONFIG[i]]` não normaliza o valor. | Resolvido na Fase 3 (F3-2): booleanos do ambiente/.env/config.json são normalizados para minúsculas e aceitam qualquer combinação de maiúsculas/minúsculas. | médio |
| KI-07 | `empiremuse/config_loader.py` (`load_config`), `empiremuse/cogs/music.py` (`Music.node_reconnect`) | [Resolvido] `LAVALINK_RECONNECT_RETRIES < 5` vira `0`, e `0` é tratado como "sem limite" em `Music.node_reconnect`. | Resolvido na Fase 3 (F3-2): tentativas entre 1 e 4 são respeitadas, 0 permanece como sem limite e valores negativos geram erro claro. | médio |
| KI-08 | `empiremuse/config_loader.py` (`load_config`) | [Resolvido] `except:` nu ao ler o `.env`. | Resolvido na Fase 3 (F3-2): captura apenas OSError e UnicodeError com aviso em log citando o caminho, sem engolir nem vazar o conteúdo. | baixo |
| KI-55 | `empiremuse/config_loader.py` (`load_config`) | [Resolvido] 0 no config.json trocado pelo padrão. | Resolvido na Fase 3 (F3-6): valor 0 inteiro é respeitado nas chaves inteiras, usando padrão só quando ausente ou vazio. | baixo |

## Banco de dados

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-09 | `empiremuse/utils/db.py` (`update_values`) | [Resolvido] `update_values` ignora valores do tipo lista (`elif not isinstance(v, list)`) ao migrar a versão do esquema. | Resolvido na Fase 3 (F3-1): a migração preserva listas e chaves do usuário. | alto |
| KI-10 | `empiremuse/utils/db.py` (`LocalDatabase.update_data`) | [Resolvido] `LocalDatabase.update_data` captura qualquer exceção, imprime e segue, atualizando o cache como se tivesse gravado. | Resolvido na Fase 3 (F3-2): falhas de gravação sobem como erro, o cache só atualiza após gravação e documentos novos usam upsert. | médio |
| KI-57 | `empiremuse/serialization/legacy_pickle.py` (`load_legacy`), `empiremuse/utils/music/legacy_reader.py` | Leitor do formato antigo de serialização mantido durante o período de transição. | O leitor legado sai na versão N+2 após a conclusão da migração dos dados legados para JSON. | baixo |
| KI-58 | Ambiente de execução (`PYTHONHASHSEED`) | Fixação da variável `PYTHONHASHSEED` no ambiente de execução. | O operador não deve fixar `PYTHONHASHSEED` no ambiente por segurança do leitor do formato antigo. | baixo |

## Pool de bots e inicialização

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-11 | `empiremuse/utils/client.py` (`BotPool.setup`) | [Resolvido] No `except KeyError`, `self.guild_bots = {guild_id: [bot]}` **substitui** o dicionário inteiro. | Resolvido na Fase 3 (F3-2): registro correto com setdefault mantendo múltiplos servidores e listas isoladas por instância do pool. | médio |
| KI-12 | `empiremuse/utils/client.py` (`BotPool.__init__`, `BotPool.reset_useragent`) | [Resolvido] `reset_useragent` atribui a `self.current_useragent` mas **não retorna** nada; `__init__` reatribui o resultado (`None`). | Resolvido na Fase 3 (F3-2): reset_useragent retorna o user-agent gerado em vez de None. | baixo |
| KI-13 | `empiremuse/utils/client.py` (`BotPool.start_bot`) | [Resolvido] A condição usa `str(e)` com `e = None` (deveria ser `error`), e `raise e` levanta `TypeError` quando `e` é `None`. | Resolvido na Fase 3 (F3-2): com KILL_ON_429=false a condição verifica o erro recebido e propaga a exceção original da API do Discord. | médio |
| KI-14 | `empiremuse/utils/client.py` (`BotPool.start_lavalink`); `empiremuse/utils/music/local_lavalink.py` (`_java_command`, `run_lavalink`) | [Resolvido] `LAVALINK_CPU_CORES` nunca é repassado a `run_lavalink` (usa o padrão `1`), e `-Xms` recebe `lavalink_ram_limit` em vez de `lavalink_initial_ram`. | Resolvido na Fase 3 (F3-2): LAVALINK_CPU_CORES é repassado ao subprocesso e -Xms usa LAVALINK_INITIAL_RAM corretamente. | baixo |

## Spotify (`empiremuse/utils/music/audio_sources/spotify.py`)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-15 | `empiremuse/utils/music/audio_sources/spotify.py` (`SpotifyClient.get_access_token`) | [Resolvido] Em erro de token, `get_access_token` zera as credenciais e chama a si mesma, mas `token_refresh` ainda é `True`: a chamada entra no laço `while self.token_refresh` e **espera para sempre**. | Resolvido na Fase 3 (F3-1): credenciais inválidas do Spotify geram erro claro, sem travar. | alto |
| KI-16 | `empiremuse/utils/music/audio_sources/spotify.py` (`SpotifyClient.get_playlist_info`) | [Resolvido] Páginas extras começam em `offset = 101`; a primeira página já traz os itens 0–99. | Resolvido na Fase 3 (F3-3): a segunda página de playlist começa em offset=100, sem pular a faixa de índice 100. | médio |
| KI-17 | `empiremuse/utils/music/audio_sources/spotify.py` (`SpotifyClient.get_playlist_info`) | [Resolvido] Condição `page_count <= playlist_extra_page_limit` (deveria ser `<`). | Resolvido na Fase 3 (F3-3): o laço carrega exatamente o limite configurado de páginas extras e para quando não há próxima página. | baixo |
| KI-18 | `empiremuse/utils/music/audio_sources/spotify.py` (`SpotifyClient.track_search`) | [Resolvido] `quote(query)` é aplicado antes de passar `params=` ao aiohttp, que codifica de novo. | Resolvido na Fase 3 (F3-3): aiohttp recebe a query crua em params= sem codificação dupla, preservando acentos e símbolos. | médio |
| KI-19 | `empiremuse/utils/music/audio_sources/spotify.py` (`SpotifyClient.get_valid_access_token`, `SpotifyClient.get_access_token`) | [Resolvido] `get_valid_access_token` lê `spotify_cache["expires_at"]` sem checar; com cache vazio dá `KeyError`. Além disso, a chave é gravada como `"tyoe"` (typo de `"type"`). | Resolvido na Fase 3 (KeyError na F3-1; typo "tyoe" corrigido para "type" na F3-3 mantendo compatibilidade com caches antigos). | médio |
| KI-20 | `empiremuse/utils/music/audio_sources/spotify.py` (`SpotifyClient.get_playlist_info`) | [Resolvido] Importação de playlist usa `playlists/{id}` e `playlists/{id}/tracks`; com *client credentials*, a Web API do Spotify omite `tracks` em `playlists/{id}` e retorna 403/404 em playlists editoriais. | Resolvido: erros 403 e 404 da API geram mensagens claras em português (F3-3) e `get_playlist_info` faz fallback automático para o JSON de embed público (`open.spotify.com/embed/playlist/{id}`) quando `tracks` não vem na resposta da API ou em 403/404. | alto |
| KI-56 | `empiremuse/utils/music/audio_sources/spotify.py`, `empiremuse/rules/ratelimit.py` | [Resolvido] 429 do Spotify desativava o suporte até reiniciar. | Resolvido na Fase 3 (F3-6): cliente pausa temporariamente apenas pelo período do Retry-After (1 s a 1 h) e retoma automaticamente. | médio |

## Player e busca de faixas (`empiremuse/utils/music/models.py`)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-21 | `empiremuse/utils/music/models.py` (`LavalinkPlayer._process_next`, `LavalinkPlayer.get_autoqueue_tracks`) | [Resolvido] `if not [i in titulo for i in exclude_tags]:` testa uma lista (sempre "verdadeira" se houver tags), então a condição nunca é satisfeita e o filtro por tags não executa. | Resolvido na Fase 3 (F3-3): condição corrigida com `any()` em `_process_next` e `get_autoqueue_tracks`, mantendo candidatas sem tags indesejadas. | médio |
| KI-22 | `empiremuse/utils/music/models.py` (`LavalinkPlayer._process_next`) | [Resolvido] `A or not B and C` é lido como `A or ((not B) and C)`: o filtro só descarta quando a duração está fora da faixa **e** o título é diferente. | Resolvido na Fase 3 (F3-3): a comparação de título passou a usar token_set_ratio, com limiar de 75 (TITLE_MATCH_THRESHOLD) e tolerância de 7 s na duração. | médio |
| KI-44 | `empiremuse/utils/music/models.py` (`LavalinkPlayer._process_next`) | [Resolvido] Quando o filtro descartava todas as candidatas, a descartada era tocada mesmo assim. | Resolvido na Fase 3 (F3-3): quando o filtro descarta todas as candidatas, a faixa é pulada, como quando não há resultado. | médio |

## Cliente Lavalink e Lavalink local

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-23 | `empiremuse/wavelink/player.py` (`Player.change_node`) | [Resolvido] `node.is_available` é lido antes de checar `if not node`. | Resolvido na Fase 3 (F3-3): checagem de existência do nó antes de ler atributos, exibindo mensagem amigável ao trocar para node inexistente. | médio |
| KI-24 | `empiremuse/utils/music/local_lavalink.py` (`_find_or_install_java`) | [Resolvido] `os.environ["JAVA_HOME"] + "bin/java"` sem separador. | Resolvido na Fase 3 (F3-2): detecção de JAVA_HOME utiliza os.path.join com o separador correto. | médio |

## Servidor web e RPC (robustez)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-25 | `empiremuse/web_app.py` (`WebSocketHandler.on_close`) | [Resolvido] `bots_ws.remove(self)` executa para conexões que nunca entraram em `bots_ws`. | Resolvido na Fase 3 (F3-4): fechar uma conexão nunca registrada não gera erro. | baixo |
| KI-26 | `empiremuse/web_app.py` (`WebSocketHandler.on_message`) | [Resolvido] `json.loads(message)` sem `try`/`except`. | Resolvido na Fase 3 (F3-4): mensagem malformada fecha a conexão com código 4400, em vez de gerar exceção. | médio |

## Qualidade, testes e modernização

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-27 | `tests/` | **Cobertura mínima de testes**: existem apenas testes de identidade/guarda de marca (`tests/brand/test_branding.py`), do filtro de URLs do Discord e do carregador da lista Lavalink. Faltam testes de caracterização do núcleo (player, filas, comandos, banco) em ~34,5 mil linhas de Python; planejados para a fase de saneamento. | Refatorações do núcleo continuam sem rede de proteção. | alto |
| KI-28 | `empiremuse/` (`cogs/`, `utils/`, `wavelink/`, `web_app.py`, `config_loader.py`) | [Resolvido] ~365 ocorrências de `except:` nu. | Resolvido no backlog pós-Fase 3 (#38, #39): 335 ocorrências substituídas por except Exception ou tipos específicos, com checagem ativa da regra E722 no ruff. | médio |
| KI-29 | `empiremuse/cogs/music.py` (8.688 linhas), `empiremuse/utils/music/models.py` (4.018), `empiremuse/utils/music/interactions.py` (3.534) | [Resolvido] Arquivos muito grandes e com muitas responsabilidades. | Resolvido na KI-29 (PRs #42 a #62): `Music` virou núcleo (`cogs/music.py`, 275 linhas) + 18 mixins em `empiremuse/music_cog/`; `models.py` e `interactions.py` viraram os pacotes `models/` e `interactions/`. Só movimentação de código: sem mudança de comportamento, de `custom_id`, de comandos nem de cooldowns, guardada por `tests/repo/` e `tests/cogs/` (payload dos comandos, estado por bot, hash dos corpos, imports isolados). Estrutura em `docs/architecture.md` (seções 3 e 5). | médio |
| KI-29b | `empiremuse/music_cog/play_command.py` (1.710 linhas), `queue_group.py` (1.058), `song_requests.py` (827), `player_controller.py` (816); `empiremuse/utils/music/interactions/skin_editor.py` (1.064), `fav_menu.py` (804) | Seis módulos seguem acima do teto de 800 linhas, cada um por conter um único comando ou classe coesa que a KI-29 só moveu. Métodos grandes: `Music.play` (1.588 linhas), `SkinEditorMenu` (938), `Music.player_controller` (776), `LavalinkPlayer.invoke_np` (390), `get_autoqueue_tracks` (371) e `_process_next` (336). | Revisão e teste continuam difíceis nesses pontos. Quebrá-los muda código e pede teste de caracterização antes; por isso ficou fora da KI-29. Cada arquivo traz um aviso de exceção no topo. | médio |
| KI-30 | `requirements.txt`, `requirements-lock.txt` (`disnake`, `jishaku`) | [Parcialmente resolvido] Lockfile com hashes SHA-256 e resolução universal (`requirements-lock.txt` e `requirements-dev-lock.txt`) implementado desde o PR #40; `disnake` e `jishaku` ainda via Git, fixados por SHA de commit imutável. | Builds reproduzíveis e protegidos por hashes criptográficos; pendente apenas transição futura de `disnake` e `jishaku` para releases estáveis do PyPI. | baixo |
| KI-31 | `empiremuse/utils/client.py` (`BotPool.setup`) | [Resolvido] Uso de `datetime.datetime.utcnow()` (obsoleto desde o Python 3.12). | Resolvido na Fase 3 (F3-2): substituído por datetime.now(timezone.utc) ciente de fuso horário em todo o projeto. | baixo |

## Identidade, guias e testes de marca (Fase 1)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-32 | `docs/guides/spotify-keys.md` | [Resolvido] Os guias ainda usam capturas de tela hospedadas no CDN do Discord e no GitHub do upstream. | Resolvido: prints mortos removidos em `docs/guides/spotify-keys.md`; guia reescrito em formato textual autossuficiente. | baixo |
| KI-33 | `empiremuse/utils/client.py` (`BotPool.setup`), `empiremuse/rules/git_remote.py` | [Resolvido] A URL do remote é extraída por fatiamento fixo da saída de `git remote -v`. | Resolvido na Fase 3 (F3-6): URL do remote lida por parsing de campos, sem credenciais de usuário ou senha no link do commit e com normalização de protocolos. | baixo |
| KI-34 | `tests/brand/test_branding.py` | [Resolvido] As varreduras estáticas dependem de `git ls-files` e usam correspondência por substring. | Resolvido na Fase 3 (F3-6): varredura estática funciona fora de um clone git usando .gitignore e casando palavras inteiras. | baixo |
| KI-35 | `empiremuse/utils/branding.py`, `assets/`, `data/lavalink_servers.ini` | [Aceito] Assets e a lista de servidores Lavalink são servidos via `raw.githubusercontent.com` da branch `main`. | Aceito por desenho: `empiremuse/utils/branding.py` é o ponto único que um fork ajusta para apontar para assets e lista de servidores próprios. | baixo |

## Painel web e comandos relacionados (saneamento)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-36 | `empiremuse/utils/music/request_channel.py` (e `empiremuse/cogs/music_settings.py`) | [Resolvido] `/reset`: limpa o banco de dados antes de executar as exclusões no Discord. | Resolvido na Fase 3 (F3-5a): o reset faz Discord primeiro, banco depois; se o Discord falhar, a configuração é mantida e o usuário recebe uma mensagem genérica. | médio |
| KI-37 | `empiremuse/utils/music/request_channel.py` (e `empiremuse/cogs/music_settings.py`) | [Resolvido] `/setup` de fórum: chamada a `post.edit()` sem nenhum argumento. | Resolvido na Fase 3 (F3-5a): chamada inútil a `post.edit()` sem argumentos removida do setup de fórum. | baixo |
| KI-38 | `empiremuse/utils/music/request_channel.py` | [Resolvido] `validate_request_target`: checagem redundante de permissão de leitura de mensagens (`view_channel`). | Resolvido na Fase 3 (F3-5a): removida checagem redundante de `view_channel` na validação de canal. | baixo |
| KI-39 | `empiremuse/utils/music/interactions.py` | [Resolvido] Modal de adicionar favorito não replica as exceções de `MAX_USER_FAVS=0` e isenção do dono; modal de adicionar integração usa indevidamente o limite de favoritos. | Resolvido na Fase 3 (F3-5a): modais de favoritos e integrações usam as cotas corretas (`MAX_USER_FAVS` e `MAX_USER_INTEGRATIONS`), com isenção do dono e suporte a cota ilimitada (`0`). | médio |
| KI-40 | `empiremuse/cogs/music_settings.py`, `empiremuse/utils/music/interactions.py` | [Resolvido] Importador de integrações do comando não aceita o formato JSON gerado pelo próprio exportador. | Resolvido na Fase 3 (F3-5a): importador de integrações aceita tanto o formato do exportador (`{"url": ..., "avatar": ...}`) quanto o formato legado de texto. | médio |
| KI-41 | `empiremuse/cogs/music_settings.py`, `empiremuse/utils/music/interactions.py` | [Resolvido] Importador de links rápidos do servidor aceita itens `> fav:` sem validar a URL. | Resolvido na Fase 3 (F3-5a): validação estrita de URLs agora vale para os três importadores (favoritos, integrações e links do servidor). | baixo |
| KI-42 | `empiremuse/cogs/music_settings.py`, `empiremuse/cogs/music.py`, `empiremuse/rules/` | [Resolvido] Cogs e painel possuíam regras duplicadas e divergentes. | Resolvido na Fase 3 (F3-5b): comandos e painel usam as mesmas regras em `empiremuse/rules/`. | médio |
| KI-43 | `empiremuse/cogs/legacy_cmds.py` (`Owner.setguildprefix`), `empiremuse/utils/client.py` (`BotPool.guild_prefix_cache`), `empiremuse/utils/db.py` (`default_model`) | [Resolvido] `setguildprefix` grava o cache com identificador incorreto; campo de configuração órfão `enable_prefixed_commands`. | Resolvido na Fase 3 (F3-5a): o cache de prefixo usa o servidor alvo; o campo órfão foi removido e o modelo foi para a versão 1.11. | baixo |
| KI-45 | `empiremuse/cogs/legacy_cmds.py` (`Owner.setguildprefix`) | [Resolvido] `setguildprefix` sem prefixo informado gerava exceção (`AttributeError`). | Resolvido na Fase 3 (F3-5a): comando sem argumento remove o prefixo customizado do servidor alvo sem erro. | baixo |
| KI-46 | `empiremuse/utils/music/interactions.py` | [Resolvido] Importador de integrações respondia pelo caminho incorreto em erros de validação. | Resolvido na Fase 3 (F3-5a): erros de validação no importador de integrações respondem com `inter.send` antes do `defer`. | baixo |
| KI-47 | `empiremuse/utils/music/interactions.py` | [Resolvido] Importador de links do servidor falhava com item malformado; mensagem citava o limite incorreto. | Resolvido na Fase 3 (F3-5a): itens malformados ou sem `url`/`description` são recusados com mensagem clara citando o limite correto (50). | baixo |
| KI-48 | `empiremuse/utils/music/interactions.py` | [Resolvido] Algumas mensagens de erro mostravam o texto técnico da exceção ao usuário. | Resolvido na Fase 3 (F3-5b): mensagens de erro sem detalhe técnico; detalhe só no log. | baixo |
| KI-49 | `empiremuse/utils/music/interactions.py` | [Resolvido] URL dos importadores validada apenas pelo início da string. | Resolvido na Fase 3 (F3-5a): URL e avatar são validados por inteiro contra espaços, quebras de linha, colchetes e menções em massa. | baixo |
| KI-50 | `empiremuse/utils/music/interactions.py` | [Resolvido] Nomes importados não possuíam limites nem sanitização. | Resolvido na Fase 3 (F3-5a): nomes importados seguem as regras de tamanho e sanitização do painel por modo (`clean_title`). | baixo |
| KI-51 | `empiremuse/utils/music/interactions.py` | [Resolvido] Importação recusada podia alterar dados em memória antes da persistência. | Resolvido na Fase 3 (F3-5a): importadores operam em cópia de trabalho local e só atualizam dados em tela e cache após validação total. | médio |
| KI-52 | `empiremuse/utils/music/interactions.py` | [Resolvido] Mensagens de erro de importação ecoavam o valor inteiro informado. | Resolvido na Fase 3 (F3-5a): valores inválidos exibidos nas mensagens de erro são truncados e sanitizados sem crases. | baixo |
| KI-53 | `empiremuse/utils/music/interactions.py` | [Resolvido] Erro exibido na interface após importação concluída com sucesso. | Resolvido na Fase 3 (F3-5a): atualização da interface pós-importação utiliza `build_txt` tanto em slash quanto em prefixo. | baixo |
| KI-54 | `empiremuse/utils/music/interactions.py` | [Resolvido] Modal de favorito não verificava a cota ao editar um item. | Resolvido na Fase 3 (F3-5a): verificação de cota é aplicada sempre que um novo nome de favorito for informado durante a edição. | baixo |

## Como usar este backlog

1. Antes de corrigir, escreva um teste que reproduza o problema (TDD) — ver
   `.claude/rules/empiremuse/python-disnake.md`.
2. Referencie o ID (`KI-xx`) na mensagem de commit/PR e no `CHANGELOG.md`.
3. Ao concluir, remova o item daqui (ou marque-o como corrigido, com o commit).

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
| Cliente Lavalink (`wavelink/`) e Lavalink local | KI-23 … KI-24 | médio |
| Servidor web / RPC (robustez) | KI-25 … KI-26 | médio |
| Qualidade, testes e modernização | KI-27 … KI-31 | alto |
| Identidade, guias e testes de marca (Fase 1) | KI-32 … KI-35 | baixo |
| Painel web e comandos relacionados (saneamento) | KI-36 … KI-43 | médio |

## Instalação e implantação

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-01 | `requirements.txt:7` | `tinymongo` sem o extra `serialization`, mas `utils/db.py:18` importa `tinydb_serialization`. | Instalação limpa falha ao iniciar o bot. Contorno: `uv pip install -r requirements.txt "tinymongo[serialization]"` (ver `development.md`). | alto |
| KI-02 | `.Dockerfile:1-2`, `.Dockerfile:4` | Imagem com `python:3.10-slim` e OpenJDK 11, distinta do ambiente validado (Python 3.13); o Lavalink exige Java 17+ (`utils/music/local_lavalink.py:63`). | Imagem divergente do que é testado; o Lavalink local depende de baixar outro JDK em tempo de execução. | médio |
| KI-03 | `render.yaml:6`, `render.yaml:20-21` | Aponta para o repositório do projeto original e fixa Python 3.11.7. | Deploy no Render não usa o EmpireMuse nem a versão validada. | baixo |
| KI-04 | `utils/client.py:267`; `modules/error_handler.py:141`, `modules/error_handler.py:303` | O reinício do processo é feito com `kill 1` (PID 1 do contêiner). | Só funciona como esperado dentro de contêiner; fora dele o sinal vai para o `init` do sistema (ou falha), sem reiniciar o bot. | médio |
| KI-05 | `requirements.txt:13`, `requirements.txt:21`, `requirements.txt:22`, `requirements.txt:25`, `requirements.txt:27`, `requirements.txt:29` | Dependências declaradas e **sem nenhum `import`** no código: `aiosqlite`, `syncedlyrics`, `pylrc`, `undetected-chromedriver`, `nest_asyncio`, `curl_cffi`. (`nodriver` é usado em `utils/music/youtube_trusted_session_generator.py`.) | Instalação mais pesada e maior superfície de dependências. | baixo |

## Configuração

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-06 | `config_loader.py:8-12`, `config_loader.py:283` | A tabela de booleanos só tem chaves em minúsculas; `bools[CONFIG[i]]` não normaliza o valor. | `FLAG=True` ou `FLAG=FALSE` aborta a inicialização com "configuração inválida". | médio |
| KI-07 | `config_loader.py:307-308` | `LAVALINK_RECONNECT_RETRIES < 5` vira `0`, e `0` é tratado como "sem limite" em `modules/music.py:6998`. | Quem configura 1–4 tentativas obtém tentativas **infinitas**. | médio |
| KI-08 | `config_loader.py:182`, `config_loader.py:187` | `except:` nus ao ler o `.env` e a cor do embed. | Erros de leitura do `.env` são engolidos silenciosamente. | baixo |

## Banco de dados

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-09 | `utils/db.py:325` | `update_values` ignora valores do tipo lista (`elif not isinstance(v, list)`) ao migrar a versão do esquema. | Ao subir o `ver` de um modelo, listas salvas (p.ex. `djroles`, `last_tracks`) são substituídas pelo padrão vazio: **perda de dados** dos usuários. | alto |
| KI-10 | `utils/db.py:201-202` | `LocalDatabase.update_data` captura qualquer exceção, imprime e segue, atualizando o cache como se tivesse gravado. | Falha de gravação no TinyMongo fica invisível; o dado some após o cache expirar. | médio |

## Pool de bots e inicialização

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-11 | `utils/client.py:900` | No `except KeyError`, `self.guild_bots = {guild_id: [bot]}` **substitui** o dicionário inteiro. | Com `guild_bots.json` com vários servidores, só o último continua registrado (os demais perdem seus bots exclusivos em `get_guild_bots`). | médio |
| KI-12 | `utils/client.py:96`, `utils/client.py:143-144` | `reset_useragent` atribui a `self.current_useragent` mas **não retorna** nada; `__init__` reatribui o resultado (`None`). | `current_useragent` fica `None` na inicialização. Hoje o uso está comentado (`modules/music.py:7145`). | baixo |
| KI-13 | `utils/client.py:243`, `utils/client.py:253` | A condição usa `str(e)` com `e = None` (deveria ser `error`), e `raise e` levanta `TypeError` quando `e` é `None`. | Com `KILL_ON_429=false`, o tratamento de rate limit do Discord falha com `TypeError` em vez de propagar o erro original. | médio |
| KI-14 | `utils/client.py:223-231`; `utils/music/local_lavalink.py:75`, `utils/music/local_lavalink.py:242` | `LAVALINK_CPU_CORES` nunca é repassado a `run_lavalink` (usa o padrão `1`), e `-Xms` recebe `lavalink_ram_limit` em vez de `lavalink_initial_ram`. | Configurações de CPU e RAM inicial do Lavalink local não têm efeito. | baixo |

## Spotify (`utils/music/audio_sources/spotify.py`)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-15 | `utils/music/audio_sources/spotify.py:170` (com `utils/music/audio_sources/spotify.py:144-149`) | Em erro de token, `get_access_token` zera as credenciais e chama a si mesma, mas `token_refresh` ainda é `True`: a chamada entra no laço `while self.token_refresh` e **espera para sempre**. | Com credenciais inválidas, qualquer comando que dependa do Spotify trava sem erro. | alto |
| KI-16 | `utils/music/audio_sources/spotify.py:102` | Páginas extras começam em `offset = 101`; a primeira página já traz os itens 0–99. | A 101ª faixa (índice 100) de playlists grandes é pulada. | médio |
| KI-17 | `utils/music/audio_sources/spotify.py:113` | Condição `page_count <= playlist_extra_page_limit` (deveria ser `<`). | Carrega uma página extra além do limite configurado. | baixo |
| KI-18 | `utils/music/audio_sources/spotify.py:139` | `quote(query)` é aplicado antes de passar `params=` ao aiohttp, que codifica de novo. | Buscas com espaços/acentos/símbolos são enviadas com dupla codificação e retornam resultado ruim. | médio |
| KI-19 | `utils/music/audio_sources/spotify.py:193`, `utils/music/audio_sources/spotify.py:177` | `get_valid_access_token` lê `spotify_cache["expires_at"]` sem checar; com cache vazio dá `KeyError`. Além disso, a chave é gravada como `"tyoe"` (typo de `"type"`). | Falha na primeira requisição se o token ainda não foi obtido; chave com nome errado no cache. | médio |
| KI-20 | `utils/music/audio_sources/spotify.py:98`, `utils/music/audio_sources/spotify.py:107` | Importação de playlist usa `playlists/{id}` e `playlists/{id}/tracks`. Segundo o briefing (mudança da API do Spotify em fev/2026), playlists de terceiros podem não ser mais acessíveis com *client credentials*. **Ainda não testado com credenciais reais.** | Importação de playlists públicas pode estar quebrada. | a confirmar (pendente de teste com credenciais reais) |

## Player e busca de faixas (`utils/music/models.py`)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-21 | `utils/music/models.py:2019` (e `utils/music/models.py:1711`) | `if not [i in titulo for i in exclude_tags]:` testa uma lista (sempre "verdadeira" se houver tags), então a condição nunca é satisfeita e o filtro por tags não executa. | Resultados com "remix", "edit", "mashup" etc. não são deprioritizados ao resolver faixas do Spotify/Deezer. | médio |
| KI-22 | `utils/music/models.py:2033` | `A or not B and C` é lido como `A or ((not B) and C)`: o filtro só descarta quando a duração está fora da faixa **e** o título é diferente. | Aceita faixa com duração correta e título errado, e faixa com título parecido e duração errada. | médio |

## Cliente Lavalink e Lavalink local

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-23 | `wavelink/player.py:629-632` | `node.is_available` é lido antes de checar `if not node`. | `AttributeError` ao trocar para um identificador de node inexistente, em vez da mensagem amigável. | médio |
| KI-24 | `utils/music/local_lavalink.py:88` | `os.environ["JAVA_HOME"] + "bin/java"` sem separador. | `JAVA_HOME` nunca é aproveitado (caminho inválido); o bot cai no download de um JDK. | médio |

## Servidor web e RPC (robustez)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-25 | `web_app.py:280` | `bots_ws.remove(self)` executa para conexões que nunca entraram em `bots_ws`. | `ValueError` no fechamento de conexões anônimas (ruído de log). | baixo |
| KI-26 | `web_app.py:149` | `json.loads(message)` sem `try`/`except`. | Mensagem malformada gera exceção não tratada no handler do WebSocket. | médio |

## Qualidade, testes e modernização

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-27 | `tests/` | **Cobertura mínima de testes**: existem apenas testes de identidade/guarda de marca (`tests/test_branding.py`), do filtro de URLs do Discord e do carregador da lista Lavalink. Faltam testes de caracterização do núcleo (player, filas, comandos, banco) em ~34,5 mil linhas de Python; planejados para a fase de saneamento. | Refatorações do núcleo continuam sem rede de proteção. | alto |
| KI-28 | `modules/`, `utils/`, `wavelink/`, `web_app.py`, `config_loader.py` | ~365 ocorrências de `except:` nu. | Erros reais são engolidos; inclui `KeyboardInterrupt`/cancelamentos de tasks. | médio |
| KI-29 | `modules/music.py` (7.876 linhas), `utils/music/models.py` (3.832), `utils/music/interactions.py` (3.310) | Arquivos muito grandes e com muitas responsabilidades. | Revisão e teste difíceis. | médio |
| KI-30 | `requirements.txt:1`, `requirements.txt:11` | `disnake` e `jishaku` fixados em commits Git (o `disnake` é anterior à 2.12.0; há 2.12.2 estável). Demais pacotes sem versão fixa e sem *lockfile*. | Builds não reproduzíveis e dependência de repositórios Git externos. | médio |
| KI-31 | `utils/client.py:805`, `utils/client.py:856` | Uso de `datetime.datetime.utcnow()` (obsoleto desde o Python 3.12). | Avisos de depreciação e remoção futura. | baixo |

## Identidade, guias e testes de marca (Fase 1)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-32 | `docs/guides/*.md` | Os guias ainda usam capturas de tela hospedadas no CDN do Discord e no GitHub do upstream. | As imagens podem expirar ou sumir. Migrar para `assets/` ou arte própria. | baixo |
| KI-33 | `utils/client.py` (~669) | A URL do remote é extraída por fatiamento fixo da saída de `git remote -v` (assume o remote `origin`). | Resultado incorreto com outro nome de remote ou formato de saída. Trocar por *parsing* por campos. | baixo |
| KI-34 | `tests/test_branding.py` | As varreduras estáticas dependem de `git ls-files` (exigem `.git`) e usam correspondência por substring. | Falham fora de um clone Git e podem gerar falsos positivos/negativos. Revisar no saneamento. | baixo |
| KI-35 | `utils/branding.py`, `assets/`, `data/lavalink_servers.ini` | Assets e a lista de servidores Lavalink são servidos via `raw.githubusercontent.com` da branch `main`. | Forks de terceiros continuam apontando para a DiscordEmpireHub até ajustarem `utils/branding.py` (informativo). | baixo |

## Painel web e comandos relacionados (saneamento)

| ID | Local | Problema | Impacto | Sev. |
|---|---|---|---|---|
| KI-36 | `utils/music/request_channel.py` (e `modules/music_settings.py`) | `/reset`: limpa o banco de dados antes de executar as exclusões no Discord. | Se ocorrer falha no Discord durante o reset com opção de deletar canal, o banco é desconfigurado mas o canal permanece, gerando estado parcial inconsistente. | médio |
| KI-37 | `utils/music/request_channel.py` (e `modules/music_settings.py`) | `/setup` de fórum: chamada a `post.edit()` sem nenhum argumento. | Gera requisição inútil à API do Discord sem efetuar nenhuma alteração de estado no post. | baixo |
| KI-38 | `utils/music/request_channel.py` | `validate_request_target`: checagem redundante de permissão de leitura de mensagens (`view_channel`). | Verificação repetida da mesma permissão em etapas sucessivas da validação de destino. | baixo |
| KI-39 | `utils/music/interactions.py` | Modal de adicionar favorito não replica as exceções de `MAX_USER_FAVS=0` e isenção do dono; modal de adicionar integração usa indevidamente o limite de favoritos. | Donos do bot e instâncias sem limite são impedidos de adicionar favoritos via modal; cadastro de integrações é limitado pela cota de favoritos em vez de `MAX_USER_INTEGRATIONS`. | médio |
| KI-40 | `modules/music_settings.py`, `utils/music/interactions.py` | Importador de integrações do comando não aceita o formato JSON gerado pelo próprio exportador. | O exportador gera objetos com `url` e `avatar`, enquanto o importador do comando só aceita strings simples, quebrando a restauração de backups via comando. | médio |
| KI-41 | `modules/music_settings.py`, `utils/music/interactions.py` | Importador de links rápidos do servidor aceita itens `> fav:` sem validar a URL. | Permite a persistência de links com URLs inválidas ou malformadas no banco de dados através da importação de arquivo. | baixo |
| KI-42 | `modules/music_settings.py`, `modules/music.py` | Cogs ainda possuem implementações próprias de regras em vez de utilizarem `panel/services/`. | Duplicação de código de regras de negócio entre comandos slash e interface web, dificultando manutenção e gerando risco de assimetrias. | médio |
| KI-43 | `modules/legacy_cmds.py:714`, `utils/client.py` | `setguildprefix` grava o cache com identificador incorreto; campo de configuração órfão `enable_prefixed_commands`. | Invalidação falha no cache em memória de prefixos do pool ao usar o comando legado; presença de campo de configuração sem nenhuma utilidade no código. | baixo |

## Como usar este backlog

1. Antes de corrigir, escreva um teste que reproduza o problema (TDD) — ver
   `.claude/rules/empiremuse/python-disnake.md`.
2. Referencie o ID (`KI-xx`) na mensagem de commit/PR e no `CHANGELOG.md`.
3. Ao concluir, remova o item daqui (ou marque-o como corrigido, com o commit).

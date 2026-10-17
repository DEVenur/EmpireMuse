---
paths: ["**/*.py"]
---
# EmpireMuse — convenções Python + disnake

Complementa `.claude/rules/ecc/python/*` (estilo, padrões, testes genéricos) com o que é **específico deste
projeto**. Contexto: `docs/architecture.md`; bugs conhecidos: `docs/known-issues.md`.

## Multi-bot (BotPool)

- Vários `BotCore` rodam no mesmo processo. **Nunca** guarde estado por bot em variável global de módulo:
  use `self.bot`, `bot.pool` e `bot.config` (`empiremuse/utils/client.py:1078-1108`).
- Todo comando precisa passar por `check_pool_bots` (`empiremuse/utils/music/checks.py:104`) para que só um bot
  responda. Declare o comportamento nas `extras` (slash) ou nos argumentos de `pool_command` (prefixo):
  `only_voiced`, `check_player`, `return_first`, `allow_private`.
- Módulos em `empiremuse/cogs/` são recarregados a cada bot e exigem `def setup(bot)` com `bot.add_cog(...)`
  (`empiremuse/cogs/misc.py:1040`). Para recurso opcional, devolva cedo em `setup` quando faltar config
  (`empiremuse/cogs/lastfm.py:735`).

## Comandos

- Slash: `@commands.slash_command(description=..., extras={...}, cooldown=..., max_concurrency=...)` seguido de
  `@commands.contexts(guild=True)`. Descrição com **no máximo 100 caracteres** — acima disso o carregamento
  de módulos aborta (`empiremuse/utils/client.py:1501-1504`).
- Parâmetros: `commands.Param(name="<nome em pt-BR>", description=...)`; o identificador Python fica em
  inglês e o nome exibido ao usuário em português (`empiremuse/cogs/music.py:228-243`).
- Prefixo: use `pool_command` (`empiremuse/utils/others.py:250`), nunca `commands.command` direto, para herdar o
  roteamento do pool. Interação e prefixo devem compartilhar a mesma lógica (um chama o `.callback` do outro,
  como em `empiremuse/cogs/music.py:316`).
- Cooldowns/concorrência: reutilize as constantes já definidas (ex.: `play_cd`, `play_mc`); comandos com
  cooldown próprio levam `extras={"exclusive_cooldown": True}` (`empiremuse/utils/client.py:1163-1205`).

## Checks e erros

- Use os decoradores de `empiremuse/utils/music/checks.py` (`has_player`, `is_dj`, `check_voice`, `has_source`,
  `can_send_message_check`, `user_cooldown`, …) acima de `@commands.slash_command`, como em
  `empiremuse/cogs/music.py:227`. Não reimplemente verificações de DJ, voz ou permissão.
- Erros **para o usuário** são `GenericError(texto)` (`empiremuse/utils/music/errors.py:22`) — o
  `empiremuse/cogs/error_handler.py` formata e responde. Não monte a resposta de erro manualmente na rota.
- Erros inesperados: deixe propagar até o `error_handler`; não use `print`/`traceback.print_exc()` para
  engolir falha. Use `logging.getLogger(__name__)`.

## Interações e `custom_id`

- Todo componente declara `custom_id` **estável e único**, em `snake_case` com prefixo da funcionalidade
  (`musicplayer_*` em `PlayerControls`, `queue_*`, `user_fav_*`, `guild_fav_*` — `empiremuse/utils/others.py:157`,
  `empiremuse/utils/music/interactions.py:117-993`). Não derive `custom_id` de dados do usuário.
- Views persistentes (registradas com `bot.add_view`, p.ex. `PanelView`) usam `timeout=None`
  (`empiremuse/utils/owner_panel.py:29`); views temporárias definem `timeout` e desativam os itens no `on_timeout`.
- Responda toda interação em até 3 s: faça `await inter.response.defer(...)` antes de I/O lento.
- Modais e selects: valide e **limite** o tamanho do que vem do usuário antes de gravar no banco
  (limites em `MAX_USER_FAVS`, `USER_FAV_MAX_*_LENGTH` de `empiremuse/config_loader.py`).

## asyncio

- Nada bloqueante no loop de eventos: sem `requests`, `time.sleep`, `subprocess.run/check_output`,
  `open()` de arquivos grandes ou cálculo pesado dentro de `async def`.
- Chamada síncrona inevitável: `await loop.run_in_executor(None, funcao, *args)` (modelo em
  `empiremuse/utils/client.py:237-245` e `:1148-1152`). Prefira `aiohttp` (`bot.session`) e `aiofiles`.
- Toda `asyncio.create_task` guarda a referência (atributo ou coleção) e é cancelada em `cog_unload`
  (veja `empiremuse/cogs/player_resume.py:836-840`). Não deixe task "fire-and-forget" sem tratamento de exceção.
- `asyncio.CancelledError` **nunca** é engolido: relance depois da limpeza.

## Banco de dados

- Acesse dados só por `bot.get_data/update_data` (por bot) e `bot.get_global_data/update_global_data`
  (`empiremuse/utils/client.py:1110-1132`), que usam `empiremuse/utils/db.py`. Proibido instanciar `AsyncIOMotorClient`/TinyMongo
  fora de `empiremuse/utils/db.py` ou abrir arquivos de `local_database/` direto.
- Mudou o formato de um documento? Atualize o modelo em `empiremuse/utils/db.py` **e** incremente `ver`; a migração
  (`update_values`) hoje descarta listas (KI-09) — cubra com teste.
- Mantenha a compatibilidade Mongo × TinyMongo: só operadores que os dois suportam (`$set`, `_id` em `str`).

## Textos e idioma

- Todo texto exibido ao usuário (embeds, botões, erros, descrições de comandos) em **português do Brasil
  com acentuação correta**. Identificadores, nomes de arquivo, chaves de config e logs técnicos podem ficar
  em inglês; comentários e docstrings, em português.
- Não fixe URL, nome de servidor ou ID no texto: use `bot.config` (`SUPPORT_SERVER`, `SOURCE_REPO`).

## Código novo

- **Sem `except:` nu** e sem `except Exception: pass`. Capture a exceção específica, registre com
  contexto e decida: tratar, converter em `GenericError` ou relançar.
- **Sem `pickle`** para persistir ou ler dados novos (nem `eval`/`exec`). Use JSON, campos do documento ou
  `dataclasses`/`TypedDict` serializados explicitamente.
- Anotações de tipo em toda assinatura nova; `from __future__ import annotations` e `TYPE_CHECKING` para
  evitar import circular com `BotCore` (padrão do projeto).
- Funções pequenas (< 50 linhas) e módulos novos em vez de crescer `empiremuse/cogs/music.py`,
  `empiremuse/utils/music/models.py` e `empiremuse/utils/music/interactions.py`.
- Configuração nova: chave em `DEFAULT_CONFIG` (`empiremuse/config_loader.py`), documentação em `.example.env` e
  conversão de tipo na lista correspondente. Booleanos só em minúsculas (`true`/`false`) até a KI-06.
- Não adicione dependência sem justificar; fixe a versão.

## Testes

- Bug corrigido ou comportamento novo → teste primeiro (TDD) em `tests/`, com `pytest` e `pytest-asyncio`
  (`asyncio_mode = "auto"`).
- Sem rede nem Discord real: use dublês (`unittest.mock.AsyncMock`) para `disnake.Interaction`, `BotCore`,
  `aiohttp` e o banco; para `empiremuse/utils/db.py`, use `LocalDatabase` em diretório temporário (`tmp_path`).
- Extraia lógica pura (filtros de faixa, conversão de config, parsing de URL) para funções testáveis sem
  o bot — foi a ausência disso que deixou passar os bugs de `docs/known-issues.md`.

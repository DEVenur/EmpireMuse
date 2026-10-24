# Painel Web — Pesquisa Externa (etapa P-0)

> Autor: DeepSearch Researcher · Data: 2026-10-15 · Branch: `feat/painel-web` · Status: **pesquisa, sem código**.
> Fontes: `gh search repos/code` e `gh api` (licença SPDX, estrelas, `pushed_at`, `archived`), PyPI, documentação
> oficial do Discord, documentação do Tornado (Context7) e inspeção local do worktree (somente leitura).
> Nada foi clonado, instalado ou executado; os CSS foram baixados como dado (diretório `mktemp`) apenas para medir o tamanho.
> Licença do EmpireMuse: **GPL-2.0**. Legenda: ✅ compatível · ⚠ sinalizar/analisar · ⛔ incompatível ou sem licença.

---

## 1. Resumo e recomendação (top 3)

**Conclusão geral:** não existe dashboard pronto, genérico e reaproveitável para Python/Tornado/disnake. Todos os
dashboards open source de bots encontrados são Node/React, acoplados a discord.js, ou têm licença restritiva. Vale
**construir sobre blocos pequenos** e usar os projetos existentes só como inspiração de UX.

1. **Tornado nativo para tudo no servidor (adotar).** `tornado.auth.OAuth2Mixin` (redireciona e faz as requisições de API),
   `set_secure_cookie`, `xsrf_cookies` e `xsrf_cookie_kwargs`. Tudo isso está no Tornado 6.5.10 que o projeto já usa
   (`requirements.txt: tornado>=6.4.2`), sem dependência nova. O `state` anti-CSRF do OAuth, a troca do `code` (via `aiohttp`,
   que já é dependência) e a sessão no servidor ficam em código próprio, pequeno e auditável.
   Nenhuma biblioteca Discord-OAuth2 em Python serve ao Tornado (todas são Flask/Quart/FastAPI/Starlette).
2. **Renderização: templates Tornado + htmx 2.x vendorizado, sem build (adotar).** Confirmo a recomendação do Frontend.
   htmx é 0BSD (verificado no arquivo `LICENSE`). Fixar a linha **2.0.x** (última 2.0.10, 2026-09-06); a v4.0.0 saiu em 2026-08-28
   e é recente demais para uma base nova.
3. **CSS: Pico CSS v2.1.1 vendorizado, com ressalva e plano B (adaptar).** ⚠ **O repositório do Pico foi arquivado em
   2026-10-04** (README: "Pico CSS is no longer maintained"; v2.1.1 é a versão final), dado que a §1 do Frontend não registra.
   Para um arquivo CSS vendorizado e sem JS isso é aceitável (nada a atualizar em execução), mas deve constar no ADR.
   Plano B: **Simple.css** (MIT, ~9 KB), que não traz componentes de painel. Detalhes na §4.2.

**Descartados de forma firme:** Zeppelin (licença Elastic 2.0, não é open source), Discord-Dashboard/Core
(shareware CC BY-NC-SA), Red-Dashboard (AGPL-3.0 e arquivado), Flask-Discord (arquivado), dashboards React/Next (build Node, arquivados ou sem licença).

---

## 2. Tabela de candidatos

### 2.1 Dashboards de bots Discord (inspiração / adoção direta)

| Projeto | URL | Licença | Último push | ★ | Stack | Encaixe com Tornado | Veredito |
|---|---|---|---|---|---|---|---|
| MrAugu/simple-discordjs-dashboard | github.com/MrAugu/simple-discordjs-dashboard | MIT ✅ | 2026-06-21 | 240 | Express + EJS + passport | Mesmo padrão (templates no servidor + OAuth + sessão), outra linguagem | **Só inspiração** |
| LachlanDev/Discord-BOT-Dashboard-V2 | github.com/LachlanDev/Discord-BOT-Dashboard-V2 | MIT ✅ | 2026-03-20 | 241 | Node/JS | Acoplado a discord.js | **Descartar** |
| fuma-nama/discord-bot-dashboard-next | github.com/fuma-nama/discord-bot-dashboard-next | MIT ✅ | 2024-05-26 (arquivado) | 235 | Next.js + Chakra UI | Exige build Node | **Só inspiração visual** (fluxo login → servidores → abas) |
| fuma-nama/discord-bot-dashboard / -2 | github.com/fuma-nama/… | MIT ✅ | 2023 | 130 / 100 | React | Exige build, desatualizados | **Descartar** |
| botlabs-gg/yagpdb | github.com/botlabs-gg/yagpdb | MIT ✅ | 2026-10-13 | 1445 | Go; painel web em `web/` com login Discord (`web/handlers_auth.go`) | Não reaproveitável (Go) | **Só inspiração** de organização por plugin/categoria e de permissões por servidor |
| Cog-Creators/Red-Dashboard | github.com/Cog-Creators/Red-Dashboard | **AGPL-3.0 ⛔** | 2025-03-02 (arquivado) | 77 | Python/Flask, depende do Red-DiscordBot (GPL-3.0) | Acoplado ao Red | **Descartar** (AGPL; não incorporar nem copiar código) |
| ZeppelinBot/Zeppelin | github.com/ZeppelinBot/Zeppelin | **Elastic License 2.0 ⛔** (`LICENSE.md`; GitHub mostra "NOASSERTION") | 2026-09-09 | 461 | TypeScript | — | **Descartar** (fonte-disponível, não open source; proíbe oferecer como serviço) |
| Discord-Dashboard/Core (npm `discord-dashboard`) | github.com/Discord-Dashboard/Core | "Shareware" CC BY-NC-SA 4.0 ⛔ (segundo fontes secundárias; repositório não acessível pela API) | — | — | Node | Acoplado a discord.js | **Descartar** (uso comercial restrito, licença atípica) |
| julianYaman/discord-bot-dashboard | github.com/julianYaman/discord-bot-dashboard | **sem licença ⛔** | 2022-05-04 | 319 | TypeScript | — | **Descartar** |
| aelumiya/Discord-Dashboard | github.com/aelumiya/Discord-Dashboard | MIT ✅ | 2023-01-01 | 22 | Python/Flask + Bootstrap | Abandonado | **Descartar** |
| VinnyTheLegend/DiscordDash | github.com/VinnyTheLegend/DiscordDash | **sem licença ⛔** | 2026-04-10 | 6 | discord.py + FastAPI + Svelte | Pequeno, sem licença | **Descartar** |
| RayExo/ZyroX-CV2-AIO-With-Dashboard | github.com/RayExo/ZyroX-CV2-AIO-With-Dashboard | MIT ✅ | 2026-07-23 | 98 | discord.py + FastAPI + Next.js | Exige build; processo separado | **Só inspiração** (configuração por servidor, estrutura de rotas) |

Observação: não há código aberto dos dashboards de bots populares (MEE6, Dyno, Carl-bot) para consulta; são fechados.

### 2.2 Blocos Python de OAuth2 do Discord

| Projeto | Licença | Última versão / push | Framework | Veredito |
|---|---|---|---|---|
| tornado.auth.OAuth2Mixin (Tornado 6.5.10) | Apache-2.0 (já é dependência) | 2026-10 | **Tornado** | **Adotar** (`authorize_redirect`, `oauth2_request`) |
| Authlib 1.9.1 | BSD-3-Clause ✅ | 2026-10-14 (PyPI) | Integrações no repositório: Django, Flask, Starlette, httpx, requests; **sem Tornado** | **Só inspiração** (RFC 7636/PKCE, cliente OAuth2); evita-se a dependência nova |
| Tert0/fastapi-discord 0.2.8 | MIT ✅ | 2026-08-04 | FastAPI | **Só inspiração** |
| nwunderly/starlette-discord 0.2.1 | MIT ✅ | 2024-09-10 | Starlette | **Descartar** |
| weibeu/Flask-Discord | MIT ✅ | 2024-09-04 (**arquivado**) | Flask | **Descartar** |
| quart-discord 2.1.4 / Quart-Nextcord 2.1.6a1 | MIT ✅ | 2021 / 2022 | Quart | **Descartar** (desatualizados) |
| treeben77/discord-oauth2.py | MIT ✅ | 2026-01-12 | agnóstico (aiohttp) | **Só inspiração** (52 ★, mantenedor único) |
| Snipy7374/ext-oauth2 | MIT ✅ | 2024-08-16 | agnóstico | **Descartar** (9 ★) |
| discord-ext-ipc / ipcx | Apache-2.0 ⚠ | 2021 / 2026-10-15 | discord.py | **Descartar**: IPC serve a painel em **processo separado**; aqui é o mesmo processo |

---

## 3. Blocos Python recomendados

- **Mesmo processo, mesmo loop (verificado no código):** `BotPool.setup` em `empiremuse/utils/client.py` chama `web_app.start()` dentro do `BotPool`;
  os bots rodam como tarefas no mesmo `loop` (`BotPool.setup`). O Tornado 6 usa o loop do `asyncio`, então handlers `async` do painel
  acessam `pool.bots`, caches do disnake e o banco (`MongoDatabase`/`LocalDatabase.get_data/update_data`, `utils/db.py`)
  sem fila, IPC nem thread. Isso dispensa ASGI/Quart/FastAPI (opção B) e IPC (opção C).
  ⚠ O servidor web só sobe com `RUN_RPC_SERVER` ativo (`BotPool.setup` em `empiremuse/utils/client.py`); o painel herda essa condição.
- **Rotas:** registrar `/painel/*` no `tornado.web.Application` de `run_app` em `empiremuse/web_app.py`, mantendo `/` e `/ws`.
- **Configurações do `Application` a ativar:** `cookie_secret` (≥32 bytes aleatórios, de variável de ambiente, nunca no repositório;
  o Tornado aceita dicionário de chaves versionadas para rotação), `xsrf_cookies=True`,
  `xsrf_cookie_kwargs={"httponly": True, "secure": True, "samesite": "Lax"}` (parâmetros confirmados no código instalado:
  `xsrf_cookie_kwargs`, `xsrf_cookie_name`, `check_xsrf_cookie`, `samesite`), `template_path`, `static_path`, autoescape (padrão ligado).
  Os handlers atuais (`/` e `/ws`) só usam GET, portanto o XSRF global não os afeta.
- **OAuth2:** `OAuth2Mixin` com `_OAUTH_AUTHORIZE_URL = https://discord.com/oauth2/authorize` e `_OAUTH_ACCESS_TOKEN_URL = https://discord.com/api/oauth2/token`.
  Assinatura instalada: `authorize_redirect(redirect_uri, client_id, client_secret, extra_params, scope, response_type)`. **O mixin não gera nem valida
  `state`**: passar `state` em `extra_params` e validá-lo no retorno é responsabilidade do código do painel. A troca do `code` é um `POST` com `aiohttp` (já dependência).
- **Sessão no servidor:** cookie assinado (`set_secure_cookie`) com apenas um **ID de sessão aleatório**; os dados ficam no servidor
  (dicionário em memória com TTL para uma instância, ou coleção própria em `utils/db.py` com índice TTL no Mongo). Evita gravar token do Discord no cookie.
- **Cliente HTTP do Discord:** `aiohttp.ClientSession` único, com timeout, tratamento de 429 (`Retry-After`) e sem registrar tokens em log.
- **Autorização por servidor (autoridade = dados do bot):** `guild = bot.get_guild(id)` para algum bot do pool; membro via `guild.get_member(user_id)`
  ou `await guild.fetch_member()` (a intent de membros já é ligada em `BotPool.setup` em `empiremuse/utils/client.py`); aprovar se `member.guild_permissions.manage_guild or .administrator`
  ou `guild.owner_id == user_id`. Revalidar em **toda escrita** (cache curto de 30–60 s), nunca só no login.
- **Dependências novas sugeridas:** nenhuma.

---

## 4. UI / renderização

### 4.1 Abordagem (confirma o Frontend)

Templates Tornado + htmx vendorizado vence a SPA: mesmo processo/porta, sem Node em produção (Replit, Render, SquareCloud, Docker),
auditoria AppSec menor e fallback sem JS. Os modelos prontos de SPA encontrados estão arquivados ou sem licença (§2.1).

- **htmx**: 0BSD ✅ (`LICENSE` = Zero-Clause BSD; a API do GitHub mostra "Other"/NOASSERTION). Fixar 2.0.10, arquivo local com nome versionado e hash em `SHA256SUMS`,
  `htmx.config.allowEval=false` e `selfRequestsOnly=true`. A linha 4.x é muito recente.
- **Alpine.js**: confirmo "fora da v1" (MIT, 3.x; o build padrão usa `eval`, incompatível com CSP `script-src 'self'`; existe build CSP, mas não é necessário).

### 4.2 Comparativo de CSS leve, sem build

Pesos medidos por mim (arquivo oficial minificado do jsDelivr, `gzip -9`). Dark mode, `:focus-visible` e `prefers-reduced-motion` foram verificados no próprio CSS.

| Kit | Licença | Mantido? (verificado) | Tamanho min / gz | Tema escuro | Acessibilidade (indícios no CSS) | Componentes para painel | Observação |
|---|---|---|---|---|---|---|---|
| **Pico CSS 2.1.1** | MIT ✅ | ⚠ **Arquivado 2026-10-04**; v2.1.1 final (2025-03-15) | 83,3 KB / 11,6 KB | `data-theme` claro/escuro + `prefers-color-scheme`; variações de cor (há `violet`, `purple`, `fuchsia`) | `:focus-visible`, `prefers-reduced-motion`, HTML semântico, `aria-invalid` | Formulários, `switch`, `<dialog>` modal, accordion (`<details>`), grid, nav, tooltip | Sem JS. Variáveis CSS permitem a paleta Nebulosa |
| **Simple.css 2.3.7** | MIT ✅ | Ativo (push 2026-07-19; última release 2025-05-29) | 9,4 KB / 2,8 KB | Só `prefers-color-scheme` (sem alternância manual) | `:focus-visible` presente; sem `reduced-motion` | Estiliza tags, mas sem switch/modal/grid de painel | Bom plano B; exigiria CSS próprio para abas/switch |
| MVP.css 1.18 | MIT ✅ | Ativo (v1.18, 2026-09-14) | 10,3 KB / 2,7 KB | `prefers-color-scheme` | Sem `:focus-visible` explícito | Layout de landing page, não de painel | Descartar para painel |
| Water.css 2 | MIT ✅ | Parado (último push 2024-02) | 22,7 KB / 3,6 KB | `prefers-color-scheme` | Sem `:focus-visible` | Mínimos | Descartar |
| Basecoat 1.0.1 | MIT ✅ | Ativo (2026-06) | 217,5 KB / 21,8 KB (CDN) | classe `.dark` | `:focus-visible` extensivo | Muitos componentes (estilo shadcn); parte exige JS | Pesado, atrelado a Tailwind; descartar para a v1 |
| Oat 0.8.3 | MIT ✅ | Ativo (2026-10-10), mas **pré-v1, com quebras previstas**; sem `dist/` no repositório (gera-se com `make`) | ~10 KB CSS+JS (declarado pelo autor) | — | — | Web components | Descartar (instável e exige build) |
| Tabler / Bulma / AdminLTE / daisyUI | MIT ✅ | Ativos | centenas de KB; Tabler/daisyUI exigem Node/Tailwind | sim | variável | completos | Descartar (peso/build); Tabler só como inspiração de layout |

**Decisão proposta (cabe ao MAESTRO/dono confirmar): Pico CSS 2.1.1 vendorizado + `nebulosa.css` com variáveis próprias.**
Razões: é o único leve com formulários, switch, modal e alternância manual de tema prontos (o painel é feito de formulários); não tem JS,
portanto não acrescenta superfície de ataque nem manutenção em execução; estar arquivado não obriga a atualizar nada porque o arquivo é
copiado para o repositório (com `LICENSE` e hash em `SHA256SUMS`, como já se faz em `assets/`). Risco residual: sem correções futuras de
bugs de navegador; mitigação: a camada `nebulosa.css` sobrepõe o que for necessário e o plano B (Simple.css) fica documentado. Se o dono
preferir um projeto vivo, é viável **bifurcar o Pico (MIT)** com outro nome, como o README dele autoriza.
Para reduzir peso há variantes `classless` e por cor (`pico.violet.min.css`).

### 4.3 Padrões de UX observados nos dashboards estudados

Fluxo login → lista de servidores (com "Adicionar bot" nos que não têm o bot) → painel do servidor por abas/categorias;
salvar por seção com confirmação; aviso de "alterações não salvas"; estados "sem permissão" e "bot não está no servidor".

---

## 5. Checklist de segurança (para o plano e a auditoria AppSec)

**OAuth2 (Discord)**
- [ ] Authorization code grant no servidor, com `client_secret` em variável de ambiente. `response_type=code`, escopos **`identify guilds`** apenas (`guilds` dá `GET /users/@me/guilds`; `identify` dá `/users/@me`). Não pedir `email`, `guilds.join` nem `guilds.members.read`.
- [ ] `state`: 32 bytes de `secrets.token_urlsafe`, guardado em cookie de curta duração (5–10 min, `HttpOnly`, `Secure`, `SameSite=Lax`, que **precisa ser Lax**, pois o retorno do Discord é navegação cruzada de topo), comparado com `hmac.compare_digest` e **apagado após o uso**. O Discord apenas "recomenda fortemente" o `state` e não o valida; a defesa é nossa. O `OAuth2Mixin` do Tornado não faz isso.
- [ ] **PKCE:** suportado pelo Discord, mas **não descrito na página genérica de OAuth2**. A documentação oficial o cita no guia do Social SDK ("Account Linking": PKCE para clientes públicos, com `code_verifier` na troca do código) e no Embedded App SDK (`code_challenge`, `code_challenge_method: 'S256'`). O painel é cliente confidencial (usa `client_secret`; o guia chama isso de "web flow"), então PKCE é defesa em profundidade opcional, não requisito. Se adotado, testar contra o Discord real. Ver §6.
- [ ] `redirect_uri` fixo, vindo de configuração (ex.: `PANEL_PUBLIC_URL`) e registrado no portal do Discord. Nunca derivar de `Host`/`X-Forwarded-*` (envenenamento de host).
- [ ] Após buscar `identify` e `guilds`, **descartar o token**: `POST /oauth2/token/revoke` (documentado; revoga todos os tokens da autorização). Não guardar `access_token`/`refresh_token` em cookie, log nem banco.
- [ ] Nada de implicit grant. Tratar erros do callback (`error=access_denied`) com mensagem amigável, sem refletir parâmetros sem escape.
- [ ] `https://` em produção; atrás de proxy (Render, Replit), tratar `X-Forwarded-Proto` somente de proxies confiáveis.

**Autorização por servidor**
- [ ] A lista de `/users/@me/guilds` (inclui `owner` e `permissions` como string) serve **só para listar**. A decisão de acesso usa os dados do bot: servidor presente no `BotPool`, membro com `manage_guild`/`administrator` ou dono (`guild.owner_id`), revalidado em toda escrita.
- [ ] IDs de servidor, canal e cargo recebidos no formulário são validados contra o que o bot enxerga naquele servidor (o canal pertence ao servidor? o cargo existe?). Evita IDOR/escrita em outro servidor.
- [ ] Configurações do **dono do bot** (`utils/owner_panel.py`, `legacy_cmds.py`) ficam fora do painel por servidor ou atrás de checagem `is_owner` separada; fora da v1 por padrão.
- [ ] Em multi-bot, resolver qual(is) bot(s) do pool estão no servidor e qual registro de banco é gravado (pergunta ao Backend).

**Sessão e cookies**
- [ ] Cookie de sessão: ID aleatório, `Secure`, `HttpOnly`, `SameSite=Lax`, prefixo `__Host-` quando possível; **gerar novo ID no login** (anti-fixation), expiração absoluta (ex.: 7 dias) e ociosa, logout que invalida no servidor.
- [ ] `cookie_secret` ≥32 bytes aleatórios por variável de ambiente (exigido no start quando o painel está ligado; falhar com mensagem clara se ausente), com rotação por chaves versionadas do Tornado.
- [ ] Não colocar dados do usuário no cookie; só o ID de sessão assinado.

**CSRF e entrada**
- [ ] `xsrf_cookies=True` + `{% module xsrf_form_html() %}` em todo formulário; para requisições htmx, enviar o token no cabeçalho `X-XSRFToken` (via `hx-headers`). Mutações só em `POST`/`PUT`/`DELETE`, nunca em `GET`.
- [ ] Validação de toda entrada no servidor com esquema por campo (tipo, faixa, comprimento, lista de valores); rejeitar campos desconhecidos (mass assignment). Gravar no banco só campos permitidos.
- [ ] Autoescape ligado em todos os templates; sem `{% raw %}` com dado de usuário. Nomes de servidor, canal e cargo vindos do Discord são entrada não confiável.
- [ ] CSP: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://cdn.discordapp.com; frame-ancestors 'none'; form-action 'self'; base-uri 'none'`. Mais `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` e `Cache-Control: no-store` nas páginas autenticadas (o `/` público não deve mudar).
- [ ] Assets vendorizados com versão e hash em `SHA256SUMS` (supply chain); sem CDN em tempo de execução.

**Rate limits**
- [ ] A página oficial lista cabeçalhos `X-RateLimit-*`, 429 com `Retry-After`/`retry_after` e **limite global de 50 req/s para bots**; **IPs com 10.000 respostas 401/403/429 em 10 minutos são bloqueados temporariamente** (relevante em hospedagem com IP compartilhado: não repetir chamadas com token inválido). Os limites por rota de `users/@me/guilds` **não estão documentados**: ler os cabeçalhos em vez de fixar números.
- [ ] Chamar `/users/@me/guilds` **uma vez por login** e guardar o resultado na sessão (em vez de a cada página); respeitar `Retry-After` no 429. A rota retorna até 200 guildas por padrão (paginar com `after` se necessário).
- [ ] Limitar o próprio painel: tentativas de login/callback por IP e escritas por usuário/servidor (balde simples em memória), com resposta 429. O Tornado não traz isso pronto.

**Convite do bot com servidor pré-selecionado (documentado)**
- [ ] `https://discord.com/oauth2/authorize?client_id=<ID_DO_BOT>&scope=bot%20applications.commands&permissions=<INTEIRO>&guild_id=<ID>&disable_guild_select=true`. `guild_id` pré-seleciona o servidor se o usuário tiver permissão nele; `disable_guild_select=true` impede trocar. Convite só com `bot` não precisa de `redirect_uri`/`response_type`.
- [ ] Gerar um link por bot do pool (cada bot tem seu `client_id`); o inteiro de permissões deve vir de uma constante única do projeto (mínimo necessário para música).

**Dados e vazamento**
- [ ] Nada de segredo em arquivo, template ou log; `.example.env` recebe as variáveis novas vazias (nomes a definir com o Backend).
- [ ] Mensagens de erro ao usuário sem traceback nem IDs internos; detalhe só no log do servidor.
- [ ] Trilha de auditoria das alterações (usuário, servidor, campo, data) sem valores sensíveis.

---

## 6. Confirmações pedidas pelo Backend (documentação oficial do Discord)

Fonte primária: repositório oficial `discord/discord-api-docs` (código-fonte de docs.discord.com, lido via `gh api`, push de 2026-10-14) e as páginas em docs.discord.com.

| # | Pergunta | Resposta | Fonte |
|---|---|---|---|
| 1 | O OAuth2 suporta PKCE (S256)? | **Sim, mas só descrito fora da página genérica de OAuth2.** Embedded App SDK lista `code_challenge` e `code_challenge_method: 'S256'`; o guia de Account Linking (Social SDK) mostra a troca com `code_verifier` e diz que clientes públicos devem usar PKCE, enquanto o fluxo web com `client_secret` é "confidential client". A página `topics/oauth2` não menciona PKCE. | https://docs.discord.com/developers/topics/oauth2 · https://docs.discord.com/developers/developer-tools/embedded-app-sdk · https://docs.discord.com/developers/discord-social-sdk/development-guides/account-linking-on-web |
| 2 | `GET /users/@me/guilds`: limites, paginação, `permissions`? | Parâmetros `before`, `after`, `limit` (padrão **200**, intervalo 1–200), `with_counts`, `shard` (só para large bot sharding). Retorna guildas parciais com `id`, `name`, `icon`, `banner`, `owner`, **`permissions` (string)** e `features`. Exige o escopo `guilds`. A docs diz que a paginação "não é necessária" na maioria das integrações. **Rate limit por rota não é documentado** na página; valem os cabeçalhos `X-RateLimit-*` e o 429 com `Retry-After`. | https://docs.discord.com/developers/resources/user · https://docs.discord.com/developers/topics/rate-limits |
| 3 | Tamanho máximo do status de canal de voz | **Até 500 caracteres** (`status`, `?string`; `null`/vazio limpa). `PUT /channels/{id}/voice-status`; exige `SET_VOICE_CHANNEL_STATUS`, e também `MANAGE_CHANNELS` se o usuário/bot não estiver conectado ao canal. Aceita `X-Audit-Log-Reason`. | https://docs.discord.com/developers/resources/channel (seção "Set Voice Channel Status") |
| 4 | Link de convite com servidor pré-selecionado | `https://discord.com/oauth2/authorize?client_id=<ID>&scope=bot%20applications.commands&permissions=<INTEIRO>&guild_id=<ID>&disable_guild_select=true`. `guild_id` pré-preenche o seletor se o usuário puder adicionar o bot ali; `disable_guild_select=true` impede trocar. Informando só `client_id` (+ `permissions`, `guild_id`, `disable_guild_select`) vale a **configuração de instalação padrão do portal**; informar `scope`, `integration_type` ou `redirect_uri` a substitui. Ao redirecionar, `guild_id` chega só como dica (a docs recomenda o "OAuth2 code grant" do bot para ter certeza). | https://docs.discord.com/developers/topics/oauth2 (seção "Bot Authorization Flow" e "Advanced Bot Authorization") |

Observação sobre o status de voz: o limite de 500 é do Discord. O modelo permanente do EmpireMuse (`voice_channel_status`, `SetStageTitle` em `empiremuse/utils/music/interactions/stage_title.py`) é um texto com variáveis; o Backend deve validar o tamanho **depois de expandir o modelo** ou limitar o modelo de forma conservadora (não conferi o limite aplicado hoje no modal).

### 6.1 Verificação dos 13 achados preliminares do Backend (§5 do `pesquisa-backend.md`)

Conferi licença, último push e arquivamento de cada um via `gh api`: **todos os dados confirmados**, sem divergência.
Acréscimos meus: `discord-ext-ipc` está arquivado (`archived=true`); `Discord-Bot-Web-Panel` é GPL-3.0 (⚠ GPL-3.0-only é incompatível com incorporação em GPL-2.0-only); `tutorial-dashboard` sem licença (`NONE`); `requests-oauthlib` é ISC mas síncrono (concordo em descartar); `quartcord` MIT, 2 ★, parado desde 2023-12.
Sobre `discord-oauth2.py` ("a verificar"): MIT, 52 ★, push 2026-01-12, mantenedor único; **não inspecionei o código** (o código só poderia ser lido, não executado). Sobre Authlib ("a verificar"): o repositório não tem integração Tornado (apenas Django, Flask, Starlette, httpx, requests), mas oferece cliente OAuth2 assíncrono via httpx; **concordo com o Backend: escrever o fluxo próprio** (nenhuma dependência nova).
Concordo integralmente com a recomendação do Backend (Tornado nativo + fluxo OAuth próprio).

---

## 7. Dúvidas para o dono / pontos em aberto

1. **Aceitar o Pico CSS arquivado** (vendorizado, congelado) ou preferir um kit vivo (Simple.css, com mais CSS próprio)?
2. **Qual bot do pool será o cliente OAuth2 de login?** A escolha afeta o `redirect_uri` e o convite.
3. **PKCE:** suportado, mas opcional para cliente confidencial; manter só `state` + `client_secret` na v1 ou adicionar PKCE como defesa em profundidade?
4. **Opções do dono do bot** (`owner_panel`) ficam fora do painel na v1?
5. **Hospedagens com IP compartilhado** (Replit/Render): aceitar o limite de 10.000 respostas inválidas/10 min como risco residual?

---

## 8. Fontes

- Fonte-base da documentação do Discord (lida via `gh api`): https://github.com/discord/discord-api-docs (`developers/topics/oauth2.mdx`, `developers/resources/channel.mdx`, `developers/resources/user.mdx`)
- Discord OAuth2: https://docs.discord.com/developers/topics/oauth2
- Discord rate limits: https://docs.discord.com/developers/topics/rate-limits
- Discord `GET /users/@me/guilds`: https://docs.discord.com/developers/resources/user
- Tornado (Context7 `/websites/tornado-doc_readthedocs_io_en`): https://www.tornadoweb.org/en/stable/auth.html · https://www.tornadoweb.org/en/stable/guide/security.html · https://github.com/tornadoweb/tornado
- htmx: https://github.com/bigskysoftware/htmx (LICENSE: Zero-Clause BSD; releases v2.0.10, v4.0.0)
- Pico CSS: https://github.com/picocss/pico (arquivado em 2026-10-04) · https://picocss.com
- Simple.css: https://github.com/kevquirk/simple.css · MVP.css: https://github.com/andybrewer/mvp · Water.css: https://github.com/kognise/water.css · Basecoat: https://github.com/hunvreus/basecoat · Oat: https://github.com/knadh/oat · Tabler: https://github.com/tabler/tabler
- Authlib: https://github.com/authlib/authlib · https://pypi.org/project/Authlib/
- fastapi-discord: https://github.com/Tert0/fastapi-discord · starlette-discord: https://github.com/nwunderly/starlette-discord · Flask-Discord: https://github.com/weibeu/Flask-Discord · discord-oauth2.py: https://github.com/treeben77/discord-oauth2.py · ext-oauth2: https://github.com/Snipy7374/ext-oauth2 · discord-ext-ipc: https://github.com/Ext-Creators/discord-ext-ipc
- Dashboards: https://github.com/MrAugu/simple-discordjs-dashboard · https://github.com/LachlanDev/Discord-BOT-Dashboard-V2 · https://github.com/fuma-nama/discord-bot-dashboard-next · https://github.com/botlabs-gg/yagpdb · https://github.com/Cog-Creators/Red-Dashboard · https://github.com/ZeppelinBot/Zeppelin (LICENSE.md: Elastic License 2.0) · https://github.com/Discord-Dashboard/Core · https://www.npmjs.com/package/discord-dashboard · https://github.com/RayExo/ZyroX-CV2-AIO-With-Dashboard
- Código local consultado (somente leitura): `run_app` e `start` em `empiremuse/web_app.py`, `BotPool.setup` em `empiremuse/utils/client.py`, `requirements.txt:15`.

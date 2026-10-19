# Painel Web — Pesquisa de Frontend (etapa P-0)

> Autor: Frontend Specialist · Data: 2026-10-15 · Branch: `feat/painel-web`
> Status: **pesquisa, sem código de produção**.
> Escopo (ajuste do dono em 2026-10-15): a **pesquisa externa** (projetos prontos, bibliotecas, UI kits) é do
> agente *DeepSearch Researcher* (`docs/painel/pesquisa-externa.md`). Este documento cobre **(2) abordagem de
> renderização, (3) wireframes e (4) identidade visual**, e traz apenas os **achados preliminares** da pesquisa
> externa que eu já tinha feito antes do ajuste.
> Complementa `docs/painel/pesquisa-backend.md` (inventário de configurações e arquitetura do Backend).

---

## 1. Achados preliminares (pesquisa externa interrompida)

Coletados em 2026-10-15 com `gh search repos` / `gh api` (estrelas, licença e último commit). Nada foi clonado,
instalado ou executado. **Não é a pesquisa completa**: o DeepSearch Researcher é a fonte oficial e pode corrigir
qualquer item. Critério de licença (projeto **GPL-2.0**): MIT/BSD/ISC/0BSD/LGPL/GPL-2.0+ compatíveis;
Apache-2.0 e GPL-3.0-only ⚠ sinalizar; sem licença = não reutilizável.

**Dashboards de bots Discord (todos Node/React; nenhum em Python/Tornado):**

| Projeto | Licença | Último commit | ★ | Stack | Leitura preliminar |
|---|---|---|---|---|---|
| MrAugu/simple-discordjs-dashboard | MIT | 2026-06 | 240 | Express + EJS + passport-discord | Mesmo padrão que propomos (templates no servidor + OAuth + sessão); só inspiração. |
| LachlanDev/Discord-BOT-Dashboard-V2 | MIT | 2026-03 | 241 | Node/JS | Acoplado a discord.js; descartar. |
| fuma-nama/discord-bot-dashboard-next | MIT | 2024-05 (arquivado) | 235 | Next 13, React, Chakra UI | Só inspiração visual (login → servidores → abas); exige build Node. |
| fuma-nama/discord-bot-dashboard | MIT | 2023-07 | 130 | React 17, Chakra 1 | Desatualizado. |
| aelumiya/Discord-Dashboard | MIT | 2023-01 | 22 | Flask + Bootstrap | Abandonado. |
| julianYaman/discord-bot-dashboard · DarrenOfficial/DiscordMusicBot-Dashboard | **sem licença** | 2022 / 2021 | 319 / 0 | TS / JS | Não reutilizáveis. |

**OAuth2 do Discord em Python (para o Backend):** Tert0/fastapi-discord (MIT, só FastAPI), nwunderly/starlette-discord
(MIT, só Starlette), quartcord (MIT, só Quart), Authlib (BSD-3, genérico, mantido). Nenhum serve direto ao Tornado.

**Kits de UI / CSS / interação (licenças verificadas):**

| Projeto | Licença | Versão / data | ★ | Observação preliminar |
|---|---|---|---|---|
| Pico CSS | MIT | v2.1.1 (final; repo **arquivado em 2026-10-04**, ver §2.5) | 16,8 mil | CSS semântico, sem JS, variáveis CSS; `pico.min.css` = 83 KB (medido). Candidato à base. |
| htmx | **0BSD** (LICENSE confere; GitHub mostra "other") | 2.0.10 (2026-09); 4.0.0 em 2026-08 | 49,6 mil | Sem build. Preferir linha 2.x; v4 é recente. |
| Alpine.js | MIT | 3.17.4 | 32 mil | Build padrão usa `eval` (CSP); existe build CSP. Opcional. |
| Tabler | MIT | core 1.6.1 (2026-09) | 41,9 mil | Layout de admin; exige pnpm/Node. Inspiração de layout. |
| AdminLTE · CoreUI Free · Bootstrap · daisyUI | MIT | recentes | 12 mil–175 mil | Pesados e/ou exigem build (daisyUI = Tailwind). Descartados nesta leitura. |

Itens a confirmar pelo DeepSearch: pesos reais minificados, acessibilidade auditada de cada kit e candidatos
que eu não encontrei (ex.: kits Tailwind/HTMX para admin, componentes headless). Os achados acima foram enviados
ao DeepSearch via Maestri.

---

## 2. Abordagem de renderização

### 2.1 Opção A — Templates no servidor (Tornado) + JS próprio sobre a API JSON

Páginas HTML renderizadas por `RequestHandler.render()` com os dados já preenchidos; um módulo JS pequeno e próprio
envia as alterações à API JSON do Backend (ver §2.4). *(Na primeira versão deste documento eu propunha htmx com
formulários HTML; o contrato JSON do Backend mudou isso.)*

Prós
- **Mesmo processo e mesma porta** do `web_app.py`: basta registrar rotas `/painel/...` no `tornado.web.Application`
  existente (`run_app` em `empiremuse/web_app.py`). Zero processo extra, zero build, zero Node em produção.
- Segurança mais simples de auditar: autorização e validação **no servidor**; cookie assinado
  (`set_secure_cookie`), `xsrf_cookies=True` + `{% module xsrf_form_html() %}` nativos do Tornado; autoescape ligado.
- Funciona em todas as hospedagens suportadas (Replit, Render, SquareCloud, Docker, local): só adiciona arquivos
  estáticos e templates.
- Leve e rápido em celular; acessibilidade vem do HTML semântico. Contribuição fácil (HTML + Python).

Contras
- Interatividade rica (reordenar, preview ao vivo de skin) exige JS manual (módulos locais); htmx/Alpine-CSP podem ser avaliados depois da v1.
- Menos "app-like"; cada navegação vai ao servidor (aceitável em painel de configuração).
- Sem componentização de frontend (mitigar com *partials* de template e um guia de componentes).

### 2.2 Opção B — SPA com build separado (React/Vue + API JSON)

Prós: UX fluida, ecossistema de componentes, preview em tempo real fácil.
Contras (decisivos aqui):
- Exige **pipeline Node/pnpm** e artefatos de build; o bot hoje é 100 % Python e roda em hospedagens baratas.
- Dobra a superfície de segurança: API JSON completa + CORS + token no navegador (XSS pode vazar sessão).
- Dependências npm ampliam a superfície de *supply chain* (a regra do projeto exige versões fixas e hashes).
- Os templates prontos encontrados estão arquivados/desatualizados (ver §1).

### 2.3 Impacto no deploy junto com o bot

| Aspecto | A (Tornado + JS próprio) | B (SPA) |
|---|---|---|
| Processo / porta | Mesmo do bot, rotas `/painel/*` | Mesmo, mais servir `dist/` estático |
| Build | Nenhum (assets vendorizados) | Obrigatório (Node) |
| Replit/Render/SquareCloud | Funciona como está | Precisa de passo de build ou `dist` versionado |
| Docker | Nenhuma alteração | Estágio extra de build |
| Auditoria AppSec | Pequena (handlers + templates) | Grande (API + bundle) |

**Rotas que não podem ser quebradas:** `/` (status) e `/ws` (RPC) continuam intactas; o painel vive sob `/painel`.
O painel só sobe quando habilitado por configuração (ex.: `ENABLE_PANEL`) e exige `PANEL_PUBLIC_URL`
(para o `redirect_uri` do OAuth) — nomes a definir com o Backend.

### 2.4 Recomendação (revisada após o contrato do Backend)

O Backend definiu uma **API JSON** versionada (`/painel/api/v1`, `docs/painel/pesquisa-backend.md` §6) com ETag/`If-Match`,
erros `{erro:{codigo,mensagem}}` e ações longas com `202` + polling. Isso muda a recomendação de interatividade:

**Páginas renderizadas pelo Tornado (templates) + um pequeno módulo JS próprio (sem biblioteca de terceiros) que
fala com a API JSON.** Detalhes:
- **Carga inicial:** o handler da página chama a mesma camada de serviços da API e renderiza o HTML já preenchido
  (autoescape). Sem tela em branco, bom para acessibilidade e para o primeiro carregamento no celular.
- **Salvar:** o JS intercepta o `<form>`, envia `PATCH/PUT/POST` JSON com `X-XSRFToken` (lido de uma `<meta>`) e
  `If-Match` (ETag recebida), e trata `200/202/412/422/429/403/401`. O servidor continua sendo a única fonte de
  validação; o JS só mostra os erros por campo.
- **JS é necessário para salvar** (o contrato não tem `POST` de formulário HTML). Aceitável para um painel
  administrativo; sem JS a página mostra os valores e um aviso "ative o JavaScript para editar".
- **htmx sai da recomendação** (ele troca fragmentos HTML; o contrato é JSON) e **Alpine segue fora**. Resultado:
  **zero JS de terceiros**, nenhuma CDN, CSP simples (`script-src 'self'`, sem `unsafe-inline`/`unsafe-eval`; nonce só
  se o Backend precisar de script inline) e menos supply chain para o AppSec auditar.
- **CSS:** kit leve e semântico sob tema Nebulosa; candidatos e ressalvas na §2.5 (**decisão do dono**). Não precisa de build.
- **Arquivos estáticos:** `panel/static/` (CSS, `painel.js` modular, logos). Cabeçalho `Cache-Control` com nome versionado.

Divergência registrada com o DeepSearch (`pesquisa-externa.md` §4): ele recomenda htmx 2.0.10 (0BSD, vendorizado) por
partir de páginas com fragmentos HTML. Com o contrato JSON do Backend, minha proposta é JS próprio; se o dono/MAESTRO
preferir htmx, o contrato precisaria de rotas que devolvam fragmentos HTML. **Ponto a decidir no plano (P-1).**

Alternativa mantida em aberto: se o dono quiser mais interatividade (preview ao vivo de skin, arrastar), avaliar
htmx/Alpine-CSP **depois da v1**, sem mudar o contrato.

Rotas de página (HTML) propostas, compatíveis com as do Backend (`/painel/login`, `/painel/callback`, `/painel/logout`):
`/painel` → `/painel/servidores` → `/painel/servidores/{gid}/{categoria}`; `/painel/conta`; `/painel/dono`.
(Troquei meu `/entrar`/`/servidor` por `/login` e `/servidores/{gid}`, em linha com a API.)


### 2.5 Kit de CSS — arquivamento do Pico e plano B (sem decisão; vai ao dono)

Informação do DeepSearch (`pesquisa-externa.md` §4.2, pesos medidos por ele com `gzip -9`):

| | Pico CSS 2.1.1 | Simple.css 2.3.7 |
|---|---|---|
| Licença | MIT | MIT |
| Manutenção | ⚠ **repositório arquivado em 2026-10-04**; 2.1.1 (2025-03-15) é a versão final | Ativa (push 2026-07-19; última release 2025-05-29) |
| Peso (min / gzip) | 83,3 KB / 11,6 KB | 9,4 KB / 2,8 KB |
| Tema escuro | `data-theme` claro/escuro + `prefers-color-scheme`; variações de cor (há violeta, roxo, fúcsia) | só `prefers-color-scheme` (sem alternância manual) |
| Acessibilidade | `:focus-visible`, `prefers-reduced-motion` | `:focus-visible`; sem `reduced-motion` |
| Componentes | formulários, `<dialog>`, `<details>`, grid, switch | estiliza tags; **sem** switch/modal/grid de painel |
| Trabalho extra | menos CSS próprio | mais CSS próprio (`nebulosa.css`: interruptores, `dialog`, grade de skins, cartões) |

Leitura de frontend (não é decisão):
- Pico arquivado é aceitável para um arquivo **vendorizado e congelado** (sem JS, nada a atualizar em execução); a
  licença MIT permite fork se surgir bug de navegador. Deve constar no ADR com versão e hash (`SHA256SUMS`).
  O painel precisa de interruptores, `dialog` de confirmação e grade, o que o Pico já estiliza.
- Simple.css é vivo e minúsculo, mas exigiria escrever esses componentes (CSS próprio estimado em algumas centenas
  de linhas) e adicionar o controle de `prefers-reduced-motion`; em contrapartida, deixa a identidade Nebulosa mais
  autoral e reduz o peso.
- Em qualquer caso, uma camada `nebulosa.css` própria define os tokens da §4.1 por cima do kit.

**Pergunta ao dono:** aceitar o Pico CSS arquivado (vendorizado, congelado) ou preferir o kit vivo (Simple.css) com mais
CSS próprio? Até a resposta, o plano e os protótipos assumem apenas a camada `nebulosa.css` + tokens, sem fixar o kit.

---

## 3. Wireframes (ASCII)

Convenções: `[Botão]`, `( ) rádio`, `[x] caixa`, `[ ▾ ]` select, `⟨…⟩` conteúdo dinâmico. Textos em pt-BR.

### 3.1 Login com Discord (`/painel/login`)

```
┌───────────────────────────────────────────────────────────┐
│                  (nebulosa ao fundo)                      │
│                       ╭───────╮                           │
│                       │ logo  │  EmpireMuse               │
│                       ╰───────╯                           │
│        Painel de controle do seu bot de música            │
│                                                           │
│   ┌─────────────────────────────────────────────┐         │
│   │  [  Entrar com o Discord  ]                 │         │
│   └─────────────────────────────────────────────┘         │
│   Pedimos apenas: identificar sua conta e listar seus     │
│   servidores. Não lemos mensagens nem enviamos nada.      │
│                                                           │
│   Privacidade · Suporte (Discord EmpireHUB)               │
└───────────────────────────────────────────────────────────┘
```
Estados: *login negado/cancelado* → `⚠ Login cancelado. Tente novamente.`; *state inválido/expirado* →
`⚠ Sessão de login expirada. Clique em entrar de novo.`; *painel desativado* → página 503 neutra.

### 3.2 Seleção de servidor (`/painel/servidores`)

```
┌ EmpireMuse ───────────────────────────── ⟨avatar⟩ Nome ▾ ┐
│ Escolha um servidor                      [🔎 filtrar…]     │
│                                                           │
│ Você gerencia                                             │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│ │ ⟨ícone⟩      │ │ ⟨ícone⟩      │ │ ⟨ícone⟩      │        │
│ │ Servidor A   │ │ Servidor B   │ │ Servidor C   │        │
│ │ ● Bot aqui   │ │ ● Bot aqui   │ │ ○ Bot ausente│        │
│ │ [Configurar] │ │ [Configurar] │ │ [Adicionar   │        │
│ │              │ │              │ │  o bot ↗]    │        │
│ └──────────────┘ └──────────────┘ └──────────────┘        │
│                                                           │
│ Sem permissão                                             │
│  Servidor D — precisa de "Gerenciar Servidor"  [desativado]│
└───────────────────────────────────────────────────────────┘
```
- "Configurar" só aparece se o **servidor confirmou** a permissão (Gerenciar Servidor/Administrador) com dados do
  próprio bot — não apenas pela lista do OAuth.
- "Adicionar o bot" abre o convite do bot em nova aba (multi-bot: `[Escolher bot ▾]` antes do botão).
- Lista vazia: `Você ainda não gerencia nenhum servidor. Peça a permissão "Gerenciar Servidor" ou crie um servidor.`

### 3.3 Painel do servidor (`/painel/servidores/⟨gid⟩/⟨categoria⟩`)

```
┌ EmpireMuse ─ Servidor A ▾ ─────────────── ⟨avatar⟩ Nome ▾ ┐
│ ┌────────────┐ ┌──────────────────────────────────────────┐│
│ │ ▸ Geral    │ │  Player                                  ││
│ │   Player   │ │  Player  [Neste bot]  Bot: [EmpireMuse #1 ▾]││
│ │   Canal do │ │  Volume padrão        [ 100 ▾ ]  (5–150) ││
│ │   player   │ │  [x] Autoplay                            ││
│ │   Cargos DJ│ │  [ ] Modo restrito (só DJs/quem pediu)   ││
│ │   Aparência│ │  [x] Não conectar se houver bots         ││
│ │   Links    │ │      incompatíveis na chamada            ││
│ │   Todos os │ │                                          ││
│ │   bots     │ │  ⚠ Acima de 100 % o áudio pode distorcer ││
│ │            │ │ ┌──────────────────────────────────────┐ ││
│ │            │ │ │ [Salvar alterações] [Descartar]      │ ││
│ └────────────┘ │ └──────────────────────────────────────┘ ││
└────────────────┴──────────────────────────────────────────┘
```

#### 3.3.1 Categorias e cobertura do inventário (conferido com `pesquisa-backend.md` §2 e §6)

Cada categoria é uma página com um `<form>` por **seção** e botão "Salvar" próprio; cada seção casa com **um** endpoint
do contrato (cada salvamento é uma chamada). Selo ao lado do título: **`Neste bot`** (campo por bot, camada `b`) ou
**`Todos os bots`** (global, camada `g`).

| Categoria (URL `…/servidores/{gid}/…`) | Itens do inventário | Endpoint do contrato | Controles |
|---|---|---|---|
| **Geral** (`geral`) | Resumo (G-18/G-19): bots presentes (nome, avatar), estado do player, **seletor de bot**, **"Adicionar mais bots"** | `GET /servidores/{gid}` | Cartões somente leitura; botão de convite por bot do pool |
| **Player** (`player`) · *Neste bot* | **G-01** volume (5–100 passo 5; 110–150 passo 10), **G-02** autoplay, **G-03** evitar outros bots, **G-04** modo restrito | `PATCH …/player` `{volume_padrao, autoplay, evitar_outros_bots, modo_restrito}` + `bot_id` | Select com os 23 valores válidos (aviso ⚠ acima de 100), 3 interruptores |
| **Canal do player** (`canal`) · *Neste bot* | **G-06** setup (escolher canal existente ou criar; limpar mensagens; título do fórum 4–30), **G-07** reset (apagar canal sim/não) | `POST …/canal-player` (`202` + `tarefa_id`) · `DELETE …/canal-player?confirmar=1` · `GET /tarefas/{id}` | Select de canais (texto/voz/fórum/palco) + "criar novo", interruptor, **barra de progresso** (polling), botão perigoso **com confirmação dupla** |
| **Cargos de DJ** (`dj`) · *Neste bot* | **G-05** cargos de DJ (sem `@everyone`, sem duplicata) | `PUT …/dj-cargos` `{cargos:[id…]}` | Lista de cargos com `+ Adicionar` (select) e `✕`; salva a lista inteira |
| **Aparência** (`aparencia`) | **G-08** skin normal, **G-09** skin do canal de pedidos *(Neste bot)*; **G-10** skin global ligada, **G-11** skin global normal/song-request *(Todos os bots)* | `PATCH …/skins` `{normal, song_request, global_ativa, global_normal, global_song_request}` | Grade de skins com **preview** (imagem), duas seleções, interruptor "Usar a mesma skin em todos os bots". **G-14 skins personalizadas: cartão desativado "Em breve"** (fora da v1) |
| **Links fixos** (`links`) · *Neste bot* | **G-16** favoritos do servidor (máx. 25; exige canal do player configurado; URL válida; nome ≤ limite do dono) | `GET/POST …/links` · `PUT/DELETE …/links/{nome}` · `POST …/links:importar` | Tabela (nome, URL, descrição) com editar/remover, formulário "Adicionar", **importar JSON** (arquivo/colar); contador `n/25` |
| **Todos os bots** (`global`) · *Todos os bots* | **G-12** prefixo (1–5 caracteres, sem espaço; vazio = padrão), **G-13** status do canal de voz (modelo com placeholders), **G-15** convites "ouvir junto" (listar/remover; máx. 5) | `PATCH …/prefixo` · `PUT …/status-voz` · `GET …/ouvir-junto` · `DELETE …/ouvir-junto/{canal}` | Campo curto com contador; textarea + lista de placeholders clicáveis; lista com `Remover` |

Sem tela (registrado de propósito): **G-14** (formato de armazenamento legado inseguro, rastreado em privado, S-04; só o cartão "Em breve") e **G-17** (campo órfão
`enable_prefixed_commands`, nenhum código o usa). Adicionar convite "ouvir junto" fica para v1.1 (depende de
`fetch_invite`); a categoria mostra "Para criar um convite use `/listenalong` no Discord".

**Área do usuário — `/painel/conta`** (U-01…U-05; só dados do próprio usuário logado):

| Seção | Itens | Endpoint | Controles |
|---|---|---|---|
| Prefixo pessoal | **U-01** (1–5 caracteres, sem espaço) | `PATCH /eu/prefixo` | Campo curto + "Restaurar padrão" |
| Favoritos | **U-02** (máx. `MAX_USER_FAVS`; nome ≤ 35; URL ≤ 90 — limites vêm da API) | `GET/POST /eu/favoritos`, `PUT/DELETE …/{nome}`, `POST …:importar` | Tabela + adicionar + importar JSON, contador `n/máx` |
| Integrações | **U-03** (listar/remover/importar; adicionar por URL só no Discord) | `GET /eu/integracoes`, `DELETE …/{titulo}`, `POST …:importar` | Lista com `Remover`, importar JSON |
| Last.fm | **U-04** scrobble | `PATCH /eu/lastfm` | Interruptor; sem conta vinculada → aviso "Vincule com `/lastfm` no Discord" e controle desativado |
| Token do app de RPC | **U-05** (**depende da decisão D-4**) | `POST /eu/rpc-token:regenerar` | Botão "Gerar novo token" → modal mostra o valor **uma única vez** com "Copiar" e aviso; nunca reexibido |
| Histórico | **U-06** somente leitura — **sem tela na v1** | — | — |

**Área do dono — `/painel/dono`** (só `OWNER_IDS`; v1 = diagnóstico):

| Seção | Itens | Endpoint | Controles |
|---|---|---|---|
| Bots | Bots do pool: id, nome, servidores, latência, Lavalink | `GET /dono/bots` | Tabela somente leitura |
| Configuração | 101 chaves agrupadas (Identidade, Webhooks/log, Banco, Música/player, Sessões, Lavalink, Spotify/Last.fm, RPC/web, Presenças, Intents); **segredos mascarados** (`configurado ✓`) | `GET /dono/config` | Acordeão por grupo (`<details>`), busca por chave; selo "exige reinício" nas intents |
| Ações | **O-1** recarregar config, **O-2** recarregar skins | `POST /dono/acoes/recarregar-config`, `…/recarregar-skins` | Dois botões com confirmação simples e resultado em aviso. **Nada** de shell/update/exportsource (O-4/O-5/O-6 vetados) |
| Fora da v1 | O-3 (recarregar módulos, opcional), O-7 (gestão de servidores, v2) | — | — |

> Cobertura: 19 itens de servidor (17 com tela ou cartão informativo; G-14 e G-17 sem tela), 6 de usuário
> (U-01…U-05 com tela; U-06 sem), 101 chaves + O-1/O-2 do dono. Os itens O-3…O-7 ficam fora da v1 conforme o Backend.

#### 3.3.2 Padrões de formulário (valem para todas as categorias)
- Um `<form>` por seção; o JS envia JSON e mostra o resultado em um aviso `aria-live="polite"`.
- Campos com `label` visível, texto de ajuda (`aria-describedby`) e erro em linha (`aria-invalid="true"` + mensagem
  vinda de `erro.mensagem`), sem depender só de cor.
- "Salvar" fica desativado até haver alteração; aviso ao sair com alterações não salvas.
- **Edição concorrente (`412`):** faixa "Esta configuração foi alterada por outra pessoa (ou pelo bot) enquanto você
  editava. [Recarregar] [Ver diferenças]"; os valores digitados ficam preservados até o usuário decidir.
- **Ação longa (`202`):** botão vira "Aplicando…" + barra/lista de etapas, polling de `GET /tarefas/{id}` a cada 1–2 s
  (com limite e `aria-busy`); resultado final em aviso de sucesso/erro e a página recarrega os dados.
- **Confirmação dupla** (reset do canal, G-07): 1º `<dialog>` explica o efeito ("Pode **apagar o canal** ou post");
  2º passo exige marcar "Entendo que isto não pode ser desfeito" e digitar `RESETAR`; só então o botão vermelho habilita.
- IDs Discord são **strings**; selects mostram nomes (de `…/recursos`), e o servidor valida que cada ID pertence ao servidor.
- Textos em pt-BR iguais aos dos comandos do bot.


### 3.4 Estados de erro e "sem permissão"

```
 403  Sem permissão                 404  Servidor não encontrado       409  Bot ausente
┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐
│ 🔒 Você não pode         │  │ 🔭 Não achamos esse      │  │ 🤖 O EmpireMuse não está │
│ configurar este servidor │  │ servidor                 │  │ neste servidor           │
│ Precisa de "Gerenciar    │  │ Ele pode ter sido        │  │ [Adicionar o bot ↗]      │
│ Servidor" ou             │  │ removido ou o link       │  │ [Voltar aos servidores]  │
│ "Administrador".         │  │ está incorreto.          │  │                          │
│ [Voltar aos servidores]  │  │ [Voltar aos servidores]  │  │                          │
└──────────────────────────┘  └──────────────────────────┘  └──────────────────────────┘
 Sessão expirada (401): "Sua sessão expirou. [Entrar de novo]" (volta à página de destino validada)
 Erro de validação (422): faixa no topo "Corrija 2 campos" + erro em cada campo
 Muitas requisições (429): "Muitas alterações seguidas. Tente de novo em ⟨n⟩ s."
 Erro do servidor (500): mensagem genérica + código de referência; detalhes só no log do servidor
 Permissão revogada durante a edição: salvar devolve 403 e mantém os valores digitados
```
Princípio: mensagens **genéricas** ao usuário (sem stack trace, tokens ou IDs internos).

### 3.5 Versão mobile (< 640 px)

```
┌──────────────────────┐   ┌──────────────────────┐
│ ☰  EmpireMuse   ⟨av⟩ │   │ ← Player             │
├──────────────────────┤   ├──────────────────────┤
│ Seus servidores      │   │ Volume padrão        │
│ ┌──────────────────┐ │   │ [ 100            ▾ ] │
│ │⟨ícone⟩ Servidor A│ │   │ Autoplay        [ ●] │
│ │ ● Bot aqui    ›  │ │   │ Modo restrito   [○ ] │
│ └──────────────────┘ │   │ Sem bots incompat.[●]│
│ ┌──────────────────┐ │   │                      │
│ │⟨ícone⟩ Servidor C│ │   ├──────────────────────┤
│ │ ○ [Adicionar bot]│ │   │ [   Salvar   ]       │
│ └──────────────────┘ │   └──────────────────────┘
└──────────────────────┘
 Categorias: o "☰" abre a lista em tela cheia (<details>/<dialog>, sem JS obrigatório);
 barra "Salvar" fixa no rodapé; alvos de toque ≥ 44 px; uma coluna; tabelas viram cartões.
```

### 3.6 Navegação e fluxo

```
/painel ──(sem sessão)──▶ /painel/login ──▶ Discord OAuth ──▶ /painel/callback ──▶ /painel/servidores
                                                                         └─(erro)─▶ /painel/login?erro=…
/painel/servidores ──▶ /painel/servidores/⟨gid⟩ (= geral) ──▶ /painel/servidores/⟨gid⟩/⟨categoria⟩
/painel/conta   (qualquer usuário logado)       /painel/dono  (só OWNER_IDS; senão 403)
POST /painel/logout ──▶ revoga o token, destrói a sessão ──▶ /painel/login
```

### 3.7 Telas adicionais (wireframes)

**Seletor de bot (multi-bot, G-18)** — aparece no topo das páginas de servidor quando há mais de um bot do pool:

```
 Configurando: [ EmpireMuse #1 ▾ ]   ← bot que atende este servidor
 ┌ Player ─ [Neste bot] ────────────────────────────────┐   ┌ Prefixo ─ [Todos os bots] ──────────┐
 │ Estas opções valem só para o EmpireMuse #1.          │   │ Vale para todos os bots do servidor. │
```
O selo deixa claro o alcance; trocar de bot recarrega a página com `?bot_id=`. Com um só bot, o seletor não aparece.

**Canal do player (G-06/G-07) com ação longa e reset**

```
 Canal do player  [Neste bot]
 Canal atual: #pedidos-de-musica  ✓         Permissões do bot: ✓ Gerenciar canais  ✓ Gerenciar mensagens
 ┌ Configurar ──────────────────────────────────────────────┐
 │ ( ) Usar um canal existente   [ #geral            ▾ ]    │
 │ ( ) Criar um canal novo                                  │
 │ [ ] Limpar as mensagens do canal (até 100)               │
 │ Título do post (fórum, 4–30 caracteres)  [____________]  │
 │ [ Aplicar ]    → "Aplicando… (2/3) criando mensagem"     │
 └──────────────────────────────────────────────────────────┘
 ┌ Zona de perigo ──────────────────────────────────────────┐
 │ Resetar o canal do player                                │
 │ [ ] Também apagar o canal/post     [ Resetar… ] (vermelho)│
 └──────────────────────────────────────────────────────────┘
   Diálogo 1: "Resetar o canal do player?" [Cancelar] [Continuar]
   Diálogo 2: [x] Entendo que isto não pode ser desfeito · Digite RESETAR: [______] [Resetar agora]
```

**Aparência (G-08…G-11)**

```
 Aparência
 Skin do player (neste bot)           Skin do canal de pedidos (neste bot)
 ┌────────┐ ┌────────┐ ┌────────┐     ┌────────┐ ┌────────┐ ┌────────┐
 │ ⟨prev⟩ │ │ ⟨prev⟩ │ │ ⟨prev⟩ │     │ ⟨prev⟩ │ │ ⟨prev⟩ │ │ ⟨prev⟩ │
 │ default│ │ classic│ │ mini   │ ...  │ default│ │ classic│ │ mini   │ ...
 │  (●)   │ │  ( )   │ │  ( )   │     │  ( )   │ │  (●)   │ │  ( )   │
 └────────┘ └────────┘ └────────┘     └────────┘ └────────┘ └────────┘
 [x] Usar a mesma skin em todos os bots  [Todos os bots]   normal: [ default ▾ ]  pedidos: [ classic ▾ ]
 ┌ Skins personalizadas ─ Em breve ───────────────────────────────┐
 │ Estamos migrando o editor para um formato mais seguro.         │  (cartão desativado, sem ação)
 └────────────────────────────────────────────────────────────────┘
 [ Salvar ]
```
Cada skin é um `radio` com imagem de preview e nome (`<label>` envolve a imagem; `alt` descritivo).

**Links fixos (G-16) e favoritos pessoais (U-02)** — mesma tela, endpoints diferentes:

```
 Links fixos do servidor [Neste bot]                                   3/25
 ┌──────────────┬───────────────────────────────┬──────────────┬────────┐
 │ Nome         │ URL                           │ Descrição    │ Ações  │
 │ Lo-fi        │ https://…                     │ para estudar │ ✎  🗑  │
 └──────────────┴───────────────────────────────┴──────────────┴────────┘
 Adicionar: Nome [____]  URL [________]  Descrição [____]  [Adicionar]      [Importar JSON…] 
 Sem canal do player configurado → "Configure o canal do player primeiro." (formulário desativado)
```

**Todos os bots (G-12, G-13, G-15)**

```
 Prefixo do servidor [Todos os bots]     [ !m ]  1–5 caracteres, sem espaços   (vazio = padrão ⟨!⟩)
 Status do canal de voz [Todos os bots]  [ 🎵 {track.title}                    ]  placeholders: [{track.title}] [{track.author}] …
 Convites "ouvir junto"  (máx. 5)        • #sala-1  discord.gg/…  [Remover]      Para criar: use /listenalong no Discord
```

**Edição concorrente (412)**

```
 ⚠ Esta configuração foi alterada enquanto você editava.   [Recarregar valores atuais]   [Manter meus valores e revisar]
```

**Conta** (`/painel/conta`) e **Dono** (`/painel/dono`), desktop:

```
 Minha conta ─ ⟨avatar⟩ Nome
 ├ Prefixo pessoal  [ ! ] [Salvar]
 ├ Favoritos        tabela (3/10) · [Importar JSON…]
 ├ Integrações      lista · [Importar JSON…]
 ├ Last.fm          Conta: ⟨usuário⟩ · Scrobble [●]   (ou "Vincule com /lastfm")
 └ App de RPC       [Gerar novo token]  → modal: "Copie agora; não será exibido de novo" [Copiar]

 Dono ─ somente leitura + 2 ações
 ├ Bots (tabela)      ├ Configuração ▸ Identidade ▸ Banco (MONGO: configurado ✓) ▸ Lavalink …
 └ Ações: [Recarregar config] [Recarregar skins]
```

### 3.8 Contrato: o que o frontend consome e o que ainda precisa ser acrescentado

Páginas (HTML, Tornado) usam as mesmas rotas/serviços da API. Eu **só dependo** do que está em §6 do Backend, mais
estes pedidos (nome e formato propostos; o Backend decide):

| # | Pedido ao contrato | Motivo (tela) | Formato proposto |
|---|---|---|---|
| 1 | `GET /servidores/{gid}/config` agrupar por alcance | selos "Neste bot" / "Todos os bots" | `{por_bot:{player,dj_cargos,skins,links,canal_player}, globais:{prefixo,status_voz,skin_global,ouvir_junto}, etag}` |
| 2 | `GET /servidores/{gid}/recursos` com **permissões do bot** | avisar antes do setup (G-06/G-07) | `permissoes_bot:{gerenciar_canais,gerenciar_mensagens,gerenciar_threads:bool}` |
| 3 | `recursos.skins` com **preview** | grade de skins | `[{id, nome, modo:"normal"|"song_request", preview_url}]` (URL vinda de `asset_url`) |
| 4 | `recursos.status_voz` | G-13 | `{placeholders:["{track.title}",…], tamanho_max:int}` |
| 5 | `GET /tarefas/{id}` | polling do G-06/G-07 | `{estado:"pendente"\|"executando"\|"ok"\|"erro", etapa?, total_etapas?, mensagem?}` |
| 6 | `GET /servidores` | cartões | cada item: `{id,nome,icone,bot_presente,bots:[{id,nome,convite_url}]}` |
| 7 | Token XSRF para o JS | cabeçalho `X-XSRFToken` | a página injeta `<meta name="xsrf-token">`; sem endpoint extra |
| 8 | Códigos de erro estáveis | mensagens por campo | `erro.codigo` + `erro.campo?` (nome do campo) para destacar o input |
| 9 | Limites em `recursos` (`links.max=25`, `ouvir_junto.max=5`, `prefixo.max=5`, `favoritos.max`, `nome.max`, `url.max`) | contadores e validação no cliente | objeto `limites` (o servidor continua validando) |
| 10 | `GET /servidores/{gid}/ouvir-junto` incluir nome do canal | lista legível | `[{canal_id, canal_nome, convite_url}]` |

Respostas e códigos que a UI trata: `200`, `202`, `400/422` (erro por campo), `401` (sessão), `403` (sem permissão),
`404`, `409` (bot ausente), `412` (ETag), `429` (`Retry-After`), `5xx` (genérico). Páginas HTML de erro seguem a §3.4.


---

## 4. Identidade visual (paleta Nebulosa) e idioma

### 4.1 Tokens de cor

| Papel | Hex | Uso no painel |
|---|---|---|
| Espaço (fundo) | `#0B0A1F` | Fundo da página, barra lateral |
| Superfície | `#15133A` (derivada) | Cartões, formulários |
| Superfície elevada | `#1E1B4B` (derivada) | Menus, `dialog`, hover de cartão |
| Borda | `#2E2A6B` (derivada) | Contornos de 1 px |
| **Violeta (principal)** | `#8B5CF6` | Botão primário, foco, item ativo, links |
| Azul | `#3B82F6` | Informação, links secundários, início do degradê |
| Magenta | `#C026D3` | Destaques, meio do degradê |
| Vermelho | `#E11D48` | Erro, ações destrutivas, fim do degradê |
| Texto | `#F5F3FF` | Corpo |
| Texto secundário | `#C4B5FD` | Ajudas, rótulos suaves |

As cores "derivadas" são propostas minhas (variações escuras do violeta sobre o fundo) e dependem de aprovação.
Degradê de marca (cabeçalho, botão de destaque):
`linear-gradient(90deg, #3B82F6, #8B5CF6, #C026D3, #E11D48)`.

Acessibilidade de cor (**a medir na implementação**): texto `#F5F3FF` sobre `#0B0A1F` deve passar com folga;
o botão primário `#8B5CF6` com texto branco pode ficar abaixo de 4,5:1 em corpo pequeno → usar texto branco em
negrito ≥ 16 px ou escurecer o botão (ex.: `#7C3AED`), decidindo após medir. Erro nunca só por cor (ícone + texto).
Foco visível: anel de 2 px `#C4B5FD`. Respeitar `prefers-reduced-motion` e `prefers-contrast`.

### 4.2 Tipografia, forma e movimento
- Fonte do sistema (`system-ui`), sem fontes externas (privacidade + CSP). Base 16 px, entrelinha 1,5.
- Cantos de 12 px; sombras suaves com brilho violeta (`0 0 24px #8B5CF633`); poucos efeitos.
- Fundo: nebulosa do banner como imagem fixa **decorativa** (`aria-hidden`), escurecida para manter contraste, com
  versão sem imagem para economia de dados.

### 4.3 Arquivos de marca
`assets/brand/logo.svg` (emblema; cabeçalho e login), `assets/brand/avatar.png` (avatar do bot; convite) e
`assets/brand/banner.png` (fundo do login/cabeçalho). **Atenção:** esses arquivos pertencem à Fase 1.1 (branch
`feat/identidade-visual-suporte`) e **ainda não existem nesta branch** (partiu da `main` b71c1168); o painel só deve
referenciá-los após o merge da Fase 1.1. Favicon: gerar a partir do `logo.svg`. URLs públicas vêm de
`utils/branding.py` (`asset_url`, `BOT_NAME`, `SUPPORT_SERVER_URL`); a cor principal do painel deve coincidir com
`EMBED_COLOR_HEX` (`8B5CF6`) para coerência com os embeds.

### 4.4 Idioma e microcopy
Interface 100 % **pt-BR com acentuação correta**; termos iguais aos do Discord e do bot ("canal", "cargo",
"servidor", "Gerenciar Servidor", "DJ", "skin"). Tom direto; erros dizem o que aconteceu e o que fazer. Strings
centralizadas (arquivo/macro de template) para facilitar i18n futuro, sem implementar outros idiomas agora.

### 4.5 Metas de acessibilidade (WCAG 2.2 AA)
Navegação 100 % por teclado; ordem de foco lógica; *skip link* "Ir para o conteúdo"; landmarks (`header`, `nav`,
`main`); rótulos em todos os campos; `aria-live="polite"` para avisos de salvamento; `<dialog>` nativo para
confirmações; alvos de toque ≥ 44 px. Verificação na etapa de QA com ferramentas de desenvolvimento (axe/Lighthouse),
que não viram dependência do projeto.

### 4.6 Kit de CSS e tokens (depende da decisão da §2.5)
Os tokens da §4.1 viram variáveis CSS em `nebulosa.css`: com Pico, sobrescrevem `--pico-*` (ex.: `--pico-primary`) em
`data-theme="dark"`; com Simple.css, sobrescrevem `--accent`, `--bg`, `--text` etc. O mapeamento é o mesmo; muda só
quanto CSS próprio é necessário.

### 4.7 Ponto de integração com o DeepSearch
Quando `pesquisa-externa.md` sair, revisar §2.4 e §4: se houver kit/template com licença compatível, bom peso e
acessibilidade comprovada que acelere as telas, adotar **o CSS/estilo** (não SPA) e remapear os tokens Nebulosa.

---

## 5. Riscos, dúvidas e próximos passos

**Dúvidas para o dono**
1. **Escopo da v1:** o Backend inventariou servidor, usuário e dono. Wireframes já cobrem as três áreas (§3.3.1); o dono
   escolhe se a v1 entrega as três ou só servidor (+ conta). Recomendação: servidor + conta; dono só leitura.
2. **Skins personalizadas (G-14):** ficam fora da v1 (formato de armazenamento legado inseguro, rastreado em privado, S-04); a tela mostra o cartão "Em breve". De acordo?
   **Token de RPC (U-05):** gerar/mostrar uma vez no painel ou manter só no Discord (decisão D-4 do Backend)?
3. **Domínio/URL pública** com HTTPS para o `redirect_uri` do OAuth (Replit, domínio próprio, outro?).
4. **Multi-bot:** um painel/uma aplicação OAuth para todos os bots do pool? Recomendação: sim.
5. **Visual:** aprovar a direção Nebulosa (superfícies derivadas, degradê) e a preferência por CSS leve sem build.
6. **Kit de CSS:** Pico CSS arquivado (vendorizado, congelado) ou Simple.css (vivo, mais CSS próprio)? Ver §2.5.

**Riscos de frontend**
- CSS/JS de terceiros: fixar versão e hash; atualizar só via PR revisado (supply chain).
- JS próprio: manter o módulo pequeno, sem `eval`/`innerHTML` com dados do servidor (usar `textContent`); revisão AppSec.
- Se htmx entrar depois da v1: ficar na 2.x, `allowEval=false`, revisar `hx-on` e `selfRequestsOnly`.
- Contraste do violeta principal com texto branco (§4.1): medir antes de fechar o tema.
- Dependência dos arquivos de marca da Fase 1.1 (ainda não mergeados).
- Inventário do Backend ainda não conferido contra as telas (§3.3.1).

**Próxima etapa sugerida (após aprovação do plano):** protótipo estático de 4 telas (login, servidores, uma
categoria, erro) em HTML/CSS com tema Nebulosa para validação visual do dono, antes de qualquer handler.

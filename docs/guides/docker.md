# Implantação com Docker

Guia prático para execução do **EmpireMuse** em contêineres Docker utilizando a imagem oficial multi-stage com o bot e o servidor de áudio Lavalink integrados.

---

## 1. O que a Imagem Traz

A imagem Docker do EmpireMuse foi projetada para oferecer uma implantação simples, segura e auto-contida em uma única instância:

- **Bot e Lavalink no mesmo contêiner**: O bot em Python 3.13 e o servidor de áudio Lavalink 4.2.2 rodam coordenados no mesmo contêiner, eliminando a complexidade de orquestrar múltiplos serviços.
- **Runtime Java 21**: Inclui o JRE oficial do **Eclipse Temurin 21**, atendendo aos requisitos do Lavalink e seus plugins.
- **Isolamento de rede local**: O Lavalink é vinculado estritamente ao endereço de loopback (`127.0.0.1` via `SERVER_ADDRESS`), comunicando-se exclusivamente com o bot via socket interno e nunca expondo portas de áudio para fora do contêiner.
- **Segurança e privilégios mínimos**:
  - Usuário não-root dedicado com UID/GID fixo `10001:10001` (`empiremuse`) e shell restrito (`/usr/sbin/nologin`).
  - Código-fonte da aplicação em `/app` de propriedade de `root` e estritamente somente leitura para o usuário da aplicação.
  - Binários e configurações pré-instaladas do Lavalink em `/opt/lavalink` em modo somente leitura.
- **Gerenciamento com `tini`**: O contêiner utiliza o inicializador `tini` como PID 1, garantindo o correto repasse de sinais do sistema operacional (`SIGTERM`, `SIGINT`) e a eliminação de processos zumbis.
- **Healthcheck nativo**: Monitoramento da integridade do serviço HTTP/status na porta configurada.

---

## 2. Como Construir e Executar

### 2.1 Construção Local da Imagem

Para construir a imagem localmente a partir da raiz do repositório:

```bash
docker build -t empiremuse:local .
```

> [!NOTE]
> A publicação da imagem oficial no registro `or4cu1o/empiremuse` estará disponível **em breve**, acompanhando a release oficial do projeto. Não utilize tags não homologadas.

### 2.2 Execução com `docker run`

Antes de iniciar, prepare o arquivo de variáveis de ambiente `.env` na máquina hospedeira com as configurações do seu bot (utilize `.example.env` como referência):

```bash
docker run -d \
  --name empiremuse \
  --restart unless-stopped \
  --env-file .env \
  -v empiremuse-data:/data \
  -p 8080:8080 \
  empiremuse:local
```

**Parâmetros fundamentais:**
- `--restart unless-stopped`: Política de reinício recomendada. Caso o contêiner pare inesperadamente ou após uma falha de subprocesso, o Docker reinicia o bot automaticamente.
- `--env-file .env`: Injeta suas credenciais e configurações (tokens do Discord, chaves de API, etc.).
- `-v empiremuse-data:/data`: Monta um volume persistente do Docker no caminho `/data`.
- `-p 8080:8080`: Mapeia a porta HTTP do contêiner (definida por `PORT=8080`) para acesso à página de status, WebSocket de Rich Presence e ao Painel Web.

---

## 3. Docker Compose

O repositório inclui um arquivo [`docker-compose.yml`](../../docker-compose.yml) pronto para uso, oferecendo orquestração declarativa, isolamento seguro e suporte opcional a banco de dados MongoDB em contêiner dedicado.

> [!WARNING]
> A orquestração via Docker Compose foi validada estruturalmente com `docker compose config` e testes estáticos, mas **ainda não foi testada com o bot conectado (teste real pendente)** (validação com instância real agendada para a etapa D-16).

### 3.1 Executando Apenas o Bot

Para executar o bot com o servidor Lavalink local integrado e persistência em banco local (TinyMongo):

1. Certifique-se de que o arquivo `.env` na raiz do projeto está preenchido com suas credenciais;
2. Execute:
   ```bash
   docker compose up -d --build
   ```

### 3.2 Executando com MongoDB Dedicado (Perfil `mongo`)

Para utilizar um contêiner oficial do MongoDB (`mongo:8.0.34`, fixado por digest imutável) como camada de persistência:

1. Crie o arquivo `.env.mongo` na raiz do projeto (**nunca versione este arquivo**; ele já está incluído no `.gitignore`):
   ```env
   MONGO_INITDB_ROOT_USERNAME=empiremuse_admin
   MONGO_INITDB_ROOT_PASSWORD=sua_senha_segura_aqui
   ```
2. No seu arquivo `.env`, configure a variável `MONGO` apontando para o serviço interno `mongo`:
   ```env
   MONGO='mongodb://empiremuse_admin:sua_senha_segura_aqui@mongo:27017/?authSource=admin'
   ```
   > [!NOTE]
   > O parâmetro `?authSource=admin` é necessário na URL de conexão porque o usuário root inicial do Mongo é criado no banco de autenticação `admin`.
3. Inicie a stack ativando o perfil `mongo`:
   ```bash
   docker compose --profile mongo up -d --build
   ```

### 3.3 Variáveis de Configuração do Compose

Você pode customizar o comportamento do Compose através do seu arquivo `.env` ou de variáveis de ambiente no host:

| Variável | Valor Padrão | Descrição |
| :--- | :--- | :--- |
| `EMPIREMUSE_IMAGE` | `or4cu1o/empiremuse:local` | Nome da imagem Docker a ser utilizada. |
| `EMPIREMUSE_MEM_LIMIT` | `768m` | Limite de memória do contêiner do bot (cobre processo Python e heap do Java). |
| `EMPIREMUSE_PORT` | `8080` | Mapeamento da porta HTTP exposta no host para o bot. |

> [!TIP]
> Se o bot estiver atrás de um proxy reverso (como Nginx, Caddy ou Traefik) rodando no mesmo host, publique a porta apenas na interface de loopback definindo `EMPIREMUSE_PORT=127.0.0.1:8080`. Isso restringe o acesso externo e garante que apenas o proxy converse com o bot.

### 3.4 Garantias de Segurança do Compose

O arquivo `docker-compose.yml` aplica uma política rigorosa de segurança defensiva:

- **Exposição Mínima de Portas**: Apenas a porta HTTP 8080 do bot é publicada no host. O Lavalink (vinculado estritamente em `127.0.0.1` dentro do contêiner) e o serviço `mongo` (porta 27017 acessível exclusivamente na rede interna do Compose) **nunca** têm portas publicadas para fora.
- **Sistema de Arquivos Somente Leitura**: O contêiner do bot roda com `read_only: true`. Diretórios temporários de escrita utilizam `/tmp` montado em memória (`tmpfs`).
- **Isolamento de Privilégios**: `security_opt: [no-new-privileges:true]` previne escalada de privilégios e `cap_drop: [ALL]` descarta todas as capacidades Linux (Linux Capabilities).
- **Volumes Nomeados**: Os dados são isolados nos volumes `empiremuse-data` (para `/data` do bot) e `empiremuse-mongo` (para `/data/db` do MongoDB).

---

## 4. Variáveis de Ambiente e Recursos

### 4.1 Variáveis Padrão da Imagem

A imagem Docker já traz pré-configuradas as seguintes variáveis de ambiente operacionais:

| Variável | Valor Padrão | Descrição |
| :--- | :--- | :--- |
| `EMPIREMUSE_HOME` | `/data` | Diretório raiz de execução e persistência de dados. |
| `RUN_LOCAL_LAVALINK` | `true` | Ativa a inicialização automática do Lavalink no contêiner. |
| `LAVALINK_OFFLINE` | `true` | Modo offline: impede downloads de binários e valida os arquivos existentes por SHA-256. |
| `LAVALINK_HOME` | `/opt/lavalink` | Diretório dos binários validados do Lavalink (`Lavalink.jar`, `application.yml`, `plugins/`). |
| `LAVALINK_JAVA_PATH` | `/opt/java/openjdk/bin/java` | Caminho do executável do runtime Java 21 JRE pré-instalado. |
| `PORT` | `8080` | Porta do servidor HTTP Tornado (status, RPC e painel). |

### 4.2 Dimensionamento de Memória (RAM) e Recursos

O uso de memória do contêiner é a soma de dois componentes principais:
1. **Processo do Bot (Python)**: Consumo estimado entre ~200 MB e ~300 MB dependendo da quantidade de servidores conectados, filas ativas e uso do painel web.
2. **Processo do Lavalink (Java)**: A JVM tem seu heap de memória configurado pelas variáveis:
   - `LAVALINK_INITIAL_RAM` (heap inicial `-Xms`, padrão `30` MB): define a memória inicial reservada pela JVM (repassada quando `0 < LAVALINK_INITIAL_RAM < LAVALINK_RAM_LIMIT`).
   - `LAVALINK_RAM_LIMIT` (heap máximo `-Xmx`, padrão `120` MB): define o teto máximo de memória que o Lavalink pode alocar (repassada quando `LAVALINK_RAM_LIMIT > 10`).
   - Além da memória, a alocação de núcleos de CPU da JVM é definida por `LAVALINK_CPU_CORES` (padrão `1`, repassada via `-XX:ActiveProcessorCount=`).

Ao configurar um limite de memória para o contêiner (como a flag `--memory` do `docker run` ou `mem_limit` / `EMPIREMUSE_MEM_LIMIT` no Docker Compose):
- O limite padrão recomendado do contêiner é de **768 MB** (`768m`), suficiente para cobrir com folga o processo Python, a JVM e as bibliotecas nativas de áudio.
- Para instâncias com grande volume de servidores ou dezenas de conexões de voz simultâneas, recomenda-se alocar **1 GB** (`1024m`) ou mais para o contêiner e expandir `LAVALINK_RAM_LIMIT` (por exemplo, `256` a `512` MB) conforme a demanda de faixas em fila.

> [!NOTE]
> Valores oficiais medidos em testes de carga e homologação real (etapa D-16) serão incluídos em revisões posteriores desta documentação.

---

## 5. O que Fica Persistido em `/data`

O contêiner executa a partir do diretório `/data` (`WORKDIR /data`), de modo que todos os dados que precisam sobreviver a reinicializações e atualizações de imagem são armazenados no volume persistente:

- **Banco de Dados Local**: Diretório `/data/local_database/` (quando utilizado o banco TinyMongo em vez do MongoDB remoto).
- **Configurações Locais**: Arquivo `config.json` ou sobrescritas locais, caso aplicáveis.
- **Caches de Sessão**: Caches do YouTube, Last.fm e sessões ativas do painel web.
- **Logs do Servidor de Áudio**: O Lavalink grava seus arquivos de log em `/data/.logs/lavalink/` (configurado via `-Dlogging.file.path`).
- **Overrides de Inicialização**: O arquivo gerado em `/data/.lavalink/plugins-override.yml`, que permite ao Lavalink iniciar sem consultas desnecessárias a repositórios externos.

---

## 6. Comportamento de Reinício e Resiliência

O EmpireMuse possui um mecanismo integrado de supervisão do processo de áudio:

1. **Vigia do Processo Java (`watch_lavalink_process`)**: Durante a execução, uma thread dedicada monitora o processo do Lavalink em tempo real.
2. **Tratamento de Quedas Inesperadas**: Se o processo do Java for finalizado de forma anômala (queda por falta de memória, encerramento externo, etc.), o bot detecta o término e aciona um encerramento gracioso do pool (`shutdown(1)`), saindo com código de status de erro `1`.
3. **Recuperação pelo Docker**: Com a política de reinício configurada (`--restart unless-stopped`), o daemon do Docker detecta a saída do processo e reinicia o contêiner de forma limpa, restabelecendo o bot e o Lavalink.

---

## 7. Como Atualizar

No modelo de contêineres, o ciclo de vida da aplicação é declarativo e imutável:

1. O antigo comando de atualização em tempo de execução via Git (`@bot update`) foi **desativado** por segurança arquitetural.
2. Para atualizar o bot:
   - Baixe ou construa a nova imagem (`docker pull` ou `docker build`);
   - Pare e remova o contêiner em execução (`docker stop empiremuse && docker rm empiremuse` ou `docker compose down`);
   - Inicie o novo contêiner mantendo o mesmo volume persistente (`-v empiremuse-data:/data` ou via compose) e o mesmo arquivo `.env`.

Seus dados, favoritos, configurações de servidores e histórico permanecerão intactos no volume `/data`.

---

## 8. Licença e Créditos

A imagem oficial contém cópias completas dos arquivos [`LICENSE`](file:///app/LICENSE) e [`CREDITS.md`](file:///app/CREDITS.md) sob o diretório `/app`. O **EmpireMuse** é disponibilizado sob a licença **GPL-2.0**, sendo uma obra derivada do projeto original [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot) desenvolvido por **zRitsu**.

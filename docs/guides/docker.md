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

## 3. Variáveis de Ambiente e Recursos

### 3.1 Variáveis Padrão da Imagem

A imagem Docker já traz pré-configuradas as seguintes variáveis de ambiente operacionais:

| Variável | Valor Padrão | Descrição |
| :--- | :--- | :--- |
| `EMPIREMUSE_HOME` | `/data` | Diretório raiz de execução e persistência de dados. |
| `RUN_LOCAL_LAVALINK` | `true` | Ativa a inicialização automática do Lavalink no contêiner. |
| `LAVALINK_OFFLINE` | `true` | Modo offline: impede downloads de binários e valida os arquivos existentes por SHA-256. |
| `LAVALINK_HOME` | `/opt/lavalink` | Diretório dos binários validados do Lavalink (`Lavalink.jar`, `application.yml`, `plugins/`). |
| `LAVALINK_JAVA_PATH` | `/opt/java/openjdk/bin/java` | Caminho do executável do runtime Java 21 JRE pré-instalado. |
| `PORT` | `8080` | Porta do servidor HTTP Tornado (status, RPC e painel). |

### 3.2 Dimensionamento de Memória (RAM)

O uso de memória do contêiner é a soma de dois componentes principais:
1. **Processo do Bot (Python)**: Consumo estimado entre ~200 MB e ~300 MB dependendo do número de servidores e filas ativas.
2. **Processo do Lavalink (Java)**: Controlado pelas variáveis `LAVALINK_INITIAL_RAM` (heap inicial `-Xms`, padrão `30` MB) e `LAVALINK_RAM_LIMIT` (heap máximo `-Xmx`, padrão `120` MB).

Ao configurar um limite de memória para o contêiner (como a flag `--memory` do `docker run` ou `mem_limit` no Docker Compose), certifique-se de que o limite total atribuído cubra com folga o processo do bot somado ao heap configurado para o Java.

> [!NOTE]
> Valores oficiais medidos em testes de carga e homologação real (etapa D-16) serão incluídos em revisões posteriores desta documentação.

---

## 4. O que Fica Persistido em `/data`

O contêiner executa a partir do diretório `/data` (`WORKDIR /data`), de modo que todos os dados que precisam sobreviver a reinicializações e atualizações de imagem são armazenados no volume persistente:

- **Banco de Dados Local**: Diretório `/data/local_database/` (quando utilizado o banco TinyMongo em vez do MongoDB remoto).
- **Configurações Locais**: Arquivo `config.json` ou sobrescritas locais, caso aplicáveis.
- **Caches de Sessão**: Caches do YouTube, Last.fm e sessões ativas do painel web.
- **Logs do Servidor de Áudio**: O Lavalink grava seus arquivos de log em `/data/.logs/lavalink/` (configurado via `-Dlogging.file.path`).
- **Overrides de Inicialização**: O arquivo gerado em `/data/.lavalink/plugins-override.yml`, que permite ao Lavalink iniciar sem consultas desnecessárias a repositórios externos.

---

## 5. Comportamento de Reinício e Resiliência

O EmpireMuse possui um mecanismo integrado de supervisão do processo de áudio:

1. **Vigia do Processo Java (`watch_lavalink_process`)**: Durante a execução, uma thread dedicada monitora o processo do Lavalink em tempo real.
2. **Tratamento de Quedas Inesperadas**: Se o processo do Java for finalizado de forma anômala (queda por falta de memória, encerramento externo, etc.), o bot detecta o término e aciona um encerramento gracioso do pool (`shutdown(1)`), saindo com código de status de erro `1`.
3. **Recuperação pelo Docker**: Com a política de reinício configurada (`--restart unless-stopped`), o daemon do Docker detecta a saída do processo e reinicia o contêiner de forma limpa, restabelecendo o bot e o Lavalink.

---

## 6. Como Atualizar

No modelo de contêineres, o ciclo de vida da aplicação é declarativo e imutável:

1. O antigo comando de atualização em tempo de execução via Git (`@bot update`) foi **desativado** por segurança arquitetural.
2. Para atualizar o bot:
   - Baixe ou construa a nova imagem (`docker pull` ou `docker build`);
   - Pare e remova o contêiner em execução (`docker stop empiremuse && docker rm empiremuse`);
   - Inicie o novo contêiner mantendo o mesmo volume persistente (`-v empiremuse-data:/data`) e o mesmo arquivo `.env`.

Seus dados, favoritos, configurações de servidores e histórico permanecerão intactos no volume `/data`.

---

## 7. Licença e Créditos

A imagem oficial contém cópias completas dos arquivos [`LICENSE`](file:///app/LICENSE) e [`CREDITS.md`](file:///app/CREDITS.md) sob o diretório `/app`. O **EmpireMuse** é disponibilizado sob a licença **GPL-2.0**, sendo uma obra derivada do projeto original [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot) desenvolvido por **zRitsu**.

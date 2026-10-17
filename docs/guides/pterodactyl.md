# Guia de Implantação no Pterodactyl

Guia prático para instalação e execução do **EmpireMuse** no painel de controle **Pterodactyl** (e derivados como Pelican) utilizando o egg oficial da comunidade.

---

> [!WARNING]
> **Egg ainda não verificado num painel real (teste em homologação pendente)**.
> Este egg foi construído com validações estáticas e testes de conformidade, mas ainda não passou por testes ponta a ponta em uma instância ativa do Pterodactyl Wings.
> Além disso, a imagem oficial `or4cu1o/empiremuse` será disponibilizada publicamente no Docker Hub acompanhando a **primeira release oficial** do projeto (`v0.1.0-rc.1` / `v0.1.0`).

---

## 1. Importando o Egg no Painel

O arquivo de definição do egg encontra-se em [`deploy/pterodactyl/egg-empiremuse.json`](../../deploy/pterodactyl/egg-empiremuse.json).

### 1.1 Procedimento de Importação (Administrador)
1. Acesse a área administrativa do Pterodactyl (**Admin Control Panel**);
2. No menu lateral, navegue até **Nests**;
3. Selecione o Nest desejado (ou crie um novo Nest, ex.: "Discord Bots");
4. Clique no botão **Import Egg** no canto superior direito;
5. Selecione o arquivo `egg-empiremuse.json` do seu computador ou informe o arquivo do repositório;
6. Associe o egg ao Nest escolhido e conclua a importação.

### 1.2 Criando o Servidor
1. Na aba **Servers** do painel administrativo, clique em **Create New**;
2. Configure o nome do servidor, o dono da instância e o Node de execução;
3. Na seção de alocação de rede (**Allocation Management**), defina a **porta principal** (Default Allocation). O bot utilizará essa porta automaticamente;
4. Na seção **Nest Configuration**, selecione o Nest e o egg **EmpireMuse**;
5. Defina os limites de recursos (consulte a seção de dimensionamento de memória abaixo);
6. Preencha a variável obrigatória **TOKEN** com o token do seu bot no Discord e conclua a criação.

---

## 2. Imagens Docker Oferecidas

O egg disponibiliza duas opções de imagem Docker:

| Tag da Imagem | Descrição | Recomendação de Uso |
| :--- | :--- | :--- |
| `or4cu1o/empiremuse:0.1` | Fixada na série menor `0.1`. Recebe automaticamente atualizações e correções de bugs da linha 0.1 sem introduzir mudanças incompatíveis. | **Recomendada para produção.** |
| `or4cu1o/empiremuse:latest` | Aponta sempre para a versão estável mais recente publicada. | Útil para quem deseja acompanhar todas as atualizações automaticamente. |

> [!TIP]
> O daemon do Pterodactyl (**Wings**) baixa novamente a imagem selecionada ao reiniciar o servidor caso haja atualizações na tag correspondente no registro.

---

## 3. Dimensionamento de Recursos e Memória

O consumo de memória varia significativamente conforme o modo de operação do servidor de áudio Lavalink:

- **Com Lavalink Local Integrado (`RUN_LOCAL_LAVALINK=true`)**:
  - **Mínimo absoluto**: `768 MB`.
  - **Recomendado**: `1 GB` (ou `1024 MB`).
  - *Contexto*: Esse espaço acomoda com segurança o processo do bot em Python 3.13, o heap da JVM do Java 21 (`LAVALINK_INITIAL_RAM` padrão 30 MB até `LAVALINK_RAM_LIMIT` padrão 120 MB) e as bibliotecas nativas de áudio.
  - *(Valores exatos medidos em carga real serão incorporados em revisões posteriores desta documentação).*
- **Sem Lavalink Local (`RUN_LOCAL_LAVALINK=false`)**:
  - Consumo reduzido (recomendado `384 MB` a `512 MB`), pois o bot utilizará nós Lavalink remotos e externos, não executando a JVM do Java no contêiner.

---

## 4. Variáveis de Configuração e Segurança

O egg expõe diversas variáveis configuráveis na aba **Startup** do servidor. As principais são:

### 4.1 Variáveis Principais
- **`TOKEN`** (*Obrigatório*): Token de autenticação do bot gerado no [Discord Developer Portal](https://discord.com/developers/applications).
- **`MONGO`** (*Opcional*): URI de conexão com cluster MongoDB externo (ex.: MongoDB Atlas ou contêiner dedicado). Se deixado em branco, o bot opera perfeitamente com persistência em disco local via TinyMongo.
- **`RUN_LOCAL_LAVALINK`**: `true` para iniciar o servidor de áudio integrado no próprio contêiner, ou `false` caso você use nós Lavalink remotos.
- **`LAVALINK_RAM_LIMIT`**: Limite máximo de memória RAM alocado à JVM do Lavalink (padrão: `120` MB).

### 4.2 Segurança de Segredos e Permissões de Subusuários (`startup.read`)
> [!CAUTION]
> Todas as variáveis de ambiente com dados sensíveis (`TOKEN`, chaves de API do Spotify, segredos do Last.fm e URI do MongoDB) possuem valor padrão vazio por segurança.
> No modelo de permissões de subusuários do Pterodactyl, a permissão **`startup.read`** (visualizar parâmetros de inicialização na aba Startup) permite a **leitura integral de todas as variáveis de ambiente em texto simples**, expondo diretamente o `TOKEN` do bot no Discord, a string de conexão com credenciais do `MONGO` e quaisquer outras chaves configuradas.
> **NUNCA conceda a permissão `startup.read` (ou acesso à aba Startup) a subusuários que não sejam operadores de total e absoluta confiança.**

---

## 5. Porta e Persistência de Dados

### 5.1 Alocação de Porta Automática (`SERVER_PORT`)
- No Pterodactyl, o Wings repassa a porta alocada ao servidor através da variável de ambiente interna `SERVER_PORT`.
- O EmpireMuse detecta e resolve a porta automaticamente: se a variável `PORT` não estiver definida, o bot adota `SERVER_PORT` de forma transparente.
- **NÃO crie uma variável de ambiente chamada `PORT`** nem sobrescreva manualmente a porta no egg, a menos que haja necessidade específica. A alocação principal do servidor no painel é suficiente.

### 5.2 Diretório de Dados (`/home/container`)
- O Pterodactyl monta o armazenamento persistente do servidor no caminho `/home/container`.
- A variável `EMPIREMUSE_HOME` vem configurada de forma fixa e não-editável como `/home/container`.
- Ao inicializar, o bot entra automaticamente em `EMPIREMUSE_HOME`, garantindo que o banco de dados local (`local_database/`), logs (`.logs/`), preferências e arquivos temporários fiquem confinados ao diretório montado do servidor, sobrevivendo a reinicializações e reconstruções de imagem.

---

## 6. Operação pelo Console e Encerramento

- **Sem Comandos no Console**: O EmpireMuse opera de maneira autônoma interagindo via eventos do Discord e requisições HTTP; ele **não processa comandos de texto digitados no console interativo** do painel.
- **Encerramento Controlado (Botão Stop)**: O egg está configurado com o comando de parada `^C` (sinal `SIGINT`). Para desligar ou reiniciar o bot, utilize os botões **Stop** ou **Restart** da interface do painel. Isso dispara o encerramento ordenado (`shutdown()`), desconectando os nós de áudio e as instâncias do bot de forma graciosa.

---

## 7. Licença e Créditos

O **EmpireMuse** é distribuído sob a licença **GPL-2.0** e é uma obra derivada do projeto original [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot), criado por **zRitsu**. Consulte os arquivos [`LICENSE`](../../LICENSE) e [`CREDITS.md`](../../CREDITS.md) na raiz do repositório para os avisos de direitos autorais e créditos completos.

# Guia de Implantação na Discloud

Guia técnico para hospedagem e execução do **EmpireMuse** na plataforma **Discloud** utilizando os arquivos de configuração padronizados do projeto.

---

> [!WARNING]
> **Configuração baseada na documentação oficial, ainda não verificada na plataforma (teste em homologação pendente)**.
> Os arquivos `discloud.config` e `.discloudignore` foram construídos conforme as especificações e regras vigentes da Discloud, mas a homologação em uma instância real ativa ocorrerá na etapa de testes do projeto.
> 
> **Requisito de Plano Pago**: O plano gratuito da Discloud (100 MB de RAM) **NÃO é suportado**. O EmpireMuse requer o **plano pago com no mínimo 1 GB (1024 MB) de RAM e 1 vCPU**, dimensão definida no parâmetro `RAM=1024` do `discloud.config`.

---

## 1. Visão Geral e Arquivo `discloud.config`

O arquivo [`discloud.config`](../../discloud.config) na raiz do repositório define os parâmetros da aplicação para a Discloud:

```ini
NAME=EmpireMuse
AVATAR=https://raw.githubusercontent.com/DiscordEmpireHub/EmpireMuse/main/assets/brand/avatar.png
TYPE=bot
MAIN=main.py
RAM=1024
AUTORESTART=true
VERSION=latest
```

### Explicação dos Parâmetros:
- **`TYPE=bot`**: Declara a aplicação como um bot do Discord (sem roteamento de porta HTTP pública na Discloud).
- **`MAIN=main.py`**: Ponto de entrada que inicializa o loop do `BotPool` via `empiremuse.__main__.main()`.
- **`RAM=1024`**: Aloca 1024 MB (1 GB) de memória RAM, necessária para suportar o processo Python somado ao processo Java do servidor de áudio Lavalink.
- **`AUTORESTART=true`**: Ativa o reinício automático pelo supervisor da Discloud caso o processo do bot encerre com código de erro (por exemplo, se o processo do Java do Lavalink cair).
- **`VERSION=latest`**: Utiliza a versão mais recente e estável do ambiente Python disponibilizada pela Discloud.
  > [!NOTE]
  > O EmpireMuse é desenvolvido para **Python 3.13** e foi validado em sua suíte automatizada de testes com **Python 3.11, 3.12 e 3.13**, garantindo ampla compatibilidade com as imagens de execução da Discloud.

---

## 2. Formas de Envio (Deploy)

A Discloud oferece duas modalidades para publicação da aplicação. Priorize sempre a integração com o GitHub.

### 2.1 Método Preferido: Integração com o GitHub
A integração direta entre a Discloud e o seu repositório GitHub é a forma **mais segura e recomendada**:
1. Conecte seu repositório GitHub ao painel da Discloud;
2. Configure as variáveis de ambiente necessárias diretamente na interface web da Discloud (aba de variáveis do aplicativo);
3. **Vantagem de segurança**: As credenciais nunca trafegam em arquivos em disco nem correm risco de exposição em commits acidentais.

### 2.2 Método Alternativo: Upload via Arquivo ZIP ou Discloud CLI
Caso utilize o envio manual por arquivo `.zip` ou através da ferramenta de linha de comando (`discloud upload`):
1. Crie o arquivo `.env` na raiz do projeto com suas credenciais;
2. **Boas Práticas Mandatórias de Segurança**:
   - **NUNCA versione o `.env`**: Certifique-se de que o `.env` está presente no `.gitignore` e que `git status` não indica o arquivo como rastreado;
   - **Permissões locais restritas**: No Linux/macOS, restrinja a leitura do arquivo:
     ```bash
     chmod 600 .env
     ```
   - **Exclua o arquivo `.zip` local imediatamente**: Logo após o envio bem-sucedido para a Discloud, delete o arquivo compactado da sua máquina para evitar vazamento de credenciais locais.
3. O arquivo [`.discloudignore`](../../.discloudignore) já vem configurado para **bloquear** compulsoriamente o envio de:
   - Arquivos auxiliares de ambiente (`.env.*`, como `.env.mongo` e backups);
   - Segredos e chaves locais (`config.json`, `*.key`, `*.pem`, `.panel-cookie-secret`, cookies do YouTube);
   - Bancos de dados locais (`local_database/`, `.local_dbs/`) e caches temporários (`.logs/`, `__pycache__/`, `.ytdl_cache/`, etc.).

---

## 3. Configurações e Variáveis de Ambiente no `.env`

Como a Discloud configura instâncias do tipo `TYPE=bot` sem portas HTTP públicas roteadas para a Web:

### 3.1 Desativação de Serviços HTTP
Para economizar memória RAM e ciclos de CPU, desative explicitamente o servidor web e o painel no `.env` da Discloud:
```env
RUN_RPC_SERVER=false
PANEL_ENABLED=false
```

### 3.2 Variáveis Essenciais
```env
TOKEN=seu_token_do_discord_aqui
MONGO=mongodb+srv://usuario:senha@cluster.mongodb.net/?retryWrites=true&w=majority
```

---

## 4. Servidor de Áudio Lavalink na Discloud

O EmpireMuse oferece dois modos de operação para a reprodução de áudio:

### 4.1 Modo Lavalink Local Embutido (`RUN_LOCAL_LAVALINK=true`)
- Fora do contêiner Docker oficial, o bot opera em modo de download dinâmico com integridade verificada (`LAVALINK_OFFLINE=false`, o padrão);
- Na primeira partida na Discloud, o bot baixa automaticamente o runtime portátil JDK da BellSoft e o binário oficial `Lavalink.jar`, conferindo os hashes **SHA-256 fixados em código** antes da execução;
- Certifique-se de ajustar a variável `LAVALINK_RAM_LIMIT` (padrão de `120` MB) para que o heap da JVM somado à memória do processo Python permaneçam confortavelmente dentro do limite de 1 GB do plano contratado. *(Valores exatos medidos em carga serão homologados no teste prático).*

### 4.2 Modo Lavalink Remoto (Mais Leve)
- Para uma inicialização instantânea e menor consumo de recursos, defina `RUN_LOCAL_LAVALINK=false` e configure nós Lavalink remotos e externos no arquivo `lavalink.ini` na raiz do projeto (arquivo que é incluído no pacote enviado à Discloud).

---

## 5. Persistência de Dados e Banco de Dados

> [!IMPORTANT]
> Na infraestrutura da Discloud, o sistema de arquivos local pode ser recriado ou sobrescrito a cada novo deploy, atualização de código ou reinício da aplicação.
> 
> - **Banco Local (TinyMongo)**: O armazenamento em `local_database/` deve ser considerado puramente efêmero e transitório.
> - **MongoDB Externo Obrigatório para Produção**: Configure a variável `MONGO` apontando para um cluster externo gerenciado (por exemplo, uma instância gratuita ou dedicada no MongoDB Atlas). Com isso, favoritos, configurações de servidores, prefixos e histórico permanecem totalmente seguros e intactos entre deploys.

---

## 6. Resiliência e Reinício Automático

A diretiva `AUTORESTART=true` no `discloud.config` assegura a continuidade do serviço:
- O EmpireMuse possui uma thread sentinela que monitora o processo do Java (`watch_lavalink_process`);
- Se o servidor de áudio cair de forma anômala, o bot encerra o processo ordenadamente com código de saída de erro (`shutdown(1)`);
- Ao detectar a saída do processo, o supervisor da Discloud executa o reinício automático da aplicação, restabelecendo as conexões.

---

## 7. Licença e Créditos

O **EmpireMuse** é disponibilizado sob a licença **GPL-2.0**, sendo uma obra derivada do projeto [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot) desenvolvido por **zRitsu**.

Os arquivos [`LICENSE`](../../LICENSE) e [`CREDITS.md`](../../CREDITS.md) acompanham compulsoriamente todos os pacotes de deploy para a Discloud, preservando a íntegra dos avisos de direitos autorais e as fontes originais de código.

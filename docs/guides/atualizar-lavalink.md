> Adaptado da wiki/gist do [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot) (zRitsu), GPL-2.0.

# Guia do Lavalink Local: Atualização, Plugins e Fontes de Áudio

Este guia é voltado para quem utiliza o servidor de áudio Lavalink em modo **LOCAL** no EmpireMuse (`RUN_LOCAL_LAVALINK=true` ou sem nós externos configurados).

Quando configurado para execução local, o próprio bot gerencia o download de binários, verificação de integridade, configuração e inicialização do processo do Lavalink em segundo plano.

---

## 1. Stack e Versões Homologadas (Release 0.0.2)

O EmpireMuse utiliza uma stack moderna baseada em releases oficiais e plugins espelhados com hashes fixados:

| Componente | Versão / Tag | Origem e Observações |
| :--- | :--- | :--- |
| **Lavalink** | **4.2.2 oficial** | Versão estável com suporte a Java 17+ e protocolo de voz **DAVE (E2EE)**. Substitui builds de desenvolvimento (snapshots). |
| **Java / JDK** | **17 ou superior** | Requisito do Lavalink 4.2.2 (Java 21 recomendado). Caso Java ≥ 17 não seja detectado no sistema, o bot baixa um JDK sob demanda. |
| **youtube-plugin** | Snapshot `2be8e542` | Build fixado pós-1.18.2 com correções críticas para clientes mobile/web e fechamento de conexões de cifra. |
| **LavaSrc** | **4.8.3** | Provedor de metadados e suporte a plataformas externas (Spotify e Deezer). |
| **Lyrics** | **2.6.1** | Plugin oficial de letras de músicas (`dev.schlaubi.lyrics`). |

Os artefatos homologados são distribuídos no espelho oficial da organização:
- **Repositório de Binários**: [DiscordEmpireHub/EmpireMuse-LL-binaries](https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/tag/0.0.2)

---

## 2. Segurança de Supply Chain e Verificação de Integridade

Para garantir a confiabilidade dos binários executados localmente, o EmpireMuse aplica validações rigorosas em `utils/music/local_lavalink.py`:

### Verificação Obrigatória por SHA-256
- Cada arquivo oficial (`Lavalink.jar`, `application.yml` e plugins) possui seu hash SHA-256 pré-computado e fixado no código (`utils/branding.py`).
- O download é realizado em arquivo temporário isolado e movido atomicamente para a pasta final somente após confirmação do hash. Em caso de divergência, o arquivo corrompido é excluído e o processo é abortado imediatamente.

### URLs Personalizadas (`LAVALINK_FILE_URL` e `LAVALINK_FILE_SHA256`)
Se você optar por hospedar seu próprio `Lavalink.jar` ou utilizar uma URL customizada:
- **É mandatório informar o hash**: Defina `LAVALINK_FILE_SHA256='<hash-sha256>'` no seu arquivo `.env` ou `config.json`.
- **Bloqueio preventivo**: Se `LAVALINK_FILE_URL` for apontado para um endereço diferente do padrão oficial e `LAVALINK_FILE_SHA256` estiver vazio, o bot recusará o download preventivamente antes de abrir qualquer conexão de rede.

### Preservação do `application.yml` Personalizado
- Se um arquivo `application.yml` já existir no diretório raiz e seu conteúdo for personalizado pelo usuário (não correspondendo ao hash padrão de fábrica), o bot **não sobrescreve o arquivo**.
- Um aviso informativo é registrado no log e a sua configuração customizada é integralmente respeitada.

### Plugins Espelhados sem Download em Tempo de Execução
- Os jars dos três plugins homologados são baixados pelo bot diretamente para o diretório `plugins/` com conferência de hash.
- O `application.yml` declara os plugins com as mesmas versões dos jars locais, garantindo que o Lavalink não precise fazer requisições dinâmicas a repositórios externos (como o Maven Central) durante a inicialização.

---

## 3. Fontes de Áudio e Decisões de Arquitetura

### 3.1. YouTube: Cifra Remota e Clientes Suportados
- **Cifra Remota (`remoteCipher`)**: A extração local de assinaturas de áudio do YouTube tornou-se inviável devido a constantes atualizações de criptografia da plataforma. O Lavalink depende de um serviço de cifra remota (`yt-cipher`) para desembaralhar streams de áudio.
  - No ambiente atual, utiliza-se a instância pública de referência (`https://cipher.kikkia.dev/`).
  - Para ambientes de produção com alto tráfego, recomenda-se implantar uma instância própria do `yt-cipher`.
- **Clientes Otimizados**: O plugin do YouTube está configurado para operar com os clientes `[MUSIC, ANDROID_VR, WEB, WEBEMBEDDED, TVHTML5_SIMPLY]`, assegurando maior estabilidade e contornando restrições de bloqueio.

### 3.2. Por que o OAuth do YouTube está Desligado?
O parâmetro `plugins.youtube.oauth.enabled` está desativado (`false`) por duas razões principais:
1. **Instabilidade Operacional**: Sem autorização manual contínua, o mecanismo de polling de dispositivo do plugin frequentemente entra em ciclos de falha (erros HTTP 400), inundando os registros de log do servidor.
2. **Proteção de Contas**: O login não oficial em contas Google automatizadas por bots de mídia acarreta riscos reais de bloqueio ou encerramento da conta associada.

A combinação dos clientes recomendados com o serviço de cifra remota provê reprodução estável sem necessidade de expor credenciais de conta pessoal.

### 3.3. Ordem de Busca e Limitação do SoundCloud
- A variável `SEARCH_PROVIDERS` tem como padrão `"ytsearch ytmsearch scsearch"`, priorizando o catálogo padrão do YouTube e do YouTube Music.
- **Limitação Conhecida do SoundCloud**: O lavaplayer upstream apresenta falha conhecida na detecção de formatos de transmissões HLS do SoundCloud (`Did not detect any supported formats`), sem correção disponibilizada até o momento. O provedor `scsearch` é mantido apenas como último recurso de fallback.

---

## 4. Procedimentos de Atualização

### Atualização do Lavalink (`@bot updatell`)
Para forçar o recarregamento do arquivo `Lavalink.jar` oficial e verificar a integridade dos binários:
1. Em um canal de texto acessível pelo bot, execute mencionando o bot:
   ```text
   @teubot updatell
   ```
2. O bot baixará a versão oficial mais recente homologada pelo projeto, validará o hash SHA-256 e atualizará os arquivos necessários.
3. Reinicie o processo do bot para que o novo servidor de áudio seja iniciado.

### Atualização do Código do Bot (`@bot update`)
Para puxar as alterações mais recentes do repositório oficial do EmpireMuse:
1. Mencione o bot com o comando de atualização:
   ```text
   @teubot update
   ```
2. O bot executará a rotina de atualização Git (`source_update.sh`).
3. Reinicie a aplicação após a conclusão para carregar os módulos atualizados.


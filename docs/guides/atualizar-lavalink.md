> Adaptado da wiki/gist do [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot) (zRitsu), GPL-2.0.

# Guia do Lavalink Local: Atualização, Plugins e Fontes de Áudio

Este guia é voltado para quem utiliza o servidor de áudio Lavalink em modo **LOCAL** no EmpireMuse (`RUN_LOCAL_LAVALINK=true` ou sem nós externos configurados).

Quando configurado para execução local, o próprio bot gerencia o download de binários, verificação de integridade, configuração e inicialização do processo do Lavalink em segundo plano.

---

## 1. Stack e Versões Homologadas (Release 0.0.3)

O EmpireMuse utiliza uma stack moderna baseada em releases oficiais e plugins espelhados com hashes fixados. A release **0.0.3** mantém os mesmos binários estáveis do Lavalink 4.2.2 e plugins da 0.0.2, introduzindo um `application.yml` atualizado com suporte ao cliente `TV` (essencial para contornar bloqueios anti-bot), OAuth desativado por padrão e nível de log de `dev.lavalink.youtube.http.YoutubeOauth2Handler` fixado em `WARN` (evitando vazamento de tokens nos logs):

| Componente | Versão / Tag | Origem e Observações |
| :--- | :--- | :--- |
| **Lavalink** | **4.2.2 oficial** | Versão estável com suporte a Java 17+ e protocolo de voz **DAVE (E2EE)**. Substitui builds de desenvolvimento (snapshots). |
| **Java / JDK** | **17 ou superior** | Requisito do Lavalink 4.2.2 (Java 21 recomendado). Caso Java ≥ 17 não seja detectado no sistema, o bot baixa um JDK sob demanda. |
| **youtube-plugin** | Snapshot `2be8e542` | Build fixado pós-1.18.2 com correções críticas para clientes mobile/web e suporte a cifra remota. |
| **LavaSrc** | **4.8.3** | Provedor de metadados e suporte a plataformas externas (Spotify e Deezer). |
| **Lyrics** | **2.6.1** | Plugin oficial de letras de músicas (`dev.schlaubi.lyrics`). |

Os artefatos homologados são distribuídos no espelho oficial da organização:
- **Repositório de Binários**: [DiscordEmpireHub/EmpireMuse-LL-binaries](https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/tag/0.0.3)

---

## 2. Segurança de Supply Chain e Verificação de Integridade

Para garantir a confiabilidade dos binários executados localmente, o EmpireMuse aplica validações rigorosas em `utils/music/local_lavalink.py`:

### Verificação Obrigatória por SHA-256
- Cada arquivo oficial (`Lavalink.jar`, `application.yml` e plugins) possui seu hash SHA-256 pré-computado e fixado no código (`utils/branding.py`).
- O download é realizado em arquivo temporário isolado e movido atomicamente para a pasta final somente após confirmação do hash. Em caso de divergência, o arquivo corrompido é excluído e o processo é abortado imediatamente.

### URLs do Jar e Regras de Download (`LAVALINK_FILE_URL` e `LAVALINK_FILE_SHA256`)
O parâmetro `LAVALINK_FILE_URL` define a origem do binário `Lavalink.jar`:
- **Vazio por padrão (recomendado)**: Se `LAVALINK_FILE_URL` estiver vazio no `.env` ou `config.json`, o bot utiliza automaticamente o espelho oficial correspondente à versão do código do EmpireMuse, sem exigir configuração manual de hash.
- **Atualização automática de versões anteriores**: Se a variável contiver uma URL oficial de versões anteriores do espelho (seja `0.0.1` ou `0.0.2`, inclusive sob o nome anterior do repositório `LL-binaries`), o bot reconhece o endereço oficial e atualiza sozinho para a versão atual, emitindo uma mensagem informativa no log recomendando esvaziar a variável.
- **Hospedagem própria ou URL customizada**: Se você optar por hospedar seu próprio `Lavalink.jar` em servidor próprio:
  - **HTTPS obrigatório**: O endereço precisa obrigatoriamente utilizar o esquema `https://`. Protocolos inseguros ou não autorizados são recusados.
  - **Hash obrigatório**: É mandatório definir `LAVALINK_FILE_SHA256='<hash-sha256>'` com o hash SHA-256 do seu arquivo. Se `LAVALINK_FILE_URL` apontar para um endereço externo sem o respectivo hash, o bot recusa o download preventivamente antes de abrir qualquer conexão de rede.

### Preservação do `application.yml` Personalizado
- Se um arquivo `application.yml` já existir no diretório raiz e seu conteúdo for personalizado pelo usuário (não correspondendo a nenhum dos hashes de versões oficiais conhecidas, como `0.0.1` ou `0.0.2`), o bot **não sobrescreve o arquivo**.
- Um aviso informativo é registrado no log e a sua configuração customizada é integralmente respeitada. Arquivos oficiais de versões anteriores são migrados de forma automática para a versão atual.

### Plugins Espelhados sem Download em Tempo de Execução
- Os jars dos três plugins homologados são baixados pelo bot diretamente para o diretório `plugins/` com conferência de hash SHA-256.
- O `application.yml` declara os plugins com as mesmas versões dos jars locais, garantindo que o Lavalink não precise fazer requisições dinâmicas a repositórios externos (como o Maven Central) durante a inicialização.

---

## 3. Fontes de Áudio e Decisões de Arquitetura

### 3.1. YouTube: Cifra Remota e Clientes Suportados
- **Cifra Remota (`remoteCipher`)**: A extração local de assinaturas de áudio do YouTube tornou-se inviável devido a constantes atualizações de criptografia da plataforma. O Lavalink depende de um serviço de cifra remota (`yt-cipher`) para desembaralhar streams de áudio.
  - No ambiente atual, utiliza-se a instância pública de referência (`https://cipher.kikkia.dev/`).
  - Para ambientes de produção com alto tráfego, recomenda-se implantar uma instância própria do `yt-cipher`.
- **Clientes Otimizados**: O plugin do YouTube está configurado para operar com os clientes `[MUSIC, TV, ANDROID_VR, WEB, WEBEMBEDDED, TVHTML5_SIMPLY]`, assegurando maior estabilidade e contornando restrições de bloqueio. O cliente `TV` é o único que suporta autenticação OAuth.

### 3.2. Bloqueio Anti-bot e Autenticação OAuth Opcional
Desde agosto de 2026, o YouTube intensificou restrições automáticas contra clientes externos e scrapers ("Sign in to confirm you're not a bot", "This video requires login"):
1. **Padrão Seguro**: O `application.yml` oficial da release 0.0.3 mantém `plugins.youtube.oauth.enabled: false` e o nível de log de `dev.lavalink.youtube.http.YoutubeOauth2Handler` fixado em `WARN`. Isso previne que tokens ou credenciais sejam impressos nos arquivos de log e evita ciclos contínuos de erro HTTP 400 quando não há conta vinculada.
2. **OAuth com Conta Descartável**: Caso seu servidor sofra bloqueios de IP na reprodução do YouTube, é possível ativar a autenticação OAuth vinculando uma **conta Google descartável** através da variável `YOUTUBE_OAUTH_REFRESH_TOKEN` no `.env`.
   - Consulte o guia completo e passo a passo em: [Guia de Configuração do YouTube OAuth](youtube-oauth.md).

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

---

## 5. Checklist de Release do Espelho (`EmpireMuse-LL-binaries`)

Ao publicar uma nova versão dos binários homologados no repositório [DiscordEmpireHub/EmpireMuse-LL-binaries](https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries), execute rigorosamente a checklist de integridade e governança abaixo:

1. **Publicação dos Artefatos**:
   - Compilar ou obter os artefatos oficiais homologados (`Lavalink.jar`, `application.yml` e jars dos plugins).
   - Gerar o arquivo `SHA256SUMS` com os hashes SHA-256 de todos os arquivos.
   - Publicar a release no GitHub sob a tag semântica (ex.: `0.0.3`) contendo todos os binários e o arquivo `SHA256SUMS`.
2. **Atualização do `utils/branding.py`**:
   - Atualizar a constante `LAVALINK_BINARIES_URL` para apontar para a nova tag de release.
   - Atualizar os hashes fixos `LAVALINK_JAR_SHA256`, `LAVALINK_APPLICATION_YML_SHA256` e o dicionário `LAVALINK_PLUGIN_SHA256` com base no `SHA256SUMS` conferido.
3. **Preservação de Versões Conhecidas do `application.yml`**:
   - Mover o hash do `application.yml` da release anterior para o conjunto `LAVALINK_APPLICATION_YML_KNOWN_SHA256`. Isso permite que o bot substitua automaticamente o arquivo padrão da versão anterior, sem sobrescrever arquivos que foram customizados pelos usuários.
4. **Preservação do Histórico de URLs Oficiais (`LAVALINK_JAR_OFFICIAL_URLS`)**:
   - Adicionar a nova URL oficial do `Lavalink.jar` ao conjunto `LAVALINK_JAR_OFFICIAL_URLS`.
   - **Manter compulsoriamente todas as URLs oficiais anteriores** (inclusive tags antigas como `0.0.1`, `0.0.2` e versões sob o nome antigo `LL-binaries`). Isso assegura que instalações antigas que tenham copiado a URL no `.env` sejam migradas de forma suave e automática, sem falhas de integridade no boot.
5. **Validação e Documentação**:
   - Atualizar as constantes correspondentes no teste de guarda `tests/test_branding.py` e executar a suíte com `pytest`.
   - Atualizar as referências da release na documentação técnica: `CREDITS.md`, `docs/architecture.md`, `docs/development.md` e `docs/guides/atualizar-lavalink.md`.
   - Registrar as alterações na seção `[Unreleased]` de `CHANGELOG.md`.


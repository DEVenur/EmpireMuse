> Adaptado da wiki/gist do [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot) (zRitsu), GPL-2.0.

# Obter Spotify CLIENT_ID e CLIENT_SECRET
<br/>

- 1 = Entre na dashboard do spotify developers [clicando aqui](https://developer.spotify.com/dashboard) (será necessário ter uma conta logada).

Nota: Caso apareça uma página como na imagem abaixo, marque a opção e clique em **ACCEPT THE TERMS**.

![](https://cdn.discordapp.com/attachments/480195401543188483/903838123363033128/Screenshot_0.png)
<br/><br/>

- 2 = Clique em **CREATE AN APP**.

![](https://cdn.discordapp.com/attachments/480195401543188483/903838125707628604/Screenshot_1.png)
<br/><br/>

- 3 = Adicione um app name e app description de sua escolha e em seguida marque a opção e clique em **CREATE**.

![](https://cdn.discordapp.com/attachments/480195401543188483/903838133089632327/Screenshot_2.png)
<br/><br/>

* 4 = Clique em **SHOW CLIENT SECRET**.

![](https://cdn.discordapp.com/attachments/480195401543188483/903838138244427826/Screenshot_3.png)
<br/><br/>

* 5 = Copie o Client ID e Client Secret para usar no projeto do seu bot.

![](https://cdn.discordapp.com/attachments/480195401543188483/903838145051787264/Screenshot_4.png)

---

## Cache de Autenticação e Tratamento de Erros

O bot autentica na API do Spotify utilizando as credenciais configuradas (`SPOTIFY_CLIENT_ID` e `SPOTIFY_CLIENT_SECRET`) e gerencia o token de acesso temporário:

- **Localização do Cache**: O token é mantido no arquivo `.spotify_cache.json` dentro do diretório de execução da aplicação (`RUNTIME_DIR`, configurável via variável de ambiente `EMPIREMUSE_HOME`), gravado com permissões restritas e substituição atômica.
- **Migração do Cache Legado**: Instalações anteriores que mantinham o cache no diretório temporário (`/tmp/.spotify_cache.json`) solicitarão automaticamente um novo token de acesso na primeira execução, salvando-o no diretório de execução atual.
- **Tratamento de Falhas de Acesso**: Em caso de expiração (HTTP 401), a renovação do token é limitada a uma tentativa por requisição. Falhas como conteúdo restrito/privado (HTTP 403) ou recurso inexistente (HTTP 404) geram mensagens claras em português na interface sem expor dados brutos da requisição.


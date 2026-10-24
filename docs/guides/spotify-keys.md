> Adaptado da wiki/gist do [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot) (zRitsu), GPL-2.0.

# Obter Spotify CLIENT_ID e CLIENT_SECRET

Para que o bot possa carregar faixas, álbuns e playlists do Spotify, é necessário obter as credenciais de API no painel de desenvolvedores do Spotify. Siga os passos abaixo:

1. Acesse o painel de desenvolvedores em [https://developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) com a sua conta do Spotify conectada (caso seja solicitado, aceite os termos de serviço para desenvolvedores).
2. Clique no botão **Create app**.
3. Preencha os campos obrigatórios do formulário:
   - **App name**: informe um nome de sua escolha (ex.: `EmpireMuse`).
   - **App description**: informe uma descrição breve (ex.: `Bot de música`).
   - **Redirect URIs**: informe um URI válido qualquer (ex.: `http://127.0.0.1:8080`). Este campo é obrigatório no formulário do Spotify, mas o bot não utiliza redirecionamentos web por usar apenas autenticação Client Credentials (comunicação direta entre servidores).
   - **Which API/SDKs are you planning to use?**: marque a opção **Web API**.
   - Aceite os termos de serviço marcando a caixa de seleção e clique em **Save**.
4. Na página do aplicativo recém-criado, clique em **Settings**:
   - Copie o valor exibido em **Client ID**.
   - Clique em **View client secret** para exibir o segredo e copie o valor exibido.
5. Abra o arquivo `.env` na raiz do seu bot e insira as credenciais obtidas:
   ```env
   SPOTIFY_CLIENT_ID=seu_client_id_aqui
   SPOTIFY_CLIENT_SECRET=seu_client_secret_aqui
   ```

---

## Cache de Autenticação e Tratamento de Erros

O bot autentica na API do Spotify utilizando as credenciais configuradas (`SPOTIFY_CLIENT_ID` e `SPOTIFY_CLIENT_SECRET`) e gerencia o token de acesso temporário:

- **Localização do Cache**: O token é mantido no arquivo `.spotify_cache.json` dentro do diretório de execução da aplicação (`RUNTIME_DIR`, configurável via variável de ambiente `EMPIREMUSE_HOME`), gravado com permissões restritas e substituição atômica.
- **Migração do Cache Legado**: Instalações anteriores que mantinham o cache no diretório temporário (`/tmp/.spotify_cache.json`) solicitarão automaticamente um novo token de acesso na primeira execução, salvando-o no diretório de execução atual.
- **Tratamento de Falhas de Acesso**: Em caso de expiração (HTTP 401), a renovação do token é limitada a uma tentativa por requisição. Falhas como conteúdo restrito/privado (HTTP 403) ou recurso inexistente (HTTP 404) geram mensagens claras em português na interface sem expor dados brutos da requisição.

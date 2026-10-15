> Adaptado da wiki/gist do [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot) (zRitsu), GPL-2.0.

> Nota: o template da Repl.it citado neste guia (`replit.com/@xRitsu/Discord-Music-Bot-PT-BR`) pertence ao autor original (zRitsu) e continua apontando para o upstream. Para hospedar o código do EmpireMuse, veja [replit-hosting.md](replit-hosting.md).

# Guia de como usar o template de source de bot de música da Repl.it

---


**Antes de prosseguir:**

**Caso não tenha um token de bot do discord ou não tenha criado uma conta de bot no developer portal, você pode conferir esse [video-tutorial](https://www.youtube.com/watch?v=lfdmZQySTXE) de como criar uma.**

**Ou caso já tenha uma conta de bot, certifique se as intents do bot que será usado nessa etapa está com a intents de [MESSAGE_CONTENT] e [MEMBERS] ativados.**

![jERdx9LGib](https://user-images.githubusercontent.com/74823568/247370590-508d49dd-3881-4e2b-8635-f528ab002126.png)

**Nota: O token do bot tem que ser copiado do menu "Bot" no developer portal (não na sessão de General Information). Caso não saiba onde obter o token de uma aplicação existente [clique aqui](https://user-images.githubusercontent.com/74823568/247370989-fb6ba9fa-6540-4f2f-8335-172aca1986f0.png) para conferir uma imagem indicando o local correto.**

---

## 1 - Fazendo fork do template da repl.it:

* 1-1: Para começar, acesse o link https://replit.com/@xRitsu/Discord-Music-Bot-PT-BR?v=1 e clique no botão **[Fork]**:

![chrome_Vy5lOTgJqC](https://user-images.githubusercontent.com/74823568/248447088-68ce5576-3b19-434a-a05a-3057a7bd6c45.png)


* 1-2: Na próxima tela coloque um nome para seu projeto (1) e uma descrição (2 - opcional) e em seguida clique no botão **[Fork Repl]** (3) e aguarde carregar:

![chrome_3aQNat6WR2](https://user-images.githubusercontent.com/74823568/248447131-51927814-9958-44f7-8c1b-64e85fec4b58.png)

* 1-3: Após o fork, vai aparecer a seguinte mensagem abaixo (clique em Manage Secrets):

![Screenshot_0](https://user-images.githubusercontent.com/74823568/285566461-0369d28b-d153-4564-af4c-51cde34937d0.png)

* 1-4: Nos campos exibidos nas secrets, coloque o token do seu bot em qualquer um dos 5 campos que começa com nome **TOKEN_MUSIC_BOT_** e depois clique no botão "Add Secret".

* Opcional: Caso queira usar mais de 1 bot por vez (pra ativar o sistema de [multi-voice](https://www.youtube.com/watch?v=3cIQEatP83I)) você pode colocar token de mais bots nos outros campos que começam com nome **TOKEN_MUSIC_BOT_**.

* Os demais campos são totalmente opcionais mas recomendo não preenche-los caso não saiba pra que servem.

![Screenshot_1](https://user-images.githubusercontent.com/74823568/285566691-fcb18480-2621-4d16-8a52-a1d7e24ae045.png)

---

## 2 - (Etapa removida, passe para a etapa 3).

---
## 3 - Iniciando o bot:

*  3-1: Agora basta apenas clicar no botão Run (Play) e aguardar as dependências serem instaladas e o(s) bot(s) serem iniciados.

![229854507-81f413c1-0208-4ed5-8e81-80d51f8b198f](https://user-images.githubusercontent.com/74823568/252920663-9b106278-62cd-449f-b6c3-4241ae27a712.png)

---

## 4 - Opcional: Migrar da repl.it para squarecloud (Hospedagem barata para manter o bot ligado 24h com planos a partir de R$8,99)

<details>
<summary>
Clique aqui para visualizar:
</summary>
</br>

Caso tenha feito fork (ou atualizado) antes do dia 25/10/2023 recomendo que atualize o code usando o comando no shell antes de prosseguir as etapas abaixo:
```sh
bash source_quick_update.sh
```

* 4-1: Antes de começar, verifique se o bot está online e se o seu projeto da repl.it está em execução. Siga os passos abaixo:

`1.` Procure o arquivo squarecloud.config.example</br>
`2.` Clique nos 3 pontos.</br>
`3.` Clique em rename.</br>

![chrome_rqD2q4g0ZG](https://user-images.githubusercontent.com/74823568/252834487-95ae7e07-1619-4223-bf2b-5c43b6d58b26.png)

Retire o .example do nome (ficando apenas com o nome squarecloud.config) e dê enter pra salvar alterações (Você pode conferir o arquivo caso queira alterar algo, lembrando que o mínimo de ram recomendável é 512mb).</br>

* 4-2: Vá no servidor onde o bot está (em um canal que o bot tenha acesso) e envie uma mensagem mencionando o bot + export (Exemplo: @teubot export) que ele vai te enviar um arquivo zip no privado.

![Screenshot_7](https://user-images.githubusercontent.com/74823568/252835284-66a426ac-0dc9-4439-8955-89a94d9df740.png)

* 4-3: Faça o download do arquivo zip enviado no seu privado.

![Screenshot_8](https://user-images.githubusercontent.com/74823568/252835404-f15e7dc9-8a18-49ed-b4d0-3a07044cef5e.png)

* 4-4: Acesse o site da squarecloud: https://squarecloud.app/

* 4-5: Clique em login e depois clique no botão **[Entrar com o discord]**. Será solicitado o acesso a algumas informações de sua conta do discord (clique em autorizar se tiver de acordo).

* 4-6: Após fazer login, clique no botão **[Adicionar aplicação]**

![Screenshot_9](https://user-images.githubusercontent.com/74823568/252835941-539b5135-f370-41be-913e-d1e4d0fd70ad.png)

* 4-7: Arraste o arquivo zip na região marcada na print abaixo (ou clique nessa mesma região pra selecionar o arquivo zip do bot manualmente) e aguarde sua aplicação ser inicializada.

![Screenshot_10](https://user-images.githubusercontent.com/74823568/252836193-886c9893-b94f-4dce-bdfa-2ec46957c4b5.png)

* 4-8: Voltando pra replit, pare o projeto (clicando no botão stop) pra evitar que o bot fique ligado em múltiplos locais causando conflitos.

* 4-9: Agora basta apenas testar o bot executando algum comando e verificar se o mesmo está funcionando normalmente.

### Nota:

* **Todos os itens configurados nas secrets (token etc) agora se encontram no arquivo .env para futuras alterações (use o gerenciador de arquivos da squarecloud para editá-lo quando necessário).**

</details>

---

### Observação importante:
Você pode usar essa source como alternativa de self-hosting do bot principal do upstream (Muse Heart) pra hospedar/rodar seu próprio bot de música para uso privado ou em servidores públicos no qual você gerencia (que você tenha permissão de adicionar seu próprio bot no servidor). Entretanto não recomendo distribuir o bot usando essa source publicamente por não estar otimizado o suficiente pra lidar com alta demanda de servidores, mas se mesmo assim decidir fazer isso o bot terá que estar sob a [licença gpl-2.0](https://github.com/DiscordEmpireHub/EmpireMuse/blob/main/LICENSE) da source original e dependendo de onde o bot estiver sendo divulgado (ex: botlists) há possibilidade de seu bot ser apontado pelo uso dessa source.


**Caso ainda tenha alguma dúvida, abra uma issue no [repositório do EmpireMuse](https://github.com/DiscordEmpireHub/EmpireMuse/issues) (convite do servidor de suporte: *pendente de definição pelo dono do projeto*).**

> Adaptado da wiki/gist do [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot) (zRitsu), GPL-2.0.

# Hospedando na Repl.it

*OBS: Será necessário criar/logar uma conta na repl.it (não será abordado essa parte no tutorial).

*Não esqueça de pegar o token do bot no [portal do desenvolvedor](https://discord.com/developers/applications/)

###

- 1 = O botão de execução em 1 clique está temporariamente desativado (veja o aviso abaixo):

Deploy em revisão — será reativado na fase de deploy (I-7).

<!-- Deploy em revisão — será reativado na fase de deploy (I-7). Botão original preservado:
[![Run on Repl.it](https://repl.it/badge/github/DiscordEmpireHub/EmpireMuse.git)](https://repl.it/github/DiscordEmpireHub/EmpireMuse.git)
-->

- 2 = Clique no cadeado localizado na barra da esquerda para abrir a página das secrets.

![](https://cdn.discordapp.com/attachments/480195401543188483/903853110546542612/unknown.png)
<br/><br/>

- 3 = Caso apareça esse aviso da imagem, apenas clique em **Got it** (caso não, pule para o próximo passo).

![](https://cdn.discordapp.com/attachments/480195401543188483/903853798995394601/unknown.png)
<br/><br/>

- 4 = No campo Key digite o nome **TOKEN** e em value cole o Token do seu bot e em seguida clique em **Add new secret**.

![](https://cdn.discordapp.com/attachments/480195401543188483/903855391178362941/unknown.png)
<br/><br/>

- 5 = Agora clique em **Run** e aguarde o bot ligar normalmente (verifique no discord se ele fica online).
<br/><br/>

- 6 = Após o bot estar online e rodando normalmente, teste os comandos de barra **/**. Caso os comandos não apareçam use o comando `@teubot syncguild` e tente seguir os passos citados na mensagem.

***

- Há algumas etapas opcionais para este método de hospedagem (alteração do prefixo de configuração inicial, suporte ao spotify, mongodb como database ao invés do arquivo database.json), [**clique aqui**](replit-hosting-opcionais.md) para conferir o guia das etapas opcionais.

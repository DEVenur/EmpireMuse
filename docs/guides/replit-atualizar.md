> Adaptado da wiki/gist do [MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot) (zRitsu), GPL-2.0.

# Repl.it: Atualizar seu bot

Guia referente ao vídeo abaixo:

[![Tutorial](https://img.youtube.com/vi/zTXF4QA05Ic/mqdefault.jpg)](https://www.youtube.com/watch?v=zTXF4QA05Ic)

Nota: Esse update pode desfazer qualquer alteração particular que você tenha feito no code original.

* 1 - Clique em stop pra parar o bot (ignore este passo caso seja o run, pois o bot já está parado).

![](https://media.discordapp.net/attachments/480195401543188483/917469841886158888/unknown.png)

* 2 - Clique em shell e digite:
```
git reset --hard && git pull --allow-unrelated-histories -X theirs && pip3 install -r requirements.txt --force-reinstall
```
e dê enter (se aparecer a mensagem `Already up to date` significa que seu code já estava atualizado, então só prossiga pro próximo passo).

![](https://media.discordapp.net/attachments/480195401543188483/922356741390360587/unknown.png)

* 3 - clique no botão run para executar o bot novamente.

![](https://media.discordapp.net/attachments/480195401543188483/917470609884205106/unknown.png)

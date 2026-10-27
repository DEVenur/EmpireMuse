# ADR-0004: Auto-update Docker por proxy de cliente com modelo fixo

**Data**: 2026-10-27
**Status**: Aceito
**Decisores**: MAESTRO, Equipe de Arquitetura e Engenharia EmpireMuse

## Contexto

O comando `update` foi removido do Docker por segurança: atualizar a imagem exige falar com o daemon, e o `docker.sock` equivale a root no host. A produção (VPS da Hostinger, onde o painel e o `docker compose` convivem com o Traefik) precisa de um `update` que o dono acione do Discord, sem dar ao bot, que roda código de terceiros e conteúdo remoto, acesso ao daemon. O bot é tratado como possivelmente comprometido.

## Decisão

O bot fala só com um **proxy próprio** por socket Unix (`empiremuse/updater/proxy.py`, arquivo único, só biblioteca padrão, rodado com `python -I -S`). O proxy é o único serviço com o `docker.sock`, aceita 5 operações fixas e **substitui o corpo** do pedido de criação por um modelo fixo de container auxiliar: o bot só escolhe o alvo `X.Y.Z@sha256:<digest>`. O auxiliar (imagem `docker` fixada por digest, sem rede) confere que a imagem puxada declara a versão alvo, recusa downgrade, troca uma única linha `image:` do compose com backup e sobe o serviço, com rollback. O alvo vem só de GitHub Releases imutáveis, com o digest da imagem assinada (cosign keyless) no `image-digest.txt`.

## Alternativas Consideradas

### Alternativa 1: Proxy de socket pronto (Tecnativa, wollomatic)
- **Prós**: prontos e mantidos.
- **Contras**: filtram por método e caminho, não pelo corpo do pedido de criação.
- **Por que não**: com o `docker.sock` como bind do auxiliar, qualquer imagem ou comando escolhido pelo bot vira root no host.

### Alternativa 2: Proxy que inspeciona o corpo (Sockguard, ChainSafe)
- **Prós**: regras por campo (`Privileged`, binds, capabilities).
- **Contras**: não fixam `Entrypoint` e `Cmd` de fábrica; comparar o corpo exige decodificar igual ao daemon (chaves sem diferenciar maiúsculas, última duplicata vale), e já houve desvios assim; a ChainSafe libera todo `GET` (leitura de arquivos e variáveis de outros containers).
- **Por que não**: o proxy próprio não compara o corpo, só o substitui.

### Alternativa 3: Plugin de autorização no daemon (OPA)
- **Prós**: o Rego enxerga tudo.
- **Contras**: vale para o daemon inteiro (painel, compose, Traefik), exige reiniciar o `dockerd` da produção, não identifica clientes do socket Unix e, se falhar, nega tudo.
- **Por que não**: o risco recai sobre a produção toda.

### Alternativa 4: API da Hostinger
- **Prós**: sem proxy.
- **Contras**: o token herda todas as permissões da conta, sem escopo.
- **Por que não**: esse token nunca vai para o bot.

## Consequências

### Positivas
- O bot nunca recebe o `docker.sock` nem o grupo do Docker; um bot comprometido só consegue pedir o auxiliar do modelo fixo.
- A imagem é escolhida por digest e versão (os dois vêm do GitHub), não por tag mutável.
- O compose é a fonte da verdade: o painel e o `compose up` enxergam o mesmo arquivo.

### Negativas
- O proxy e o auxiliar são código novo a manter; o auxiliar ainda equivale a root, por desenho (script fixo, sem rede).
- O `update` depende de permissões estritas do projeto (dono root, sem escrita de grupo ou outros).
- O bot não roda `cosign verify` na hora do `update`.

### Riscos e Mitigações
- **Risco**: token vazado do Docker Hub publica uma imagem com tag conhecida.
  - **Mitigação**: o auxiliar puxa por digest e o bot só oferece versões com GitHub Release imutável; as duas imagens do compose usam `tag@sha256`. Residual: quem tem escrita no repositório antes da imutabilidade troca o asset.
- **Risco**: o painel da Hostinger não tolerar o compose editado por fora.
  - **Mitigação**: o dono valida no primeiro `update` real; o guia pede para não editar o compose pelo painel durante um `update`.
- **Risco**: reversão indevida com o Lavalink fora do ar (sucesso exige um nó de áudio).
  - **Mitigação**: aceito e documentado; o dono repete o `update`.

Guia de uso: [`../guides/auto-update.md`](../guides/auto-update.md).

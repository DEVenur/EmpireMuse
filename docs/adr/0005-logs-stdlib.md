# ADR-0005: Log centralizado com a biblioteca padrão, redator único e agregador de repetidos

**Data**: 2026-10-27
**Status**: Aceito
**Decisores**: MAESTRO, Equipe de Arquitetura e Engenharia EmpireMuse

## Contexto

O log do bot era um conjunto de `print` (cerca de 135), de `traceback.print_exc()` (cerca de 90) e de um `FileHandler` ligado só com `ENABLE_LOGGER`, que punha o nível global em `DEBUG`. Com centenas de servidores tocando ao mesmo tempo isso não funciona: o console fica ilegível, o arquivo enche em minutos, os erros chegam sem contexto e nada garante que um segredo (token, senha de nó, URI do banco) não vaze numa exceção HTTP ou numa URL com chave. Títulos e nomes vindos de terceiros também podiam forjar linhas de log ou mexer no terminal do painel da hospedagem.

## Decisão

Adotamos o módulo `logging` da biblioteca padrão, configurado num ponto só (`empiremuse/logs/`), com três peças:

1. **Redator único.** Todo registro passa, nos dois destinos (console e arquivo), por uma cadeia de filtros: contexto → nível por servidor → saneamento e redação → agregação. O saneamento neutraliza quebras de linha e sequências de controle e limita o tamanho; a redação troca segredos por `***`.
2. **Agregador de repetidos.** Avisos e erros iguais saem inteiros uma vez por janela de 60 s e as repetições viram uma linha de resumo.
3. **Nível por servidor.** `LOG_LEVEL` vale para todos; `LOG_DEBUG_GUILDS` sobe só os servidores listados para `DEBUG`. Em `INFO`, o console traz problemas e um resumo periódico de métricas.

A telemetria é só local (console e arquivo rotativo de 5 MB × 3). Os detalhes de uso estão em [`docs/guides/logs.md`](../guides/logs.md).

## Alternativas Consideradas

### Alternativa 1: `loguru`
- **Prós**: API simples, cores e rotação prontas.
- **Contras**: dependência nova; as bibliotecas do projeto (disnake, aiohttp, pymongo) já usam `logging`, então seria preciso interceptá-las; filtros por servidor e redação em todos os destinos exigiriam um adaptador de qualquer forma.
- **Por que não**: o `logging` padrão já tem tudo de que precisamos (handlers, filtros, rotação, `contextvars` para o contexto) e recebe os registros das bibliotecas sem ponte.

### Alternativa 2: Serviço externo (Sentry, OpenTelemetry, Loki)
- **Prós**: busca, alertas e painéis prontos.
- **Contras**: manda dados de usuários e possíveis segredos para fora do host, custa manutenção e exige rede e conta.
- **Por que não**: a decisão do dono é telemetria local; o volume e o tamanho do projeto não justificam.

### Alternativa 3: Redigir só na saída (webhook e arquivo), e não em todo handler
- **Prós**: menos código por registro.
- **Contras**: um destino esquecido vaza; dois destinos com conteúdos diferentes complicam o suporte.
- **Por que não**: o filtro fica nos handlers (também vale para registros de bibliotecas que propagam ao root) e há um agregador compartilhado, então console e arquivo têm o mesmo conteúdo e diferem só em cor, emoji e data.

## Como o Redator e o Agregador Funcionam

- **Segredos.** Valores conhecidos (configuração, ambiente e segredos aprendidos em tempo de execução, como a senha de cada nó do Lavalink) são mascarados por valor, e os formatos conhecidos (credencial em URL, `api_key`/`token`/`sk` em query ou em dicionário, cabeçalho `Authorization`, token do Discord e de webhook) por padrão. Se a redação falhar, o registro é trocado por um aviso fixo: nunca sai sem redação. Exceções HTTP usam um resumo seguro (status, método e host), nunca `repr`.
- **Texto de terceiros.** Quebras de linha, ESC e controles viram marcadores, e as linhas de continuação de uma mensagem ou de um traceback ganham um prefixo, de modo que só o cabeçalho de um registro começa na coluna 0.
- **Agregação.** A chave de um erro repetido é logger + nível + modelo da mensagem + tipo de exceção. Os campos abaixo existem para a agregação nunca esconder um problema diferente ou um código que o dono precise achar.

### K8: o código de erro nunca some

O código `ERR-XXXXXX` é o que o dono usa para achar um erro. Por isso, em erros que carregam código, a primeira ocorrência da janela sai com o traceback inteiro, e as seguintes (até 50 por janela) saem como uma linha curta que **mantém o próprio código** e aponta para o traceback já impresso. Acima de 50 (rajada), só o resumo conta as repetições. Além disso, a chave inclui uma impressão digital do **caminho de chamada** do traceback (arquivo, linha e função, nunca a mensagem): dois erros de pontos diferentes com o mesmo tipo e o mesmo modelo de mensagem não se confundem, e uma mensagem forjada não consegue fingir ser outro ponto.

### K16: discriminador opcional para o mesmo modelo

Quando o mesmo modelo de mensagem cobre problemas diferentes, o produtor pode passar um discriminador de **baixa cardinalidade** (por exemplo, o identificador do nó ou o código de fechamento). Assim, a queda do nó A e a do nó B na mesma janela aparecem como duas linhas, e não como uma e uma contagem. O valor entra só na chave (cortado e saneado), nunca é impresso, e nunca deve ser ID de servidor, de canal ou de usuário, o que estouraria o teto de 500 chaves.

### K15: a regra vale para todo produtor

Todo ponto do código que registra um código de erro em `WARNING` ou acima tem de seguir o K8 e, quando o modelo é ambíguo, o K16: eventos do player, falhas do Lavalink, o tratador de erros de comandos e os tratadores do painel web. Um produtor novo segue a mesma regra, e o gate de revisão rejeita quem não segue.

## Consequências

### Positivas
- Console calmo em escala (no máximo uma linha de resumo por intervalo, mais os problemas) e detalhe sob demanda por servidor.
- Nenhum destino recebe segredo nem texto de terceiros sem tratamento; o webhook de erro passa pelo mesmo redator.
- Erros com contexto mínimo (IDs, comando, parâmetros resumidos por tipo) e códigos `ERR-…` localizáveis (até 50 ocorrências com código por chave e janela; acima disso só o resumo as conta).
- Sem dependência nova e sem rede.

### Negativas
- Mais código próprio de log para manter (cerca de 1,5 mil linhas em `empiremuse/logs/`) e uma regra de revisão para os produtores de erro.
- Valores de segredo com menos de 6 caracteres não são mascarados por valor (os formatos conhecidos ainda são).
- Registros emitidos antes da configuração do log (início do `boot_guard`) usam o comportamento padrão do Python (`WARNING` ou acima); as exceções não tratadas desse trecho já passam por ganchos com redação.
- IDs de servidor e de usuário no log são dado pessoal (LGPD): a retenção fica limitada pela rotação do arquivo e pelo driver do Docker.

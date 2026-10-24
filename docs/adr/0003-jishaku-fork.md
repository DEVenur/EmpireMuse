# ADR-0003: Justificativa de Uso do Fork zRitsu/jishaku para Disnake

**Data**: 2026-10-24
**Status**: Aceito
**Decisores**: MAESTRO, Equipe de Arquitetura e Engenharia EmpireMuse

## Contexto

O pacote oficial `jishaku` distribuído via PyPI é implementado exclusivamente para o framework `discord.py`. O **EmpireMuse** utiliza o framework `disnake`, o que impede a utilização direta do pacote oficial sem adaptações estruturais de compatibilidade.

Em razão disso, o projeto depende do fork `zRitsu/jishaku` (mantido pelo autor original do upstream MuseHeart-MusicBot), que provê a adaptação da extensão de desenvolvimento e depuração para a API do Disnake. Essa dependência é declarada em `requirements-git.txt:4` e fixada pelo SHA completo de commit `14d2dbd51d61382c687af8d8655f54f41674c0eb`, dado que instalações via VCS/Git não suportam o mecanismo `--require-hashes` do pip/uv (conforme documentado em `.claude/rules/empiremuse/security.md` §8 e no item KI-30).

As diretrizes de governança do projeto (`security.md` §6) determinam que qualquer dependência originada de fork de terceiro exige justificativa formal registrada em ADR.

## Decisão

Mantemos temporariamente o fork `zRitsu/jishaku` fixado por commit SHA completo em `requirements-git.txt`, adotando salvaguardas operacionais rígidas:

1. **Desativação por Padrão**: a extensão `jishaku` permanece **desligada por padrão** e só é carregada quando a variável de ambiente `ENABLE_JISHAKU=true` for explicitamente configurada pelo operador.
2. **Auditoria de Operação**: execuções de comandos de proprietário do bot são registradas em log estruturado (identificador do operador, comando invocado e horário), sem exposição de dados sensíveis ou segredos.

## Alternativas Consideradas

### Alternativa 1: Remover o jishaku por Completo
- **Prós**: Elimina a dependência de repositório Git externo e simplifica a gestão de dependências.
- **Contras**: Perda de ferramentas fundamentais de diagnóstico interativo, inspeção de estado e REPL em tempo de execução durante o desenvolvimento.
- **Por que não**: O utilitário é valioso para diagnóstico técnico controlado; sua desativação por padrão neutraliza o risco em ambientes produtivos.

### Alternativa 2: Usar o Pacote Oficial do PyPI
- **Prós**: Pacote padrão distribuído no índice oficial com suporte a hashes de integridade.
- **Contras**: Incompatibilidade técnica com a biblioteca `disnake`, causando falhas na importação e nos comandos.
- **Por que não**: Inviável tecnicamente sem manter uma camada de compatibilidade equivalente a um fork.

## Consequências

### Positivas
- Preservação da capacidade de depuração interativa quando habilitada voluntariamente pelo operador.
- Ausência de superfície de exposição em configurações padrão (`ENABLE_JISHAKU=false`).
- Imutabilidade do código assegurada pela fixação do commit por SHA completo de 40 caracteres hexadecimais.

### Negativas
- Concentração de risco de cadeia de suprimentos em repositório externo de terceiro no GitHub.
- Impossibilidade de uso de verificação criptográfica por `--require-hashes` no arquivo de lock para dependências Git.
- Necessidade de conferência manual de histórico para eventuais atualizações de versão ou correções.

### Riscos e Mitigações
- **Risco**: Indisponibilidade, exclusão ou comprometimento do repositório remoto de terceiro.
  - **Mitigação**: O fork fica desativado por padrão; o clone utiliza SHA imutável; planeja-se a migração para governança da própria organização.

## Evolução Futura

Conforme planejado no roteiro técnico do projeto (item 6 do planejamento e catálogo KI-30), a dependência será migrada para um fork próprio sob a organização `EmpireCommunity` (`EmpireCommunity/jishaku`), com auditoria prévia completa, controle direto de publicação e releases tagueadas de forma independente.

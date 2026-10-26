# ADR-0003: Fork EmpireCommunity/EmpireMuse-jishaku para o Disnake

**Data**: 2026-10-24 (atualizado em 2026-10-25)
**Status**: Aceito
**Decisores**: MAESTRO, Equipe de Arquitetura e Engenharia EmpireMuse

## Contexto

O pacote oficial `jishaku` do PyPI é feito para `discord.py`; o **EmpireMuse** usa `disnake`, então precisa de um fork adaptado. Até 2026-10-24 o projeto usava `zRitsu/jishaku` fixado por SHA de commit em `requirements-git.txt`, porque dependências VCS não aceitam `--require-hashes`. O `security.md` §6 exige ADR para dependência vinda de fork de terceiro.

## Decisão

Adotamos o fork próprio **[EmpireCommunity/EmpireMuse-jishaku](https://github.com/EmpireCommunity/EmpireMuse-jishaku)** (submódulo `repos/EmpireMuse-jishaku`), distribuição `empiremuse-jishaku` (pacote importável `jishaku`), versão `2.6.6.post1` (base 2.6.6 do disnake-jishaku). A instalação é pelo **wheel da release por URL com `--hash` SHA-256** (`ee097676…5a6f`) no `requirements-lock.txt`, com as dependências (`braceexpand`, `click`, `disnake>=2.12,<3`, `import_expression>=1,<2`) também com hash. Não há mais dependência VCS (`requirements-git.txt` foi removido).

Salvaguardas mantidas e acrescentadas:

1. **Desligado por padrão**: só carrega com `ENABLE_JISHAKU=true`.
2. **Auditoria de operação**: comandos de dono são registrados em log estruturado (`legacy_cmds.py`).
3. **Endurecimento do fork** (opt-in no fork; o EmpireMuse as ativa em `load_jishaku_if_enabled`): `JISHAKU_MASK_SECRETS=true` (mascara token e segredos do ambiente na saída), `JISHAKU_DM_ONLY=true` e `JISHAKU_OWNER_IDS` a partir de `OWNER_IDS` quando houver IDs (o dono do aplicativo precisa estar na lista, pois lista vazia nega todos). O `jsk sh` roda com ambiente mínimo. Tracebacks voltam por DM (`JISHAKU_NO_DM_TRACEBACK` foi removido).

## Auditorias

- **Segurança** (Cybersecurity Specialist, 2026-10-25): árvore do fork idêntica à de `zRitsu/jishaku@14d2dbd5` verificada antes das mudanças; recomendou migrar para a organização e endurecer segredos, ambiente do shell e restrição de donos. Veredito: aceitar com as salvaguardas acima.
- **Revisão e padronização** (Backend, 2026-10-25): CI do fork (lint, testes em Python 3.10–3.14, wheel em instalação limpa), correções de compatibilidade com Python 3.13/3.14 e as melhorias de segurança acima; release `v2.6.6.post1` com `SHA256SUMS`.
- Os relatórios completos ficam no ambiente privado do projeto, sem detalhes exploráveis.

## Alternativas Consideradas

- **Remover o jishaku**: perde-se o diagnóstico interativo; descartado porque a extensão fica desligada por padrão.
- **Pacote oficial do PyPI**: incompatível com `disnake`.
- **Manter `zRitsu/jishaku` por SHA**: sem hash de distribuição, sem controle de publicação; substituído.

## Consequências

- Positivas: instalação verificável por hash, controle direto de correções e releases, sem VCS no build.
- Negativas: o projeto passa a manter o fork; atualizações são feitas por nova release e novo hash no lock, com diff revisado.
- Risco residual: indisponibilidade do GitHub Releases no build (mitigado pelo hash e pelo submódulo com o código-fonte).

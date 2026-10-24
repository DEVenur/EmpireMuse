# Testes — EmpireMuse

**Esta regra prevalece sobre `.claude/rules/ecc/common/testing.md`**: a meta de 80% e o TDD obrigatório do ECC
não se aplicam aqui.

**Problema que resolve:** a suíte chegou a 8.422 testes e o CI a 6–7 min para um bot comunitário; boa parte
travava a estrutura em vez de proteger comportamento. **Custo que evita:** minutos de pipeline por PR e tokens
gastos escrevendo, mantendo e relendo testes de pouco valor.

## O que merece teste

- Segurança: painel, RPC, OAuth/sessão, segredos e toda entrada de usuário.
- Persistência e migração de dados.
- `config_loader` (precedência e tipagem).
- Contratos com Discord e Lavalink.
- Regras puras (`empiremuse/rules`).
- Regressão de bug real: um teste por bug.

## Proibido

- Caracterização em massa.
- Snapshots ou "dourados" de estrutura.
- Testes que leem o texto de docs, compose, Dockerfile ou workflows.
- Testes que dependem de tempo real ou `sleep`.
- Testes tautológicos (reafirmam constante ou mock).
- Vários testes para o mesmo caminho mudando só o valor: use `parametrize` enxuto.

## TDD

RED antes só para correção de bug e regra pura. No resto, teste depois e somente se o item cair em
"O que merece teste".

## Cobertura

- piso global no pyproject (`fail_under = 56`), que nunca cai;
- áreas críticas (painel, RPC/web, regras, config, banco, serialização e leitor legado) com ≥ 90%, garantido por um passo no CI; teste removido ali que derrube a cobertura reprova o PR;
- sem meta global de 70%: cogs e player (código de Discord/voz) ganham teste só por bug real ou risco, nunca para subir o número.

## Testes locais

Rode localmente só o que o CI/CD e o bot ECC Tools não cobrem. Lint, smoke e a suíte rodam no CI e não se
repetem localmente. **Pronto = CI verde.**

## Marcadores

`smoke`, `critical` e `regression` (a serem criados na T2c). Use-os ao escrever testes novos.

Revisão desta regra: 2027-01-24.

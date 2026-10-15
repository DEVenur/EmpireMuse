@AGENTS.md

# Configuração do Claude Code — EmpireMuse

Diretrizes específicas para o Claude Code complementando as instruções unificadas de `@AGENTS.md`.

## 1. Plugin Everything Claude Code (ECC)

O plugin `ecc@ecc` opera no escopo de usuário. Utilize as capacidades integradas:

- **Comandos Principais**:
  - `/ecc:plan`: Planejamento arquitetural, PRDs e quebra de tarefas.
  - `/ecc:code-review`: Revisão técnica de qualidade antes de commits.
  - `/ecc:python-review`: Revisão especializada em padrões idiomáticos Python.
  - `/ecc:security-scan`: Varredura e auditoria de vulnerabilidades de segurança.
- **Subagentes Principais e TDD**:
  - Fluxo TDD conduzido via skill `ecc:tdd-workflow` com o agente `ecc:tdd-guide` (RED → GREEN → IMPROVE).
  - `ecc:planner`: Planejamento de implementação e refatorações complexas.
  - `ecc:tdd-guide`: Implementação orientada a testes e validação de cobertura.
  - `ecc:python-reviewer`: Revisão especializada em padrões e boas práticas Python.
  - `ecc:security-reviewer`: Análise de vulnerabilidades, validações e segredos.
  - `ecc:code-reviewer`: Revisão de manutenibilidade e qualidade de código.

## 2. Regras Automáticas (`.claude/rules`)

O Claude Code carrega automaticamente as regras sob `.claude/rules/`:
- `.claude/rules/empiremuse/*`: Regras específicas do projeto (com precedência estrita).
- `.claude/rules/ecc/{common,python}/*`: Regras genéricas do ECC (common + python, sem fastapi), versionadas **de propósito** no projeto para garantir que todos os colaboradores e instâncias sigam as mesmas diretrizes.

## 3. Evitar Duplicação de Hooks, Agentes e Comandos

**Não instale hooks, agentes ou comandos ECC localmente no projeto**: Esses componentes já são fornecidos centralmente pelo plugin `ecc@ecc` no escopo do usuário. Mantenha o repositório enxuto, versionando estritamente as regras de `.claude/rules/`.

# Governança de Regras — EmpireMuse

**Problema que resolve:** regras acumuladas sem motivo registrado viram burocracia (a suíte de 8.422 testes e o
CI de 6–7 min nasceram assim) e cada regra extra é relida por todo agente a cada sessão. **Custo que evita:**
tempo de pipeline e tokens de contexto.

Vale para regras de teste, de processo e de agentes (`AGENTS.md`, `CLAUDE.md`, `.claude/rules/`).

Toda regra nova ou alterada deve:

1. **Citar o problema concreto** que resolve e o **custo em tempo/tokens** que evita ou impõe.
2. Ser **proporcional e curta**.
3. **Preferir editar** uma regra existente a criar outra.
4. Ter uma **data de revisão**.

Regra sem problema concreto não entra. Na revisão, a regra que não resolve mais o problema citado sai.

Revisão desta regra: 2027-01-24.

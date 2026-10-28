# Problemas conhecidos (backlog técnico)

Lista de bugs e riscos **abertos**, com local, impacto e severidade. Itens de segurança não entram aqui: ver
[`.github/SECURITY.md`](../.github/SECURITY.md) (rastreados em privado).

**Severidade:** *crítico* (quebra o uso básico ou perde dados de forma geral) · *alto* (recurso importante quebrado
ou perda de dados em cenário comum) · *médio* (comportamento incorreto com contorno) · *baixo* (qualidade,
desperdício ou risco futuro).

## Abertos

Nenhum (2026-10-26).

## Aceitos por desenho

| ID | Local | Decisão |
|---|---|---|
| KI-35 | `empiremuse/utils/branding.py`, `assets/`, `data/lavalink_servers.ini` | Os assets (organizados em subpastas de `assets/`) e a lista de servidores Lavalink são servidos via `raw.githubusercontent.com`: os assets pela tag da versão quando o bot roda numa imagem com `EMPIREMUSE_VERSION` (uma versão publicada não perde as próprias imagens) e pela `main` em um checkout git; a lista de servidores, sempre pela `main`. `branding.py` é o ponto único que um fork ajusta para apontar para os próprios. |

## Histórico

Os itens KI-01 a KI-58 (exceto a KI-35) foram resolvidos entre a Fase 3 e a v2.0.2. A descrição completa de cada um está na
versão anterior deste arquivo (`git log -p -- docs/known-issues.md`), e a maioria também é citada no
[`CHANGELOG.md`](../CHANGELOG.md); testes e docs que citam um `KI-xx` apontam para esse histórico.

## Como registrar e corrigir

1. Novo item: próximo ID livre (**KI-59**), com local por símbolo (classe, função ou método, não número de linha),
   problema, impacto e severidade, na tabela de "Abertos".
2. Bug: teste de regressão RED antes da correção (ver `.claude/rules/empiremuse/testing.md`).
3. Cite o `KI-xx` no commit, no PR e no `CHANGELOG.md`.
4. Ao concluir, remova o item daqui; o registro fica no `CHANGELOG.md`.

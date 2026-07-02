# Backlog — simplicio-mapper

Lista priorizada de tudo que precisa ser feito. É a fonte da verdade de pendências do produto.

> Este arquivo é classificado como `product_paths` em `template-manifest.json` (ver
> ADR-004): carrega o backlog real deste produto, não o exemplo genérico do starter.
> A fonte de verdade rastreável é a épica
> [#131](https://github.com/wesleysimplicio/simplicio-mapper/issues/131) no GitHub;
> esta tabela é o resumo local.

## Como usar este backlog

- Cada linha é um item rastreável que vira uma `task.md` quando entra em sprint.
- Prioridades:
  - **P0** — bloqueador, sem isso o produto não funciona.
  - **P1** — importante, planejado pra próximas 1-2 sprints.
  - **P2** — desejável, fica no radar mas pode esperar.
- Status:
  - `todo` — não começou.
  - `doing` — em andamento na sprint atual.
  - `done` — entregue, em produção.
- Ordenação dentro da tabela: P0 primeiro, depois P1, depois P2. Dentro da mesma prioridade, ordenar por `sprint alvo`.

## Regras de manutenção

- Toda nova ideia entra como P2 até alguém defender priorizar.
- Itens `done` ficam no histórico por uma sprint e depois são arquivados em `BACKLOG-archive.md`.
- Se um item passa 2 sprints como `todo`, reavalia: ainda faz sentido? Reprioriza ou remove.
- Quem altera prioridade ou move pra `doing` deve atualizar a tabela no mesmo PR.

## Backlog atual — Motor de Documentação Viva (épica #131)

| #   | Título                                                              | Issue | Prioridade | Fase | Status |
| --- | -------------------------------------------------------------------- | ----- | ---------- | ---- | ------ |
| F2  | `flows` — inventário de fluxos técnicos stack-neutral                | #133  | P0         | 1    | done   |
| F4  | Diagramas mermaid determinísticos em todos os docs                   | #135  | P0         | 1    | done   |
| F5  | `sync` — docs-sync dirigido por diff                                  | #136  | P0         | 2    | done   |
| F6  | `history`/`diff` — histórico e changelog de arquitetura               | #137  | P1         | 2    | done   |
| F1  | `survey` — onboarding "novo dev"                                      | #132  | P1         | 3    | done   |
| F3  | `business` — regras de negócio + glossário                            | #134  | P1         | 3    | done   |
| F10 | `ask` — consultas estruturadas sobre o mapa                           | #141  | P2         | exp. | done   |
| F9  | Manifest template vs produto (ADR-004)                                | #140  | P1         | pré-F7 | done |
| F7  | `drift` — spec-drift e matriz de rastreabilidade                      | #138  | P1         | 4    | doing  |
| F8  | GitHub Action de fluxos afetados no PR                                | #139  | P2         | 4    | todo   |

## Dívida conhecida (surfaced pelo próprio `drift`/F7)

Ver `template-manifest.json` → `known_gaps`. Docs de produto ainda não preenchidos
para o simplicio-mapper (carregam os tokens de template originais — PRODUCT_NAME,
TEAM, DOMAIN, STACK — sem os angle brackets):

| #   | Doc                                  | Prioridade | Sprint alvo | Status |
| --- | ------------------------------------- | ---------- | ----------- | ------ |
| 11  | Preencher `.specs/architecture/DESIGN.md` para simplicio-mapper   | P2 | backlog | todo |
| 12  | Preencher `.specs/architecture/PATTERNS.md` para simplicio-mapper | P2 | backlog | todo |
| 13  | Preencher `.specs/workflow/WORKFLOW.md` para simplicio-mapper     | P2 | backlog | todo |
| 14  | Preencher `.specs/workflow/CONTRIBUTING.md` para simplicio-mapper | P2 | backlog | todo |
| 15  | Preencher `.specs/workflow/RELEASE.md` para simplicio-mapper      | P2 | backlog | todo |

## Histórico recente (últimos done)

| #   | Título                              | Sprint     | Concluído em |
| --- | ----------------------------------- | ---------- | ------------ |
| 0   | Bootstrap de repositório + AGENTS.md | sprint-00 | 2026-05-07   |
| F2,F4,F5,F6,F1,F3,F10,F9 | Motor de Documentação Viva — fases 1-3 + expansão | sprint-flow-docs | 2026-07-02 |

## Itens descartados ou movidos pra fora

- Nenhum item descartado ainda.

## Próximas decisões pendentes

- F7 (`drift`) e F8 (GitHub Action) fecham o loop de governança spec-driven da épica #131.
- Preenchimento dos docs em "Dívida conhecida" depende de decisão de processo real do time
  (branch strategy, cadência de release, papéis) — não é um problema de código, é conteúdo
  que só o time pode fornecer com precisão.

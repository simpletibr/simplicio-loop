# Auditoria de issues — GitHub issue #265

> Relatório gerado por `python3 scripts/meta_issue_audit.py`; não editar manualmente.

## Escopo, responsabilidade e limites

O `simplicio-dev-cli` é a CLI determinística de desenvolvimento que consome Mapper, PlanDAG, Prompt e Runtime, preservando contratos estáveis e saída auditável. Esta auditoria especifica e classifica issues; ela não substitui implementação, resultados de testes nem evidência externa, e não declara integração ou desempenho sem medição.

## Inventário

- Total: **97**
- Estados: `{"closed": 90, "open": 7}`
- Decisões: `{"CLOSE-READY": 3, "HISTORICAL-EVIDENCE-GAP": 87, "NEEDS-IMPLEMENTATION": 7}`
- SHA-256 da normalização: `fe56e8baf3115249e62910a116c78cd78f5374eefa126e35014d88dc5344ad0d`

## Matriz resumida

| # | criada | estado | componente | risco | prioridade | decisão |
|---:|---|---|---|---|---|---|
| [6](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/6) | 2026-05-27 | closed | mapper | high | unassigned | HISTORICAL-EVIDENCE-GAP |
| [7](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/7) | 2026-05-27 | closed | mapper | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [8](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/8) | 2026-05-27 | closed | mapper | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [9](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/9) | 2026-05-27 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [10](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/10) | 2026-05-27 | closed | prompt | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [11](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/11) | 2026-05-27 | closed | prompt | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [14](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/14) | 2026-05-28 | closed | prompt | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [15](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/15) | 2026-05-28 | closed | prompt | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [16](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/16) | 2026-05-28 | closed | mapper | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [17](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/17) | 2026-05-28 | closed | quality | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [18](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/18) | 2026-05-28 | closed | prompt | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [21](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/21) | 2026-05-28 | closed | mapper | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [31](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/31) | 2026-05-29 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [32](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/32) | 2026-05-29 | closed | plandag | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [33](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/33) | 2026-05-29 | closed | quality | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [34](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/34) | 2026-05-29 | closed | plandag | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [35](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/35) | 2026-05-29 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [36](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/36) | 2026-05-29 | closed | plandag | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [37](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/37) | 2026-05-29 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [41](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/41) | 2026-05-30 | closed | plandag | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [42](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/42) | 2026-05-31 | closed | quality | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [46](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/46) | 2026-05-31 | closed | cli | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [51](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/51) | 2026-05-31 | closed | quality | high | unassigned | HISTORICAL-EVIDENCE-GAP |
| [53](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/53) | 2026-06-01 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [57](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/57) | 2026-06-02 | closed | plandag | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [60](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/60) | 2026-06-02 | closed | mapper | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [61](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/61) | 2026-06-02 | closed | prompt | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [62](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/62) | 2026-06-02 | closed | mapper | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [63](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/63) | 2026-06-02 | closed | cli | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [64](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/64) | 2026-06-02 | closed | cli | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [65](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/65) | 2026-06-02 | closed | cli | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [66](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/66) | 2026-06-02 | closed | quality | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [67](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/67) | 2026-06-02 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [68](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/68) | 2026-06-02 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [78](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/78) | 2026-06-30 | closed | prompt | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [80](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/80) | 2026-07-02 | closed | prompt | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [85](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/85) | 2026-07-02 | closed | prompt | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [88](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/88) | 2026-07-02 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [89](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/89) | 2026-07-02 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [90](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/90) | 2026-07-02 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [93](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/93) | 2026-07-02 | closed | mapper | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [98](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/98) | 2026-07-07 | open | runtime | high | P0 | NEEDS-IMPLEMENTATION |
| [99](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/99) | 2026-07-07 | closed | mapper | low | P1 | HISTORICAL-EVIDENCE-GAP |
| [100](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/100) | 2026-07-07 | closed | runtime | medium | P1 | HISTORICAL-EVIDENCE-GAP |
| [101](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/101) | 2026-07-07 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [102](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/102) | 2026-07-07 | closed | runtime | medium | P1 | HISTORICAL-EVIDENCE-GAP |
| [103](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/103) | 2026-07-07 | closed | runtime | high | P2 | HISTORICAL-EVIDENCE-GAP |
| [104](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/104) | 2026-07-07 | closed | quality | low | P2 | HISTORICAL-EVIDENCE-GAP |
| [105](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/105) | 2026-07-07 | closed | cli | low | P1 | HISTORICAL-EVIDENCE-GAP |
| [106](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/106) | 2026-07-07 | closed | mapper | low | P1 | HISTORICAL-EVIDENCE-GAP |
| [107](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/107) | 2026-07-07 | closed | mapper | medium | P1 | HISTORICAL-EVIDENCE-GAP |
| [111](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/111) | 2026-07-09 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [113](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/113) | 2026-07-09 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [114](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/114) | 2026-07-10 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [115](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/115) | 2026-07-10 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [116](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/116) | 2026-07-10 | closed | plandag | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [117](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/117) | 2026-07-10 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [118](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/118) | 2026-07-10 | closed | mapper | high | P0 | CLOSE-READY |
| [119](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/119) | 2026-07-10 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [120](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/120) | 2026-07-10 | closed | runtime | medium | P1 | CLOSE-READY |
| [121](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/121) | 2026-07-10 | closed | runtime | medium | P1 | HISTORICAL-EVIDENCE-GAP |
| [122](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/122) | 2026-07-10 | closed | mapper | low | P1 | HISTORICAL-EVIDENCE-GAP |
| [126](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/126) | 2026-07-10 | closed | quality | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [127](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/127) | 2026-07-10 | closed | mapper | medium | P1 | HISTORICAL-EVIDENCE-GAP |
| [129](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/129) | 2026-07-11 | closed | mapper | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [140](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/140) | 2026-07-11 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [141](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/141) | 2026-07-11 | closed | runtime | medium | P1 | HISTORICAL-EVIDENCE-GAP |
| [166](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/166) | 2026-07-12 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [167](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/167) | 2026-07-12 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [181](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/181) | 2026-07-13 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [200](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/200) | 2026-07-14 | closed | mapper | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [201](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/201) | 2026-07-14 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [202](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/202) | 2026-07-14 | closed | cli | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [212](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/212) | 2026-07-17 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [213](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/213) | 2026-07-17 | closed | mapper | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [218](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/218) | 2026-07-17 | closed | mapper | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [219](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/219) | 2026-07-17 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [221](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/221) | 2026-07-17 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [223](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/223) | 2026-07-17 | closed | mapper | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [227](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/227) | 2026-07-17 | closed | mapper | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [231](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/231) | 2026-07-18 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [232](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/232) | 2026-07-18 | closed | mapper | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [236](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/236) | 2026-07-18 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [237](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/237) | 2026-07-18 | closed | runtime | medium | unassigned | CLOSE-READY |
| [243](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/243) | 2026-07-18 | closed | prompt | low | unassigned | HISTORICAL-EVIDENCE-GAP |
| [246](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/246) | 2026-07-19 | closed | prompt | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [247](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/247) | 2026-07-19 | closed | runtime | high | unassigned | HISTORICAL-EVIDENCE-GAP |
| [251](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/251) | 2026-07-19 | open | runtime | medium | unassigned | NEEDS-IMPLEMENTATION |
| [252](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/252) | 2026-07-19 | closed | runtime | medium | unassigned | HISTORICAL-EVIDENCE-GAP |
| [255](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/255) | 2026-07-20 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [256](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/256) | 2026-07-20 | open | runtime | high | P0 | NEEDS-IMPLEMENTATION |
| [257](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/257) | 2026-07-20 | open | runtime | high | P0 | NEEDS-IMPLEMENTATION |
| [258](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/258) | 2026-07-20 | open | runtime | high | P0 | NEEDS-IMPLEMENTATION |
| [259](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/259) | 2026-07-21 | closed | runtime | high | P0 | HISTORICAL-EVIDENCE-GAP |
| [261](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/261) | 2026-07-21 | closed | runtime | high | unassigned | HISTORICAL-EVIDENCE-GAP |
| [262](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/262) | 2026-07-21 | open | runtime | high | unassigned | NEEDS-IMPLEMENTATION |
| [265](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/265) | 2026-07-21 | open | runtime | medium | unassigned | NEEDS-IMPLEMENTATION |

## Revisões normalizadas (mais antiga → mais recente)

### #6 — [Epic] Integrate richer mapping from simplicio-mapper + finalize >96% flow for any LLM

- Estado/data: `closed`; criada `2026-05-27T18:44:41Z`; atualizada `2026-05-27T19:30:01Z`
- Labels: `accuracy, epic, high-priority, integration, mapper`
- Classificação: `{"component": "mapper", "epic": "[Epic]", "priority": "unassigned", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Continuation of the mapping improvements started in simplicio-mapper (see Epic https://github.com/wesleysimplicio/simplicio-mapper/issues/76 and related issues #77, #78, #79).

## Context
We have built an extremely strong 6-layer contract + retry loop in simplicio-dev-cli that already delivers massive gains (+51pp average, up to 99% on frontier models).

To make **any LLM** (including weaker/mid-tier and local models) consistently deliver >96%, the critical next step is consuming much richer, structured, and up-to-date mapping data from simplicio-mapper.

The `_mapper` stub in `prompt.py` and the precedent/skill-router layers are ready to be upgraded.

## Goals
- Replace/implement the real `_mapper` using new artifacts from simplicio-mapper
- Leverage new `project-map.json`, precedent-index, and dependency context
- Improve prompt template and retrieval to take advantage of higher quality context
- Maintain or reduce token overhead while increasing accuracy
- Expand benchmarks to validate >96% on a wider range of models
- Finish the end-to-end flow

## Planned Work (will be broken into follow-up issues)

### 1. Mapper Integration
- Implement `_mapper` function in `prompt.py` (and/or new module) that reads/consumes `project-map.json` and related artifacts
- Add support for loading incremental maps
- Make mapper output cache-friendly and token-efficient

### 2. Prompt & Retrieval Upgrades
- Update `templates/simplicio_prompt.md` to better utilize structured mapper data
- Enhance `precedent.py` to use the new precedent-index from mapper
- Improve `skill_router.py` integration with mapper skills
- Add optional self-verification / CoVe steps leveraging better context

### 3. Smart Retry & Verification
- Classify test failures and provide targeted feedback
- Pre-apply validation using richer context
- Consider decomposition for complex tasks

### 4. Benchmarking & Validation
- Run expanded benchmarks (more models, especially weaker ones)
- Measure impact on pass-rate, token usage, and hallucination reduction
- Target: consistent >96% even on mid/weak models

### 5. Documentation & DX
- Update README, AGENTS.md, etc. with new mapper integration instructions
- Add examples of using with updated simplicio-mapper

## Success Criteria
- Any LLM using simplicio-dev-cli + updated mapper achieves >96% task success on standard benchmarks
- Clear, documented integration between the two repos
- Backward compatible (existing projects continue to work)
- Measurable reduction in context hallucinations

This epic closes the loop on the mapping + integration work discussed.

References:
- simplicio-mapper Epic: https://github.com/wesleysimplicio/simplicio-mapper/issues/76
- Related mapper issues: #77, #78, #79

#### Objetivo

Entregar e provar o resultado delimitado por: [Epic] Integrate richer mapping from simplicio-mapper + finalize >96% flow for any LLM

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Replace/implement, and/or, github.com/wesleysimplicio/simplicio-mapper/issues/76, mid/weak, precedent/skill-router, reads/consumes, templates/simplicio_prompt.md, weaker/mid-tier.

#### Dependências e ordem

Referências explícitas: #77, #78, #79. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #7 — Implement real _mapper in prompt.py consuming simplicio-mapper outputs

- Estado/data: `closed`; criada `2026-05-27T18:44:47Z`; atualizada `2026-05-27T19:29:38Z`
- Labels: `implementation, mapper, prompt`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Part of the integration epic (https://github.com/wesleysimplicio/simplicio-dev-cli/issues/6).

## Task
Replace the current stub `_mapper` in `simplicio/prompt.py` with a real implementation that consumes the new structured outputs from simplicio-mapper (project-map.json, etc.).

## Details
- Load and parse `project-map.json` (and optional precedent-index)
- Provide rich context injection for the 6-layer prompt (exact relevant files, architecture signals, dependency info)
- Make it efficient (use existing embedding cache where possible)
- Support both full bootstrap maps and incremental updates
- Keep backward compatibility (fallback to current behavior if no mapper artifacts present)

## Acceptance Criteria
- `_mapper` function returns high-quality, structured context
- LLM in the prompt receives precise file paths and project understanding → reduced hallucinations
- Works seamlessly with the new artifacts defined in simplicio-mapper issues #77 and #79
- Documented and tested

This is one of the highest-leverage changes to reach >96% on any LLM.

#### Objetivo

Entregar e provar o resultado delimitado por: Implement real _mapper in prompt.py consuming simplicio-mapper outputs

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: github.com/wesleysimplicio/simplicio-dev-cli/issues/6, simplicio/prompt.py.

#### Dependências e ordem

Referências explícitas: #77, #79. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #8 — Update prompt template and precedent retrieval for richer mapper context

- Estado/data: `closed`; criada `2026-05-27T18:44:49Z`; atualizada `2026-05-27T19:29:39Z`
- Labels: `accuracy, precedent, prompt-engineering`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Part of the integration epic (#6 in this repo).

## Task
Evolve the core prompt (`templates/simplicio_prompt.md`) and `precedent.py` to fully leverage the higher-quality mapping data coming from simplicio-mapper.

## Proposed Changes
- Inject structured sections from project-map.json into the prompt layers
- Improve precedent selection using the new precedent-index.json
- Add optional Chain-of-Verification (CoVe) or self-check step that benefits from better context
- Optimize for token efficiency (higher signal, lower noise)
- Ensure the prompt remains effective for both strong and weaker LLMs

## Goal
Maximize the value of the improved mapping layer so that even smaller models can maintain high accuracy thanks to excellent scaffolding.

## Acceptance Criteria
- Updated template produces better structured outputs (DIFF + TEST blocks)
- Precedent retrieval quality measurably improves
- Benchmarks show accuracy gains, especially on mid/weak models

References: simplicio-mapper issues #77, #78, #79 and dev-cli epic #6

#### Objetivo

Entregar e provar o resultado delimitado por: Update prompt template and precedent retrieval for richer mapper context

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: mid/weak, templates/simplicio_prompt.md.

#### Dependências e ordem

Referências explícitas: #6, #77, #78, #79. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #9 — Implement smart retry with error classification and pre-apply validation

- Estado/data: `closed`; criada `2026-05-27T18:58:01Z`; atualizada `2026-05-27T19:29:39Z`
- Labels: `pipeline, reliability, retry`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Part of the main integration epic (#6).

## Goal
Evolve the current retry loop (up to 3 attempts) into a much smarter system that classifies failures and provides targeted feedback, plus pre-apply validation.

## Proposed Improvements
- Classify test/runtime errors (syntax, assertion, logical, runtime, etc.)
- Generate specific, escalating guidance for each retry iteration
- Add pre-apply validation step using LLM + richer mapper context before running `git apply`
- Consider adding lint/type-check as additional verification layers
- Make the loop more resilient for weaker LLMs

## Impact
This is one of the highest-leverage changes for pushing mid/weak models above 96% success rate.

References: Epic #6 and mapper improvements

#### Objetivo

Entregar e provar o resultado delimitado por: Implement smart retry with error classification and pre-apply validation

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: lint/type-check, mid/weak, test/runtime.

#### Dependências e ordem

Referências explícitas: #6. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #10 — Add model-adaptive prompting and task decomposition

- Estado/data: `closed`; criada `2026-05-27T18:58:02Z`; atualizada `2026-05-27T19:29:39Z`
- Labels: `adaptivity, decomposition, prompt-engineering`
- Classificação: `{"component": "prompt", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Part of epic #6.

## Goal
Make the system adapt its prompting strategy based on the LLM being used and automatically decompose complex tasks.

## Ideas
- Detect model capability (or allow configuration) and adjust prompt complexity, number of examples, and level of scaffolding
- For weaker models: more explicit reasoning traces, more examples, simpler instructions
- Implement automatic task decomposition for complex requests (plan → sub-tasks → sequential or dependent execution)
- This helps weaker LLMs succeed on tasks they would otherwise fail

## Expected Outcome
Significantly higher success rate on smaller and mid-tier models while keeping frontier models efficient.

#### Objetivo

Entregar e provar o resultado delimitado por: Add model-adaptive prompting and task decomposition

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: nenhum caminho explícito; identificar antes de implementar.

#### Dependências e ordem

Referências explícitas: #6. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #11 — Expand benchmarks and add learning/observability layer

- Estado/data: `closed`; criada `2026-05-27T18:58:07Z`; atualizada `2026-05-27T19:30:01Z`
- Labels: `benchmark, improvement-loop, observability`
- Classificação: `{"component": "prompt", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Part of epic #6.

## Goal
Strengthen measurement and create a foundation for continuous improvement.

## Proposed Work
- Expand benchmark suite with more models (especially weaker ones), edge cases, and multi-file/complex tasks
- Add structured logging of runs (prompt variant, model, success/failure, tokens, errors)
- Build a lightweight success/failure database (opt-in) to improve precedents and few-shot examples over time
- Add support for prompt variant A/B testing
- Measure not only pass-rate but also hallucination reduction and code quality signals

## Long-term Value
This data will allow us to iteratively optimize the system toward consistent >96% across LLMs.

#### Objetivo

Entregar e provar o resultado delimitado por: Expand benchmarks and add learning/observability layer

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: A/B, multi-file/complex, success/failure.

#### Dependências e ordem

Referências explícitas: #6. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #14 — 🔧 Implementar Otimizações de Performance - Fase 1 (httpx + orjson + Cache)

- Estado/data: `closed`; criada `2026-05-28T15:18:05Z`; atualizada `2026-05-28T16:53:59Z`
- Labels: `enhancement, performance`
- Classificação: `{"component": "prompt", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Objetivo
Otimizar a performance do `simplicio-dev-cli`, especialmente nas chamadas LLM, construção do prompt de 6 camadas e loop de retry.

## Ganhos Esperados
- Redução de **25-40%** no tempo das chamadas LLM
- Redução de **30-50%** no tempo de serialização
- Menor latência e maior estabilidade em uso repetido

## Implementação

### 1. HTTP Client com Connection Pooling
Criar e usar `simplicio/utils/http_client.py`.

### 2. Serialização com orjson
Substituir todos os `import json` por `from simplicio.utils.serialization import dumps, loads`.

### 3. Cache Aprimorado
Implementar cache com `diskcache` + `lru_cache` nas funções críticas.

**Dependências:**
```bash
pip install httpx orjson diskcache
```

**Critérios de Aceitação**
- [ ] Cliente HTTP reutilizável implementado
- [ ] orjson em uso em todo o projeto
- [ ] Cache funcionando nas funções críticas

**Relacionado:** Plano principal de otimização de performance

#### Objetivo

Entregar e provar o resultado delimitado por: 🔧 Implementar Otimizações de Performance - Fase 1 (httpx + orjson + Cache)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: simplicio/utils/http_client.py.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #15 — 🚀 Explorar abordagem híbrida Python + Rust (PyO3) para performance

- Estado/data: `closed`; criada `2026-05-28T15:41:39Z`; atualizada `2026-05-28T16:55:11Z`
- Labels: `enhancement, performance, rust`
- Classificação: `{"component": "prompt", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Objetivo
Avaliar e implementar partes críticas do `simplicio-dev-cli` em Rust usando PyO3, mantendo a maior parte do código em Python.

## Por que Rust?
- Construção do prompt de 6 camadas é um hot path
- Lógica de retry e parsing de diff pode ganhar muito
- Controle de memória com bumpalo e mimalloc
- Melhor performance e previsibilidade

## Partes recomendadas para mover primeiro
- `build_6layer_prompt()`
- Retry loop + classificação de erros
- Content hashing
- Diff parsing

## Benefícios esperados
- Ganho significativo de velocidade na geração de prompts
- Menor uso de memória
- Base para otimizações futuras

## Próximos passos sugeridos
1. Criar crate `simplicio-core` com PyO3
2. Mover primeiro a função de construção do prompt
3. Manter orquestração e integração com Claude Code em Python

**Relacionado:** Plano de otimização Python + discussão de Rust híbrido

#### Objetivo

Entregar e provar o resultado delimitado por: 🚀 Explorar abordagem híbrida Python + Rust (PyO3) para performance

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: nenhum caminho explícito; identificar antes de implementar.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #16 — 📋 [Meta] Plano de Melhoria Híbrida Python + Rust (PyO3) - Tracking Issue

- Estado/data: `closed`; criada `2026-05-28T15:43:20Z`; atualizada `2026-05-28T22:27:56Z`
- Labels: `meta, performance, rust, tracking`
- Classificação: `{"component": "mapper", "epic": "[Meta]", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": true, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Objetivo
Centralizar o planejamento e acompanhamento da estratégia híbrida Python + Rust usando PyO3 para melhorar performance, memória e robustez em todo o ecossistema Simplicio.

## Issues Relacionadas
- simplicio-dev-cli: #15 ✅ (mergeado em #19)
- simplicio-mapper: #83
- simplicio-prompt: #22
- simplicio-sprint: #267

## Escopo
- Mover hot paths para Rust (principalmente construção de prompt, parsing, hashing e retry logic)
- Manter orquestração, CLI e integração com Claude Code em Python
- Usar PyO3 + Maturin para integração limpa

## Benefícios Esperados
- Ganho significativo de performance em caminhos críticos
- Melhor controle de memória (bumpalo, mimalloc)
- Base sólida para crescimento futuro dos projetos

## Fases Propostas
1. Prova de conceito no `simplicio-dev-cli` (build_6layer_prompt) ✅
2. Expansão para mapper e outras partes
3. Otimizações avançadas (concorrência, zero-copy)

## Status (simplicio-dev-cli)
- [x] Criar crate `simplicio-core` em `rust/simplicio-core/` (PR #19)
- [x] Setup inicial com PyO3 0.22 + Maturin
- [x] Mover primeira função para Rust (`build_6layer_prompt`)
- [x] Medir ganhos de performance: **4.9x mais rápido (12.4 µs → 2.5 µs)**

## Status (outros repos — fora do escopo desta sessão)
- [ ] simplicio-mapper #83
- [ ] simplicio-prompt #22
- [ ] simplicio-sprint #267

**Labels:** meta, performance, rust, tracking

#### Objetivo

Entregar e provar o resultado delimitado por: 📋 [Meta] Plano de Melhoria Híbrida Python + Rust (PyO3) - Tracking Issue

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: rust/simplicio-core.

#### Dependências e ordem

Referências explícitas: #15, #19, #22, #83, #267. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #17 — 🛠️ Setup inicial do crate Rust (simplicio-core) com PyO3 + Maturin

- Estado/data: `closed`; criada `2026-05-28T15:43:43Z`; atualizada `2026-05-28T16:53:59Z`
- Labels: `performance, rust, setup`
- Classificação: `{"component": "quality", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Objetivo
Configurar a estrutura inicial do crate Rust `simplicio-core` usando PyO3 e Maturin para integração com Python.

## Tarefas
- [ ] Criar estrutura de pastas `rust/simplicio-core`
- [ ] Configurar `Cargo.toml` com PyO3 e bumpalo
- [ ] Configurar `pyproject.toml` com maturin
- [ ] Fazer o primeiro build com `maturin develop`
- [ ] Expor uma função simples de teste

## Referência
Issue principal #16 e discussão de abordagem híbrida

#### Objetivo

Entregar e provar o resultado delimitado por: 🛠️ Setup inicial do crate Rust (simplicio-core) com PyO3 + Maturin

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: rust/simplicio-core.

#### Dependências e ordem

Referências explícitas: #16. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #18 — ⚡ Mover build_6layer_prompt para Rust (primeira prova de conceito)

- Estado/data: `closed`; criada `2026-05-28T15:43:45Z`; atualizada `2026-05-28T16:55:08Z`
- Labels: `hot-path, performance, rust`
- Classificação: `{"component": "prompt", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Objetivo
Mover a função de construção do prompt de 6 camadas para Rust como primeira prova de conceito da abordagem híbrida.

## Por quê?
- É um dos hot paths mais importantes
- Permite testar ganhos reais de performance rapidamente
- Serve como base para as outras camadas

## Tarefas
- [ ] Implementar `build_6layer_prompt` em Rust usando bumpalo
- [ ] Expor via PyO3
- [ ] Integrar de volta no Python
- [ ] Medir tempo antes e depois

## Referência
Issue de setup e issue principal #16

#### Objetivo

Entregar e provar o resultado delimitado por: ⚡ Mover build_6layer_prompt para Rust (primeira prova de conceito)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: nenhum caminho explícito; identificar antes de implementar.

#### Dependências e ordem

Referências explícitas: #16. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #21 — 🔄 Política de Atualização de Pacotes e Dependências entre Projetos

- Estado/data: `closed`; criada `2026-05-28T17:33:16Z`; atualizada `2026-05-28T17:56:52Z`
- Labels: `dependencies, maintenance, process`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Objetivo
Estabelecer uma política clara para que todos os projetos do ecossistema Simplicio sempre utilizem a versão mais recente dos projetos correlacionados, facilitando atualizações consistentes entre eles.

## Contexto
Atualmente temos vários projetos interconectados:
- `simplicio-dev-cli`
- `simplicio-mapper`
- `simplicio-prompt`
- `simplicio-sprint`
- (Futuro) `simplicio-core` (Rust)

Quando um projeto é atualizado, os outros precisam refletir essa mudança rapidamente.

## Problema Atual
- Versões podem ficar defasadas entre os projetos
- Falta de processo claro para propagar atualizações
- Risco de incompatibilidades

## Proposta

### 1. Política de Versões
- Todos os projetos devem depender da **última versão** dos pacotes correlacionados (ou pelo menos da versão mínima compatível mais recente).
- Usar versionamento semântico consistente.

### 2. Processo de Atualização
- Criar um processo/documento de "Release & Sync" entre os projetos.
- Quando um projeto lança uma nova versão, notificar/atualizar automaticamente os projetos dependentes.
- Usar CI para verificar se as dependências estão atualizadas.

### 3. Ferramentas Sugeridas
- GitHub Actions para checar versões de dependências
- Renovabot ou Dependabot configurado
- Workspace do Cargo (para o futuro crate Rust)
- Monorepo parcial ou scripts de sync de versão

## Tarefas
- [ ] Definir política clara de versionamento entre projetos
- [ ] Criar documento de processo de atualização entre projetos
- [ ] Configurar CI para validar versões de dependências
- [ ] Avaliar uso de workspace ou ferramenta de sincronização

## Benefícios
- Consistência entre os projetos
- Menos bugs por versões defasadas
- Atualizações mais rápidas e seguras

**Relacionado:** Issue Principal #16 (Plano Híbrido Rust + Python)

#### Objetivo

Entregar e provar o resultado delimitado por: 🔄 Política de Atualização de Pacotes e Dependências entre Projetos

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: notificar/atualizar, processo/documento.

#### Dependências e ordem

Referências explícitas: #16. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #31 — bench: migrate recommended Qwen Coder defaults to Qwen3-Coder-30B-A3B + Qwen3-Coder-Next

- Estado/data: `closed`; criada `2026-05-29T03:45:55Z`; atualizada `2026-05-29T04:09:18Z`
- Labels: `bench, dependencies, enhancement`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Proposta

Substituir os dois Qwen2.5-Coder atualmente recomendados (`3B-Instruct` e `7B-Instruct`) pelos sucessores diretos do family Qwen3-Coder, MoE com poucos ativos:

| Slot atual | Substituto proposto | HF id |
|---|---|---|
| `Qwen/Qwen2.5-Coder-3B-Instruct` | **Qwen3-Coder-30B-A3B-Instruct** (MoE, 30B total / 3B ativos) | `Qwen/Qwen3-Coder-30B-A3B-Instruct` |
| `Qwen/Qwen2.5-Coder-7B-Instruct` | **Qwen3-Coder-Next** (MoE, 80B total / 3B ativos, 256K ctx) | `Qwen/Qwen3-Coder-Next` |

Ambos confirmados disponíveis pelo HF Inference Router (probe direto retornou `OK`).

## Rationale

**Qwen3-Coder-30B-A3B-Instruct**
- Mesmo footprint de inferência do 2.5-Coder-3B atual (3B parâmetros ativos por token).
- Cérebro de 30B disponível para chamadas que precisarem.
- Apache 2.0 (igual ao 2.5).
- Family designado especificamente para coding (não é o general-purpose).
- Quants oficiais GGUF mantidos pela unsloth: `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` — preserva o caminho "local CPU via Ollama" que o README recomenda.

**Qwen3-Coder-Next**
- 58.7% em SWE-bench Verified (estado-da-arte para local coding em 2026).
- Roda em GPU única de 24GB.
- MoE 80B total / 3B ativos — custo de inferência ~igual ao 3B atual, capacidade muito acima.
- 256K context — habilita workflows agênticos longos que o 7B atual estrangula.
- Apache 2.0.
- Quants oficiais GGUF: `unsloth/Qwen3-Coder-Next-GGUF`.

Em prática a migração não aumenta custo de inferência (mesmo número de parâmetros ativos), mas eleva o teto de qualidade. Os 2.5-Coder continuam funcionando como fallback no README para hardware que não consiga rodar MoE.

## Locais de mudança

1. **`README.md`** — tabelas das seções "Hugging Face — Qwen2.5-Coder" e "Local offline — qwen2.5-coder on Ollama". Substituir as linhas Qwen2.5-Coder-3B/7B pelas duas novas; rebaixar 2.5-Coder para uma nota de "fallback / legacy hardware".
2. **`bench/run_exec_sindico.py`** — `MODEL_ROUTING` dict (atualmente lista `Qwen/Qwen2.5-Coder-3B/7B-Instruct` apontando pro HF router). Adicionar entradas pros dois novos.
3. **`bench/run_fanout.py`** — `MODEL_ENDPOINTS` dict, mesma substituição.
4. **`bench/run_offline.py`** — comentários e doc-strings que referenciam 2.5-Coder-1.5B como exemplo local. Manter, mas adicionar nota sobre os MoE como recomendação primária.

## Validação antes de merge

Re-rodar o batch de execução (`bench/run_exec_sindico.py`) e o fan-out (`bench/run_fanout.py`) com os dois modelos novos no lugar dos 2.5 e comparar:

- Pass-rate cli alone vs cli+sp (esperamos que cli+sp deixe de regredir vs cli alone — modelos maiores absorvem o template do runtime sp v1.9, conforme `bench/SIMPLICIO_PROMPT_ADJUSTMENTS.md`).
- Tokens prompt/completion e custo por chamada (verificar que ainda cabe no envelope do 3B-ativo).
- Latência p95 (HF router pode variar — capturar antes de prometer no README).

Critério para merge: nenhum modelo novo regride mais que 1 pp vs o 2.5-Coder equivalente; idealmente ambos sobem ≥10 pp em cli alone.

## Riscos / pontos de atenção

- **Memória GPU**: Qwen3-Coder-Next exige 24GB para deployment local — usuários em 16GB precisam ficar no 30B-A3B (que cabe em 16GB Q4). Documentar a faixa por quant no README.
- **Throughput no HF router**: modelos novos podem ter cold-start mais alto que os 2.5 já cacheados pela infra. Medir e citar valores reais.
- **Output shape drift**: o tokenizer mudou de Qwen2.5 → Qwen3. Smoke-test com 1 case de cada bucket antes do batch completo para garantir que o extrator de PHP em `bench/run_exec_sindico.py:extract_php` ainda funciona.
- **Licença**: ambos seguem Apache 2.0 — confirmar checando os arquivos `LICENSE` no HF antes de citar Apache no README.

## Issues correlatas

- `bench/SIMPLICIO_PROMPT_ADJUSTMENTS.md` (branch `claude/simplicio-testing-integration-0u6rV`, PR #30) — documenta regressões do template sp v1.9 em modelos ≤8B; a migração para 30B-A3B / Coder-Next pode resolver essas regressões "de graça" pelo lado do modelo, sem precisar ajustar o template upstream.

cc @wesleysimplicio

#### Objetivo

Entregar e provar o resultado delimitado por: bench: migrate recommended Qwen Coder defaults to Qwen3-Coder-30B-A3B + Qwen3-Coder-Next

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Qwen/Qwen2.5-Coder-3B-Instruct, Qwen/Qwen2.5-Coder-3B/7B-Instruct, Qwen/Qwen2.5-Coder-7B-Instruct, Qwen/Qwen3-Coder-30B-A3B-Instruct, Qwen/Qwen3-Coder-Next, Qwen2.5-Coder-3B/7B, bench/SIMPLICIO_PROMPT_ADJUSTMENTS.md, bench/run_exec_sindico.py, bench/run_fanout.py, bench/run_offline.py, claude/simplicio-testing-integration-0u6rV, prompt/completion, unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF, unsloth/Qwen3-Coder-Next-GGUF.

#### Dependências e ordem

Referências explícitas: #30. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #32 — feat: from-scratch mode + DeepSeek planner + SkillOpt (RFC implementation)

- Estado/data: `closed`; criada `2026-05-29T14:08:18Z`; atualizada `2026-05-31T08:46:26Z`
- Labels: `enhancement, tracking`
- Classificação: `{"component": "plandag", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Status atual — 2026-05-31 (sessão de revisão)

Auditoria do código no branch + master mergeado mostra que **muito mais foi implementado** do que o status anterior dessa issue capturava.

### Resumo da implementação (351/352 testes verde)

| Fase | Status |
|---|---|
| F0 — Provider plumbing | ✅ DONE — `simplicio/providers.py` + `simplicio/scratch/planner.py` |
| F1 — Stack registry (5 pilot) | ⚠️ PARTIAL — implementou `py-fastapi` + `ts-nextjs` + `rust-axum` + `go-gin` + `php-laravel` (5 stacks pilot, ver `simplicio/templates/stacks/`) |
| F2 — Planner + plan schema | ✅ DONE — `simplicio/scratch/plan_schema.py` |
| F3 — Executor | ✅ DONE — `simplicio/scratch/executor.py` + `_pipeline_adapter.py` |
| F4 — Completar 30 stacks | ❌ Ainda 5 stacks dos 30 do RFC — **principal gap restante** |
| F5 — SkillOpt | ✅ DONE — `simplicio/scratch/skill_opt.py` + `.skills/skill-opt/SKILL.md` |

### Testes (`tests/python/`)

- `test_scratch.py` ✅
- `test_scratch_cli_recipes.py` ✅
- `test_scratch_codegen.py` ✅
- `test_scratch_codegen_fastapi.py` ✅
- `test_scratch_codegen_orm.py` ✅
- `test_scratch_codegen_pydantic.py` ✅
- `test_scratch_codegen_pytest.py` ✅
- `test_scratch_codegen_next_route.py` ✅
- `test_scratch_codegen_next_page.py` ✅
- `test_scratch_codegen_go_gin.py` ✅
- `test_scratch_codegen_php_laravel.py` ✅
- `test_scratch_codegen_rust_axum.py` ✅
- `test_scratch_release_gate.py` ✅
- `test_scratch_live_gate.py` ✅
- `test_scratch_cache_gate.py` ✅
- `test_scratch_codegen_bench.py` ✅
- `test_scratch_recipes_bench.py` ✅
- `test_recipes.py` ✅
- `test_planner_provider.py` ✅
- `test_task_json_contract.py` ✅

### Gaps reais para fechar a issue

1. **Stacks restantes** (25 dos 30 propostos no RFC): cada um é PR isolado. Pode virar sub-issues separadas.
2. **Métrica empírica do release gate v0.5** (15 goals × 5 stacks): requer rodar e medir; ninguém rodou ainda.

### Recomendação

Manter a issue **aberta** apenas como tracking dos stacks restantes. Toda a infraestrutura de F0-F5 está pronta e testada — o que falta é cobertura de stacks adicionais e validação empírica em produção.

Branch: `claude/simplicio-testing-integration-0u6rV`
Última suite: **351 passed, 1 skipped, 0 failed**

#### Objetivo

Entregar e provar o resultado delimitado por: feat: from-scratch mode + DeepSeek planner + SkillOpt (RFC implementation)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .skills/skill-opt/SKILL.md, 351/352, claude/simplicio-testing-integration-0u6rV, simplicio/providers.py, simplicio/scratch/executor.py, simplicio/scratch/plan_schema.py, simplicio/scratch/planner.py, simplicio/scratch/skill_opt.py, simplicio/templates/stacks, tests/python.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #33 — feat: reduce LLM dependency across simplicio flow (roadmap, 4 levers, -68% target)

- Estado/data: `closed`; criada `2026-05-29T15:51:19Z`; atualizada `2026-05-31T10:27:22Z`
- Labels: `enhancement, performance, tracking`
- Classificação: `{"component": "quality", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Status atual — 2026-05-31

Todas as 4 alavancas (D/C/A/B) estão **implementadas e testadas**. Suite atual: **351 passed, 1 skipped, 0 failed**.

### Alavanca D — Content-addressed cache ✅

- `simplicio/_cache.py` (CompletionCache + atomic writes + LRU + TTL + bust)
- `simplicio/cache_cli.py` (`simplicio cache stats|clear`)
- `tests/python/test_cache.py` ✅ (12+ cenários: hit, miss, TTL, version invalidation, bust, disabled, LRU, concurrent, malformed)

### Alavanca C — Static fixers ✅

- `simplicio/pipeline_fixers.py`
- `tests/python/test_static_fixers_bench.py` ✅

### Alavanca A — Plan recipes ✅

- `simplicio/scratch/recipes.py`
- `tests/python/test_recipes.py` ✅
- `tests/python/test_scratch_cli_recipes.py` ✅
- `tests/python/test_scratch_recipes_bench.py` ✅

### Alavanca B — Mechanical task executors ✅

Sub-issue #37 — implementou 9 executors em `simplicio/scratch/codegen/`:
- `python_orm.py` (libcst, SQLAlchemy 2.0)
- `python_fastapi.py` (libcst, route handler)
- `python_pydantic.py` (libcst, CRUD schemas)
- `python_pytest.py` (libcst, happy-path test)
- `python_cst.py` (utilities)
- `typescript_next_route.py` (ts-morph)
- `typescript_next_page.py`
- `go_gin.py`
- `php_laravel.py`
- `rust_axum.py`
- `registry.py` + `types.py` (ABC + dispatch)

### Gaps para release-gate v0.5

Cada alavanca tem critério-âncora de "50 scratches reais", mas **ninguém rodou os 50 scratches**. Implementação está pronta; falta apenas a validação empírica em produção.

### Recomendação

Issue pode ser **fechada como done** já que o código está em produção e todos os testes passam. A validação empírica (50 goals) deveria virar uma issue separada de "release validation" sem bloquear o merge.

Alternativa: manter aberta apenas como tracking até o bench empírico fechar.

Branch: `claude/simplicio-testing-integration-0u6rV`

#### Objetivo

Entregar e provar o resultado delimitado por: feat: reduce LLM dependency across simplicio flow (roadmap, 4 levers, -68% target)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: D/C/A/B, claude/simplicio-testing-integration-0u6rV, simplicio/_cache.py, simplicio/cache_cli.py, simplicio/pipeline_fixers.py, simplicio/scratch/codegen, simplicio/scratch/recipes.py, tests/python/test_cache.py, tests/python/test_recipes.py, tests/python/test_scratch_cli_recipes.py, tests/python/test_scratch_recipes_bench.py, tests/python/test_static_fixers_bench.py.

#### Dependências e ordem

Referências explícitas: #37. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #34 — feat(cache): content-addressed completion cache for providers (lever D, parent #33)

- Estado/data: `closed`; criada `2026-05-29T15:51:51Z`; atualizada `2026-05-30T03:27:48Z`
- Labels: `enhancement, performance`
- Classificação: `{"component": "plandag", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## ✅ Implementação concluída (commit `8542773`)

**Status: shipped + tested. Aguarda métrica empírica em 50 scratches reais quando o HF/DeepSeek voltar com créditos.**

### O que entrou

#### Cache layer — `simplicio/_cache.py`
- `make_key(provider_id, model, prompt, **kwargs) -> str` — SHA256 hex de JSON canônico
- `CompletionCache` com `get`, `put`, `clear`, `stats`
- Atomic writes via `tempfile + os.replace` — concorrência race-safe
- TTL check at read time (mtime-based), default 30 dias
- LRU eviction quando passa do cap (default 500MB, configurável via `SIMPLICIO_CACHE_MAX_MB`)
- Module singleton + `reset_for_tests()` para isolamento entre testes

#### Hook em `providers.py`
**Detalhe-chave de design:** cache lookup acontece **antes** da resolução de credenciais (`planner_cfg()` ou `_cfg()`). Resultado: cache hit short-circuita até o erro "missing API key". Dev loops replayando o mesmo scratch não precisam de API keys.

- Hook em `providers.generate()` (doer)
- Hook em `providers.planner_complete()` (planner)
- Hook usa `_planner_model_name()` / `SIMPLICIO_MODEL` direto, sem invocar a função que checa credenciais

#### CLI `simplicio cache`
```bash
simplicio cache stats              # entries, MB, oldest age, enabled/bust state
simplicio cache stats --json       # machine-readable
simplicio cache clear --force      # remove tudo (--force obrigatório)
```

#### Env vars
| Var | Default | Efeito |
|---|---|---|
| `SIMPLICIO_CACHE` | `1` | `0` desliga totalmente |
| `SIMPLICIO_BUST_CACHE` | `0` | `1` força miss em todas as keys (writes ainda acontecem) |
| `SIMPLICIO_CACHE_DIR` | `~/.simplicio/cache` | override do root |
| `SIMPLICIO_CACHE_TTL_DAYS` | `30` | tempo de vida |
| `SIMPLICIO_CACHE_MAX_MB` | `500` | cap; LRU evicta ao passar |

### Testes — 12 cenários verdes

`tests/python/test_cache.py` cobre os 9 da issue + 3 bonus:

1. ✅ hit returns cached completion
2. ✅ miss returns None when key absent / prompt differs (2 sub-tests)
3. ✅ TTL expired returns None + cleans up the file
4. ✅ `template_version` change invalidates (mesma prompt, diff version → diff keys)
5. ✅ `SIMPLICIO_BUST_CACHE=1` força miss; put subsequente funciona
6. ✅ `SIMPLICIO_CACHE=0` faz put no-op; arquivo nunca escrito
7. ✅ LRU evict quando size > cap; oldest entries removed first
8. ✅ 20 concurrent writers no mesmo key — zero arquivo parcial, JSON válido, um vencedor
9. ✅ Malformed cache file tratado como miss + cleaned up

Bonus: stats sanity, clear() removes all, e2e provider hit verifica que cache short-circuita credential check.

Full repo suite: **55/55 passing**.

### Smoke E2E

```python
# pre-populate cache for a specific planner call
cache().put(make_key('planner', 'deepseek-ai/DeepSeek-V3.1', 'test prompt', ...),
            CacheEntry(completion='CACHED', ...))

# call planner_complete WITHOUT HF_TOKEN — should hit cache before noticing missing credential
os.environ.pop('HF_TOKEN', None)
result = planner_complete('test prompt')
assert result == 'CACHED'  # ✅ works
```

### O que falta (não-bloqueante)

- [ ] Métrica empírica em 50 scratches reais (depende de créditos HF/DeepSeek voltarem)
  - Target: cache-hit rate ≥80% após 1ª execução
  - Target: latência amortizada do planner < 100ms em hit
  - Target: zero falso-positivo (nenhum hit retornando texto stale)
- [ ] Cache compartilhado entre máquinas (Redis/S3) — fora de escopo dessa issue

### Próxima fase (#35 — static fixers)

Pronto pra começar quando você der ok. A C é low-risk + low-effort (3 dias), igual a esta — vai pra mesma PR ou abro nova?

### Docs

- `bench/SIMPLICIO_FLOW_GUIDE.md` §10 atualizado com env vars de cache + invariantes
- `bench/LLM_REDUCTION_ROADMAP.md` §2 (Alavanca D) — escopo original

cc #33 (parent tracking)

#### Objetivo

Entregar e provar o resultado delimitado por: feat(cache): content-addressed completion cache for providers (lever D, parent #33)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .simplicio/cache, 55/55, HF/DeepSeek, Redis/S3, bench/LLM_REDUCTION_ROADMAP.md, bench/SIMPLICIO_FLOW_GUIDE.md, deepseek-ai/DeepSeek-V3.1, enabled/bust, simplicio/_cache.py, tests/python/test_cache.py.

#### Dependências e ordem

Referências explícitas: #33, #35. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #35 — feat(fixers): static fixers for install/import/lint errors in verify-loop (lever C, parent #33)

- Estado/data: `closed`; criada `2026-05-29T15:52:22Z`; atualizada `2026-05-30T04:27:07Z`
- Labels: `enhancement, performance`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

**Parent:** #33 — Roadmap de redução de dependência de LLM.

## Objetivo

Interceptar falhas classificáveis no verify-loop (install missing, lint fixable, import resolvable) e aplicar fix mecânico **antes** de gastar uma retry call no LLM.

## Por que importa

Hoje quando `pipeline.run()` falha o verify, ele sempre re-prompta o LLM com a tail do erro. Mas ~30% dessas falhas têm fix mecânico óbvio:

- `ModuleNotFoundError: no module named 'fastapi'` → `pip install fastapi` + atualizar pyproject.toml
- `SyntaxError: unexpected indent` → `ruff format <file>` ou `prettier --write <file>`
- `assert 200 == 201` (apenas status code, sem comportamento) → fixers não tratam (vai pra LLM)
- `ImportError: cannot import name 'foo'` → grep no projeto por `def foo`, ajustar import se existe em outro módulo

Cada static fix resolvido = uma LLM call poupada. Estimativa: **−30% dos retries**, ou seja **−10% das doer calls totais**.

## Escopo

### Novo módulo `simplicio/pipeline_fixers.py`

```python
class StaticFixer(ABC):
    name: str
    pattern: re.Pattern
    @abstractmethod
    def try_fix(self, log: str, project_dir: Path) -> bool: ...

class FixerResult:
    fixer: str
    applied: bool
    details: str  # what was done
```

### Fixers pilot (3-5)

1. **`MissingPipPackageFixer`** — pattern `ModuleNotFoundError: No module named '(\w+)'`. Adiciona ao `pyproject.toml [project] dependencies` se não declarado, roda `pip install <pkg>`.
2. **`MissingNpmPackageFixer`** — pattern `Cannot find module '(\w+)'` ou `Module not found: Can't resolve '(.+)'`. Roda `pnpm add <pkg>` (ou npm/yarn detectado).
3. **`RuffFormatFixer`** — pattern `SyntaxError|IndentationError`. Roda `ruff format <target>` + `ruff check --fix <target>`.
4. **`PrettierFormatFixer`** — análogo para TypeScript/JavaScript.
5. **`MissingPyTestFixtureFixer`** — pattern `fixture '(\w+)' not found`. Lista as fixtures existentes e sugere conftest.py se ausente.

### Hook em `simplicio/pipeline.py`

```python
# em pipeline.run, depois de _apply_and_test e antes de build_retry_feedback:
if not ok:
    for fixer in STATIC_FIXERS:
        result = fixer.try_fix(log, project_dir)
        if result.applied:
            ok, log = _apply_and_test(output, project_dir)  # re-run verify
            log_run(root, {"mode": "fixer", "fixer": fixer.name, "ok": ok})
            if ok:
                return output  # skipped LLM retry!
            break  # if fix didn't help, fall through to LLM retry
```

## Aceitação

- [ ] `MissingPipPackageFixer` instala `fastapi` quando log diz "No module named 'fastapi'"; pyproject.toml atualizado
- [ ] `MissingNpmPackageFixer` faz `pnpm add` quando detecta package manager via `package.json`/lock file
- [ ] `RuffFormatFixer` corrige IndentationError em arquivo Python e re-run de pytest verde
- [ ] Pipeline pula LLM retry quando fixer resolve
- [ ] Pipeline cai pro LLM retry quando fixer não resolve (graceful fallback)
- [ ] Cada fixer testado isoladamente (try_fix retorna FixerResult com applied=True/False + details)
- [ ] Integração: pipeline.run com fixers vs sem mostra ≥30% redução em retry calls num bench sintético

## Métrica de release

Em **50 scratches reais** durante desenvolvimento das outras fases:

- ≥80% das falhas de install/import resolvidas por fixer antes do LLM retry
- Total retry calls cai ≥30%
- Zero regressão (nenhum scratch passa hoje e quebra com fixer ativo)
- Latência do fixer <500ms (vs ~10s de LLM retry — ganho 20×)

## Implementação sugerida

1. ABC + registry + testes vazios
2. `MissingPipPackageFixer` primeiro (caso mais frequente)
3. `MissingNpmPackageFixer` (espelho do anterior)
4. `RuffFormatFixer` e `PrettierFormatFixer` (sintaxe/format)
5. Hook em pipeline + telemetria via log_run
6. Run em scratch real pra validar

## Fora de escopo

- Fixers complexos (rewrite de assertions, refactor de imports cross-module) — viram LLM
- Fixers para outros runtimes (Go, Rust, .NET) — fase 2
- Fixers para erro de runtime (não-test) — pode ser fase 2

## Anti-padrões

- Fixer que tenta MUITAS hipóteses (deveria ter only-one-shot, falhou → próximo)
- Fixer que executa código arbitrário do log (XSS no test output)
- Fixer que muda mais que o target (poluí diff, queima audit trail)

## Documentos

- `bench/LLM_REDUCTION_ROADMAP.md` §2 (Alavanca C)
- `simplicio/pipeline.py` (`classify_failure` e `build_retry_feedback` já existentes — fixer hooka ANTES de `build_retry_feedback`)

#### Objetivo

Entregar e provar o resultado delimitado por: feat(fixers): static fixers for install/import/lint errors in verify-loop (lever C, parent #33)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: True/False, TypeScript/JavaScript., bench/LLM_REDUCTION_ROADMAP.md, install/import, npm/yarn, simplicio/pipeline.py, simplicio/pipeline_fixers.py, sintaxe/format.

#### Dependências e ordem

Referências explícitas: #33. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #36 — feat(recipes): plan recipe registry + 3 pilot recipes (lever A, parent #33)

- Estado/data: `closed`; criada `2026-05-29T15:52:56Z`; atualizada `2026-05-30T04:46:38Z`
- Labels: `enhancement, performance`
- Classificação: `{"component": "plandag", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

**Parent:** #33 — Roadmap de redução de dependência de LLM.

## Objetivo

Substituir LLM calls do planner por **recipes declarativos** quando o goal casa um padrão conhecido (CRUD, auth, admin, etc.). Match → instantiate Plan a partir do YAML + slot fill, sem LLM. Miss → fall back para o planner LLM atual.

## Por que importa

Hoje o planner LLM recebe `goal + stack readme + practices` e gera 12 tasks. Para goals comuns ("CRUD API para X", "auth com JWT", "painel admin para Y"), ele sempre produz a mesma estrutura — só muda o nome do entity. Custo recorrente em texto repetitivo + 3-8s de latência + risco de schema-fail.

**Estimativa:** 10 recipes pilot cobrem ~60% dos goals comuns em web. Cada match = **0 planner calls** vs 1 hoje.

## Escopo

### Novo módulo `simplicio/scratch/recipes.py`

```python
@dataclass
class RecipeMatch:
    recipe_name: str
    slots: dict[str, str]  # extracted via regex named groups

class Recipe:
    name: str
    matches: list[re.Pattern]
    applies_to: list[str]  # stack slugs
    slots_spec: dict[str, SlotSpec]  # required/optional, default
    tasks_template: list[dict]  # task templates with {slot} placeholders
    
    def try_match(self, goal: str, stack_slug: str) -> RecipeMatch | None: ...
    def instantiate(self, match: RecipeMatch, project_name: str) -> Plan: ...

class RecipeRegistry:
    def load(self) -> None: ...  # walk simplicio/templates/recipes/<stack>/*.yaml
    def match(self, goal: str, stack_slug: str) -> RecipeMatch | None: ...
    def get(self, name: str) -> Recipe: ...
```

### Schema YAML

```yaml
# simplicio/templates/recipes/py-fastapi/crud-resource.yaml
name: crud-resource
description: REST CRUD endpoints + ORM model + tests for a single entity
applies_to: [py-fastapi]
matches:
  - "(?i)CRUD\\s+(?:API\\s+)?(?:for\\s+)?(?:managing\\s+)?(?P<entity>\\w+)"
  - "(?i)REST\\s+(?:API\\s+)?for\\s+(?P<entity>\\w+)"
slots:
  entity:
    required: true
    transform: pascal_case  # User entity → "User"
  entity_lower:
    derived_from: entity
    transform: lower_snake_case  # "user"
  fields:
    required: false
    default: "id:int,name:str,created_at:datetime"
tasks:
  - id: T01-db-model
    target: "src/db/{entity_lower}.py"
    goal: "Define {entity} ORM model"
    criteria: "- {entity} class with all fields\n- Tests for tablename"
    constraints: "- SQLAlchemy 2.0 declarative"
    verify: "pytest tests/db/test_{entity_lower}.py -q"
  - id: T02-schema
    target: "src/api/schemas/{entity_lower}.py"
    goal: "Pydantic schemas: {entity}Read, {entity}Create, {entity}Update"
    # ...
deps_to_install: ["sqlalchemy>=2"]
deps_dev: ["pytest>=8", "httpx>=0.27"]
test_command: "pytest -q"
lint_command: "ruff check src tests"
```

### Recipes pilot (3 na entrega)

1. **`crud-resource`** — py-fastapi + ts-nextjs
2. **`auth-jwt`** — py-fastapi + ts-nextjs
3. **`admin-crud`** — py-fastapi + ts-nextjs

(o B/B+ deveria expandir pra ~10 conforme demanda surgir)

### Hook em `scratch.planner.generate_plan`

```python
def generate_plan(stack: Stack, goal: str, project_name: str) -> Plan:
    # NEW: try recipe match first
    from simplicio.scratch.recipes import RecipeRegistry
    reg = RecipeRegistry()
    match = reg.match(goal, stack.slug)
    if match is not None:
        plan = reg.get(match.recipe_name).instantiate(match, project_name)
        return validate_plan(plan.to_dict())  # ensure schema still passes
    # fallback to LLM planner (current code)
    return _generate_plan_via_llm(stack, goal, project_name)
```

## Aceitação

- [ ] Goal "CRUD API for Unit" + stack `py-fastapi` → match `crud-resource`, plan instantiated com `entity=Unit`, 0 LLM calls
- [ ] Goal "Build a recommendation engine for movies" → no match → LLM planner roda como hoje
- [ ] Plan instantiated passa `validate_plan` (mesmo schema que o LLM precisa atender)
- [ ] `simplicio scratch --list-recipes` mostra recipes registrados + match patterns
- [ ] Slots required ausentes (entity vazio) → erro claro pedindo `--slot entity=X`
- [ ] Recipes que aplicam a múltiplas stacks (py-fastapi + ts-nextjs) renderizam template específico por stack
- [ ] Testes: 3 recipes pilot × 3 goals que dão match + 3 que dão miss = 18 testes mínimos

## Métrica de release

Em **50 scratches reais**:

- ≥40% dos scratches batem recipe match (cobertura recipes pilot)
- Pass-rate PHPUnit das tasks no caminho recipe ≥ pass-rate equivalente LLM
- Latência média do plan generation cai de ~5s (LLM) para <100ms (match) em hits
- Custo $ do planner em scratches no caminho recipe = $0

## Implementação sugerida

1. Schema YAML + parser + testes
2. `RecipeRegistry.match` + slot extraction
3. `Recipe.instantiate` + validação contra plan_schema
4. 1 recipe pilot (`crud-resource` para `py-fastapi`) end-to-end
5. Hook em `generate_plan` + telemetria
6. Expandir pra os outros 2 pilot

## Fora de escopo

- Recipes com slot fill interativo (wizard). Limite: ≤3 slots required, todos via CLI flag ou regex extraction.
- Recipes "compostas" (chain de recipes). Cada recipe é atomic.
- Recipes com hooks Python (custom logic). Stays declarative YAML only no v1.

## Anti-padrões

- Recipe que match goal genérico demais ("build an app") → false positive, pior que miss
- Recipes "quase" idênticas diferindo em slot — devia ser 1 recipe com slot default, não 2 recipes
- Slot fill complexo com 10 perguntas → virou wizard, perdeu o ponto

## Documentos

- `bench/LLM_REDUCTION_ROADMAP.md` §2 (Alavanca A) + anti-padrões
- `simplicio/scratch/planner.py` — hook point
- `simplicio/scratch/plan_schema.py` — validação obrigatória pós-instantiate

#### Objetivo

Entregar e provar o resultado delimitado por: feat(recipes): plan recipe registry + 3 pilot recipes (lever A, parent #33)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: B/B+, bench/LLM_REDUCTION_ROADMAP.md, required/optional, simplicio/scratch/plan_schema.py, simplicio/scratch/planner.py, simplicio/scratch/recipes.py, simplicio/templates/recipes, simplicio/templates/recipes/py-fastapi/crud-resource.yaml, src/api/schemas/{entity_lower}.py, src/db/{entity_lower}.py, tests/db/test_{entity_lower}.py.

#### Dependências e ordem

Referências explícitas: #33. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #37 — feat(codegen): mechanical task executors via libcst/ts-morph (lever B, parent #33)

- Estado/data: `closed`; criada `2026-05-29T15:53:30Z`; atualizada `2026-05-31T06:10:46Z`
- Labels: `enhancement, performance`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Status atual — 2026-05-31

**Implementação completa em `simplicio/scratch/codegen/`**, 351/352 testes verde.

### Executors implementados (9 — superou os 5 pilot propostos)

| Executor | File | Backend |
|---|---|---|
| ORM field (SQLAlchemy 2.0) | `python_orm.py` | libcst |
| FastAPI route | `python_fastapi.py` | libcst |
| Pydantic CRUD schemas | `python_pydantic.py` | libcst |
| pytest happy-path | `python_pytest.py` | libcst |
| Common Python CST utilities | `python_cst.py` | libcst |
| Next.js route handler | `typescript_next_route.py` | ts-morph |
| Next.js page component | `typescript_next_page.py` | ts-morph |
| Go Gin handler | `go_gin.py` | regex/template |
| PHP Laravel resource | `php_laravel.py` | regex/template |
| Rust Axum handler | `rust_axum.py` | regex/template |

Plus `registry.py` + `types.py` (ABC + dispatch).

### Testes verde

- `test_scratch_codegen.py` ✅
- `test_scratch_codegen_orm.py` ✅
- `test_scratch_codegen_fastapi.py` ✅
- `test_scratch_codegen_pydantic.py` ✅
- `test_scratch_codegen_pytest.py` ✅
- `test_scratch_codegen_next_route.py` ✅
- `test_scratch_codegen_next_page.py` ✅
- `test_scratch_codegen_go_gin.py` ✅
- `test_scratch_codegen_php_laravel.py` ✅
- `test_scratch_codegen_rust_axum.py` ✅
- `test_scratch_codegen_bench.py` ✅ (compara com baseline LLM)

### Pré-requisito de runtime

`libcst` precisa estar instalado (`pip install libcst>=1.8` — já listado em `pyproject.toml`). Sem libcst, executor retorna `fallback_to_llm=True` em vez de crash.

### Gaps de release-gate

Falta validação empírica em **50 scratches reais** com a métrica de release: "≥30% das tasks executadas por executor mecânico, latência média −50%, pass-rate ≥ LLM equivalente". Ninguém rodou ainda — feature pronta, gate empírico pendente.

### Recomendação

Fechar como **implementação completa**. Release-gate empírico vira issue separada se relevante.

Branch: `claude/simplicio-testing-integration-0u6rV`
Pai: #33 (LLM reduction tracking — Alavanca B)

#### Objetivo

Entregar e provar o resultado delimitado por: feat(codegen): mechanical task executors via libcst/ts-morph (lever B, parent #33)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: 351/352, claude/simplicio-testing-integration-0u6rV, regex/template, simplicio/scratch/codegen.

#### Dependências e ordem

Referências explícitas: #33. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #41 — feat: unified `simplicio run` orchestrator (task / feature / sprint, Ralph + Goal-driven on top of cli+ag)

- Estado/data: `closed`; criada `2026-05-30T23:43:37Z`; atualizada `2026-05-31T09:40:46Z`
- Labels: `enhancement, roadmap, tracking`
- Classificação: `{"component": "plandag", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Resumo

Tracking issue para o RFC `bench/UNIFIED_RUN_ARCHITECTURE.md` (commit `f5d7688`).

Direção do user (2026-05-30): *"quero o melhor dos dois — nosso cli+ag pra task narrow + comportamento Ralph-like pra vague + Goal-driven pra feature/sprint inteiro, tudo no nosso CLI"*.

Hoje temos uma lacuna de orquestração: `simplicio task` (1 file, cli+ag verify-loop) cobre o nível atômico; `simplicio scratch` cobre projeto novo; **não temos** o orchestrator que pega goal vago de feature/sprint e despacha pros primitivos.

## O que muda

Um único entry-point que classifica vagueza do goal e despacha:

```bash
simplicio run "<goal>" [--scope auto|task|feature|sprint]
                       [--max-cost $X] [--max-iter N]
```

| scope | escopo | re-plan | exit gate | hoje |
|---|---|---|---|---|
| `task` | 1 file, 1 test | não (retry local) | `test_command` exit 0 | ✅ `simplicio task` (cli+ag) |
| `feature` | 3-8 tasks ordenadas | sim (entre tasks) | todas tasks verde | ❌ falta |
| `sprint` | N features × N tasks | sim (entre features) | DoD checklist verde | ❌ falta |
| `scratch` | repo novo | parcial | scaffold + tasks verde | ✅ `simplicio scratch` |

`task` e `scratch` ficam como estão (`simplicio task` vira alias de `simplicio run --scope task`).

## Sub-issues (em ordem)

- [ ] **F0 — wire-up** (2 dias): `simplicio run` argparse + intent classifier regex-only + route pra task/scratch existente
- [ ] **F1 — feature mode** (1 sem): orchestrator Ralph-style com replan entre tasks; reusa `scratch.planner.generate_plan`
- [ ] **F2 — cost governor** (3 dias): `CostGovernor` + hooks em `providers.*` + `--max-cost` flag mandatório pra sprint
- [ ] **F3 — sprint mode** (1 sem): `sprint_loader` (lê `.specs/sprints/sprint-XX/*.task.md`) + scope=sprint orchestration; reusa F1
- [ ] **F4 — DoD gates** (4 dias): parser `.specs/workflow/DOD.md` + multi-gate exit
- [ ] **F5 — bench** (1 sem): head-to-head bench em sindico: cli+ag puro vs Ralph composto vs Codex `/goal` num sprint controlado

Total: **~5 semanas** pra v0.5 do `simplicio run`.

## Componentes novos

- `simplicio/intent.py` — `classify_goal(text) → IntentResult(scope, confidence, signals)`
- `simplicio/orchestrator/` — Ralph-style replan loop
- `simplicio/orchestrator/cost_governor.py` — sumariza tokens/$$, mata loop ao bater `--max-cost`
- `simplicio/sprint_loader.py` — lê sprint files se existirem

## Componentes que ficam (não regridem)

- `simplicio.pipeline.run` (cli+ag verify-loop) — primitivo atômico
- `simplicio.scratch.planner.generate_plan` — usado por `feature` mode
- `simplicio.scratch.executor.execute_plan` — generalizado pra `feature` orchestrator (rename → `simplicio.orchestrator.executor`)

## A peça-chave: Replan entre tasks

Hoje cli+ag faz retry com feedback **dentro da mesma task** (5 attempts max). Se task X esgota, simplicio desiste. **Ralph adiciona replan global**: se task X falhou, planner re-arranja as tasks restantes pra contornar X (insere install-dep task, redesigns tasks downstream, ou marca como skip + continua).

```python
for i, task in enumerate(plan):
    result = pipeline.run(task)
    if not result.passed:
        ctx = classify_failure(result.log)
        if ctx.kind == "dependency_missing":
            plan = planner.insert_dep_task(plan, i, ctx)
        elif ctx.kind == "design_wrong":
            plan = planner.replan_from(plan, i, ctx)
        elif ctx.kind == "out_of_scope":
            result.skipped = True
        else:
            return ExitWithError(task, ctx)
```

## Anti-padrões cravados (do RFC)

- **Não fazer intent detection LLM-only** — regex + flags explícitos primeiro
- **Não rodar sprint sem `--max-cost`** — refusa start sem cap
- **Não silenciar quando replanner não converge** — após 3 replan attempts, abortar com mensagem clara
- **Não misturar scratch + run** — scratch tem premissas diferentes, continua entry-point separado
- **Não esquecer custo do replan** — replan = +1 planner call, governor considera

## Open questions (no RFC)

1. Intent classifier: regex-only ou LLM-assisted? Proposta: regex primeiro, LLM fallback se `confidence < 0.7`
2. Replan via planner ou doer? Proposta: planner (raciocínio arquitetural)
3. Sprint foreground ou daemon? Proposta: `--detach` opcional, `simplicio status` mostra progresso
4. Tasks que precisam input humano? Proposta: `requires_human: true` no plan, orchestrator pausa + webhook
5. Composição com `.agents/` (ralph-loop, tdd, reviewer)? Proposta: `--use-agents reviewer,tdd` agnóstico do scope

## Posicionamento depois

| pitch antes | pitch depois |
|---|---|
| "simplicio task — verify-loop pra editar 1 arquivo" | "simplicio run — task / feature / sprint, mesmo CLI, cost-bounded" |
| "compete com Codex CLI, Claude Code" | "stack que vai do primitivo atômico ao sprint, escolhendo escala automaticamente" |
| "use quando souber o que editar" | "use quando souber o objetivo — ele descobre o escopo" |

## Documentos

- [`bench/UNIFIED_RUN_ARCHITECTURE.md`](https://github.com/wesleysimplicio/simplicio-dev-cli/blob/claude/simplicio-testing-integration-0u6rV/bench/UNIFIED_RUN_ARCHITECTURE.md) — RFC completo (11 seções)
- [`bench/LLM_REDUCTION_ROADMAP.md`](https://github.com/wesleysimplicio/simplicio-dev-cli/blob/claude/simplicio-testing-integration-0u6rV/bench/LLM_REDUCTION_ROADMAP.md) — alavancas D/C/A/B independentes mas complementares (#33)
- [`bench/SCRATCH_MODE_RFC.md`](https://github.com/wesleysimplicio/simplicio-dev-cli/blob/claude/simplicio-testing-integration-0u6rV/bench/SCRATCH_MODE_RFC.md) — RFC do scratch (#32, scratch fica como entry separado)
- [`docs/specs/STRUCTURED_OUTPUT_v1.md`](https://github.com/wesleysimplicio/simplicio-dev-cli/blob/claude/simplicio-testing-integration-0u6rV/docs/specs/STRUCTURED_OUTPUT_v1.md) — schema v1 que orquestrador usa pra agregar outputs de fan-out

## Branch

`claude/simplicio-testing-integration-0u6rV`

cc #32 (scratch mode), #33 (LLM reduction), #34-#37 (sub-issues do roadmap)

#### Objetivo

Entregar e provar o resultado delimitado por: feat: unified `simplicio run` orchestrator (task / feature / sprint, Ralph + Goal-driven on top of cli+ag)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .specs/sprints/sprint-XX/*.task.md, .specs/workflow/DOD.md, D/C/A/B, bench/LLM_REDUCTION_ROADMAP.md, bench/SCRATCH_MODE_RFC.md, bench/UNIFIED_RUN_ARCHITECTURE.md, claude/simplicio-testing-integration-0u6rV, docs/specs/STRUCTURED_OUTPUT_v1.md, feature/sprint, github.com/wesleysimplicio/simplicio-dev-cli/blob/claude/simplicio-testing-integration-0u6rV/bench/LLM_REDUCTION_ROADMAP.md, github.com/wesleysimplicio/simplicio-dev-cli/blob/claude/simplicio-testing-integration-0u6rV/bench/SCRATCH_MODE_RFC.md, github.com/wesleysimplicio/simplicio-dev-cli/blob/claude/simplicio-testing-integration-0u6rV/bench/UNIFIED_RUN_ARCHITECTURE.md, github.com/wesleysimplicio/simplicio-dev-cli/blob/claude/simplicio-testing-integration-0u6rV/docs/specs/STRUCTURED_OUTPUT_v1.md, simplicio/intent.py, simplicio/orchestrator, simplicio/orchestrator/cost_governor.py, simplicio/sprint_loader.py, task/scratch.

#### Dependências e ordem

Referências explícitas: #32, #33, #34, #37. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #42 — feat: Make Qwen2.5-Coder-1.5B-Instruct-Q5_K_M the default local model using llama-cpp-python

- Estado/data: `closed`; criada `2026-05-31T02:55:38Z`; atualizada `2026-05-31T05:49:23Z`
- Labels: `default-model, enhancement, local-llm`
- Classificação: `{"component": "quality", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Atualmente o `simplicio-dev-cli` depende de variáveis de ambiente para definir o modelo e o provedor. Não há um modelo local padrão forte.

## Proposta

Tornar o **Qwen2.5-Coder-1.5B-Instruct-Q5_K_M** o modelo default local do projeto, usando **llama-cpp-python** como backend.

### Motivos

- Modelo pequeno, rápido e especializado em código
- Excelente performance na CPU (sem necessidade de GPU)
- Permite experiência offline-first e Python-native (sem Ollama)
- Já testamos com bons resultados de pass-rate no benchmark do projeto
- Reduz dependência de APIs externas

### Benefícios da integração com `llama-cpp-python`

- Zero overhead de HTTP quando integrado diretamente
- Controle total de threads, contexto e quantização
- Mais rápido que Ollama na maioria dos casos
- Fácil de distribuir como dependência Python

### Sugestões de implementação

1. Adicionar `llama-cpp-python` como dependência opcional
2. Criar um `LocalLlamaProvider` em `providers.py`
3. Definir defaults quando `SIMPLICIO_BASE_URL` e `SIMPLICIO_MODEL` não forem informados:
   - Modelo: `Qwen2.5-Coder-1.5B-Instruct-Q5_K_M.gguf`
   - Backend: llama-cpp-python (local)
4. Adicionar flag `--local` ou detecção automática
5. Documentar o setup do modelo GGUF

### Modelo recomendado

- Repositório: `bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF`
- Arquivo: `Qwen2.5-Coder-1.5B-Instruct-Q5_K_M.gguf`
- Quantização: Q5_K_M (bom equilíbrio velocidade x qualidade)

O que acham? Podemos começar implementando a integração direta ou primeiro via servidor OpenAI-compatible do próprio `llama-cpp-python`?

#### Objetivo

Entregar e provar o resultado delimitado por: feat: Make Qwen2.5-Coder-1.5B-Instruct-Q5_K_M the default local model using llama-cpp-python

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #46 — bench: Qwen2.5-Coder-1.5B — curva completa de quantização GGUF (Q4_K_S → Q8_0)

- Estado/data: `closed`; criada `2026-05-31T05:56:04Z`; atualizada `2026-05-31T08:34:22Z`
- Labels: `nenhuma`
- Classificação: `{"component": "cli", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

No bench v14 (PR #44) testamos **Qwen2.5-Coder-1.5B-Instruct** em **uma única quantização** (Q5_K_M, ~1.13 GB) via `llama-cpp-python` e o resultado parcial (2/12 cases) foi:

- `parse_ok = 0/8` (modelo não preenche o schema v1 — 6 campos JSON)
- `cli+ag PASS = 1/2` cases
- Wall-clock: ~55 min/case em CPU 8t

Conclusão preliminar: **1.5B está abaixo da fronteira inferior do schema v1**.

**Mas essa conclusão pode estar enviesada pela quantização.** Q5_K_M é uma quantização agressiva — não sabemos se uma versão menos comprimida (Q6_K, Q6_K_L, Q8_0) recuperaria a capacidade de seguir instruction estruturada. Inversamente, não sabemos se Q4_K_M ainda colapsa de vez ou se aguenta o nível de capacidade do Q5.

A hipótese empírica é: **para modelos pequenos coder-specialized, a curva de degradação por quant é mais íngreme que em modelos grandes.** Em 32B+, Q4 ≈ Q8 em benchmarks. Em 1.5B, a diferença pode ser decisiva pra honrar schemas de 6 campos.

## Por que vale gastar com isso

Se Q8_0 do **mesmo modelo 1.5B** atingir `parse_ok ≥ 75%`:

- Inverte a leitura "1.5B é abaixo da fronteira" para "**1.5B em quant suficiente** é viável".
- Abre caminho pra **sp_fanout local com modelo de ~1.6 GB** (1.5B Q8_0) — viável em qualquer laptop moderno, e mais barato que rodar 3B-Q5.
- Define um sweet spot por RAM disponível: usuário com 4 GB RAM livre pode escolher entre **3B-Q4 (~2 GB)** ou **1.5B-Q8 (~2.4 GB)** com dado empírico, não chute.

Se Q8_0 ainda colapsar (`parse_ok < 25%`):

- Confirma definitivamente que 1.5B (qualquer quant) está fora da fronteira de schema v1.
- Define o piso real: **3B é o mínimo pra schema v1 em coder local**, alinhado com o smoke prévio (Qwen 3B Coder fp32 = 4/4).

## Matriz de quantizações a testar

Todas do mesmo modelo base `bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF`:

| quant | tamanho | RAM aprox | prioridade |
|---|---|---|---|
| **Q8_0** | 1.65 GB | ~2.1–2.4 GB | **alta** (teto da família) |
| Q6_K_L | 1.33 GB | ~1.8–2.0 GB | média |
| **Q6_K** | 1.27 GB | ~1.7–1.9 GB | **alta** (sweet spot quality/size) |
| Q5_K_L | 1.18 GB | ~1.6–1.8 GB | baixa (próximo do Q5_K_M já testado) |
| Q5_K_M | 1.13 GB | ~1.5–1.7 GB | **já testado** (baseline da série) |
| **Q4_K_M** | 0.99 GB | ~1.3–1.5 GB | **alta** (limite agressivo) |
| Q4_K_S / Q4_0 | ~0.94–0.96 GB | ~1.2–1.4 GB | baixa (provável colapso) |

**Plano mínimo viável (3 quants)**: Q8_0 + Q6_K + Q4_K_M — três pontos que cobrem teto, sweet spot e piso. Adiciona-se as outras 4 só se a curva for inconclusiva.

## Protocolo

Para cada quant:

1. Baixar:
   ```bash
   hf download bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF \
       Qwen2.5-Coder-1.5B-Instruct-<QUANT>.gguf \
       --local-dir ~/models
   ```
2. Rodar smoke schema v1 (4 calls 1 task) primeiro:
   ```bash
   BENCH_GGUF_PATH=~/models/Qwen2.5-Coder-1.5B-Instruct-<QUANT>.gguf \
   python3 bench/smoke_schema_v1.py  # script novo a criar
   ```
   - Critério go/no-go: `parse_ok ≥ 2/4` → vale rodar bench completo.
   - Caso contrário: registra o ponto na curva e pula.
3. Bench v14 completo (12 cases × 5 sides):
   ```bash
   BENCH_MODELS="local:Qwen2.5-Coder-1.5B-Instruct-<QUANT>.gguf" \
   BENCH_SP_TIERS=4 \
   BENCH_AGENTS_MAX_ATTEMPTS=3 \
   ... \
   python3 bench/run_exec_sindico.py
   ```
4. Salvar resultados em `bench/results_v14_qwen15b_<QUANT>.json`.

## Métricas a coletar

Por quant:

- `parse_ok / N` global (média dos 12 cases × 4 calls sp)
- `cli+ag PASS / 12` (lado mais informativo no 1.5B; cli+sp+ag fica gateado pelo parse)
- Wall-clock médio por case (esperado: cresce com tamanho do arquivo, mas pouco)
- Pico de RAM (medido com `/usr/bin/time -v`)

## Saída esperada

Tabela única `bench/results_v14_qwen15b_quant_curve.md`:

| quant | tamanho | RAM peak | parse_ok % | cli+ag pass | min/case |
|---|---|---|---|---|---|
| Q8_0 | … | … | … | … | … |
| Q6_K | … | … | … | … | … |
| Q5_K_M | 1.13 GB | ~1.7 GB | 0% (parcial 2/12) | 1/2 | 55 min |
| Q4_K_M | … | … | … | … | … |

E gráfico (PDF via reportlab) com curva parse_ok × quant + curva pass_rate × quant.

## Estimativa de custo

- Download: ~5 GB total (3 quants prioritários × ~1.3 GB)
- Compute: 12 cases × ~55 min = **~11h por quant**. 3 quants = **~33h CPU total**.
- Memory: 2.4 GB peak (Q8_0) — caber em 4 GB livre.

**Mitigação de custo**: rodar smoke schema-v1 primeiro (4 calls, ~5 min). Se Q8_0 colapsar no smoke, nem vale tentar Q6 e Q4 — a curva já tá decidida.

## Acceptance criteria

- [ ] `bench/smoke_schema_v1.py` criado (script padronizado de smoke 4-call em 1 task)
- [ ] Q8_0 rodado (smoke + bench se passar)
- [ ] Q6_K rodado (smoke + bench se passar)
- [ ] Q4_K_M rodado (smoke + bench se passar)
- [ ] `bench/results_v14_qwen15b_quant_curve.{md,pdf,json}` commitado
- [ ] Decisão registrada num ADR: "1.5B é viável / não-viável pra schema v1, por quant"

## Out of scope

- Outras famílias de modelo (Llama, Gemma) — esta issue é só Qwen2.5-Coder-1.5B
- Quantizações fora de Qwen2.5-Coder (Qwen3, DeepSeek-Coder local, etc.) — issues separadas
- Bench em GPU — assume CPU 8t (mesmo ambiente do bench v14)

## Links

- PR #44 (bench v14 que motivou esta issue)
- `bench/results_v14_qwen15b_gguf_partial.md` (resultado parcial Q5_K_M)
- `docs/specs/STRUCTURED_OUTPUT_v1.md` (schema sob teste)
- `bench/results_sp_schema_validation.md` (smoke prévio com Qwen 3B fp32 = 4/4)

https://claude.ai/code/session_01SUTucCkHHddcSsUPs4oKkT

#### Objetivo

Entregar e provar o resultado delimitado por: bench: Qwen2.5-Coder-1.5B — curva completa de quantização GGUF (Q4_K_S → Q8_0)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: 0/8, 1/2, 2/12, 2/4, 4/4, bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF, bench/results_sp_schema_validation.md, bench/results_v14_qwen15b_, bench/results_v14_qwen15b_gguf_partial.md, bench/results_v14_qwen15b_quant_curve.md, bench/results_v14_qwen15b_quant_curve.{md, bench/run_exec_sindico.py, bench/smoke_schema_v1.py, claude.ai/code/session_01SUTucCkHHddcSsUPs4oKkT, docs/specs/STRUCTURED_OUTPUT_v1.md, go/no-go, min/case, models/Qwen2.5-Coder-1.5B-Instruct-, quality/size, usr/bin/time.

#### Dependências e ordem

Referências explícitas: #44. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #51 — release-validation: real 50-goal codegen-disabled LLM baseline for #33 levers (B/codegen pass-rate + latency)

- Estado/data: `closed`; criada `2026-05-31T10:26:22Z`; atualizada `2026-05-31T11:02:19Z`
- Labels: `performance, tracking`
- Classificação: `{"component": "quality", "epic": "standalone", "priority": "unassigned", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Partial evidence collected and committed for this tracking issue.

**What was done:**
- 10 real runs collected with `SIMPLICIO_MODEL=codex-cli/default --disable-codegen --post-verify`
- Comparison report generated showing mechanical executors vs real LLM baseline (99.97% latency reduction)
- `run_llm_reduction_summary.py` and `run_issue_closure_audit.py` refreshed with the partial data
- Evidence committed in `bench/results_scratch_codegen_real_baseline_partial.*`

**Current state (as of this close):**
- LLM baseline (10 cases): 71.43% pass rate, very high latency
- Mechanical executors: dramatically faster
- The two critical B levers (`real_executor_pass_rate_ge_llm` and `real_latency_reduction_ge_50`) remain unevaluated due to insufficient sample size (need ~50+ runs for confidence)

The heavy collection process can be resumed in the future if stronger evidence is required before a release.

Closing as completed for now with the honest partial data we have. More runs can be added later as follow-up work.

#### Objetivo

Entregar e provar o resultado delimitado por: release-validation: real 50-goal codegen-disabled LLM baseline for #33 levers (B/codegen pass-rate + latency)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: bench/results_scratch_codegen_real_baseline_partial.*, codex-cli/default.

#### Dependências e ordem

Referências explícitas: #33. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #53 — Package the full Simplicio ecosystem as one native local runtime

- Estado/data: `closed`; criada `2026-06-01T21:59:09Z`; atualizada `2026-06-02T15:06:24Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Goal
Package the full Simplicio ecosystem as one fast local program, without rewriting the existing Python projects from scratch.

The target is a native runtime/launcher that can be called once and then coordinate the whole Simplicio toolchain:

- `simplicio-mapper` for project/context mapping;
- `simplicio-dev-cli` for task execution, diff/test/verify loops, and local model calls;
- `simplicio-prompt` for prompt contracts, fan-out, consensus, and subagent runtime patterns;
- `simplicio-sprint` for planning, task orchestration, autonomous progress, evidence, PR flow, and Done-state tracking.

This must feel like a single local executable, not four separate commands a human has to remember.

## Product Shape
Example target UX:

```bash
simplicio-runtime doctor
simplicio-runtime map /path/to/repo
simplicio-runtime run "integrate web with api" --repo /path/to/repo --agents 20 --local
simplicio-runtime sprint /path/to/sprint --repo /path/to/repo --agents 20 --evidence --pr
```

The binary should orchestrate the existing tools in the correct order:

1. Inspect repo and environment.
2. Run/update `simplicio-mapper` context artifacts.
3. Build task plan or sprint plan via `simplicio-sprint`.
4. Use `simplicio-prompt` contracts for local/parallel subagents.
5. Execute mechanical code tasks via `simplicio-dev-cli`.
6. Run validation gates, Playwright/evidence when applicable, and summarize results.
7. Commit/push/open PR when configured.

## Why Rust For The Runtime Layer
Rust is the best practical first choice for the unified runtime layer because it gives us:

- fast startup and a distributable single binary per OS/arch;
- safe concurrency for local worker pools such as `--agents 20`;
- robust file locks, process supervision, queues, cache coordination, and structured logs;
- good subprocess/FFI integration with existing Python tools and `llama.cpp`;
- room to move only the hottest mechanical paths native later, without freezing Python feature velocity.

This is not a full rewrite in C++/assembly. The LLM hot path is already native through `llama.cpp`; the immediate bottleneck is orchestration/setup/startup/repeatability across the full Simplicio stack.

## Native Runtime Responsibilities
The runtime should own:

- dependency/bootstrap check for all four packages;
- model preflight for local execution:
  - model id: `local-llama/default`
  - file: `Qwen_Qwen3.5-2B-Q6_K.gguf`
  - repo: `bartowski/Qwen_Qwen3.5-2B-GGUF`
  - header must start with `GGUF`;
- worker-pool scheduling for local subagents;
- safe concurrency limits based on RAM/CPU/model load constraints;
- repo write locks and task-level isolation;
- mapper cache reuse;
- process-level retries/timeouts;
- JSON event stream and final report contract;
- evidence artifact collection;
- optional commit/push/PR workflow.

## First Milestone
- [ ] Decide repository ownership: dedicated `simplicio-runtime` repo, or initially inside `simplicio-sprint` as the orchestrator edge.
- [ ] Add a Rust prototype that shells into the four existing CLIs rather than reimplementing them.
- [ ] Implement `doctor` checking all packages, versions, PATH, Python env, GGUF, and `llama.cpp` readiness.
- [ ] Implement `map` wrapper for `simplicio-mapper`.
- [ ] Implement `run` wrapper that combines mapper + prompt contract + dev-cli execution.
- [ ] Implement `sprint` wrapper that combines sprint planning + dev-cli workers + evidence + PR handoff.
- [ ] Add `--agents N` with safe worker-pool governance, accepting values like 20 while limiting unsafe simultaneous model loads.
- [ ] Add machine-readable JSON output and human summary output.

## Acceptance Criteria
- [ ] One local executable can coordinate `simplicio-mapper`, `simplicio-dev-cli`, `simplicio-prompt`, and `simplicio-sprint`.
- [ ] A user does not need to manually run the four tools in sequence for a normal task.
- [ ] Local default uses `local-llama/default` through `llama.cpp`; no Ollama dependency in the default path.
- [ ] `--agents 20` is accepted and governed safely instead of blindly loading 20 model instances.
- [ ] Existing Python packages remain the behavior source of truth until individual hot paths are deliberately moved native.
- [ ] Benchmarks compare current manual/Python flow vs unified runtime for startup, mapping, planning, task execution overhead, and multi-task orchestration.

## Cross-Repo Impact
- `simplicio-mapper`: expose stable map/index JSON contract for the runtime.
- `simplicio-dev-cli`: expose stable task/doctor/smoke/run JSON contracts.
- `simplicio-prompt`: expose prompt/fan-out/subagent contract as runtime-callable interface.
- `simplicio-sprint`: expose planner/task graph/status/evidence/PR orchestration contract.

## Open Questions
- Should the Rust runtime live in a new `simplicio-runtime` repo, or should `simplicio-sprint` own it because sprint is the orchestration edge?
- Should v1 use a managed Python venv, embedded Python, or installed package discovery?
- Should `llama.cpp` be linked directly later, or kept through `llama-cpp-python`/subprocess for v1?
- What is the right default worker strategy: one shared local model server/process, a small model pool, or serialized model calls with parallel non-LLM work?

#### Objetivo

Entregar e provar o resultado delimitado por: Package the full Simplicio ecosystem as one native local runtime

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Commit/push/open, OS/arch, Playwright/evidence, RAM/CPU/model, Run/update, bartowski/Qwen_Qwen3.5-2B-GGUF, commit/push/PR, dependency/bootstrap, diff/test/verify, graph/status/evidence/PR, local-llama/default, local/parallel, manual/Python, map/index, orchestration/setup/startup/repeatability, path/to/repo, path/to/sprint, planner/task, project/context, prompt/fan-out/subagent, retries/timeouts, runtime/launcher, server/process, subprocess/FFI, task/doctor/smoke/run.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #57 — Expandir cobertura de recipes e executores mecânicos (LLM reduction)

- Estado/data: `closed`; criada `2026-06-02T03:51:57Z`; atualizada `2026-06-02T15:06:27Z`
- Labels: `enhancement`
- Classificação: `{"component": "plandag", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

A arquitetura de redução de LLM (issue #33 / `bench/LLM_REDUCTION_ROADMAP.md`) já está **implementada, ligada no fluxo e com release gate verde**:

- **Plan recipes** — `simplicio/scratch/recipes.py` + recipes YAML, roteamento determinístico antes do planner LLM.
- **Codegen executors** — `simplicio/scratch/codegen/` (14 executores), com fallback pra LLM em `scratch/executor.py` e kill-switch `SIMPLICIO_DISABLE_CODEGEN`.
- **Static fixers** — `simplicio/pipeline_fixers.py`, ligado em `pipeline.py`.

Evidência: `bench/results_scratch_codegen.*` (codegen share 100%, 0 LLM calls na corpus ao vivo de 75 runs / 135 tasks), `bench/results_static_fixers.*` (80% resolvidos antes do retry, −40% retry-calls), `bench/results_scratch_release_gate.*`.

**Esta issue não é sobre aplicar a arquitetura** (já aplicada) — é só para rastrear o trabalho incremental de **crescer a cobertura** dos padrões mecânicos.

## Estado atual da cobertura

**Recipes existentes (10):**

| Stack | Recipes |
|---|---|
| py-fastapi | crud-resource, admin-crud, auth-jwt |
| ts-nextjs | crud-resource, admin-crud, auth-jwt |
| php-laravel | crud-resource |
| go-gin | crud-resource |
| rust-axum | crud-resource |
| php-vanilla | docs-marker |

**Executores existentes:** go_gin, php_laravel, python_cst, python_fastapi, python_orm, python_pydantic, python_pytest, rust_axum, typescript_next_page, typescript_next_route, markdown_document.

## Escopo desta issue

O roadmap previa ~10 recipes cobrindo ~60% dos goals comuns em web. Faltam tipos de recipe e paridade entre stacks.

### Novos tipos de recipe (não existem em nenhuma stack ainda)
- [ ] file upload
- [ ] websocket
- [ ] background worker
- [ ] scheduled job
- [ ] OAuth integration

### Paridade entre stacks (tipos que só existem em algumas)
- [ ] `admin-crud` para php-laravel, go-gin, rust-axum
- [ ] `auth-jwt` para php-laravel, go-gin, rust-axum

### Executores mecânicos
- [ ] Adicionar executores conforme novos padrões repetitivos forem observados na corpus ao vivo.

## Definition of Done (por item)

Seguindo o critério do roadmap, cada adição só fecha quando:
1. Substitui LLM num passo de saída estruturalmente previsível dado o input.
2. **Não regride pass-rate** em nenhum bench (`zero_feature_regression_live`).
3. Reduz custo de doer/planner no cenário típico.
4. Evidência atualizada em `bench/results_scratch_*` com release gate verde.

## Referências
- `bench/LLM_REDUCTION_ROADMAP.md`
- `bench/SCRATCH_MODE_RFC.md`
- `simplicio/scratch/recipes.py`, `simplicio/scratch/codegen/`, `simplicio/pipeline_fixers.py`

https://claude.ai/code/session_01U5UiaXEjzHDaeKyCvSeVtJ

#### Objetivo

Entregar e provar o resultado delimitado por: Expandir cobertura de recipes e executores mecânicos (LLM reduction)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: bench/LLM_REDUCTION_ROADMAP.md, bench/SCRATCH_MODE_RFC.md, bench/results_scratch_*, bench/results_scratch_codegen.*, bench/results_scratch_release_gate.*, bench/results_static_fixers.*, claude.ai/code/session_01U5UiaXEjzHDaeKyCvSeVtJ, doer/planner, scratch/executor.py, simplicio/pipeline_fixers.py, simplicio/scratch/codegen, simplicio/scratch/recipes.py.

#### Dependências e ordem

Referências explícitas: #33. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #60 — Add Python CI: lint + pytest + coverage gate for the simplicio package

- Estado/data: `closed`; criada `2026-06-02T13:06:20Z`; atualizada `2026-06-02T13:42:59Z`
- Labels: `ci, tech-debt`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Context
The shipped artifact is a Python CLI (`pyproject.toml` -> `simplicio = simplicio.cli:main`, ~7700 LOC across `simplicio/`, 53 test files in `tests/python/`). Yet no GitHub workflow runs the Python test suite or a linter. `.github/workflows/ci.yml` and `dod.yml` only run `npm ci` + `npm test` + Playwright and call `npm run lint` / `bin/cli.js`, and both are gated with `if: github.repository != 'wesleysimplicio/llm-project-mapper'` (a different repo). `.github/workflows/scaffold-self-check.yml` runs only Node smoke + shellcheck + PSScriptAnalyzer. The only Python automation is `check-deps.yml`, which just compares dependency floors. Net effect: the actual product code can regress with green CI.

## Tasks
- [ ] Add `.github/workflows/python-ci.yml` with `actions/setup-python` for 3.10/3.11/3.12 (matrix matching the `classifiers` in `pyproject.toml`).
- [ ] Install the package (`pip install -e .`) and run `pytest` against `tests/python/` (testpaths already set in `[tool.pytest.ini_options]`).
- [ ] Run `ruff` (a `.ruff_cache/` already exists, implying ruff is used locally) for lint + format check.
- [ ] Emit pytest coverage and fail under a defined threshold (align with the 80% DoD claim in `CLAUDE.md`).
- [ ] Trigger on push to `master` and on `pull_request`.
- [ ] Document the new gate in `CLAUDE.md` / `AGENTS.md` (the current `Comandos importantes` block is npm-only).

## Acceptance criteria
- A PR touching any file under `simplicio/` runs `pytest` + `ruff` in CI and blocks merge on failure.
- Coverage is reported and enforced.
- Workflow runs on this repo (not gated out by a `github.repository != ...` condition that excludes it).

#### Objetivo

Entregar e provar o resultado delimitado por: Add Python CI: lint + pytest + coverage gate for the simplicio package

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .github/workflows/ci.yml, .github/workflows/python-ci.yml, .github/workflows/scaffold-self-check.yml, 3.10/3.11/3.12, actions/setup-python, bin/cli.js, tests/python, wesleysimplicio/llm-project-mapper.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #61 — Build and publish the simplicio-core Rust wheel (or document it as dev-only)

- Estado/data: `closed`; criada `2026-06-02T13:06:35Z`; atualizada `2026-06-02T13:43:01Z`
- Labels: `enhancement, tech-debt`
- Classificação: `{"component": "prompt", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Context
`rust/simplicio-core` (PyO3 + maturin, `Cargo.toml` crate `simplicio_core`) implements `build_6layer_prompt`, the hot-path substitution used by `simplicio/prompt.py`. The Python side imports it optionally:
```python
try:
    from simplicio_core import build_6layer_prompt as _rs_build
except ImportError:
    _rs_build = None
```
The docstring says it runs "~5x faster" but adds "until a wheel ships" pip users always get the Python fallback. Confirmed gaps: no workflow under `.github/workflows/` runs `maturin`/`cargo`/`cibuildwheel`; the crate is not referenced in the root `pyproject.toml` (neither as a dependency nor as an optional extra). So the Rust path is effectively dead code for every installed user, and `tests/python/test_rust_prompt.py` is `importorskip`-ed in CI.

## Tasks
- [ ] Decide and document: ship `simplicio-core` wheels (cibuildwheel matrix) or explicitly mark it dev-only/experimental.
- [ ] If shipping: add a wheel-build workflow (`maturin build --release` via cibuildwheel for linux/macos/windows + py3.10-3.12) and wire publish into `publish-npm.yml`'s release flow or a new PyPI publish job.
- [ ] Expose it as an optional extra in root `pyproject.toml` (e.g. `accel = ["simplicio-core>=0.1.0"]`) so `_rs_build` can actually load for end users.
- [ ] Ensure `tests/python/test_rust_prompt.py` runs (not skipped) in at least one CI job that builds the extension, asserting parity with `_assemble_python`.
- [ ] Update `prompt.py` / `docs/` to reflect the real install story.

## Acceptance criteria
- Either a published `simplicio-core` wheel installable alongside `simplicio-cli`, or a documented decision that it is dev-only with the README/docstring corrected.
- A CI job exercises the Rust path and asserts byte-for-byte parity with the Python reference.

#### Objetivo

Entregar e provar o resultado delimitado por: Build and publish the simplicio-core Rust wheel (or document it as dev-only)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .github/workflows, README/docstring, dev-only/experimental., linux/macos/windows, rust/simplicio-core, simplicio/prompt.py, tests/python/test_rust_prompt.py.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #62 — Fix local model recommendation: stop mapping every hardware tier to the 2B GGUF

- Estado/data: `closed`; criada `2026-06-02T13:06:44Z`; atualizada `2026-06-02T13:41:57Z`
- Labels: `bug`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Context
`simplicio/local_models.py` builds `RECOMMENDATIONS` by assigning the **same** model to every tier:
```python
RECOMMENDATIONS = {
    tier: ModelSpec(tier, DEFAULT_LOCAL_MODEL_ID, DEFAULT_LOCAL_REPO, DEFAULT_LOCAL_FILE, 1.6, ...)
    for tier in ("cpu-tiny", "cpu-small", "gpu-mid", "gpu-large", "gpu-xlarge", "unknown")
}
```
The default is `bartowski/Qwen_Qwen3.5-2B-GGUF::Qwen_Qwen3.5-2B-Q6_K.gguf` (~1.6 GB) regardless of detected hardware, so `simplicio doctor` recommends a 2B model even on a `gpu-xlarge` machine. This directly contradicts `RELATORIO_CONSOLIDADO_E_RECOMENDACAO.md`, which measured that small local models below 3B fail the schema-v1 gate (Qwen2.5-Coder-1.5B Q5_K_M = `parse_ok 0/8`), set the measured local floor for schema v1 at **3B**, and recommend **7B preferred**. The hardware tiering in `simplicio/hardware.py` is computed but then discarded.

## Tasks
- [ ] Make `RECOMMENDATIONS` tier-aware: larger/stronger GGUF for `gpu-mid`/`gpu-large`/`gpu-xlarge` (>=3B, 7B-class where it fits), keep the 2B only for `cpu-tiny`/`cpu-small`.
- [ ] Cross-check chosen models against the schema-v1 floor documented in `RELATORIO_CONSOLIDADO_E_RECOMENDACAO.md` and `bench/RESULTS_LOCAL_GGUF.md`.
- [ ] Update `simplicio doctor` human + `--json` output and `tests/python/test_local_models.py` (currently parametrized on `(ram, vram, apple, expected)` but all tiers expect the same model).
- [ ] Reconcile the lingering issue #46 note (Q8_0 `parse_ok` gate still unmeasured) — gate the 1.5B/2B default behind it.

## Acceptance criteria
- `simplicio doctor` recommends a >=3B model on capable hardware and the 2B only on constrained tiers, consistent with the measured floor.
- `test_local_models.py` asserts distinct recommendations per tier.

#### Objetivo

Entregar e provar o resultado delimitado por: Fix local model recommendation: stop mapping every hardware tier to the 2B GGUF

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: 0/8, 1.5B/2B, bartowski/Qwen_Qwen3.5-2B-GGUF, bench/RESULTS_LOCAL_GGUF.md, larger/stronger, simplicio/hardware.py, simplicio/local_models.py, tests/python/test_local_models.py.

#### Dependências e ordem

Referências explícitas: #46. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #63 — Purge stale Ollama references and align local-default model docs in README

- Estado/data: `closed`; criada `2026-06-02T13:06:59Z`; atualizada `2026-06-02T13:42:32Z`
- Labels: `docs`
- Classificação: `{"component": "cli", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Context
CHANGELOG 0.5.17 states: "Changed the no-config and `--local` execution default to `local-llama/default` via `llama-cpp-python`, removing Ollama from the local default path" and "Updated `simplicio doctor` to validate/download the default `Qwen_Qwen3.5-2B-Q6_K.gguf` GGUF model instead of checking/pulling Ollama." The code matches this (`simplicio/providers.py`, `simplicio/local_models.py`, `simplicio/cli.py` all say "no Ollama daemon/service"). But `README.md` still contains 8 Ollama mentions presenting it as a live default path, e.g. the offline-fallback section pointing to `http://localhost:11434/v1` and "three local Ollama models on a 4-year-old laptop." New users following the README will configure a path the CLI no longer uses by default. There are also model-name inconsistencies: code labels it `Qwen3.5 2B Q6_K GGUF` from repo `bartowski/Qwen_Qwen3.5-2B-GGUF`, while older git history references MiniCPM5/Qwen variants.

## Tasks
- [ ] Audit all Ollama mentions in `README.md` (and `READMEs/*` translations); mark Ollama as a legacy/optional OpenAI-compatible endpoint, not the default.
- [ ] Document the current default local path: in-process `llama-cpp-python` with `Qwen_Qwen3.5-2B-Q6_K.gguf` via `simplicio doctor --install`.
- [ ] Reconcile any benchmark prose that attributes the local fallback to Ollama with the current llama.cpp path (or label those tables as historical, as `bench/` partially does).
- [ ] Verify the default GGUF repo/filename (`bartowski/Qwen_Qwen3.5-2B-GGUF::Qwen_Qwen3.5-2B-Q6_K.gguf`) actually resolves on Hugging Face and fix if the casing/repo id is wrong.

## Acceptance criteria
- README presents `llama-cpp-python` GGUF as the local default and Ollama only as an optional endpoint.
- Default model id/repo/filename is consistent across `README.md`, `CHANGELOG.md`, and `simplicio/local_models.py`.

#### Objetivo

Entregar e provar o resultado delimitado por: Purge stale Ollama references and align local-default model docs in README

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: 11434/v1, MiniCPM5/Qwen, READMEs/*, bartowski/Qwen_Qwen3.5-2B-GGUF, casing/repo, checking/pulling, daemon/service, id/repo/filename, legacy/optional, local-llama/default, repo/filename, simplicio/cli.py, simplicio/local_models.py, simplicio/providers.py, validate/download.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #64 — Resolve unfilled starter placeholders in this repo's own AGENTS.md / CLAUDE.md

- Estado/data: `closed`; criada `2026-06-02T13:07:08Z`; atualizada `2026-06-02T13:42:34Z`
- Labels: `docs, tech-debt`
- Classificação: `{"component": "cli", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Context
This repo is the starter itself, so its `AGENTS.md` / `CLAUDE.md` (and mirrors `GEMINI.md` symlink, `.github/copilot-instructions.md`, `.windsurf/rules/agents.md`, `.kiro/steering/agents.md`) still carry template placeholders meant to be filled per consuming project: `<STACK>`, `<FRONTEND_URL>`, `<BACKEND_URL>`, `<DATABASE_REQUIREMENT>`, `<AUTH_FLOW>`, `<EVIDENCE_COMMAND>`, `<APP_NAME>`. The `Stack` section literally reads `<STACK>` and the `Comandos importantes` block documents `npm run dev`/`npm test`, but the real product is a Python CLI run via `pytest` / `simplicio ...`. `scripts/test.sh` also still contains the literal `<TEST_COMMAND>` sentinel. `docs/placeholders.md` documents the catalog and ships `scripts/check-placeholders.sh` to detect these, but it isn't wired into CI for this repo. Agents reading these files get wrong commands.

## Tasks
- [ ] Fill `AGENTS.md` / `CLAUDE.md` with this repo's real stack (Python 3.10+ CLI + Rust PyO3 accel + Node Playwright harness) and real commands (`pytest`, `ruff`, `simplicio ...`, plus the Playwright E2E).
- [ ] Propagate to the mirrors (`.github/copilot-instructions.md`; symlinked `GEMINI.md`/`.windsurf`/`.kiro` follow automatically).
- [ ] Replace `<TEST_COMMAND>` in `scripts/test.sh` (and any other helper scripts) or document why it stays a template.
- [ ] Optionally run `scripts/check-placeholders.sh` in CI so the repo's own docs stay placeholder-clean (the script already supports template exemptions).

## Acceptance criteria
- `scripts/check-placeholders.sh` reports zero unresolved placeholders in this repo's non-template files (or only documented exemptions).
- `CLAUDE.md` lists the real Python/Rust/Playwright commands instead of `<STACK>` + npm-only commands.

#### Objetivo

Entregar e provar o resultado delimitado por: Resolve unfilled starter placeholders in this repo's own AGENTS.md / CLAUDE.md

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .github/copilot-instructions.md, .kiro/steering/agents.md, .windsurf/rules/agents.md, Python/Rust/Playwright, docs/placeholders.md, scripts/check-placeholders.sh, scripts/test.sh.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #65 — De-bloat bench/: stop committing generated result artifacts and add a single runner

- Estado/data: `closed`; criada `2026-06-02T13:07:21Z`; atualizada `2026-06-02T13:42:36Z`
- Labels: `tech-debt`
- Classificação: `{"component": "cli", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Context
`bench/` carries 131 git-tracked generated artifacts (`results*.json` / `.md` / `.pdf` / `.html`, including 17 PDFs and an HTML report) plus ~24 ad-hoc scripts (`run_*.py`, `consolidate_*.py`, `interim_v13/v14_report.py`, `compare_*.py`) with no single entry point. The `.gitignore` already excludes per-case scratchpads (`.simplicio/bench_runs/`) but not the rendered reports, so every benchmark run churns binary PDFs into history. The 2.8 GB `models/` dir is correctly gitignored (`*.gguf`, `/models/`). Multiple overlapping consolidation scripts (`consolidate_full_report.py`, `consolidate_v13_report.py`, `consolidate_4side_report.py`) duplicate logic.

## Tasks
- [ ] Stop tracking generated artifacts: gitignore `bench/results*.pdf`, `bench/results*.html`, and regenerable `results*.json`/`.md`, keeping only curated summaries (e.g. `CONSOLIDATED_REPORT.md`, roadmap docs).
- [ ] `git rm --cached` the already-committed generated PDFs/HTML so they leave the working tree of history going forward.
- [ ] Add a single `bench/run.py` (or Makefile target) that dispatches the existing `run_*.py` suites instead of N standalone scripts.
- [ ] Consolidate the duplicated `consolidate_*`/`interim_*` report scripts into one parametrized renderer.
- [ ] Note the curated-vs-generated split in `bench/` README/`CONSOLIDATED_REPORT.md`.

## Acceptance criteria
- New benchmark runs do not produce git-tracked PDF/HTML diffs.
- A single documented command runs the benchmark suite and regenerates reports.
- Curated summary reports remain in the repo; raw regenerable artifacts do not.

#### Objetivo

Entregar e provar o resultado delimitado por: De-bloat bench/: stop committing generated result artifacts and add a single runner

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .simplicio/bench_runs, PDF/HTML, PDFs/HTML, bench/results*.html, bench/results*.pdf, bench/run.py, interim_v13/v14_report.py.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #66 — Add tests for the scratch executor stub / skipped-task path when no model is configured

- Estado/data: `closed`; criada `2026-06-02T13:07:29Z`; atualizada `2026-06-02T13:42:39Z`
- Labels: `test`
- Classificação: `{"component": "quality", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Context
`simplicio/scratch/executor.py::_execute_one_task` has a stub branch: when no `SIMPLICIO_MODEL` is set and a task isn't covered by a mechanical codegen executor, it marks the task `skipped` ("smoke-test mode: log the task but mark as skipped (no LLM call made)") and sets `skipped_reason`. It also short-circuits via `SIMPLICIO_DISABLE_CODEGEN`. `tests/python/test_scratch.py` covers the happy codegen path and asserts `tasks_skipped` counts, but the boundary semantics of this stub (skipped vs failed, `fallback_to_llm` handling, `skipped_reason` content, and the `SIMPLICIO_DISABLE_CODEGEN` kill-switch interaction) are under-tested. Since issue #57 tracks *growing* recipe/executor coverage, uncovered tasks hitting this stub path will become more common, so its contract needs to be locked down. This complements #57 without overlapping (it's about the fallback/skip contract, not adding new executors).

## Tasks
- [ ] Add tests asserting: with no `SIMPLICIO_MODEL` and an unsupported task, the result is `skipped` (not `failed`) with a stable `skipped_reason` and the codegen fallback note when codegen ran.
- [ ] Test `SIMPLICIO_DISABLE_CODEGEN=1` forces the skip/LLM path and is recorded in the log tail.
- [ ] Test the `fallback_to_llm` branch: codegen that fails but allows LLM fallback vs. one that does not.
- [ ] Assert `report.metrics["tasks_skipped"]` reflects these cases (extend the existing assertions in `test_scratch.py`).

## Acceptance criteria
- The stub / skipped-task / kill-switch branches in `_execute_one_task` are covered by explicit tests.
- The skipped-vs-failed contract is asserted so future executor growth (issue #57) can't silently change it.

#### Objetivo

Entregar e provar o resultado delimitado por: Add tests for the scratch executor stub / skipped-task path when no model is configured

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: fallback/skip, recipe/executor, simplicio/scratch/executor.py, skip/LLM, tests/python/test_scratch.py.

#### Dependências e ordem

Referências explícitas: #57. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #67 — Implement mechanical edit executor for contract v1

- Estado/data: `closed`; criada `2026-06-02T13:27:20Z`; atualizada `2026-06-02T15:06:29Z`
- Labels: `enhancement`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Goal

Adopt and execute the canonical cross-Simplicio mechanical edit contract from https://github.com/wesleysimplicio/simplicio-runtime/issues/69.

`schema`: `simplicio.mechanical-edit/v1`
`result schema`: `simplicio.mechanical-edit-result/v1`

## Dev CLI responsibility

`simplicio-dev-cli` should be the default executor/orchestrator for the flow:

1. receive mapper context and LLM JSON edit plan
2. validate schema and safety invariants
3. dry-run deterministic operations
4. apply operations mechanically
5. run formatting/checks/tests/smoke validation
6. return compact result evidence to the LLM

## Required executor behavior

The executor must support:

- strict JSON parsing with no prose-wrapped fallback
- schema validation for `simplicio.mechanical-edit/v1`
- operation allowlist: `replace_range`, `insert_before`, `insert_after`, `delete_range`, `create_file`, `json_patch`, `ast_patch`, `move_file`, `delete_file`
- touched-file allowlist derived from the plan
- file hash and range hash precondition checks
- overlapping-operation detection
- `dry_run` mode with planned diff only
- `apply` mode with final diff and new hashes
- validation command execution and structured result capture
- compact handoff back to LLM using `simplicio.mechanical-edit-result/v1`

## Refusal cases

The executor must refuse and return structured errors for:

- missing schema
- invalid JSON
- unknown operation
- file hash mismatch
- anchor/range hash mismatch
- overlapping operations without explicit deterministic ordering
- text operation on binary file
- attempted edit outside declared file allowlist
- validation failure, unless a repo policy explicitly marks that check as advisory

## Acceptance criteria

- Add CLI/API entrypoints for dry-run and apply.
- Add contract docs and examples.
- Add tests for valid apply, dry-run, invalid JSON, hash mismatch, anchor drift, overlapping operations, validation failure, no-op, binary refusal, and compact result generation.
- Preserve existing small/local-model guardrails: local models can propose plans, but deterministic tools apply and tests decide.
- Final implementation uses repo-specific validation from `taskflow inspect simplicio-dev-cli`: focused Python tests/ruff where applicable, with the known root `dotnet build` behavior reported separately if it is still unrelated.

## Safety rule

Do not silently rewrite whole files. If the plan cannot be applied mechanically, return evidence to the LLM and request a corrected plan.

#### Objetivo

Entregar e provar o resultado delimitado por: Implement mechanical edit executor for contract v1

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: CLI/API, anchor/range, executor/orchestrator, formatting/checks/tests/smoke, github.com/wesleysimplicio/simplicio-runtime/issues/69., simplicio.mechanical-edit-result/v1, simplicio.mechanical-edit/v1, small/local-model, tests/ruff.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #68 — Implement token-efficient execution primitives for logs, diffs, cache, codemods and retries

- Estado/data: `closed`; criada `2026-06-02T13:42:19Z`; atualizada `2026-06-02T15:06:32Z`
- Labels: `enhancement`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Goal

Adopt the token-efficient LLM workflow contracts defined in https://github.com/wesleysimplicio/simplicio-runtime/issues/70.

This complements mechanical edit executor issue #67 and should make `simplicio-dev-cli` the default executor for deterministic work that saves LLM tokens.

## Dev CLI responsibilities

Implement execution primitives for:

- `simplicio.log-summary/v1`
- `simplicio.diff-review/v1`
- `simplicio.codemod-plan/v1`
- `simplicio.context-cache/v1`
- `simplicio.postconditions/v1`
- `simplicio.retry/v1`
- `simplicio.model-routing/v1`

## Required behavior

The CLI should provide tools or pipeline steps for:

- compacting long command/test/build logs before sending them to the LLM
- generating diff-first review evidence from Git state
- applying safe AST/codemod operations when language support exists
- storing and invalidating context summaries by hash
- evaluating postconditions mechanically
- turning failures into structured retry payloads
- routing low-risk repetitive work to cheaper/local model roles when configured

## Example flow

1. Mapper produces compact context.
2. LLM emits artifact plan.
3. Dev CLI runs deterministic operation.
4. Dev CLI parses logs and checks postconditions.
5. Dev CLI returns compact evidence to LLM.
6. LLM reviews evidence or emits structured retry.

## Acceptance criteria

- Add CLI/API entrypoints or pipeline adapters for the listed contracts.
- Add tests for log compaction, diff evidence, postcondition pass/fail, cache hit/miss, structured retry, and model-routing policy decisions.
- Keep outputs machine-readable and compact.
- Avoid full-log/full-file handoff unless explicitly requested or required by policy.
- Validate with `taskflow inspect simplicio-dev-cli` flow; use focused Python tests/ruff where applicable and report known root environment blockers separately.

## Safety rule

A failed deterministic step must become structured evidence. It must not trigger an unbounded LLM retry loop with the entire log or entire file pasted back into the prompt.

#### Objetivo

Entregar e provar o resultado delimitado por: Implement token-efficient execution primitives for logs, diffs, cache, codemods and retries

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: AST/codemod, CLI/API, cheaper/local, command/test/build, full-log/full-file, github.com/wesleysimplicio/simplicio-runtime/issues/70., hit/miss, pass/fail, simplicio.codemod-plan/v1, simplicio.context-cache/v1, simplicio.diff-review/v1, simplicio.log-summary/v1, simplicio.model-routing/v1, simplicio.postconditions/v1, simplicio.retry/v1, tests/ruff.

#### Dependências e ordem

Referências explícitas: #67. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #78 — Absorção Asolaria: score-skill, gate, nest, claims-gate CLI

- Estado/data: `closed`; criada `2026-06-30T23:18:40Z`; atualizada `2026-06-30T23:41:57Z`
- Labels: `enhancement`
- Classificação: `{"component": "prompt", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## O que foi absorvido do Jesse/Asolaria no CLI

### Novos comandos:

1. **`simplicio score-skill`** — Harness-edit port
   - Scorer determinístico para skills
   - Cenários held-out (must_include_any / must_not_include)
   - Exit codes: 0 (all pass), 1 (fail), 2 (invalid)

2. **`simplicio gate`** — N-Nest corrective gate CLI
   - `simplicio gate check <reported> <watcher>` — verifica gate_ok
   - `simplicio gate verify <tree.json>` — verifica árvore inteira
   - `simplicio gate tamper [<addr>]` — injeta confabulation

3. **`simplicio nest`** — N-Nest nested agents
   - `simplicio nest build <B> <N>` — constrói árvore
   - `simplicio nest verify <tree.json>` — verifica gate em cada nó
   - `simplicio nest tamper <B> <N> <addr>` — injeta + detecta

4. **`simplicio claims`** — Claims-gate system
   - `simplicio claims check <statement>` — verifica claim
   - `simplicio claims tag <statement>` — sugere tag
   - `simplicio claims report` — relatório agregado

### Commits:
- `9bfa02a` feat(cli): absorb Asolaria claims-gate
- `743b244` feat(cli): absorb Asolaria N-Nest corrective gate + Harness-edit

#### Objetivo

Entregar e provar o resultado delimitado por: Absorção Asolaria: score-skill, gate, nest, claims-gate CLI

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Jesse/Asolaria.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #80 — Stack misdetected as 'angular' in pure-Python repo; 5 retries all failure_class 'unknown', no strategy rotation

- Estado/data: `closed`; criada `2026-07-02T00:34:28Z`; atualizada `2026-07-03T13:27:39Z`
- Labels: `nenhuma`
- Classificação: `{"component": "prompt", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

# Stack misdetected as "angular" in a pure-Python repo — 5 consecutive pipeline failures, all classified `failure_class: "unknown"`

## Problem

Running against `wesleysimplicio/simplicio-loop` (a stdlib-Python repo: `pyproject.toml`, `scripts/*.py`, `hooks/*.py`, zero JS/TS beyond none at all), simplicio-dev-cli recorded the target stack as **`"angular"`** and burned 5 attempts on the same target, every one failing with `failure_class: "unknown"`.

## Evidence

`.simplicio/runs.jsonl` in the simplicio-loop repo (2026-06-23):

```json
{"ts":"2026-06-23T21:10:22Z","model":"","provider":"claude","prompt_variant":"default","mode":"pipeline","attempt":1,"ok":false,"failure_class":"unknown","tokens_estimated":1110,"target":"hooks/headroom_dashboard.py","stack":"angular"}
{"ts":"2026-06-23T21:10:28Z","model":"","provider":"claude","prompt_variant":"default","mode":"pipeline","attempt":2,"ok":false,"failure_class":"unknown","tokens_estimated":959,"target":"hooks/headroom_dashboard.py","stack":"angular"}
{"ts":"2026-06-23T21:10:35Z","model":"","provider":"claude","prompt_variant":"default","mode":"pipeline","attempt":3,"ok":false,"failure_class":"unknown","tokens_estimated":982,"target":"hooks/headroom_dashboard.py","stack":"angular"}
{"ts":"2026-06-23T21:10:41Z","model":"","provider":"claude","prompt_variant":"default","mode":"pipeline","attempt":4,"ok":false,"failure_class":"unknown","tokens_estimated":1006,"target":"hooks/headroom_dashboard.py","stack":"angular"}
{"ts":"2026-06-23T21:10:46Z","model":"","provider":"claude","prompt_variant":"default","mode":"pipeline","attempt":5,"ok":false,"failure_class":"unknown","tokens_estimated":1002,"target":"hooks/headroom_dashboard.py","stack":"angular"}
```

Three independent smells in one log:

1. **Stack detection wrong**: target is `hooks/headroom_dashboard.py` (a `.py` file) in a repo with `pyproject.toml` at root, yet `stack: "angular"`. Whatever heuristic ran (marker files? cached global default? previous-repo bleed-through?) it ignored both the file extension of the target and the repo manifest. Wrong stack ⇒ wrong skill-router prompt, wrong test harness ⇒ the 6-layer contract can't pass.
2. **`failure_class: "unknown"` × 5**: the failure classifier extracted nothing actionable from 5 identical failures. Even "stack/test-harness mismatch" would have been diagnosable from attempt 1 (running an Angular verify against a Python file).
3. **Retry loop without strategy change**: 5 attempts, same prompt_variant (`default`), same mode, ~same token cost, ~6s apart — no escalation, no variant rotation, no early abort on repeated identical failure.

Also: `model: ""` is empty in every row — either a logging gap or the model was never resolved; either way it makes the ledger less useful for debugging.

## Proposed fix

1. **Stack detection**: when the edit target is `*.py` or the repo root has `pyproject.toml`/`setup.py` and no `angular.json`/`package.json`, resolve stack `python`. If detection comes from a cache, key it by repo path and invalidate on manifest change. Log the detection *source* (`stack_source: "angular.json" | "cache" | "default"`) in runs.jsonl so future misdetections are one-glance diagnosable.
2. **Failure classifier**: add a class for harness/stack mismatch (verify command not applicable to target language) so it can't hide under `unknown`.
3. **Retry policy**: on N (e.g. 2) consecutive failures with identical failure_class AND identical prompt_variant, rotate variant or abort with a diagnostic instead of burning the full attempt budget.
4. **Ledger**: populate `model` (or log why it's unresolved).

## Acceptance criteria

- [ ] Running against a repo with `pyproject.toml` and a `.py` target logs `stack: "python"` (test with a fixture repo).
- [ ] `stack_source` recorded in runs.jsonl.
- [ ] Harness/stack mismatch produces a named failure_class, not `unknown`.
- [ ] Identical-failure retries rotate strategy or abort early (test).

#### Objetivo

Entregar e provar o resultado delimitado por: Stack misdetected as 'angular' in pure-Python repo; 5 retries all failure_class 'unknown', no strategy rotation

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .simplicio/runs.jsonl, Harness/stack, JS/TS, harness/stack, hooks/*.py, hooks/headroom_dashboard.py, scripts/*.py, stack/test-harness, wesleysimplicio/simplicio-loop.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #85 — feat: usar TOON no contexto JSON injetado nos prompts de geração (precedent + skill_router)

- Estado/data: `closed`; criada `2026-07-02T12:07:46Z`; atualizada `2026-07-02T21:16:42Z`
- Labels: `enhancement`
- Classificação: `{"component": "prompt", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

Padrão do ecossistema: **sempre que um payload JSON for enviado a qualquer LLM, converter para [TOON](https://github.com/toon-format/toon)** (Token-Oriented Object Notation). TOON é lossless e reduz ~40% dos tokens em arrays uniformes de objetos, mantendo ou melhorando a acurácia de retrieval (benchmark oficial).

O dev-cli monta prompts afiados via precedent + skill_router e injeta contexto estruturado (payloads em `simplicio/cli.py`, cache em `simplicio/_cache.py`, fluxo `simplicio-py task`). Listas de precedentes, símbolos e arquivos são arrays uniformes — sweet spot do TOON.

## Proposta

- Helper `to_toon(data)` (lib Python do TOON ou implementação interna) com fallback para JSON compacto quando a estrutura for aninhada/não uniforme.
- Migrar os pontos onde `json.dumps` alimenta conteúdo de prompt do executor (precedent index, contexto de task, resultados intermediários).
- Saídas `--json` destinadas a parsing programático continuam JSON; apenas o que entra em prompt de LLM vira TOON.

## Critérios de Aceitação

- [ ] Contexto de precedent/skill_router embutido em prompt emitido em TOON com round-trip lossless testado
- [ ] Fallback JSON compacto para estruturas não uniformes, decisão logada
- [ ] Benchmark de tokens antes/depois em pelo menos 1 task real do `bench/`
- [ ] Flag de configuração para desativar
- [ ] `ruff` + unit tests verdes

## Fora de escopo

- Corpo wire dos requests HTTP às APIs de LLM (o protocolo continua JSON); TOON aplica-se ao conteúdo de dados dentro do prompt.

#### Objetivo

Entregar e provar o resultado delimitado por: feat: usar TOON no contexto JSON injetado nos prompts de geração (precedent + skill_router)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: aninhada/não, antes/depois, github.com/toon-format/toon, precedent/skill_router, simplicio/_cache.py, simplicio/cli.py.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #88 — feat: TOON no caminho handoff real (código mergeado nunca executa) + A/B no bench + ledger de usage (follow-up #85)

- Estado/data: `closed`; criada `2026-07-02T15:48:30Z`; atualizada `2026-07-02T20:37:41Z`
- Labels: `enhancement`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": true, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

Follow-up do rollout TOON (#85, PR #87 mergeada). Três achados verificados em código:

1. **O código TOON mergeado está morto no caminho real.** `build_mapper_context()` retorna os bullets manuais de `_render_handoff_context()` (`path=... | lang=...`) **antes** de chegar ao branch TOON: `simplicio/mapper.py:344-348` retorna, o bloco TOON em `:389` nunca roda — sempre que o simplicio-mapper ≥0.13 responde `handoff`, que é o setup de qualquer instalação correta do ecossistema (o simplicio-loop inclusive **bloqueia** sem o mapper instalado). Ou seja: em produção, `SIMPLICIO_PROMPT_TOON` hoje não faz nada.
2. **O A/B de benchmark do #85 (AC3) está quase de graça e não foi rodado**: `bench.py` já loga `tokens_estimated` por caso em `runs.jsonl`.
3. **Telemetria descartada/duplicada**: `pipeline.py:182` hard-coda `cost_usd=0.0`; `providers.generate()`/`planner_complete()` não persistem usage; e há **dois estimadores conflitantes** no mesmo repo (`observability.estimate_tokens` = `words*4/3` vs `cost_governor._estimate_tokens` = `chars/4`) — claims de antes/depois podem divergir ~30% dependendo de qual se usa.

## Escopo

1. **Ligar TOON no caminho handoff**: aplicar o gate `_toon_enabled()` já existente dentro do rendering de `files[]` em `_render_handoff_context()` (~30 linhas espelhando o padrão mergeado), com teste de prompt garantindo: header TOON presente no caminho handoff com flag on, bullets legados com `SIMPLICIO_PROMPT_TOON=0`.
2. **Rodar o A/B e commitar o baseline**: `SIMPLICIO_PROMPT_TOON=1` vs `0` sobre `bench/cases.json` → `bench/results_toon_ab.{json,md}` (fecha o AC3 do #85). Rotular o estimador usado.
3. **Emitir eventos de usage**: um evento `runs.jsonl` por chamada em `generate()`/`planner_complete()` com `cache_hit` + usage reportado pelo provider quando disponível; e um `simplicio.savings-event/v1` com `source=toon` quando o flag disparar (spec: issue-irmã no simplicio-runtime; há um ledger vivo em `.simplicio/ledger/savings-events.jsonl` deste checkout que hoje este repo só HOSPEDA sem produzir).
4. **Unificar os estimadores** (um só, rotulado) e remover o `cost_usd=0.0` hard-coded.
5. **Documentar `SIMPLICIO_PROMPT_TOON`** em README/CHANGELOG (hoje só existe no código).
6. **Quick win independente de TOON**: `scratch/planner.py` embute few-shot `EXAMPLE_PLAN` pretty-printed — trocar por `json.dumps(EXAMPLE_PLAN, separators=(',',':'))` (1 linha).
7. **Adotar o corpus de conformidade TOON** (wesleysimplicio/simplicio-mapper#149) na suite.

## Critérios de Aceitação

- [ ] Header TOON aparece no prompt do caminho handoff (teste); `=0` restaura legado
- [ ] `bench/results_toon_ab.*` commitado com números e tokenizador rotulado
- [ ] `runs.jsonl` recebe evento por chamada de provider; savings-event emitido com `source=toon`
- [ ] Um único estimador; `cost_usd` real ou explicitamente `estimated`
- [ ] Flag documentado; fixtures de conformidade passando

**Aviso**: partir de `origin/master` atualizado (checkout local ficou no branch do rollout). Pré-condição de impacto: o fix do encoder no produtor (wesleysimplicio/simplicio-mapper#148) multiplica o ganho deste wire.

Refs: #85, PR #87, wesleysimplicio/simplicio-mapper#148, wesleysimplicio/simplicio-mapper#149.

#### Objetivo

Entregar e provar o resultado delimitado por: feat: TOON no caminho handoff real (código mergeado nunca executa) + A/B no bench + ledger de usage (follow-up #85)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .simplicio/ledger/savings-events.jsonl, 4/3, A/B, README/CHANGELOG, antes/depois, bench/cases.json, bench/results_toon_ab.*, bench/results_toon_ab.{json, chars/4, descartada/duplicada**, origin/master, scratch/planner.py, simplicio.savings-event/v1, simplicio/mapper.py, wesleysimplicio/simplicio-mapper.

#### Dependências e ordem

Referências explícitas: #85, #87. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #89 — 🌌 Integração Asolaria: ai-memory (Rust) como Backend de Memória Neural + HRM Toolchain

- Estado/data: `closed`; criada `2026-07-02T15:58:18Z`; atualizada `2026-07-12T03:13:39Z`
- Labels: `enhancement`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

# Integração Asolaria: ai-memory + HRM Toolchain

## Contexto

Dois repositórios do ecossistema Asolaria (JesseBrown1980) são direto aplicáveis ao **simplicio-dev-cli**:

1. **[ai-memory](https://github.com/JesseBrown1980/ai-memory)** (★1, Rust) — Solução de long-term memory para agent coding CLIs. Facilita handoff entre diferentes agent vendors (Claude Code, Codex, Cursor, etc.). Roda como MCP server em Rust.

2. **[HRM — Hierarchical Reasoning Model](https://github.com/JesseBrown1980/HRM)** — Modelo de raciocínio hierárquico que pode ser usado como toolchain de verificação de edições.

O **simplicio-dev-cli** é a ferramenta de desenvolvimento que implementa edição determinística, validação, e fluxo de trabalho do Simplicio. Integrar ai-memory + HRM significa evoluir a memória neural e o pipeline de edição/validação.

---

## Análise ai-memory (Rust)

### Conceitos-Chave

**1. MCP Server em Rust**
- Servidor MCP nativo em Rust (performance máxima)
- Comunicação via stdio MCP protocol
- Compatível com qualquer cliente MCP (Claude, Codex, Cursor, VS Code)

**2. Cross-Vendor Handoff**
- Memória persistente entre sessões de diferentes agentes
- Claude Code → Codex → Cursor → Simplicio → qualquer um
- Padrão de dados unificado

**3. Markdown Wiki Storage**
- Memória armazenada como markdown files + git
- FTS5 search para recall
- Organizado por tópicos/domínios

**4. Zero-LLM Mode**
- Operação sem chamadas de LLM para recall
- Search puramente determinístico

### Mapeamento para o simplicio-dev-cli

| ai-memory Concept | Feature no simplicio-dev-cli |
|---|---|
| MCP Server Rust | `simplicio dev-cli serve --mcp` — dev-cli como MCP server |
| Cross-vendor handoff | Memória neural compartilhada entre agentes |
| Markdown wiki + git | `simplicio edit` com histórico git |
| FTS5 search | `simplicio memory --search` |
| Zero-LLM mode | Edição determinística sem tokens de LLM |

---

## Propostas de Implementação

### 🔴 P0 — Dev-CLI como MCP Server (port do ai-memory)

**Descrição:** Implementar o dev-cli como MCP server em Rust (ou Python com bindings Rust), seguindo o padrão do ai-memory.

**Detalhes:**
- `simplicio dev-cli serve --mcp` expõe tools MCP: editar, validar, memory, map
- Compatível com stdio MCP protocol (mesmo do ai-memory)
- Tools registradas: `dev-cli_edit`, `dev-cli_validate`, `dev-cli_memory`
- Performance nativa vs chamadas HTTP
- Bind para Claude Code, Codex, Cursor via `simplicio mcp register`

### 🔴 P0 — Cross-Vendor Memory Handoff

**Descrição:** Implementar o padrão de handoff do ai-memory no dev-cli, permitindo que diferentes agentes compartilhem estado de memória.

**Detalhes:**
- `simplicio memory init` — inicializa armazenamento markdown + git
- `simplicio memory recall "<query>"` — FTS5 search no banco compartilhado
- `simplicio memory store "<key>" "<value>"` — armazenamento cross-vendor
- `simplicio memory handoff --from codex --to claude` — transferência de contexto
- Banco em `~/.simplicio/memory/` acessível por qualquer agente MCP

### 🟡 P1 — Markdown Wiki + Git como Storage Determinístico

**Descrição:** Usar markdown + git como formato de armazenamento de memória e histórico de edições, seguindo o ai-memory.

**Detalhes:**
- Cada sessão de `simplicio edit` gera diff markdown
- `simplicio edit --history` mostra histórico git das edições
- `simplicio edit --blame` mostra quem editou o quê (cross-vendor)
- Rollback via `git revert` no diretório de memória
- `simplicio memory prune` — compactação de histórico

### 🟡 P1 — FTS5 Search + Vector Search Híbrido

**Descrição:** Combinar FTS5 search (do ai-memory) com vector search (já existente no runtime) para recall híbrido.

**Detalhes:**
- FTS5 para busca textual exata
- Vector (embeddings) para busca semântica
- `simplicio memory "<query>"` usa ambos, ranqueia por relevância
- `--mode fts5|vector|hybrid` para controlar

### 🔵 P2 — HRM Toolchain de Validação Determinística

**Descrição:** Implementar o padrão de raciocínio hierárquico do HRM como toolchain de validação.

**Detalhes:**
- **High-level validator:** verifica se a edição respeita a arquitetura do projeto
- **Low-level validator:** verifica sintaxe, tipos, lint
- **Comunicação bidirecional:** se low-level falha, high-level ajusta o plano
- `simplicio validate --hrm` ativa validação hierárquica

### 🔵 P2 — Token-Saving Report via HRM Dual Module

**Descrição:** Usar o padrão dual module do HRM para produzir relatórios de economia de tokens.

**Detalhes:**
- Módulo alto nível: estima quantos tokens seriam gastos sem Simplicio
- Módulo baixo nível: mede tokens reais gastos
- `simplicio dev-cli savings` — relatório estruturado
- Output formatado para `AGENTS.md` (ex: `Simplicio: ~2.1K · without ~15.3K · saved ~13.2K (86%)`)

---

## Referências

- ai-memory: https://github.com/JesseBrown1980/ai-memory (Rust)
- HRM: https://github.com/JesseBrown1980/HRM
- MCP Protocol: https://modelcontextprotocol.io
- Simplicio dev-cli: https://github.com/wesleysimplicio/simplicio-dev-cli

---

## Métricas de Sucesso

- [ ] Dev-CLI como MCP server funcional com tools de edição/validação/memory
- [ ] Cross-vendor handoff operacional (Claude Code ↔ Codex ↔ Simplicio)
- [ ] Markdown wiki + git como storage de edições
- [ ] FTS5 + vector search híbrido funcional
- [ ] HRM toolchain de validação hierárquica
- [ ] Token-saving report automatizado

#### Objetivo

Entregar e provar o resultado delimitado por: 🌌 Integração Asolaria: ai-memory (Rust) como Backend de Memória Neural + HRM Toolchain

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .simplicio/memory, edição/validação., edição/validação/memory, github.com/JesseBrown1980/HRM, github.com/JesseBrown1980/ai-memory, github.com/wesleysimplicio/simplicio-dev-cli, tópicos/domínios.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #90 — feat: piloto 2 do autoresearch — otimizar os templates de prompt (precedent + skill_router) contra o bench (eval = pass-rate gate + tokens)

- Estado/data: `closed`; criada `2026-07-02T17:34:05Z`; atualizada `2026-07-03T13:06:36Z`
- Labels: `enhancement`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

Segundo piloto da skill `simplicio-autoresearch` (wesleysimplicio/simplicio-loop#95). Este repo é o fit mais natural do ecossistema: o produto é literalmente **"prompt afiado medido em bench"** (+39/+51/+58 pts, 99% pass-rate são os números de marketing do próprio README) — e o harness de avaliação já existe: `bench/cases.json` + `bench.py` logando `tokens_estimated` por caso em `runs.jsonl`.

O autoresearch fecha o ciclo: em vez de afiar o prompt na mão e medir depois, o loop muta o template e o bench decide o que sobrevive.

## Setup do run

- **Alvos** (um run por alvo, começar pelo primeiro):
  1. Bloco de precedent (`simplicio/precedent.py::build_precedent_block()` — hand-formatted, flagado como follow-up no PR #87)
  2. Bloco do skill_router (`simplicio/skill_router.py`)
  3. Template principal (`simplicio/prompt.py::build_prompt()`)
- **Eval (composto, nessa ordem)**:
  1. GATE: pass-rate do bench **não regride** vs baseline (`bench/cases.json`, mesmo modelo, mesma seed/config) + `ruff check` + testes unitários verdes — regrediu → revert.
  2. SCORE: com pass-rate mantido, menor `tokens_estimated` médio por caso vence (estimador ÚNICO e rotulado — pré-requisito da unificação de estimadores do #88).
- **Validation set fixo**: subconjunto fixo de `bench/cases.json` (não mudar durante o run; separar um holdout para verificação final anti-overfit).
- **Modelo do bench**: preferir o ladder local (é o caso de uso do produto — sub-4B a 74%); os números valem para o modelo usado, rotular.
- **Caps (yool §11)**: branch isolado, máx. iterações/orçamento, squash final.

## Critérios de Aceitação

- [ ] Run 1 (precedent block) completo com log de iterações como evidência
- [ ] Pass-rate no holdout ≥ baseline (verificação anti-overfit independente do loop)
- [ ] Redução de tokens documentada em `bench/results_autoresearch.{json,md}` ao lado do A/B TOON do #88
- [ ] Nenhum commit vermelho; PR final com 1 commit squashed
- [ ] `simplicio.savings-event/v1` por run (`source=autoresearch`)
- [ ] Se o template otimizado divergir do estilo documentado em PATTERNS/docs, atualizar a doc no mesmo PR (o template é contrato)

## Dependências

1. #88 (unificar estimadores + A/B baseline — sem estimador único o score é ruído)
2. wesleysimplicio/simplicio-loop#95 (a skill com guardrails)
3. Recomendado: wesleysimplicio/simplicio-runtime#2774 (ladder local como motor de mutação barato)

Refs: #85, #87, #88, wesleysimplicio/simplicio-loop#95, wesleysimplicio/simplicio-runtime#2775.

#### Objetivo

Entregar e provar o resultado delimitado por: feat: piloto 2 do autoresearch — otimizar os templates de prompt (precedent + skill_router) contra o bench (eval = pass-rate gate + tokens)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: 39/+51, A/B, PATTERNS/docs, bench/cases.json, bench/results_autoresearch.{json, iterações/orçamento, seed/config, simplicio.savings-event/v1, simplicio/precedent.py, simplicio/prompt.py, simplicio/skill_router.py, wesleysimplicio/simplicio-loop, wesleysimplicio/simplicio-runtime.

#### Dependências e ordem

Referências explícitas: #85, #87, #88. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #93 — feat(regression-safety): a camada verify do contrato 6-layer roda os testes de impacto, não só os do arquivo tocado

- Estado/data: `closed`; criada `2026-07-02T19:51:24Z`; atualizada `2026-07-03T05:02:29Z`
- Labels: `enhancement`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

Pedido do operador: **garantir testes + evidência e certeza de que a mudança não afeta outros lugares.** O contrato 6-layer do dev-cli (mapper→precedent→prompt→diff→test→verify) já roda test+verify — mas a camada `test` tende a rodar os testes do arquivo editado, não os testes de tudo que **depende** dele. Uma edição que passa localmente pode quebrar um caller a duas camadas de distância.

## Escopo

1. **Verify por blast-radius**: a camada `verify` consulta o call-graph do mapper (já é o operator `orient` do ecossistema) para o diff produzido e roda os testes dos callers/dependentes afetados, não só os do arquivo alvo. Reusa o `impact` do mapper (`simplicio-mapper ask . impact --json`).
2. **Evidência no resultado da task**: o JSON de saída do `task` ganha `impact: {callers, tests_run, result}` — citável em `runs.jsonl` e no PR. Sem impacto verificável em mudança que toca símbolo com callers = `UNVERIFIED(impact)` honesto.
3. **Gate de retry**: se um teste de impacto falha, entra no loop de retry do contrato (≤3) como qualquer falha de verify — o dev-cli conserta ou reporta honestamente, nunca declara sucesso com caller quebrado.
4. `ruff` + `pytest tests/python` verdes; comportamento coberto por teste.

## Critérios de Aceitação

- [ ] `verify` roda testes de callers afetados via impact do mapper (teste com fixture de caller)
- [ ] Saída do `task` carrega bloco `impact`; UNVERIFIED honesto quando não computável
- [ ] Falha de teste de impacto entra no retry do contrato
- [ ] Suite verde; estimador de token rotulado (consistência com #88)

Refs: #88 (usage/telemetria), simplicio-mapper `ask impact`, simplicio-loop#104-irmã (blast-radius gate).

#### Objetivo

Entregar e provar o resultado delimitado por: feat(regression-safety): a camada verify do contrato 6-layer roda os testes de impacto, não só os do arquivo tocado

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: callers/dependentes, tests/python, usage/telemetria.

#### Dependências e ordem

Referências explícitas: #88. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #98 — [P0][Branch] Migrar a branch default de master para main e alinhar referências locais

- Estado/data: `open`; criada `2026-07-07T03:57:12Z`; atualizada `2026-07-21T20:46:02Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **NEEDS-IMPLEMENTATION**

#### Contexto e problema

## Reabertura — auditoria de 2026-07-19

A issue foi fechada, mas o repositório continuava com `master` como default e não possuía branch `main`. O aceite não estava satisfeito.

## Objetivo atual

Migração explícita e não destrutiva:

1. criar `main` no mesmo commit da `master` atual;
2. tornar `main` a branch default no GitHub;
3. direcionar os novos PRs para `main`;
4. atualizar referências vivas de `master` para `main` quando representarem a default;
5. manter `master` temporariamente como compatibilidade, sem novos commits;
6. verificar clone/fetch/PR contra `main`;
7. registrar o commit antigo e o novo default na evidência.

## Progresso verificado

- [x] branch `main` criada inicialmente em `cf528b1df766aff21e07f48d9d070efc66c5e5a6`;
- [ ] GitHub informa `default_branch=main`;
- [x] PRs #253 e #254 usaram base `main`;
- [x] documentação e contratos não tratam `master` como default;
- [x] `master` não foi apagada;
- [x] validação local reproduzível anexada;
- [x] `main` reconsultada após merge e contém as correções;
- [ ] issue só fecha após reconsulta do metadata remoto com `default_branch=main`.

## Evidência

- PR de alinhamento: https://github.com/wesleysimplicio/simplicio-dev-cli/pull/254
- merge em `main`: `d5dbb07b0372e48fde05793c6103251fa0276abd`
- 16 testes focados, Ruff/format focados, token budget, coverage-gate selftest e `git diff --check` passaram;
- GitHub Actions está fora do escopo e do aceite;
- reconsulta do metadata remoto após o merge ainda retorna `default_branch=master`.

## Bloqueio administrativo remanescente

O conector GitHub instalado tem permissão administrativa no repositório, mas não expõe a operação de atualizar `default_branch`. A mudança precisa ser feita em **Settings → Branches → Default branch → main** (ou por uma API/CLI administrativa que exponha esse campo). Depois disso, reconsultar o metadata e fechar esta issue.

<!-- SIMPLICIO-ISSUE-AUDIT:v1 -->
## Revisão complementar do projeto: simplicio-dev-cli

Responsabilidade avaliada: **CLI**. Esta issue deve ser entendida no contexto da auditoria-mãe do repositório.

### Objetivo específico

validar CLI → Mapper → PlanDAG → Runtime → saída auditável

### Fluxo de testes obrigatório

happy path, argumentos inválidos, worktree, snapshot, retry, timeout, export e compatibilidade

1. Registrar SHA/branch, ambiente, dependências e configuração.
2. Executar o caminho feliz completo e capturar logs/receipts.
3. Injetar entrada inválida, timeout, falha externa ou permissão ausente aplicável.
4. Verificar retry, cancelamento, idempotência e rollback quando o fluxo suportar.
5. Executar testes unitários, integração, sistema/E2E, regressão, segurança e desempenho aplicáveis.
6. Reexecutar com os mesmos dados e comparar resultado/hashes.
7. Confirmar que falha nunca vira sucesso e que recursos são liberados.

### Critérios de aceite adicionais

- [ ] O comportamento principal está demonstrado por teste executável.
- [ ] Pelo menos um caminho de falha está coberto e documentado.
- [ ] Contratos entre projetos são validados nas versões/SHAs declarados.
- [ ] Logs e receipts permitem reconstruir a decisão.
- [ ] Métricas não observáveis são `null` com motivo, nunca estimadas.
- [ ] Segredos, PII e dados privados não aparecem nos artefatos.
- [ ] O procedimento é reproduzível localmente ou em container sem GitHub Actions pago.
- [ ] PR/commit, logs, hashes e riscos residuais estão anexados antes de fechar.

### Evidências obrigatórias

- PR/commit vinculado;
- comandos e versões;
- logs do caminho feliz e da falha;
- testes/coverage/benchmark aplicáveis;
- receipts, hashes e relatório de rollback;
- limitações e próximos passos.

### Regra de encerramento

Não fechar sem todos os critérios desta issue e da auditoria-mãe atendidos. Se faltar implementação, marcar como `NEEDS-IMPLEMENTATION` ou `BLOCKED`, nunca como concluída.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][Branch] Migrar a branch default de master para main e alinhar referências locais

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: API/CLI, PR/commit, Ruff/format, SHA/branch, clone/fetch/PR, github.com/wesleysimplicio/simplicio-dev-cli/pull/254, logs/receipts., resultado/hashes., sistema/E2E, testes/coverage/benchmark, versões/SHAs.

#### Dependências e ordem

Referências explícitas: #253, #254. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #99 — packaging: move heavy ML and provider dependencies behind extras

- Estado/data: `closed`; criada `2026-07-07T03:57:34Z`; atualizada `2026-07-07T04:54:11Z`
- Labels: `nenhuma`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "P1", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

O `simplicio-dev-cli` é a camada de execução focada. Para adoção, instalação e bootstrap rápido, o caminho padrão deve ser leve e previsível. Hoje dependências pesadas de ML/provedores entram no install base, mesmo quando o usuário só precisa do executor, contrato, mapper context e edição/verificação.

## Objetivo

Separar dependências obrigatórias do núcleo das dependências opcionais de provedores, ML, local inference e benchmarks.

## Proposta

Base mínima sugerida:

```toml
dependencies = [
  "simplicio-mapper>=0.14.0",
  "simplicio-prompt>=1.14.1",
  "httpx>=0.28.1",
  "orjson>=3.11.9",
  "diskcache>=5.6.3",
  "libcst>=1.8.6",
]

[project.optional-dependencies]
providers = ["openai>=2.44.0", "anthropic>=0.112.0"]
ml = ["sentence-transformers>=5.6.0", "numpy>=2.1.0"]
local = ["llama-cpp-python>=0.3.32", "huggingface-hub>=1.21.0"]
bench = ["fpdf2>=2.8.7"]
all = [ ... ]
```

A lista final pode mudar conforme imports reais, mas a intenção é clara: install base não deve puxar stack pesada sem necessidade.

## Escopo

- Mapear imports para descobrir o que é realmente obrigatório no caminho base.
- Mover dependências pesadas para extras sem quebrar comandos existentes.
- Melhorar mensagens de erro quando um extra necessário não está instalado.
- Adicionar testes de instalação:
  - install base
  - install `[providers]`
  - install `[ml]`
  - install `[local]` quando viável em smoke leve
- Atualizar docs de instalação.

## Fora de escopo

- Remover suporte a provedores remotos.
- Remover suporte local/llama.cpp.
- Trocar arquitetura do executor.

## Critérios de aceite

- [ ] `pip install simplicio-cli` instala e executa `simplicio-py --help` sem dependências ML pesadas.
- [ ] Comandos que exigem provider remoto exibem erro acionável indicando o extra correto.
- [ ] Comandos ML/semantic/RAG exibem erro acionável indicando `pip install "simplicio-cli[ml]"`.
- [ ] CI cobre install base em ambiente limpo.
- [ ] CI cobre pelo menos um extra real.
- [ ] README/INSTALL documenta os perfis: base, providers, ml, local, all.
- [ ] Nenhum import top-level de dependência opcional quebra o install base.

## Prioridade sugerida

P1 — melhora adoção e reduz falha de instalação.

#### Objetivo

Entregar e provar o resultado delimitado por: packaging: move heavy ML and provider dependencies behind extras

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: ML/provedores, ML/semantic/RAG, README/INSTALL, edição/verificação., local/llama.cpp..

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #100 — contract: add executor compatibility tests for mapper and runtime integration

- Estado/data: `closed`; criada `2026-07-07T04:02:33Z`; atualizada `2026-07-07T04:54:11Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P1", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

O `simplicio-dev-cli` consome artifacts do `simplicio-mapper` e também deve cooperar com o `simplicio-runtime` quando o runtime compilado estiver disponível. Para evitar regressões silenciosas, essa integração precisa virar teste de contrato.

## Objetivo

Adicionar uma suite de compatibilidade que prove que o executor continua entendendo o mapa do repo, criando o contrato de execução e validando a saída esperada sem depender de chamadas remotas.

## Escopo

- Criar suite `tests/contracts/`.
- Usar fixtures reais de `project-map.json` e `precedent-index.json`.
- Validar o fluxo mínimo:
  - carregar artifacts do mapper
  - classificar uma tarefa pequena
  - montar contrato de execução
  - produzir saída estruturada
  - executar verificação local simples
- Validar payload JSON estável para comandos críticos, como `detect --json`, `doctor --json` e o comando de task equivalente.
- Cobrir dois modos:
  - execução standalone do pacote Python
  - execução integrada quando a superfície do runtime estiver disponível em ambiente de teste controlado

## Fora de escopo

- Rodar benchmark completo.
- Chamar provedores pagos ou remotos no CI.
- Exigir modelo local pesado no CI.

## Critérios de aceite

- [ ] Existe suite de contract tests sem chamadas externas.
- [ ] A suite valida consumo de pelo menos um `project-map.json` realista.
- [ ] A suite cobre execução standalone do `simplicio-cli`.
- [ ] A suite cobre caminho integrado com runtime usando ambiente de teste controlado.
- [ ] Saídas JSON críticas são validadas por schema ou snapshot.
- [ ] O CI executa esses testes no install base.
- [ ] Falhas de contrato retornam mensagens acionáveis, não stack trace cru.

## Prioridade sugerida

P1 — protege integração mapper/dev-cli/runtime.

#### Objetivo

Entregar e provar o resultado delimitado por: contract: add executor compatibility tests for mapper and runtime integration

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: mapper/dev-cli/runtime., tests/contracts.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #101 — docs: replace stale package interdependence doc with generated ecosystem contract

- Estado/data: `closed`; criada `2026-07-07T04:08:23Z`; atualizada `2026-07-07T04:54:12Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": true, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

`docs/PYTHON_PACKAGE_INTERDEPENDENCE.md` documenta o grafo Python do ecossistema, mas esse tipo de arquivo fica rapidamente defasado quando versões e constraints evoluem. Como o `simplicio-dev-cli` depende do mapper e é consumido pelo loop/runtime, esse documento precisa ser confiável ou gerado.

## Objetivo

Atualizar ou substituir o documento manual por uma visão gerada/checável do contrato de dependências do `simplicio-dev-cli`.

## Escopo

- Ler a versão real do `pyproject.toml`.
- Ler constraints reais de:
  - `simplicio-mapper`
  - `simplicio-prompt`
  - extras relevantes
- Atualizar `docs/PYTHON_PACKAGE_INTERDEPENDENCE.md` ou substituí-lo por documento gerado.
- Adicionar checagem no CI para impedir drift.
- Apontar para o contrato/doctor do ecossistema quando disponível.

## Fora de escopo

- Alterar constraints de pacote sem necessidade.
- Publicar release.
- Resolver documentação de todos os repos neste PR.

## Critérios de aceite

- [ ] O documento mostra a versão real atual do `simplicio-cli`.
- [ ] O documento mostra constraints reais lidas de `pyproject.toml`.
- [ ] O documento não menciona versões antigas que não correspondem ao metadata atual.
- [ ] Existe comando local `--check` ou equivalente para detectar drift.
- [ ] O CI executa essa verificação.
- [ ] README/CONTRIBUTING explica que o grafo não deve ser editado manualmente, se for gerado.
- [ ] O documento deixa claro como o dev-cli se encaixa entre mapper, runtime e loop.

## Prioridade sugerida

P0/P1 — documentação de dependência precisa bater com o pacote real.

#### Objetivo

Entregar e provar o resultado delimitado por: docs: replace stale package interdependence doc with generated ecosystem contract

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: P0/P1, README/CONTRIBUTING, contrato/doctor, docs/PYTHON_PACKAGE_INTERDEPENDENCE.md, gerada/checável, loop/runtime.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #102 — ci: add ruff + mypy + py.typed lint/type gate for the Python package

- Estado/data: `closed`; criada `2026-07-07T04:16:44Z`; atualizada `2026-07-07T06:02:29Z`
- Labels: `enhancement, needs-triage`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P1", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

O produto real é o pacote Python `simplicio-cli` (~8.776 linhas em `simplicio/*.py`). Hoje **não existe nenhum linter/type-checker configurado na raiz** para esse código:

- `pyproject.toml` só tem `[tool.setuptools.*]` e `[tool.pytest.ini_options]` — nenhum `[tool.ruff]`, `[tool.mypy]`, `[tool.black]`.
- As únicas configs `ruff` do repo estão dentro de `simplicio/templates/stacks/py-*/tree/pyproject.toml`, ou seja, valem para os projetos gerados, **não** para o código do próprio CLI.
- Não há `simplicio/py.typed`, apesar de o código usar type hints extensivamente (`from __future__ import annotations`, assinaturas tipadas).

Isso contradiz o DoD do repo (`CLAUDE.md` / `AGENTS.md`), que exige "lint verde" como gate — mas não há linter Python que possa ficar verde ou vermelho.

> Nota: a issue #98 trata de adicionar o gate de `pytest`/CI Python. Esta issue é complementar e cobre especificamente **lint + type-check + exportação de tipos**, que #98 não menciona.

## Objetivo

Configurar `ruff` (lint + format) e `mypy` (type-check) para `simplicio/` e `tests/python/`, marcar o pacote como tipado com `py.typed`, e rodar tudo no CI.

## Escopo

- Adicionar ao `pyproject.toml` (raiz):
  - `[tool.ruff]` com `line-length`, `target-version = "py310"`, e um conjunto de regras inicial (`E`, `F`, `I`, `UP`, `B` no mínimo).
  - `[tool.ruff.format]` (substitui black).
  - `[tool.mypy]` começando permissivo (`ignore_missing_imports = true`) e endurecendo por módulo depois.
- Criar arquivo vazio `simplicio/py.typed` e incluí-lo em `[tool.setuptools.package-data]`.
- Adicionar as dev-deps em um extra (`dev = ["ruff>=...", "mypy>=..."]`) — **não** no install base (alinha com a filosofia da #99).
- Adicionar/estender job de CI que roda:
  ```bash
  ruff check .
  ruff format --check .
  mypy simplicio
  ```
- Corrigir (ou suprimir com justificativa `# noqa`/`# type: ignore[...]` pontual) o que a primeira passada acusar. Endurecimento incremental é aceitável: começar com baseline verde, não exigir mypy strict de cara.
- Documentar o comando local equivalente em `CONTRIBUTING`/`AGENTS.md`.

## Fora de escopo

- Refactor de código não relacionado a erros de lint/type.
- mypy `--strict` global neste PR (pode virar issue de follow-up).
- Alterar dependências de runtime.

## Critérios de aceite

- [ ] `pyproject.toml` tem seções `[tool.ruff]` e `[tool.mypy]` na raiz.
- [ ] `ruff check .` roda com exit 0 em ambiente limpo (baseline verde, com supressões justificadas se necessário).
- [ ] `ruff format --check .` passa (código já formatado).
- [ ] `mypy simplicio` roda com exit 0 no nível de rigor escolhido, documentado no `pyproject.toml`.
- [ ] `simplicio/py.typed` existe e é empacotado (`package-data`).
- [ ] `ruff`/`mypy` estão declarados como dev-deps, **não** no install base.
- [ ] O CI executa `ruff check`, `ruff format --check` e `mypy` e falha o build quando qualquer um falha.
- [ ] `CONTRIBUTING`/`AGENTS.md` descrevem o comando local (`ruff check . && mypy simplicio`).
- [ ] O `CLAUDE.md`/`AGENTS.md` deixam de referenciar "lint" genérico sem ferramenta e passam a apontar o comando Python real.

## Prioridade sugerida

P1 — o DoD já promete lint verde; hoje não há ferramenta que o cumpra.

#### Objetivo

Entregar e provar o resultado delimitado por: ci: add ruff + mypy + py.typed lint/type gate for the Python package

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Adicionar/estender, lint/type., linter/type-checker, simplicio/*.py, simplicio/py.typed, simplicio/templates/stacks/py-*, tests/python, tree/pyproject.toml.

#### Dependências e ordem

Referências explícitas: #98, #99. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #103 — refactor: break up cli.py god-file (1.294 lines) by moving subcommand handlers into commands/

- Estado/data: `closed`; criada `2026-07-07T04:17:00Z`; atualizada `2026-07-07T06:02:31Z`
- Labels: `enhancement, needs-triage`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P2", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

`simplicio/cli.py` tem **1.294 linhas** e é de longe o maior arquivo do pacote. A função `main()` (a partir de ~linha 886) define ~40 subcomandos inline via `sub.add_parser(...)`: `index`, `task`, `run`, `bench`, `cache`, `smoke`, `init`, `detect`, `status`, `claims`, `inspect`, `doctor`, `env`, `mechanical`, `edit`, `file`, `test`, `token`, `score-skill`, `runtime`, `serve`, `memory`, entre outros — muitos com a lógica do handler no mesmo arquivo.

O repo já estabeleceu o padrão de extração: `simplicio/commands/` contém `claims.py`, `file_read.py`, `gate.py`, `nest.py`, `score_skill.py`, `test_run.py` (~2.065 linhas já migradas). Falta terminar a migração — vários handlers continuam morando no `cli.py`.

## Objetivo

Reduzir `cli.py` a um dispatcher fino (parser + roteamento) movendo a lógica de cada subcomando para módulos dedicados em `simplicio/commands/`, seguindo o padrão já existente.

## Escopo

- Inventariar quais subcomandos ainda têm o handler embutido em `cli.py`.
- Para cada um, extrair a lógica para `simplicio/commands/<nome>.py` expondo uma função handler com assinatura consistente com as já migradas (ex: `run(args) -> int`).
- `cli.py` deve conter apenas: construção do `argparse`, wiring de `set_defaults(func=...)` e o dispatch em `main()`.
- Manter 100% de compatibilidade de comportamento e de superfície de CLI (mesmos comandos, flags, exit codes, formato de saída/JSON).
- Adicionar/mover testes unitários por handler em `tests/python/` (ex: `test_cmd_<nome>.py`), testando o handler isolado do argparse.

## Fora de escopo

- Mudar nomes de comandos, flags ou formato de saída (isso seria breaking change — issue separada).
- Alterar lógica de negócio dos handlers além do necessário para extrair.
- Mexer no `mcp_server.py`.

## Critérios de aceite

- [ ] `cli.py` fica abaixo de ~400 linhas e não contém lógica de handler (só parsing + dispatch).
- [ ] Cada subcomando restante tem seu handler em `simplicio/commands/<nome>.py`.
- [ ] `simplicio-py --help` e o `--help` de cada subcomando produzem exatamente a mesma saída de antes (snapshot test).
- [ ] Exit codes e payloads JSON de comandos críticos (`detect --json`, `doctor --json`, `task`, `status`) permanecem idênticos (validado por teste).
- [ ] Cada handler extraído tem teste unitário que o exercita sem passar pelo argparse.
- [ ] `pytest` verde; nenhuma regressão de comportamento.
- [ ] Nenhum import circular novo introduzido.

## Prioridade sugerida

P2 — dívida técnica; não urgente, mas o god-file dificulta teste e manutenção.

#### Objetivo

Entregar e provar o resultado delimitado por: refactor: break up cli.py god-file (1.294 lines) by moving subcommand handlers into commands/

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Adicionar/mover, saída/JSON, simplicio/cli.py, simplicio/commands, tests/python.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #104 — chore: clean up repository root (backup README, stray reports, 800 KB tracked PNG)

- Estado/data: `closed`; criada `2026-07-07T04:17:20Z`; atualizada `2026-07-07T06:02:31Z`
- Labels: `enhancement, needs-triage`
- Classificação: `{"component": "quality", "epic": "standalone", "priority": "P2", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

A raiz do repositório acumulou ruído versionado que polui a primeira impressão e o `git`:

- `README.backup-2026-05-27.md` (25 KB) — backup manual de README. O histórico do git **já é o backup**; arquivos `*.backup-*` versionados são anti-padrão.
- `RELATORIO_CONSOLIDADO_E_RECOMENDACAO.md` (7,4 KB) e `_BOOTSTRAP.md` (15,5 KB) — relatórios/notas de trabalho na raiz.
- `simplicio-cli-readme-hero-web.png` — **821 KB** de imagem binária versionada na raiz, inflando todo `clone`.
- Duplicação de docs de topo: `README.md` + `README.pt-BR.md` + `AGENTS.md` + `CLAUDE.md` (cópia regular) + `INIT.md` + `INSTALL.md` + pasta `READMEs/`.

Nada disso é código de produto, mas está no caminho de quem abre o repo.

## Objetivo

Enxugar a raiz: remover backups redundantes, mover relatórios/notas para `docs/`, e tirar assets binários pesados do caminho padrão de clone.

## Escopo

- Remover `README.backup-2026-05-27.md` (o git history preserva).
- Mover `RELATORIO_CONSOLIDADO_E_RECOMENDACAO.md`, `_BOOTSTRAP.md` e similares para `docs/` (ou arquivá-los se obsoletos).
- Tratar o hero image:
  - opção A: mover para `docs/assets/` e referenciar por caminho relativo;
  - opção B (preferida se o peso importar): servir via GitHub Release asset / branch de docs e referenciar por URL absoluta no README;
  - garantir que o `README` continua renderizando a imagem no PyPI/GitHub.
- Revisar a pasta `READMEs/` — consolidar ou documentar seu propósito.
- Confirmar que `MANIFEST.in`/`package-data` e `npm pack`/sdist não incluem os arquivos removidos indevidamente.
- Adicionar ao `.gitignore` padrões de artefato temporário (`*.backup-*`, `output/`, se aplicável) para evitar reincidência.

## Fora de escopo

- Reescrever o conteúdo do README.
- Consolidar `AGENTS.md`/`CLAUDE.md` (o `CLAUDE.md` é cópia proposital por não seguir symlink; mudar isso é decisão à parte).
- Remover `README.pt-BR.md` (bilinguismo é intencional).

## Critérios de aceite

- [ ] `README.backup-2026-05-27.md` não existe mais no branch.
- [ ] Relatórios/notas soltos (`RELATORIO_CONSOLIDADO_E_RECOMENDACAO.md`, `_BOOTSTRAP.md`) estão em `docs/` ou removidos, e a raiz só contém docs canônicos.
- [ ] O hero image não está mais na raiz; o README renderiza a imagem corretamente no GitHub (verificado visualmente).
- [ ] `git ls-files` na raiz mostra apenas arquivos canônicos (manifests, docs de topo, LICENSE, configs).
- [ ] `.gitignore` previne reincidência de backups/artefatos.
- [ ] `npm pack --dry-run` e `python -m build` continuam gerando pacotes válidos sem os arquivos removidos.
- [ ] Nenhum link quebrado introduzido nos READMEs (checagem de links relativos).

## Prioridade sugerida

P2 — higiene; baixo risco, alto ganho de legibilidade.

#### Objetivo

Entregar e provar o resultado delimitado por: chore: clean up repository root (backup README, stray reports, 800 KB tracked PNG)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: PyPI/GitHub., Relatórios/notas, backups/artefatos., docs/assets, relatórios/notas.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #105 — docs: fix CLAUDE.md/AGENTS.md commands that reference non-existent npm scripts instead of the real Python stack

- Estado/data: `closed`; criada `2026-07-07T04:17:42Z`; atualizada `2026-07-07T06:02:30Z`
- Labels: `documentation, needs-triage`
- Classificação: `{"component": "cli", "epic": "standalone", "priority": "P1", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

O `CLAUDE.md`/`AGENTS.md` são descritos como "o contrato entre humano e IA neste repositório" e são lidos por vários agentes (Claude Code, Codex, Copilot, Cursor, etc.). Porém a seção **"Comandos importantes"** documenta comandos que **não existem** neste repo:

```bash
npm run dev        # não existe
npm run build      # não existe
npm run lint       # não existe
npm run lint:fix   # não existe
npm test           # não existe
```

O `package.json` real só define `test:e2e`, `test:e2e:ui` e `test:e2e:report`. O produto é o pacote **Python** `simplicio-cli`; os comandos reais são `uv`/`pip install -e .`, `pytest`, `ruff` (após #<a>ruff issue</a>) e `playwright`.

Consequência: qualquer agente (ou humano) que siga o `CLAUDE.md` ao pé da letra roda `npm run lint`/`npm test` e recebe **"Missing script"** — o "workflow loop obrigatório" e o DoD ficam impossíveis de cumprir como escritos. Isso também se conecta ao guard de CI obsoleto descrito na #98.

## Objetivo

Alinhar os comandos documentados no `AGENTS.md` (e espelhos `CLAUDE.md`, `.github/copilot-instructions.md`) com a stack Python real do repositório.

## Escopo

- Reescrever a seção "Comandos importantes" para os comandos reais:
  - setup: `uv sync` / `pip install -e ".[dev]"`
  - testes: `pytest` (e `pytest --cov`)
  - lint/type: `ruff check .` / `mypy simplicio` (quando a #ruff estiver mergeada)
  - E2E: `npx playwright test` (permanece — é o harness do starter embutido)
  - CLI: `simplicio-py --help`, `simplicio-cli --help`
- Ajustar a seção "Stack" para refletir Python 3.10+ / setuptools / pytest / (ruff+mypy), em vez dos placeholders `<STACK>` genéricos.
- Ajustar o "Workflow loop OBRIGATÓRIO" e o "Definition of Done" para citar `pytest`/`ruff` em vez de `npm test`/`npm run lint`.
- Propagar as mesmas mudanças para todos os espelhos: `AGENTS.md` (master), `CLAUDE.md` (cópia regular), `.github/copilot-instructions.md` (cópia regular). Symlinks (`GEMINI.md`, `.windsurf/rules/agents.md`, `.kiro/steering/agents.md`) acompanham automaticamente.
- Deixar claro no doc quais comandos valem para o **produto** (Python) vs. para o **starter embutido** (Node/Playwright), para não confundir os dois contextos.

## Fora de escopo

- Adicionar scripts `lint`/`test` ao `package.json` só para casar com o doc (a direção correta é o doc apontar para Python, não criar wrappers npm falsos).
- Mudar o conteúdo do workflow em si (só a documentação dos comandos).

## Critérios de aceite

- [ ] Nenhum comando em `AGENTS.md`/`CLAUDE.md` referencia um script npm inexistente.
- [ ] A seção "Comandos importantes" lista os comandos Python reais e eles funcionam quando copiados/colados num checkout limpo.
- [ ] A seção "Stack" descreve a stack real (Python 3.10+, pytest, ruff/mypy, Playwright para o starter), sem `<STACK>` órfão onde já se sabe a resposta.
- [ ] O "Definition of Done" cita os gates reais (`pytest`, `ruff`, cobertura) coerentes com o CI da #98.
- [ ] `AGENTS.md`, `CLAUDE.md` e `.github/copilot-instructions.md` estão sincronizados (mesmo conteúdo nas seções alteradas).
- [ ] Um leitor consegue distinguir comandos do produto Python dos comandos do starter Node/Playwright.

## Prioridade sugerida

P1 — doc enganosa quebra o fluxo de qualquer agente que a siga literalmente.

#### Objetivo

Entregar e provar o resultado delimitado por: docs: fix CLAUDE.md/AGENTS.md commands that reference non-existent npm scripts instead of the real Python stack

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .github/copilot-instructions.md, .kiro/steering/agents.md, .windsurf/rules/agents.md, Node/Playwright, Node/Playwright., copiados/colados, lint/type, ruff/mypy.

#### Dependências e ordem

Referências explícitas: #98. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #106 — refactor: centralize output/logging (268 scattered print() calls) and protect MCP stdio

- Estado/data: `closed`; criada `2026-07-07T04:18:06Z`; atualizada `2026-07-07T06:02:30Z`
- Labels: `enhancement, needs-triage`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "P1", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

Existem **268 chamadas `print(...)`** espalhadas por `simplicio/*.py`, apesar de o pacote já ter um módulo `simplicio/observability.py`. Problemas decorrentes:

1. **Sem separação disciplinada stdout/stderr.** Dados que outros programas consomem (JSON de `detect --json`, `doctor --json`) precisam ir para stdout limpo; mensagens de status/progresso/erro precisam ir para stderr. Com `print()` solto isso vira caso a caso e é fácil poluir o stdout de dados.
2. **Risco no modo MCP.** `simplicio/mcp_server.py` fala o protocolo MCP por stdio. Qualquer `print()` para stdout dentro do caminho do servidor **corrompe o framing do protocolo** e pode derrubar a sessão do cliente MCP. Isso é uma classe de bug silencioso e difícil de diagnosticar.
3. **Sem níveis nem controle de verbosidade** (`-q`/`-v`/`--json`) uniformes.

## Objetivo

Introduzir uma camada fina de saída/logging centralizada e migrar os `print()` para ela, garantindo que o caminho MCP nunca escreva no stdout de protocolo por engano.

## Escopo

- Definir helpers centrais (em `observability.py` ou novo `simplicio/output.py`):
  - `emit_data(...)` → stdout (payloads/JSON destinados a consumo por máquina).
  - `info/warn/error(...)` → stderr (status legível por humano), com respeito a `--quiet`/`--verbose`.
  - logger `logging` configurável por env (`SIMPLICIO_LOG_LEVEL`).
- Migrar os `print()` de código de biblioteca (`providers.py`, `pipeline*.py`, `mapper.py`, `mcp_server.py`, etc.) para os helpers. `print()` explícito pode permanecer apenas nos handlers de CLI onde a saída para stdout é o resultado pretendido.
- **Regra dura para o caminho MCP:** nenhum `print()`/escrita a `sys.stdout` no fluxo do `mcp_server.py` e no que ele chama; toda diagnose vai para stderr/logger.
- Adicionar teste que rode o servidor MCP com um request e afirme que **stdout contém apenas frames MCP válidos** (nenhuma linha de log vazada).
- Adicionar guard de CI/lint (ex: regra `ruff` `T201` no módulo `mcp_server` e libs) para impedir reincidência de `print()` fora dos pontos permitidos.

## Fora de escopo

- Redesenhar `observability.py` além do necessário para expor os helpers.
- Trocar formato de saída dos comandos (o que sai não muda; só *por onde* sai).
- Internacionalizar mensagens.

## Critérios de aceite

- [ ] Existe uma camada central de saída/logging com separação explícita stdout (dados) vs stderr (status).
- [ ] `providers.py`, `pipeline*.py`, `mapper.py` e `mcp_server.py` não usam `print()` para status/diagnóstico — usam os helpers/logger.
- [ ] `print()` remanescente existe apenas em handlers de CLI onde stdout é o resultado pretendido, e isso está documentado.
- [ ] Teste automatizado prova que o `mcp_server` não vaza nada para o stdout do protocolo (stdout só contém frames MCP válidos).
- [ ] `--quiet` suprime status em stderr; `--verbose`/`SIMPLICIO_LOG_LEVEL` aumentam verbosidade — comportamento coberto por teste.
- [ ] Saídas `--json` continuam sendo stdout puro e parseável (validado por teste).
- [ ] Regra de lint impede novos `print()` nos módulos sensíveis; CI falha se reincidir.
- [ ] Nenhuma regressão em `pytest`.

## Prioridade sugerida

P1 — o vazamento de stdout no caminho MCP é um bug latente de corrupção de protocolo, não só estética.

#### Objetivo

Entregar e provar o resultado delimitado por: refactor: centralize output/logging (268 scattered print() calls) and protect MCP stdio

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: CI/lint, helpers/logger., info/warn/error, payloads/JSON, saída/logging, simplicio/*.py, simplicio/mcp_server.py, simplicio/observability.py, simplicio/output.py, status/diagnóstico, status/progresso/erro, stderr/logger., stdout/stderr.**.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #107 — observability: integrate central logging with loop journal for unified evidence + MCP safety

- Estado/data: `closed`; criada `2026-07-07T04:27:44Z`; atualizada `2026-07-07T06:02:30Z`
- Labels: `enhancement, evidence, mcp, observability`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "P1", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

A issue #106 (centralizar output/logging) é excelente para proteger o caminho MCP e separar stdout (dados) de stderr (status). Porém, o ecossistema ganha ainda mais se essa camada de observability for **integrada com o journal/evidence do `simplicio-loop`**.

Hoje:
- dev-cli tem muitos `print()` soltos + risco de corromper framing MCP
- loop tem journal durável + evidence-gated exit
- Não há visão unificada de "o que aconteceu durante uma task executada via dev-cli dentro de um loop"

Isso perde oportunidade de ter um **evidence ledger** rico que agents (Claude Code, Cursor, etc.) possam consultar via MCP ou via `/simplicio-loop`.

## Objetivo

Estender a camada de logging centralizada do dev-cli para produzir eventos estruturados que o loop journal possa consumir, garantindo MCP safety total e criando um fluxo de evidence unificado entre executor (dev-cli) e orquestrador (loop).

## Escopo

1. Em `simplicio/observability.py` (ou novo módulo):
   - Definir `emit_event(event_type, payload, level="info")` que:
     - Escreve em stderr (legível)
     - Opcionalmente serializa para JSON estruturado (para consumo por journal)
     - Nunca escreve no stdout quando rodando como MCP server
   - Eventos sugeridos: `task_start`, `task_complete`, `evidence_captured`, `token_usage`, `edit_applied`, `validation_pass/fail`, `handoff`

2. Integrar com o journal do loop:
   - Quando dev-cli é invocado dentro de um loop, os eventos são anexados ao journal da task atual
   - Usar formato compatível com `loop_journal.py` (append-only, timestamp, structured)

3. Garantir proteção MCP:
   - Teste automatizado que prova que nenhum evento vaza para stdout durante execução do MCP server
   - Ruff rule ou lint para impedir `print()` / `sys.stdout.write` fora dos pontos permitidos

4. Atualizar `CLAUDE.md` / docs para mostrar o fluxo de evidence unificado.

5. Adicionar métrica básica de "tokens saved" quando possível (estimativa simples).

## Fora de escopo
- Implementar UI/dashboard de evidence (só o ledger estruturado)
- Mudar o formato do journal do loop
- Adicionar tracing distribuído completo (OpenTelemetry etc.)

## Critérios de aceite
- [ ] Camada central de observability existe e é usada por todos os módulos críticos (providers, pipeline, mapper integration, mcp_server).
- [ ] `simplicio-py doctor` ou comando similar mostra eventos de observability.
- [ ] Execução via MCP server não produz nenhuma linha extra no stdout além dos frames MCP válidos (teste automatizado verde).
- [ ] Eventos de dev-cli são consumíveis pelo journal do loop (formato documentado + teste de integração).
- [ ] `CLAUDE.md` descreve o fluxo de evidence unificado (dev-cli → journal do loop).
- [ ] Ruff/mypy passam; nenhuma regressão em testes existentes.
- [ ] Exemplo de output de evidence aparece na documentação.

## Prioridade sugerida
**P1** — transforma logging de "proteção técnica" em "evidence ledger de valor para agents", alinhado com a filosofia de evidence-gated do loop.

## Relacionado
- dev-cli #106 (central logging)
- loop #115 (contract de execution)
- Futuro: integração mais profunda com ai-memory / cross-vendor handoff

#### Objetivo

Entregar e provar o resultado delimitado por: observability: integrate central logging with loop journal for unified evidence + MCP safety

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Ruff/mypy, UI/dashboard, journal/evidence, output/logging, simplicio/observability.py, validation_pass/fail.

#### Dependências e ordem

Referências explícitas: #106, #115. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #111 — observability: savings por verbo de delegação native-vs-python + token budget guard no CI

- Estado/data: `closed`; criada `2026-07-09T15:52:55Z`; atualizada `2026-07-09T17:19:11Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

A delegação nativa está madura (`simplicio/runtime_bridge.py`; `gate`, `nest`, `edit`, `file read`, `test run` delegam com fallback e kill-switches `SIMPLICIO_BIN`/`SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT`/`--native`/`--python`), mas é **invisível**: `record_savings_event` (`simplicio/observability.py:~180`) mede por *source* (ex.: TOON), não pela decisão native-vs-python por verbo. Hoje não dá para responder "qual % das execuções foi pelo caminho nativo?" nem "quanto cada verbo delegado economizou?" — exatamente o número necessário para dirigir a meta de subir o native path de ~10-11% para 40-60%+ nas tarefas típicas.

Segunda lacuna: não há token/context budget guard neste repo (o padrão existe no simplicio-loop: `scripts/token_budget.py` + baseline, CI-enforced).

## Escopo

- Instrumentar `route_command`/`try_route_via_simplicio` (`simplicio/commands/__init__.py`, `commands/_shared.py`) e os call sites diretos (`commands/edit.py`, `file_read.py`, `test_run.py`) para registrar por invocação: verbo, rota tomada (native | python-fallback | python-forçado), motivo do fallback quando houver, e savings (`record_savings_event` com `source="native-delegation:<verbo>"`).
- Agregado exposto em `simplicio-py doctor` (humano e `--json`): % de execuções via native path por verbo + total, a partir do ledger/events existentes (`events_summary()` como base).
- Portar o token budget guard do loop: `scripts/token_budget.py` + baseline committed cobrindo AGENTS.md/CLAUDE.md e os maiores módulos de `simplicio/`; ligado no job `lint`/`python` do `ci.yml`.
- Resolver a inconsistência documentada: o docstring do roteador declara `score-skill` delegável, mas não há call site — ou ligar, ou corrigir o docstring.

## Critérios de aceite

- [ ] Cada invocação de verbo delegável gera registro com rota + motivo; nenhum `print()` (regra ruff T20 — usar `observability`).
- [ ] `simplicio-py doctor --json` responde o % native path por verbo e total; evidência real no PR (stdout capturado, critério de evidência do repo).
- [ ] Savings por verbo no schema `simplicio.savings-event/v1` com proof-kind honesto (`measured` quando derivado de medição real; `estimated` explícito caso contrário).
- [ ] `scripts/token_budget.py` + baseline no CI; regressão de tamanho falha o job (teste negativo no PR).
- [ ] `score-skill`: delegação ligada OU docstring corrigido (decisão registrada).
- [ ] `pytest`, `ruff check .`, `ruff format --check .`, `mypy simplicio` verdes.

## Referências

`simplicio/runtime_bridge.py`, `simplicio/commands/__init__.py` + `_shared.py`, `simplicio/observability.py` (#106/#107), simplicio-loop `scripts/token_budget.py` (#121 de lá), simplicio-runtime `docs/SAVINGS_EVENT_SPEC.md` (#2775 de lá).

#### Objetivo

Entregar e provar o resultado delimitado por: observability: savings por verbo de delegação native-vs-python + token budget guard no CI

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: AGENTS.md/CLAUDE.md, commands/_shared.py, commands/edit.py, docs/SAVINGS_EVENT_SPEC.md, ledger/events, scripts/token_budget.py, simplicio.savings-event/v1, simplicio/commands/__init__.py, simplicio/observability.py, simplicio/runtime_bridge.py, token/context.

#### Dependências e ordem

Referências explícitas: #106, #121, #2775. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #113 — [P0] Contrato version/capability, dogfood real e promoção de release

- Estado/data: `closed`; criada `2026-07-09T23:18:51Z`; atualizada `2026-07-12T03:13:37Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Parent: wesleysimplicio/simplicio-runtime#2998

## Problemas medidos
Consumidores esperam `--version --json`, mas o dev-cli não possui esse comando; mínimos divergem; cross-repo dogfood documenta substituições em vez de executar operadores reais; publish ocorre sem promoção segura.

## Critérios de aceite
- [ ] Comando canônico de version/capability é definido e todos os consumidores concordam.
- [ ] Runtime/Agent homônimo ou versão antiga falham com diagnóstico acionável.
- [ ] `task` usa Runtime real, mapper context e verificação, sem hop substituído.
- [ ] #89 é ampliada com init/migrate/seed idempotente e backend neural existente.
- [ ] Clean-wheel smoke, lint, mypy, pytest e contracts bloqueiam.
- [ ] Publish só após CI verde e cria GitHub Release coerente.
- [ ] Benchmark registra tokens/retries/latência com proof_kind honesto.

## Dependências
Identidade Runtime, mapper lock/contract e CI.

## Evidência
E2E instalado, pacote publicado e receipts do operador.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0] Contrato version/capability, dogfood real e promoção de release

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Runtime/Agent, init/migrate/seed, lock/contract, tokens/retries/latência, version/capability, wesleysimplicio/simplicio-runtime.

#### Dependências e ordem

Referências explícitas: #89. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #114 — [P0][EPIC] Task-to-Delivery v2: de card bruto a entrega integrada e comprovada

- Estado/data: `closed`; criada `2026-07-10T16:14:58Z`; atualizada `2026-07-13T19:28:32Z`
- Labels: `enhancement, roadmap, tracking`
- Classificação: `{"component": "runtime", "epic": "[EPIC]", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## North Star

Permitir que uma pessoa entregue **uma task completa ou várias tasks brutas** (texto, Markdown, stdin, arquivo ou URL suportada) e que o Simplicio:

1. normalize cada card sem perder contexto;
2. extraia AC, regras de negócio, NFRs, dependências, impacto, anexos e incertezas;
3. mapeie o repositório e proponha um plano rastreável;
4. execute cada slice com o operador correto;
5. prove cada AC com teste/evidência;
6. só declare conclusão quando task, integrações e DoD estiverem comprovados.

Exemplo de referência: task PLANES “Tela de Modelagem — Ordenação de linhas”, com AC1–AC5 e RN01–RN03.

## Diagnóstico medido em 2026-07-10

- O exemplo PLANES foi classificado por `simplicio-py detect --json` como `scope=feature`, mas `is_code_task=false` e score 1; portanto o hook automático não o encaminha.
- `simplicio-py task` exige `--target`; `run --scope feature` exige `--stack`. Os defaults de contrato ainda são `- true state\n- false state`, em vez de extrair os AC da entrada ([cli.py](https://github.com/wesleysimplicio/simplicio-dev-cli/blob/master/simplicio/cli.py#L126-L166)).
- O sprint loader lê arquivos pré-posicionados e reduz cada card a título + goal; AC, RN, NFR, protótipo, acesso, dependências e sinais de impacto não viram campos estruturados ([sprint_loader.py](https://github.com/wesleysimplicio/simplicio-dev-cli/blob/master/simplicio/sprint_loader.py)).
- O schema do planner guarda `criteria` e `constraints` como strings livres, sem IDs de origem/traceability ([plan_schema.py](https://github.com/wesleysimplicio/simplicio-dev-cli/blob/master/simplicio/scratch/plan_schema.py)).
- O pipeline usa `echo 'configure SIMPLICIO_TEST_CMD'` como fallback de teste; retries aplicam patches diretamente no worktree sem transação explícita/rollback; impacto ausente é tratado como “no impact tests” e pode concluir ([pipeline.py](https://github.com/wesleysimplicio/simplicio-dev-cli/blob/master/simplicio/pipeline.py#L41-L139), [pipeline.py](https://github.com/wesleysimplicio/simplicio-dev-cli/blob/master/simplicio/pipeline.py#L314-L330)).
- `runtime doctor` reserva o binário `simplicio`, mas no ambiente auditado esse nome aponta ao Simplicio Agent/Hermes; falta handshake de capability. Cobertura existente: #113.
- A documentação ainda atribui MCP a `simplicio/mcp_server.py`, mas esse módulo não existe no tree atual. Cobertura planejada: #89.
- Testes focados: 46 passaram e 1 falhou em Windows (`test_nest_build_records_native_when_binary_available`, WinError 193).
- As execuções recentes de CI do `master` estão vermelhas; exemplo: https://github.com/wesleysimplicio/simplicio-dev-cli/actions/runs/29037580737.

## Lacuna de produto

O produto entrega bem o **primitivo atômico quando goal, target, stack, criteria e test command já foram preparados por outra camada**. Ele ainda não entrega o contrato “cole a task e deixe a IA concluir 100%” sem trabalho manual e sem dependência de convenções externas.

## Épicos/filhos

- [ ] #115 — Intake universal + TaskSpec v2
- [ ] #116 — Compilador de AC/RN/NFR com rastreabilidade e human gates
- [ ] #117 — Orientação automática do repo + ExecutionPlan congelado
- [ ] #118 — Execução transacional, rollback e verification fail-closed
- [ ] #119 — Orquestração de várias tasks com DAG, resume e isolamento
- [ ] #120 — Evidence ledger por AC + UI/E2E/protótipos
- [ ] #121 — Benchmark e release gate realista (PLANES + corpus multi-task)
- [ ] Integrar/fechar #113 (runtime capability/identidade)
- [ ] Integrar/fechar #89 (MCP/cross-vendor)

## Definition of Done do épico

- [ ] Uma única invocação aceita o texto PLANES sem flags de `target`, `criteria` ou `stack` e produz TaskSpec validada antes de editar.
- [ ] AC1–AC5 e RN01–RN03 aparecem no plano, nos testes e no relatório final com IDs estáveis.
- [ ] “Backend: possível” e “validar com o time” viram incertezas/human gates, não suposições silenciosas.
- [ ] Um lote com várias tasks cria DAG determinística, isola falhas e retoma sem repetir items concluídos.
- [ ] Nenhum sucesso é possível sem test command real e receipts por AC.
- [ ] Falha/retry não deixa patch parcial no branch do usuário.
- [ ] Mapper, runtime, loop e MCP passam contratos de integração com capability handshake.
- [ ] Benchmark live mede conclusão correta, regressões, retries, tokens, custo e evidências em mais de um modelo/provider.
- [ ] CI, clean-wheel smoke e release gates estão verdes.

## Fora de escopo

Implementar as melhorias nesta issue. Este item é apenas o contrato pai e a ordem do trabalho.

## Relações

Continua/completa #41 e #93. Reusa #113 e #89 em vez de duplicá-las.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][EPIC] Task-to-Delivery v2: de card bruto a entrega integrada e comprovada

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: AC/RN/NFR, Agent/Hermes, Continua/completa, Falha/retry, Integrar/fechar, MCP/cross-vendor, UI/E2E/protótipos, capability/identidade, explícita/rollback, github.com/wesleysimplicio/simplicio-dev-cli/actions/runs/29037580737., github.com/wesleysimplicio/simplicio-dev-cli/blob/master/simplicio/cli.py, github.com/wesleysimplicio/simplicio-dev-cli/blob/master/simplicio/pipeline.py, github.com/wesleysimplicio/simplicio-dev-cli/blob/master/simplicio/scratch/plan_schema.py, github.com/wesleysimplicio/simplicio-dev-cli/blob/master/simplicio/sprint_loader.py, incertezas/human, modelo/provider., origem/traceability, simplicio/mcp_server.py, teste/evidência, Épicos/filhos.

#### Dependências e ordem

Referências explícitas: #41, #89, #93, #113, #115, #116, #117, #118, #119, #120, #121. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #115 — [P0] Intake universal: TaskSpec v2 para uma ou várias tasks brutas

- Estado/data: `closed`; criada `2026-07-10T16:16:26Z`; atualizada `2026-07-10T19:06:33Z`
- Labels: `enhancement`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Parent: #114

## Problema

A entrada atual é orientada a flags (`goal`, `target`, `criteria`, `constraints`) e o sprint loader pressupõe arquivos já organizados. Uma task rica como PLANES perde estrutura; várias tasks coladas não viram items independentes.

## Objetivo

Criar uma etapa de intake determinística, sem editar código, que aceite texto/Markdown via argumento, stdin ou arquivo e produza `simplicio.task-spec/v2`. Adaptadores de URL (GitHub/Jira/Linear etc.) devem usar o mesmo schema quando disponíveis, sem acoplar o core a um fornecedor.

## Schema mínimo

- `task_id`, `source`, `source_hash`, `language`
- sistema, funcionalidade, tipo e narrativa COMO/QUERO/PARA
- `acceptance_criteria[]` com ID estável, Given/When/Then e refs de RN
- `business_rules[]`, `non_functional_requirements[]`
- protótipos/anexos como referências preservadas
- acesso/navigation
- dependências explícitas e inferidas (marcadas como hipótese)
- sinais de impacto por camada
- informações adicionais
- `uncertainties[]` e `human_gates[]`
- suporte a `tasks[]` para lote, preservando fronteiras e ordem da fonte

## Critérios de aceite

- [ ] Uma única invocação aceita a task PLANES completa sem `--target`, `--criteria` ou `--stack`.
- [ ] O JSON contém AC1–AC5 e RN01–RN03 sem perda, duplicação ou renumeração instável.
- [ ] “Backend: possível” permanece hipótese; “validar com o time” vira incerteza/gate.
- [ ] Um documento com 3 cards produz exatamente 3 TaskSpecs, cada uma com `source_hash` próprio.
- [ ] Parser suporta pt-BR e inglês e preserva texto original/source spans.
- [ ] Entrada malformada falha com diagnóstico acionável e não chama LLM nem operador de edição.
- [ ] Existe modo `--validate-only --json`.
- [ ] Golden tests cobrem PLANES, card mínimo, múltiplos cards, seções ausentes, anexos e encoding Windows/UTF-8.
- [ ] O schema é versionado e possui contrato de compatibilidade para runtime/loop/MCP.

## Fora de escopo

Planejar ou editar o repositório. Esta issue termina na TaskSpec validada.

## Dependências

Nenhuma para o parser core. Adaptadores remotos podem depender de #89/#113.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0] Intake universal: TaskSpec v2 para uma ou várias tasks brutas

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: COMO/QUERO/PARA, GitHub/Jira/Linear, Given/When/Then, Windows/UTF-8., acesso/navigation, incerteza/gate., original/source, protótipos/anexos, runtime/loop/MCP., simplicio.task-spec/v2, texto/Markdown.

#### Dependências e ordem

Referências explícitas: #89, #114. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #116 — [P0] Compilador de contrato: rastreabilidade AC↔RN↔teste↔evidência e human gates

- Estado/data: `closed`; criada `2026-07-10T16:16:27Z`; atualizada `2026-07-10T19:06:32Z`
- Labels: `enhancement`
- Classificação: `{"component": "plandag", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Parent: #114
Depends on: intake TaskSpec v2

## Problema

Hoje `criteria` é string livre e possui default genérico `true state/false state`. O pipeline consegue passar sem provar que cada AC/RN da fonte foi implementado. Incertezas podem ser silenciosamente convertidas em suposições.

## Objetivo

Compilar a TaskSpec em um `ExecutionContract` imutável e rastreável antes do primeiro edit.

## Regras

- Cada AC/RN/NFR recebe ID estável e mantém backlink para source span.
- Cada AC deve apontar para pelo menos um plano de verificação executável.
- Critérios vagos/placeholders são erro, não default.
- Contradições, campos ausentes e regras não decididas geram `human_gate`; o compilador não inventa regra.
- Alteração do texto-fonte invalida o contrato congelado e exige re-anchor.
- Hipótese nunca pode ser promovida a fato sem receipt.

## Critérios de aceite

- [ ] O contrato PLANES representa AC1–AC5, RN01–RN03 e a ordem combinada.
- [ ] O compilador identifica ao menos as decisões não especificadas: empate de datas, data ausente/inválida, collation/acentos/case na ordem alfabética e comportamento se houver mais de uma estrutural.
- [ ] “Nenhum NFR identificado — validar com o time” e “Backend possível — a definir” viram gates/hypotheses explícitos.
- [ ] Nenhuma execução inicia enquanto houver gate marcado `blocking`.
- [ ] Cada AC possui `verification_intents[]` (unit/integration/E2E/visual) e critérios true/false/borda.
- [ ] `criteria="- true state\n- false state"` e test command placeholder são rejeitados em execução real.
- [ ] JSON de resultado contém matriz `AC → RN → files → tests → evidence → status`.
- [ ] Contract tests provam que remover RN02 ou um cenário torna o gate vermelho.
- [ ] Claims sem receipt são rotuladas UNVERIFIED e não fecham a task.

## Fora de escopo

Descobrir arquivos ou aplicar patches; isso pertence ao planner/executor.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0] Compilador de contrato: rastreabilidade AC↔RN↔teste↔evidência e human gates

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: AC/RN, AC/RN/NFR, ausente/inválida, collation/acentos/case, gates/hypotheses, planner/executor., state/false, true/false/borda., unit/integration/E2E/visual, vagos/placeholders.

#### Dependências e ordem

Referências explícitas: #114. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #117 — [P0] Orientação autônoma: descobrir stack, targets, fluxo e testes antes de executar

- Estado/data: `closed`; criada `2026-07-10T16:16:28Z`; atualizada `2026-07-12T03:13:34Z`
- Labels: `enhancement`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Parent: #114
Depends on: TaskSpec v2 + ExecutionContract

## Problema

O caminho atual exige que o humano informe `--stack` e/ou `--target`. Para a experiência “envie apenas a task”, o sistema precisa descobrir onde a regra vive e quais superfícies serão afetadas sem adivinhar.

## Objetivo

Produzir um `ExecutionPlan` congelado usando mapper + contexto operacional do projeto antes de chamar qualquer LLM executor.

## Fluxo esperado

`scan/status → inspect → handoff → ask impact/tests-for/callers/flows/rules → ler arquivos apontados → propor slices → freeze`.

## Critérios de aceite

- [ ] PLANES pode ser planejada sem flags de stack/target.
- [ ] O planner identifica fluxo UI → state/query → API/backend quando existir e registra por que a ordenação será feita em cada camada.
- [ ] “Frontend: sim / Backend: possível” resulta em investigação mensurável; não em escolha arbitrária.
- [ ] Cada slice tem target(s), AC/RN cobertos, precedentes, testes, comando de verify, dependências e blast radius.
- [ ] Arquivo/shared contract com dependentes não revisados bloqueia o plano.
- [ ] Mapper ausente, stale ou artifact incompleto bloqueia com ação de recuperação; não cai para survey improvisado.
- [ ] Multi-repo é representado explicitamente e aponta qual operador atua em cada repo.
- [ ] Existe `--plan-only --json` que não altera o worktree e inclui `plan_hash`/`pack_hash`.
- [ ] Mudança do repo ou da TaskSpec após freeze invalida o plano.
- [ ] Testes cobrem descoberta frontend-only, backend-sorted, full-stack, monorepo e target ambíguo.

## Integração

O runtime/loop decide e agenda; mapper orienta; dev-cli executa apenas slices decididos. Reusar #113 para capability/identity handshake.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0] Orientação autônoma: descobrir stack, targets, fluxo e testes antes de executar

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: AC/RN, API/backend, Arquivo/shared, capability/identity, e/ou, impact/tests-for/callers/flows/rules, runtime/loop, scan/status, stack/target., state/query.

#### Dependências e ordem

Referências explícitas: #113, #114. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #118 — [P0] Executor transacional fail-closed: testes obrigatórios, rollback e retries idempotentes

- Estado/data: `closed`; criada `2026-07-10T16:16:29Z`; atualizada `2026-07-17T06:20:26Z`
- Labels: `enhancement`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **CLOSE-READY**

#### Contexto e problema

Parent: #114
Completes: #93
Related: #113

## Problema medido

- O fallback atual de `SIMPLICIO_TEST_CMD` é `echo 'configure SIMPLICIO_TEST_CMD'`, que retorna 0.
- O patch é aplicado diretamente antes do teste.
- Uma falha não restaura explicitamente o estado anterior antes do retry.
- O static fixer pode voltar ao mesmo caminho de apply.
- Impacto não calculável/no callers/no tests pode concluir como sucesso.

## Objetivo

Cada tentativa deve acontecer numa transação isolada e só promover mudanças ao branch alvo após todos os gates verdes.

## Critérios de aceite

- [ ] Execução real sem test command concreto falha antes de gerar/aplicar patch.
- [ ] Cada attempt usa worktree/snapshot transacional com base SHA e dirty-tree policy explícita.
- [ ] Falha de apply, teste, impacto, docs/flow gate ou timeout descarta a tentativa sem tocar alterações preexistentes do usuário.
- [ ] Retry parte do estado promovido mais recente e não reaplica o mesmo patch sobre si próprio.
- [ ] Teste gerado faz parte do diff permitido; não fica apenas como bloco textual `TEST:`.
- [ ] Primary tests, tests-for callers e gates requeridos pelo ExecutionContract precisam de receipts.
- [ ] `UNVERIFIED`, mapper indisponível, no-tests e placeholder nunca equivalem a PASS.
- [ ] Após sucesso, promoção é atômica e registra files, hashes, comandos, exit codes e output tails.
- [ ] Falha após N tentativas deixa branch do usuário byte-for-byte igual ao início, exceto artifacts de log em local separado/ignorado.
- [ ] Testes cobrem patch parcial, segunda tentativa, fixer, conflito, timeout e worktree inicialmente dirty.
- [ ] Windows, Linux e macOS passam o mesmo contrato; corrigir a regressão WinError 193 observada em `test_native_delegation.py`.

## Fora de escopo

Commit/push/PR automático.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0] Executor transacional fail-closed: testes obrigatórios, rollback e retries idempotentes

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Commit/push/PR, calculável/no, callers/no, docs/flow, gerar/aplicar, separado/ignorado., worktree/snapshot.

#### Dependências e ordem

Referências explícitas: #93, #113, #114. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #119 — [P0] Orquestração multi-task: DAG, isolamento, resume e conclusão por item

- Estado/data: `closed`; criada `2026-07-10T16:16:30Z`; atualizada `2026-07-12T03:13:31Z`
- Labels: `enhancement`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Parent: #114
Continues: #41
Depends on: TaskSpec v2, ExecutionContract, ExecutionPlan, executor transacional

## Problema

O modo sprint atual exige `.specs/sprints/sprint-XX/*.task.md` já preparado e transforma cada arquivo em feature. Não existe intake direto de vários cards brutos com dependências, isolamento e conclusão comprovada por item.

## Objetivo

Aceitar `tasks[]`, construir/fixar uma DAG e drenar a fila de modo determinístico com simplicio-loop/runtime/dev-cli.

## Critérios de aceite

- [ ] Um documento com N cards cria N items estáveis antes da execução.
- [ ] Dependências explícitas e inferidas são validadas; ciclos, IDs desconhecidos e ambiguidades bloqueiam.
- [ ] Cada item possui anchor/contract próprios e não pode consumir AC de outra task.
- [ ] Tasks independentes podem rodar em worktrees isolados; tasks dependentes aguardam promoção da predecessora.
- [ ] Falha de uma task é quarantined/blocked com evidência e não corrompe items concluídos.
- [ ] Resume usa source_hash + plan_hash + base SHA; não repete item já comprovado nem aceita estado stale.
- [ ] Novas tasks que chegam durante drain são detectadas antes da conclusão; fila vazia precisa permanecer vazia por rounds determinísticos.
- [ ] Status JSON mostra pending/running/passed/blocked, dependências, custo, attempts e receipts.
- [ ] Conclusão global exige todas as tasks em estado terminal aceito e todos os gates de integração/DoD verdes.
- [ ] Cancel/STOP encerra entre attempts sem processos/worktrees órfãos.
- [ ] Testes cobrem lote misto, DAG, paralelismo, falha parcial, retomada, task alterada e late arrival.

## Integração

`simplicio-loop` é o driver de re-feed/evidence gate; runtime coordena; mapper orienta; dev-cli opera slices.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0] Orquestração multi-task: DAG, isolamento, resume e conclusão por item

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .specs/sprints/sprint-XX/*.task.md, Cancel/STOP, anchor/contract, construir/fixar, integração/DoD, pending/running/passed/blocked, processos/worktrees, quarantined/blocked, re-feed/evidence, simplicio-loop/runtime/dev-cli..

#### Dependências e ordem

Referências explícitas: #41, #114. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #120 — [P1] Evidence ledger por AC: UI/E2E, protótipos, anexos e relatório final

- Estado/data: `closed`; criada `2026-07-10T16:16:31Z`; atualizada `2026-07-12T03:13:29Z`
- Labels: `enhancement`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P1", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **CLOSE-READY**

#### Contexto e problema

Parent: #114
Depends on: ExecutionContract + executor transacional
Related: #107, #89

## Problema

O prompt atual pede um script Playwright ou `N/A`, mas gerar texto não prova que a interface real funcionou. A task PLANES é visual e precisa demonstrar ordenação combinada por usina/tipo/data.

## Objetivo

Criar um evidence ledger append-only em que cada claim de conclusão aponte para receipts reais e artifacts verificáveis.

## Critérios de aceite

- [ ] Cada AC/RN possui pelo menos um receipt com command, exit code, timestamp, environment, commit/base SHA e artifact hash.
- [ ] Para PLANES, a prova E2E cobre:
  - usinas em ordem alfabética;
  - estrutural primeiro;
  - temporal/modelagem misturados pela data;
  - regra combinada em múltiplas usinas;
  - borda e caminho de erro definidos no contrato.
- [ ] Mudança visual executa Playwright real e salva trace + screenshot + video conforme política do projeto.
- [ ] Protótipo/anexo de entrada é preservado, acessível ao planner e ligado ao cenário que ele informa.
- [ ] Evidência stale (base SHA/plan hash divergente) é rejeitada.
- [ ] O watcher independente reexecuta/recalcula a matriz de AC antes do sucesso.
- [ ] O relatório final distingue MEASURED de UNVERIFIED e não permite claim sem receipt.
- [ ] Saída JSON é consumível pelo loop journal/runtime/MCP sem poluir stdout.
- [ ] PR template pode renderizar automaticamente a matriz AC → receipt.
- [ ] Testes de contrato cobrem artifact ausente, hash alterado, screenshot de cenário errado e watcher mismatch.

## Fora de escopo

Dashboard visual; o ledger e os artifacts são suficientes nesta fase.

#### Objetivo

Entregar e provar o resultado delimitado por: [P1] Evidence ledger por AC: UI/E2E, protótipos, anexos e relatório final

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: AC/RN, N/A, Protótipo/anexo, SHA/plan, commit/base, journal/runtime/MCP, reexecuta/recalcula, temporal/modelagem, usina/tipo/data..

#### Dependências e ordem

Referências explícitas: #89, #107, #114. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #121 — [P1] Corpus e release gate: provar PLANES e lotes multi-task cross-provider

- Estado/data: `closed`; criada `2026-07-10T16:16:32Z`; atualizada `2026-07-12T03:13:27Z`
- Labels: `enhancement`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P1", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Parent: #114
Depends on: todas as issues funcionais do épico
Related: #113

## Problema

Benchmarks existentes provam principalmente o efeito do prompt/primitivo atômico. Eles não provam o North Star “colar uma ou várias tasks ricas e receber entrega integrada 100%”.

## Objetivo

Criar corpus, harness e gate de release end-to-end para medir intake, planejamento, execução, integração e evidência.

## Corpus mínimo

- PLANES ordenação de linhas (card rico pt-BR).
- Task mínima com target explícito.
- Feature full-stack ambígua.
- UI com protótipo/anexo.
- Backend-only.
- Lote com DAG.
- Lote com uma task bloqueada.
- Task com NFR/dependência ausente.
- Monorepo/multi-repo.
- Casos negativos: AC contraditório, data inválida, no tests, mapper stale, runtime errado.

## Critérios de aceite

- [ ] Harness roda o fluxo real, sem stubs no caminho de integração medido.
- [ ] Existe lane de referência com GPT-5.4 medium configurado via Simplicio Runtime e lane local/fallback suportada.
- [ ] Métricas: preservação de campos, AC recall/precision, plano válido, implementação correta, regressões, receipts, retries, latência, tokens e custo.
- [ ] Score de “concluída” exige comportamento correto + todos os AC comprovados; parse/diff shape isolado não basta.
- [ ] Resultado diferencia standalone dev-cli, runtime+dev-cli e runtime+loop+dev-cli.
- [ ] Falha de runtime identity/capability é detectada, não contada como resultado do dev-cli.
- [ ] Windows/Linux passam; inclui regressão WinError 193.
- [ ] CI roda corpus determinístico sem provider pago e job live agendado para lanes remotas.
- [ ] Release é bloqueada se contratos, corpus determinístico, clean wheel, lint, mypy, pytest ou docs drift falharem.
- [ ] README/architecture/docs são geradas/checadas contra as capabilities reais; nenhuma referência a módulo/feature ausente.
- [ ] Relatório publica raw artifacts e `proof_kind` honesto, sem headline “100%” baseada em subset.

## Evidência atual

Master está com execuções recentes vermelhas, incluindo https://github.com/wesleysimplicio/simplicio-dev-cli/actions/runs/29037580737.

#### Objetivo

Entregar e provar o resultado delimitado por: [P1] Corpus e release gate: provar PLANES e lotes multi-task cross-provider

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Monorepo/multi-repo., NFR/dependência, README/architecture/docs, Windows/Linux, geradas/checadas, github.com/wesleysimplicio/simplicio-dev-cli/actions/runs/29037580737., identity/capability, local/fallback, módulo/feature, parse/diff, prompt/primitivo, protótipo/anexo., recall/precision.

#### Dependências e ordem

Referências explícitas: #113, #114. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #122 — [P1][Diagnostics] dev-cli dry-run-task should emit structured blocked-precondition receipts

- Estado/data: `closed`; criada `2026-07-10T18:22:03Z`; atualizada `2026-07-11T01:03:36Z`
- Labels: `nenhuma`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "P1", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Parent: #113

## Problem

In the governed run, `simplicio-dev-cli task --dry-run-task --json` failed closed for Agent targets, but the result was too opaque to act on quickly:

- the command returned an error/hash,
- the surrounding state indicated missing artifacts / no handoff targets / broader-context needs,
- the operator still had to inspect external state to understand whether the failure was target resolution, artifact freshness, handoff readiness, or another precondition.

For a control-plane tool, this is too lossy. A fail-closed result should still explain the blocked preconditions precisely.

## Expected behavior

`--dry-run-task --json` should emit structured blocked-precondition information when it refuses to proceed.

## Acceptance criteria

- `simplicio-dev-cli task --dry-run-task --json` returns machine-readable blocked reasons for common precondition failures.
- Target resolution failure, missing artifacts, stale artifacts, missing handoff targets, and broader-context requirements are distinguishable in the JSON output.
- The command still fails closed, but the receipt is actionable without external guesswork.
- The JSON contract names the next expected surface (for example mapper artifacts, handoff target, context pack, etc.).
- At least one focused example demonstrates the blocked receipt for an artifact/handoff failure.
- Documentation or help output references the blocked-precondition schema.

## Measured evidence

- In the active run, `task --dry-run-task --json` failed closed with an error hash while Agent lanes were also reporting `artifacts_missing` and `no_handoff_targets`.
- The operator had to correlate multiple sources manually to understand the real blocker.

## Scope

This issue is about diagnostic fidelity of fail-closed dry-run receipts. It is not about widening permissions or bypassing safety.

#### Objetivo

Entregar e provar o resultado delimitado por: [P1][Diagnostics] dev-cli dry-run-task should emit structured blocked-precondition receipts

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: artifact/handoff, error/hash.

#### Dependências e ordem

Referências explícitas: #113. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #126 — [HANDOFF] Auditoria consolidada e backlog restante pós-PR125 (2026-07-10)

- Estado/data: `closed`; criada `2026-07-10T19:34:18Z`; atualizada `2026-07-11T07:00:41Z`
- Labels: `nenhuma`
- Classificação: `{"component": "quality", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Estado consolidado em 2026-07-10

### Publicado/mergeado nesta rodada
- PR #124 — `Add task intake and fail-closed execution contracts` (MERGED)
- Issues #115 e #116 foram concluídas e fechadas antes desta consolidação

### Em PR agora
- PR #125 — `feat: publish verify receipts and blocked dry-run diagnostics`
  - `36a3f32` Surface primary verify receipts in task contracts
  - `19e58fb` Fail closed dry-run task with blocked receipts

### Slices concluídos no branch atual
- executor transacional roda tentativas em workspace isolado
- receipts persistidos para falha de apply, timeout e verificação primária
- retries reiniciam do último estado promovido
- worktree dirty do usuário é preservado
- testes nativos/delegação estabilizados no Windows
- impacto passa a expor receipt estruturado
- verificação primária passa a expor receipt estruturado no `task result` e no `task_contract`
- `task --dry-run-task --json` agora falha fechado com `blocked_preconditions` estruturado

### Evidência medida usada nesta consolidação
- PR #125 aberta contra `master`
- comentários de progresso já registrados em #118 e #122
- testes focados executados para verify receipts e dry-run blocked receipts

### O que ainda falta
#### #118 — Executor transacional fail-closed
Ainda aberto porque o contrato mais amplo continua pendente, incluindo pelo menos:
- fechamento completo dos critérios de aceite cross-platform do executor
- prova completa de gates adicionais além dos receipts já publicados
- auditoria final dos ACs restantes antes de fechar

#### #122 — dry-run blocked receipts
Ainda aberto porque falta:
- fechamento do contrato mais amplo de receipts/docs/help
- exemplo/documentação canônica do schema bloqueado
- auditoria final dos cenários bloqueados cobertos vs. esperados

#### Backlog maior ainda aberto
- #117 orientação autônoma antes de executar
- #119 orquestração multi-task com DAG/isolamento/resume
- #120 evidence ledger por AC
- #121 corpus e release gate multi-task cross-provider
- #113 contrato version/capability e promoção de release
- #114 epic task-to-delivery v2

### Próxima retomada sugerida
1. decidir se a próxima frente é fechar #122 por completo ou voltar para #117/#119
2. revisar o PR #125 e mergear se os checks passarem
3. depois reavaliar fechamento parcial de #118/#122 com evidência de critérios restantes

#### Objetivo

Entregar e provar o resultado delimitado por: [HANDOFF] Auditoria consolidada e backlog restante pós-PR125 (2026-07-10)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: DAG/isolamento/resume, Publicado/mergeado, exemplo/documentação, nativos/delegação, receipts/docs/help, version/capability.

#### Dependências e ordem

Referências explícitas: #113, #114, #115, #116, #117, #118, #119, #120, #121, #122, #124, #125. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #127 — [P1][PR Hygiene] Normalize PR #125 rebase/conflict state

- Estado/data: `closed`; criada `2026-07-10T19:46:52Z`; atualizada `2026-07-10T19:58:59Z`
- Labels: `nenhuma`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "P1", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Problema medido

O PR #125 está aberto, mas não está pronto para merge por estado de branch:

- `mergeStateStatus=DIRTY`
- tentativa de rebase/reconstrução em clone temporário confirmou conflito manual real
- os conflitos aparecem logo no primeiro slice relevante pós-merge em:
  - `simplicio/pipeline.py`
  - `tests/python/test_mapping_retry_flow.py`

Também não há feedback visível de review acionável no momento; o blocker atual é mergeabilidade/rebase, não requested changes.

## Impacto

- o branch não pode avançar honestamente para merge sem resolução manual dos conflitos;
- o handoff #126 registra isso, mas não substitui uma issue específica para o trabalho de normalização do PR;
- enquanto esse blocker estiver implícito, a retomada futura tende a reabrir a mesma investigação.

## Critérios de aceite

- [ ] Resolver os conflitos de rebase do PR #125 contra `master`.
- [ ] Preservar os slices já publicados no branch (`verify receipts`, `blocked dry-run receipts`) sem reintroduzir o histórico antigo de PR #124.
- [ ] Rerodar o pacote focado de testes do pipeline/contract após a resolução.
- [ ] Atualizar o PR #125 para sair de `DIRTY` e voltar a um caminho de merge verificável.
- [ ] Reavaliar então se #118 e #122 continuam abertas integralmente ou podem ser parcialmente fechadas.

## Evidência

- Handoff #126 já documenta o estado `DIRTY`.
- Rebase em clone temporário encontrou conflito manual em `simplicio/pipeline.py` e `tests/python/test_mapping_retry_flow.py`.
- `gh pr view --comments` não mostrou feedback textual acionável de review até aqui.

#### Objetivo

Entregar e provar o resultado delimitado por: [P1][PR Hygiene] Normalize PR #125 rebase/conflict state

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: mergeabilidade/rebase, pipeline/contract, rebase/reconstrução, simplicio/pipeline.py, tests/python/test_mapping_retry_flow.py.

#### Dependências e ordem

Referências explícitas: #118, #122, #124, #125, #126. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #129 — [P0][Operator] Codex CLI patch extraction must recover corrupt/stale unified diffs deterministically

- Estado/data: `closed`; criada `2026-07-11T00:05:16Z`; atualizada `2026-07-12T03:13:25Z`
- Labels: `nenhuma`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Problema medido

`simplicio-dev-cli task` com `SIMPLICIO_MODEL=codex-cli/gpt-5.6-luna` gera conteúdo para o arquivo correto, mas o pipeline de extração/aplicação devolve patches inválidos e consome todos os 5 retries.

## Reprodução

Target: `tests/test_runner_cli.py` em `simplicio-loop` atualizado no commit `8440c2be`.

Resultado terminal:

```text
validation_fail attempts=5
git apply --check failed: corrupt patch at <stdin>:72
git apply --recount --check failed: patch failed: tests/test_runner_cli.py:255
files_changed=["tests/test_runner_cli.py"]
applied=false
```

A mesma lane com MiniCPM5 falhava antes por ausência total de unified diff. Após atualizar Codex CLI 0.142.5 -> 0.144.1, `gpt-5.6-luna`/medium/fast passou no probe `MODEL_OK`, isolando a falha no contrato de diff/apply do Dev CLI.

## Impacto

- bloqueia o operador obrigatório do `simplicio-loop`;
- queima cinco chamadas de modelo por mudança sem aplicar nada;
- impede testes/docs da issue loop#144 e qualquer drain autônomo confiável.

## Critérios de aceite

- [ ] Extrair de forma estável o unified diff/final artifact produzido por Codex CLI atual.
- [ ] Normalizar/recontar hunks sem aceitar patch ambíguo ou fora do target.
- [ ] Se o modelo devolve conteúdo completo do target, produzir diff determinístico contra o arquivo atual ou falhar com reason code específico, sem 5 retries idênticos.
- [ ] Rebasear contexto a cada retry para não reaplicar hunks obsoletos.
- [ ] Adicionar fixture de patch `corrupt at line` e fixture `patch does not apply`.
- [ ] Provar uma edição real em worktree limpo usando `codex-cli/gpt-5.6-luna`, medium, fast.
- [ ] Receipt JSON deve registrar requested/effective model, effort, tier, parser strategy e fingerprint.

## Evidência

Medido em 2026-07-10 no Windows com `simplicio-cli 0.11.0`, `simplicio-mapper 0.19.0`, Codex CLI 0.144.1.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][Operator] Codex CLI patch extraction must recover corrupt/stale unified diffs deterministically

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Normalizar/recontar, codex-cli/gpt-5.6-luna, diff/apply, diff/final, extração/aplicação, medium/fast, requested/effective, testes/docs, tests/test_runner_cli.py.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #140 — [P0][Prompt Economy] Enforce per-layer budgets and cache-stable retry deltas

- Estado/data: `closed`; criada `2026-07-11T07:26:37Z`; atualizada `2026-07-12T03:13:24Z`
- Labels: `enhancement, high-priority, performance, pipeline, prompt, prompt-engineering, retry`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Parent and purpose

Parent epic: https://github.com/wesleysimplicio/simplicio-runtime/issues/3086

Mapper dependencies:
- https://github.com/wesleysimplicio/simplicio-mapper/issues/199
- https://github.com/wesleysimplicio/simplicio-mapper/issues/200

Related existing work: #113, #117, #118, #121.

Turn prompt construction and retry behavior into a versioned, budgeted envelope whose immutable prefix can be reused. Retries must send the smallest sufficient delta while retaining correctness, safety constraints, and proof requirements.

## Measured current-state evidence

- The current prompt combines template, mapper context, up to two precedents, skill material, adaptations, criteria, and constraints, but it has no enforceable token allocation per layer.
- Pipeline retry/fixer paths can resend the complete base prompt plus new feedback.
- Provider wrappers provide exact-response caching in places, but there is no ecosystem-wide stable-prefix contract or comparable provider cache receipt.
- The inspected Anthropic-native path did not expose an explicit cache-control policy.
- Repeated savings reports across the five repositories reported `cache_hits=0` and `prompts_reused=0`; therefore savings must be proven at the provider boundary, not inferred from local intent.

## Proposed prompt-envelope contract

A versioned `PromptEnvelope` contains:

- immutable goal and policy prefix;
- compact repository/context handles and hashes;
- selected context pack with provenance;
- acceptance/proof contract;
- mutable attempt delta: prior failure classification, minimal diagnostics, affected files/symbols, and requested correction;
- per-layer token estimates, hard/soft budgets, truncation decisions, and fidelity risk;
- stable `prefix_hash`, `context_pack_hash`, `delta_hash`, provider/model identity, and cache eligibility;
- explicit `needs_broader_context` escalation rather than silent truncation.

Budget policy must be configurable by task class and model context window. It must not be one universal hard-coded number.

## Step-by-step implementation

1. Instrument current prompts and retries by layer without changing behavior; establish distributions and top offenders.
2. Define and version `PromptEnvelope`, layer identities, receipts, and redaction rules.
3. Add task-class budget profiles for mechanical edit, diagnosis, review, planning, verification, and repair.
4. Allocate mapper, precedent, skill, policy, acceptance, and retry-delta budgets before rendering.
5. Ask mapper for budgeted context rather than truncating a fully rendered pack.
6. Pin the immutable prefix for a run/session; append only a compact, typed retry delta.
7. Classify failures so the retry includes only relevant diagnostics and handles.
8. Negotiate provider-native prefix caching where supported; provide deterministic local KV/exact fallback where safe.
9. Keep tool/schema ordering and prefix bytes stable across attempts unless a semantic invalidator fires.
10. Emit requested/actual input/output tokens, cache-read/write/creation tokens, hit/miss/bypass reason, and cost to https://github.com/wesleysimplicio/simplicio-runtime/issues/3087.
11. Add a fidelity gate: expand context or fall back to full mode when uncertainty/risk exceeds policy.
12. Dogfood on representative Simplicio tasks and tune profiles from measured quality and cost.
13. Document envelope inspection and an operator command that explains every included/excluded layer.

## Acceptance criteria

- [ ] Every generated prompt has a version, layer ledger, token estimate, effective budget, and inclusion/truncation reason.
- [ ] No layer silently exceeds its hard budget; an overflow either compacts, retrieves more selectively, or emits `needs_broader_context`.
- [ ] Attempts 2+ reuse a byte-stable immutable prefix when no semantic invalidator occurred.
- [ ] Retry payload contains only the typed delta and referenced handles; a test proves the full base prompt is not duplicated.
- [ ] File/context/policy/model/tool-schema changes invalidate exactly the affected cache identity.
- [ ] Provider receipts distinguish cache write/creation, cache read/hit, local exact reuse, and bypass.
- [ ] A/B evaluation shows lower total input tokens and cost per green WorkItem with no statistically meaningful drop in acceptance/proof success.
- [ ] High-risk tasks can deliberately select full-context mode, and that decision is visible in the receipt.
- [ ] Logs and keys contain no secrets or raw unredacted prompt bodies.
- [ ] Clean-wheel CLI and library consumers expose the same envelope/budget behavior.

## Required tests and evidence

- Golden tests for byte-stable prefixes and deterministic layer ordering.
- Unit tests for profiles, overflow, invalidation, redaction, and failure classification.
- Integration matrix: cold/warm provider, cache-supporting/non-supporting provider, success/retry/escalation, restart/resume.
- Quality corpus: mechanical edits, multi-file refactors, ambiguous diagnoses, and verifier failures.
- Before/after artifact: tokens by layer/attempt, cache tokens, cost, latency, acceptance, proof result, model/provider, commit, and fixture.

## Non-goals

- Blindly shrinking prompts without measuring correctness.
- Relying on undocumented provider cache behavior.
- Replacing mapper retrieval; this issue consumes its budgeted output.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][Prompt Economy] Enforce per-layer budgets and cache-stable retry deltas

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: A/B, Before/after, File/context/policy/model/tool-schema, KV/exact, acceptance/proof, cache-read/write/creation, cache-supporting/non-supporting, cold/warm, envelope/budget, files/symbols, github.com/wesleysimplicio/simplicio-mapper/issues/199, github.com/wesleysimplicio/simplicio-mapper/issues/200, github.com/wesleysimplicio/simplicio-runtime/issues/3086, github.com/wesleysimplicio/simplicio-runtime/issues/3087., hard/soft, hit/miss/bypass, included/excluded, inclusion/truncation, input/output, layer/attempt, model/provider, provider/model, read/hit, repository/context, requested/actual, restart/resume., retry/fixer, run/session, success/retry/escalation, tool/schema, uncertainty/risk, write/creation.

#### Dependências e ordem

Referências explícitas: #113, #117, #118, #121. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #141 — [P1][Maintainability] Split pipeline stages and restore the token/context budget gate

- Estado/data: `closed`; criada `2026-07-11T07:26:37Z`; atualizada `2026-07-12T03:13:22Z`
- Labels: `ci, enhancement, maintenance, performance, pipeline, test`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P1", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Parent and purpose

Parent epic: https://github.com/wesleysimplicio/simplicio-runtime/issues/3086

Related prompt-envelope work: https://github.com/wesleysimplicio/simplicio-dev-cli/issues/140.

Refactor the monolithic pipeline into narrow, testable stages, then restore a meaningful source/token budget gate. The goal is not aesthetic file splitting: it is to reduce the amount of implementation and context an agent must load for a targeted change while preserving all public behavior.

## Measured current-state evidence

The repository token-budget check measured `simplicio/pipeline.py` at approximately **10,042 estimated tokens** against a **5,555-token baseline**: about **+80.8%**, and the gate failed. Increasing the baseline would hide the regression rather than fix the context cost.

## Target stage boundaries

1. Request/task normalization and policy selection.
2. Prompt-envelope/context assembly.
3. Provider invocation and structured result decoding.
4. Patch extraction and validation.
5. Transactional apply/rollback.
6. Impact analysis and verification planning.
7. Retry/fixer orchestration.
8. Evidence, receipts, and final result assembly.

Stage contracts should be typed, serializable where useful, and small enough that a change to one stage does not require loading the full orchestration implementation.

## Step-by-step implementation

1. Freeze public APIs and capture characterization tests for success, no-op, failure, retry, rollback, and verification paths.
2. Generate a call/dependency map for `pipeline.py`, including global state and side effects.
3. Define typed inputs/outputs and explicit error taxonomy for each stage.
4. Extract pure decoding, patch, transaction, verification, retry, and receipt logic one slice at a time.
5. Keep the top-level pipeline as a small coordinator with dependency injection.
6. Remove duplicated provider/result normalization and centralize semantic invalidators.
7. Replace broad object passing with narrow handles/receipts; avoid copying full prompts, maps, or diagnostics between stages.
8. Add focused unit tests beside each extracted stage and retain end-to-end characterization tests.
9. Run mapper task-aware selection for representative maintenance tasks and record selected files/tokens before and after.
10. Reinstate the token/context budget gate with documented per-file/module thresholds and an aggregate policy.
11. Reject any baseline update that is not accompanied by a written architectural reason and reviewer-visible delta.
12. Validate source checkout, wheel, and CLI behavior.

## Acceptance criteria

- [ ] `pipeline.py` is a coordinator within an agreed budget at or below the prior 5,555-token baseline, unless a stricter reviewed threshold is adopted.
- [ ] No extracted production module becomes a new oversized dumping ground; per-module limits are enforced in CI.
- [ ] Existing public imports, CLI behavior, exit codes, and receipt schemas remain compatible or have an explicit migration.
- [ ] Characterization tests prove identical behavior for success, retry, rollback, verification failure, cancellation, and no-op paths.
- [ ] Each stage can be unit-tested without live provider/network/filesystem access unless that side effect is its explicit responsibility.
- [ ] A targeted change in one stage yields a smaller mapper context pack than the baseline on the evaluation corpus.
- [ ] The token-budget CI job fails on regression and prints the responsible files plus measured delta.
- [ ] No baseline is simply raised to make CI green.
- [ ] Windows and POSIX test paths pass.

## Required tests and evidence

- Characterization suite before extraction and regression suite after every slice.
- Import/API compatibility tests from a clean installed wheel.
- Fault injection at every stage boundary, including interrupted apply and retry exhaustion.
- Mapper context comparison for at least five representative tasks.
- CI artifact with module tokens, baseline, delta, threshold, and commit.
- Full project gate plus targeted performance tests.

## Non-goals

- Changing provider/model semantics in the same refactor.
- Large behavioral rewrites hidden inside file movement.
- Optimizing line count at the expense of cohesive contracts.

#### Objetivo

Entregar e provar o resultado delimitado por: [P1][Maintainability] Split pipeline stages and restore the token/context budget gate

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Import/API, Prompt-envelope/context, Request/task, Retry/fixer, apply/rollback., call/dependency, files/tokens, github.com/wesleysimplicio/simplicio-dev-cli/issues/140., github.com/wesleysimplicio/simplicio-runtime/issues/3086, handles/receipts, inputs/outputs, per-file/module, provider/model, provider/network/filesystem, provider/result, simplicio/pipeline.py, source/token, token/context.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #166 — [P0][Plan Compiler] Goal + ContextSnapshot → PlanDAG tipado, effect-free e verificável

- Estado/data: `closed`; criada `2026-07-12T05:30:38Z`; atualizada `2026-07-13T02:39:21Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Parent e ownership

Filha de https://github.com/wesleysimplicio/simplicio-runtime/issues/3134.

Redefinir o Dev CLI como compilador de mudança: receber GoalEnvelope + ContextSnapshot e produzir PlanDAG + EffectPlan + VerificationPlan. No modo integrado, o Dev CLI não é scheduler, não possui retry global e não comita efeitos fora do Runtime.

## Problema observado

- Chamadas ao Mapper e ao Runtime abrem subprocessos por operação, mesmo havendo dependência Python direta.
- O cache do Mapper não inclui revision/fingerprint e pode devolver contexto stale em processo longo.
- Feature, sprint, retry, memória, gate e evidência se sobrepõem ao Loop e ao Runtime.
- Retry interno pode se multiplicar pelo retry externo.
- Presença de um plano textual não prova dependências, conflitos, cobertura de AC ou reversibilidade.

Reutilizar #140 e #141 como fundações de budget/pipeline; não duplicá-las.

## Saídas v1

PlanDAG:

- plan_id, goal_id, context_snapshot_id e revision;
- nodes com capability requerida, inputs/outputs tipados e dependency edges;
- read set, write set, conflito e isolamento;
- risco, incerteza, custo/budget estimado e reason codes;
- mapeamento node → acceptance criteria;
- gates, checkpoint requirement e rollback/reconcile strategy.

EffectPlan:

- efeito proposto, authority requerida, idempotency key e preconditions;
- patch/artifact content-addressed;
- nenhuma execução embutida.

VerificationPlan:

- verifier, comando/capability, timeout e ambiente;
- AC coberto e evidência esperada;
- critérios de stop, abstention e replan.

## Plano passo a passo

### 0. Caracterizar o pipeline atual

1. Mapear todos os call sites de subprocess, retry, feature/sprint, gate e write.
2. Medir processos por tarefa, cold/warm latency, chamadas de modelo, retries e cache hits/staleness.
3. Marcar ownership de cada função e sua migração.

### 1. Contratos

1. Consumir schemas do épico sem criar variantes locais.
2. Implementar modelos tipados, validação e canonical hash.
3. Tornar revision e snapshot_id obrigatórios no cache key.
4. Rejeitar schema/producer incompatível com erro estruturado.

### 2. Front-end determinístico

1. Normalizar objetivo e ACs.
2. Resolver receitas conhecidas sem modelo quando possível.
3. Detectar contexto insuficiente antes de gerar patch.
4. Emitir ambiguidades como NEEDS_CLARIFICATION, não como suposição silenciosa.

### 3. Compilação de DAG

1. Decompor em nós atômicos e verificáveis.
2. Inferir dependências e conflito por read/write set.
3. Mapear todos os ACs a pelo menos um verifier.
4. Identificar efeito irreversível e exigir gate/checkpoint.
5. Validar ciclo, node órfão, budget e authority.

### 4. Geração de efeito sem execução

1. Produzir patch/artifact em sandbox/worktree isolado.
2. Registrar base revision e hash.
3. Dry-run deve ser observavelmente effect-free.
4. No modo integrado, enviar EffectPlan ao Runtime; somente o Runtime autoriza e registra commit/mutação.
5. Manter modo standalone apenas como adaptador explícito e deprecável, sem semântica paralela.

### 5. Remover control plane duplicado

1. Migrar feature/sprint para PlanDAG.
2. Migrar retry global e memória operacional ao Runtime/Loop policy.
3. Dev CLI realiza no máximo uma tentativa atômica por comando recebido.
4. Retornar observação classificada, sem iniciar nova estratégia sozinho.

### 6. Caminho quente

1. Substituir subprocessos Mapper/Runtime por API/IPC persistente quando capability negociada.
2. Manter fallback explícito e medido.
3. Adicionar capabilities --json; não analisar texto de --help.
4. Reutilizar objetos e handles content-addressed entre tentativas.

## Critérios de aceite

- [x] Mesma entrada canônica gera PlanDAG semanticamente idêntico no modo determinístico.
- [x] PlanDAG inválido, cíclico, sem authority ou sem cobertura de AC é rejeitado antes de qualquer efeito.
- [x] Dry-run não altera worktree, ledger, rede externa ou estado persistente.
- [x] Cache nunca cruza revision/snapshot_id.
- [x] No modo integrado, zero escrita/commit fora da Effect API do Runtime.
- [ ] Retry global, feature/sprint scheduler e operational memory deixam de ter dois owners ativos.
- [x] Cada AC aponta para verificador e evidência esperada.
- [x] Clean install executa contract tests minimum/latest.
- [x] Golden E2E preserva trace_id, goal_id, plan_id, revision e budget.
- [ ] Benchmark publica processos, chamadas, tokens, p50/p95 e task success antes/depois.
- [x] Falha de hipótese vira resultado documentado; nenhuma redução de latência pode reduzir segurança/evidência.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][Plan Compiler] Goal + ContextSnapshot → PlanDAG tipado, effect-free e verificável

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: API/IPC, Mapper/Runtime, Runtime/Loop, antes/depois., budget/pipeline, cold/warm, comando/capability, commit/mutação., custo/budget, escrita/commit, feature/sprint, gate/checkpoint., github.com/wesleysimplicio/simplicio-runtime/issues/3134., hits/staleness., inputs/outputs, minimum/latest., p50/p95, patch/artifact, read/write, revision/fingerprint, revision/snapshot_id., rollback/reconcile, sandbox/worktree, schema/producer, segurança/evidência..

#### Dependências e ordem

Referências explícitas: #140, #141. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #167 — [P0][Ecosystem Rebrand] Dev CLI usa Simplicio Agent em bootstraps, descriptors, locales e contracts

- Estado/data: `closed`; criada `2026-07-12T06:33:50Z`; atualizada `2026-07-13T02:39:22Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Objetivo

Rebrand completo das integrações públicas Hermes do `simplicio-dev-cli` para **Simplicio Agent**, sem renomear o próprio Dev CLI nem quebrar handoffs/automations legados.

## Evidência atual

A busca encontra Hermes em `bootstrap.sh/.ps1`, `INIT.md`, `AGENTS.md`, `CLAUDE.md`, README principal e muitas traduções.

## Invariantes

1. Dev CLI compila Goal+Context em plano; no modo integrado não aplica efeito.
2. Seu package/comando continuam próprios.
3. Agent é `Simplicio Agent`; Runtime é `simplicio`.
4. Conteúdo multilíngue deriva do mesmo glossário.
5. Handoff/schema usa versão/adapters.
6. Compatibilidade Hermes fica em uma borda registrada.

## Plano passo a passo

1. Adotar naming/glossary do Agent #186/#192.
2. Inventariar source, docs, translations, scripts, package e artifacts.
3. Classificar public/compat/upstream/history/internal/error.
4. Atualizar bootstrap POSIX/PowerShell para release canônica.
5. Remover URL/repo Hermes como origem de produção.
6. Atualizar INIT/AGENTS/CLAUDE labels e instruções públicas.
7. Atualizar README source e gerar traduções.
8. Validar que nenhuma tradução confunde Agent, Runtime e Dev CLI.
9. Atualizar examples/prompts/templates.
10. Versionar GoalEnvelope/PlanDAG producer/consumer IDs.
11. Criar adapter inbound/outbound N-1.
12. Emitir PlanDAG canônico por default.
13. No modo integrado, enviar EffectProposal ao Agent/ToolPipeline.
14. Bloquear instrução que contorne Runtime gate.
15. Atualizar help/errors/completion e machine outputs.
16. Garantir warning de alias em stderr/canal seguro.
17. Registrar uso local sem args/prompt/env values.
18. Criar glossary machine-readable e pseudolocale.
19. Rodar snapshot/lint de todas as traduções.
20. Construir package e inspecionar metadata/data.
21. Executar clean install e quickstart standalone.
22. Executar Agent→Mapper→Dev plan compile E2E.
23. Testar N-1↔N contract e rollback.
24. Escanear artifacts com regra Agent #194.
25. Publicar migration guide.
26. Retirar alias só pela policy #193.

## Critérios de aceite

- [x] Dev CLI não é renomeado para Agent.
- [x] Docs/bootstrap usam Simplicio Agent canônico.
- [x] Nenhum installer baixa upstream Hermes.
- [x] Goal/Plan schemas usam IDs versionados.
- [x] Modo integrado não executa writes diretamente.
- [x] Standalone continua funcional.
- [x] N-1 adapter possui fixtures/expiry.
- [x] Todas as traduções preservam termos Agent/Runtime/Dev CLI.
- [x] Warning não corrompe JSON.
- [x] Alias telemetry não contém conteúdo sensível.
- [x] Package instalado contém docs/schemas esperados.
- [x] Quickstart roda fora do checkout.
- [x] Artifacts passam scanner.
- [ ] Rollback restaura compatibilidade.
- [x] Claim de integração exige E2E.

## Dependências

Dev CLI #166; Runtime #3134/#3135; Mapper #208; Agent #186/#191/#192/#193/#194/#195.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][Ecosystem Rebrand] Dev CLI usa Simplicio Agent em bootstraps, descriptors, locales e contracts

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Agent/Runtime/Dev, Agent/ToolPipeline., Docs/bootstrap, Goal/Plan, GoalEnvelope/PlanDAG, Handoff/schema, INIT/AGENTS/CLAUDE, POSIX/PowerShell, URL/repo, args/prompt/env, bootstrap.sh/.ps1, docs/schemas, examples/prompts/templates., fixtures/expiry., handoffs/automations, help/errors/completion, inbound/outbound, metadata/data., naming/glossary, package/comando, producer/consumer, public/compat/upstream/history/internal/error., snapshot/lint, stderr/canal, versão/adapters..

#### Dependências e ordem

Referências explícitas: #166, #186, #193, #194, #208, #3134. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #181 — [Loop Audit] Issue #114 closed without verified evidence

- Estado/data: `closed`; criada `2026-07-13T01:44:01Z`; atualizada `2026-07-13T06:57:33Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "[EPIC]", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Audit context

Automated 48h closure audit (window: closed:&gt;=2026-07-11) of issues closed in `wesleysimplicio/simplicio-dev-cli`.

## Issue in question

#114 — `[P0][EPIC] Task-to-Delivery v2: de card bruto a entrega integrada e comprovada`

Closed 2026-07-12T03:13:36Z, `state_reason=completed`, no native GitHub sub-issues linked (`get_sub_issues` returns empty).

## What's missing

- The issue's own comment trail on 2026-07-11 (`MEASURED|Release v0.13.0 ...`) explicitly says: *"This release does not claim the remaining live/runtime/cross-repo acceptance criteria; issue remains open until its full AC matrix has receipts."* (tagged `UNVERIFIED`).
- The very next (and final) comment, 2026-07-12, which accompanies the close, reads only: *"Implementado e mergeado na master nos PRs da wave; release v0.15.0 publicada. Fechamento autorizado pelo mantenedor."* — it cites **no PR numbers**, no test run, no specific AC evidence, and contradicts the prior "remains open until AC matrix has receipts" statement without addressing what changed.
- Every merged PR that does reference #114 in this same window (#133, #134, #147, #159) explicitly disclaims completing the epic, e.g. PR #147: *"This PR delivers bounded slices; it does not claim the full #114/#113/#89 epics ... Those remain open until their acceptance criteria have current receipts."* and PR #159: *"This is a focused, non-closing slice of issue #114's raw URL intake acceptance. It does not close issue #114."*
- No PR in the audited window contains `Closes #114` or `Fixes #114`, and no comment on #114 names which specific PRs/receipts satisfy the epic's full acceptance criteria.

## Ask

Re-open or add a comment to #114 that either (a) enumerates the specific PRs/commits and measured evidence that satisfy each remaining acceptance criterion the 2026-07-11 comment called out as unverified, or (b) explains why the epic's scope was reduced/descoped at closure time.

---
Filed by an automated audit pass; not itself part of the loop/PR flow for #114.

#### Objetivo

Entregar e provar o resultado delimitado por: [Loop Audit] Issue #114 closed without verified evidence

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: PRs/commits, PRs/receipts, live/runtime/cross-repo, loop/PR, reduced/descoped, wesleysimplicio/simplicio-dev-cli.

#### Dependências e ordem

Referências explícitas: #114, #133, #134, #147, #159. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #200 — [Unit Tests] Cobrir comandos, prompts, retries, configuração e tratamento de erros

- Estado/data: `closed`; criada `2026-07-14T05:17:21Z`; atualizada `2026-07-14T15:36:14Z`
- Labels: `nenhuma`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Objetivo
Garantir que cada comando do `simplicio-dev-cli` tenha comportamento previsível e testável.

## Escopo
- Parsing de argumentos e configuração.
- Construção de prompts e seleção de contexto.
- Retry, fallback, timeout e cancelamento.
- Leitura dos artefatos do mapper.
- Saídas, códigos de retorno e mensagens de erro.

## Critérios de aceite
- [ ] 90% de cobertura nas áreas críticas.
- [ ] Todos os comandos públicos possuem testes.
- [ ] LLM, filesystem, relógio e subprocessos usam fakes.
- [ ] Exit codes e erros são validados.
- [ ] Casos de configuração inválida e ausência de dependência são cobertos.
- [ ] Bugs corrigidos recebem regressão.

#### Objetivo

Entregar e provar o resultado delimitado por: [Unit Tests] Cobrir comandos, prompts, retries, configuração e tratamento de erros

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: nenhum caminho explícito; identificar antes de implementar.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #201 — [Integration/E2E] Validar execução real dos comandos com mapper, runtime e projetos fixture

- Estado/data: `closed`; criada `2026-07-14T05:17:34Z`; atualizada `2026-07-14T15:33:19Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Objetivo
Provar que os comandos funcionam de ponta a ponta em instalações limpas e projetos representativos.

## Cenários
- Instalação e primeiro uso.
- Inicialização, mapeamento e execução de tarefa.
- Projeto válido, vazio, grande e parcialmente corrompido.
- LLM indisponível, timeout e resposta inválida.
- Interrupção pelo usuário e retomada segura.
- Compatibilidade entre versões dos pacotes.

## Critérios de aceite
- [ ] Fluxos principais possuem E2E executado pelo binário real.
- [ ] stdout, stderr, exit code e efeitos no filesystem são validados.
- [ ] Integrações usam fixtures reproduzíveis.
- [ ] Contratos com mapper/runtime são testados.
- [ ] A suíte roda no CI em plataformas suportadas.

#### Objetivo

Entregar e provar o resultado delimitado por: [Integration/E2E] Validar execução real dos comandos com mapper, runtime e projetos fixture

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: mapper/runtime.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #202 — [CI Quality Gate] Exigir testes, cobertura, compatibilidade e regressão em toda PR

- Estado/data: `closed`; criada `2026-07-14T05:17:47Z`; atualizada `2026-07-14T15:22:51Z`
- Labels: `nenhuma`
- Classificação: `{"component": "cli", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Objetivo
Bloquear merges que quebrem comandos, compatibilidade ou experiência do CLI.

## Implementação
- Jobs de lint, unit, integration e E2E.
- Matriz de sistemas e versões suportadas.
- Coverage gate de 85% global e 90% crítico.
- Snapshot controlado para help e mensagens públicas.
- Testes de instalação do pacote publicado.
- Artefatos de logs e relatórios.

## Critérios de aceite
- [ ] Todos os checks bloqueiam merge.
- [ ] Mudança de interface pública exige atualização explícita dos snapshots.
- [ ] Instalação limpa é validada.
- [ ] Todo bug corrigido possui regressão.
- [ ] Branch principal exige pipeline verde.

#### Objetivo

Entregar e provar o resultado delimitado por: [CI Quality Gate] Exigir testes, cobertura, compatibilidade e regressão em toda PR

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: nenhum caminho explícito; identificar antes de implementar.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #212 — [Performance] Migrar pipeline Python para concorrência estruturada, HTTP async e uvloop opcional

- Estado/data: `closed`; criada `2026-07-17T19:28:10Z`; atualizada `2026-07-17T20:25:35Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

A CLI executa providers HTTP, subprocessos, mapper, precedentes, edição e testes. O ganho virá de sobrepor esperas independentes, reutilizar conexões e limitar concorrência — não de paralelizar etapas dependentes.

## Objetivo

Disponibilizar uma API async nativa baseada em AnyIO/`asyncio`, compartilhar `httpx.AsyncClient` e habilitar `uvloop` opcional, preservando todos os comandos e contratos atuais.

## Passo a passo

1. Instrumentar baseline por etapa: prompt, provider, mapper, edição, teste e retry.
2. Mapear o DAG real do pipeline e marcar dependências obrigatórias.
3. Introduzir um `RuntimeContext` por execução contendo clients, limites, cancel scope e telemetria.
4. Substituir criação repetida de clientes por `httpx.AsyncClient` compartilhado, com pooling, timeout e fechamento determinístico.
5. Migrar providers e subprocessos para APIs async; encapsular bibliotecas bloqueantes em worker threads limitadas.
6. Executar apenas operações comprovadamente independentes em TaskGroups.
7. Implementar semáforos por provider, projeto e tipo de recurso, retries com jitter e circuit breaker.
8. Criar `run_async()`; manter `run()`/CLI como ponte segura, detectando loop já ativo.
9. Oferecer extra `performance` com `uvloop` em plataformas suportadas e fallback padrão.
10. Integrar futuramente ao Simplicio Loop Hub via interface de scheduler, sem acoplamento obrigatório.

## Testes

- Providers mockados, streaming, timeout, retry e cancelamento.
- Subprocessos com saída grande, falha, timeout e limpeza de árvore.
- Execuções simultâneas sem vazamento de sessão/descritor.
- Compatibilidade da CLI e do pacote instalado.
- Benchmark com conexões frias/quentes e 1/N tarefas.

## Critérios de aceite

- [ ] Um client compartilhado por escopo, sem conexões vazadas.
- [ ] Concorrência limitada e configurável.
- [ ] Cancelamento interrompe subprocessos e fecha recursos.
- [ ] Não há `asyncio.run()` aninhado.
- [ ] Windows funciona sem uvloop; Unix usa uvloop somente quando habilitado/suportado.
- [ ] Resultado funcional e ordem das etapas dependentes não mudam.
- [ ] Relatório antes/depois inclui latência p50/p95, CPU, RSS e tokens.

#### Objetivo

Entregar e provar o resultado delimitado por: [Performance] Migrar pipeline Python para concorrência estruturada, HTTP async e uvloop opcional

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: 1/N, antes/depois, frias/quentes, habilitado/suportado., p50/p95, sessão/descritor..

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #213 — [Integration] Consumir mapa canônico e overlay do worktree sem full remap redundante

- Estado/data: `closed`; criada `2026-07-17T19:32:42Z`; atualizada `2026-07-17T20:51:35Z`
- Labels: `nenhuma`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Objetivo

Fazer o dev-cli solicitar ao Simplicio Loop Hub/Simplicio Mapper uma visão composta do projeto, reutilizando o mapa da branch default e o overlay do worktree atual, sem disparar full remap por task, retry ou agent.

## Plano passo a passo

1. Adotar os contratos versionados `CanonicalMapManifest`, `WorktreeOverlay` e `EffectiveMapView`.
2. Resolver common repo, worktree, HEAD, merge-base, dirty fingerprint e mapper config.
3. Consultar primeiro o Map Service do Hub; não iniciar mapper local enquanto a solicitação estiver pendente.
4. Reutilizar o mesmo view handle durante todo o run/retry.
5. Solicitar refresh incremental somente quando arquivos/config/HEAD relevantes mudarem.
6. Invalidar contexto derivado, RAG e precedentes apenas para entidades afetadas.
7. Propagar map snapshot ID em prompts, task contracts, receipts e reports.
8. Recusar silenciosamente mapas incompatíveis; rebuild/fallback deve ser explícito e registrado.
9. Evitar cópia/materialização integral quando API lazy/handle estiver disponível.
10. Encaminhar execução do mapper ao Process Supervisor central.
11. Implementar fallback standalone usando os mesmos contratos.
12. Adicionar doctor/status explicando canonical hit, overlay hit, remapped files e motivo de fallback.

## Testes obrigatórios

- Múltiplos runs e retries no mesmo worktree.
- Dois worktrees com deltas diferentes.
- Alterações dirty entre planejamento e execução.
- Branch switch/rebase durante run.
- Hub indisponível/reiniciado e contrato incompatível.
- Comparação com full remap.

## Critérios de aceite

- [ ] Nenhum full remap ocorre quando canonical+overlay válidos existem.
- [ ] Retry do mesmo run fixa ou atualiza snapshot conforme política explícita.
- [ ] Prompts/execução nunca recebem símbolos removidos ou conteúdo de outro worktree.
- [ ] Snapshot ID aparece em todas as evidências relevantes.
- [ ] Fallback é correto, observável e não duplica processos.
- [ ] Benchmark registra tempo, CPU, RSS, I/O e arquivos remapeados.

#### Objetivo

Entregar e provar o resultado delimitado por: [Integration] Consumir mapa canônico e overlay do worktree sem full remap redundante

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Hub/Simplicio, I/O, Prompts/execução, arquivos/config/HEAD, cópia/materialização, doctor/status, indisponível/reiniciado, lazy/handle, rebuild/fallback, run/retry., switch/rebase.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #218 — [Compatibility] Normalize structured simplicio-mapper ask results in the impact gate

- Estado/data: `closed`; criada `2026-07-17T22:58:03Z`; atualizada `2026-07-17T23:24:19Z`
- Labels: `bug`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

O `simplicio-mapper ask <root> impact|tests-for <arg> --json` atual retorna `simplicio.ask/v1` com `results` como objeto estruturado, por exemplo `affected_symbols`, `affected_flows` e `needs_review`. O `simplicio-cli`/dev-cli 0.16.1 ainda assume que `results` é uma lista em `simplicio/mapper.py:map_ask`, devolvendo `None`. Isso faz o gate de impacto classificar mudanças válidas como `mapper_unavailable` e recusar receipts do operador.

## Reprodução live

- mapper: 0.23.1
- simplicio-cli: 0.16.1
- comando: `simplicio-mapper ask . impact tests/python/test_mapper_canonical_identity.py --json`
- resposta: `schema=simplicio.ask/v1`, `results.affected_symbols` presente
- comportamento atual: `from simplicio.mapper import map_ask; map_ask(...) -> None`

## Critérios de aceitação

1. `map_ask` normaliza de forma compatível tanto o formato legado `results: list[dict]` quanto o formato estruturado atual.
2. O resultado normalizado preserva `path`, `symbol`, callers/affected symbols e demais campos úteis sem perda silenciosa.
3. `run_impact_tests` deixa de reportar `mapper_unavailable` quando o CLI responde validamente com `simplicio.ask/v1`.
4. Há testes unitários para os dois formatos e teste de integração contra um binário/fixture real do mapper.
5. A matriz do dev-cli passa com a cobertura mínima do projeto; mudanças em contratos compartilhados incluem regressão e benchmark quando aplicável.
6. O receipt do operador registra impacto executável e permite validar uma mudança real no `simplicio-mapper`.

## Dependências e riscos

- Compatibilidade com mapper 0.14+ e com consumidores que já esperam listas.
- Não alterar o schema do mapper nesta issue.
- Evitar transformar ausência de resultados em falso impacto vazio.

## Não objetivos

- Não implementar as features das issues #233/#235/#236 nesta issue.
- Não desabilitar o gate de impacto nem aceitar receipts sem evidência.

#### Objetivo

Entregar e provar o resultado delimitado por: [Compatibility] Normalize structured simplicio-mapper ask results in the impact gate

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: binário/fixture, callers/affected, simplicio.ask/v1, simplicio/mapper.py, tests/python/test_mapper_canonical_identity.py.

#### Dependências e ordem

Referências explícitas: #233. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #219 — [Reliability] Tornar task do operador observável e cancelável em tentativas sem progresso

- Estado/data: `closed`; criada `2026-07-17T23:19:44Z`; atualizada `2026-07-17T23:52:26Z`
- Labels: `bug`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

Durante a tentativa de corrigir a compatibilidade de `map_ask` com o contrato estruturado do `simplicio-mapper`, o operador foi executado com escopo de um único arquivo e recebeu um comando de testes focado. A primeira tentativa anterior falhou por gerar testes dentro de `simplicio/mapper.py`. A tentativa corrigida, sem testes e com bound path único, permaneceu viva por vários minutos sem emitir novo receipt depois de `token_usage attempt=1`; precisou ser encerrada pelo processo pai.

## Reprodução observada

- Modelo: `codex-cli/gpt-5.6-luna`
- Esforço: `high`
- Stack: `python`
- Target/bound path: `simplicio/mapper.py`
- Test command: `py -m pytest tests/python/test_mapper_handoff_integration.py tests/python/test_pipeline_task_result.py -q`
- Resultado: nenhum `applied=true`, nenhum receipt final e nenhuma indicação de progresso após a primeira tentativa.
- O patch parcial gravado em `.simplicio/last_patch.diff` era uma substituição destrutiva do arquivo inteiro e foi descartado; o working tree não recebeu código de produto.

## Acceptance criteria

1. Cada tentativa emite heartbeat/estado com limite de tempo e etapa atual.
2. O comando retorna receipt terminal `applied=false` com motivo explícito quando o modelo/runtime fica sem progresso.
3. Existe cancelamento cooperativo por timeout e limpeza de subprocessos filhos.
4. O bound-path validator rejeita qualquer patch que substitua um arquivo inteiro quando a solicitação é uma alteração localizada.
5. O retry reduz escopo ou muda estratégia automaticamente, sem repetir o mesmo prompt.
6. Há testes unitários e de integração para timeout, cancelamento, receipt terminal e rejeição de patch destrutivo.
7. A execução permanece compatível com os gates de impacto e não desabilita validação.

## Dependencies

- Runtime/runner de tarefas do `simplicio-dev-cli`.
- Integração com `simplicio-mapper`/receipts.

## Risks

- Cancelamento incompleto pode deixar subprocessos e locks.
- Heartbeats excessivos podem aumentar custo/token.
- Validação agressiva de patch pode rejeitar mudanças legítimas se não considerar hunks.

## Non-goals

- Não alterar o schema `simplicio.ask/v1`.
- Não implementar a correção de `map_ask` nesta issue.
- Não desabilitar gates ou aceitar sucesso sem diff/testes verificáveis.

#### Objetivo

Entregar e provar o resultado delimitado por: [Reliability] Tornar task do operador observável e cancelável em tentativas sem progresso

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .simplicio/last_patch.diff, Runtime/runner, Target/bound, codex-cli/gpt-5.6-luna, custo/token., diff/testes, heartbeat/estado, modelo/runtime, simplicio.ask/v1, simplicio/mapper.py, tests/python/test_mapper_handoff_integration.py, tests/python/test_pipeline_task_result.py.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #221 — [CI] Corrigir coleta de test_mapping_retry_flow em Python 3.9

- Estado/data: `closed`; criada `2026-07-17T23:23:35Z`; atualizada `2026-07-17T23:40:15Z`
- Labels: `bug`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Reprodução

No checkout isolado baseado em `origin/master`, a coleta de `tests/python/test_mapping_retry_flow.py` falha antes de executar testes:

```
SyntaxError: f-string expression part cannot include a backslash
tests/python/test_mapping_retry_flow.py:950
```

A expressão do f-string contém literais com `\\n`, incompatíveis com a versão de Python usada na execução.

## Impacto

A suíte de regressão de pipeline/mapeamento não pode ser usada como evidência de DoD; a falha é independente da correção de `map_ask`.

## Acceptance criteria

1. `py -m pytest tests/python/test_mapping_retry_flow.py -q` coleta e executa sem SyntaxError.
2. O teste que valida o conteúdo de `app.py` preserva a mesma semântica.
3. A correção funciona no Python mínimo suportado pelo projeto.
4. A suíte focada de mapper e o arquivo corrigido passam.
5. Não mascarar erros de runtime nem relaxar gates.

## Non-goals

- Não alterar o contrato `simplicio.ask/v1`.
- Não incluir a correção de compatibilidade de `map_ask` nesta issue.

#### Objetivo

Entregar e provar o resultado delimitado por: [CI] Corrigir coleta de test_mapping_retry_flow em Python 3.9

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: origin/master, pipeline/mapeamento, simplicio.ask/v1, tests/python/test_mapping_retry_flow.py.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #223 — [Windows CI] Tornar testes de impacto portáveis e estabilizar o retry pós-impacto

- Estado/data: `closed`; criada `2026-07-17T23:33:11Z`; atualizada `2026-07-17T23:40:16Z`
- Labels: `bug`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Reprodução

No `origin/master` após a coleta de `tests/python/test_mapping_retry_flow.py` com Python 3.14:

```
py -3.14 -m pytest tests/python/test_mapping_retry_flow.py -q
3 failed, 32 passed
```

Falhas observadas:

1. `test_pipeline_retry_after_impact_failure_restarts_from_unpromoted_state` esgota a sequência de respostas simuladas e lança `StopIteration`.
2. `test_impact_verification_emits_receipt_and_honors_transaction_timeout` usa `printf impact`, inexistente no shell do Windows, retornando `failed`.
3. `test_impact_timeout_is_unverified_and_fail_closed` usa `sleep 2`, inexistente no shell do Windows, retornando `failed` em vez de `unverified`.

## Acceptance criteria

1. A suíte focada passa em Windows com a versão de Python suportada.
2. Testes de subprocesso usam comandos portáveis baseados em `sys.executable`, sem depender de utilitários POSIX.
3. O retry após falha de impacto consome exatamente as tentativas previstas e verifica que a mudança não promovida é descartada.
4. O teste de timeout obtém `unverified` por timeout real, não por comando ausente.
5. Há validação focada em Windows e Linux/macOS, sem desabilitar gates.

## Non-goals

- Não alterar a semântica de `run_impact_tests` para esconder falhas.
- Não incluir a correção sintática de #221.

#### Objetivo

Entregar e provar o resultado delimitado por: [Windows CI] Tornar testes de impacto portáveis e estabilizar o retry pós-impacto

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Linux/macOS, origin/master, tests/python/test_mapping_retry_flow.py.

#### Dependências e ordem

Referências explícitas: #221. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #227 — [Reliability] Emitir receipt terminal quando Codex CLI esgota créditos ou encerra silenciosamente

- Estado/data: `closed`; criada `2026-07-17T23:59:25Z`; atualizada `2026-07-18T00:50:28Z`
- Labels: `nenhuma`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Evidência observada

Após o merge de #219/#226, uma execução real de:

```powershell
$env:SIMPLICIO_MODEL='codex-cli/gpt-5.6-luna'
$env:SIMPLICIO_CODEX_EFFORT='high'
$env:SIMPLICIO_TEST_CMD='py -3.14 -m pytest ... -q'
simplicio-dev-cli task "..." --root . --target simplicio_mapper/cli/__init__.py --json
```

passou os preconditions, emitiu `task_start` e criou um subprocesso `codex`, porém o subprocesso terminou com saldo de créditos `0`. Não houve `task_end`, `blocked`, `failed`, patch receipt ou resultado JSON terminal. O worktree não recebeu diff de código.

## Problema

Um executor consumidor não consegue diferenciar execução ainda em curso de provider sem capacidade. Isso quebra observabilidade, retry/cancelamento e coordenação GitHub mesmo após o guard de progresso de #219.

## Critérios de aceite

- Qualquer saída/erro/encerramento do provider Codex gera exatamente um resultado terminal estruturado, incluindo `status`, `reason_code`, tentativa, duração e provider/model/effort redigidos.
- Saldo/crédito/rate-limit/cota indisponível mapeia para `provider_capacity_unavailable`, sem fingir sucesso e sem aplicar diff.
- `task_start` sem evento terminal é detectado e recuperado após timeout/child exit.
- O processo filho é reaped; retries respeitam limite e cancelamento continua possível.
- Testes simulam saída do Codex que comunica crédito esgotado e child exit silencioso; validam JSON, eventos e ausência de mutação.
- Uma execução CLI real ou fixture de subprocesso prova o receipt final.

## Não objetivo

Não alterar seleção de modelo, preços ou credenciais do usuário.

#### Objetivo

Entregar e provar o resultado delimitado por: [Reliability] Emitir receipt terminal quando Codex CLI esgota créditos ou encerra silenciosamente

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Saldo/crédito/rate-limit/cota, codex-cli/gpt-5.6-luna, provider/model/effort, retry/cancelamento, saída/erro/encerramento, simplicio_mapper/cli/__init__.py, timeout/child.

#### Dependências e ordem

Referências explícitas: #219. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #231 — [P0][Integration] Tornar o dev-cli worker determinístico do Loop Hub com zero scheduler duplicado

- Estado/data: `closed`; criada `2026-07-18T02:47:59Z`; atualizada `2026-07-18T07:42:35Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Parent: https://github.com/wesleysimplicio/simplicio-loop/issues/555
Related: wesleysimplicio/simplicio-loop#496, #498, #555; wesleysimplicio/simplicio-runtime#3327

## Diagnóstico verificado

O Dev CLI corretamente recebe uma tarefa decidida e transforma plano em diff, testes e receipt. O batch em `simplicio/orchestrator/multi_task.py` mantém DAG/estado e usa `ThreadPoolExecutor` próprio. Em múltiplas IDEs/sessões isso pode criar pools, worktrees, subprocessos, mapas e chamadas LLM concorrentes fora do orçamento global.

Não existe issue aberta dedicada à integração do Dev CLI com o Loop Hub.

## Objetivo

Transformar o Dev CLI em worker idempotente e focado do Hub: o Loop possui workflow/fairness; o Runtime possui processos/recursos; o Dev CLI compila/aplica/verifica uma mudança delimitada e retorna evidência.

## Fronteiras

- Dev CLI não cria daemon, scheduler global, fila durável ou model pool.
- `TaskBatch` pode continuar como compilador/visão local de DAG e fallback standalone.
- Em modo Hub, dependências, claim, lease, retry e capacidade vêm do contrato comum.
- Subprocessos, testes e worktrees passam pelo Process Supervisor/Runtime.
- LLM só é usado para diff semântico; edição mecânica usa Runtime/plan determinístico.
- Mapper context é recebido por handle/version, não reconstruído por worker.

## Passo a passo

1. Criar `HubTaskAdapter` e schemas de capability/receipt.
2. Mapear `TaskBatch` para work items/dependencies do Hub sem estado duplo.
3. Propagar ecosystem/run/task/attempt/lease/fence/trace/idempotency IDs.
4. Receber map/context handles e validar versão/freshness.
5. Implementar route `mechanical | semantic | blocked`.
6. Encaminhar semantic route ao Agent/inference pool compartilhado; nunca abrir modelo próprio quando Hub ativo.
7. Encaminhar exec/test/build/worktree ao Runtime supervisor.
8. Garantir apply atômico, rollback e file-conflict lease.
9. Classificar retries: transient, model, test-failure, invalid-plan e non-retryable.
10. Emitir progress/eventos e receipt completo por tentativa.
11. Expor `--hub auto|on|off`, doctor/status e fallback explícito.
12. Remover/não ativar ThreadPoolExecutor local em modo Hub.
13. Adicionar conformance suite e rollout shadow/canário.

## SLOs

- tempo submit→first diff e submit→green;
- tokens/LLM calls por tarefa verde;
- mapper/context reuse hit-rate;
- process/thread/worktree counts;
- CPU-seconds/RSS/I/O;
- retry/stall/success;
- cold vs warm session.

## Testes

- unitários de adapter/router/receipt;
- contract Loop↔DevCLI↔Runtime;
- integração com worktree real e conflitos;
- novo arquivo, alteração, delete e mudança multi-file;
- LLM indisponível com mechanical route funcional;
- cancel/timeout/lease loss/restart;
- 20 jobs/múltiplos clients;
- standalone parity;
- benchmark local ThreadPool vs Hub central;
- E2E tarefa→diff→test→receipt.

## Critérios de aceite

- [ ] Em modo Hub, nenhum pool/scheduler/model/processo é criado fora das autoridades definidas.
- [ ] DAG não diverge entre TaskBatch e Hub.
- [ ] Edição mecânica consome zero tokens.
- [ ] Contexto/mapa equivalentes são reutilizados.
- [ ] Worktree e efeitos são protegidos por lease/fence/idempotency.
- [ ] Cancelamento não deixa processos ou worktrees órfãos.
- [ ] Receipt permite reproduzir diff/test/route sem armazenar secrets.
- [ ] p95, tokens/tarefa verde e recursos melhoram contra baseline.
- [ ] Standalone continua funcional e observável.
- [ ] Conformance cross-repo passa e evidencia o parent #555.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][Integration] Tornar o dev-cli worker determinístico do Loop Hub com zero scheduler duplicado

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: Agent/inference, CPU-seconds/RSS/I/O, Contexto/mapa, DAG/estado, IDEs/sessões, Remover/não, Runtime/plan, Supervisor/Runtime., adapter/router/receipt, cancel/timeout/lease, capability/receipt., compila/aplica/verifica, compilador/visão, diff/test/route, doctor/status, ecosystem/run/task/attempt/lease/fence/trace/idempotency, exec/test/build/worktree, github.com/wesleysimplicio/simplicio-loop/issues/555, handle/version, items/dependencies, jobs/múltiplos, lease/fence/idempotency., loss/restart, map/context, mapper/context, pool/scheduler/model/processo, process/thread/worktree, processos/recursos, progress/eventos, retry/stall/success, shadow/canário., simplicio/orchestrator/multi_task.py, tokens/LLM, tokens/tarefa, versão/freshness., wesleysimplicio/simplicio-loop, wesleysimplicio/simplicio-runtime, workflow/fairness.

#### Dependências e ordem

Referências explícitas: #498, #555. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #232 — [P0][Release Train] Atualizar Mapper automaticamente e propagar a release do Dev CLI ao Loop

- Estado/data: `closed`; criada `2026-07-18T03:05:48Z`; atualizada `2026-07-18T07:51:46Z`
- Labels: `nenhuma`
- Classificação: `{"component": "mapper", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Parent release train: https://github.com/wesleysimplicio/simplicio-loop/issues/558
Related: #231; wesleysimplicio/simplicio-mapper#236, #279

## Contexto verificado

`simplicio-cli 0.16.1` declara `simplicio-mapper>=0.23.1`, enquanto o Mapper já publica `0.24.0`. O range permite resolução recente em instalação limpa, mas não atualiza ambientes/locks existentes, não prova a combinação e não propaga uma nova release do Dev CLI para o Loop.

## Objetivo

Automatizar os dois lados do Dev CLI no release train:

1. consumir imediatamente a última release compatível e verificada do Mapper;
2. publicar sua própria release/contratos;
3. disparar atualização do `simplicio-loop`.

## Passo a passo

1. Declarar no component manifest a dependência Mapper, schemas e compatibility range.
2. Receber release event do Mapper e reconciliar registries.
3. Criar/atualizar um único PR de bump por release train, sem PR storm.
4. Atualizar constraint e lock/resolution efetiva; registrar versão/digest testado.
5. Rodar mapper contract tests com pacote instalado e fixtures N/N-1.
6. Rodar tarefas reais map→retrieve→edit→test→receipt.
7. Comparar performance e economia com baseline.
8. Auto-merge somente se schemas, correctness, security e budgets passarem.
9. Publicar Dev CLI com `component-release/v1`, SBOM, provenance e changelog.
10. Disparar bump do Loop após PyPI confirmado.
11. Bloquear versões yanked/revoked e suportar rollback.
12. Expor `simplicio-cli versions --json` com latest/installed/tested.
13. Detectar ambiente antigo e oferecer upgrade sem interromper task ativa.
14. Documentar expand→migrate→contract para breaking changes.

## Testes obrigatórios

- Mapper patch/minor compatible e incompatible;
- lock antigo, instalação limpa e offline;
- evento duplicado/perdido;
- package publicado mas artifact indisponível;
- map/schema drift;
- concurrent bump PRs;
- yanked/revoked version;
- regressão de task receipt;
- Windows/Linux/macOS;
- propagação Dev CLI→Loop;
- rollback para último conjunto verde.

## Critérios de aceite

- [ ] A resolução testada usa a última versão compatível do Mapper.
- [ ] Range amplo nunca substitui lock/digest/evidência da combinação.
- [ ] Bump PR nasce em até 15 minutos e é deduplicado.
- [ ] Conformance instalada bloqueia incompatibilidade.
- [ ] PR verde compatível pode auto-merge.
- [ ] Dev CLI publica manifest assinado e dispara o consumidor Loop.
- [ ] Versão antiga sem justificativa abre drift issue automaticamente.
- [ ] Nenhum update ocorre durante task em andamento.
- [ ] Rollback preserva receipts/cache compatíveis.
- [ ] p95, tokens e CPU/RSS não ultrapassam budgets.
- [ ] Doctor mostra latest, installed, compatibility e blocked reason.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][Release Train] Atualizar Mapper automaticamente e propagar a release do Dev CLI ao Loop

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: CPU/RSS, Criar/atualizar, N/N-1., Windows/Linux/macOS, ambientes/locks, component-release/v1, duplicado/perdido, github.com/wesleysimplicio/simplicio-loop/issues/558, latest/installed/tested., lock/digest/evidência, lock/resolution, map/schema, patch/minor, receipts/cache, release/contratos, versão/digest, wesleysimplicio/simplicio-mapper, yanked/revoked.

#### Dependências e ordem

Referências explícitas: #231, #279. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #236 — [P0][Prototype-First][Loop #568] Implementar scaffold, dry-run, validate e promoção segura de protótipos

- Estado/data: `closed`; criada `2026-07-18T13:16:47Z`; atualizada `2026-07-19T02:00:35Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

Upstream contract: [simplicio-loop#568](https://github.com/wesleysimplicio/simplicio-loop/issues/568)

## Objetivo

Adicionar ao Dev CLI a camada determinística de operação do Prototype-First Gate: converter planos/context packs em scaffolds e candidatos isolados, validar artifacts e promover somente o candidate aceito para o próximo nível.

## Fluxo produtivo

```text
Loop plan + Mapper context
→ dev-cli prototype scaffold
→ dry-run patch/schema/test/model
→ Runtime sandbox execution
→ validate + evidence
→ candidate receipt
→ accepted promotion into isolated worktree
```

Nenhum comando `prototype` pode alterar branch/shared target por default.

## Passo a passo

1. Consumir schemas/hash/capabilities de #568.
2. Criar comandos `prototype plan|scaffold|dry-run|validate|diff|promote|reject|doctor --json`.
3. Implementar scaffolds por tipo: schema, data model, failing test, mock/fake, code spike, vertical slice.
4. Gerar patch plan e preview antes de escrever.
5. Aplicar P1 em sandbox e P2 em worktree/transaction isolada.
6. Integrar validators reais do projeto e evidence capture.
7. Implementar content hashes, source drift e stale-candidate rejection.
8. Promover apenas com `prototype-decision/v1 ACCEPT` válido.
9. Revalidar após promoção e produzir rollback plan.
10. Integrar deterministic edits/diagnostics existentes, sem duplicar Runtime.
11. Implementar batch/fan-out com backpressure.
12. Publicar contract tests com Loop/Mapper/Runtime.

## Testes obrigatórios

- cada artifact type;
- dry-run sem escrita;
- accepted/rejected/revised/stale;
- forged decision;
- partial patch/rollback;
- Windows/Linux/macOS;
- concurrent worktrees;
- validator missing/failing;
- performance em 100/1.000 candidates.

## Critérios de aceite

- [ ] Dry-run prova zero mudança no working tree.
- [ ] Scaffolds seguem context/negative-space do Mapper.
- [ ] P1/P2 escrevem somente em destinos isolados.
- [ ] FULL é bloqueado sem decision receipt válido quando required.
- [ ] Source/plan drift invalida candidate.
- [ ] Validate executa comandos reais e guarda evidence.
- [ ] Promote é atômico, revalidado e reversível.
- [ ] Nenhum fallback contorna Runtime/action gate.
- [ ] Batch respeita quotas e não corrompe artifacts.
- [ ] CLI humana e automação usam o mesmo contrato.
- [ ] Testes unitários, contract, integração, sistema, segurança e performance passam.
- [ ] Cobertura mínima de 85%.

## Definition of Done

Um task set gera schema, failing test e code spike; o CLI pré-visualiza sem escrever, executa candidatos isolados, rejeita decision forjada/stale, promove apenas o vencedor aceito e reverte uma validação pós-promoção falha.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][Prototype-First][Loop #568] Implementar scaffold, dry-run, validate e promoção segura de protótipos

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: 100/1.000, Loop/Mapper/Runtime., P1/P2, Runtime/action, Source/plan, Windows/Linux/macOS, accepted/rejected/revised/stale, batch/fan-out, branch/shared, context/negative-space, edits/diagnostics, forjada/stale, github.com/wesleysimplicio/simplicio-loop/issues/568, missing/failing, mock/fake, patch/rollback, patch/schema/test/model, planos/context, prototype-decision/v1, schemas/hash/capabilities, worktree/transaction.

#### Dependências e ordem

Referências explícitas: #568. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #237 — feat(token-economy): substituir estimativa words*4/3 por medição tiktoken auditável

- Estado/data: `closed`; criada `2026-07-18T14:17:39Z`; atualizada `2026-07-18T14:23:51Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **CLOSE-READY**

#### Contexto e problema

## Objetivo
Trocar a estimativa canônica `words*4/3` por contagem BPE com `openai/tiktoken`, sem alterar o caminho de execução nem tornar observabilidade bloqueante.

## Contexto auditado
`simplicio/observability.py:estimate_tokens` alimenta `providers.py`, o cost governor, `runs.jsonl`, eventos e o ledger de savings. Hoje a métrica é coerente internamente, mas imprecisa para código, JSON, TOON e prompts multilíngues.

## Implementação incremental
1. Adicionar `tiktoken` como dependência de runtime e resolver encoding por `SIMPLICIO_MODEL`; quando o modelo não tiver mapeamento, usar `o200k_base`.
2. Manter uma única API `estimate_tokens(text)`, vazia = 0, sem mudar consumidores.
3. Tornar a função fail-open: se o tokenizer não estiver disponível ou falhar, usar o fallback atual e expor o modo no rótulo/registro.
4. Atualizar `ESTIMATOR_LABEL` e os campos de evento/ledger para distinguir `provider`, `tiktoken` e `heuristic-fallback`; nenhum número local deve ser chamado de medido pelo provedor.
5. Preservar contagens reais de `usage` do provedor como fonte prioritária.
6. Testar texto vazio, inglês, português, código/JSON, modelo conhecido, modelo desconhecido e falha simulada do tokenizer.

## Critérios de aceite
- [ ] Toda estimativa local passa pelo mesmo tokenizer canônico.
- [ ] `runs.jsonl` identifica origem e encoding, sem prompt bruto.
- [ ] Provider usage continua vencendo qualquer estimativa.
- [ ] Falha do tokenizer nunca interrompe geração, cache ou ledger.
- [ ] Testes existentes e novos passam; não há regressão do schema de eventos.
- [ ] PR inclui benchmark comparando heuristic x BPE em prompt, diff e TOON.

## Fora de escopo
Não impor orçamento/bloqueio nesta issue; a decisão de política fica no runtime/loop.

#### Objetivo

Entregar e provar o resultado delimitado por: feat(token-economy): substituir estimativa words*4/3 por medição tiktoken auditável

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: 4/3, código/JSON, evento/ledger, openai/tiktoken, orçamento/bloqueio, runtime/loop., rótulo/registro., simplicio/observability.py.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #243 — bug: build_precedent_block crashes with KeyError on fresh repo when SIMPLICIO_ENABLE_EMBED_INDEX is unset (default)

- Estado/data: `closed`; criada `2026-07-18T20:54:01Z`; atualizada `2026-07-18T21:45:26Z`
- Labels: `nenhuma`
- Classificação: `{"component": "prompt", "epic": "standalone", "priority": "unassigned", "risk": "low"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": true, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Resumo

`simplicio-py bench` (e, pela mesma call chain, `simplicio-py run`/`task`) quebra com um `KeyError` cru sempre que:
1. o repo é novo (sem `.simplicio/emb_cache.npz`/`emb_index.json` prévios, ou sem histórico de precedente),
2. `grep_candidates()` encontra ao menos um bloco de código correspondente ao stack, e
3. `SIMPLICIO_ENABLE_EMBED_INDEX` **não** está setado — ou seja, a configuração padrão de qualquer instalação nova (`pip install -e .`, sem extras).

Isso não é um edge case: é o caminho default em qualquer repo novo com código real no stack detectado.

## Causa raiz

`simplicio/precedent.py`:

- `_embedding_index_enabled()` (linha 162) só retorna `True` se a env var `SIMPLICIO_ENABLE_EMBED_INDEX` estiver setada para `1/true/yes/on` — **opt-in, desligado por padrão**.
- `index_repo()` (linha 194): quando `_embedding_index_enabled()` é `False`, pula o embedding (`embedded=0`, nunca chama `cache.add()`/`cache.save()`), mas **ainda retorna `cache, cands`** normalmente, como se os candidatos estivessem cacheados.
- `build_precedent_block()` (linha 214): quando `rank_precedents()` retorna vazio (comum em repo novo), cai no fallback (linha 237+): chama `index_repo()`, pega `cands` não-vazio (via grep), e então executa incondicionalmente `cache.lookup(texts)` (linha 241) — **sem checar se o embedding foi de fato pulado**.
- `EmbeddingCache.lookup()` (`cache.py` linha 56-59): `rows = [self.index[self.h(t)] for t in texts]` — acesso direto ao dict, sem `.get()`/fallback, então lança `KeyError` na primeira hash ausente.

Resultado: em instalação padrão (`pip install -e .`, sem `SIMPLICIO_ENABLE_EMBED_INDEX=1` e sem `sentence-transformers` instalado — que também não vem no install base, só documentado como dependência transitiva pesada), o pipeline "with simplicio" nunca chega a chamar o LLM: quebra antes, dentro de `build_prompt → build_precedent_block`.

## Repro

Ambiente: `pip install -e .` limpo (sem extras) a partir deste repo, Python 3.11, sem `sentence-transformers` instalado, sem `SIMPLICIO_ENABLE_EMBED_INDEX` setado.

```bash
# projeto fixture qualquer com >=1 arquivo .py contendo padrões do stack "python"
git init && git add -A && git commit -m "init"
export SIMPLICIO_MODEL=claude-cli/sonnet   # ou qualquer provider configurado
simplicio-py bench --root . --stack python --cases bench/cases.json
```

Saída:

```
[provider_completed] {"label":"Claude Code CLI (`claude -p`)","elapsed_s":14.46}
simplicio-py: error: '6074dccb7bfedf46bc652025ce8c01655d680ae9'
```

A mensagem de erro exposta ao usuário é literalmente o hash SHA1 que faltava no cache (`KeyError` sem tratamento vazando até a CLI) — nem sequer indica que o problema é embedding/precedent.

Traceback completo (reproduzido chamando `run_bench` diretamente):

```
Traceback (most recent call last):
  File "simplicio/bench.py", line 98, in run_bench
    out_with = _pipeline(c, root, stack)
  File "simplicio/bench.py", line 57, in _pipeline
    prompt = build_prompt(...)
  File "simplicio/prompt.py", line 66, in build_prompt
    prec = build_precedent_block(root, stack, goal, k=2)
  File "simplicio/precedent.py", line 241, in build_precedent_block
    vc = cache.lookup(texts)  # from cache, no re-embed
  File "simplicio/cache.py", line 58, in lookup
    rows = [self.index[self.h(t)] for t in texts]
KeyError: '6074dccb7bfedf46bc652025ce8c01655d680ae9'
```

## Impacto

- O braço "with simplicio" de `simplicio-py bench` nunca produz um resultado em repo novo/config default — o comando cujo próprio propósito é provar "with vs without" quebra exatamente no lado que deveria provar o valor do produto.
- Mesma call chain (`build_prompt` → `build_precedent_block`) é usada por `simplicio-py run`/`task`, então o mesmo crash deve atingir o fluxo principal de edição também, não só o bench — não testei `run`/`task` isoladamente neste relato, mas a stack de chamada é idêntica.
- A mensagem de erro (`'<hash>'`) não dá nenhuma pista ao usuário sobre a causa real (embedding desabilitado + fallback sem guarda).

## Sugestão de fix

Uma das duas (ou ambas):

1. `EmbeddingCache.lookup()` deveria degradar graciosamente em vez de `KeyError` cru — retornar `None`/vazio para hashes ausentes, ou expor um `lookup_safe()` que filtra candidatos sem embedding em vez de quebrar.
2. `build_precedent_block()` deveria checar `_embedding_index_enabled()` **antes** de entrar no branch de similaridade vetorial (linha 237+) e cair direto no fallback textual (`"(no match for {stack!r})"` ou equivalente) quando o embedding está desligado — em vez de assumir que `index_repo()` sempre deixa o cache populado.

Prefiro a opção 2 como fix principal (trata a causa: o fallback não deveria tentar usar um cache que sabe que não populou) mais um guard defensivo na opção 1 (correção de robustez do `cache.py`, independente do caller).

## Como encontrei

Rodando um benchmark real "com vs sem simplicio" (CRUD de usuários, `simplicio-py bench` com `SIMPLICIO_MODEL=claude-cli/sonnet`) para medir tempo e tokens do ecossistema Simplicio ponta a ponta. O braço "without" completou normalmente (chamada real ao `claude -p`, 14.46s); o braço "with" quebrou antes de qualquer chamada ao LLM.

#### Objetivo

Entregar e provar o resultado delimitado por: bug: build_precedent_block crashes with KeyError on fresh repo when SIMPLICIO_ENABLE_EMBED_INDEX is unset (default)

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .simplicio/emb_cache.npz, 1/true/yes/on, bench/cases.json, claude-cli/sonnet, embedding/precedent., novo/config, simplicio/bench.py, simplicio/cache.py, simplicio/precedent.py, simplicio/prompt.py.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #246 — proposta: teste por propriedade/fuzzing + fixtures com código real + revisão por invariante

- Estado/data: `closed`; criada `2026-07-19T00:22:29Z`; atualizada `2026-07-19T01:20:55Z`
- Labels: `nenhuma`
- Classificação: `{"component": "prompt", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

Ver [simplicio-loop#579](https://github.com/wesleysimplicio/simplicio-loop/issues/579) (issue hub, mesmo raciocínio replicado em todos os repos do ecossistema).

Nesta sessão, um bug-hunt dedicado encontrou um bug real e sério neste repo que o DoD dos 7 pilares (implementation+unit+integration+system+regression+perf+coverage≥85%) não pegou: `simplicio/mechanical_edit.py`, `_operation_order()` decidia honrar o campo `order` explícito checando `all(...)` no **plano inteiro**, enquanto `_validate_overlaps()` decide sobreposição por **arquivo**. Um plano multi-arquivo com ordenação explícita correta num arquivo + qualquer operação sem `order` noutro arquivo (ex. `create_file`) aplicava as edições fora de ordem — **corrompendo o arquivo silenciosamente e reportando `"status": "ok"`**. Já corrigido localmente (escopar o check de "todas as ops têm order explícito" por arquivo, não por plano inteiro), com teste de regressão novo.

## Proposta concreta pra este repo

1. **Hypothesis** (property-based) para `simplicio/mechanical_edit.py` — gerar planos aleatórios com N arquivos, M operações por arquivo, combinações de `order` explícito/ausente, e verificar a propriedade central: "o resultado final do arquivo bate com aplicar as operações na ordem correta", não só "o comando retornou `status: ok`". Esse é exatamente o tipo de bug (interação entre duas funções com granularidade de escopo diferente) que fuzzing de combinações pega e teste por exemplo não pega.
2. Mesma técnica vale pra `simplicio/providers.py` (dispatch entre os 5 modos de provider) e `simplicio/precedent.py`/`cache.py` (já corrigido uma vez nesta sessão, issue #243 — mas o padrão "cache populado vs não populado em combinação com outro estado" é exatamente o tipo de caso que Hypothesis geraria sozinho).
3. **Fixtures com repositórios reais** — os testes de `mechanical_edit`/`edit` deveriam incluir pelo menos um cenário rodando contra um repo com estrutura real (múltiplos arquivos, imports cruzados), não só arquivos isolados sintéticos.
4. **Checklist de invariante no PR template**: "se este PR adiciona uma função que particiona/agrupa uma lista de itens (arquivos, operações, candidatos), ela usa a mesma chave/granularidade que outras funções que processam a mesma lista?" — pergunta direta que teria pego o bug sem precisar de nenhum teste.
5. **Testes de integração devem afirmar sobre o conteúdo final do arquivo**, não só sobre o `status`/`errors` retornado pela ferramenta — esse é o gap que deixou o bug passar despercebido mesmo com `status: ok` sendo checado.

#### Objetivo

Entregar e provar o resultado delimitado por: proposta: teste por propriedade/fuzzing + fixtures com código real + revisão por invariante

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: chave/granularidade, explícito/ausente, github.com/wesleysimplicio/simplicio-loop/issues/579, particiona/agrupa, simplicio/mechanical_edit.py, simplicio/precedent.py, simplicio/providers.py.

#### Dependências e ordem

Referências explícitas: #243. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #247 — DoD Camada 3/4: mutation testing, contract tests, eval harness — plano passo a passo

- Estado/data: `closed`; criada `2026-07-19T00:55:07Z`; atualizada `2026-07-19T01:20:56Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

References #579 (hub) and #246. This repo just landed Layer 1/2 of the 4-layer
DoD framework (`DOD.md`, added in commit implementing #246): universal gates
(coverage, regression tests) and risk-surface gates (property testing via
Hypothesis, invariant review). This issue tracks the remaining Layer 3
(sprint/release cadence) and Layer 4 (ecosystem/release) items, which are
real work, not something to fake past with a lower bar.

Both layers below are motivated by the same two real bugs that motivated
`DOD.md` itself: `simplicio/mechanical_edit.py`'s `_operation_order()` vs
`_validate_overlaps()` granularity mismatch (fixed in `d24e18c`, corrupted a
file silently while reporting `status: ok`) and `simplicio-mapper`'s
`mapper/graph.py` regex line-number bug (fixed in `464cc03` in that repo,
fabricated phantom self-call graph edges while reporting success). Neither
would have been caught by "tests are green" alone; a note in this session's
findings while wiring the coverage gate: `.github/workflows/` was removed
entirely in `d7ff8c9` (billing lockout + centralization on
`simplicio-runtime`), which also silently disabled the lint (`ruff check .`
/ `mypy simplicio`) and coverage CI jobs — 32 pre-existing ruff errors and 7
pre-existing mypy errors currently sit uncaught in the tree outside any file
this issue's originating PR touched, alongside 21 pre-existing pytest
failures (3 of them reading now-deleted `.github/workflows/*.yml` files).
That debt is out of scope for this issue but should be swept up as part of
whichever of the items below touches those files first (or as its own
follow-up if none do).

## 1. Mutation testing (`mutmut`)

Priority order, both modules chosen because they had a **real, silent**
bug fixed this session — the exact failure shape mutation testing is meant
to catch (a mutant survives because no test actually asserts the
observable, correct result, only that *some* result came back):

- [ ] `simplicio/mechanical_edit.py` — start with `_operation_order()` and
  `_validate_overlaps()` specifically (the two functions whose granularity
  mismatch caused `d24e18c`); the new Hypothesis property test
  (`test_explicit_order_survives_any_shuffle_of_unordered_ops_across_n_files`
  in `tests/python/test_mechanical_edit.py`) should kill mutants a narrow
  unit test would miss — verify that with `mutmut run --paths-to-mutate
  simplicio/mechanical_edit.py` and check the surviving-mutant list by hand.
- [ ] `simplicio/precedent.py` — currently the lowest-coverage "critical"
  module per `[tool.coverage.simplicio_critical]` in `pyproject.toml` (66%
  per the last local run); mutation testing here will likely surface gaps
  before a coverage number would.
- [ ] Wire a `mutmut run` step somewhere real (pre-commit is too slow for
  this; a periodic/manual sprint-cadence script under `scripts/` is more
  appropriate, matching Layer 3's "not required per-PR" framing in
  `DOD.md`). Do not silently skip if `mutmut` isn't installed — either add
  it as a `dev`-extra dependency (ask before adding, per `AGENTS.md`'s
  "no new dependency without asking" rule) or document the manual install
  step.
- [ ] Record a baseline mutation score for both modules so future
  regressions in "tests only assert status, not the real result" are
  visible as a number, not a vibe.

## 2. Contract tests (both schema directions)

This repo is simultaneously a **consumer** of `simplicio-mapper`'s output
(reads `.simplicio/project_map.json` / `.simplicio/precedent_index.json`,
checks the `schema` field for compatibility — see `simplicio/mapper.py`
around line 221-259) and a **producer** of
`simplicio.mechanical-edit/v1` / `simplicio.mechanical-edit-result/v1`
(`simplicio/mechanical_edit.py`, `PLAN_SCHEMA`/`RESULT_SCHEMA` constants),
consumed downstream by callers like `simplicio-loop`/`simplicio-runtime`.

- [ ] **Consumer side**: a contract test that pins the exact schema shape
  `simplicio-mapper` is expected to produce (field names, types, the
  `schema` version string) and fails loudly — not silently falls back —
  when a real `simplicio-mapper` install produces something this repo's
  `mapper.py` doesn't recognize. `tests/contracts/` already exists as a
  test path (see `testpaths` in `pyproject.toml`) — check what's already
  there before adding a new one.
- [ ] **Producer side**: a contract test asserting `execute_plan_json`'s
  output always validates against a frozen JSON Schema for
  `simplicio.mechanical-edit-result/v1`, so a field rename/removal in
  `mechanical_edit.py` fails a test instead of silently breaking every
  downstream consumer that pattern-matches this repo's JSON output.
- [ ] Decide and document where the frozen schema files live (this repo,
  a shared schema repo, or duplicated with a drift check like
  `scripts/gen_package_interdependence.py` does for the dependency graph
  doc) — don't just wing it per-test.

## 3. Eval / pass-rate harness (`bench.py` → N-run pass-rate)

`simplicio/bench.py` already compares WITH vs WITHOUT the pipeline
(baseline raw-goal vs precedent+skill+layers+verify) and writes
`bench/results.md`, but each case currently runs **once** — a single
pass/fail proves nothing about reliability of an LLM-routed path.

- [ ] Extend `bench.py` (or add a thin wrapper) to run each case N≥20 times
  and report a **pass rate** (e.g. "17/20, 85%") instead of a single
  pass/fail, using the same `_test()`/`_baseline()` machinery already
  there.
- [ ] Decide the N and the acceptable-pass-rate floor per case type
  (mechanical/deterministic cases should be ~100%; LLM-routed generation
  cases will legitimately be lower — don't apply one floor to both).
  Document the reasoning, don't just pick a number.
- [ ] Wire this as a Layer 4 (ecosystem/release) check, not per-PR — it's
  real LLM spend, matching `DOD.md`'s framing of what's "generally too
  expensive to run per-PR."
- [ ] Record results with enough detail to distinguish "the pipeline is
  flaky" from "this specific case is flaky" — per-case history, not just
  an aggregate number.

## Out of scope for this issue (tracked separately)

- Restoring `.github/workflows/` / centralized CI on `simplicio-runtime` —
  that's the billing-lockout/centralization decision itself, not a DoD
  framework task.
- Raising `mechanical_edit.py`/`doctor.py`/`execution_contract.py`/
  `pipeline.py` to the 90% critical-module coverage floor
  (`scripts/coverage_gate.py` currently reports 71%/73%/88%/87.5%
  respectively) — real coverage work, not a config change; flag as its own
  task if picked up.
- The 21 pre-existing pytest failures / 32 ruff errors / 7 mypy errors
  noted above — pre-existing debt, unrelated to the DoD framework itself,
  but should be triaged (fixed or explicitly written off with a reason)
  before any of this issue's items can honestly claim a clean baseline to
  measure mutation score or contract-test pass/fail against.

#### Objetivo

Entregar e provar o resultado delimitado por: DoD Camada 3/4: mutation testing, contract tests, eval harness — plano passo a passo

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .github/workflows, .github/workflows/*.yml, .simplicio/precedent_index.json, .simplicio/project_map.json, 1/2, 17/20, bench/results.md, billing-lockout/centralization, ecosystem/release, mapper/graph.py, mechanical/deterministic, pass/fail, periodic/manual, rename/removal, scripts/coverage_gate.py, scripts/gen_package_interdependence.py, simplicio.mechanical-edit-result/v1, simplicio.mechanical-edit/v1, simplicio/bench.py, simplicio/mapper.py, simplicio/mechanical_edit.py, simplicio/precedent.py, sprint/release, tests/contracts, tests/python/test_mechanical_edit.py.

#### Dependências e ordem

Referências explícitas: #246, #579. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #251 — [Audit #582] Restore blocking CI coverage gate and remove stale workflow references

- Estado/data: `open`; criada `2026-07-19T03:35:10Z`; atualizada `2026-07-21T20:46:01Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **NEEDS-IMPLEMENTATION**

#### Contexto e problema

The repository has `scripts/coverage_gate.py` and local pre-commit hooks, but no effective `.github/workflows` coverage workflow was discoverable. This reproduces the integrity gap recorded in simplicio-loop#582.

## Acceptance criteria
- Restore a blocking PR/push CI workflow invoking the real coverage gate.
- Verify the documented threshold equals the enforced threshold.
- Audit tests/docs for references to workflow files that no longer exist and fix or remove each stale reference.
- Add a repository self-check and report evidence to simplicio-loop#582.

<!-- SIMPLICIO-ISSUE-AUDIT:v1 -->
## Revisão complementar do projeto: simplicio-dev-cli

Responsabilidade avaliada: **CLI**. Esta issue deve ser entendida no contexto da auditoria-mãe do repositório.

### Objetivo específico

validar CLI → Mapper → PlanDAG → Runtime → saída auditável

### Fluxo de testes obrigatório

happy path, argumentos inválidos, worktree, snapshot, retry, timeout, export e compatibilidade

1. Registrar SHA/branch, ambiente, dependências e configuração.
2. Executar o caminho feliz completo e capturar logs/receipts.
3. Injetar entrada inválida, timeout, falha externa ou permissão ausente aplicável.
4. Verificar retry, cancelamento, idempotência e rollback quando o fluxo suportar.
5. Executar testes unitários, integração, sistema/E2E, regressão, segurança e desempenho aplicáveis.
6. Reexecutar com os mesmos dados e comparar resultado/hashes.
7. Confirmar que falha nunca vira sucesso e que recursos são liberados.

### Critérios de aceite adicionais

- [ ] O comportamento principal está demonstrado por teste executável.
- [ ] Pelo menos um caminho de falha está coberto e documentado.
- [ ] Contratos entre projetos são validados nas versões/SHAs declarados.
- [ ] Logs e receipts permitem reconstruir a decisão.
- [ ] Métricas não observáveis são `null` com motivo, nunca estimadas.
- [ ] Segredos, PII e dados privados não aparecem nos artefatos.
- [ ] O procedimento é reproduzível localmente ou em container sem GitHub Actions pago.
- [ ] PR/commit, logs, hashes e riscos residuais estão anexados antes de fechar.

### Evidências obrigatórias

- PR/commit vinculado;
- comandos e versões;
- logs do caminho feliz e da falha;
- testes/coverage/benchmark aplicáveis;
- receipts, hashes e relatório de rollback;
- limitações e próximos passos.

### Regra de encerramento

Não fechar sem todos os critérios desta issue e da auditoria-mãe atendidos. Se faltar implementação, marcar como `NEEDS-IMPLEMENTATION` ou `BLOCKED`, nunca como concluída.

#### Objetivo

Entregar e provar o resultado delimitado por: [Audit #582] Restore blocking CI coverage gate and remove stale workflow references

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: .github/workflows, PR/commit, PR/push, SHA/branch, logs/receipts., resultado/hashes., scripts/coverage_gate.py, sistema/E2E, testes/coverage/benchmark, tests/docs, versões/SHAs.

#### Dependências e ordem

Referências explícitas: #582. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #252 — fix(task): remover shadowing do assembler de TaskResult e restaurar receipt estruturado

- Estado/data: `closed`; criada `2026-07-19T23:29:08Z`; atualizada `2026-07-19T23:51:45Z`
- Labels: `bug`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Problema

`simplicio-dev-cli task --dry-run-task --json` falhava com traceback:

```
_task_result() got an unexpected keyword argument 'target_kind'
```

## Causa raiz

`simplicio/pipeline.py` importava o assembler extraído de `pipeline_task_result.py`, mas o sobrescrevia depois com uma cópia local antiga. O CLI chamava a assinatura obsoleta, perdia receipts nativos de impacto e podia classificar incorretamente um arquivo existente como novo.

## Correção concluída

- [x] implementação duplicada/sombreada removida;
- [x] único assembler canônico usado;
- [x] precondições de arquivo novo versus existente corrigidas;
- [x] receipt nativo de impacto preservado;
- [x] regressões de identidade da função e do envelope adicionadas.

## Critérios de aceite

- [x] task dry-run retorna envelope estruturado sem traceback;
- [x] arquivo existente não recebe precondição de novo arquivo;
- [x] receipt nativo de impacto é preservado;
- [x] testes focados de pipeline/mapper/runtime passam;
- [x] wheel `simplicio_cli-0.16.1-py3-none-any.whl` construída e instalada com Mapper e Loop atuais;
- [x] PR #253 mesclado e revalidado em `main`;
- [x] branch default atual (`master`, pendente de troca administrativa na #98) fast-forwarded para o mesmo SHA de `main`.

## Evidência local

- 91 testes focados passaram no gate principal; slice ampliado: 140 passaram;
- smoke estruturado de task sem traceback;
- wheel SHA-256: `1b4707a077aede7d418e089e1c64952c45ae305dce86ec52b59bd91c97c0d0e3`;
- smoke instalado: `wheel+mapper+loop: ok`;
- entrada `simplicio-py --help` executada a partir do wheel;
- `main` e `master` reconsultadas como idênticas em `d5dbb07b0372e48fde05793c6103251fa0276abd`.

PR: https://github.com/wesleysimplicio/simplicio-dev-cli/pull/253

GitHub Actions não faz parte do aceite.

#### Objetivo

Entregar e provar o resultado delimitado por: fix(task): remover shadowing do assembler de TaskResult e restaurar receipt estruturado

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: duplicada/sombreada, github.com/wesleysimplicio/simplicio-dev-cli/pull/253, pipeline/mapper/runtime, simplicio/pipeline.py.

#### Dependências e ordem

Referências explícitas: #98, #253. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #255 — [P0][Contracts] Remover ContextSnapshot v1 incompatível e consumir a ABI canônica do Mapper

- Estado/data: `closed`; criada `2026-07-20T00:39:23Z`; atualizada `2026-07-21T04:49:25Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Contexto

O `simplicio-dev-cli` declara localmente `simplicio.context-snapshot/v1` em `simplicio/plan_compiler/models.py`, mas o modelo possui shape diferente do contrato produzido pelo `simplicio-mapper`. O Mapper é o owner federado desse schema.

Contrato canônico em construção/congelamento:

- [Mapper #317 — ContextSnapshot/ContextGraph v1 e kit de conformidade](https://github.com/wesleysimplicio/simplicio-mapper/issues/317)

Arquitetura relacionada:

- [Runtime #3134](https://github.com/wesleysimplicio/simplicio-runtime/issues/3134)
- [Runtime #3136](https://github.com/wesleysimplicio/simplicio-runtime/issues/3136)

## Problema

O Dev CLI usa o mesmo schema id para um payload simplificado, criando falsa compatibilidade. Isso permite que:

- testes locais passem com um contrato que o Mapper nunca emite;
- campos obrigatórios do Mapper sejam descartados;
- `PlanDAG` seja compilado a partir de contexto sem fidelity/provenance verificáveis;
- mudanças cross-repo quebrem apenas em runtime;
- fixtures copiadas divirjam silenciosamente.

## Resultado esperado

Remover o shadow contract do Dev CLI e consumir a ABI canônica publicada pelo Mapper, preservando compatibilidade explícita durante a migração.

Após a mudança, nenhum modelo do Dev CLI pode declarar `simplicio.context-snapshot/v1` sem passar pela contract suite do Mapper.

## Escopo

- modelos do plan compiler;
- `mapper.py`, `map_handoff`, `pipeline_task_result` e call sites;
- armazenamento/cache local do snapshot;
- conversão de snapshot canônico para as views internas necessárias ao planner;
- negociação de versão;
- migração de artefatos antigos;
- testes cross-repo e clean install.

## Não objetivos

- duplicar o schema do Mapper dentro do Dev CLI;
- tornar o Mapper dependência do domínio de planejamento;
- permitir que o Dev CLI modifique snapshots;
- alterar o schema `PlanDAG` nesta issue;
- aceitar silenciosamente payload incompatível.

## Plano passo a passo

1. Inventariar todos os usos de `ContextSnapshot`, `snapshot_id`, `revision`, `base_sha`, `root` e `extra`.
2. Classificar cada campo atual:
   - equivalente canônico;
   - derivável;
   - somente interno;
   - obsoleto;
   - sem equivalente e requer decisão.
3. Remover do Dev CLI a declaração de ownership do schema id.
4. Adicionar dependência/adaptador sobre o artefato de contrato publicado por Mapper #317, pinado por versão e digest.
5. Criar um `MapperContextAdapter` de borda que:
   - valide schema/version/digest;
   - preserve o payload canônico;
   - exponha views internas tipadas ao plan compiler;
   - não altere ou reserialize com perda;
   - retorne reason codes em falha.
6. Atualizar `PlanDAG` para referenciar `snapshot_id`, revision/content hash e, quando aplicável, subgraph/context-pack handles — sem incorporar uma segunda cópia do graph.
7. Migrar `map_handoff` e `pipeline_task_result` para transportar provenance completa.
8. Definir comportamento por modo:
   - integrated: contrato canônico obrigatório;
   - standalone com Mapper instalado: contrato canônico;
   - standalone sem Mapper: fallback explicitamente identificado por outro schema id, nunca `simplicio.context-snapshot/v1`.
9. Criar leitor/migrador para artefatos legados do Dev CLI:
   - detecção inequívoca do shape antigo;
   - conversão somente quando todos os invariantes puderem ser provados;
   - erro fail-closed caso contrário;
   - nenhum overwrite sem backup/receipt.
10. Remover schemas/fixtures copiados e substituí-los por consumo pinado do kit de Mapper #317.
11. Adicionar CI cross-repo minimum/latest e teste fora de checkouts irmãos.
12. Documentar matriz de compatibilidade, fallback, migration e rollback.
13. Instrumentar contadores de:
   - canonical snapshot accepted;
   - legacy migrated;
   - fallback used;
   - schema mismatch;
   - fidelity rejected.

## Testes obrigatórios

### Unitários

- parse e validação das fixtures canônicas;
- mapeamento canônico → view interna;
- preservação de ids, hashes e source handles;
- rejeição do payload shadow atual sob o schema id v1;
- reason codes para versão/hash/fidelity inválidos;
- fallback usa schema id distinto.

### Contract tests

- rodar integralmente as fixtures publicadas por Mapper #317;
- testar N/N-1;
- falhar quando digest pinado divergir;
- detectar breaking change no mesmo v1.

### Migração

- artefato legado convertível;
- artefato ambíguo;
- artefato incompleto;
- rollback;
- idempotência da migração;
- nenhum dado original perdido.

### Integração/E2E

- instalar Mapper e Dev CLI fora dos checkouts;
- produzir snapshot real pelo Mapper;
- compilar `PlanDAG` usando esse snapshot;
- provar que o plan referencia exatamente o snapshot/hash produzido;
- alterar deliberadamente a fixture e provar falha antes do planejamento.

## Critérios de aceite

- [ ] Não existe no Dev CLI uma segunda definição de `simplicio.context-snapshot/v1`.
- [ ] Todo snapshot com esse id é validado pelo contrato publicado em Mapper #317.
- [ ] O payload canônico é preservado sem perda; views internas são derivadas.
- [ ] `PlanDAG` referencia snapshot/revision/hash verificáveis.
- [ ] O antigo shape do Dev CLI é rejeitado quando usa o schema id canônico.
- [ ] Fallback standalone, se mantido, usa outro schema id e é observável.
- [ ] Migração de legado é explícita, idempotente e rollbackável.
- [ ] CI minimum/latest não depende de checkout irmão ou schema copiado.
- [ ] Schema mismatch bloqueia antes da compilação do plano.
- [ ] Métricas distinguem canonical, legacy, fallback e rejected.
- [ ] Documentação de compatibilidade e runbook de rollback estão publicados.
- [ ] Clean install Mapper → snapshot → Dev CLI → PlanDAG passa com receipts e digests.

## Evidências exigidas para fechamento

- diff removendo o shadow model/schema;
- versão e digest do contrato Mapper consumido;
- logs da suite de conformidade;
- golden E2E instalado;
- fixture negativa representando o payload antigo;
- matriz N/N-1;
- receipt do plan contendo o snapshot id/hash;
- comandos exatos e artifacts de CI.

Esta issue não fecha com adapter mockado ou teste que importa o Mapper de um checkout irmão.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][Contracts] Remover ContextSnapshot v1 incompatível e consumir a ABI canônica do Mapper

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: ContextSnapshot/ContextGraph, Integração/E2E, N/N-1, armazenamento/cache, backup/receipt., construção/congelamento, dependência/adaptador, fidelity/provenance, github.com/wesleysimplicio/simplicio-mapper/issues/317, github.com/wesleysimplicio/simplicio-runtime/issues/3134, github.com/wesleysimplicio/simplicio-runtime/issues/3136, id/hash, leitor/migrador, minimum/latest, model/schema, revision/content, schema/version/digest, schemas/fixtures, simplicio.context-snapshot/v1, simplicio/plan_compiler/models.py, snapshot/hash, snapshot/revision/hash, subgraph/context-pack, versão/hash/fidelity.

#### Dependências e ordem

Referências explícitas: #317, #3134, #3136. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #256 — [P0][EffectSink] Implementar RuntimeEffectSink real com EffectTransaction e receipts

- Estado/data: `open`; criada `2026-07-20T00:42:49Z`; atualizada `2026-07-21T20:46:04Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **NEEDS-IMPLEMENTATION**

#### Contexto e problema

## Contexto

O Plan Compiler já produz PlanDAG/EffectPlan, porém o modo integrado usa RecordingEffectSink, que apenas registra propostas localmente. accepted=true significa custódia no stub; não prova gate, aplicação, validação, rollback ou receipt do Runtime.

Dependências e owners existentes:

- [Runtime #3218 — EffectTransaction/v1](https://github.com/wesleysimplicio/simplicio-runtime/issues/3218)
- [Runtime #3284 — Effect Executor real](https://github.com/wesleysimplicio/simplicio-runtime/issues/3284)
- [Runtime #3134 — coordenadores independentes; Runtime executa](https://github.com/wesleysimplicio/simplicio-runtime/issues/3134)
- [Agent #222 — SimplicioBridge](https://github.com/wesleysimplicio/simplicio-agent/issues/222)
- [Dev CLI #255 — ContextSnapshot canônico](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/255)

## Problema

O Dev CLI pode declarar execução integrada sem entregar efeitos ao owner determinístico. Isso mantém dois caminhos de escrita e perde causalidade, idempotência e evidência verificável.

## Resultado esperado

Implementar RuntimeEffectSink real sobre contratos públicos do Runtime. No modo integrado, Dev CLI compila o plano e solicita efeitos autorizados; nunca aplica write/commit diretamente.

RecordingEffectSink deve permanecer somente para testes explícitos.

## Escopo

- mapping EffectPlan → EffectRequest/EffectTransaction;
- capability/version negotiation;
- transportes públicos suportados;
- causal IDs e idempotência;
- state/outcome completo;
- validação de receipts;
- reconciliation;
- observabilidade e circuit breaker;
- testes instalados e fault injection.

## Não objetivos

- redefinir schemas do Runtime;
- implementar executor dentro do Dev CLI;
- retry automático de efeito ambíguo;
- exigir Simplicio Agent como coordenador exclusivo;
- remover standalone nesta issue.

## Plano passo a passo

1. Congelar tabela de mapping entre EffectPlan/PlanNode e os campos Runtime.
2. Implementar RuntimeEffectSink concreto e selecionar transporte por capability negotiation, não por parsing de help ou presença de arquivo.
3. Propagar coordinator_kind/coordinator_id, session, turn, attempt, subworkflow, plan_node e effect IDs.
4. Gerar idempotency key estável a partir de identidade causal + digest do efeito; mesma key com digest distinto deve falhar.
5. Propagar deadline, risk/policy revision, preconditions, base/source hashes, read/write sets, validation plan e rollback policy.
6. Persistir intent local mínimo antes do envio e outcome/receipt antes de responder ao caller.
7. Mapear sem perda os estados:
   - not_started;
   - denied;
   - running;
   - completed;
   - validation_failed;
   - rolled_back;
   - blocked_conflict;
   - cancelled_safe;
   - effect_unknown.
8. Substituir bool accepted por outcome tipado. Custódia não pode ser confundida com efeito aplicado.
9. Verificar schema, digest, correlation IDs, gate decision, hashes, validation e redaction de todo receipt.
10. Implementar query/reconcile por idempotency key para resposta perdida ou restart.
11. Proibir retry/fallback automático em effect_unknown; devolver decisão ao coordenador.
12. Implementar circuit breaker e health/capability status, preservando reason codes.
13. Remover writes diretos do modo integrado e adicionar guard/regression test contra reintrodução.
14. Instrumentar latency, transport, reconnect, dedupe, outcome, fallback e receipt verification sem prompts/secrets.
15. Documentar recovery, diagnóstico, versão mínima/máxima e rollback.

## Testes obrigatórios

### Contract/unit

- fixtures oficiais do Runtime;
- mapping completo request/receipt;
- allow/deny;
- malformed/tampered receipt;
- schema/version incompatível;
- causal ID mismatch;
- idempotency same key/same digest e same key/different digest.

### Falhas e recuperação

- resposta perdida após efeito;
- timeout antes/depois da admission;
- disconnect;
- crash/restart;
- replay;
- validation_failed + rollback;
- blocked conflict;
- cancelled safe;
- effect_unknown sem retry.

### Integração

- parity CLI/MCP/binding para o mesmo contrato quando suportados;
- Runtime instalado fora do checkout;
- coordenador Simplicio Agent e pelo menos um coordenador diferente;
- stale source hash bloqueia antes de mutar;
- receipt correlaciona plan node, AC e effect id.

### Segurança

- secrets/prompt ausentes em logs/receipts;
- payload oversized;
- path/write-set escape;
- forged coordinator/receipt.

## Critérios de aceite

- [ ] Produção integrada nunca instancia RecordingEffectSink.
- [ ] Dev CLI não escreve, commita ou aplica patch no modo integrado.
- [ ] Todo efeito termina com receipt Runtime verificado ou estado não terminal/ambíguo explícito.
- [ ] accepted não é usado como sinônimo de applied/completed.
- [ ] Replay da mesma key/digest não duplica efeito.
- [ ] Key igual com digest diferente falha fechado.
- [ ] effect_unknown nunca dispara retry ou fallback automático.
- [ ] IDs causais, plan node e ACs atravessam request e receipt.
- [ ] Validation/rollback são preservados no outcome.
- [ ] Transportes públicos têm contract parity.
- [ ] Mesmo contrato funciona sem depender do processo/SDK privado do Agent.
- [ ] Clean install e fault injection estão verdes.
- [ ] Guard test impede write direto no integrated mode.

## Evidências exigidas para fechamento

- trace PlanDAG → EffectTransaction → Gate → effect → validation → receipt;
- versões/digests de Dev CLI e Runtime;
- fixtures e contract results;
- fault matrix com replay/unknown/rollback;
- prova de zero writes diretos;
- logs redigidos;
- comandos de clean install;
- raw outcomes/latencies.

A issue não fecha com fake executor, fixture-only integration ou receipt fabricado no Dev CLI.

<!-- SIMPLICIO-ISSUE-AUDIT:v1 -->
## Revisão complementar do projeto: simplicio-dev-cli

Responsabilidade avaliada: **CLI**. Esta issue deve ser entendida no contexto da auditoria-mãe do repositório.

### Objetivo específico

validar CLI → Mapper → PlanDAG → Runtime → saída auditável

### Fluxo de testes obrigatório

happy path, argumentos inválidos, worktree, snapshot, retry, timeout, export e compatibilidade

1. Registrar SHA/branch, ambiente, dependências e configuração.
2. Executar o caminho feliz completo e capturar logs/receipts.
3. Injetar entrada inválida, timeout, falha externa ou permissão ausente aplicável.
4. Verificar retry, cancelamento, idempotência e rollback quando o fluxo suportar.
5. Executar testes unitários, integração, sistema/E2E, regressão, segurança e desempenho aplicáveis.
6. Reexecutar com os mesmos dados e comparar resultado/hashes.
7. Confirmar que falha nunca vira sucesso e que recursos são liberados.

### Critérios de aceite adicionais

- [ ] O comportamento principal está demonstrado por teste executável.
- [ ] Pelo menos um caminho de falha está coberto e documentado.
- [ ] Contratos entre projetos são validados nas versões/SHAs declarados.
- [ ] Logs e receipts permitem reconstruir a decisão.
- [ ] Métricas não observáveis são `null` com motivo, nunca estimadas.
- [ ] Segredos, PII e dados privados não aparecem nos artefatos.
- [ ] O procedimento é reproduzível localmente ou em container sem GitHub Actions pago.
- [ ] PR/commit, logs, hashes e riscos residuais estão anexados antes de fechar.

### Evidências obrigatórias

- PR/commit vinculado;
- comandos e versões;
- logs do caminho feliz e da falha;
- testes/coverage/benchmark aplicáveis;
- receipts, hashes e relatório de rollback;
- limitações e próximos passos.

### Regra de encerramento

Não fechar sem todos os critérios desta issue e da auditoria-mãe atendidos. Se faltar implementação, marcar como `NEEDS-IMPLEMENTATION` ou `BLOCKED`, nunca como concluída.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][EffectSink] Implementar RuntimeEffectSink real com EffectTransaction e receipts

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: CLI/MCP/binding, Contract/unit, EffectPlan/PlanNode, EffectRequest/EffectTransaction, EffectTransaction/v1, PR/commit, PlanDAG/EffectPlan, SHA/branch, Validation/rollback, allow/deny, antes/depois, applied/completed., base/source, capability/version, coordinator/receipt., coordinator_kind/coordinator_id, crash/restart, github.com/wesleysimplicio/simplicio-agent/issues/222, github.com/wesleysimplicio/simplicio-dev-cli/issues/255, github.com/wesleysimplicio/simplicio-runtime/issues/3134, github.com/wesleysimplicio/simplicio-runtime/issues/3218, github.com/wesleysimplicio/simplicio-runtime/issues/3284, guard/regression, health/capability, key/different, key/digest, key/same, logs/receipts, logs/receipts., malformed/tampered, mínima/máxima, outcome/receipt, outcomes/latencies., path/write-set, processo/SDK, prompts/secrets., query/reconcile, read/write, replay/unknown/rollback, request/receipt, resultado/hashes., retry/fallback, risk/policy, schema/version, secrets/prompt, sistema/E2E, state/outcome, terminal/ambíguo, testes/coverage/benchmark, versões/SHAs, versões/digests, write/commit.

#### Dependências e ordem

Referências explícitas: #222, #255, #3134, #3218, #3284. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #257 — [P0][Entrypoint] Expor modo integrado e torná-lo o caminho negociado para coordenadores

- Estado/data: `open`; criada `2026-07-20T00:46:36Z`; atualizada `2026-07-21T20:46:05Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **NEEDS-IMPLEMENTATION**

#### Contexto e problema

## Contexto

[#256](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/256) entrega o RuntimeEffectSink real e [#255](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/255) corrige ContextSnapshot. Ainda falta expor o modo integrado como produto. Hoje ele é essencialmente um parâmetro Python interno; o caminho normal permanece standalone e pode aplicar patch local.

Relações: [Runtime #3136](https://github.com/wesleysimplicio/simplicio-runtime/issues/3136), [Runtime #3218](https://github.com/wesleysimplicio/simplicio-runtime/issues/3218) e [Agent #222](https://github.com/wesleysimplicio/simplicio-agent/issues/222).

## Resultado esperado

Expor auto, integrated e standalone em CLI/config/API. auto seleciona por capability handshake. integrated falha fechado sem contratos compatíveis e nunca cai silenciosamente em standalone.

## Plano passo a passo

1. Definir semântica:
   - auto: resolve por handshake + policy/profile;
   - integrated: exige RuntimeEffectSink e ContextSnapshot canônico;
   - standalone: lifecycle local explícito.
2. Adicionar --mode auto|integrated|standalone a task, feature e sprint aplicáveis, com equivalentes config/env/API e precedência documentada.
3. Produzir execution profile com requested/effective mode, coordinator, Mapper contract, sink, Runtime version/capability e fallback reason.
4. Em auto, usar handshake versionado; proibir inferência por arquivo, help ou nome de processo.
5. Em integrated:
   - exigir #256;
   - exigir snapshot real #255;
   - bloquear antes de plan/effect se incompatível;
   - proibir qualquer write local.
6. Em standalone:
   - manter compatibilidade;
   - identificar receipts/status como standalone;
   - não alegar gate/evidence Runtime.
7. Remover snapshot_id sintético derivado de path. Sem snapshot real, retornar CONTEXT_REQUIRED ou INCOMPATIBLE_CONTEXT.
8. Criar doctor/capabilities --json com modo solicitado/efetivo, contracts/digests, sink, coordinator, degradações e elegibilidade para default.
9. Propagar modo por CLI, API, workers, packages e receipts.
10. Implementar rollout shadow → canary → default, kill switch e rollback governado.
11. Nunca trocar de modo após effect_unknown ou outcome ambíguo.
12. Instrumentar seleção, fallback, mismatch e outcomes.
13. Documentar matriz, exemplos, troubleshooting e recovery.

## Testes obrigatórios

- auto/integrated/standalone × Runtime presente/ausente/incompatível;
- Mapper presente/ausente/incompatível;
- coordinator Agent e não-Agent;
- policy permite/proíbe fallback;
- CLI/API/task/feature/sprint parity;
- stdout JSON limpo;
- clean install;
- integrated sem sink/snapshot falha antes de write;
- standalone não emite receipt Runtime;
- shadow não muta duas vezes;
- canary, kill switch e rollback;
- effect_unknown nunca muda o modo.

## Critérios de aceite

- [ ] Modo é selecionável sem API Python interna.
- [ ] auto usa handshake versionado.
- [ ] integrated falha fechado sem RuntimeEffectSink/capability.
- [ ] integrated exige ContextSnapshot real.
- [ ] Nenhum write local ocorre em integrated.
- [ ] standalone continua funcional, explícito e não se apresenta como integrado.
- [ ] doctor explica requested/effective mode, contracts, sink e razão.
- [ ] CLI/API/entrypoints instalados têm paridade.
- [ ] effect_unknown não dispara fallback/troca de modo.
- [ ] Rollout e rollback são exercitados.
- [ ] Métricas distinguem seleção normal, degradação e erro.
- [ ] Promoção a default referencia receipts E2E/DEFAULT/GATED, não testes locais.

## Evidências de fechamento

- matriz completa;
- outputs doctor/capabilities;
- trace auto→integrated e fail-closed;
- prova de snapshot real e zero write local;
- clean install;
- rollout/rollback receipts;
- versões/digests.

Não fecha se integrated continuar interno ou se auto puder cair silenciosamente em standalone.

<!-- SIMPLICIO-ISSUE-AUDIT:v1 -->
## Revisão complementar do projeto: simplicio-dev-cli

Responsabilidade avaliada: **CLI**. Esta issue deve ser entendida no contexto da auditoria-mãe do repositório.

### Objetivo específico

validar CLI → Mapper → PlanDAG → Runtime → saída auditável

### Fluxo de testes obrigatório

happy path, argumentos inválidos, worktree, snapshot, retry, timeout, export e compatibilidade

1. Registrar SHA/branch, ambiente, dependências e configuração.
2. Executar o caminho feliz completo e capturar logs/receipts.
3. Injetar entrada inválida, timeout, falha externa ou permissão ausente aplicável.
4. Verificar retry, cancelamento, idempotência e rollback quando o fluxo suportar.
5. Executar testes unitários, integração, sistema/E2E, regressão, segurança e desempenho aplicáveis.
6. Reexecutar com os mesmos dados e comparar resultado/hashes.
7. Confirmar que falha nunca vira sucesso e que recursos são liberados.

### Critérios de aceite adicionais

- [ ] O comportamento principal está demonstrado por teste executável.
- [ ] Pelo menos um caminho de falha está coberto e documentado.
- [ ] Contratos entre projetos são validados nas versões/SHAs declarados.
- [ ] Logs e receipts permitem reconstruir a decisão.
- [ ] Métricas não observáveis são `null` com motivo, nunca estimadas.
- [ ] Segredos, PII e dados privados não aparecem nos artefatos.
- [ ] O procedimento é reproduzível localmente ou em container sem GitHub Actions pago.
- [ ] PR/commit, logs, hashes e riscos residuais estão anexados antes de fechar.

### Evidências obrigatórias

- PR/commit vinculado;
- comandos e versões;
- logs do caminho feliz e da falha;
- testes/coverage/benchmark aplicáveis;
- receipts, hashes e relatório de rollback;
- limitações e próximos passos.

### Regra de encerramento

Não fechar sem todos os critérios desta issue e da auditoria-mãe atendidos. Se faltar implementação, marcar como `NEEDS-IMPLEMENTATION` ou `BLOCKED`, nunca como concluída.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][Entrypoint] Expor modo integrado e torná-lo o caminho negociado para coordenadores

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: CLI/API/entrypoints, CLI/API/task/feature/sprint, CLI/config/API., E2E/DEFAULT/GATED, PR/commit, RuntimeEffectSink/capability., SHA/branch, auto/integrated/standalone, config/env/API, contracts/digests, doctor/capabilities, fallback/troca, gate/evidence, github.com/wesleysimplicio/simplicio-agent/issues/222, github.com/wesleysimplicio/simplicio-dev-cli/issues/255, github.com/wesleysimplicio/simplicio-dev-cli/issues/256, github.com/wesleysimplicio/simplicio-runtime/issues/3136, github.com/wesleysimplicio/simplicio-runtime/issues/3218, logs/receipts., permite/proíbe, plan/effect, policy/profile, presente/ausente/incompatível, receipts/status, requested/effective, resultado/hashes., rollout/rollback, sink/snapshot, sistema/E2E, solicitado/efetivo, testes/coverage/benchmark, version/capability, versões/SHAs, versões/digests..

#### Dependências e ordem

Referências explícitas: #222, #255, #256, #3136, #3218. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #258 — [P0][Ownership] Uma tentativa atômica no integrado e zero scheduler/retry duplicado

- Estado/data: `open`; criada `2026-07-20T00:47:15Z`; atualizada `2026-07-21T20:46:06Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **NEEDS-IMPLEMENTATION**

#### Contexto e problema

## Contexto

[#257](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/257) torna o modo integrado selecionável e [#256](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/256) entrega effects ao Runtime. Ainda resta ownership duplicado dentro do Dev CLI:

- run_task possui tentativas internas;
- run_feature/max_iter e TaskBatch mantêm scheduling próprio;
- pools/worktrees/model invocations podem se multiplicar;
- docs registram cenário de retry externo × retry interno, por exemplo 3×5=15 tentativas.

No modo integrado, retry/replan/stop pertencem ao coordenador/Loop do subworkflow; Dev CLI deve executar uma tentativa atômica e devolver observação tipada.

## Resultado esperado

Uma invocação integrada do Dev CLI executa no máximo uma tentativa atômica por WorkItem/PlanNode/attempt_id. Dev CLI não agenda, replana, decide completion nem cria pools paralelos nesse modo.

Standalone pode preservar lifecycle local temporariamente, de forma isolada, observável e com prazo de migração.

## Relações

- [#256 RuntimeEffectSink](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/256)
- [#257 modo integrado](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/257)
- histórico [#166 Plan Compiler](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/166)
- histórico [#231 Loop Hub worker](https://github.com/wesleysimplicio/simplicio-dev-cli/issues/231)
- [Runtime #3134](https://github.com/wesleysimplicio/simplicio-runtime/issues/3134)

## Plano passo a passo

1. Inventariar call graph real de run_task, run_feature, TaskBatch, scratch executor, planner retries, model/subprocess/worktree creation e operational memory.
2. Produzir tabela owner por capability nos modos integrated/standalone.
3. Definir execute_work_item_once(plan_node, attempt, lease/fence, context_handle, effect_sink) → typed observation.
4. Garantir que a função:
   - não faz retry/replan;
   - não agenda outro item;
   - não escolhe next node;
   - não cria pool;
   - não altera attempt_id;
   - não declara completion global.
5. Fazer o modo integrated chamar exatamente uma vez execute_work_item_once por dispatch.
6. Migrar feature/sprint para PlanDAG/WorkItems; no modo integrated desativar run_feature.max_iter, MAX_ATTEMPTS, TaskBatch scheduler e ThreadPoolExecutor local.
7. Receber do coordenador attempt_id, retry policy resultante, deadline, cancellation, lease e fencing token.
8. Respeitar cancel/lease loss/fence antes de cada boundary mutante; devolver estado tipado.
9. Retornar observação suficiente para decisão externa:
   - outcome;
   - reason/failure fingerprint;
   - retryability declarada pelo executor, não decisão de retry;
   - evidence/receipt handles;
   - validation;
   - resource/latency/tokens;
   - context/effect IDs.
10. Remover ownership duplicado de queue, operational memory e terminal status no integrated.
11. Manter scheduler/retry legado apenas em standalone, em namespace/store/processo isolados, com telemetry e expiry.
12. Adicionar invariantes/runtime guards que detectem nested attempt ou pool local em integrated.
13. Medir antes/depois: attempts, model calls, subprocessos, threads, worktrees, effects, tokens, p50/p95 e AC success.
14. Documentar migration, compatibility e rollback.

## Testes obrigatórios

- outer retry N gera exatamente N atomic attempts, nunca N×M;
- feature max_iter não atua no integrated;
- 20 WorkItems não criam pool local no Dev CLI;
- cancel antes/durante boundaries;
- lease loss e stale fencing;
- retryable/non-retryable/effect_unknown;
- crash/restart com attempt id;
- PlanDAG deps/conflitos;
- integrated e standalone não compartilham queue/state;
- standalone parity;
- package instalado;
- coordinator Agent e não-Agent;
- guard falha diante de nested retry/scheduler.

## Critérios de aceite

- [ ] Uma invocação integrada executa no máximo uma tentativa atômica.
- [ ] Dev CLI não decide retry, replan, next node ou completion em integrated.
- [ ] Nenhum ThreadPoolExecutor/scheduler/worktree/model pool local nasce nesse modo.
- [ ] Feature/sprint usam PlanDAG/WorkItems, sem DAG paralelo divergente.
- [ ] attempt_id, lease e fence vêm do coordenador e são preservados nos receipts.
- [ ] Lease loss/cancel impedem novo efeito.
- [ ] Observação permite ao coordenador decidir a próxima ação.
- [ ] Standalone permanece explícito, isolado e medido.
- [ ] Não há operational memory/queue/terminal writer duplicado.
- [ ] N retries externos resultam em N, não N×M, model/effect attempts.
- [ ] Benchmark mostra counts brutos e não reduz AC/evidence success.
- [ ] Guard tests impedem regressão.

## Evidências de fechamento

- call graph e tabela de ownership before/after;
- traces N=1, N=3 e failure/retry;
- process/thread/worktree counts;
- cancel/lease/fence matrix;
- PlanDAG feature/sprint E2E;
- standalone parity;
- benchmark bruto e versões/digests.

Não fecha apenas configurando MAX_ATTEMPTS=1 por env; o caminho integrado deve estruturalmente não possuir retry/scheduler interno.

<!-- SIMPLICIO-ISSUE-AUDIT:v1 -->
## Revisão complementar do projeto: simplicio-dev-cli

Responsabilidade avaliada: **CLI**. Esta issue deve ser entendida no contexto da auditoria-mãe do repositório.

### Objetivo específico

validar CLI → Mapper → PlanDAG → Runtime → saída auditável

### Fluxo de testes obrigatório

happy path, argumentos inválidos, worktree, snapshot, retry, timeout, export e compatibilidade

1. Registrar SHA/branch, ambiente, dependências e configuração.
2. Executar o caminho feliz completo e capturar logs/receipts.
3. Injetar entrada inválida, timeout, falha externa ou permissão ausente aplicável.
4. Verificar retry, cancelamento, idempotência e rollback quando o fluxo suportar.
5. Executar testes unitários, integração, sistema/E2E, regressão, segurança e desempenho aplicáveis.
6. Reexecutar com os mesmos dados e comparar resultado/hashes.
7. Confirmar que falha nunca vira sucesso e que recursos são liberados.

### Critérios de aceite adicionais

- [ ] O comportamento principal está demonstrado por teste executável.
- [ ] Pelo menos um caminho de falha está coberto e documentado.
- [ ] Contratos entre projetos são validados nas versões/SHAs declarados.
- [ ] Logs e receipts permitem reconstruir a decisão.
- [ ] Métricas não observáveis são `null` com motivo, nunca estimadas.
- [ ] Segredos, PII e dados privados não aparecem nos artefatos.
- [ ] O procedimento é reproduzível localmente ou em container sem GitHub Actions pago.
- [ ] PR/commit, logs, hashes e riscos residuais estão anexados antes de fechar.

### Evidências obrigatórias

- PR/commit vinculado;
- comandos e versões;
- logs do caminho feliz e da falha;
- testes/coverage/benchmark aplicáveis;
- receipts, hashes e relatório de rollback;
- limitações e próximos passos.

### Regra de encerramento

Não fechar sem todos os critérios desta issue e da auditoria-mãe atendidos. Se faltar implementação, marcar como `NEEDS-IMPLEMENTATION` ou `BLOCKED`, nunca como concluída.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][Ownership] Uma tentativa atômica no integrado e zero scheduler/retry duplicado

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: AC/evidence, Feature/sprint, PR/commit, PlanDAG/WorkItems, SHA/branch, ThreadPoolExecutor/scheduler/worktree/model, WorkItem/PlanNode/attempt_id., antes/depois, antes/durante, before/after, cancel/lease, cancel/lease/fence, context/effect, coordenador/Loop, crash/restart, deps/conflitos, evidence/receipt, failure/retry, feature/sprint, github.com/wesleysimplicio/simplicio-dev-cli/issues/166, github.com/wesleysimplicio/simplicio-dev-cli/issues/231, github.com/wesleysimplicio/simplicio-dev-cli/issues/256, github.com/wesleysimplicio/simplicio-dev-cli/issues/257, github.com/wesleysimplicio/simplicio-runtime/issues/3134, integrated/standalone., invariantes/runtime, lease/fence, logs/receipts., loss/cancel, loss/fence, memory/queue/terminal, model/effect, model/subprocess/worktree, namespace/store/processo, p50/p95, pools/worktrees/model, process/thread/worktree, queue/state, reason/failure, resource/latency/tokens, resultado/hashes., retry/replan, retry/replan/stop, retry/scheduler, retry/scheduler., retryable/non-retryable/effect_unknown, run_feature/max_iter, scheduler/retry, sistema/E2E, testes/coverage/benchmark, versões/SHAs, versões/digests..

#### Dependências e ordem

Referências explícitas: #166, #231, #256, #257, #3134. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #259 — [P0][Local Inference Pause] Desabilitar inferência local automática no Dev CLI

- Estado/data: `closed`; criada `2026-07-21T02:40:19Z`; atualizada `2026-07-21T04:44:02Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "P0", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": false}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Objetivo

Pausar **por padrão** toda inferência local do Simplicio Dev CLI — incluindo MiniCPM5/llama.cpp, Qwen, Ollama e qualquer backend/modelo local futuro — sem remover artefatos já instalados e sem degradar os fluxos determinísticos do CLI.

Esta é uma medida reversível de segurança, custo e previsibilidade. Não usa GitHub Actions; a evidência de aceite será produzida e anexada localmente.

## Contrato de comportamento

- O estado padrão efetivo é `local_inference=disabled`.
- Configuração vazia, configuração legada, perfil recém-instalado e atualização não podem baixar modelo, carregar peso, iniciar processo local, abrir porta, chamar rede, nem escolher inferência local automaticamente.
- Isso inclui aliases implícitos de MiniCPM5/llama.cpp, Qwen e Ollama; o bloqueio deve ser por classe de backend, não por uma lista incompleta de nomes.
- Fluxos determinísticos continuam operacionais sem LLM: `recipe`, `map`, `plan`, validação, testes e demais comandos puramente locais.
- Provedor remoto só pode ser usado mediante seleção explícita do usuário; não pode haver fallback silencioso do local bloqueado para rede/remoto.
- Cada decisão deve retornar o motivo estável `LOCAL_INFERENCE_PAUSED` e um *policy receipt* com modo solicitado/efetivo, origem da configuração, backend recusado e correlação.
- A reativação futura exige configuração explícita, escopo, confirmação de política e trilha de auditoria; este item não reativa modelo algum.

## Implementação

1. Centralizar a resolução de provider/modelo antes de qualquer download, carregamento, spawn ou conexão.
2. Introduzir política fail-closed compatível com configurações antigas: valores ausentes e aliases legados resolvem para `disabled`.
3. Garantir que todos os entrypoints (CLI, API/bindings, comandos auxiliares e instalador/upgrade) compartilham a mesma resolução e o mesmo receipt.
4. Separar de forma explícita os caminhos determinísticos dos caminhos de inferência.
5. Documentar como observar o bloqueio e como uma reativação futura será autorizada, sem recomendar bypass.

## Critérios de aceite

- [ ] Em ambiente limpo e com configuração vazia, cada comando de inferência retorna `LOCAL_INFERENCE_PAUSED` antes de I/O de modelo, criação de processo ou rede.
- [ ] Configurações antigas/aliases de MiniCPM5, llama.cpp, Qwen e Ollama também são bloqueados antes de efeitos.
- [ ] Não há download, carregamento, subprocesso, socket ou porta local nos testes de bloqueio.
- [ ] `recipe`, `map`, `plan` e testes determinísticos continuam funcionando sem provider local.
- [ ] Provider remoto só é alcançado quando selecionado explicitamente e deixa receipt verificável; bloqueio local nunca promove fallback remoto.
- [ ] CLI, bindings e superfícies auxiliares exibem o mesmo modo efetivo, motivo estável e receipt.
- [ ] Suite local cobre instalação limpa, configuração legada, cancelamento/retry e reativação negada sem autorização; resultados são anexados à PR.
- [ ] Nenhum workflow de GitHub Actions é criado, modificado ou usado como evidência.

## Dependências e ordem

- Runtime #3490 define a política global de pausa e o motivo canônico.
- Dev CLI #256, #257 e #258 devem propagar a política, receipt e roteamento integrado.
- Para qualquer capacidade/MCP do Runtime que produza efeito, aplicar também o firewall Runtime #3491: o efeito atravessa exclusivamente o executor/EffectTransaction do Runtime.

## Fora de escopo

Não apagar modelos existentes, não reativar inferência local, não tornar o Runtime opcional para capacidades que já o selecionaram.

#### Objetivo

Entregar e provar o resultado delimitado por: [P0][Local Inference Pause] Desabilitar inferência local automática no Dev CLI

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: API/bindings, I/O, MiniCPM5/llama.cpp, antigas/aliases, backend/modelo, cancelamento/retry, capacidade/MCP, executor/EffectTransaction, instalador/upgrade, provider/modelo, rede/remoto., solicitado/efetivo.

#### Dependências e ordem

Referências explícitas: #256, #257, #258, #3490, #3491. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #261 — [Binary formats] Migrate internal JSON state to HBP, HBI and TOML

- Estado/data: `closed`; criada `2026-07-21T04:44:57Z`; atualizada `2026-07-21T12:49:53Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": false, "tests_mentioned": true}`
- Decisão: **HISTORICAL-EVIDENCE-GAP**

#### Contexto e problema

## Parent decision

- Architecture program: https://github.com/wesleysimplicio/simplicio-runtime/issues/3492
- Accepted ADR draft: https://github.com/wesleysimplicio/simplicio-runtime/pull/3493
- Depends on Runtime HBI v1 for HBI-labeled artifacts.

## Objective

Remove JSON/JSONL/NDJSON from cache, command state, ecosystem/run/edit/task/gate flows, observability, scratch state and benchmark/release evidence.

## Evidence to audit first

`simplicio/cache.py`, `_cache.py`, `commands/run.py`, `commands/edit.py`, `ecosystem.py`, `observability.py`, `bench/run_exec.py` and `bench/results_*.json`

Search results are starting points only. The implementation must trace producers, readers, generated outputs, package contents and runtime directories.

## Target architecture

Use HBI for cache/indexed workspace snapshots; HBP for run, gate, benchmark and release receipts; TOML for user configuration; consume Runtime/Mapper through binary contracts.

## Implementation steps

1. Add a reviewed `config/json-boundaries.toml` inventory containing exact path/module, producer, consumer, lifecycle, category, owner and target format.
2. Scan source and build outputs for JSON files, imports, serializers, JSONL/NDJSON, JSON-RPC and embedded JSON.
3. Classify each match as internal persistence/cache/IPC/evidence, external protocol/export, toolchain-mandated or immutable historical documentation.
4. Map append-only/auditable data to HBP, read-mostly/indexed data to conformant HBI, and human-edited configuration to typed TOML.
5. Replace inter-Simplicio JSON contracts with versioned binary envelopes and generated typed bindings.
6. Implement legacy migration with dry-run, bounded parse, backup, atomic write, semantic/integrity verification and idempotent resume.
7. Remove legacy writers. Any temporary reader or double-write path needs a feature flag, owner, telemetry and removal date.
8. Update documentation, samples, fixtures and package contents so internal JSON is not regenerated.
9. Record measured before/after artifact size, latency, allocations and peak RSS.
10. Link the compatibility/quality issue and block release until it passes.

## Required tests

- unit tests for each new codec/config model;
- golden HBP/HBI/TOML fixtures;
- legacy migration from minimum/current/large/corrupt/truncated inputs;
- interruption and concurrent-reader/writer scenarios;
- semantic equivalence of representative workflows;
- no raw external JSON crosses an adapter boundary;
- clean install, upgrade and rollback;
- package scan proving removed artifacts are not reintroduced.

## Acceptance criteria

- [ ] Every JSON occurrence is classified in the TOML inventory.
- [ ] No owned internal persistence, cache, IPC, queue, evidence or index uses JSON/JSONL/NDJSON.
- [ ] HBP/HBI/TOML ownership follows the ADR and HBI conformance is proven.
- [ ] External/toolchain exceptions are exact, owned, justified and dated.
- [ ] Legacy migration is atomic, idempotent and preserves backups.
- [ ] Legacy writers are removed; temporary readers have an expiry.
- [ ] Representative workflows pass without a JSON internal fallback.
- [ ] Performance evidence uses observed values or `null` plus a reason, never estimates.

#### Objetivo

Entregar e provar o resultado delimitado por: [Binary formats] Migrate internal JSON state to HBP, HBI and TOML

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: External/toolchain, HBP/HBI/TOML, JSON/JSONL/NDJSON, JSON/JSONL/NDJSON., JSONL/NDJSON, Runtime/Mapper, append-only/auditable, before/after, bench/results_*.json, bench/run_exec.py, benchmark/release, cache/indexed, codec/config, commands/edit.py, commands/run.py, compatibility/quality, concurrent-reader/writer, config/json-boundaries.toml, ecosystem/run/edit/task/gate, github.com/wesleysimplicio/simplicio-runtime/issues/3492, github.com/wesleysimplicio/simplicio-runtime/pull/3493, minimum/current/large/corrupt/truncated, path/module, persistence/cache/IPC/evidence, protocol/export, read-mostly/indexed, semantic/integrity, simplicio/cache.py.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #262 — [Quality] Enforce no-internal-JSON and prove binary-format migration E2E

- Estado/data: `open`; criada `2026-07-21T04:45:46Z`; atualizada `2026-07-21T20:46:07Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "standalone", "priority": "unassigned", "risk": "high"}`
- Rastreabilidade original: `{"evidence_mentioned": false, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **NEEDS-IMPLEMENTATION**

#### Contexto e problema

## Dependencies

- Architecture program: https://github.com/wesleysimplicio/simplicio-runtime/issues/3492
- Accepted ADR draft: https://github.com/wesleysimplicio/simplicio-runtime/pull/3493
- Repository migration: https://github.com/wesleysimplicio/simplicio-dev-cli/issues/261
- HBI v1 conformance: https://github.com/wesleysimplicio/simplicio-runtime/issues/3494
- Shared policy scanner: https://github.com/wesleysimplicio/simplicio-runtime/issues/3496

## Objective

Make the repository migration release-blocking and prove that cache hit/miss, run/edit/task/gate commands, Mapper consumption, Runtime delegation, benchmark/release gates and installed CLI upgrades work without JSON in any Simplicio-owned internal path.

## Implementation steps

1. Integrate the pinned shared scanner in baseline and strict CI modes.
2. Check source, tests, fixtures, generated outputs, build/package contents and runtime state directories.
3. Add an exact TOML exception registry; reject broad globs, missing owners, missing reasons and expired exceptions.
4. Add unit tests for codecs/config models and corruption/bounds behavior.
5. Add integration tests for HBP/HBI/TOML producers and consumers.
6. Add system tests that restart processes, recover from interruption and verify semantic state.
7. Add cross-repository E2E using released/installed packages rather than only source checkouts.
8. Exercise clean install, legacy upgrade, rollback and mixed-version rejection/compatibility windows.
9. Verify third-party JSON is accepted/emitted only in explicit adapters and cannot enter domain/storage types.
10. Publish Markdown test summary plus HBP receipts; do not generate internal JSON evidence.
11. Benchmark cold/warm behavior, file size, allocations and peak RSS on the same workload/hardware.
12. Protect the release so missing/unobservable evidence is `null` with a reason and never treated as a passing zero.

## Required test matrix

- Linux, macOS and Windows where the repository ships support;
- empty/minimal/large state;
- legacy/current/future-version artifact;
- corrupt/truncated/oversized/out-of-bounds artifact;
- interrupted migration and concurrent access;
- clean install, upgrade, rollback and restart;
- source checkout and installed package;
- online external adapter and offline internal workflow;
- supported adjacent Simplicio producer/consumer versions.

## Acceptance criteria

- [ ] Strict scanner reports zero unclassified internal JSON findings.
- [ ] Every exception is exact, owned, justified and dated.
- [ ] No package or generated output recreates removed internal JSON.
- [ ] Unit, integration, system and cross-repository E2E lanes pass.
- [ ] HBI artifacts pass the Runtime conformance suite; no custom mmap layout is mislabeled HBI.
- [ ] HBP receipts prove execution and migration lineage.
- [ ] Legacy migration is atomic, idempotent and interruption-safe.
- [ ] Raw third-party JSON cannot cross adapter boundaries.
- [ ] No silent fallback to JSON occurs after any binary/TOML error.
- [ ] Performance report contains real measured data or explicit unavailable reasons.
- [ ] Release/publish jobs are blocked when any criterion fails.


<!-- SIMPLICIO-ISSUE-AUDIT:v1 -->
## Revisão complementar do projeto: simplicio-dev-cli

Responsabilidade avaliada: **CLI**. Esta issue deve ser entendida no contexto da auditoria-mãe do repositório.

### Objetivo específico

validar CLI → Mapper → PlanDAG → Runtime → saída auditável

### Fluxo de testes obrigatório

happy path, argumentos inválidos, worktree, snapshot, retry, timeout, export e compatibilidade

1. Registrar SHA/branch, ambiente, dependências e configuração.
2. Executar o caminho feliz completo e capturar logs/receipts.
3. Injetar entrada inválida, timeout, falha externa ou permissão ausente aplicável.
4. Verificar retry, cancelamento, idempotência e rollback quando o fluxo suportar.
5. Executar testes unitários, integração, sistema/E2E, regressão, segurança e desempenho aplicáveis.
6. Reexecutar com os mesmos dados e comparar resultado/hashes.
7. Confirmar que falha nunca vira sucesso e que recursos são liberados.

### Critérios de aceite adicionais

- [ ] O comportamento principal está demonstrado por teste executável.
- [ ] Pelo menos um caminho de falha está coberto e documentado.
- [ ] Contratos entre projetos são validados nas versões/SHAs declarados.
- [ ] Logs e receipts permitem reconstruir a decisão.
- [ ] Métricas não observáveis são `null` com motivo, nunca estimadas.
- [ ] Segredos, PII e dados privados não aparecem nos artefatos.
- [ ] O procedimento é reproduzível localmente ou em container sem GitHub Actions pago.
- [ ] PR/commit, logs, hashes e riscos residuais estão anexados antes de fechar.

### Evidências obrigatórias

- PR/commit vinculado;
- comandos e versões;
- logs do caminho feliz e da falha;
- testes/coverage/benchmark aplicáveis;
- receipts, hashes e relatório de rollback;
- limitações e próximos passos.

### Regra de encerramento

Não fechar sem todos os critérios desta issue e da auditoria-mãe atendidos. Se faltar implementação, marcar como `NEEDS-IMPLEMENTATION` ou `BLOCKED`, nunca como concluída.

#### Objetivo

Entregar e provar o resultado delimitado por: [Quality] Enforce no-internal-JSON and prove binary-format migration E2E

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: HBP/HBI/TOML, PR/commit, Release/publish, SHA/branch, accepted/emitted, benchmark/release, binary/TOML, build/package, codecs/config, cold/warm, corrupt/truncated/oversized/out-of-bounds, corruption/bounds, domain/storage, empty/minimal/large, github.com/wesleysimplicio/simplicio-dev-cli/issues/261, github.com/wesleysimplicio/simplicio-runtime/issues/3492, github.com/wesleysimplicio/simplicio-runtime/issues/3494, github.com/wesleysimplicio/simplicio-runtime/issues/3496, github.com/wesleysimplicio/simplicio-runtime/pull/3493, hit/miss, legacy/current/future-version, logs/receipts., missing/unobservable, producer/consumer, rejection/compatibility, released/installed, resultado/hashes., run/edit/task/gate, sistema/E2E, testes/coverage/benchmark, versões/SHAs, workload/hardware..

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

### #265 — [META-AUDIT] Revisar todas as issues — objetivos, fluxo de testes e critérios de aceite

- Estado/data: `open`; criada `2026-07-21T20:43:13Z`; atualizada `2026-07-21T20:43:13Z`
- Labels: `nenhuma`
- Classificação: `{"component": "runtime", "epic": "[META-AUDIT]", "priority": "unassigned", "risk": "medium"}`
- Rastreabilidade original: `{"evidence_mentioned": true, "pr_or_commit_mentioned": true, "tests_mentioned": true}`
- Decisão: **NEEDS-IMPLEMENTATION**

#### Contexto e problema

## Objetivo do projeto

Este repositório é o componente **simplicio-dev-cli** do ecossistema Simplicio. Papel auditado: **CLI de desenvolvimento**.

Fornecer CLI determinístico que consuma Mapper, PlanDAG, Prompt e Runtime com contratos estáveis e saída auditável.

## Escopo da auditoria

Revisar todas as issues, da mais antiga à mais recente, incluindo abertas, fechadas, duplicadas, obsoletas e bloqueadas. Nenhuma issue deve ser considerada concluída apenas por descrição textual: a solução precisa de implementação, teste e evidência.

## Passo a passo

1. Inventariar todas as issues e registrar número, estado, data, labels, referências e dependências.
2. Ordenar por criação e agrupar por épico, componente, risco e prioridade.
3. Para cada issue, reescrever o contexto, objetivo, fora de escopo, entradas, saídas e contrato afetado.
4. Relacionar a issue às branches, commits, PRs, arquivos, testes e outros projetos envolvidos.
5. Descrever o fluxo operacional completo, inclusive pré-condições, caminho feliz, falhas, retries, cancelamento e rollback.
6. Separar comportamento obrigatório, otimização opcional e hipótese ainda não comprovada.
7. Definir testes unitários, integração, sistema/E2E, regressão, concorrência, desempenho, segurança e reprodução aplicáveis.
8. Criar critérios de aceite mensuráveis, sem termos vagos como “funcionar” ou “melhorar”.
9. Registrar artefatos esperados: PR/commit, logs, receipts, métricas, hashes, relatório de falhas e decisão.
10. Validar dependências cruzadas com os contratos atuais da main; abrir issue vinculada quando houver quebra.
11. Manter issues de código, documentação, benchmark e investigação separadas.
12. Fechar apenas após revisão dos critérios, evidências anexadas e riscos residuais documentados.

## Fluxo de testes específico

Testar comandos felizes, argumentos inválidos, worktree, snapshot, PlanDAG, execução de ferramenta, retry, timeout, JSON/export e compatibilidade.

## Padrão obrigatório para cada issue revisada

Cada issue deverá conter:

1. **Contexto e problema**
2. **Objetivo**
3. **Fora de escopo**
4. **Entradas, saídas e contratos**
5. **Dependências e ordem**
6. **Passo a passo implementável**
7. **Fluxo de testes**
8. **Critérios de aceite verificáveis**
9. **Evidências obrigatórias**
10. **Riscos, rollback e decisão de encerramento**

## Critérios de aceite desta auditoria

- [ ] 100% das issues acessíveis foram inventariadas da mais antiga à mais recente.
- [ ] 100% das issues têm objetivo e fora de escopo explícitos.
- [ ] 100% têm passos numerados e dependências.
- [ ] 100% têm fluxo de testes aplicável ao componente.
- [ ] 100% têm critérios de aceite objetivos e verificáveis.
- [ ] 100% exigem PR/commit, logs e evidências para fechamento.
- [ ] Nenhuma issue declara economia, cobertura, desempenho ou integração sem medição.
- [ ] Falhas, timeouts, entradas inválidas e rollback são testados.
- [ ] Segredos, PII e dados privados não aparecem em exemplos ou logs.
- [ ] A revisão é reproduzível localmente ou em container e não depende de GitHub Actions pago.
- [ ] Quebras entre projetos estão ligadas por referências cruzadas.
- [ ] O README/ADR do projeto descreve sua responsabilidade e seus limites.

## Evidências obrigatórias

- relatório de inventário com contagens por estado;
- diff das issues reescritas;
- PRs/commits associados;
- logs de testes e falhas injetadas;
- receipts e métricas;
- matriz de dependências;
- decisão de encerramento ou bloqueio para cada item.

## Regra de encerramento

Só fechar esta auditoria quando todos os critérios estiverem marcados e o relatório final estiver publicado no repositório. Issues sem implementação permanecerão abertas como `SPEC`, `BLOCKED` ou `NEEDS-IMPLEMENTATION`, nunca como concluídas.

Épico do ecossistema: vincular ao projeto Simplicio central e às issues de integração correspondentes.

#### Objetivo

Entregar e provar o resultado delimitado por: [META-AUDIT] Revisar todas as issues — objetivos, fluxo de testes e critérios de aceite

#### Fora de escopo

Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.

#### Entradas, saídas e contratos

Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: JSON/export, PR/commit, PRs/commits, README/ADR, sistema/E2E.

#### Dependências e ordem

Referências explícitas: nenhuma. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.

#### Passo a passo implementável

1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.

#### Fluxo de testes

Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.

#### Critérios de aceite verificáveis

Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.

#### Evidências obrigatórias

PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.

#### Riscos, rollback e decisão de encerramento

Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.

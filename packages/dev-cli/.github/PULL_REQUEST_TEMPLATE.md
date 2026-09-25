# Pull Request

## Resumo

<!-- Descreva em 1-3 frases o que muda e por quê. Foco no "porquê", não no "como". -->

## Task relacionada

<!-- Link obrigatório para a task: #NNN, .specs/sprints/sprint-XX/NN-titulo.task.md, ou issue. -->

- Task: <!-- ex: #42 ou .specs/sprints/sprint-01/01-example.task.md -->
- Closes: <!-- Closes #42 -->

## Tipo de mudança

- [ ] feat — nova feature
- [ ] fix — bug fix
- [ ] refactor — refactor sem mudança comportamental
- [ ] perf — melhoria de performance
- [ ] docs — documentação
- [ ] test — só testes
- [ ] chore — build/CI/tooling
- [ ] breaking — quebra contrato (descrever em "Breaking changes")

## Definition of Done

- [ ] Acceptance criteria da task atendidos
- [ ] Lint passa local (`npm run lint`)
- [ ] Unit tests passam (`npm test`)
- [ ] Coverage >= 80%
- [ ] E2E Playwright passa (`npx playwright test`)
- [ ] Evidência E2E anexada (screenshots/trace) abaixo
- [ ] **Evidência aponta pro resultado observável final, não só status/exit-code**
      (conteúdo do arquivo gerado, output real do comando, diff aplicado —
      "exit 0" ou "status: ok" sozinhos não são evidência; ver `DOD.md`
      Camada 1, casos `mechanical_edit.py`/`mapper/graph.py` onde ambos
      retornaram sucesso produzindo resultado errado)
- [ ] Sem TODO/FIXME novos sem issue tracked
- [ ] Sem secrets/credenciais hardcoded
- [ ] Conventional commits seguidos no histórico
- [ ] Documentação atualizada (`README.md`, `.specs/`, JSDoc) quando aplicável
- [ ] Changelog atualizado se mudança user-facing
- [ ] Versão bumped conforme SemVer (`package.json`)
- [ ] ADR linkado se mudou `architecture/` (ADR-NNN)

## Pergunta de invariante (DoD Camada 2, `DOD.md`)

<!-- Responda diretamente; não deixe em branco se o PR toca parsing,
     transformação, ou qualquer lógica que decide algo sobre uma coleção. -->

Se duas (ou mais) funções deste diff processam a mesma coleção/dado (a mesma
lista de operações, o mesmo texto, a mesma árvore), elas concordam na MESMA
granularidade de decisão? (Exemplo real desta issue: `_operation_order()` e
`_validate_overlaps()` em `mechanical_edit.py` decidiam "está explicitamente
ordenado?" em granularidades diferentes — uma por plano inteiro, outra por
arquivo — e essa divergência corrompia arquivos silenciosamente.)

- Resposta: <!-- "N/A, PR não tem duas funções sobre a mesma coleção" ou a análise real -->

## Evidências / Screenshots

<!-- Anexe screenshots, gifs, traces do Playwright. Para cada cenário coberto, mostre estado final. -->
<!-- Exemplo: -->
<!-- ![happy-path](url) -->
<!-- ![error-state](url) -->

## Matriz AC → receipt

<!-- Cole a saída JSON de `EvidenceLedger.watch(...)`. Claims sem receipt permanecem
     UNVERIFIED; lacunas não podem virar claims. -->

```json
{"schema":"simplicio.dev-cli.evidence-ledger/v1","claims":{},"watcher":{"revalidated":true}}
```

## Cenários E2E cobertos

- [ ] Caminho feliz
- [ ] Casos de erro (input inválido, falha de rede)
- [ ] Estados de auth (anônimo, logado, sem permissão)
- [ ] Variantes de viewport (mobile, desktop)
- [ ] Edge cases relevantes

## Breaking changes

<!-- Se aplicável, descreva impacto e migração. Caso contrário, "N/A". -->

## Notas de deploy

<!-- Variáveis de ambiente novas, migrations, side effects de deploy. "N/A" se nenhum. -->

## Checklist do reviewer

- [ ] Código segue `.specs/architecture/PATTERNS.md`
- [ ] Testes cobrem o comportamento, não apenas linhas
- [ ] Sem refatoração extra fora do escopo
- [ ] Mensagens de commit seguem Conventional Commits

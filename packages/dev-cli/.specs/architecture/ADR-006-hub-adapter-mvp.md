# ADR-006: Adotar um adapter local `mechanical|semantic|blocked` + guarda anti-scheduler-duplicado, sem cliente de rede para o Loop Hub

---

## Status

`Aceito`

---

## Data

`2026-07-18`

---

## Autores

- `Claude Code (agente, sessão simplicio-loop)`

---

## Contexto

Issue #231 pede para transformar o dev-cli num worker idempotente e determinístico de um "Loop
Hub" externo: o Hub possui workflow/fairness, o Runtime possui processos/recursos, o Dev CLI só
compila/aplica/verifica uma mudança delimitada e retorna evidência. O plano completo inclui
`HubTaskAdapter`, propagação de IDs (ecosystem/run/task/attempt/lease/fence/trace/idempotency),
roteamento `mechanical|semantic|blocked`, encaminhamento de exec/test/build/worktree a um
"Process Supervisor/Runtime", conformance suite cross-repo, e rollout shadow/canário.

Nenhum desses sistemas — Loop Hub, Process Supervisor, Runtime — existe neste repositório nem
tem um contrato de rede publicado em `simplicio-mapper`/nenhum pacote consumido aqui. Issue #231
referencia parents em `simplicio-loop#555` e `simplicio-runtime#3327` — repositórios diferentes.

## Decisão

Implementar apenas a metade **local e segura** do plano, em `simplicio/hub_adapter.py`:

- `HubTaskIdentity`: os 8 campos de identidade propagada exigidos pelo AC 3, lidos de env vars
  (`SIMPLICIO_HUB_*`) na mesma convenção já usada pelo resto do pacote (`SIMPLICIO_MODEL` etc.).
  `is_complete()` checa o subconjunto mínimo (`run_id`/`task_id`/`lease`/`idempotency_key`) sem o
  qual um attempt Hub-driven não pode prosseguir com segurança.
- `route_task()`: `mechanical` quando o plano já é o shape determinístico que
  `mechanical_edit.execute_plan_json` consome (zero tokens de LLM, AC "Edição mecânica consome
  zero tokens"); `semantic` quando só há um goal para o caminho LLM (`pipeline.run_task`);
  `blocked` quando nenhum dos dois.
- `HubTaskAdapter.guard_identity()`/`.route()`: em `mode="on"`, recusam explicitamente (levantam
  `HubModeBlocked`) em vez de cair silenciosamente para comportamento standalone quando a
  identidade está incompleta ou a tarefa não é roteável — mesmo princípio do `map_view.py`/ADR-005
  (rejeitar incompatibilidade é obrigatório; a rejeição deve ser barulhenta, nunca silenciosa).
- `TaskBatch.drain(disallow_local_pool=...)`: novo parâmetro opcional (default `False`, sem
  mudança de comportamento existente) que recusa `max_workers > 1` quando um Hub já é dono da
  concorrência — atende ao AC 1 / plano passo 12 ("Remover/não ativar ThreadPoolExecutor local em
  modo Hub") sem acoplar `multi_task.py` ao vocabulário "Hub" (o parâmetro é genérico).
- `simplicio-py doctor` ganha uma seção "hub adapter" (humano e `--json`) mostrando modo,
  completude da identidade e se um scheduler local é permitido.

Fora de escopo (registrado para follow-up): cliente de rede para o Loop Hub de fato (claim/lease
sobre a rede, negociação de capacidade com um Runtime remoto), encaminhamento real de
exec/test/build a um Process Supervisor externo, e a conformance suite cross-repo do AC final —
todos dependem de um contrato de rede que ainda não existe publicamente.

---

## Consequências

### Positivas (+)

- Zero risco de regressão no caminho standalone: `disallow_local_pool` e o próprio adapter são
  aditivos, com defaults que preservam o comportamento atual byte-a-byte.
- O roteamento `mechanical|semantic` reaproveita infraestrutura já existente e testada
  (`mechanical_edit.execute_plan_json`, `pipeline.run_task`) em vez de duplicar lógica.
- `doctor` torna visível uma misconfiguração real (`mode=on` sem identidade propagada) sem
  precisar inspecionar variáveis de ambiente à mão.

### Negativas (-)

- Não entrega a integração real com um Loop Hub — é a metade client-side/local do contrato, como
  em ADR-005 para a issue #213.
- `disallow_local_pool` só cobre o `ThreadPoolExecutor` de `TaskBatch`; não impede outros pontos
  do código (ex.: subprocessos LLM concorrentes fora deste módulo) de abrir seus próprios
  recursos — o encaminhamento completo a um Process Supervisor central fica para follow-up.

### Neutras / observações

- A convenção de env vars (`SIMPLICIO_HUB_*`) espelha a já usada pelo restante do pacote — um
  cliente real de Hub que vier a existir pode continuar usando as mesmas variáveis para injetar a
  identidade no processo filho.

---

## Alternativas consideradas

### Alternativa A — Implementar o cliente de rede do Loop Hub também

- Resumo: adicionar um cliente HTTP/gRPC que realmente conversa com um Hub remoto para
  claim/lease/capacidade.
- Por que foi descartada: não há endpoint/contrato publicado para tal Hub neste ecossistema
  acessível a partir deste repositório; construir contra uma API inexistente fabricaria
  integração, não implementaria uma.

### Alternativa B — Acoplar `multi_task.py` diretamente ao conceito de "Hub"

- Resumo: fazer `TaskBatch.drain()` importar `hub_adapter` e decidir sozinho se deve recusar
  concorrência local.
- Por que foi descartada: viola "TaskBatch pode continuar como compilador/visão local de DAG e
  fallback standalone" (fronteira explícita da issue) — `multi_task.py` deve continuar agnóstico
  de Hub; por isso o parâmetro `disallow_local_pool` é um booleano genérico decidido pelo
  chamador (`hub_adapter.py`), não uma dependência direta de import.

---

## Critério de revisão

- Se um contrato de rede real do Loop Hub for publicado em algum pacote deste ecossistema,
  revisitar para que `HubTaskAdapter` passe a negociar claim/lease de fato pela rede, preservando
  os mesmos contratos locais (`HubTaskIdentity`, `route_task`).
- Se subprocessos LLM concorrentes fora de `TaskBatch` também precisarem respeitar
  `local_scheduler_allowed`, estender o guard para além de `drain()`.

---

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-dev-cli/issues/231
- Implementação: `simplicio/hub_adapter.py`, `simplicio/orchestrator/multi_task.py::TaskBatch.drain`, `simplicio/doctor.py`
- Testes: `tests/python/test_hub_adapter.py`, `tests/python/test_multi_task.py`
- Documentos relacionados: `[DESIGN](./DESIGN.md)`, `[PATTERNS](./PATTERNS.md)`, `[ADR-005](./ADR-005-canonical-map-worktree-overlay.md)`

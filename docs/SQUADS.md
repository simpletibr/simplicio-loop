# Squads v2: três regras (#1504, parte de #1502)

O `/simplicio-loop` divide o trabalho em squads (1 coordenador + até 4 workers). A v2 acrescenta três regras determinísticas, cada uma em um módulo pequeno e sem chamada a modelo. O `plan_squads` (#1502) chama só a regra 3 (`contracts_for`) e devolve os contratos no plano; as regras 1 e 2 (`route`, `plan_train`/`run_train`) são chamadas à parte pelo coordenador geral.

## 1. Modelo pela complexidade (`simplicio_loop/squad_routing.py`)

`route(task)` decide o papel do **primeiro** worker. A tarefa é `execution` (Haiku ou equivalente) só se **todas** as condições valem:

- um único módulo;
- não integra módulos já existentes;
- não mexe em arquivo compartilhado;
- não é de segurança.

Qualquer outro caso é `coordination` (Sonnet ou equivalente). Dois módulos já é `coordination`. `route(task).explain()` lista os motivos. A escada de `escalation.py` continua valendo depois do primeiro worker.

## 2. Merge em lote (`simplicio_loop/merge_train.py`)

- `plan_train(approved_prs, order, max_batch=4)` monta lotes na ordem de merge definida pelo coordenador geral.
- `run_train(batch, test_fn, merge_fn)` integra o lote numa branch temporária e testa **uma vez**. Se passa, faz merge de todos em ordem, sem novo smoke.
- Se falha, faz bisseção: acha o primeiro PR que deixa o lote vermelho em log2(n) testes, marca como culpado, testa o restante **em cima do prefixo bom** e repete; todo teste é cumulativo (bons até aqui + trecho candidato), então o conjunto final foi testado verde como um todo. Nada entra no main antes de isolar os culpados; depois entram só os PRs bons, em ordem.
- O relatório traz `merged`, `failed`, `bisect_steps` e `wall_ms`. Nunca há force-push.

## 3. Interfaces primeiro (`simplicio_loop/squad_contracts.py`)

`plan_squads` deriva as arestas das dependências declaradas entre issues (`depends_on`, ou "depends on / depende de / parte de #N" no corpo): uma issue que depende de uma issue de **outro** squad é a aresta (squad produtor, squad consumidor). Cada par distinto sai como um contrato em `SquadPlan.contracts` (e em `contracts` no JSON de `plan --json`: produtor, consumidor, `module_path`, `test_path`, `signature`, `function`; o corpo do teste não vai no JSON). Dependência dentro do mesmo squad, ou ausência de dependência, não gera contrato. O `schema` continua `simplicio.squad-plan/v1` (campo aditivo).

O plano só **descreve** os contratos; ele não escreve nada em disco. Ainda não há chamada automática que grave os stubs no repositório antes de os workers começarem: hoje o coordenador geral chama `write_contracts(repo, plan.contracts)` à mão. Para arestas com assinatura própria, chame `contracts_for(edges)` direto.

`write_contracts(repo, contracts)` cria, no repositório alvo, o stub (a função levanta `NotImplementedError("contract: <squad>")`) e o teste ao lado dele, em `dest` (padrão `.simplicio-loop/contracts/`, configurável em `contracts_for(edges, dest=...)`; nunca dentro do pacote distribuído). Arquivos existentes nunca são sobrescritos. O squad consumidor codifica contra a assinatura; o produtor troca o corpo; o teste de contrato fica `xfail` até a implementação existir.

## Uso no `/simplicio-loop`

1. O coordenador geral (planning) chama `plan_squads`: squads, ordem de merge e contratos das arestas de dependência.
2. `write_contracts(repo, plan.contracts)` grava os stubs (passo manual hoje); eles entram no main antes dos squads.
3. Para cada tarefa, `route` escolhe o papel do primeiro worker.
4. Os PRs aprovados pelos squads vão para `plan_train`; `run_train` faz o merge em lotes.

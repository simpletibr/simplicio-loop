# Squads v2: três regras (#1504, parte de #1502)

O `/simplicio-loop` divide o trabalho em squads (1 coordenador + até 4 workers). A v2 acrescenta três regras determinísticas, cada uma em um módulo pequeno e sem chamada a modelo. O `plan_squads` (#1502) chama os três.

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
- Se falha, faz bisseção: acha o primeiro PR que deixa o lote vermelho em log2(n) testes, marca como culpado, testa o restante uma vez e repete. Nada entra no main antes de isolar os culpados; depois entram só os PRs bons, em ordem.
- O relatório traz `merged`, `failed`, `bisect_steps` e `wall_ms`. Nunca há force-push.

## 3. Interfaces primeiro (`simplicio_loop/squad_contracts.py`)

Antes de os squads começarem, o coordenador geral chama `contracts_for(edges)`. Para cada dependência entre squads (produtor, consumidor) sai um contrato: caminho do módulo, assinatura da função e um teste de contrato.

`write_contracts(repo, contracts)` cria o stub em `simplicio_loop/squad_iface/` (a função levanta `NotImplementedError("contract: <squad>")`) e o teste em `tests/contracts/`. Arquivos existentes nunca são sobrescritos. O squad consumidor codifica contra a assinatura; o produtor troca o corpo; o teste de contrato fica `xfail` até a implementação existir. A ligação final é uma chamada.

## Uso no `/simplicio-loop`

1. O coordenador geral (planning) monta os squads, a ordem de merge e as arestas de dependência.
2. `contracts_for` + `write_contracts` geram as interfaces e entram no main antes dos squads.
3. Para cada tarefa, `route` escolhe o papel do primeiro worker.
4. Os PRs aprovados pelos squads vão para `plan_train`; `run_train` faz o merge em lotes.

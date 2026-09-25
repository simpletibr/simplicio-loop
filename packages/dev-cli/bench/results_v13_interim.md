# v13 INTERIM — bench em andamento (snapshot dos logs ao vivo)

Captura: **2026-05-30 22:10:41**

Parser dos logs `/tmp/exec_v13.log` e `/tmp/regex_v13.log`. Modelos com linha `-> baseline …` ESTÃO completos; modelos sem ela ainda rodam (mostro o que veio até agora).

## Sides

- `sem`  = baseline (raw goal)
- `com`  = cli alone (6-layer contract)
- `sp`   = cli + sp (composition)
- `ag`   = cli + ag (verify-loop max 3 attempts)
- `spag` = cli + sp + ag (composition + verify-loop)

## Headline — fechados (`-> baseline ...`)

### `llama-3.2-3b-instruct`

| metric | base | cli | cli+sp | cli+ag | cli+sp+ag | Δcli | Δsp | Δag | Δsp+ag |
|---|---|---|---|---|---|---|---|---|---|
| exec  (n=12)  | 8% | 8% | 8% | 8% | 8% | **+0** | **+0** | **+0** | **+0** |
| regex (t=52) | 32% | 69% | 67% | 88% | 76% | **+37** | **+35** | **+56** | **+44** |

### `gemma-3-4b-it`

| metric | base | cli | cli+sp | cli+ag | cli+sp+ag | Δcli | Δsp | Δag | Δsp+ag |
|---|---|---|---|---|---|---|---|---|---|
| exec  (n=12)  | 33% | 66% | 50% | 66% | 41% | **+33** | **+17** | **+33** | **+8** |
| regex (t=52) | 42% | 92% | 88% | 92% | 92% | **+50** | **+46** | **+50** | **+50** |

### `qwen-2.5-coder-32b-instruct`

| metric | base | cli | cli+sp | cli+ag | cli+sp+ag | Δcli | Δsp | Δag | Δsp+ag |
|---|---|---|---|---|---|---|---|---|---|
| exec  (n=12)  | 8% | 16% | 16% | 16% | 16% | **+8** | **+8** | **+8** | **+8** |
| regex (t=52) | 34% | 44% | 38% | 82% | 80% | **+10** | **+4** | **+48** | **+46** |


## Em andamento (parcial)

_(nenhum modelo em andamento — todos fecharam ou nem começaram)_

## Per-task exec (modelos fechados)

Format: `b/c/s/a/sa` (P=pass, .=fail)

| Task | llama-3.2-3b-instruct | gemma-3-4b-it | qwen-2.5-coder-32b-instruct |
|---|---|---|---|
| `password_strength` | ././././. | ./P/P/P/. | ././././. |
| `password_require_symbol` | ././././. | ././././. | ././././. |
| `env_get_int` | ././././. | ./P/P/P/P | ./P/P/P/P |
| `env_get_bool` | ././././. | ./P/./P/. | P/P/P/P/P |
| `admin_only_allowed_roles` | P/P/P/P/P | P/P/P/P/P | ././././. |
| `rate_limit_bucket_key` | ././././. | ./P/P/P/P | ././././. |
| `base_repository_build_where_sql` | ././././. | ././././. | ././././. |
| `router_has` | ././././. | P/P/P/P/P | ././././. |
| `bugfix_password_policy_lowercase` | ././././. | P/P/P/P/P | ././././. |
| `password_assess` | ././././. | P/P/./P/. | ././././. |
| `base_repository_build_update_sql` | ././././. | ././././. | ././././. |
| `router_extract_params` | ././././. | ././././. | ././././. |

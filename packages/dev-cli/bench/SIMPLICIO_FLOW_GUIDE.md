# Fluxo simplicio — da entrada do usuário ao retorno do LLM

Documento técnico cobrindo os **dois caminhos principais** do CLI atual:

- **`simplicio-py task`** — modo edit, herdado do produto v0.4 (existente)
- **`simplicio-py scratch`** — modo from-scratch, novo (issue #32)

Plus os auxiliares `doctor`, `skill new`, `index`, `detect`.

> **Status no HEAD atual:** este guia preserva o mapa de fluxo citado pela
> issue #33 e pelo roadmap `bench/LLM_REDUCTION_ROADMAP.md`. Alguns números de
> chamada LLM neste documento são estimativas de design; os gates atuais devem
> ser lidos nos relatórios versionados em `bench/results_*.md`.

Todos os caminhos compartilham a camada de **providers**, que decide
entre 6 rotas (Anthropic native, OpenAI-compat, OAuth shell-out, etc.)
e tem **duas pools separadas**: doer (`generate`) e planner (`planner_complete`).

---

## 1. Mapa geral

```
                ┌─────────────────────────┐
                │   simplicio <subcmd>    │
                │   (entry: cli.py:main)  │
                └────────────┬────────────┘
                             │
        ┌──────────┬─────────┼─────────┬──────────┬──────────┐
        ▼          ▼         ▼         ▼          ▼          ▼
     doctor    skill new   task    scratch    detect      init/index
        │          │         │         │          │          │
        │          │         │         │     (no LLM)    (no LLM)
        ▼          ▼         ▼         ▼
   ┌────────┐ ┌─────────┐ ┌──────┐ ┌─────────┐
   │ hard-  │ │ planner │ │ doer │ │ planner │
   │ ware + │ │ provider│ │ prov.│ │ provider│
   │ Ollama │ │         │ │      │ │   +     │
   │ probe  │ │         │ │      │ │  doer   │
   └────────┘ └────┬────┘ └──┬───┘ │provider │
                   │         │     └────┬────┘
                   │         │          │
                   └────┬────┴──────────┘
                        │
                        ▼
                ┌───────────────┐
                │  providers.py │
                │  route table  │
                └───────┬───────┘
                        │
        ┌───────────┬───┴────┬──────────────┬────────────┐
        ▼           ▼        ▼              ▼            ▼
    anthropic    OpenAI-   shell-out      Ollama        HF
    SDK (native) compat    (claude-cli,   (local)       router
    [no base_url]│         codex-cli)
                 ▼
           OpenRouter / DeepSeek / OpenAI / HF / etc.
```

---

## 2. Camada de **providers** (a peça central)

Arquivo: [`simplicio/providers.py`](../simplicio/providers.py)

Duas funções públicas:

| Função | Usada por | Env var de seleção | Default |
|---|---|---|---|
| `generate(prompt, feedback=None)` | doer (edita arquivos, gera código) | `SIMPLICIO_MODEL` + `SIMPLICIO_BASE_URL` + `SIMPLICIO_API_KEY` | nenhum (erro se não setado) |
| `planner_complete(prompt, temperature=0.1)` | planner (gera plano JSON) | `SIMPLICIO_PLANNER` | `deepseek-hf/deepseek-ai/DeepSeek-V3.1` (usa `HF_TOKEN`) |

**Por que duas pools separadas:**
plan e doer têm tradeoffs opostos (frontier vs barato; deterministic vs criativo).
Usuário troca o doer (Coder-Next) sem mexer no planner (DeepSeek-V3.1) e vice-versa.

### Tabela de rotas (válido para `planner_complete`)

```
prefix                  base URL                                env var      tipo
─────────────────────────────────────────────────────────────────────────────────────
deepseek-hf/<model>     https://router.huggingface.co/v1        HF_TOKEN     OpenAI-compat
deepseek/<model>        https://api.deepseek.com/v1             DEEPSEEK_API_KEY  OpenAI-compat
openai/<model>          https://api.openai.com/v1               OPENAI_API_KEY    OpenAI-compat
openrouter/<model>      https://openrouter.ai/api/v1            OPENROUTER_API_KEY OpenAI-compat
hf/<model>              https://router.huggingface.co/v1        HF_TOKEN          OpenAI-compat
anthropic/<model>       (none — SDK nativo)                     ANTHROPIC_API_KEY anthropic
claude-cli/<model>      (none — shell out)                      (nenhuma)         subprocess
codex-cli/<model>       (none — shell out)                      (nenhuma)         subprocess
<bare>                  fallback pro SIMPLICIO_MODEL config     compartilhado     OpenAI-compat
```

### Fluxo de `generate()` (doer) — passo a passo

```
caller passa (prompt, feedback)
            │
            ▼
┌──────────────────────────────────────┐
│  _cfg() lê SIMPLICIO_MODEL/_BASE_URL │
│  /_API_KEY do ambiente                │
└──────────────┬───────────────────────┘
               │
       ┌───────┼───────┐
       ▼       ▼       ▼
  starts with  bare    no base
  claude-cli/  model   → native Anthropic SDK
  codex-cli/    │
       │        │
       ▼        ▼
   _shell_out  OpenAI-compat client
   subprocess  (.chat.completions.create)
       │             │
       └──────┬──────┘
              ▼
       output (str) ────► retorna ao caller
```

### Fluxo de `planner_complete()` — diferente:

- temperature default = **0.1** (plan precisa ser determinístico, não criativo)
- max_tokens default = **8192** (plans longos)
- **NUNCA** anexa feedback automático (vs `generate` que tem retry interno)
- Caller (`scratch/planner.py`) faz o retry loop com diff de schema

---

## 3. Fluxo **`simplicio-py task "<goal>" --target <file>`** (modo edit)

Arquivos: [`simplicio/cli.py`](../simplicio/cli.py), [`simplicio/pipeline.py`](../simplicio/pipeline.py)

```
┌─────────────────────────────────────────────────────────────────┐
│ user: simplicio-py task "add foo() to PasswordPolicy"              │
│                  --target src/Core/PasswordPolicy.php            │
│                  --criteria "..." --constraints "..."            │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
   ┌───────────────────────────────────────┐
   │ cli.py:main()                          │
   │   argparse parse                       │
   │   maybe_autoinstall("task")            │
   │   → pipeline.run(root, stack, goal,    │
   │                  target, criteria,     │
   │                  constraints)          │
   └────────────────┬──────────────────────┘
                    ▼
   ┌──────────────────────────────────────────┐
   │ pipeline.py:run()                         │
   │ 1. build_prompt(...) → 6-layer contract   │
   │    (role + goal + target + criteria +     │
   │     constraints + output shape)           │
   └────────────────┬──────────────────────────┘
                    ▼
   ┌──────────────────────────────────────────────┐
   │ for t in 1..MAX_ATTEMPTS (=3):               │
   │   output = providers.generate(prompt,        │
   │                                feedback)     │
   │           ────────────────────┐              │
   │                               ▼              │
   │              ┌─────────────────────────────┐ │
   │              │  providers.py route         │ │
   │              │  (one of 4 paths above)     │ │
   │              │  POST → LLM provider        │ │
   │              │  retorna texto              │ │
   │              └─────────────────────────────┘ │
   │                               │              │
   │   ok, log = _apply_and_test(output)          │
   │     ├─ validate_generated_output(output)     │
   │     │  (regex: diff present? test present?)  │
   │     │                                        │
   │     └─ subprocess.run(                       │
   │          $SIMPLICIO_TEST_CMD, cwd=root)      │
   │                                              │
   │   if ok: return output  (DONE)               │
   │                                              │
   │   feedback = build_retry_feedback(           │
   │     attempt=t+1,                             │
   │     validation=validate(output),             │
   │     test_log=log)                            │
   │     ↑ classifies failure kind:               │
   │       syntax / assertion / dependency /      │
   │       timeout / runtime / unknown            │
   │     ↑ tail do test log (-1600 chars)         │
   │                                              │
   │   log_run(attempt, ok, failure_kind,         │
   │           tokens_estimated, target, stack)   │
   └────────────────┬─────────────────────────────┘
                    ▼
   ┌──────────────────────────────────────────────┐
   │ attempts exhausted → return None             │
   │ (pipeline did not converge)                  │
   └──────────────────────────────────────────────┘
```

**Onde os dados ficam em cada passo:**

| Passo | Dado | Onde |
|---|---|---|
| 1. CLI parse | args | memória do processo |
| 2. build_prompt | 6-layer text | memória |
| 3. providers.generate | output text | memória + log via `log_run` |
| 4. _apply_and_test | (ok, log) | `.simplicio/last_output.txt` no root |
| 5. retry feedback | feedback string | memória, anexada à próxima call |
| 6. log_run | jsonl event | `.simplicio/runs.jsonl` |

---

## 4. Fluxo **`simplicio-py scratch "<goal>"`** (modo from-scratch)

Arquivos: [`simplicio/scratch/cli.py`](../simplicio/scratch/cli.py), [`simplicio/scratch/planner.py`](../simplicio/scratch/planner.py), [`simplicio/scratch/executor.py`](../simplicio/scratch/executor.py), [`simplicio/scratch/_pipeline_adapter.py`](../simplicio/scratch/_pipeline_adapter.py)

Este é o fluxo **novo** — pipeline em **duas grandes etapas** (planner + executor),
onde executor delega cada task ao pipeline existente do modo task.

```
┌────────────────────────────────────────────────────────────────┐
│ user: simplicio-py scratch "CRUD API for condo units" [--stack X] │
└────────────────────────────┬───────────────────────────────────┘
                             ▼
   ┌──────────────────────────────────────────┐
   │ cli.py:main() → short-circuit            │
   │   sys.argv[1] == "scratch"               │
   │   → scratch.cli.main(sys.argv[2:])       │
   └────────────────┬─────────────────────────┘
                    ▼
   ╔══════════════════════════════════════════════════════╗
   ║ ETAPA 1 — STACK SELECTION                            ║
   ╠══════════════════════════════════════════════════════╣
   ║ scratch.cli.main():                                  ║
   ║   reg = StackRegistry()       ← lazy load            ║
   ║   stack = args.stack OR _infer_stack(reg, goal)      ║
   ║                                                       ║
   ║   _infer_stack: regex match no goal                  ║
   ║   ('nextjs' → ts-nextjs, 'fastapi' → py-fastapi, …)  ║
   ║                                                       ║
   ║   stack = reg.get(slug)       ← load Stack from disk:║
   ║     stack.json, README, practices.md, verify.json,   ║
   ║     tree/ (files copiados na Etapa 3)                ║
   ║                                                       ║
   ║   project_name = args.name OR slugify_project(goal)  ║
   ╚════════════════════════╤═════════════════════════════╝
                            ▼
   ╔══════════════════════════════════════════════════════╗
   ║ ETAPA 2 — PLAN GENERATION (LLM call #1: planner)     ║
   ╠══════════════════════════════════════════════════════╣
   ║ scratch.planner.generate_plan(stack, goal, name):    ║
   ║   prompt = PLAN_PROMPT_TEMPLATE.format(               ║
   ║     system=PLAN_SYSTEM_PREAMBLE,    ← regras estritas║
   ║     stack_slug, language, framework,                  ║
   ║     stack_readme,            ← truncado em 4000 ch   ║
   ║     stack_practices,         ← truncado em 6000 ch   ║
   ║     goal, project_name,                              ║
   ║     schema_example=EXAMPLE_PLAN)                     ║
   ║                                                       ║
   ║   for attempt in 1..PLANNER_MAX_RETRIES+1 (=4):      ║
   ║     raw = providers.planner_complete(prompt)         ║
   ║           ──────────────────┐                        ║
   ║                             ▼                        ║
   ║         ┌───────────────────────────────────┐        ║
   ║         │ planner_cfg() resolve SIMPLICIO_  │        ║
   ║         │ PLANNER (default deepseek-hf/...) │        ║
   ║         │                                    │        ║
   ║         │ POST → HF router / DeepSeek /     │        ║
   ║         │ OpenAI / Anthropic SDK            │        ║
   ║         │ temp=0.1 max_tokens=8192          │        ║
   ║         └───────────────────────────────────┘        ║
   ║                             │                        ║
   ║     parsed = _extract_json(raw)                      ║
   ║       (tolera fences, scan balanced braces)          ║
   ║                                                       ║
   ║     try: plan = validate_plan(parsed)  ── (success)  ║
   ║     except PlanValidationError as e:                 ║
   ║       feedback = e.errors            ← list[str]     ║
   ║       prompt += "[RETRY] ..." + diff                 ║
   ║                                                       ║
   ║   if exhausted: raise PlannerError                   ║
   ╚════════════════════════╤═════════════════════════════╝
                            ▼
              ┌─────────────────────────────┐
              │ Plan (typed dataclass):      │
              │   version: "1.0"             │
              │   stack: "py-fastapi"        │
              │   project_name: "condo-mgmt" │
              │   rationale: "..."           │
              │   files_to_create: [...]     │
              │   tasks: [Task, Task, ...]   │
              │   deps_to_install: [...]     │
              │   deps_dev: [...]            │
              │   test_command, lint_command │
              └──────────────┬──────────────┘
                             │
                if --plan-only: print + exit ◄── decision branch
                             │
                             ▼
   ╔══════════════════════════════════════════════════════╗
   ║ ETAPA 3 — EXECUTION                                  ║
   ╠══════════════════════════════════════════════════════╣
   ║ scratch.executor.execute_plan(plan, stack, parent):  ║
   ║                                                       ║
   ║   3.1 Create project_dir = parent / plan.project_name║
   ║       (raise FileExistsError if exists)              ║
   ║                                                       ║
   ║   3.2 stack.render_tree(project_dir, render_vars):   ║
   ║       copia simplicio/templates/stacks/<slug>/tree/  ║
   ║       substitui {project_name}, {goal} in-place      ║
   ║       → files_written list[Path]                     ║
   ║                                                       ║
   ║   3.3 Write .simplicio/plan.json                     ║
   ║       (audit trail completo do plan)                  ║
   ║                                                       ║
   ║   3.4 if stack.install_command and not skip_install: ║
   ║       _safe_run(install_cmd, cwd=project_dir,        ║
   ║                 timeout=600)                          ║
   ║       → report.install_ok, report.install_log        ║
   ║                                                       ║
   ║   3.5 ordered_tasks = _topo_sort(plan.tasks)         ║
   ║                                                       ║
   ║   3.6 for task in ordered_tasks:                     ║
   ║         _execute_one_task(task, project_dir, stack)  ║
   ║         ┌─────────────────────────────────────┐      ║
   ║         │ no SIMPLICIO_MODEL?                  │      ║
   ║         │   → return TaskResult(skipped=True)  │      ║
   ║         │   (stub mode — não chama LLM)        │      ║
   ║         │                                       │      ║
   ║         │ else:                                 │      ║
   ║         │   _pipeline_adapter.run_task():       │      ║
   ║         │     prev = os.environ.get(            │      ║
   ║         │       'SIMPLICIO_TEST_CMD')           │      ║
   ║         │     os.environ['SIMPLICIO_TEST_CMD']  │      ║
   ║         │       = task.verify    ← per-task!   │      ║
   ║         │     try:                              │      ║
   ║         │       pipeline.run(root=project_dir,  │      ║
   ║         │         stack=...,                    │      ║
   ║         │         goal=task.goal,               │      ║
   ║         │         target=task.target,           │      ║
   ║         │         criteria=task.criteria,       │      ║
   ║         │         constraints=task.constraints) │      ║
   ║         │       (mesma máquina do modo task!)   │      ║
   ║         │     finally:                          │      ║
   ║         │       restore SIMPLICIO_TEST_CMD      │      ║
   ║         └─────────────────────────────────────┘      ║
   ║                                                       ║
   ║   3.7 Write .simplicio/scratch_report.json           ║
   ║       (per-task result, passed/skipped, duration)    ║
   ╚══════════════════════════════════════════════════════╝
```

**Observação central:** uma vez gerado o Plan, **a Etapa 3 reutiliza o
pipeline do modo task** — cada task vira uma chamada
`pipeline.run(...)` com seu próprio verify-loop de 3 attempts. Isso
significa que o **mesmo retry-feedback machinery** que faz `simplicio
task` funcionar bem em edit-mode atua dentro do scratch também.

**LLM calls totais num scratch típico:**

- 1 call para o **planner** (frontier model, ~$0.05)
- N calls para o **doer** (uma por task; cada task pode disparar até 3
  attempts no verify-loop)
- Worst case: `1 + N × 3` calls

Para N=12 tasks: 1 + 36 = 37 calls. Custo dominado pelo doer (Coder-Next ~$0/call no HF gratis ou centavos via OR).

---

## 5. Fluxo `simplicio-py doctor` (auxiliar — sem LLM)

Arquivos: [`simplicio/doctor.py`](../simplicio/doctor.py), [`simplicio/hardware.py`](../simplicio/hardware.py), [`simplicio/local_models.py`](../simplicio/local_models.py)

```
┌──────────────────────────────────────────────────┐
│ user: simplicio-py doctor [--install] [--json]      │
└────────────────────────┬─────────────────────────┘
                         ▼
   ┌─────────────────────────────────────────┐
   │ hardware.detect()                        │
   │   detect_ram():                          │
   │     Linux  → /proc/meminfo               │
   │     macOS  → sysctl hw.memsize           │
   │   detect_gpu():                          │
   │     try nvidia-smi (any platform)        │
   │     try apple silicon                    │
   │       (arm64 + sysctl machdep brand)     │
   │     else 0                               │
   │   pick_tier(ram, vram, apple_si) →       │
   │     cpu-tiny | cpu-small | gpu-mid |     │
   │     gpu-large | gpu-xlarge               │
   └──────────────────┬──────────────────────┘
                      ▼
   ┌─────────────────────────────────────────┐
   │ local_models.evaluate(profile)           │
   │   spec = RECOMMENDATIONS[profile.tier]   │
   │   usable_gb = ram if apple else          │
   │               max(vram, ram)             │
   │   needed_gb = spec.size + 4 GB margin    │
   │   can_run = usable_gb >= needed_gb       │
   │   can_pull = ollama_present and can_run  │
   │   installed = ollama_list_installed has  │
   │               spec.ollama_id             │
   └──────────────────┬──────────────────────┘
                      ▼
   ┌─────────────────────────────────────────┐
   │ ensure_recommended(profile,              │
   │                    auto_pull=args.install)│
   │   if installed: return                   │
   │   if not can_pull: return (reason)       │
   │   if auto_pull or SIMPLICIO_AUTO_PULL=1: │
   │     pull(spec.ollama_id)                 │
   │     → subprocess `ollama pull <id>`      │
   │   else:                                  │
   │     return with reason="opt in via       │
   │             --install or env var"        │
   └──────────────────┬──────────────────────┘
                      ▼
              renderiza human / json
```

**Garantia hard-coded:** mesmo com `--install`, se `can_run=False` (modelo
não cabe no hardware), `ensure_recommended` **NÃO chama `ollama pull`**.
Teste em `tests/python/test_local_models.py::test_ensure_recommended_refuses_pull_when_undersized`.

---

## 6. Fluxo `simplicio skill new` (auxiliar — usa planner)

Arquivos: [`simplicio/scratch/skill_opt.py`](../simplicio/scratch/skill_opt.py), [`.skills/skill-opt/SKILL.md`](../.skills/skill-opt/SKILL.md)

```
┌────────────────────────────────────────────────┐
│ user: simplicio skill new "<description>"      │
└────────────────────┬───────────────────────────┘
                     ▼
   ┌────────────────────────────────────────┐
   │ scratch.skill_opt.generate_skill_doc:  │
   │   list existing skills (_list_existing)│
   │   build prompt (SKILL_GEN_TEMPLATE)    │
   │   text = providers.planner_complete()  │
   │   ────────────────────────────────┐    │
   │                                   ▼    │
   │     planner provider route (same as    │
   │     scratch.planner — DeepSeek default)│
   │                                   │    │
   │   slug = _extract_slug(text)      │    │
   │   if not slug: raise               │    │
   │   if not _has_review_gate(text):  │    │
   │     raise (review_required missing)│   │
   │   if slug in existing: raise      │    │
   │   return (slug, text)              │    │
   └────────────────┬───────────────────────┘
                    ▼
   ┌────────────────────────────────────────┐
   │ install_skill(slug, text):              │
   │   mkdir .skills/<slug>/                 │
   │   write SKILL.md                        │
   │   print reminder pra revisar            │
   └────────────────────────────────────────┘
```

**Gate inegociável:** `_has_review_gate(text)` rejeita qualquer SKILL.md
gerado sem `review_required: true` no frontmatter. Esse é o anti-padrão
nº 5 do RFC: "SkillOpt sem review gate".

---

## 7. Os "dados em trânsito" — diagrama de ciclo completo no modo scratch

Resumo visual do que chega e o que sai em cada chamada LLM:

```
   user input:
   ┌──────────────────────────────────────────────┐
   │ "CRUD API for condo units" + [--stack X]     │
   └────────┬─────────────────────────────────────┘
            │ ⓘ goal + optional stack
            ▼
   ┌──────────────────────────────────────────────┐
   │ stack chosen + project_name resolved          │
   │ → (stack_slug, language, framework,           │
   │    readme[:4k], practices[:6k], goal, name)   │
   └────────┬─────────────────────────────────────┘
            │
            │ →→→ LLM CALL #1 (planner) →→→
            │     POST /v1/chat/completions
            │     model: DeepSeek-V3.1 (default)
            │     temp: 0.1   max_tokens: 8192
            │     ~5-7 KB de prompt    ←
            │     ~1-3 KB de plan JSON ←
            │
            ▼
   ┌──────────────────────────────────────────────┐
   │ Plan (validated) :                            │
   │   { tasks: [T01, T02, ..., T12], ...}         │
   └────────┬─────────────────────────────────────┘
            │
            │ scaffold tree → files written
            │ install command → install_log
            │
            ▼
   ┌──────────────────────────────────────────────┐
   │ for each task T_i in topological order:       │
   │                                                │
   │   →→→ LLM CALL #N (doer attempt 1) →→→        │
   │       POST (depending on SIMPLICIO_MODEL)     │
   │       6-layer prompt (~1-2 KB)                │
   │       ~500-2000 tokens output                  │
   │                                                │
   │   run task.verify command:                    │
   │     - if pass → DONE                           │
   │     - if fail → retry up to 2x with feedback   │
   │                                                │
   │   (worst case 3 LLM calls per task)           │
   └──────────────────────────────────────────────┘
            │
            ▼
   ┌──────────────────────────────────────────────┐
   │ .simplicio/scratch_report.json                 │
   │   project_dir + N task results                 │
   │   passed/total, durations, log tails           │
   └──────────────────────────────────────────────┘
```

---

## 8. Onde está cada coisa (cheat sheet)

| Pergunta | Arquivo |
|---|---|
| Como o CLI roteia? | `simplicio/cli.py` |
| Onde está o verify-loop do modo task? | `simplicio/pipeline.py` |
| Como construir o 6-layer prompt? | `simplicio/prompt.py` |
| Como o planner é resolvido? | `simplicio/providers.py:planner_cfg` |
| Como o doer é resolvido? | `simplicio/providers.py:_cfg` |
| Como detectar hardware? | `simplicio/hardware.py:detect` |
| Como decidir tier → modelo? | `simplicio/hardware.py:pick_tier` |
| Como instalar modelo local? | `simplicio/local_models.py:ensure_recommended` |
| Onde estão os 30 templates? | `simplicio/templates/stacks/<slug>/` |
| Como o registry carrega? | `simplicio/scratch/stack_registry.py:StackRegistry` |
| Como validar o plan? | `simplicio/scratch/plan_schema.py:validate_plan` |
| Como gerar o plan? | `simplicio/scratch/planner.py:generate_plan` |
| Como executar o plan? | `simplicio/scratch/executor.py:execute_plan` |
| Como bridgear plan task → pipeline.run? | `simplicio/scratch/_pipeline_adapter.py:run_task` |
| Como gerar nova skill? | `simplicio/scratch/skill_opt.py:generate_skill_doc` |
| Como o detect classifica prompt? | `simplicio/detect.py` |

---

## 9. Logs e auditoria

Cada execução deixa rastro em **3 lugares**:

| Arquivo | Conteúdo | Quando escrito |
|---|---|---|
| `<root>/.simplicio/runs.jsonl` | per-attempt: mode, attempt, ok, failure_class, tokens_estimated, target, stack | `pipeline.log_run` (modo task) |
| `<root>/.simplicio/last_output.txt` | output cru da última LLM call | `pipeline._apply_and_test` (modo task) |
| `<project_dir>/.simplicio/plan.json` | plan validado completo, audit trail do scratch | `executor.execute_plan` (modo scratch) |
| `<project_dir>/.simplicio/scratch_report.json` | per-task result com duration, log_tail, skipped reason | fim do `executor.execute_plan` |

---

## 10. Pontos de personalização

Resumo das env vars que afetam o fluxo:

```bash
# Doer
SIMPLICIO_MODEL=Qwen/Qwen3-Coder-Next     # qual modelo o doer usa
SIMPLICIO_BASE_URL=https://router.huggingface.co/v1
SIMPLICIO_API_KEY=hf_...

# Planner (independente do doer)
SIMPLICIO_PLANNER=deepseek-hf/deepseek-ai/DeepSeek-V3.1   # default
HF_TOKEN=hf_...                                            # default planner deps

# Pipeline (modo task)
SIMPLICIO_TEST_CMD="pnpm test"     # comando de verify
SIMPLICIO_PROVIDER=claude          # marcador de telemetria

# Scratch
SIMPLICIO_STACKS_DIR=/custom/path/to/stacks      # override do registry
SIMPLICIO_PLANNER_MAX_RETRIES=3                  # quantas vezes re-prompt em schema fail

# Doctor / local models
SIMPLICIO_AUTO_PULL=1              # opt-in a baixar modelo via ollama
SIMPLICIO_SKILLS_DIR=/custom/.skills    # override .skills/ root

# Cache (issue #34)
SIMPLICIO_CACHE=0                  # desliga totalmente o cache
SIMPLICIO_BUST_CACHE=1             # força miss em todas as keys (caching novas)
SIMPLICIO_CACHE_DIR=/custom/path   # override de ~/.simplicio/cache
SIMPLICIO_CACHE_TTL_DAYS=30        # tempo de vida de entries no disco
SIMPLICIO_CACHE_MAX_MB=500         # cap de tamanho; LRU evicta ao passar

# Hook control
SIMPLICIO_HOOK_GUARD=1             # interno: previne recursão em shell-out
SIMPLICIO_SKIP_AUTO_INIT=1         # desliga auto-bootstrap em ~/.claude
```

### Cache layer (`simplicio-py cache`, issue #34)

O cache vive em `simplicio/_cache.py` e é content-addressed por SHA256 de
`(provider_id, model, prompt, kwargs)`. Hookado em `providers.generate` e
`providers.planner_complete` — toda chamada LLM consulta cache antes de
pagar a chamada ao provider e popula após sucesso.

**Garantia de short-circuit:** cache hit retorna **antes** da resolução de
credenciais. Isso significa que num dev loop você pode ter `SIMPLICIO_API_KEY`
unset e ainda assim re-rodar scratches do cache.

```bash
simplicio-py cache stats         # quantas entries, MB, idade da mais antiga
simplicio-py cache stats --json  # machine-readable
simplicio-py cache clear --force # remove tudo (requer --force explícito)
```

**Invariantes testados** em `tests/python/test_cache.py` (12 cenários,
incluindo: hit, miss, TTL expirado, mudança de `template_version`, bust
env var, disabled, LRU eviction, escrita concorrente race-safe, arquivo
cache malformado tratado como miss).

---

Histórico:
- 2026-05-29 — documento inicial cobrindo task + scratch + doctor + skill new
  pós-implementação de issue #32 (commits `f26b139`, `2de45f5`, `b020cb1`).

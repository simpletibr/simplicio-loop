# Roadmap — reduzir dependência de LLM no fluxo simplicio

> **Premissa central:** cada chamada LLM é (a) latência, (b) custo, (c) ponto
> de variabilidade não-determinística. Onde a tarefa é **mecânica**, LLM agrega
> custo sem agregar inteligência. Onde a tarefa exige **decisão arquitetural**
> ou **síntese de texto livre**, LLM é insubstituível. Esse roadmap separa as
> duas categorias e elimina LLM da primeira.

> **Critério de avaliação:** uma redução é válida quando (1) substitui LLM
> num passo onde a saída é estruturalmente previsível dado o input, (2) não
> regride pass-rate em nenhum bench, (3) reduz custo de doer/planner em ≥30%
> no cenário típico (scratch + 12 tasks).

> **Status no HEAD atual:** este documento preserva o roadmap original citado
> pela issue #33. Evidência executável atualizada vive em
> `bench/results_scratch_codegen.*`, `bench/results_static_fixers.*` e
> `bench/results_scratch_release_gate.*`.

---

## 1. Mapa atual — onde o LLM é chamado e por quê

Por execução de `simplicio-py scratch "<goal>"` típica (12 tasks):

| Etapa | LLM calls | % do custo | Pode virar determinístico? |
|---|---|---|---|
| Stack inference | 0 (rule-based) | 0% | já é (basta expandir) |
| **Plan generation** | **1 planner call** | ~15% | **parcial — recipes** |
| Scaffold tree | 0 (cp) | 0% | já é |
| Install deps | 0 (subprocess) | 0% | já é |
| **Task generation** | **1-3 doer calls × N tasks** | ~80% | **parcial — codegen + AST** |
| **Test/lint feedback** | reusa as 3 doer calls acima | (incluso) | **parcial — static fixers** |
| **Skill generation** (eventual) | 1 planner call | <1% | **parcial — templates** |
| Audit log | 0 (jsonl write) | 0% | já é |

**Soma típica:** 1 planner + ~30 doer = 31 calls. Dessas, **~60% caem em
padrões repetitivos** ("crie model com campos X,Y", "endpoint REST CRUD
para resource Z", "teste happy-path para função W") que **não exigem
síntese livre** — exigem template + slot fill.

---

## 2. Estratégia em 4 alavancas

### Alavanca A — **Plan recipes** (plan generation sem LLM em ~60% dos casos)

**Problema:** hoje o planner LLM recebe `goal + stack readme + practices`
e gera 12 tasks. Para goals comuns ("CRUD API para X", "auth com JWT",
"painel admin para Y"), o planner sempre produz a mesma estrutura — só
muda o nome do entity.

**Solução:** registry de **recipes** = plans declarativos + slot fills.

```yaml
# simplicio/templates/recipes/py-fastapi/crud-resource.yaml
name: crud-resource
matches:
  - "CRUD (.+) for managing (?P<entity>\\w+)"
  - "REST API for (?P<entity>\\w+)"
applies_to: [py-fastapi]
slots:
  entity: required  # extracted from goal regex
  fields: optional  # asked interactively or parsed from goal
tasks:
  - id: T01-db-model
    target: "src/db/{entity_lower}.py"
    goal: "Define {entity} ORM model with declared fields"
    criteria: "- {entity} class\n- 4+ columns typed"
    constraints: "- SQLAlchemy 2.0 declarative"
    verify: "pytest tests/db/test_{entity_lower}.py"
  - id: T02-schema
    target: "src/api/schemas/{entity_lower}.py"
    goal: "Pydantic schemas: {Entity}Read, {Entity}Create, {Entity}Update"
    # ...
```

**Fluxo:**

```
goal received
  ↓
recipe_registry.match(goal, stack)
  ├─ match → instantiate Plan from yaml + slot fill (0 LLM calls)
  └─ no match → fall back to LLM planner (atual)
```

**Quando aplica:** o registry tem recipes para CRUD, auth, admin, file
upload, websocket, background worker, scheduled job, OAuth integration —
~10 recipes cobrem ~60% dos goals comuns em web.

**Ganho:** **−1 planner call em 60% dos scratches**. Custo $0.05/scratch
× 60% = economia ~$0.03/scratch + 3-8s de latência de planner. Para
1.000 scratches/mês: ~$30 + ~2h.

**Esforço:** 1 semana inicial (engine + 3 recipes pilot) + 2-3 dias por
recipe novo.

---

### Alavanca B — **Mechanical task executor** (codegen sem LLM para tasks padrão)

**Problema:** hoje cada task vira chamada doer LLM. Mas muitas tasks são
**operações mecânicas** sobre AST: "adicionar coluna `email` na tabela
`User`", "criar endpoint `GET /users/{id}`", "gerar teste happy-path
para função `parse_csv`".

**Solução:** classificar cada task em **automatic** vs **freeform**.
Automatic = roda codegen determinístico (libcst para Python, ts-morph
para TypeScript, php-parser, syn para Rust). Freeform = roda LLM como
hoje.

```python
# simplicio/scratch/codegen/__init__.py
class TaskExecutor(ABC):
    def can_handle(self, task: Task, stack: Stack) -> bool: ...
    def execute(self, task: Task, project_dir: Path) -> CodegenResult: ...

# Registry pickea o primeiro can_handle=True; fallback LLM
EXECUTORS = [
    PythonAddOrmFieldExecutor(),    # libcst: adiciona coluna SQLAlchemy
    PythonAddFastApiRouteExecutor(),# libcst: adiciona @router.get + handler
    PythonAddPydanticSchemaExecutor(),
    PythonAddPytestTestExecutor(),
    TypeScriptAddNextRouteExecutor(),
    # ...
    LLMFallbackExecutor(),  # último — usa simplicio.pipeline.run
]
```

**Heurísticas pra classificar:**

- Task tem `target` em `src/db/<model>.py` + goal contém "model"/"column"/"field"
  → `PythonAddOrmFieldExecutor`
- Task tem `target` em `src/api/<resource>.py` + goal contém "endpoint"/"route"
  → `PythonAddFastApiRouteExecutor`
- Task tem `target` em `tests/` + goal contém "test"
  → `PythonAddPytestTestExecutor`
- Caso contrário: LLM fallback

**Quando aplica:** ~50% das tasks num scratch típico de CRUD app são
mecânicas. Para "auth com JWT": ~70%. Para "admin panel": ~80%.

**Ganho:** **−1 a 3 doer calls por task mecânica**. Considerando 6 tasks
mecânicas × 2 calls médias = **−12 doer calls em 18 totais**. Custo do
doer cai 2/3, latência idem.

Adicional: **codegen é mais correto** que LLM em operações estruturais
— não tem risco de "esqueceu de fechar parêntese" ou "deletou método
adjacente" (os modos de falha que vimos em Coder 7B).

**Esforço:** alto. 1-2 semanas por executor; ~5-7 executors pilot pra
cobrir os padrões dominantes em py-fastapi/ts-nextjs.

---

### Alavanca C — **Static fixers no verify-loop** (zero LLM em retries de baixo nível)

**Problema:** quando uma task falha no verify, o pipeline atual sempre
re-prompta o LLM. Mas muitas falhas têm **fix mecânico óbvio**:

- `ModuleNotFoundError: no module named 'fastapi'` → `pip install fastapi`
  (e atualizar pyproject.toml)
- `SyntaxError: unexpected indent` → `ruff format <file>`
- `assert 200 == 201` (apenas status code) → testar com a string literal
  no source e checar se há `status_code=201` ausente
- `ImportError: cannot import name 'foo' from 'bar'` → grep no projeto
  por `def foo`, se existe em outro módulo, ajustar import

**Solução:** intercept o `classify_failure` antes do retry-feedback ir
pro LLM. Se o erro casa um pattern conhecido, **roda o fix mecânico** e
re-tenta verify **sem** chamar LLM.

```python
# simplicio/pipeline_fixers.py
class StaticFixer(ABC):
    pattern: re.Pattern
    def fix(self, log: str, project_dir: Path) -> bool: ...

class MissingPipPackageFixer(StaticFixer):
    pattern = re.compile(r"ModuleNotFoundError: No module named '(\w+)'")
    def fix(self, log, project_dir):
        m = self.pattern.search(log)
        if not m: return False
        pkg = m.group(1)
        # check pyproject.toml — if not declared, add + reinstall
        ...
        return True

# em pipeline.run, antes do build_retry_feedback:
for fixer in STATIC_FIXERS:
    if fixer.try_fix(log, project_dir):
        ok, log = _apply_and_test(output, project_dir)  # re-run verify
        if ok: return output
```

**Quando aplica:** ~30% dos retries em scratches reais (heurística — vai
medir). Cada static fix poupa 1 LLM call.

**Ganho:** **−30% dos retries**, ou seja −10% de doer calls totais.
Latência adicional do fix é <500ms (subprocess install) vs ~10s de LLM
retry.

**Esforço:** baixo. 3-5 fixers cobre 80% das falhas de install/import/lint.
2-3 dias de implementação por fixer (com testes).

---

### Alavanca D — **Plan + task caching** (zero LLM em runs repetidos)

**Problema:** desenvolver o simplicio iterativamente exige rodar o
mesmo scratch dezenas de vezes ajustando templates/practices. Cada
run = 1 planner + N doer calls. Caching mata isso.

**Solução:** caching content-addressed em dois níveis.

```
~/.simplicio-loop/cache/
├── plans/
│   ├── <sha256(planner_prompt)>.json
│   └── ...
└── completions/
    ├── <sha256(prompt + model)>.txt
    └── ...
```

- `planner_complete()` consulta cache antes de chamar; insere depois
- `generate()` (doer) idem
- Cache invalida quando: stack template muda (hash inclui template version),
  practices.md muda (hash idem), env var `SIMPLICIO_BUST_CACHE=1`

**Quando aplica:** desenvolvimento + CI (mesmo scratch num build de
integração). Em produção (cada usuário com goal único) cache raramente
hita.

**Ganho:** em dev/CI, segundo run + onwards = 0 LLM calls. Em produção:
~5% hit rate (mesmo goal de usuários diferentes).

**Esforço:** baixo. 2-3 dias incluindo testes de invalidação.

---

## 3. Roadmap consolidado

| Alavanca | Onde corta | Cut esperado em LLM calls | Esforço | Order |
|---|---|---|---|---|
| **D — Caching** | dev + CI repeats | −100% em hits, ~5% prod | baixo | **1ª** (low risk, immediate dev win) |
| **C — Static fixers** | retries triviais | −10% doer totais | baixo | **2ª** |
| **A — Plan recipes** | planner em goals comuns | −60% planner calls | médio | **3ª** |
| **B — Mechanical executors** | tasks mecânicas | −60% doer totais | alto | **4ª** |

### Total esperado se tudo entrega

Para scratch típico de 12 tasks com goal "CRUD API for X":

```
Hoje:    1 planner + 18 doer = 19 LLM calls         (~$0.05 + ~$0.15)
+ A:     0 planner + 18 doer = 18 LLM calls         (~$0.00 + ~$0.15)
+ A+C:   0 planner + 16 doer = 16 LLM calls         (~$0.00 + ~$0.13)
+ A+C+B: 0 planner +  6 doer =  6 LLM calls         (~$0.00 + ~$0.05)
```

**Redução total: −68% de LLM calls em scratch comum.** Em scratch
fora dos padrões (sem recipe match, sem task mecânica detectada), cai
pra 0% de redução e o fluxo é idêntico ao atual — degradação graceful.

---

## 4. Quando NÃO substituir LLM

Anti-padrões que precisamos cravar:

- **Goals criativos** — "build me an app that does X interesting" não
  tem recipe; LLM é necessário. Não forçar match parcial.
- **Refactors largos** — codegen mecânico não cobre "reorganize the
  module" ou "extract this pattern into a base class". LLM continua.
- **Bugfix sem reproduzir** — task de "fix the bug reported by user"
  exige raciocínio sobre comportamento. Static fixers só pegam padrões
  óbvios; o resto vai pra LLM.
- **Geração de prosa** (READMEs, docstrings, CHANGELOGs) — texto livre
  é trabalho de LLM por natureza.

A regra prática: **se a saída esperada tem entropia alta e estrutura
livre, é LLM. Se a saída tem entropia baixa e estrutura conhecida, é
template/codegen/static-fix.**

---

## 5. Métricas que decidem se cada fase entrega

Cada alavanca shippa quando, em 50 scratches reais de bench:

- **A (recipes):** ≥40% dos scratches batem recipe match. Pass-rate
  PHPUnit das tasks no caminho recipe = pass-rate das LLM (igualar
  pelo menos; idealmente +5pp porque template é mais consistente).
- **B (mechanical executors):** ≥30% das tasks executadas por executor.
  Latência média da task cai ≥50%. Pass-rate igual ou maior que LLM
  (esperado: codegen estrutural é mais correto que LLM em operações
  AST puras).
- **C (static fixers):** ≥80% das falhas de install/import resolvidas
  por fixer antes do LLM retry. Total retry calls cai ≥30%.
- **D (caching):** taxa de cache-hit em dev ≥80% após primeira execução
  do scratch. Cache invalida corretamente em mudança de template.

Cada métrica é instrumento pra rejeitar release prematuro — fase só
sai quando os números batem em scratch reais, não em smoke tests
sintéticos.

---

## 6. Anti-padrões de over-engineering

- **Recipes com slot fill complexo demais.** Se o template precisar de
  10 perguntas pro usuário pra preencher slots, virou wizard, perdeu o
  ponto. Limite: ≤3 slots por recipe; resto LLM.
- **AST executors para tudo.** Manter executors só pros padrões TOP-5
  por stack. Adicionar novo só com evidência de bench (task X repete em
  ≥30% dos scratches).
- **Cache sem TTL nem invalidação.** Cache stale = bugs piores que
  custo do LLM. Stack template version no hash + bust env var é o
  mínimo.
- **Cobrir 100% sem LLM.** Stop reasonable. Casos exóticos são
  exatamente o que LLM resolve bem. Mira em 60-70% de redução em
  cenário comum; o resto é qualidade.

---

## 7. Por onde começar (concreto)

Sequência de PRs sugerida no `simplicio-dev-cli`:

1. **`feat(cache): content-addressed completion cache`** (Alavanca D)
   - Novo módulo `simplicio/_cache.py` com SHA256-keyed JSON store
   - Hook em `providers.generate` e `providers.planner_complete`
   - Env var `SIMPLICIO_BUST_CACHE=1`, `SIMPLICIO_CACHE_DIR=~/.simplicio-loop/cache`
   - 2 dias

2. **`feat(fixers): static fixers for install/import errors`** (C)
   - `simplicio/pipeline_fixers.py` com 3 fixers pilot
   - Hook em `pipeline.run` antes do retry feedback
   - 3 dias

3. **`feat(recipes): plan recipe registry + 3 pilot`** (A)
   - `simplicio/scratch/recipes.py` + `templates/recipes/<stack>/*.yaml`
   - Match-before-LLM em `scratch.planner.generate_plan`
   - Recipes: `crud-resource` (py-fastapi + ts-nextjs), `auth-jwt`, `admin-crud`
   - 1 semana

4. **`feat(executors): mechanical executor framework + 3 pilot`** (B)
   - `simplicio/scratch/codegen/__init__.py` ABC + registry
   - `PythonAddOrmFieldExecutor` (libcst), `PythonAddFastApiRouteExecutor`,
     `PythonAddPytestTestExecutor`
   - Hook em `executor._execute_one_task` antes do LLM fallback
   - 1-2 semanas

Total: ~4 semanas pra entregar redução de ~50-70% em scratches comuns.

---

## Histórico

- 2026-05-29 — roadmap criado em resposta à pergunta "tem como fazer o
  fluxo depender menos das LLMs?". Base na análise do
  `bench/SIMPLICIO_FLOW_GUIDE.md` (commit `a4ef463`) e nos resultados do
  bench Qwen3 Coder MoE (`bench/results_full_qwen3.{md,pdf}`).

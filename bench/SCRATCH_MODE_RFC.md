# From-scratch mode + Planner provider + SkillOpt — design proposal

> **Status:** rascunho de arquitetura. Base nas direções dadas:
> (1) modo "do zero" com templates de boas práticas por stack, (2) planner
> remoto via DeepSeek-V4-Pro em vez de LLM local, (3) skill `skill-opt` pra
> criar skill nova sob demanda.
> **Repo:** `wesleysimplicio/simplicio-dev-cli`
> **Dependências relevantes:** `simplicio/init.py`, `simplicio/providers.py`,
> `simplicio/pipeline.py`, `.skills/`, `.specs/sprints/`.

---

## 1. Problema — o gap entre task e do-zero

O `simplicio-py task` de hoje assume:

- Projeto **existe** (repo iniciado, dependências instaladas)
- Arquivo-alvo **existe** (a tarefa edita ele)
- Goal é **modificação** num código já presente

Pedido "do zero" é fundamentalmente outro problema:

- Não há projeto — precisa escolher stack, scaffolding, deps
- Não há arquivo-alvo — primeiro precisa CRIAR a árvore
- Goal é **construção**, não modificação

Tentar resolver os dois com o mesmo prompt 6-layer é forçar a barra. O
template do cli foi medido em modificações pontuais (12 cases, todos
edits) — ele NÃO foi validado pra ser arquiteto de projeto novo. Hoje
quando alguém pede "faça um app de gerenciamento de condomínios em Next.js
do zero", a saída é uma sopa imprevisível.

---

## 2. Vision — dois modos, um pipeline

Sp + cli viram **duas entradas para o mesmo pipeline de verify-loop**:

| Modo | Comando | Premissa | Template-driver |
|---|---|---|---|
| **task** (existente) | `simplicio-py task "<goal>"` | repo existe, edit incremental | cli 6-layer |
| **scratch** (novo) | `simplicio-py scratch "<goal>"` | repo vazio ou inexistente, build inicial | cli 6-layer **+** stack template **+** plan |

Diferença-chave: **scratch tem fase de plan ANTES da geração**. O planner
recebe o goal, escolhe stack a partir dos 30 templates, propõe estrutura
de arquivos, lista as N tasks de implementação. Cada task vira um
`simplicio-py task` interno. Verify-loop final usa o test runner do template.

---

## 3. Arquitetura — onde cada peça mora

### 3.1 CLI surface (nova)

```bash
# do zero — pede stack se ambíguo, escreve árvore, gera plan, executa tasks
simplicio-py scratch "<one-line goal>" [--stack <slug>] [--planner <provider>]

# auxiliares
simplicio-py scratch --list-stacks         # 30 templates registrados
simplicio-py scratch --show-stack <slug>   # readme + arquivos do template
simplicio-py scratch --plan-only "<goal>"  # gera só o plan, não executa
```

### 3.2 Módulos novos em `simplicio/`

```
simplicio/
├── scratch/
│   ├── __init__.py
│   ├── cli.py              # subcomando `simplicio-py scratch`
│   ├── stack_registry.py   # carrega templates locais + remotos
│   ├── planner.py          # roda planner LLM (DeepSeek por default)
│   ├── plan_schema.py      # contrato {stack, files, tasks, deps, tests}
│   └── executor.py         # itera o plan chamando pipeline.run por task
├── templates/
│   └── stacks/              # 30 sub-pastas, uma por stack — schema na §4
│       ├── ts-nextjs/
│       ├── py-fastapi/
│       ├── rust-axum/
│       └── ...
└── providers.py             # +DeepSeek route (planner-grade)
```

### 3.3 Data flow

```
   ┌──────────────────┐
   │ user goal text   │
   └────────┬─────────┘
            ▼
   ┌──────────────────┐    1. stack inference
   │ stack_registry   │       (rule-based + LLM fallback)
   └────────┬─────────┘
            ▼
   ┌──────────────────┐    2. plan generation
   │ planner          │       (DeepSeek-V4-Pro by default,
   │ (DeepSeek)       │        configurable via env)
   └────────┬─────────┘
            ▼
   ┌──────────────────┐    3. PlanSchema validated
   │ plan_schema      │       (files, tasks, test-cmd, deps)
   └────────┬─────────┘
            ▼
   ┌──────────────────┐    4. scaffold from template
   │ executor         │       + write package manifests + install deps
   │  ↓ for each task │    5. for each task in plan.tasks:
   │  → pipeline.run  │           simplicio-py task internally (cli + verify-loop)
   └────────┬─────────┘
            ▼
   ┌──────────────────┐    6. final report (passed tasks, evidence)
   │ scratch report   │
   └──────────────────┘
```

---

## 4. Template registry — as 30 stacks

### 4.1 Schema de um template (`simplicio/templates/stacks/<slug>/`)

```
<slug>/
├── stack.json              # metadata + dependency manifest
├── README.md               # human-readable, fed to planner as context
├── tree/                   # files literally copied at scaffold time
│   ├── package.json (or pyproject.toml, Cargo.toml, ...)
│   ├── .gitignore
│   ├── README.template.md  # rendered with {project_name}, {goal}
│   ├── src/...
│   └── tests/...
├── practices.md            # best practices for THIS stack version
│                            # (linter, format, test runner, file layout,
│                            #  naming, error handling, log strategy)
└── verify.json             # how cli's verify-loop runs tests + lint
```

`stack.json`:

```json
{
  "slug": "ts-nextjs",
  "language": "TypeScript",
  "framework": "Next.js 14 (app router)",
  "version_pinned": "next@14.2",
  "node": ">=20",
  "package_manager": "pnpm",
  "test_runner": "vitest",
  "e2e_runner": "playwright",
  "linter": "eslint + prettier",
  "deps_required": ["next", "react", "react-dom"],
  "deps_dev": ["typescript", "vitest", "@playwright/test"],
  "tags": ["web", "ssr", "react", "typescript"]
}
```

### 4.2 Lista inicial dos 30 slugs

Priorização por adoção (StackOverflow Dev Survey 2024-25 + GitHub
language stats) cruzada com clareza de "stack default" (linguagem só
não basta; framework precisa ser escolhido).

| # | slug | language | framework |
|---|---|---|---|
| 1 | `ts-nextjs` | TypeScript | Next.js 14 app router |
| 2 | `ts-nestjs` | TypeScript | NestJS 10 + Fastify |
| 3 | `ts-remix` | TypeScript | Remix 2 |
| 4 | `js-express` | JavaScript | Express 4 + Node 20 |
| 5 | `py-fastapi` | Python 3.12 | FastAPI + uvicorn |
| 6 | `py-django` | Python 3.12 | Django 5 + DRF |
| 7 | `py-flask` | Python 3.12 | Flask 3 |
| 8 | `py-cli` | Python 3.12 | Typer + Rich |
| 9 | `rust-axum` | Rust | Axum + tokio + sqlx |
| 10 | `rust-leptos` | Rust | Leptos (full-stack SSR) |
| 11 | `rust-cli` | Rust | Clap + anyhow |
| 12 | `go-gin` | Go 1.23 | Gin + GORM |
| 13 | `go-echo` | Go 1.23 | Echo + sqlc |
| 14 | `go-cli` | Go 1.23 | Cobra + Viper |
| 15 | `java-spring` | Java 21 | Spring Boot 3 |
| 16 | `kotlin-spring` | Kotlin | Spring Boot 3 |
| 17 | `kotlin-ktor` | Kotlin | Ktor 3 |
| 18 | `kotlin-android` | Kotlin | Jetpack Compose |
| 19 | `swift-vapor` | Swift 5 | Vapor 4 |
| 20 | `swift-ios` | Swift 5 | SwiftUI |
| 21 | `csharp-aspnet` | C# 12 | ASP.NET Core 8 minimal API |
| 22 | `csharp-blazor` | C# 12 | Blazor Server |
| 23 | `php-laravel` | PHP 8.3 | Laravel 11 |
| 24 | `php-symfony` | PHP 8.3 | Symfony 7 |
| 25 | `php-vanilla` | PHP 8.3 | Composer + PHPUnit (template do sindico) |
| 26 | `ruby-rails` | Ruby 3.3 | Rails 7 |
| 27 | `elixir-phoenix` | Elixir 1.17 | Phoenix 1.7 + LiveView |
| 28 | `dart-flutter` | Dart 3 | Flutter (mobile) |
| 29 | `bash-cli` | Bash | shellcheck + bats |
| 30 | `react-vite` | TypeScript | React 18 + Vite (SPA pura) |

> Critério de inclusão: stack onde "cria projeto novo" é prática
> reconhecida (não só "compila código"). Linguagens académicas (Haskell,
> OCaml, Julia) ficam de fora do v1 — entram via PR comunitário.

### 4.3 Versionamento

- Cada `stack.json` carrega `template_version: "0.1.0"`
- `simplicio-py scratch --list-stacks` mostra versões
- Atualização de stack vira PR no `simplicio-dev-cli` (não no
  `simplicio-prompt` — templates de scaffold são responsabilidade do cli)
- Templates remotos (futuro): `simplicio-py scratch --stack-source github:org/repo`

---

## 5. Planner provider — DeepSeek via HuggingFace por default

> **Atualização (commit subsequente ao RFC inicial):** o planner default
> mudou de DeepSeek API direto pra DeepSeek servido pelo HuggingFace
> Inference Router. Razão: a maioria dos usuários já tem `HF_TOKEN`,
> reduzindo o atrito de "comprar mais um plano só pra planner". Quem
> prefere DeepSeek direto passa `SIMPLICIO_PLANNER=deepseek/<model>`.



### 5.1 Por que separar planner de doer

Plan demanda capacidade de raciocínio amplo (escolher arquitetura, decompor
em tasks coerentes, antecipar deps). Doer demanda fidelidade ao contrato
(o cli 6-layer já mede 91% nesses cenários). São dois tradeoffs diferentes:

- **Planner**: precisa de modelo frontier — DeepSeek-V4-Pro, Claude Opus 4.7,
  GPT-5.5, Qwen 3.7 Max. Custo alto OK porque é 1 call por scratch.
- **Doer**: roda Coder-Next ou similar — custo baixo por task, mas N tasks
  num scratch. Total domina; precisa ser otimizado.

### 5.2 Como DeepSeek vira default

Adicionar route em `simplicio/providers.py`:

```python
# pseudocódigo
def _planner_provider() -> str:
    return os.environ.get("SIMPLICIO_PLANNER",
                          "deepseek/deepseek-v4-pro")

def _planner_complete(prompt: str) -> str:
    model = _planner_provider()
    if model.startswith("deepseek/"):
        return _openai_compatible_call(
            base_url="https://api.deepseek.com/v1",
            api_key=os.environ["DEEPSEEK_API_KEY"],
            model=model.split("/", 1)[1],
            prompt=prompt,
            temperature=0.1,  # plan needs to be deterministic
        )
    # fallback: roteia pelo `complete` genérico
    return complete(prompt)
```

Variáveis de ambiente:

```bash
# default — DeepSeek-V3.1 via HuggingFace Inference Router
SIMPLICIO_PLANNER=deepseek-hf/deepseek-ai/DeepSeek-V3.1
HF_TOKEN=hf_...

# DeepSeek direto (sem HF middleman)
SIMPLICIO_PLANNER=deepseek/deepseek-v4-pro
DEEPSEEK_API_KEY=sk-...

# overrides comuns
SIMPLICIO_PLANNER=openai/gpt-5.5                # OPENAI_API_KEY
SIMPLICIO_PLANNER=openrouter/anthropic/claude-opus-4-8  # OPENROUTER_API_KEY
SIMPLICIO_PLANNER=anthropic/claude-opus-4-8     # ANTHROPIC_API_KEY (SDK nativo)
SIMPLICIO_PLANNER=hf/Qwen/Qwen3-Coder-Next      # qualquer modelo no HF router
SIMPLICIO_PLANNER=claude-cli/auto               # Claude Code Pro/Max (shell-out)
```

### 5.3 Plan schema (saída do planner)

Contrato rígido, validado por `plan_schema.py` (jsonschema):

```json
{
  "version": "1.0",
  "stack": "ts-nextjs",
  "project_name": "condo-mgmt-app",
  "rationale": "string — por que essa stack para essa goal",
  "files_to_create": [
    {"path": "src/lib/db.ts", "purpose": "Drizzle setup with PostgreSQL"},
    {"path": "src/app/api/units/route.ts", "purpose": "REST endpoint"}
  ],
  "tasks": [
    {
      "id": "T01-db-setup",
      "depends_on": [],
      "goal": "Initialize Drizzle ORM with PostgreSQL connection",
      "target": "src/lib/db.ts",
      "criteria": "- db client exported as default\n- env var DB_URL respected\n- 1 unit test of connection",
      "constraints": "- use drizzle-orm@latest\n- no other ORM",
      "verify": "pnpm test src/lib/db.test.ts"
    },
    "..."
  ],
  "deps_to_install": ["drizzle-orm", "postgres", "@types/node"],
  "deps_dev": ["vitest", "@types/postgres"],
  "test_command": "pnpm test --run",
  "lint_command": "pnpm lint",
  "estimated_total_tasks": 12
}
```

Planner é instruído a obedecer essas keys e nada mais — schema-validated
antes de virar plan. Saída fora do schema → reject + retry com feedback.

---

## 6. SkillOpt — gerador de skill sob demanda

### 6.1 Onde mora

Vira um skill ele mesmo: `.skills/skill-opt/SKILL.md`. Trigger explícito:

```bash
simplicio skill new "<descrição do que a skill faz>"
```

Roda flow:

1. Lê o template em `.skills/_template/SKILL.md`
2. Manda pra DeepSeek com:
   - Template do `_template`
   - Lista das skills existentes (anti-duplicate)
   - Descrição do usuário
3. Saída esperada: SKILL.md preenchido + `description`, `trigger`, `steps`, `dod`
4. Valida via schema (frontmatter obrigatório + seções esperadas)
5. Cria pasta `.skills/<slug>/` com SKILL.md
6. Adiciona entrada em `.skills/README.md`
7. Roda smoke test (se a skill declarar comando de teste)

### 6.2 Integração com scratch

Quando o plan exige operação não-padrão (ex: "esse projeto usa Liquibase
pra migration — não tem skill pra isso"), o executor pode chamar SkillOpt
inline pra criar a skill antes de seguir. Loop:

```
plan.tasks[i] requires X →
  X has matching skill in .skills/? →
    YES → execute task
    NO  → simplicio skill new "<derivada do task contrato>"
          → execute task with new skill loaded
```

### 6.3 Schema do SKILL.md

Mantém o frontmatter atual (`name`, `description`, `trigger`, `steps`, `dod`)
+ novo bloco opcional `auto_generated` com a metadata de origem:

```yaml
auto_generated:
  by: skill-opt
  date: 2026-05-29
  source_goal: "string que originou a criação"
  planner_model: "deepseek/deepseek-v4-pro"
  review_required: true   # true para skills geradas — humano valida antes de virar default
```

---

## 7. Implementação em fases

Mesmo modelo do roadmap do sp — cada fase tem métrica-âncora.

### Fase 0 — Provider plumbing (3 dias)

- Adicionar DeepSeek route em `simplicio/providers.py`
- Env var `DEEPSEEK_API_KEY` + `SIMPLICIO_PLANNER` documentados
- Test unit cobrindo as 3 routes (existing + claude-cli/codex-cli + deepseek/*)
- Métrica: `python -c "from simplicio.providers import complete; ..."` funciona com `SIMPLICIO_PLANNER=deepseek/deepseek-v4-pro`

### Fase 1 — Template registry com 5 stacks pilot (1 semana)

- Estrutura `simplicio/templates/stacks/` com schema
- Implementa 5 templates (`ts-nextjs`, `py-fastapi`, `rust-axum`, `go-gin`, `php-laravel`) — cobrem os arquétipos principais
- CLI: `simplicio-py scratch --list-stacks` + `--show-stack`
- Métrica: cada template scaffolds clean (npm/pip/cargo install passa, test runner verde no projeto vazio)

### Fase 2 — Planner + plan schema (1-2 semanas)

- `simplicio/scratch/planner.py` chama DeepSeek com goal + template README + practices
- `plan_schema.py` valida saída (jsonschema strict)
- CLI: `simplicio-py scratch --plan-only "<goal>"` retorna plan validado
- Métrica: 20 goals reais (5 por stack) — DeepSeek retorna plan-schema-válido em ≥18/20 (90%)

### Fase 3 — Executor + integração com pipeline.run (2 semanas)

- `executor.py` itera tasks do plan, cada uma vira `simplicio-py task` interno
- Scaffolding inicial: copia tree/, roda package manager install, cria git init
- Loop verify por task (já existe via `pipeline.run`)
- Métrica: scratch end-to-end em 5 stacks com goal "CRUD básico" — projeto compila + roda + tests passam em ≥4/5

### Fase 4 — Completar para 30 stacks (3-4 semanas, paralelo)

- Cada stack vira PR isolado (templates não conflitam entre si)
- Aceita contribuição comunitária via skeleton bem documentado
- Métrica: 30 templates, todos passam smoke test (scaffold + install + test runner clean)

### Fase 5 — SkillOpt + auto-criação inline (2 semanas)

- `.skills/skill-opt/SKILL.md` com flow descrito
- `simplicio skill new "<desc>"` standalone
- Integração em executor: faltou skill no plan → cria inline com gate de review
- Métrica: 10 skills geradas, ≥8 passam review humano sem reescrita

---

## 8. Anti-padrões — o que NÃO fazer

- **Misturar task e scratch no mesmo prompt.** São tradeoffs opostos
  (modify vs build). Forçar uma única interface confunde o modelo e
  empilha edge cases.
- **Confiar no LLM pra escolher stack sem template explícito.** Sem o
  schema do `stack.json` + practices, o plan fica genérico e o
  scaffolding sai inconsistente. Templates SÃO a memória institucional.
- **Templates sem versioning.** Stack evolui (Next.js 14 → 15, Spring 3 →
  4). Sem `template_version` no `stack.json`, manutenção vira pesadelo.
- **Planner local.** DeepSeek-V4-Pro custa ~$0.05 por plan; rodar
  planner em modelo local pra economizar custo significa plans ruins.
  Economiza centavo, queima hora.
- **SkillOpt sem review gate.** Skills geradas vão direto pra produção =
  receita pra contaminação do `.skills/` com skill duplicada/quebrada.
  `review_required: true` no frontmatter da skill gerada é não-negociável.
- **Stack templates importando deps esotéricas.** Cada template puxa
  apenas deps **com >1k stars no GitHub e release nos últimos 12 meses**.
  Anti-bitrot rule.

---

## 9. Open questions

1. **Stack inference**: `simplicio-py scratch "build me a condo app"` precisa
   inferir stack ou exigir `--stack`? Proposta: **inferir** via DeepSeek com
   fallback "ts-nextjs" pra web não-especificado; sempre IMPRIMIR a stack
   escolhida antes de executar (interrompível com Ctrl+C).
2. **Plan execution paralela ou sequencial**? Tasks com `depends_on: []`
   poderiam rodar em paralelo. Risco: race em package.json + DB migrations.
   Proposta: **sequencial v1**, paralelo via flag `--parallel` em v2.
3. **Custo do planner**: 1 scratch ≈ 1 DeepSeek call (~$0.05) + N task
   calls. Pra projetos grandes (N=30+), DeepSeek também executa tasks ou
   só plana? Proposta: DeepSeek só plana; tasks vão pro `SIMPLICIO_MODEL`
   normal (default Coder-Next).
4. **Template como código vs como dados**: stacks puramente declarativas
   (JSON+files) limitam customização. Permitir hooks Python opcionais
   (`stacks/ts-nextjs/hooks.py`) com `pre_scaffold`, `post_scaffold` etc.?
   Proposta: começar declarativo, adicionar hooks só se demanda concreta
   aparecer.
5. **Compatibilidade com `simplicio-py init`**: o init atual instala skill +
   hook. Scratch é um terceiro modo. Renomear pro alinhamento? `simplicio
   install` (hook), `simplicio-py scratch` (do zero), `simplicio-py task`
   (modify)?
6. **Telemetria**: scratch é caro (planner + N tasks). Vale logar
   stack-scolhida, # tasks, % passados, tempo total pra alimentar a
   próxima geração de templates? Proposta: opt-in via
   `SIMPLICIO_TELEMETRY=1`.

---

## 10. Critério de release v0.5

`simplicio-py scratch` pode chamar de release quando o bench (novo —
não existe ainda) mostrar:

- **15 goals reais × 5 stacks pilot** (Fase 1): planner válido em ≥90%,
  scaffold limpo em ≥95%, projeto compila + roda + tests verdes em ≥80%
- **End-to-end median wall-clock ≤ 8 minutos** para CRUD básico em qualquer
  stack pilot (planner + scaffold + 12 tasks + verify-loop)
- **Custo $ por scratch ≤ $1.00** (planner DeepSeek + Coder-Next em N tasks)
- **Skill-opt taxa de aprovação humana ≥ 80%** nas primeiras 20 skills

---

## 11. Próximo passo concreto

Se aprovado, sequência operacional pra começar:

1. PR no `simplicio-dev-cli`: adicionar Fase 0 (DeepSeek route em
   `providers.py`) + skeleton `simplicio/scratch/` vazio + um stack pilot
   (`py-fastapi`, mais simples de validar)
2. Issue tracking pra os 30 templates (cada um vira PR comunitário ou
   ticket interno)
3. RFC público (este doc) commitado em `bench/SCRATCH_MODE_RFC.md`
   pra coleta de feedback antes de implementação

---

## Histórico

- 2026-05-29 — proposta inicial. Base na conversa "do zero + DeepSeek
  planner + SkillOpt" da sessão de bench Qwen3 Coder MoE.

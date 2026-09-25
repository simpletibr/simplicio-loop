# Relatório consolidado de benchmark — simplicio-cli

> Documento único que reúne todo o material de benchmark de `bench/` (e as tabelas
> de benchmark do `README.md` / `CHANGELOG.md`).
>
> **Regra de honestidade (cumprida à risca):** só aparecem aqui números que constam
> literalmente nos arquivos-fonte. Onde o valor não existe, está marcado `n/d` (não
> disponível). Cada tabela cita o arquivo de origem. **Nada foi estimado, arredondado
> ou extrapolado.** Quando uma fonte é estimativa de design (não medição), está dito.
>
> Data de consolidação: 2026-05-31. Lista de fontes no fim do arquivo.

---

## Sumário executivo

- **Uplift de capa medido = +58pt (regex).** Na suíte regex de 156 checks, Qwen2.5-Coder-7B sobe de **38% para 96%** com o contrato 6-layer. Fonte: `README.md` (linha 117), `bench/results_comparison.md`.
- **Decomposição causal (4-quadrant, agregado, n=40):** prompt 6-layer sozinho (Q2−Q1) **+55pt**; loop sozinho (Q3−Q1) **+47pt**; juntos (Q4) chegam a **70%** de pass-rate. As 3 hipóteses ("loop sozinho basta", "simplicio sozinho basta", "ganhos somam linearmente") **TODAS REJEITADAS**. Fonte: `bench/results_4quadrant_full.md`.
- **Maior pass-rate absoluto com execução real (PHPUnit) = 100%:** `Qwen3-Coder-Next` (cli+ag e modal-vote fan-out 12/12) e `deepseek/deepseek-v4-flash` (cli+ag e cli+sp+ag, 12/12). Fontes: `bench/results_full_qwen3.md`, `bench/results_v14_interim.md`, `bench/results_exec_sindico.md`, `bench/results_fanout.md`.
- **`cli+ag` (verify-loop) é o único lado que bate o `cli` sozinho de forma confiável no funcional.** O `cli+sp` (composição com simplicio-prompt) empata ou fica atrás do `cli` em single-call. Fontes: `bench/results_full_qwen3.md`, `bench/results_4side_qwen3.md`.
- **`regex` infla vs funcional:** no fan-out N=200 (temp=0.7), `Qwen3-Coder-30B-A3B-Instruct` marca regex 100% e PHPUnit 0% em **6 de 12 casos** (gap +50pt cada); agregado dos 2 modelos: regex 94% vs funcional 66% (gap **+28pt**). Prova numérica do "regex não quer dizer que roda". Fontes: `bench/results_fanout.md`, `bench/results_4side_qwen3.md`.
- **simplicio-prompt (sp) sozinho NÃO supera o contrato cli** em geração one-shot — numa rodada foi até net-negativo (**47% baseline → 44% com sp, −3pt**; cli ref 75%). Fonte: `bench/results_sp_compare.md`.
- **Família tiny: contrato multiplica modelo capaz, não cria capacidade.** No sindico real, Gemma-3-4B vai 0%→75% (+75pt), mas Llama-3.2-1B e Gemma-3n-e4B ficam 0%/0% (não emitem PHP parseável). Fonte: `README.md` (linhas 52-61).
- **Schema v1 (structured output) tem fronteira de tamanho:** Qwen2.5-Coder-3B faz **4/4 (100%) parse_ok**, DeepSeek-V4-Flash **3/4 (75%)**, mas Gemma-4B e Qwen-1.5B fazem **0%**. Especialização coder ajuda, mas não compensa abaixo de ~3B. Fontes: `bench/results_sp_schema_validation.md`, `bench/results_v14_qwen15b_gguf_partial.md`.
- **Alavancas determinísticas (fixers/recipes/codegen/cache) cortam chamadas de LLM** sem perder pass-rate: caminho local modelado **19 → 6 chamadas (−68,42%)**; prova de release **210 → 0 (−100%)**. Fontes: `bench/results_llm_reduction_summary.md`, `bench/results_static_fixers.md`, `bench/results_scratch_codegen.md`.
- **Modo scratch passa o gate live:** **75/75 e2e verde** em 5 stacks (go-gin, php-laravel, py-fastapi, rust-axum, ts-nextjs), custo zero, com codegen determinístico (executor 100% vs LLM baseline 55.56%). Só não é "release ready" por falta de aprovação humana de SkillOpt. Fontes: `bench/results_scratch_live_gate.md`, `bench/results_scratch_codegen.md`.
- **Rust hot-path (`simplicio-core`) valida o prompt:** 5/5 parity, **8.47x** mais rápido que Python, e o prompt montado em Rust leva `qwen2.5-coder:3b` a **5/6 (83%)** no exec real. Fonte: `bench/results_rust_qwen.md`.
- **Curva de quantização do 1.5B GGUF (issue #46) é parcial:** Q5_K_M = **66% (4/6)** e Q8_0 = **83% (5/6)** via ollama (run_exec, single-shot); Q5_K_M = **parcial 2/12** via llama-cpp-python (sindico). Q6_K e Q4_K_M **não foram rodados**. Fontes: `bench/RESULTS_LOCAL_GGUF.md`, `bench/results_v14_qwen15b_gguf_partial.md`.

---

## Metodologia

Fontes desta seção: `bench/SIMPLICIO_FLOW_GUIDE.md`, `bench/UNIFIED_RUN_ARCHITECTURE.md`,
`bench/results_v13_5side.md`, `bench/results_4quadrant_full.md`, `bench/results_full_qwen3.md`,
`bench/results_fanout.md`.

### Sides (variações de pipeline) — terminologia oficial dos relatórios

Os relatórios usam os rótulos `sem`/`com`/`sp`/`ag`/`spag`:

| key no JSON | rótulo | O que é |
|---|---|---|
| `sem` | **baseline** | goal cru de uma linha + conteúdo do arquivo. Sem simplicio. |
| `com` | **cli** (cli alone) | contrato 6-layer do simplicio-cli (role/stack, goal, target, criteria como estados testáveis, constraints, output shape). |
| `sp` | **cli + sp** | mesmo contrato embutido como user-input-X dentro do runtime simplicio-prompt v1.9 (Tuple-Space + Yool, ~3.907 chars de preâmbulo). Composição. |
| `ag` | **cli + ag** | mesmo contrato como semente de um verify-loop: em falha, a harness classifica o tail do PHPUnit (ou padrões regex faltando) e re-prompta, **até 3 tentativas**. Espelha `simplicio-py task --verify` / `simplicio.pipeline.run()`. |
| `spag` | **cli + sp + ag** | full stack: cli embrulhado em sp como semente do verify-loop. Composição + retry. |

Lado adicional: **`cli (fan-out)`** — contrato cli repetido **N=200** subagents em paralelo via `kernel.subagent_runtime.SubagentRuntime` (temperature=0.7, `use_cache=False`). Pass = (a) taxa por tentativa, (b) modal-vote (output normalizado mais comum). Fonte: `bench/results_fanout.md`.

### Quadrantes (bench 4-quadrant)

| Cell | Prompt | Execução |
|---|---|---|
| Q1 | goal cru | 1-shot (baseline) |
| Q2 | simplicio 6-layer | 1-shot |
| Q3 | goal cru | loop com feedback |
| Q4 | simplicio 6-layer | loop com feedback (composição) |

Fonte: `bench/results_4quadrant_full.md` (metodologia em `docs/benchmark-4quadrant.md`).

### Suítes / oráculos de avaliação

- **regex** — checagem estrutural determinística (regex) contra o output do modelo (menção ao arquivo-alvo, bloco DIFF, bloco TEST, palavras de contract-state). **156 checks** sobre **10 casos/lado** (stacks angular/dotnet/react). **Proxy barato — pode inflar vs comportamento real.** Fonte: `bench/results.md`, `bench/cases_offline.json`.
- **exec (sindico)** — execução real: o arquivo gerado substitui o original numa cópia de [`wesleysimplicio/sistema-sindico`](https://github.com/wesleysimplicio/sistema-sindico) (PHP 8, PHPUnit 11); um **teste PHPUnit oculto** (nunca mostrado ao modelo, asserindo estados verdadeiro E falso) é injetado; roda a **suíte de produção inteira**. **Pass = `vendor/bin/phpunit` exit code 0.** **12 casos.** Fonte: `bench/results_exec_sindico.md`.
- **exec (Python, run_exec)** — 6 funções Python self-contained, cada `solution.py` rodada contra suíte pytest oculta. Single-shot (sem verify-loop). Fonte: `bench/results_rust_qwen.md`, `bench/RESULTS_LOCAL_GGUF.md`.
- **scratch gates** — gates do modo from-scratch: preflight → live gate (75 runs, 5 stacks) → release gate. Fontes: `bench/results_scratch_*.md`.

### Métrica e amostragem

- **pass-rate** = checks/casos aprovados ÷ total. **uplift** = pass-rate(lado) − pass-rate(baseline) em pontos (pt).
- O bench regex roda a `temperature=0` (single-sample, sujeito a ruído de provider); o fan-out a `temperature=0.7` com N=200.
- `cli+ag` roda **até 3 tentativas**; o sufixo `(N)` nas matrizes per-task é o número de tentativas consumidas (1 = passou de primeira).

### Backends

| Backend | Como resolve | Exemplo nas fontes |
|---|---|---|
| HF (transformers) local | baixa peso do HF Hub, roda em CPU | `local:Qwen/Qwen2.5-Coder-1.5B-Instruct` |
| HF Inference Router | API remota HF | `Qwen/Qwen3-Coder-30B-A3B-Instruct` |
| Ollama (local) | daemon `ollama serve`, endpoint OpenAI-compat | `qwen2.5-coder:7b` |
| GGUF local (llama-cpp-python) | carrega `.gguf` in-process | Qwen2.5-Coder-1.5B Q5_K_M |
| OpenRouter | API remota | `qwen/qwen-2.5-coder-32b-instruct`, `deepseek/deepseek-v4-flash` |

---

## Resultados por bench

Uma subseção por arquivo de resultado. Tabelas copiadas fielmente da fonte.

### `bench/results.md` — bench regex offline (3 modelos OpenRouter, 156 checks)

**Mede:** `with` vs `without` simplicio (só o contrato 6-layer, 1-shot), 156 checks regex sobre 10 casos, 3 modelos via OpenRouter. Data 2026-05-30.

Headline: **without 57/156 (36%) → with 107/156 (68%), Δ +32pt (+88% relativo).**

| Model | Cases | Without | With | Delta (pts) | Relative gain |
|---|---|---|---|---|---|
| `meta-llama/llama-3.2-3b-instruct` | 10 | 17/52 (32%) | 36/52 (69%) | +37 | +112% |
| `google/gemma-3-4b-it` | 10 | 22/52 (42%) | 48/52 (92%) | +50 | +118% |
| `qwen/qwen-2.5-coder-32b-instruct` | 10 | 18/52 (34%) | 23/52 (44%) | +10 | +28% |

Sinais estruturais (30 runs/lado): DIFF block 0%→90%; target file 0%→100%; TEST block 80%→53%. Custo: tokens +8%, wall-clock −37%.

**Takeaway:** contrato sobe pass-rate em todos; ganho enorme no gemma (+50pt), modesto no 32B nessa rodada single-sample (+10pt). É a fonte "regex" que os `consolidate_*.py` cruzam com o exec.

### `bench/results_exec.md` — exec real Python, qwen2.5-coder:3b (6 casos)

**Mede:** WITH vs WITHOUT contrato em 6 funções Python self-contained, pytest oculto, single-shot. Data 2026-05-28. Modelo `qwen2.5-coder:3b`.

Headline: **without 4/6 (66%) → with 5/6 (83%), Δ +17pt.**

| Model | Without | With | Delta (pts) |
|---|---|---|---|
| `qwen2.5-coder:3b` | 4/6 (66%) | 5/6 (83%) | +17 |

Per-task: `validate_password` vira fail→pass com o contrato; `merge_intervals` falha nos dois lados (limite de raciocínio do 3B).

**Takeaway:** rodada de execução real Python pequena (6 casos); o contrato recupera 1 caso. É a mesma harness usada em `results_rust_qwen.md` e `RESULTS_LOCAL_GGUF.md`.

### `bench/results_exec_sindico.md` — execução real PHPUnit (DeepSeek-V4-Flash, 5 lados, 12 casos)

**Mede:** 12 tasks reais em `sistema-sindico`, oráculo PHPUnit exit 0. Modelo `deepseek/deepseek-v4-flash`. Data 2026-05-31.

Headline: baseline **6/12 (50%)** · cli **11/12 (91%, +41pt)** · cli+sp **9/12 (75%, +25pt)** · cli+ag **12/12 (100%, +50pt)**.

| Model | Baseline | cli alone | cli + sp | cli + ag | Δ cli | Δ (cli+sp) | Δ (cli+ag) |
|---|---|---|---|---|---|---|---|
| `deepseek/deepseek-v4-flash` | 6/12 (50%) | 11/12 (91%) | 9/12 (75%) | 12/12 (100%) | +41 | +25 | +50 |

**Takeaway:** no funcional real, `cli+ag` leva a 100%; `cli+sp` (75%) fica abaixo do `cli` sozinho (91%) — a composição com sp não ajuda single-call. Este JSON (`results_exec_sindico.json`) é a base de exec dos scripts de consolidação.

> Nota: o README documenta uma rodada **anterior** deste bench com **9 modelos × 4 tasks** (não 12): baseline **33% → cli 64% (+31pt)**. O `.md` versionado reflete a rodada DeepSeek de 12 casos. São medições diferentes.

### `bench/results_v13_5side.md` — 5 lados, v13 (3 modelos, exec + regex)

**Mede:** os 5 lados em 2 métricas (PHPUnit funcional n=12 + regex t=52), 3 modelos. Data 2026-05-30.

| Model | metric | base | cli | cli+sp | cli+ag | cli+sp+ag | Δcli | Δsp | Δag | Δsp+ag |
|---|---|---|---|---|---|---|---|---|---|---|
| `llama-3.2-3b-instruct` | exec | 8% | 8% | 8% | 8% | 8% | +0 | +0 | +0 | +0 |
| `llama-3.2-3b-instruct` | regex | 32% | 69% | 67% | 88% | 76% | +37 | +35 | +56 | +44 |
| `gemma-3-4b-it` | exec | 33% | 66% | 50% | 66% | 41% | +33 | +17 | +33 | +8 |
| `gemma-3-4b-it` | regex | 42% | 92% | 88% | 92% | 92% | +50 | +46 | +50 | +50 |
| `qwen-2.5-coder-32b-instruct` | exec | 8% | 16% | 16% | 16% | 16% | +8 | +8 | +8 | +8 |
| `qwen-2.5-coder-32b-instruct` | regex | 34% | 44% | 38% | 82% | 80% | +10 | +4 | +48 | +46 |

Convergência verify-loop (exec, tentativas médias): llama cli+ag 2.83 / spag 2.83; gemma 1.67 / 2.17; qwen-32b 2.67 / 2.67.

**Takeaway:** divergência forte exec×regex nos pequenos (llama exec 8% em todos os lados, regex sobe a 88%). No 32B o exec é baixo (16%) — casos sindico são duros para 1-shot; `cli+ag` é quem mais move o regex (+48pt). `cli+sp` chega a **regredir** o exec do gemma (66%→50%).

### `bench/results_v13_interim.md` — v13 interim (snapshot ao vivo, mesmos números)

**Mede:** parser dos logs ao vivo do v13; os 3 modelos já fechados. Captura 2026-05-30 22:10. Os números são **idênticos** aos de `results_v13_5side.md` (mesma rodada). Não repetir a tabela.

**Takeaway:** referência de progresso; usar `results_v13_5side.md` como versão final.

### `bench/results_v14_interim.md` — v14 interim (PHPUnit, parcial)

**Mede:** v14 funcional PHPUnit 3 modelos × 12 casos × 5 lados, schema v1 ativo nos lados sp. Snapshot 2026-05-31 01:56. Só `deepseek-v4-flash` fechou; os 2 Qwen locais (3B/1.5B) ficaram **em andamento (0/12)**.

| Side | Passed | Rate | Δ vs baseline |
|---|---|---|---|
| baseline | 6/12 | 50% | — |
| cli | 11/12 | 91% | +41 |
| cli+sp | 9/12 | 75% | +25 |
| cli+ag | 12/12 | 100% | +50 |
| cli+sp+ag | 12/12 | 100% | +50 |

Achado: DeepSeek-V4-Flash honra schema v1 em média **81%** dos N=64 subagents (552 parse_ok de 712). DeepSeek+cli+sp parou em cycle 1 (sem escalar pra N=100).

**Takeaway:** confirma a rodada DeepSeek; os Qwen locais (3B/1.5B) não fecharam nesta sessão — lacuna.

### `bench/results_4quadrant_full.md` — decomposição causal (4 modelos, n=40)

**Mede:** Q1/Q2/Q3/Q4 agregados sobre 4 modelos × 10 casos, max_iters=5. Data 2026-05-26. Modelos: gemma-3-4b-it, llama-3.2-3b-instruct, qwen/qwen-2.5-7b-instruct, anthropic/claude-3.5-haiku.

| Quadrant | Pass rate | Avg iters | Tokens / pass | Wall-clock / pass |
|---|---|---|---|---|
| Q1 (no agent, no simplicio) | 0/40 (0%) | 1.00 | 29.522 | 1.016.220 ms |
| Q2 (no agent, with simplicio) | 22/40 (55%) | 1.00 | 991 | 23.551 ms |
| Q3 (with agent, no simplicio) | 19/40 (47%) | 3.92 | 4.978 | 107.562 ms |
| Q4 (with agent, with simplicio) | 28/40 (70%) | 2.60 | 1.563 | 30.584 ms |

Decomposição (pontos): prompt sem loop (Q2−Q1) **+55pt**; loop sem simplicio (Q3−Q1) **+47pt**; prompt dentro do loop (Q4−Q3) **+23pt**; loop com simplicio (Q4−Q2) **+15pt**; sinergia vs soma linear **−32pt**.

Per-model × quadrant: gemma 0/70/40/80%; llama 0/50/40/60%; **qwen-2.5-7b 0/60/80/100%**; claude-3.5-haiku 0/40/30/40%.

**Takeaway:** a peça central de causalidade. 3 hipóteses ("loop sozinho basta", "simplicio sozinho basta", "soma linear") **REJEITADAS** (|Δ| ≥ 5pt). Q4 (70%) > qualquer eixo isolado. Qwen-2.5-7B (general) é o único que chega a 100% no Q4.

### `bench/results_4quadrant.md` — 4-quadrant (focused run, gemma-only)

**Mede:** mesma metodologia, run focado: **só `google/gemma-3-4b-it`, 5 casos, max_iters=3**. Data 2026-05-26.

| Quadrant | Pass rate | Avg iters |
|---|---|---|
| Q1 | 0/5 (0%) | 1.00 |
| Q2 | 3/5 (60%) | 1.00 |
| Q3 | 2/5 (40%) | 3.00 |
| Q4 | 4/5 (80%) | 1.80 |

Decomposição: Q2−Q1 **+60pt**; Q3−Q1 **+40pt**; Q4−Q3 **+40pt**; Q4−Q2 **+20pt**; sinergia **−20pt**. 3 hipóteses REJEITADAS.

**Takeaway:** réplica menor (1 modelo, 5 casos); mesma conclusão (Q4 80% > eixos; sinergia negativa). Usar o full para o agregado robusto.

### `bench/results_4quadrant_wide.md` — 4-quadrant wide (3 modelos, run interrompido)

**Mede:** mesmo desenho varrendo mais casos; **run morto no meio** — qwen-2.5-7b cobriu só 5 de 10 casos; claude-3.5-haiku nunca foi alcançado. Agrega cada tupla (model,case,quadrant) observada (25 tuplas). Data 2026-05-26.

| Quadrant | Pass rate | Avg iters | Tokens / pass | Wall-clock / pass |
|---|---|---|---|---|
| Q1 | 0/25 (0%) | 1.00 | 22.387 | 817.437 ms |
| Q2 | 16/25 (64%) | 1.00 | 1.093 | 14.797 ms |
| Q3 | 11/25 (44%) | 4.00 | 7.154 | 106.382 ms |
| Q4 | 19/25 (76%) | 2.44 | 1.914 | 24.170 ms |

Decomposição: Q2−Q1 **+64pt**; Q3−Q1 **+44pt**; Q4−Q3 **+32pt**; Q4−Q2 **+12pt**; sinergia **−32pt**.
Per-model: gemma 0/70/40/80% (10/10); llama 0/50/40/60% (10/10); qwen-2.5-7b 0/80/60/100% (5/10).

**Takeaway:** consistente com o full (Q4 ~70-76%), mas **parcial** (25 tuplas). 3 hipóteses de novo REJEITADAS.

### `bench/results_full_qwen3.md` — família Qwen3-Coder MoE (exec + regex + fan-out)

**Mede:** relatório "single-source-of-truth" do branch Qwen3. 2 modelos, exec (12) + regex (10) + fan-out (N=200). Data 2026-05-29. Modelos: `Qwen/Qwen3-Coder-30B-A3B-Instruct` (MoE 30B/3B ativo) e `Qwen/Qwen3-Coder-Next` (MoE 80B/3B ativo, 256K ctx), via HF router.

Headline single-call:

| Model | metric | baseline | cli | cli+sp | cli+ag | Δcli | Δcli+sp | Δcli+ag |
|---|---|---|---|---|---|---|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` | exec | 33% | 91% | 91% | 91% | +58 | +58 | +58 |
| `Qwen3-Coder-30B-A3B-Instruct` | regex | 36% | 90% | 98% | 90% | +54 | +62 | +54 |
| `Qwen3-Coder-Next` | exec | 50% | 83% | 83% | 91% | +33 | +33 | +41 |
| `Qwen3-Coder-Next` | regex | 44% | 100% | 94% | 100% | +56 | +50 | +56 |

Fan-out N=200 (contrato cli, modal-vote):

| Model | per-attempt fn | modal fn | per-attempt rx | modal rx | avg uniq/200 | wall-clock | cost |
|---|---|---|---|---|---|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` | 994/2400 (41%) | **5/12** | 2231/2400 (92%) | 11/12 | 6.2 | 520s | $0.0000 |
| `Qwen3-Coder-Next` | 2208/2400 (92%) | **12/12** | 2297/2400 (95%) | 12/12 | 28.2 | 240s | $0.0000 |

**Takeaway:** `Qwen3-Coder-Next` chega a **12/12 funcional** via modal-vote; o 30B-A3B só 5/12 e mostra o regex-infla (regex 92% vs funcional 41% por tentativa). `cli+ag` é o único que melhora o `cli` no funcional. Custo $0 (HF router gratuito nessa rodada).

### `bench/results_4side_qwen3.md` — Qwen3 detalhado (4 lados + gap regex×funcional)

**Mede:** mesmos 2 modelos Qwen3, detalha os 4 lados, convergência e a tabela de discordância regex×funcional. Data 2026-05-29. Headline single-call idêntico ao `results_full_qwen3` — não repetir.

Convergência (tentativas médias cli+ag): 30B-A3B funcional 1.17 / regex 2.00; Coder-Next funcional 1.17 / regex 1.00.

Discordância regex×funcional (fan-out, gap ≥ 30pt) — todos no `30B-A3B`, exceto o último:

| Task | Model | rx | fn | gap |
|---|---|---|---|---|
| env_get_int | 30B-A3B | 100% | 0% | +100 (infla) |
| env_get_bool | 30B-A3B | 100% | 0% | +100 (infla) |
| admin_only_allowed_roles | 30B-A3B | 100% | 0% | +100 (infla) |
| rate_limit_bucket_key | 30B-A3B | 100% | 0% | +100 (infla) |
| base_repository_build_where_sql | 30B-A3B | 100% | 0% | +100 (infla) |
| router_has | 30B-A3B | 100% | 0% | +100 (infla) |
| base_repository_build_update_sql | Coder-Next | 100% | 61% | +39 (infla) |

**Takeaway:** evidência caso-a-caso de que regex mente: 6 casos do 30B-A3B com regex 100% e PHPUnit 0%. Reforça usar exec real, não regex, para decisão.

### `bench/results_fanout.md` — fan-out (kernel simplicio-prompt, N=200)

**Mede:** fan-out via `SubagentRuntime` real do simplicio-prompt v1.7.0, N=200, temp=0.7, `use_cache=False`, 2 modelos Qwen3, 12 tasks sindico, scored por PHPUnit (funcional) E regex. Data 2026-05-29.

| Model | N | fn per-attempt | rx per-attempt | fn modal | rx modal | tokens | cost | avg s |
|---|---|---|---|---|---|---|---|---|
| `Qwen3-Coder-30B-A3B-Instruct` | 200 | 994/2400 (41%) | 2231/2400 (92%) | 5/12 | 11/12 | 3.498.441 | $0.0000 | 43.3s |
| `Qwen3-Coder-Next` | 200 | 2208/2400 (92%) | 2297/2400 (95%) | 12/12 | 12/12 | 3.495.987 | $0.0000 | 20.0s |

Agregado (ambos modelos): fn 3202/4800 (66%) vs rx 4528/4800 (94%), **gap +28pt**; fn modal 17/24, rx modal 23/24.

**Takeaway:** fonte primária do fan-out (`results_fanout.json` é lido pelos `consolidate_*.py`). Confirma: Coder-Next modal 12/12 funcional; 30B-A3B só 5/12 e regex infla +28pt no agregado.

### `bench/results_comparison.md` — old vs new, 17 modelos (regex)

**Mede:** re-run regex (10 casos) comparando o número antigo (README) com o novo. Data 2026-05-28. Qwen2.5-Coder via HF router (1.5B local transformers; 3B/7B HF Inference); os outros 14 via OpenRouter.

Local offline qwen2.5-coder:

| Model | Without (old→new) | With (old→new) | Δ without | Δ with |
|---|---|---|---|---|
| Qwen 2.5 Coder 7B | 36% → 38% | 92% → 96% | +2 | +4 |
| Qwen 2.5 Coder 3B | 34% → 34% | 82% → 94% | +0 | +12 |
| Qwen 2.5 Coder 1.5B | 32% → 30% | 88% → 92% | −2 | +4 |

Tiny sub-4B: Gemma 3 4B 38→40 / 96→92; Llama 3.2 3B 28→30 / 73→76; Gemma 3n e4B 44→38 / 88→90; Phi-4 mini 36→36 / 73→73; Llama 3.2 1B 26→25 / 40→36.
Frontier 2026: GPT-5.5 38→38 / 100→98; Kimi K2.6 40→44 / 100→100; Gemini 3.5 Flash 42→42 / 100→100; Qwen 3.7 Max 44→n/a / 100→n/a; Claude Opus 4.7 42→n/a / 98→n/a; DeepSeek V4 Pro 44→n/a / 96→n/a.
Mid-tier: Gemma 3 12B 34→46 / 92→92; Llama 3.1 8B 36→36 / 90→88; Qwen 2.5 7B 34→34 / 88→100.

Overall (14 re-rodados): without 36%→36%; **with 86%→88%** (dentro do ruído).

**Takeaway:** maior tabela cross-model. Com simplicio, coder/frontier ficam 88-100%. Três frontier (Qwen 3.7 Max, Claude Opus 4.7, DeepSeek V4 Pro) ficaram `n/a` no re-run por falha de provider (HTTP 402); seus números "old" vêm do README.

### `bench/results_rust_qwen.md` — Rust hot-path + qwen2.5-coder:3b (exec real Python)

**Mede:** validação do crate Rust `simplicio-core` (build/correctness/speed/live). Data 2026-05-29. Modelo live: `qwen2.5-coder:3b` (Ollama).

- Build: wheel cp314 nativo em CPython 3.14.5 em 9.49s.
- Correctness: **5/5** parity tests, byte-identical num prompt de 2294 chars.
- Speed: **8.47x** (2.710 µs vs 22.965 µs/call).
- Live (contract effect, run_exec): `qwen2.5-coder:3b` **4/6 (66%) → 5/6 (83%), +17pt**.
- Prompt montado em Rust → qwen → pytest oculto: **5/6 (83%)** (paridade end-to-end).

**Takeaway:** única rodada que cruza Rust e modelo vivo. O 3B em exec real fica em 83% com contrato (single-shot, 6 casos). `merge_intervals` falha nos dois lados (limite do 3B).

### `bench/results_sp_compare.md` / `bench/results_sp_v9.md` — simplicio-prompt vs baseline (exec real)

**Mede:** WITH vs WITHOUT simplicio-prompt (v1.7.0) no sindico real, 3 modelos × 12 tasks = 36 runs/lado. Data 2026-05-28. (Os dois arquivos têm conteúdo idêntico nesta sessão.) Coluna de referência: o contrato cli.

Headline: WITHOUT (baseline) **17/36 (47%)** · WITH simplicio-prompt **16/36 (44%, −3pt)** · *cli ref* **27/36 (75%, +28pt)*.

| Model | WITHOUT | WITH sp | Δ (pts) | *cli ref* |
|---|---|---|---|---|
| `google/gemma-3-4b-it` | 4/12 (33%) | 4/12 (33%) | +0 | *8/12 (66%)* |
| `meta-llama/llama-3.1-8b-instruct` | 5/12 (41%) | 4/12 (33%) | −8 | *7/12 (58%)* |
| `google/gemini-3.5-flash` | 8/12 (66%) | 8/12 (66%) | +0 | *12/12 (100%)* |

**Takeaway:** simplicio-prompt sozinho é **net-neutral a net-negativo** vs baseline cru em one-shot, e **fica bem abaixo do cli** (44% vs 75%). Os dois produtos resolvem problemas diferentes (sp = runtime de agente always-on com fan-out; cli = contrato task-shaped). Não usar sp esperando bater o cli em single-call.

### `bench/results_sp_schema_validation.md` — schema v1 (structured output), 2 modelos

**Mede:** smoke real do `STRUCTURED_OUTPUT=v1` (JSON com 6 campos) em 2 modelos contrastantes. Data 2026-05-30. Task: `isStrong` em `PasswordPolicy`.

| diagnostic | DeepSeek V4 Flash | Qwen 2.5 Coder 3B |
|---|---|---|
| Backend | OpenRouter API | transformers local CPU |
| N invocations | 4 (cycle 1 OK) | 4 sequenciais |
| **parse_ok / N** | **3/4 (75%)** | **4/4 (100%)** |
| behavior groups | 4 | 4 |
| winner.confidence | 1.0 | 0.9 |
| artifact correto (`strlen >= 12`)? | sim | sim |
| Wall-clock | 16.4s (4 paralelos) | ~470s (4 sequenciais CPU) |

Curva de parse_ok por especialização (tabela da fonte): Gemma-4B-it (general) **0/16 (0%)**; DeepSeek V4 Flash (~37B general) **3/4 (75%)**; **Qwen 2.5 Coder 3B 4/4 (100%)**. (Os JSONs brutos `results_sp_schema_smoke_*.json` confirmam: Qwen-3B parse_ok 4/4; DeepSeek parse_ok 3/4 parse_fail 1.)

**Takeaway:** schema v1 **não é luxo de modelo grande** — Qwen-Coder-3B faz 100% parse_ok, refutando a hipótese. A diferença é especialização coder, não tamanho. Smoke pequeno (N=4, 1 task, oráculo heurístico).

### `bench/results_sp_escalation_v1.md` — escalonamento gradual + schema (design + smoke)

**Mede:** design da escalação 64→100→200 subagents + schema v1; smoke com Gemma-4B. Data 2026-05-30. **É majoritariamente design + smoke, não medição de pass-rate.**

Smoke (Gemma-4B, `password_strength`, tiers proxy 4→8→16): `cli+sp fail [tiers=4→8→16, u=16, modal=1, parse=0/16]`; `cli PASS`. Custo modelado (**estimativa de design, NÃO medição**): N=200 cego vs escalator — modelo grande+task fácil −68%; pior caso (cycle 3) +82% (64+100+200=364). Tradeoff: escalator vence se P(passa cycle 1) > 0.45.

**Takeaway:** mecânica do escalator validada end-to-end; **schema falha em modelo pequeno** (Gemma-4B parse 0/16). Os números de economia de custo são **modelados (design)**, não medidos.

### `bench/results_llm_reduction_summary.md` — redução de chamadas LLM (issue #33)

**Mede:** visão agregada das alavancas (cache/static-fixers/recipes/codegen). Valores são **contagens/taxas de gate**, não pass-rate de modelo.

- Caminho local modelado: **19 → 6 chamadas (−68,42%)**.
- Prova de release: **210 → 0 chamadas (−100%)** (135 viraram codegen, 75 planner-calls economizadas por recipe).
- Alavancas (todas gate=True): D cache (warm hit 100%, 50/0); C static fixers (fixed 80%, retry calls −40%, real pkg probe 10/10); A recipes (match 60%, planner calls saved 30); B codegen (codegen share 100%, pass-rate 100%, avg 49ms); scratch live gate (75/75 e2e verde, median 6.262s).
- `release evidence complete: False` (faltam: baseline real de LLM para B/codegen; aprovação humana SkillOpt ≥80%).

**Takeaway:** alavancas determinísticas cortam chamadas drasticamente; evidência de release **ainda incompleta**.

### `bench/results_static_fixers.md` — static fixers (synthetic + probe real)

**Mede:** verify-loop fixer (50 casos sintéticos) + probe real de package-manager + corpus live.

- Casos: **50/50** passaram. Fixed antes do LLM retry: **80%**. Chamadas LLM 100 → 60 (**−40%**).
- Probe real package-manager: **10/10**. Scratch import failure probe: **1/1**.
- Corpus live: 75 runs, **75/75 e2e verde**, 0 falhas elegíveis.
- Breakdown: 40 casos `missing-pip-*` (fixed_before_retry=True, 2→1 chamada); 10 casos `assertion-*` (fixed=False, 2→2 chamadas, mas passed=True).

**Takeaway:** fixers determinísticos resolvem 80% dos retries antes de chamar o LLM (cortam 40%); falhas de assertion não são consertáveis por fixer (precisam de LLM) — esperado.

### `bench/results_scratch_codegen.md` — executores codegen (90 casos)

**Mede:** benchmark determinístico dos executores codegen + corpus live. Métricas de executor (não pass-rate de modelo).

- Casos: **90/90** passaram. Codegen share 100%. Match de executor 100%. Latência média **49 ms**. Planner/llm calls 0.
- LLM baseline: 90 casos, pass-rate **55.56%**, latência média 1173 ms; executor pass-rate ≥ LLM; redução de latência **95.82%**.
- Corpus live: 75/75 e2e verde, 135/135 codegen, 0 chamadas LLM, latência média 61 ms.

**Takeaway:** em task mecânica (CRUD/route/schema), o codegen determinístico bate o LLM (100% vs 55.56%) e é ~95% mais rápido, com zero chamada.

### `bench/results_scratch_recipes.md` — recipes (50 casos goal)

**Mede:** match-before-planner das recipes declarativas + integridade do plan.

- Casos: 50. Matched: **30 (60%)**. Planos válidos: 30. Recipe plan pass-rate **100%**. Planner calls saved **30**.
- LLM baseline (30 matched): pass-rate **100%**, latência média **35.494 ms**; recipe pass-rate ≥ LLM.
- Corpus live: 75 runs, matched **75 (100%)**, planos válidos 75, e2e 75/75.
- 20 casos não-matched são goals "exóticos" (recommendation engine, websocket chat, ML gateway, etc.) — corretamente NÃO casados.

**Takeaway:** recipes cobrem 60% do corpus sintético (100% do corpus live de CRUD), gerando o plano sem chamar o planner (−30 planner-calls), pass-rate igual ao LLM (100%), ~35s mais rápido.

### `bench/results_scratch_live_gate.md` — live gate (75 runs reais, 5 stacks)

**Mede:** execução real do gate scratch v0.5. 15 goals × 5 stacks = 75 runs.

- Planner válido **75/75 (100%)**; scaffold limpo **75 (100%)**; task all passed **75 (100%)**; **e2e verde 75 (100%)**; median wall-clock **6.262 s**; custo médio **0.0**.
- **release_ready: False** — único gate vermelho: `skillopt_human_approval_ge_80` (0/0 skills revisadas = 0%).
- Stacks: go-gin, php-laravel, py-fastapi, rust-axum, ts-nextjs. (php-laravel é o mais lento, ~23-29s; go-gin o mais rápido, ~0.3s.)

**Takeaway:** o modo scratch passa 75/75 e2e em 5 stacks reais com custo zero (codegen determinístico). Não é "release ready" só por falta de evidência de aprovação humana de SkillOpt — não por falha de geração.

### `bench/results_scratch_release_gate.md` — release gate preflight

**Mede:** preflight do release gate scratch v0.5 (não substitui execução com credenciais).

- Goals 15; stacks piloto 5; runs planejados 75. Mínimos: planner válido 90%, scaffold limpo 95%, e2e verde 80%, wall-clock mediano ≤ 8 min, custo médio ≤ $1.00.
- **Ready for live gate: True; blocker count: 0.** 5 stacks presentes, 0 ferramentas faltando.

**Takeaway:** preflight verde (0 blockers); o gate live correspondente roda os 75. É preflight, sem pass-rate de modelo.

### `bench/results_v14_qwen15b_gguf_partial.md` — GGUF 1.5B parcial (issue #46, llama-cpp)

**Mede:** rodada parcial do 1.5B em GGUF Q5_K_M via `llama-cpp-python`, 5 lados, exec sindico PHPUnit. Data 2026-05-31. **Interrompida em 2/12 casos.** Valores são contagem de casos.

| # | case | baseline | cli | cli+sp | cli+ag | cli+sp+ag |
|---|---|---|---|---|---|---|
| 1 | password_strength | fail | fail | fail (parse 0/4) | **PASS 1/3** | fail 3/3 |
| 2 | password_require_symbol | fail | fail | fail (parse 0/4) | fail 3/3 | fail 3/3 |

Resumo: parse_ok schema v1 = **0/8 (0%)**; cli+ag passou **1 de 2 casos rodados**. Wall-clock ~55min/caso (CPU 8t). JSON consolidado **não gerado** (interrompido antes do save).

**Takeaway:** smoke parcial (N=2 casos = "estatística zero", segundo a própria fonte). Schema falha em 1.5B (0/8). cli+ag passa onde cli+sp falha. Não extrapolar.

### `bench/RESULTS_LOCAL_GGUF.md` — GGUF 1.5B via ollama (run_exec, single-shot)

**Mede:** quantizações bartowski GGUF de `Qwen2.5-Coder-1.5B-Instruct` via **ollama**, contra `bench/run_exec.py` (6 casos Python, pytest oculto, **single-shot, sem verify-loop** → mede só o prompt). Hardware Apple M1 8GB.

| Quant | file | RAM | without simplicio | with simplicio | throughput |
|---|---|---|---|---|---|
| Q5_K_M | 1.0 GB | 1.7 GB | 66% (4/6) | 66% (4/6) | ~63 tok/s |
| Q8_0 | 1.5 GB | ~2.2 GB | **83% (5/6)** | 66% (4/6) | ~42 tok/s |

**Takeaway:** Q8_0 ganha em qualidade crua (83% vs 66%); o contrato **não ajudou** esses quants 1.5B single-shot (Q8_0 regrediu 83%→66%, Q5_K_M flat) — modelo pequeno tropeça no prompt mais longo sem o verify-loop. Divergência dos números do README (30%→92%) é esperada: README usa transformers full-precision + verify-loop.

---

## Modelos testados — visão consolidada

Tabela master cruzando todas as rodadas. **"melhor pass-rate visto"** = maior pass-rate
medido em qualquer bench versionado, com suíte/lado anotados. **Cada célula cita a fonte.**
`(regex)` = proxy barato (comprovadamente infla); `(exec)` = execução real (PHPUnit/pytest).

| Modelo | size/quant | backend | melhor pass-rate visto | suíte/lado | fonte |
|---|---|---|---|---|---|
| Qwen2.5-Coder-1.5B | 1.5B | HF local transformers | 92% (with) | regex 156-check | results_comparison |
| Qwen2.5-Coder-1.5B (GGUF Q5_K_M) | 1.5B / Q5_K_M | ollama (M1) | 66% (4/6) | exec Python single-shot | RESULTS_LOCAL_GGUF |
| Qwen2.5-Coder-1.5B (GGUF Q5_K_M) | 1.5B / Q5_K_M | llama-cpp-python | parcial 2/12 (cli+ag passou 1 de 2 rodados) | exec sindico (parcial) | results_v14_qwen15b_gguf_partial |
| Qwen2.5-Coder-1.5B (GGUF Q8_0) | 1.5B / Q8_0 | ollama (M1) | **83% (5/6, without)** | exec Python single-shot | RESULTS_LOCAL_GGUF |
| Qwen2.5-Coder-3B | 3B | HF Inference / local | 94% (with) | regex 156-check | results_comparison |
| qwen2.5-coder:3b | 3B | Ollama | 83% (5/6, with) | exec Python single-shot | results_rust_qwen / results_exec |
| Qwen2.5-Coder-3B | 3B | transformers CPU | 100% parse_ok (schema v1, não é pass-rate) | smoke schema | results_sp_schema_validation |
| Qwen2.5-Coder-7B | 7B | HF Inference | **96% (with)** | regex 156-check | results_comparison / README |
| Qwen2.5-Coder-7B | 7B | Ollama | 92% (with) | regex 156-check | README (local offline) |
| Qwen2.5-Coder-32B | 32B | OpenRouter | 80% (cli+sp+ag, regex); 16% (todos os lados, exec) | regex / exec sindico | results_v13_5side |
| Qwen2.5-7B (general) | 7B | OpenRouter | 100% (with regex; Q4); 25% (exec sindico, rodada README) | regex / 4-quadrant / exec | results_comparison / results_4quadrant_full / README |
| Qwen3-Coder-30B-A3B-Instruct | 30B MoE / 3B ativo | HF router | 91% (cli/cli+sp/cli+ag, exec); 98% (cli+sp, regex) | exec + regex | results_full_qwen3 / results_4side_qwen3 |
| Qwen3-Coder-Next | 80B MoE / 3B ativo | HF router | **100% (cli, regex); 91% (cli+ag, exec); 12/12 modal fan-out** | exec + regex + fan-out | results_full_qwen3 / results_fanout |
| Llama-3.2-1B | 1B | OpenRouter | 0% (ambos os lados, exec); 40%→36% (regex) | exec sindico / regex | README / results_comparison |
| Llama-3.2-3B | 3B | OpenRouter | 88% (cli+ag, regex); 8% (todos os lados, exec) | regex / exec sindico | results_v13_5side |
| Llama-3.1-8B | 8B | OpenRouter | 100% (with, exec sindico rodada README); 88% (with, regex) | exec / regex | README / results_comparison |
| Gemma-3-4b-it | 4B | OpenRouter | 96% (with, regex); 75% (with, exec sindico rodada README) | regex / exec | README / results_v13_5side |
| Gemma-3-4b-it | 4B | — | 0/16 parse_ok (schema v1) | smoke schema | results_sp_schema_validation / results_sp_escalation_v1 |
| Gemma-3-12B | 12B | OpenRouter | 92% (with, regex); 75% (with, exec sindico) | regex / exec | results_comparison / README |
| Gemma-3n-e4B | 4B MoE | OpenRouter | 90% (with, regex); 0% (exec sindico) | regex / exec | results_comparison / README |
| Phi-4 mini | mini | OpenRouter | 73% (with, regex) | regex | results_comparison |
| anthropic/claude-3.5-haiku | — | OpenRouter | 40% (Q4) | 4-quadrant | results_4quadrant_full |
| Claude Opus 4.7 | — | OpenRouter | 98% (with, regex — "old", n/a no re-run) | regex | results_comparison / README |
| GPT-5.5 | — | OpenRouter | 100%→98% (with, regex) | regex | results_comparison / README |
| Kimi K2.6 | — | OpenRouter | 100% (with, regex) | regex | results_comparison / README |
| Gemini 3.5 Flash | — | OpenRouter | 100% (with regex; with exec rodada README); 66% (exec sp-compare) | regex / exec | results_comparison / README / results_sp_compare |
| Qwen 3.7 Max | — | OpenRouter | 100% (with, regex — "old", n/a no re-run) | regex | README |
| deepseek/deepseek-v4-flash | ~37B (proprietary) | OpenRouter | **100% (cli+ag e cli+sp+ag, exec); 91% (cli, exec)** | exec sindico (12 casos) | results_exec_sindico / results_v14_interim |
| deepseek/deepseek-v4-flash | ~37B | OpenRouter | 3/4 parse_ok (schema v1) | smoke schema | results_sp_schema_validation |
| DeepSeek V4 Pro | — | OpenRouter | 96% (with, regex — "old", n/a no re-run) | regex | README |

> **Notas importantes:**
> - **DeepSeek aparece, sim** (V4-Flash e V4-Pro).
> - Há **dois "Qwen 7B"**: **Qwen2.5-Coder-7B** (coder, melhor 96% regex) e **Qwen2.5-7B** (general, melhor 100% regex / 100% Q4, mas só 25% exec sindico na rodada do README). Não confundir.
> - O **mesmo modelo varia muito entre regex (proxy) e exec (real)**: Llama-3.2-3B 88% regex vs 8% exec; Qwen2.5-Coder-32B 80% regex vs 16% exec. O exec é o número honesto.
> - **`Qwen3-Coder-Next` e `deepseek-v4-flash` são os únicos que atingem teto funcional (100%/12-de-12)** via cli+ag ou modal-vote.

---

## Curva de quantização Qwen2.5-Coder-1.5B (issue #46)

Pontos de dado **reais** que existem para o 1.5B em GGUF. Há **duas rodadas distintas**,
ambas single-shot ou parciais — **nenhuma é a curva completa pedida na issue #46.**

### Rodada A — ollama, `bench/run_exec` (6 casos Python, single-shot). Fonte: `bench/RESULTS_LOCAL_GGUF.md`

| Quant | without simplicio | with simplicio | RAM | throughput | status |
|---|---|---|---|---|---|
| Q5_K_M | 66% (4/6) | 66% (4/6) | 1.7 GB | ~63 tok/s | rodado |
| Q8_0 | **83% (5/6)** | 66% (4/6) | ~2.2 GB | ~42 tok/s | rodado |
| Q6_K | n/d | n/d | n/d | n/d | **pendente** |
| Q4_K_M | n/d | n/d | n/d | n/d | **pendente** |

### Rodada B — llama-cpp-python, bench v14 sindico (PHPUnit, 5 lados). Fonte: `bench/results_v14_qwen15b_gguf_partial.md`

Interrompida em **2/12 casos**. Valores são **contagem de casos**, não taxa%.

| # | case | baseline | cli | cli+sp | cli+ag | cli+sp+ag |
|---|---|---|---|---|---|---|
| 1 | password_strength | fail | fail | fail (parse 0/4) | **PASS 1/3** | fail 3/3 |
| 2 | password_require_symbol | fail | fail | fail (parse 0/4) | fail 3/3 | fail 3/3 |

Resumo (contagem): parse_ok schema v1 = **0/8 (0%)**; cli+ag passou **1 de 2 casos rodados**. Wall-clock ~55min/caso (CPU 8t). Q8_0/Q6_K/Q4_K_M nesta rodada llama-cpp: **não rodados**.

### Estado da curva completa (o que a issue #46 pede)

- **Não existe** uma curva única e completa Q4_K_M ↔ Q5_K_M ↔ Q6_K ↔ Q8_0 medida no mesmo bench/backend.
- O que existe: Q5_K_M e Q8_0 em **exec Python single-shot via ollama** (rodada A) + Q5_K_M **parcial 2/12 em exec sindico via llama-cpp** (rodada B).
- **Q6_K e Q4_K_M permanecem `pendente` em todos os backends.**
- A rodada B foi interrompida pelo operador e o JSON consolidado **não foi gerado**. Os blobs `models/*.gguf` são gitignored (só Modelfiles + docs versionados).

> Honestidade: **não há pass-rate% confiável e comparável entre quantizações.** Os únicos %
> reais (66% Q5_K_M, 83% Q8_0) vêm de 6 casos Python single-shot — base estatística mínima.

---

## Lacunas e pendências

- **Curva de quantização GGUF do 1.5B incompleta** (issue #46): Q6_K e Q4_K_M não rodados em nenhum backend; rodada llama-cpp parou em 2/12 sem salvar JSON. Fontes: `results_v14_qwen15b_gguf_partial.md`, `RESULTS_LOCAL_GGUF.md`.
- **v14 dos Qwen locais não fechou:** Qwen2.5-Coder-3B e 1.5B ficaram 0/12 (em andamento) no `results_v14_interim.md`. Só DeepSeek-V4-Flash fechou.
- **regex × exec divergem muito:** a maioria das tabelas grandes (results.md, results_comparison.md, README) é **regex (proxy)**, que comprovadamente infla (results_fanout.md / results_4side_qwen3.md mostram gap +28 a +100pt). Os números honestos são os de exec (sindico/Python), que cobrem menos modelos.
- **exec sindico tem duas rodadas com escopo diferente:** a do `.md` versionado é DeepSeek 12 casos; a do README é 9 modelos × 4 tasks (33%→64%). Não são a mesma medição.
- **4-quadrant wide foi interrompido** (25 de 40 tuplas); qwen-2.5-7b só 5/10 casos, claude-3.5-haiku nunca rodou.
- **Frontier no re-run:** Qwen 3.7 Max, Claude Opus 4.7, DeepSeek V4 Pro deram `n/a` (falha de provider) em `results_comparison.md`; seus números são os "old" do README, não re-medidos.
- **Números de economia de custo do escalonamento (sp_escalation_v1) são MODELADOS (design), não medidos.** O smoke real (Gemma-4B) deu parse 0/16.
- **Evidência de release incompleta:** `results_llm_reduction_summary.md` e `results_scratch_live_gate.md` marcam `release_ready: False` por falta de aprovação humana SkillOpt ≥80% e de baseline real de LLM para codegen.
- **schema v1 falha abaixo de ~3B:** Gemma-4B e Qwen-1.5B em 0% parse_ok; só Qwen-3B-Coder e DeepSeek honram.

---

## Recomendação preliminar de modelo default

Baseada **estritamente** nos pass-rates medidos. Priorizo **exec real (PHPUnit/pytest)**
sobre **regex (proxy)**, porque a própria base mostra o regex inflando.

- **Default geral (melhor qualidade absoluta em execução real):**
  empate técnico no teto entre **`Qwen3-Coder-Next`** (HF router) e **`deepseek/deepseek-v4-flash`** (OpenRouter), ambos **12/12 (100%) no exec sindico** com `cli+ag` (DeepSeek) ou modal-vote fan-out (Coder-Next: 12/12; cli+ag single-call: 91%). Fontes: `results_exec_sindico.md`, `results_full_qwen3.md`, `results_fanout.md`, `results_v14_interim.md`.
  - **`Qwen3-Coder-Next`** é o mais robusto a temperatura (modal-vote 12/12 a temp=0.7, enquanto o 30B-A3B só 5/12) e é Apache-2.0/aberto via HF router; **`deepseek-v4-flash`** atinge 100% já no `cli+ag` single-call (sem 200 subagents), mais barato em chamadas. Escolha: **Coder-Next se prioriza robustez/abertura; DeepSeek-V4-Flash se prioriza custo por chamada.**
  - Caveat: `Qwen3-Coder-30B-A3B-Instruct` parece ótimo no regex (98%) mas **infla** — só 5/12 no funcional modal-vote. Não usar o número regex dele para decidir.

- **Default LOCAL/offline recomendado: `Qwen2.5-Coder-7B`.**
  Melhor coder local com número alto e consistente: **96% regex via HF Inference** e **92% regex via Ollama** (`README.md`, `results_comparison.md`); é o default que README/CHANGELOG documentam para uso local sério. Não há exec sindico do 7B coder versionado — então o 96% é **regex**, tratar como teto otimista.
  - Alternativa local mais leve: **`Qwen2.5-Coder-3B`** (94% regex; 83%/5-de-6 exec Python single-shot via Ollama; 100% parse_ok schema v1).
  - Default offline mínimo (CHANGELOG 0.5.0): o produto já cai para **`Qwen2.5-Coder-1.5B-Instruct-Q5_K_M` GGUF** quando nada está configurado. Honestamente, esse 1.5B GGUF mede só **66% (4/6) single-shot** (`RESULTS_LOCAL_GGUF.md`) e **0% parse_ok de schema**; serve para tarefas triviais offline, frágil para o resto. O README projeta ~88% para o 1.5B, mas isso é a rodada transformers full-precision + verify-loop, **não** o GGUF single-shot.

**Caveats para tarefas full-stack complexas (sindico):**
- O teto de capa (96% do 7B) é **regex**. Em **exec sindico real, modelos médios desabam**: Qwen2.5-Coder-32B fica em **16%**, Llama-3.2-3B em **8%**, e tarefas duras (`base_repository_build_*`, `password_require_symbol`) falham mesmo com 3 tentativas e 200 subagents (teto de capacidade do modelo, não do loop). Fontes: `results_v13_5side.md`, `results_full_qwen3.md`.
- Para sindico/produção, **só `Qwen3-Coder-Next` e `deepseek-v4-flash` fecharam 12/12.** Modelo menor precisa de `cli+ag` (a alavanca que mais recupera casos) e/ou fan-out com modal-vote.
- **Sempre usar `cli+ag`** (verify-loop): no funcional é o único lado que bate o `cli` de forma confiável. `cli+sp` (composição) **não** ajuda single-call e pode regredir (gemma exec 66%→50% com sp em `results_v13_5side.md`).
- Para tarefas mecânicas (CRUD/route/schema no modo scratch), preferir o **codegen determinístico** (executor 100% vs LLM 55.56%, ~95% mais rápido, zero chamada) em vez de gerar via LLM. Fonte: `results_scratch_codegen.md`.

---

## Índice de artefatos

Todos os artefatos rastreados em `bench/` (via `git ls-files`), por família.
**Há artefatos binários versionados:** 16 PDFs, 10 SVGs, 13 PNG/JPG (results_pages), 1 HTML.
Total bench/: 133 arquivos rastreados.

### Documentação de metodologia / roadmap
| Arquivo | Tipo | Conteúdo |
|---|---|---|
| `bench/SIMPLICIO_FLOW_GUIDE.md` | md | Fluxo task/scratch/doctor/skill; providers; o que cada lado injeta |
| `bench/UNIFIED_RUN_ARCHITECTURE.md` | md | RFC do `simplicio-py run` (task/feature/sprint); sides; backends |
| `bench/SCRATCH_MODE_RFC.md` | md | RFC do modo scratch |
| `bench/LLM_REDUCTION_ROADMAP.md` | md | Roadmap de redução de chamadas (issue #33) |
| `bench/SIMPLICIO_PROMPT_ADJUSTMENTS.md` / `SIMPLICIO_PROMPT_ROADMAP.md` | md | Ajustes / roadmap de prompt |

### Bench regex offline (família results.*)
| Arquivo | Tipo | Conteúdo |
|---|---|---|
| `bench/results.md` / `.pdf` / `.html` / `.json` | md/pdf/html/json | Regex 3 modelos OR, 36%→68% (+32pt) |
| `bench/charts/overall.svg` `delta.svg` `by_case.svg` `by_stack.svg` | svg | Gráficos do bench regex |
| `bench/results_all.json` | json | Dataset merge do re-run 17 modelos |
| `bench/results_comparison.md` / `.pdf` | md/pdf | Old vs new, 17 modelos (86%→88% with) |
| `bench/results_pages/*.png` `*.jpg` (page-1..6, all-pages) | png/jpg | Render em imagem do relatório principal |

### Execução real (sindico / Python / v13 / v14)
| Arquivo | Tipo | Conteúdo |
|---|---|---|
| `bench/results_exec.md` / `.json` | md/json | Exec Python 6 casos, qwen2.5-coder:3b 66%→83% |
| `bench/results_exec_sindico.md` / `.pdf` / `.json` | md/pdf/json | Exec PHPUnit, DeepSeek 12 casos (50→91→75→100%) |
| `bench/results_v13_5side.md` / `.pdf` | md/pdf | 5 lados v13, 3 modelos, exec+regex |
| `bench/results_v13_interim.md` / `.pdf` | md/pdf | Snapshot ao vivo v13 (mesmos números) |
| `bench/results_v14_interim.md` / `.pdf` | md/pdf | v14 PHPUnit parcial (só DeepSeek fechou) |
| `bench/results_v14_qwen15b_gguf_partial.md` / `.json` | md/json | 1.5B GGUF Q5_K_M parcial 2/12 (llama-cpp) |
| `bench/RESULTS_LOCAL_GGUF.md` | md | 1.5B GGUF Q5_K_M/Q8_0 via ollama (66%/83%) |

### 4-quadrant (decomposição causal)
| Arquivo | Tipo | Conteúdo |
|---|---|---|
| `bench/results_4quadrant.md` / `.pdf` / `.json` | md/pdf/json | Focused gemma-only, 5 casos (Q4=80%) |
| `bench/results_4quadrant_full.md` / `.pdf` / `.json` | md/pdf/json | 4 modelos n=40 (Q4=70%; +55/+47pt) |
| `bench/results_4quadrant_wide.md` / `.pdf` / `.json` | md/pdf/json | Wide interrompido (25 tuplas; Q4=76%) |
| `bench/charts/4q_*.svg` `4q_wide_*.svg` | svg | Gráficos 4-quadrant |

### Família Qwen3-Coder MoE + fan-out
| Arquivo | Tipo | Conteúdo |
|---|---|---|
| `bench/results_full_qwen3.md` / `.pdf` | md/pdf | Qwen3 exec+regex+fan-out (Coder-Next 100%) |
| `bench/results_4side_qwen3.md` / `.pdf` | md/pdf | Qwen3 4 lados + gap regex×funcional |
| `bench/results_fanout.md` / `.pdf` / `.json` | md/pdf/json | Fan-out N=200 kernel sp (30B-A3B 5/12, Next 12/12) |

### simplicio-prompt (sp) / schema / escalonamento
| Arquivo | Tipo | Conteúdo |
|---|---|---|
| `bench/results_sp_compare.md` / `.pdf` | md/pdf | sp vs baseline (47%→44%; cli ref 75%) |
| `bench/results_sp_v9.md` / `.pdf` | md/pdf | Conteúdo idêntico ao sp_compare nesta sessão |
| `bench/results_sp_schema_validation.md` / `.pdf` | md/pdf | Schema v1: Qwen-3B 100% parse, Gemma-4B 0% |
| `bench/results_sp_schema_smoke_deepseek.json` / `_qwen3b.json` | json | Smoke schema (dados brutos: DeepSeek 3/4, Qwen-3B 4/4) |
| `bench/results_sp_escalation_v1.md` / `.pdf` | md/pdf | Escalonamento 64→100→200 (design+smoke) |

### Família scratch (codegen / recipes / gates / cache)
| Arquivo | Tipo | Conteúdo |
|---|---|---|
| `bench/results_scratch_codegen.md` / `.json` (+ `_llm_baseline.json`) | md/json | 90/90 executores; LLM baseline 55.56% |
| `bench/results_scratch_recipes.md` / `.json` (+ `_llm_baseline.json`) | md/json | 30/50 matched (60%); planos 100% válidos |
| `bench/results_scratch_live_gate.md` / `.json` | md/json | 75/75 e2e verde, 5 stacks |
| `bench/results_scratch_release_gate.md` / `.json` | md/json | Preflight verde, 0 blockers |
| `bench/results_scratch_cache_gate.md` / `.json` | md/json | Cache cold/warm, warm hit-rate 100% (50/0) |
| `bench/results_scratch_live_llm_baseline.md` / `.json` | md/json | Slice de 1 run com codegen desligado (go-gin, 204.7s) |
| `bench/results_llm_reduction_summary.md` / `.json` | md/json | Agregado: 19→6 e 210→0 chamadas |
| `bench/results_static_fixers.md` / `.json` | md/json | Fixers 50/50; retry −40% |

### Rust
| Arquivo | Tipo | Conteúdo |
|---|---|---|
| `bench/results_rust_qwen.md` | md | Crate Rust 8.47x; qwen:3b 66%→83% exec |

### Harnesses / scripts (não são resultados)
| Arquivo | Tipo | Conteúdo |
|---|---|---|
| `bench/run_offline.py` | py | Bench regex (transformers/ollama/OR) |
| `bench/run_exec.py` / `run_exec_sindico.py` | py | Exec Python / exec PHPUnit sindico |
| `bench/run_4quadrant.py` / `run_fanout.py` | py | Bench 4-quadrant / fan-out via SubagentRuntime |
| `bench/run_scratch_*.py` (codegen/recipes/live/release/cache) | py | Gates do modo scratch |
| `bench/run_static_fixers.py` `run_llm_reduction_summary.py` | py | Static fixers / agregador |
| `bench/consolidate_full_report.py` | py | Gera results_full_qwen3.{md,pdf} de exec+regex+fanout |
| `bench/consolidate_v13_report.py` | py | Gera results_v13_5side.{md,pdf} |
| `bench/consolidate_4side_report.py` | py | Gera results_4side_qwen3.{md,pdf} |
| `bench/interim_v13_report.py` `interim_v14_report.py` | py | Parsers de log ao vivo |
| `bench/compare_sp.py` `compare_versions.py` | py | Comparadores sp / old-vs-new |
| `bench/sp_fanout_helper.py` `sp_output_schema.py` | py | Helper de fan-out / schema v1 |
| `bench/exec_cases.py` `sindico_cases.py` | py | Definição de casos |
| `bench/cases.json` `cases_offline.json` | json | Casos do bench |
| `bench/sindico_hidden/*.php` (12 arquivos) | php | Testes PHPUnit ocultos do sindico |

### Este documento
| Arquivo | Tipo | Conteúdo |
|---|---|---|
| `bench/CONSOLIDATED_REPORT.md` | md | Este relatório consolidado (pt-BR) |
| `bench/CONSOLIDATED_REPORT.en.md` | md | Companion em inglês (sumário + tabela master + recomendação) |

---

## Fontes

Arquivos lidos para produzir este relatório (todos em `/home/user/simplicio-dev-cli`):

- `README.md` (seção "Benchmarks", linhas ~24-241 e ~519-656)
- `CHANGELOG.md` (topo, ~120 linhas)
- `bench/SIMPLICIO_FLOW_GUIDE.md`
- `bench/UNIFIED_RUN_ARCHITECTURE.md`
- `bench/results.md`
- `bench/results_exec.md`
- `bench/results_exec_sindico.md`
- `bench/results_v13_5side.md`
- `bench/results_v13_interim.md`
- `bench/results_v14_interim.md`
- `bench/results_v14_qwen15b_gguf_partial.md`
- `bench/RESULTS_LOCAL_GGUF.md`
- `bench/results_4quadrant.md`
- `bench/results_4quadrant_full.md`
- `bench/results_4quadrant_wide.md`
- `bench/results_full_qwen3.md`
- `bench/results_4side_qwen3.md`
- `bench/results_fanout.md`
- `bench/results_comparison.md`
- `bench/results_rust_qwen.md`
- `bench/results_sp_compare.md`
- `bench/results_sp_v9.md`
- `bench/results_sp_schema_validation.md`
- `bench/results_sp_escalation_v1.md`
- `bench/results_sp_schema_smoke_deepseek.json`
- `bench/results_sp_schema_smoke_qwen3b.json`
- `bench/results_llm_reduction_summary.md`
- `bench/results_static_fixers.md`
- `bench/results_scratch_codegen.md`
- `bench/results_scratch_recipes.md`
- `bench/results_scratch_live_gate.md`
- `bench/results_scratch_release_gate.md`
- `bench/results_scratch_cache_gate.md`
- `bench/results_scratch_live_llm_baseline.md`
- `bench/consolidate_full_report.py`
- `bench/consolidate_v13_report.py`
- `bench/consolidate_4side_report.py`
- `git ls-files bench/` (índice de artefatos)

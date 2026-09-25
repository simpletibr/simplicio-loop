# Schema v1 — validação empírica em 2 modelos

Date: **2026-05-30**

Smoke real do `STRUCTURED_OUTPUT=v1` (spec em
[`docs/specs/STRUCTURED_OUTPUT_v1.md`](../docs/specs/STRUCTURED_OUTPUT_v1.md))
em dois modelos contrastantes pra checar se a feature de saída padronizada
funciona na prática.

## Modelos testados

| modelo | tamanho | backend | role |
|---|---|---|---|
| `deepseek/deepseek-v4-flash` | ~37B (proprietary) | OpenRouter API | grande / cloud |
| `Qwen/Qwen2.5-Coder-3B-Instruct` | 3B | transformers local CPU fp32 | pequeno / coder-specialized |

**Por que esses dois**: pra responder "schema funciona só em modelo grande ou em qualquer coder?". Gemma-4B (general-purpose) já tinha mostrado `parse=0/16` em smoke anterior — esperávamos Qwen 3B se comportar parecido. Não foi o caso.

## Setup

Mesmo task em ambos: adicionar `isStrong(string $password): bool` à classe `PasswordPolicy` retornando `strlen >= 12`. Prompt:

```
[sp v1.9 runtime template, 3,907 chars]

---

[USER INPUT - task X]
You are a senior engineer working IN THIS project.
Stack: PHP 8 + composer + PHPUnit.

[GOAL]    Add static isStrong...
[TARGET]  Touch ONLY: src/Core/PasswordPolicy.php (current content shown)
[CONTRACT] isStrong returns true for 12+, false for shorter
[OUTPUT]  Return ONLY the complete updated file. PHP only.

[OUTPUT FORMAT — STRUCTURED v1]
Your entire response MUST be a single JSON object. The JSON object MUST have these exact fields:
  - "artifact": ... (the complete deliverable)
  - "files_changed": [...]
  - "behaviors_added": [...]
  - "expected_oracle_pass": [...]
  - "confidence": 0.0..1.0
  - "concerns": [...]
```

`sp_fanout_escalating()` com tiers proxy (4,8 pra DeepSeek; 4 sequencial pro Qwen no CPU).

## Resultados

| diagnostic | DeepSeek V4 Flash | Qwen 2.5 Coder 3B |
|---|---|---|
| **Backend** | OpenRouter API | transformers local CPU |
| **N invocations** | 4 (cycle 1 OK) | 4 sequenciais |
| **parse_ok / N** | **3 / 4 (75%)** | **4 / 4 (100%)** |
| **parse_failed** | 1 | 0 |
| **behavior groups** | 4 | 4 |
| **modal_count** | 1 | 1 |
| **winner.confidence** | 1.0 | 0.9 |
| **behaviors_added** | (não capturado) | `["App\\Core\\PasswordPolicy::isStrong"]` |
| **expected_oracle_pass** | 2 expectativas | 5 expectativas (assert-shaped) |
| **artifact correto** (returns `strlen >= 12`)? | ✅ | ✅ |
| **Wall-clock total** | 16.4s (4 paralelos) | ~470s (4 sequenciais CPU) |

## Achados-chave

### 1. **Schema funciona em modelo 3B coder-specialized — surpresa positiva**

Expectativa antes do teste: small models (≤7B) parse failure rate alto, baseada no Gemma-4B (`parse=0/16`). **Qwen 2.5 Coder 3B refutou isso com 4/4 (100%) parse_ok.**

A diferença não é tamanho — é especialização:

| modelo | tamanho | tipo | parse_ok rate |
|---|---|---|---|
| Gemma-4B-it | 4B | general | 0/16 (0%) |
| DeepSeek V4 Flash | ~37B | general (chat) | 3/4 (75%) |
| **Qwen 2.5 Coder 3B** | **3B** | **coder-specialized** | **4/4 (100%)** |

**Hipótese**: coder-tuned models seguem instructions estruturadas melhor que general models do mesmo tamanho. Esses modelos viram MUITO JSON/YAML/schemas em training, então a instrução "retorne JSON com esses 6 campos" cai num padrão familiar.

Implicação: schema v1 **não é uma feature apenas pra modelo grande**. Coder models, mesmo pequenos (3B), participam.

### 2. **Qwen 3B preenche os campos de auto-relato com substância real**

A `winner.expected_oracle_pass` do Qwen 3B veio com 5 asserts concretos:

```
"assert(PasswordPolicy::isStrong('a') === false);",
"assert(PasswordPolicy::isStrong('abc') === false);",
"assert(PasswordPolicy::isStrong('abcdefg') === false);",
"assert(PasswordPolicy::isStrong('abcdefg123') === true);",
"assert(PasswordPolicy::isStrong('12345678901234567890') === true);"
```

Não é placeholder. **O modelo articulou expectativas testáveis sobre o próprio output.** Isso é exatamente o que o schema foi desenhado pra capturar — sinal pra detecção de divergência parse-vs-oracle.

DeepSeek também preencheu (2 expectativas), mas Qwen 3B foi mais explícito.

### 3. **Diversifier funciona — gera 4 behavior groups distintos em N=4**

Ambos os modelos produziram 4 grupos de behavior signature únicos. Em N pequeno (4) não tem consenso modal, mas a diversificação está acontecendo. Em N=64+, consenso emergiria.

### 4. **Escalator parou em cycle 1 nos 2 modelos**

`cycles_run=1` em ambos. Oracle (heurística text-only no smoke: tem `isStrong` e `12`?) passou na primeira rodada. Confirma que pra tasks fáceis o gradual escalation economiza calls (não passa pro tier 2).

### 5. **Custo prático**

| modelo | calls | tempo | $$ |
|---|---|---|---|
| DeepSeek V4 Flash | 4 | 16s | < $0.01 OpenRouter |
| Qwen 3B local | 4 | 8 min | $0 (CPU local) + ~6GB RAM |

CPU é viável pra batch pequeno; pra batch real (>100 calls) precisa GPU.

## Limitações do smoke

1. **N=4 é pequeno** pra modal-vote real (precisa N=64+ pra consenso emergir). Validamos só a *honrança do schema*, não a vitória do behavior-modal-vote sobre raw-string-modal.
2. **Oracle do smoke é heurístico** (`'isStrong' in text and '12' in text`), não real PHPUnit. Pra validação completa, precisa rodar o bench v13 com schema ON.
3. **1 task só** (`password_strength`). Pra extrapolar pra todos os 12 cases, precisa do batch completo.
4. **Não testamos modelo medium** (Gemma-4B). O 0/16 vem do bench anterior; um re-teste com schema atual seria útil.

## O que isso desbloqueia

Antes desse smoke, a hipótese era: schema v1 é luxo de modelo grande, modelos ≤7B caem pro fallback raw. **Refutado**.

Implicações práticas:

- **`simplicio task` pode adotar schema v1 mesmo com doer pequeno** (Qwen 2.5 Coder 3B, Coder 7B). O modal-vote-por-behavior melhora pra qualquer coder.
- **`bench/sp_fanout_escalating(structured=True)` pode ser default** pra coder models, com fallback automático nos outros (general models pequenos).
- **Issue de adoção upstream no `simplicio-prompt`** ganha argumento empírico: "funciona em modelo 3B coder, é prática viável".

## Próximo passo recomendado

Re-rodar o **bench v13 completo** (3 modelos × 12 cases × 5 lados) com schema v1 ATIVO no lado sp. Comparar:

- `cli+sp v13 antigo (sem schema, string modal)` vs `cli+sp v14 (com schema, behavior modal)`
- Custo: ~3000 chamadas, ~$3, ~1h
- Hipótese: schema melhora pass-rate dos lados sp em modelos coder porque modal-vote-por-behavior agrega melhor

Comando:
```bash
# todos os 5 lados, schema v1 default no sp via STRUCTURED_OUTPUT_INSTRUCTION
HF_TOKEN=... OPENROUTER_API_KEY=... \
BENCH_SIMPLICIO_PROMPT_PATH=/tmp/prompt_check/prompts/agent-runtime-execution-prompt.md \
BENCH_MODELS="meta-llama/llama-3.2-3b-instruct,google/gemma-3-4b-it,qwen/qwen-2.5-coder-32b-instruct" \
BENCH_INCLUDE_SP=1 BENCH_INCLUDE_AGENTS=1 BENCH_INCLUDE_SP_AG=1 \
BENCH_SP_TIERS="64,100,200" \
python3 bench/run_exec_sindico.py
```

---

## Histórico

- 2026-05-30 — smoke executado pra validar schema v1 antes de comprometer o
  bench full com a feature.

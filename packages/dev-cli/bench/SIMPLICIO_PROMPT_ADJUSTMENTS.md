# Ajustes propostos para `simplicio-prompt` v1.10

> **Status:** rascunho — evidência preliminar do batch v11 em andamento
> (`bench/results_exec_sindico.json`). Re-avaliar quando o batch fechar e o
> output cru dos cases regredidos estiver disponível.
>
> **Repositório-alvo:** `wesleysimplicio/simplicio-prompt`
> **Arquivo-alvo:** `prompts/agent-runtime-execution-prompt.md` (ONE-SHOT, 102 linhas, 3,907 chars)

---

## 1. Evidência empírica

Benchmark de execução real (`bench/run_exec_sindico.py` em `sistema-sindico`,
PHPUnit como juiz, 12 cases × 3 lados — baseline / cli alone / cli + sp
composition).

Resultados parciais (2 de 4 modelos):

| Modelo | baseline | cli alone | cli + sp | Δ cli | Δ cli+sp | cli+sp vs cli |
|---|---|---|---|---|---|---|
| `Qwen/Qwen2.5-Coder-3B-Instruct` | 5/12 (41%) | 9/12 (75%) | 9/12 (75%) | **+34** | **+34** | **0** (paridade) |
| `Qwen/Qwen2.5-Coder-7B-Instruct` | 4/12 (33%) | 8/12 (66%) | 6/12 (50%) | **+33** | **+17** | **−17 pts** ⚠️ |

**Sinal preocupante:** no Coder 7B o template do sp **regrediu 2 cases que
o cli alone resolvia**:

| case | baseline | cli | cli+sp | observação |
|---|---|---|---|---|
| `env_get_int` | fail | **PASS** | fail | cli já tinha resolvido |
| `router_has` | **PASS** | **PASS** | fail | até o baseline (raw goal) passava |

`router_has` é o ponto crítico: é um case onde o **raw goal sozinho já passa**,
o **cli mantém**, e **o sp quebrou**. Isso descarta dificuldade da tarefa como
causa — a degradação vem do wrapping do runtime.

---

## 2. Diagnóstico (hipóteses ordenadas por probabilidade)

### H1 — Context dilution (mais provável)

O template injeta ~3,900 chars (~1k tokens) de runtime **antes** da tarefa
cli. Modelos 7B têm budget de atenção limitado; o sinal do `[USER INPUT - task X]`
compete com o ruído do runtime. A cli alone entrega ~500 chars de 6-layer:
sinal limpo, modelo executa.

**Evidência indireta:** Coder 3B (modelo menor) empata em vez de regredir.
Coder 7B regride mais. Hipótese é consistente com "modelos pequenos não
absorvem template longo de runtime, mas ainda assim seguem o último bloco
estruturado que veem".

### H2 — Output-shape conflict

O cli especifica:

```
[OUTPUT]
Return ONLY the complete updated contents of {target}. PHP only, no prose, no fences.
```

O runtime do sp tem seu próprio protocolo de output ("seu response inteiro
É o artefato; nada antes, nada depois"). As duas regras dizem coisas
semanticamente compatíveis mas **estruturalmente diferentes**. Modelos 7B
tendem a misturar — geram prose curta, ou cerimônia, ou comentário, e o
extrator de PHP do harness recupera código mas a estrutura sai corrompida.

### H3 — Instruction-following literalismo

Modelos 7B tratam **tudo** no prompt como instrução acionável. Em vez de
ler o runtime como "ambiente operacional implícito", tentam performar os
moves do Tuple-Space mesmo no modo ONE-SHOT (apesar do template gritar que
não). Modelos maiores aprendem a hierarquizar (runtime = HOW, X = WHAT).

### H4 — Ruído amostral

`temperature=0` no `run_offline`, mas o router HF às vezes ignora temp e
introduz variância. 2 cases em 12 não exclui essa hipótese, mas
`router_has` regredindo de "baseline já passava" enfraquece.

---

## 3. Patches propostos ao template

### Patch A — Hoist "Compose with simplicio-cli" para o topo

**Justificativa:** quando a cli é injetada como X, o modelo lê 96 linhas
antes de encontrar a única seção que reconhece "X é uma cli contract". A
hierarquia certa é informada cedo, não tardiamente.

**Hoje** (linhas 97–102, último bloco do prompt):

```markdown
### Compose with simplicio-cli

For code tasks that benefit from explicit role/stack, testable success
criteria, and constraints, [`simplicio-cli`]...'s 6-layer contract is
the recommended shape: contract = WHAT the task is; this runtime = HOW
the agent operates. The two compose cleanly.
```

**Proposta** (mover para logo após `## Prompt`, antes do "Match the shape"):

```markdown
## Prompt

You are a senior engineer producing a single deliverable artifact.

**If the user input contains `[GOAL]`, `[TARGET]`, `[CONTRACT]`, or
`[OUTPUT]` blocks (the simplicio-cli 6-layer contract shape), treat
them as ground truth and pass through. The contract specifies WHAT
the task is; this runtime specifies HOW you operate. Where the two
disagree on output shape, the contract's `[OUTPUT]` block wins.**

Your entire response IS the artifact: no preamble, no commentary, ...
```

Custo: ~80 chars. Impacto esperado: resolve H2 explicitamente, alivia H3.

### Patch B — Cortar a seção "Stop conditions" do template ONE-SHOT

**Justificativa:** linhas 79–95 (~700 chars, ~180 tokens) descrevem quando
engajar BATCH mode. No template ONE-SHOT esse texto **nunca dispara** — é
puro overhead que dilui atenção (H1).

**Proposta:** mover para o template BATCH (`agent-runtime-batch.md`), ou
encapsular sob um flag de pre-processamento (`if YOOL_TUPLE_FULL_RUNTIME:`
expand; else: drop). Em ONE-SHOT, manter apenas:

```markdown
### Stop conditions

This is the ONE-SHOT runtime. Do not invoke fan-out, do not decompose
into a tuple graph, do not narrate parallel subagents.
```

Custo: −600 chars (~−15% do template). Impacto esperado: alivia H1.

### Patch C — Reforçar anti-cerimônia no fechamento

**Justificativa:** o template ONE-SHOT termina em "Compose with simplicio-cli"
— tom positivo. As últimas linhas têm peso desproporcional na atenção do
modelo. Modelos 7B se beneficiam de um fechamento imperativo curto.

**Proposta:** adicionar no final do prompt:

```markdown
---

**REMINDER (last instruction wins):** Begin your response with the first
character of the artifact. End with the last character of the artifact.
Nothing before, nothing after. If you find yourself typing "Here", "I'll",
"Let me", "First", or any commentary marker — delete and restart from the
artifact directly.
```

Custo: ~300 chars. Impacto esperado: ataca H2 (output drift) e H3
(literalismo).

### Patch D — Adicionar diretiva de orçamento de wrapper

**Justificativa:** quando o input X já vem estruturado (cli 6-layer), boa
parte do runtime é redundante. Permitir ao caller declarar "X é
auto-estruturado, suprime worked example".

**Proposta:** suportar um marcador no input que enxuga o runtime
dinamicamente:

```markdown
### Self-structured input (opt-in)

If the user input X opens with the marker `[CLI-6LAYER]` (or contains
the literal blocks `[GOAL] ... [CONTRACT] ... [OUTPUT]`), suppress the
Worked Example and Honor Host Code sections — they're already implied
by the contract's `[CONSTRAINTS]` block. Emit the artifact directly per
the contract's `[OUTPUT]` shape.
```

E o `bench/run_exec_sindico.py` (no nosso lado) já está estruturado pra
emitir esse marker. Custo: ~250 chars. Impacto: combina A + C.

---

## 4. Como validar os patches

1. Aplicar A + B + C em `prompts/agent-runtime-execution-prompt.md` de uma
   versão `1.10-rc.1` do simplicio-prompt.
2. Re-rodar `bench/run_exec_sindico.py` com os 4 modelos, comparando:
   - cli alone (controle, não muda)
   - cli + sp v1.9 (atual, dados deste batch)
   - cli + sp v1.10-rc.1 (template patched)
3. Critério de sucesso: cli+sp v1.10 **não regride nenhum case** que
   cli alone resolve. Stretch: cli+sp v1.10 **ganha cases** que cli alone
   não resolve (sinal de que o runtime adiciona valor de verdade em
   single-call, não só em fan-out).
4. Re-rodar `bench/run_fanout.py` N=200 com v1.10 pra garantir que os
   cortes em B não quebraram o multi-shot.

---

## 5. Evidência cara que falta (pendente do batch fechar)

Quando o batch v11 fechar (4 modelos × 12 cases × 3 lados), abrir
`bench/results_exec_sindico.json` e extrair:

- Para os cases regredidos (`env_get_int`, `router_has` no 7B):
  - Primeiras 30 linhas do output cru de `cli` vs `cli+sp`.
  - `tail` do PHPUnit em cada lado (mensagem de erro real).
- Para o batch inteiro:
  - Tokens prompt / completion / total por lado, por modelo.
  - Latência p50 / p95 por lado.
  - Diferencial de custo $ (sp vs cli) em chamada única.

Se `cli+sp` em `router_has` gerar **prose antes do PHP** → H2 confirmada,
patches A + C são suficientes.

Se gerar **PHP estruturalmente válido mas semanticamente errado** → H1
confirmada, patch B vira prioritário.

Se o output cru for **idêntico ao do cli** mas o phpunit ainda falhar →
H4 (ruído de endpoint), patches viram opcionais e dobramos N pra mitigar
variância.

---

## 6. Decisão de release

- v1.10 sai como **patch** se A + C bastarem (compatível, só fortalece).
- v1.10 sai como **minor** se B for incluído (mudança comportamental no
  modo ONE-SHOT — texto removido pode mudar saída em casos edge).
- A + B + C juntos justificam **v2.0.0** se o resultado bench virar
  monotônico (cli+sp ≥ cli em todos os modelos testados, sem regressão).

Issue gêmea no `simplicio-cli`: bumpar o floor para `simplicio-prompt>=1.10`
no `pyproject.toml` quando publicado.

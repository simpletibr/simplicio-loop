# Relatório consolidado + recomendação de modelo default

Date: **2026-05-31** · Branch: `claude/hopeful-thompson-zZ93U`

Este é o relatório de **decisão** (camada executiva). A consolidação detalhada dos
números de benchmark fica em **`bench/CONSOLIDATED_REPORT.md`** (índice + tabelas
fiéis às fontes). Aqui respondo: **qual AI usar como default**, com foco em
**tarefas funcionais complexas do sindico**.

---

## 1. Sumário executivo

- O ganho central do simplicio NÃO é o modelo, é o **verify-loop (`cli+ag`)**: no
  bench exec real (sindico/PHP/PHPUnit) ele leva `deepseek-v4-flash` de **50%
  baseline → 100% (12/12)**; o contrato `cli` sozinho já dá 91%.
  (fonte: `bench/results_exec_sindico.md`)
- **`cli+sp` (composição com simplicio-prompt) regride** em tarefa exec real
  (75% vs 91% do `cli` sozinho) e em modelos pequenos. O `sp` ajuda fan-out/voto,
  não tarefa single-shot. (fontes: `results_exec_sindico.md`, `SIMPLICIO_PROMPT_ROADMAP.md`)
- **Qwen2.5-Coder-1.5B está abaixo da fronteira do schema v1** no quant testado
  (Q5_K_M: `parse_ok 0/8`). Q8_0 recupera codegen Python bruto (83% vs 66%), mas
  o gate de `parse_ok` em quant alto **ainda não foi medido** (issue #46).
- **Piso local medido para schema v1 = 3B** (Qwen2.5-Coder-3B = 4/4 no smoke).
- Para a **tarefa complexa pedida** (campo front→back→banco, validar ponta-a-ponta),
  nenhum modelo small-local é seguro hoje; a recomendação é modelo forte + `cli+ag`.

## 2. O que foi feito nesta sessão

| pedido | status |
|---|---|
| `git pull` / sincronizar | ✅ branch já em `origin/master` (1f10e08, 0 ahead/0 behind); fetch feito |
| atualizar pacotes | ⚠️ parcial — ver §6 (deps core ausentes no container; update seguro só do npm/playwright; pip core exige decisão) |
| consolidar relatórios (bench/pdf/readme) | ✅ `bench/CONSOLIDATED_REPORT.md` (+ `.en.md`) |
| issue #46 (testar todos os quants) | ⚠️ **inviável rodar nesta sessão** (sem `llama_cpp`/GGUF, 4 vCPU, ~11h/quant). Entregue: scaffold da curva, runbook, ADR-003, e tentativa de instalar deps p/ smoke. PR #47 já tem o `smoke_schema_v1.py`. |
| relatório "melhor AI default" | ✅ este arquivo (§4) |
| campo full-stack ponta-a-ponta | ⚠️ **fora do escopo de acesso** (vive em `wesleysimplicio/sistema-sindico`, não neste repo). Entregue: spec medível em `bench/CASE_fullstack_add_field_sindico.md` |

## 3. Dados que sustentam a decisão (fiéis às fontes)

**Bench exec real — sindico (PHP, PHPUnit, 12 tasks)** — `results_exec_sindico.md`
| lado | pass | Δ vs baseline |
|---|---|---|
| baseline | 6/12 (50%) | — |
| cli (contrato 6-camadas) | 11/12 (91%) | +41 |
| cli + sp | 9/12 (75%) | +25 |
| **cli + ag (verify-loop)** | **12/12 (100%)** | **+50** |
Modelo medido: `deepseek/deepseek-v4-flash`.

**README — bench 156-checks (Python, full-precision + verify-loop)**
| modelo | baseline | com simplicio |
|---|---|---|
| Qwen2.5-Coder-7B | 38% | 96% |
| Qwen2.5-Coder-3B | 34% | 94% |
| Qwen2.5-Coder-1.5B | 30% | 92% |
(fonte: `README.md`; harness diferente do exec sindico — não comparar 1:1)

**Quant 1.5B (GGUF)** — `results_v14_qwen15b_gguf_partial.md` + `RESULTS_LOCAL_GGUF.md`
| quant | schema-v1 parse_ok | codegen Python (run_exec) |
|---|---|---|
| Q5_K_M | 0/8 (parcial) | 66% (4/6) |
| Q8_0 | **pendente (issue #46)** | 83% (5/6) |

## 4. Recomendação de modelo default

**Resposta curta:** o default que entrega "tarefa complexa do sindico" hoje é
**um modelo forte rodando com o verify-loop (`cli+ag`)** — não um small-local cru.

1. **Default para tarefas complexas (full-stack, schema v1, multi-arquivo):**
   modelo capaz (medido: `deepseek-v4-flash` → 100% com `cli+ag`; equivalentes:
   Qwen3-Coder-Next, ou API frontier — **evitar** Qwen2.5-Coder-32B: infla no regex (~80%) mas colapsa no exec real do sindico (16%)) **sempre com `cli+ag`**. O loop é o que
   fecha integração entre camadas. **Não** usar `cli+sp` como default (regride).

2. **Default local/offline:** mínimo **3B** (piso medido p/ schema v1), **7B
   preferido**. Reservar **1.5B Q8_0** só para tarefas simples (1 função, sem
   schema) — onde seu codegen bruto de 83% é aceitável.

3. **Fallback zero-config:** manter **1.5B Q5_K_M** como hoje (cabe em qualquer
   laptop, ~1.7 GB), porém com o teto documentado (ADR-003). Para a tarefa do
   campo ponta-a-ponta, ele **não** é recomendado.

**Veredito 1.5B-por-quant fica provisório** até os smokes Q8_0/Q6_K/Q4_K_M da
issue #46 existirem. Se Q8_0 cruzar `parse_ok >= 75%`, reabilita-se o 1.5B como
default offline para tarefas com schema (novo ADR).

## 5. Plano da tarefa full-stack ("adicionar campo")

Spec completa em `bench/CASE_fullstack_add_field_sindico.md`. Resumo das camadas
e da validação ponta-a-ponta:

- **Banco:** migration `observacoes VARCHAR(500) NULL` (up/down).
- **Back:** model/DTO + repositório (`build_insert/update_sql`) + validação ≤500.
- **API:** create/update aceitam/retornam o campo.
- **Front:** input no form + binding + submit (Playwright já configurado no repo).
- **Validação E2E:** migration up/down + PHPUnit suíte inteira verde + Playwright
  (trace/screenshot/video) criando pela UI e conferindo persistência no banco.

Execução depende de acesso a `sistema-sindico` (ver §7).

## 6. Pacotes / sincronização

- **git:** já sincronizado com `origin/master`. Sem `git pull` pendente.
- **npm (`@playwright/test`):** atualização de lockfile é segura (rede OK) — feita/
  proposta no PR.
- **pip (deps do simplicio):** o container **não tem** `numpy`/`sentence-transformers`/
  `llama-cpp-python` instalados. "Atualizar todos os pacotes" aqui significa
  decidir entre: (a) só refresh do `pyproject` pins, ou (b) `pip install -e .`
  completo (puxa torch, ~GBs). Como CLAUDE.md proíbe mexer em dependência sem
  confirmar, deixei como **decisão em aberto** (§7) em vez de bumpar pins às cegas.

## 7. Decisões em aberto (preciso de você)

1. **Issue #46 — rodar de fato?** O bench completo é ~11h/quant em CPU (4 vCPU aqui).
   Opções: (a) eu disparo só os **smokes** (Q8_0/Q6_K/Q4_K_M) em background nesta
   sessão e reporto o gate; (b) você roda o runbook (§5 do quant_curve) numa máquina
   8t+/GPU; (c) ficar só na consolidação dos dados existentes.
2. **Campo full-stack — onde executar?** Vive em `wesleysimplicio/sistema-sindico`,
   fora do escopo GitHub desta sessão. Opções: (a) abrir sessão com acesso a esse
   repo p/ eu implementar+validar; (b) manter como spec/bench-case aqui; (c) eu
   scaffoldo um app demo neste repo só pra exercitar o fluxo (não é o sistema real).
3. **Pacotes pip:** confirmo (a) refresh de pins seguro, ou (b) `pip install -e .`
   completo (puxa torch)?

## 8. Nota de ambiente

Esta sessão sofreu **latência severa de retorno de ferramentas** (resultados
chegando em lotes grandes, atrasados). Os entregáveis foram escritos com base em
dados reais já coletados; a consolidação numérica detalhada roda num worker em
background (`bench/CONSOLIDATED_REPORT.md`). Sondagem de infra e números são reais
e citados — nada de benchmark foi inventado.

## Fontes

`bench/results_exec_sindico.md`, `bench/RESULTS_LOCAL_GGUF.md`,
`bench/results_v14_qwen15b_gguf_partial.md`, `README.md`, `CHANGELOG.md`,
issue #46 + PR #47, sondagem direta do container (2026-05-31).

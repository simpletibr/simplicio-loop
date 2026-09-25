# Roadmap de melhoria — `simplicio-prompt` v1.10 → v2.0

> **Status:** rascunho estratégico. Base empírica em
> `bench/results_full_qwen3.md` + `bench/SIMPLICIO_PROMPT_ADJUSTMENTS.md`.
> **Repositório-alvo:** `wesleysimplicio/simplicio-prompt`
> **Repositório de validação:** `wesleysimplicio/simplicio-dev-cli` (este)
> **Premissa central:** sp não vai ganhar single-call competindo com cli — ele
> ganha em fan-out diversificado com agregação inteligente. O roadmap reposiciona
> o produto pra arena onde tem chão pra crescer.

---

## 1. Diagnóstico — onde o sp v1.9 está hoje

Evidência consolidada em 4 modelos × 3 benches (exec single-call, regex,
fan-out N=200):

| Cenário | Sinal |
|---|---|
| `cli` vs `cli + sp` (single-call exec, 4 modelos) | **empate ou regressão** em todos. Sp adiciona ~1k tokens sem ganho de pass-rate |
| `cli + sp` em modelos ≤ 8B (single-call) | **regride 2 cases** em Qwen2.5-Coder-7B (`router_has`, `env_get_int`) e Llama-8B |
| `cli + sp` em modelo grande (Qwen 3.7 Max) | paridade 12/12 com cli — overhead puro |
| `cli (fan-out N=200, modal-vote)` em Coder-Next | **12/12 PHPUnit verde** — único cenário onde sp brilha |
| `cli (fan-out N=200, modal-vote)` em 30B-A3B | **5/12** (uniq=1 em 4 cases → 200 subagents convergem no mesmo erro) |

**Conclusões duras:**

1. **Single-call sp está morto.** O template wraping não pulla ranking. 4 modelos
   × 12 cases × 3 lados é amostra suficiente pra dizer "não vence".
2. **Fan-out modal-vote ganha quando o pool diversifica.** Coder-Next produz
   uniq alto (média 25/200) → modal captura consenso real. 30B-A3B colapsa
   em uniq=1 → modal só repete viés.
3. **O ROI do runtime sp está bloqueado por dois gargalos arquiteturais:**
   prompts idênticos (variância só por temperatura) e agregação só por código
   (modal-vote ignora o que phpunit/regex está dizendo sobre comportamento).

---

## 2. Visão — o produto sp v2.0

Sp deixa de ser "wrapper de prompt que adiciona Tuple-Space ao input" e
passa a ser **"runtime de fan-out diversificado com agregação por
comportamento"**. Três compromissos:

1. **Subagents são personas, não cópias.** N=200 chamadas com 200
   framings/perspectivas/restrições diferentes geradas determinísticamente
   a partir da mesma task X.
2. **Agregação vota em comportamentos, não em strings.** Se phpunit/regex
   sabe o que cada candidato faz, o vote é "qual subset comportamental
   tem consenso?", não "qual código é mais frequente?".
3. **Adversarial é built-in.** Metade do pool gera, metade critica. Resultado
   final = sobrevivente da arena, não vencedor de votação cega.

---

## 3. Roadmap em 4 fases

### Fase 0 — Higiene + repositioning (1 semana, low risk)

**Objetivo:** parar o sangramento (sp deixar de regredir vs cli em ≤8B) +
narrativa pública alinhada com a evidência.

**Mudanças:**

- **Template (`prompts/agent-runtime-execution-prompt.md`)** — aplicar os 4
  patches do `bench/SIMPLICIO_PROMPT_ADJUSTMENTS.md`:
  - A. Hoist do "Compose with simplicio-cli" pro topo
  - B. Drop da seção "Stop conditions" no template ONE-SHOT
  - C. Anti-cerimônia no fechamento (reminder imperativo nas últimas linhas)
  - D. Marker `[CLI-6LAYER]` pra suprimir worked-example quando X já vem estruturado
- **Docs (`README.md` do sp)** — reescrever a seção "Why" com:
  - Remover claim de ganho em single-call (não tem dado)
  - Citar o resultado fan-out modal Coder-Next 12/12 como diferencial real
  - Posicionar sp como "runtime de fan-out", cli como "contrato de tarefa"; usar `simplicio-dev-cli` como referência arquitetural
- **CHANGELOG** entrada `v1.10.0`: "ONE-SHOT template hygiene; runtime
  positioning clarified; no behavioral change for fan-out users."

**Métrica de sucesso:**

Re-rodar `bench/run_exec_sindico.py` com 4 modelos × 12 cases × 3 lados:
- Critério mínimo: `cli + sp v1.10` **não regride nenhum case** vs cli alone (versus 1-2 regressões atuais)
- Stretch: paridade ou +1 case em modelos ≥7B

**Esforço:** 2 dias de template + 1 dia de docs + 1 dia de re-bench.

---

### Fase 1 — Diverse-prompt fan-out (2-3 semanas, médio risk)

**Objetivo:** elevar `cli (fan-out N=200, modal)` para **+3 a +5 cases vs cli single-call** em qualquer modelo testado — não só Coder-Next.

**Problema empírico que ataca:** 30B-A3B colapsando em uniq=1 (200 outputs
idênticos) em 4 cases do nosso bench. O modelo tem variância de saída, mas
**não tem variância de plano** porque os 200 prompts são bit-idênticos.

**Mudanças no kernel:**

- Adicionar `kernel.diversifier.PromptDiversifier` que recebe um prompt-base
  e gera N variantes através de transformações determinísticas:
  - 4 framings de papel (senior engineer / cautious reviewer / refactoring expert / test-first author)
  - 3 ênfases (security-first / readability-first / performance-first)
  - 3 perspectivas de host code (preserve existing / propose alternative / minimal patch)
  - Combinações geram ~36 variantes únicas; pra N=200, repete com seeds diferentes
- `SubagentRuntime.run(diversify=True)` aciona o pipeline novo; default desligado pra preservar comportamento atual (semver-safe minor bump)
- Cada variante recebe um marker `[PERSONA: <slug>]` injetado antes do user input X, para que o modelo se alinhe ao papel

**Mudanças no template:**

- Adicionar seção "Persona injection" reconhecendo `[PERSONA: ...]` como
  modulador local — sem mudar o output shape (X continua mandando)
- Documentar que a persona é instrumento de diversificação, não definição de saída

**Métrica de sucesso:**

Re-rodar `bench/run_fanout.py` N=200 nos 2 Coder MoE + adicionar um modelo
sensível (Qwen2.5-Coder-7B):

- **uniq médio por case sobe de ~13 para ≥40** (medida direta de diversificação)
- **modal-vote PHPUnit no 30B-A3B sobe de 5/12 para ≥9/12** (quebra os colapsos uniq=1)
- **modal-vote do Coder-Next mantém 12/12** (não pode regredir)
- **Custo: +0 tokens/call** (diversifier só muda CONTEÚDO do prompt, não tamanho)

**Esforço:** 5 dias kernel + 2 dias template + 3 dias re-bench + relatório.

---

### Fase 2 — Behavior consensus em vez de code consensus (3-4 semanas, alto valor)

**Objetivo:** fan-out passa a ganhar nos cases onde modal-vote atual perde
porque 199 candidatos estão errados do mesmo jeito (`admin_only_allowed_roles`,
`rate_limit_bucket_key` no 30B-A3B).

**Problema empírico que ataca:** modal-vote escolhe o código mais frequente.
Quando o modelo tem viés sistêmico contra o ground truth, fan-out só amplifica.
Precisa de outro sinal — o resultado do oracle (phpunit/regex) — pra desempatar.

**Mudanças no kernel:**

- Adicionar `kernel.aggregator.BehaviorConsensus` que recebe:
  - N candidatos (código gerado)
  - Função `oracle(code) -> dict[str, bool]` (mapping test_name → passed)
  - Retorna o candidato cujo perfil de pass/fail tem **maior consenso entre os outros candidatos no SUBSET de tests onde a maioria passa**
- `SubagentRuntime.run(..., aggregator="behavior")` aciona o pipeline novo
- Para casos onde NENHUM candidato passa todos os testes, retorna candidato
  com maior cobertura parcial + lista dos testes ainda quebrados (input pro
  próximo round, se houver)

**Pré-requisito de produto:**

A simplicio-prompt v2.0 publica uma API de **integração de oracle**: o usuário
plugga o test runner (phpunit, pytest, jest, dotnet test, regex). O kernel
chama o oracle por candidato e usa o sinal para a agregação.

**Mudanças no template:**

- Adicionar seção "Oracle-driven aggregation" explicando ao desenvolvedor
  como rodar o oracle entre as N gerações.
- Sem mudança no prompt do subagent — ele continua emitindo só o artefato.

**Métrica de sucesso:**

- **Cases onde modal cego falhava por uniq baixo** (`admin_only_allowed_roles`, `rate_limit_bucket_key`, `base_repository_build_where_sql`, `router_has` no 30B-A3B — 4 cases) → behavior consensus recupera ≥2
- **Modal-vote 30B-A3B sobe de 9/12 (pós-Fase 1) para ≥11/12**
- **Latência por bench job aumenta ≤30%** (oracle eval por candidato)

**Esforço:** 7-10 dias kernel + 3 dias docs + 5 dias re-bench.

---

### Fase 3 — Adversarial pairs (3 semanas, diferenciador de produto)

**Objetivo:** sp deixa de ser apenas "rodar N vezes" e vira **"arena": metade
gera, metade crítica, sobrevivente fica".** Defende contra o caso "modelo
chuta certo por acaso" que vimos no Coder 7B (cli passa, cli+sp regride).

**Problema empírico que ataca:** modelos de tamanho médio às vezes acertam
sem entender — o mesmo prompt em temp=0 acerta, em temp=0.7 erra. Não é
falta de variância, é falta de **pressão**. Crítico força justificativa.

**Mudanças no kernel:**

- Adicionar `kernel.arena.AdversarialPairs` que opera em N=2M (M=100 attempts
  + M=100 critics):
  - M attempts geram com `[ROLE: implementer]`
  - M critics avaliam cada attempt com `[ROLE: senior reviewer]`, emitindo:
    - score (0-10)
    - lista de violações da contract criteria
    - lista de falsos-positivos esperados em test runtime
  - Cada attempt recebe agregado de scores + violations
  - Vencedor = attempt com maior score *e* zero violations críticas
- Quando combinado com Fase 2 (behavior consensus): vencedor adversarial
  passa pelo oracle. Vencedor adversarial + oracle = duplo gate.

**Mudanças no template:**

- Nova seção "Critic role contract" definindo o protocolo de saída do crítico
  (JSON: `{score, violations: [...], runtime_concerns: [...]}`)
- ONE-SHOT continua intocado — adversarial só é acionado via API explícita

**Métrica de sucesso:**

- **Cases onde sp regrediu vs cli em modelos médios** (`router_has`,
  `env_get_int` no Coder 7B; `password_require_symbol`, `bugfix_password_policy_lowercase` no Coder-Next) → adversarial recupera ≥3
- **Não introduz regressão nos cases já verdes** (zero new failures)
- **Custo: 2x calls vs fan-out puro**, mas custo $ acompanha (M=100+100 vs
  N=200, mesmo número de invocações; só muda o que cada lane faz)

**Esforço:** 8 dias kernel + 3 dias template + 4 dias re-bench.

---

## 4. Roadmap consolidado

| Fase | Semanas | Métrica-âncora | Risco |
|---|---|---|---|
| **0 — Higiene** | 1 | Zero regressão vs cli em single-call ≤8B | Baixo |
| **1 — Diverse-prompt** | 2-3 | Modal 30B-A3B: 5/12 → ≥9/12 | Médio |
| **2 — Behavior consensus** | 3-4 | Modal 30B-A3B: ≥9/12 → ≥11/12 | Médio-alto |
| **3 — Adversarial pairs** | 3 | Recovery em ≥3 cases que cli+sp regrediu | Médio |
| **Total entrega v2.0** | ~10 | Modal-vote ≥11/12 nos 2 modelos × 12 cases | — |

Cada fase publica um release semver — v1.10 (higiene), v1.11 (diverse-prompt),
v1.12 (behavior consensus), v2.0 (adversarial pairs + breaking API consolidation).

---

## 5. Métricas que decidem se a fase entrega

Tracking obrigatório em cada release, gravados em `bench/results_*.json`:

- **functional pass rate per attempt** (oracle real, não regex)
- **functional pass rate modal-vote** (a métrica que importa)
- **uniq outputs / N** (sinal de saúde da diversificação)
- **avg attempts to first pass** (quanto subagent foi desperdiçado)
- **tokens/call** (custo)
- **wall-clock end-to-end** (latência)
- **regex vs functional gap** (anti-vaidade — manter alto significa estamos enganando)

Cada fase só é declarada entregue quando os 7 sinais movem na direção certa,
não 1-2 cherry-picked.

---

## 6. Anti-padrões — o que NÃO fazer

- **Manter sp como wrapper de single-call.** Já provamos que não funciona.
  Cada hora investida em otimizar isso é uma hora não investida em fan-out.
- **Headline em regex isolado.** O dado mais forte do batch atual é
  "regex 100% / phpunit 0% em 6 cases". Vender sp com regex score = perda
  de credibilidade na primeira pergunta técnica.
- **Adicionar mais texto ao template.** Cada token adicional é um quartil
  a mais de modelos pequenos perdidos. O template ONE-SHOT precisa
  ENCOLHER, não crescer.
- **Subagent count alto como métrica de venda.** "N=200" não é vantagem
  se uniq=1 e fn=0. Vender capacidade de orquestração, não cardinalidade.
- **Comprometer com latência baixa antes da Fase 2.** Oracle eval por
  candidato vai custar. Trade explícito: 30% mais latência por +6 cases
  no modal-vote é trade ótimo.

---

## 7. Open questions (precisam decisão antes de Fase 1)

1. **Oracle API: opt-in ou built-in?** Plugar phpunit/pytest/jest é trabalho
   de integração não-trivial. Vale shippar Fase 2 sem oracle (modal-vote
   melhorado) e deixar oracle pra v2.0?
2. **Persona templates: hardcoded ou configuráveis?** Hardcoded é mais
   simples, mas perde fit por stack (PHP/Python/Rust precisam de personas
   diferentes). Configurável adiciona surface API.
3. **Adversarial: gerar/criticar com o MESMO modelo ou modelos diferentes?**
   Mesmo modelo é mais barato e simpler; diferentes têm mais robustez teórica
   mas adiciona complexidade de provider routing.
4. **Compatibilidade v1.x:** quebrar `SubagentRuntime.run()` em v2.0 ou
   manter como deprecated path? Decisão depende de quantos users externos
   já dependem da assinatura atual.

---

## 8. Critério de release v2.0

Sp pode chamar de "v2.0 — Real fan-out runtime" quando o bench público,
mesmo formato dos relatórios atuais (`bench/results_full_qwen3.pdf`),
mostrar:

- `cli + sp v2.0 (fan-out modal)` > `cli single-call` em **pelo menos 3 dos
  4 modelos testados**, sem regredir nenhum
- **Gap regex-vs-functional ≤10%** nos casos onde sp ganha (sinal de que
  estamos ganhando porque o código realmente funciona, não porque parece
  funcionar)
- Custo total por task (tokens × $) menor que 5x cli single-call (sustentável
  pra produção, não só lab)

Esses três simultaneamente. Não é negociável "pega 2 de 3".

---

## 9. Por onde começar agora

1. Aplicar Fase 0 patches no template em PR isolado no repo `simplicio-prompt`
2. Bumpar versão pra v1.10.0-rc.1 e publicar no test.pypi pra rodar bench
3. Re-rodar o `bench/run_exec_sindico.py` com 4 modelos do bench original
   + os 2 Qwen3 MoE — confirmar critério da Fase 0 (zero regressão)
4. Se passou: tag v1.10.0 final, abrir tracking issue no `simplicio-cli`
   pra bumpar floor, e começar `kernel.diversifier` da Fase 1
5. Se não passou: revisitar diagnóstico antes de andar pra Fase 1 — fase
   posterior assume hygiene como base

---

## Histórico

- 2026-05-29 — roadmap inicial criado a partir do batch consolidado
  `bench/results_full_qwen3.{md,pdf}` (3 benches × 2 modelos × 4-5 sides).

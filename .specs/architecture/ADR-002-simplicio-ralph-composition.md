# ADR-002: Compor ralph-loop com simplicio-cli em vez de inchar o CLI

---

## Status

`Aceito`

---

## Data

2026-05-26

---

## Autores

- Wesley Simplicio

---

## Contexto

O `simplicio-cli` é um CLI Python pequeno (~10 KB de código) cujo diferencial mensurado é o **prompt afiado**: injeção de `precedent` extraído do repo (`precedent.py`) + `skill_router` que escolhe skill por goal (`skill_router.py`) + benchmark próprio (`bench/results.md`) que mostrou ganho real em tiny models (35% → 74%).

Hoje o CLI expõe um único comando de execução: `simplicio task <goal> --target <path>` com loop interno de 3 tentativas (`pipeline.py`, `MAX_ATTEMPTS = 3`) e apply-de-diff em stub (linha 11: `# PLUG: extract diff -> git apply`).

Surgiu a pergunta: para virar um **agent autônomo de cobertura ampla** (igual Claude Code / Codex `/goal` / Copilot autopilot), deveríamos:

1. **Inchar o `simplicio-cli`** — adicionar `simplicio refactor`, `simplicio review`, `simplicio plan`, `simplicio debug`, `simplicio doc`, `simplicio migrate`, gerenciamento de loop infinito, apply automático, gates de lint/test/e2e, evidência Playwright, etc., transformando o CLI num agent end-to-end?
2. **Compor com `ralph-loop`** — manter `simplicio` focado em code-gen com precedent, e usar `ralph-loop` (padrão já documentado em `.agents/ralph-loop.agent.md`) como **orquestrador externo** que decide quando chamar `simplicio task` no passo `execute`?

Restrições em jogo:

- Time pequeno (1 dev). Bandwidth de manutenção limitada.
- Diferencial **medido** do simplicio é o prompt, não a orquestração.
- Já existe um ecossistema maduro de orquestradores (Claude Code, Codex CLI, Copilot CLI, Cursor, Aider) que implementam Ralph Loop nativo.
- Reinventar orquestração = competir contra ferramentas com ordens de magnitude mais investimento (Anthropic, OpenAI, GitHub, Cursor).

Tocou também a regra de `~/.claude/CLAUDE.md` seção 2: "solução mais simples que funciona; sem abstrações pra uso único".

---

## Decisão

**Adotamos composição.** O `simplicio-cli` permanece focado em **code-gen com precedent + skill_router**. A autonomia (loop, gates, evidência, exit dual gate, commit, PR) fica a cargo do **ralph-loop pattern**, invocado pelo agent `.agents/simplicio-ralph.agent.md`.

Escopo:

- **Entra:** agent `.agents/simplicio-ralph.agent.md` que define como ralph-loop chama `simplicio task` no passo `execute`. Roteamento por tipo de task: code-gen → simplicio; refactor amplo / análise / review / arquitetura → outras ferramentas.
- **Não entra:** novos subcomandos no CLI (`simplicio review`, `simplicio plan`, etc.). Não entra modificação em `simplicio/pipeline.py` para virar agent end-to-end.
- **Aditivo:** zero alteração em `simplicio/*.py`, `bench/`, `README.md`. Benchmarks publicados permanecem reproduzíveis.

Como aplicar:

1. Tarefa code-gen com target claro e AC mensurável → agent invoca `simplicio task`.
2. Tarefa fora desse perfil → ralph-loop usa edit direto, `architect.agent.md`, `reviewer.agent.md` ou outro agent apropriado.
3. Composição é **stateless** — ralph orquestra, simplicio gera, cada um isolado.

Dono / mantenedor: Wesley Simplicio.

---

## Consequências

### Positivas (+)

- **Foco preservado.** `simplicio-cli` continua sendo o CLI de prompt + precedent + bench. Diferencial intacto.
- **Cobertura maior sem inchaço.** Tasks fora do code-gen (review, refactor amplo, análise, arquitetura) ficam com ferramentas que já fazem isso bem — não precisa reimplementar.
- **Trocabilidade.** Substituir `simplicio` por `aider`, `copilot`, edit direto, ou outro gerador é uma linha no agent spec. Substituir `ralph-loop` por `santa-loop` / `/goal` / autopilot idem.
- **Benchmark estável.** Como não mexemos no CLI, `bench/results.md` permanece reproduzível com as mesmas versões.
- **Adesão ao padrão `AGENTS.md`** — agent spec é lido por Claude Code, Codex, Copilot, Simplicio Agent, OpenClaw, Cursor, Aider igual.
- **Manutenção barata.** Spec markdown é texto; não há código novo de orquestração pra manter.

### Negativas (-)

- **Cobertura depende do orquestrador externo.** Sem Claude Code / Codex / Copilot / Cursor / Aider rodando o agent, `simplicio task` continua sendo um CLI de uma só chamada com 3 tentativas. Quem quer "agent autônomo" precisa de um desses.
- **Curva de aprendizado dupla.** Usuário precisa entender ralph-loop (orquestração) **e** simplicio (geração) para usar bem.
- **Apply de diff continua manual / stub.** Composição não resolve a limitação de `pipeline.py:11`. Quem aplica os edits é o orquestrador. Se rodar `simplicio task` solto, ainda precisa aplicar manual.
- **Não há trace unificado.** Logs do ralph vivem no orquestrador; logs do simplicio vivem em `.simplicio/last_output.txt`. Debug exige cruzar dois.

### Neutras / observações

- O agent `.agents/simplicio-ralph.agent.md` documenta limitações conhecidas explicitamente — usuário não é pego de surpresa.
- Se daqui pra frente o bench mostrar que `simplicio` ganha em domínios novos (Go, Rust, etc.), basta atualizar o roteamento, sem reescrever orquestração.

---

## Alternativas consideradas

### Alternativa A — "Tudo no `simplicio-cli`"

Resumo: expandir o CLI para `simplicio refactor`, `simplicio review`, `simplicio plan`, `simplicio debug`, `simplicio doc`, `simplicio migrate`, `simplicio loop --until-dod`, com apply automático de diff, gates de lint/test/e2e integrados, captura de evidência Playwright, exit gate dual, commit + PR.

Por que foi descartada:

- Sobreposição direta com Claude Code, Codex CLI, Copilot autopilot, Cursor Background Agent, Aider — competidores com investimento ordens de magnitude maior.
- Diluiria o diferencial medido (prompt + precedent + bench). Vira "mais um agent CLI".
- Manutenção pesada para 1 dev. Cada subcomando novo = mais código, mais testes, mais bugs, mais tempo longe do que importa (afinar prompt + ampliar bench).
- Quebra a regra de simplicidade do `CLAUDE.md` global ("sem abstrações pra uso único").
- Reinventaria orquestração que já existe e funciona (`ralph-loop` pattern + `/goal` + `/ralph-loop`).

### Alternativa B — Não fazer nada (manter `simplicio task` solto)

Resumo: deixar o CLI como está, sem agent spec. Usuário que quiser autonomia inventa wrapper bash.

Por que foi descartada:

- Conhecimento sobre como compor com ralph-loop fica implícito. Cada usuário reinventa.
- Sem `.agents/simplicio-ralph.agent.md`, ferramentas que leem `.agents/` (Claude Code, Codex, Cursor, etc.) não sabem que esta composição existe.
- Custo de criar a spec é baixo (1 arquivo markdown). Benefício de documentar é alto (todas as ferramentas convergem).

### Alternativa C — Plugin model

Resumo: `simplicio-cli` expõe API estável; orquestradores externos (ralph, santa, /goal) chamam como plugin via subprocess/stdio JSON.

Por que foi adiada (não descartada):

- É essencialmente o que a composição já faz (subprocess chamando `simplicio task`).
- Formalizar como "plugin protocol" exige spec de IO estruturado (JSON-RPC, MCP, etc.) e isso só vale a pena quando houver ≥3 orquestradores diferentes integrando.
- Reavaliar em 6 meses se aparecer demanda real.

---

## Critério de revisão

Revisitar esta decisão se **qualquer** uma das condições ocorrer:

- Bench mostrar que `simplicio` perde diferencial vs Claude Code / Codex direto em ≥3 stacks (sinal de que prompt+precedent não basta como vantagem).
- Surgir demanda explícita de ≥3 usuários diferentes pedindo `simplicio review` / `simplicio refactor` (sinal de que cobertura externa não basta).
- Apply automático de diff virar bloqueador real (impede composição em CI/CD de outros usuários).
- Em 6 meses (2026-11-26), revisar incondicionalmente.

---

## Links

- Agent spec: [`.agents/simplicio-ralph.agent.md`](../.agents/simplicio-ralph.agent.md)
- Padrão ralph-loop: [`.agents/ralph-loop.agent.md`](../.agents/ralph-loop.agent.md)
- CLI principal: [`simplicio/cli.py`](../../simplicio/cli.py)
- Loop interno: [`simplicio/pipeline.py`](../../simplicio/pipeline.py)
- Bench: [`bench/results.md`](../../bench/results.md)
- DESIGN: [`DESIGN.md`](./DESIGN.md)
- PATTERNS: [`PATTERNS.md`](./PATTERNS.md)
- ADRs relacionados: [`ADR-001`](./ADR-001-example.md)
- Doc de arquitetura agentic: [`../../docs/agent-architecture.md`](../../docs/agent-architecture.md)
- Ralph Wiggum technique (origem do padrão): https://ghuntley.com/ralph/

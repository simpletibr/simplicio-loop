# GEMINI.md — simplicio-loop (Gemini / other runtimes)

The **simplicio-loop** skill is runtime-agnostic. Gemini, Codex, Copilot, Grok, or
any local agent can run it from the same source file.

## Load

Point your agent at:

```
.claude/skills/simplicio-loop/SKILL.md
```

The folder name is `.claude/` for convention, but nothing in the skill is
Claude-specific — it uses only shell, git, gh, file edit, and web.

## Use

```
simplicio-loop: finish all the open issues
```

## Current flow for any LLM

Read `llms.txt` → `AGENTS.md` → `.claude/skills/simplicio-loop/SKILL.md`. Check
`simplicio-mapper --help`, `simplicio-fast --help`, and `simplicio-dev-cli --help`; then run
Mapper `scan`, `inspect`, and `handoff` before deciding an AC-scoped change. Use Fast for
bounded snapshot/PlanDAG context, Dev CLI for the edit plus verification, and real tests/gates
for evidence. Runtime/MCP is off by default (`standalone`); do not invoke it unless explicitly
opted in.

The orchestrator delegates, when loaded, to five satellite skills — `simplicio-loop`
(Ralph loop), `simplicio-orient` (terminal-first token economy), `simplicio-review`
(adversarial review), `simplicio-compress` (prose + memory compression), `simplicio-learn`
(retrospective). All live in `.claude/skills/`.

## Install & token economy

```bash
bash scripts/install.sh gemini      # writes .gemini/settings.json MCP + loads the skills
python3 hooks/orient_clamp.py -- <heavy command>   # reduce output before it hits context
```

## Binding

Use the host-independent [bounded delivery policy](.claude/skills/simplicio-loop/SKILL.md#bounded-delivery-policy)
and its [ADR 0008](docs/adr/0008-bounded-delivery-policy.md) for WIP, frozen scope, reviews,
ownership, integration, and release boundaries.

Where your runtime exposes native capabilities (a repo mapper, a deterministic file
writer, a local model fan-out, a durable scheduler), bind them to the matching
extension points in the Step 1b table so the steps become deterministic and
near-zero-token. Otherwise the LLM fallbacks cover 100% of the work.

See [`AGENTS.md`](AGENTS.md) for the full contract and [`adapters/MATRIX.md`](adapters/MATRIX.md)
for all 12 runtimes.

## Commands and features

Use [`docs/CLI_COMMANDS.md`](docs/CLI_COMMANDS.md) as the complete command
index. Run the most specific `--help` before use. New commands require
meaningful help text and a regression check. The coordinated train is Mapper
0.26.34, Dev CLI 0.18.16, Fast 2.0.35, and Loop 3.43.16. Issue bodies should
contain objective, implementation/deployment, and tests, without an Acceptance
Criteria section.

<!-- simplicio-global-llm-architecture-rules:start -->
## Regras arquiteturais obrigatórias para qualquer LLM

Estas regras valem para análise, planejamento, implementação, revisão, testes,
release e documentação neste ecossistema. O agente deve lê-las antes de agir:

1. **Não mantenha compatibilidade retroativa.** O que está obsoleto deve ser
   deletado diretamente. Não adicione camadas de compatibilidade, migrações ou
   fallbacks.
2. **Escolha a implementação mais simples que atende à necessidade atual.**
   Não crie abstrações preventivas nem camadas de configuração desnecessárias.
3. **Divida o sistema em camadas longas.** Faça primeiro uma versão mínima
   end-to-end funcionando; depois adicione capacidades por cima. Não desmonte
   algo que funciona por complexidades inacabadas.
4. **Mantenha os componentes modulares**, com responsabilidades claramente
   separadas e limites explícitos.
5. **Priorize bibliotecas maduras e mantidas.** Não reescreva do zero sem
   motivo técnico explícito e registrado.
6. **Inspecione primeiro as dependências existentes.** Antes de adicionar um
   pacote ou escrever uma solução própria, verifique o que o projeto já possui.
7. **Decida a arquitetura pensando no longo prazo.** Não aceite soluções
   temporárias com a intenção de mudar depois.
8. **Use padrões de produtos maduros.** Pesquise como soluções consolidadas
   resolvem o mesmo problema e reutilize padrões validados; não reinvente a roda.

<!-- simplicio-global-llm-architecture-rules:end -->



## Language precedence

[docs/LLM_OPERATING_INSTRUCTIONS.md](docs/LLM_OPERATING_INSTRUCTIONS.md) is the authoritative active instruction set and is written in English. Any other-language passage retained in this compatibility/reference file is non-normative; do not execute it as an instruction.

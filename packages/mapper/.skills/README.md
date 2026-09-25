# Skills

Skills são **capacidades reutilizáveis** que o agente carrega sob demanda. Cada skill é um arquivo `SKILL.md` autocontido, com frontmatter (`name`, `description`) e corpo descrevendo trigger, passos, padrões e Definition of Done.

A pasta `.skills/` deste projeto é onde ficam as skills **locais** — específicas deste repositório. Skills globais (compartilhadas entre projetos) ficam em `~/.claude/skills/`.

---

## O que é uma skill

Uma skill é um **manual operacional curto** que ensina o agente a executar uma tarefa recorrente do jeito certo. Não é código, não é dependência — é texto markdown que o agente lê quando o trigger casa.

Exemplos típicos:

- Como escrever um teste E2E neste projeto (configuração, fixtures, evidências).
- Como formatar uma mensagem de commit (Conventional Commits, breaking changes).
- Como abrir um PR (template, checklist DoD, rótulos obrigatórios).
- Como criar uma migration de banco (naming, reversibilidade, dry-run).

Skills **não substituem** documentação humana (essa fica em `.specs/`). Skills são otimizadas para **leitura por agente**: passos numerados, sem rodeio, com checklist final.

---

## Quando criar uma nova skill

Crie uma skill quando:

1. **Padrão repetido** — algo que aparece em mais de uma task e o agente erra sem orientação explícita.
2. **Decisão local não óbvia** — convenção que difere do padrão global (ex.: este projeto usa Vitest em vez de Jest).
3. **Fluxo multi-passo** — sequência longa que se beneficia de checklist (ex.: release pipeline com 8 etapas).
4. **Trigger claro** — você consegue descrever em uma frase quando a skill deve ativar.

**Não crie skill** para:

- Algo que aparece uma vez (use comentário inline ou ADR).
- Convenção universal (deixa nas skills globais).
- Conhecimento de stack genérico (use `*-patterns` global).

---

## Como triggar uma skill

Há dois modos:

### 1. Trigger explícito (`$skill-name`)

O usuário (ou outro agente) menciona o nome da skill no prompt:

```
$playwright-e2e — escreve teste para o fluxo de login
```

O agente carrega `.skills/playwright-e2e/SKILL.md` e segue os passos.

### 2. Trigger implícito (match por description)

O agente lê o `description` no frontmatter de cada skill disponível e ativa quando o pedido casa. Exemplo:

- Skill `conventional-commits` tem `description: padroniza mensagens de commit`.
- Usuário pede "faz commit dessas mudanças".
- Agente identifica match e aplica a skill automaticamente.

Por isso, **o `description` é a coisa mais importante do frontmatter**. Escreva-o como quem escreve uma query: imagine como o trigger vai aparecer no pedido futuro.

---

## Boas práticas

- **Concisão** — skill tem 30-100 linhas. Acima disso, vira documentação; mova pra `.specs/`.
- **Idempotente** — rodar a skill duas vezes deve ter o mesmo efeito da primeira. Não acumula estado.
- **Single-responsibility** — uma skill faz uma coisa. Se sentir vontade de juntar, divida.
- **Linguagem direta** — verbo no imperativo ("escreva", "rode", "valide"). Sem floreio.
- **Definition of Done** — toda skill termina com checklist verificável. Sem isso, agente não sabe quando parou.
- **Exemplos concretos** — code blocks com linguagem real do projeto, não pseudocódigo.
- **Sem emojis em código** — pode usar em prosa se ajudar leitura, mas não dentro de blocks.

---

## Skills incluídas neste starter

| Skill | Quando ativa |
| --- | --- |
| [`_template/`](./_template/SKILL.md) | Template base para criar novas skills |
| [`skillopt/`](./skillopt/SKILL.md) | Otimizar um `SKILL.md`/prompt com o loop SkillOpt (Rollout→Reflect→Edit→Gate) contra uma suíte de tarefas |
| [`playwright-e2e/`](./playwright-e2e/SKILL.md) | Escrever ou atualizar testes E2E com Playwright |
| [`conventional-commits/`](./conventional-commits/SKILL.md) | Padronizar mensagens de commit |
| [`ralph-loop/`](./ralph-loop/SKILL.md) | **Always-on.** Loop autônomo read→plan→execute→lint→unit→e2e→fix→repeat até DoD verde |
| [`caveman/`](./caveman/SKILL.md) | **Always-on.** Modo terse de resposta para economizar tokens (~65% saída) |
| [`everything-claude-code/`](./everything-claude-code/SKILL.md) | **Always-on.** Catálogo + protocolo de uso da suite ECC (60 agents, 221 skills) em paralelo |
| [`hyperframes/`](./hyperframes/SKILL.md) | Autoria de composição HTML para vídeo (timing, GSAP, captions, transitions, audio-reactive) |
| [`hyperframes-cli/`](./hyperframes-cli/SKILL.md) | CLI `npx hyperframes` (init, lint, inspect, preview, render, doctor) |
| [`hyperframes-media/`](./hyperframes-media/SKILL.md) | Preprocessing de assets (`tts`, `transcribe`, `remove-background`) |
| [`hyperframes-registry/`](./hyperframes-registry/SKILL.md) | Instalar blocos prontos do catálogo via `hyperframes add` |
| [`gsap/`](./gsap/SKILL.md) | Padrões GSAP timeline-based (paused, seekable) para hyperframes |
| [`animejs/`](./animejs/SKILL.md) | Anime.js como frame adapter |
| [`css-animations/`](./css-animations/SKILL.md) | CSS keyframe animations (seek-friendly) |
| [`lottie/`](./lottie/SKILL.md) | Lottie / dotLottie paused playback |
| [`three/`](./three/SKILL.md) | Three.js frame-synced via `hf-seek` |
| [`waapi/`](./waapi/SKILL.md) | Web Animations API via `document.getAnimations()` |
| [`tailwind/`](./tailwind/SKILL.md) | Tailwind v4 browser runtime no scaffold hyperframes |
| [`typegpu/`](./typegpu/SKILL.md) | TypeGPU / WebGPU shaders em compositions |
| [`contribute-catalog/`](./contribute-catalog/SKILL.md) | Contribuir blocos para o catálogo hyperframes |
| [`remotion-to-hyperframes/`](./remotion-to-hyperframes/SKILL.md) | Migrar projetos Remotion para hyperframes |
| [`website-to-hyperframes/`](./website-to-hyperframes/SKILL.md) | Converter site/landing em composição hyperframes |
| [`using-superpowers/`](./using-superpowers/SKILL.md) | Entrypoint da methodology superpowers: como achar e usar skills antes de qualquer resposta |
| [`brainstorming/`](./brainstorming/SKILL.md) | Refina ideia em design/spec via diálogo antes de implementar (hard-gate antes de codar) |
| [`writing-plans/`](./writing-plans/SKILL.md) | Escreve plano de implementação em tasks bite-sized (2-5 min) a partir de spec |
| [`test-driven-development/`](./test-driven-development/SKILL.md) | RED-GREEN-REFACTOR: sem código de produção sem teste falhando antes |
| [`subagent-driven-development/`](./subagent-driven-development/SKILL.md) | Executa plano com subagent fresco por task + review duplo (spec, depois qualidade) |
| [`systematic-debugging/`](./systematic-debugging/SKILL.md) | Root cause antes de fix: quatro fases, sem patch de sintoma |
| [`verification-before-completion/`](./verification-before-completion/SKILL.md) | Evidência antes de afirmar conclusão: roda o comando de verificação antes de qualquer claim |

> Skills `hyperframes*`, `gsap`, `animejs`, `css-animations`, `lottie`, `three`, `waapi`, `tailwind`, `typegpu`, `contribute-catalog`, `remotion-to-hyperframes`, `website-to-hyperframes` são **vendored verbatim** de https://github.com/wesleysimplicio/hyperframes (Apache 2.0). Veja `.skills/UPSTREAM-LICENSE` para o texto da licença e `.skills/NOTICE.md` para atribuição.
>
> Skills `using-superpowers`, `brainstorming`, `writing-plans`, `test-driven-development`, `subagent-driven-development`, `systematic-debugging`, `verification-before-completion` são **vendored verbatim** de https://github.com/obra/superpowers (MIT, Copyright (c) 2025 Jesse Vincent). Veja `.skills/UPSTREAM-LICENSE-superpowers` para o texto da licença e `.skills/NOTICE.md` para atribuição. Cada skill traz seus arquivos de apoio (`references/`, `*-prompt.md`, técnicas de debugging).

### Skills always-on (padrão do projeto)

Três skills são **ativadas automaticamente em toda sessão** via `.claude/settings.json` SessionStart hook:

- `caveman` — economiza tokens sem perder substância técnica
- `ralph-loop` — loop até DoD verde em toda task técnica
- `everything-claude-code` — máximo de agents em paralelo a cada alteração

Não precisam de invocação explícita. Neste README, skills marcadas como **always-on** devem ser tratadas como obrigatórias durante a sessão, sem opt-out local documentado nesta seção.

---

## Estrutura mínima de uma SKILL.md

```markdown
---
name: nome-da-skill
description: quando usar, em uma frase
---

## Trigger

- Quando ativar a skill.

## Steps

1. Passo um.
2. Passo dois.

## Padrões

- Convenção 1.
- Convenção 2.

## Definition of Done

- [ ] Critério verificável 1.
- [ ] Critério verificável 2.
```

Use `_template/SKILL.md` como ponto de partida. Copie para `.skills/<nova-skill>/SKILL.md` e edite.

---

## Manutenção

- Revise as skills a cada release. Skill desatualizada vira armadilha.
- Se uma skill for ignorada com frequência, simplifique ou delete.
- Se um padrão da skill virar regra global, mova pra `~/.claude/skills/` ou pra `.specs/architecture/PATTERNS.md`.

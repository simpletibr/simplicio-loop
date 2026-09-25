# PERSONAS — <PRODUCT_NAME>

Quem usa <PRODUCT_NAME>. Cada persona é um arquétipo: representa um grupo real de pessoas com objetivos, frustrações e contexto comuns. Decisões de produto e features se justificam contra estas personas, não contra opiniões.

> Regra: se uma feature não move a agulha de pelo menos uma persona aqui, ela não entra no backlog.

---

## Persona 1 — `<NOME_PERSONA_1>`

**Arquétipo:** <ex: Dev solo construindo SaaS>

### Quem é

- **Papel/profissão:** <ex: Founder técnico, full-stack>
- **Idade aproximada:** <ex: 28-40>
- **Contexto profissional:** <ex: trabalha sozinho ou em time de até 3, sem PM dedicado>
- **Familiaridade com tech:** <ex: alta — usa terminal, git, CI todo dia>
- **Familiaridade com o <DOMAIN>:** <ex: média — sabe o suficiente, não é especialista>

### Objetivos

O que essa persona quer alcançar? Listar 3-5.

- Lançar releases pequenas e frequentes sem quebrar produção.
- Manter contexto do projeto consistente entre dias/semanas.
- Reduzir tempo gasto em setup repetitivo entre projetos.
- Trabalhar com IA sem virar refém de um único provedor.

### Frustrações / dores

O que dói hoje? Cada item deve poder virar feature.

- Specs ficam desatualizadas e o agente perde contexto na semana seguinte.
- Cada projeto novo começa do zero com instruction files inconsistentes.
- Tasks vagas viram retrabalho e PRs gigantes.
- Falta de gate automático faz código ruim chegar em produção.

### Contexto de uso

Onde, quando, como usa <PRODUCT_NAME>.

- **Ambiente:** terminal + editor (VS Code/Cursor) + GitHub.
- **Frequência:** diariamente.
- **Sessão típica:** 2-6h focado, com pausas curtas.
- **Trigger principal:** começar projeto novo ou adicionar feature em projeto existente.

### Métrica que importa para essa persona

Como sabemos que estamos servindo bem?

- <ex: cycle time de task < 1 dia>
- <ex: PRs com checklist de DoD passando no gate>

---

## Persona 2 — `<NOME_PERSONA_2>`

**Arquétipo:** <ex: Líder técnico em time de 5-15 pessoas>

### Quem é

- **Papel/profissão:** <ex: Tech Lead, EM>
- **Idade aproximada:** <ex: 32-45>
- **Contexto profissional:** <ex: lidera time misto, responsável por velocidade e qualidade>
- **Familiaridade com tech:** <ex: alta>
- **Familiaridade com o <DOMAIN>:** <ex: alta>

### Objetivos

- Padronizar como o time usa AI agents para reduzir variância de output.
- Garantir que onboarding de devs novos seja em horas, não semanas.
- Ter visibilidade do que está sendo construído sem ler todo PR.
- Manter qualidade alta mesmo com aumento de velocidade.

### Frustrações / dores

- Cada dev usa IA do seu jeito, gerando código inconsistente.
- Specs vivem em ferramentas diferentes (Notion, Linear, comentários de PR), nunca no repo.
- Code review vira gargalo porque PRs são grandes e mal explicados.
- Decisões arquiteturais passadas se perdem na rotação de pessoas.

### Contexto de uso

- **Ambiente:** GitHub + ferramentas de gestão (Linear/Jira) + reuniões.
- **Frequência:** revê o repo toda semana, não codifica todo dia.
- **Sessão típica:** 30-60 min de revisão.
- **Trigger principal:** abrir o repo para revisar PR, escrever ADR ou planejar sprint.

### Métrica que importa

- <ex: variância entre PRs do time caiu>
- <ex: tempo de onboarding de dev novo caiu de X para Y>

---

## Persona 3 — `<NOME_PERSONA_3>` (opcional)

**Arquétipo:** <ex: Agente AI consumindo o repo>

### Quem é

- Não é humano. É o agente (Claude Code, Codex, Copilot) lendo `AGENTS.md` e specs.
- "Idade", "contexto profissional" não se aplicam, mas tem capacidades e limitações reais.
- **Limitações:** janela de contexto, sem memória entre sessões, depende 100% do que está escrito no repo.

### Objetivos

- Encontrar contexto rápido (VISION -> DESIGN -> task).
- Não inventar quando a spec não cobre.
- Validar trabalho contra DoD antes de fechar PR.
- Reaproveitar skills existentes em vez de reescrever lógica.

### Frustrações / dores

- Specs ambíguas geram código errado.
- Falta de exemplos concretos faz desviar do padrão.
- Hooks/CI sem mensagens claras dificultam autocorreção.
- Tasks sem critério de aceite testável geram retrabalho.

### Contexto de uso

- **Ambiente:** dentro do repo via CLI/IDE.
- **Frequência:** sempre que invocado.
- **Sessão típica:** uma task por vez, idealmente pequena.
- **Trigger principal:** humano dispara comando ou abre task.

### Métrica que importa

- <ex: % de tasks fechadas sem necessidade de retrabalho humano>
- <ex: % de PRs que passam no gate de DoD na primeira tentativa>

---

## Histórico

| Data | Mudança | Quem |
|---|---|---|
| YYYY-MM-DD | Criação inicial | <TEAM> |

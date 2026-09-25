# VISION — <PRODUCT_NAME>

Documento de uma página. Mantém o time alinhado sobre o porquê. Atualizar quando a tese mudar; nunca apagar a versão anterior sem registrar em ADR.

---

## Problema

Descreva em 2-3 frases o problema concreto que o produto resolve.

- Quem sente dor hoje no <DOMAIN>?
- Qual o custo dessa dor (tempo, dinheiro, frustração, oportunidade perdida)?
- Por que as soluções existentes não resolvem?

> Exemplo: "Times que constroem produtos com IA perdem tempo demais configurando contexto, instruction files e specs do zero a cada projeto. Isso atrasa a primeira release em semanas e produz repos inconsistentes."

---

## Quem usa

Resumo das personas. Detalhes completos em `PERSONAS.md`.

- **Persona primária:** <descrever em uma linha>
- **Persona secundária:** <descrever em uma linha>
- **Quem NÃO é o público:** <listar para evitar drift>

Veja `./PERSONAS.md` para objetivos, frustrações e contexto de uso de cada persona.

---

## Diferencial

O que faz <PRODUCT_NAME> diferente das alternativas? Listar 3-5 pontos verificáveis.

- Diferencial 1: <ex: setup zero-config em 10 minutos>
- Diferencial 2: <ex: gate de Definition of Done automatizado>
- Diferencial 3: <ex: skills reutilizáveis entre projetos>
- Diferencial 4: <ex: agnóstico de stack>

Evitar buzzwords vazios ("o melhor", "revolucionário"). Cada bullet deve poder virar teste.

---

## Métricas de sucesso

Indicadores que dizem se a tese está certa. Mensuráveis. Com baseline e meta.

| Métrica | Baseline | Meta (3 meses) | Como medimos |
|---|---|---|---|
| Tempo até primeira release | <ex: 4 semanas> | <ex: 1 semana> | Data primeiro commit -> data deploy v0.1 |
| Cobertura de testes mínima por PR | <ex: 0%> | <ex: 80%> | CI gate |
| Cycle time médio de task | <ex: 5 dias> | <ex: 1 dia> | Issue closed - issue created |
| Reverts em produção / mês | <ex: ?> | <ex: <= 1> | git log no main |

---

## Não-objetivos

O que <PRODUCT_NAME> intencionalmente NÃO faz. Tão importante quanto o que faz, evita scope creep.

- Não somos <X>. Quem precisa de <X> deve usar <Y>.
- Não otimizamos para <Z>. Optamos por <W> em troca.
- Não entregamos <feature comum> porque <razão>.

> Exemplo: "Não somos um framework. Não geramos código. Entregamos estrutura e processo."

---

## Tese de longo prazo

Em 12 meses, se der certo, como o mundo do <DOMAIN> está diferente?

> Frase única. Memorável. Algo que qualquer pessoa do <TEAM> consegue repetir sem ler.

---

## Histórico

| Data | Versão | Mudança | Quem |
|---|---|---|---|
| YYYY-MM-DD | 0.1 | Criação inicial | <TEAM> |

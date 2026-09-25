---
name: skillopt
description: otimiza um documento de skill (SKILL.md) com o loop SkillOpt (Rollout -> Reflect -> Edit -> Gate) contra uma suíte de tarefas, sem treinar o modelo
---

# Skill: `skillopt`

Otimização de skill no estilo [SkillOpt](https://microsoft.github.io/SkillOpt/) (Microsoft Research): o **documento de skill é o único artefato treinável**, o modelo-alvo permanece congelado. Um otimizador propõe edits limitados (add/delete/replace) e só aceita os que melhoram um split held-out.

Implementação local neste repo: `bin/skillopt.js` + engine determinístico em `scripts/skillopt/engine.js`. Roda offline, sem dependências e sem chave de API — o scorer default é determinístico e pode ser trocado por um adapter de LLM real via `opts.scorer`.

---

## Trigger

- Quando o usuário pedir para "otimizar", "melhorar" ou "afinar" um `SKILL.md` / prompt de instrução.
- Quando uma skill existente falha repetidamente em um conjunto de tarefas com critérios objetivos.
- Sempre que houver uma suíte de tarefas com `requires` / `forbids` mensuráveis para guiar o ajuste.

---

## Steps

1. Escreva a suíte de tarefas em JSON: cada task tem `id`, `split` (`train` ou `holdout`), `requires` (diretrizes que devem aparecer) e `forbids` (diretrizes proibidas). Veja `example.suite.json`.
2. Aponte para o skill inicial via `suite.skill` ou `--skill <SKILL.md>`.
3. Rode `node bin/skillopt.js --suite <suite.json> --out best_skill.md --report report.json`.
4. Inspecione o resumo: `gate score` inicial -> final, `pass rate`, edits aceitos/rejeitados e `EXIT_SIGNAL`.
5. Revise `best_skill.md` (diff contra o original) antes de promover. O otimizador adiciona diretrizes sob a seção `## SkillOpt Directives`.
6. Se aprovado, substitua o `SKILL.md` original pelo otimizado e rode lint/test.

---

## Padrões

- **Edit budget = textual learning rate**: `--budget N` limita ops aceitos por round. Comece baixo (1-2) para updates conservadores.
- **Gate em held-out**: defina ao menos uma task `split: "holdout"`. Sem held-out, o gate cai para o split de train (sinalizado em `scores.usedHoldout`).
- **Rejected-edit buffer**: edits que regridem o gate vão para a lista de rejeitados e não são repropostos — feedback negativo.
- **Determinismo**: a ordenação de candidatos é por frequência de falha e depois alfabética; rodar duas vezes dá o mesmo resultado.
- **Naming**: suíte em `*.suite.json`, saída padrão `best_skill.md`, receipt em `.catalog/receipts/<sha>.json`.
- **Evite**: aceitar `best_skill.md` sem revisão humana do diff; suítes sem `holdout`.

---

## Definition of Done

- [ ] `node bin/skillopt.js --suite <suite.json>` roda com exit 0.
- [ ] `best_skill.md` gerado e contém as diretrizes faltantes que a suíte exigia.
- [ ] `scores.best.gate >= scores.initial.gate` (sem regressão no held-out).
- [ ] `EXIT_SIGNAL: true` quando a suíte converge (train e gate com pass rate 1).
- [ ] Receipt escrito em `.catalog/receipts/` (ou `--no-receipt` deliberado).
- [ ] Diff do skill revisado antes de promover.

---

## Exemplo

```bash
# otimiza o skill fraco de exemplo contra a suíte de exemplo
node bin/skillopt.js \
  --suite .skills/skillopt/example.suite.json \
  --out best_skill.md \
  --report skillopt-report.json

# via subcomando do CLI
node bin/cli.js skillopt --suite .skills/skillopt/example.suite.json
```

Saída resumida:

```text
SkillOpt run complete
  gate score  : 0.4 -> 1 (Δ +0.6)
  pass rate   : train 1, gate 1
  edits       : 2 accepted, 0 rejected
  EXIT_SIGNAL : true
```

---

## Notas

- Loop e mecânica: `scripts/skillopt/engine.js` (`optimize`, `reflect`, `applyEdits`, `evaluateSplit`).
- Para usar um LLM real como scorer/optimizer, passe `opts.scorer` para `optimize()` retornando `{ score, pass, missing, offending }` por task — o loop não muda.
- Origem do método: https://microsoft.github.io/SkillOpt/ (otimização de skill para agents com modelo congelado).
- Última revisão: 2026-05-26.

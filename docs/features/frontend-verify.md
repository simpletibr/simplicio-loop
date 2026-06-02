# Frontend verify com Playwright

## Objetivo

Usar o Playwright como a **etapa de verify** do loop do `simplicio` quando a task
mexe em frontend. Como o `simplicio` executa tasks em várias linguagens, o verify
precisa ser capaz de provar que uma mudança de tela funciona — e o Playwright dirige
um browser real contra a UI renderizada, então vale pra qualquer stack de front
(React, Vue, Angular, Blazor, HTML puro...). Ele testa o que aparece na tela, não o
código-fonte.

## Como o loop do simplicio enxerga "verify"

O verify do `simplicio` é genérico e plugável. Em `simplicio/pipeline.py` o passo de
teste é literalmente um comando de shell:

```python
# pipeline.py
cmd = os.environ.get("SIMPLICIO_TEST_CMD", "echo 'configure SIMPLICIO_TEST_CMD'")
p = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True)
return p.returncode == 0, (p.stdout + p.stderr)[-2000:]
```

Ou seja: `returncode 0` = passou; em falha, a saída (últimos 2000 chars) volta como
feedback pro LLM corrigir, até `MAX_ATTEMPTS` (3). **Não precisa mudar nada no código
do simplicio pra usar Playwright** — basta apontar `SIMPLICIO_TEST_CMD` pra ele.

## Uso numa task de frontend

```bash
export SIMPLICIO_MODEL="anthropic/claude-..."   # id do modelo do seu provider
export SIMPLICIO_API_KEY="..."                   # ou OPENROUTER_/ANTHROPIC_API_KEY
export SIMPLICIO_TEST_CMD="npx playwright test --project=chromium"

simplicio-py task "Mostrar 12 tarefas concluídas no dashboard" \
  --target src/pages/Dashboard.tsx \
  --criteria "- dashboard mostra '12 tarefas concluídas'" \
  --constraints "- playwright verify passa"
```

Fluxo: `build → generate → apply → test (Playwright) → fix → repeat`. Se o spec
quebra, a saída do Playwright vira o feedback que guia a próxima tentativa. A
evidência fica em `playwright-report/` e nos prints que o spec captura (ver
`tests/e2e/README.md` e `docs/evidence/`).

> O spec de exemplo está em `tests/e2e/frontend-flow.spec.ts` (fluxo
> `login → dashboard → relatórios` + caso de erro), com Page Object em
> `tests/e2e/pages/DemoApp.ts`. Use-o como molde pros specs das suas tasks.

## Demo reproduzível do loop

`scripts/demo/frontend_verify_demo.py` roda o `pipeline.run` **real** com Playwright
**real** como `SIMPLICIO_TEST_CMD`, mostrando o loop ir de vermelho → feedback →
verde numa asserção de frontend.

O que é real vs stub nesse demo:

| Parte | Estado | Por quê |
|---|---|---|
| Loop de tentativas, decisão pass/fail, feedback, `MAX_ATTEMPTS` | **real** | é o núcleo do `pipeline.run` |
| `SIMPLICIO_TEST_CMD` (Playwright dirigindo o browser) | **real** | é o que estamos provando |
| `build_prompt` | stub | o real carrega embeddings (sentence-transformers) |
| `generate` (chamada LLM) | stub | o real precisa de `SIMPLICIO_MODEL` + chave |

Rodar (precisa de `npm install` + `npx playwright install chromium` + `pip install numpy`):

```bash
python3 scripts/demo/frontend_verify_demo.py
```

Transcript real do loop:

```text
--- attempt 1 (provider=claude) ---
failed:
Running 1 test using 1 worker
  ✘  1 [chromium] › verify.spec.ts:5:5 › dashboard reports 12 completed tasks
    Error: expect(locator).toHaveText( ...
--- attempt 2 (provider=claude) ---
PASSED the contract. DONE.

[demo] pipeline result: PASSED
[demo] evidence: docs/evidence/frontend-verify/dashboard-verified.png
```

Evidência (print do estado final, métrica corrigida para 12):

![dashboard verificado](../evidence/frontend-verify/dashboard-verified.png)

## Do demo para o loop de verdade

A única diferença é trocar os dois stubs pelo provider real: definir
`SIMPLICIO_MODEL` + chave faz o `generate` chamar o LLM, e o `build_prompt` real
monta o prompt com precedent + skill. O comando de verify (`SIMPLICIO_TEST_CMD=npx
playwright test ...`) é exatamente o mesmo.

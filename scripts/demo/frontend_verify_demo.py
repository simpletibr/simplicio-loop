#!/usr/bin/env python3
"""
Demo: Playwright as the frontend verify step of the simplicio loop.

Runs the REAL `simplicio.pipeline.run` control flow with a REAL Playwright run as
SIMPLICIO_TEST_CMD, so you can watch the loop go red -> feedback -> green on a
frontend assertion.

Only the two provider-dependent steps are stubbed, because they need external
resources this demo intentionally avoids:
  - build_prompt  -> stubbed (the real one loads sentence-transformers embeddings)
  - generate      -> stubbed (the real one calls an LLM and needs SIMPLICIO_MODEL + key)

Everything else is real: the attempt loop, SIMPLICIO_TEST_CMD execution, the
returncode -> pass/fail decision, the failure feedback, and MAX_ATTEMPTS.

For the TRUE end-to-end loop, set SIMPLICIO_MODEL + a provider key and run:
    SIMPLICIO_TEST_CMD="npx playwright test ..." simplicio-py task "<goal>" --target <file>
"""
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORK = REPO / ".runtime-logs" / "demo-frontend-verify"
EVIDENCE = REPO / "docs" / "evidence" / "frontend-verify" / "dashboard-verified.png"

# The frontend under test, deliberately starting in a broken state (metric reads 0).
BROKEN_HTML = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Dashboard</title></head>
<body>
  <h1>Dashboard</h1>
  <p>Tarefas concluidas hoje: <strong data-testid="metric-done">0</strong></p>
</body></html>
"""
FIXED_HTML = BROKEN_HTML.replace(">0<", ">12<")

SPEC = """import { test, expect } from '@playwright/test';
import { pathToFileURL } from 'node:url';
import * as path from 'node:path';

test('dashboard reports 12 completed tasks', async ({ page }) => {
  await page.goto(pathToFileURL(path.resolve(__dirname, 'app.html')).href);
  await expect(page.getByTestId('metric-done')).toHaveText('12');
  if (process.env.EVIDENCE_PNG) {
    await page.screenshot({ path: process.env.EVIDENCE_PNG, fullPage: true });
  }
});
"""

CONFIG = """import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: '.',
  reporter: [['list']],
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
"""


def scaffold():
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    (WORK / "app.html").write_text(BROKEN_HTML, encoding="utf-8")
    (WORK / "verify.spec.ts").write_text(SPEC, encoding="utf-8")
    (WORK / "playwright.config.ts").write_text(CONFIG, encoding="utf-8")


def main():
    sys.path.insert(0, str(REPO))
    scaffold()

    import simplicio.pipeline as pipeline

    # Stub the prompt builder so the demo does not load the embedding model.
    pipeline.build_prompt = lambda *a, **k: "[demo] make the dashboard metric read 12"

    # Stub the LLM. Attempt 1 leaves the bug (loop must fail and feed back).
    # Attempt 2 receives the failure feedback and applies the fix to disk,
    # standing in for "LLM generates a diff + the apply step writes it".
    def fake_generate(prompt, feedback=None, **_):
        if feedback is None:
            return "no change yet"
        (WORK / "app.html").write_text(FIXED_HTML, encoding="utf-8")
        return "set metric-done to 12"

    pipeline.generate = fake_generate

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    os.environ["EVIDENCE_PNG"] = str(EVIDENCE)
    os.environ["SIMPLICIO_TEST_CMD"] = (
        "npx playwright test --config=playwright.config.ts verify.spec.ts --project=chromium"
    )

    result = pipeline.run(
        root=str(WORK),
        stack="html",
        goal="Dashboard metric should read 12",
        target="app.html",
        criteria="- dashboard shows 12 completed tasks",
        constraints="- playwright verify passes",
    )
    print("\n[demo] pipeline result:", "PASSED" if result else "exhausted")
    print("[demo] evidence:", EVIDENCE.relative_to(REPO) if EVIDENCE.exists() else "(none)")
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())

# E2E Tests

The starter ships with a generic Playwright smoke test.

Run it with:

```bash
BASE_URL=<FRONTEND_URL> npx playwright test --project=chromium
```

Replace or extend `smoke.spec.ts` with project-specific scenarios:

- login or demo access
- primary navigation
- critical business flow
- expected data/result visible on screen
- screenshot/video/trace saved as evidence

Keep tests deterministic. If a project needs external access such as VPN, document it in `docs/local-setup.md`.

## Frontend flow example (`frontend-flow.spec.ts`)

A runnable, self-contained example of how Playwright tests a **frontend**: it drives
a real browser, navigates screens, fills forms, asserts what the user sees, and saves
screenshots as PR evidence. It works regardless of the frontend language/framework —
Playwright tests the *rendered* page, not the source.

First time only (installs deps + browser):

```bash
npm install
npx playwright install chromium
```

Run it:

```bash
npm run test:e2e -- frontend-flow.spec.ts --project=chromium
# interactive: npm run test:e2e:ui
# open report: npm run test:e2e:report
```

What it covers:

- **Login screen** → fills e-mail/senha and submits.
- **Dashboard** → asserts heading, the logged-in user and a metric.
- **Relatórios** → navigates and asserts the table rows.
- **Error case** → wrong password shows the error and keeps the user on login.

Where the parts live:

| Part | File |
|---|---|
| Demo app under test (offline SPA, `file://`) | `fixtures/demo-app/index.html` |
| Page Object (selectors by role/label/testid) | `pages/DemoApp.ts` |
| Spec (flow + asserts + evidence) | `frontend-flow.spec.ts` |
| Screenshots (committed, shown in the PR) | `../../docs/evidence/frontend-flow/*.png` |

### Adapting it to a real product

1. Replace `fixtures/demo-app` with nothing — point at your running app instead.
2. In `pages/DemoApp.ts`, change `url()` to use `BASE_URL` (e.g. `await page.goto('/login')`)
   and keep the role/label-based selectors.
3. Run with the app URL: `BASE_URL=http://localhost:3000 npm run test:e2e`.
4. If the app needs a dev server, uncomment the `webServer` block in `playwright.config.ts`.

### Evidence

Evidence is **screenshots only** for now (`video: 'off'` in `playwright.config.ts`).
Each screen is saved as a stable PNG in `docs/evidence/frontend-flow/` so it appears
in the PR diff, and is also attached to the HTML report. To re-enable video/trace
evidence (the full DoD policy), flip `video` back to `'retain-on-failure'`.

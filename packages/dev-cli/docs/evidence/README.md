# Evidence

Evidence proves that a change works in the running application, not only in code.

## When To Capture

- UI changes: screenshot.
- User flows: video plus screenshot.
- Flaky or complex flows: Playwright trace.
- API-only changes: request/response sample or test output.
- Worker/job changes: log excerpt plus resulting data state.

## Default Output

```text
.runtime-logs/evidence/
  <feature>-<scenario>-<timestamp>.png
  <feature>-<scenario>-<timestamp>.webm
  <feature>-<scenario>-<timestamp>-trace.zip
```

## Naming

Use lowercase, hyphenated names:

```text
billing-february-omni-20260513-181500.png
```

## Acceptance Checklist

- [ ] Evidence matches the requested scenario.
- [ ] Sensitive inputs are not visible.
- [ ] The expected result is visible or asserted.
- [ ] The evidence path is included in the final response or PR.
- [ ] Any limitation is documented with the reason.

## Playwright

Prefer a scenario-specific spec when the flow matters. For a generic smoke run:

```bash
BASE_URL=<FRONTEND_URL> npx playwright test --project=chromium
```

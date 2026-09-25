# Issue acceptance audit

This repo now carries a deterministic local acceptance-criteria audit for
issues `#199`, `#208`, and `#213`.

Run it with:

```bash
python scripts/issue_acceptance_audit.py --json
python scripts/issue_acceptance_audit.py --text
python -m unittest tests/python/test_issue_acceptance_audit.py
```

What the audit does:

- maps each criterion to concrete local evidence (`file:line` receipts);
- attaches replay commands for the relevant local proof path;
- rolls each criterion up to `DONE`, `PARTIAL`, or `UNVERIFIED`;
- keeps cross-repo boundaries explicit instead of pretending local files prove
  Runtime / Dev CLI / Loop behavior.

Status meanings:

- `DONE` — the local repo contains direct receipts for the criterion.
- `PARTIAL` — there is real local evidence, but the criterion is broader than
  the local proof currently available.
- `UNVERIFIED` — this repo alone cannot prove the criterion honestly, usually
  because the missing proof lives in GitHub state, CI state, or a downstream
  Runtime / Dev CLI / Loop consumer.

Important scope rule:

This audit is intentionally local and deterministic. It does not query GitHub
or external CI by default, and it does not silently upgrade cross-repo claims
to `DONE`.

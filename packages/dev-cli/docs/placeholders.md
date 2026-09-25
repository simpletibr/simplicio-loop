# Placeholder catalog

> Every token the starter sprinkles across `AGENTS.md`, `.specs/**`, `docs/**` and helper scripts. Use this page to know **what to fill**, **who fills it**, and **when**.

## Filling rules

1. Bootstrap (`npx`, `bootstrap.sh`, `bootstrap.ps1`) auto-fills `PRODUCT_NAME` and `STACK` from the project manifest **only inside starter-managed paths** and **only if the file still contains the literal placeholder**.
2. INIT.md (the prompt the chosen CLI runs on first launch) infers `TEAM`, `DOMAIN`, `VISION_ONELINER` and `PRIMARY_PERSONAS` by reading the codebase. It does not ask the human.
3. Everything else stays a placeholder until a human edits it. Run `scripts/check-placeholders.sh` after INIT.md to list unresolved tokens.

## Catalog

| Placeholder | Meaning | Filled by | Lives in |
|---|---|---|---|
| `<PRODUCT_NAME>` | Human-readable product name. | Bootstrap (from `package.json` `name`, `pyproject.toml` `[project].name`, `*.csproj` `<AssemblyName>`, `go.mod` `module`, `Cargo.toml` `package.name`, `pubspec.yaml` `name`, etc.). | `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, `.specs/product/VISION.md`, `.specs/sprints/**` |
| `<STACK>` | One-liner stack summary (e.g. `Node.js 20 + Next.js 14 + Playwright`). | Bootstrap (heuristic from manifests). | `AGENTS.md`, `.specs/architecture/DESIGN.md` |
| `<TEAM>` | Owning team name. | INIT.md (infers from CODEOWNERS / GitHub org). | `.specs/product/VISION.md`, `.specs/sprints/sprint-XX/SPRINT.md` |
| `<DOMAIN>` | Business domain (e.g. `fintech`, `healthcare`, `developer-tools`). | INIT.md (infers from README + UI copy). | `.specs/product/VISION.md`, `.specs/product/DOMAIN.md`, sprint docs |
| `<VISION_ONELINER>` | The one-sentence product thesis. | INIT.md (infers from README / landing copy). | `.specs/product/VISION.md` |
| `<PRIMARY_PERSONAS>` | List of primary user personas. | INIT.md (infers from auth roles, route guards, UI flows). Default: `developer`. | `.specs/product/PERSONAS.md` |
| `<NODE_DOTNET_PYTHON_GO_JAVA_VERSION>` | Runtime version pin. | Human (from `.nvmrc` / `global.json` / `pyproject.toml` / `go.mod` / `pom.xml`). | `docs/local-setup.md` |
| `<NPM_PNPM_YARN_NUGET_PIP_POETRY>` | Package manager command. | Human. | `docs/local-setup.md` |
| `<DATABASE_REQUIREMENT>` | Database flavor + version. | Human. | `docs/local-setup.md` |
| `<VPN_OR_NONE>` | Network access requirement. | Human. | `docs/local-setup.md` |
| `<WHERE_TO_GET_ENV_VARS>` | Link to secrets vault / `.env.example`. | Human. | `docs/local-setup.md` |
| `<ENV_NAME>` / `<VALUE>` / `<NOTES>` | Per-env-var row in the local setup table. | Human. | `docs/local-setup.md` |
| `<INSTALL_COMMAND>` | One-liner install command. | Human. | `docs/local-setup.md` |
| `<FRONTEND_URL>` / `<BACKEND_URL>` / `<FRONTEND_HEALTH>` / `<BACKEND_HEALTH>` | Local-dev URLs and health endpoints. | Human. | `docs/local-setup.md`, `scripts/start.*` |
| `<AUTH_FLOW>` | Auth flow id (e.g. `oauth2-pkce`, `password+jwt`). | Human. | `docs/local-setup.md` |
| `<DEMO_USER_OR_NONE>` / `<PASSWORD_LOCATION_OR_NONE>` | Demo-credential pointers (never literal passwords). | Human. | `docs/local-setup.md` |
| `<EVIDENCE_COMMAND>` | Project-specific evidence capture command. | Human. | `docs/evidence/README.md` |
| `<APP_NAME>` | App name (when distinct from product name). | Human. | `docs/architecture-map.md` |
| `<LICENSE_PLACEHOLDER>` | License text. | Human (replace with [`LICENSE`](../LICENSE) link). | Historical — already fixed in current `README.md`. |

## Tooling

`scripts/check-placeholders.sh` (POSIX) walks the repo and lists every remaining `<...>` token. Use it in CI to gate releases on a clean placeholder slate.

```bash
./scripts/check-placeholders.sh
# Exit code 0: no placeholders left.
# Exit code 1: at least one placeholder still present (file paths printed).
```

The script intentionally ignores: `docs/placeholders.md` (this file), `.specs/sprints/task-template.md`, `.specs/architecture/ADR-template.md`, `.specs/sprints/sprint-XX/SPRINT.md` and any `*.template.*`. Add more exemptions there if you ship templates.

# Pricing — simplicio-loop

simplicio-loop is open source under the [MIT license](LICENSE). This page describes what is sold today: the engine is free, and the only paid product is the **Simplicio MCP + Loop** subscription.

## Free

Everything in this repository is free under MIT: the orchestrator loop and its skills, the hooks, `simplicio-mapper`, `simplicio-dev-cli` and the local tools. Self-hosting needs no Simplicio account and no subscription.

The 24/7 watcher is the one exception. Its code is in this repository (`simplicio_loop/watcher247/`), but it runs only while the account has an active subscription.

## Subscription

| | |
|---|---|
| Product | Simplicio MCP + Loop |
| Price | US$10 per month, or US$100 per year |
| Trial | 7 free days |
| Covers | Simplicio Runtime and MCP access, and the 24/7 watcher |
| Payment | Stripe Checkout, by card or PIX |
| Sign-in | Google, through the Simplicio Runtime (`simplicio login google`) |
| Buy | https://simpleti.com.br/simplicio/ |

The sales page is the source of truth for the current price and trial terms.

## How the 24/7 gate works

Before each tick, `simplicio-loop watch247` checks the subscription (`simplicio_loop/watcher247/subscription.py`):

1. It reads the Simplicio login file. By default that is `~/.simplicio/login.json`, the file the Runtime shares. `SIMPLICIO_AUTH_FILE` changes that path, and `SIMPLICIO_247_LOGIN` takes precedence for the watcher.
2. If the access token expires within a minute, it refreshes the token.
3. It asks `https://simpleti.com.br/api/simplicio/validate.php` for the account's entitlement. The watcher runs only when the entitlement is active: status `active` or `trialing`, from a paid source, on a tier other than free.
4. Otherwise the tick does no work and the status file records the reason code. An unreachable server counts as not active, so the watcher fails closed.

`--dry-run` skips the check and changes nothing. To check the account yourself, run `simplicio-loop auth status --online`. Reason codes and troubleshooting are in [docs/WATCHER_247.md](docs/WATCHER_247.md).

## Not offered

There is no hosted Pro, Team or Enterprise tier today.

| Plan | Status |
|---|---|
| Hosted Pro | not offered |
| Team / Cloud (usage-based) | not offered |
| Enterprise (custom) | not offered |

Hosted dashboards and savings reports, per-seat or usage-based billing, SSO, audit logs, multi-repo fleets, distributed video render, and commercial license or support contracts are not offered.

# 🔁 simplicio-loop — The Universal Looping AI Orchestrator

> **Canonical operational contract:** This translation is informational. For current dependency, runtime, conformance, and validation behavior, [README.md](../README.md) is authoritative: Loop installs standalone; Runtime bindings are optional; 3 runtimes are guaranteed and 12 are best-effort; and `scripts/check.py` requires an importable `pytest` with no bare-Python fallback. Historical numeric counts and claims of complete categorization below are release snapshots, not current gate evidence; the checkout and latest local receipt are authoritative, and `scripts/test_categories.py` reports uncategorized files. GitHub Actions is not required gate evidence.

<p align="center">
  <img src="../assets/simplicio-loop-hero-stage-agents-2026.webp" alt="simplicio-loop met concrete agents per fase en gekoppelde rapportage" width="920" />
</p>

<p align="center">
  <a href="https://github.com/wesleysimplicio/simplicio-loop/stargazers"><img src="https://img.shields.io/github/stars/wesleysimplicio/simplicio-loop?style=social" alt="Stars"></a>
  <a href="#-de-7-skills--5-accelerators"><img src="https://img.shields.io/badge/skills-7-7C3AED" alt="7 skills"></a>
  <a href="#-source-adapters"><img src="https://img.shields.io/badge/source%20adapters-5-00E08A" alt="5 source adapters"></a>
  <a href="#-15-runtimes-één-protocol"><img src="https://img.shields.io/badge/runtimes-15-2563EB" alt="15 runtimes"></a>
  <a href="#-de-44-uitbreidingspunten"><img src="https://img.shields.io/badge/extension%20points-48-00E08A" alt="48 extension points"></a>
  <a href="#-token-economie"><img src="https://img.shields.io/badge/tokens-up%20to%2096%25%20fewer-green" alt="Up to 96% fewer tokens"></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
</p>

<p align="center">
  <a href="#-tldr">TL;DR</a> ·
  <a href="#-de-7-skills--5-accelerators">7 Skills</a> ·
  <a href="#-source-adapters">Source Adapters</a> ·
  <a href="#-15-runtimes-één-protocol">15 Runtimes</a> ·
  <a href="#-de-lus">De lus</a> ·
  <a href="#-token-economie">Token-economie</a> ·
  <a href="#-token-economie">Capture Engine</a> ·
  <a href="#-installeren--gebruiken">Installeren</a>
</p>

<p align="center">
  <strong>🌍 Languages:</strong><br>
  <a href="../README.md">🇬🇧 English</a> |
  <a href="README.pt-BR.md">🇧🇷 Português</a> |
  <a href="README.es-ES.md">🇪🇸 Español</a> |
  <a href="README.fr-FR.md">🇫🇷 Français</a> |
  <a href="README.de-DE.md">🇩🇪 Deutsch</a> |
  <a href="README.it-IT.md">🇮🇹 Italiano</a> |
  <a href="README.ja-JP.md">🇯🇵 日本語</a> |
  <a href="README.ko-KR.md">🇰🇷 한국어</a> |
  <a href="README.zh-CN.md">🇨🇳 简体中文</a> |
  <a href="README.ru-RU.md">🇷🇺 Русский</a> |
  <a href="README.pl-PL.md">🇵🇱 Polski</a> |
  <a href="README.tr-TR.md">🇹🇷 Türkçe</a> |
  <a href="README.nl-NL.md">🇳🇱 Nederlands</a> |
  <a href="README.hi-IN.md">🇮🇳 हिन्दी</a> |
  <a href="README.ar-SA.md">🇸🇦 العربية</a>
</p>

---

<!-- visual-story:start -->
## 🚀 De nieuwe generatie — een besturingssysteem voor verifieerbaar agentwerk

**simplicio-loop is veel meer geworden dan een prompt die tot voltooiing wordt herhaald.** Het zet intentie om in een bevroren taakcontract, brengt de repository in kaart, plant op afhankelijkheden, verdeelt uitvoering over geïsoleerde worktrees, verzamelt gestructureerde bewijzen, verifieert onafhankelijk, rolt veilig terug, onthoudt iedere poging en houdt de bron van waarheid synchroon tot en met levering.

- **Eerst het contract** — acceptatiecriteria, afhankelijkheden, risico’s, bronstatus en completion oracle zijn vóór uitvoering expliciet.
- **Parallel zonder corruptie** — gereed werk draait in geïsoleerde lanes/worktrees en convergeert via een operationeel ledger.
- **Bewijs vóór voltooiing** — tests, impact/flow-controles, watcher challenges, delivery receipts en HBP evidence weigeren valse done-statussen.
- **Geheugen dat gedrag verandert** — journal, stall detector, checkpoints en cross-agent wiki voorkomen oscillatie en maken handoffs duurzaam.

<p align="center">
  <img src="../assets/simplicio-loop-parallel-worktrees.png" alt="simplicio-loop parallel isolated worktree execution" width="920" />
</p>

<p align="center"><em>Afhankelijkheidsbewuste fan-out: geïsoleerde workers draaien parallel, leveren bewijs terug en convergeren naar één geverifieerde levering.</em></p>

<p align="center">
  <img src="../assets/simplicio-loop-lifecycle-2026.svg" alt="simplicio-loop lifecycle from intake to durable memory" width="920" />
</p>

<p align="center"><em>Elke fase is expliciet, begrensd, observeerbaar en omkeerbaar.</em></p>

<p align="center">
  <img src="../assets/simplicio-loop-evidence-memory.png" alt="simplicio-loop evidence memory verification rollback and completion" width="920" />
</p>

<p align="center"><em>Bewijs en geheugen horen bij het uitvoeringspad, niet bij een achteraf geschreven rapport.</em></p>

Deze architectuur maakt van één doel een bestuurd leveringssysteem: van een moeilijke taak tot een volledige backlog, over sessions en runtimes heen, met local-first operators en receipts die mensen, CI of een andere agent kunnen auditen.

<p align="center">
  <img src="../assets/simplicio-loop-architecture-2026.svg" alt="simplicio-loop control execution evidence and delivery planes" width="920" />
</p>
<!-- visual-story:end -->

<!-- stage-agents-roadmap:start -->
## 🤖 Roadmap — een concrete agent achter elke fase

> **Status:** geplande architectuur in [#422](https://github.com/wesleysimplicio/simplicio-loop/issues/422)–[#436](https://github.com/wesleysimplicio/simplicio-loop/issues/436). De canonieke GitHub-lifecyclecomment bestaat al; de volledige gate voor stage-agents en verplichte rapportage wordt nog gebouwd in [#433](https://github.com/wesleysimplicio/simplicio-loop/issues/433).

Intake/planning, implementatie, veiligheid, levering, recovery en de eindaudit krijgen elk één verantwoordelijke agent. Review vertakt naar vier onafhankelijke agents — beveiliging/correctheid, kwaliteit, runtime/E2E-reproductie en blast radius — en convergeert daarna pas.

<p align="center"><img src="../assets/simplicio-loop-stage-agents-reporting-2026.webp" alt="simplicio-loop stage-agents en opmerkingen in work trackers" width="920" /></p>

```mermaid
flowchart LR
  P["Intake- + plannings-agent"] --> I["Implementatie-agent"] --> S["Veiligheids-agent"]
  S --> R["4 onafhankelijke review-agents"] --> D["Delivery-agent"] --> A["Completion auditor"]
  D --> F["Feedback- + recovery-agent"] --> I
  P -.-> E["Events + receipts"]
  I -.-> E
  R -.-> E
  A -.-> E
  E --> G["GitHub-comments · VERPLICHT"]
  E -. "alleen indien gekoppeld" .-> O["Azure DevOps · Jira · Asana · Trello"]
```

**Beleid:** GitHub is verplicht voor aan GitHub gebonden runs en `COMPLETE` wacht op remote bevestiging. Azure DevOps, Jira, Asana en Trello krijgen alleen comments na bewezen verbinding, authenticatie, autorisatie en target-resolutie; `NOT_CONNECTED` is een expliciete, niet-blokkerende skip. Contract en tests: [#436](https://github.com/wesleysimplicio/simplicio-loop/issues/436).
<!-- stage-agents-roadmap:end -->

## 🆕 Nieuw in v3.38.0 — de multi-agent-coördinatierelease

Deze release lost één hard probleem op dat pas zichtbaar wordt zodra **meerdere agent-sessies
tegelijk in dezelfde repo werken**: hoe weet een sessie wat al geclaimd is, wat al gemerged-maar-
onaf is, en wat te doen met eigen idle-tijd in plaats van het werk van een zustersessie te
dupliceren? Alles hieronder is gebouwd en getest tegen de **live, multi-sessie-staat van deze repo
zelf** — geen synthetisch scenario.

- **`scripts/coordinator.py` — de beslissingskern.** Op basis van de actuele GitHub-status
  (claim-comments op open issues + gemergede PR's) geeft het één deterministische actie per issue
  terug: `OWN` (nog niets geclaimd), `CONTINUE_OWN` (jij bent al de laatste claimant),
  `DEFER_ACTIVE_CLAIM` (een zustersessie claimde het recent — niet dupliceren),
  `RECLAIM_STALE` (die claim is verkoeld, veilig over te nemen), of `VERIFY_PARTIAL` (er is al een
  PR gemerged voor dit issue, maar het staat nog open — check eerst wat er echt af is). Het zet ook
  een `duplicate_risk`-vlag zodra twee sessies hetzelfde issue kort na elkaar claimen. Live gevangen
  op dag één: twee sessies die onafhankelijk van elkaar een findings-collector voor hetzelfde issue
  bouwden, onder twee verschillende bestandsnamen.
- **`scripts/pr_dod_review.py` — de reviewer voor idle-tijd.** Wanneer elk open issue al geclaimd
  is, is de beste zet van een sessie niet wachten, maar de open PR's toetsen aan de eigen lat van
  deze repo: de 7-dimensionale Definition of Done (implementatie, unit-/integratie-/systeem-/
  regressietests, een prestatiebenchmark, ≥85% dekking) en de bevroren acceptatiecriteria-checklist
  van het onderliggende issue. `check --post` plaatst een mechanisch, item-voor-item oordeel als
  PR-comment in plaats van een gevoelsmatige goedkeuring. Bewezen tegen een echte, al gemergede
  "MVP slice"-PR: het markeerde correct **17 van de 17** acceptatiecriteria van de bovenliggende
  epic als nog onopgelost.
- **`scripts/finding_collector.py` — duurzaam, gededupliceerd defectgeheugen (issue #466, fase 1).**
  Eén `simplicio.finding/v1`-record per onderscheiden defect, gefingerprint zodat dezelfde
  onderliggende bug — gezien door welke agent, welke run, welk tijdstip dan ook — samenvalt in één
  record met een optellende voorkomens-teller in plaats van dubbele ruis te genereren. Nog geen
  GitHub-aanroepen; dat komt in de volgende fase.
- **`references/multi-agent-coordination.md` + `references/background-verification.md`** — twee
  nieuwe, in `SKILL.md` vastgelegde conventies: check eigenaarschap bij de coordinator vóórdat je
  een issue aanraakt, review PR's in plaats van idle te blijven zodra alles geclaimd is, en start
  trage verificatiecommando's (tests/`claims_audit.py`) op de achtergrond zodat een beurt
  vooruitgang blijft boeken in plaats van op een voortgangsbalk te wachten.
- **Twee echte regressies live gevangen en gefixt op `main` zelf, deze releasecyclus** — een PR die
  stilletjes een functiedefinitie verwijderde (waardoor `loop_progress.py`'s eigen selftest brak)
  werd één keer gemerged, en een squash-merge race herintroduceerde exact dezelfde kapotte code
  daarna nog een keer op `main`. Beide werden gevonden door het betreffende script daadwerkelijk uit
  te voeren, niet door een groene PR-beschrijving te vertrouwen — precies de reden waarom
  `coordinator.py` en `pr_dod_review.py` nu bestaan.

**Wat dit concreet voor je betekent:** als je `simplicio-loop` in meer dan één sessie of machine op
dezelfde repo draait, beschermt het je nu actief tegen de twee faalmodi die in de praktijk echt
gebeuren — twee agents die stilletjes hetzelfde werk overdoen, en een "klaar"-PR die wel merged maar
het echte issue maar deels oploste. Geen van beide was voorheen zichtbaar; beide zijn dat nu,
mechanisch, elke triage-beurt.

Zie [`CHANGELOG.md`](../CHANGELOG.md) voor de volledige lijst.

## ⚡ TL;DR

**simplicio-loop** is een runtime-onafhankelijk **super-plugin** — één autonome lussende
orkestrator (aangeroepen als **`/simplicio-loop`**) plus **vijf satelliet-skills** — dat elke
sterke LLM (Claude, Codex, Copilot, Gemini, Cursor, lokale modellen) verandert in een zelfsturende
worker. Je wijst hem op een hoeveelheid werk — *"maak alle open issues af"*, *"werk de CI-wachtrij
weg"*, *"leeg het Jira-board"* — en hij draait de hele levenscyclus helemaal zelf:

> **ontdekken → begrijpen → beslissen → handelen → verifiëren → corrigeren → vastleggen → herhalen**

Hij ontdekt werk uit elke bron (GitHub Issues, Jira, Azure DevOps, agentsview-sessies, en meer),
ontdubbelt, schaalt automatisch een agentvloot op naar jouw machine, implementeert elk item via een
kwaliteitslus die **de code uitvoert (niet alleen compileert)**, opent PR's, verwerkt
CI-/reviewfeedback, merget, en blijft **24/7** speuren naar nieuw werk — allemaal achter
veiligheidspoorten en een harde kostennoodstop.

```text
/simplicio-loop finish all open issues
→ identity + pre-flight (auth, runtime, STOP path)
→ discover 50 issues · dedup · build dependency DAG
→ autoscale fleet = 14 · pipeline implement→review→merge
→ each item: read body+ACs → orient code → plan → edit → run → verify → PR
→ merge · close with evidence · rollback if main breaks
→ keep looping every ~2 min until the queue is dry (evidence-gated, never a false "done")
```

Drie dingen maken het anders: het is een **super-plugin van toegespitste skills**, het draait
**hetzelfde protocol op 15 runtimes**, en het doet dit alles met **agressieve, eerlijke
token-economie**.

---

## 📘 Officieel capaciteitsregister

Het complete, officiële overzicht van wat `simplicio-loop` levert — elke capaciteit hieronder is
**echt, uitvoerbaar en getest** door de toepasselijke lokale gate. Exacte aantallen verzamelde,
uitgevoerde en overgeslagen tests horen bij het nieuwste gate-receipt, niet bij dit document. Elk
verwijst naar zijn uitgebreide sectie en zijn worker.

| Capaciteit | Wat het doet | Bewijs / worker | Details |
|---|---|---|---|
| 🎬 **Video-bewijs** (`video_evidence`) | Legt de **echte browsersessie** vast als bewegend bewijs dat een UI-wijziging werkt (Playwright, standaard); rendert een **deterministische, ondertitelde MP4** met [hyperframes](https://github.com/heygen-com/hyperframes) voor een expliciet verzoek om een uitlegvideo (`/simplicio-loop make a video of screen X`) | `scripts/video_evidence.py` · GEBLOKKEERD (nooit fake-pass) zonder de toolchain | [§ Video-bewijs](#-video-evidence--playwright-by-default-hyperframes-on-request) |
| 🧠 **Pogingengeheugen + stall-detector** | Een duurzaam run-journal (`.simplicio-loop/orchestrator/loop/journal.jsonl`) + een stall-detector zodat de lus **van strategie verandert in plaats van te oscilleren**; incrementele triage (`since`) leest elke beurt alleen het verschil | `scripts/loop_journal.py` · `selftest` 9/9 | [§ Anti-oscillatie](#-pogingengeheugen--stall-detector-anti-oscillatie) |
| 🔒 **Fail-closed veiligheidspoort** (`action_gate`) | Een `PreToolUse`-/git-pre-push-hook die **mechanisch** force-push, history-herschrijving, massa-verwijdering, destructieve DDL, infra-afbraak en commits/pushes vol secrets **blokkeert** — Stap 5 uitvoerbaar gemaakt, niet als proza | `hooks/action_gate.py` · `selftest` 15/15 | [§ Veiligheid](#-veiligheid-niet-onderhandelbaar) |
| 🔬 **Lokale verificatie** | Een testsuite (worker-selftests + een **e2e van de loop-driver** die bewijs-gepoorte uitgang aantoont) + een **claims-audit** (gerefereerde scripts bestaan · tellingen consistent · `_bundle ≡ source`) — allemaal lokaal, **geen betaalde CI** | `scripts/check.py` · `scripts/claims_audit.py` · `tests/` | [§ Tests & lokale checks](#-tests--lokale-checks-geen-betaalde-ci) |
| ✅ **Eerlijke besparing** | De besparingsregel is nu **bewijs-gepoort, niet verplicht** — een getal wordt alleen getoond met een gemeten bewijsstuk (clamp/signatures/cache/`deterministic_edit`/ledger); nooit verzonnen | token-economie-contract | [§ Token-economie](#-token-economie) |
| 🤝 **Multi-agent-coordinator** (`coordinator.py`) | Beslist `OWN` / `CONTINUE_OWN` / `DEFER_ACTIVE_CLAIM` / `RECLAIM_STALE` / `VERIFY_PARTIAL` per issue op basis van live claim-comments + gemergede PR's, zodat twee sessies nooit hetzelfde werk dupliceren | `scripts/coordinator.py` · `selftest` 10/10 | [§ Nieuw in v3.38.0](#-nieuw-in-v3380--de-multi-agent-coördinatierelease) |
| 🕵️ **PR DoD/AC-reviewer** (`pr_dod_review`) | Wanneer elk issue geclaimd is, toetst het open PR's aan de 7-dimensionale Definition of Done + de eigen acceptatiecriteria-checklist van het issue — een mechanisch oordeel, geen gevoelsmatige goedkeuring | `scripts/pr_dod_review.py` · `selftest` 13/13 | [§ Nieuw in v3.38.0](#-nieuw-in-v3380--de-multi-agent-coördinatierelease) |
| 🐞 **Finding-collector** (`finding_collector`) | Gefingerprint, gededupliceerd defectgeheugen — dezelfde onderliggende bug valt samen in één record met een voorkomens-teller, ongeacht hoeveel agents/runs hem waarnemen | `scripts/finding_collector.py` · `selftest` 9/9 | [§ Officieel capaciteitsregister](#-officieel-capaciteitsregister) |

Twee lus-**modi** maken terminatie expliciet: **converge** (één harde taak — eindigt op de
bewijs-gepoorte `<promise>` of een stall-escalatie) versus **drain** (een wachtrij — eindigt wanneer
de herbevraging van de bron K rondes leeg blijft). Beide gehoorzamen nog steeds de universele
Both modes are still governed by universal exits: promise+evidence, `max_iterations`, and STOP.

> Lusscore over deze lijn van werk: **7.5** (sterk ontwerp, onbewezen) → **9** (pogingengeheugen +
> anti-oscillatie) → **9.5** (reproduceerbaar lokaal bewijs) → **~10** (afgedwongen veiligheid +
> complete lus-semantiek). De verificatie-infra vangt nu de eigen regressies van het project op
> naarmate het groeit.

---

## 🧠 De 7 skills + 5 accelerators

De orkestrator-kern + zes satellieten + vijf accelerators/integraties. Elke satelliet is
**optioneel** — wanneer geladen, delegeert de orkestrator eraan (rijker + goedkoper); wanneer
afwezig, dekt het inline-protocol 100%. Accelerators worden **automatisch gedetecteerd** — aanwezig
= gebruikt, afwezig = LLM-fallback.

| # | Capaciteit | Neemt over van | Wat het doet | Token-impact |
|---|---|---|---|---|
| 1 | 🔁 **simplicio-loop** | — | Unified public entrypoint: orchestrator core + hardened loop behind one command | Core + loop |
| 2 | ↩️ **simplicio-tasks** | legacy alias | Compatibility shim for older installs and saved prompts | Legacy alias |
| 3 | 🧱 **simplicio-orient** | [rtk](https://github.com/rtk-ai/rtk) + [caveman](https://github.com/JuliusBrussee/caveman) | Terminal-first uitvoering, output-reductiecatalogus, tee-cache, signatures-read | L0 deterministisch |
| 4 | 🔥 **simplicio-review** | [thermos](https://github.com/cursor/plugins/tree/main/thermos) | Parallelle adversariële review op afzonderlijke rubrieken → gededupliceerd oordeel | Kwaliteitspoort |
| 5 | 🗜️ **simplicio-compress** | [caveman](https://github.com/JuliusBrussee/caveman) | Output- + geheugencompressie, fail-closed `transform_guard` | 40-60% minder |
| 6 | 🎓 **simplicio-learn** | [teaching](https://github.com/cursor/plugins/tree/main/teaching) | Post-run-retrospectief → duurzame, gededupliceerde lessen in het geheugen | Slimmer per run |
| 7 | 🧪 **simplicio-autoresearch** | Karpathy [autoresearch](https://github.com/balukosuri/Andrej-Karpathy-s-Autoresearch-As-a-Universal-Skill) + ECC `autoresearch-agent` | Evolutionaire mutate/eval/keep-revert-lus: yool-gebonden plafonds, git-geïsoleerde branch, anti-Goodhart poort-eerst-evaluatie, `savings-event`-bewijsstuk | Auto-optimaliseren |
| 8 | 🧭 **Understand Anything** | [Egonex-AI](https://github.com/Egonex-AI/Understand-Anything) | Kennisgrafiek-oriëntatie: semantisch zoeken, geleide tours, afhankelijkheidsgrafiek | **L0 nul tokens** |
| 9 | 📊 **agentsview** | [kenn-io](https://github.com/kenn-io/agentsview) | Sessie-analyse, kostenregistratie, ontdekking van vastgelopen sessies | **L1** alleen SQL |
| 10 | ⚡ **LMCache** | [LMCache](https://github.com/LMCache/LMCache) | KV-cache tussen lusbeurten — 40-70% TTFT-reductie op lokale modellen | GPU-tijd ↓ |
| 11 | 🗜️ **Simplicio capture engine** | `engine/simplicio_engine.py` (native, alleen-stdlib) | Transparante capture-proxy: stuurt door naar de echte provider, meet + comprimeert deterministisch, schrijft `proxy_savings.json` | **deterministisch** |
| 12 | 🎬 **video_evidence** | Playwright (standaard) · [hyperframes](https://github.com/heygen-com/hyperframes) (op verzoek) | Legt de **echte sessie** vast als bewegend bewijs van een UI-wijziging (Playwright); rendert een **deterministische, ondertitelde MP4**-uitlegvideo met hyperframes wanneer de video ZÉLF het op te leveren product is | Bewijsproducent |

Elke skill leeft onder [`.claude/skills/`](../.claude/skills); elke accelerator heeft een
referentiedocument onder `.claude/skills/simplicio-loop/references/` (de video-producent:
[`video-evidence.md`](../.claude/skills/simplicio-loop/references/video-evidence.md), worker
[`scripts/video_evidence.py`](../scripts/video_evidence.py)).

---

## 📡 Source adapters

De orkestrator ontdekt werk uit elke bron via pluggable adapters. Elke biedt zes werkwoorden:
`list_ready`, `get_details`, `claim`, `update_status`, `attach_evidence`, `close`.

| Bron | Adapter | Doel |
|---|---|---|
| GitHub Issues/PR's | `gh` CLI (native) | Primaire bron voor werkitems |
| Jira / Asana / ClickUp / Linear / Notion | host-connector | Board-/projectbeheer |
| Trello / Azure DevOps | `az boards`-adapter | Azure work tracking |
| **agentsview-sessies** | `scripts/agentsview_adapter.py` | Herstel van vastgelopen sessies + kostenzichtbaarheid |
| Lokale bestanden / CI-wachtrij | filesystem / CI API | Intern werkbeheer |

Zie het referentiedocument van elke adapter onder `.claude/skills/simplicio-loop/references/`.

---

## 🌐 15 runtimes, één protocol — 3 gegarandeerd + 12 best-effort

Eén universele skill-kern + één set hooks drijft elke runtime aan. Een adapter is dun: hij vertelt
een runtime *waar de skills te laden*, *hoe de lus scherp te stellen* en *hoe de native snelheid te
binden*. **De skill noemt geen enkele runtime; de runtime detecteert de skill.** De native
`simplicio-runtime` MCP-binding is optioneel op elke runtime; bij een ontbrekende of onbereikbare
binding meldt de adapter expliciete gedegradeerde modus en blijft de standalone-lus beschikbaar —
zie [`docs/MCP_SETUP.md`](../docs/MCP_SETUP.md).

### Tier 1 — Gegarandeerd (bij elke commit getest)

| Runtime | Skill-laden | Lusaandrijving | Native binding (MCP) |
|---|---|---|---|
| **Claude Code** | `.claude/skills/` + plugin | `Stop`-hook | VERPLICHT — `~/.claude.json` |
| **Codex** | `AGENTS.md` | zelf-getimed | VERPLICHT — `~/.codex/config.toml` |
| **Cursor** | `.cursor-plugin/` | `stop`+`afterAgentResponse` | VERPLICHT — `.cursor/mcp.json` |

### Tier 2 — Best-effort (bijdragen welkom, geen gate)

| Runtime | Skill-laden | Lusaandrijving | Native binding (MCP) |
|---|---|---|---|
| **VS Code (Copilot)** | `copilot-instructions.md` | tasks | VERPLICHT — `.vscode/mcp.json` |
| **Antigravity** | rules / `AGENTS.md` | zelf-getimed | VERPLICHT — best-effort pad |
| **Kiro** | `.kiro/steering/` | specs | VERPLICHT — `.kiro/settings/mcp.json` |
| **OpenCode** | `AGENTS.md` | zelf-getimed | VERPLICHT — `opencode.json` |
| **Gemini** (CLI/Code Assist) | `GEMINI.md` | zelf-getimed | VERPLICHT — `.gemini/settings.json` (CLI) |
| **Kimi** | ingesloten conventies | zelf-getimed | VERPLICHT — best-effort, geen geverifieerde client |
| **Qwen** (Code/CLI) | `AGENTS.md`-equivalent | zelf-getimed | VERPLICHT — `.qwen/settings.json` (best-effort) |
| **DeepSeek** | ingesloten conventies | zelf-getimed | VERPLICHT — geen first-party client, best-effort |
| **Aider** | `CONVENTIONS.md` | zelf-getimed | VERPLICHT — geen MCP-client (LLM-fallback voor exec) |
| **Simplicio Agent** *(voorheen Hermes)* | native recall | native lus | VERPLICHT — **native** |
| **OpenClaw** | plugin SDK | native scheduler | VERPLICHT — **native** |
| **Orca** | via interne agent + skills-registry | interne hook / geplande automatiseringen | VERPLICHT — registry-/interne-agentconfig |

De belofte: **hetzelfde protocol, dezelfde poorten, dezelfde veiligheid op alle 15 — Tier 1
mechanisch geverifieerd, Tier 2 best-effort.** `orient_clamp.py` (token-economie) werkt op elke
runtime zonder enige bedrading. Zie [`adapters/MATRIX.md`](../adapters/MATRIX.md).

---

## 🗺️ De volledige flow — van vraag tot oplevering

Elke laag waarop de orkestrator inwerkt, op volgorde — van het lezen van de vraag (issues, taken,
toewijzingen) tot het opleveren van gemerged, onderbouwd werk, en dan 24/7 lussen voor meer.

```mermaid
flowchart LR
  IN["Intent: issue · task · queue"] --> CONTRACT["1 · Freeze task contract"]
  CONTRACT --> MAP["2 · Map source + normalize"]
  MAP --> PLAN["3 · Dependency DAG + acceptance criteria"]
  PLAN --> ROUTE{"4 · Ready task?"}
  ROUTE -->|"solo / small"| SOLO["Targeted lane"]
  ROUTE -->|"parallel / medium+"| FAN["Bounded fan-out"]
  FAN --> A["Isolated worktree A"]
  FAN --> B["Isolated worktree B"]
  FAN --> C["Isolated worktree C"]
  SOLO --> VERIFY["5 · Test + impact/flow evidence"]
  A --> VERIFY
  B --> VERIFY
  C --> VERIFY
  VERIFY --> RECEIPT["Watcher challenge + evidence receipt"]
  RECEIPT --> ORACLE{"6 · Completion oracle"}
  ORACLE -->|"pending / blocked"| RECOVER["Journal · checkpoint · rollback · backlog-only maintenance"]
  RECOVER --> PLAN
  ORACLE -->|"verified / measured"| DELIVER["7 · Source sync · PR · merge"]
  DELIVER --> MEMORY["8 · Ledger · wiki · durable attempt memory"]
  MEMORY --> WATCH["9 · Re-feed · watcher · STOP path"]
  WATCH -->|"new work"| IN
```

---

## 🔁 De lus

De **bewijs-gepoorte lus** is het kernmechanisme. Hij voert hetzelfde doel elke beurt opnieuw in
zodat de agent zijn eigen eerdere werk ziet. Uitgang is ALLEEN via:

1. **Bewijs-gepoorte `<promise>`** — de beurt die de belofte uitzendt MOET ook concreet bewijs
   dragen (geslaagde test, gemergede PR, herbevraging van gesloten item). Een belofte zonder bewijs
   = genegeerd.
2. **`max_iterations`-plafond** — harde veiligheidsbackstop
3. **STOP/cancel path** — explicit STOP file or channel command stops unattended runs
4. **STOP-signaal** — `.simplicio-loop/orchestrator/STOP` of kanaalcommando

Tussen beurten cachet LMCache (indien beschikbaar) de KV-toestand zodat herinvoer bijna-nul prefill
kost.

### 🧠 Pogingengeheugen + stall-detector (anti-oscillatie)

Een herinvoer-lus die niets onthoudt oscilleert — probeer X, faal, probeer X opnieuw — totdat het
plafond opbrandt. simplicio-loop houdt een **duurzaam run-journal** bij
(`.simplicio-loop/orchestrator/loop/journal.jsonl`, append-only:
`iteration · action · hypothesis · gate · error-fingerprint`) en een **stall-detector**
([`scripts/loop_journal.py`](../scripts/loop_journal.py), deterministisch + modelvrij):

- **Error fingerprint** — de output van de falende poort wordt gereduceerd tot een stabiele hash met
  regelnummers, paden, hex/uuids, timestamps en duraties weg-genormaliseerd, zodat dezelfde bug over
  beurten heen wordt herkend, zelfs wanneer de bijkomstige tekst verschilt.
- **Stall = K identieke-fingerprint-falingen op rij** (standaard K=3). Een veranderende fingerprint
  betekent dat de lus beweegt (PROGRESS); dezelfde K keer betekent dat hij rondtolt (STALLED).
- Bij STALLED voert de lus **niet** hetzelfde doel opnieuw in — hij benoemt de te vermijden
  **doodlopende acties**, en **wisselt dan van strategie** of **escaleert naar de menselijke poort**
  met de fingerprint.
- `loop_journal.py resume` wordt aan het begin van elke beurt gelezen, zodat een vers proces
  doorgaat zonder eerdere pogingen opnieuw af te leiden (echte resume) en nooit een bekende
  doodlopende weg opnieuw probeert.

```bash
loop_journal.py resume                       # what was tried + dead-ends to avoid
loop_journal.py record --iteration N --action "…" --gate fail --gate-output test.log
loop_journal.py stall --k 3 --exit-code      # PROGRESS → re-feed · STALLED → switch/escalate
```

---

## 🎬 Video evidence — Playwright by default, hyperframes on request

De lus produceert **demovideo's** als bewijs dat een wijziging werkt — **twee engines**, één
`video_evidence`-uitbreidingspunt (worker
[`scripts/video_evidence.py`](../scripts/video_evidence.py), contract
[`references/video-evidence.md`](../.claude/skills/simplicio-loop/references/video-evidence.md)):

1. **Standaard — de normale bewijsstroom gebruikt Playwright.** Na een UI-wijziging legt
   `video_evidence` de **echte browsersessie** vast die het scherm aanstuurt (Playwright-native
   video → `.webm`, → `.mp4` met FFmpeg) — het sterkste "werkt, niet alleen compileert"-bewijsstuk
   (Stap 4b) en een geldige bewijs-gepoorte `<promise>`.

   ```bash
   python3 scripts/video_evidence.py verify --url http://localhost:3000/login \
       --name login-demo --expect "Sign in" --issue 42 [--upload --pr 42]
   ```

2. **Op verzoek — een gepersonaliseerde uitlegvideo gebruikt hyperframes.** Wanneer de video zélf
   het op te leveren product is ("make an explainer video of screen X"), rendert de orkestrator een
   **deterministische, ondertitelde diavoorstelling** van de `web_verify`-screenshots met
   [**hyperframes**](https://github.com/heygen-com/hyperframes) (van HeyGen — "dezelfde input,
   dezelfde frames, dezelfde output", CI-reproduceerbaar, geen API-sleutels, lokale render via
   headless Chrome + FFmpeg).

   ```text
   /simplicio-loop make an explainer video of the system login screen
   → detect: video-creation request → web_verify captures the screens
   → video_evidence verify --engine hyperframes → deterministic MP4 → attached to the PR
   ```

Beide engines: een video die nooit opgenomen/gerenderd werd levert **BLOCKED** op, nooit een
nep-pass. Bewijs is altijd een **bestandspad + booleaans oordeel** — nooit videobytes in context
(token-economie).

---

## 📊 Token-economie

| Techniek | Besparing |
|---|---|
| `deterministic_edit` (L0) | 100% van de edit-tokens (bestand mechanisch geschreven, nooit door de LLM) |
| Terminal-first uitvoering | Feiten uit de shell, geen LLM-hallucinatie |
| Output-reductiecatalogus | Plafonds per commandotype (`CAP_ERRORS=20`, `CAP_WARNINGS=10`, `CAP_LIST=20`) — `orient_clamp.py` |
| Tee+CCR-cache bij falen | Voer een gefaald commando nooit opnieuw uit — lees de gecachete output |
| Signatures-only leesmodus | `simplicio-cli signatures <file>` — bestand van 870 regels → 65 regels (**93% bespaard**), bodies weggelaten |
| `simplicio-compress` | Beknopte proza + eenmalige geheugencompactie |
| `orient_clamp.py` | Clamp + tee op elk shell-commando, zonder bedrading |
| Native response-cache | herhaald deterministisch (temp=0) verzoek → bediend vanuit de cache, slaat de LLM-call over (**100% bij hit**) — `simplicio-cli cache`, standaard aan (`SIMPLICIO_CACHE=0` om uit te zetten) |
| Simplicio capture-proxy + MCP | 60-95% minder tokens op tool-outputs via een transparante compressiedaemon |

Besparingen tellen alleen bij een geverifieerd-correcte uitkomst. Baseline = het goedkoopste
verstandige niet-georkestreerde pad naar hetzelfde resultaat. **Besparingsrapportage is
bewijs-gepoort, niet verplicht:** een besparingscijfer wordt alleen getoond wanneer een beurt
daadwerkelijk een economie-producerend commando heeft uitgevoerd en het getal traceerbaar is naar
een gemeten bewijsstuk (clamp-tee, signatures-read, cache-hit, `deterministic_edit`,
`savings_ledger`). Geen gemeten economie → geen besparingsregel; de orkestrator verzint nooit een
baseline of een percentage. Zie `references/token-economy.md`.

### 🔎 `simplicio-loop` draaien: economie versus meting (per runtime)

Twee verschillende dingen gebeuren wanneer je **`simplicio-loop`** aanroept, en ze gedragen zich
verschillend per runtime:

- **Economie** — compressie, output-clamps, signatures-only leesmodus, `deterministic_edit` — geldt
  **elke keer dat de skill draait en `simplicio-orient` / `simplicio-compress` laadt, op elke
  runtime.** Het is het gedrag van de skill plus de hooks (het sterkst waar hooks bestaan:
  `orient_clamp.py` clamp't automatisch op Claude en Cursor; elders is het instructie-gedreven).
- **Meting** — de live-getallen van de Token Monitor — telt alleen verkeer dat **door de
  capture-proxy** stroomt.

| Runtime | Economie (skill) | Meting (monitor) |
|---|---|---|
| **Simplicio Agent** | ✓ | ✓ **automatisch** — al gerouteerd via de proxy (`base_url → :8788`) |
| **Claude** | ✓ (skill + hooks) | ✗ standaard — Claude praat rechtstreeks met `api.anthropic.com`; alleen gemeten zodra gerouteerd (`simplicio-cli wrap claude`, of `ANTHROPIC_BASE_URL → http://127.0.0.1:8788`) |
| **Codex** | ✓ (skill) | ✗ standaard — `simplicio-cli init codex` voegt de MCP-tools toe maar routeert geen LLM-verkeer; gemeten met `simplicio-cli wrap codex` of een OpenAI base-url die naar de proxy wijst |

Dus: de **besparingen gebeuren op elke runtime**; de **monitor telt ze automatisch op Simplicio Agent**, en
op Claude/Codex na een **eenmalige routeringsstap** (`simplicio-cli wrap …` / base-url → `:8788`).
Zonder routering geldt de economie nog steeds — de monitor telt die tokens alleen niet.
`scripts/simplicio-economy.sh wire` doet deze routering voor OpenAI-compatibele clients bij de
installatie.

### 📈 Simplicio Token Monitor

Een live, altijd-aan zicht op de besparingen:

- **Web-dashboard** — `http://127.0.0.1:9090` — realtime token-grafiek, besparingsmeter, de
  LLMs/runtimes en providers die we onderscheppen, en een live proxy-log.
- **Menubalk- / tray-widget** — live bespaarde tokens in de systeemtray (macOS rumps · Windows/Linux pystray).
- **Eén module** — `scripts/simplicio-economy.sh {status|up|wire}` brengt de capture-proxy + monitor
  + tray + de deterministische `simplicio-dev-cli`-operator op en rapporteert de hele stack.

De installatie registreert alle drie als auto-start-services (macOS launchd · Linux systemd ·
Windows Startup) via `scripts/setup_simplicio.sh`, of de cross-platform
`python3 scripts/install_services.py install`. Na installatie draaien de monitor + capture **zonder
de lus aan te roepen** — zie `references/token-capture.md`.

### 🛠️ De capture engine — één native module, elk commando

[`engine/simplicio_engine.py`](../engine/simplicio_engine.py) is de native Simplicio capture engine
— **native, alleen-stdlib, fail-open, zonder externe afhankelijkheid**.
Voer elk commando uit via de [`scripts/simplicio-engine`](../scripts/simplicio-engine)-wrapper
(bijv. `simplicio-engine doctor`):

| Commando | Wat het doet |
|---|---|
| `proxy` | de transparante capture-proxy — routeert elk model naar zijn **echte** provider, comprimeert + meet + cachet (geen model-swap) |
| `doctor` | bereikbaarheid van de proxy + levenslange besparingen |
| `cache` | native response-cache (`stats`/`clear`) — een herhaald deterministisch verzoek wordt vanuit de cache bediend en slaat de LLM-call over |
| `signatures` | signatures-only weergave van een bronbestand (bodies weggelaten, ~93% minder tokens om code te lezen) |
| `semantic` | omkeerbare extractieve (semantic-lite) compressie |
| `detect` | content-type-detectie + slimme routering per blok |
| `rag` | TF-IDF (of `--ml` embedding) retrieval over de CCR-geheugenopslag |
| `memory` | CCR compress-cache-retrieve-opslag (`remember`/`recall`/`forget`/`list`/`stats`) |
| `mcp` | native stdio MCP-server (compress / retrieve / stats tools) |
| `init` / `wrap` | registreer Simplicio in een client (Claude / Codex / Copilot / OpenClaw) · draai een client met capture-routering |
| `report` / `audit` / `capture` / `evals` | besparingsrapport · audit een boom op compressiekansen · dry-run van een verzoek · compressie-regressiepoort |

---

## 🏛️ Ontwerppijlers (in detail)

Vier mechanismen dragen de orkestratiekracht:

| Pijler | Focus | Leeft in |
|---|---|---|
| **DAG + pipeline** | parallellisme per afhankelijkheid, gefaseerd per item | `references/orchestration.md` (Stap 3 pool + pipeline) |
| **Worktree-isolatie** | parallelle edits zonder de boom te corrumperen, merge-gepoort | `references/orchestration.md` |
| **Adversariële verificatie** | een panel van sceptici vóór "delivered" | `references/quality-safety-delivery.md` · skill `simplicio-review` |
| **Bounded loop cap** | anti-infinite-loop, evidence-gated exit | `references/standing-loop-247.md` · skill `simplicio-loop` |

---

## 🚀 Installeren & gebruiken

```bash
git clone https://github.com/wesleysimplicio/simplicio-loop
cd simplicio-loop

# install for your runtime (omit <runtime> to auto-detect)
bash scripts/install.sh <runtime> [--global]        # macOS / Linux
pwsh scripts/install.ps1 <runtime> [-Global]        # Windows
# <runtime> ∈ claude codex vscode cursor antigravity kiro opencode gemini aider simplicio_agent openclaw
```

Of installeer het op Claude Code / Cursor rechtstreeks vanuit de nieuwste GitHub-release (geen marketplace):

```bash
gh release download --repo wesleysimplicio/simplicio-loop --archive tar.gz
tar xzf simplicio-loop-*.tar.gz && cd simplicio-loop-*/
bash scripts/install.sh claude    # or: bash scripts/install.sh cursor
```

Dan:

```
/simplicio-loop finish all the open issues
```

De enige vereiste is **python3** op het PATH (skills, hooks en installer zijn cross-platform
Python). Voor GitHub-bronnen, `git` + een geauthenticeerde `gh`. Zie [`INSTALL.md`](../INSTALL.md)
en [`adapters/MATRIX.md`](../adapters/MATRIX.md).

**Before an unattended 24/7 run:** verify persistent source auth, keep the irreversible-operation human gate + secret-scan enabled, and ensure a reachable STOP/cancel path.

---

## 🔒 Veiligheid (niet onderhandelbaar)

- **Secret-scan** van elke diff; blokkeer bij een treffer.
- **Menselijke poort voor onomkeerbare operaties** — force-push, history-herschrijving, prod-deploy,
  data-/schemaverwijdering, massale bestandsverwijdering → stop en vraag het. Headless + geen
  goedkeurder → verwijder de destructieve capaciteit.
- **Afgedwongen, niet alleen beloofd** — `hooks/action_gate.py` is een **fail-closed**
  `PreToolUse`-/git-pre-push-hook die het bovenstaande (en commits vol secrets) mechanisch blokkeert
  *voordat* ze draaien. Het veiligheidscontract houdt stand zelfs als het model het vergeet.
  `selftest` bewijst de regelset (15/15).
- **4-status pre-executieoordeel** — optimalisatie mag de risicotier van een commando nooit verhogen.
- **Trust-before-load** — perceptie-vormende config (clamp-profielen, suppressielijsten) is niet
  vertrouwd totdat een mens haar reviewt en per hash vastpint.
- **Verharding tegen prompt-injectie** — inhoud van item/PR/commentaar kan het contract nooit
  overschrijven.
- **Harde $-noodstop** voor onbewaakte runs; **bewijs-gepoorte** voltooiing (nooit een vals "done");
  **fail-open** hooks (sluit de agent nooit op in een lus).

---

## ✅ Tests & lokale checks (geen betaalde CI)

Claims worden geverifieerd, niet alleen beweerd — en de poort draait **lokaal**, met nul CI-kosten:

```bash
python3 scripts/check.py            # the whole gate (audit + tests)
```

- **Testsuite** (`tests/`) — de deterministische `selftest`s van de workers, plus een **e2e van de
  loop-driver** (`hooks/loop_stop.py`): hij bewijst dat de lus **stopt op bewijs**, **een kale
  `<promise>` negeert** en **stopt op het plafond** als afzonderlijke uitgangen — en dat de
  bewijsproducenten **BLOKKEREN** (nooit fake-pass) wanneer hun toolchain afwezig is. De gate vereist
  een importeerbare `pytest`; er is geen kale-Python-fallback.
- **Claims-audit** (`scripts/claims_audit.py`, fail-closed) — elke `scripts/*.py` waar de docs naar
  verwijzen bestaat · het aantal uitbreidingspunten klopt over alle bestanden · elk geciteerd
  worker-commando draait daadwerkelijk · de meegeleverde `simplicio_loop/_bundle/`-skills zijn
  **byte-identiek** aan de bron.
- **Draad het als git-pre-push-hook** om `main` gratis eerlijk te houden:
  ```bash
  printf '#!/bin/sh\npython3 scripts/check.py\n' > .git/hooks/pre-push && chmod +x .git/hooks/pre-push
  ```

`pip install "simplicio-loop[dev]"` installeert de verplichte `pytest`-dependency voor `scripts/check.py`.

---

## ⭐ Stergeschiedenis

[![Star History Chart](https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-loop&type=Date)](https://star-history.com/#wesleysimplicio/simplicio-loop&Date)

---

## 📄 Licentie

MIT

<!-- simplicio-loop:github-comment-coordination:v1 -->
## 🌐 Coördinatie via GitHub-opmerkingen tussen runtimes

`simplicio-loop` kan tegelijk draaien in Claude Code, Codex, Cursor, Gemini en Hermes. Een run die aan een GitHub-issue is gekoppeld, publiceert idempotente lifecycle-updates in de canonieke opmerking: claim, planning, voortgang, bewijs, PR en afsluiting. Agents op verschillende machines werken zo in dezelfde GitHub-thread zonder gedeeld lokaal bestandssysteem.

```powershell
pwsh scripts/install.ps1 claude -Global
pwsh scripts/install.ps1 codex -Global
pwsh scripts/install.ps1 cursor -Global
pwsh scripts/install.ps1 gemini -Global
pwsh scripts/install.ps1 hermes -Global   # legacy-alias voor simplicio_agent
```

Lokale queue, leases, worktrees, heartbeats en bewijs blijven actief; GitHub-opmerkingen zijn de gedeelde coördinatieprojectie. Deze flow is alleen voor GitHub: Jira, Azure DevOps en andere trackers ontvangen niets. Zonder GitHub blijft de loop lokaal bruikbaar en wordt de synchronisatiefout vastgelegd, zonder externe bevestiging te verzinnen. Gebruik hetzelfde `source_issue` en GitHub-toegang voor elke runtime.

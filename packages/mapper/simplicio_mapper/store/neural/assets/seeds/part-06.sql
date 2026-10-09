INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:llm-verification','project_skill','skill://simplicio-runtime/llm-verification','skill: llm-verification','---
name: llm-verification
description: verificação independente e adversarial de uma task DEPOIS que o DoD está todo verde, antes de declarar "feito"; ativa ao fechar qualquer task técnica, ao responder "deu ok?" / "verifica de novo", ou quando alguém confunde "verde no DoD" com "concluído de verdade"
---

# Skill: `llm-verification`

DoD todo verde **não** é o mesmo que "feito de verdade". O verde mede *proxy* (teste passou, lint passou, coverage ≥80%); ele não prova que a intenção da task foi atendida. Esta skill é a passada final que fecha esse buraco.

> Princípio central: **uma re-verificação só agrega se for ortogonal à anterior.** Repetir a mesma checagem reproduz o mesmo ponto cego e só serve de teatro. Não basta "+1x igual" — precisa ser de natureza diferente, adversarial.

---

## Trigger

- Ao **fechar** qualquer task técnica com AC mensurável (depois de lint/unit/E2E verdes, antes do commit/PR).
- Quando o usuário pergunta "deu ok?", "verifica de novo", "tudo foi realmente feito?".
- Sempre que houver tentação de declarar concluído só porque o DoD ficou verde.

---

## Steps

1. **Releia a intenção, não o diff.** Abra a AC original da task e cole cada critério lado a lado com o resultado entregue. Para cada um, aponte a **evidência concreta** que o sustenta — não "deve estar ok".
2. **Troque a lente.** Pare de perguntar "tá ok?" (a IA racionaliza o "sim") e pergunte **"onde isto quebra?"**. Liste no mínimo 3 hipóteses de falha.
3. **Exercite a coisa de verdade.** Rode o binário/endpoint/UI real — não só a suíte. Inclua deliberadamente **1 cenário de borda** e **1 caminho de erro** (input vazio, valor extremo, dependência fora, concorrência).
4. **Cace o que o verde não cobre.** Verifique se: a AC foi interpretada torta, o teste testa a coisa errada, a suíte só cobre golden path, há efeito colateral fora do diff.
5. **Garanta independência.** Se a passada usar a mesma lente de quem escreveu, ela não conta. Busque ângulo diferente — delegue a um sub-agent sem o contexto de autoria, ou aos reviewers (`reviewer.agent.md`, `security-reviewer`).
6. **Registre o resultado adversarial.** Anote no PR/`PROGRESS.md` o que você *tentou quebrar* e o que aguentou. Sem isso, a verificação não aconteceu.

---

## Padrões

- **"+1x igual" é teatro.** A passada só conta se mudar de ângulo/lente em relação à anterior.
- **Verde no DoD ≠ feito.** O DoD mede sintoma; valide contra a intenção.
- **Nunca formule como confirmação.** "Deu ok?" enviesa pro "sim". Formule sempre como busca de defeito: "onde falha?".
- **Não existe 100% absoluto.** O alvo é **risco residual aceitável com evidência**, não certeza.
- **Verificação independente > auto-verificação.** Revisor fresco pega o que o autor não vê.

---

## Definition of Done

- [ ] AC relida lado a lado com o resultado, **cada critério com evidência concreta** apontada.
- [ ] Pelo menos **1 cenário de borda + 1 caminho de erro** exercitados ativamente (não só golden path).
- [ ] Feature **rodada de verdade** (binário/endpoint/UI), não apenas a suíte de testes.
- [ ] Passada de verificação é **ortogonal** à anterior (ângulo/lente diferente), não repetição.
- [ ] Resultado adversarial **registrado** (o que tentou quebrar, o que aguentou).
- [ ] Nenhum item verde aceito sem evidência que o sustente.

---

## Exemplo

```text
Task: "CLI deve aceitar --model e cair pro default quando ausente."

Verde no DoD: unit cobre --model=x e ausência -> default. Tudo passa.

Passada adversarial (ortogonal):
  - hipótese 1: --model="" (string vazia, não ausente) -> cai no default? -> NÃO, crasha. BUG.
  - hipótese 2: --model com espaço " gpt " -> trim? -> não trata. risco.
  - hipótese 3: --model repetido duas vezes -> qual vence? -> indefinido.
Registro: 1 bug real (string vazia) que o golden-path-only não pegou.
=> task NÃO estava feita, apesar do verde.
```

---

## Notas

- Esta skill é a operacionalização do item de DoD "Verificação independente/adversarial pós-verde" (ver `AGENTS.md` / `CLAUDE.md`).
- Última revisão: 2026-05-27.
','.simplicio-loop\skills\llm-verification\SKILL.md','e793ae6a439c63fa6083b8a8bb831e3466ed5b44d54a77e5db48f2de538df2cc','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:llm-wiki:skills','project_skill','skill://simplicio-runtime/llm-wiki','skill: llm-wiki','---
name: llm-wiki
description: "Karpathy''s LLM Wiki: build/query interlinked markdown KB."
version: 2.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [wiki, knowledge-base, research, notes, markdown, rag-alternative]
    category: research
    related_skills: [obsidian, arxiv]
---

# Karpathy''s LLM Wiki

Build and maintain a persistent, compounding knowledge base as interlinked markdown files.
Based on [Andrej Karpathy''s LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

Unlike traditional RAG (which rediscovers knowledge from scratch per query), the wiki
compiles knowledge once and keeps it current. Cross-references are already there.
Contradictions have already been flagged. Synthesis reflects everything ingested.

**Division of labor:** The human curates sources and directs analysis. The agent
summarizes, cross-references, files, and maintains consistency.

## When This Skill Activates

Use this skill when the user:
- Asks to create, build, or start a wiki or knowledge base
- Asks to ingest, add, or process a source into their wiki
- Asks a question and an existing wiki is present at the configured path
- Asks to lint, audit, or health-check their wiki
- References their wiki, knowledge base, or "notes" in a research context

## Wiki Location

**Location:** Set via `WIKI_PATH` environment variable (e.g. in `~/.hermes/.env`).

If unset, defaults to `~/wiki`.

```bash
WIKI="${WIKI_PATH:-$HOME/wiki}"
```

The wiki is just a directory of markdown files — open it in Obsidian, VS Code, or
any editor. No database, no special tooling required.

## Architecture: Three Layers

```
wiki/
├── SCHEMA.md           # Conventions, structure rules, domain config
├── index.md            # Sectioned content catalog with one-line summaries
├── log.md              # Chronological action log (append-only, rotated yearly)
├── raw/                # Layer 1: Immutable source material
│   ├── articles/       # Web articles, clippings
│   ├── papers/         # PDFs, arxiv papers
│   ├── transcripts/    # Meeting notes, interviews
│   └── assets/         # Images, diagrams referenced by sources
├── entities/           # Layer 2: Entity pages (people, orgs, products, models)
├── concepts/           # Layer 2: Concept/topic pages
├── comparisons/        # Layer 2: Side-by-side analyses
└── queries/            # Layer 2: Filed query results worth keeping
```

**Layer 1 — Raw Sources:** Immutable. The agent reads but never modifies these.
**Layer 2 — The Wiki:** Agent-owned markdown files. Created, updated, and
cross-referenced by the agent.
**Layer 3 — The Schema:** `SCHEMA.md` defines structure, conventions, and tag taxonomy.

## Resuming an Existing Wiki (CRITICAL — do this every session)

When the user has an existing wiki, **always orient yourself before doing anything**:

① **Read `SCHEMA.md`** — understand the domain, conventions, and tag taxonomy.
② **Read `index.md`** — learn what pages exist and their summaries.
③ **Scan recent `log.md`** — read the last 20-30 entries to understand recent activity.

```bash
WIKI="${WIKI_PATH:-$HOME/wiki}"
# Orientation reads at session start
read_file "$WIKI/SCHEMA.md"
read_file "$WIKI/index.md"
read_file "$WIKI/log.md" offset=<last 30 lines>
```

Only after orientation should you ingest, query, or lint. This prevents:
- Creating duplicate pages for entities that already exist
- Missing cross-references to existing content
- Contradicting the schema''s conventions
- Repeating work already logged

For large wikis (100+ pages), also run a quick `search_files` for the topic
at hand before creating anything new.

## Initializing a New Wiki

When the user asks to create or start a wiki:

1. Determine the wiki path (from `$WIKI_PATH` env var, or ask the user; default `~/wiki`)
2. Create the directory structure above
3. Ask the user what domain the wiki covers — be specific
4. Write `SCHEMA.md` customized to the domain (see template below)
5. Write initial `index.md` with sectioned header
6. Write initial `log.md` with crea','.simplicio-loop\skills\llm-wiki\SKILL.md','4655a95b88fef2a3ebece85a96bc21e0f029fd850e63340493085fd4e5f87994','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:lottie','project_skill','skill://simplicio-runtime/lottie','skill: lottie','---
name: lottie
description: Lottie and dotLottie adapter patterns for HyperFrames. Use when embedding lottie-web JSON animations, .lottie files, @lottiefiles/dotlottie-web players, registering instances on window.__hfLottie, or making After Effects exports deterministic in HyperFrames.
---

# Lottie for HyperFrames

HyperFrames can seek both `lottie-web` and dotLottie players through its `lottie` runtime adapter. Lottie is a strong fit because the animation timeline is already encoded in the asset; HyperFrames only needs a player object it can seek.

## Contract

- Load assets from local project files, usually under `assets/`.
- Set `autoplay: false`.
- Prefer `loop: false` unless the user explicitly wants a loop.
- Register every returned animation or player on `window.__hfLottie`.
- Keep the Lottie container dimensions stable with CSS.

The adapter seeks `lottie-web` with `goToAndStop(timeMs, false)` and dotLottie with frame or percentage APIs depending on player shape.

## lottie-web Pattern

```html
<div id="logo-lottie" class="lottie-layer"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/bodymovin/5.12.2/lottie.min.js"></script>
<script>
  const anim = lottie.loadAnimation({
    container: document.getElementById("logo-lottie"),
    renderer: "svg",
    loop: false,
    autoplay: false,
    path: "assets/logo-reveal.json",
  });

  window.__hfLottie = window.__hfLottie || [];
  window.__hfLottie.push(anim);
</script>
```

```css
.lottie-layer {
  width: 100%;
  height: 100%;
}
```

## dotLottie Pattern

```html
<canvas id="product-lottie" class="lottie-canvas"></canvas>
<script src="https://unpkg.com/@lottiefiles/dotlottie-web"></script>
<script>
  const player = new DotLottie({
    canvas: document.getElementById("product-lottie"),
    src: "assets/product-flow.lottie",
    autoplay: false,
    loop: false,
  });

  window.__hfLottie = window.__hfLottie || [];
  window.__hfLottie.push(player);
</script>
```

```css
.lottie-canvas {
  width: 100%;
  height: 100%;
  display: block;
}
```

## Multiple Animations

Push each player into the same registry:

```js
window.__hfLottie = window.__hfLottie || [];
window.__hfLottie.push(backgroundAnim);
window.__hfLottie.push(iconAnim);
window.__hfLottie.push(confettiAnim);
```

HyperFrames seeks them all to the same composition time.

## Good Uses

- After Effects exports that are already known to render correctly in lottie-web.
- Logo reveals, icon loops, decorative accents, and product UI motion.
- Translating Remotion Lottie usage into plain HyperFrames HTML.

## Avoid

- Relying on remote `path` URLs at render time.
- Starting playback with `play()`.
- Assuming unsupported After Effects effects will survive export. Test the JSON or `.lottie` file in a browser first.
- Loading a player asynchronously and registering it after HyperFrames validation has already inspected the page.

## Validation

After editing a Lottie composition:

```bash
npx hyperframes lint
npx hyperframes validate
```

## Credits And References

- HyperFrames adapter source: `packages/core/src/runtime/adapters/lottie.ts`.
- lottie-web by Airbnb: https://github.com/airbnb/lottie-web
- lottie-web `loadAnimation` options: https://github.com/airbnb/lottie-web/wiki/loadAnimation-options
- dotLottie web player methods by LottieFiles: https://developers.lottiefiles.com/docs/dotlottie-player/dotlottie-web/methods
','.simplicio-loop\skills\lottie\SKILL.md','35551db7646402f60c9622d64534b59a9a4aeaecf63253142bb295b4f6f34d94','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:macos-computer-use','project_skill','skill://simplicio-runtime/macos-computer-use','skill: macos-computer-use','---
name: macos-computer-use
description: |
  Drive the macOS desktop in the background — screenshots, mouse, keyboard,
  scroll, drag — without stealing the user''s cursor, keyboard focus, or
  Space. Works with any tool-capable model. Load this skill whenever the
  `computer_use` tool is available.
version: 1.0.0
platforms: [macos]
metadata:
  hermes:
    tags: [computer-use, macos, desktop, automation, gui]
    category: desktop
    related_skills: [browser]
---

# macOS Computer Use (universal, any-model)

You have a `computer_use` tool that drives the Mac in the **background**.
Your actions do NOT move the user''s cursor, steal keyboard focus, or switch
Spaces. The user can keep typing in their editor while you click around in
Safari in another Space. This is the opposite of pyautogui-style automation.

Everything here works with any tool-capable model — Claude, GPT, Gemini, or
an open model running through a local OpenAI-compatible endpoint. There is
no Anthropic-native schema to learn.

## The canonical workflow

**Step 1 — Capture first.** Almost every task starts with:

```
computer_use(action="capture", mode="som", app="Safari")
```

Returns a screenshot with numbered overlays on every interactable element
AND an AX-tree index like:

```
#1  AXButton ''Back'' @ (12, 80, 28, 28) [Safari]
#2  AXTextField ''Address and Search'' @ (80, 80, 900, 32) [Safari]
#7  AXLink ''Sign In'' @ (900, 420, 80, 24) [Safari]
...
```

**Step 2 — Click by element index.** This is the single most important
habit:

```
computer_use(action="click", element=7)
```

Much more reliable than pixel coordinates for every model. Claude was
trained on both; other models are often only reliable with indices.

**Step 3 — Verify.** After any state-changing action, re-capture. You can
save a round-trip by asking for the post-action capture inline:

```
computer_use(action="click", element=7, capture_after=True)
```

## Capture modes

| `mode` | Returns | Best for |
|---|---|---|
| `som` (default) | Screenshot + numbered overlays + AX index | Vision models; preferred default |
| `vision` | Plain screenshot | When SOM overlay interferes with what you want to verify |
| `ax` | AX tree only, no image | Text-only models, or when you don''t need to see pixels |

## Actions

```
capture           mode=som|vision|ax   app=…  (default: current app)
click             element=N     OR     coordinate=[x, y]
double_click      element=N     OR     coordinate=[x, y]
right_click       element=N     OR     coordinate=[x, y]
middle_click      element=N     OR     coordinate=[x, y]
drag              from_element=N, to_element=M        (or from/to_coordinate)
scroll            direction=up|down|left|right   amount=3 (ticks)
type              text="…"
key               keys="cmd+s" | "return" | "escape" | "ctrl+alt+t"
wait              seconds=0.5
list_apps
focus_app         app="Safari"  raise_window=false   (default: don''t raise)
```

All actions accept optional `capture_after=True` to get a follow-up
screenshot in the same tool call.

All actions that target an element accept `modifiers=["cmd","shift"]` for
held keys.

## Background rules (the whole point)

1. **Never `raise_window=True`** unless the user explicitly asked you to
   bring a window to front. Input routing works without raising.
2. **Scope captures to an app** (`app="Safari"`) — less noisy, fewer
   elements, doesn''t leak other windows the user has open.
3. **Don''t switch Spaces.** cua-driver drives elements on any Space
   regardless of which one is visible.

## Text input patterns

- `type` sends whatever string you give it, respecting the current layout.
  Unicode works.
- For shortcuts use `key` with `+`-joined names:
  - `cmd+s` save
  - `cmd+t` new tab
  - `cmd+w` close tab
  - `return` / `escape` / `tab` / `space`
  - `cmd+shift+g` go to path (Finder)
  - Arrow keys: `up`, `down`, `left`, `right`, optionally with modifiers.

## Drag & drop

Prefer element indices:

```
computer_use(action="drag", from_element=3, to_element=17)
```

For a rubber-band selection on empty canvas, use coordinates:

```
compu','.simplicio-loop\skills\macos-computer-use\SKILL.md','13495469953451eebf320fe78a488a21f88f798fc0a548fa808b8517a31493df','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:manim-video','project_skill','skill://simplicio-runtime/manim-video','skill: manim-video','---
name: manim-video
description: "Manim CE animations: 3Blue1Brown math/algo videos."
version: 1.0.0
platforms: [linux, macos, windows]
---

# Manim Video Production Pipeline

## When to use

Use when users request: animated explanations, math animations, concept visualizations, algorithm walkthroughs, technical explainers, 3Blue1Brown style videos, or any programmatic animation with geometric/mathematical content. Creates 3Blue1Brown-style explainer videos, algorithm visualizations, equation derivations, architecture diagrams, and data stories using Manim Community Edition.

## Creative Standard

This is educational cinema. Every frame teaches. Every animation reveals structure.

**Before writing a single line of code**, articulate the narrative arc. What misconception does this correct? What is the "aha moment"? What visual story takes the viewer from confusion to understanding? The user''s prompt is a starting point — interpret it with pedagogical ambition.

**Geometry before algebra.** Show the shape first, the equation second. Visual memory encodes faster than symbolic memory. When the viewer sees the geometric pattern before the formula, the equation feels earned.

**First-render excellence is non-negotiable.** The output must be visually clear and aesthetically cohesive without revision rounds. If something looks cluttered, poorly timed, or like "AI-generated slides," it is wrong.

**Opacity layering directs attention.** Never show everything at full brightness. Primary elements at 1.0, contextual elements at 0.4, structural elements (axes, grids) at 0.15. The brain processes visual salience in layers.

**Breathing room.** Every animation needs `self.wait()` after it. The viewer needs time to absorb what just appeared. Never rush from one animation to the next. A 2-second pause after a key reveal is never wasted.

**Cohesive visual language.** All scenes share a color palette, consistent typography sizing, matching animation speeds. A technically correct video where every scene uses random different colors is an aesthetic failure.

## Prerequisites

Run `scripts/setup.sh` to verify all dependencies. Requires: Python 3.10+, Manim Community Edition v0.20+ (`pip install manim`), LaTeX (`texlive-full` on Linux, `mactex` on macOS), and ffmpeg. Reference docs tested against Manim CE v0.20.1.

## Modes

| Mode | Input | Output | Reference |
|------|-------|--------|-----------|
| **Concept explainer** | Topic/concept | Animated explanation with geometric intuition | `references/scene-planning.md` |
| **Equation derivation** | Math expressions | Step-by-step animated proof | `references/equations.md` |
| **Algorithm visualization** | Algorithm description | Step-by-step execution with data structures | `references/graphs-and-data.md` |
| **Data story** | Data/metrics | Animated charts, comparisons, counters | `references/graphs-and-data.md` |
| **Architecture diagram** | System description | Components building up with connections | `references/mobjects.md` |
| **Paper explainer** | Research paper | Key findings and methods animated | `references/scene-planning.md` |
| **3D visualization** | 3D concept | Rotating surfaces, parametric curves, spatial geometry | `references/camera-and-3d.md` |

## Stack

Single Python script per project. No browser, no Node.js, no GPU required.

| Layer | Tool | Purpose |
|-------|------|---------|
| Core | Manim Community Edition | Scene rendering, animation engine |
| Math | LaTeX (texlive/MiKTeX) | Equation rendering via `MathTex` |
| Video I/O | ffmpeg | Scene stitching, format conversion, audio muxing |
| TTS | ElevenLabs / Qwen3-TTS (optional) | Narration voiceover |

## Pipeline

```
PLAN --> CODE --> RENDER --> STITCH --> AUDIO (optional) --> REVIEW
```

1. **PLAN** — Write `plan.md` with narrative arc, scene list, visual elements, color palette, voiceover script
2. **CODE** — Write `script.py` with one class per scene, each independently renderable
3. **RENDER** — `manim -ql script.py Scene1 Scene2 ...` for draft, `-qh` for production
4. **STITCH** — ffmpeg concat of scene clips i','.simplicio-loop\skills\manim-video\SKILL.md','46d68d8d8633383e2d5c5f4895666791dddeef324839f94b53b963e26b315959','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:maps','project_skill','skill://simplicio-runtime/maps','skill: maps','---
name: maps
description: "Geocode, POIs, routes, timezones via OpenStreetMap/OSRM."
version: 1.2.0
author: Mibayy
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [maps, geocoding, places, routing, distance, directions, nearby, location, openstreetmap, nominatim, overpass, osrm]
    category: productivity
    requires_toolsets: [terminal]
    supersedes: [find-nearby]
---

# Maps Skill

Location intelligence using free, open data sources. 8 commands, 44 POI
categories, zero dependencies (Python stdlib only), no API key required.

Data sources: OpenStreetMap/Nominatim, Overpass API, OSRM, TimeAPI.io.

This skill supersedes the old `find-nearby` skill — all of find-nearby''s
functionality is covered by the `nearby` command below, with the same
`--near "<place>"` shortcut and multi-category support.

## When to Use

- User sends a Telegram location pin (latitude/longitude in the message) → `nearby`
- User wants coordinates for a place name → `search`
- User has coordinates and wants the address → `reverse`
- User asks for nearby restaurants, hospitals, pharmacies, hotels, etc. → `nearby`
- User wants driving/walking/cycling distance or travel time → `distance`
- User wants turn-by-turn directions between two places → `directions`
- User wants timezone information for a location → `timezone`
- User wants to search for POIs within a geographic area → `area` + `bbox`

## Prerequisites

Python 3.8+ (stdlib only — no pip installs needed).

Script path: `~/.hermes/skills/maps/scripts/maps_client.py`

## Commands

```bash
MAPS=~/.hermes/skills/maps/scripts/maps_client.py
```

### search — Geocode a place name

```bash
python3 $MAPS search "Eiffel Tower"
python3 $MAPS search "1600 Pennsylvania Ave, Washington DC"
```

Returns: lat, lon, display name, type, bounding box, importance score.

### reverse — Coordinates to address

```bash
python3 $MAPS reverse 48.8584 2.2945
```

Returns: full address breakdown (street, city, state, country, postcode).

### nearby — Find places by category

```bash
# By coordinates (from a Telegram location pin, for example)
python3 $MAPS nearby 48.8584 2.2945 restaurant --limit 10
python3 $MAPS nearby 40.7128 -74.0060 hospital --radius 2000

# By address / city / zip / landmark — --near auto-geocodes
python3 $MAPS nearby --near "Times Square, New York" --category cafe
python3 $MAPS nearby --near "90210" --category pharmacy

# Multiple categories merged into one query
python3 $MAPS nearby --near "downtown austin" --category restaurant --category bar --limit 10
```

46 categories: restaurant, cafe, bar, hospital, pharmacy, hotel, guest_house,
camp_site, supermarket, atm, gas_station, parking, museum, park, school,
university, bank, police, fire_station, library, airport, train_station,
bus_stop, church, mosque, synagogue, dentist, doctor, cinema, theatre, gym,
swimming_pool, post_office, convenience_store, bakery, bookshop, laundry,
car_wash, car_rental, bicycle_rental, taxi, veterinary, zoo, playground,
stadium, nightclub.

Each result includes: `name`, `address`, `lat`/`lon`, `distance_m`,
`maps_url` (clickable Google Maps link), `directions_url` (Google Maps
directions from the search point), and promoted tags when available —
`cuisine`, `hours` (opening_hours), `phone`, `website`.

### distance — Travel distance and time

```bash
python3 $MAPS distance "Paris" --to "Lyon"
python3 $MAPS distance "New York" --to "Boston" --mode driving
python3 $MAPS distance "Big Ben" --to "Tower Bridge" --mode walking
```

Modes: driving (default), walking, cycling. Returns road distance, duration,
and straight-line distance for comparison.

### directions — Turn-by-turn navigation

```bash
python3 $MAPS directions "Eiffel Tower" --to "Louvre Museum" --mode walking
python3 $MAPS directions "JFK Airport" --to "Times Square" --mode driving
```

Returns numbered steps with instruction, distance, duration, road name, and
maneuver type (turn, depart, arrive, etc.).

### timezone — Timezone for coordinates

```bash
python3 $MAPS timezone 48.8584 2.2945
python3 $MAPS timezone 35.6762 139.6503
`','.simplicio-loop\skills\maps\SKILL.md','09e3f39af06f3ce387a1ec8b7ce460ff2610b37a4fb437f52eb18720fb8130c6','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:mcporter','project_skill','skill://simplicio-runtime/mcporter','skill: mcporter','---
name: mcporter
description: Use the mcporter CLI to list, configure, auth, and call MCP servers/tools directly (HTTP or stdio), including ad-hoc servers, config edits, and CLI/type generation.
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [MCP, Tools, API, Integrations, Interop]
    homepage: https://mcporter.dev
prerequisites:
  commands: [npx]
---

# mcporter

Use `mcporter` to discover, call, and manage [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) servers and tools directly from the terminal.

## Prerequisites

Requires Node.js:
```bash
# No install needed (runs via npx)
npx mcporter list

# Or install globally
npm install -g mcporter
```

## Quick Start

```bash
# List MCP servers already configured on this machine
mcporter list

# List tools for a specific server with schema details
mcporter list <server> --schema

# Call a tool
mcporter call <server.tool> key=value
```

## Discovering MCP Servers

mcporter auto-discovers servers configured by other MCP clients (Claude Desktop, Cursor, etc.) on the machine. To find new servers to use, browse registries like [mcpfinder.dev](https://mcpfinder.dev) or [mcp.so](https://mcp.so), then connect ad-hoc:

```bash
# Connect to any MCP server by URL (no config needed)
mcporter list --http-url https://some-mcp-server.com --name my_server

# Or run a stdio server on the fly
mcporter list --stdio "npx -y @modelcontextprotocol/server-filesystem" --name fs
```

## Calling Tools

```bash
# Key=value syntax
mcporter call linear.list_issues team=ENG limit:5

# Function syntax
mcporter call "linear.create_issue(title: \"Bug fix needed\")"

# Ad-hoc HTTP server (no config needed)
mcporter call https://api.example.com/mcp.fetch url=https://example.com

# Ad-hoc stdio server
mcporter call --stdio "bun run ./server.ts" scrape url=https://example.com

# JSON payload
mcporter call <server.tool> --args ''{"limit": 5}''

# Machine-readable output (recommended for Hermes)
mcporter call <server.tool> key=value --output json
```

## Auth and Config

```bash
# OAuth login for a server
mcporter auth <server | url> [--reset]

# Manage config
mcporter config list
mcporter config get <key>
mcporter config add <server>
mcporter config remove <server>
mcporter config import <path>
```

Config file location: `./config/mcporter.json` (override with `--config`).

## Daemon

For persistent server connections:
```bash
mcporter daemon start
mcporter daemon status
mcporter daemon stop
mcporter daemon restart
```

## Code Generation

```bash
# Generate a CLI wrapper for an MCP server
mcporter generate-cli --server <name>
mcporter generate-cli --command <url>

# Inspect a generated CLI
mcporter inspect-cli <path> [--json]

# Generate TypeScript types/client
mcporter emit-ts <server> --mode client
mcporter emit-ts <server> --mode types
```

## Notes

- Use `--output json` for structured output that''s easier to parse
- Ad-hoc servers (HTTP URL or `--stdio` command) work without any config — useful for one-off calls
- OAuth auth may require interactive browser flow — use `terminal(command="mcporter auth <server>", pty=true)` if needed
','.simplicio-loop\skills\mcporter\SKILL.md','cfa853b5deabe6b170545bb33337500f22d91a30c9e5ea59456b562fd09d5e98','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:meme-generation','project_skill','skill://simplicio-runtime/meme-generation','skill: meme-generation','---
name: meme-generation
description: Generate real meme images by picking a template and overlaying text with Pillow. Produces actual .png meme files.
version: 2.0.0
author: adanaleycio
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [creative, memes, humor, images]
    related_skills: [ascii-art, generative-widgets]
    category: creative
---

# Meme Generation

Generate actual meme images from a topic. Picks a template, writes captions, and renders a real .png file with text overlay.

## When to Use

- User asks you to make or generate a meme
- User wants a meme about a specific topic, situation, or frustration
- User says "meme this" or similar

## Available Templates

The script supports **any of the ~100 popular imgflip templates** by name or ID, plus 10 curated templates with hand-tuned text positioning.

### Curated Templates (custom text placement)

| ID | Name | Fields | Best for |
|----|------|--------|----------|
| `this-is-fine` | This is Fine | top, bottom | chaos, denial |
| `drake` | Drake Hotline Bling | reject, approve | rejecting/preferring |
| `distracted-boyfriend` | Distracted Boyfriend | distraction, current, person | temptation, shifting priorities |
| `two-buttons` | Two Buttons | left, right, person | impossible choice |
| `expanding-brain` | Expanding Brain | 4 levels | escalating irony |
| `change-my-mind` | Change My Mind | statement | hot takes |
| `woman-yelling-at-cat` | Woman Yelling at Cat | woman, cat | arguments |
| `one-does-not-simply` | One Does Not Simply | top, bottom | deceptively hard things |
| `grus-plan` | Gru''s Plan | step1-3, realization | plans that backfire |
| `batman-slapping-robin` | Batman Slapping Robin | robin, batman | shutting down bad ideas |

### Dynamic Templates (from imgflip API)

Any template not in the curated list can be used by name or imgflip ID. These get smart default text positioning (top/bottom for 2-field, evenly spaced for 3+). Search with:
```bash
python "$SKILL_DIR/scripts/generate_meme.py" --search "disaster"
```

## Procedure

### Mode 1: Classic Template (default)

1. Read the user''s topic and identify the core dynamic (chaos, dilemma, preference, irony, etc.)
2. Pick the template that best matches. Use the "Best for" column, or search with `--search`.
3. Write short captions for each field (8-12 words max per field, shorter is better).
4. Find the skill''s script directory:
   ```
   SKILL_DIR=$(dirname "$(find ~/.hermes/skills -path ''*/meme-generation/SKILL.md'' 2>/dev/null | head -1)")
   ```
5. Run the generator:
   ```bash
   python "$SKILL_DIR/scripts/generate_meme.py" <template_id> /tmp/meme.png "caption 1" "caption 2" ...
   ```
6. Return the image with `MEDIA:/tmp/meme.png`

### Mode 2: Custom AI Image (when image_generate is available)

Use this when no classic template fits, or when the user wants something original.

1. Write the captions first.
2. Use `image_generate` to create a scene that matches the meme concept. Do NOT include any text in the image prompt — text will be added by the script. Describe only the visual scene.
3. Find the generated image path from the image_generate result URL. Download it to a local path if needed.
4. Run the script with `--image` to overlay text, choosing a mode:
   - **Overlay** (text directly on image, white with black outline):
     ```bash
     python "$SKILL_DIR/scripts/generate_meme.py" --image /path/to/scene.png /tmp/meme.png "top text" "bottom text"
     ```
   - **Bars** (black bars above/below with white text — cleaner, always readable):
     ```bash
     python "$SKILL_DIR/scripts/generate_meme.py" --image /path/to/scene.png --bars /tmp/meme.png "top text" "bottom text"
     ```
   Use `--bars` when the image is busy/detailed and text would be hard to read on top of it.
5. **Verify with vision** (if `vision_analyze` is available): Check the result looks good:
   ```
   vision_analyze(image_url="/tmp/meme.png", question="Is the text legible and well-positioned? Does the meme work visually?")
   ```
   If the vision model flags issues (text hard to read, bad ','.simplicio-loop\skills\meme-generation\SKILL.md','0e2487dc0bfa09c24c2862aa73004237ec2f0c2131f87e03f8155bca774870ba','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:memento-flashcards','project_skill','skill://simplicio-runtime/memento-flashcards','skill: memento-flashcards','---
name: memento-flashcards
description: >-
  Spaced-repetition flashcard system. Create cards from facts or text,
  chat with flashcards using free-text answers graded by the agent,
  generate quizzes from YouTube transcripts, review due cards with
  adaptive scheduling, and export/import decks as CSV.
version: 1.0.0
author: Memento AI
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Education, Flashcards, Spaced Repetition, Learning, Quiz, YouTube]
    requires_toolsets: [terminal]
    category: productivity
---

# Memento Flashcards — Spaced-Repetition Flashcard Skill

## Overview

Memento gives you a local, file-based flashcard system with spaced-repetition scheduling.
Users can chat with their flashcards by answering in free text and having the agent grade the response before scheduling the next review.
Use it whenever the user wants to:

- **Remember a fact** — turn any statement into a Q/A flashcard
- **Study with spaced repetition** — review due cards with adaptive intervals and agent-graded free-text answers
- **Quiz from a YouTube video** — fetch a transcript and generate a 5-question quiz
- **Manage decks** — organise cards into collections, export/import CSV

All card data lives in a single JSON file. No external API keys are required — you (the agent) generate flashcard content and quiz questions directly.

User-facing response style for Memento Flashcards:
- Use plain text only. Do not use Markdown formatting in replies to the user.
- Keep review and quiz feedback brief and neutral. Avoid extra praise, pep, or long explanations.

## When to Use

Use this skill when the user wants to:
- Save facts as flashcards for later review
- Review due cards with spaced repetition
- Generate a quiz from a YouTube video transcript
- Import, export, inspect, or delete flashcard data

Do not use this skill for general Q&A, coding help, or non-memory tasks.

## Quick Reference

| User intent | Action |
|---|---|
| "Remember that X" / "save this as a flashcard" | Generate a Q/A card, call `memento_cards.py add` |
| Sends a fact without mentioning flashcards | Ask "Want me to save this as a Memento flashcard?" — only create if confirmed |
| "Create a flashcard" | Ask for Q, A, collection; call `memento_cards.py add` |
| "Review my cards" | Call `memento_cards.py due`, present cards one-by-one |
| "Quiz me on [YouTube URL]" | Call `youtube_quiz.py fetch VIDEO_ID`, generate 5 questions, call `memento_cards.py add-quiz` |
| "Export my cards" | Call `memento_cards.py export --output PATH` |
| "Import cards from CSV" | Call `memento_cards.py import --file PATH --collection NAME` |
| "Show my stats" | Call `memento_cards.py stats` |
| "Delete a card" | Call `memento_cards.py delete --id ID` |
| "Delete a collection" | Call `memento_cards.py delete-collection --collection NAME` |

## Card Storage

Cards are stored in a JSON file at:

```
~/.hermes/skills/productivity/memento-flashcards/data/cards.json
```

**Never edit this file directly.** Always use `memento_cards.py` subcommands. The script handles atomic writes (write to temp file, then rename) to prevent corruption.

The file is created automatically on first use.

## Procedure

### Creating Cards from Facts

### Activation Rules

Not every factual statement should become a flashcard. Use this three-tier check:

1. **Explicit intent** — the user mentions "memento", "flashcard", "remember this", "save this card", "add a card", or similar phrasing that clearly requests a flashcard → **create the card directly**, no confirmation needed.
2. **Implicit intent** — the user sends a factual statement without mentioning flashcards (e.g. "The speed of light is 299,792 km/s") → **ask first**: "Want me to save this as a Memento flashcard?" Only create the card if the user confirms.
3. **No intent** — the message is a coding task, a question, instructions, normal conversation, or anything that is clearly not a fact to memorize → **do NOT activate this skill at all**. Let other skills or default behavior handle it.

When activation is confirmed (tier 1 directly, tier 2 ','.simplicio-loop\skills\memento-flashcards\SKILL.md','b4a9a4f3531987f972551ad91a6eca5f35db21a1a8c61b3bc5455f500919f0ce','skill,simplicio,content',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:merger-model','project_skill','skill://simplicio-runtime/merger-model','skill: merger-model','---
name: merger-model
description: Build accretion/dilution (merger) models in Excel — pro-forma P&L, synergies, financing mix, EPS impact. Pairs with excel-author. Use for M&A pitches, board materials, or deal evaluation.
version: 1.0.0
author: Anthropic (adapted by Nous Research)
license: Apache-2.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [finance, m-and-a, merger, accretion-dilution, excel, openpyxl, modeling, investment-banking]
    related_skills: [excel-author, pptx-author, dcf-model, 3-statement-model]
---

## Environment

This skill assumes **headless openpyxl** — you are producing an .xlsx file on disk.
Follow the `excel-author` skill''s conventions for cell coloring, formulas, named ranges, and sensitivity tables.
Recalculate before delivery: `python /path/to/excel-author/scripts/recalc.py ./out/model.xlsx`.

# Merger Model

Build accretion/dilution analysis for M&A transactions. Models pro forma EPS impact, synergy sensitivities, and purchase price allocation. Use when evaluating a potential acquisition, preparing merger consequences analysis for a pitch, or advising on deal terms.

## Workflow

### Step 1: Gather Inputs

**Acquirer:**
- Company name, current share price, shares outstanding
- LTM and NTM EPS (GAAP and adjusted)
- P/E multiple
- Pre-tax cost of debt, tax rate
- Cash on balance sheet, existing debt

**Target:**
- Company name, current share price, shares outstanding (if public)
- LTM and NTM EPS or net income
- Enterprise value or equity value

**Deal Terms:**
- Offer price per share (or premium to current)
- Consideration mix: % cash vs. % stock
- New debt raised to fund cash portion
- Expected synergies (revenue and cost) and phase-in timeline
- Transaction fees and financing costs
- Expected close date

### Step 2: Purchase Price Analysis

| Item | Value |
|------|-------|
| Offer price per share | |
| Premium to current | |
| Equity value | |
| Plus: net debt assumed | |
| Enterprise value | |
| EV / EBITDA implied | |
| P/E implied | |

### Step 3: Sources & Uses

| Sources | $ | Uses | $ |
|---------|---|------|---|
| New debt | | Equity purchase price | |
| Cash on hand | | Refinance target debt | |
| New equity issued | | Transaction fees | |
| | | Financing fees | |
| **Total** | | **Total** | |

### Step 4: Pro Forma EPS (Accretion / Dilution)

Calculate year-by-year (Year 1-3):

| | Standalone | Pro Forma | Accretion/(Dilution) |
|---|-----------|-----------|---------------------|
| Acquirer net income | | | |
| Target net income | | | |
| Synergies (after tax) | | | |
| Foregone interest on cash (after tax) | | | |
| New debt interest (after tax) | | | |
| Intangible amortization (after tax) | | | |
| Pro forma net income | | | |
| Pro forma shares | | | |
| **Pro forma EPS** | | | |
| **Accretion / (Dilution) %** | | | |

### Step 5: Sensitivity Analysis

**Accretion/Dilution vs. Synergies and Offer Premium:**

| | $0M syn | $25M syn | $50M syn | $75M syn | $100M syn |
|---|---------|----------|----------|----------|-----------|
| 15% premium | | | | | |
| 20% premium | | | | | |
| 25% premium | | | | | |
| 30% premium | | | | | |

**Accretion/Dilution vs. Cash/Stock Mix:**

| | 100% cash | 75/25 | 50/50 | 25/75 | 100% stock |
|---|-----------|-------|-------|-------|------------|
| Year 1 | | | | | |
| Year 2 | | | | | |

### Step 6: Breakeven Synergies

Calculate the minimum synergies needed for the deal to be EPS-neutral in Year 1.

### Step 7: Output

- Excel workbook with:
  - Assumptions tab
  - Sources & uses
  - Pro forma income statement
  - Accretion/dilution summary
  - Sensitivity tables
  - Breakeven analysis
- One-page merger consequences summary for pitch book

## Important Notes

- Always show both GAAP and adjusted (cash) EPS where relevant
- Stock deals: use acquirer''s current price for exchange ratio, note dilution from new shares
- Include purchase price allocation — goodwill and intangible amortization matter for GAAP EPS
- Synergy phase-in is critical — Year 1 is often only 25-50% of run-rate synergies
- Don''t forget foregone interest i','.simplicio-loop\skills\merger-model\SKILL.md','3cfae930455746d90b7f2f0c1ea338460ce778a472f0d3e436f208ee26ba8f5c','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:minecraft-modpack-server','project_skill','skill://simplicio-runtime/minecraft-modpack-server','skill: minecraft-modpack-server','---
name: minecraft-modpack-server
description: "Host modded Minecraft servers (CurseForge, Modrinth)."
tags: [minecraft, gaming, server, neoforge, forge, modpack]
platforms: [linux, macos]
---

# Minecraft Modpack Server Setup

## When to use
- User wants to set up a modded Minecraft server from a server pack zip
- User needs help with NeoForge/Forge server configuration
- User asks about Minecraft server performance tuning or backups

## Gather User Preferences First
Before starting setup, ask the user for:
- **Server name / MOTD** — what should it say in the server list?
- **Seed** — specific seed or random?
- **Difficulty** — peaceful / easy / normal / hard?
- **Gamemode** — survival / creative / adventure?
- **Online mode** — true (Mojang auth, legit accounts) or false (LAN/cracked friendly)?
- **Player count** — how many players expected? (affects RAM & view distance tuning)
- **RAM allocation** — or let agent decide based on mod count & available RAM?
- **View distance / simulation distance** — or let agent pick based on player count & hardware?
- **PvP** — on or off?
- **Whitelist** — open server or whitelist only?
- **Backups** — want automated backups? How often?

Use sensible defaults if the user doesn''t care, but always ask before generating the config.

## Steps

### 1. Download & Inspect the Pack
```bash
mkdir -p ~/minecraft-server
cd ~/minecraft-server
wget -O serverpack.zip "<URL>"
unzip -o serverpack.zip -d server
ls server/
```
Look for: `startserver.sh`, installer jar (neoforge/forge), `user_jvm_args.txt`, `mods/` folder.
Check the script to determine: mod loader type, version, and required Java version.

### 2. Install Java
- Minecraft 1.21+ → Java 21: `sudo apt install openjdk-21-jre-headless`
- Minecraft 1.18-1.20 → Java 17: `sudo apt install openjdk-17-jre-headless`
- Minecraft 1.16 and below → Java 8: `sudo apt install openjdk-8-jre-headless`
- Verify: `java -version`

### 3. Install the Mod Loader
Most server packs include an install script. Use the INSTALL_ONLY env var to install without launching:
```bash
cd ~/minecraft-server/server
ATM10_INSTALL_ONLY=true bash startserver.sh
# Or for generic Forge packs:
# java -jar forge-*-installer.jar --installServer
```
This downloads libraries, patches the server jar, etc.

### 4. Accept EULA
```bash
echo "eula=true" > ~/minecraft-server/server/eula.txt
```

### 5. Configure server.properties
Key settings for modded/LAN:
```properties
motd=\u00a7b\u00a7lServer Name \u00a7r\u00a78| \u00a7aModpack Name
server-port=25565
online-mode=true          # false for LAN without Mojang auth
enforce-secure-profile=true  # match online-mode
difficulty=hard            # most modpacks balance around hard
allow-flight=true          # REQUIRED for modded (flying mounts/items)
spawn-protection=0         # let everyone build at spawn
max-tick-time=180000       # modded needs longer tick timeout
enable-command-block=true
```

Performance settings (scale to hardware):
```properties
# 2 players, beefy machine:
view-distance=16
simulation-distance=10

# 4-6 players, moderate machine:
view-distance=10
simulation-distance=6

# 8+ players or weaker hardware:
view-distance=8
simulation-distance=4
```

### 6. Tune JVM Args (user_jvm_args.txt)
Scale RAM to player count and mod count. Rule of thumb for modded:
- 100-200 mods: 6-12GB
- 200-350+ mods: 12-24GB
- Leave at least 8GB free for the OS/other tasks

```
-Xms12G
-Xmx24G
-XX:+UseG1GC
-XX:+ParallelRefProcEnabled
-XX:MaxGCPauseMillis=200
-XX:+UnlockExperimentalVMOptions
-XX:+DisableExplicitGC
-XX:+AlwaysPreTouch
-XX:G1NewSizePercent=30
-XX:G1MaxNewSizePercent=40
-XX:G1HeapRegionSize=8M
-XX:G1ReservePercent=20
-XX:G1HeapWastePercent=5
-XX:G1MixedGCCountTarget=4
-XX:InitiatingHeapOccupancyPercent=15
-XX:G1MixedGCLiveThresholdPercent=90
-XX:G1RSetUpdatingPauseTimePercent=5
-XX:SurvivorRatio=32
-XX:+PerfDisableSharedMem
-XX:MaxTenuringThreshold=1
```

### 7. Open Firewall
```bash
sudo ufw allow 25565/tcp comment "Minecraft Server"
```
Check with: `sudo ufw status | grep 25565`

### 8. Create Launch Script
```bash
cat > ~/start-minecraf','.simplicio-loop\skills\minecraft-modpack-server\SKILL.md','58948be8715e7eb785833b3181b07a547fd4757bdb0d3114f02ef0e10ff85bd3','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:modal','project_skill','skill://simplicio-runtime/modal','skill: modal','---
name: modal-serverless-gpu
description: Serverless GPU cloud platform for running ML workloads. Use when you need on-demand GPU access without infrastructure management, deploying ML models as APIs, or running batch jobs with automatic scaling.
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [modal>=0.64.0]
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Infrastructure, Serverless, GPU, Cloud, Deployment, Modal]

---

# Modal Serverless GPU

Comprehensive guide to running ML workloads on Modal''s serverless GPU cloud platform.

## When to use Modal

**Use Modal when:**
- Running GPU-intensive ML workloads without managing infrastructure
- Deploying ML models as auto-scaling APIs
- Running batch processing jobs (training, inference, data processing)
- Need pay-per-second GPU pricing without idle costs
- Prototyping ML applications quickly
- Running scheduled jobs (cron-like workloads)

**Key features:**
- **Serverless GPUs**: T4, L4, A10G, L40S, A100, H100, H200, B200 on-demand
- **Python-native**: Define infrastructure in Python code, no YAML
- **Auto-scaling**: Scale to zero, scale to 100+ GPUs instantly
- **Sub-second cold starts**: Rust-based infrastructure for fast container launches
- **Container caching**: Image layers cached for rapid iteration
- **Web endpoints**: Deploy functions as REST APIs with zero-downtime updates

**Use alternatives instead:**
- **RunPod**: For longer-running pods with persistent state
- **Lambda Labs**: For reserved GPU instances
- **SkyPilot**: For multi-cloud orchestration and cost optimization
- **Kubernetes**: For complex multi-service architectures

## Quick start

### Installation

```bash
pip install modal
modal setup  # Opens browser for authentication
```

### Hello World with GPU

```python
import modal

app = modal.App("hello-gpu")

@app.function(gpu="T4")
def gpu_info():
    import subprocess
    return subprocess.run(["nvidia-smi"], capture_output=True, text=True).stdout

@app.local_entrypoint()
def main():
    print(gpu_info.remote())
```

Run: `modal run hello_gpu.py`

### Basic inference endpoint

```python
import modal

app = modal.App("text-generation")
image = modal.Image.debian_slim().pip_install("transformers", "torch", "accelerate")

@app.cls(gpu="A10G", image=image)
class TextGenerator:
    @modal.enter()
    def load_model(self):
        from transformers import pipeline
        self.pipe = pipeline("text-generation", model="gpt2", device=0)

    @modal.method()
    def generate(self, prompt: str) -> str:
        return self.pipe(prompt, max_length=100)[0]["generated_text"]

@app.local_entrypoint()
def main():
    print(TextGenerator().generate.remote("Hello, world"))
```

## Core concepts

### Key components

| Component | Purpose |
|-----------|---------|
| `App` | Container for functions and resources |
| `Function` | Serverless function with compute specs |
| `Cls` | Class-based functions with lifecycle hooks |
| `Image` | Container image definition |
| `Volume` | Persistent storage for models/data |
| `Secret` | Secure credential storage |

### Execution modes

| Command | Description |
|---------|-------------|
| `modal run script.py` | Execute and exit |
| `modal serve script.py` | Development with live reload |
| `modal deploy script.py` | Persistent cloud deployment |

## GPU configuration

### Available GPUs

| GPU | VRAM | Best For |
|-----|------|----------|
| `T4` | 16GB | Budget inference, small models |
| `L4` | 24GB | Inference, Ada Lovelace arch |
| `A10G` | 24GB | Training/inference, 3.3x faster than T4 |
| `L40S` | 48GB | Recommended for inference (best cost/perf) |
| `A100-40GB` | 40GB | Large model training |
| `A100-80GB` | 80GB | Very large models |
| `H100` | 80GB | Fastest, FP8 + Transformer Engine |
| `H200` | 141GB | Auto-upgrade from H100, 4.8TB/s bandwidth |
| `B200` | Latest | Blackwell architecture |

### GPU specification patterns

```python
# Single GPU
@app.function(gpu="A100")

# Specific memory variant
@app.function(gpu="A100-80GB")

# Multiple GPUs (up to 8)
@app.function(gpu="H100:4")

','.simplicio-loop\skills\modal\SKILL.md','ddb146766a795d9e13f6b73b5b8bf060ac4baf289e7f94618322d67364286bd8','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:nano-pdf','project_skill','skill://simplicio-runtime/nano-pdf','skill: nano-pdf','---
name: nano-pdf
description: "Edit PDF text/typos/titles via nano-pdf CLI (NL prompts)."
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [PDF, Documents, Editing, NLP, Productivity]
    homepage: https://pypi.org/project/nano-pdf/
---

# nano-pdf

Edit PDFs using natural-language instructions. Point it at a page and describe what to change.

## Prerequisites

```bash
# Install with uv (recommended — already available in Hermes)
uv pip install nano-pdf

# Or with pip
pip install nano-pdf
```

## Usage

```bash
nano-pdf edit <file.pdf> <page_number> "<instruction>"
```

## Examples

```bash
# Change a title on page 1
nano-pdf edit deck.pdf 1 "Change the title to ''Q3 Results'' and fix the typo in the subtitle"

# Update a date on a specific page
nano-pdf edit report.pdf 3 "Update the date from January to February 2026"

# Fix content
nano-pdf edit contract.pdf 2 "Change the client name from ''Acme Corp'' to ''Acme Industries''"
```

## Notes

- Page numbers may be 0-based or 1-based depending on version — if the edit hits the wrong page, retry with ±1
- Always verify the output PDF after editing (use `read_file` to check file size, or open it)
- The tool uses an LLM under the hood — requires an API key (check `nano-pdf --help` for config)
- Works well for text changes; complex layout modifications may need a different approach
','.simplicio-loop\skills\nano-pdf\SKILL.md','4243b329789c6d7fcea95749438228e5f8cbc0234cd44d2d72cd86f837bf1f35','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:nemo-curator','project_skill','skill://simplicio-runtime/nemo-curator','skill: nemo-curator','---
name: nemo-curator
description: GPU-accelerated data curation for LLM training. Supports text/image/video/audio. Features fuzzy deduplication (16× faster), quality filtering (30+ heuristics), semantic deduplication, PII redaction, NSFW detection. Scales across GPUs with RAPIDS. Use for preparing high-quality training datasets, cleaning web data, or deduplicating large corpora.
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [nemo-curator, cudf, dask, rapids]
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Data Processing, NeMo Curator, Data Curation, GPU Acceleration, Deduplication, Quality Filtering, NVIDIA, RAPIDS, PII Redaction, Multimodal, LLM Training Data]

---

# NeMo Curator - GPU-Accelerated Data Curation

NVIDIA''s toolkit for preparing high-quality training data for LLMs.

## When to use NeMo Curator

**Use NeMo Curator when:**
- Preparing LLM training data from web scrapes (Common Crawl)
- Need fast deduplication (16× faster than CPU)
- Curating multi-modal datasets (text, images, video, audio)
- Filtering low-quality or toxic content
- Scaling data processing across GPU cluster

**Performance**:
- **16× faster** fuzzy deduplication (8TB RedPajama v2)
- **40% lower TCO** vs CPU alternatives
- **Near-linear scaling** across GPU nodes

**Use alternatives instead**:
- **datatrove**: CPU-based, open-source data processing
- **dolma**: Allen AI''s data toolkit
- **Ray Data**: General ML data processing (no curation focus)

## Quick start

### Installation

```bash
# Text curation (CUDA 12)
uv pip install "nemo-curator[text_cuda12]"

# All modalities
uv pip install "nemo-curator[all_cuda12]"

# CPU-only (slower)
uv pip install "nemo-curator[cpu]"
```

### Basic text curation pipeline

```python
from nemo_curator import ScoreFilter, Modify
from nemo_curator.datasets import DocumentDataset
import pandas as pd

# Load data
df = pd.DataFrame({"text": ["Good document", "Bad doc", "Excellent text"]})
dataset = DocumentDataset(df)

# Quality filtering
def quality_score(doc):
    return len(doc["text"].split()) > 5  # Filter short docs

filtered = ScoreFilter(quality_score)(dataset)

# Deduplication
from nemo_curator.modules import ExactDuplicates
deduped = ExactDuplicates()(filtered)

# Save
deduped.to_parquet("curated_data/")
```

## Data curation pipeline

### Stage 1: Quality filtering

```python
from nemo_curator.filters import (
    WordCountFilter,
    RepeatedLinesFilter,
    UrlRatioFilter,
    NonAlphaNumericFilter
)

# Apply 30+ heuristic filters
from nemo_curator import ScoreFilter

# Word count filter
dataset = dataset.filter(WordCountFilter(min_words=50, max_words=100000))

# Remove repetitive content
dataset = dataset.filter(RepeatedLinesFilter(max_repeated_line_fraction=0.3))

# URL ratio filter
dataset = dataset.filter(UrlRatioFilter(max_url_ratio=0.2))
```

### Stage 2: Deduplication

**Exact deduplication**:
```python
from nemo_curator.modules import ExactDuplicates

# Remove exact duplicates
deduped = ExactDuplicates(id_field="id", text_field="text")(dataset)
```

**Fuzzy deduplication** (16× faster on GPU):
```python
from nemo_curator.modules import FuzzyDuplicates

# MinHash + LSH deduplication
fuzzy_dedup = FuzzyDuplicates(
    id_field="id",
    text_field="text",
    num_hashes=260,      # MinHash parameters
    num_buckets=20,
    hash_method="md5"
)

deduped = fuzzy_dedup(dataset)
```

**Semantic deduplication**:
```python
from nemo_curator.modules import SemanticDuplicates

# Embedding-based deduplication
semantic_dedup = SemanticDuplicates(
    id_field="id",
    text_field="text",
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    threshold=0.8  # Cosine similarity threshold
)

deduped = semantic_dedup(dataset)
```

### Stage 3: PII redaction

```python
from nemo_curator.modules import Modify
from nemo_curator.modifiers import PIIRedactor

# Redact personally identifiable information
pii_redactor = PIIRedactor(
    supported_entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON", "LOCATION"],
    anonymize_action="replace"  # or "redact"
)

redacted ','.simplicio-loop\skills\nemo-curator\SKILL.md','547554d3131520680cf715727b69e08455ed5319354a59c9df4ef65e3889a213','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:neuroskill-bci','project_skill','skill://simplicio-runtime/neuroskill-bci','skill: neuroskill-bci','---
name: neuroskill-bci
description: >
  Connect to a running NeuroSkill instance and incorporate the user''s real-time
  cognitive and emotional state (focus, relaxation, mood, cognitive load, drowsiness,
  heart rate, HRV, sleep staging, and 40+ derived EXG scores) into responses.
  Requires a BCI wearable (Muse 2/S or OpenBCI) and the NeuroSkill desktop app
  running locally.
platforms: [linux, macos, windows]
version: 1.0.0
author: Hermes Agent + Nous Research
license: MIT
metadata:
  hermes:
    tags: [BCI, neurofeedback, health, focus, EEG, cognitive-state, biometrics, neuroskill]
    category: health
    related_skills: []
---

# NeuroSkill BCI Integration

Connect Hermes to a running [NeuroSkill](https://neuroskill.com/) instance to read
real-time brain and body metrics from a BCI wearable. Use this to give
cognitively-aware responses, suggest interventions, and track mental performance
over time.

> **⚠️ Research Use Only** — NeuroSkill is an open-source research tool. It is
> NOT a medical device and has NOT been cleared by the FDA, CE, or any regulatory
> body. Never use these metrics for clinical diagnosis or treatment.

See `references/metrics.md` for the full metric reference, `references/protocols.md`
for intervention protocols, and `references/api.md` for the WebSocket/HTTP API.

---

## Prerequisites

- **Node.js 20+** installed (`node --version`)
- **NeuroSkill desktop app** running with a connected BCI device
- **BCI hardware**: Muse 2, Muse S, or OpenBCI (4-channel EEG + PPG + IMU via BLE)
- `npx neuroskill status` returns data without errors

### Verify Setup
```bash
node --version                    # Must be 20+
npx neuroskill status             # Full system snapshot
npx neuroskill status --json      # Machine-parseable JSON
```

If `npx neuroskill status` returns an error, tell the user:
- Make sure the NeuroSkill desktop app is open
- Ensure the BCI device is powered on and connected via Bluetooth
- Check signal quality — green indicators in NeuroSkill (≥0.7 per electrode)
- If `command not found`, install Node.js 20+

---

## CLI Reference: `npx neuroskill <command>`

All commands support `--json` (raw JSON, pipe-safe) and `--full` (human summary + JSON).

| Command | Description |
|---------|-------------|
| `status` | Full system snapshot: device, scores, bands, ratios, sleep, history |
| `session [N]` | Single session breakdown with first/second half trends (0=most recent) |
| `sessions` | List all recorded sessions across all days |
| `search` | ANN similarity search for neurally similar historical moments |
| `compare` | A/B session comparison with metric deltas and trend analysis |
| `sleep [N]` | Sleep stage classification (Wake/N1/N2/N3/REM) with analysis |
| `label "text"` | Create a timestamped annotation at the current moment |
| `search-labels "query"` | Semantic vector search over past labels |
| `interactive "query"` | Cross-modal 4-layer graph search (text → EXG → labels) |
| `listen` | Real-time event streaming (default 5s, set `--seconds N`) |
| `umap` | 3D UMAP projection of session embeddings |
| `calibrate` | Open calibration window and start a profile |
| `timer` | Launch focus timer (Pomodoro/Deep Work/Short Focus presets) |
| `notify "title" "body"` | Send an OS notification via the NeuroSkill app |
| `raw ''{json}''` | Raw JSON passthrough to the server |

### Global Flags
| Flag | Description |
|------|-------------|
| `--json` | Raw JSON output (no ANSI, pipe-safe) |
| `--full` | Human summary + colorized JSON |
| `--port <N>` | Override server port (default: auto-discover, usually 8375) |
| `--ws` | Force WebSocket transport |
| `--http` | Force HTTP transport |
| `--k <N>` | Nearest neighbors count (search, search-labels) |
| `--seconds <N>` | Duration for listen (default: 5) |
| `--trends` | Show per-session metric trends (sessions) |
| `--dot` | Graphviz DOT output (interactive) |

---

## 1. Checking Current State

### Get Live Metrics
```bash
npx neuroskill status --json
```

**Always use `--json`** for reliable parsing. The default output is colorized
human-readab','.simplicio-loop\skills\neuroskill-bci\SKILL.md','dacfa0b7899a0a7e645b68f02c898c86d2d837d015f89b42b957e8dbd61de41e','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:node-inspect-debugger','project_skill','skill://simplicio-runtime/node-inspect-debugger','skill: node-inspect-debugger','---
name: node-inspect-debugger
description: "Debug Node.js via --inspect + Chrome DevTools Protocol CLI."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [debugging, nodejs, node-inspect, cdp, breakpoints, ui-tui]
    related_skills: [systematic-debugging, python-debugpy, debugging-hermes-tui-commands]
---

# Node.js Inspect Debugger

## Overview

When `console.log` isn''t enough, drive Node''s built-in V8 inspector programmatically from the terminal. You get real breakpoints, step in/over/out, call-stack walking, local/closure scope dumps, and arbitrary expression evaluation in the paused frame.

Two tools, pick one:

- **`node inspect`** — built-in, zero install, CLI REPL. Best for quick poking.
- **`ndb` / CDP via `chrome-remote-interface`** — scriptable from Node/Python; best when you want to automate many breakpoints, collect state across runs, or debug non-interactively from an agent loop.

**Prefer `node inspect` first.** It''s always available and the REPL is fast.

## When to Use

- A Node test fails and you need to see intermediate state
- ui-tui crashes or behaves wrong and you want to inspect React/Ink state pre-render
- tui_gateway child processes (`_SlashWorker`, PTY bridge workers) misbehave
- You need to inspect a value in a closure that `console.log` can''t reach without patching
- Perf: attach to a running process to capture a CPU profile or heap snapshot

**Don''t use for:** things `console.log` solves in under a minute. Breakpoint-driven debugging is heavier; use it when the payoff is real.

## Quick Reference: `node inspect` REPL

Launch paused on first line:

```bash
node inspect path/to/script.js
# or with tsx
node --inspect-brk $(which tsx) path/to/script.ts
```

The `debug>` prompt accepts:

| Command | Action |
|---|---|
| `c` or `cont` | continue |
| `n` or `next` | step over |
| `s` or `step` | step into |
| `o` or `out` | step out |
| `pause` | pause running code |
| `sb(''file.js'', 42)` | set breakpoint at file.js line 42 |
| `sb(42)` | set breakpoint at line 42 of current file |
| `sb(''functionName'')` | break when function is called |
| `cb(''file.js'', 42)` | clear breakpoint |
| `breakpoints` | list all breakpoints |
| `bt` | backtrace (call stack) |
| `list(5)` | show 5 lines of source around current position |
| `watch(''expr'')` | evaluate expr on every pause |
| `watchers` | show watched expressions |
| `repl` | drop into REPL in current scope (Ctrl+C to exit REPL) |
| `exec expr` | evaluate expression once |
| `restart` | restart script |
| `kill` | kill the script |
| `.exit` | quit debugger |

**In the `repl` sub-mode:** type any JS expression, including access to locals/closure variables. `Ctrl+C` exits back to `debug>`.

## Attaching to a Running Process

When the process is already running (e.g. a long-lived dev server or the TUI gateway):

```bash
# 1. Send SIGUSR1 to enable the inspector on an existing process
kill -SIGUSR1 <pid>
# Node prints: Debugger listening on ws://127.0.0.1:9229/<uuid>

# 2. Attach the debugger CLI
node inspect -p <pid>
# or by URL
node inspect ws://127.0.0.1:9229/<uuid>
```

To start a process with the inspector from the beginning:

```bash
node --inspect script.js           # listen on 127.0.0.1:9229, keep running
node --inspect-brk script.js       # listen AND pause on first line
node --inspect=0.0.0.0:9230 script.js   # custom host:port
```

For TypeScript via tsx:

```bash
node --inspect-brk --import tsx script.ts
# or older tsx
node --inspect-brk -r tsx/cjs script.ts
```

## Programmatic CDP (scripting from terminal)

When you want to automate — set many breakpoints, capture scope state, script a repro — use `chrome-remote-interface`:

```bash
npm i -g chrome-remote-interface        # or project-local
# Start your target:
node --inspect-brk=9229 target.js &
```

Driver script (save as `/tmp/cdp-debug.js`):

```javascript
const CDP = require(''chrome-remote-interface'');

(async () => {
  const client = await CDP({ port: 9229 });
  const { Debugger, Runtime } = client;

  Debugger.paused(async ','.simplicio-loop\skills\node-inspect-debugger\SKILL.md','7a01e3774442cff79989b8d3a030fe1ffb652ba095dfc5b0f09ad3947aec3054','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:notion','project_skill','skill://simplicio-runtime/notion','skill: notion','---
name: notion
description: "Notion API + ntn CLI: pages, databases, markdown, Workers."
version: 2.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
prerequisites:
  env_vars: [NOTION_API_KEY]
metadata:
  hermes:
    tags: [Notion, Productivity, Notes, Database, API, CLI, Workers]
    homepage: https://developers.notion.com
---

# Notion

Talk to Notion two ways. Same integration token works for both — pick by what''s available.

◆ **`ntn` CLI** — Notion''s official CLI. Shorter syntax, one-line file uploads, required for Workers. macOS + Linux only as of May 2026 (Windows support "coming soon"). **Default when installed.**
◆ **HTTP + curl** — works everywhere including Windows. **Default fallback** when `ntn` isn''t installed.

## Setup

### 1. Get an integration token (required for both paths)

1. Create an integration at https://notion.so/my-integrations
2. Copy the API key (starts with `ntn_` or `secret_`)
3. Store in `~/.hermes/.env`:
   ```
   NOTION_API_KEY=ntn_your_key_here
   ```
4. **Share target pages/databases with the integration** in Notion: page menu `...` → `Connect to` → your integration name. Without this, the API returns 404 for that page even though it exists.

### 2. Install `ntn` (preferred path on macOS / Linux)

```bash
# Recommended
curl -fsSL https://ntn.dev | bash

# Or via npm (needs Node 22+, npm 10+)
npm install --global ntn

ntn --version    # verify
```

**Skip `ntn login` — use the integration token instead.** This works headlessly, no browser needed:
```bash
export NOTION_API_TOKEN=$NOTION_API_KEY      # ntn reads NOTION_API_TOKEN
export NOTION_KEYRING=0                       # don''t try to use the OS keychain
```

Add those exports to your shell profile (or to `~/.hermes/.env`) so every session inherits them.

### 3. Choose path at runtime

```bash
if command -v ntn >/dev/null 2>&1; then
  # use ntn
else
  # fall back to curl
fi
```

Windows users: skip step 2 entirely until native `ntn` ships — Path B works fine. If you want CLI ergonomics now, install `ntn` inside WSL2.

## API Basics

`Notion-Version: 2025-09-03` is required on all HTTP requests. `ntn` handles this for you. In this version, what users call "databases" are called **data sources** in the API.

## Path A — `ntn` CLI (preferred, macOS / Linux)

### Raw API calls (shorthand for curl)
```bash
ntn api v1/users                                  # GET
ntn api v1/pages parent[page_id]=abc123 \         # POST with inline body
  properties[title][0][text][content]="Notes"
ntn api v1/pages/abc123 -X PATCH archived:=true   # PATCH; := is non-string (bool/num/null)
```

Syntax notes:
- `key=value` — string fields
- `key[nested]=value` — nested object fields
- `key:=value` — typed assignment (booleans, numbers, null, arrays)

### Search
```bash
ntn api v1/search query="page title"
```

### Read page metadata
```bash
ntn api v1/pages/{page_id}
```

### Read page as Markdown (agent-friendly)
```bash
ntn api v1/pages/{page_id}/markdown
```

### Read page content as blocks
```bash
ntn api v1/blocks/{page_id}/children
```

### Create page from Markdown
```bash
ntn api v1/pages \
  parent[page_id]=xxx \
  properties[title][0][text][content]="Notes from meeting" \
  markdown="# Agenda

- Q3 roadmap
- Hiring"
```

### Patch a page with Markdown
```bash
ntn api v1/pages/{page_id}/markdown -X PATCH \
  markdown="## Update

Shipped the prototype."
```

### Query a database (data source)
```bash
ntn api v1/data_sources/{data_source_id}/query -X POST \
  filter[property]=Status filter[select][equals]=Active
```

For complex queries with `sorts`, multiple filter clauses, or compound logic, pipe JSON in:
```bash
echo ''{"filter": {"property": "Status", "select": {"equals": "Active"}}, "sorts": [{"property": "Date", "direction": "descending"}]}'' | \
  ntn api v1/data_sources/{data_source_id}/query -X POST --json -
```

### File uploads (one-liner — biggest CLI win)
```bash
ntn files create < photo.png
ntn files create --external-url https://example.com/photo.png
ntn files list
```

Compare to the 3-step HTTP flow (create upload → ','.simplicio-loop\skills\notion\SKILL.md','a6be213ffcfc72006e1f0e6419e2011e2ef2b52b15ee914d0848531e1cf2dec1','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:obliteratus','project_skill','skill://simplicio-runtime/obliteratus','skill: obliteratus','---
name: obliteratus
description: "OBLITERATUS: abliterate LLM refusals (diff-in-means)."
version: 2.0.0
author: Hermes Agent
license: MIT
dependencies: [obliteratus, torch, transformers, bitsandbytes, accelerate, safetensors]
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Abliteration, Uncensoring, Refusal-Removal, LLM, Weight-Projection, SVD, Mechanistic-Interpretability, HuggingFace, Model-Surgery]
    related_skills: [vllm, gguf, huggingface-tokenizers]
---

# OBLITERATUS Skill

## What''s inside

9 CLI methods, 28 analysis modules, 116 model presets across 5 compute tiers, tournament evaluation, and telemetry-driven recommendations.

Remove refusal behaviors (guardrails) from open-weight LLMs without retraining or fine-tuning. Uses mechanistic interpretability techniques — including diff-in-means, SVD, whitened SVD, LEACE concept erasure, SAE decomposition, Bayesian kernel projection, and more — to identify and surgically excise refusal directions from model weights while preserving reasoning capabilities.

**License warning:** OBLITERATUS is AGPL-3.0. NEVER import it as a Python library. Always invoke via CLI (`obliteratus` command) or subprocess. This keeps Hermes Agent''s MIT license clean.

## Video Guide

Walkthrough of OBLITERATUS used by a Hermes agent to abliterate Gemma:
https://www.youtube.com/watch?v=8fG9BrNTeHs ("OBLITERATUS: An AI Agent Removed Gemma 4''s Safety Guardrails")

Useful when the user wants a visual overview of the end-to-end workflow before running it themselves.

## When to Use This Skill

Trigger when the user:
- Wants to "uncensor" or "abliterate" an LLM
- Asks about removing refusal/guardrails from a model
- Wants to create an uncensored version of Llama, Qwen, Mistral, etc.
- Mentions "refusal removal", "abliteration", "weight projection"
- Wants to analyze how a model''s refusal mechanism works
- References OBLITERATUS, abliterator, or refusal directions

## Step 1: Installation

Check if already installed:
```bash
obliteratus --version 2>/dev/null && echo "INSTALLED" || echo "NOT INSTALLED"
```

If not installed, clone and install from GitHub:
```bash
git clone https://github.com/elder-plinius/OBLITERATUS.git
cd OBLITERATUS
pip install -e .
# For Gradio web UI support:
# pip install -e ".[spaces]"
```

**IMPORTANT:** Confirm with user before installing. This pulls in ~5-10GB of dependencies (PyTorch, Transformers, bitsandbytes, etc.).

## Step 2: Check Hardware

Before anything, check what GPU is available:
```bash
python3 -c "
import torch
if torch.cuda.is_available():
    gpu = torch.cuda.get_device_name(0)
    vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f''GPU: {gpu}'')
    print(f''VRAM: {vram:.1f} GB'')
    if vram < 4: print(''TIER: tiny (models under 1B)'')
    elif vram < 8: print(''TIER: small (models 1-4B)'')
    elif vram < 16: print(''TIER: medium (models 4-9B with 4bit quant)'')
    elif vram < 32: print(''TIER: large (models 8-32B with 4bit quant)'')
    else: print(''TIER: frontier (models 32B+)'')
else:
    print(''NO GPU - only tiny models (under 1B) on CPU'')
"
```

### VRAM Requirements (with 4-bit quantization)

| VRAM     | Max Model Size  | Example Models                              |
|:---------|:----------------|:--------------------------------------------|
| CPU only | ~1B params      | GPT-2, TinyLlama, SmolLM                    |
| 4-8 GB   | ~4B params      | Qwen2.5-1.5B, Phi-3.5 mini, Llama 3.2 3B   |
| 8-16 GB  | ~9B params      | Llama 3.1 8B, Mistral 7B, Gemma 2 9B       |
| 24 GB    | ~32B params     | Qwen3-32B, Llama 3.1 70B (tight), Command-R |
| 48 GB+   | ~72B+ params    | Qwen2.5-72B, DeepSeek-R1                    |
| Multi-GPU| 200B+ params    | Llama 3.1 405B, DeepSeek-V3 (685B MoE)      |

## Step 3: Browse Available Models & Get Recommendations

```bash
# Browse models by compute tier
obliteratus models --tier medium

# Get architecture info for a specific model
obliteratus info <model_name>

# Get telemetry-driven recommendation for best method & params
obliteratus recommend <model_name>
obliteratus recommend <mod','.simplicio-loop\skills\obliteratus\SKILL.md','e9d26cee54055f31c768c8ea76cf7a418f7733bc13622d62ffc74d175e207575','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:obsidian','project_skill','skill://simplicio-runtime/obsidian','skill: obsidian','---
name: obsidian
description: Read, search, create, and edit notes in the Obsidian vault.
platforms: [linux, macos, windows]
---

# Obsidian Vault

Use this skill for filesystem-first Obsidian vault work: reading notes, listing notes, searching note files, creating notes, appending content, and adding wikilinks.

## Vault path

Use a known or resolved vault path before calling file tools.

The documented vault-path convention is the `OBSIDIAN_VAULT_PATH` environment variable, for example from `~/.hermes/.env`. If it is unset, use `~/Documents/Obsidian Vault`.

File tools do not expand shell variables. Do not pass paths containing `$OBSIDIAN_VAULT_PATH` to `read_file`, `write_file`, `patch`, or `search_files`; resolve the vault path first and pass a concrete absolute path. Vault paths may contain spaces, which is another reason to prefer file tools over shell commands.

If the vault path is unknown, `terminal` is acceptable for resolving `OBSIDIAN_VAULT_PATH` or checking whether the fallback path exists. Once the path is known, switch back to file tools.

## Read a note

Use `read_file` with the resolved absolute path to the note. Prefer this over `cat` because it provides line numbers and pagination.

## List notes

Use `search_files` with `target: "files"` and the resolved vault path. Prefer this over `find` or `ls`.

- To list all markdown notes, use `pattern: "*.md"` under the vault path.
- To list a subfolder, search under that subfolder''s absolute path.

## Search

Use `search_files` for both filename and content searches. Prefer this over `grep`, `find`, or `ls`.

- For filenames, use `search_files` with `target: "files"` and a filename `pattern`.
- For note contents, use `search_files` with `target: "content"`, the content regex as `pattern`, and `file_glob: "*.md"` when you want to restrict matches to markdown notes.

## Create a note

Use `write_file` with the resolved absolute path and the full markdown content. Prefer this over shell heredocs or `echo` because it avoids shell quoting issues and returns structured results.

## Append to a note

Prefer a native file-tool workflow when it is not awkward:

- Read the target note with `read_file`.
- Use `patch` for an anchored append when there is stable context, such as adding a section after an existing heading or appending before a known trailing block.
- Use `write_file` when rewriting the whole note is clearer than constructing a fragile patch.

For an anchored append with `patch`, replace the anchor with the anchor plus the new content.

For a simple append with no stable context, `terminal` is acceptable if it is the clearest safe option.

## Targeted edits

Use `patch` for focused note changes when the current content gives you stable context. Prefer this over shell text rewriting.

## Wikilinks

Obsidian links notes with `[[Note Name]]` syntax. When creating notes, use these to link related content.
','.simplicio-loop\skills\obsidian\SKILL.md','d2d080f82893dac86190e3885720e27acb6730cbea8bbb1dd7c25aaa53231127','skill,simplicio,content',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:ocr-and-documents','project_skill','skill://simplicio-runtime/ocr-and-documents','skill: ocr-and-documents','---
name: ocr-and-documents
description: "Extract text from PDFs/scans (pymupdf, marker-pdf)."
version: 2.3.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [PDF, Documents, Research, Arxiv, Text-Extraction, OCR]
    related_skills: [powerpoint]
---

# PDF & Document Extraction

For DOCX: use `python-docx` (parses actual document structure, far better than OCR).
For PPTX: see the `powerpoint` skill (uses `python-pptx` with full slide/notes support).
This skill covers **PDFs and scanned documents**.

## Step 1: Remote URL Available?

If the document has a URL, **always try `web_extract` first**:

```
web_extract(urls=["https://arxiv.org/pdf/2402.03300"])
web_extract(urls=["https://example.com/report.pdf"])
```

This handles PDF-to-markdown conversion via Firecrawl with no local dependencies.

Only use local extraction when: the file is local, web_extract fails, or you need batch processing.

## Step 2: Choose Local Extractor

| Feature | pymupdf (~25MB) | marker-pdf (~3-5GB) |
|---------|-----------------|---------------------|
| **Text-based PDF** | ✅ | ✅ |
| **Scanned PDF (OCR)** | ❌ | ✅ (90+ languages) |
| **Tables** | ✅ (basic) | ✅ (high accuracy) |
| **Equations / LaTeX** | ❌ | ✅ |
| **Code blocks** | ❌ | ✅ |
| **Forms** | ❌ | ✅ |
| **Headers/footers removal** | ❌ | ✅ |
| **Reading order detection** | ❌ | ✅ |
| **Images extraction** | ✅ (embedded) | ✅ (with context) |
| **Images → text (OCR)** | ❌ | ✅ |
| **EPUB** | ✅ | ✅ |
| **Markdown output** | ✅ (via pymupdf4llm) | ✅ (native, higher quality) |
| **Install size** | ~25MB | ~3-5GB (PyTorch + models) |
| **Speed** | Instant | ~1-14s/page (CPU), ~0.2s/page (GPU) |

**Decision**: Use pymupdf unless you need OCR, equations, forms, or complex layout analysis.

If the user needs marker capabilities but the system lacks ~5GB free disk:
> "This document needs OCR/advanced extraction (marker-pdf), which requires ~5GB for PyTorch and models. Your system has [X]GB free. Options: free up space, provide a URL so I can use web_extract, or I can try pymupdf which works for text-based PDFs but not scanned documents or equations."

---

## pymupdf (lightweight)

```bash
pip install pymupdf pymupdf4llm
```

**Via helper script**:
```bash
python scripts/extract_pymupdf.py document.pdf              # Plain text
python scripts/extract_pymupdf.py document.pdf --markdown    # Markdown
python scripts/extract_pymupdf.py document.pdf --tables      # Tables
python scripts/extract_pymupdf.py document.pdf --images out/ # Extract images
python scripts/extract_pymupdf.py document.pdf --metadata    # Title, author, pages
python scripts/extract_pymupdf.py document.pdf --pages 0-4   # Specific pages
```

**Inline**:
```bash
python3 -c "
import pymupdf
doc = pymupdf.open(''document.pdf'')
for page in doc:
    print(page.get_text())
"
```

---

## marker-pdf (high-quality OCR)

```bash
# Check disk space first
python scripts/extract_marker.py --check

pip install marker-pdf
```

**Via helper script**:
```bash
python scripts/extract_marker.py document.pdf                # Markdown
python scripts/extract_marker.py document.pdf --json         # JSON with metadata
python scripts/extract_marker.py document.pdf --output_dir out/  # Save images
python scripts/extract_marker.py scanned.pdf                 # Scanned PDF (OCR)
python scripts/extract_marker.py document.pdf --use_llm      # LLM-boosted accuracy
```

**CLI** (installed with marker-pdf):
```bash
marker_single document.pdf --output_dir ./output
marker /path/to/folder --workers 4    # Batch
```

---

## Arxiv Papers

```
# Abstract only (fast)
web_extract(urls=["https://arxiv.org/abs/2402.03300"])

# Full paper
web_extract(urls=["https://arxiv.org/pdf/2402.03300"])

# Search
web_search(query="arxiv GRPO reinforcement learning 2026")
```

## Split, Merge & Search

pymupdf handles these natively — use `execute_code` or inline Python:

```python
# Split: extract pages 1-5 to a new PDF
import pymupdf
doc = pymupdf.open("report.pdf")
new = pymupdf.open()
for i in range(5):
    new.insert_pdf(doc, from_pag','.simplicio-loop\skills\ocr-and-documents\SKILL.md','7d6a419320e917d3c512e642b67bba202d2d3d780769d687bfb27dca5862899e','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:one-three-one-rule','project_skill','skill://simplicio-runtime/one-three-one-rule','skill: one-three-one-rule','---
name: one-three-one-rule
description: >
  Structured decision-making framework for technical proposals and trade-off analysis.
  When the user faces a choice between multiple approaches (architecture decisions,
  tool selection, refactoring strategies, migration paths), this skill produces a
  1-3-1 format: one clear problem statement, three distinct options with pros/cons,
  and one concrete recommendation with definition of done and implementation plan.
  Use when the user asks for a "1-3-1", says "give me options", or needs help
  choosing between competing approaches.
platforms: [linux, macos, windows]
version: 1.0.0
author: Willard Moore
license: MIT
category: communication
metadata:
  hermes:
    tags: [communication, decision-making, proposals, trade-offs]
---

# 1-3-1 Communication Rule

Structured decision-making format for when a task has multiple viable approaches and the user needs a clear recommendation. Produces a concise problem framing, three options with trade-offs, and an actionable plan for the recommended path.

## When to Use

- The user explicitly asks for a "1-3-1" response.
- The user says "give me options" or "what are my choices" for a technical decision.
- A task has multiple viable approaches with meaningful trade-offs (architecture, tooling, migration strategy).
- The user needs a proposal they can forward to a team or stakeholder.

Do NOT use for simple questions with one obvious answer, debugging sessions, or tasks where the user has already decided on an approach.

## Procedure

1. **Problem** (one sentence)
   - State the core decision or desired outcome in a single concise sentence.
   - Focus on the *what*, not the *how* — no implementation details, tool names, or specific technologies.
   - Keep it tight. If you need "and", you''re describing two problems.

2. **Options** (exactly three)
   - Present three distinct, viable approaches labeled A, B, C.
   - Each option gets a brief description, pros, and cons.
   - Options should represent genuinely different strategies, not minor variations of the same approach.

3. **Recommendation** (one option)
   - State which option you recommend and why, based on the user''s context and priorities.
   - Be direct — this is your professional judgment, not a hedge.

4. **Definition of Done**
   - List the specific success criteria for the recommended option.
   - These are concrete, verifiable outcomes — not vague aspirations.
   - If the user picks a different option, revise this section to match.

5. **Implementation Plan**
   - Concrete steps to execute the recommended option.
   - Include specific commands, tools, or actions where applicable.
   - If the user picks a different option, revise this section to match.

## Verification

- Response has exactly one Problem sentence.
- Response has exactly three Options (A, B, C) with pros and cons for each.
- Response has a single Recommendation that picks one option with reasoning.
- Definition of Done and Implementation Plan align with the recommended option.
- If the user selects a different option, Recommendation, DoD, and Implementation Plan update accordingly.

## Example

User: "Give me a 1-3-1 for adding retry logic to our API client."

Agent:

**Problem:** API calls to external services fail intermittently under load and need graceful retry handling.

**Options:**

- **Option A: Exponential backoff with jitter in a shared utility.**
  Pros: Simple, well-understood pattern; single implementation shared across all callers.
  Cons: No circuit-breaking; callers still block during retries.

- **Option B: Retry library (tenacity) as a decorator on each endpoint call.**
  Pros: Configurable per-endpoint; built-in support for circuit breakers and rate limits.
  Cons: Adds a dependency; decorator pattern can obscure control flow.

- **Option C: Queue-based async retry with dead letter handling.**
  Pros: Non-blocking; failed calls are tracked and replayable; scales well.
  Cons: Significant complexity increase; requires a queue backend; overkill for low-volume services.

**Recommendation:** Option A.','.simplicio-loop\skills\one-three-one-rule\SKILL.md','b899ee001a1caca821ded6a9f6680d9c1ba9bb914667e99a50a96c5e2072db12','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:openclaw-migration','project_skill','skill://simplicio-runtime/openclaw-migration','skill: openclaw-migration','---
name: openclaw-migration
description: Migrate a user''s OpenClaw customization footprint into Hermes Agent. Imports Hermes-compatible memories, SOUL.md, command allowlists, user skills, and selected workspace assets from ~/.openclaw, then reports exactly what could not be migrated and why.
version: 1.0.0
author: Hermes Agent (Nous Research)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Migration, OpenClaw, Hermes, Memory, Persona, Import]
    related_skills: [hermes-agent]
---

# OpenClaw -> Hermes Migration

Use this skill when a user wants to move their OpenClaw setup into Hermes Agent with minimal manual cleanup.

## CLI Command

For a quick, non-interactive migration, use the built-in CLI command:

```bash
hermes claw migrate              # Full interactive migration
hermes claw migrate --dry-run    # Preview what would be migrated
hermes claw migrate --preset user-data   # Migrate without secrets
hermes claw migrate --overwrite  # Overwrite existing conflicts
hermes claw migrate --source /custom/path/.openclaw  # Custom source
```

The CLI command runs the same migration script described below. Use this skill (via the agent) when you want an interactive, guided migration with dry-run previews and per-item conflict resolution.

**First-time setup:** The `hermes setup` wizard automatically detects `~/.openclaw` and offers migration before configuration begins.

## What this skill does

It uses `scripts/openclaw_to_hermes.py` to:

- import `SOUL.md` into the Hermes home directory as `SOUL.md`
- transform OpenClaw `MEMORY.md` and `USER.md` into Hermes memory entries
- merge OpenClaw command approval patterns into Hermes `command_allowlist`
- migrate Hermes-compatible messaging settings such as `TELEGRAM_ALLOWED_USERS`, and map OpenClaw workspace settings to Hermes working-directory configuration
- copy OpenClaw skills into `~/.hermes/skills/openclaw-imports/`
- optionally copy the OpenClaw workspace instructions file into a chosen Hermes workspace
- mirror compatible workspace assets such as `workspace/tts/` into `~/.hermes/tts/`
- archive non-secret docs that do not have a direct Hermes destination
- produce a structured report listing migrated items, conflicts, skipped items, and reasons

## Path resolution

The helper script lives in this skill directory at:

- `scripts/openclaw_to_hermes.py`

When this skill is installed from the Skills Hub, the normal location is:

- `~/.hermes/skills/migration/openclaw-migration/scripts/openclaw_to_hermes.py`

Do not guess a shorter path like `~/.hermes/skills/openclaw-migration/...`.

Before running the helper:

1. Prefer the installed path under `~/.hermes/skills/migration/openclaw-migration/`.
2. If that path fails, inspect the installed skill directory and resolve the script relative to the installed `SKILL.md`.
3. Only use `find` as a fallback if the installed location is missing or the skill was moved manually.
4. When calling the terminal tool, do not pass `workdir: "~"`. Use an absolute directory such as the user''s home directory, or omit `workdir` entirely.

With `--migrate-secrets`, it will also import a small allowlisted set of Hermes-compatible secrets, currently:

- `TELEGRAM_BOT_TOKEN`

## Default workflow

1. Inspect first with a dry run.
2. Present a simple summary of what can be migrated, what cannot be migrated, and what would be archived.
3. If the `clarify` tool is available, use it for user decisions instead of asking for a free-form prose reply.
4. If the dry run finds imported skill directory conflicts, ask how those should be handled before executing.
5. Ask the user to choose between the two supported migration modes before executing.
6. Ask for a target workspace path only if the user wants the workspace instructions file brought over.
7. Execute the migration with the matching preset and flags.
8. Summarize the results, especially:
   - what was migrated
   - what was archived for manual review
   - what was skipped and why

## User interaction protocol

Hermes CLI supports the `clarify` tool for interactive prompts, b','.simplicio-loop\skills\openclaw-migration\SKILL.md','2e6e12ab9d6fecbffb7401b380c65c49bea66449b303bafc40e971d20b33b509','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:opencode','project_skill','skill://simplicio-runtime/opencode','skill: opencode','---
name: opencode
description: "Delegate coding to OpenCode CLI (features, PR review)."
version: 1.2.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, OpenCode, Autonomous, Refactoring, Code-Review]
    related_skills: [claude-code, codex, hermes-agent]
---

# OpenCode CLI

Use [OpenCode](https://opencode.ai) as an autonomous coding worker orchestrated by Hermes terminal/process tools. OpenCode is a provider-agnostic, open-source AI coding agent with a TUI and CLI.

## When to Use

- User explicitly asks to use OpenCode
- You want an external coding agent to implement/refactor/review code
- You need long-running coding sessions with progress checks
- You want parallel task execution in isolated workdirs/worktrees

## Prerequisites

- OpenCode installed: `npm i -g opencode-ai@latest` or `brew install anomalyco/tap/opencode`
- Auth configured: `opencode auth login` or set provider env vars (OPENROUTER_API_KEY, etc.)
- Verify: `opencode auth list` should show at least one provider
- Git repository for code tasks (recommended)
- `pty=true` for interactive TUI sessions

## Binary Resolution (Important)

Shell environments may resolve different OpenCode binaries. If behavior differs between your terminal and Hermes, check:

```
terminal(command="which -a opencode")
terminal(command="opencode --version")
```

If needed, pin an explicit binary path:

```
terminal(command="$HOME/.opencode/bin/opencode run ''...''", workdir="~/project", pty=true)
```

## One-Shot Tasks

Use `opencode run` for bounded, non-interactive tasks:

```
terminal(command="opencode run ''Add retry logic to API calls and update tests''", workdir="~/project")
```

Attach context files with `-f`:

```
terminal(command="opencode run ''Review this config for security issues'' -f config.yaml -f .env.example", workdir="~/project")
```

Show model thinking with `--thinking`:

```
terminal(command="opencode run ''Debug why tests fail in CI'' --thinking", workdir="~/project")
```

Force a specific model:

```
terminal(command="opencode run ''Refactor auth module'' --model openrouter/anthropic/claude-sonnet-4", workdir="~/project")
```

## Interactive Sessions (Background)

For iterative work requiring multiple exchanges, start the TUI in background:

```
terminal(command="opencode", workdir="~/project", background=true, pty=true)
# Returns session_id

# Send a prompt
process(action="submit", session_id="<id>", data="Implement OAuth refresh flow and add tests")

# Monitor progress
process(action="poll", session_id="<id>")
process(action="log", session_id="<id>")

# Send follow-up input
process(action="submit", session_id="<id>", data="Now add error handling for token expiry")

# Exit cleanly — Ctrl+C
process(action="write", session_id="<id>", data="\x03")
# Or just kill the process
process(action="kill", session_id="<id>")
```

**Important:** Do NOT use `/exit` — it is not a valid OpenCode command and will open an agent selector dialog instead. Use Ctrl+C (`\x03`) or `process(action="kill")` to exit.

### TUI Keybindings

| Key | Action |
|-----|--------|
| `Enter` | Submit message (press twice if needed) |
| `Tab` | Switch between agents (build/plan) |
| `Ctrl+P` | Open command palette |
| `Ctrl+X L` | Switch session |
| `Ctrl+X M` | Switch model |
| `Ctrl+X N` | New session |
| `Ctrl+X E` | Open editor |
| `Ctrl+C` | Exit OpenCode |

### Resuming Sessions

After exiting, OpenCode prints a session ID. Resume with:

```
terminal(command="opencode -c", workdir="~/project", background=true, pty=true)  # Continue last session
terminal(command="opencode -s ses_abc123", workdir="~/project", background=true, pty=true)  # Specific session
```

## Common Flags

| Flag | Use |
|------|-----|
| `run ''prompt''` | One-shot execution and exit |
| `--continue` / `-c` | Continue the last OpenCode session |
| `--session <id>` / `-s` | Continue a specific session |
| `--agent <name>` | Choose OpenCode agent (build or plan) |
| `--model provider/model` | Force specific model |
| `--format json` | Machine-readable output/events |
|','.simplicio-loop\skills\opencode\SKILL.md','81c2044dad7f2ba989b7d97ef56ed32bbfea36060b1545cf8975da8f6c650e3f','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:openhands','project_skill','skill://simplicio-runtime/openhands','skill: openhands','---
name: openhands
description: Delegate coding to OpenHands CLI (model-agnostic, LiteLLM).
version: 0.1.0
author: Tim Koepsel (xzessmedia), Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Coding-Agent, OpenHands, Model-Agnostic, LiteLLM]
    related_skills: [claude-code, codex, opencode, hermes-agent]
---

# OpenHands CLI

Delegate coding tasks to the [OpenHands CLI](https://github.com/All-Hands-AI/OpenHands) via the `terminal` tool. OpenHands is model-agnostic: any LiteLLM-supported provider (OpenAI, Anthropic, OpenRouter, DeepSeek, Ollama, vLLM, etc.).

This skill is the headless-mode wrapper for batch / one-shot delegation. The interactive textual UI is not used from Hermes.

## When to Use

- User wants a coding task delegated to OpenHands specifically.
- User wants a coding agent that can run on a non-Anthropic / non-OpenAI provider (DeepSeek, Qwen, Ollama, vLLM, Nous, etc.) — sibling skills `claude-code` and `codex` are tied to one vendor.
- Multi-step file edits + shell commands inside a workspace.

For Claude-native, prefer `claude-code`. For OpenAI-native, prefer `codex`. For Hermes-native subagents, use `delegate_task`.

## Prerequisites

1. Install upstream (requires Python 3.12+ and `uv`):

   ```
   terminal(command="uv tool install openhands --python 3.12")
   ```

   Verify: `openhands --version` (currently `OpenHands CLI 1.16.0` / `SDK v1.21.0` at time of writing).

2. Pick a model and set env vars for `--override-with-envs`:

   ```
   export LLM_MODEL=openrouter/openai/gpt-4o-mini       # or any LiteLLM slug
   export LLM_API_KEY=$OPENROUTER_API_KEY
   export LLM_BASE_URL=https://openrouter.ai/api/v1     # omit for native OpenAI
   ```

   `LLM_MODEL` uses LiteLLM''s full slug. When the provider is OpenRouter the slug is doubly-prefixed: `openrouter/<vendor>/<model>` (e.g. `openrouter/anthropic/claude-sonnet-4.5`). For native Anthropic: `anthropic/claude-sonnet-4-5`. For native OpenAI: `openai/gpt-4o-mini`.

3. Suppress the startup banner so JSON output isn''t preceded by ASCII art:

   ```
   export OPENHANDS_SUPPRESS_BANNER=1
   ```

## How to Run

Always invoke through the `terminal` tool. Always pass `--headless --json --override-with-envs --exit-without-confirmation` for automation.

### One-shot task

```
terminal(
  command="OPENHANDS_SUPPRESS_BANNER=1 LLM_MODEL=openrouter/openai/gpt-4o-mini LLM_API_KEY=$OPENROUTER_API_KEY LLM_BASE_URL=https://openrouter.ai/api/v1 openhands --headless --json --override-with-envs --exit-without-confirmation -t ''Add error handling to all API calls in src/''",
  workdir="/path/to/project",
  timeout=600
)
```

### Background for long tasks

```
terminal(command="<same as above>", workdir="/path/to/project", background=true, notify_on_complete=true)
process(action="poll", session_id="<id>")
process(action="log", session_id="<id>")
```

### Resume a previous conversation

OpenHands prints `Conversation ID: <32-hex>` and a `Hint: openhands --resume <dashed-uuid>` line at the end of each run. Use the dashed form to resume:

```
terminal(
  command="OPENHANDS_SUPPRESS_BANNER=1 LLM_MODEL=... openhands --headless --json --override-with-envs --exit-without-confirmation --resume <dashed-uuid> -t ''Now fix the bug you found''",
  workdir="/path/to/project"
)
```

## Real Flag List

Verified against `openhands --help` (CLI 1.16.0). Anything not in this table is not a flag — pass it via env var or settings file.

| Flag | Effect |
|------|--------|
| `--headless` | No UI, requires `-t` or `-f`. Auto-approves all actions (no `--llm-approve` in this mode). |
| `--json` | JSONL event stream (requires `--headless`). |
| `-t TEXT` | Task prompt. |
| `-f PATH` | Read task from file. |
| `--resume [ID]` | Resume conversation. No ID → list recent. |
| `--last` | Resume most recent (with `--resume`). |
| `--override-with-envs` | Apply `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` env vars. Without this, OpenHands uses `~/.openhands/settings.json` and ignores the env. |
| `--exit-without-confirmation` | Don''t show the "are you sure" exit dialog. |
| `--alwa','.simplicio-loop\skills\openhands\SKILL.md','5237552f955df8343c89f82548456ea50297d6fb5c6c50f7e7eafcdb2c5b0aaa','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:openhue','project_skill','skill://simplicio-runtime/openhue','skill: openhue','---
name: openhue
description: "Control Philips Hue lights, scenes, rooms via OpenHue CLI."
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Smart-Home, Hue, Lights, IoT, Automation]
    homepage: https://www.openhue.io/cli
prerequisites:
  commands: [openhue]
---

# OpenHue CLI

Control Philips Hue lights and scenes via a Hue Bridge from the terminal.

## Prerequisites

```bash
# Linux (pre-built binary)
curl -sL https://github.com/openhue/openhue-cli/releases/latest/download/openhue-linux-amd64 -o ~/.local/bin/openhue && chmod +x ~/.local/bin/openhue

# macOS
brew install openhue/cli/openhue-cli
```

First run requires pressing the button on your Hue Bridge to pair. The bridge must be on the same local network.

## When to Use

- "Turn on/off the lights"
- "Dim the living room lights"
- "Set a scene" or "movie mode"
- Controlling specific Hue rooms, zones, or individual bulbs
- Adjusting brightness, color, or color temperature

## Common Commands

### List Resources

```bash
openhue get light       # List all lights
openhue get room        # List all rooms
openhue get scene       # List all scenes
```

### Control Lights

```bash
# Turn on/off
openhue set light "Bedroom Lamp" --on
openhue set light "Bedroom Lamp" --off

# Brightness (0-100)
openhue set light "Bedroom Lamp" --on --brightness 50

# Color temperature (warm to cool: 153-500 mirek)
openhue set light "Bedroom Lamp" --on --temperature 300

# Color (by name or hex)
openhue set light "Bedroom Lamp" --on --color red
openhue set light "Bedroom Lamp" --on --rgb "#FF5500"
```

### Control Rooms

```bash
# Turn off entire room
openhue set room "Bedroom" --off

# Set room brightness
openhue set room "Bedroom" --on --brightness 30
```

### Scenes

```bash
openhue set scene "Relax" --room "Bedroom"
openhue set scene "Concentrate" --room "Office"
```

## Quick Presets

```bash
# Bedtime (dim warm)
openhue set room "Bedroom" --on --brightness 20 --temperature 450

# Work mode (bright cool)
openhue set room "Office" --on --brightness 100 --temperature 250

# Movie mode (dim)
openhue set room "Living Room" --on --brightness 10

# Everything off
openhue set room "Bedroom" --off
openhue set room "Office" --off
openhue set room "Living Room" --off
```

## Notes

- Bridge must be on the same local network as the machine running Hermes
- First run requires physically pressing the button on the Hue Bridge to authorize
- Colors only work on color-capable bulbs (not white-only models)
- Light and room names are case-sensitive — use `openhue get light` to check exact names
- Works great with cron jobs for scheduled lighting (e.g. dim at bedtime, bright at wake)
','.simplicio-loop\skills\openhue\SKILL.md','550f94848d10ab82619db8fec240a4d2b792c33606fba5d391bf3a78bc1119e9','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:osint-investigation','project_skill','skill://simplicio-runtime/osint-investigation','skill: osint-investigation','---
name: osint-investigation
description: Public-records OSINT investigation framework — SEC EDGAR filings, USAspending contracts, Senate lobbying, OFAC sanctions, ICIJ offshore leaks, NYC property records (ACRIS), OpenCorporates registries, CourtListener court records, Wayback Machine archives, Wikipedia + Wikidata, GDELT news monitoring. Entity resolution across sources, cross-link analysis, timing correlation, evidence chains. Python stdlib only.
version: 0.1.0
platforms: [linux, macos, windows]
author: Hermes Agent (adapted from ShinMegamiBoson/OpenPlanter, MIT)
metadata:
  hermes:
    tags: [osint, investigation, public-records, sec, sanctions, corporate-registry, property, courts, due-diligence, journalism]
    category: research
    related_skills: [domain-intel, arxiv]
---

# OSINT Investigation — Public Records Cross-Reference

Investigative framework for public-records OSINT: government contracts,
corporate filings, lobbying, sanctions, offshore leaks, property records,
court records, web archives, knowledge bases, and global news. Resolve
entities across heterogeneous sources, build cross-links with explicit
confidence, run statistical timing tests, and produce structured evidence
chains.

**Python stdlib only.** Zero install. Works on Linux, macOS, Windows. Most
sources work with no API key (OpenCorporates has an optional free token
that raises rate limits).

Adapted from the MIT-licensed ShinMegamiBoson/OpenPlanter project; expanded
to cover identity / property / litigation / archives / news sources that
the original didn''t address.

## When to use this skill

Use when the user asks for:

- "follow the money" — government contracts, lobbying → legislation, sanctions
- corporate due diligence — who controls company X, where are they
  incorporated, who serves on their boards, what filings have they made
- sanctions screening — is entity X on OFAC SDN, ICIJ offshore leaks
- pay-to-play investigation — contractors with offshore ties, lobbying
  clients winning awards
- property ownership — find recorded deeds/mortgages by name or address
  (NYC; for other counties point users at the relevant recorder)
- litigation history — find federal + state court opinions and PACER dockets
- multi-source entity resolution where naming varies (LLC suffixes, abbreviations)
- evidence-chain construction with explicit confidence levels
- "what''s been said about X" — international news (GDELT) + Wikipedia
  narrative + Wayback Machine to recover dead URLs

Do NOT use this skill for:

- general web research → `web_search` / `web_extract`
- domain/infrastructure OSINT → `domain-intel` skill
- academic literature → `arxiv` skill
- social-media profile discovery → `sherlock` skill (optional)
- US **federal** campaign finance — FEC is intentionally NOT covered here
  (the API is unreliable for ad-hoc contributor-name queries on the free
  DEMO_KEY tier). For federal donations, point users at
  https://www.fec.gov/data/ directly.

## Workflow

The agent runs scripts via the `terminal` tool. `SKILL_DIR` is the directory
holding this SKILL.md.

### 1. Identify which sources apply

Read the data-source wiki entries to plan the investigation:

```
ls SKILL_DIR/references/sources/

# Federal financial / regulatory
cat SKILL_DIR/references/sources/sec-edgar.md       # corporate filings
cat SKILL_DIR/references/sources/usaspending.md     # federal contracts
cat SKILL_DIR/references/sources/senate-ld.md       # lobbying
cat SKILL_DIR/references/sources/ofac-sdn.md        # sanctions
cat SKILL_DIR/references/sources/icij-offshore.md   # offshore leaks

# Identity / property / litigation / archives / news
cat SKILL_DIR/references/sources/nyc-acris.md       # NYC property records
cat SKILL_DIR/references/sources/opencorporates.md  # global corporate registry
cat SKILL_DIR/references/sources/courtlistener.md   # court records (federal + state)
cat SKILL_DIR/references/sources/wayback.md         # Wayback Machine archives
cat SKILL_DIR/references/sources/wikipedia.md       # Wikipedia + Wikidata
cat SKILL_DIR/references/sources/gdelt.md          ','.simplicio-loop\skills\osint-investigation\SKILL.md','830fce347d5b32d2a54325f1dcdf16129a212280c108086770d4ee63155e8eb0','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:oss-forensics','project_skill','skill://simplicio-runtime/oss-forensics','skill: oss-forensics','---
name: oss-forensics
description: |
  Supply chain investigation, evidence recovery, and forensic analysis for GitHub repositories.
  Covers deleted commit recovery, force-push detection, IOC extraction, multi-source evidence
  collection, hypothesis formation/validation, and structured forensic reporting.
  Inspired by RAPTOR''s 1800+ line OSS Forensics system.
platforms: [linux, macos, windows]
category: security
triggers:
  - "investigate this repository"
  - "investigate [owner/repo]"
  - "check for supply chain compromise"
  - "recover deleted commits"
  - "forensic analysis of [owner/repo]"
  - "was this repo compromised"
  - "supply chain attack"
  - "suspicious commit"
  - "force push detected"
  - "IOC extraction"
toolsets:
  - terminal
  - web
  - file
  - delegation
---

# OSS Security Forensics Skill

A 7-phase multi-agent investigation framework for researching open-source supply chain attacks.
Adapted from RAPTOR''s forensics system. Covers GitHub Archive, Wayback Machine, GitHub API,
local git analysis, IOC extraction, evidence-backed hypothesis formation and validation,
and final forensic report generation.

---

## ⚠️ Anti-Hallucination Guardrails

Read these before every investigation step. Violating them invalidates the report.

1. **Evidence-First Rule**: Every claim in any report, hypothesis, or summary MUST cite at least one evidence ID (`EV-XXXX`). Assertions without citations are forbidden.
2. **STAY IN YOUR LANE**: Each sub-agent (investigator) has a single data source. Do NOT mix sources. The GH Archive investigator does not query the GitHub API, and vice versa. Role boundaries are hard.
3. **Fact vs. Hypothesis Separation**: Mark all unverified inferences with `[HYPOTHESIS]`. Only statements verified against original sources may be stated as facts.
4. **No Evidence Fabrication**: The hypothesis validator MUST mechanically check that every cited evidence ID actually exists in the evidence store before accepting a hypothesis.
5. **Proof-Required Disproval**: A hypothesis cannot be dismissed without a specific, evidence-backed counter-argument. "No evidence found" is not sufficient to disprove—it only makes a hypothesis inconclusive.
6. **SHA/URL Double-Verification**: Any commit SHA, URL, or external identifier cited as evidence must be independently confirmed from at least two sources before being marked as verified.
7. **Suspicious Code Rule**: Never run code found inside the investigated repository locally. Analyze statically only, or use `execute_code` in a sandboxed environment.
8. **Secret Redaction**: Any API keys, tokens, or credentials discovered during investigation must be redacted in the final report. Log them internally only.

---

## Example Scenarios

- **Scenario A: Dependency Confusion**: A malicious package `internal-lib-v2` is uploaded to NPM with a higher version than the internal one. The investigator must track when this package was first seen and if any PushEvents in the target repo updated `package.json` to this version.
- **Scenario B: Maintainer Takeover**: A long-term contributor''s account is used to push a backdoored `.github/workflows/build.yml`. The investigator looks for PushEvents from this user after a long period of inactivity or from a new IP/location (if detectable via BigQuery).
- **Scenario C: Force-Push Hide**: A developer accidentally commits a production secret, then force-pushes to "fix" it. The investigator uses `git fsck` and GH Archive to recover the original commit SHA and verify what was leaked.

---

> **Path convention**: Throughout this skill, `SKILL_DIR` refers to the root of this skill''s
> installation directory (the folder containing this `SKILL.md`). When the skill is loaded,
> resolve `SKILL_DIR` to the actual path — e.g. `~/.hermes/skills/security/oss-forensics/`
> or the `optional-skills/` equivalent. All script and template references are relative to it.

## Phase 0: Initialization

1. Create investigation working directory:
   ```bash
   mkdir investigation_$(echo "REPO_NAME" | tr ''/'' ''_'')
   cd investigation_$(echo "REPO_NAME" | tr ''/'' ','.simplicio-loop\skills\oss-forensics\SKILL.md','96cb1810ad2a174edc040de69e29d967bd4b640ef0656300ca4b8c801347b7ae','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:p5js','project_skill','skill://simplicio-runtime/p5js','skill: p5js','---
name: p5js
description: "p5.js sketches: gen art, shaders, interactive, 3D."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [creative-coding, generative-art, p5js, canvas, interactive, visualization, webgl, shaders, animation]
    related_skills: [ascii-video, manim-video, excalidraw]
---

# p5.js Production Pipeline

## When to use

Use when users request: p5.js sketches, creative coding, generative art, interactive visualizations, canvas animations, browser-based visual art, data viz, shader effects, or any p5.js project.

## What''s inside

Production pipeline for interactive and generative visual art using p5.js. Creates browser-based sketches, generative art, data visualizations, interactive experiences, 3D scenes, audio-reactive visuals, and motion graphics — exported as HTML, PNG, GIF, MP4, or SVG. Covers: 2D/3D rendering, noise and particle systems, flow fields, shaders (GLSL), pixel manipulation, kinetic typography, WebGL scenes, audio analysis, mouse/keyboard interaction, and headless high-res export.

## Creative Standard

This is visual art rendered in the browser. The canvas is the medium; the algorithm is the brush.

**Before writing a single line of code**, articulate the creative concept. What does this piece communicate? What makes the viewer stop scrolling? What separates this from a code tutorial example? The user''s prompt is a starting point — interpret it with creative ambition.

**First-render excellence is non-negotiable.** The output must be visually striking on first load. If it looks like a p5.js tutorial exercise, a default configuration, or "AI-generated creative coding," it is wrong. Rethink before shipping.

**Go beyond the reference vocabulary.** The noise functions, particle systems, color palettes, and shader effects in the references are a starting vocabulary. For every project, combine, layer, and invent. The catalog is a palette of paints — you write the painting.

**Be proactively creative.** If the user asks for "a particle system," deliver a particle system with emergent flocking behavior, trailing ghost echoes, palette-shifted depth fog, and a background noise field that breathes. Include at least one visual detail the user didn''t ask for but will appreciate.

**Dense, layered, considered.** Every frame should reward viewing. Never flat white backgrounds. Always compositional hierarchy. Always intentional color. Always micro-detail that only appears on close inspection.

**Cohesive aesthetic over feature count.** All elements must serve a unified visual language — shared color temperature, consistent stroke weight vocabulary, harmonious motion speeds. A sketch with ten unrelated effects is worse than one with three that belong together.

## Modes

| Mode | Input | Output | Reference |
|------|-------|--------|-----------|
| **Generative art** | Seed / parameters | Procedural visual composition (still or animated) | `references/visual-effects.md` |
| **Data visualization** | Dataset / API | Interactive charts, graphs, custom data displays | `references/interaction.md` |
| **Interactive experience** | None (user drives) | Mouse/keyboard/touch-driven sketch | `references/interaction.md` |
| **Animation / motion graphics** | Timeline / storyboard | Timed sequences, kinetic typography, transitions | `references/animation.md` |
| **3D scene** | Concept description | WebGL geometry, lighting, camera, materials | `references/webgl-and-3d.md` |
| **Image processing** | Image file(s) | Pixel manipulation, filters, mosaic, pointillism | `references/visual-effects.md` § Pixel Manipulation |
| **Audio-reactive** | Audio file / mic | Sound-driven generative visuals | `references/interaction.md` § Audio Input |

## Stack

Single self-contained HTML file per project. No build step required.

| Layer | Tool | Purpose |
|-------|------|---------|
| Core | p5.js 1.11.3 (CDN) | Canvas rendering, math, transforms, event handling |
| 3D | p5.js WebGL mode | 3D geometry, camera, lighting, GLSL shaders |
| Audio | p5.sound.js (CDN) | FFT analysis, amplitude, mic input, ','.simplicio-loop\skills\p5js\SKILL.md','8c65e7403f299b0b89921c1d2d75549c6b0ac21d2b9acac34fb2ed3ef16ebc3a','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:page-agent','project_skill','skill://simplicio-runtime/page-agent','skill: page-agent','---
name: page-agent
description: Embed alibaba/page-agent into your own web application — a pure-JavaScript in-page GUI agent that ships as a single <script> tag or npm package and lets end-users of your site drive the UI with natural language ("click login, fill username as John"). No Python, no headless browser, no extension required. Use this skill when the user is a web developer who wants to add an AI copilot to their SaaS / admin panel / B2B tool, make a legacy web app accessible via natural language, or evaluate page-agent against a local (Ollama) or cloud (Qwen / OpenAI / OpenRouter) LLM. NOT for server-side browser automation — point those users to Hermes'' built-in browser tool instead.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [web, javascript, agent, browser, gui, alibaba, embed, copilot, saas]
    category: web-development
---

# page-agent

alibaba/page-agent (https://github.com/alibaba/page-agent, 17k+ stars, MIT) is an in-page GUI agent written in TypeScript. It lives inside a webpage, reads the DOM as text (no screenshots, no multi-modal LLM), and executes natural-language instructions like "click the login button, then fill username as John" against the current page. Pure client-side — the host site just includes a script and passes an OpenAI-compatible LLM endpoint.

## When to use this skill

Load this skill when a user wants to:

- **Ship an AI copilot inside their own web app** (SaaS, admin panel, B2B tool, ERP, CRM) — "users on my dashboard should be able to type ''create invoice for Acme Corp and email it'' instead of clicking through five screens"
- **Modernize a legacy web app** without rewriting the frontend — page-agent drops on top of existing DOM
- **Add accessibility via natural language** — voice / screen-reader users drive the UI by describing what they want
- **Demo or evaluate page-agent** against a local (Ollama) or hosted (Qwen, OpenAI, OpenRouter) LLM
- **Build interactive training / product demos** — let an AI walk a user through "how to submit an expense report" live in the real UI

## When NOT to use this skill

- User wants **Hermes itself to drive a browser** → use Hermes'' built-in browser tool (Browserbase / Camofox). page-agent is the *opposite* direction.
- User wants **cross-tab automation without embedding** → use Playwright, browser-use, or the page-agent Chrome extension
- User needs **visual grounding / screenshots** → page-agent is text-DOM only; use a multimodal browser agent instead

## Prerequisites

- Node 22.13+ or 24+, npm 10+ (docs claim 11+ but 10.9 works fine)
- An OpenAI-compatible LLM endpoint: Qwen (DashScope), OpenAI, Ollama, OpenRouter, or anything speaking `/v1/chat/completions`
- Browser with devtools (for debugging)

## Path 1 — 30-second demo via CDN (no install)

Fastest way to see it work. Uses alibaba''s free testing LLM proxy — **for evaluation only**, subject to their terms.

Add to any HTML page (or paste into the devtools console as a bookmarklet):

```html
<script src="https://cdn.jsdelivr.net/npm/page-agent@1.8.0/dist/iife/page-agent.demo.js" crossorigin="true"></script>
```

A panel appears. Type an instruction. Done.

Bookmarklet form (drop into bookmarks bar, click on any page):

```javascript
javascript:(function(){var s=document.createElement(''script'');s.src=''https://cdn.jsdelivr.net/npm/page-agent@1.8.0/dist/iife/page-agent.demo.js'';document.head.appendChild(s);})();
```

## Path 2 — npm install into your own web app (production use)

Inside an existing web project (React / Vue / Svelte / plain):

```bash
npm install page-agent
```

Wire it up with your own LLM endpoint — **never ship the demo CDN to real users**:

```javascript
import { PageAgent } from ''page-agent''

const agent = new PageAgent({
    model: ''qwen3.5-plus'',
    baseURL: ''https://dashscope.aliyuncs.com/compatible-mode/v1'',
    apiKey: process.env.LLM_API_KEY,   // never hardcode
    language: ''en-US'',
})

// Show the panel for end users:
agent.panel.show()

// Or drive it programmatically:
await agent.ex','.simplicio-loop\skills\page-agent\SKILL.md','9ecb8f5bb47ce22ec328b0a67fcae7d05741d528183752c3290a7a45b0e22277','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:parallel-cli','project_skill','skill://simplicio-runtime/parallel-cli','skill: parallel-cli','---
name: parallel-cli
description: Optional vendor skill for Parallel CLI — agent-native web search, extraction, deep research, enrichment, FindAll, and monitoring. Prefer JSON output and non-interactive flows.
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, Web, Search, Deep-Research, Enrichment, CLI]
    related_skills: [duckduckgo-search, mcporter]
---

# Parallel CLI

Use `parallel-cli` when the user explicitly wants Parallel, or when a terminal-native workflow would benefit from Parallel''s vendor-specific stack for web search, extraction, deep research, enrichment, entity discovery, or monitoring.

This is an optional third-party workflow, not a Hermes core capability.

Important expectations:
- Parallel is a paid service with a free tier, not a fully free local tool.
- It overlaps with Hermes native `web_search` / `web_extract`, so do not prefer it by default for ordinary lookups.
- Prefer this skill when the user mentions Parallel specifically or needs capabilities like Parallel''s enrichment, FindAll, or monitor workflows.

`parallel-cli` is designed for agents:
- JSON output via `--json`
- Non-interactive command execution
- Async long-running jobs with `--no-wait`, `status`, and `poll`
- Context chaining with `--previous-interaction-id`
- Search, extract, research, enrichment, entity discovery, and monitoring in one CLI

## When to use it

Prefer this skill when:
- The user explicitly mentions Parallel or `parallel-cli`
- The task needs richer workflows than a simple one-shot search/extract pass
- You need async deep research jobs that can be launched and polled later
- You need structured enrichment, FindAll entity discovery, or monitoring

Prefer Hermes native `web_search` / `web_extract` for quick one-off lookups when Parallel is not specifically requested.

## Installation

Try the least invasive install path available for the environment.

### Homebrew

```bash
brew install parallel-web/tap/parallel-cli
```

### npm

```bash
npm install -g parallel-web-cli
```

### Python package

```bash
pip install "parallel-web-tools[cli]"
```

### Standalone installer

```bash
curl -fsSL https://parallel.ai/install.sh | bash
```

If you want an isolated Python install, `pipx` can also work:

```bash
pipx install "parallel-web-tools[cli]"
pipx ensurepath
```

## Authentication

Interactive login:

```bash
parallel-cli login
```

Headless / SSH / CI:

```bash
parallel-cli login --device
```

API key environment variable:

```bash
export PARALLEL_API_KEY="***"
```

Verify current auth status:

```bash
parallel-cli auth
```

If auth requires browser interaction, run with `pty=true`.

## Core rule set

1. Always prefer `--json` when you need machine-readable output.
2. Prefer explicit arguments and non-interactive flows.
3. For long-running jobs, use `--no-wait` and then `status` / `poll`.
4. Cite only URLs returned by the CLI output.
5. Save large JSON outputs to a temp file when follow-up questions are likely.
6. Use background processes only for genuinely long-running workflows; otherwise run in foreground.
7. Prefer Hermes native tools unless the user wants Parallel specifically or needs Parallel-only workflows.

## Quick reference

```text
parallel-cli
├── auth
├── login
├── logout
├── search
├── extract / fetch
├── research run|status|poll|processors
├── enrich run|status|poll|plan|suggest|deploy
├── findall run|ingest|status|poll|result|enrich|extend|schema|cancel
└── monitor create|list|get|update|delete|events|event-group|simulate
```

## Common flags and patterns

Commonly useful flags:
- `--json` for structured output
- `--no-wait` for async jobs
- `--previous-interaction-id <id>` for follow-up tasks that reuse earlier context
- `--max-results <n>` for search result count
- `--mode one-shot|agentic` for search behavior
- `--include-domains domain1.com,domain2.com`
- `--exclude-domains domain1.com,domain2.com`
- `--after-date YYYY-MM-DD`

Read from stdin when convenient:

```bash
echo "What is the latest funding for Anthropic?" | parallel','.simplicio-loop\skills\parallel-cli\SKILL.md','28d23c4e02deda724827d957e9224d205963eb401ec4e4751d7f5fb9f0ed717e','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:payments','project_skill','skill://simplicio-runtime/payments','skill: payments','---
name: payments
description: Create invoices/charges, check payment status, issue refunds, and reconcile statements across Stripe, PayPal, Mercado Pago, and PIX. Use when the user asks to charge a customer, create an invoice, check a payment, refund a transaction, or reconcile a date range.
version: 0.1.0
author: Simplicio Runtime
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Payments, Stripe, PayPal, MercadoPago, PIX, Billing, Refund, Reconciliation]
    category: payments
    related_skills: [finance, stocks]
---

# Payments Skill

Integra o agente com provedores de pagamento para **criar faturas/cobranças,
verificar status, reembolsar transações e conciliar extratos**. Implementação de
provider em Python stdlib-only (`scripts/payments_client.py`), sem dependências
pip. Quando nenhuma credencial está presente, o cliente opera em modo
`--dry-run` determinístico — útil para dogfood sem segredos.

## Quando usar (Trigger)

- O usuário pede para **criar uma fatura/cobrança** (ex.: "cobra R$ 49,90 do cliente").
- O usuário quer **verificar o status** de um pagamento por ID.
- O usuário quer **reembolsar** uma transação (total ou parcial).
- O usuário quer **conciliar** transações entre duas datas.
- Qualquer integração com **Stripe, PayPal, Mercado Pago ou PIX**.

## Provedores suportados

| Provedor     | Auth          | Features                                      |
|--------------|---------------|-----------------------------------------------|
| Stripe       | API Key       | Faturas, pagamentos, reembolsos, webhooks     |
| PayPal       | OAuth         | Cobranças, assinaturas, reembolsos            |
| Mercado Pago | Access Token  | PIX, boleto, cartão, link de pagamento        |
| PIX          | Certificado   | QR Code estático/dinâmico, cobrança imediata  |

Status de implementação do provider Python:

- **Stripe** — implementado (REST `api.stripe.com/v1`, `STRIPE_API_KEY`).
- **Mercado Pago** — implementado (REST `api.mercadopago.com/v1`, `MP_ACCESS_TOKEN`).
- **PIX** — geração de QR Code estático (payload EMV/BR Code + CRC16) offline,
  sem credencial; cobrança dinâmica via Mercado Pago.
- **PayPal** — stub explícito (retorna erro orientando uso de Stripe/MP até as
  credenciais OAuth serem configuradas).

## Prerequisites

Python 3.8+ (stdlib only). Variáveis de ambiente, conforme o provedor:

- Stripe: `STRIPE_API_KEY`
- Mercado Pago: `MP_ACCESS_TOKEN`
- PayPal: `PAYPAL_CLIENT_ID` + `PAYPAL_CLIENT_SECRET` (futuro)

Sem credenciais, todos os comandos rodam em modo `--dry-run` (determinístico,
sem rede). PIX `qrcode` nunca precisa de credencial.

## How to Run

Invoque via terminal. Saída sempre JSON em stdout.

```
SCRIPT=skills/payments/scripts/payments_client.py
python3 $SCRIPT invoice.create 49.90 BRL --provider stripe --description "Plano Pro"
python3 $SCRIPT payment.status pi_123 --provider stripe
python3 $SCRIPT refund ch_123 --amount 10.00 --provider stripe
python3 $SCRIPT reconciliation 2026-06-01 2026-06-18 --provider mercadopago
python3 $SCRIPT pix.qrcode 49.90 --key chave@pix.com --merchant "Loja X" --city "Sao Paulo"
```

## Steps (como o agente opera)

1. Identifique o **provedor** (`--provider stripe|paypal|mercadopago|pix`) e a
   credencial correspondente no ambiente.
2. Execute a ação: `invoice.create`, `payment.status`, `refund`,
   `reconciliation` ou `pix.qrcode`.
3. Se a credencial faltar, o cliente cai em `--dry-run` — confirme com o usuário
   antes de habilitar chamadas reais (ação que move dinheiro **deve ser gated**).
4. Reporte o JSON de saída e o `mode` (`live` vs `dry-run`).

## Comandos (Quick Reference)

```
payments:invoice.create <amount> <currency> [--description ...] [--provider P]
payments:payment.status <id> [--provider P]
payments:refund <transaction_id> [--amount A] [--provider P]
payments:reconciliation <date_from> <date_to> [--provider P]
payments:pix.qrcode <amount> --key <pix_key> [--merchant ...] [--city ...] [--txid ...]
```

## Padrões

- Toda saída é **JSON em stdout**; erros vão para stderr com exit code != 0.
- Valores monetário','.simplicio-loop\skills\payments\SKILL.md','f5096f0bc6f28cc490224b43770109dd84d4d7c9df3d1ab0933bd4ae5715f191','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:peft','project_skill','skill://simplicio-runtime/peft','skill: peft','---
name: peft-fine-tuning
description: Parameter-efficient fine-tuning for LLMs using LoRA, QLoRA, and 25+ methods. Use when fine-tuning large models (7B-70B) with limited GPU memory, when you need to train <1% of parameters with minimal accuracy loss, or for multi-adapter serving. HuggingFace''s official library integrated with transformers ecosystem.
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [peft>=0.13.0, transformers>=4.45.0, torch>=2.0.0, bitsandbytes>=0.43.0]
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Fine-Tuning, PEFT, LoRA, QLoRA, Parameter-Efficient, Adapters, Low-Rank, Memory Optimization, Multi-Adapter]

---

# PEFT (Parameter-Efficient Fine-Tuning)

Fine-tune LLMs by training <1% of parameters using LoRA, QLoRA, and 25+ adapter methods.

## When to use PEFT

**Use PEFT/LoRA when:**
- Fine-tuning 7B-70B models on consumer GPUs (RTX 4090, A100)
- Need to train <1% parameters (6MB adapters vs 14GB full model)
- Want fast iteration with multiple task-specific adapters
- Deploying multiple fine-tuned variants from one base model

**Use QLoRA (PEFT + quantization) when:**
- Fine-tuning 70B models on single 24GB GPU
- Memory is the primary constraint
- Can accept ~5% quality trade-off vs full fine-tuning

**Use full fine-tuning instead when:**
- Training small models (<1B parameters)
- Need maximum quality and have compute budget
- Significant domain shift requires updating all weights

## Quick start

### Installation

```bash
# Basic installation
pip install peft

# With quantization support (recommended)
pip install peft bitsandbytes

# Full stack
pip install peft transformers accelerate bitsandbytes datasets
```

### LoRA fine-tuning (standard)

```python
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer
from peft import get_peft_model, LoraConfig, TaskType
from datasets import load_dataset

# Load base model
model_name = "meta-llama/Llama-3.1-8B"
model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype="auto", device_map="auto")
tokenizer = AutoTokenizer.from_pretrained(model_name)
tokenizer.pad_token = tokenizer.eos_token

# LoRA configuration
lora_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=16,                          # Rank (8-64, higher = more capacity)
    lora_alpha=32,                 # Scaling factor (typically 2*r)
    lora_dropout=0.05,             # Dropout for regularization
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],  # Attention layers
    bias="none"                    # Don''t train biases
)

# Apply LoRA
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()
# Output: trainable params: 13,631,488 || all params: 8,043,307,008 || trainable%: 0.17%

# Prepare dataset
dataset = load_dataset("databricks/databricks-dolly-15k", split="train")

def tokenize(example):
    text = f"### Instruction:\n{example[''instruction'']}\n\n### Response:\n{example[''response'']}"
    return tokenizer(text, truncation=True, max_length=512, padding="max_length")

tokenized = dataset.map(tokenize, remove_columns=dataset.column_names)

# Training
training_args = TrainingArguments(
    output_dir="./lora-llama",
    num_train_epochs=3,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    fp16=True,
    logging_steps=10,
    save_strategy="epoch"
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized,
    data_collator=lambda data: {"input_ids": torch.stack([f["input_ids"] for f in data]),
                                 "attention_mask": torch.stack([f["attention_mask"] for f in data]),
                                 "labels": torch.stack([f["input_ids"] for f in data])}
)

trainer.train()

# Save adapter only (6MB vs 16GB)
model.save_pretrained("./lora-llama-adapter")
```

### QLoRA fine-tuning (memory-efficient)

```python
from transformers import AutoModelForCausalLM, BitsAndBytesConfig
from peft import get_peft_model, LoraConfig, prepare_model_for_kbit_training

# 4-bit quantization ','.simplicio-loop\skills\peft\SKILL.md','dd3b21d349380daa5b2b514065afdd45436e7ba341139a2af2752c68622b02b2','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pinecone','project_skill','skill://simplicio-runtime/pinecone','skill: pinecone','---
name: pinecone
description: Managed vector database for production AI applications. Fully managed, auto-scaling, with hybrid search (dense + sparse), metadata filtering, and namespaces. Low latency (<100ms p95). Use for production RAG, recommendation systems, or semantic search at scale. Best for serverless, managed infrastructure.
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [pinecone-client]
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [RAG, Pinecone, Vector Database, Managed Service, Serverless, Hybrid Search, Production, Auto-Scaling, Low Latency, Recommendations]

---

# Pinecone - Managed Vector Database

The vector database for production AI applications.

## When to use Pinecone

**Use when:**
- Need managed, serverless vector database
- Production RAG applications
- Auto-scaling required
- Low latency critical (<100ms)
- Don''t want to manage infrastructure
- Need hybrid search (dense + sparse vectors)

**Metrics**:
- Fully managed SaaS
- Auto-scales to billions of vectors
- **p95 latency <100ms**
- 99.9% uptime SLA

**Use alternatives instead**:
- **Chroma**: Self-hosted, open-source
- **FAISS**: Offline, pure similarity search
- **Weaviate**: Self-hosted with more features

## Quick start

### Installation

```bash
pip install pinecone-client
```

### Basic usage

```python
from pinecone import Pinecone, ServerlessSpec

# Initialize
pc = Pinecone(api_key="your-api-key")

# Create index
pc.create_index(
    name="my-index",
    dimension=1536,  # Must match embedding dimension
    metric="cosine",  # or "euclidean", "dotproduct"
    spec=ServerlessSpec(cloud="aws", region="us-east-1")
)

# Connect to index
index = pc.Index("my-index")

# Upsert vectors
index.upsert(vectors=[
    {"id": "vec1", "values": [0.1, 0.2, ...], "metadata": {"category": "A"}},
    {"id": "vec2", "values": [0.3, 0.4, ...], "metadata": {"category": "B"}}
])

# Query
results = index.query(
    vector=[0.1, 0.2, ...],
    top_k=5,
    include_metadata=True
)

print(results["matches"])
```

## Core operations

### Create index

```python
# Serverless (recommended)
pc.create_index(
    name="my-index",
    dimension=1536,
    metric="cosine",
    spec=ServerlessSpec(
        cloud="aws",         # or "gcp", "azure"
        region="us-east-1"
    )
)

# Pod-based (for consistent performance)
from pinecone import PodSpec

pc.create_index(
    name="my-index",
    dimension=1536,
    metric="cosine",
    spec=PodSpec(
        environment="us-east1-gcp",
        pod_type="p1.x1"
    )
)
```

### Upsert vectors

```python
# Single upsert
index.upsert(vectors=[
    {
        "id": "doc1",
        "values": [0.1, 0.2, ...],  # 1536 dimensions
        "metadata": {
            "text": "Document content",
            "category": "tutorial",
            "timestamp": "2025-01-01"
        }
    }
])

# Batch upsert (recommended)
vectors = [
    {"id": f"vec{i}", "values": embedding, "metadata": metadata}
    for i, (embedding, metadata) in enumerate(zip(embeddings, metadatas))
]

index.upsert(vectors=vectors, batch_size=100)
```

### Query vectors

```python
# Basic query
results = index.query(
    vector=[0.1, 0.2, ...],
    top_k=10,
    include_metadata=True,
    include_values=False
)

# With metadata filtering
results = index.query(
    vector=[0.1, 0.2, ...],
    top_k=5,
    filter={"category": {"$eq": "tutorial"}}
)

# Namespace query
results = index.query(
    vector=[0.1, 0.2, ...],
    top_k=5,
    namespace="production"
)

# Access results
for match in results["matches"]:
    print(f"ID: {match[''id'']}")
    print(f"Score: {match[''score'']}")
    print(f"Metadata: {match[''metadata'']}")
```

### Metadata filtering

```python
# Exact match
filter = {"category": "tutorial"}

# Comparison
filter = {"price": {"$gte": 100}}  # $gt, $gte, $lt, $lte, $ne

# Logical operators
filter = {
    "$and": [
        {"category": "tutorial"},
        {"difficulty": {"$lte": 3}}
    ]
}  # Also: $or

# In operator
filter = {"tags": {"$in": ["python", "ml"]}}
```

## Namespaces

```python
# Partition data by namespace','.simplicio-loop\skills\pinecone\SKILL.md','8316751ad470a4f131f1ef8b65ab9c50d32973f5e430ce3b99f6076f1d455f24','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pinggy-tunnel','project_skill','skill://simplicio-runtime/pinggy-tunnel','skill: pinggy-tunnel','---
name: pinggy-tunnel
description: Zero-install localhost tunnels over SSH via Pinggy.
version: 0.1.0
author: Teknium (teknium1), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Pinggy, Tunnel, Networking, SSH, Webhook, Localhost]
    related_skills: [cloudflared-quick-tunnel, webhook-subscriptions]
---

# Pinggy Tunnel Skill

Expose a local service (dev server, webhook receiver, MCP endpoint, demo) to the public internet using a Pinggy SSH reverse tunnel. No daemon to install — the user''s stock SSH client connects to `a.pinggy.io:443` and Pinggy hands back a public HTTP/HTTPS URL.

Free tier: 60-minute tunnels, random subdomain, no signup. Pro tier ($3/mo) is an opt-in with a token.

## When to Use

- User asks to "expose this locally", "share my dev server", "make this URL public", "tunnel port N", "get a public URL for a webhook"
- Need to receive a webhook callback during a local task (Stripe, GitHub, Discord, AgentMail)
- Sharing a one-off HTTP demo (MCP server, Ollama/vLLM endpoint, dashboard) with a remote party
- The host has SSH but no `cloudflared` / `ngrok` binary, and installing one would be overkill

If the host already has `cloudflared` configured, prefer the `cloudflared-quick-tunnel` skill — Cloudflare quick tunnels don''t expire after 60 minutes.

## Prerequisites

- `ssh` on PATH (`ssh -V`). Default on Linux, macOS, and Windows 10+. No other install.
- A local service listening on `127.0.0.1:<port>` before the tunnel starts. Pinggy will return URLs but they''ll 502 until the local origin is up.

Optional:

- `PINGGY_TOKEN` env var for paid Pro features (persistent subdomain, custom domain, multiple tunnels, no 60-minute cap). Free tier needs no credentials.

## Quick Reference

```bash
# Plain HTTP/HTTPS tunnel for port 8000 (free tier)
ssh -p 443 -o StrictHostKeyChecking=no -o ServerAliveInterval=30 \
    -R0:localhost:8000 free@a.pinggy.io

# TCP tunnel (databases, raw SSH, etc.)
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:5432 tcp@a.pinggy.io

# TLS tunnel (Pinggy can''t decrypt — bring your own certs at origin)
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:443 tls@a.pinggy.io

# Basic auth gate (b:user:pass)
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:8000 \
    "b:admin:secret+free@a.pinggy.io"

# Bearer token gate (k:token)
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:8000 \
    "k:mysecrettoken+free@a.pinggy.io"

# IP whitelist (w:CIDR)
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:8000 \
    "w:203.0.113.0/24+free@a.pinggy.io"

# Enable CORS + force HTTPS redirect
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:8000 \
    "co+x:https+free@a.pinggy.io"

# Pro tier (persistent URL, no 60-min cap)
ssh -p 443 -o StrictHostKeyChecking=no -R0:localhost:8000 "$PINGGY_TOKEN+a.pinggy.io"
```

## Procedure — Start a Tunnel and Get the URL

The model SHOULD use the `terminal` tool. The tunnel must stay alive for the duration of the share, so run it as a background process and parse the public URL from stdout.

### 1. Confirm a local origin is up

```bash
curl -sI http://127.0.0.1:8000/ | head -1
# expect HTTP/1.x 200 (or any non-connection-refused response)
```

If nothing is listening yet, start it first (e.g. `python3 -m http.server 8000 --bind 127.0.0.1`). Pinggy will happily return a URL pointed at nothing — the user will see 502 until the origin comes up.

### 2. Launch the tunnel as a background process

Use `terminal(background=True)` and capture output to a logfile (Pinggy prints the URLs on stdout, then keeps the connection open):

```bash
LOG=/tmp/pinggy-8000.log
nohup ssh -p 443 \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -R0:localhost:8000 free@a.pinggy.io \
    > "$LOG" 2>&1 &
echo $! > /tmp/pinggy-8000.pid
```

`StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null` skips the first-run host-key prompt. `ServerAliveInterval=30` keeps the SSH session from getting torn down by an idle NAT.

### 3. Parse the UR','.simplicio-loop\skills\pinggy-tunnel\SKILL.md','db99dceda97693e0125be1ecf3cbbc2f48d005eb02597429e7f6ac16e0f9e9a5','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pixel-art','project_skill','skill://simplicio-runtime/pixel-art','skill: pixel-art','---
name: pixel-art
description: "Pixel art w/ era palettes (NES, Game Boy, PICO-8)."
version: 2.0.0
author: dodo-reach
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [creative, pixel-art, arcade, snes, nes, gameboy, retro, image, video]
    category: creative
    credits:
      - "Hardware palettes and animation loops ported from Synero/pixel-art-studio (MIT) — https://github.com/Synero/pixel-art-studio"
---

# Pixel Art

Convert any image into retro pixel art, then optionally animate it into a short
MP4 or GIF with era-appropriate effects (rain, fireflies, snow, embers).

Two scripts ship with this skill:

- `scripts/pixel_art.py` — photo → pixel-art PNG (Floyd-Steinberg dithering)
- `scripts/pixel_art_video.py` — pixel-art PNG → animated MP4 (+ optional GIF)

Each is importable or runnable directly. Presets snap to hardware palettes
when you want era-accurate colors (NES, Game Boy, PICO-8, etc.), or use
adaptive N-color quantization for arcade/SNES-style looks.

## When to Use

- User wants retro pixel art from a source image
- User asks for NES / Game Boy / PICO-8 / C64 / arcade / SNES styling
- User wants a short looping animation (rain scene, night sky, snow, etc.)
- Posters, album covers, social posts, sprites, characters, avatars

## Workflow

Before generating, confirm the style with the user. Different presets produce
very different outputs and regenerating is costly.

### Step 1 — Offer a style

Call `clarify` with 4 representative presets. Pick the set based on what the
user asked for — don''t just dump all 14.

Default menu when the user''s intent is unclear:

```python
clarify(
    question="Which pixel-art style do you want?",
    choices=[
        "arcade — bold, chunky 80s cabinet feel (16 colors, 8px)",
        "nes — Nintendo 8-bit hardware palette (54 colors, 8px)",
        "gameboy — 4-shade green Game Boy DMG",
        "snes — cleaner 16-bit look (32 colors, 4px)",
    ],
)
```

When the user already named an era (e.g. "80s arcade", "Gameboy"), skip
`clarify` and use the matching preset directly.

### Step 2 — Offer animation (optional)

If the user asked for a video/GIF, or the output might benefit from motion,
ask which scene:

```python
clarify(
    question="Want to animate it? Pick a scene or skip.",
    choices=[
        "night — stars + fireflies + leaves",
        "urban — rain + neon pulse",
        "snow — falling snowflakes",
        "skip — just the image",
    ],
)
```

Do NOT call `clarify` more than twice in a row. One for style, one for scene if
animation is on the table. If the user explicitly asked for a specific style
and scene in their message, skip `clarify` entirely.

### Step 3 — Generate

Run `pixel_art()` first; if animation was requested, chain into
`pixel_art_video()` on the result.

## Preset Catalog

| Preset | Era | Palette | Block | Best for |
|--------|-----|---------|-------|----------|
| `arcade` | 80s arcade | adaptive 16 | 8px | Bold posters, hero art |
| `snes` | 16-bit | adaptive 32 | 4px | Characters, detailed scenes |
| `nes` | 8-bit | NES (54) | 8px | True NES look |
| `gameboy` | DMG handheld | 4 green shades | 8px | Monochrome Game Boy |
| `gameboy_pocket` | Pocket handheld | 4 grey shades | 8px | Mono GB Pocket |
| `pico8` | PICO-8 | 16 fixed | 6px | Fantasy-console look |
| `c64` | Commodore 64 | 16 fixed | 8px | 8-bit home computer |
| `apple2` | Apple II hi-res | 6 fixed | 10px | Extreme retro, 6 colors |
| `teletext` | BBC Teletext | 8 pure | 10px | Chunky primary colors |
| `mspaint` | Windows MS Paint | 24 fixed | 8px | Nostalgic desktop |
| `mono_green` | CRT phosphor | 2 green | 6px | Terminal/CRT aesthetic |
| `mono_amber` | CRT amber | 2 amber | 6px | Amber monitor look |
| `neon` | Cyberpunk | 10 neons | 6px | Vaporwave/cyber |
| `pastel` | Soft pastel | 10 pastels | 6px | Kawaii / gentle |

Named palettes live in `scripts/palettes.py` (see `references/palettes.md` for
the complete list — 28 named palettes total). Any preset can be overridden:

```python
pixel_art("in.png", "out.png", preset="snes", palette="PICO_8",','.simplicio-loop\skills\pixel-art\SKILL.md','8163d0d8d1d97115ed90d6ea405210dbbcc15bab92360b63076fbc88d6d78fa1','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:plan','project_skill','skill://simplicio-runtime/plan','skill: plan','---
name: plan
description: "Plan mode: write an actionable markdown plan to .hermes/plans/, no execution. Bite-sized tasks, exact paths, complete code."
version: 2.0.0
author: Hermes Agent (writing-craft adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [planning, plan-mode, implementation, workflow, design, documentation]
    related_skills: [subagent-driven-development, test-driven-development, requesting-code-review]
---

# Plan Mode

Use this skill when the user wants a plan instead of execution.

## Core behavior

For this turn, you are planning only.

- Do not implement code.
- Do not edit project files except the plan markdown file.
- Do not run mutating terminal commands, commit, push, or perform external actions.
- You may inspect the repo or other context with read-only commands/tools when needed.
- Your deliverable is a markdown plan saved inside the active workspace under `.hermes/plans/`.

## Output requirements

Write a markdown plan that is concrete and actionable.

Include, when relevant:
- Goal
- Current context / assumptions
- Proposed approach
- Step-by-step plan
- Files likely to change
- Tests / validation
- Risks, tradeoffs, and open questions

If the task is code-related, include exact file paths, likely test targets, and verification steps.

## Save location

Save the plan with `write_file` under:
- `.hermes/plans/YYYY-MM-DD_HHMMSS-<slug>.md`

Treat that as relative to the active working directory / backend workspace. Hermes file tools are backend-aware, so using this relative path keeps the plan with the workspace on local, docker, ssh, modal, and daytona backends.

If the runtime provides a specific target path, use that exact path.
If not, create a sensible timestamped filename yourself under `.hermes/plans/`.

## Interaction style

- If the request is clear enough, write the plan directly.
- If no explicit instruction accompanies `/plan`, infer the task from the current conversation context.
- If it is genuinely underspecified, ask a brief clarifying question instead of guessing.
- After saving the plan, reply briefly with what you planned and the saved path.

---

# Writing the Plan Well

The rest of this skill is the craft of authoring a *good* implementation plan — the content that goes inside the markdown file above.

## Overview

Write comprehensive implementation plans assuming the implementer has zero context for the codebase and questionable taste. Document everything they need: which files to touch, complete code, testing commands, docs to check, how to verify. Give them bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume the implementer is a skilled developer but knows almost nothing about the toolset or problem domain. Assume they don''t know good test design very well.

**Core principle:** A good plan makes implementation obvious. If someone has to guess, the plan is incomplete.

## When a Full Implementation Plan Helps

**Always use before:**
- Implementing multi-step features
- Breaking down complex requirements
- Delegating to subagents via subagent-driven-development

**Don''t skip when:**
- Feature seems simple (assumptions cause bugs)
- You plan to implement it yourself (future you needs guidance)
- Working alone (documentation matters)

## Bite-Sized Task Granularity

**Each task = 2-5 minutes of focused work.**

Every step is one action:
- "Write the failing test" — step
- "Run it to make sure it fails" — step
- "Implement the minimal code to make the test pass" — step
- "Run the tests and make sure they pass" — step
- "Commit" — step

**Too big:**
```markdown
### Task 1: Build authentication system
[50 lines of code across 5 files]
```

**Right size:**
```markdown
### Task 1: Create User model with email field
[10 lines, 1 file]

### Task 2: Add password hash field to User
[8 lines, 1 file]

### Task 3: Create password hashing utility
[15 lines, 1 file]
```

## Plan Document Structure

### Header (Required)

Every plan MUST start with:

```markdown
# [Feature Name] Implementation Plan

> **For Hermes:** Use','.simplicio-loop\skills\plan\SKILL.md','cb1a8c3dd5338bfe580aa514828b439d0860d21f09bde4d39bd80e39cccc4f38','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:playwright-e2e','project_skill','skill://simplicio-runtime/playwright-e2e','skill: playwright-e2e','---
name: playwright-e2e
description: escrever ou atualizar testes end-to-end com Playwright neste projeto, garantindo trace, screenshot, vídeo e asserções consistentes
---

# Skill: `playwright-e2e`

Padrão para criar e atualizar testes E2E com Playwright. Garante que toda mudança que afeta UI ou fluxo crítico tenha cobertura, evidência salva e asserções determinísticas — sem `sleep` arbitrário, sem mock pra fazer passar.

---

## Trigger

- **OBRIGATÓRIO em TODA task técnica** (feature, fix, refactor, doc com build) — Playwright roda antes do commit. Smoke test mínimo se task não tem UI.
- Fluxo de usuário ponta a ponta (login, checkout, onboarding, etc.).
- Feature web nova sem cobertura E2E.
- Bug que se manifesta na UI e exige teste de regressão.
- Pedido explícito: "escreve teste e2e", "playwright", "smoke test web".
- Antes de fechar QUALQUER PR (toca rota, página, interação ou não — smoke garante que app sobe).

---

## Hard rule — evidência em TODA task

Regra dura, sem exceção: nenhum PR fecha sem **trace + screenshot + video** salvos em `playwright-report/` + `test-results/`. Sem evidência = sem merge. CI bloqueia via `.github/workflows/dod.yml`.

- Task de UI → cenários: happy path, erro, auth states, viewports 375/1280, edge case.
- Task de backend puro → smoke spec: app sobe, endpoint principal responde 2xx, fluxo crítico passa.
- Task de doc/config → smoke: build não quebra + serve responde.
- Task de migration → roda app + valida fluxo afetado pela migration.

---

## Steps

1. **Identifique o cenário**. Liste o caminho feliz e os principais erros (input inválido, sessão expirada, 404/500, viewport mobile/desktop). Cada cenário vira um `test(...)`.
2. **Crie o arquivo** em `tests/e2e/<feature>.spec.ts`. Nome em `kebab-case` casando com a feature (ex.: `tests/e2e/login.spec.ts`).
3. **Importe fixtures padrão** do Playwright (`test`, `expect`) e qualquer fixture customizada do projeto (`tests/e2e/fixtures/`).
4. **Configure o `test.describe`** com nome legível (ex.: `Login flow`). Agrupe cenários relacionados.
5. **Use Page Object** quando o mesmo seletor aparecer em 3+ testes. Caso contrário, seletores inline são aceitáveis.
6. **Asserte estado final** com `await expect(...)`. Asserte URL, DOM visível e textos esperados — não asserte só ausência de erro.
7. **Confirme evidência**. `playwright.config.ts` já liga `trace: ''on''`, `screenshot: ''only-on-failure''` e `video: ''on-first-retry''`. Não desligue isso por teste.
8. **Rode local** com `npx playwright test tests/e2e/<feature>.spec.ts --reporter=list`. Verifique HTML report em `playwright-report/`.
9. **Commit**. Inclua o arquivo `.spec.ts`. Não commite `test-results/` nem `playwright-report/` (estão no `.gitignore`).
10. **No PR**, anexe screenshot do estado final do caminho feliz e descreva os cenários cobertos.

---

## Padrões

- **Naming**: `<feature>.spec.ts`, `<feature>.<sub>.spec.ts` para sub-fluxos longos.
- **Localização**: sempre `tests/e2e/`. Page Objects em `tests/e2e/pages/<Page>.ts`.
- **Seletores**: prefira `getByRole`, `getByLabel`, `getByTestId`. Evite `locator(''div.classe123'')` — frágil.
- **Espera**: nunca `await page.waitForTimeout(ms)`. Use `await expect(locator).toBeVisible()`, `toHaveURL`, `toHaveText`.
- **Asserções**: prefira `await expect(...).toBeVisible()` em vez de `if (locator.isVisible())`. Auto-retry built-in.
- **Setup/Teardown**: use `test.beforeEach` para login/seed; `test.afterEach` só se realmente precisar limpar.
- **Dados**: gere dados únicos por teste (`crypto.randomUUID()`) para evitar colisão entre runs paralelos.
- **Viewports**: cubra mobile (`375x667`), tablet (`768x1024`) e desktop (`1280x800`) quando o layout muda.
- **i18n**: se o app é multi-locale, parametrize `locale` no `test.use({ locale: ''pt-BR'' })` ou rode como projeto.
- **Sem `console.log`** deixado nos specs. Use `test.info().annotations` se precisar anotar.

---

## Definition of Done

- [ ] Spec roda local sem erro: `npx playwright test tests/e2e/<feature>.spec.ts`.
- [ ] Cenários documentados: caminho feliz + ao menos 1 erro + 1 viewport alternat','.simplicio-loop\skills\playwright-e2e\SKILL.md','6fd739e0498b912b79e6f22233c55df0798aad631a5572d9c133fd7ed2576a6d','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pokemon-player','project_skill','skill://simplicio-runtime/pokemon-player','skill: pokemon-player','---
name: pokemon-player
description: "Play Pokemon via headless emulator + RAM reads."
tags: [gaming, pokemon, emulator, pyboy, gameplay, gameboy]
platforms: [linux, macos, windows]
---
# Pokemon Player

Play Pokemon games via headless emulation using the `pokemon-agent` package.

## When to Use
- User says "play pokemon", "start pokemon", "pokemon game"
- User asks about Pokemon Red, Blue, Yellow, FireRed, etc.
- User wants to watch an AI play Pokemon
- User references a ROM file (.gb, .gbc, .gba)

## Startup Procedure

### 1. First-time setup (clone, venv, install)
The repo is NousResearch/pokemon-agent on GitHub. Clone it, then
set up a Python 3.10+ virtual environment. Use uv (preferred for speed)
to create the venv and install the package in editable mode with the
pyboy extra. If uv is not available, fall back to python3 -m venv + pip.

On this machine it is already set up at /home/teknium/pokemon-agent
with a venv ready — just cd there and source .venv/bin/activate.

You also need a ROM file. Ask the user for theirs. On this machine
one exists at roms/pokemon_red.gb inside that directory.
NEVER download or provide ROM files — always ask the user.

### 2. Start the game server
From inside the pokemon-agent directory with the venv activated, run
pokemon-agent serve with --rom pointing to the ROM and --port 9876.
Run it in the background with &.
To resume from a saved game, add --load-state with the save name.
Wait 4 seconds for startup, then verify with GET /health.

### 3. Set up live dashboard for user to watch
Use an SSH reverse tunnel via localhost.run so the user can view
the dashboard in their browser. Connect with ssh, forwarding local
port 9876 to remote port 80 on nokey@localhost.run. Redirect output
to a log file, wait 10 seconds, then grep the log for the .lhr.life
URL. Give the user the URL with /dashboard/ appended.
The tunnel URL changes each time — give the user the new one if restarted.

## Save and Load

### When to save
- Every 15-20 turns of gameplay
- ALWAYS before gym battles, rival encounters, or risky fights
- Before entering a new town or dungeon
- Before any action you are unsure about

### How to save
POST /save with a descriptive name. Good examples:
before_brock, route1_start, mt_moon_entrance, got_cut

### How to load
POST /load with the save name.

### List available saves
GET /saves returns all saved states.

### Loading on server startup
Use --load-state flag when starting the server to auto-load a save.
This is faster than loading via the API after startup.

## The Gameplay Loop

### Step 1: OBSERVE — check state AND take a screenshot
GET /state for position, HP, battle, dialog.
GET /screenshot and save to /tmp/pokemon.png, then use vision_analyze.
Always do BOTH — RAM state gives numbers, vision gives spatial awareness.

### Step 2: ORIENT
- Dialog/text on screen → advance it
- In battle → fight or run
- Party hurt → head to Pokemon Center
- Near objective → navigate carefully

### Step 3: DECIDE
Priority: dialog > battle > heal > story objective > training > explore

### Step 4: ACT — move 2-4 steps max, then re-check
POST /action with a SHORT action list (2-4 actions, not 10-15).

### Step 5: VERIFY — screenshot after every move sequence
Take a screenshot and use vision_analyze to confirm you moved where
intended. This is the MOST IMPORTANT step. Without vision you WILL get lost.

### Step 6: RECORD progress to memory with PKM: prefix

### Step 7: SAVE periodically

## Action Reference
- press_a — confirm, talk, select
- press_b — cancel, close menu
- press_start — open game menu
- walk_up/down/left/right — move one tile
- hold_b_N — hold B for N frames (use for speeding through text)
- wait_60 — wait about 1 second (60 frames)
- a_until_dialog_end — press A repeatedly until dialog clears

## Critical Tips from Experience

### USE VISION CONSTANTLY
- Take a screenshot every 2-4 movement steps
- The RAM state tells you position and HP but NOT what is around you
- Ledges, fences, signs, building doors, NPCs — only visible via screenshot
- Ask the vision model specific questions: "wh','.simplicio-loop\skills\pokemon-player\SKILL.md','2253fe5bc47621b31b7e0bd786e18234c250c3e94038617bf2c9970a0b775513','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:polymarket','project_skill','skill://simplicio-runtime/polymarket','skill: polymarket','---
name: polymarket
description: "Query Polymarket: markets, prices, orderbooks, history."
version: 1.0.0
author: Hermes Agent + Teknium
tags: [polymarket, prediction-markets, market-data, trading]
platforms: [linux, macos, windows]
---

# Polymarket — Prediction Market Data

Query prediction market data from Polymarket using their public REST APIs.
All endpoints are read-only and require zero authentication.

See `references/api-endpoints.md` for the full endpoint reference with curl examples.

## When to Use

- User asks about prediction markets, betting odds, or event probabilities
- User wants to know "what are the odds of X happening?"
- User asks about Polymarket specifically
- User wants market prices, orderbook data, or price history
- User asks to monitor or track prediction market movements

## Key Concepts

- **Events** contain one or more **Markets** (1:many relationship)
- **Markets** are binary outcomes with Yes/No prices between 0.00 and 1.00
- Prices ARE probabilities: price 0.65 means the market thinks 65% likely
- `outcomePrices` field: JSON-encoded array like `["0.80", "0.20"]`
- `clobTokenIds` field: JSON-encoded array of two token IDs [Yes, No] for price/book queries
- `conditionId` field: hex string used for price history queries
- Volume is in USDC (US dollars)

## Three Public APIs

1. **Gamma API** at `gamma-api.polymarket.com` — Discovery, search, browsing
2. **CLOB API** at `clob.polymarket.com` — Real-time prices, orderbooks, history
3. **Data API** at `data-api.polymarket.com` — Trades, open interest

## Typical Workflow

When a user asks about prediction market odds:

1. **Search** using the Gamma API public-search endpoint with their query
2. **Parse** the response — extract events and their nested markets
3. **Present** market question, current prices as percentages, and volume
4. **Deep dive** if asked — use clobTokenIds for orderbook, conditionId for history

## Presenting Results

Format prices as percentages for readability:
- outcomePrices `["0.652", "0.348"]` becomes "Yes: 65.2%, No: 34.8%"
- Always show the market question and probability
- Include volume when available

Example: `"Will X happen?" — 65.2% Yes ($1.2M volume)`

## Parsing Double-Encoded Fields

The Gamma API returns `outcomePrices`, `outcomes`, and `clobTokenIds` as JSON strings
inside JSON responses (double-encoded). When processing with Python, parse them with
`json.loads(market[''outcomePrices''])` to get the actual array.

## Rate Limits

Generous — unlikely to hit for normal usage:
- Gamma: 4,000 requests per 10 seconds (general)
- CLOB: 9,000 requests per 10 seconds (general)
- Data: 1,000 requests per 10 seconds (general)

## Limitations

- This skill is read-only — it does not support placing trades
- Trading requires wallet-based crypto authentication (EIP-712 signatures)
- Some new markets may have empty price history
- Geographic restrictions apply to trading but read-only data is globally accessible
','.simplicio-loop\skills\polymarket\SKILL.md','becfa71e730b482c3f087c4de4071fd25f0feb475aec1293aee0b845c10fa190','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:popular-web-designs','project_skill','skill://simplicio-runtime/popular-web-designs','skill: popular-web-designs','---
name: popular-web-designs
description: 54 real design systems (Stripe, Linear, Vercel) as HTML/CSS.
version: 1.0.0
author: Hermes Agent + Teknium (design systems sourced from VoltAgent/awesome-design-md)
license: MIT
tags: [design, css, html, ui, web-development, design-systems, templates]
platforms: [linux, macos, windows]
triggers:
  - build a page that looks like
  - make it look like stripe
  - design like linear
  - vercel style
  - create a UI
  - web design
  - landing page
  - dashboard design
  - website styled like
---

# Popular Web Designs

54 real-world design systems ready for use when generating HTML/CSS. Each template captures a
site''s complete visual language: color palette, typography hierarchy, component styles, spacing
system, shadows, responsive behavior, and practical agent prompts with exact CSS values.

## Related design skills

- **`claude-design`** — use for the design *process and taste* (scoping a brief,
  producing variants, verifying a local HTML artifact, avoiding AI-design slop).
  Pair it with this skill when the user wants a thoughtfully-designed page styled
  after a known brand: `claude-design` drives the workflow, this skill supplies
  the visual vocabulary.
- **`design-md`** — use when the deliverable is a formal DESIGN.md token spec
  file, not a rendered artifact.

## How to Use

1. Pick a design from the catalog below
2. Load it: `skill_view(name="popular-web-designs", file_path="templates/<site>.md")`
3. Use the design tokens and component specs when generating HTML
4. Pair with the `generative-widgets` skill to serve the result via cloudflared tunnel

Each template includes a **Hermes Implementation Notes** block at the top with:
- CDN font substitute and Google Fonts `<link>` tag (ready to paste)
- CSS font-family stacks for primary and monospace
- Reminders to use `write_file` for HTML creation and `browser_vision` for verification

## HTML Generation Pattern

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Page Title</title>
  <!-- Paste the Google Fonts <link> from the template''s Hermes notes -->
  <link href="https://fonts.googleapis.com/css2?family=..." rel="stylesheet">
  <style>
    /* Apply the template''s color palette as CSS custom properties */
    :root {
      --color-bg: #ffffff;
      --color-text: #171717;
      --color-accent: #533afd;
      /* ... more from template Section 2 */
    }
    /* Apply typography from template Section 3 */
    body {
      font-family: ''Inter'', system-ui, sans-serif;
      color: var(--color-text);
      background: var(--color-bg);
    }
    /* Apply component styles from template Section 4 */
    /* Apply layout from template Section 5 */
    /* Apply shadows from template Section 6 */
  </style>
</head>
<body>
  <!-- Build using component specs from the template -->
</body>
</html>
```

Write the file with `write_file`, serve with the `generative-widgets` workflow (cloudflared tunnel),
and verify the result with `browser_vision` to confirm visual accuracy.

## Font Substitution Reference

Most sites use proprietary fonts unavailable via CDN. Each template maps to a Google Fonts
substitute that preserves the design''s character. Common mappings:

| Proprietary Font | CDN Substitute | Character |
|---|---|---|
| Geist / Geist Sans | Geist (on Google Fonts) | Geometric, compressed tracking |
| Geist Mono | Geist Mono (on Google Fonts) | Clean monospace, ligatures |
| sohne-var (Stripe) | Source Sans 3 | Light weight elegance |
| Berkeley Mono | JetBrains Mono | Technical monospace |
| Airbnb Cereal VF | DM Sans | Rounded, friendly geometric |
| Circular (Spotify) | DM Sans | Geometric, warm |
| figmaSans | Inter | Clean humanist |
| Pin Sans (Pinterest) | DM Sans | Friendly, rounded |
| NVIDIA-EMEA | Inter (or Arial system) | Industrial, clean |
| CoinbaseDisplay/Sans | DM Sans | Geometric, trustworthy |
| UberMove | DM Sans | Bold, tight |
| HashiCorp Sans | Inter | Enterprise, neutral |
| waldenburgNormal (Sanity) | Space ','.simplicio-loop\skills\popular-web-designs\SKILL.md','d46b48297047a888d11c9ee7a4f3b6f70ea60dc776f7306cd41609bece840288','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:powerpoint','project_skill','skill://simplicio-runtime/powerpoint','skill: powerpoint','---
name: powerpoint
description: "Create, read, edit .pptx decks, slides, notes, templates."
license: Proprietary. LICENSE.txt has complete terms
platforms: [linux, macos, windows]
---

# Powerpoint Skill

## When to use

Use this skill any time a .pptx file is involved in any way — as input, output, or both. This includes: creating slide decks, pitch decks, or presentations; reading, parsing, or extracting text from any .pptx file (even if the extracted content will be used elsewhere, like in an email or summary); editing, modifying, or updating existing presentations; combining or splitting slide files; working with templates, layouts, speaker notes, or comments. Trigger whenever the user mentions "deck," "slides," "presentation," or references a .pptx filename, regardless of what they plan to do with the content afterward. If a .pptx file needs to be opened, created, or touched, use this skill.

## Quick Reference

| Task | Guide |
|------|-------|
| Read/analyze content | `python -m markitdown presentation.pptx` |
| Edit or create from template | Read [editing.md](editing.md) |
| Create from scratch | Read [pptxgenjs.md](pptxgenjs.md) |

---

## Reading Content

```bash
# Text extraction
python -m markitdown presentation.pptx

# Visual overview
python scripts/thumbnail.py presentation.pptx

# Raw XML
python scripts/office/unpack.py presentation.pptx unpacked/
```

---

## Editing Workflow

**Read [editing.md](editing.md) for full details.**

1. Analyze template with `thumbnail.py`
2. Unpack → manipulate slides → edit content → clean → pack

---

## Creating from Scratch

**Read [pptxgenjs.md](pptxgenjs.md) for full details.**

Use when no template or reference presentation is available.

---

## Design Ideas

**Don''t create boring slides.** Plain bullets on a white background won''t impress anyone. Consider ideas from this list for each slide.

### Before Starting

- **Pick a bold, content-informed color palette**: The palette should feel designed for THIS topic. If swapping your colors into a completely different presentation would still "work," you haven''t made specific enough choices.
- **Dominance over equality**: One color should dominate (60-70% visual weight), with 1-2 supporting tones and one sharp accent. Never give all colors equal weight.
- **Dark/light contrast**: Dark backgrounds for title + conclusion slides, light for content ("sandwich" structure). Or commit to dark throughout for a premium feel.
- **Commit to a visual motif**: Pick ONE distinctive element and repeat it — rounded image frames, icons in colored circles, thick single-side borders. Carry it across every slide.

### Color Palettes

Choose colors that match your topic — don''t default to generic blue. Use these palettes as inspiration:

| Theme | Primary | Secondary | Accent |
|-------|---------|-----------|--------|
| **Midnight Executive** | `1E2761` (navy) | `CADCFC` (ice blue) | `FFFFFF` (white) |
| **Forest & Moss** | `2C5F2D` (forest) | `97BC62` (moss) | `F5F5F5` (cream) |
| **Coral Energy** | `F96167` (coral) | `F9E795` (gold) | `2F3C7E` (navy) |
| **Warm Terracotta** | `B85042` (terracotta) | `E7E8D1` (sand) | `A7BEAE` (sage) |
| **Ocean Gradient** | `065A82` (deep blue) | `1C7293` (teal) | `21295C` (midnight) |
| **Charcoal Minimal** | `36454F` (charcoal) | `F2F2F2` (off-white) | `212121` (black) |
| **Teal Trust** | `028090` (teal) | `00A896` (seafoam) | `02C39A` (mint) |
| **Berry & Cream** | `6D2E46` (berry) | `A26769` (dusty rose) | `ECE2D0` (cream) |
| **Sage Calm** | `84B59F` (sage) | `69A297` (eucalyptus) | `50808E` (slate) |
| **Cherry Bold** | `990011` (cherry) | `FCF6F5` (off-white) | `2F3C7E` (navy) |

### For Each Slide

**Every slide needs a visual element** — image, chart, icon, or shape. Text-only slides are forgettable.

**Layout options:**
- Two-column (text left, illustration on right)
- Icon + text rows (icon in colored circle, bold header, description below)
- 2x2 or 2x3 grid (image on one side, grid of content blocks on other)
- Half-bleed image (full left or right side) with content overlay

**Data display:**
','.simplicio-loop\skills\powerpoint\SKILL.md','edad502ed9eaebd9a06026137e056c5afbe8049c9f9966263632ffb93f8c24b7','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pptx-author','project_skill','skill://simplicio-runtime/pptx-author','skill: pptx-author','---
name: pptx-author
description: Build PowerPoint decks headless with python-pptx. Pairs with excel-author for model-backed decks where every number traces to a workbook cell. Use for pitch decks, IC memos, earnings notes.
version: 1.0.0
author: Anthropic (adapted by Nous Research)
license: Apache-2.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [powerpoint, pptx, python-pptx, presentation, finance]
    related_skills: [excel-author, powerpoint]
---

# pptx-author

Produce a .pptx file on disk using `python-pptx`. Use when you need to deliver a deck as a file artifact, not drive a live PowerPoint session.

Adapted from Anthropic''s `pptx-author` and `pitch-deck` skills in [anthropics/financial-services](https://github.com/anthropics/financial-services). The MCP / Office-JS branches of the originals are dropped — this assumes headless Python.

For the broader, already-shipped PowerPoint authoring skill (slides, speaker notes, embeds, media), see the built-in `powerpoint` skill. This skill is a lighter-weight pattern tuned for model-backed decks (pitch decks, IC memos, earnings notes) where every number must trace to a source workbook.

## Output contract

- Write to `./out/<name>.pptx`. Create `./out/` if it does not exist.
- Return the relative path in your final message.

## Setup

```bash
pip install "python-pptx>=0.6"
```

## Core conventions

### One idea per slide
Title states the takeaway; body supports it. A slide titled "Q3 Revenue" is weak; "Revenue growth accelerated to 14% Y/Y in Q3" is strong.

### Every number traces to the model
If a figure on a slide came from `./out/model.xlsx`, footnote the sheet and cell.

```
Revenue: $1,250M  (Source: model.xlsx, Inputs!C3)
```

Never transcribe numbers from memory or from a summary — open the workbook, read the named range, and bind the deck value to it programmatically when you can.

### Use the firm template when one is mounted
If `./templates/firm-template.pptx` exists, load it so the deck inherits branded colors, fonts, and master layouts.

```python
from pptx import Presentation
from pathlib import Path

template = Path("./templates/firm-template.pptx")
prs = Presentation(str(template)) if template.exists() else Presentation()
```

### Charts: PNG-from-model beats native pptx charts
When fidelity matters (the model''s chart styling must match the deck exactly), render the chart to PNG from the source workbook and embed the image. Native `pptx.chart` charts are fragile and often don''t match firm conventions.

```python
from pptx.util import Inches
slide.shapes.add_picture("./out/charts/football_field.png",
                         Inches(1), Inches(2),
                         width=Inches(8))
```

### No external sends
This skill writes a file. It never emails, uploads, or posts. Orchestration layers handle delivery.

## Skeleton

```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pathlib import Path

template = Path("./templates/firm-template.pptx")
prs = Presentation(str(template)) if template.exists() else Presentation()

# Title slide
slide = prs.slides.add_slide(prs.slide_layouts[0])
slide.shapes.title.text = "Project Aurora — Strategic Alternatives"
slide.placeholders[1].text = "Preliminary Discussion Materials"

# Valuation summary slide (title-only layout)
slide = prs.slides.add_slide(prs.slide_layouts[5])
slide.shapes.title.text = "Valuation implies $38–$52 per share across methodologies"

# Add a table bound to model outputs
rows, cols = 5, 4
tbl_shape = slide.shapes.add_table(rows, cols,
                                   Inches(0.5), Inches(1.5),
                                   Inches(9), Inches(3))
tbl = tbl_shape.table
headers = ["Methodology", "Low ($)", "Mid ($)", "High ($)"]
for c, h in enumerate(headers):
    tbl.cell(0, c).text = h

# In a real deck, read these from the model workbook with openpyxl
data = [
    ("Trading comps",     "35", "41", "48"),
    ("Precedent M&A",     "39", "45", "52"),
    ("DCF (base)",        "36", "43", "51"),
    ("LBO (10% IRR)','.simplicio-loop\skills\pptx-author\SKILL.md','7d5b7f38a93eb2179f2850508aae6b99a90baa26db8b9cbb5cdb676e962886b4','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pretext','project_skill','skill://simplicio-runtime/pretext','skill: pretext','---
name: pretext
description: "Use when building creative browser demos with @chenglou/pretext — DOM-free text layout for ASCII art, typographic flow around obstacles, text-as-geometry games, kinetic typography, and text-powered generative art. Produces single-file HTML demos by default."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [creative-coding, typography, pretext, ascii-art, canvas, generative, text-layout, kinetic-typography]
    related_skills: [p5js, claude-design, excalidraw, architecture-diagram]
---

# Pretext Creative Demos

## Overview

[`@chenglou/pretext`](https://github.com/chenglou/pretext) is a 15KB zero-dependency TypeScript library by Cheng Lou (React core, ReasonML, Midjourney) for **DOM-free multiline text measurement and layout**. It does one thing: given `(text, font, width)`, return the line breaks, per-line widths, per-grapheme positions, and total height — all via canvas measurement, no reflow.

That sounds like plumbing. It is not. Because it is fast and geometric, it is a **creative primitive**: you can reflow paragraphs around a moving sprite at 60fps, build games whose level geometry is made of real words, drive ASCII logos through prose, shatter text into particles with exact per-grapheme starting positions, or pack shrink-wrapped multiline UI without any `getBoundingClientRect` thrash.

This skill exists so Hermes can make **cool demos** with it — the kind people post to X. See `pretext.cool` and `chenglou.me/pretext` for the community demo corpus.

## When to Use

Use when the user asks for:
- A "pretext demo" / "cool pretext thing" / "text-as-X"
- Text flowing around a moving shape (hero sections, editorial layouts, animated long-form pages)
- ASCII-art effects using **real words or prose**, not monospace rasters
- Games where the playfield / obstacles / bricks are made of text (Tetris-from-letters, Breakout-of-prose)
- Kinetic typography with per-glyph physics (shatter, scatter, flock, flow)
- Typographic generative art, especially with non-Latin scripts or mixed scripts
- Multiline "shrink-wrap" UI (smallest container width that still fits the text)
- Anything that would require knowing line breaks *before* rendering

Don''t use for:
- Static SVG/HTML pages where CSS already solves layout — just use CSS
- Rich text editors, general inline formatting engines (pretext is intentionally narrow)
- Image → text (use `ascii-art` / `ascii-video` skills)
- Pure canvas generative art with no text role — use `p5js`

## Creative Standard

This is visual art rendered in a browser. Pretext returns numbers; **you** draw the thing.

- **Don''t ship a "hello world" demo.** The `hello-orb-flow.html` template is the *starting* point. Every delivered demo must add intentional color, motion, composition, and one visual detail the user didn''t ask for but will appreciate.
- **Dark backgrounds, warm cores, considered palette.** Classic amber-on-black (CRT / terminal) works, but so do cold-white-on-charcoal (editorial) and desaturated pastels (risograph). Pick one and commit.
- **Proportional fonts are the point.** Pretext''s whole vibe is "not monospaced" — lean into it. Use Iowan Old Style, Inter, JetBrains Mono, Helvetica Neue, or a variable font. Never default sans.
- **Real source/text, not lorem ipsum.** The corpus should mean something. Short manifestos, poetry, real source code, a found text, the library''s own README — never `lorem ipsum`.
- **First-paint excellence.** No loading states, no blank frames. The demo must look shippable the instant it opens.

## Stack

Single self-contained HTML file per demo. No build step.

| Layer | Tool | Purpose |
|-------|------|---------|
| Core | `@chenglou/pretext` via `esm.sh` CDN | Text measurement + line layout |
| Render | HTML5 Canvas 2D | Glyph rendering, per-frame composition |
| Segmentation | `Intl.Segmenter` (built-in) | Grapheme splitting for emoji / CJK / combining marks |
| Interaction | Raw DOM events | Mouse / touch / wheel — no framework |

```html
<script type="module">
import {','.simplicio-loop\skills\pretext\SKILL.md','4e625a31285f98e71957bf09f3fa5ad2b42786f58fafae99322cc09f54014e72','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:python-debugpy','project_skill','skill://simplicio-runtime/python-debugpy','skill: python-debugpy','---
name: python-debugpy
description: "Debug Python: pdb REPL + debugpy remote (DAP)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [debugging, python, pdb, debugpy, breakpoints, dap, post-mortem]
    related_skills: [systematic-debugging, node-inspect-debugger, debugging-hermes-tui-commands]
---

# Python Debugger (pdb + debugpy)

## Overview

Three tools, picked by situation:

| Tool | When |
|---|---|
| **`breakpoint()` + pdb** | Local, interactive, simplest. Add `breakpoint()` in the source, run normally, get a REPL at that line. |
| **`python -m pdb`** | Launch an existing script under pdb with no source edits. Useful for quick poking. |
| **`debugpy`** | Remote / headless / "attach to already-running process." Talks DAP, scriptable from terminal, works for long-lived processes (gateway, daemon, PTY children). |

**Start with `breakpoint()`.** It''s the cheapest thing that works.

## When to Use

- A test fails and the traceback doesn''t reveal why a value is wrong
- You need to step through a function and watch a collection mutate
- A long-running process (hermes gateway, tui_gateway) misbehaves and you can''t restart it
- Post-mortem: an exception fired in prod-ish code and you want to inspect locals at the crash site
- A subprocess / child (Python `_SlashWorker`, PTY bridge worker) is the actual bug site

**Don''t use for:** things `print()` / `logging.debug` solve in under a minute, or things `pytest -vv --tb=long --showlocals` already reveals.

## pdb Quick Reference

Inside any pdb prompt (`(Pdb)`):

| Command | Action |
|---|---|
| `h` / `h cmd` | help |
| `n` | next line (step over) |
| `s` | step into |
| `r` | return from current function |
| `c` | continue |
| `unt N` | continue until line N |
| `j N` | jump to line N (same function only) |
| `l` / `ll` | list source around current line / full function |
| `w` | where (stack trace) |
| `u` / `d` | move up / down in the stack |
| `a` | print args of the current function |
| `p expr` / `pp expr` | print / pretty-print expression |
| `display expr` | auto-print expr on every stop |
| `b file:line` | set breakpoint |
| `b func` | break on function entry |
| `b file:line, cond` | conditional breakpoint |
| `cl N` | clear breakpoint N |
| `tbreak file:line` | one-shot breakpoint |
| `!stmt` | execute arbitrary Python (assignments included) |
| `interact` | drop into full Python REPL in current scope (Ctrl+D to exit) |
| `q` | quit |

The `interact` command is the most powerful — you can import anything, inspect complex objects, even call methods that mutate state. Locals are read-only by default; use `!x = 42` from the `(Pdb)` prompt to mutate.

## Recipe 1: Local breakpoint

Easiest. Edit the file:

```python
def compute(x, y):
    result = some_helper(x)
    breakpoint()           # <-- drops into pdb here
    return result + y
```

Run the code normally. You land at the `breakpoint()` line with full access to locals.

**Don''t forget to remove `breakpoint()` before committing.** Use `git diff` or a pre-commit grep:
```bash
rg -n ''breakpoint\(\)'' --type py
```

## Recipe 2: Launch a script under pdb (no source edits)

```bash
python -m pdb path/to/script.py arg1 arg2
# Lands at first line of script
(Pdb) b path/to/script.py:42
(Pdb) c
```

## Recipe 3: Debug a pytest test

The hermes test runner and pytest both support this:

```bash
# Drop to pdb on failure (or on any raised exception):
scripts/run_tests.sh tests/path/to/test_file.py::test_name --pdb

# Drop to pdb at the START of the test:
scripts/run_tests.sh tests/path/to/test_file.py::test_name --trace

# Show locals in tracebacks without pdb:
scripts/run_tests.sh tests/path/to/test_file.py --showlocals --tb=long
```

Note: `scripts/run_tests.sh` uses xdist (`-n 4`) by default, and pdb does NOT work under xdist. Add `-p no:xdist` or run a single test with `-n 0`:

```bash
scripts/run_tests.sh tests/foo_test.py::test_bar --pdb -p no:xdist
# or
source .venv/bin/activate
python -m pytest tests/foo_test.py::test_bar --pdb
```

This bypasses the hermetic-','.simplicio-loop\skills\python-debugpy\SKILL.md','d9b0d688f8835b606620feb6b6d69023d955588de73567feb5068e7bf7428784','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pytorch-fsdp','project_skill','skill://simplicio-runtime/pytorch-fsdp','skill: pytorch-fsdp','---
name: pytorch-fsdp
description: Expert guidance for Fully Sharded Data Parallel training with PyTorch FSDP - parameter sharding, mixed precision, CPU offloading, FSDP2
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [torch>=2.0, transformers]
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Distributed Training, PyTorch, FSDP, Data Parallel, Sharding, Mixed Precision, CPU Offloading, FSDP2, Large-Scale Training]

---

# Pytorch-Fsdp Skill

Comprehensive assistance with pytorch-fsdp development, generated from official documentation.

## When to Use This Skill

This skill should be triggered when:
- Working with pytorch-fsdp
- Asking about pytorch-fsdp features or APIs
- Implementing pytorch-fsdp solutions
- Debugging pytorch-fsdp code
- Learning pytorch-fsdp best practices

## Quick Reference

### Common Patterns

**Pattern 1:** Generic Join Context Manager# Created On: Jun 06, 2025 | Last Updated On: Jun 06, 2025 The generic join context manager facilitates distributed training on uneven inputs. This page outlines the API of the relevant classes: Join, Joinable, and JoinHook. For a tutorial, see Distributed Training with Uneven Inputs Using the Join Context Manager. class torch.distributed.algorithms.Join(joinables, enable=True, throw_on_early_termination=False, **kwargs)[source]# This class defines the generic join context manager, which allows custom hooks to be called after a process joins. These hooks should shadow the collective communications of non-joined processes to prevent hanging and erroring and to ensure algorithmic correctness. Refer to JoinHook for details about the hook definition. Warning The context manager requires each participating Joinable to call the method notify_join_context() before its own per- iteration collective communications to ensure correctness. Warning The context manager requires that all process_group attributes in the JoinHook objects are the same. If there are multiple JoinHook objects, then the device of the first is used. The process group and device information is used for checking for non- joined processes and for notifying processes to throw an exception if throw_on_early_termination is enabled, both of which using an all- reduce. Parameters joinables (List[Joinable]) – a list of the participating Joinable s; their hooks are iterated over in the given order. enable (bool) – a flag enabling uneven input detection; setting to False disables the context manager’s functionality and should only be set when the user knows the inputs will not be uneven (default: True). throw_on_early_termination (bool) – a flag controlling whether to throw an exception upon detecting uneven inputs (default: False). Example: >>> import os >>> import torch >>> import torch.distributed as dist >>> import torch.multiprocessing as mp >>> import torch.nn.parallel.DistributedDataParallel as DDP >>> import torch.distributed.optim.ZeroRedundancyOptimizer as ZeRO >>> from torch.distributed.algorithms.join import Join >>> >>> # On each spawned worker >>> def worker(rank): >>> dist.init_process_group("nccl", rank=rank, world_size=2) >>> model = DDP(torch.nn.Linear(1, 1).to(rank), device_ids=[rank]) >>> optim = ZeRO(model.parameters(), torch.optim.Adam, lr=0.01) >>> # Rank 1 gets one more input than rank 0 >>> inputs = [torch.tensor([1.]).to(rank) for _ in range(10 + rank)] >>> with Join([model, optim]): >>> for input in inputs: >>> loss = model(input).sum() >>> loss.backward() >>> optim.step() >>> # All ranks reach here without hanging/erroring static notify_join_context(joinable)[source]# Notifies the join context manager that the calling process has not yet joined. Then, if throw_on_early_termination=True, checks if uneven inputs have been detected (i.e. if one process has already joined) and throws an exception if so. This method should be called from a Joinable object before its per-iteration collective communications. For example, this should be called at the beginning of the forward pass in DistributedDataParallel. Only the first Joinable object passed into the context mana','.simplicio-loop\skills\pytorch-fsdp\SKILL.md','b07cf84ef519ea991cd6473b7a92a23c5afed060d4fd0dc365e14a390140c57b','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:pytorch-lightning','project_skill','skill://simplicio-runtime/pytorch-lightning','skill: pytorch-lightning','---
name: pytorch-lightning
description: High-level PyTorch framework with Trainer class, automatic distributed training (DDP/FSDP/DeepSpeed), callbacks system, and minimal boilerplate. Scales from laptop to supercomputer with same code. Use when you want clean training loops with built-in best practices.
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [lightning, torch, transformers]
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [PyTorch Lightning, Training Framework, Distributed Training, DDP, FSDP, DeepSpeed, High-Level API, Callbacks, Best Practices, Scalable]

---

# PyTorch Lightning - High-Level Training Framework

## Quick start

PyTorch Lightning organizes PyTorch code to eliminate boilerplate while maintaining flexibility.

**Installation**:
```bash
pip install lightning
```

**Convert PyTorch to Lightning** (3 steps):

```python
import lightning as L
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

# Step 1: Define LightningModule (organize your PyTorch code)
class LitModel(L.LightningModule):
    def __init__(self, hidden_size=128):
        super().__init__()
        self.model = nn.Sequential(
            nn.Linear(28 * 28, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, 10)
        )

    def training_step(self, batch, batch_idx):
        x, y = batch
        y_hat = self.model(x)
        loss = nn.functional.cross_entropy(y_hat, y)
        self.log(''train_loss'', loss)  # Auto-logged to TensorBoard
        return loss

    def configure_optimizers(self):
        return torch.optim.Adam(self.parameters(), lr=1e-3)

# Step 2: Create data
train_loader = DataLoader(train_dataset, batch_size=32)

# Step 3: Train with Trainer (handles everything else!)
trainer = L.Trainer(max_epochs=10, accelerator=''gpu'', devices=2)
model = LitModel()
trainer.fit(model, train_loader)
```

**That''s it!** Trainer handles:
- GPU/TPU/CPU switching
- Distributed training (DDP, FSDP, DeepSpeed)
- Mixed precision (FP16, BF16)
- Gradient accumulation
- Checkpointing
- Logging
- Progress bars

## Common workflows

### Workflow 1: From PyTorch to Lightning

**Original PyTorch code**:
```python
model = MyModel()
optimizer = torch.optim.Adam(model.parameters())
model.to(''cuda'')

for epoch in range(max_epochs):
    for batch in train_loader:
        batch = batch.to(''cuda'')
        optimizer.zero_grad()
        loss = model(batch)
        loss.backward()
        optimizer.step()
```

**Lightning version**:
```python
class LitModel(L.LightningModule):
    def __init__(self):
        super().__init__()
        self.model = MyModel()

    def training_step(self, batch, batch_idx):
        loss = self.model(batch)  # No .to(''cuda'') needed!
        return loss

    def configure_optimizers(self):
        return torch.optim.Adam(self.parameters())

# Train
trainer = L.Trainer(max_epochs=10, accelerator=''gpu'')
trainer.fit(LitModel(), train_loader)
```

**Benefits**: 40+ lines → 15 lines, no device management, automatic distributed

### Workflow 2: Validation and testing

```python
class LitModel(L.LightningModule):
    def __init__(self):
        super().__init__()
        self.model = MyModel()

    def training_step(self, batch, batch_idx):
        x, y = batch
        y_hat = self.model(x)
        loss = nn.functional.cross_entropy(y_hat, y)
        self.log(''train_loss'', loss)
        return loss

    def validation_step(self, batch, batch_idx):
        x, y = batch
        y_hat = self.model(x)
        val_loss = nn.functional.cross_entropy(y_hat, y)
        acc = (y_hat.argmax(dim=1) == y).float().mean()
        self.log(''val_loss'', val_loss)
        self.log(''val_acc'', acc)

    def test_step(self, batch, batch_idx):
        x, y = batch
        y_hat = self.model(x)
        test_loss = nn.functional.cross_entropy(y_hat, y)
        self.log(''test_loss'', test_loss)

    def configure_optimizers(self):
        return torch.optim.Adam(self.parameters(), lr=1e-3)

# Train with validation
trainer = L.Trainer(max_epochs=10)
trainer.fit(model, train_lo','.simplicio-loop\skills\pytorch-lightning\SKILL.md','b45ee9425b4b3497b050a4c16abad20a9887dc0e29731bb1dbd281ed6eacfed9','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:qdrant','project_skill','skill://simplicio-runtime/qdrant','skill: qdrant','---
name: qdrant-vector-search
description: High-performance vector similarity search engine for RAG and semantic search. Use when building production RAG systems requiring fast nearest neighbor search, hybrid search with filtering, or scalable vector storage with Rust-powered performance.
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [qdrant-client>=1.12.0]
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [RAG, Vector Search, Qdrant, Semantic Search, Embeddings, Similarity Search, HNSW, Production, Distributed]

---

# Qdrant - Vector Similarity Search Engine

High-performance vector database written in Rust for production RAG and semantic search.

## When to use Qdrant

**Use Qdrant when:**
- Building production RAG systems requiring low latency
- Need hybrid search (vectors + metadata filtering)
- Require horizontal scaling with sharding/replication
- Want on-premise deployment with full data control
- Need multi-vector storage per record (dense + sparse)
- Building real-time recommendation systems

**Key features:**
- **Rust-powered**: Memory-safe, high performance
- **Rich filtering**: Filter by any payload field during search
- **Multiple vectors**: Dense, sparse, multi-dense per point
- **Quantization**: Scalar, product, binary for memory efficiency
- **Distributed**: Raft consensus, sharding, replication
- **REST + gRPC**: Both APIs with full feature parity

**Use alternatives instead:**
- **Chroma**: Simpler setup, embedded use cases
- **FAISS**: Maximum raw speed, research/batch processing
- **Pinecone**: Fully managed, zero ops preferred
- **Weaviate**: GraphQL preference, built-in vectorizers

## Quick start

### Installation

```bash
# Python client
pip install qdrant-client

# Docker (recommended for development)
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant

# Docker with persistent storage
docker run -p 6333:6333 -p 6334:6334 \
    -v $(pwd)/qdrant_storage:/qdrant/storage \
    qdrant/qdrant
```

### Basic usage

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

# Connect to Qdrant
client = QdrantClient(host="localhost", port=6333)

# Create collection
client.create_collection(
    collection_name="documents",
    vectors_config=VectorParams(size=384, distance=Distance.COSINE)
)

# Insert vectors with payload
client.upsert(
    collection_name="documents",
    points=[
        PointStruct(
            id=1,
            vector=[0.1, 0.2, ...],  # 384-dim vector
            payload={"title": "Doc 1", "category": "tech"}
        ),
        PointStruct(
            id=2,
            vector=[0.3, 0.4, ...],
            payload={"title": "Doc 2", "category": "science"}
        )
    ]
)

# Search with filtering
results = client.search(
    collection_name="documents",
    query_vector=[0.15, 0.25, ...],
    query_filter={
        "must": [{"key": "category", "match": {"value": "tech"}}]
    },
    limit=10
)

for point in results:
    print(f"ID: {point.id}, Score: {point.score}, Payload: {point.payload}")
```

## Core concepts

### Points - Basic data unit

```python
from qdrant_client.models import PointStruct

# Point = ID + Vector(s) + Payload
point = PointStruct(
    id=123,                              # Integer or UUID string
    vector=[0.1, 0.2, 0.3, ...],        # Dense vector
    payload={                            # Arbitrary JSON metadata
        "title": "Document title",
        "category": "tech",
        "timestamp": 1699900000,
        "tags": ["python", "ml"]
    }
)

# Batch upsert (recommended)
client.upsert(
    collection_name="documents",
    points=[point1, point2, point3],
    wait=True  # Wait for indexing
)
```

### Collections - Vector containers

```python
from qdrant_client.models import VectorParams, Distance, HnswConfigDiff

# Create with HNSW configuration
client.create_collection(
    collection_name="documents",
    vectors_config=VectorParams(
        size=384,                        # Vector dimensions
        distance=Distance.COSINE         # COSINE, EUCLID, D','.simplicio-loop\skills\qdrant\SKILL.md','a79a258539612486260698a151c5dc4809b82fe81d310d09f58b8afcf4f48f3a','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:qmd','project_skill','skill://simplicio-runtime/qmd','skill: qmd','---
name: qmd
description: Search personal knowledge bases, notes, docs, and meeting transcripts locally using qmd — a hybrid retrieval engine with BM25, vector search, and LLM reranking. Supports CLI and MCP integration.
version: 1.0.0
author: Hermes Agent + Teknium
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [Search, Knowledge-Base, RAG, Notes, MCP, Local-AI]
    related_skills: [obsidian, native-mcp, arxiv]
---

# QMD — Query Markup Documents

Local, on-device search engine for personal knowledge bases. Indexes markdown
notes, meeting transcripts, documentation, and any text-based files, then
provides hybrid search combining keyword matching, semantic understanding, and
LLM-powered reranking — all running locally with no cloud dependencies.

Created by [Tobi Lütke](https://github.com/tobi/qmd). MIT licensed.

## When to Use

- User asks to search their notes, docs, knowledge base, or meeting transcripts
- User wants to find something across a large collection of markdown/text files
- User wants semantic search ("find notes about X concept") not just keyword grep
- User has already set up qmd collections and wants to query them
- User asks to set up a local knowledge base or document search system
- Keywords: "search my notes", "find in my docs", "knowledge base", "qmd"

## Prerequisites

### Node.js >= 22 (required)

```bash
# Check version
node --version  # must be >= 22

# macOS — install or upgrade via Homebrew
brew install node@22

# Linux — use NodeSource or nvm
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
# or with nvm:
nvm install 22 && nvm use 22
```

### SQLite with Extension Support (macOS only)

macOS system SQLite lacks extension loading. Install via Homebrew:

```bash
brew install sqlite
```

### Install qmd

```bash
npm install -g @tobilu/qmd
# or with Bun:
bun install -g @tobilu/qmd
```

First run auto-downloads 3 local GGUF models (~2GB total):

| Model | Purpose | Size |
|-------|---------|------|
| embeddinggemma-300M-Q8_0 | Vector embeddings | ~300MB |
| qwen3-reranker-0.6b-q8_0 | Result reranking | ~640MB |
| qmd-query-expansion-1.7B | Query expansion | ~1.1GB |

### Verify Installation

```bash
qmd --version
qmd status
```

## Quick Reference

| Command | What It Does | Speed |
|---------|-------------|-------|
| `qmd search "query"` | BM25 keyword search (no models) | ~0.2s |
| `qmd vsearch "query"` | Semantic vector search (1 model) | ~3s |
| `qmd query "query"` | Hybrid + reranking (all 3 models) | ~2-3s warm, ~19s cold |
| `qmd get <docid>` | Retrieve full document content | instant |
| `qmd multi-get "glob"` | Retrieve multiple files | instant |
| `qmd collection add <path> --name <n>` | Add a directory as a collection | instant |
| `qmd context add <path> "description"` | Add context metadata to improve retrieval | instant |
| `qmd embed` | Generate/update vector embeddings | varies |
| `qmd status` | Show index health and collection info | instant |
| `qmd mcp` | Start MCP server (stdio) | persistent |
| `qmd mcp --http --daemon` | Start MCP server (HTTP, warm models) | persistent |

## Setup Workflow

### 1. Add Collections

Point qmd at directories containing your documents:

```bash
# Add a notes directory
qmd collection add ~/notes --name notes

# Add project docs
qmd collection add ~/projects/myproject/docs --name project-docs

# Add meeting transcripts
qmd collection add ~/meetings --name meetings

# List all collections
qmd collection list
```

### 2. Add Context Descriptions

Context metadata helps the search engine understand what each collection
contains. This significantly improves retrieval quality:

```bash
qmd context add qmd://notes "Personal notes, ideas, and journal entries"
qmd context add qmd://project-docs "Technical documentation for the main project"
qmd context add qmd://meetings "Meeting transcripts and action items from team syncs"
```

### 3. Generate Embeddings

```bash
qmd embed
```

This processes all documents in all collections and generates vector
embeddings. Re-run after adding new ','.simplicio-loop\skills\qmd\SKILL.md','bf111efd1da590ae26d64d66ebdb66d4554e320b4a95da03799cdc80d79bb953','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:ralph-loop','project_skill','skill://simplicio-runtime/ralph-loop','skill: ralph-loop','---
name: ralph-loop
description: Loop autônomo de coding (read → plan → execute → lint → unit → e2e → fix → repeat) até DoD verde. Padrão deste projeto em TODA task técnica com acceptance criteria mensurável.
status: always-on
source: https://github.com/frankbria/ralph-claude-code
---

# Skill: `ralph-loop`

Padrão Ralph Wiggum technique adaptado pro LLM-Project-Mapper. Toda task técnica passa por este loop. Não opcional.

> **Sempre ativo neste projeto.** Disparado via `/ralph-loop "<objetivo>"`, `$ralph-loop` no prompt, ou implicitamente quando task tem AC mensurável.

---

## Trigger

- Task técnica com acceptance criteria mensurável em `.specs/sprints/sprint-XX/<id>.task.md`.
- Pedido com verbo: "implementa", "corrige", "refatora", "adiciona", "finaliza".
- Comando explícito: `/ralph-loop "<objetivo>"`, `$ralph-loop`.
- Bug com reprodução clara + critério de fix.

NÃO ativa pra: pergunta one-off, lookup, exploração read-only, decisão arquitetural (esse é `architect` agent).

---

## Steps (loop até DoD verde)

1. **Read** — abre task em `.specs/sprints/sprint-XX/<id>.task.md`. Lê Contexto + AC + Test plan + DoD + Pegadinhas. Lê ADRs linkadas em `.specs/architecture/`.
2. **Plan** — escreve plano interno curto: arquivos que mudam, ordem, como verificar, efeitos colaterais. Task ambígua → pergunta antes de codar. Task grande → dispara agents `planner` + `architect` paralelo.
3. **Execute** — edits cirúrgicos. Só toca o pedido. Sem refactor extra. Sem rename. Sem comentário a mais.
4. **Lint** — `npm run lint` (ou equivalente da stack). Vermelho → volta passo 3.
5. **Unit** — `npm test`. Coverage diff ≥ 80%. Vermelho → volta passo 3.
6. **E2E** — `npx playwright test --reporter=list,html` com trace + screenshot + video (todos, não "ou"). Cobre cenários: happy path, erro, auth states, locales, viewports. Vermelho → volta passo 3.
7. **Status block** — emitir bloco abaixo no fim de cada iteração:

   ```
   ---RALPH_STATUS---
   STATUS: IN_PROGRESS | COMPLETE | BLOCKED
   TASKS_COMPLETED_THIS_LOOP: <n>
   FILES_MODIFIED: <n>
   TESTS_STATUS: PASSING | FAILING | NOT_RUN
   WORK_TYPE: IMPLEMENTATION | TESTING | DOCUMENTATION | REFACTORING
   EXIT_SIGNAL: false | true
   RECOMMENDATION: <próximo passo curto>
   ---END_RALPH_STATUS---
   ```

8. **Exit gate (dual)** — só sai quando AMBOS verdadeiros:
   - Indicadores: AC todos `[x]`, lint+unit+E2E verdes, sem erro/warning novo, sem TODO sem dono.
   - `EXIT_SIGNAL: true` no status block.

9. **Commit + PR** — Conventional Commits inglês. PR via `gh pr create --fill`. Anexa evidências Playwright (`playwright-report/`, `test-results/`).

---

## Padrões

- **Uma task por loop** — foca no item de maior prioridade. Não acumula escopo.
- **Search before assume** — `Explore` agent antes de declarar "não existe".
- **Subagents pra trabalho independente** — disparar 3-5+ paralelo (research, read, review).
- **Testes proporcionais ao risco e ao DoD** — escrever os testes mínimos necessários para validar a mudança, cobrir regressão e cumprir unit + E2E + coverage diff exigidos pelo loop/DoD. Não impor quota fixa de esforço. Não escrever teste pra comportamento ainda não implementado nesta loop.
- **Files protegidos**: `.specs/sprints/*/SPRINT.md` em curso, `.claude/settings.json` (só via `update-config`), `AGENTS.md`/`CLAUDE.md` (só com aprovação).
- **Stack-aware**: identifica linguagem → carrega `*-patterns` + `*-security` + `*-testing` da stack ANTES de codar.
- **Reviewer agents obrigatório** após edits: `*-reviewer` da stack + `security-reviewer` se toca auth/input/segredo.

---

## Integração com agents

Dispara em paralelo conforme contexto:

| Fase | Agents |
|---|---|
| Plan | `Plan`, `everything-claude-code:planner`, `everything-claude-code:architect` |
| Search | `Explore` (quick/medium/thorough), `general-purpose` |
| Review | `*-reviewer` da stack, `everything-claude-code:code-reviewer`, `everything-claude-code:security-reviewer` |
| Build error | `*-build-resolver` da stack |
| E2E | `everything-claude-code:e2e-runner` |
| Docs | `everything-claude-code:doc-updater` |

P','.simplicio-loop\skills\ralph-loop\SKILL.md','7143dc67ef40e88d264caee7f2f09ae1e131c8a531d5767415b9018be2eeccdd','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:remotion-to-hyperframes:skills','project_skill','skill://simplicio-runtime/remotion-to-hyperframes','skill: remotion-to-hyperframes','---
name: remotion-to-hyperframes
description: Translate an existing Remotion (React-based) video composition into a HyperFrames HTML composition. Use ONLY when the user explicitly asks to port, convert, migrate, translate, or rewrite a Remotion composition as HyperFrames (e.g. "port my Remotion project to HyperFrames"). Do NOT use when (a) authoring a NEW HyperFrames composition (even if A/B-testing a Remotion video); (b) Remotion is mentioned in passing; (c) Remotion code is shared as reference, not for translation; (d) the user wants "the same video as my Remotion one" without explicitly asking to migrate the source — treat as a fresh HyperFrames build. When in doubt, default to the `hyperframes` skill. Detects unsupported patterns (useState, useEffect side effects, async calculateMetadata, third-party React component libraries, `@remotion/lambda`) and recommends the runtime interop escape hatch instead of a lossy translation.
---

# Remotion to HyperFrames

## Overview

Translate Remotion (React-based) video compositions into HyperFrames (HTML + GSAP) compositions. Most Remotion idioms have direct HyperFrames equivalents — the translation is mechanical for ~80% of typical compositions. This skill encodes the mapping and guards against the lossy 20% by refusing to translate patterns that don''t fit HF''s seek-driven model and recommending the runtime interop pattern from [PR #214](https://github.com/heygen-com/hyperframes/pull/214) instead.

The skill ships with a **tiered test corpus** (T1–T4, 4 fixtures total) that grades translations against measured SSIM thresholds. Don''t translate without running the eval — a translation that "looks right" but renders 0.05 SSIM lower than the validated baseline is silently wrong.

## When to use

**Use this skill ONLY when the user explicitly asks to migrate from Remotion.** Example trigger phrases:

- "port my Remotion project to HyperFrames"
- "convert this Remotion code to HyperFrames"
- "migrate from Remotion"
- "translate this Remotion comp"
- "rewrite this as HyperFrames HTML"

**Do NOT use this skill when:**

- (a) The user is authoring a **new** HyperFrames composition, even if they have or are A/B-testing a similar Remotion video.
- (b) The user mentions Remotion in passing without asking for migration.
- (c) The user shares Remotion code as reference material rather than asking for a translation.
- (d) The user asks for "the same video as my Remotion one" without explicitly asking to migrate the source — treat that as a fresh HyperFrames build.

When in doubt, default to authoring a native HyperFrames composition with the `hyperframes` skill instead.

## Workflow

### Step 1: Lint the source

Run [`scripts/lint_source.py`](scripts/lint_source.py) over the Remotion source directory. The lint detects patterns that can''t translate cleanly:

- **Blockers** (refuse + recommend interop): `useState`, `useReducer`, `useEffect`/`useLayoutEffect` with non-empty deps, async `calculateMetadata`, third-party React UI libraries (MUI, Chakra, Mantine, antd, shadcn, Radix, NextUI).
- **Warnings** (translate after dropping the construct): `@remotion/lambda` config, `delayRender`, `useCallback`, `useMemo`, custom hooks.
- **Info** (translate with note): `staticFile`, `interpolateColors`.

If any blocker fires, **stop**. Read [`references/escape-hatch.md`](references/escape-hatch.md) and surface the recommendation message. Warnings don''t stop translation — drop the offending construct in step 3 and note the gap in `TRANSLATION_NOTES.md`. `@remotion/lambda` config is the canonical warning case: the skill drops the import + `renderMediaOnLambda(...)` calls but translates the rest of the composition.

### Step 2: Plan the translation

Read [`references/api-map.md`](references/api-map.md) — the index of every Remotion API and its HF equivalent or per-topic reference. Identify which topic references you''ll need based on what the source uses:

| Source contains                                                           | Load reference                                |
| ---------------------------','.simplicio-loop\skills\remotion-to-hyperframes\SKILL.md','83980f426cdbb1746f24ed30cb7bd855b3721c1880c6f028ddb45798a4cc2ef1','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:requesting-code-review','project_skill','skill://simplicio-runtime/requesting-code-review','skill: requesting-code-review','---
name: requesting-code-review
description: "Pre-commit review: security scan, quality gates, auto-fix."
version: 2.0.0
author: Hermes Agent (adapted from obra/superpowers + MorAlekss)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [code-review, security, verification, quality, pre-commit, auto-fix]
    related_skills: [subagent-driven-development, plan, test-driven-development, github-code-review]
---

# Pre-Commit Code Verification

Automated verification pipeline before code lands. Static scans, baseline-aware
quality gates, an independent reviewer subagent, and an auto-fix loop.

**Core principle:** No agent should verify its own work. Fresh context finds what you miss.

## When to Use

- After implementing a feature or bug fix, before `git commit` or `git push`
- When user says "commit", "push", "ship", "done", "verify", or "review before merge"
- After completing a task with 2+ file edits in a git repo
- After each task in subagent-driven-development (the two-stage review)

**Skip for:** documentation-only changes, pure config tweaks, or when user says "skip verification".

**This skill vs github-code-review:** This skill verifies YOUR changes before committing.
`github-code-review` reviews OTHER people''s PRs on GitHub with inline comments.

## Step 1 — Get the diff

```bash
git diff --cached
```

If empty, try `git diff` then `git diff HEAD~1 HEAD`.

If `git diff --cached` is empty but `git diff` shows changes, tell the user to
`git add <files>` first. If still empty, run `git status` — nothing to verify.

If the diff exceeds 15,000 characters, split by file:
```bash
git diff --name-only
git diff HEAD -- specific_file.py
```

## Step 2 — Static security scan

Scan added lines only. Any match is a security concern fed into Step 5.

```bash
# Hardcoded secrets
git diff --cached | grep "^+" | grep -iE "(api_key|secret|password|token|passwd)\s*=\s*[''\"][^''\"]{6,}[''\"]"

# Shell injection
git diff --cached | grep "^+" | grep -E "os\.system\(|subprocess.*shell=True"

# Dangerous eval/exec
git diff --cached | grep "^+" | grep -E "\beval\(|\bexec\("

# Unsafe deserialization
git diff --cached | grep "^+" | grep -E "pickle\.loads?\("

# SQL injection (string formatting in queries)
git diff --cached | grep "^+" | grep -E "execute\(f\"|\.format\(.*SELECT|\.format\(.*INSERT"
```

## Step 3 — Baseline tests and linting

Detect the project language and run the appropriate tools. Capture the failure
count BEFORE your changes as **baseline_failures** (stash changes, run, pop).
Only NEW failures introduced by your changes block the commit.

**Test frameworks** (auto-detect by project files):
```bash
# Python (pytest)
python -m pytest --tb=no -q 2>&1 | tail -5

# Node (npm test)
npm test -- --passWithNoTests 2>&1 | tail -5

# Rust
cargo test 2>&1 | tail -5

# Go
go test ./... 2>&1 | tail -5
```

**Linting and type checking** (run only if installed):
```bash
# Python
which ruff && ruff check . 2>&1 | tail -10
which mypy && mypy . --ignore-missing-imports 2>&1 | tail -10

# Node
which npx && npx eslint . 2>&1 | tail -10
which npx && npx tsc --noEmit 2>&1 | tail -10

# Rust
cargo clippy -- -D warnings 2>&1 | tail -10

# Go
which go && go vet ./... 2>&1 | tail -10
```

**Baseline comparison:** If baseline was clean and your changes introduce failures,
that''s a regression. If baseline already had failures, only count NEW ones.

## Step 4 — Self-review checklist

Quick scan before dispatching the reviewer:

- [ ] No hardcoded secrets, API keys, or credentials
- [ ] Input validation on user-provided data
- [ ] SQL queries use parameterized statements
- [ ] File operations validate paths (no traversal)
- [ ] External calls have error handling (try/catch)
- [ ] No debug print/console.log left behind
- [ ] No commented-out code
- [ ] New code has tests (if test suite exists)

## Step 5 — Independent reviewer subagent

Call `delegate_task` directly — it is NOT available inside execute_code or scripts.

The reviewer gets ONLY the diff and static scan results. No shared context with
the implementer. Fail-closed:','.simplicio-loop\skills\requesting-code-review\SKILL.md','0531dc4ec026f6f8578f1eddf3ab031d714bb5121f1b04e2d11f35aa48d61736','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:research-paper-writing','project_skill','skill://simplicio-runtime/research-paper-writing','skill: research-paper-writing','---
name: research-paper-writing
title: Research Paper Writing Pipeline
description: "Write ML papers for NeurIPS/ICML/ICLR: design→submit."
version: 1.1.0
author: Orchestra Research
license: MIT
dependencies: [semanticscholar, arxiv, habanero, requests, scipy, numpy, matplotlib, SciencePlots]
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Research, Paper Writing, Experiments, ML, AI, NeurIPS, ICML, ICLR, ACL, AAAI, COLM, LaTeX, Citations, Statistical Analysis]
    category: research
    related_skills: [arxiv, ml-paper-writing, subagent-driven-development, plan]
    requires_toolsets: [terminal, files]

---

# Research Paper Writing Pipeline

End-to-end pipeline for producing publication-ready ML/AI research papers targeting **NeurIPS, ICML, ICLR, ACL, AAAI, and COLM**. This skill covers the full research lifecycle: experiment design, execution, monitoring, analysis, paper writing, review, revision, and submission.

This is **not a linear pipeline** — it is an iterative loop. Results trigger new experiments. Reviews trigger new analysis. The agent must handle these feedback loops.

<!-- ascii-guard-ignore -->
```
┌─────────────────────────────────────────────────────────────┐
│                    RESEARCH PAPER PIPELINE                  │
│                                                             │
│  Phase 0: Project Setup ──► Phase 1: Literature Review      │
│       │                          │                          │
│       ▼                          ▼                          │
│  Phase 2: Experiment     Phase 5: Paper Drafting ◄──┐      │
│       Design                     │                   │      │
│       │                          ▼                   │      │
│       ▼                    Phase 6: Self-Review      │      │
│  Phase 3: Execution &           & Revision ──────────┘      │
│       Monitoring                 │                          │
│       │                          ▼                          │
│       ▼                    Phase 7: Submission               │
│  Phase 4: Analysis ─────► (feeds back to Phase 2 or 5)     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```
<!-- ascii-guard-ignore-end -->

---

## When To Use This Skill

Use this skill when:
- **Starting a new research paper** from an existing codebase or idea
- **Designing and running experiments** to support paper claims
- **Writing or revising** any section of a research paper
- **Preparing for submission** to a specific conference or workshop
- **Responding to reviews** with additional experiments or revisions
- **Converting** a paper between conference formats
- **Writing non-empirical papers** — theory, survey, benchmark, or position papers (see [Paper Types Beyond Empirical ML](#paper-types-beyond-empirical-ml))
- **Designing human evaluations** for NLP, HCI, or alignment research
- **Preparing post-acceptance deliverables** — posters, talks, code releases

## Core Philosophy

1. **Be proactive.** Deliver complete drafts, not questions. Scientists are busy — produce something concrete they can react to, then iterate.
2. **Never hallucinate citations.** AI-generated citations have ~40% error rate. Always fetch programmatically. Mark unverifiable citations as `[CITATION NEEDED]`.
3. **Paper is a story, not a collection of experiments.** Every paper needs one clear contribution stated in a single sentence. If you can''t do that, the paper isn''t ready.
4. **Experiments serve claims.** Every experiment must explicitly state which claim it supports. Never run experiments that don''t connect to the paper''s narrative.
5. **Commit early, commit often.** Every completed experiment batch, every paper draft update — commit with descriptive messages. Git log is the experiment history.

### Proactivity and Collaboration

**Default: Be proactive. Draft first, ask with the draft.**

| Confidence Level | Action |
|-----------------|--------|
| **High** (clear repo, obvious contribution) | Write full draft, deliver, iterate on feedback |
| **Mediu','.simplicio-loop\skills\research-paper-writing\SKILL.md','7c814d90a3b83d8513d404944e4cc4cfb5fd830db9521695c79f6d8dda70f063','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:rest-graphql-debug','project_skill','skill://simplicio-runtime/rest-graphql-debug','skill: rest-graphql-debug','---
name: rest-graphql-debug
description: "Debug REST/GraphQL APIs: status codes, auth, schemas, repro."
version: 1.2.0
author: eren-karakus0
license: MIT
metadata:
  hermes:
    tags: [api, rest, graphql, http, debugging, testing, curl, integration]
    category: software-development
    related_skills: [systematic-debugging, test-driven-development]
---

# API Testing & Debugging

Drive REST and GraphQL diagnosis through Hermes tools — `terminal` for `curl`, `execute_code` for Python `requests`, `web_extract` for vendor docs. Isolate the failing layer before guessing at the fix.

## When to Use

- API returns unexpected status or body
- Auth fails (401/403 after token refresh, OAuth, API key)
- Works in Postman but fails in code
- Webhook / callback integration debugging
- Building or reviewing API integration tests
- Rate limiting or pagination issues

Skip for UI rendering, DB query tuning, or DNS/firewall infra (escalate).

## Core Principle

**Isolate the layer, then fix.** A 200 OK can hide broken data. A 500 can mask a one-character auth typo. Walk the chain in order; never skip a step.

```
1. Connectivity   → can we reach the host at all?
1.5 Timeouts      → connect-slow vs read-slow?
2. TLS/SSL        → cert valid and trusted?
3. Auth           → credentials correct and unexpired?
4. Request format → payload shape match server expectations?
5. Response parse → does our code accept what came back?
6. Semantics      → does the data mean what we assume?
```

## 5-Minute Quickstart

### REST via terminal

```python
# Verbose request/response exchange
terminal(''curl -v https://api.example.com/users/1'')

# POST with JSON
terminal("""curl -X POST https://api.example.com/users \\
  -H ''Content-Type: application/json'' \\
  -H "Authorization: Bearer $TOKEN" \\
  -d ''{"name":"test","email":"test@example.com"}''""")

# Headers only
terminal(''curl -sI https://api.example.com/health'')

# Pretty-print JSON
terminal(''curl -s https://api.example.com/users | python3 -m json.tool'')
```

### GraphQL via terminal

```python
terminal("""curl -X POST https://api.example.com/graphql \\
  -H ''Content-Type: application/json'' \\
  -H "Authorization: Bearer $TOKEN" \\
  -d ''{"query":"{ user(id: 1) { name email } }"}''""")
```

**GraphQL gotcha:** servers often return HTTP 200 even when the query failed. Always inspect the `errors` field regardless of status code:

```python
execute_code(''''''
import os, requests
resp = requests.post(
    "https://api.example.com/graphql",
    json={"query": "{ user(id: 1) { name email } }"},
    headers={"Authorization": f"Bearer {os.environ[''TOKEN'']}"},
    timeout=10,
)
data = resp.json()
if data.get("errors"):
    for err in data["errors"]:
        print(f"GraphQL error: {err[''message'']} (path: {err.get(''path'')})")
print(data.get("data"))
'''''')
```

### Python (requests) via execute_code

```python
execute_code(''''''
import requests
resp = requests.get(
    "https://api.example.com/users/1",
    headers={"Authorization": "Bearer <TOKEN>"},
    timeout=(3.05, 30),  # (connect, read)
)
print(resp.status_code, dict(resp.headers))
print(resp.text[:500])
'''''')
```

## Layered Debug Flow

### Step 1 — Connectivity

```python
terminal(''nslookup api.example.com'')
terminal(''curl -v --connect-timeout 5 https://api.example.com/health'')
```

Failures: DNS not resolving, firewall, VPN required, proxy missing.

### Step 1.5 — Timeouts

Distinguish *can''t reach* from *reaches but slow*:

```python
terminal(''''''curl -w "dns:%{time_namelookup}s connect:%{time_connect}s tls:%{time_appconnect}s ttfb:%{time_starttransfer}s total:%{time_total}s\\n" \\
  -o /dev/null -s https://api.example.com/endpoint'''''')
```

In Python, always pass a tuple timeout — `requests` has no default and will hang forever:

```python
execute_code(''''''
import requests
from requests.exceptions import ConnectTimeout, ReadTimeout
try:
    requests.get(url, timeout=(3.05, 30))
except ConnectTimeout:
    print("Cannot reach host — DNS, firewall, VPN")
except ReadTimeout:
    print("Connected but server is slow")
'''''')
```

Diagnosis: high `time_connect` is networ','.simplicio-loop\skills\rest-graphql-debug\SKILL.md','c50e5cf3430fa6a40bb2f2e2855b99a64cf1f363161241ab4728b87f18526f2d','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:revisao-humanizada','project_skill','skill://simplicio-runtime/revisao-humanizada','skill: revisao-humanizada','---
name: revisao-humanizada
description: Revisa e reescreve textos para soarem humanos, naturais e conversacionais — removendo a "cara de IA". Use SEMPRE que o usuário pedir para revisar, humanizar, deixar natural, tirar cara de IA, reescrever, polir ou melhorar um texto, roteiro, post, legenda, e-mail, copy, artigo, script de YouTube, carrossel ou qualquer conteúdo escrito. Também acione em pedidos como "revisa esse texto", "tá com cara de ChatGPT", "deixa mais humano", "tira o ar de IA", "naturaliza", "reescreve isso", "melhora a escrita", "faz soar como pessoa", "revisão de roteiro", "humanizar copy", mesmo que o usuário não cite IA explicitamente. Dispara também quando o texto colado tem sinais óbvios de geração por IA (estrutura rígida, palavras corporativas, regra de três excessiva, parágrafos simétricos).
---

# Revisão Humanizada (Roteirista Humano)

Transforma textos com "cara de IA" em textos que soam escritos por uma pessoa real — naturais, com ritmo, com personalidade, e que funcionam quando lidos em voz alta.

## Princípio fundamental

O texto precisa passar no **teste da leitura em voz alta**. Se uma frase parece estranha, travada ou "formal demais" quando lida em voz alta, ela precisa ser reescrita. Escrita humana tem ritmo irregular, texturas, apartes, viradas e um pouco de bagunça controlada — não perfeição simétrica de relatório.

A revisão usa **prompt negativo**: não basta dizer "escreva melhor", é preciso BANIR ativamente padrões específicos que a IA produz por padrão.

---

## Fluxo de trabalho

Ao receber um texto para revisar:

1. **Diagnóstico rápido** — identificar quais padrões de IA estão presentes (palavras banidas, estruturas travadas, ritmo monótono, etc). Não precisa listar exaustivamente, só mapear mentalmente o que há para corrigir.
2. **Reescrita aplicando os bans** — reescrever o texto eliminando TODOS os padrões listados abaixo.
3. **Teste de leitura em voz alta (mental)** — reler cada frase perguntando: "Eu falaria isso numa conversa?". Se não, reescrever.
4. **Entrega em dois blocos**:
   - O texto revisado (sempre primeiro, limpo, pronto para uso)
   - Um breve resumo do que foi mudado (3–6 bullets, no máximo), apontando os padrões de IA removidos

Se o usuário pedir apenas a versão revisada sem explicação, entregue só o texto.

---

## Ban 1: Palavras proibidas (lista negra)

Essas palavras/expressões quase nunca aparecem em fala natural. A IA abusa delas porque foi treinada com texto corporativo e artigos mal escritos. Cortar ou substituir SEMPRE.

### Em português

**Transições e muletas genéricas:**
- "Além disso", "Ademais", "Outrossim", "Dito isso", "Nesse sentido", "Nesse contexto", "Vale ressaltar", "É importante destacar", "Em suma", "Por fim", "Em última análise", "De forma geral", "Fundamentalmente"
- "Vamos mergulhar", "Vamos explorar", "Bora lá" (quando forçado)
- "Aqui está um panorama", "Aqui está uma visão geral"

**Descritores formais vazios:**
- "Robusto", "Dinâmico", "Vibrante", "Rico", "Intrincado", "Multifacetado", "Holístico", "Abrangente", "Estratégico" (quando vazio), "Inovador" (quando vazio), "Sinérgico", "Alinhado", "Otimizado" (genérico)

**Frases de anúncio (nunca anuncie importância, mostre):**
- "É importante notar que...", "Vale destacar que...", "Isso ressalta...", "Isso evidencia...", "Isso demonstra que...", "Serve como...", "Marca um ponto de virada", "Representa um marco"

**Fechamentos vagos e feel-good:**
- "E é assim que você também pode alcançar o sucesso"
- "No final das contas, o que importa é..."
- "A jornada continua"
- "O céu é o limite"
- "As possibilidades são infinitas"

### Em inglês (se o texto for em inglês)

- Additionally, Furthermore, Moreover, In order to, Due to the fact, Both… and…, Here''s a breakdown, Let''s dive in
- Align, Enhance, Intricacies, Tapestry, Robust, Vibrant, Rich, Dynamic, Seamless
- Stands as, Serves as, Marks as a turning point, This highlights, This underscores

**Verbos genéricos** (substitua por ação concreta):
- "fazer" → quebrar, montar, puxar, empurrar, cortar (use o verbo específico)
- "realizar" → f','.simplicio-loop\skills\revisao-humanizada\SKILL.md','052f1b12149d406e4b390b4bcf5b9f0e0b3bed493af366529f25527b12bdc5ad','skill,simplicio,content',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:rtk-cli','project_skill','skill://simplicio-runtime/rtk-cli','skill: rtk-cli','---
name: rtk-cli
description: usar RTK CLI para reduzir tokens em exploração de repositório, git, grep/find e comandos shell verbosos, preservando o sinal técnico relevante
source: https://github.com/rtk-ai/rtk
---

# Skill: `rtk-cli`

Use RTK quando o gargalo for **ruído de terminal**. A ideia: comprimir output verboso antes de ele virar contexto de agent.

> RTK é opcional. Se não estiver instalado, continua com o comando normal.

---

## Trigger

- Quando o usuário pedir para economizar tokens.
- Quando a task envolver muito `git status`, `git diff`, `git log`, `grep`, `find`, `ls`, `npm test`, `cargo test`, `gh ...`.
- Quando a exploração for shell-heavy e o output normal do terminal tende a desperdiçar contexto.
- Quando o pedido mencionar explicitamente `rtk`, `RTK CLI`, `Rust Token Killer`.

Não ativar para:

- comandos interativos;
- browser/UI automation;
- output que precisa ser preservado verbatim como evidência principal.

---

## Steps

1. Verifique se `rtk` existe no ambiente: `command -v rtk`.
2. Se existir, prefira `rtk read`, `rtk grep`, `rtk find`, `rtk git ...` e `rtk <comando-verbooso>` nas etapas de inspeção/validação.
3. Se não existir, siga normalmente e não bloqueie a task só por isso.
4. Quando um comando exigir a saída crua como evidência, rode sem RTK.
5. Se precisar explicar o padrão ao usuário/time, registre que RTK é um acelerador opcional para reduzir tokens, não uma dependência obrigatória do projeto.

---

## Padrões

- Prefira:
  - `rtk read AGENTS.md`
  - `rtk grep "pattern" src/`
  - `rtk find "*.ts" .`
  - `rtk git status`
  - `rtk git diff`
  - `rtk git log -n 10`
  - `rtk npm test`
- Evite RTK em:
  - `curl`
  - `playwright`
  - comandos com prompt interativo
  - comandos em que cada linha completa do output importa para auditoria
- Se houver configuração local de RTK, use exclusões para comandos como `curl` e `playwright`.
- Trate RTK como otimização de I/O textual, não como substituto de leitura criteriosa.

---

## Definition of Done

- [ ] `rtk` foi usado quando disponível em comandos shell-heavy relevantes.
- [ ] Comandos que precisavam output bruto ficaram fora do RTK.
- [ ] A task não ficou bloqueada na ausência de RTK.
- [ ] O padrão de uso ficou documentado no repo para sessões futuras.

---

## Exemplos

```bash
command -v rtk >/dev/null 2>&1 && rtk git status || git status
command -v rtk >/dev/null 2>&1 && rtk grep "TODO" . || rg "TODO" .
command -v rtk >/dev/null 2>&1 && rtk npm test || npm test
```

---

## Notas

- Docs oficiais: `rtk init --codex`, `rtk init -g`, `rtk gain`, `rtk --version`.
- Fonte primária: `rtk-ai/rtk`.
- Integração com Codex é por instrução/prompt-level; não depende de hook nativo no Codex.
','.simplicio-loop\skills\rtk-cli\SKILL.md','49ff0b1fbb0e6cee8b74bd305bf6b025b75805f96adc8057f853c79c97aa5073','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:saelens','project_skill','skill://simplicio-runtime/saelens','skill: saelens','---
name: sparse-autoencoder-training
description: Provides guidance for training and analyzing Sparse Autoencoders (SAEs) using SAELens to decompose neural network activations into interpretable features. Use when discovering interpretable features, analyzing superposition, or studying monosemantic representations in language models.
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [sae-lens>=6.0.0, transformer-lens>=2.0.0, torch>=2.0.0]
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Sparse Autoencoders, SAE, Mechanistic Interpretability, Feature Discovery, Superposition]

---

# SAELens: Sparse Autoencoders for Mechanistic Interpretability

SAELens is the primary library for training and analyzing Sparse Autoencoders (SAEs) - a technique for decomposing polysemantic neural network activations into sparse, interpretable features. Based on Anthropic''s groundbreaking research on monosemanticity.

**GitHub**: [jbloomAus/SAELens](https://github.com/jbloomAus/SAELens) (1,100+ stars)

## The Problem: Polysemanticity & Superposition

Individual neurons in neural networks are **polysemantic** - they activate in multiple, semantically distinct contexts. This happens because models use **superposition** to represent more features than they have neurons, making interpretability difficult.

**SAEs solve this** by decomposing dense activations into sparse, monosemantic features - typically only a small number of features activate for any given input, and each feature corresponds to an interpretable concept.

## When to Use SAELens

**Use SAELens when you need to:**
- Discover interpretable features in model activations
- Understand what concepts a model has learned
- Study superposition and feature geometry
- Perform feature-based steering or ablation
- Analyze safety-relevant features (deception, bias, harmful content)

**Consider alternatives when:**
- You need basic activation analysis → Use **TransformerLens** directly
- You want causal intervention experiments → Use **pyvene** or **TransformerLens**
- You need production steering → Consider direct activation engineering

## Installation

```bash
pip install sae-lens
```

Requirements: Python 3.10+, transformer-lens>=2.0.0

## Core Concepts

### What SAEs Learn

SAEs are trained to reconstruct model activations through a sparse bottleneck:

```
Input Activation → Encoder → Sparse Features → Decoder → Reconstructed Activation
    (d_model)       ↓        (d_sae >> d_model)    ↓         (d_model)
                 sparsity                      reconstruction
                 penalty                          loss
```

**Loss Function**: `MSE(original, reconstructed) + L1_coefficient × L1(features)`

### Key Validation (Anthropic Research)

In "Towards Monosemanticity", human evaluators found **70% of SAE features genuinely interpretable**. Features discovered include:
- DNA sequences, legal language, HTTP requests
- Hebrew text, nutrition statements, code syntax
- Sentiment, named entities, grammatical structures

## Workflow 1: Loading and Analyzing Pre-trained SAEs

### Step-by-Step

```python
from transformer_lens import HookedTransformer
from sae_lens import SAE

# 1. Load model and pre-trained SAE
model = HookedTransformer.from_pretrained("gpt2-small", device="cuda")
sae, cfg_dict, sparsity = SAE.from_pretrained(
    release="gpt2-small-res-jb",
    sae_id="blocks.8.hook_resid_pre",
    device="cuda"
)

# 2. Get model activations
tokens = model.to_tokens("The capital of France is Paris")
_, cache = model.run_with_cache(tokens)
activations = cache["resid_pre", 8]  # [batch, pos, d_model]

# 3. Encode to SAE features
sae_features = sae.encode(activations)  # [batch, pos, d_sae]
print(f"Active features: {(sae_features > 0).sum()}")

# 4. Find top features for each position
for pos in range(tokens.shape[1]):
    top_features = sae_features[0, pos].topk(5)
    token = model.to_str_tokens(tokens[0, pos:pos+1])[0]
    print(f"Token ''{token}'': features {top_features.indices.tolist()}")

# 5. Reconstruct activations
reconstructed = sae.decode(sae_f','.simplicio-loop\skills\saelens\SKILL.md','92ff3be75958794059d19e0e193c0f61a65e0fa0cc1176993e9c463daadcddfb','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:scrapling','project_skill','skill://simplicio-runtime/scrapling','skill: scrapling','---
name: scrapling
description: Web scraping with Scrapling - HTTP fetching, stealth browser automation, Cloudflare bypass, and spider crawling via CLI and Python.
version: 1.0.0
author: FEUAZUR
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Web Scraping, Browser, Cloudflare, Stealth, Crawling, Spider]
    related_skills: [duckduckgo-search, domain-intel]
    homepage: https://github.com/D4Vinci/Scrapling
prerequisites:
  commands: [scrapling, python]
---

# Scrapling

[Scrapling](https://github.com/D4Vinci/Scrapling) is a web scraping framework with anti-bot bypass, stealth browser automation, and a spider framework. It provides three fetching strategies (HTTP, dynamic JS, stealth/Cloudflare) and a full CLI.

**This skill is for educational and research purposes only.** Users must comply with local/international data scraping laws and respect website Terms of Service.

## When to Use

- Scraping static HTML pages (faster than browser tools)
- Scraping JS-rendered pages that need a real browser
- Bypassing Cloudflare Turnstile or bot detection
- Crawling multiple pages with a spider
- When the built-in `web_extract` tool does not return the data you need

## Installation

```bash
pip install "scrapling[all]"
scrapling install
```

Minimal install (HTTP only, no browser):
```bash
pip install scrapling
```

With browser automation only:
```bash
pip install "scrapling[fetchers]"
scrapling install
```

## Quick Reference

| Approach | Class | Use When |
|----------|-------|----------|
| HTTP | `Fetcher` / `FetcherSession` | Static pages, APIs, fast bulk requests |
| Dynamic | `DynamicFetcher` / `DynamicSession` | JS-rendered content, SPAs |
| Stealth | `StealthyFetcher` / `StealthySession` | Cloudflare, anti-bot protected sites |
| Spider | `Spider` | Multi-page crawling with link following |

## CLI Usage

### Extract Static Page

```bash
scrapling extract get ''https://example.com'' output.md
```

With CSS selector and browser impersonation:

```bash
scrapling extract get ''https://example.com'' output.md \
  --css-selector ''.content'' \
  --impersonate ''chrome''
```

### Extract JS-Rendered Page

```bash
scrapling extract fetch ''https://example.com'' output.md \
  --css-selector ''.dynamic-content'' \
  --disable-resources \
  --network-idle
```

### Extract Cloudflare-Protected Page

```bash
scrapling extract stealthy-fetch ''https://protected-site.com'' output.html \
  --solve-cloudflare \
  --block-webrtc \
  --hide-canvas
```

### POST Request

```bash
scrapling extract post ''https://example.com/api'' output.json \
  --json ''{"query": "search term"}''
```

### Output Formats

The output format is determined by the file extension:
- `.html` -- raw HTML
- `.md` -- converted to Markdown
- `.txt` -- plain text
- `.json` / `.jsonl` -- JSON

## Python: HTTP Scraping

### Single Request

```python
from scrapling.fetchers import Fetcher

page = Fetcher.get(''https://quotes.toscrape.com/'')
quotes = page.css(''.quote .text::text'').getall()
for q in quotes:
    print(q)
```

### Session (Persistent Cookies)

```python
from scrapling.fetchers import FetcherSession

with FetcherSession(impersonate=''chrome'') as session:
    page = session.get(''https://example.com/'', stealthy_headers=True)
    links = page.css(''a::attr(href)'').getall()
    for link in links[:5]:
        sub = session.get(link)
        print(sub.css(''h1::text'').get())
```

### POST / PUT / DELETE

```python
page = Fetcher.post(''https://api.example.com/data'', json={"key": "value"})
page = Fetcher.put(''https://api.example.com/item/1'', data={"name": "updated"})
page = Fetcher.delete(''https://api.example.com/item/1'')
```

### With Proxy

```python
page = Fetcher.get(''https://example.com'', proxy=''http://user:pass@proxy:8080'')
```

## Python: Dynamic Pages (JS-Rendered)

For pages that require JavaScript execution (SPAs, lazy-loaded content):

```python
from scrapling.fetchers import DynamicFetcher

page = DynamicFetcher.fetch(''https://example.com'', headless=True)
data = page.css(''.js-loaded-content::text'').getall()
```

### Wait for Specific Element

```','.simplicio-loop\skills\scrapling\SKILL.md','d68e9f06f350a5cb68a848d6e1bdecc7e8d0132efb1051526c89b0e6d0725fa9','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:searxng-search','project_skill','skill://simplicio-runtime/searxng-search','skill: searxng-search','---
name: searxng-search
description: Free meta-search via SearXNG — aggregates results from 70+ search engines. Self-hosted or use a public instance. No API key needed. Falls back automatically when the web search toolset is unavailable.
version: 1.0.0
author: hermes-agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [search, searxng, meta-search, self-hosted, free, fallback]
    related_skills: [duckduckgo-search, domain-intel]
    fallback_for_toolsets: [web]
---

# SearXNG Search

Free meta-search using [SearXNG](https://searxng.org/) — a privacy-respecting, self-hosted search aggregator that queries 70+ search engines simultaneously.

**No API key required** when using a public instance. Can also be self-hosted for full control. Automatically appears as a fallback when the main web search toolset (`FIRECRAWL_API_KEY`) is not configured.

## Configuration

SearXNG requires a `SEARXNG_URL` environment variable pointing to your SearXNG instance:

```bash
# Public instances (no setup required)
SEARXNG_URL=https://searxng.example.com

# Self-hosted SearXNG
SEARXNG_URL=http://localhost:8888
```

If no instance is configured, this skill is unavailable and the agent falls back to other search options.

## Detection Flow

Check what is actually available before choosing an approach:

```bash
# Check if SEARXNG_URL is set and the instance is reachable
curl -s --max-time 5 "${SEARXNG_URL}/search?q=test&format=json" | head -c 200
```

Decision tree:
1. If `SEARXNG_URL` is set and the instance responds, use SearXNG
2. If `SEARXNG_URL` is unset or unreachable, fall back to other available search tools
3. If the user wants SearXNG specifically, help them set up an instance or find a public one

## Method 1: CLI via curl (Preferred)

Use `curl` via `terminal` to call the SearXNG JSON API. This avoids assuming any particular Python package is installed.

```bash
# Text search (JSON output)
curl -s --max-time 10 \
  "${SEARXNG_URL}/search?q=python+async+programming&format=json&engines=google,bing&limit=10"

# With Safesearch off
curl -s --max-time 10 \
  "${SEARXNG_URL}/search?q=example&format=json&safesearch=0"

# Specific categories (general, news, science, etc.)
curl -s --max-time 10 \
  "${SEARXNG_URL}/search?q=AI+news&format=json&categories=news"
```

### Common CLI Flags

| Flag | Description | Example |
|------|-------------|---------|
| `q` | Query string (URL-encoded) | `q=python+async` |
| `format` | Output format: `json`, `csv`, `rss` | `format=json` |
| `engines` | Comma-separated engine names | `engines=google,bing,ddg` |
| `limit` | Max results per engine (default 10) | `limit=5` |
| `categories` | Filter by category | `categories=news,science` |
| `safesearch` | 0=none, 1=moderate, 2=strict | `safesearch=0` |
| `time_range` | Filter: `day`, `week`, `month`, `year` | `time_range=week` |

### Parsing JSON Results

```bash
# Extract titles and URLs from JSON
curl -s --max-time 10 "${SEARXNG_URL}/search?q=fastapi&format=json&limit=5" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
for r in data.get(''results'', []):
    print(r.get(''title'',''''))
    print(r.get(''url'',''''))
    print(r.get(''content'','''')[:200])
    print()
"
```

Returns per result: `title`, `url`, `content` (snippet), `engine`, `parsed_url`, `img_src`, `thumbnail`, `author`, `published_date`

## Method 2: Python API via `requests`

Use the SearXNG REST API directly from Python with the `requests` library:

```python
import os, requests, urllib.parse

base_url = os.environ.get("SEARXNG_URL", "")
if not base_url:
    raise RuntimeError("SEARXNG_URL is not set")

query = "fastapi deployment guide"
params = {
    "q": query,
    "format": "json",
    "limit": 5,
    "engines": "google,bing",
}

resp = requests.get(f"{base_url}/search", params=params, timeout=10)
resp.raise_for_status()
data = resp.json()

for r in data.get("results", []):
    print(r["title"])
    print(r["url"])
    print(r.get("content", "")[:200])
    print()
```

## Method 3: searxng-data Python Package

For more structured access, install the `searxng-da','.simplicio-loop\skills\searxng-search\SKILL.md','b8a46f22f5be86f23c21b5e14ebe5d4dc89b771d003f6158f89ce08daf176378','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:sherlock','project_skill','skill://simplicio-runtime/sherlock','skill: sherlock','---
name: sherlock
description: OSINT username search across 400+ social networks. Hunt down social media accounts by username.
version: 1.0.0
author: unmodeled-tyler
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [osint, security, username, social-media, reconnaissance]
    category: security
prerequisites:
  commands: [sherlock]
---

# Sherlock OSINT Username Search

Hunt down social media accounts by username across 400+ social networks using the [Sherlock Project](https://github.com/sherlock-project/sherlock).

## When to Use

- User asks to find accounts associated with a username
- User wants to check username availability across platforms
- User is conducting OSINT or reconnaissance research
- User asks "where is this username registered?" or similar

## Requirements

- Sherlock CLI installed: `pipx install sherlock-project` or `pip install sherlock-project`
- Alternatively: Docker available (`docker run -it --rm sherlock/sherlock`)
- Network access to query social platforms

## Procedure

### 1. Check if Sherlock is Installed

**Before doing anything else**, verify sherlock is available:

```bash
sherlock --version
```

If the command fails:
- Offer to install: `pipx install sherlock-project` (recommended) or `pip install sherlock-project`
- **Do NOT** try multiple installation methods — pick one and proceed
- If installation fails, inform the user and stop

### 2. Extract Username

**Extract the username directly from the user''s message if clearly stated.**

Examples where you should **NOT** use clarify:
- "Find accounts for nasa" → username is `nasa`
- "Search for johndoe123" → username is `johndoe123`
- "Check if alice exists on social media" → username is `alice`
- "Look up user bob on social networks" → username is `bob`

**Only use clarify if:**
- Multiple potential usernames mentioned ("search for alice or bob")
- Ambiguous phrasing ("search for my username" without specifying)
- No username mentioned at all ("do an OSINT search")

When extracting, take the **exact** username as stated — preserve case, numbers, underscores, etc.

### 3. Build Command

**Default command** (use this unless user specifically requests otherwise):
```bash
sherlock --print-found --no-color "<username>" --timeout 90
```

**Optional flags** (only add if user explicitly requests):
- `--nsfw` — Include NSFW sites (only if user asks)
- `--tor` — Route through Tor (only if user asks for anonymity)

**Do NOT ask about options via clarify** — just run the default search. Users can request specific options if needed.

### 4. Execute Search

Run via the `terminal` tool. The command typically takes 30-120 seconds depending on network conditions and site count.

**Example terminal call:**
```json
{
  "command": "sherlock --print-found --no-color \"target_username\"",
  "timeout": 180
}
```

### 5. Parse and Present Results

Sherlock outputs found accounts in a simple format. Parse the output and present:

1. **Summary line:** "Found X accounts for username ''Y''"
2. **Categorized links:** Group by platform type if helpful (social, professional, forums, etc.)
3. **Output file location:** Sherlock saves results to `<username>.txt` by default

**Example output parsing:**
```
[+] Instagram: https://instagram.com/username
[+] Twitter: https://twitter.com/username
[+] GitHub: https://github.com/username
```

Present findings as clickable links when possible.

## Pitfalls

### No Results Found
If Sherlock finds no accounts, this is often correct — the username may not be registered on checked platforms. Suggest:
- Checking spelling/variation
- Trying similar usernames with `?` wildcard: `sherlock "user?name"`
- The user may have privacy settings or deleted accounts

### Timeout Issues
Some sites are slow or block automated requests. Use `--timeout 120` to increase wait time, or `--site` to limit scope.

### Tor Configuration
`--tor` requires Tor daemon running. If user wants anonymity but Tor isn''t available, suggest:
- Installing Tor service
- Using `--proxy` with an alternative proxy

### False Positives
Some sites a','.simplicio-loop\skills\sherlock\SKILL.md','55c9af80b7aeae9cce754bb70f9baf6d19e15f975fc75eb5648775c2931f772d','skill,simplicio,content',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:shop-app','project_skill','skill://simplicio-runtime/shop-app','skill: shop-app','---
name: shop-app
description: "Shop.app: product search, order tracking, returns, reorder."
version: 0.0.28
author: community
license: MIT
platforms: [linux, macos, windows]
prerequisites:
  commands: [curl]
metadata:
  hermes:
    tags: [Shopping, E-commerce, Shop.app, Products, Orders, Returns]
    related_skills: [shopify, maps]
    homepage: https://shop.app
    upstream: https://shop.app/SKILL.md
---

# Shop.app — Personal Shopping Assistant

Use this skill when the user wants to **search products across stores, compare prices, find similar items, track an order, manage a return, or re-order a past purchase** through Shop.app''s agent API.

No auth required for product search. Auth (device-authorization flow) is required for any per-user operation: orders, tracking, returns, reorder. Store tokens **only in your working memory for the current session** — never write them to disk, never ask the user to paste them.

All endpoints return **plain-text markdown** (including errors, which look like `# Error\n\n{message} ({status})`). Use `curl` via the `terminal` tool; for the try-on feature use the `image_generate` tool.

---

## Product Search (no auth)

**Endpoint:** `GET https://shop.app/agents/search`

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | — | Search keywords |
| `limit` | int | no | 10 | Results 1–10 |
| `ships_to` | string | no | `US` | ISO-3166 country code (controls currency + availability) |
| `ships_from` | string | no | — | ISO-3166 country code for product origin |
| `min_price` | decimal | no | — | Min price |
| `max_price` | decimal | no | — | Max price |
| `available_for_sale` | int | no | 1 | `1` = in-stock only |
| `include_secondhand` | int | no | 1 | `0` = new only |
| `categories` | string | no | — | Comma-delimited Shopify taxonomy IDs |
| `shop_ids` | string | no | — | Filter to specific shops |
| `products_limit` | int | no | 10 | Variants per product, 1–10 |

```
curl -s ''https://shop.app/agents/search?query=wireless+earbuds&limit=10&ships_to=US''
```

**Response format:** Plain text. Products separated by `\n\n---\n\n`.

**Fields to extract per product:**
- **Title** — first line
- **Price + Brand + Rating** — second line (`$PRICE at BRAND — RATING`)
- **Product URL** — line starting with `https://`
- **Image URL** — line starting with `Img: `
- **Product ID** — line starting with `id: `
- **Variant IDs** — in the Variants section or from the `variant=` query param in the product URL
- **Checkout URL** — line starting with `Checkout: ` (contains `{id}` placeholder; replace with a real variant ID)

**Pagination:** none. For more or different results, **vary the query** (different keywords, synonyms, narrower/broader terms). Up to ~3 search rounds.

**Errors:** missing/empty `query` returns `# Error\n\nquery is missing (400)`.

---

## Find Similar Products

Same response format as Product Search.

**By variant ID (GET):**

```
curl -s ''https://shop.app/agents/search?variant_id=33169831854160&limit=10&ships_to=US''
```

The `variant_id` must come from the `variant=` query param in a product URL — the `id:` field from search results is **not** accepted.

**By image (POST):**

```
curl -s -X POST https://shop.app/agents/search \
  -H ''Content-Type: application/json'' \
  -d ''{"similarTo":{"media":{"contentType":"image/jpeg","base64":"<BASE64>"}},"limit":10}''
```

Requires base64-encoded image bytes. URLs are **not** accepted — download the image first (`curl -o`), then `base64 -w0 file.jpg` to inline.

---

## Authentication — Device Authorization Flow (RFC 8628)

Required for orders, tracking, returns, reorder. Not required for product search.

**Session state (hold in your reasoning context for this conversation only):**

| Key | Lifetime | Description |
|---|---|---|
| `access_token` | until expired / 401 | Bearer token for authenticated endpoints |
| `refresh_token` | until refresh fails | Renews `access_token` without re-auth |
| `device_id` | whole session | `shop-skill--<uuid>` — generate once, reuse for every request |
| `country','.simplicio-loop\skills\shop-app\SKILL.md','7281b8fe2965ea35716d3d7e8ee3795c88332823afeea0fd975647d88f8bb54e','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:shopify','project_skill','skill://simplicio-runtime/shopify','skill: shopify','---
name: shopify
description: Shopify Admin & Storefront GraphQL APIs via curl. Products, orders, customers, inventory, metafields.
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
prerequisites:
  env_vars: [SHOPIFY_ACCESS_TOKEN, SHOPIFY_STORE_DOMAIN]
  commands: [curl, jq]
required_environment_variables:
  - name: SHOPIFY_ACCESS_TOKEN
    prompt: Shopify Admin API access token (starts with shpat_)
    help: "Shopify admin → Settings → Apps and sales channels → Develop apps → Create an app → API credentials. Token shown ONCE on install."
  - name: SHOPIFY_STORE_DOMAIN
    prompt: Your shop subdomain without protocol (e.g. my-store.myshopify.com)
    help: "The permanent myshopify.com domain, not your custom domain."
  - name: SHOPIFY_API_VERSION
    prompt: Shopify API version (default 2026-01)
    help: "Stable quarterly version. Override if you need an older one."
metadata:
  hermes:
    tags: [Shopify, E-commerce, Commerce, API, GraphQL]
    related_skills: [airtable, xurl]
    homepage: https://shopify.dev/docs/api/admin-graphql
---

# Shopify — Admin & Storefront GraphQL APIs

Work with Shopify stores directly through `curl`: list products, manage inventory, pull orders, update customers, read metafields. No SDK, no app framework — just the GraphQL endpoint and a custom-app access token.

The REST Admin API is legacy since 2024-04 and only receives security fixes. **Use GraphQL Admin** for all admin work. Use **Storefront GraphQL** for read-only customer-facing queries (products, collections, cart).

## Prerequisites

1. In Shopify admin: **Settings → Apps and sales channels → Develop apps → Create an app**.
2. Click **Configure Admin API scopes**, select what you need (examples below), save.
3. **Install app** → the Admin API access token appears ONCE. Copy it immediately — Shopify will never show it again. Tokens start with `shpat_`.
4. Save to `${HERMES_HOME:-~/.hermes}/.env`:
   ```
   SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxx
   SHOPIFY_STORE_DOMAIN=my-store.myshopify.com
   SHOPIFY_API_VERSION=2026-01
   ```

> **Heads up:** As of January 1, 2026, new "legacy custom apps" created in the Shopify admin are gone. New setups should use the **Dev Dashboard** (`shopify.dev/docs/apps/build/dev-dashboard`). Existing admin-created apps keep working. If the user''s shop has no existing custom app and it''s after 2026-01-01, direct them to Dev Dashboard instead of the admin flow.

Common scopes by task:
- Products / collections: `read_products`, `write_products`
- Inventory: `read_inventory`, `write_inventory`, `read_locations`
- Orders: `read_orders`, `write_orders` (30 most recent without `read_all_orders`)
- Customers: `read_customers`, `write_customers`
- Draft orders: `read_draft_orders`, `write_draft_orders`
- Fulfillments: `read_fulfillments`, `write_fulfillments`
- Metafields / metaobjects: covered by the matching resource scopes

## API Basics

- **Endpoint:** `https://$SHOPIFY_STORE_DOMAIN/admin/api/$SHOPIFY_API_VERSION/graphql.json`
- **Auth header:** `X-Shopify-Access-Token: $SHOPIFY_ACCESS_TOKEN` (NOT `Authorization: Bearer`)
- **Method:** always `POST`, always `Content-Type: application/json`, body is `{"query": "...", "variables": {...}}`
- **HTTP 200 does not mean success.** GraphQL returns errors in a top-level `errors` array and per-field `userErrors`. Always check both.
- **IDs are GID strings:** `gid://shopify/Product/10079467700516`, `gid://shopify/Variant/...`, `gid://shopify/Order/...`. Pass these verbatim — don''t strip the prefix.
- **Rate limit:** calculated via query cost (leaky bucket). Each response has `extensions.cost` with `requestedQueryCost`, `actualQueryCost`, `throttleStatus.{currentlyAvailable, maximumAvailable, restoreRate}`. Back off when `currentlyAvailable` drops below your next query''s cost. Standard shops = 100 points bucket, 50/s restore; Plus = 1000/100.

Base curl pattern (reusable):

```bash
shop_gql() {
  local query="$1"
  local variables="${2:-{}}"
  curl -sS -X POST \
    "https://${SHOPIFY_STORE_DOMAIN}/admin/api/${SHOPIFY_API_VERSIO','.simplicio-loop\skills\shopify\SKILL.md','679e25afd983e894ba790f0fd4baa77ec32bc5ca07977675556985628fd8df6e','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:simplicio-cli','project_skill','skill://simplicio-runtime/simplicio-cli','skill: simplicio-cli','---
name: simplicio-cli
description: Use simplicio-cli to turn a one-line task into a verified code change (diff + test + verify loop). Trigger ALWAYS when the user asks for a small/medium code edit in a known file — "hide X for non-admins", "add validation to Y", "fix the empty-state on Z", "rename the prop in <file>" — even if they do not mention the word "simplicio". Especially trigger when the active model is small/local (Ollama, Gemma, Llama 3 sub-8B, Phi, Qwen 7B), or the user mentions "task-to-code", "diff+test", "verify loop", "6-layer contract", "pass-rate", "precedent + skill router", or any of the benchmark numbers (+39 pts, +51 pts, +58 pts, 99% pass-rate). Use this skill BEFORE writing the edit by hand — simplicio-cli measurably boosts pass-rate on the same model from ~41% to ~99% on frontier and ~35% to ~74% on sub-4B by stacking mapper + precedent + skill-router + 6-layer prompt + test + verify-loop. Also trigger on explicit Python invocations: `$simplicio-py`, `/simplicio-py`, "use simplicio-py", "rode o simplicio-py", "via simplicio-cli".
---

# Skill: `simplicio-cli`

Wrap a code task in simplicio-cli''s 6-layer contract instead of asking the LLM to guess. Same model, same task — only the prompt structure changes. Measured: **+51 pts average gain across 14 models** (sub-4B to frontier 2026).

> Source: this repo (`simplicio-cli`, PyPI `simplicio-cli`, MIT, v0.2.10). See `README.md` for the full bench table and methodology, `docs/benchmark-4quadrant.md` for the 4-quadrant decomposition.

---

## When to trigger

**Always** when the user asks for a code edit that fits all of these:

- One concrete target file (or small set) the user named or you can resolve from `Explore`.
- Mensurable success criteria (button gone / validation rejects empty / endpoint returns 401).
- Stack is one of the indexed stacks (`angular`, `react`, `next`, `vue`, `django`, `laravel`, `springboot`, `nestjs`, `dotnet`, `flutter`, etc. — anything with skills under `SIMPLICIO_SKILLS_DIR`) or a generic edit (`--stack generic`).

**Also trigger** on:

- Small/local model active (Ollama, Gemma sub-8B, Llama 3 sub-8B, Phi, Qwen 7B) — simplicio adds the biggest absolute gain there (+39 pts to +58 pts).
- User explicitly says: `$simplicio-py`, `/simplicio-py`, "use simplicio-py", "rode o simplicio-py", "via simplicio-cli".
- User mentions verify-loop, 6-layer prompt, precedent injection, pass-rate, skill router, content-hash cache.

**Do NOT trigger** on:

- Pure read-only ask ("what does this function do?") — answer directly.
- Architectural decision / refactor amplo cross-file — that goes to `architect` agent + ADR.
- One-off shell command, lookup, install task.
- The user is already inside `ralph-loop` and explicitly wants edits by hand — respect.

---

## Steps

### 1. Verify install + config

```bash
# is simplicio-py on PATH?
command -v simplicio-py \
  || pip install --user simplicio-cli \
  || pip install -e .            # fallback: editable install from repo root (locked venv / no PyPI)

# config check (one-shot, costs 1 LLM call)
simplicio-py smoke
```

If `smoke` fails: set the env vars and retry. Read `~/.config/simplicio/.env` or current shell env. Required:

| Provider | `SIMPLICIO_MODEL` | `SIMPLICIO_BASE_URL` | Key env var |
|---|---|---|---|
| OpenRouter | `anthropic/claude-opus-4` (or any) | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| GLM (z.ai) | `glm-4.6` | `https://api.z.ai/api/paas/v4` | `OPENAI_API_KEY` |
| DeepSeek | `deepseek-chat` | `https://api.deepseek.com` | `OPENAI_API_KEY` |
| OpenAI | `gpt-4.1` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| Ollama local | `llama3` (or any) | `http://localhost:11434/v1` | `OPENAI_API_KEY=dummy` |
| Anthropic native | `claude-opus-4-7` | *(unset)* | `ANTHROPIC_API_KEY` |

`base_url` unset + `ANTHROPIC_API_KEY` present → native Anthropic SDK. Else OpenAI-compatible client.

### 2. Index (cache warm-up)

First run on the repo (or after large changes): index once. Re-runs reuse embeddings keyed by content hash — unchanged blocks cost zero.

```bash
simplicio-py ','.simplicio-loop\skills\simplicio-cli\SKILL.md','f8dcf98d290a0a8695f4b5fc9e550d9e56def6c8bb93c2c22b1663e58a2379b9','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:simplify-code','project_skill','skill://simplicio-runtime/simplify-code','skill: simplify-code','---
name: simplify-code
description: "Parallel 3-agent cleanup of recent code changes."
version: 1.0.0
author: Hermes Agent (inspired by Claude Code /simplify)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [code-review, cleanup, refactor, delegation, subagent, parallel, simplify]
    related_skills: [requesting-code-review, test-driven-development, plan]
---

# Simplify Code — Parallel Review & Cleanup

Review your recent code changes with three focused reviewers running in
parallel, aggregate their findings, and apply the fixes worth applying.

**Core principle:** Three narrow reviewers beat one broad reviewer. Each one
deeply searches the codebase for a single class of problem — reuse, quality,
efficiency — without diluting its attention across all three. They run
concurrently, so you pay the latency of one review, not three.

## When to Use

Trigger this skill when the user says any of:

- "simplify" / "simplify my changes" / "simplify these changes"
- "review my code" / "review my recent changes" / "clean up my changes"
- "/simplify" (if they''re carrying the Claude Code habit over)

Optional modifiers the user may add — honor them:

- **Focus:** "simplify focus on efficiency" → run only the efficiency reviewer
  (or weight the aggregation toward it). Recognized focuses: `reuse`,
  `quality`, `efficiency`.
- **Dry run:** "simplify but don''t change anything" / "just report" → run the
  three reviewers, present findings, apply NOTHING. Ask before applying.
- **Scope:** "simplify the last commit" / "simplify staged" / "simplify
  src/foo.py" → narrow the diff source accordingly (see Phase 1).

Do NOT auto-run this after every edit. It costs three subagents'' worth of
tokens — invoke it only when the user explicitly asks.

## The Process

### Phase 1 — Identify the changes

Capture the diff to review. Pick the source by what the user asked for, in
this default order:

```bash
# 1. Default: uncommitted working-tree changes (tracked files)
git diff

# 2. If that''s empty, include staged changes
git diff HEAD

# 3. Scoped variants the user may request:
git diff --staged                 # "staged changes"
git diff HEAD~1                    # "the last commit"
git diff main...HEAD              # "this branch" / "my PR"
git diff -- src/foo.py            # specific file(s)
```

If `git diff` and `git diff HEAD` are both empty and there''s no git repo or no
changes, fall back to the files the user explicitly named or that were
recently created/edited in this session. If you genuinely can''t find any
changed code, say so and stop — there''s nothing to simplify.

Capture the full diff text. Note its size: if it''s very large (say >2000
changed lines), warn the user that three subagents each carrying the full diff
will be token-heavy, and offer to scope it down (per-directory, per-commit)
before proceeding.

### Phase 2 — Launch three reviewers in parallel

Use `delegate_task` **batch mode** — pass all three tasks in one `tasks`
array so they run concurrently. Three is the right fan-out for this pattern;
it''s well within the `delegation.max_concurrent_children` budget on any
default install.

Give **every** reviewer the **complete diff** (not fragments — cross-file
issues hide in the gaps) plus the absolute repo path so they can search the
wider codebase. Each reviewer gets `terminal`, `file`, and `search`
toolsets (so they can `git`, `read_file`, and `search_files`/grep).

Tell each reviewer to:
- Search the existing codebase for evidence (don''t reason from the diff alone).
- Report findings as a concrete list: `file:line → problem → suggested fix`.
- Rank each finding `high` / `medium` / `low` confidence.
- Skip nits and style-only churn. Only flag things that materially improve
  the code.

Pass these three goals (drop any the user''s focus excludes):

**Reviewer 1 — Code Reuse**
> Review this diff for code that duplicates functionality already in the
> codebase. Search utility modules, shared helpers, and adjacent files
> (use search_files / grep) for existing functions, constants, or patterns
> the new ','.simplicio-loop\skills\simplify-code\SKILL.md','bfd2dbb1581909ba0071fd834c6f6c918603e028d6b467f2d3890c0aeafde879','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:simpo','project_skill','skill://simplicio-runtime/simpo','skill: simpo','---
name: simpo-training
description: Simple Preference Optimization for LLM alignment. Reference-free alternative to DPO with better performance (+6.4 points on AlpacaEval 2.0). No reference model needed, more efficient than DPO. Use for preference alignment when want simpler, faster training than DPO/PPO.
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [torch, transformers, datasets, trl, accelerate]
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Post-Training, SimPO, Preference Optimization, Alignment, DPO Alternative, Reference-Free, LLM Alignment, Efficient Training]

---

# SimPO - Simple Preference Optimization

## Quick start

SimPO is a reference-free preference optimization method that outperforms DPO without needing a reference model.

**Installation**:
```bash
# Create environment
conda create -n simpo python=3.10 && conda activate simpo

# Install PyTorch 2.2.2
# Visit: https://pytorch.org/get-started/locally/

# Install alignment-handbook
git clone https://github.com/huggingface/alignment-handbook.git
cd alignment-handbook
python -m pip install .

# Install Flash Attention 2
python -m pip install flash-attn --no-build-isolation
```

**Training** (Mistral 7B):
```bash
ACCELERATE_LOG_LEVEL=info accelerate launch \
  --config_file accelerate_configs/deepspeed_zero3.yaml \
  scripts/run_simpo.py \
  training_configs/mistral-7b-base-simpo.yaml
```

## Common workflows

### Workflow 1: Train from base model (Mistral 7B)

**Config** (`mistral-7b-base-simpo.yaml`):
```yaml
# Model
model_name_or_path: mistralai/Mistral-7B-v0.1
torch_dtype: bfloat16

# Dataset
dataset_mixer:
  HuggingFaceH4/ultrafeedback_binarized: 1.0
dataset_splits:
  - train_prefs
  - test_prefs

# SimPO hyperparameters
beta: 2.0                  # Reward scaling (2.0-10.0)
gamma_beta_ratio: 0.5       # Target margin (0-1)
loss_type: sigmoid          # sigmoid or hinge
sft_weight: 0.0             # Optional SFT regularization

# Training
learning_rate: 5e-7         # Critical: 3e-7 to 1e-6
num_train_epochs: 1
per_device_train_batch_size: 1
gradient_accumulation_steps: 8

# Output
output_dir: ./outputs/mistral-7b-simpo
```

**Launch training**:
```bash
accelerate launch --config_file accelerate_configs/deepspeed_zero3.yaml \
  scripts/run_simpo.py training_configs/mistral-7b-base-simpo.yaml
```

### Workflow 2: Fine-tune instruct model (Llama 3 8B)

**Config** (`llama3-8b-instruct-simpo.yaml`):
```yaml
model_name_or_path: meta-llama/Meta-Llama-3-8B-Instruct

dataset_mixer:
  argilla/ultrafeedback-binarized-preferences-cleaned: 1.0

beta: 2.5
gamma_beta_ratio: 0.5
learning_rate: 5e-7
sft_weight: 0.1             # Add SFT loss to preserve capabilities

num_train_epochs: 1
per_device_train_batch_size: 2
gradient_accumulation_steps: 4
output_dir: ./outputs/llama3-8b-simpo
```

**Launch**:
```bash
accelerate launch --config_file accelerate_configs/deepspeed_zero3.yaml \
  scripts/run_simpo.py training_configs/llama3-8b-instruct-simpo.yaml
```

### Workflow 3: Reasoning-intensive tasks (lower LR)

**For math/code tasks**:
```yaml
model_name_or_path: deepseek-ai/deepseek-math-7b-base

dataset_mixer:
  argilla/distilabel-math-preference-dpo: 1.0

beta: 5.0                   # Higher for stronger signal
gamma_beta_ratio: 0.7       # Larger margin
learning_rate: 3e-7         # Lower LR for reasoning
sft_weight: 0.0

num_train_epochs: 1
per_device_train_batch_size: 1
gradient_accumulation_steps: 16
```

## When to use vs alternatives

**Use SimPO when**:
- Want simpler training than DPO (no reference model)
- Have preference data (chosen/rejected pairs)
- Need better performance than DPO
- Limited compute resources
- Single-node training sufficient

**Algorithm selection**:
- **SimPO**: Simplest, best performance, no reference model
- **DPO**: Need reference model baseline, more conservative
- **PPO**: Maximum control, need reward model, complex setup
- **GRPO**: Memory-efficient RL, no critic

**Use alternatives instead**:
- **OpenRLHF**: Multi-node distributed training, PPO/GRPO
- **TRL**: Need multiple methods in one','.simplicio-loop\skills\simpo\SKILL.md','6db4bbc9cd6c49f9088a44d2a0ee358f5aa95325174f12ede64a4c57070c2a5a','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:siyuan','project_skill','skill://simplicio-runtime/siyuan','skill: siyuan','---
name: siyuan
description: SiYuan Note API for searching, reading, creating, and managing blocks and documents in a self-hosted knowledge base via curl.
version: 1.0.0
author: FEUAZUR
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [SiYuan, Notes, Knowledge Base, PKM, API]
    related_skills: [obsidian, notion]
    homepage: https://github.com/siyuan-note/siyuan
prerequisites:
  env_vars: [SIYUAN_TOKEN]
  commands: [curl, jq]
required_environment_variables:
  - name: SIYUAN_TOKEN
    prompt: SiYuan API token
    help: "Settings > About in SiYuan desktop app"
  - name: SIYUAN_URL
    prompt: SiYuan instance URL (default http://127.0.0.1:6806)
    required_for: remote instances
---

# SiYuan Note API

Use the [SiYuan](https://github.com/siyuan-note/siyuan) kernel API via curl to search, read, create, update, and delete blocks and documents in a self-hosted knowledge base. No extra tools needed -- just curl and an API token.

## Prerequisites

1. Install and run SiYuan (desktop or Docker)
2. Get your API token: **Settings > About > API token**
3. Store it in `${HERMES_HOME:-~/.hermes}/.env`:
   ```
   SIYUAN_TOKEN=your_token_here
   SIYUAN_URL=http://127.0.0.1:6806
   ```
   `SIYUAN_URL` defaults to `http://127.0.0.1:6806` if not set.

## API Basics

All SiYuan API calls are **POST with JSON body**. Every request follows this pattern:

```bash
curl -s -X POST "${SIYUAN_URL:-http://127.0.0.1:6806}/api/..." \
  -H "Authorization: Token $SIYUAN_TOKEN" \
  -H "Content-Type: application/json" \
  -d ''{"param": "value"}''
```

Responses are JSON with this structure:
```json
{"code": 0, "msg": "", "data": { ... }}
```
`code: 0` means success. Any other value is an error -- check `msg` for details.

**ID format:** SiYuan IDs look like `20210808180117-6v0mkxr` (14-digit timestamp + 7 alphanumeric chars).

## Quick Reference

| Operation | Endpoint |
|-----------|----------|
| Full-text search | `/api/search/fullTextSearchBlock` |
| SQL query | `/api/query/sql` |
| Read block | `/api/block/getBlockKramdown` |
| Read children | `/api/block/getChildBlocks` |
| Get path | `/api/filetree/getHPathByID` |
| Get attributes | `/api/attr/getBlockAttrs` |
| List notebooks | `/api/notebook/lsNotebooks` |
| List documents | `/api/filetree/listDocsByPath` |
| Create notebook | `/api/notebook/createNotebook` |
| Create document | `/api/filetree/createDocWithMd` |
| Append block | `/api/block/appendBlock` |
| Update block | `/api/block/updateBlock` |
| Rename document | `/api/filetree/renameDocByID` |
| Set attributes | `/api/attr/setBlockAttrs` |
| Delete block | `/api/block/deleteBlock` |
| Delete document | `/api/filetree/removeDocByID` |
| Export as Markdown | `/api/export/exportMdContent` |

## Common Operations

### Search (Full-Text)

```bash
curl -s -X POST "${SIYUAN_URL:-http://127.0.0.1:6806}/api/search/fullTextSearchBlock" \
  -H "Authorization: Token $SIYUAN_TOKEN" \
  -H "Content-Type: application/json" \
  -d ''{"query": "meeting notes", "page": 0}'' | jq ''.data.blocks[:5]''
```

### Search (SQL)

Query the blocks database directly. Only SELECT statements are safe.

```bash
curl -s -X POST "${SIYUAN_URL:-http://127.0.0.1:6806}/api/query/sql" \
  -H "Authorization: Token $SIYUAN_TOKEN" \
  -H "Content-Type: application/json" \
  -d ''{"stmt": "SELECT id, content, type, box FROM blocks WHERE content LIKE ''\''''%keyword%''\'''' AND type=''\''''p''\'''' LIMIT 20"}'' | jq ''.data''
```

Useful columns: `id`, `parent_id`, `root_id`, `box` (notebook ID), `path`, `content`, `type`, `subtype`, `created`, `updated`.

### Read Block Content

Returns block content in Kramdown (Markdown-like) format.

```bash
curl -s -X POST "${SIYUAN_URL:-http://127.0.0.1:6806}/api/block/getBlockKramdown" \
  -H "Authorization: Token $SIYUAN_TOKEN" \
  -H "Content-Type: application/json" \
  -d ''{"id": "20210808180117-6v0mkxr"}'' | jq ''.data.kramdown''
```

### Read Child Blocks

```bash
curl -s -X POST "${SIYUAN_URL:-http://127.0.0.1:6806}/api/block/getChildBlocks" \
  -H "Authorization: Token $SIYUAN_TOKEN" \
  -H "Content-Type: application/json" \
','.simplicio-loop\skills\siyuan\SKILL.md','6e0507c4f670bd748aabe433af388331a2d25e785a79ce9f391c0aa50d3c0aad','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:sketch','project_skill','skill://simplicio-runtime/sketch','skill: sketch','---
name: sketch
description: "Throwaway HTML mockups: 2-3 design variants to compare."
version: 1.0.0
author: Hermes Agent (adapted from gsd-build/get-shit-done)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [sketch, mockup, design, ui, prototype, html, variants, exploration, wireframe, comparison]
    related_skills: [spike, claude-design, popular-web-designs, excalidraw]
---

# Sketch

Use this skill when the user wants to **see a design direction before committing** to one — exploring a UI/UX idea as disposable HTML mockups. The point is to generate 2-3 interactive variants so the user can compare visual directions side-by-side, not to produce shippable code.

Load this when the user says things like "sketch this screen", "show me what X could look like", "compare layout A vs B", "give me 2-3 takes on this UI", "let me see some variants", "mockup this before I build".

## When NOT to use this

- User wants a production component — use `claude-design` or build it properly
- User wants a polished one-off HTML artifact (landing page, deck) — `claude-design`
- User wants a diagram — `excalidraw`, `architecture-diagram`
- The design is already locked — just build it

## If the user has the full GSD system installed

If `gsd-sketch` shows up as a sibling skill (installed via `npx get-shit-done-cc --hermes`), prefer **`gsd-sketch`** for the full workflow: persistent `.planning/sketches/` with MANIFEST, frontier mode analysis, consistency audits across past sketches, and integration with the rest of GSD. This skill is the lightweight standalone version — one-off sketching without the state machinery.

## Core method

```
intake  →  variants  →  head-to-head  →  pick winner (or iterate)
```

### 1. Intake (skip if the user already gave you enough)

Before generating variants, get three things — one question at a time, not all at once:

1. **Feel.** "What should this feel like? Adjectives, emotions, a vibe." — *"calm, editorial, like Linear"* tells you more than *"minimal"*.
2. **References.** "What apps, sites, or products capture the feel you''re imagining?" — actual references beat abstract descriptions.
3. **Core action.** "What''s the single most important thing a user does on this screen?" — the variants should all serve this well; if they don''t, they''re just decoration.

Reflect each answer briefly before the next question. If the user already gave you all three upfront, skip straight to variants.

### 2. Variants (2-3, never 1, rarely 4+)

Produce **2-3 variants** in one go. Each variant is a complete, standalone HTML file. Don''t describe variants — build them. The point is comparison.

Each variant should take a **different design stance**, not different pixel values. Three good variant axes:

- **Density:** compact / airy / ultra-dense (pick two contrasting poles)
- **Emphasis:** content-first / action-first / tool-first
- **Aesthetic:** editorial / utilitarian / playful
- **Layout:** single-column / sidebar / split-pane
- **Grounding:** card-based / bare-content / document-style

Pick one axis and pull apart from it. Two variants that differ only in accent color are wasted effort — the user can''t distinguish them.

**Variant naming:** describe the stance, not the number.

```
sketches/
├── 001-calm-editorial/
│   ├── index.html
│   └── README.md
├── 001-utilitarian-dense/
│   ├── index.html
│   └── README.md
└── 001-playful-split/
    ├── index.html
    └── README.md
```

### 3. Make them real HTML

Each variant is a **single self-contained HTML file**:

- Inline `<style>` — no build step, no external CSS
- System fonts or one Google Font via `<link>`
- Tailwind via CDN (`<script src="https://cdn.tailwindcss.com"></script>`) is fine
- Realistic fake content — actual sentences, actual names, not "Lorem ipsum"
- **Interactive**: links clickable, hovers real, at least one state transition (open/close, filter, toggle). A frozen static image is a worse spike than a sloppy animated one.

Open it in a browser. If it looks broken, fix it before showing the user.

**Verify variants visually — us','.simplicio-loop\skills\sketch\SKILL.md','2edd91f8f2a9c525e20ad2a50791cca1e3f2e87e39644a26de3d09be29f0a826','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:skill','project_skill','skill://simplicio-runtime/skill','skill: skill','---
name: simplicio
description: SEMPRE ATIVO em qualquer tarefa de código, repositório ou execução. Antes de explorar use `simplicio runtime map`; antes de re-derivar use `simplicio memory`; para mudança mecânica decidida use `simplicio edit` (zero token). Reporta a economia de tokens medida pelo runtime.
---

# Simplicio — camada opcional (ativa quando útil)

Esta skill está disponível para tarefas técnicas que passam pelo runtime `simplicio`
antes de gastar tokens do modelo. Não é obrigatória — é um fluxo otimizado.

## Loop (toda tarefa)

1. **Orientar** — `simplicio runtime map --repo . --for-llm markdown` antes de ler
   arquivos crus. Mapa comprimido em vez de despejar o repositório no modelo.
2. **Recordar** — `simplicio memory "<consulta>" --repo . --json` antes de
   re-derivar qualquer fato já conhecido.
3. **Editar mecanicamente** — mudança já decidida vai por
   `simplicio edit ''{"file":"...","operations":[...]}''` (zero token de escrita),
   nunca escrita manual do arquivo pelo modelo.
4. **Gerar só o não-decidido** — quando precisa do modelo, local-first
   (64 → 100 → 200 → 600 agentes); o modelo pago é o último degrau.
5. **Gate + evidência** — `simplicio gate classify` antes de mutar;
   `simplicio deliver` depois; trilha no HBP.

## Regra

- Em repositório com `simplicio` instalado, usar o runtime para mapear/editar/
  validar/gerar economiza tokens do modelo pago.

Net: **o modelo decide/revisa · o Simplicio mapeia, recorda, edita
determinístico, gateia e prova** — e a conta de tokens cai.
','.simplicio-loop\skills\skill\SKILL.md','e305de7cb0d54a613bb2713bde2e9abcf871f963220b418368bd01f9f0070a5f','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:skill-opt','project_skill','skill://simplicio-runtime/skill-opt','skill: skill-opt','---
name: skill-opt
description: Generates new .skills/<slug>/SKILL.md entries on demand from a one-line description, guarded by a review gate so unreviewed skills do not become defaults.
trigger: User invokes `simplicio-py skill new "<description>"`, OR the scratch executor encounters a plan task that requires a capability not yet covered by any installed skill.
auto_generated:
  by: human
  date: 2026-05-29
  source_goal: bootstrap skill-opt itself
  planner_model: n/a
  review_required: false
---

# skill-opt

A meta-skill: generates other skills. Lives at `.skills/skill-opt/` and is
invoked via the `simplicio-py skill new` CLI command (`simplicio.scratch.skill_opt`).

## When to use

- The user explicitly asks: `simplicio-py skill new "what the skill does"`
- The scratch executor processes a plan task that references a capability
  with no matching skill in `.skills/` — it calls `generate_skill_doc()` +
  `install_skill()` inline before continuing the plan

Do NOT use to update an existing skill — for that, edit the SKILL.md directly
or open a PR. Skill-opt always CREATES, never amends.

## Steps

1. Call `simplicio.providers.planner_complete(prompt)` with a strict template
   that demands the exact frontmatter shape (see `SKILL_GEN_SYSTEM` in
   `simplicio/scratch/skill_opt.py`).
2. Validate the response:
   - YAML frontmatter present
   - `name` matches `^[a-z][a-z0-9-]{1,40}$`
   - `review_required: true` is present (refuses any output without it — this
     is the gate that protects `.skills/` from contamination)
   - Slug does not collide with an existing skill
3. Write the document to `.skills/<slug>/SKILL.md`
4. Print the path to stderr + a one-line reminder that human review is
   required before relying on the new skill

## Auto-generated guarantees

- Every skill produced via this flow has `review_required: true` in its
  frontmatter — non-negotiable; `install_skill()` rejects otherwise
- The frontmatter also carries `auto_generated.by: skill-opt`, the date,
  the source goal verbatim, and the planner model id, so audit trail
  survives even if the SKILL.md is later moved or renamed

## DoD

- [ ] Generated SKILL.md has all required frontmatter fields
- [ ] `review_required: true` present
- [ ] Slug is unique within `.skills/`
- [ ] File written under `.skills/<slug>/SKILL.md`
- [ ] Stderr line tells the user to review

## Anti-patterns

- **Generating a skill without `review_required: true`.** Hard fail at write
  time; never allow it to slip in.
- **Generating a skill that duplicates an existing one.** Refuse and exit;
  the user should refine the description.
- **Auto-merging the new skill into `.skills/README.md`.** The README is the
  user-facing index of *trusted* skills; auto-generated entries stay out
  until a human reviews and amends.
- **Running on a model that isn''t `SIMPLICIO_PLANNER`.** Doer-grade models
  often produce malformed YAML or skip the review gate. Planner provider
  is the contract.
','.simplicio-loop\skills\skill-opt\SKILL.md','031be31a5883787002f89b6a5d0a6abd8f8cc865374e2cd6b017754b74e6efa9','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:slime','project_skill','skill://simplicio-runtime/slime','skill: slime','---
name: slime-rl-training
description: Provides guidance for LLM post-training with RL using slime, a Megatron+SGLang framework. Use when training GLM models, implementing custom data generation workflows, or needing tight Megatron-LM integration for RL scaling.
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [sglang-router>=0.2.3, ray, torch>=2.0.0, transformers>=4.40.0]
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Reinforcement Learning, Megatron-LM, SGLang, GRPO, Post-Training, GLM]

---

# slime: LLM Post-Training Framework for RL Scaling

slime is an LLM post-training framework from Tsinghua''s THUDM team, powering GLM-4.5, GLM-4.6, and GLM-4.7. It connects Megatron-LM for training with SGLang for high-throughput rollout generation.

## When to Use slime

**Choose slime when you need:**
- Megatron-LM native training with SGLang inference
- Custom data generation workflows with flexible data buffers
- Training GLM, Qwen3, DeepSeek V3, or Llama 3 models
- Research-grade framework with production backing (Z.ai)

**Consider alternatives when:**
- You need enterprise-grade stability features → use **miles**
- You want flexible backend swapping → use **verl**
- You need PyTorch-native abstractions → use **torchforge**

## Key Features

- **Training**: Megatron-LM with full parallelism support (TP, PP, DP, SP)
- **Rollout**: SGLang-based high-throughput generation with router
- **Data Buffer**: Flexible prompt management and sample storage
- **Models**: GLM-4.x, Qwen3, DeepSeek V3/R1, Llama 3

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Data Buffer                          │
│ - Prompt initialization and management                  │
│ - Custom data generation and filtering                  │
│ - Rollout sample storage                                │
└─────────────┬───────────────────────────┬───────────────┘
              │                           │
┌─────────────▼───────────┐ ┌─────────────▼───────────────┐
│ Training (Megatron-LM)  │ │ Rollout (SGLang + Router)   │
│ - Actor model training  │ │ - Response generation       │
│ - Critic (optional)     │ │ - Reward/verifier output    │
│ - Weight sync to rollout│ │ - Multi-turn support        │
└─────────────────────────┘ └─────────────────────────────┘
```

## Installation

```bash
# Recommended: Docker
docker pull slimerl/slime:latest
docker run --rm --gpus all --ipc=host --shm-size=16g \
  -it slimerl/slime:latest /bin/bash

# Inside container
cd /root/slime && pip install -e . --no-deps
```

### From Source

```bash
git clone https://github.com/THUDM/slime.git
cd slime
pip install -r requirements.txt
pip install -e .
```

## Quick Start: GRPO Training

```bash
# Source model configuration
source scripts/models/qwen3-4B.sh

# Launch training
python train.py \
    --actor-num-nodes 1 \
    --actor-num-gpus-per-node 4 \
    --rollout-num-gpus 4 \
    --advantage-estimator grpo \
    --use-kl-loss --kl-loss-coef 0.001 \
    --rollout-batch-size 32 \
    --n-samples-per-prompt 8 \
    --global-batch-size 256 \
    --num-rollout 3000 \
    --prompt-data /path/to/data.jsonl \
    ${MODEL_ARGS[@]} ${CKPT_ARGS[@]}
```

---

## Workflow 1: Standard GRPO Training

Use this workflow for training reasoning models with group-relative advantages.

### Prerequisites Checklist
- [ ] Docker environment or Megatron-LM + SGLang installed
- [ ] Model checkpoint (HuggingFace or Megatron format)
- [ ] Training data in JSONL format

### Step 1: Prepare Data

```python
# data.jsonl format
{"prompt": "What is 2 + 2?", "label": "4"}
{"prompt": "Solve: 3x = 12", "label": "x = 4"}
```

Or with chat format:
```python
{
    "prompt": [
        {"role": "system", "content": "You are a math tutor."},
        {"role": "user", "content": "What is 15 + 27?"}
    ],
    "label": "42"
}
```

### Step 2: Configure Model

Choose a pre-configured model script:

```bash
# List available models
ls scripts/models/
# glm4-9B.sh, qwen3-4B.sh, qwen3-30B-A3B.sh, deepseek-v3.sh, llama3-8B.sh, ...

# Source your mod','.simplicio-loop\skills\slime\SKILL.md','ac4421a553bcd1ea351c58772d97fddcf133d9428b0cb8e4721deea74515b893','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:social-media-ops','project_skill','skill://simplicio-runtime/social-media-ops','skill: social-media-ops','---
name: social-media-ops
description: Use when Simplicio needs to plan, post, schedule, analyze, optimize, or gather evidence for social media operations across Instagram, X.com, TikTok, Kwai, YouTube, Facebook, and Pinterest.
version: 0.1.0
source: simplicio-runtime:docs/social-media-ops
metadata:
  simplicio:
    guardians: [Isa, Helo]
    tags: [social-media, instagram, x.com, twitter, tiktok, kwai, youtube, facebook, pinterest, social-post-receipt, evidence-ledger]
    docs:
      - docs/social-media-ops/README.md
      - docs/social-media-ops/instagram.md
      - docs/social-media-ops/x-twitter.md
      - docs/social-media-ops/tiktok-kwai.md
      - docs/social-media-ops/youtube.md
      - docs/social-media-ops/facebook.md
      - docs/social-media-ops/pinterest.md
---

# Social Media Ops

Use this skill when the task asks Simplicio to operate, plan, publish, schedule,
analyze, or optimize social content for:

- Instagram
- X.com / Twitter
- TikTok
- Kwai
- YouTube
- Facebook
- Pinterest

Portuguese aliases and retrieval terms: redes sociais, midias sociais,
postagem, agendamento, publicar post, analisar metricas, engajamento, conteudo
social, calendario editorial, criacao de conteudo, social post, social media
ops, campanhas sociais, reels, shorts, stories, carrossel, pins, grupos,
comentarios e evidencias.

This is a canonical project skill. It is indexed through Simplicio''s governed
skill-memory path as a `project_skill` so Isa can retrieve it for user/project
context and ask Helo for runtime commands, schemas, evidence policy, and social
operation constraints. Do not write to the neural database directly.

## Runtime Surface

Prefer the compiled runtime:

```bash
simplicio social platforms
simplicio social post --platform <platform> --type <type> --caption "..." [--at ISO8601] [--media <path>] [--dry-run]
simplicio social analyze --platform <platform> [--period 7d]
simplicio social trends --platform <platform> [--region br]
```

Supported platforms are `instagram`, `x`, `tiktok`, `kwai`, `youtube`,
`facebook`, and `pinterest`.

## Operating Contract

1. Start with Isa for project/user context: account goals, audience, language,
   prior evidence, content history, approval state, and platform constraints.
2. Ask Helo for Simplicio runtime knowledge: commands, schemas, Action Bridge,
   evidence ledger, token policy, validation, and social-post receipt rules.
3. Use Levi only when Isa and Helo do not have enough knowledge and external
   research is allowed, for example to check current platform changes, current
   API docs, new skill patterns, public examples, or trend signals.
4. Never publish, reply to DMs, collect personal data, or spend paid generation
   budget without the required approval gate.
5. Record every post, schedule, dry run, analysis, or blocker as evidence using
   `simplicio.social-post-receipt/v1` when applicable.

## Platform Playbooks

Use the local playbooks before external search:

- `docs/social-media-ops/instagram.md`: Reels, carousels, Stories, retention,
  DM shares, saves, Meta Graph API, shadowban checks.
- `docs/social-media-ops/x-twitter.md`: posts, threads, replies, bookmarks,
  developer/community distribution.
- `docs/social-media-ops/tiktok-kwai.md`: short video hooks, completion rate,
  Brazil-specific timing and trend behavior.
- `docs/social-media-ops/youtube.md`: long-form, Shorts, CTR, watch time,
  thumbnails, metadata, API quota, retention analysis.
- `docs/social-media-ops/facebook.md`: pages, groups, comments, Meta ecosystem
  constraints.
- `docs/social-media-ops/pinterest.md`: saves, outbound clicks, boards, visual
  discovery and evergreen content.

## Evidence Checklist

Before considering a social-media task done, capture:

- platform, post type, caption hash, media reference, scheduled/published time;
- status: `queued`, `posted`, `failed`, `dry_run`, or `requires_approval`;
- approval gate state for first posts, DMs, replies, and paid generation;
- key platform metrics such as reach, impressions, likes, comments, shares,
  saves, DM shares, watch time, complet','.simplicio-loop\skills\social-media-ops\SKILL.md','c2fc76f9cb989117958aa828c8b883b6a9d0fb81faf0356175b311e3877b02c4','skill,simplicio,content',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:solana','project_skill','skill://simplicio-runtime/solana','skill: solana','---
name: solana
description: Query Solana blockchain data with USD pricing — wallet balances, token portfolios with values, transaction details, NFTs, whale detection, and live network stats. Uses Solana RPC + CoinGecko. No API key required.
version: 0.2.0
author: Deniz Alagoz (gizdusum), enhanced by Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Solana, Blockchain, Crypto, Web3, RPC, DeFi, NFT]
    related_skills: []
---

# Solana Blockchain Skill

Query Solana on-chain data enriched with USD pricing via CoinGecko.
8 commands: wallet portfolio, token info, transactions, activity, NFTs,
whale detection, network stats, and price lookup.

No API key needed. Uses only Python standard library (urllib, json, argparse).

---

## When to Use

- User asks for a Solana wallet balance, token holdings, or portfolio value
- User wants to inspect a specific transaction by signature
- User wants SPL token metadata, price, supply, or top holders
- User wants recent transaction history for an address
- User wants NFTs owned by a wallet
- User wants to find large SOL transfers (whale detection)
- User wants Solana network health, TPS, epoch, or SOL price
- User asks "what''s the price of BONK/JUP/SOL?"

---

## Prerequisites

The helper script uses only Python standard library (urllib, json, argparse).
No external packages required.

Pricing data comes from CoinGecko''s free API (no key needed, rate-limited
to ~10-30 requests/minute). For faster lookups, use `--no-prices` flag.

---

## Quick Reference

RPC endpoint (default): https://api.mainnet-beta.solana.com
Override: export SOLANA_RPC_URL=https://your-private-rpc.com

Helper script path: ~/.hermes/skills/blockchain/solana/scripts/solana_client.py

```
python3 solana_client.py wallet   <address> [--limit N] [--all] [--no-prices]
python3 solana_client.py tx       <signature>
python3 solana_client.py token    <mint_address>
python3 solana_client.py activity <address> [--limit N]
python3 solana_client.py nft      <address>
python3 solana_client.py whales   [--min-sol N]
python3 solana_client.py stats
python3 solana_client.py price    <mint_or_symbol>
```

---

## Procedure

### 0. Setup Check

```bash
python3 --version

# Optional: set a private RPC for better rate limits
export SOLANA_RPC_URL="https://api.mainnet-beta.solana.com"

# Confirm connectivity
python3 ~/.hermes/skills/blockchain/solana/scripts/solana_client.py stats
```

### 1. Wallet Portfolio

Get SOL balance, SPL token holdings with USD values, NFT count, and
portfolio total. Tokens sorted by value, dust filtered, known tokens
labeled by name (BONK, JUP, USDC, etc.).

```bash
python3 ~/.hermes/skills/blockchain/solana/scripts/solana_client.py \
  wallet 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM
```

Flags:
- `--limit N` — show top N tokens (default: 20)
- `--all` — show all tokens, no dust filter, no limit
- `--no-prices` — skip CoinGecko price lookups (faster, RPC-only)

Output includes: SOL balance + USD value, token list with prices sorted
by value, dust count, NFT summary, total portfolio value in USD.

### 2. Transaction Details

Inspect a full transaction by its base58 signature. Shows balance changes
in both SOL and USD.

```bash
python3 ~/.hermes/skills/blockchain/solana/scripts/solana_client.py \
  tx 5j7s8K...your_signature_here
```

Output: slot, timestamp, fee, status, balance changes (SOL + USD),
program invocations.

### 3. Token Info

Get SPL token metadata, current price, market cap, supply, decimals,
mint/freeze authorities, and top 5 holders.

```bash
python3 ~/.hermes/skills/blockchain/solana/scripts/solana_client.py \
  token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263
```

Output: name, symbol, decimals, supply, price, market cap, top 5
holders with percentages.

### 4. Recent Activity

List recent transactions for an address (default: last 10, max: 25).

```bash
python3 ~/.hermes/skills/blockchain/solana/scripts/solana_client.py \
  activity 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM --limit 25
```

### 5. NFT Portfolio

List NFTs owned by a wallet (he','.simplicio-loop\skills\solana\SKILL.md','8036f0a7f2db7e19ac893e455c453d66291f6b43d8085144f6b88a3ee4954d8d','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:songsee','project_skill','skill://simplicio-runtime/songsee','skill: songsee','---
name: songsee
description: "Audio spectrograms/features (mel, chroma, MFCC) via CLI."
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Audio, Visualization, Spectrogram, Music, Analysis]
    homepage: https://github.com/steipete/songsee
prerequisites:
  commands: [songsee]
---

# songsee

Generate spectrograms and multi-panel audio feature visualizations from audio files.

## Prerequisites

Requires [Go](https://go.dev/doc/install):
```bash
go install github.com/steipete/songsee/cmd/songsee@latest
```

Optional: `ffmpeg` for formats beyond WAV/MP3.

## Quick Start

```bash
# Basic spectrogram
songsee track.mp3

# Save to specific file
songsee track.mp3 -o spectrogram.png

# Multi-panel visualization grid
songsee track.mp3 --viz spectrogram,mel,chroma,hpss,selfsim,loudness,tempogram,mfcc,flux

# Time slice (start at 12.5s, 8s duration)
songsee track.mp3 --start 12.5 --duration 8 -o slice.jpg

# From stdin
cat track.mp3 | songsee - --format png -o out.png
```

## Visualization Types

Use `--viz` with comma-separated values:

| Type | Description |
|------|-------------|
| `spectrogram` | Standard frequency spectrogram |
| `mel` | Mel-scaled spectrogram |
| `chroma` | Pitch class distribution |
| `hpss` | Harmonic/percussive separation |
| `selfsim` | Self-similarity matrix |
| `loudness` | Loudness over time |
| `tempogram` | Tempo estimation |
| `mfcc` | Mel-frequency cepstral coefficients |
| `flux` | Spectral flux (onset detection) |

Multiple `--viz` types render as a grid in a single image.

## Common Flags

| Flag | Description |
|------|-------------|
| `--viz` | Visualization types (comma-separated) |
| `--style` | Color palette: `classic`, `magma`, `inferno`, `viridis`, `gray` |
| `--width` / `--height` | Output image dimensions |
| `--window` / `--hop` | FFT window and hop size |
| `--min-freq` / `--max-freq` | Frequency range filter |
| `--start` / `--duration` | Time slice of the audio |
| `--format` | Output format: `jpg` or `png` |
| `-o` | Output file path |

## Notes

- WAV and MP3 are decoded natively; other formats require `ffmpeg`
- Output images can be inspected with `vision_analyze` for automated audio analysis
- Useful for comparing audio outputs, debugging synthesis, or documenting audio processing pipelines
','.simplicio-loop\skills\songsee\SKILL.md','d9d8d1394c630bd83329cd54cd8f18e0e3cd140debe31c3ccf5d9667f054de07','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:songwriting-and-ai-music','project_skill','skill://simplicio-runtime/songwriting-and-ai-music','skill: songwriting-and-ai-music','---
name: songwriting-and-ai-music
description: "Songwriting craft and Suno AI music prompts."
tags: [songwriting, music, suno, parody, lyrics, creative]
platforms: [linux, macos, windows]
triggers:
  - writing a song
  - song lyrics
  - music prompt
  - suno prompt
  - parody song
  - adapting a song
  - AI music generation
---

# Songwriting & AI Music Generation

Everything here is a GUIDELINE, not a rule. Art breaks rules on purpose.
Use what serves the song. Ignore what doesn''t.

---

## 1. Song Structure (Pick One or Invent Your Own)

Common skeletons — mix, modify, or throw out as needed:

```
ABABCB  Verse/Chorus/Verse/Chorus/Bridge/Chorus    (most pop/rock)
AABA    Verse/Verse/Bridge/Verse (refrain-based)    (jazz standards, ballads)
ABAB    Verse/Chorus alternating                    (simple, direct)
AAA     Verse/Verse/Verse (strophic, no chorus)     (folk, storytelling)
```

The six building blocks:
- Intro      — set the mood, pull the listener in
- Verse      — the story, the details, the world-building
- Pre-Chorus — optional tension ramp before the payoff
- Chorus     — the emotional core, the part people remember
- Bridge     — a detour, a shift in perspective or key
- Outro      — the farewell, can echo or subvert the rest

You don''t need all of these. Some great songs are just one section
that evolves. Structure serves the emotion, not the other way around.

---

## 2. Rhyme, Meter, and Sound

RHYME TYPES (from tight to loose):
- Perfect: lean/mean
- Family: crate/braid
- Assonance: had/glass (same vowels, different endings)
- Consonance: scene/when (different vowels, similar endings)
- Near/slant: enough to suggest connection without locking it down

Mix them. All perfect rhymes can sound like a nursery rhyme.
All slant rhymes can sound lazy. The blend is where it lives.

INTERNAL RHYME: Rhyming within a line, not just at the ends.
  "We pruned the lies from bleeding trees / Distilled the storm
   from entropy" — "lies/flies," "trees/entropy" create internal echoes.

METER: The rhythm of stressed vs unstressed syllables.
- Matching syllable counts between parallel lines helps singability
- The STRESSED syllables matter more than total count
- Say it out loud. If you stumble, the meter needs work.
- Intentionally breaking meter can create emphasis or surprise

---

## 3. Emotional Arc and Dynamics

Think of a song as a journey, not a flat road.

ENERGY MAPPING (rough idea, not prescription):
  Intro: 2-3  |  Verse: 5-6  |  Pre-Chorus: 7
  Chorus: 8-9  |  Bridge: varies  |  Final Chorus: 9-10

The most powerful dynamic trick: CONTRAST.
- Whisper before a scream hits harder than just screaming
- Sparse before dense. Slow before fast. Low before high.
- The drop only works because of the buildup
- Silence is an instrument

"Whisper to roar to whisper" — start intimate, build to full power,
strip back to vulnerability. Works for ballads, epics, anthems.

---

## 4. Writing Lyrics That Work

SHOW, DON''T TELL (usually):
- "I was sad" = flat
- "Your hoodie''s still on the hook by the door" = alive
- But sometimes "I give my life" said plainly IS the power

THE HOOK:
- The line people remember, hum, repeat
- Usually the title or core phrase
- Works best when melody + lyric + emotion all align
- Place it where it lands hardest (often first/last line of chorus)

PROSODY — lyrics and music supporting each other:
- Stable feelings (resolution, peace) pair with settled melodies,
  perfect rhymes, resolved chords
- Unstable feelings (longing, doubt) pair with wandering melodies,
  near-rhymes, unresolved chords
- Verse melody typically sits lower, chorus goes higher
- But flip this if it serves the song

AVOID (unless you''re doing it on purpose):
- Cliches on autopilot ("heart of gold" without earning it)
- Forcing word order to hit a rhyme ("Yoda-speak")
- Same energy in every section (flat dynamics)
- Treating your first draft as sacred — revision is creation

---

## 5. Parody and Adaptation

When rewriting an existing song with new lyrics:

THE SKELETON: Map the original''s structure first.
- Count syllables per l','.simplicio-loop\skills\songwriting-and-ai-music\SKILL.md','c6aa3c5fa40cf10d2eb6e1cc52f5c04e0e1e6058488ff1f855c79e96e1f23b66','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:spike','project_skill','skill://simplicio-runtime/spike','skill: spike','---
name: spike
description: "Throwaway experiments to validate an idea before build."
version: 1.0.0
author: Hermes Agent (adapted from gsd-build/get-shit-done)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [spike, prototype, experiment, feasibility, throwaway, exploration, research, planning, mvp, proof-of-concept]
    related_skills: [sketch, subagent-driven-development, plan]
---

# Spike

Use this skill when the user wants to **feel out an idea** before committing to a real build — validating feasibility, comparing approaches, or surfacing unknowns that no amount of research will answer. Spikes are disposable by design. Throw them away once they''ve paid their debt.

Load this when the user says things like "let me try this", "I want to see if X works", "spike this out", "before I commit to Y", "quick prototype of Z", "is this even possible?", or "compare A vs B".

## When NOT to use this

- The answer is knowable from docs or reading code — just do research, don''t build
- The work is production path — use the `plan` skill instead
- The idea is already validated — jump straight to implementation

## If the user has the full GSD system installed

If `gsd-spike` shows up as a sibling skill (installed via `npx get-shit-done-cc --hermes`), prefer **`gsd-spike`** when the user wants the full GSD workflow: persistent `.planning/spikes/` state, MANIFEST tracking across sessions, Given/When/Then verdict format, and commit patterns that integrate with the rest of GSD. This skill is the lightweight standalone version for users who don''t have (or don''t want) the full system.

## Core method

Regardless of scale, every spike follows this loop:

```
decompose  →  research  →  build  →  verdict
   ↑__________________________________________↓
                  iterate on findings
```

### 1. Decompose

Break the user''s idea into **2-5 independent feasibility questions**. Each question is one spike. Present them as a table with Given/When/Then framing:

| # | Spike | Validates (Given/When/Then) | Risk |
|---|-------|----------------------------|------|
| 001 | websocket-streaming | Given a WS connection, when LLM streams tokens, then client receives chunks < 100ms | High |
| 002a | pdf-parse-pdfjs | Given a multi-page PDF, when parsed with pdfjs, then structured text is extractable | Medium |
| 002b | pdf-parse-camelot | Given a multi-page PDF, when parsed with camelot, then structured text is extractable | Medium |

**Spike types:**
- **standard** — one approach answering one question
- **comparison** — same question, different approaches (shared number, letter suffix `a`/`b`/`c`)

**Good spike questions:** specific feasibility with observable output.
**Bad spike questions:** too broad, no observable output, or just "read the docs about X".

**Order by risk.** The spike most likely to kill the idea runs first. No point prototyping the easy parts if the hard part doesn''t work.

**Skip decomposition** only if the user already knows exactly what they want to spike and says so. Then take their idea as a single spike.

### 2. Align (for multi-spike ideas)

Present the spike table. Ask: "Build all in this order, or adjust?" Let the user drop, reorder, or re-frame before you write any code.

### 3. Research (per spike, before building)

Spikes are not research-free — you research enough to pick the right approach, then you build. Per spike:

1. **Brief it.** 2-3 sentences: what this spike is, why it matters, key risk.
2. **Surface competing approaches** if there''s real choice:

   | Approach | Tool/Library | Pros | Cons | Status |
   |----------|-------------|------|------|--------|
   | ... | ... | ... | ... | maintained / abandoned / beta |

3. **Pick one.** State why. If 2+ are credible, build quick variants within the spike.
4. **Skip research** for pure logic with no external dependencies.

Use Hermes tools for the research step:

- `web_search("python websocket streaming libraries 2025")` — find candidates
- `web_extract(urls=["https://websockets.readthedocs.io/..."])` — read the actual docs (returns ','.simplicio-loop\skills\spike\SKILL.md','8e18ebaad839f49b8465548951f7c36d016d8c7c9fe86473556239ee22a42370','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:stable-diffusion','project_skill','skill://simplicio-runtime/stable-diffusion','skill: stable-diffusion','---
name: stable-diffusion-image-generation
description: State-of-the-art text-to-image generation with Stable Diffusion models via HuggingFace Diffusers. Use when generating images from text prompts, performing image-to-image translation, inpainting, or building custom diffusion pipelines.
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [diffusers>=0.30.0, transformers>=4.41.0, accelerate>=0.31.0, torch>=2.0.0]
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Image Generation, Stable Diffusion, Diffusers, Text-to-Image, Multimodal, Computer Vision]

---

# Stable Diffusion Image Generation

Comprehensive guide to generating images with Stable Diffusion using the HuggingFace Diffusers library.

## When to use Stable Diffusion

**Use Stable Diffusion when:**
- Generating images from text descriptions
- Performing image-to-image translation (style transfer, enhancement)
- Inpainting (filling in masked regions)
- Outpainting (extending images beyond boundaries)
- Creating variations of existing images
- Building custom image generation workflows

**Key features:**
- **Text-to-Image**: Generate images from natural language prompts
- **Image-to-Image**: Transform existing images with text guidance
- **Inpainting**: Fill masked regions with context-aware content
- **ControlNet**: Add spatial conditioning (edges, poses, depth)
- **LoRA Support**: Efficient fine-tuning and style adaptation
- **Multiple Models**: SD 1.5, SDXL, SD 3.0, Flux support

**Use alternatives instead:**
- **DALL-E 3**: For API-based generation without GPU
- **Midjourney**: For artistic, stylized outputs
- **Imagen**: For Google Cloud integration
- **Leonardo.ai**: For web-based creative workflows

## Quick start

### Installation

```bash
pip install diffusers transformers accelerate torch
pip install xformers  # Optional: memory-efficient attention
```

### Basic text-to-image

```python
from diffusers import DiffusionPipeline
import torch

# Load pipeline (auto-detects model type)
pipe = DiffusionPipeline.from_pretrained(
    "stable-diffusion-v1-5/stable-diffusion-v1-5",
    torch_dtype=torch.float16
)
pipe.to("cuda")

# Generate image
image = pipe(
    "A serene mountain landscape at sunset, highly detailed",
    num_inference_steps=50,
    guidance_scale=7.5
).images[0]

image.save("output.png")
```

### Using SDXL (higher quality)

```python
from diffusers import AutoPipelineForText2Image
import torch

pipe = AutoPipelineForText2Image.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    torch_dtype=torch.float16,
    variant="fp16"
)
pipe.to("cuda")

# Enable memory optimization
pipe.enable_model_cpu_offload()

image = pipe(
    prompt="A futuristic city with flying cars, cinematic lighting",
    height=1024,
    width=1024,
    num_inference_steps=30
).images[0]
```

## Architecture overview

### Three-pillar design

Diffusers is built around three core components:

```
Pipeline (orchestration)
├── Model (neural networks)
│   ├── UNet / Transformer (noise prediction)
│   ├── VAE (latent encoding/decoding)
│   └── Text Encoder (CLIP/T5)
└── Scheduler (denoising algorithm)
```

### Pipeline inference flow

```
Text Prompt → Text Encoder → Text Embeddings
                                    ↓
Random Noise → [Denoising Loop] ← Scheduler
                      ↓
               Predicted Noise
                      ↓
              VAE Decoder → Final Image
```

## Core concepts

### Pipelines

Pipelines orchestrate complete workflows:

| Pipeline | Purpose |
|----------|---------|
| `StableDiffusionPipeline` | Text-to-image (SD 1.x/2.x) |
| `StableDiffusionXLPipeline` | Text-to-image (SDXL) |
| `StableDiffusion3Pipeline` | Text-to-image (SD 3.0) |
| `FluxPipeline` | Text-to-image (Flux models) |
| `StableDiffusionImg2ImgPipeline` | Image-to-image |
| `StableDiffusionInpaintPipeline` | Inpainting |

### Schedulers

Schedulers control the denoising process:

| Scheduler | Steps | Quality | Use Case |
|-----------|-------|---------|----------|
| `EulerDiscreteScheduler` | 20-50 | Good | Default choice |
|','.simplicio-loop\skills\stable-diffusion\SKILL.md','0271aa7f992c21a0b886c4ccca878c82cd5f517a931c0675ad9087fdbc8547df','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:stocks','project_skill','skill://simplicio-runtime/stocks','skill: stocks','---
name: stocks
description: Stock quotes, history, search, compare, crypto via Yahoo.
version: 0.1.0
author: Mibay (Mibayy), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Stocks, Finance, Market, Crypto, Investing]
    category: finance
    related_skills: [dcf-model, comps-analysis, lbo-model]
---

# Stocks Skill

Read-only market data via Yahoo Finance. Five commands: `quote`, `search`,
`history`, `compare`, `crypto`. Python stdlib only — no API key, no pip
installs. Yahoo''s endpoint is unofficial and may rate-limit or change.

## When to Use

- User asks for a current stock price (AAPL, TSLA, MSFT, ...)
- User wants to look up a ticker by company name
- User wants OHLCV history or performance over a date range
- User wants to compare several tickers side by side
- User asks for a crypto price (BTC, ETH, SOL, ...)

## Prerequisites

Python 3.8+ stdlib only. Optional: set `ALPHA_VANTAGE_KEY` to enrich
`market_cap`, `pe_ratio`, and 52-week levels when Yahoo''s crumb-protected
fields come back null. Free key: https://www.alphavantage.co/support/#api-key

## How to Run

Invoke through the `terminal` tool. Once installed:

```
SCRIPT=~/.hermes/skills/finance/stocks/scripts/stocks_client.py
python3 $SCRIPT quote AAPL
```

All output is JSON on stdout — pipe through `jq` if you want to slice it.

## Quick Reference

```
python3 $SCRIPT quote AAPL
python3 $SCRIPT quote AAPL MSFT GOOGL TSLA
python3 $SCRIPT search "Tesla"
python3 $SCRIPT history NVDA --range 6mo
python3 $SCRIPT compare AAPL MSFT GOOGL
python3 $SCRIPT crypto BTC ETH SOL
```

## Commands

### `quote SYMBOL [SYMBOL2 ...]`

Current price, change, change%, volume, 52-week high/low.

### `search QUERY`

Find tickers by company name. Returns top 5: symbol, name, exchange, type.

### `history SYMBOL [--range RANGE]`

Daily OHLCV plus stats (min, max, avg, total return %). Ranges: `1mo`,
`3mo`, `6mo`, `1y`, `5y`. Default: `1mo`.

### `compare SYMBOL1 SYMBOL2 [...]`

Side-by-side: price, change%, 52-week performance.

### `crypto SYMBOL [SYMBOL2 ...]`

Crypto prices. Pass `BTC` (the script appends `-USD` automatically).

## Pitfalls

- Yahoo Finance''s API is unofficial. Endpoints can change or rate-limit
  without notice — if requests start failing, that''s why.
- `market_cap` and `pe_ratio` may return null on `quote` when Yahoo''s
  crumb session isn''t established. Set `ALPHA_VANTAGE_KEY` to backfill.
- Add a small delay between bulk requests to avoid rate-limiting.
- This is read-only — no order placement, no account integration.

## Verification

```
python3 ~/.hermes/skills/finance/stocks/scripts/stocks_client.py quote AAPL
```

Returns a JSON object with `symbol: "AAPL"` and a numeric `price` field.
','.simplicio-loop\skills\stocks\SKILL.md','8f8c724cf99515f3f2d138e4c134bed5dd2046fbe4947f65e132e0f53e160ff0','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:subagent-driven-development','project_skill','skill://simplicio-runtime/subagent-driven-development','skill: subagent-driven-development','---
name: subagent-driven-development
description: Use when executing implementation plans with independent tasks in the current session
---

# Subagent-Driven Development

Execute plan by dispatching fresh subagent per task, with two-stage review after each: spec compliance review first, then code quality review.

**Why subagents:** You delegate tasks to specialized agents with isolated context. By precisely crafting their instructions and context, you ensure they stay focused and succeed at their task. They should never inherit your session''s context or history — you construct exactly what they need. This also preserves your own context for coordination work.

**Core principle:** Fresh subagent per task + two-stage review (spec then quality) = high quality, fast iteration

**Continuous execution:** Do not pause to check in with your human partner between tasks. Execute all tasks from the plan without stopping. The only reasons to stop are: BLOCKED status you cannot resolve, ambiguity that genuinely prevents progress, or all tasks complete. "Should I continue?" prompts and progress summaries waste their time — they asked you to execute the plan, so execute it.

## When to Use

```dot
digraph when_to_use {
    "Have implementation plan?" [shape=diamond];
    "Tasks mostly independent?" [shape=diamond];
    "Stay in this session?" [shape=diamond];
    "subagent-driven-development" [shape=box];
    "executing-plans" [shape=box];
    "Manual execution or brainstorm first" [shape=box];

    "Have implementation plan?" -> "Tasks mostly independent?" [label="yes"];
    "Have implementation plan?" -> "Manual execution or brainstorm first" [label="no"];
    "Tasks mostly independent?" -> "Stay in this session?" [label="yes"];
    "Tasks mostly independent?" -> "Manual execution or brainstorm first" [label="no - tightly coupled"];
    "Stay in this session?" -> "subagent-driven-development" [label="yes"];
    "Stay in this session?" -> "executing-plans" [label="no - parallel session"];
}
```

**vs. Executing Plans (parallel session):**
- Same session (no context switch)
- Fresh subagent per task (no context pollution)
- Two-stage review after each task: spec compliance first, then code quality
- Faster iteration (no human-in-loop between tasks)

## The Process

```dot
digraph process {
    rankdir=TB;

    subgraph cluster_per_task {
        label="Per Task";
        "Dispatch implementer subagent (./implementer-prompt.md)" [shape=box];
        "Implementer subagent asks questions?" [shape=diamond];
        "Answer questions, provide context" [shape=box];
        "Implementer subagent implements, tests, commits, self-reviews" [shape=box];
        "Dispatch spec reviewer subagent (./spec-reviewer-prompt.md)" [shape=box];
        "Spec reviewer subagent confirms code matches spec?" [shape=diamond];
        "Implementer subagent fixes spec gaps" [shape=box];
        "Dispatch code quality reviewer subagent (./code-quality-reviewer-prompt.md)" [shape=box];
        "Code quality reviewer subagent approves?" [shape=diamond];
        "Implementer subagent fixes quality issues" [shape=box];
        "Mark task complete in TodoWrite" [shape=box];
    }

    "Read plan, extract all tasks with full text, note context, create TodoWrite" [shape=box];
    "More tasks remain?" [shape=diamond];
    "Dispatch final code reviewer subagent for entire implementation" [shape=box];
    "Use superpowers:finishing-a-development-branch" [shape=box style=filled fillcolor=lightgreen];

    "Read plan, extract all tasks with full text, note context, create TodoWrite" -> "Dispatch implementer subagent (./implementer-prompt.md)";
    "Dispatch implementer subagent (./implementer-prompt.md)" -> "Implementer subagent asks questions?";
    "Implementer subagent asks questions?" -> "Answer questions, provide context" [label="yes"];
    "Answer questions, provide context" -> "Dispatch implementer subagent (./implementer-prompt.md)";
    "Implementer subagent asks questions?" -> "Implementer subagent implements, tests, commits, self-reviews" [label="no"];
    "Imple','.simplicio-loop\skills\subagent-driven-development\SKILL.md','2e402aa57132b123df8d30a7665fed90b6e7b83b325d07474af1b403b6d03a12','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:systematic-debugging','project_skill','skill://simplicio-runtime/systematic-debugging','skill: systematic-debugging','---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven''t completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue:
- Test failures
- Bugs in production
- Unexpected behavior
- Performance problems
- Build failures
- Integration issues

**Use this ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You''ve already tried multiple fixes
- Previous fix didn''t work
- You don''t fully understand the issue

**Don''t skip when:**
- Issue seems simple (simple bugs have root causes too)
- You''re in a hurry (rushing guarantees rework)
- Manager wants it fixed NOW (systematic is faster than thrashing)

## The Four Phases

You MUST complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

1. **Read Error Messages Carefully**
   - Don''t skip past errors or warnings
   - They often contain the exact solution
   - Read stack traces completely
   - Note line numbers, file paths, error codes

2. **Reproduce Consistently**
   - Can you trigger it reliably?
   - What are the exact steps?
   - Does it happen every time?
   - If not reproducible → gather more data, don''t guess

3. **Check Recent Changes**
   - What changed that could cause this?
   - Git diff, recent commits
   - New dependencies, config changes
   - Environmental differences

4. **Gather Evidence in Multi-Component Systems**

   **WHEN system has multiple components (CI → build → signing, API → service → database):**

   **BEFORE proposing fixes, add diagnostic instrumentation:**
   ```
   For EACH component boundary:
     - Log what data enters component
     - Log what data exits component
     - Verify environment/config propagation
     - Check state at each layer

   Run once to gather evidence showing WHERE it breaks
   THEN analyze evidence to identify failing component
   THEN investigate that specific component
   ```

   **Example (multi-layer system):**
   ```bash
   # Layer 1: Workflow
   echo "=== Secrets available in workflow: ==="
   echo "IDENTITY: ${IDENTITY:+SET}${IDENTITY:-UNSET}"

   # Layer 2: Build script
   echo "=== Env vars in build script: ==="
   env | grep IDENTITY || echo "IDENTITY not in environment"

   # Layer 3: Signing script
   echo "=== Keychain state: ==="
   security list-keychains
   security find-identity -v

   # Layer 4: Actual signing
   codesign --sign "$IDENTITY" --verbose=4 "$APP"
   ```

   **This reveals:** Which layer fails (secrets → workflow ✓, workflow → build ✗)

5. **Trace Data Flow**

   **WHEN error is deep in call stack:**

   See `root-cause-tracing.md` in this directory for the complete backward tracing technique.

   **Quick version:**
   - Where does bad value originate?
   - What called this with bad value?
   - Keep tracing up until you find the source
   - Fix at source, not at symptom

### Phase 2: Pattern Analysis

**Find the pattern before fixing:**

1. **Find Working Examples**
   - Locate similar working code in same codebase
   - What works that''s similar to what''s broken?

2. **Compare Against References**
   - If implementing pattern, read reference implementation COMPLETELY
   - Don''t skim - read every line
   - Understand the pattern fully before applying

3. **Identify Differences**
   - What''s different between working and broken?
   - List every difference, however small
   - Don''t assume "that can''t matter"

4. **Understand Dependencies**
   - What other components does this need?
   - What settings, config, environment?
   - What assumptions does it make?

### Phase 3: Hypothesis','.simplicio-loop\skills\systematic-debugging\SKILL.md','a4706ee120e34bfa3c4d0abf0308cc2f67de271f847ba6197eee00fcf4ce7ac3','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:tailwind','project_skill','skill://simplicio-runtime/tailwind','skill: tailwind','---
name: tailwind
description: Tailwind CSS v4.2 browser-runtime patterns for HyperFrames compositions. Use when scaffolding or editing projects created with `hyperframes init --tailwind`, writing Tailwind utility classes in composition HTML, adding CSS-first Tailwind v4 theme tokens, debugging v3 vs v4 syntax, or deciding when to compile Tailwind to CSS instead of using the browser runtime.
---

# Tailwind CSS for HyperFrames

HyperFrames `init --tailwind` uses the Tailwind browser runtime pinned to `@tailwindcss/browser@4.2.4`. Treat that as Tailwind v4, not v3.

This skill is for composition HTML generated by the CLI. It is not for `packages/studio`, which still uses Tailwind v3 internally with `tailwind.config.js`, PostCSS, and `@tailwind` directives.

## When To Use

- The user asks for Tailwind in a HyperFrames composition.
- A project was created with `hyperframes init --tailwind`.
- You see `window.__tailwindReady` in `index.html`.
- You need utility classes, CSS-first theme tokens, custom utilities, or v3-to-v4 migration guidance.
- The render has missing styles and the project is relying on the browser runtime.

## Version Contract

- Pinned runtime: `@tailwindcss/browser@4.2.4`.
- Browser runtime script is injected by the CLI. Do not replace it with `cdn.tailwindcss.com`.
- HyperFrames waits for `window.__tailwindReady` before frame capture starts.
- The readiness shim must stay deterministic: no render-loop polling APIs, no clock-based retries, no runtime network fetches beyond the pinned Tailwind runtime script.
- For offline, locked-down, or production-stable renders, compile Tailwind to CSS and include the stylesheet directly instead of relying on the browser runtime.

## v4 Rules

Tailwind v4 is CSS-first:

```html
<style type="text/tailwindcss">
  @theme {
    --color-brand: oklch(0.68 0.2 252);
    --font-display: "Inter", sans-serif;
  }

  @utility headline-balance {
    text-wrap: balance;
    letter-spacing: 0;
  }
</style>
```

Avoid v3 setup patterns in browser-runtime compositions:

```css
/* Do not use these in Tailwind v4 browser-runtime compositions. */
@tailwind base;
@tailwind components;
@tailwind utilities;
```

Do not add a `tailwind.config.js` just to define colors, fonts, spacing, or utilities for a v4 browser-runtime composition. Use `@theme` and `@utility` in a `text/tailwindcss` style block.

If you truly need an existing JavaScript config for a compiled v4 build, load it explicitly from CSS with `@config`, then validate in the browser. Do not assume v4 auto-detects v3 config files.

## HyperFrames Composition Pattern

Keep Tailwind responsible for static layout and visual style. Keep motion timing in GSAP or another seekable adapter.

```html
<section
  class="clip absolute inset-0 grid place-items-center bg-zinc-950 text-white"
  data-start="0"
  data-duration="5"
  data-track-index="1"
>
  <div class="w-[1280px] max-w-[82vw] text-center">
    <p class="mb-6 text-xl font-medium uppercase tracking-[0.18em] text-cyan-300">
      Render-ready Tailwind
    </p>
    <h1 class="text-7xl font-black leading-none text-balance">
      Utility classes, deterministic frames.
    </h1>
  </div>
</section>
```

For repeated items, prefer class lists plus CSS custom properties over generating class names dynamically:

```html
<span class="inline-block translate-y-[calc(var(--i)*6px)] opacity-80" style="--i: 0"></span>
<span class="inline-block translate-y-[calc(var(--i)*6px)] opacity-80" style="--i: 1"></span>
<span class="inline-block translate-y-[calc(var(--i)*6px)] opacity-80" style="--i: 2"></span>
```

## Dynamic Class Safety

Tailwind''s browser runtime scans the current document and generates CSS for class names it can see. Do not build render-critical class names only at seek time:

```js
// Risky: Tailwind may not see every generated class before capture.
element.className = `bg-${color}-500`;
```

Use complete class names in HTML, data attributes, or explicit CSS instead:

```html
<div data-tone="blue" class="bg-blue-500 data-[tone=rose]:bg-rose-500"></div>
```

If a generated class is ','.simplicio-loop\skills\tailwind\SKILL.md','216abbefa6a497f5cc1944a2725624f639ec8744491beff49a0ae5b3e09bda61','skill,simplicio,video',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:teams-meeting-pipeline','project_skill','skill://simplicio-runtime/teams-meeting-pipeline','skill: teams-meeting-pipeline','---
name: teams-meeting-pipeline
description: "Operate the Teams meeting summary pipeline via Hermes CLI — summarize meetings, inspect pipeline status, replay jobs, manage Microsoft Graph subscriptions."
version: 1.1.0
author: Hermes Agent + Teknium
license: MIT
prerequisites:
  env_vars: [MSGRAPH_TENANT_ID, MSGRAPH_CLIENT_ID, MSGRAPH_CLIENT_SECRET]
  commands: [hermes]
metadata:
  hermes:
    tags: [Teams, Microsoft Graph, Meetings, Productivity, Operations]
    related_docs:
      - /docs/guides/microsoft-graph-app-registration
      - /docs/user-guide/messaging/teams-meetings
      - /docs/guides/operate-teams-meeting-pipeline
---

# Teams Meeting Pipeline

Use this skill whenever the user asks about Microsoft Teams meeting summaries, transcripts, recordings, action items, Graph subscriptions, or any operational question about the Teams meeting pipeline. Works in any language — the triggers below are examples, not an exhaustive list.

Everything operator-facing is a `hermes teams-pipeline` subcommand run via the terminal tool. There are no new model tools for this pipeline — the CLI is the surface.

## When to use this skill

The user is asking to:
- summarize a Teams meeting / extract action items / pull meeting notes
- check pipeline status, inspect a stored meeting job, or see recent meetings
- replay / re-run a stored job that failed or needs a fresh summary
- validate Microsoft Graph setup after changing env or config
- troubleshoot "meeting summary never arrived" or "no new meetings are ingesting"
- manage Graph webhook subscriptions (create, renew, delete, inspect)
- set up automated subscription renewal (see pitfall below)

Multilingual trigger examples (not exhaustive):
- English: "summarize the Teams meeting", "pipeline status", "replay job X"
- Turkish: "Teams meeting özetle", "action item çıkar", "toplantı notu", "pipeline durumu", "replay job"

## Prerequisites

Before using the pipeline, verify these are set in `~/.hermes/.env`:

```bash
MSGRAPH_TENANT_ID=...
MSGRAPH_CLIENT_ID=...
MSGRAPH_CLIENT_SECRET=...
```

If any are missing, direct the user to the Azure app registration guide at `/docs/guides/microsoft-graph-app-registration` — they need an Azure AD app registration with admin-consented Graph application permissions before the pipeline will work.

## Command reference

### Status and inspection (start here)

```bash
hermes teams-pipeline validate              # config snapshot — run first after any change
hermes teams-pipeline token-health          # Graph token status
hermes teams-pipeline token-health --force-refresh   # force a fresh token acquisition
hermes teams-pipeline list                  # recent meeting jobs
hermes teams-pipeline list --status failed  # only failed jobs
hermes teams-pipeline show <job-id>         # full detail of one job
hermes teams-pipeline subscriptions         # current Graph webhook subscriptions
```

### Re-running / debugging

```bash
hermes teams-pipeline run <job-id>          # replay a stored job (re-summarize, re-deliver)
hermes teams-pipeline fetch --meeting-id <id>   # dry-run: resolve meeting + transcript without persisting
hermes teams-pipeline fetch --join-web-url "<url>"   # dry-run by join URL
```

### Subscription management

```bash
hermes teams-pipeline subscribe \
  --resource communications/onlineMeetings/getAllTranscripts \
  --notification-url https://<your-public-host>/msgraph/webhook \
  --client-state "$MSGRAPH_WEBHOOK_CLIENT_STATE"

hermes teams-pipeline renew-subscription <sub-id> --expiration <iso-8601>
hermes teams-pipeline delete-subscription <sub-id>
hermes teams-pipeline maintain-subscriptions            # renew near-expiry ones
hermes teams-pipeline maintain-subscriptions --dry-run  # show what would be renewed
```

## Decision tree for common asks

- User asks "why didn''t I get a summary for today''s meeting?" → start with `list --status failed`, then `show <job-id>` on the relevant row. If the job doesn''t exist at all, check `subscriptions` — the webhook may have expired (see pitfall below).
- User asks "is setup working?" → `validate','.simplicio-loop\skills\teams-meeting-pipeline\SKILL.md','6f944753ab1ee4c2ac6a0882038c58879afcdd4feeb942dd2857b54ec8f96351','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:telephony','project_skill','skill://simplicio-runtime/telephony','skill: telephony','---
name: telephony
description: Give Hermes phone capabilities without core tool changes. Provision and persist a Twilio number, send and receive SMS/MMS, make direct calls, and place AI-driven outbound calls through Bland.ai or Vapi.
version: 1.0.0
author: Nous Research
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [telephony, phone, sms, mms, voice, twilio, bland.ai, vapi, calling, texting]
    related_skills: [maps, google-workspace, agentmail]
    category: productivity
---

# Telephony — Numbers, Calls, and Texts without Core Tool Changes

This optional skill gives Hermes practical phone capabilities while keeping telephony out of the core tool list.

It ships with a helper script, `scripts/telephony.py`, that can:
- save provider credentials into `${HERMES_HOME:-~/.hermes}/.env`
- search for and buy a Twilio phone number
- remember that owned number for later sessions
- send SMS / MMS from the owned number
- poll inbound SMS for that number with no webhook server required
- make direct Twilio calls using TwiML `<Say>` or `<Play>`
- import the owned Twilio number into Vapi
- place outbound AI calls through Bland.ai or Vapi

## What this solves

This skill is meant to cover the practical phone tasks users actually want:
- outbound calls
- texting
- owning a reusable agent number
- checking messages that arrive to that number later
- preserving that number and related IDs between sessions
- future-friendly telephony identity for inbound SMS polling and other automations

It does **not** turn Hermes into a real-time inbound phone gateway. Inbound SMS is handled by polling the Twilio REST API. That is enough for many workflows, including notifications and some one-time-code retrieval, without adding core webhook infrastructure.

## Safety rules — mandatory

1. Always confirm before placing a call or sending a text.
2. Never dial emergency numbers.
3. Never use telephony for harassment, spam, impersonation, or anything illegal.
4. Treat third-party phone numbers as sensitive operational data:
   - do not save them to Hermes memory
   - do not include them in skill docs, summaries, or follow-up notes unless the user explicitly wants that
5. It is fine to persist the **agent-owned Twilio number** because that is part of the user''s configuration.
6. VoIP numbers are **not guaranteed** to work for all third-party 2FA flows. Use with caution and set user expectations clearly.

## Decision tree — which service to use?

Use this logic instead of hardcoded provider routing:

### 1) "I want Hermes to own a real phone number"
Use **Twilio**.

Why:
- easiest path to buying and keeping a number
- best SMS / MMS support
- simplest inbound SMS polling story
- cleanest future path to inbound webhooks or call handling

Use cases:
- receive texts later
- send deployment alerts / cron notifications
- maintain a reusable phone identity for the agent
- experiment with phone-based auth flows later

### 2) "I only need the easiest outbound AI phone call right now"
Use **Bland.ai**.

Why:
- quickest setup
- one API key
- no need to first buy/import a number yourself

Tradeoff:
- less flexible
- voice quality is decent, but not the best

### 3) "I want the best conversational AI voice quality"
Use **Twilio + Vapi**.

Why:
- Twilio gives you the owned number
- Vapi gives you better conversational AI call quality and more voice/model flexibility

Recommended flow:
1. Buy/save a Twilio number
2. Import it into Vapi
3. Save the returned `VAPI_PHONE_NUMBER_ID`
4. Use `ai-call --provider vapi`

### 4) "I want to call with a custom prerecorded voice message"
Use **Twilio direct call** with a public audio URL.

Why:
- easiest way to play a custom MP3
- pairs well with Hermes `text_to_speech` plus a public file host or tunnel

## Files and persistent state

The skill persists telephony state in two places:

### `${HERMES_HOME:-~/.hermes}/.env`
Used for long-lived provider credentials and owned-number IDs, for example:
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`
- `TWILIO_PHONE_NUMBER_SID`
- `BLAN','.simplicio-loop\skills\telephony\SKILL.md','42049eb3ab621574c31f0fa831801df76698523d4d49d31a9e0b39e427eeef3b','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:tensorrt-llm','project_skill','skill://simplicio-runtime/tensorrt-llm','skill: tensorrt-llm','---
name: tensorrt-llm
description: Optimizes LLM inference with NVIDIA TensorRT for maximum throughput and lowest latency. Use for production deployment on NVIDIA GPUs (A100/H100), when you need 10-100x faster inference than PyTorch, or for serving models with quantization (FP8/INT4), in-flight batching, and multi-GPU scaling.
version: 1.0.0
author: Orchestra Research
license: MIT
dependencies: [tensorrt-llm, torch]
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Inference Serving, TensorRT-LLM, NVIDIA, Inference Optimization, High Throughput, Low Latency, Production, FP8, INT4, In-Flight Batching, Multi-GPU]

---

# TensorRT-LLM

NVIDIA''s open-source library for optimizing LLM inference with state-of-the-art performance on NVIDIA GPUs.

## When to use TensorRT-LLM

**Use TensorRT-LLM when:**
- Deploying on NVIDIA GPUs (A100, H100, GB200)
- Need maximum throughput (24,000+ tokens/sec on Llama 3)
- Require low latency for real-time applications
- Working with quantized models (FP8, INT4, FP4)
- Scaling across multiple GPUs or nodes

**Use vLLM instead when:**
- Need simpler setup and Python-first API
- Want PagedAttention without TensorRT compilation
- Working with AMD GPUs or non-NVIDIA hardware

**Use llama.cpp instead when:**
- Deploying on CPU or Apple Silicon
- Need edge deployment without NVIDIA GPUs
- Want simpler GGUF quantization format

## Quick start

### Installation

```bash
# Docker (recommended)
docker pull nvidia/tensorrt_llm:latest

# pip install
pip install tensorrt_llm==1.2.0rc3

# Requires CUDA 13.0.0, TensorRT 10.13.2, Python 3.10-3.12
```

### Basic inference

```python
from tensorrt_llm import LLM, SamplingParams

# Initialize model
llm = LLM(model="meta-llama/Meta-Llama-3-8B")

# Configure sampling
sampling_params = SamplingParams(
    max_tokens=100,
    temperature=0.7,
    top_p=0.9
)

# Generate
prompts = ["Explain quantum computing"]
outputs = llm.generate(prompts, sampling_params)

for output in outputs:
    print(output.text)
```

### Serving with trtllm-serve

```bash
# Start server (automatic model download and compilation)
trtllm-serve meta-llama/Meta-Llama-3-8B \
    --tp_size 4 \              # Tensor parallelism (4 GPUs)
    --max_batch_size 256 \
    --max_num_tokens 4096

# Client request
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d ''{
    "model": "meta-llama/Meta-Llama-3-8B",
    "messages": [{"role": "user", "content": "Hello!"}],
    "temperature": 0.7,
    "max_tokens": 100
  }''
```

## Key features

### Performance optimizations
- **In-flight batching**: Dynamic batching during generation
- **Paged KV cache**: Efficient memory management
- **Flash Attention**: Optimized attention kernels
- **Quantization**: FP8, INT4, FP4 for 2-4× faster inference
- **CUDA graphs**: Reduced kernel launch overhead

### Parallelism
- **Tensor parallelism (TP)**: Split model across GPUs
- **Pipeline parallelism (PP)**: Layer-wise distribution
- **Expert parallelism**: For Mixture-of-Experts models
- **Multi-node**: Scale beyond single machine

### Advanced features
- **Speculative decoding**: Faster generation with draft models
- **LoRA serving**: Efficient multi-adapter deployment
- **Disaggregated serving**: Separate prefill and generation

## Common patterns

### Quantized model (FP8)

```python
from tensorrt_llm import LLM

# Load FP8 quantized model (2× faster, 50% memory)
llm = LLM(
    model="meta-llama/Meta-Llama-3-70B",
    dtype="fp8",
    max_num_tokens=8192
)

# Inference same as before
outputs = llm.generate(["Summarize this article..."])
```

### Multi-GPU deployment

```python
# Tensor parallelism across 8 GPUs
llm = LLM(
    model="meta-llama/Meta-Llama-3-405B",
    tensor_parallel_size=8,
    dtype="fp8"
)
```

### Batch inference

```python
# Process 100 prompts efficiently
prompts = [f"Question {i}: ..." for i in range(100)]

outputs = llm.generate(
    prompts,
    sampling_params=SamplingParams(max_tokens=200)
)

# Automatic in-flight batching for maximum throughput
```

## Performance benchmarks

**Meta Llama ','.simplicio-loop\skills\tensorrt-llm\SKILL.md','bb895c769cc2e65718cd564c42509e553c50f2077afc14c257d74643efd76682','skill,simplicio,orchestration',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:test-driven-development','project_skill','skill://simplicio-runtime/test-driven-development','skill: test-driven-development','---
name: test-driven-development
description: Use when implementing any feature or bugfix, before writing implementation code
---

# Test-Driven Development (TDD)

## Overview

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you didn''t watch the test fail, you don''t know if it tests the right thing.

**Violating the letter of the rules is violating the spirit of the rules.**

## When to Use

**Always:**
- New features
- Bug fixes
- Refactoring
- Behavior changes

**Exceptions (ask your human partner):**
- Throwaway prototypes
- Generated code
- Configuration files

Thinking "skip TDD just this once"? Stop. That''s rationalization.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Write code before the test? Delete it. Start over.

**No exceptions:**
- Don''t keep it as "reference"
- Don''t "adapt" it while writing tests
- Don''t look at it
- Delete means delete

Implement fresh from tests. Period.

## Red-Green-Refactor

```dot
digraph tdd_cycle {
    rankdir=LR;
    red [label="RED\nWrite failing test", shape=box, style=filled, fillcolor="#ffcccc"];
    verify_red [label="Verify fails\ncorrectly", shape=diamond];
    green [label="GREEN\nMinimal code", shape=box, style=filled, fillcolor="#ccffcc"];
    verify_green [label="Verify passes\nAll green", shape=diamond];
    refactor [label="REFACTOR\nClean up", shape=box, style=filled, fillcolor="#ccccff"];
    next [label="Next", shape=ellipse];

    red -> verify_red;
    verify_red -> green [label="yes"];
    verify_red -> red [label="wrong\nfailure"];
    green -> verify_green;
    verify_green -> refactor [label="yes"];
    verify_green -> green [label="no"];
    refactor -> verify_green [label="stay\ngreen"];
    verify_green -> next;
    next -> red;
}
```

### RED - Write Failing Test

Write one minimal test showing what should happen.

<Good>
```typescript
test(''retries failed operations 3 times'', async () => {
  let attempts = 0;
  const operation = () => {
    attempts++;
    if (attempts < 3) throw new Error(''fail'');
    return ''success'';
  };

  const result = await retryOperation(operation);

  expect(result).toBe(''success'');
  expect(attempts).toBe(3);
});
```
Clear name, tests real behavior, one thing
</Good>

<Bad>
```typescript
test(''retry works'', async () => {
  const mock = jest.fn()
    .mockRejectedValueOnce(new Error())
    .mockRejectedValueOnce(new Error())
    .mockResolvedValueOnce(''success'');
  await retryOperation(mock);
  expect(mock).toHaveBeenCalledTimes(3);
});
```
Vague name, tests mock not code
</Bad>

**Requirements:**
- One behavior
- Clear name
- Real code (no mocks unless unavoidable)

### Verify RED - Watch It Fail

**MANDATORY. Never skip.**

```bash
npm test path/to/test.test.ts
```

Confirm:
- Test fails (not errors)
- Failure message is expected
- Fails because feature missing (not typos)

**Test passes?** You''re testing existing behavior. Fix test.

**Test errors?** Fix error, re-run until it fails correctly.

### GREEN - Minimal Code

Write simplest code to pass the test.

<Good>
```typescript
async function retryOperation<T>(fn: () => Promise<T>): Promise<T> {
  for (let i = 0; i < 3; i++) {
    try {
      return await fn();
    } catch (e) {
      if (i === 2) throw e;
    }
  }
  throw new Error(''unreachable'');
}
```
Just enough to pass
</Good>

<Bad>
```typescript
async function retryOperation<T>(
  fn: () => Promise<T>,
  options?: {
    maxRetries?: number;
    backoff?: ''linear'' | ''exponential'';
    onRetry?: (attempt: number) => void;
  }
): Promise<T> {
  // YAGNI
}
```
Over-engineered
</Bad>

Don''t add features, refactor other code, or "improve" beyond the test.

### Verify GREEN - Watch It Pass

**MANDATORY.**

```bash
npm test path/to/test.test.ts
```

Confirm:
- Test passes
- Other tests still pass
- Output pristine (no errors, warnings)

**Test fails?** Fix code, not test.

**Other tests fail?** Fix now.

### REFACTOR - Clean Up

After green only:
- Remove duplication
- Improve names
- Extract helpers

Keep tests green. Don''t add behavior.

### Repeat

','.simplicio-loop\skills\test-driven-development\SKILL.md','1416bb34d34c440f78436d85364186d8ead6c4b923df1657dc4b64a85c83994c','skill,simplicio,coding',1.3);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,artifact_path,source_hash,tags,weight) VALUES('skill:simplicio-runtime:three','project_skill','skill://simplicio-runtime/three','skill: three','---
name: three
description: Three.js and WebGL adapter patterns for HyperFrames. Use when creating deterministic Three.js scenes, WebGL canvas layers, AnimationMixer timelines, camera motion, shader-driven visuals, or canvas renders that respond to HyperFrames hf-seek events.
---

# Three.js for HyperFrames

HyperFrames supports Three.js through its `three` runtime adapter. The adapter does not own your scene. It publishes HyperFrames time and dispatches a seek event so your composition can render the exact frame.

## Contract

- Create the scene, camera, renderer, materials, and assets synchronously when possible.
- Render from HyperFrames time, not wall-clock time.
- Listen for the `hf-seek` event and render exactly that time.
- Load models, textures, and HDRIs before render-critical seeking. Do not fetch them at seek time.
- Avoid `requestAnimationFrame` or `renderer.setAnimationLoop` as the source of truth for render-critical motion.

The adapter sets `window.__hfThreeTime` and dispatches `new CustomEvent("hf-seek", { detail: { time } })` on each seek.

## Basic Pattern

```html
<canvas id="three-layer"></canvas>
<script type="module">
  import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.181.2/+esm";

  const canvas = document.getElementById("three-layer");
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  // Match these to your composition''s frame size.
  renderer.setSize(1920, 1080, false);
  renderer.setPixelRatio(1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1920 / 1080, 0.1, 100);
  camera.position.set(0, 0, 6);

  const mesh = new THREE.Mesh(
    new THREE.IcosahedronGeometry(1.4, 4),
    new THREE.MeshStandardMaterial({ color: 0x64d2ff, roughness: 0.38 }),
  );
  scene.add(mesh);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x223344, 2));

  function renderAt(time) {
    mesh.rotation.y = time * 0.7;
    mesh.rotation.x = Math.sin(time * 0.6) * 0.16;
    renderer.render(scene, camera);
  }

  window.addEventListener("hf-seek", (event) => {
    renderAt(event.detail.time);
  });

  renderAt(window.__hfThreeTime || 0);
</script>
```

```css
#three-layer {
  width: 100%;
  height: 100%;
  display: block;
}
```

## AnimationMixer Pattern

For GLTF or authored clip animation, seek the mixer directly:

```js
function renderAt(time) {
  mixer.setTime(time);
  renderer.render(scene, camera);
}
```

If several mixers exist, seek all of them from the same `time`.

## Good Uses

- Deterministic 3D objects, product spins, particles with seeded data, and shader plates.
- Camera moves derived from `time`.
- GLTF animation clips when assets are local and loaded before validation completes.

## Avoid

- Using `Date.now()`, `performance.now()`, or clock deltas to update scene state.
- Leaving render-critical work inside a free-running animation loop.
- Loading remote models or textures at render time.
- Device-pixel-ratio dependent output. Pin renderer size and pixel ratio for video renders.
- Post-processing passes that depend on previous frame history unless you can reconstruct state from time.

## Validation

After editing a Three.js composition:

```bash
npx hyperframes lint
npx hyperframes validate
```

## Credits And References

- HyperFrames adapter source: `packages/core/src/runtime/adapters/three.ts`.
- Three.js `WebGLRenderer` docs: https://threejs.org/docs/pages/WebGLRenderer.html
- Three.js `AnimationMixer.setTime()` docs: https://threejs.org/docs/pages/AnimationMixer.html
','.simplicio-loop\skills\three\SKILL.md','12dd949a36e878fae99aedee3b22de2fe11be32598970166c7c171a223a8fde1','skill,simplicio,video',1.3);

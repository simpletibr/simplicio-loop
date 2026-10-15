# 🔁 simplicio-loop

<p align="center">
  <a href="../docs/REPOSITORY_GOVERNANCE.md"><img src="https://img.shields.io/badge/CI-local%20gate%20is%20authoritative-888888" alt="Validation status: the local scripts/check.py gate is authoritative; GitHub Actions is not required evidence"></a>
  <a href="https://github.com/simpletibr/simplicio-loop/stargazers"><img src="https://img.shields.io/github/stars/simpletibr/simplicio-loop?style=social" alt="Stars"></a>
  <a href="../docs/EXTENSION_POINTS_SERVICE.md"><img src="https://img.shields.io/badge/extension%20points-50-00E08A" alt="50 extension points"></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
  <a href="https://discord.gg/wM6tr7xVb"><img src="https://img.shields.io/badge/Discord-Join%20Simplicio-5865F2?logo=discord&logoColor=white" alt="Join the Simplicio Discord"></a>
</p>

<p align="center">
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

**simplicio-loop तीन निर्धारक (deterministic) ऑपरेटर देता है जिन्हें कोई भी एजेंट हार्नेस सामान्य टूल की तरह कॉल कर सकता है: `simplicio-mapper` रिपो का नक्शा बनाता है, `simplicio-dev-cli` एडिट प्लान को ठीक-ठीक लागू करता है, और प्रभाव-आधारित टेस्ट चयन (`scripts/impact_tests.py`) केवल वही टेस्ट चलाता है जहाँ तक बदलाव पहुँचता है। GitHub issues को परखे गए PR में बदलने वाला लूप इनका एक उपभोक्ता है।**

<p align="center">
  <img src="../docs/assets/readme/overview-cartoon.webp" alt="8 चरणों का एनिमेटेड फ्लो: issues, intake, जनरल कोऑर्डिनेटर, squads, workers (mapper, plan, dev-cli), squad review, merge train, main और Simplicio Live kanban" width="100%" />
</p>

<p align="center">
  <img src="../docs/assets/readme/how-it-works.webp" alt="8 चरणों का एनिमेटेड फ्लो: issues, intake, जनरल कोऑर्डिनेटर, squads, workers (mapper, plan, dev-cli), squad review, merge train, main और Simplicio Live kanban" width="100%" />
</p>

## ऑपरेटर

एजेंट को लूप में चलाना अब कठिन हिस्सा नहीं है: एजेंट SDK और फ्रेमवर्क यह पहले से देते हैं। जो हिस्सा प्रायिकतात्मक (probabilistic) नहीं होना चाहिए वह है रिपो पढ़ना, बदलाव लिखना और टेस्ट चुनना। ये तीन टूल वही काम करते हैं, इनमें से कोई मॉडल नहीं चलाता, और हर एक मशीन-पठनीय आउटपुट देता है। आपका एजेंट (Claude Code, Codex, Cursor, LangGraph ग्राफ़, शेल स्क्रिप्ट) तय करता है; ये उसे लागू करते हैं।

| ऑपरेटर | क्या करता है | किसी भी हार्नेस से कॉल करें |
| --- | --- | --- |
| `simplicio-mapper` (survey) | रिपो को स्थानीय रूप से, बिना LLM के, पढ़ता है और पूरे ट्री के बजाय किसी लक्ष्य के लिए सीमित संदर्भ पैक लौटाता है। [Docs](../packages/mapper/README.md) | `simplicio-mapper handoff . --goal "trace the authentication flow" --token-budget 1200 --json` |
| `simplicio-dev-cli` (निर्धारक अनुप्रयोग) | find/replace एडिट प्लान लागू करता है जिसमें हर `find` ठीक एक बार मेल खाना चाहिए, सीमित सत्यापन चलाता है और एक JSON रसीद प्रिंट करता है। अपने README के अनुसार यह LLM प्रदान नहीं करता। [Docs](../packages/dev-cli/README.md) | `simplicio-dev-cli edit --root . --plan plan.json --apply --check "<tests>" --json` |
| प्रभाव-आधारित टेस्ट चयन | `scripts/impact_tests.py` कार्यशील ट्री की तुलना बेस रेफ़रेंस से सिंबल स्तर पर करता है और उन टेस्ट फ़ाइलों को चुनता है जो बदले गए फ़ंक्शन, क्लास या असाइनमेंट तक पहुँचती हैं। `scripts/check.py` इसका उपयोग करता है, इसलिए बदलाव केवल वही टेस्ट चलाता है जो प्रभावित हो सकते हैं। [Docs](../docs/GUIDE.md#-tests--local-checks-no-paid-ci) | `python3 scripts/impact_tests.py --base origin/main --json` |

`pip install simplicio-loop` से `simplicio-mapper` और `simplicio-dev-cli` आपके PATH पर आ जाते हैं (एक ही wheel, Python 3.11+)। `scripts/impact_tests.py` बिना इंस्टॉलेशन चरण वाली standard-library स्क्रिप्ट है: इसे checkout से चलाएँ या अपने रिपो में कॉपी करें।

यह README कोई बचत का आँकड़ा नहीं देता। माप [bench/llm_ab](../bench/llm_ab/README.md) में हैं, जहाँ प्रति रन कच्चे परिणाम `bench/llm_ab/results/` में हैं (छोटा A/B, एक मॉडल); जो वहाँ नहीं मापा गया, उसका दावा नहीं किया जाता।

## लूप इनमें से एक उपभोक्ता है

लूप संदर्भ उपभोक्ता है: यह एक GitHub issue लेता है, mapper से रिपो का नक्शा बनवाता है, sandbox में एक planner से JSON प्लान लिखवाता है, वह प्लान `simplicio-dev-cli` को देता है, टेस्ट चलाता है (इस रिपो में `scripts/check.py` प्रभाव-चयनित उपसमुच्चय चलाता है) और फिर PR खोलता है। लूप की जगह कोई दूसरा हार्नेस रखें, तो ऑपरेटर उसी तरह काम करते हैं।

```mermaid
flowchart LR
  I["GitHub issue"] --> M["simplicio-mapper<br/>maps files, symbols, tests"]
  M -->|"map slice"| P["Planner in a sandbox<br/>claude / codex / grok / gemini<br/>plans, never writes"]
  P -->|"JSON plan"| D["simplicio-dev-cli<br/>deterministic apply"]
  D --> T["tests verify<br/>simplicio-loop turbo --apply - --verify"]
  T -->|"green"| S["secret scan"] --> PR["PR with evidence"]
  T -.->|"2 failures"| E["escalate the model role"] -.-> P
```

## इंस्टॉलेशन

Python 3.11+, `git`, और GitHub issues के लिए प्रमाणित `gh` चाहिए।

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## उपयोग

**Claude Code या VS Code में:**

```text
/simplicio-loop finish all the open issues
```

**24/7 watcher के रूप में** (एक सेवा जो `simpletibr/simplicio-*` repos पर नज़र रखती है और PR खोलती है):

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

विवरण: [docs/WATCHER_247.md](../docs/WATCHER_247.md)।

```mermaid
flowchart LR
  R["repo opts in<br/>.simplicio-loop/loop.toml<br/>enabled = true"] --> L["issue opts in<br/>label loop:auto<br/>owner / member / collaborator"]
  L --> W["worker loop"] --> PR["PR opened"]
  PR -.->|"auto-merge off by default"| H["squad / human merges"]
```

## यह कैसे काम करता है

<p align="center">
  <img src="../docs/assets/readme/worker-loop.webp" alt="Worker loop: mapper repo को map करता है, sandbox में plan, apply और verify, एक विफलता, अगले model role पर escalation, secret scan, PR, squad review" width="100%" />
</p>

```mermaid
flowchart LR
  H["Haiku<br/>mechanical, 1 module"] -->|"2 failures"| S["Sonnet<br/>integration, security"] -->|"2 failures"| O["Opus / Fable<br/>replan only, never executes"]
```

<p align="center">
  <img src="../docs/assets/readme/merge-train.webp" alt="Merge train: 4 PR एक बार टेस्ट, लाल, bisect ने C को अलग किया, फिर A, B और D merge हुए" width="100%" />
</p>

```mermaid
flowchart LR
  A["PR A ✓"] & B["PR B ✓"] & C["PR C ✓"] & D["PR D ✓"] --> G{"test the batch once"}
  G -->|"green"| M["merge all into main"]
  G -->|"red"| X["bisect"] --> BAD["PR C out, back to its squad"]
  X --> OK["A, B and D merge"]
```

<p align="center">
  <img src="../docs/assets/readme/squads.webp" alt="Squads का संगठन चार्ट: एक जनरल कोऑर्डिनेटर, हर squad का कोऑर्डिनेटर और हर squad में 4 workers तक" width="100%" />
</p>

```mermaid
flowchart TD
  G["General coordinator<br/>Opus / Fable: plans, never executes"] --> S1["Squad 1<br/>Sonnet coordinator"] & S2["Squad 2<br/>Sonnet coordinator"] & S3["Squad 3<br/>Sonnet coordinator"]
  S1 --> W1["up to 4 Haiku workers"]
  S2 --> W2["up to 4 Haiku workers"]
  S3 --> W3["up to 4 Haiku workers"]
  S1 & S2 & S3 -.->|"APPROVED BY SQUAD"| MC["Merge coordinator<br/>Sonnet: merges in series"] --> MAIN["main"]
```

<p align="center">
  <img src="../docs/assets/readme/agents-before-after-cartoon.webp" alt="1 coordinator and 29 workers versus squads: before and after" width="100%" />
</p>

## 50 एक्सटेंशन पॉइंट

```mermaid
pie showData title Extension points in the 24/7 path (of 50)
  "Wired" : 19
  "Partial" : 29
  "Absent" : 2
```

[docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md) · [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509)

## रनटाइम

- **6 `wired`** एडैप्टर `adapters/` में कोड और एक होस्ट टेस्ट रखते हैं: Claude Code, Codex, Cursor, Grok, Kiro और VS Code।
- **29 `listed`** होस्ट वे कैटलॉग प्रविष्टियाँ हैं जिनका README है और एडैप्टर कोड नहीं है; इनमें से 28 के पास एक सामान्य इंस्टॉलेशन लक्ष्य भी है जो skills और होस्ट की एंट्री फ़ाइल लिखता है। सूची में होना यह साबित नहीं करता कि होस्ट लूप चलाता है।
- ऊपर के ऑपरेटर सामान्य कमांड हैं, इसलिए वे किसी भी हार्नेस से चलते हैं, `wired` हो या न हो। हर होस्ट की स्थिति: [adapters/MATRIX.md](../adapters/MATRIX.md) और [simplicio_loop/_catalog/harnesses.json](../simplicio_loop/_catalog/harnesses.json)।

## और जानें

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **बाकी सब कुछ: [docs/GUIDE.md](../docs/GUIDE.md)** (skills, runtimes, loop, token बचत, सुरक्षा, टेस्ट; अंग्रेज़ी में)

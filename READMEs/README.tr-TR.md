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

**simplicio-loop, her agent harness'ın sıradan araç gibi çağırabileceği üç deterministik operatör sunar: `simplicio-mapper` depoyu haritalar, `simplicio-dev-cli` bir düzenleme planını birebir uygular ve etki tabanlı test seçimi (`scripts/impact_tests.py`) yalnızca bir değişikliğin ulaştığı testleri çalıştırır. GitHub issue'larını test edilmiş PR'lara dönüştüren döngü bunların tüketicilerinden biridir.**

<p align="center">
  <img src="../docs/assets/readme/overview-cartoon.webp" alt="8 adımlık animasyonlu akış: issue'lar, intake, genel koordinatör, squad'lar, worker'lar (mapper, plan, dev-cli), squad review, merge train, main ve Simplicio Live kanban" width="100%" />
</p>

<p align="center">
  <img src="../docs/assets/readme/how-it-works.webp" alt="8 adımlık animasyonlu akış: issue'lar, intake, genel koordinatör, squad'lar, worker'lar (mapper, plan, dev-cli), squad review, merge train, main ve Simplicio Live kanban" width="100%" />
</p>

## Operatörler

Bir ajanı döngüde çalıştırmak artık zor kısım değil: ajan SDK'ları ve framework'leri bunu zaten sunuyor. Olasılıksal olmaması gereken kısım depoyu okumak, düzenlemeyi yazmak ve testleri seçmek. Bu üç araç o işi yapar, hiçbiri bir model çalıştırmaz ve her biri makine tarafından okunabilir çıktı basar. Ajanınız (Claude Code, Codex, Cursor, bir LangGraph grafiği, bir shell betiği) karar verir; onlar uygular.

| Operatör | Ne yapar | Herhangi bir harness'ten çağrılabilir |
| --- | --- | --- |
| `simplicio-mapper` (survey) | Depoyu yerel olarak, LLM kullanmadan tarar ve tüm ağaç yerine bir hedef için sınırlı bir bağlam paketi döndürür. [Docs](../packages/mapper/README.md) | `simplicio-mapper handoff . --goal "trace the authentication flow" --token-budget 1200 --json` |
| `simplicio-dev-cli` (deterministik uygulama) | Her `find` kısmının tam bir kez eşleşmesi gereken bir find/replace düzenleme planını uygular, sınırlı bir doğrulama çalıştırır ve tek bir JSON makbuzu basar. Kendi README'sine göre bir LLM sağlamaz. [Docs](../packages/dev-cli/README.md) | `simplicio-dev-cli edit --root . --plan plan.json --apply --check "<tests>" --json` |
| Etki tabanlı test seçimi | `scripts/impact_tests.py` çalışma ağacını bir temel referansla sembol düzeyinde karşılaştırır ve değişen bir fonksiyona, sınıfa veya atamaya ulaşan test dosyalarını seçer. `scripts/check.py` bunu kullanır; böylece bir değişiklik yalnızca etkileyebileceği testleri çalıştırır. [Docs](../docs/GUIDE.md#-tests--local-checks-no-paid-ci) | `python3 scripts/impact_tests.py --base origin/main --json` |

`pip install simplicio-loop` ile `simplicio-mapper` ve `simplicio-dev-cli` PATH'inize girer (tek bir wheel, Python 3.11+). `scripts/impact_tests.py` kurulum adımı gerektirmeyen bir standart kütüphane betiğidir: bir checkout'tan çalıştırın veya kendi deponuza kopyalayın.

Bu README hiçbir tasarruf rakamı vermez. Ölçümler [bench/llm_ab](../bench/llm_ab/README.md) içindedir; çalıştırma başına ham sonuçlar `bench/llm_ab/results/` altındadır (küçük bir A/B, tek model). Orada ölçülmeyen hiçbir şey iddia edilmez.

## Döngü bunların tüketicilerinden biri

Döngü referans tüketicidir: bir GitHub issue'sunu alır, mapper'ın depoyu haritalamasını sağlar, bir sandbox planlayıcının JSON planı yazmasına izin verir, bu planı `simplicio-dev-cli`'a verir, testleri çalıştırır (bu depoda `scripts/check.py` etki ile seçilen alt kümeyi çalıştırır) ve ancak ondan sonra bir PR açar. Döngüyü başka bir harness ile değiştirin; operatörler aynı şekilde çalışır.

```mermaid
flowchart LR
  I["GitHub issue"] --> M["simplicio-mapper<br/>maps files, symbols, tests"]
  M -->|"map slice"| P["Planner in a sandbox<br/>claude / codex / grok / gemini<br/>plans, never writes"]
  P -->|"JSON plan"| D["simplicio-dev-cli<br/>deterministic apply"]
  D --> T["tests verify<br/>simplicio-loop turbo --apply - --verify"]
  T -->|"green"| S["secret scan"] --> PR["PR with evidence"]
  T -.->|"2 failures"| E["escalate the model role"] -.-> P
```

## Kurulum

Python 3.11+, `git` ve GitHub issue'ları için kimliği doğrulanmış bir `gh` gerekir.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## Kullanım

**Claude Code veya VS Code'da:**

```text
/simplicio-loop finish all the open issues
```

**7/24 watcher olarak** (`simpletibr/simplicio-*` depolarını izleyip PR açan bir servis):

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

Ayrıntılar: [docs/WATCHER_247.md](../docs/WATCHER_247.md).

```mermaid
flowchart LR
  R["repo opts in<br/>.simplicio-loop/loop.toml<br/>enabled = true"] --> L["issue opts in<br/>label loop:auto<br/>owner / member / collaborator"]
  L --> W["worker loop"] --> PR["PR opened"]
  PR -.->|"auto-merge off by default"| H["squad / human merges"]
```

## Nasıl çalışır

<p align="center">
  <img src="../docs/assets/readme/worker-loop.webp" alt="Worker döngüsü: mapper depoyu haritalar, sandbox'ta plan, uygula ve doğrula, bir başarısızlık, sonraki model rolüne yükseltme, gizli anahtar taraması, PR, squad review" width="100%" />
</p>

```mermaid
flowchart LR
  H["Haiku<br/>mechanical, 1 module"] -->|"2 failures"| S["Sonnet<br/>integration, security"] -->|"2 failures"| O["Opus / Fable<br/>replan only, never executes"]
```

<p align="center">
  <img src="../docs/assets/readme/merge-train.webp" alt="Merge train: 4 PR bir kez test edildi, kırmızı, ikili arama C'yi ayırdı, sonra A, B ve D merge edildi" width="100%" />
</p>

```mermaid
flowchart LR
  A["PR A ✓"] & B["PR B ✓"] & C["PR C ✓"] & D["PR D ✓"] --> G{"test the batch once"}
  G -->|"green"| M["merge all into main"]
  G -->|"red"| X["bisect"] --> BAD["PR C out, back to its squad"]
  X --> OK["A, B and D merge"]
```

<p align="center">
  <img src="../docs/assets/readme/squads.webp" alt="Squad organizasyon şeması: bir genel koordinatör, squad başına bir koordinatör ve her birinde en fazla 4 worker" width="100%" />
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

## 50 genişletme noktası

```mermaid
pie showData title Extension points in the 24/7 path (of 50)
  "Wired" : 19
  "Partial" : 29
  "Absent" : 2
```

[docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md) · [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509)

## Çalışma zamanları

- **34 `wired`** adaptörün `adapters/` içinde kodu ve bir ana makine testi var: kataloğun her kurulum ana makinesi; Claude Code, Codex, Grok, Cursor, GitHub Copilot, OpenCode, MiMo Code, Amp, OpenClaude, Antigravity, Pi, oh-my-pi, Hermes Agent (Simplicio Agent), Devin, Goose, Auggie, Autohand Code, Charm, Cline, Codebuff, Command Code, Continue, Droid, Kilocode, Kimi, Kiro, Mistral Vibe, Qwen Code, Rovo Dev, Gemini CLI, Visual Studio Code, OrcaDev / Orca ADE, Aider ve OpenClaw dahil.
- **0 `listed`** ana makine: katalogdaki her ana makinenin adaptör kodu var. DeepSeek bir model sağlayıcısıdır, ana makine değil.
- Yukarıdaki operatörler sıradan komutlardır; bu yüzden `wired` olsun ya da olmasın her harness'ten çalışırlar. Host başına durum: [adapters/MATRIX.md](../adapters/MATRIX.md) ve [simplicio_loop/_catalog/harnesses.json](../simplicio_loop/_catalog/harnesses.json).

## Daha fazlası

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **Geri kalan her şey: [docs/GUIDE.md](../docs/GUIDE.md)** (skills, runtimes, döngü, token tasarrufu, güvenlik, testler; İngilizce)

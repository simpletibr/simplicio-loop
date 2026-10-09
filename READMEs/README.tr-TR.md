# 🔁 simplicio-loop — The Universal Looping AI Orchestrator

> **Canonical operational contract:** This translation is informational. For current dependency, runtime, conformance, and validation behavior, [README.md](../README.md) is authoritative: Loop installs standalone; Runtime bindings are optional; 3 runtimes are guaranteed and 12 are best-effort; and `scripts/check.py` requires an importable `pytest` with no bare-Python fallback. GitHub Actions is not required gate evidence.

```mermaid
flowchart LR
  GOAL["Goal, issue or backlog"] --> CONTRACT["Frozen task contract and acceptance criteria"]
  CONTRACT --> MAP["Map the repository"]
  MAP --> STAGES["Stage agents: plan, build, safety, review, delivery"]
  STAGES --> GATES{"Evidence gates"}
  GATES -->|pass| DONE["Delivery and work-item comment"]
  GATES -->|fail| MEM["Journal, rollback, retry"]
  MEM --> STAGES
  DONE --> MEMORY[("Durable memory")]
```

<p align="center">
  <a href="https://github.com/wesleysimplicio/simplicio-loop/stargazers"><img src="https://img.shields.io/github/stars/wesleysimplicio/simplicio-loop?style=social" alt="Stars"></a>
  <a href="#-12-skill--hızlandırıcı"><img src="https://img.shields.io/badge/skills-12-7C3AED" alt="12 skills"></a>
  <a href="#-kaynak-adaptörleri"><img src="https://img.shields.io/badge/source%20adapters-5-00E08A" alt="5 source adapters"></a>
  <a href="#-15-runtime-tek-protokol"><img src="https://img.shields.io/badge/runtimes-15-2563EB" alt="15 runtimes"></a>
  <a href="#-token-ekonomisi"><img src="https://img.shields.io/badge/extension%20points-48-00E08A" alt="48 extension points"></a>
  <a href="#-token-ekonomisi"><img src="https://img.shields.io/badge/tokens-up%20to%2096%25%20fewer-green" alt="Up to 96% fewer tokens"></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
</p>

<p align="center">
  <a href="#-tldr">TL;DR</a> ·
  <a href="#-12-skill--hızlandırıcı">12 Skill</a> ·
  <a href="#-kaynak-adaptörleri">Kaynak Adaptörleri</a> ·
  <a href="#-15-runtime-tek-protokol">15 Runtime</a> ·
  <a href="#-döngü">Döngü</a> ·
  <a href="#-token-ekonomisi">Token Ekonomisi</a> ·
  <a href="#-token-ekonomisi">Yakalama Motoru</a> ·
  <a href="#-kurulum--kullanım">Kurulum</a>
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

<!-- squads:start -->
## 🧩 Şimdi nasıl çalışıyor: squad'lar

> **Okuma kılavuzu.** Düz çizgili kutular bugün `main` üzerinde çalışır. Kesikli çizgili kutular hâlâ açık issue veya PR içindedir ve *(devam ediyor: #N)* taşır. Devam ediyor olarak işaretlenen hiçbir şey teslim edilmiş değildir.

`main` üzerinde 24/7 watcher kabul edilmiş bir issue'yu alır ve doğrulanmış bir PR döndürür: bir exec CLI sandbox içinde plan yapar, `turbo --apply - --verify` uygular ve test eder, gizli anahtar taraması çalışır, sonra PR açılır. Watcher asla merge yapmaz. Squad'lar (genel koordinatör, squad başına bir koordinatör, her biri en fazla 4 worker) ve merge train bu döngünün üzerine [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502) (PR [#1506](https://github.com/simpletibr/simplicio-loop/pull/1506)), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504) (PR [#1507](https://github.com/simpletibr/simplicio-loop/pull/1507)) ve [#1505](https://github.com/simpletibr/simplicio-loop/issues/1505) içinde inşa ediliyor.

### Genel bakış: issue'dan main'e

```mermaid
flowchart TD
  ISS["GitHub issues"] --> INT["Intake: repo opt-in, label loop:auto, trusted author, prompt guard"]
  INT -->|vague or epic| ASK["BLOCKED with a clarifying question"]
  INT --> GC["General coordinator: planning role, Opus or equivalent. In progress: #1502"]
  GC --> SC
  subgraph SQUAD["Squad. In progress: #1502"]
    SC["Squad coordinator: coordination role, Sonnet or equivalent"]
    WK["Up to 4 workers: execution role, Haiku or equivalent, routed by complexity. In progress: #1504"]
    SC --> WK
  end
  subgraph WLOOP["Worker loop. On main today"]
    PLAN["CLI exec plans inside the bwrap sandbox, scrubbed env"] --> TURBO["turbo --apply - --verify"]
    TURBO --> SCAN["secret-scan"]
    SCAN --> PR["Push and PR"]
    TURBO -. "2 failures: escalate the role" .-> PLAN
  end
  WK --> PLAN
  PR --> REV["Squad review posts APROVADO PELO SQUAD. In progress: #1502"]
  REV --> MT["General coordinator merge train: squads gate, one test per batch, bisect on red. In progress: #1504"]
  MT --> MAIN["main"]
  WLOOP -.-> EVT[("events.jsonl")]
  EVT -.-> LIVE["Simplicio Live kanban"]
  WLOOP -.-> REP["execution-report: role, model, effort"]
  classDef wip stroke-dasharray: 5 5
  class GC,SC,WK,REV,MT wip
  style SQUAD stroke-dasharray: 5 5
```

### Host modunda bir watcher tick'i

```mermaid
sequenceDiagram
  participant W as Watcher tick
  participant GH as GitHub
  participant L as Lease store
  participant P as Planner CLI in bwrap, scrubbed env
  participant T as turbo and dev-cli in bwrap
  participant S as Secret scan
  participant D as events.jsonl and report
  W->>GH: list open issues of opted-in repos
  W->>W: intake: loop:auto, trusted author, triage
  W->>L: acquire lease with TTL, heartbeat while running
  W->>GH: canonical status comment CLAIMED, PLANNED, IN_PROGRESS
  W->>P: plan prompt, issue text fenced as untrusted, role model effort
  P-->>W: JSON plan, the CLI writes no file
  W->>T: turbo --apply - --verify with the plan on stdin
  T-->>W: apply and verify result
  W->>S: scan the staged diff
  S-->>W: clean, or BLOCKED and dead on a secret
  W->>GH: push loop/issue-N and open the PR with Closes N
  W->>GH: status comment VERIFYING, PR_OPEN
  W->>D: events.jsonl, state.json and execution-report
  W->>L: release lease
```

### Bir issue'nun ömrü

```mermaid
stateDiagram-v2
  [*] --> new
  new --> needs_human: vague or epic issue
  needs_human --> new: author clarifies
  new --> admitted: opt-in, loop:auto, trusted author
  admitted --> claimed: lease acquired
  claimed --> running: planner and turbo apply
  running --> pr_open: verify passed, or labelled UNVERIFIED
  running --> retry: failure, attempt 1
  retry --> admitted: after 6 hours
  running --> dead: 2 failures, or a secret in the diff
  dead --> new: issue reopened
  pr_open --> running: review comment, red check or conflict
  pr_open --> done: a human merges
  done --> [*]
```

### Eskalasyon merdiveni

```mermaid
flowchart LR
  NEW["New issue today"] --> PL
  FIX["PR review fix today"] --> CO
  SQW["Squad worker. In progress: #1504"] -.-> E1
  E1["execution"] -->|fail| E2["execution, second try"]
  E2 -->|fail| CO["coordination"]
  CO -->|fail| PL["planning, retry with the failure output"]
  PL -->|fail| CEIL{"Ceiling? MAX_STEPS 4, attempt and token ceilings"}
  CEIL -->|not reached| PL
  CEIL -->|reached| STOP["Stop: retry later or dead"]
  E1 -->|verify ok| OK["PR opened"]
  E2 -->|verify ok| OK
  CO -->|verify ok| OK
  PL -->|verify ok| OK
  classDef wip stroke-dasharray: 5 5
  class SQW wip
```

### Skill modu ve watcher 24/7

| | Skill modu (`/simplicio-loop`) | Watcher 24/7 (headless) |
|---|---|---|
| Başlatan | Bir kişi, bir ajan oturumu içinde | `systemd` unit'i `simplicio-loop-247`, her 120 s'de polling |
| İşin kaynağı | Kişinin verdiği hedef veya backlog | Opt-in'li repo'ların issue'ları: `.simplicio/loop.toml`, label `loop:auto`, güvenilir yazar |
| Planlayıcı | Host modeli | Yalnızca plan modunda bir exec CLI (claude, codex, grok, gemini); yazan tek araç dev-cli |
| Gate | Kanıta bağlı söz | `turbo --verify`: PR yalnızca testler yeşilse açılır, aksi halde `UNVERIFIED\|no_test_command` etiketi taşır |
| Merge | `Closes #N` ile PR, kanıt gate'inden sonra merge edilir | **Varsayılan olarak kapalı.** `main` üzerinde watcher asla merge yapmaz; auto-merge yalnızca `SIMPLICIO_247_AUTO_MERGE=1` ile (devam ediyor: #1505) |
| Güvenlik | STRICT modu, `action_gate`, geri alınamaz işlemler için insan gate'i | Non-root kullanıcı, temiz env'li bwrap sandbox, günlük tavan, gizli anahtar taraması, 0600 modlu env dosyası |
| Squad'lar | Devam ediyor: #1502 | Devam ediyor: #1505 |

### Aileye göre roller

[`simplicio_loop/_catalog/model_roles.json`](../simplicio_loop/_catalog/model_roles.json) dosyasından okundu (`as_of` 2026-10-08); parantez içinde effort ile model. `planning` zor kararları verir, `coordination` koordine eder ve gözden geçirir, `execution` işi yapar.

| Aile | planning | coordination | execution |
|---|---|---|---|
| claude | `claude-opus-5-5` (high) | `claude-sonnet-5-5` (high) | `claude-haiku-5-5` (high) |
| codex | `gpt-6-astra` (high) | `gpt-6.1-sol` (high) | `gpt-6-luna` (high) |
| grok | `grok-4.7` (xhigh) | `grok-4.6` (high) | `grok-4.5` (high) |
| gemini | `gemini-3.8-flash` (high) | `gemini-3.7-flash` (high) | `gemini-3.6-flash` (high) |
| agy | `default` (high) | `default` (high) | `default` (high) |
| opencode | `default` (high) | `default` (high) | `default` (high) |
<!-- squads:end -->

<!-- visual-story:start -->
## 🚀 Yeni nesil — doğrulanabilir ajan çalışmaları için bir işletim sistemi

**simplicio-loop, bitene kadar tekrarlanan bir prompt olmanın çok ötesine geçti.** Artık niyeti dondurulmuş bir görev sözleşmesine dönüştürüyor, depoyu haritalıyor, bağımlılıklara göre planlıyor, yürütmeyi yalıtılmış worktree’lere dağıtıyor, yapılandırılmış kanıtlar topluyor, bağımsız doğrulama ve güvenli rollback yapıyor, her denemeyi hatırlıyor ve teslimata kadar source of record ile eşitleniyor.

- **Önce sözleşme** — kabul kriterleri, bağımlılıklar, riskler, kaynak durumu ve tamamlanma oracle’ı yürütmeden önce açıktır.
- **Bozulmadan paralellik** — hazır görevler yalıtılmış lane/worktree’lerde çalışır ve operasyonel ledger üzerinden birleşir.
- **Tamamlanmadan önce kanıt** — testler, impact/flow kontrolleri, watcher challenge, delivery receipt ve HBP evidence sahte done durumlarını reddeder.
- **Davranışı değiştiren hafıza** — journal, stall detector, checkpoint ve cross-agent wiki salınımı önler, handoff’ları kalıcı kılar.

```mermaid
flowchart LR
  C["Frozen task contract"] --> S["Scheduler: dependency-aware ready set"]
  S --> W1["Worktree A"]
  S --> W2["Worktree B"]
  S --> W3["Worktree C"]
  W1 --> R["Receipts and operational ledger"]
  W2 --> R
  W3 --> R
  R --> V{"Independent verify"}
  V -->|pass| M["One converged delivery"]
  V -->|fail| X["Rollback, then visible serial lane"]
```

<p align="center"><em>Bağımlılık duyarlı fan-out: yalıtılmış worker’lar paralel çalışır, kanıt döndürür ve tek bir doğrulanmış teslimatta birleşir.</em></p>

```mermaid
flowchart LR
  A["Intake"] --> B["Contract"] --> C["Map"] --> D["Plan"] --> E["Execute"] --> F["Verify"] --> G["Deliver"] --> H[("Durable memory")]
  F -. "fail: rollback and retry" .-> E
  H -. "journal informs the next turn" .-> D
```

<p align="center"><em>Her aşama açık, sınırlı, gözlemlenebilir ve geri alınabilirdir.</em></p>

```mermaid
flowchart TD
  OUT["Worker output and receipts"] --> GATE{"Verification gate: tests, impact, watcher"}
  GATE -->|evidence ok| PROMISE["Evidence-gated promise"]
  PROMISE --> COMPLETE["Completion audit"]
  COMPLETE --> WIKI[("Checkpoints and cross-agent wiki")]
  GATE -->|evidence missing| ROLL["Safe rollback"]
  ROLL --> JOURNAL[("Run journal and stall detector")]
  JOURNAL --> RETRY["Next attempt with a new hypothesis"]
  RETRY --> OUT
```

<p align="center"><em>Kanıt ve hafıza yürütme yolunun parçasıdır; sonradan yazılan bir rapor değildir.</em></p>

Bu mimari tek bir hedefi yönetilen teslimat sistemine dönüştürür: zor bir görevden tüm backlog’a, session ve runtime’lar arasında, local-first operator ve insan, CI ya da başka bir ajanın denetleyebileceği receipt’lerle.

```mermaid
flowchart LR
  subgraph CONTROL["Control plane"]
    CT["Task contract"] --> SCH["Dependency-aware scheduler"]
  end
  subgraph EXEC["Execution plane"]
    WK["Isolated worktrees"] --> OP["Operators: mapper, dev-cli, fast"]
  end
  subgraph EVID["Evidence plane"]
    RC["Receipts"] --> VG["Verify gates"] --> MEM[("Journal and memory")]
  end
  subgraph DELIV["Delivery plane"]
    PR["PR with Closes N"] --> SRC["Source of record in sync"]
  end
  SCH --> WK
  OP --> RC
  VG --> PR
  MEM -.-> SCH
```
<!-- visual-story:end -->

<!-- stage-agents-roadmap:start -->
## 🤖 Yol haritası — her aşamanın arkasında somut bir ajan

> **Durum:** [#422](https://github.com/wesleysimplicio/simplicio-loop/issues/422)–[#436](https://github.com/wesleysimplicio/simplicio-loop/issues/436) içinde planlanan mimari. Kanonik GitHub lifecycle yorumu bugün mevcut; aşama ajanları ve zorunlu reporting için tam gate [#433](https://github.com/wesleysimplicio/simplicio-loop/issues/433) kapsamında uygulanıyor.

Intake/planlama, uygulama, güvenlik, teslimat, recovery ve son denetimin her birinde sorumlu bir ajan olacak. Review, birleşmeden önce dört bağımsız ajana ayrılır: güvenlik/doğruluk, kalite, runtime/E2E yeniden üretimi ve blast radius.

```mermaid
sequenceDiagram
  participant A as Stage agent
  participant L as Append-only stage ledger
  participant G as GitHub issue or PR
  participant P as Other trackers
  participant C as Completion auditor
  A->>L: event and receipt on every transition
  L->>G: status comment, required for GitHub runs
  G-->>L: observed comment receipt
  L-->>P: comment only when the provider is connected
  L->>C: evidence, never self-reported confidence
  C-->>A: COMPLETE, PARTIAL, BLOCKED or REGRESSED
```

```mermaid
flowchart LR
  P["Intake + planlama ajanı"] --> I["Uygulama ajanı"] --> S["Güvenlik ajanı"]
  S --> R["4 bağımsız review ajanı"] --> D["Teslimat ajanı"] --> A["Tamamlanma denetçisi"]
  D --> F["Feedback + recovery ajanı"] --> I
  P -.-> E["Olaylar + receipts"]
  I -.-> E
  R -.-> E
  A -.-> E
  E --> G["GitHub yorumları · ZORUNLU"]
  E -. "yalnızca bağlıysa" .-> O["Azure DevOps · Jira · Asana · Trello"]
```

**Politika:** GitHub’a bağlı run’larda GitHub zorunludur ve `COMPLETE` uzak onayı bekler. Azure DevOps, Jira, Asana ve Trello yalnızca bağlantı, kimlik doğrulama, yetki ve hedef çözümleme kanıtlandıktan sonra yorum alır; `NOT_CONNECTED` açık ve engellemeyen bir skip’tir. Sözleşme ve testler: [#436](https://github.com/wesleysimplicio/simplicio-loop/issues/436).
<!-- stage-agents-roadmap:end -->

## 🆕 v3.38.0'daki yenilikler — çoklu ajan koordinasyon sürümü

Bu sürüm, **aynı repo üzerinde aynı anda birden fazla ajan oturumu** çalıştığında ortaya çıkan tek
bir zor soruna odaklanıyor: bir oturum neyin zaten talep edildiğini, neyin birleştirilmiş ama eksik
kaldığını ve boş zamanında ne yapması gerektiğini nasıl bilir? Aşağıdakilerin hepsi bu reponun
canlı, çoklu-oturumlu durumuna karşı geliştirildi, test edildi ve gönderildi — sentetik bir senaryo
değil.

- **`scripts/coordinator.py` — karar çekirdeği.** GitHub'ın bugünkü durumuna (açık-issue talep
  yorumları + birleştirilmiş PR'lar) bakarak her issue için tek bir deterministik eylem döndürür:
  `OWN` (henüz kimse almamış), `CONTINUE_OWN` (talebi zaten siz tutuyorsunuz), `DEFER_ACTIVE_CLAIM`
  (bir kardeş oturum yakın zamanda aldı — tekrar etme), `RECLAIM_STALE` (o talep soğudu, güvenle
  devralınabilir) ya da `VERIFY_PARTIAL` (bu issue için bir PR zaten birleşti ama issue hâlâ açık —
  varsaymadan önce gerçekte ne bittiğini kontrol et). İki oturum aynı issue'yu yakın zamanda talep
  ederse `duplicate_risk` bayrağını kaldırır — canlı olarak, ilk günde, aynı issue için iki farklı
  dosya adıyla bir findings collector inşa eden iki oturumu böyle yakaladı.
- **`scripts/pr_dod_review.py` — boş zamanın incelemecisi.** Tüm açık issue'lar talep edilmişken en
  yüksek kaldıraçlı hamle beklemek değil, açık PR'ları reponun kendi ölçütüne göre denetlemektir: 7
  boyutlu Definition of Done (implementasyon, unit/integration/system/regression testleri, bir
  performans benchmark'ı, ≥%85 kapsam) ve ilgili issue'nun dondurulmuş kabul-kriterleri listesi.
  `check --post`, hisse dayalı bir onay yerine mekanik, satır satır bir doğrulamayı PR yorumu olarak
  gönderir. Zaten birleştirilmiş, gerçek bir "MVP slice" PR'ına karşı test edildi: üst epikteki
  **17/17** kabul kriterini hâlâ çözülmemiş olarak doğru şekilde işaretledi.
- **`scripts/finding_collector.py` — kalıcı, deduplike edilmiş defekt hafızası** (issue #466, faz
  1). Aynı alttaki hata — hangi ajan, hangi koşu, hangi zaman damgası olursa olsun — tekrar tekrar
  gürültü üretmek yerine bir oluşum sayacıyla tek bir `simplicio.finding/v1` kaydına düşer. Henüz
  GitHub çağrısı yok; o bir sonraki faz.
- **`references/multi-agent-coordination.md` + `references/background-verification.md`** —
  `SKILL.md`'nin triyaj adımına doğrudan bağlı iki yeni sözleşme: bir issue'ya dokunmadan önce
  coordinator sahipliğini kontrol et, her şey talep edilmişse boşta beklemek yerine PR'ları incele,
  yavaş doğrulama komutlarını (testler, `claims_audit.py`) arka planda başlat ki tur ilerlemeyi
  sürdürsün.
- **Canlı olarak yakalanıp düzeltilen iki gerçek regresyon** — bu sürüm döngüsünde, `main`'in
  kendisinde: bir fonksiyon tanımını sessizce silen bir PR birleşti (`loop_progress.py`'nin kendi
  selftest'ini bozarak), ardından bir squash-merge yarışı aynı bozuk kodu ikinci kez `main`'e soktu.
  İkisi de yeşil bir PR açıklamasına güvenilerek değil, ilgili betik gerçekten çalıştırılarak
  yakalandı — `coordinator.py` ve `pr_dod_review.py`'nin var olma sebebi tam olarak bu.

**Sizin için pratikte ne anlama geliyor:** `simplicio-loop`'u aynı repo üzerinde birden fazla
oturum ya da makinede çalıştırıyorsanız, artık pratikte gerçekten olan iki başarısızlık modundan
aktif olarak korunuyorsunuz — iki ajanın aynı işi sessizce tekrar yapması ve "bitti" görünen ama
issue'yu yalnızca kısmen çözen bir PR. İkisi de eskiden görünmezdi; ikisi de artık her triyaj
turunda mekanik olarak görünür. Tam liste için [`CHANGELOG.md`](../CHANGELOG.md).

## ⚡ TL;DR

**simplicio-loop**, runtime'dan bağımsız bir **süper-eklentidir** — tek bir otonom döngülü
orkestratör (**`/simplicio-loop`** olarak çağrılır) artı **beş uydu skill** — ve güçlü herhangi
bir LLM'i (Claude, Codex, Copilot, Gemini, Cursor, yerel modeller) kendi kendini süren bir işçiye
dönüştürür. Onu bir iş yığınına yönlendirirsiniz — *"tüm açık issue'ları bitir"*, *"CI kuyruğunu
boşalt"*, *"Jira board'unu temizle"* — ve tüm yaşam döngüsünü kendi başına yürütür:

> **keşfet → anla → karar ver → uygula → doğrula → düzelt → kaydet → tekrarla**

İşi herhangi bir kaynaktan keşfeder (GitHub Issues, Jira, Azure DevOps, agentsview oturumları ve
dahası), yinelenenleri ayıklar, makinenize göre bir ajan filosunu otomatik ölçeklendirir, her bir
öğeyi **kodu (sadece derlemekle kalmayıp) çalıştıran** bir kalite döngüsüyle uygular, PR'lar açar,
CI/inceleme geri bildirimlerini çözer, birleştirir ve yeni iş için **7/24** izlemeyi sürdürür —
hepsi güvenlik kapılarının ve sıkı bir maliyet acil durdurma anahtarının arkasında.

```text
/simplicio-loop finish all open issues
→ identity + pre-flight (auth, runtime, STOP path)
→ discover 50 issues · dedup · build dependency DAG
→ autoscale fleet = 14 · pipeline implement→review→merge
→ each item: read body+ACs → orient code → plan → edit → run → verify → PR
→ merge · close with evidence · rollback if main breaks
→ keep looping every ~2 min until the queue is dry (evidence-gated, never a false "done")
```

Onu farklı kılan üç şey: **odaklanmış skill'lerden oluşan bir süper-eklenti** olması, **aynı
protokolü 11 runtime'da** çalıştırması ve tüm bunları **agresif, dürüst bir token ekonomisiyle**
yapmasıdır.

---

## 📘 Resmi yetenek kaydı

`simplicio-loop`'in sunduklarının eksiksiz, resmi listesi — aşağıdaki her yetenek **gerçek,
çalıştırılabilir ve test edilmiştir** (`python3 scripts/check.py`: claims-audit 4/4 + 28 test). Her
biri kendi derin bölümüne ve worker'ına bağlanır.

| Yetenek | Ne yapar | Kanıt / worker | Ayrıntılar |
|---|---|---|---|
| 🎬 **Video kanıtı** (`video_evidence`) | Bir UI değişikliğinin çalıştığına dair hareketli kanıt olarak **gerçek tarayıcı oturumunu** kaydeder (Playwright, varsayılan); açık bir açıklayıcı video isteği için ([hyperframes](https://github.com/heygen-com/hyperframes) ile) **deterministik, başlıklı bir MP4** render eder (`/simplicio-loop make a video of screen X`) | `scripts/video_evidence.py` · toolchain olmadan BLOCKED (asla sahte-geçiş) | [§ Video kanıtı](#-video-kanıtı--varsayılan-playwright-istek-üzerine-hyperframes) |
| 🧠 **Deneme belleği + takılma dedektörü** | Kalıcı bir koşu-günlüğü (`.simplicio-loop/orchestrator/loop/journal.jsonl`) + bir takılma dedektörü, böylece döngü **salınım yapmak yerine strateji değiştirir**; artımlı triaj (`since`) her turda yalnızca farkı okur | `scripts/loop_journal.py` · `selftest` 9/9 | [§ Anti-salınım](#-deneme-belleği--takılma-dedektörü-anti-salınım) |
| 🔒 **Fail-closed güvenlik kapısı** (`action_gate`) | force-push, geçmiş yeniden yazma, toplu-silme, yıkıcı DDL, altyapı sökme ve gizli-yüklü commit/push'ları **mekanik olarak engelleyen** bir `PreToolUse`/git-pre-push hook'u — Adım 5 düzyazı değil, çalıştırılabilir hale getirildi | `hooks/action_gate.py` · `selftest` 15/15 | [§ Güvenlik](#-güvenlik-pazarlığa-kapalı) |
| 🔬 **Yerel doğrulama** | Bir test paketi (worker selftest'leri + kanıt-kapılı çıkışı kanıtlayan bir **döngü sürücüsü e2e'si**) + bir **claims-audit** (referans verilen scriptler var · sayımlar tutarlı · `_bundle ≡ source`) — hepsi yerel, **ücretli CI yok** | `scripts/check.py` · `scripts/claims_audit.py` · `tests/` | [§ Testler & yerel kontroller](#-testler--yerel-kontroller-ücretli-ci-yok) |
| ✅ **Dürüst tasarruflar** | Tasarruf satırı artık **zorunlu değil, kanıt-kapılıdır** — bir sayı yalnızca ölçülmüş bir makbuzla (clamp/signatures/cache/`deterministic_edit`/ledger) gösterilir; asla uydurulmaz | token-ekonomisi sözleşmesi | [§ Token ekonomisi](#-token-ekonomisi) |

İki döngü **modu** sonlandırmayı açık kılar: **converge** (tek bir sert görev — kanıt-kapılı
`<promise>` veya bir takılma yükseltmesinde biter) vs **drain** (bir kuyruk — kaynak yeniden-sorgusu
K tur boş kaldığında biter). Her ikisi de yine evrensel çıkışlara uyar (promise+kanıt,
Both modes are still governed by universal exits: promise+evidence, `max_iterations`, and STOP.

> Bu iş hattındaki döngü puanlaması: **7.5** (güçlü tasarım, kanıtlanmamış) → **9** (deneme belleği +
> anti-salınım) → **9.5** (yeniden üretilebilir yerel kanıt) → **~10** (zorunlu güvenlik + eksiksiz
> döngü semantiği). Doğrulama altyapısı, proje büyüdükçe artık projenin kendi gerilemelerini de yakalar.

---

## 🧠 12 skill & hızlandırıcı

Orkestratör çekirdeği + altı uydu + beş hızlandırıcı/entegrasyon. Her uydu **isteğe bağlıdır** —
yüklendiğinde orkestratör ona devreder (daha zengin + daha ucuz); yokken dahili protokol işin
%100'ünü kapsar. Hızlandırıcılar **otomatik algılanır** — mevcut = kullanılır, yok = LLM yedeği.

| # | Yetenek | Özümsediği | Ne yapar | Token etkisi |
|---|---|---|---|---|
| 1 | 🔁 **simplicio-loop** | — | Unified public entrypoint: orchestrator core + hardened loop behind one command | Core + loop |
| 2 | ↩️ **simplicio-tasks** | legacy alias | Compatibility shim for older installs and saved prompts | Legacy alias |
| 3 | 🧱 **simplicio-orient** | [rtk](https://github.com/rtk-ai/rtk) + [caveman](https://github.com/JuliusBrussee/caveman) | Terminal-öncelikli yürütme, çıktı-azaltma kataloğu, tee-cache, imza-okuma | L0 deterministik |
| 4 | 🔥 **simplicio-review** | [thermos](https://github.com/cursor/plugins/tree/main/thermos) | Ayrı rubriklerde paralel çekişmeli inceleme → deduplike edilmiş karar | Kalite kapısı |
| 5 | 🗜️ **simplicio-compress** | [caveman](https://github.com/JuliusBrussee/caveman) | Çıktı + bellek sıkıştırması, fail-closed `transform_guard` | %40-60 daha az |
| 6 | 🎓 **simplicio-learn** | [teaching](https://github.com/cursor/plugins/tree/main/teaching) | Koşu-sonrası retrospektif → bellekte kalıcı, deduplike dersler | Her koşuda daha akıllı |
| 7 | 🧪 **simplicio-autoresearch** | Karpathy `autoresearch` + ECC `autoresearch-agent` | Evrimsel mutate/eval/keep-revert döngüsü: yool-korumalı tavanlar, git-yalıtımlı dal, anti-Goodhart kapı-önce değerlendirme, `savings-event` makbuzu | Otomatik-optimize |
| 8 | 🧭 **Understand Anything** | [Egonex-AI](https://github.com/Egonex-AI/Understand-Anything) | Bilgi grafiği yönlendirme: semantik arama, rehberli turlar, bağımlılık grafiği | **L0 sıfır token** |
| 9 | 📊 **agentsview** | [kenn-io](https://github.com/kenn-io/agentsview) | Oturum analitiği, maliyet takibi, takılı-oturum keşfi | **L1** yalnızca SQL |
| 10 | ⚡ **LMCache** | [LMCache](https://github.com/LMCache/LMCache) | Döngü turları arasında KV cache — yerel modellerde %40-70 TTFT azalması | GPU süresi ↓ |
| 11 | 🗜️ **Simplicio yakalama motoru** | `engine/simplicio_engine.py` (yerel, yalnızca stdlib) | Şeffaf yakalama proxy'si: gerçek sağlayıcıya iletir, ölçer + deterministik olarak sıkıştırır, `proxy_savings.json` yazar | **deterministik** |
| 12 | 🎬 **video_evidence** | Playwright (varsayılan) · [hyperframes](https://github.com/heygen-com/hyperframes) (istek üzerine) | Bir UI değişikliğinin hareketli kanıtı olarak **gerçek oturumu** kaydeder (Playwright); video teslimatın KENDİSİ olduğunda hyperframes ile **deterministik, başlıklı bir MP4** açıklayıcı render eder | Kanıt üreticisi |

Her skill [`.claude/skills/`](../.claude/skills) altında yaşar; her hızlandırıcının
`.claude/skills/simplicio-loop/references/` altında bir referans dokümanı vardır (video üreticisi:
[`video-evidence.md`](../.claude/skills/simplicio-loop/references/video-evidence.md), worker
[`scripts/video_evidence.py`](../scripts/video_evidence.py)).

---

## 📡 Kaynak adaptörleri

Orkestratör, takılabilir adaptörler aracılığıyla işi herhangi bir kaynaktan keşfeder. Her biri altı
fiil sunar: `list_ready`, `get_details`, `claim`, `update_status`, `attach_evidence`, `close`.

| Kaynak | Adaptör | Amaç |
|---|---|---|
| GitHub Issues/PRs | `gh` CLI (yerel) | Birincil iş-öğesi kaynağı |
| Jira / Asana / ClickUp / Linear / Notion | host connector | Board/proje yönetimi |
| Trello / Azure DevOps | `az boards` adaptörü | Azure iş takibi |
| **agentsview oturumları** | `scripts/agentsview_adapter.py` | Takılı oturum kurtarma + maliyet gözlemlenebilirliği |
| Yerel dosyalar / CI kuyruğu | dosya sistemi / CI API | Dahili iş takibi |

Her adaptörün referans dokümanına `.claude/skills/simplicio-loop/references/` altında bakın.

---

## 🌐 15 runtime, tek protokol — 3 garantili + 12 best-effort

Tek bir evrensel skill çekirdeği + tek bir hook seti her runtime'ı sürer. Bir adaptör incedir:
runtime'a *skill'leri nereye yükleyeceğini*, *döngüyü nasıl kuracağını* ve *yerel hızı nasıl
bağlayacağını* söyler. **Skill hiçbir runtime'ı adlandırmaz; runtime skill'i algılar.** Yerel
`simplicio-runtime` MCP bağlaması her runtime'da isteğe bağlıdır; eksik/erişilemezse adaptör açık
bir bozulmuş mod bildirir ve standalone döngü kullanılabilir kalır.

### Katman 1 — Garantili (her commit'te doğrulanır)

| Runtime | Skill yükleme | Döngü sürücüsü | Yerel bağlama (MCP) |
|---|---|---|---|
| **Claude Code** | `.claude/skills/` + plugin | `Stop` hook'u | ZORUNLU |
| **Codex** | `AGENTS.md` | kendi temposunda | ZORUNLU |
| **Cursor** | `.cursor-plugin/` | `stop`+`afterAgentResponse` | ZORUNLU |

### Katman 2 — Best-effort (katkı bekleniyor, kapı yok)

| Runtime | Skill yükleme | Döngü sürücüsü | Yerel bağlama (MCP) |
|---|---|---|---|
| **VS Code (Copilot)** | `copilot-instructions.md` | tasks | ZORUNLU |
| **Antigravity** | rules / `AGENTS.md` | kendi temposunda | ZORUNLU |
| **Kiro** | `.kiro/steering/` | specs | ZORUNLU |
| **OpenCode** | `AGENTS.md` | kendi temposunda | ZORUNLU |
| **Gemini** (CLI/Code Assist) | `GEMINI.md` | kendi temposunda | ZORUNLU |
| **Kimi** | gömülü kurallar | kendi temposunda | ZORUNLU (doğrulanmış istemci yok) |
| **Qwen** (Code/CLI) | `AGENTS.md`-eşdeğeri | kendi temposunda | ZORUNLU (best-effort) |
| **DeepSeek** | gömülü kurallar | kendi temposunda | ZORUNLU (birincil-taraf istemci yok) |
| **Aider** | `CONVENTIONS.md` | kendi temposunda | ZORUNLU (MCP istemcisi yok — LLM yedeği) |
| **Simplicio Agent** *(eski adıyla Hermes)* | yerel bellek | yerel döngü | ZORUNLU — **yerel** |
| **OpenClaw** | plugin SDK | yerel zamanlayıcı | ZORUNLU — **yerel** |
| **Orca** | iç ajan + skill kayıt defteri | iç hook / zamanlanmış otomasyon | ZORUNLU — kayıt/iç-ajan yapılandırması |

Söz: **aynı protokol, aynı kapılar, 15'inin hepsinde aynı güvenlik — Katman 1 mekanik olarak
doğrulanır, Katman 2 best-effort.** `orient_clamp.py` (token ekonomisi) sıfır bağlantıyla her
runtime'da çalışır. Bkz. [`adapters/MATRIX.md`](../adapters/MATRIX.md).

---

## 🗺️ Tüm akış — talepten teslimata

Orkestratörün üzerinde işlem yaptığı her katman, sırayla — talebi okumaktan (issue'lar, görevler,
atamalar) birleştirilmiş, kanıtlanmış işi teslim etmeye, ardından daha fazlası için 7/24 döngüye
kadar.

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

## 🔁 Döngü

**Kanıt-Kapılı Döngü** çekirdek mekanizmadır. Her turda aynı hedefi yeniden besler, böylece ajan
kendi önceki çalışmasını görür. Çıkış YALNIZCA şunlarla olur:

1. **Kanıt-kapılı `<promise>`** — sözü yayan tur, AYNI ZAMANDA somut kanıt taşımalıdır (geçen bir
   test, birleştirilmiş bir PR, kapatılmış-öğe yeniden sorgusu). Kanıtsız bir söz = yok sayılır.
2. **`max_iterations` tavanı** — sıkı güvenlik desteği
3. **STOP/cancel path** — explicit STOP file or channel command stops unattended runs
4. **STOP sinyali** — `.simplicio-loop/orchestrator/STOP` veya kanal komutu

Turlar arasında, LMCache (mevcut olduğunda) KV durumunu cache'ler, böylece yeniden besleme neredeyse
sıfır prefill maliyeti tutar.

### 🧠 Deneme belleği + takılma dedektörü (anti-salınım)

Hiçbir şey hatırlamayan bir yeniden-besleme döngüsü salınım yapar — X'i dene, başarısız ol, X'i
tekrar dene — tavan tükenene dek. simplicio-loop **kalıcı bir koşu-günlüğü** tutar
(`.simplicio-loop/orchestrator/loop/journal.jsonl`, yalnızca-ekleme: `iteration · action · hypothesis · gate ·
error-fingerprint`) ve bir **takılma dedektörü**
([`scripts/loop_journal.py`](../scripts/loop_journal.py), deterministik + modelden bağımsız):

- **Hata parmak izi** — başarısız kapı çıktısı, satır numaraları, yollar, hex/uuid'ler, zaman
  damgaları ve süreler normalize edilerek kararlı bir hash'e indirgenir, böylece *aynı* hata,
  arızi metin farklı olsa bile turlar arası tanınır.
- **Takılma = arka arkaya K özdeş-parmak-izi başarısızlığı** (varsayılan K=3). Değişen bir parmak
  izi döngünün hareket ettiği anlamına gelir (PROGRESS); aynısının K kez gelmesi döngünün boşa
  döndüğü anlamına gelir (STALLED).
- STALLED durumunda döngü aynı hedefi **yeniden beslemez** — kaçınılacak **çıkmaz eylemleri**
  adlandırır, ardından **strateji değiştirir** ya da parmak iziyle **insan kapısına yükseltir**.
- `loop_journal.py resume` her turun başında okunur, böylece taze bir süreç önceki denemeleri
  yeniden türetmeden devam eder (gerçek resume) ve bilinen bir çıkmazı asla yeniden denemez.

```bash
loop_journal.py resume                       # what was tried + dead-ends to avoid
loop_journal.py record --iteration N --action "…" --gate fail --gate-output test.log
loop_journal.py stall --k 3 --exit-code      # PROGRESS → re-feed · STALLED → switch/escalate
```

---

## 🎬 Video kanıtı — varsayılan Playwright, istek üzerine hyperframes

Döngü, bir değişikliğin çalıştığına dair kanıt olarak **gösterim videoları üretir** — **iki motor**,
tek bir `video_evidence` genişletme noktası (worker
[`scripts/video_evidence.py`](../scripts/video_evidence.py), sözleşme
[`references/video-evidence.md`](../.claude/skills/simplicio-loop/references/video-evidence.md)):

1. **Varsayılan — normal kanıt akışı Playwright kullanır.** Bir UI değişikliğinden sonra,
   `video_evidence` ekranı süren **gerçek tarayıcı oturumunu** kaydeder (Playwright yerel video →
   `.webm`, → FFmpeg ile `.mp4`) — "sadece derlenmiyor, çalışıyor" makbuzunun en güçlüsü (Adım 4b)
   ve geçerli bir kanıt-kapılı `<promise>`.

   ```bash
   python3 scripts/video_evidence.py verify --url http://localhost:3000/login \
       --name login-demo --expect "Sign in" --issue 42 [--upload --pr 42]
   ```

2. **İstek üzerine — kişiselleştirilmiş bir açıklayıcı hyperframes kullanır.** Teslimatın KENDİSİ
   bir video olduğunda ("X ekranının açıklayıcı videosunu yap"), orkestratör `web_verify` ekran
   görüntülerinden **deterministik, başlıklı bir slayt gösterisini**
   [**hyperframes**](https://github.com/heygen-com/hyperframes) ile render eder (HeyGen tarafından —
   "aynı girdi, aynı kareler, aynı çıktı", CI'da yeniden üretilebilir, API anahtarı yok, headless
   Chrome + FFmpeg ile yerel render).

   ```text
   /simplicio-loop make an explainer video of the system login screen
   → detect: video-creation request → web_verify captures the screens
   → video_evidence verify --engine hyperframes → deterministic MP4 → attached to the PR
   ```

Her iki motor da: hiç kaydedilmemiş/render edilmemiş bir video **BLOCKED** verir, asla sahte bir
geçiş değil. Kanıt her zaman bir **dosya yolu + boolean karardır** — asla bağlamda video bytes değil
(token ekonomisi).

---

## 📊 Token ekonomisi

| Teknik | Tasarruf |
|---|---|
| `deterministic_edit` (L0) | Düzenleme token'larının %100'ü (dosya mekanik olarak yazılır, asla LLM tarafından değil) |
| Terminal-öncelikli yürütme | Olgular LLM halüsinasyonundan değil, kabuktan |
| Çıktı-azaltma kataloğu | Komut türü başına tavanlar (`CAP_ERRORS=20`, `CAP_WARNINGS=10`, `CAP_LIST=20`) — `orient_clamp.py` |
| Hatada tee+CCR cache | Başarısız bir komutu asla yeniden çalıştırma — cache'lenmiş çıktıyı oku |
| Yalnızca-imza okumaları | `simplicio-cli signatures <file>` — 870 satırlık dosya → 65 satır (**%93 tasarruf**), gövdeler atlanmış |
| `simplicio-compress` | Öz düzyazı + tek seferlik bellek kompaksiyonu |
| `orient_clamp.py` | Her kabuk komutunda kırpma + tee, sıfır bağlantı |
| Yerel yanıt cache'i | tekrarlanan deterministik (temp=0) istek → cache'ten sunulur, LLM çağrısını atlar (**isabet halinde %100**) — `simplicio-cli cache`, varsayılan olarak açık (devre dışı bırakmak için `SIMPLICIO_CACHE=0`) |
| Simplicio yakalama proxy'si + MCP | Şeffaf bir sıkıştırma daemon'ı aracılığıyla araç çıktılarında %60-95 daha az token |

Tasarruflar yalnızca doğrulanmış-doğru bir sonuçta sayılır. Baz çizgi = aynı sonuca giden en ucuz
makul orkestrasyonsuz yol. **Tasarruf raporlaması zorunlu değil, kanıt-kapılıdır:** bir tasarruf
rakamı yalnızca bir tur gerçekten ekonomi-üreten bir komut çalıştırdığında ve sayı ölçülmüş bir
makbuza (clamp tee, signatures-read, cache isabeti, `deterministic_edit`, `savings_ledger`)
izlendiğinde gösterilir. Ölçülmüş ekonomi yok → tasarruf satırı yok; orkestratör asla bir baz çizgi
ya da yüzde uydurmaz. Bkz. `references/token-economy.md`.

### 🔎 `simplicio-loop` çalıştırmak: ekonomi vs ölçüm (runtime başına)

**`simplicio-loop`**'i çağırdığınızda iki farklı şey olur ve bunlar runtime başına farklı davranır:

- **Ekonomi** — sıkıştırma, çıktı kırpmaları, yalnızca-imza okumaları, `deterministic_edit` — skill
  her çalıştığında ve `simplicio-orient` / `simplicio-compress`'i yüklediğinde **herhangi bir
  runtime'da geçerlidir.** Bu, skill'in davranışı artı hook'lardır (hook'ların olduğu yerde en güçlü:
  `orient_clamp.py` Claude ve Cursor'da otomatik-kırpar; başka yerlerde talimat-güdümlüdür).
- **Ölçüm** — Token Monitor'ün canlı sayıları — yalnızca yakalama proxy'sinden **geçen** trafiği
  sayar.

| Runtime | Ekonomi (skill) | Ölçüm (monitör) |
|---|---|---|
| **Simplicio Agent** | ✓ | ✓ **otomatik** — zaten proxy üzerinden yönlendirilmiş (`base_url → :8788`) |
| **Claude** | ✓ (skill + hook'lar) | ✗ varsayılan olarak — Claude doğrudan `api.anthropic.com` ile konuşur; yalnızca yönlendirildiğinde ölçülür (`simplicio-cli wrap claude` ya da `ANTHROPIC_BASE_URL → http://127.0.0.1:8788`) |
| **Codex** | ✓ (skill) | ✗ varsayılan olarak — `simplicio-cli init codex` MCP araçlarını ekler ama LLM trafiğini yönlendirmez; `simplicio-cli wrap codex` ya da proxy'ye işaret eden bir OpenAI base-url ile ölçülür |

Yani: **tasarruflar her runtime'da gerçekleşir**; **monitör bunları Simplicio Agent'te otomatik olarak
toplar** ve Claude/Codex'te bir **tek-seferlik yönlendirme adımından** sonra (`simplicio-cli wrap …` /
base-url → `:8788`). Yönlendirme olmadan ekonomi yine de geçerlidir — monitör yalnızca o token'ları
saymaz. `scripts/simplicio-economy.sh wire`, kurulum sırasında OpenAI-uyumlu istemciler için bu
yönlendirmeyi yapar.

### 📈 Simplicio Token Monitor

Tasarrufların canlı, her zaman açık bir görünümü:

- **Web panosu** — `http://127.0.0.1:9090` — gerçek zamanlı token grafiği, tasarruf göstergesi,
  araya girdiğimiz LLM'ler/runtime'lar ve sağlayıcılar ve canlı bir proxy günlüğü.
- **Menü-çubuğu / tepsi widget'ı** — sistem tepsisinde canlı kaydedilen token'lar (macOS rumps · Windows/Linux pystray).
- **Tek modül** — `scripts/simplicio-economy.sh {status|up|wire}` yakalama proxy'sini + monitörü +
  tepsiyi + `simplicio-dev-cli` deterministik operatörünü çalıştırır ve tüm yığını raporlar.

Kurulum, üçünü de otomatik-başlatma servisleri (macOS launchd · Linux systemd · Windows Startup)
olarak `scripts/setup_simplicio.sh` ya da platformlar-arası `python3 scripts/install_services.py install`
aracılığıyla kaydeder. Kurulumdan sonra monitör + yakalama **döngüyü çağırmadan** çalışır — bkz.
`references/token-capture.md`.

### 🛠️ Yakalama motoru — tek yerel modül, her komut

[`engine/simplicio_engine.py`](../engine/simplicio_engine.py) yerel Simplicio yakalama motorudur
(yalnızca stdlib, fail-open, harici bağımlılık yok). Herhangi bir komutu
[`scripts/simplicio-engine`](../scripts/simplicio-engine) sarmalayıcısı aracılığıyla çalıştırın
(ör. `simplicio-engine doctor`):

| Komut | Ne yapar |
|---|---|
| `proxy` | şeffaf yakalama proxy'si — her modeli **gerçek** sağlayıcısına yönlendirir, sıkıştırır + ölçer + cache'ler (model değişimi yok) |
| `doctor` | proxy erişilebilirliği + ömür boyu tasarruflar |
| `cache` | yerel yanıt cache'i (`stats`/`clear`) — tekrarlanan deterministik bir istek cache'ten sunulur, LLM çağrısını atlar |
| `signatures` | bir kaynak dosyanın yalnızca-imza görünümü (gövdeler atlanmış, kodu okumak için ~%93 daha az token) |
| `semantic` | tersine çevrilebilir çıkarımsal (semantic-lite) sıkıştırma |
| `detect` | içerik-türü algılama + blok başına akıllı yönlendirme |
| `rag` | CCR bellek deposu üzerinde TF-IDF (veya `--ml` gömme) erişimi |
| `memory` | CCR compress-cache-retrieve deposu (`remember`/`recall`/`forget`/`list`/`stats`) |
| `mcp` | yerel stdio MCP sunucusu (compress / retrieve / stats araçları) |
| `init` / `wrap` | Simplicio'yu bir istemciye kaydet (Claude / Codex / Copilot / OpenClaw) · bir istemciyi yakalama yönlendirmesiyle çalıştır |
| `report` / `audit` / `capture` / `evals` | tasarruf raporu · bir ağacı sıkıştırma fırsatı için denetle · bir isteği kuru-çalıştır · sıkıştırma regresyon kapısı |

---

## 🏛️ Tasarım sütunları (ayrıntılı)

Orkestrasyon gücünü dört mekanizma taşır:

| Sütun | Odak | Yaşadığı yer |
|---|---|---|
| **DAG + boru hattı** | bağımlılığa göre paralellik, öğe başına aşamalı | `references/orchestration.md` (Adım 3 havuz + boru hattı) |
| **Worktree yalıtımı** | ağacı bozmadan paralel düzenlemeler, birleştirme-kapılı | `references/orchestration.md` |
| **Çekişmeli doğrulama** | "teslim edildi"den önce bir şüpheciler paneli | `references/quality-safety-delivery.md` · skill `simplicio-review` |
| **Bounded loop cap** | anti-infinite-loop, evidence-gated exit | `references/standing-loop-247.md` · skill `simplicio-loop` |

---

## 🚀 Kurulum & kullanım

```bash
git clone https://github.com/wesleysimplicio/simplicio-loop
cd simplicio-loop

# install for your runtime (omit <runtime> to auto-detect)
bash scripts/install.sh <runtime> [--global]        # macOS / Linux
pwsh scripts/install.ps1 <runtime> [-Global]        # Windows
# <runtime> ∈ claude codex vscode cursor antigravity kiro opencode gemini aider simplicio_agent openclaw
```

Veya, Claude Code / Cursor üzerinde, onu doğrudan en son GitHub sürümünden kurun (marketplace yok):

```bash
gh release download --repo wesleysimplicio/simplicio-loop --archive tar.gz
tar xzf simplicio-loop-*.tar.gz && cd simplicio-loop-*/
bash scripts/install.sh claude    # or: bash scripts/install.sh cursor
```

Ardından:

```
/simplicio-loop finish all the open issues
```

Tek gereksinim, PATH'te **python3**'tür (skill'ler, hook'lar ve yükleyici platformlar-arası
Python'dur). GitHub kaynakları için `git` + kimliği doğrulanmış bir `gh`. Bkz.
[`INSTALL.md`](../INSTALL.md) ve [`adapters/MATRIX.md`](../adapters/MATRIX.md).

**Before an unattended 24/7 run:** verify persistent source auth, keep the irreversible-operation human gate + secret-scan enabled, and ensure a reachable STOP/cancel path.

---

## 🔒 Güvenlik (pazarlığa kapalı)

- Her diff'i **gizli-tara**; isabet halinde engelle.
- **Geri-alınamaz-işlem insan kapısı** — force-push, geçmiş yeniden yazma, prod dağıtımı,
  veri/şema silme, toplu-dosya silme → dur ve sor. Headless + onaylayan yok → yıkıcı yeteneği
  kaldır.
- **Sadece vaat değil, zorunlu** — `hooks/action_gate.py`, yukarıdakileri (ve gizli-yüklü
  commit'leri) çalışmadan *önce* mekanik olarak engelleyen bir **fail-closed** `PreToolUse` /
  git-pre-push hook'udur. Güvenlik sözleşmesi, model onu unutsa bile geçerli kalır. `selftest`
  kural setini kanıtlar (14/14).
- **4 durumlu yürütme-öncesi karar** — optimizasyon, bir komutun risk kademesini asla yükseltemez.
- **Yüklemeden-önce-güven** — algıyı şekillendiren yapılandırma (kırpma profilleri, bastırma
  listeleri), bir insan onu inceleyip hash ile sabitleyene dek güvenilmezdir.
- **Prompt-injection sertleştirme** — öğe/PR/yorum içeriği sözleşmeyi asla geçersiz kılamaz.
- Gözetimsiz koşular için **sıkı $ acil durdurma anahtarı**; **kanıt-kapılı** tamamlama (asla sahte
  "bitti"); **fail-open** hook'lar (ajanı bir döngüye asla hapsetmez).

---

## ✅ Testler & yerel kontroller (ücretli CI yok)

İddialar yalnızca öne sürülmez, doğrulanır — ve kapı **yerel** çalışır, sıfır CI maliyetiyle:

```bash
python3 scripts/check.py            # the whole gate (audit + tests)
```

- **Test paketi** (`tests/`) — worker'ların deterministik `selftest`'leri, artı bir **döngü
  sürücüsü e2e'si** (`hooks/loop_stop.py`): döngünün ayrı çıkışlar olarak **kanıtta durduğunu**,
  **çıplak bir `<promise>`'i yok saydığını** ve **tavanda durduğunu** kanıtlar — ve kanıt
  üreticilerinin, araç zincirleri yokken **BLOCK** ettiğini (asla sahte-geçiş değil). Gate,
  içe aktarılabilir `pytest` gerektirir; çıplak Python fallback'i yoktur.
- **Claims audit** (`scripts/claims_audit.py`, fail-closed) — dokümanların referans verdiği her
  `scripts/*.py` var · genişletme noktası sayısı tüm dosyalarda uyuşuyor · her atıf yapılan worker
  komutu gerçekten çalışıyor · sevk edilen `simplicio_loop/_bundle/` skill'leri kaynakla
  **byte-özdeş**.
- **Onu bir git pre-push hook'u olarak bağlayın**, `main`'i ücretsiz dürüst tutmak için:
  ```bash
  printf '#!/bin/sh\npython3 scripts/check.py\n' > .git/hooks/pre-push && chmod +x .git/hooks/pre-push
  ```

`pip install "simplicio-loop[dev]"`, `scripts/check.py` için zorunlu `pytest` bağımlılığını kurar.

---

## ⭐ Yıldız Geçmişi

[![Star History Chart](https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-loop&type=Date)](https://star-history.com/#wesleysimplicio/simplicio-loop&Date)

---

## 📄 Lisans

MIT

<!-- simplicio-loop:github-comment-coordination:v1 -->
## 🌐 Runtime’lar arasında GitHub yorumlarıyla koordinasyon

`simplicio-loop`, Claude Code, Codex, Cursor, Gemini ve Hermes içinde aynı anda çalışabilir. GitHub issue’suna bağlı bir run, kanonik yorumda claim, plan, ilerleme, kanıt, PR ve kapatma durumlarını idempotent biçimde yayınlar. Farklı makinelerdeki agent’lar ortak yerel dosya sistemi olmadan aynı GitHub başlığında koordinasyon kurabilir.

```powershell
pwsh scripts/install.ps1 claude -Global
pwsh scripts/install.ps1 codex -Global
pwsh scripts/install.ps1 cursor -Global
pwsh scripts/install.ps1 gemini -Global
pwsh scripts/install.ps1 hermes -Global   # simplicio_agent için eski takma ad
```

Yerel kuyruk, lease, worktree, heartbeat ve kanıtlar çalışmaya devam eder; GitHub yorumları ortak koordinasyon yansıtmasıdır. Akış yalnızca GitHub içindir; Jira, Azure DevOps ve diğer tracker’lara yorum gönderilmez. GitHub kullanılamazsa loop yerel çalışır ve hatayı kaydeder, uzak onay uydurmaz. Her runtime’a GitHub erişimi verin ve aynı `source_issue` kullanın.

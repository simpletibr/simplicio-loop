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

**simplicio-loopは、どのエージェントハーネスからも通常のツールとして呼び出せる3つの決定的オペレーターを提供します。`simplicio-mapper`はリポジトリを調査し、`simplicio-dev-cli`は編集計画を正確に適用し、影響ベースのテスト選択（`scripts/impact_tests.py`）は変更が及ぶテストだけを実行します。GitHubのissueをテスト済みのPRに変えるループは、その利用者の一つです。**

<p align="center">
  <img src="../docs/assets/readme/overview-cartoon.webp" alt="8ステップのアニメーション: issue、インテーク、総括コーディネータ、スカッド、サンドボックスのワーカー、スカッドのレビュー、マージトレイン、main、Simplicio Liveカンバン" width="100%" />
</p>

<p align="center">
  <img src="../docs/assets/readme/how-it-works.webp" alt="8ステップのアニメーション: issue、インテーク、総括コーディネータ、スカッド、サンドボックスのワーカー、スカッドのレビュー、マージトレイン、main、Simplicio Liveカンバン" width="100%" />
</p>

## オペレーター

エージェントをループで回すことは、もはや難しい部分ではありません。エージェントSDKやフレームワークがすでに提供しています。確率的であってはならないのは、リポジトリの読み取り、編集の書き込み、テストの選択です。この3つのツールがその作業を担い、どれもモデルを呼び出さず、それぞれ機械可読な出力を返します。エージェント（Claude Code、Codex、Cursor、LangGraphのグラフ、シェルスクリプトなど）が判断し、これらが実行します。

| オペレーター | 役割 | どのハーネスからでも呼べる |
| --- | --- | --- |
| `simplicio-mapper`（survey） | リポジトリをローカルで（LLMなしで）走査し、全体のツリーではなく目的に対する上限付きのコンテキストパックを返します。[Docs](../packages/mapper/README.md) | `simplicio-mapper handoff . --goal "trace the authentication flow" --token-budget 1200 --json` |
| `simplicio-dev-cli`（決定的な適用） | 各`find`がちょうど1回だけ一致しなければならない find/replace の編集計画を適用し、範囲を絞った検証を実行して JSON の受領書を1つ出力します。自身の README によれば LLM は提供しません。[Docs](../packages/dev-cli/README.md) | `simplicio-dev-cli edit --root . --plan plan.json --apply --check "<tests>" --json` |
| 影響ベースのテスト選択 | `scripts/impact_tests.py`は作業ツリーを基準refとシンボル単位で比較し、変更された関数・クラス・代入に到達するテストファイルを選びます。`scripts/check.py`がこれを使うため、変更は影響しうるテストだけを実行します。[Docs](../docs/GUIDE.md#-tests--local-checks-no-paid-ci) | `python3 scripts/impact_tests.py --base origin/main --json` |

`pip install simplicio-loop` で `simplicio-mapper` と `simplicio-dev-cli` が PATH に入ります（単一の wheel、Python 3.11+）。`scripts/impact_tests.py` は標準ライブラリだけで動くスクリプトでインストール手順はありません。checkout から実行するか、自分のリポジトリにコピーしてください。

この README は節約率の数値を載せていません。計測結果は [bench/llm_ab](../bench/llm_ab/README.md) にあり、実行ごとの生の結果は `bench/llm_ab/results/` にあります（小規模な A/B、単一モデル）。そこで計測されていないことは主張しません。

## ループはその利用者の一つ

ループは参照用の利用者です。GitHub の issue を受け取り、mapper にリポジトリの地図を作らせ、サンドボックス内のプランナーに JSON の計画を書かせ、その計画を `simplicio-dev-cli` に渡し、テストを実行してから（このリポジトリでは `scripts/check.py` が影響ベースで選ばれたサブセットを実行します）PR を開きます。ループを別のハーネスに置き換えても、オペレーターは同じように動きます。

```mermaid
flowchart LR
  I["GitHub issue"] --> M["simplicio-mapper<br/>maps files, symbols, tests"]
  M -->|"map slice"| P["Planner in a sandbox<br/>claude / codex / grok / gemini<br/>plans, never writes"]
  P -->|"JSON plan"| D["simplicio-dev-cli<br/>deterministic apply"]
  D --> T["tests verify<br/>simplicio-loop turbo --apply - --verify"]
  T -->|"green"| S["secret scan"] --> PR["PR with evidence"]
  T -.->|"2 failures"| E["escalate the model role"] -.-> P
```

## インストール

Python 3.11+、`git`、GitHub issue用に認証済みの`gh`が必要です。

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## 使い方

**Claude CodeまたはVS Codeで:**

```text
/simplicio-loop finish all the open issues
```

**24時間365日のwatcherとして**（`simpletibr/simplicio-*`リポジトリを監視してPRを開くサービス）:

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

詳細: [docs/WATCHER_247.md](../docs/WATCHER_247.md)。

```mermaid
flowchart LR
  R["repo opts in<br/>.simplicio-loop/loop.toml<br/>enabled = true"] --> L["issue opts in<br/>label loop:auto<br/>owner / member / collaborator"]
  L --> W["worker loop"] --> PR["PR opened"]
  PR -.->|"auto-merge off by default"| H["squad / human merges"]
```

## 仕組み

<p align="center">
  <img src="../docs/assets/readme/worker-loop.webp" alt="ワーカーループ: サンドボックスで計画、適用と検証、1回の失敗、次のモデル役割へのエスカレーション、シークレットスキャン、PR、スカッドのレビュー" width="100%" />
</p>

```mermaid
flowchart LR
  H["Haiku<br/>mechanical, 1 module"] -->|"2 failures"| S["Sonnet<br/>integration, security"] -->|"2 failures"| O["Opus / Fable<br/>replan only, never executes"]
```

<p align="center">
  <img src="../docs/assets/readme/merge-train.webp" alt="マージトレイン: 4つのPRを1回テスト、赤、二分探索でCを特定、その後A、B、Dをマージ" width="100%" />
</p>

```mermaid
flowchart LR
  A["PR A ✓"] & B["PR B ✓"] & C["PR C ✓"] & D["PR D ✓"] --> G{"test the batch once"}
  G -->|"green"| M["merge all into main"]
  G -->|"red"| X["bisect"] --> BAD["PR C out, back to its squad"]
  X --> OK["A, B and D merge"]
```

<p align="center">
  <img src="../docs/assets/readme/squads.webp" alt="スカッドの組織図: 総括コーディネータ、スカッドごとのコーディネータ、各最大4人のワーカー" width="100%" />
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

## 50の拡張ポイント

```mermaid
pie showData title Extension points in the 24/7 path (of 50)
  "Wired" : 19
  "Partial" : 29
  "Absent" : 2
```

[docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md) · [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509)

## ランタイム

- **34 `wired`** アダプターは `adapters/` にコードとホストテストを持ちます。カタログのインストール対象ホストすべてが対象で、Claude Code、Codex、Cursor、Grok、Kiro、VS Code、20 の `AGENTS.md` ホスト、ウェーブ B の 8 ホストを含みます。
- **0 `listed`** ホスト: カタログの各ホストにはアダプターのコードがあります。DeepSeek はモデルプロバイダーであり、ホストではありません。
- 上のオペレーターは普通のコマンドなので、`wired` かどうかに関係なく、どのハーネスからでも動きます。ホストごとの状態：[adapters/MATRIX.md](../adapters/MATRIX.md) と [simplicio_loop/_catalog/harnesses.json](../simplicio_loop/_catalog/harnesses.json)。

## さらに詳しく

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **その他すべて: [docs/GUIDE.md](../docs/GUIDE.md)**（skills、runtimes、ループ、トークン節約、安全性、テスト、英語）

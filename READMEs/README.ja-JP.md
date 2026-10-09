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

**simplicio-loopは、GitHubのissueをテスト済みのPRに変えます。リポジトリをマップし、AIが計画し、決定的エディタが適用し、テストが検証し、スカッドがレビューします。**

<p align="center">
  <img src="../docs/assets/readme/how-it-works.gif" alt="8ステップのアニメーション: issue、インテーク、総括コーディネータ、スカッド、サンドボックスのワーカー、スカッドのレビュー、マージトレイン、main、Simplicio Liveカンバン" width="920" />
</p>

## できること

3つのオペレータ: `simplicio-mapper`（マップ）、プランナーモデル（計画）、`simplicio-dev-cli`（決定的な適用）。

- **まずマップする:** `simplicio-mapper`がリポジトリ（ファイル、シンボル、テスト）をプロジェクトマップにまとめ、プランナーは必要な部分だけを受け取ります。
- **計画するだけで、書き込まない:** AI（claude、codex、grok、geminiなどのexec CLI）がサンドボックス内で各変更を計画し、ファイルを編集するのは決定的な`dev-cli`だけです。
- **PRを開く前に証明する:** `turbo --apply - --verify`がテストを実行し、push前にシークレットスキャンが走ります。
- **スカッドがレビューしてまとめてマージする**（作業中: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)、[#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)、[#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)）。現在はwatcherはオープンなPRで止まります。

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

- **リポジトリごとのオプトイン:** `.simplicio/loop.toml`を追加して`enabled = true`を設定します。
- **issueごとのオプトイン:** 信頼できる作成者（owner、member、collaborator）が付けた`loop:auto`ラベル。
- **自動マージはオフです。** watcherはPRを開くだけです。`SIMPLICIO_247_AUTO_MERGE=1`は作業中です（[#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)）。

詳細: [docs/WATCHER_247.md](../docs/WATCHER_247.md)。

## 仕組み

**ワーカーループ**（現在`main`で動作）: `simplicio-mapper`がリポジトリをマップ → プランナー（exec CLI、サンドボックス内）がマップの一部を受け取って計画を作成 → `simplicio-dev-cli`が適用（`turbo --apply - --verify`） → テストで検証（2回失敗するとモデルの役割を格上げ） → シークレットスキャン → PR。スカッドのレビューとマージトレインは作業中です（[#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)、[#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)）。

<p align="center">
  <img src="../docs/assets/readme/worker-loop.gif" alt="ワーカーループ: サンドボックスで計画、適用と検証、1回の失敗、次のモデル役割へのエスカレーション、シークレットスキャン、PR、スカッドのレビュー" width="920" />
</p>

**マージトレイン**（作業中: [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)）: 承認済みのPRをまとめて1回だけテストし、赤になったら二分探索で問題のPRを特定して残りをマージします。

<p align="center">
  <img src="../docs/assets/readme/merge-train.gif" alt="マージトレイン: 4つのPRを1回テスト、赤、二分探索でCを特定、その後A、B、Dをマージ" width="920" />
</p>

**スカッド**（作業中: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)）: 総括コーディネータ1人、スカッドごとにコーディネータ1人、各スカッドに最大4人のワーカー。理由: [コーディネータ1人対スカッド](../docs/assets/readme/agents-before-after-cartoon.webp)。

<p align="center">
  <img src="../docs/assets/readme/squads-cartoon.webp" alt="スカッドの組織図: 総括コーディネータ、スカッドごとのコーディネータ、各最大4人のワーカー" width="920" />
</p>

<p align="center">
  <img src="../docs/assets/readme/overview-cartoon.webp" alt="フロー全体: issue、インテーク、総括コーディネータ、スカッド、サンドボックスのワーカー、dev-cli、スカッドの承認、マージトレイン、main、Simplicio Liveカンバン" width="920" />
</p>

## 50の拡張ポイント

24時間365日のサービス経路は50のうち11を接続済み（24は一部、15は未実装）: [docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md)。残りを接続する計画は[#1509](https://github.com/simpletibr/simplicio-loop/issues/1509)です。

## さらに詳しく

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **その他すべて: [docs/GUIDE.md](../docs/GUIDE.md)**（skills、runtimes、ループ、トークン節約、安全性、テスト、英語）

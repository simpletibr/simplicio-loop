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

**simplicio-loop zamienia issues z GitHuba w przetestowane PR-y: mapuje repo, AI planuje, deterministyczny edytor stosuje zmiany, testy weryfikują, squady robią review.**

<p align="center">
  <img src="../docs/assets/readme/how-it-works.gif" alt="Animowany przepływ w 8 krokach: issues, intake, główny koordynator, squady, workery (mapper, plan, dev-cli), review squadu, merge train, main i kanban Simplicio Live" width="920" />
</p>

## Co robi

Trzy operatory: `simplicio-mapper` (mapa), model planujący (plan), `simplicio-dev-cli` (deterministyczne stosowanie zmian).

- **Najpierw mapuje:** `simplicio-mapper` mapuje repo (pliki, symbole, testy) do mapy projektu, a planista dostaje tylko potrzebny fragment.
- **Planuje, nigdy nie pisze:** AI (exec CLI, np. claude, codex, grok lub gemini) planuje każdą zmianę w sandboxie; pliki edytuje wyłącznie deterministyczny `dev-cli`.
- **Dowodzi, zanim otworzy PR:** `turbo --apply - --verify` uruchamia Twoje testy, a przed pushem działa skan sekretów.
- **Squady robią review i mergują partiami** (w toku: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504), [#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)). Dziś watcher zatrzymuje się na otwartym PR.

## Instalacja

Wymaga Pythona 3.11+, `git` oraz uwierzytelnionego `gh` dla issues na GitHubie.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## Użycie

**W Claude Code lub VS Code:**

```text
/simplicio-loop finish all the open issues
```

**Jako watcher 24/7** (usługa, która obserwuje repo `simpletibr/simplicio-*` i otwiera PR-y):

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

- **Opt-in per repo:** dodaj `.simplicio/loop.toml` z `enabled = true`.
- **Opt-in per issue:** etykieta `loop:auto` nadana przez zaufanego autora (owner, member lub collaborator).
- **Auto-merge jest wyłączony.** Watcher tylko otwiera PR-y; `SIMPLICIO_247_AUTO_MERGE=1` jest w toku ([#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)).

Szczegóły: [docs/WATCHER_247.md](../docs/WATCHER_247.md).

## Jak to działa

**Pętla workera** (dziś na `main`): `simplicio-mapper` mapuje repo → planista (exec CLI, w sandboxie) dostaje fragment mapy i pisze plan → `simplicio-dev-cli` go stosuje (`turbo --apply - --verify`) → testy weryfikują (dwie porażki podnoszą rolę modelu) → skan sekretów → PR. Review squadu i merge train są w toku ([#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)).

<p align="center">
  <img src="../docs/assets/readme/worker-loop.gif" alt="Pętla workera: mapper mapuje repo, planowanie w sandboxie, zastosowanie i weryfikacja, porażka, eskalacja do kolejnej roli modelu, skan sekretów, PR, review squadu" width="920" />
</p>

**Merge train** (w toku: [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)): zatwierdzone PR-y są testowane raz jako partia; przy czerwonym wyniku bisekcja znajduje wadliwy PR, a reszta jest mergowana.

<p align="center">
  <img src="../docs/assets/readme/merge-train.gif" alt="Merge train: 4 PR-y przetestowane raz, czerwono, bisekcja izoluje C, potem A, B i D są mergowane" width="920" />
</p>

**Squady** (w toku: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)): jeden główny koordynator, po jednym koordynatorze na squad, do 4 workerów w każdym. Dlaczego: [jeden koordynator kontra squady](../docs/assets/readme/agents-before-after-cartoon.webp).

<p align="center">
  <img src="../docs/assets/readme/squads-cartoon.webp" alt="Schemat organizacyjny squadów: główny koordynator, koordynator na squad i do 4 workerów w każdym" width="920" />
</p>

<p align="center">
  <img src="../docs/assets/readme/overview-cartoon.webp" alt="Cały przepływ: issues, intake, główny koordynator, squady, workery w sandboxie, dev-cli, zatwierdzenie squadu, merge train, main i kanban Simplicio Live" width="920" />
</p>

## 50 punktów rozszerzenia

Tor usługi 24/7 podłącza 11 z 50 (24 częściowo, 15 brak): [docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md). Plan podłączenia reszty to [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509).

## Dowiedz się więcej

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **Wszystko inne: [docs/GUIDE.md](../docs/GUIDE.md)** (skills, runtimes, pętla, oszczędność tokenów, bezpieczeństwo, testy; po angielsku)

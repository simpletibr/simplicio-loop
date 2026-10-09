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

**simplicio-loop trasforma le issue di GitHub in PR testate: mappa il repo, un'IA pianifica, un editor deterministico applica, i test verificano e gli squad revisionano.**

<p align="center">
  <img src="../docs/assets/readme/how-it-works.gif" alt="Flusso animato in 8 passi: issue, intake, coordinatore generale, squad, worker in sandbox, revisione dello squad, merge train, main e il kanban Simplicio Live" width="920" />
</p>

## Cosa fa

Tre operatori: `simplicio-mapper` (mappa), il modello pianificatore (piano), `simplicio-dev-cli` (applicazione deterministica).

- **Mappa per prima cosa:** `simplicio-mapper` mappa il repo (file, simboli, test) in una mappa del progetto, e il pianificatore riceve solo la porzione che gli serve.
- **Pianifica, non scrive mai:** un'IA (una CLI exec come claude, codex, grok o gemini) pianifica ogni modifica dentro una sandbox; solo il `dev-cli` deterministico modifica i file.
- **Dimostra prima di aprire la PR:** `turbo --apply - --verify` esegue i tuoi test e prima del push gira una scansione dei segreti.
- **Gli squad revisionano e fanno il merge a lotti** (in corso: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504), [#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)). Oggi il watcher si ferma alla PR aperta.

## Installazione

Richiede Python 3.11+, `git` e un `gh` autenticato per le issue di GitHub.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## Uso

**In Claude Code o VS Code:**

```text
/simplicio-loop finish all the open issues
```

**Come watcher 24/7** (un servizio che osserva i repo `simpletibr/simplicio-*` e apre PR):

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

- **Opt-in per repo:** aggiungi `.simplicio/loop.toml` con `enabled = true`.
- **Opt-in per issue:** l'etichetta `loop:auto`, messa da un autore fidato (owner, member o collaborator).
- **L'auto-merge è disattivato.** Il watcher apre solo PR; `SIMPLICIO_247_AUTO_MERGE=1` è in corso ([#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)).

Dettagli: [docs/WATCHER_247.md](../docs/WATCHER_247.md).

## Come funziona

**Il loop del worker** (oggi su `main`): `simplicio-mapper` mappa il repo → il pianificatore (una CLI exec, nella sandbox) riceve la porzione della mappa e scrive un piano → `simplicio-dev-cli` lo applica (`turbo --apply - --verify`) → i test verificano (due fallimenti fanno salire il ruolo del modello) → scansione dei segreti → PR. La revisione dello squad e il merge train sono in corso ([#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)).

<p align="center">
  <img src="../docs/assets/readme/worker-loop.gif" alt="Loop del worker: pianifica nella sandbox, applica e verifica, un fallimento, escalation al ruolo di modello successivo, scansione dei segreti, PR, revisione dello squad" width="920" />
</p>

**Il merge train** (in corso: [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)): le PR approvate vengono testate una volta come lotto; se va in rosso, fa una bisezione fino alla PR difettosa e fa il merge delle altre.

<p align="center">
  <img src="../docs/assets/readme/merge-train.gif" alt="Merge train: 4 PR testate una volta, rosso, la bisezione isola C, poi A, B e D vengono mergiate" width="920" />
</p>

**Gli squad** (in corso: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)): un coordinatore generale, un coordinatore per squad, fino a 4 worker ciascuno. Perché: [un coordinatore contro gli squad](../docs/assets/readme/agents-before-after-cartoon.webp).

<p align="center">
  <img src="../docs/assets/readme/squads-cartoon.webp" alt="Organigramma degli squad: un coordinatore generale, un coordinatore per squad e fino a 4 worker ciascuno" width="920" />
</p>

<p align="center">
  <img src="../docs/assets/readme/overview-cartoon.webp" alt="L'intero flusso: issue, intake, coordinatore generale, squad, worker in sandbox, dev-cli, approvazione dello squad, merge train, main e il kanban Simplicio Live" width="920" />
</p>

## I 50 punti di estensione

Il percorso del servizio 24/7 ne collega 11 su 50 (24 parziali, 15 assenti): [docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md). Il piano per collegare il resto è la [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509).

## Per saperne di più

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **Tutto il resto: [docs/GUIDE.md](../docs/GUIDE.md)** (skill, runtime, il loop, risparmio di token, sicurezza, test; in inglese)

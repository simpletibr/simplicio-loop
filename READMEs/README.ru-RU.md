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

**simplicio-loop превращает issue в GitHub в протестированные PR: он картирует репозиторий, ИИ планирует, детерминированный редактор применяет, тесты проверяют, сквады ревьюят.**

<p align="center">
  <img src="../docs/assets/readme/how-it-works.gif" alt="Анимированный поток из 8 шагов: issue, intake, общий координатор, сквады, воркеры (mapper, план, dev-cli), ревью сквада, merge train, main и канбан Simplicio Live" width="100%" />
</p>

## Что он делает

Три оператора: `simplicio-mapper` (карта), модель-планировщик (план), `simplicio-dev-cli` (детерминированное применение).

- **Сначала картирует:** `simplicio-mapper` превращает репозиторий (файлы, символы, тесты) в карту проекта, и планировщик получает только нужный фрагмент.
- **Планирует, никогда не пишет:** ИИ (exec CLI, например claude, codex, grok или gemini) планирует каждое изменение в песочнице; файлы правит только детерминированный `dev-cli`.
- **Доказывает до открытия PR:** `turbo --apply - --verify` запускает ваши тесты, а перед push идёт сканирование секретов.
- **Сквады ревьюят и мёрджат пачками** (в работе: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504), [#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)). Сейчас watcher останавливается на открытом PR.

## Установка

Нужны Python 3.11+, `git` и авторизованный `gh` для issue в GitHub.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## Использование

**В Claude Code или VS Code:**

```text
/simplicio-loop finish all the open issues
```

**Как watcher 24/7** (сервис, который следит за репозиториями `simpletibr/simplicio-*` и открывает PR):

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

- **Opt-in на репозиторий:** добавьте `.simplicio/loop.toml` с `enabled = true`.
- **Opt-in на issue:** метка `loop:auto` от доверенного автора (owner, member или collaborator).
- **Авто-мёрдж выключен.** Watcher только открывает PR; `SIMPLICIO_247_AUTO_MERGE=1` в работе ([#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)).

Подробнее: [docs/WATCHER_247.md](../docs/WATCHER_247.md).

## Как это работает

**Цикл воркера** (сейчас в `main`): `simplicio-mapper` картирует репозиторий → планировщик (exec CLI, в песочнице) получает фрагмент карты и пишет план → `simplicio-dev-cli` применяет его (`turbo --apply - --verify`) → тесты проверяют (два сбоя повышают роль модели) → сканирование секретов → PR. Ревью сквада и merge train в работе ([#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)).

<p align="center">
  <img src="../docs/assets/readme/worker-loop.gif" alt="Цикл воркера: mapper картирует репозиторий, план в песочнице, применение и проверка, сбой, повышение до следующей роли модели, сканирование секретов, PR, ревью сквада" width="920" />
</p>

**Merge train** (в работе: [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)): одобренные PR тестируются один раз пачкой; при красном бисекция находит плохой PR, а остальные мёрджатся.

<p align="center">
  <img src="../docs/assets/readme/merge-train.gif" alt="Merge train: 4 PR протестированы один раз, красный, бисекция изолирует C, затем A, B и D мёрджатся" width="920" />
</p>

**Сквады** (в работе: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)): общий координатор, по координатору на сквад, до 4 воркеров в каждом. Почему: [один координатор против сквадов](../docs/assets/readme/agents-before-after-cartoon.webp).

<p align="center">
  <img src="../docs/assets/readme/squads.gif" alt="Оргструктура сквадов: общий координатор, координатор на сквад и до 4 воркеров в каждом" width="920" />
</p>


## 50 точек расширения

Путь 24/7-сервиса подключает 11 из 50 (24 частично, 15 отсутствуют): [docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md). План подключения остальных — [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509).

## Подробнее

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **Всё остальное: [docs/GUIDE.md](../docs/GUIDE.md)** (skills, runtimes, цикл, экономия токенов, безопасность, тесты; на английском)

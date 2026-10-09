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

**يحوّل simplicio-loop مشكلات GitHub إلى طلبات دمج (PR) مختبرة: يرسم خارطة للمستودع، ويخطط ذكاء اصطناعي، ويطبق محرر حتمي، وتتحقق الاختبارات، وتراجع الفرق (squads).**

<p align="center">
  <img src="../docs/assets/readme/how-it-works.gif" alt="مسار متحرك من 8 خطوات: المشكلات، الاستقبال، المنسق العام، الفرق، العمّال (mapper، خطة، dev-cli)، مراجعة الفريق، merge train، main ولوحة Simplicio Live" width="100%" />
</p>

## ماذا يفعل

ثلاثة مشغّلات: `simplicio-mapper` (الخريطة)، نموذج التخطيط (الخطة)، `simplicio-dev-cli` (التطبيق الحتمي).

- **يرسم الخارطة أولاً:** يحوّل `simplicio-mapper` المستودع (الملفات والرموز والاختبارات) إلى خارطة مشروع، ولا يحصل المخطط إلا على الجزء الذي يحتاجه.
- **يخطط ولا يكتب أبداً:** ذكاء اصطناعي (أداة exec CLI مثل claude أو codex أو grok أو gemini) يخطط كل تغيير داخل sandbox؛ ولا يعدّل الملفات إلا `dev-cli` الحتمي.
- **يثبت قبل فتح الـ PR:** يشغّل `turbo --apply - --verify` اختباراتك، ويعمل فحص الأسرار قبل الدفع.
- **الفرق تراجع وتدمج دفعات** (قيد العمل: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)، [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)، [#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)). اليوم يتوقف الـ watcher عند PR مفتوح.

## التثبيت

يتطلب Python 3.11+ و`git` و`gh` موثّقاً لمشكلات GitHub.

```bash
pip install simplicio-loop
simplicio-loop install            # skills + hooks in this project (--global: user-wide, --host <name>: another host)
simplicio-loop doctor             # check the installed stack
```

## الاستخدام

**في Claude Code أو VS Code:**

```text
/simplicio-loop finish all the open issues
```

**كـ watcher على مدار الساعة** (خدمة تراقب مستودعات `simpletibr/simplicio-*` وتفتح طلبات PR):

```bash
simplicio-loop watch247 --once --dry-run          # one simulated tick, changes nothing
simplicio-loop watch247 login-check               # are the exec CLIs logged in?
# from a repo checkout, as root, after creating the non-root user simplicio-loop:
sudo cp packaging/systemd/simplicio-loop-247.service /etc/systemd/system/
sudo cp packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env   # edit it, then chmod 600
sudo systemctl enable --now simplicio-loop-247
```

- **الموافقة لكل مستودع (opt-in):** أضف `.simplicio/loop.toml` مع `enabled = true`.
- **الموافقة لكل مشكلة (opt-in):** الوسم `loop:auto` من مؤلف موثوق (owner أو member أو collaborator).
- **الدمج التلقائي معطّل.** الـ watcher يفتح طلبات PR فقط؛ `SIMPLICIO_247_AUTO_MERGE=1` قيد العمل ([#1505](https://github.com/simpletibr/simplicio-loop/issues/1505)).

التفاصيل: [docs/WATCHER_247.md](../docs/WATCHER_247.md).

## كيف يعمل

**حلقة العامل** (على `main` اليوم): يرسم `simplicio-mapper` خارطة المستودع ← يحصل المخطط (exec CLI داخل sandbox) على جزء الخارطة ويكتب خطة ← يطبقها `simplicio-dev-cli` (`turbo --apply - --verify`) ← تتحقق الاختبارات (فشلان يرفعان دور النموذج) ← فحص الأسرار ← PR. مراجعة الفريق وـ merge train قيد العمل ([#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)، [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)).

<p align="center">
  <img src="../docs/assets/readme/worker-loop.gif" alt="حلقة العامل: mapper يرسم خارطة المستودع، تخطيط في sandbox، تطبيق وتحقق، فشل، تصعيد إلى دور النموذج التالي، فحص الأسرار، PR، مراجعة الفريق" width="920" />
</p>

**الـ merge train** (قيد العمل: [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)): تُختبر طلبات PR المعتمدة مرة واحدة كدفعة؛ عند الفشل يجري بحثاً ثنائياً لإيجاد الـ PR المعيب ويدمج الباقي.

<p align="center">
  <img src="../docs/assets/readme/merge-train.gif" alt="Merge train: 4 طلبات PR اختُبرت مرة واحدة، أحمر، البحث الثنائي يعزل C، ثم دُمجت A وB وD" width="920" />
</p>

**الفرق (squads)** (قيد العمل: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)): منسق عام واحد، ومنسق لكل فريق، وحتى 4 عمّال في كل فريق. لماذا: [منسق واحد مقابل فرق](../docs/assets/readme/agents-before-after-cartoon.webp).

<p align="center">
  <img src="../docs/assets/readme/squads.gif" alt="الهيكل التنظيمي للفرق: منسق عام، ومنسق لكل فريق، وحتى 4 عمّال في كل فريق" width="920" />
</p>


## نقاط التوسعة الخمسون

مسار خدمة 24/7 يوصّل 11 من 50 (24 جزئياً و 15 غائبة): [docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md). خطة توصيل الباقي هي [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509).

## المزيد

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **كل ما عدا ذلك: [docs/GUIDE.md](../docs/GUIDE.md)** (skills، runtimes، الحلقة، توفير الرموز، الأمان، الاختبارات؛ بالإنجليزية)

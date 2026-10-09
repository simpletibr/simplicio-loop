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

**simplicio-loop GitHub issues को टेस्ट किए गए PR में बदलता है: यह repo को map करता है, AI योजना बनाता है, निर्धारणात्मक एडिटर लागू करता है, टेस्ट सत्यापित करते हैं, squads रिव्यू करते हैं।**

<p align="center">
  <img src="../docs/assets/readme/how-it-works.gif" alt="8 चरणों का एनिमेटेड फ्लो: issues, intake, जनरल कोऑर्डिनेटर, squads, workers (mapper, plan, dev-cli), squad review, merge train, main और Simplicio Live kanban" width="920" />
</p>

## यह क्या करता है

तीन ऑपरेटर: `simplicio-mapper` (map), planner मॉडल (plan), `simplicio-dev-cli` (निर्धारणात्मक apply)।

- **पहले map करता है:** `simplicio-mapper` repo (files, symbols, tests) को project map में बदलता है, और planner को सिर्फ़ वही हिस्सा मिलता है जिसकी उसे ज़रूरत है।
- **योजना बनाता है, लिखता कभी नहीं:** एक AI (claude, codex, grok या gemini जैसा exec CLI) sandbox के अंदर हर बदलाव की योजना बनाता है; फ़ाइलें सिर्फ़ निर्धारणात्मक `dev-cli` एडिट करता है।
- **PR खोलने से पहले सिद्ध करता है:** `turbo --apply - --verify` आपके टेस्ट चलाता है, और push से पहले secret scan चलता है।
- **Squads रिव्यू करते हैं और batch में merge करते हैं** (जारी: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504), [#1505](https://github.com/simpletibr/simplicio-loop/issues/1505))। आज watcher खुले PR पर रुक जाता है।

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

- **प्रति repo opt-in:** `.simplicio/loop.toml` जोड़ें और `enabled = true` रखें।
- **प्रति issue opt-in:** भरोसेमंद लेखक (owner, member या collaborator) द्वारा लगाया गया `loop:auto` लेबल।
- **Auto-merge बंद है।** watcher सिर्फ़ PR खोलता है; `SIMPLICIO_247_AUTO_MERGE=1` जारी है ([#1505](https://github.com/simpletibr/simplicio-loop/issues/1505))।

विवरण: [docs/WATCHER_247.md](../docs/WATCHER_247.md)।

## यह कैसे काम करता है

**Worker loop** (आज `main` पर): `simplicio-mapper` repo को map करता है → planner (exec CLI, sandbox में) को map का हिस्सा मिलता है और वह plan लिखता है → `simplicio-dev-cli` उसे apply करता है (`turbo --apply - --verify`) → टेस्ट सत्यापित करते हैं (दो विफलताएँ model role बढ़ाती हैं) → secret scan → PR। Squad review और merge train जारी हैं ([#1502](https://github.com/simpletibr/simplicio-loop/issues/1502), [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504))।

<p align="center">
  <img src="../docs/assets/readme/worker-loop.gif" alt="Worker loop: mapper repo को map करता है, sandbox में plan, apply और verify, एक विफलता, अगले model role पर escalation, secret scan, PR, squad review" width="920" />
</p>

**Merge train** (जारी: [#1504](https://github.com/simpletibr/simplicio-loop/issues/1504)): अप्रूव्ड PR को batch में एक बार टेस्ट किया जाता है; लाल होने पर bisect से खराब PR मिलता है और बाकी merge हो जाते हैं।

<p align="center">
  <img src="../docs/assets/readme/merge-train.gif" alt="Merge train: 4 PR एक बार टेस्ट, लाल, bisect ने C को अलग किया, फिर A, B और D merge हुए" width="920" />
</p>

**Squads** (जारी: [#1502](https://github.com/simpletibr/simplicio-loop/issues/1502)): एक जनरल कोऑर्डिनेटर, हर squad का एक कोऑर्डिनेटर, हर squad में 4 workers तक। क्यों: [एक कोऑर्डिनेटर बनाम squads](../docs/assets/readme/agents-before-after-cartoon.webp)।

<p align="center">
  <img src="../docs/assets/readme/squads-cartoon.webp" alt="Squads का संगठन चार्ट: एक जनरल कोऑर्डिनेटर, हर squad का कोऑर्डिनेटर और हर squad में 4 workers तक" width="920" />
</p>

<p align="center">
  <img src="../docs/assets/readme/overview-cartoon.webp" alt="पूरा फ्लो: issues, intake, जनरल कोऑर्डिनेटर, squads, sandbox में workers, dev-cli, squad approval, merge train, main और Simplicio Live kanban" width="920" />
</p>

## 50 एक्सटेंशन पॉइंट

24/7 सेवा पाथ 50 में से 11 को जोड़ता है (24 आंशिक, 15 अनुपस्थित): [docs/EXTENSION_POINTS_SERVICE.md](../docs/EXTENSION_POINTS_SERVICE.md)। बाकी को जोड़ने की योजना [#1509](https://github.com/simpletibr/simplicio-loop/issues/1509) है।

## और जानें

- [INSTALL.md](../INSTALL.md) · [docs/CLI_COMMANDS.md](../docs/CLI_COMMANDS.md) · [docs/WATCHER_247.md](../docs/WATCHER_247.md)
- [docs/MODEL_ROLES.md](../docs/MODEL_ROLES.md) · [docs/DASHBOARD.md](../docs/DASHBOARD.md) · [CHANGELOG.md](../CHANGELOG.md)
- **बाकी सब कुछ: [docs/GUIDE.md](../docs/GUIDE.md)** (skills, runtimes, loop, token बचत, सुरक्षा, टेस्ट; अंग्रेज़ी में)

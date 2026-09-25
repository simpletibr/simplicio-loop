<h1 align="center" dir="rtl">simplicio-cli</h1>

<p align="center" dir="rtl">
  <strong>הופך משימה בשורה אחת לשינוי קוד מאומת: הקשר mapper, חוזה שש שכבות, diff, בדיקה והוכחה.</strong><br />
  <em>הפקודות נשארות באנגלית כדי שאפשר יהיה להעתיק אותן במדויק.</em>
</p>

<p align="center">
<a href="https://github.com/wesleysimplicio/simplicio-dev-cli/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/wesleysimplicio/simplicio-dev-cli?style=flat-square" /></a>
<a href="https://pypi.org/project/simplicio-cli/"><img alt="PyPI" src="https://img.shields.io/pypi/v/simplicio-cli.svg?style=flat-square" /></a>
<a href="https://pypi.org/project/simplicio-cli/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/simplicio-cli.svg?style=flat-square" /></a>
<a href="../LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-yellow?style=flat-square" /></a>
</p>

<p align="center">
<a href="../README.md">English</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.es-ES.md">Español</a> | <a href="README.ja-JP.md">日本語</a> | <a href="README.ko-KR.md">한국어</a> | <a href="README.zh-CN.md">简体中文</a> | <a href="README.it-IT.md">Italiano</a> | <a href="README.fr-FR.md">Français</a> | <a href="README.ru-RU.md">Русский</a> | <a href="README.pl-PL.md">Polski</a> | <a href="README.hi-IN.md">हिन्दी</a> | <a href="README.ar-SA.md">العربية</a> | <a href="README.he-IL.md">עברית</a> | <a href="README.ms-MY.md">Bahasa Melayu</a> | <a href="README.id-ID.md">Bahasa Indonesia</a>
</p>

<p align="center">
  <img src="../output/imagegen/simplicio-cli-readme-hero-web.png" alt="צינור הביצוע של simplicio-dev-cli" width="860" />
</p>
<p align="center">
  <img src="../output/imagegen/simplicio-cli-proof-receipt.png" alt="diff, בדיקות ואישור אימות" width="760" />
</p>

---

## בקצרה

הופך משימה בשורה אחת לשינוי קוד מאומת: הקשר mapper, חוזה שש שכבות, diff, בדיקה והוכחה.

## DNA הפרויקט

העמוד המקומי שומר על הדרך המהירה. המדריך הטכני המשוחזר נמצא ב-README הראשי כדי לשמור על הקול המקורי ופרטי ההפעלה של הפרויקט.

- Full restored guide: [../README.md](../README.md)

## התחלה מהירה

```bash
pip install -U simplicio-cli
simplicio-py detect "hide the Delete button for non-admins"
simplicio-py task "hide the Delete button for non-admins"
```

## מה זה עושה

- מקבל משימה ממוקדת מה-runtime, מסוכן או מהממשק של ה-CLI.
- טוען את ההקשר של `simplicio-mapper` ואת התקדים הרלוונטי לפני עריכה.
- מחיל diff מוגבל, מריץ בדיקות ומתעד קבלה ניתנת לבדיקה של האימות.
- משאיר את התזמור, בחירת המודל ומצב הלולאה המתמשך לשכבות Simplicio שמסביב.

## למה ה-README הזה נבנה למשיכת תשומת לב

- הבטחה ברורה במסך הראשון
- קישורי שפה לפני התקנה
- badges ותמונת hero לאמון
- quick start שניתן להעתקה
- הוכחות לפני פירוט ארוך
- גרף כוכבים כהוכחה חברתית

## איך זה עובד

```mermaid
flowchart LR
  task(["bounded task"])
  subgraph install["SIMPLICIO-DEV-CLI 0.16.1 INSTALL SURFACE"]
    mapper["simplicio-mapper 0.23.1<br/>context + precedent"]
    operator["focused operator"]
    diff["bounded diff"]
    tests["tests + gates"]
  end
  subgraph proof["PROOF"]
    receipt[("evidence receipt")]
  end
  task --> mapper --> operator
  operator --> diff
  operator --> tests
  diff --> receipt
  tests --> receipt
  classDef input fill:#13233f,stroke:#79d8ff,color:#ffffff
  classDef action fill:#102e2a,stroke:#48e0ae,color:#ffffff
  classDef proofNode fill:#3a244e,stroke:#ffb86b,color:#ffffff
  class task input
  class mapper,operator,diff,tests action
  class receipt proofNode
```

## הוכחות ואימות

- Benchmark docs compare plain prompting vs the Simplicio contract on real code tasks.
- Package metadata tests pin ecosystem dependency floors.
- The CLI is the executor layer used by SendSprint and SimplicioCode flows.

## אקוסיסטם Simplicio

- [simplicio-mapper](https://github.com/wesleysimplicio/simplicio-mapper) supplies repo context before interpretation.
- [simplicio-cli](https://github.com/wesleysimplicio/simplicio-dev-cli) executes focused code tasks with verification.
- [simplicio-prompt](https://github.com/wesleysimplicio/simplicio-prompt) provides fan-out and consensus runtime patterns.
- [simplicio-sprint](https://github.com/wesleysimplicio/simplicio-sprint) turns cards into draft PR delivery loops.
- [Simplicio Agent](https://github.com/wesleysimplicio/simplicio-agent) is the desktop/CLI host that runs this ecosystem's skills and tools end to end.

## תקן התיעוד

- [docs/PYTHON_PACKAGE_INTERDEPENDENCE.md](../docs/PYTHON_PACKAGE_INTERDEPENDENCE.md)
- [docs/LLM_USAGE_POLICY.md](../docs/LLM_USAGE_POLICY.md)
- [docs/readme-globalization-standard.md](../docs/readme-globalization-standard.md)

## היסטוריית כוכבים

<a href="https://www.star-history.com/#wesleysimplicio/simplicio-dev-cli&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-dev-cli&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-dev-cli&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-dev-cli&type=Date" />
  </picture>
</a>

## רישיון

MIT. See [LICENSE](../LICENSE).

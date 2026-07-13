<div dir="rtl">

# simplicio-mapper

> הפכו מאגר לקוד להקשר תחום, ניתן לשאילתה ואמין עבור אנשים וסוכני AI.

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/)

[README קנוני וכל השפות](../README.md)

<p align="center"><img src="../assets/llm-project-mapper-hero.png" alt="מאגר שהופך להקשר תחום המבוסס על ראיות" width="100%"></p>

`simplicio-mapper` הופך בסיס קוד לארטיפקטים עם גרסאות תחת `.simplicio/`: ארכיטקטורה, סמלים, זרימות, כללים, בדיקות וחבילות הקשר המכוונות למשימה. זהו מנוע המיפוי של אקוסיסטם Simplicio; הידע על המאגר קטן מספיק לבדיקה ומפורש מספיק לביקורת.

## התחלה מהירה

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "עקוב אחר זרימת האימות" --token-budget 1200 --json
```

## מה מבדיל אותו

- **אחזור תחום:** `handoff` ו־`orient` מדווחים על רלוונטיות, כיסוי, תקציב טוקנים, קנסות ונאמנות, במקום להזרים בשקט את כל המאגר ל־prompt.
- **הקשר שמודע לשינוי:** `sync`, `history`, `diff` ו־`delta` שומרים את ContextGraph לאורך שינויים ומפגשים.
- **חוזי ראיות:** סכמות ציבוריות, אימות, תגי ביטחון, קבלות התנהגותיות ותעודות מפרידים בין עובדות מדודות לטענות ללא תמיכה.
- **תוצרים שימושיים:** מפות פרויקט, מסמכי ארכיטקטורה, מלאי endpoints ומסכים, זרימות, כללי עסק, סקרי onboarding ושאילתות גרף.

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

חבילת Python היא מנוע המיפוי הקנוני. חבילת npm [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) היא starter משלים.

ראו את [אתר התיעוד](https://wesleysimplicio.github.io/simplicio-mapper/), [החוזים](../contracts/), [מדריך האינטגרציה](../SIMPLICIO_INTEGRATION.md) ו־[מהדורת v0.23.1](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1). הרישיון הוא [MIT](../LICENSE).

</div>

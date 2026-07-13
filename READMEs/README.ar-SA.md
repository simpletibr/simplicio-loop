<div dir="rtl">

# simplicio-mapper

> حوّل المستودع إلى سياق محدود وقابل للاستعلام وجدير بالثقة للبشر ووكلاء الذكاء الاصطناعي.

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/)

[README المرجعي وجميع اللغات](../README.md)

<p align="center"><img src="../assets/llm-project-mapper-hero.png" alt="مستودع يتحول إلى سياق محدود مدعوم بالأدلة" width="100%"></p>

يحوّل `simplicio-mapper` قاعدة الشفرة إلى مخرجات مُصَدَّرة بإصدارات داخل `.simplicio/`: معمارية، ورموز، وتدفقات، وقواعد، واختبارات، وحزم سياق موجهة للمهام. وهو محرك الخرائط في منظومة Simplicio، بحيث تصبح معرفة المستودع صغيرة بما يكفي للفحص وصريحة بما يكفي للتدقيق.

## بداية سريعة

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "تتبّع مسار المصادقة" --token-budget 1200 --json
```

## ما الذي يميّزه؟

- **استرجاع محدود:** يعرض `handoff` و`orient` الملاءمة والتغطية وميزانية الرموز والعقوبات والدقة، بدلاً من وضع المستودع كله سراً في prompt.
- **سياق يواكب التغيير:** تحافظ `sync` و`history` و`diff` و`delta` على ContextGraph عبر التغييرات والجلسات.
- **عقود الأدلة:** تفصل المخططات العامة والتحقق وعلامات الثقة والإيصالات السلوكية والشهادات الحقائق المقاسة عن الادعاءات بلا سند.
- **مخرجات عملية:** خرائط المشروع ووثائق المعمارية وجرد نقاط النهاية والشاشات والتدفقات وقواعد العمل واستبيانات التهيئة واستعلامات الرسم البياني.

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

حزمة Python هي محرك الخرائط المرجعي. حزمة npm [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) هي بادئ مشروع مكمّل.

راجع [موقع التوثيق](https://wesleysimplicio.github.io/simplicio-mapper/)، و[العقود](../contracts/)، و[دليل التكامل](../SIMPLICIO_INTEGRATION.md)، و[إصدار v0.23.1](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1). الترخيص [MIT](../LICENSE).

</div>

<div dir="rtl">

# 🔁 simplicio-loop — The Universal Looping AI Orchestrator

</div>

> **Canonical operational contract:** This translation is informational. For current dependency, runtime, conformance, and validation behavior, [README.md](../README.md) is authoritative: Loop installs standalone; Runtime bindings are optional; 3 runtimes are guaranteed and 12 are best-effort; and `scripts/check.py` requires an importable `pytest` with no bare-Python fallback. GitHub Actions is not required gate evidence.

<p align="center">
  <img src="../assets/simplicio-loop-hero-stage-agents-2026.webp" alt="simplicio-loop مع وكلاء فعليين لكل مرحلة وتقارير متصلة" width="920" />
</p>

<p align="center">
  <a href="https://github.com/wesleysimplicio/simplicio-loop/stargazers"><img src="https://img.shields.io/github/stars/wesleysimplicio/simplicio-loop?style=social" alt="Stars"></a>
  <a href="#-المهارات-والمسرّعات-الـ-7-5"><img src="https://img.shields.io/badge/skills-7-7C3AED" alt="7 skills"></a>
  <a href="#-محوّلات-المصادر"><img src="https://img.shields.io/badge/source%20adapters-5-00E08A" alt="5 source adapters"></a>
  <a href="#-15-بيئة-تشغيل-بروتوكول-واحد"><img src="https://img.shields.io/badge/runtimes-15-2563EB" alt="15 runtimes"></a>
  <a href="#-نقاط-التوسعة-الـ-49"><img src="https://img.shields.io/badge/extension%20points-50-00E08A" alt="50 extension points"></a>
  <a href="#-اقتصاد-الرموز"><img src="https://img.shields.io/badge/tokens-up%20to%2096%25%20fewer-green" alt="Up to 96% fewer tokens"></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
</p>

<p align="center">
  <a href="#-الخلاصة">الخلاصة</a> ·
  <a href="#-المهارات-والمسرّعات-الـ-7-5">7 مهارات</a> ·
  <a href="#-محوّلات-المصادر">محوّلات المصادر</a> ·
  <a href="#-15-بيئة-تشغيل-بروتوكول-واحد">15 بيئة تشغيل</a> ·
  <a href="#-الحلقة">الحلقة</a> ·
  <a href="#-اقتصاد-الرموز">اقتصاد الرموز</a> ·
  <a href="#-اقتصاد-الرموز">محرّك الالتقاط</a> ·
  <a href="#-التثبيت-والاستخدام">التثبيت</a>
</p>

<p align="center">
  <strong>🌍 Languages:</strong><br>
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

---

<!-- visual-story:start -->
## 🚀 الجيل الجديد — نظام تشغيل لعمل الوكلاء القابل للتحقق

**تطوّر simplicio-loop إلى ما هو أبعد بكثير من تكرار prompt حتى الاكتمال.** فهو يحوّل النية إلى عقد مهمة ثابت، ويرسم خريطة المستودع، ويخطط وفق الاعتماديات، ويوزع التنفيذ على worktree معزولة، ويجمع إيصالات منظمة، ويتحقق بصورة مستقلة، وينفذ rollback آمناً، ويتذكر كل محاولة، ويبقي source of record متزامناً حتى التسليم.

- **العقد أولاً** — تكون معايير القبول والاعتماديات والمخاطر وحالة المصدر وcompletion oracle صريحة قبل التنفيذ.
- **توازٍ بلا إفساد** — تعمل المهام الجاهزة داخل lane/worktree معزولة ثم تتقارب عبر ledger تشغيلي.
- **الدليل قبل الاكتمال** — ترفض الاختبارات وفحوص impact/flow وتحديات watcher وإيصالات التسليم وHBP evidence حالات done الزائفة.
- **ذاكرة تغيّر السلوك** — تمنع journal وstall detector وcheckpoint وcross-agent wiki التكرار وتجعل handoff مستداماً.

<p align="center">
  <img src="../assets/simplicio-loop-parallel-worktrees.png" alt="simplicio-loop parallel isolated worktree execution" width="920" />
</p>

<p align="center"><em>Fan-out واعٍ بالاعتماديات: يعمل كل worker المعزول بالتوازي، ويعيد الدليل، ثم تتقارب النتائج في تسليم واحد متحقق منه.</em></p>

<p align="center">
  <img src="../assets/simplicio-loop-lifecycle-2026.svg" alt="simplicio-loop lifecycle from intake to durable memory" width="920" />
</p>

<p align="center"><em>كل مرحلة صريحة ومحدودة وقابلة للمراقبة والعكس.</em></p>

<p align="center">
  <img src="../assets/simplicio-loop-evidence-memory.png" alt="simplicio-loop evidence memory verification rollback and completion" width="920" />
</p>

<p align="center"><em>الدليل والذاكرة جزء من مسار التنفيذ، وليسا تقريراً يُكتب بعد انتهائه.</em></p>

تحوّل هذه البنية هدفاً واحداً إلى نظام تسليم محكوم: من مهمة صعبة إلى backlog كامل، عبر sessions وruntimes، باستخدام local-first operators وإيصالات يستطيع الإنسان أو CI أو وكيل آخر تدقيقها.

<p align="center">
  <img src="../assets/simplicio-loop-architecture-2026.svg" alt="simplicio-loop control execution evidence and delivery planes" width="920" />
</p>
<!-- visual-story:end -->

<!-- stage-agents-roadmap:start -->
## 🤖 خارطة الطريق — وكيل فعلي خلف كل مرحلة

> **الحالة:** بنية مخططة ومتابعة في [#422](https://github.com/wesleysimplicio/simplicio-loop/issues/422)–[#436](https://github.com/wesleysimplicio/simplicio-loop/issues/436). تعليق lifecycle القانوني في GitHub موجود اليوم؛ أما gate الكامل لوكلاء المراحل وreporting الإلزامي فما زال قيد التنفيذ في [#433](https://github.com/wesleysimplicio/simplicio-loop/issues/433).

سيكون لكل من intake/التخطيط والتنفيذ والسلامة والتسليم وrecovery والتدقيق النهائي وكيل مسؤول. تتفرع review إلى أربعة وكلاء مستقلين — الأمن/الصحة، الجودة، إعادة إنتاج runtime/E2E، ونطاق التأثير — قبل أن تتقارب.

<p align="center"><img src="../assets/simplicio-loop-stage-agents-reporting-2026.webp" alt="وكلاء مراحل simplicio-loop وتعليقات work tracker" width="920" /></p>

```mermaid
flowchart LR
  P["وكيل intake + التخطيط"] --> I["وكيل التنفيذ"] --> S["وكيل السلامة"]
  S --> R["4 وكلاء review مستقلين"] --> D["وكيل التسليم"] --> A["مدقق الاكتمال"]
  D --> F["وكيل feedback + recovery"] --> I
  P -.-> E["أحداث + receipts"]
  I -.-> E
  R -.-> E
  A -.-> E
  E --> G["تعليقات GitHub · إلزامية"]
  E -. "فقط عند الاتصال" .-> O["Azure DevOps · Jira · Asana · Trello"]
```

**السياسة:** تعليقات GitHub إلزامية للـ runs المرتبطة بـ GitHub، وينتظر `COMPLETE` تأكيداً بعيداً. لا تتلقى Azure DevOps وJira وAsana وTrello التعليقات إلا بعد إثبات الاتصال والمصادقة والتفويض وحل الهدف؛ `NOT_CONNECTED` هو skip صريح وغير حاجب. العقد والاختبارات: [#436](https://github.com/wesleysimplicio/simplicio-loop/issues/436).
<!-- stage-agents-roadmap:end -->

<div dir="rtl">

## 🆕 الجديد في الإصدار v3.38.0 — إصدار تنسيق الوكلاء المتعدّدين

هذا الإصدار يعالج مشكلة تظهر فقط حين تعمل **عدّة جلسات وكيل على المستودع نفسه في آنٍ واحد**: كيف
تعرف الجلسة ما هو محجوز مسبقاً، وما تمّ دمجه لكنه غير مكتمل، وماذا تفعل بوقتها الخامل بدل تكرار
عمل جلسة أخرى؟ كل ما يلي بُني واختُبر وشُحن على الحالة **الحيّة متعدّدة الجلسات لهذا المستودع نفسه**.

- **`scripts/coordinator.py` — نواة القرار.** بالاستناد إلى حالة GitHub الحالية (تعليقات حجز على
  issues مفتوحة + طلبات دمج مُدمَجة)، يُرجِع فعلاً حتمياً واحداً لكل issue: `OWN` (لا حجز بعد)،
  `CONTINUE_OWN` (أنت آخر من حجزها)، `DEFER_ACTIVE_CLAIM` (جلسة أخرى حجزتها حديثاً — لا تكرّر
  العمل)، `RECLAIM_STALE` (الحجز بَرَد، يمكن أخذها بأمان)، أو `VERIFY_PARTIAL` (طلب دمج دُمج
  لهذه الـ issue لكنها ما زالت مفتوحة — تحقّق ممّا أُنجز فعلاً). ويرفع علم `duplicate_risk` لحظة
  حجز جلستين للـ issue نفسها بفارق زمني قصير — وقد أمسك فعلياً بجلستين تبنيان finding collector
  للـ issue نفسها بملفّين مختلفين في اليوم الأول.
- **`scripts/pr_dod_review.py` — المراجع لوقت الخمول.** حين تكون كل الـ issues محجوزة، أفضل تحرّك
  للجلسة ليس الانتظار بل مراجعة طلبات الدمج المفتوحة مقابل معيار "تعريف الاكتمال" ذي 7 أبعاد
  (تنفيذ، اختبارات وحدة/تكامل/نظام/انحدار، قياس أداء، تغطية ≥85%) وقائمة معايير القبول المُجمَّدة
  للـ issue. `check --post` ينشر حكماً آلياً سطراً بسطر كتعليق على طلب الدمج بدل موافقة انطباعية —
  وقد أثبت ذلك على طلب دمج حقيقي مدموج مسبقاً بوسمه **17 من 17** معياراً كمعلَّق لا يزال غير محلول.
- **`scripts/finding_collector.py` — ذاكرة عيوب مُتينة ومُزالة التكرار (issue #466، المرحلة 1).**
  سجلّ `simplicio.finding/v1` واحد لكل عيبٍ مميّز، مُبصَم بحيث ينهار *العطل نفسه* — مهما رآه وكيلٌ
  أو تشغيلٌ أو توقيتٌ مختلف — إلى سجلّ واحد مع عدّاد تكرار بدل ضجيج مُكرَّر.
- **مرجعان جديدان** `references/multi-agent-coordination.md` و`references/background-verification.md`
  مربوطان مباشرة في خطوة الفرز في `SKILL.md`: تحقّق من ملكية المنسّق قبل لمس أي issue، راجع طلبات
  الدمج بدل الخمول حين يُحجَز كل شيء، وشغّل أوامر التحقّق البطيئة في الخلفية.
- **تنظيف إلزامي بعد الدمج** (`scripts/worktree_cleanup.py`, #484) — worktree والفرع المحليّان
  لفرع مُدمَج يُزالان آلياً بدل التراكم عبر الجلسات.
- **انحداران حقيقيان أُمسِكا وأُصلِحا على `main` نفسه، حيّاً، في دورة هذا الإصدار** — طلب دمج حذف
  تعريف دالة بصمت (فكسر اختبار `loop_progress.py` الذاتي) دُمج مرّة، ثم أعاد تسابق squash-merge
  الشيفرة المكسورة نفسها إلى `main` مرّة ثانية. كلاهما اكتُشف بتشغيل السكربت المتأثّر فعلياً، لا
  بالثقة بوصف طلب دمج أخضر — وهذا بالضبط سبب وجود `coordinator.py` و`pr_dod_review.py` الآن.

**ماذا يعني هذا لك عملياً:** إن كنت تُشغّل `simplicio-loop` عبر أكثر من جلسة أو جهاز على المستودع
نفسه، فهو الآن يحميك فعلياً من فشلين شائعين: وكيلان يُعيدان العمل نفسه بصمت، وطلب دمج "مكتمل" لكنه
يترك الـ issue الحقيقية محلولة جزئياً فقط. راجع [`CHANGELOG.md`](../CHANGELOG.md) للقائمة الكاملة.

</div>

<div dir="rtl">

## ⚡ الخلاصة

**simplicio-loop** هو **سوبر-بلجن** مستقلّ عن بيئة التشغيل — منسّق واحد ذاتي الحركة يعمل
بحلقة متكررة (يُستدعى بوصفه **`/simplicio-loop`**)، إضافةً إلى **خمس مهارات تابعة** — يحوّل أي
نموذج لغوي قوي (Claude أو Codex أو Copilot أو Gemini أو Cursor أو النماذج المحلية) إلى عاملٍ
ذاتي القيادة. توجّهه نحو مجموعة من الأعمال — *"أنهِ كل القضايا المفتوحة"*، *"أفرغ طابور الـ CI"*،
*"صفّ لوحة Jira"* — وهو يدير دورة الحياة كاملةً بنفسه:

> **اكتشف ← افهم ← قرّر ← نفّذ ← تحقّق ← صحّح ← سجّل ← كرّر**

يكتشف الأعمال من أي مصدر (GitHub Issues وJira وAzure DevOps وجلسات agentsview وغيرها)،
ويزيل التكرارات، ويوسّع تلقائياً أسطولاً من الوكلاء بما يناسب جهازك، ثم ينفّذ كل عنصر عبر حلقة
جودة **تُشغّل الشيفرة (لا تكتفي بتصريفها)**، ويفتح طلبات الدمج، ويعالج ملاحظات الـ CI والمراجعة،
ويدمج، ويواصل المراقبة **على مدار الساعة طوال أيام الأسبوع** بحثاً عن أعمال جديدة — كل ذلك خلف
بوابات أمان ومفتاح إيقاف صارم للتكلفة.

</div>

```text
/simplicio-loop finish all open issues
→ identity + pre-flight (auth, runtime, STOP path)
→ discover 50 issues · dedup · build dependency DAG
→ autoscale fleet = 14 · pipeline implement→review→merge
→ each item: read body+ACs → orient code → plan → edit → run → verify → PR
→ merge · close with evidence · rollback if main breaks
→ keep looping every ~2 min until the queue is dry (evidence-gated, never a false "done")
```

<div dir="rtl">

ثلاثة أمور تجعله مختلفاً: فهو **سوبر-بلجن من مهارات مركّزة**، ويشغّل **البروتوكول نفسه على 15
بيئة تشغيل**، ويفعل كل ذلك بـ**اقتصاد رموز جريء وصادق**.

</div>

---

<div dir="rtl">

## 📘 سجلّ القدرات الرسمي

القائمة الكاملة والرسمية لما يشحنه `simplicio-loop` — كل قدرة في الأسفل **حقيقية وقابلة
للتشغيل ومُختبَرة** (`python3 scripts/check.py`: تدقيق الادّعاءات 4/4 + 28 اختباراً). ويرتبط
كلٌّ منها بقسمه التفصيلي وبعامله (worker).

| القدرة | ماذا تفعل | البرهان / العامل | التفاصيل |
|---|---|---|---|
| 🎬 **أدلّة الفيديو** (`video_evidence`) | تُسجّل **جلسة المتصفّح الحقيقية** برهاناً متحرّكاً على أن تغييراً في الواجهة يعمل (Playwright، افتراضياً)؛ وتُصيِّر **MP4 حتميّاً مُعنوَناً** عبر [hyperframes](https://github.com/heygen-com/hyperframes) عند طلب شرح صريح (`/simplicio-loop make a video of screen X`) | `scripts/video_evidence.py` · مَحجوب (لا تمرير زائف) دون سلسلة الأدوات | [§ أدلّة الفيديو](#-أدلّة-الفيديو--playwright-افتراضياً-hyperframes-عند-الطلب) |
| 🧠 **ذاكرة المحاولات + كاشف التعثّر** | سجلّ تشغيل مُتين (`.simplicio/orchestrator/loop/journal.jsonl`) + كاشف تعثّر بحيث **تغيّر الحلقة الاستراتيجية بدل أن تتذبذب**؛ فرز تدريجي (`since`) يقرأ الفارق فقط في كل دورة | `scripts/loop_journal.py` · `selftest` 9/9 | [§ مكافحة التذبذب](#-ذاكرة-المحاولات--كاشف-التعثّر-مكافحة-التذبذب) |
| 🔒 **بوابة أمان تفشل مغلقةً** (`action_gate`) | خطّاف `PreToolUse`/git-pre-push **يحجب آلياً** الدفع القسري، وإعادة كتابة التاريخ، والحذف الجماعي، وعمليات DDL المدمِّرة، وتفكيك البنية التحتية، والـ commits/pushes المحمّلة بالأسرار — الخطوة 5 جُعلت قابلة للتنفيذ لا مجرّد نثر | `hooks/action_gate.py` · `selftest` 15/15 | [§ الأمان](#-الأمان-غير-قابل-للتفاوض) |
| 🔬 **التحقق المحلي** | مجموعة اختبارات (selftests للعمّال + **اختبار e2e لقائد الحلقة** يُثبت الخروج المرتبط بالأدلة) + **تدقيق ادّعاءات** (السكربتات المُشار إليها موجودة · الأعداد متّسقة · `_bundle ≡ source`) — كله محلي، **بلا CI مدفوع** | `scripts/check.py` · `scripts/claims_audit.py` · `tests/` | [§ الاختبارات والفحوص المحلية](#-الاختبارات-والفحوص-المحلية-بلا-ci-مدفوع) |
| ✅ **توفير صادق** | سطر التوفير صار **مرتبطاً بالأدلة لا إلزامياً** — لا يُعرَض رقم إلا مع إيصال مقيس (clamp/signatures/cache/`deterministic_edit`/ledger)؛ ولا يُلفَّق أبداً | عقد اقتصاد الرموز | [§ اقتصاد الرموز](#-اقتصاد-الرموز) |

ويجعل **وضعان** للحلقة الإنهاء صريحاً: **converge** (مهمة صعبة واحدة — تنتهي عند `<promise>`
المرتبط بالأدلة أو عند تصعيد تعثّر) مقابل **drain** (طابور — ينتهي حين يبقى استعلام المصدر فارغاً
Both modes are still governed by universal exits: promise+evidence, `max_iterations`, and STOP.

> تقييم الحلقة عبر هذا الخطّ من العمل: **7.5** (تصميم قوي غير مُثبَت) ← **9** (ذاكرة محاولات +
> مكافحة تذبذب) ← **9.5** (برهان محلي قابل لإعادة الإنتاج) ← **~10** (أمان مفروض + دلالات حلقة
> مكتملة). وتُمسك بنية التحقق الآن بانحدارات المشروع ذاته مع نموّه.

---

## 🧠 المهارات والمسرّعات الـ 7 + 5

نواة المنسّق + ستة توابع + خمسة مسرّعات/تكاملات. كل تابع **اختياري** — فعند تحميله يفوّض إليه
المنسّق (أغنى + أرخص)؛ وعند غيابه يغطّي البروتوكول المضمّن 100%. والمسرّعات **تُكتشف تلقائياً** —
موجودة = تُستخدَم، غائبة = بديل احتياطي بالنموذج اللغوي.

| # | القدرة | ماذا تستوعب | ماذا تفعل | أثر الرموز |
|---|---|---|---|---|
| 1 | 🔁 **simplicio-loop** | — | نقطة الدخول العامة الموحّدة: نواة المنسّق + الحلقة المُحكَمة خلف أمر واحد | النواة + الحلقة |
| 2 | ↩️ **simplicio-tasks** | اسم بديل قديم | غلاف توافق للتثبيتات القديمة والـ prompts المحفوظة | اسم بديل قديم |
| 3 | 🧱 **simplicio-orient** | [rtk](https://github.com/rtk-ai/rtk) + [caveman](https://github.com/JuliusBrussee/caveman) | تنفيذ مُوجَّه نحو الطرفية أولاً، كتالوج تقليل المُخرَجات، tee-cache، قراءة signatures | L0 حتميّ |
| 4 | 🔥 **simplicio-review** | [thermos](https://github.com/cursor/plugins/tree/main/thermos) | مراجعة تخاصمية متوازية على معايير متمايزة ← حُكم واحد بلا تكرار | بوابة الجودة |
| 5 | 🗜️ **simplicio-compress** | [caveman](https://github.com/JuliusBrussee/caveman) | ضغط المُخرَجات + الذاكرة، `transform_guard` يفشل آمناً | 40-60% أقل |
| 6 | 🎓 **simplicio-learn** | [teaching](https://github.com/cursor/plugins/tree/main/teaching) | مراجعة استرجاعية بعد التشغيل ← دروس مُتينة بلا تكرار في الذاكرة | أذكى في كل تشغيل |
| 7 | 🧪 **simplicio-autoresearch** | نمط Karpathy `autoresearch` + `autoresearch-agent` | حلقة تطوّرية mutate/eval/keep-revert: سقوف yool، فرع معزول بـ git، تقييم مضاد لـ Goodhart، إيصال `savings-event` | تحسين آلي |
| 8 | 🧭 **Understand Anything** | [Egonex-AI](https://github.com/Egonex-AI/Understand-Anything) | توجيه برسم بياني معرفي: بحث دلالي، جولات موجَّهة، رسم بياني للتبعيات | **L0 بلا رموز** |
| 9 | 📊 **agentsview** | [kenn-io](https://github.com/kenn-io/agentsview) | تحليلات الجلسات، تتبّع التكلفة، اكتشاف الجلسات المتوقّفة | **L1** SQL فقط |
| 10 | ⚡ **LMCache** | [LMCache](https://github.com/LMCache/LMCache) | تخزين KV بين دورات الحلقة — تقليل TTFT بنسبة 40-70% على النماذج المحلية | وقت GPU ↓ |
| 11 | 🗜️ **محرّك التقاط Simplicio** | `engine/simplicio_engine.py` (أصيل، مكتبة معيارية فقط) | وكيل التقاط شفّاف: يمرّر إلى المزوّد الحقيقي، يقيس + يضغط حتميّاً، يكتب `proxy_savings.json` | **حتميّ** |
| 12 | 🎬 **video_evidence** | Playwright (افتراضياً) · [hyperframes](https://github.com/heygen-com/hyperframes) (عند الطلب) | تُسجّل **الجلسة الحقيقية** برهاناً متحرّكاً على تغيير في الواجهة (Playwright)؛ وتُصيِّر **MP4 حتميّاً مُعنوَناً** للشرح عبر hyperframes حين يكون الفيديو هو المُسلَّم | منتج الأدلة |

كذلك، ضمن سجلّ القدرات: **`coordinator.py`** (منسّق قرار متعدّد الجلسات)، **`pr_dod_review.py`**
(مراجع DoD/AC لطلبات الدمج)، و**`finding_collector.py`** (ذاكرة عيوب مُزالة التكرار) — ثلاثة
عمّال جدد يخدمون نقاط التوسعة نفسها الموصوفة في § الجديد في v3.38.0 أعلاه.

كل مهارة تقيم ضمن [`.claude/skills/`](../.claude/skills)؛ ولكل مسرّع مستند مرجعي ضمن
`.claude/skills/simplicio-loop/references/` (منتج الفيديو:
[`video-evidence.md`](../.claude/skills/simplicio-loop/references/video-evidence.md)، العامل
[`scripts/video_evidence.py`](../scripts/video_evidence.py)).

---

## 📡 محوّلات المصادر

يكتشف المنسّق الأعمال من أي مصدر عبر محوّلات قابلة للتركيب. ويُظهِر كلٌّ منها ستة أفعال:
`list_ready` و`get_details` و`claim` و`update_status` و`attach_evidence` و`close`.

| المصدر | المحوّل | الغرض |
|---|---|---|
| GitHub Issues/PRs | `gh` CLI (أصيل) | المصدر الأساسي لعناصر العمل |
| Jira / Asana / ClickUp / Linear / Notion | موصِّل المضيف | إدارة اللوحات/المشاريع |
| Trello / Azure DevOps | محوّل `az boards` | تتبّع أعمال Azure |
| **جلسات agentsview** | `scripts/agentsview_adapter.py` | استرداد الجلسات المتوقّفة + رصد التكلفة |
| الملفات المحلية / طابور CI | نظام الملفات / واجهة CI | تتبّع العمل الداخلي |

راجع المستند المرجعي لكل محوّل ضمن `.claude/skills/simplicio-loop/references/`.

---

## 🌐 15 بيئة تشغيل، بروتوكول واحد

نواة مهارة عالمية واحدة + مجموعة خطّافات واحدة تقود كل بيئة تشغيل. والمحوّل رفيع: فهو يخبر بيئة
التشغيل *أين تحمّل المهارات*، و*كيف تسلّح الحلقة*، و*كيف تربط السرعة الأصيلة*. **المهارة لا
تسمّي أي بيئة تشغيل؛ بل بيئة التشغيل هي التي تكتشف المهارة.**

| بيئة التشغيل | تحميل المهارة | قيادة الحلقة | الربط الأصيل |
|---|---|---|---|
| **Claude Code** | `.claude/skills/` + plugin | `Stop` hook | MCP |
| **Codex** | `AGENTS.md` | self-paced | MCP / adapter |
| **VS Code (Copilot)** | `copilot-instructions.md` | tasks | MCP |
| **Cursor** | `.cursor-plugin/` | `stop`+`afterAgentResponse` | MCP / rules |
| **Antigravity** | rules / `AGENTS.md` | self-paced | MCP |
| **Kiro** | `.kiro/steering/` | specs | MCP |
| **OpenCode** | `AGENTS.md` | self-paced | MCP |
| **Gemini** | `GEMINI.md` | self-paced | MCP / adapter |
| **Aider** | `CONVENTIONS.md` | self-paced | — (LLM fallback) |
| **Simplicio Agent** *(اسمها القديم Hermes)* | native recall | native loop | **native** |
| **OpenClaw** | plugin SDK | native scheduler | **native** |
| **Kimi** | تعليمات مضمّنة | self-paced | best-effort |
| **Qwen** (Code/CLI) | مكافئ `AGENTS.md` | self-paced | best-effort |
| **DeepSeek** | تعليمات مضمّنة | self-paced | best-effort |
| **Orca** | عبر الوكيل الداخلي وسجلّ المهارات | hook داخلي / أتمتة مجدولة | تهيئة سجلّ/وكيل داخلي |

الوعد: **البروتوكول نفسه، والبوابات نفسها، والأمان نفسه على كل البيئات الخمس عشرة — 3 مضمونة
آلياً في كل commit (Claude Code وCodex وCursor)، و12 بأفضل جهد.** ويعمل `orient_clamp.py`
(اقتصاد الرموز) على كل بيئة تشغيل دون أي توصيل. راجع [`adapters/MATRIX.md`](../adapters/MATRIX.md).

---

## 🗺️ المسار الكامل — من الطلب إلى التسليم

كل طبقة يعمل عليها المنسّق، بالترتيب — من قراءة الطلب (issues وtasks وassigns) إلى تسليم عملٍ
مدموج ومدعوم بالأدلة، ثم التكرار على مدار الساعة طلباً للمزيد.

</div>

```mermaid
flowchart LR
  IN["Intent: issue · task · queue"] --> CONTRACT["1 · Freeze task contract"]
  CONTRACT --> MAP["2 · Map source + normalize"]
  MAP --> PLAN["3 · Dependency DAG + acceptance criteria"]
  PLAN --> ROUTE{"4 · Ready task?"}
  ROUTE -->|"solo / small"| SOLO["Targeted lane"]
  ROUTE -->|"parallel / medium+"| FAN["Bounded fan-out"]
  FAN --> A["Isolated worktree A"]
  FAN --> B["Isolated worktree B"]
  FAN --> C["Isolated worktree C"]
  SOLO --> VERIFY["5 · Test + impact/flow evidence"]
  A --> VERIFY
  B --> VERIFY
  C --> VERIFY
  VERIFY --> RECEIPT["Watcher challenge + evidence receipt"]
  RECEIPT --> ORACLE{"6 · Completion oracle"}
  ORACLE -->|"pending / blocked"| RECOVER["Journal · checkpoint · rollback · backlog-only maintenance"]
  RECOVER --> PLAN
  ORACLE -->|"verified / measured"| DELIVER["7 · Source sync · PR · merge"]
  DELIVER --> MEMORY["8 · Ledger · wiki · durable attempt memory"]
  MEMORY --> WATCH["9 · Re-feed · watcher · STOP path"]
  WATCH -->|"new work"| IN
```

---

<div dir="rtl">

## 🔁 الحلقة

**الحلقة المرتبطة بالأدلة** هي الآلية الأساسية. فهي تُعيد تغذية الهدف نفسه في كل دورة كي يرى
الوكيل عمله السابق. والخروج لا يكون **إلا** عبر:

1. **`<promise>` مرتبط بالأدلة** — فالدورة التي تنبعث منها الوعد **يجب** أن تحمل أيضاً برهاناً
   ملموساً (اختبار ناجح، طلب دمج مدموج، إعادة استعلام عن عنصر مُغلق). والوعد بلا أدلة = يُتجاهَل.
2. **سقف `max_iterations`** — حاجز أمان صارم
3. **STOP/cancel path** — explicit STOP file or channel command stops unattended runs
4. **إشارة STOP** — `.simplicio/orchestrator/STOP` أو أمر القناة

بين الدورات، يخزّن LMCache (حين يتوفّر) حالة KV فتقترب كلفة إعادة التغذية من صفر prefill.

### 🧠 ذاكرة المحاولات + كاشف التعثّر (مكافحة التذبذب)

حلقة إعادة تغذية لا تتذكّر شيئاً تتذبذب — جرّب X، افشل، جرّب X مجدداً — حتى يحترق السقف.
يحفظ simplicio-loop **سجلّ تشغيل مُتيناً** (`.simplicio/orchestrator/loop/journal.jsonl`، للإلحاق فقط:
`iteration · action · hypothesis · gate · error-fingerprint`) و**كاشف تعثّر**
([`scripts/loop_journal.py`](../scripts/loop_journal.py)، حتميّ + بلا نموذج):

- **بصمة الخطأ** — يُختزَل مُخرَج البوابة الفاشلة إلى تجزئة (hash) مستقرّة بعد تطبيع أرقام
  الأسطر، والمسارات، والـ hex/uuids، والطوابع الزمنية والمُدد، فيُعرَف *العطل نفسه* عبر الدورات
  حتى عندما يختلف النصّ العَرَضي.
- **التعثّر = K حالات فشل ببصمة متطابقة على التوالي** (الافتراضي K=3). فتغيّر البصمة يعني أن
  الحلقة تتحرّك (PROGRESS)؛ وتطابقها K مرات يعني أنها تدور في مكانها (STALLED).
- عند STALLED لا تُعيد الحلقة تغذية الهدف نفسه — بل تسمّي **الأفعال المسدودة** كي تتجنّبها، ثم
  **تبدّل الاستراتيجية** أو **تصعّد إلى البوابة البشرية** مع البصمة.
- يُقرأ `loop_journal.py resume` في رأس كل دورة، فتواصل عمليةٌ جديدة دون إعادة استنباط المحاولات
  السابقة (استئناف حقيقي) ولا تعيد أبداً محاولة طريقٍ مسدودٍ معروف.

</div>

```bash
loop_journal.py resume                       # what was tried + dead-ends to avoid
loop_journal.py record --iteration N --action "…" --gate fail --gate-output test.log
loop_journal.py stall --k 3 --exit-code      # PROGRESS → re-feed · STALLED → switch/escalate
```

---

<div dir="rtl">

## 🎬 أدلّة الفيديو — Playwright افتراضياً، hyperframes عند الطلب

تُنتج الحلقة **فيديوهات عرض** برهاناً على أن تغييراً يعمل — **محرّكان**، ونقطة توسعة
`video_evidence` واحدة (العامل [`scripts/video_evidence.py`](../scripts/video_evidence.py)،
العقد [`references/video-evidence.md`](../.claude/skills/simplicio-loop/references/video-evidence.md)):

1. **الافتراضي — مسار الأدلة المعتاد يستخدم Playwright.** بعد تغيير في الواجهة، يُسجّل
   `video_evidence` **جلسة المتصفّح الحقيقية** وهي تقود الشاشة (فيديو Playwright الأصيل ←
   `.webm`، ← `.mp4` عبر FFmpeg) — أقوى إيصال على "يعمل، لا يُصرَّف فحسب" (الخطوة 4b)
   و`<promise>` صالح مرتبط بالأدلة.

   ```bash
   python3 scripts/video_evidence.py verify --url http://localhost:3000/login \
       --name login-demo --expect "Sign in" --issue 42 [--upload --pr 42]
   ```

2. **عند الطلب — شرح مُخصَّص يستخدم hyperframes.** حين يكون الفيديو نفسه هو المُسلَّم
   ("اصنع فيديو شرح لشاشة X")، يُصيِّر المنسّق **عرضاً منزلِقاً (slideshow) حتميّاً مُعنوَناً**
   من لقطات `web_verify` عبر [**hyperframes**](https://github.com/heygen-com/hyperframes)
   (من HeyGen — "المدخل نفسه، الإطارات نفسها، المُخرَج نفسه"، قابل لإعادة الإنتاج في الـ CI، بلا
   مفاتيح API، تصيير محلي عبر Chrome بلا واجهة + FFmpeg).

   ```text
   /simplicio-loop make an explainer video of the system login screen
   → detect: video-creation request → web_verify captures the screens
   → video_evidence verify --engine hyperframes → deterministic MP4 → attached to the PR
   ```

أيٌّ من المحرّكين: فيديو لم يُسجَّل/يُصيَّر قطّ يُنتج **BLOCKED**، لا تمريراً زائفاً أبداً.
والدليل دوماً **مسار ملف + حُكم منطقي (boolean)** — لا بايتات فيديو في السياق أبداً (اقتصاد
الرموز).

</div>

---

<div dir="rtl">

## 📊 اقتصاد الرموز

| التقنية | التوفير |
|---|---|
| `deterministic_edit` (L0) | 100% من رموز التحرير (الملف يُكتب آلياً، لا بالنموذج اللغوي أبداً) |
| التنفيذ المُوجَّه نحو الطرفية أولاً | حقائق من الصدفة، لا هلوسة النموذج اللغوي |
| كتالوج تقليل المُخرَجات | سقوف لكل نوع أمر (`CAP_ERRORS=20`، `CAP_WARNINGS=10`، `CAP_LIST=20`) — `orient_clamp.py` |
| tee+CCR cache عند الفشل | لا تُعِد تشغيل أمرٍ فاشل أبداً — اقرأ المُخرَجات المخزّنة |
| قراءات signatures-only | `simplicio-cli signatures <file>` — ملف من 870 سطراً ← 65 سطراً (**93% توفير**)، المتون محذوفة |
| `simplicio-compress` | نثر مقتضب + ضغط ذاكرة لمرة واحدة |
| `orient_clamp.py` | تقليم + tee على كل أمر صدفة، بلا توصيل |
| Native response cache | طلب حتميّ متكرّر (temp=0) ← يُخدَم من الذاكرة المؤقتة، يتخطّى استدعاء النموذج اللغوي (**100% عند الإصابة**) — `simplicio-cli cache`، مُفعَّل افتراضياً (`SIMPLICIO_CACHE=0` للتعطيل) |
| وكيل التقاط Simplicio + MCP | 60-95% رموز أقل على مُخرَجات الأدوات عبر خادم ضغط شفّاف |

التوفير لا يُحتسب إلا عند نتيجة مُتحقَّق من صحتها. والأساس المرجعي = أرخص مسار معقول غير مُنسَّق
يبلغ النتيجة نفسها. **والإبلاغ عن التوفير مرتبط بالأدلة لا إلزامي:** لا يُعرَض رقم توفير إلا حين
تكون دورةٌ ما قد شغّلت فعلاً أمراً مُنتِجاً للاقتصاد وكان الرقم يتتبّع إلى إيصال مقيس (clamp tee،
قراءة signatures، إصابة cache، `deterministic_edit`، `savings_ledger`). فلا اقتصاد مقيس ← لا
سطر توفير؛ ولا يلفّق المنسّق أساساً مرجعياً أو نسبة أبداً. راجع `references/token-economy.md`.

### 🔎 تشغيل `simplicio-loop`: الاقتصاد مقابل القياس (لكل بيئة تشغيل)

يحدث أمران مختلفان عند استدعاء **`simplicio-loop`**، ويسلكان سلوكاً مختلفاً لكل بيئة تشغيل:

- **الاقتصاد** — الضغط، وتقليم المُخرَجات، وقراءات signatures-only، و`deterministic_edit` — ينطبق
  **في كل مرة تعمل فيها المهارة وتحمّل `simplicio-orient` / `simplicio-compress`، على أي بيئة
  تشغيل.** فهو سلوك المهارة إضافةً إلى الخطّافات (أقوى حيث توجد الخطّافات: `orient_clamp.py`
  يُقلِّم تلقائياً على Claude وCursor؛ وفي غيرها بقيادة التعليمات).
- **القياس** — أرقام Token Monitor الحيّة — لا يحتسب إلا الحركة التي تمرّ **عبر وكيل الالتقاط.**

| بيئة التشغيل | الاقتصاد (المهارة) | القياس (المراقب) |
|---|---|---|
| **Simplicio Agent** | ✓ | ✓ **تلقائي** — موجَّه أصلاً عبر الوكيل (`base_url → :8788`) |
| **Claude** | ✓ (المهارة + الخطّافات) | ✗ افتراضياً — يتحدّث Claude إلى `api.anthropic.com` مباشرةً؛ يُقاس فقط بعد التوجيه (`simplicio-cli wrap claude`، أو `ANTHROPIC_BASE_URL → http://127.0.0.1:8788`) |
| **Codex** | ✓ (المهارة) | ✗ افتراضياً — يضيف `simplicio-cli init codex` أدوات MCP لكنه لا يوجّه حركة النموذج؛ يُقاس بـ`simplicio-cli wrap codex` أو base-url لـOpenAI يشير إلى الوكيل |

إذن: **التوفير يحدث على كل بيئة تشغيل**؛ و**المراقب يحصيه تلقائياً على Simplicio Agent**، وعلى
Claude/Codex بعد **خطوة توجيه لمرة واحدة** (`simplicio-cli wrap …` / base-url → `:8788`). بدون
توجيه، يبقى الاقتصاد منطبقاً — لكن المراقب لن يحصي تلك الرموز فحسب. ويقوم
`scripts/simplicio-economy.sh wire` بهذا التوجيه للعملاء المتوافقين مع OpenAI وقت التثبيت.

### 📈 مراقب رموز Simplicio (Simplicio Token Monitor)

عرض حيّ ودائم التشغيل للتوفير:

- **لوحة معلومات على الويب** — `http://127.0.0.1:9090` — مخطّط رموز آنيّ، مقياس توفير، النماذج
  اللغوية/بيئات التشغيل و**141/144 مزوّداً (98%)** نعترضها، وسجلّ وكيل حيّ.
- **عنصر شريط القوائم / الصينية** — الرموز المُوفَّرة آنياً في صينية النظام (macOS rumps · Windows/Linux pystray).
- **وحدة واحدة** — `scripts/simplicio-economy.sh {status|up|wire}` يشغّل وكيل الالتقاط + المراقب +
  الصينية + المُشغِّل الحتميّ `simplicio-dev-cli` ويُبلِّغ عن المنظومة كاملةً.

يسجّل التثبيت الثلاثة جميعاً كخدمات ذاتية البدء (macOS launchd · Linux systemd · Windows Startup) عبر
`scripts/setup_simplicio.sh`، أو عبر المتعدّد المنصات `python3 scripts/install_services.py install`. وبعد
التثبيت يعمل المراقب + الالتقاط **دون استدعاء الحلقة** — راجع `references/token-capture.md`.

### 🛠️ محرّك الالتقاط — وحدة أصيلة واحدة، لكل أمر

[`engine/simplicio_engine.py`](../engine/simplicio_engine.py) هو محرّك التقاط Simplicio الأصيل
(مكتبة معيارية فقط، fail-open، دون أي تبعية خارجية). شغّل أي
أمر عبر غلاف [`scripts/simplicio-engine`](../scripts/simplicio-engine) (مثلاً `simplicio-engine doctor`):

| الأمر | ماذا يفعل |
|---|---|
| `proxy` | وكيل الالتقاط الشفّاف — يوجّه كل نموذج إلى مزوّده **الحقيقي**، يضغط + يقيس + يخزّن مؤقتاً (بلا استبدال نموذج) |
| `doctor` | إمكانية الوصول إلى الوكيل + التوفير مدى العمر |
| `cache` | ذاكرة الاستجابة الأصيلة (`stats`/`clear`) — الطلب الحتميّ المتكرّر يُخدَم من الذاكرة، فيتخطّى استدعاء النموذج اللغوي |
| `signatures` | عرض signatures-only لملف مصدري (المتون محذوفة، ~93% رموز أقل لقراءة الشيفرة) |
| `semantic` | ضغط استخراجي قابل للعكس (دلالي خفيف) |
| `detect` | اكتشاف نوع المحتوى + توجيه ذكيّ لكل كتلة |
| `rag` | استرجاع TF-IDF (أو تضمين `--ml`) فوق مخزن ذاكرة CCR |
| `memory` | مخزن CCR للضغط-التخزين-الاسترجاع (`remember`/`recall`/`forget`/`list`/`stats`) |
| `mcp` | خادم MCP أصيل عبر stdio (أدوات compress / retrieve / stats) |
| `init` / `wrap` | تسجيل Simplicio في عميل (Claude / Codex / Copilot / OpenClaw) · تشغيل عميل بتوجيه الالتقاط |
| `report` / `audit` / `capture` / `evals` | تقرير التوفير · تدقيق شجرة بحثاً عن فرصة ضغط · تجربة طلب على الجاف · بوابة انحدار الضغط |

---

## 🏛️ ركائز التصميم (بالتفصيل)

تحمل أربع آليات قوة التنسيق:

| الركيزة | المحور | أين تقيم |
|---|---|---|
| **DAG + خط الأنابيب** | التوازي بحسب التبعية، مُدرَّج لكل عنصر | `references/orchestration.md` (Step 3 pool + pipeline) |
| **عزل Worktree** | تعديلات متوازية دون إفساد الشجرة، مُحكَمة بالدمج | `references/orchestration.md` |
| **التحقق التخاصمي** | لجنة من المتشكّكين قبل "التسليم" | `references/quality-safety-delivery.md` · skill `simplicio-review` |
| **Bounded loop cap** | anti-infinite-loop, evidence-gated exit | `references/standing-loop-247.md` · skill `simplicio-loop` |

---

## 🚀 التثبيت والاستخدام

</div>

```bash
git clone https://github.com/wesleysimplicio/simplicio-loop
cd simplicio-loop

# install for your runtime (omit <runtime> to auto-detect)
bash scripts/install.sh <runtime> [--global]        # macOS / Linux
pwsh scripts/install.ps1 <runtime> [-Global]        # Windows
# <runtime> ∈ claude codex vscode cursor antigravity kiro opencode gemini aider simplicio_agent openclaw
```

<div dir="rtl">

أو، على Claude Code / Cursor، ثبِّته مباشرةً من أحدث إصدار على GitHub (دون السوق):

</div>

```bash
gh release download --repo wesleysimplicio/simplicio-loop --archive tar.gz
tar xzf simplicio-loop-*.tar.gz && cd simplicio-loop-*/
bash scripts/install.sh claude    # or: bash scripts/install.sh cursor
```

<div dir="rtl">

ثم:

</div>

```
/simplicio-loop finish all the open issues
```

<div dir="rtl">

المتطلّب الوحيد هو **python3** على PATH (المهارات والخطّافات والمثبِّت كلها بلغة Python متعددة
المنصات). أما لمصادر GitHub فيلزم `git` + أداة `gh` موثَّقة الدخول. راجع [`INSTALL.md`](../INSTALL.md)
و[`adapters/MATRIX.md`](../adapters/MATRIX.md).

**قبل تشغيل غير مُشرَف عليه على مدار الساعة:** اضبط سقفاً للتكلفة في
رفض المراقب التشغيل دون إشراف (فشل آمن).

---

## 🔒 الأمان (غير قابل للتفاوض)

- **فحص الأسرار** لكل فرق (diff)؛ والإيقاف عند أي إصابة.
- **بوابة بشرية للعمليات غير القابلة للتراجع** — الدفع القسري، إعادة كتابة التاريخ، النشر
  للإنتاج، حذف البيانات/المخطّط، حذف الملفات الجماعي ← توقّف واسأل. وفي وضع بلا واجهة + بلا
  مُوافِق ← أزِل القدرة المدمِّرة.
- **مفروض لا موعود فحسب** — `hooks/action_gate.py` خطّاف `PreToolUse` / git-pre-push
  **يفشل مغلقاً** يحجب آلياً ما سبق (والـ commits المحمّلة بالأسرار) *قبل* تشغيلها. ويصمد عقد
  الأمان حتى لو نسيه النموذج. ويُثبت `selftest` مجموعة القواعد (14/14).
- **حُكم رباعي الحالات قبل التنفيذ** — لا يجوز للتحسين أبداً أن يرفع فئة خطورة أمرٍ ما.
- **ثقة قبل التحميل** — الإعداد المُشكِّل للإدراك (ملفات التقليم، قوائم الكتم) غير موثوق حتى
  يراجعه إنسان ويثبّته بالبصمة (hash-pin).
- **تحصين ضد حقن التعليمات** — لا يمكن لمحتوى العنصر/طلب الدمج/التعليق أن يتجاوز العقد أبداً.
- **مفتاح إيقاف صارم بالدولار** للتشغيلات دون إشراف؛ وإنجاز **مرتبط بالأدلة** (لا "done" زائف
  أبداً)؛ وخطّافات **fail-open** (لا تحبس الوكيل في حلقة أبداً).

---

## ✅ الاختبارات والفحوص المحلية (بلا CI مدفوع)

الادّعاءات مُتحقَّق منها لا مُؤكَّدة فحسب — والبوابة تعمل **محلياً**، بتكلفة CI صفرية:

</div>

```bash
python3 scripts/check.py            # the whole gate (audit + tests)
```

<div dir="rtl">

- **مجموعة الاختبارات** (`tests/`) — selftests العمّال الحتميّة، إضافةً إلى **اختبار e2e لقائد
  الحلقة** (`hooks/loop_stop.py`): يُثبت أن الحلقة **تتوقّف عند الأدلة**، و**تتجاهل `<promise>`
  مجرّداً**، و**تتوقّف عند السقف** كمخارج متمايزة — وأن منتجي الأدلة **يَحجبان** (لا تمرير زائف)
  عند غياب أدوات سلسلتهما. يتطلب البوابة `pytest` قابلاً للاستيراد؛ ولا يوجد fallback إلى Python عارٍ.
- **تدقيق الادّعاءات** (`scripts/claims_audit.py`، يفشل مغلقاً) — كل `scripts/*.py` تشير إليه
  الوثائق موجود · عدد نقاط التوسعة متّفق عبر كل الملفات · كل أمر عامل مُستشهَد به يعمل فعلاً ·
  مهارات `simplicio_loop/_bundle/` المشحونة **متطابقة بايتاً ببايت** مع المصدر.
- **وصّلها كخطّاف git pre-push** لإبقاء `main` أميناً مجاناً:
  ```bash
  printf '#!/bin/sh\npython3 scripts/check.py\n' > .git/hooks/pre-push && chmod +x .git/hooks/pre-push
  ```

يثبّت `pip install "simplicio-loop[dev]"` اعتماد `pytest` الإلزامي لـ `scripts/check.py`.

---

## ⭐ سجل النجوم

[![Star History Chart](https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-loop&type=Date)](https://star-history.com/#wesleysimplicio/simplicio-loop&Date)

---

## 📄 الترخيص

MIT

</div>

<!-- simplicio-loop:github-comment-coordination:v1 -->
## 🌐 تنسيق التعليقات عبر GitHub بين بيئات التشغيل

يمكن تشغيل `simplicio-loop` بالتزامن داخل Claude Code وCodex وCursor وGemini وHermes. عند ربط التشغيل بمشكلة في GitHub، ينشر تحديثات دورة الحياة بشكل idempotent في التعليق الأساسي: المطالبة والتخطيط والتقدم والأدلة وطلب الدمج والإغلاق. وهكذا تتعاون الوكلاء على أجهزة مختلفة عبر سلسلة تعليقات GitHub نفسها دون نظام ملفات محلي مشترك.

```powershell
pwsh scripts/install.ps1 claude -Global
pwsh scripts/install.ps1 codex -Global
pwsh scripts/install.ps1 cursor -Global
pwsh scripts/install.ps1 gemini -Global
pwsh scripts/install.ps1 hermes -Global   # اسم قديم لـ simplicio_agent
```

تبقى الطوابير المحلية والتأجير ومساحات العمل ونبضات الحياة والأدلة فعّالة على كل جهاز؛ وتعليقات GitHub هي إسقاط التنسيق المشترك. هذا التدفق خاص بـ GitHub؛ لا تُرسل التعليقات إلى Jira أو Azure DevOps أو متتبعات أخرى. عند تعذر GitHub يستمر التشغيل محلياً ويسجل فشل المزامنة دون اختلاق تأكيد بعيد. استخدم نفس `source_issue` مع صلاحية GitHub لكل بيئة.

# simplicio-fast

[English](../README.md) · **العربية**

سياق دلالي ثنائي وتزايدي ومربوط بالذاكرة لوكلاء البرمجيات.

تنتج ملفات المصدر العادية ذاكرة مشتقة `.sfast` تُقرأ عبر `mmap`. يعاد استخدام الملفات غير
المتغيرة بواسطة SHA-256، وتبقى الشفرة المصدرية مصدر الحقيقة الوحيد.

في تجربة POC تضم 500 ملف و1,500 رمز، كان الاستعلام أسرع بنحو 23 مرة واستخدم CPU أقل بنسبة
95.65%. هذه نتيجة مقاسة وليست ضماناً عاماً لكل بيئة.

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast && python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

يعد `simplicio-mapper` إلزامياً في مسار الوكلاء الرسمي ويظل منتج ContextGraph القياسي.
راجع [AGENTS.md](../AGENTS.md) و[README الكامل](../README.md).

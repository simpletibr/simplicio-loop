# simplicio-fast

[English](../README.md) · **हिन्दी**

सॉफ्टवेयर एजेंटों के लिए बाइनरी, इन्क्रीमेंटल और मेमोरी-मैप्ड सिमेंटिक कॉन्टेक्स्ट।

सामान्य सोर्स फ़ाइलों से `.sfast` व्युत्पन्न कैश बनता है और उसे `mmap` से पढ़ा जाता है।
बिना बदली फ़ाइलें SHA-256 द्वारा पुनः उपयोग होती हैं; सोर्स कोड ही सत्य का एकमात्र स्रोत रहता है।

500 फ़ाइल और 1,500 सिंबल वाली POC में क्वेरी लगभग 23 गुना तेज़ थी और 95.65% कम CPU उपयोग हुआ।
यह मापा हुआ परिणाम है, हर वातावरण की गारंटी नहीं।

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast && python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

आधिकारिक एजेंट प्रवाह में `simplicio-mapper` अनिवार्य है और canonical ContextGraph बनाता है।
[AGENTS.md](../AGENTS.md) और [पूरा README](../README.md) देखें।

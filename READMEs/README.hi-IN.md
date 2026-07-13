# simplicio-mapper

> किसी रिपॉज़िटरी को लोगों और AI एजेंटों के लिए सीमित, क्वेरी-योग्य और भरोसेमंद संदर्भ में बदलें।

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/)

[कैनोनिकल README और सभी भाषाएँ](../README.md)

<p align="center"><img src="../assets/llm-project-mapper-hero.png" alt="रिपॉज़िटरी साक्ष्य-समर्थित सीमित संदर्भ में बदलती हुई" width="100%"></p>

`simplicio-mapper` कोडबेस को `.simplicio/` में संस्करणित आर्टिफैक्ट में बदलता है: आर्किटेक्चर, प्रतीक, फ्लो, नियम, टेस्ट और कार्य-आधारित संदर्भ पैक। यह Simplicio इकोसिस्टम का मैपिंग इंजन है—रिपॉज़िटरी ज्ञान को निरीक्षण के लिए छोटा और ऑडिट के लिए स्पष्ट बनाता है।

## त्वरित शुरुआत

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "प्रमाणीकरण फ्लो का पता लगाएँ" --token-budget 1200 --json
```

## यह अलग क्यों है

- **सीमित retrieval:** `handoff` और `orient` पूरी रिपॉज़िटरी को चुपचाप prompt में डालने के बजाय प्रासंगिकता, कवरेज, टोकन बजट, दंड और fidelity दिखाते हैं।
- **बदलाव-सचेत संदर्भ:** `sync`, `history`, `diff` और `delta` बदलावों तथा सत्रों के बीच ContextGraph को अद्यतन रखते हैं।
- **साक्ष्य अनुबंध:** सार्वजनिक schema, validation, confidence tags, behavioral receipts और certificates मापे गए तथ्यों को असमर्थित दावों से अलग करते हैं।
- **उपयोगी आउटपुट:** प्रोजेक्ट मैप, आर्किटेक्चर दस्तावेज़, endpoint और स्क्रीन सूची, फ्लो, बिज़नेस नियम, onboarding survey और graph query।

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

Python पैकेज कैनोनिकल मैपिंग इंजन है। npm का [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) पूरक प्रोजेक्ट स्टार्टर है।

[दस्तावेज़ साइट](https://wesleysimplicio.github.io/simplicio-mapper/), [contracts](../contracts/), [integration guide](../SIMPLICIO_INTEGRATION.md) और [v0.23.1 release](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1) देखें। लाइसेंस [MIT](../LICENSE) है।

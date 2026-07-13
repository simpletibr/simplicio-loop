# simplicio-mapper

> Tukarkan repositori kepada konteks yang bersempadan, boleh ditanya dan boleh dipercayai untuk manusia serta ejen AI.

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/)

[README kanonik dan semua bahasa](../README.md)

<p align="center"><img src="../assets/llm-project-mapper-hero.png" alt="Repositori menjadi konteks bersempadan yang disokong bukti" width="100%"></p>

`simplicio-mapper` menukarkan pangkalan kod kepada artifak berversi dalam `.simplicio/`: seni bina, simbol, aliran, peraturan, ujian dan pek konteks berasaskan tugasan. Ia ialah enjin pemetaan ekosistem Simplicio — pengetahuan repositori cukup kecil untuk diperiksa dan cukup jelas untuk diaudit.

## Mula pantas

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "jejaki aliran pengesahan" --token-budget 1200 --json
```

## Perbezaannya

- **Pemerolehan bersempadan:** `handoff` dan `orient` melaporkan kerelevanan, liputan, bajet token, penalti dan kesetiaan, bukan memasukkan seluruh repositori secara senyap ke dalam prompt.
- **Konteks peka perubahan:** `sync`, `history`, `diff` dan `delta` mengekalkan ContextGraph merentas perubahan dan sesi.
- **Kontrak bukti:** skema awam, pengesahan, tag keyakinan, resit tingkah laku dan sijil membezakan fakta yang diukur daripada tuntutan tanpa sokongan.
- **Output praktikal:** peta projek, dokumen seni bina, inventori endpoint dan skrin, aliran, peraturan perniagaan, tinjauan onboarding dan pertanyaan graf.

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

Pakej Python ialah enjin pemetaan kanonik. Pakej npm [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) ialah starter projek pelengkap.

Lihat [laman dokumentasi](https://wesleysimplicio.github.io/simplicio-mapper/), [kontrak](../contracts/), [panduan integrasi](../SIMPLICIO_INTEGRATION.md) dan [keluaran v0.23.1](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1). Dilesenkan di bawah [MIT](../LICENSE).

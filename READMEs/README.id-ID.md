# simplicio-mapper

> Ubah repositori menjadi konteks terbatas, dapat dikueri, dan tepercaya untuk manusia maupun agen AI.

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/)

[README kanonis dan semua bahasa](../README.md)

<p align="center"><img src="../assets/llm-project-mapper-hero.png" alt="Repositori menjadi konteks terbatas yang didukung bukti" width="100%"></p>

`simplicio-mapper` mengubah basis kode menjadi artefak berversi di `.simplicio/`: arsitektur, simbol, alur, aturan, pengujian, dan paket konteks berbasis tugas. Ini adalah mesin pemetaan ekosistem Simplicio: pengetahuan repositori cukup kecil untuk diperiksa dan cukup eksplisit untuk diaudit.

## Mulai cepat

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "telusuri alur autentikasi" --token-budget 1200 --json
```

## Pembeda utama

- **Pengambilan terbatas:** `handoff` dan `orient` melaporkan relevansi, cakupan, anggaran token, penalti, dan fidelitas, bukan diam-diam memasukkan seluruh repositori ke prompt.
- **Konteks sadar perubahan:** `sync`, `history`, `diff`, dan `delta` menjaga ContextGraph lintas perubahan dan sesi.
- **Kontrak bukti:** skema publik, validasi, tag kepercayaan, tanda terima perilaku, dan sertifikat membedakan fakta terukur dari klaim tanpa dukungan.
- **Keluaran praktis:** peta proyek, dokumen arsitektur, inventaris endpoint dan layar, alur, aturan bisnis, survei onboarding, dan kueri graf.

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

Paket Python adalah mesin pemetaan kanonis. Paket npm [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) adalah starter proyek pelengkap.

Lihat [situs dokumentasi](https://wesleysimplicio.github.io/simplicio-mapper/), [kontrak](../contracts/), [panduan integrasi](../SIMPLICIO_INTEGRATION.md), dan [rilis v0.23.1](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1). Berlisensi [MIT](../LICENSE).

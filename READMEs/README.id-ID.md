<h1 align="center">simplicio-mapper</h1>

<p align="center">
  <strong>Memetakan repo apa pun menjadi konteks yang bisa dibaca AI: project map, precedent index, inventaris arsitektur, indeks simbol, call graph, dan docs.</strong><br />
  <em>Perintah tetap dalam bahasa Inggris agar bisa disalin persis.</em>
</p>

<p align="center">
<a href="https://github.com/wesleysimplicio/simplicio-mapper/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/wesleysimplicio/simplicio-mapper?style=flat-square" /></a>
<a href="https://pypi.org/project/simplicio-mapper/"><img alt="PyPI" src="https://img.shields.io/pypi/v/simplicio-mapper.svg?style=flat-square" /></a>
<a href="https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper"><img alt="npm" src="https://img.shields.io/npm/v/%40wesleysimplicio%2Fllm-project-mapper.svg?style=flat-square" /></a>
<a href="../LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-yellow?style=flat-square" /></a>
</p>

<p align="center">
<a href="../README.md">English</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.es-ES.md">Español</a> | <a href="README.ja-JP.md">日本語</a> | <a href="README.ko-KR.md">한국어</a> | <a href="README.zh-CN.md">简体中文</a> | <a href="README.it-IT.md">Italiano</a> | <a href="README.fr-FR.md">Français</a> | <a href="README.ru-RU.md">Русский</a> | <a href="README.pl-PL.md">Polski</a> | <a href="README.hi-IN.md">हिन्दी</a> | <a href="README.ar-SA.md">العربية</a> | <a href="README.he-IL.md">עברית</a> | <a href="README.ms-MY.md">Bahasa Melayu</a> | <a href="README.id-ID.md">Bahasa Indonesia</a>
</p>

<p align="center">
  <img src="../assets/llm-project-mapper-hero.png" alt="simplicio-mapper preview" width="860" />
</p>

<p align="center">
  <img src="../assets/overlay-install.svg" alt="Overlay install flow" width="860" />
</p>

---

## Ringkasnya

Memetakan repo apa pun menjadi konteks yang bisa dibaca AI: project map, precedent index, inventaris arsitektur, indeks simbol, call graph, dan docs.

## DNA proyek

Halaman lokal ini mempertahankan jalur cepat. Panduan teknis lengkap yang dipulihkan ada di README utama agar suara asli dan detail operasional proyek tetap hidup.

- Full restored guide: [../README.md](../README.md)
- Local project note: simplicio-mapper is the map before the plan. Its value is not only the artifact names; it is the habit it teaches agents: read the repository, preserve shared context, expose architecture, and make future work cheaper. The original guide explained that operational philosophy in detail, so this refresh restores it under the sharper global landing page.

## Mulai cepat

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper endpoints ./web --against ./api --json
```

## Apa yang dilakukan

- Generates versioned .simplicio artifacts agents can read before planning.
- Works as both Python CLI and npm starter package.
- Builds architecture, symbol and call graph artifacts without forcing a framework.
- Exports markdown docs for wiki/review workflows while keeping remote publishing opt-in.

## Mengapa README ini dibuat agar mudah menarik perhatian

- janji nilai yang jelas di layar pertama
- tautan bahasa sebelum instalasi
- badge dan hero untuk kepercayaan
- quick start siap salin
- bukti sebelum detail panjang
- grafik bintang sebagai social proof

## Cara kerjanya

```mermaid
flowchart LR
  mapper["simplicio-mapper
repo context"] --> current["simplicio-mapper
this project"]
  prompt["simplicio-prompt
reasoning runtime"] --> current
  current --> evidence["validated evidence
tests, docs, screenshots"]
  current --> sprint["simplicio-sprint
delivery loop"]
```

## Bukti dan validasi

- Current local mapper version is 0.7.x with background indexing and docs-only modes.
- This repo is the canonical standard for visible, versioned .simplicio artifacts.
- It now carries the README globalization standard used across this workspace.

## Ekosistem Simplicio

- [simplicio-mapper](https://github.com/wesleysimplicio/simplicio-mapper) supplies repo context before interpretation.
- [simplicio-cli](https://github.com/wesleysimplicio/simplicio-dev-cli) executes focused code tasks with verification.
- [simplicio-prompt](https://github.com/wesleysimplicio/simplicio-prompt) provides fan-out and consensus runtime patterns.
- [simplicio-sprint](https://github.com/wesleysimplicio/simplicio-sprint) turns cards into draft PR delivery loops.

## Standar dokumentasi

- [SIMPLICIO_INTEGRATION.md](../SIMPLICIO_INTEGRATION.md)
- [docs/readme-globalization-standard.md](../docs/readme-globalization-standard.md)

## Riwayat bintang

<a href="https://www.star-history.com/#wesleysimplicio/simplicio-mapper&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-mapper&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-mapper&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-mapper&type=Date" />
  </picture>
</a>

## Lisensi

MIT. See [LICENSE](../LICENSE).

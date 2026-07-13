<h1 align="center">simplicio-cli</h1>

<p align="center">
  <strong>Convierte una tarea de una línea en un cambio verificado: contexto del mapper, contrato de seis capas, diff, prueba y evidencia.</strong><br />
  <em>Los comandos se mantienen en inglés para copiarlos exactamente.</em>
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
  <img src="../output/imagegen/simplicio-cli-readme-hero-web.png" alt="pipeline de ejecución de simplicio-dev-cli" width="860" />
</p>
<p align="center">
  <img src="../output/imagegen/simplicio-cli-proof-receipt.png" alt="diff, pruebas y recibo de verificación" width="760" />
</p>

---

## Resumen directo

Convierte una tarea de una línea en un cambio verificado: contexto del mapper, contrato de seis capas, diff, prueba y evidencia.

## ADN del proyecto

Esta pagina localizada mantiene el camino rapido. La guia tecnica restaurada vive en el README principal para conservar la voz original y los detalles operativos del proyecto.

- Full restored guide: [../README.md](../README.md)

## Inicio rápido

```bash
pip install -U simplicio-cli
simplicio-py detect "hide the Delete button for non-admins"
simplicio-py task "hide the Delete button for non-admins"
```

## Qué hace

- Recibe una tarea concreta desde el runtime, un agente o la CLI.
- Carga el contexto de `simplicio-mapper` y los precedentes relevantes antes de editar.
- Aplica un diff acotado, ejecuta las pruebas y registra un recibo de verificación inspeccionable.
- Deja la orquestación, la elección del modelo y el estado duradero del bucle a las capas de Simplicio.

## Por qué este README está diseñado para ganar atención

- promesa clara en la primera pantalla
- idiomas antes de instalar
- badges y hero visual
- quick start copiable
- prueba antes de detalles largos
- gráfico de estrellas

## Cómo funciona

```mermaid
flowchart LR
  task["decided task"] --> mapper["simplicio-mapper
repo context"]
  mapper --> operator["simplicio-dev-cli
focused operator"]
  operator --> diff["bounded diff"]
  operator --> tests["tests"]
  diff --> receipt["evidence receipt"]
  tests --> receipt
```

## Prueba y validación

- Benchmark docs compare plain prompting vs the Simplicio contract on real code tasks.
- Package metadata tests pin ecosystem dependency floors.
- The CLI is the executor layer used by SendSprint and SimplicioCode flows.

## Ecosistema Simplicio

- [simplicio-mapper](https://github.com/wesleysimplicio/simplicio-mapper) supplies repo context before interpretation.
- [simplicio-cli](https://github.com/wesleysimplicio/simplicio-dev-cli) executes focused code tasks with verification.
- [simplicio-prompt](https://github.com/wesleysimplicio/simplicio-prompt) provides fan-out and consensus runtime patterns.
- [simplicio-sprint](https://github.com/wesleysimplicio/simplicio-sprint) turns cards into draft PR delivery loops.

## Estándar de documentación

- [docs/PYTHON_PACKAGE_INTERDEPENDENCE.md](../docs/PYTHON_PACKAGE_INTERDEPENDENCE.md)
- [docs/LLM_USAGE_POLICY.md](../docs/LLM_USAGE_POLICY.md)
- [docs/readme-globalization-standard.md](../docs/readme-globalization-standard.md)

## Historial de estrellas

<a href="https://www.star-history.com/#wesleysimplicio/simplicio-dev-cli&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-dev-cli&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-dev-cli&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=wesleysimplicio/simplicio-dev-cli&type=Date" />
  </picture>
</a>

## Licencia

MIT. See [LICENSE](../LICENSE).

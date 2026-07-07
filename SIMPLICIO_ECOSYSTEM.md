# simplicio-mapper no Ecossistema Simplicio

<!-- simplicio-generated-doc: SIMPLICIO_ECOSYSTEM.md -->
<!-- GENERATED FILE — do not hand-edit. Run `python3 scripts/generate-ecosystem-doc.py` to refresh it, or `python3 scripts/generate-ecosystem-doc.py --check` to verify it is fresh (wired into CI via .github/workflows/python-ci.yml). Source of truth: pyproject.toml / package.json versions plus scripts/ecosystem-consumers.json (consumer-constraints fixture; see scripts/README.md for its schema). -->

## Quem depende deste repo
- [simplicio-dev-cli](https://github.com/wesleysimplicio/simplicio-dev-cli) >=0.15.0
- [simplicio-loop](https://github.com/wesleysimplicio/simplicio-loop) >=0.15.0

## De quem este repo depende
Nenhum outro repositório Simplicio. `simplicio-mapper` é a **base independente** do grafo do ecossistema Simplicio: nada nele exige outro pacote Simplicio para rodar, e todo o resto do ecossistema (simplicio-dev-cli, simplicio-loop, simplicio-runtime) consome os artefatos que ele produz.

## Versão atual
0.15.0 (lido de `pyproject.toml` e `package.json`)

## Versão mínima esperada pelos dependentes
| Consumidor | Constraint mínima | Status |
|---|---|---|
| simplicio-dev-cli | >=0.15.0 | em dia com a versão atual |
| simplicio-loop | >=0.15.0 | em dia com a versão atual |

---

_Generated: 2026-07-07T04:19:54Z_

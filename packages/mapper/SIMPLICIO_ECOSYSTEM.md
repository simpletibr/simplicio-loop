# simplicio-mapper no Ecossistema Simplicio

<!-- simplicio-generated-doc: SIMPLICIO_ECOSYSTEM.md -->
<!-- GENERATED FILE — do not hand-edit. Run `python3 scripts/generate-ecosystem-doc.py` to refresh it, or `python3 scripts/generate-ecosystem-doc.py --check` to verify it is fresh (wired into CI via .github/workflows/python-ci.yml). Source of truth: pyproject.toml / package.json versions plus scripts/ecosystem-consumers.json (consumer-constraints fixture; see scripts/README.md for its schema). -->

## Quem depende deste repo
- [simplicio-dev-cli](https://github.com/wesleysimplicio/simplicio-dev-cli) >=0.15.0
- [simplicio-loop](https://github.com/wesleysimplicio/simplicio-loop) >=0.15.0

## De quem este repo depende
Nenhum outro repositório Simplicio. `simplicio-mapper` é a **base independente** do grafo do ecossistema Simplicio: nada nele exige outro pacote Simplicio para rodar, e todo o resto do ecossistema (simplicio-dev-cli, simplicio-loop, simplicio-runtime) consome os artefatos que ele produz.

## Dogfooding
Este repo aplica o próprio mapper em si mesmo, de forma explícita e reproduzível — não é só um efeito colateral implícito do desenvolvimento. `python3 scripts/dogfood.py` roda `simplicio-mapper index . --json` (o CLI real, empacotado) contra este repositório, valida o resultado contra o contrato versionado (`contracts/mapper-artifacts/v1/`, issue #157), e publica um snapshot estável em [`examples/ecosystem-dogfood/`](examples/ecosystem-dogfood/README.md) (issue #165) — `project-map.json`, `precedent-index.json` e `architecture-inventory.json` reais deste repo, não uma fixture de brinquedo. `python3 scripts/dogfood.py --check` verifica o snapshot sem regenerar. A perna cross-repo da receita completa (mapper + simplicio-dev-cli + simplicio-loop juntos) fica documentada, não executada, no README daquele diretório — precisa de checkouts separados dos três repos.

## Versão atual
0.15.0 (lido de `pyproject.toml` e `package.json`)

## Versão mínima esperada pelos dependentes
| Consumidor | Constraint mínima | Status |
|---|---|---|
| simplicio-dev-cli | >=0.15.0 | em dia com a versão atual |
| simplicio-loop | >=0.15.0 | em dia com a versão atual |

---

_Generated: 2026-07-07T06:31:09Z_

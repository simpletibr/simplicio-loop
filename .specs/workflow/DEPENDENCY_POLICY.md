# Política de Dependências entre Projetos Simplicio

Status: aprovada — vigente a partir de 2026-05-28 (issue #21).

## Projetos do ecossistema

| Pacote | Repo | Ecossistema | Versão atual |
|---|---|---|---|
| `simplicio-cli` | `wesleysimplicio/simplicio-dev-cli` | PyPI | 0.4.0 |
| `simplicio-mapper` | `wesleysimplicio/simplicio-mapper` | PyPI + npm | 0.5.0 |
| `simplicio-prompt` | `wesleysimplicio/simplicio-prompt` | PyPI + npm | 1.7.0 |
| `simplicio-sprint` | `wesleysimplicio/simplicio-sprint` | PyPI | (verificar) |
| `simplicio-core` | `wesleysimplicio/simplicio-dev-cli/rust/simplicio-core` | Local extension (futuro PyPI) | 0.1.0 |

## Princípios

1. **Semver consistente.** Todos os pacotes seguem
   [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (`MAJOR.MINOR.PATCH`).
2. **Pin por floor, não por exato.** Dependências entre projetos do
   ecossistema usam o operador `>=` na versão mais recente publicada no
   momento do release (`simplicio-mapper>=0.5.0`, não `==0.5.0`).
   Compatibilidade futura inclusiva por padrão.
3. **Sem dependência cíclica.** Um pacote NUNCA depende de outro pacote
   que dependa dele transitivamente. A ordem do grafo é:
   `simplicio-mapper → simplicio-prompt → simplicio-cli`.
4. **Atualização ativa.** Quando um pacote do ecossistema lança nova
   versão, todos os dependentes devem bumpar o floor em até **15 dias**
   se a versão nova for backward-compatible (minor / patch). Releases
   major exigem PR de migração com nota no CHANGELOG.

## Processo de release-sync

Quando publicar uma nova versão de um pacote do ecossistema, o autor
**na mesma janela**:

1. Bumpa `version` no `pyproject.toml` (e `package.json` para os pacotes
   duplos npm).
2. Atualiza `CHANGELOG.md` com a seção `[X.Y.Z]` (Added / Changed /
   Fixed / Removed).
3. Constrói + publica:
   - PyPI: `python -m build && twine upload dist/*`
   - npm (quando aplicável): `npm publish --access public`
4. Cria a tag `vX.Y.Z` e empurra (`git push origin vX.Y.Z`).
5. Cria GitHub Release apontando para a tag, com o body = seção
   `[X.Y.Z]` do CHANGELOG.
6. Abre um issue + PR em cada pacote dependente bumpando o floor
   (ex.: `simplicio-cli` recebe `simplicio-mapper>=0.6.0`).

## Verificação local

- Antes de cada PR para `main`, compare as versões pinadas em
  `pyproject.toml` contra a última versão pública no PyPI de cada dependência
  do ecossistema. Se o floor estiver atrasado em pelo menos 1 minor, abra ou
  atualize uma issue `chore(deps): bump <pkg> floor`.
- `.github/dependabot.yml` configura updates automáticos para
  `pip` (deps Python) e `cargo` (crate Rust), com schedule semanal
  e auto-merge de patches via `dependabot/auto-merge`. Updates major
  ficam manuais.

## Quando relaxar a política

A regra de 15 dias pode ser estendida quando:

- A release upstream introduziu uma regressão conhecida (registrar no
  issue de bump com link para o issue upstream).
- O downstream está em meio a um refactor maior que tornaria o bump
  pouco produtivo. Nesse caso, anotar no `CHANGELOG.md` `Known: held at
  <pkg> X.Y` e abrir um issue de tracking.

## Histórico

- 2026-05-28 — política inicial criada via issue #21.

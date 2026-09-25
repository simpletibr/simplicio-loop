# ADR-004: `Separar conteúdo de template (starter) e conteúdo de produto via manifest`

> Resolve https://github.com/wesleysimplicio/simplicio-mapper/issues/140 (F9 da épica #131)

---

## Status

`Aceito`

---

## Data

`2026-07-02`

---

## Autores

- `Claude (agent) — a pedido de wesleysimplicio`

---

## Contexto

Este repositório tem dois papéis simultâneos sobre o mesmo conjunto de arquivos:

1. **Produto** — o mapper (código, specs reais, backlog real do simplicio-mapper).
2. **Template/starter** — `bin/cli.js` (`TEMPLATE_PATHS`, `bin/cli.js:49-70`) copia diretórios
   inteiros da raiz (`.specs/`, `.skills/`, `.agents/`, `.github/`, `docs/`, `AGENTS.md`,
   `CLAUDE.md`, ...) para qualquer projeto host que rode `npx @wesleysimplicio/llm-project-mapper`.

Consequência observada (dogfood, ver issue #131): `.specs/sprints/BACKLOG.md` da raiz
continha conteúdo de exemplo genérico não relacionado a este produto (`"Implementar
autenticação por email + senha"`, um placeholder literal do token DOMAIN não resolvido),
enquanto o `AGENTS.md` do próprio repo afirma que esse arquivo é "a fonte da verdade de
pendências do produto". Sem um jeito de distinguir "isto é payload de exemplo para o host"
de "isto é conteúdo real do simplicio-mapper", qualquer verificação futura de spec-drift
(issue #138, F7) teria que carregar uma whitelist ad-hoc — ou pior, ficaria cega para o
próprio repo.

## Decisão

Adotamos a **Opção B** (manifest de classificação), não a Opção A (mover tudo para um
diretório `template/` dedicado):

- Criamos `template-manifest.json` na raiz do repo com três listas:
  - `template_root_paths`: espelha `TEMPLATE_PATHS` do `bin/cli.js` — o payload que é
    copiado byte-a-byte para o host.
  - `product_paths`: subconjunto de `template_root_paths` que **também** carrega conteúdo
    real e específico deste produto (ex.: `.specs/product/VISION.md` descreve a visão do
    simplicio-mapper e serve de exemplo bem preenchido para o `INIT.md` refinar no host).
  - `generic_placeholder_paths`: subconjunto cujo propósito **é** conter placeholders
    genéricos (`ADR-template.md`, `task-template.md`, `sprint-01/*` de exemplo) — nunca
    deve virar finding de drift.
- `.specs/sprints/BACKLOG.md` deixa de ser exemplo genérico e passa a listar o backlog
  real deste produto (as capacidades F1–F10 da épica #131, rastreadas como issues do
  GitHub).
- O comando `drift` (F7, issue #138) consulta este manifest: só investiga placeholder
  em arquivos que não estejam em `generic_placeholder_paths`, e nunca em arquivos fora de
  `template_root_paths`/`product_paths`.

Escopo: só classificação e o fix do `BACKLOG.md`. Não move nenhum arquivo de lugar —
`bin/cli.js`, `bootstrap.sh` e `bootstrap.ps1` continuam funcionando sem alteração de
comportamento para o usuário final do `npx`.

## Consequências

### Positivas (+)

- Zero risco de regressão no fluxo `npx @wesleysimplicio/llm-project-mapper` (nenhum path
  copiado muda de lugar).
- `drift` (F7) consegue rodar no próprio repo sem whitelist hardcoded.
- Doc novo do produto (ex.: `.specs/product/flow-documentation-spec.md`) só precisa de uma
  linha nova em `product_paths` para ficar isento de falso-positivo de drift.
- `BACKLOG.md` do produto agora reflete a realidade (rastreável via GitHub Issues).

### Negativas (-)

- Manutenção manual: todo doc novo que "mora" em `.specs/`/`docs/` mas é conteúdo real do
  produto precisa ser adicionado a `product_paths` — se esquecido, `drift` pode reportar um
  falso-positivo de placeholder (mitigado: o critério primário de placeholder é a presença
  de token `<...>` literal, que não deveria aparecer em doc terminado de qualquer forma).
- Continua existindo ambiguidade de *donidade* para humanos que abrem o repo pela primeira
  vez — resolvida por este ADR e pelo comentário no topo do `template-manifest.json`, não
  pela estrutura de pastas em si.

### Neutras / observações

- A Opção A (diretório `template/` dedicado) permanece disponível como evolução futura se
  o custo de manutenção do manifest crescer; este ADR não a descarta, só a adia.

## Alternativas consideradas

### Alternativa A — diretório `template/` dedicado

- Resumo: mover todo `TEMPLATE_PATHS` para `template/`, deixar a raiz 100% produto.
- Por que foi descartada (por ora): exige reescrever `bin/cli.js` (`copyTemplate`),
  `bootstrap.sh`, `bootstrap.ps1`, `INSTALL.md` e testes E2E de paridade do payload
  copiado (`tests/unit/overlay-docs.test.js` e afins) no mesmo ciclo — risco alto para
  o caminho crítico de instalação (`npx`) sem tempo de validação manual em múltiplos SOs.
  Fica registrada como opção B→A de evolução futura se necessário.

### Alternativa C — repositórios separados (starter vs mapper)

- Resumo: um repo só para o template, outro só para o produto.
- Por que foi descartada: quebra a promessa "um repo, um `npx`" do README e duplica
  release/CI; overkill para o problema real (classificação, não hospedagem).

## Critério de revisão

- Se `product_paths`/`generic_placeholder_paths` ficarem maiores que ~40 entradas cada
  (sinal de que a manutenção manual não escala), revisitar para a Alternativa A.
- Se `drift` (F7) reportar falso-positivo recorrente por manifest desatualizado em mais de
  2 PRs seguidos, revisitar o mecanismo de classificação (ex.: automatizar via convenção de
  nome de arquivo em vez de lista manual).

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-mapper/issues/140
- Epic: https://github.com/wesleysimplicio/simplicio-mapper/issues/131
- Spec: [`.specs/product/flow-documentation-spec.md`](../product/flow-documentation-spec.md)
- Documentos relacionados: `[DESIGN](./DESIGN.md)`, `[PATTERNS](./PATTERNS.md)`
- Manifest: `../../template-manifest.json`

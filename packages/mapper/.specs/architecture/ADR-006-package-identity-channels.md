# ADR-006: `Identidade única do pacote (nome canônico, canal live vs legado, fate do alias)`

> Resolve https://github.com/wesleysimplicio/simplicio-mapper/issues/160
> (formaliza uma decisão que já existia em prosa solta desde a issue #87 —
> ver `README.md` linha ~113 antes desta ADR)

---

## Status

`Aceito`

---

## Data

`2026-07-07`

---

## Autores

- `Claude (agent) — a pedido de wesleysimplicio`

---

## Contexto

Este produto é publicado sob **três identidades** que não bateram entre si:

1. O **repositório** GitHub: `wesleysimplicio/simplicio-mapper` (nome atual).
2. O pacote **PyPI**: `simplicio-mapper` (nome atual, alinhado ao repo).
3. O pacote **npm**: `@wesleysimplicio/llm-project-mapper` (nome antigo,
   herdado de antes do rename do produto para "simplicio-mapper").

Além do nome, o pacote **cobre duas capacidades distintas** que este ADR
precisa distinguir com cuidado (misturar as duas levaria a uma
recomendação errada de "depreciar o npm inteiro"):

- **(a) Scaffolder/starter installer** — `npx @wesleysimplicio/llm-project-mapper`
  instala o starter pack (`AGENTS.md`, `.skills/`, `.specs/`, etc.) num
  projeto host. É **Node-only**, não tem equivalente PyPI, e continua
  **ativamente mantido** — não é candidato a depreciação.
- **(b) O engine do mapper** — os comandos `map`/`update`/`index`/etc. que
  produzem `.simplicio/*.json`. Historicamente existiam **duas
  implementações paralelas**: o pacote `simplicio_mapper` (Python) e
  `bin/mapper-artifacts.js` (Node, dentro do mesmo pacote npm). A ADR-005
  (issue #158) já tornou Python a fonte de verdade pra este engine
  especificamente, com Node fazendo *shim* pra ele quando disponível.

`package.json`'s `homepage`/`repository`/`bugs` ainda apontam pro nome de
repo antigo (`llm-project-mapper`), enquanto `pyproject.toml`'s `[project.urls]`
já aponta pro nome atual (`simplicio-mapper`) — um mismatch mecânico simples
de corrigir, resolvido junto com esta ADR.

---

## Decisão

### Nome canônico público

**`simplicio-mapper`** é o nome canônico do produto em toda comunicação nova
(docs, título do README, badges, texto de divulgação). Os dois console
scripts (`simplicio-mapper` e `llm-project-mapper`) continuam instalados em
ambos os canais — ver "fate do alias" abaixo.

### Canal live vs legado — só se aplica à capacidade (b), o engine

- **Canal live**: **PyPI `simplicio-mapper`**. É onde o engine do mapper
  (`map`/`update`/`index`/`ask`/`drift`/etc.) recebe feature nova primeiro.
  `pip install -U simplicio-mapper` é a recomendação padrão pra quem só
  quer o engine.
- **Canal legado/congelado (só a cópia Node do engine, não o pacote npm
  inteiro)**: `bin/mapper-artifacts.js`/`bin/map.js` dentro do pacote npm
  `@wesleysimplicio/llm-project-mapper` continuam existindo apenas como
  **fallback pra host sem Python** (ADR-005) — não recebem feature nova
  antes do Python; mudanças ali são só pra manter esse fallback correto.
- **O pacote npm `@wesleysimplicio/llm-project-mapper` em si NÃO está
  depreciado** — ele continua sendo o único jeito de rodar o scaffolder
  (capacidade (a), que não tem equivalente Python) e segue recebendo
  releases regulares acompanhando a versão do produto (`0.15.0` hoje, ver
  `scripts/check-version-sync.js`). "Legado" se aplica estritamente à cópia
  Node do engine do mapper dentro dele, não ao pacote como um todo.

### Fate do alias `llm-project-mapper`

**Mantido, sem prazo de remoção.** Dois lugares distintos:

1. **Nome do pacote npm** (`@wesleysimplicio/llm-project-mapper`) e seu
   `bin` `llm-project-mapper` — renomear quebraria todo `npx
   @wesleysimplicio/llm-project-mapper` já publicado em docs, vídeos,
   badges e instalações existentes por aí. Custo de rename > benefício de
   nome bonito. **Recomendação: manter indefinidamente**, sem timeline de
   depreciação — o "nome canônico" vive na documentação/branding
   (`simplicio-mapper`), não precisa forçar o nome do pacote a acompanhar.
2. **Console script Python** `llm-project-mapper` (alias de
   `simplicio-mapper` em `pyproject.toml` `[project.scripts]`) — mantido
   por compatibilidade com quem vem de docs/tutoriais antigos que usavam
   esse nome. **Recomendação de timeline**: revisitar na próxima *major*
   bump do produto (nenhuma major planejada hoje) — não remover
   preventivamente sem dado real de uso, já que este projeto não tem
   telemetria de downloads por script. Até lá, zero custo de manutenção
   pra manter (é uma linha em `pyproject.toml`).

### O que muda mecanicamente junto com esta ADR

- `package.json`'s `homepage`/`repository.url`/`bugs.url` corrigidos para
  `wesleysimplicio/simplicio-mapper` (batendo com `pyproject.toml`'s
  `[project.urls]`, que já estava certo).
- Nota de depreciação/redirecionamento no topo do README (visível pra quem
  chega via npm) explicando a distinção (a)/(b) acima em vez de um "isto
  está depreciado" genérico e impreciso.
- Uma seção única "Install matrix" consolidando "quero X → instalo Y" (ver
  README.md).

---

## Consequências

### Positivas (+)

- Elimina o mismatch mecânico de URL entre os dois manifestos de pacote.
- Reduz confusão real: sem esta ADR, alguém lendo "PyPI é o canal live"
  concluiria (errado) que o pacote npm inteiro está sendo descontinuado,
  quando só a cópia Node do engine está congelada — o scaffolder continua
  vivo e é Node-only por natureza.
- Uma única seção de instalação evita a pergunta recorrente "eu instalo via
  pip ou via npm?" — a resposta passa a depender do que a pessoa quer
  (scaffolder vs engine), não de uma escolha arbitrária.

### Negativas (-)

- Manter dois nomes de pacote (`simplicio-mapper` no PyPI,
  `@wesleysimplicio/llm-project-mapper` no npm) é uma fonte permanente de
  "por que os nomes são diferentes?" pra quem chega de fora — mitigado
  pela nota de branding no README, não eliminado.
- Nenhuma telemetria real existe pra validar quando o alias
  `llm-project-mapper` (console script Python) deixa de ser usado — a
  decisão de "manter indefinidamente" é conservadora por falta de dado,
  não por certeza de que ainda é necessário.

### Neutras / observações

- Esta ADR não move nem renomeia nenhum arquivo de código — é
  puramente uma decisão de identidade/documentação + o fix mecânico de URL.

---

## Alternativas consideradas

### Alternativa A — Unificar os dois nomes de pacote (renomear o pacote npm para `@wesleysimplicio/simplicio-mapper`)
- Mais "limpo" no papel, mas quebra toda instalação/documentação/vídeo
  existente que usa `@wesleysimplicio/llm-project-mapper`; exigiria
  depreciar o pacote antigo no registry (mensagem de depreciação do npm) e
  manter os dois publicados em paralelo por uma janela de transição.
- Descartada por agora: custo de migração real > benefício de nome, dado
  que o nome antigo já convive bem com o nome canônico via branding no
  README (não é ambiguidade técnica, é só um nome de pacote diferente do
  nome do produto — problema comum e resolvido de forma barata só com
  documentação clara).

### Alternativa B — Depreciar o pacote npm inteiro, forçar todo mundo pro PyPI
- Simplifica a superfície de manutenção (um canal só), mas quebra a
  capacidade (a) (o scaffolder), que **não tem equivalente Python** — não
  dá pra fazer `pip install` rodar `npx @wesleysimplicio/llm-project-mapper`.
- Descartada: é uma mudança de capacidade real (perde o scaffolder-via-npx
  pra quem não tem Python), não uma limpeza de nome.

### Alternativa C — não fazer nada (deixar a prosa solta da issue #87 como está)
- Descartada: é exatamente o que a issue #160 pede para resolver — a nota
  solta em uma linha do README não é uma decisão registrada, revisável, e
  ligada ao fix mecânico de URL que também precisava acontecer.

---

## Critério de revisão

- Se o npm alguma vez ganhar suporte de telemetria de download por script
  (`llm-project-mapper` vs `simplicio-mapper`) e o alias mostrar uso
  próximo de zero por um período sustentado, reabrir a decisão de remover
  o alias do console script Python (não o nome do pacote npm, que continua
  preso ao scaffolder).
- Se o scaffolder (capacidade (a)) algum dia ganhar um port Python real, a
  Alternativa B volta a ser viável e esta ADR deve ser revisitada.

---

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-mapper/issues/160
- Issue relacionada (decisão original em prosa): #87 (ver README.md antes
  desta ADR)
- ADR relacionada: `.specs/architecture/ADR-005-node-thin-shim.md` (issue
  #158 — por que a cópia Node do engine é "legada" especificamente)
- `package.json`, `pyproject.toml` (`[project.urls]`), `README.md`
  ("Install matrix" / nota de depreciação)

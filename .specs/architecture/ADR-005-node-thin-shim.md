# ADR-005: `Node como thin shim sobre o CLI Python canônico (map/update), com fallback transitório`

> Resolve https://github.com/wesleysimplicio/simplicio-mapper/issues/158

---

## Status

`Aceito` (parcial — ver escopo abaixo)

---

## Data

`2026-07-07`

---

## Autores

- `Claude (agent) — a pedido de wesleysimplicio`

---

## Contexto

`simplicio_mapper/mapper.py` (1830 linhas) é a implementação canônica do
mapper. `bin/mapper-artifacts.js` (945 linhas) é uma **reimplementação
completa em JS** do mesmo parsing/graph/emit, mantida manualmente em
paridade via `tests/python/test_parity.py` (issue #98) — toda mudança de
comportamento no mapper precisa ser replicada nos dois lados, ou os dois
runtimes divergem silenciosamente até o teste de paridade pegar (se pegar).
Isso é dupla manutenção real, não hipotética: `mapper.py` e
`mapper-artifacts.js` já divergiram no passado (ver histórico de
`test_parity.py`).

`bin/cli.js` é o entrypoint publicado (`llm-project-mapper` no npm) que
distribui para: o scaffolder (comportamento default — instala o starter
pack), e três subcomandos delegados via `spawnSync` para wrappers próprios:
`build-hamt-catalog`, `skillopt`, e `map`/`update` (delegado a `bin/map.js`,
que usa `bin/mapper-artifacts.js`).

## Decisão

**`map`/`update` passam a preferir shimming para o CLI Python canônico
(`python3 -m simplicio_mapper.cli map|update <mesmos argv>`) quando um
Python 3 com `simplicio_mapper` importável está disponível no PATH**, com
fallback automático e silencioso para a reimplementação Node existente
(`bin/map.js` + `bin/mapper-artifacts.js`) quando Python não está presente.//

### Escopo desta mudança (issue #158, honesto sobre o que é parcial)

Dado o tamanho e risco de converter TODO `bin/*.js` num único passe, esta
ADR cobre deliberadamente apenas o recorte que dá pra fazer com segurança
validada (testes reais rodados, não apenas raciocínio):

1. **Feito** — `bin/cli.js`'s dispatch de `map`/`update`: shim real para
   `python3 -m simplicio_mapper.cli`, argv passa direto (as duas CLIs já
   aceitam o mesmo conjunto de flags `--root`/`--stack`/`--product-name`/
   `--out`/`--incremental`/`--watch`/`--silent` para esses dois
   subcomandos — não havia tradução de flags para escrever).
2. **Feito** — caminho de fallback Python-ausente: `detectPythonShim()`
   sonda `python3`/`python` (ordem invertida no Windows) tentando
   `import simplicio_mapper`; se nenhum candidato funciona, cai para
   `bin/map.js` sem erro, sem log de ruído. `SIMPLICIO_MAPPER_NO_SHIM=1`
   força o caminho Node (usado pelos próprios testes deste repo para
   continuar testando a reimplementação Node isoladamente).
3. **Feito** — `tests/python/test_parity.py` reforçado com dois testes
   novos: (a) o shim real acontece por padrão nesta env (evidência viva de
   paridade — quando o shim dispara, "rodar Node" e "rodar Python" chamam
   literalmente o mesmo processo Python); (b) `SIMPLICIO_MAPPER_NO_SHIM=1`
   força e testa o fallback Node isoladamente, provando que ele ainda
   produz artefatos equivalentes por si só.
4. **NÃO feito nesta ADR** — `bin/auto-map.js` (scaffolder-side, não é o
   mapper `map`/`update`; ele reimplementa auto-detecção de stack para a
   *primeira instalação* do starter, um problema adjacente mas distinto) e
   `bin/mapper-artifacts.js` continuam existindo como estão — não foram
   apagados, porque `bin/map.js`/`bin/cli.js` ainda caem neles no caminho
   de fallback. Elas se tornam **código morto na maior parte do tempo**
   (só rodam quando Python está ausente do host), não removidas ainda —
   remover precisaria antes decidir se o fallback deve existir ou se
   `map`/`update` devem simplesmente **exigir** Python (mudança de contrato
   maior, fora do escopo desta ADR).
5. **NÃO feito nesta ADR** — os outros subcomandos de `bin/cli.js`
   (scaffolder default, `build-hamt-catalog`, `skillopt`) não têm
   equivalente Python e não são candidatos a este shim.

### Quem é dono / mantenedor

`simplicio_mapper/cli.py` (Python) é a fonte de verdade daqui em diante
para o comportamento de `map`/`update`. `bin/map.js` +
`bin/mapper-artifacts.js` são mantidos apenas como fallback — mudanças de
comportamento no mapper só precisam ser escritas uma vez em Python; o
fallback Node só precisa ser tocado se uma regressão real aparecer nele
(fica cada vez mais "legado testado", não "ativamente evoluído em
paralelo").

---

## Consequências

### Positivas (+)

- Elimina a dupla manutenção para o caminho comum (host com Python
  instalado — que é o caso de qualquer ambiente que já tem
  `simplicio-mapper` via `pip`, incluindo CI e os outros repos do
  ecossistema).
- `bin/cli.js map`/`update` passam a herdar automaticamente qualquer
  feature nova do CLI Python (`--for-llm toon`, `--json`, etc.) sem
  reimplementação em JS — a nota em `bin/map.js` sobre `--for-llm` "Node
  parity remains pending" deixa de ser um problema pendente para quem tem
  Python instalado.
- Fallback gracioso: hosts Node-only (sem Python) continuam funcionando
  exatamente como antes — nenhuma regressão de disponibilidade.

### Negativas (-)

- **Nova dependência de runtime para o caminho feliz**: `map`/`update` via
  `npx llm-project-mapper` agora silenciosamente invocam um processo
  Python quando disponível — um usuário depurando "por que isso está
  chamando Python?" precisa conhecer esta ADR. Mitigado por
  `SIMPLICIO_MAPPER_NO_SHIM=1` e pelo comentário no código.
  apontando para esta ADR.
- **`bin/mapper-artifacts.js`/`bin/map.js` continuam existindo** como
  código quase-morto (só o fallback os exercita) — a dupla manutenção não
  desaparece de vez, só passa a ser rara (só quando alguém sem Python
  reporta um bug no fallback). Remover de vez exigiria decidir se Python
  vira dependência obrigatória de `map`/`update` (ver Alternativa B).
- Detecção de Python via `spawnSync` a cada chamada de `map`/`update` tem
  custo de processo extra (~dezenas de ms) mesmo quando o shim não
  acontece — aceitável frente ao ganho de manutenção, mas mensurável.

### Neutras / observações

- O shim é **transparente para os testes de paridade existentes**: os
  campos que `tests/unit/mapping-artifacts.test.js` verifica
  (`update_mode`, `changed_files`, `recent_changes`, `git_status`) já
  existem igualmente em `simplicio_mapper/mapper.py` — não foi necessário
  mudar nenhuma asserção desses testes Node para o shim passar.

---

## Alternativas consideradas

### Alternativa A — Node-as-thin-shim (escolhida)
- `bin/cli.js` prefere invocar o Python real; Node só reimplementa quando
  Python está ausente.
- Descartar totalmente `bin/mapper-artifacts.js` seria mais limpo, mas
  quebraria a promessa de "funciona sem Python" que o pacote npm
  `@wesleysimplicio/llm-project-mapper` faz hoje (`engines.node >=16.7.0`,
  nenhuma dependência de Python declarada). Faseamento ficou para depois.

### Alternativa B — Python como dependência obrigatória de `map`/`update`
- Remove `bin/mapper-artifacts.js` de vez; `map`/`update` falham com uma
  mensagem clara se Python/`simplicio_mapper` não estiverem presentes.
- Descartada por agora: é uma mudança de contrato para quem instala só via
  npm sem Python (breaking change de disponibilidade), precisa de aviso de
  depreciação e uma janela de migração — não algo pra decidir no mesmo PR
  que introduz o shim. Boa candidata para uma ADR-006 futura se o shim
  atual se provar estável.

### Alternativa C — não fazer nada (manter as duas implementações paralelas)
- Descartada: é o próprio problema que a issue #158 pede para resolver;
  `test_parity.py` já existe precisamente porque a duplicação já causou
  drift real no passado.

---

## Critério de revisão

- Quando `bin/mapper-artifacts.js`'s caminho de fallback não for mais
  exercitado por meses em produção real (telemetria/relatos), reavaliar a
  Alternativa B (tornar Python obrigatório) formalmente.
- Se `--for-llm`/`--json`/outros subcomandos do CLI Python (`index`,
  `inspect`, `ask`, etc.) ganharem uma demanda real de espelho Node, essa
  ADR deve ser revisitada para decidir se eles entram no mesmo shim
  (provavelmente sim, mesmo padrão) ou se merecem uma ADR própria.

---

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-mapper/issues/158
- `bin/cli.js` (dispatch do shim), `bin/map.js`/`bin/mapper-artifacts.js`
  (fallback Node), `simplicio_mapper/cli.py` (fonte de verdade)
- `tests/python/test_parity.py` (issue #98, reforçado por esta ADR)
- ADRs relacionados: nenhum diretamente; ver `SIMPLICIO_INTEGRATION.md`
  para o contrato de artefatos que ambos os lados precisam respeitar.

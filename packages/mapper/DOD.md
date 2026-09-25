# Definition of Done -- 4 camadas (simplicio-mapper)

> Complementa o DoD já existente em `AGENTS.md`/`CLAUDE.md` (as "7 dimensões"
> do pacote Python + o gate de coverage real em CI). Não substitui nada de
> lá -- este arquivo organiza o mesmo compromisso em 4 camadas, motivado por
> **2 bugs reais** encontrados nesta sessão no ecossistema Simplicio (issue
> hub: [simplicio-loop#579](https://github.com/wesleysimplicio/simplicio-loop/issues/579),
> issue deste repo: [#310](https://github.com/wesleysimplicio/simplicio-mapper/issues/310)).

## Por que isso existe -- os 2 bugs motivadores

1. **`simplicio_mapper/mapper/graph.py` -- linha errada no symbol-index por
   regex engolindo linha em branco.** Todo padrão de linguagem em
   `_symbol_definitions_for_file` ancorava em `^\s*<keyword>` com
   `re.MULTILINE`. Como `\s` casa também com `\n`, um `def`/`class` precedido
   por uma ou mais linhas em branco (o caso comum -- PEP8 pede 1-2 linhas
   em branco antes de uma função top-level, ou um docstring de módulo
   seguido de linhas em branco) deixava `^` ancorar numa linha em branco
   anterior e `\s*` engolir as quebras de linha intermediárias --
   deslocando `match.start()` (e a linha reportada) para essa linha em
   branco em vez da linha real do `def`/`class`. Isso corrompia todo
   consumidor daquele número de linha: `ask callers/callees/tests-for`, o
   filtro de self-call do call-graph, etc. O fix (já commitado nesta
   branch, `fix(mapper): correct symbol line numbers for defs preceded by
   blank lines`) trocou `match.start()` por `match.start(1)` -- o grupo
   capturado do próprio identificador, que sempre fica na linha real da
   definição, independente de quanto whitespace o `\s*` engoliu antes dele.
   Um teste unitário fixo (`SymbolLineNumberBlankLinesTest` em
   `tests/python/test_mapper_graph.py`) prova o fix para 2 casos escolhidos
   à mão; a Camada 2 abaixo generaliza essa prova com Hypothesis.
2. **`simplicio_mapper.mechanical_edit` (repo irmão `simplicio-dev-cli`) --
   corrupção silenciosa por aplicar operações fora de ordem.** O executor
   determinístico de edições (`simplicio/mechanical_edit.py`,
   `_operation_order`) podia reordenar operações por linha para o **plano
   inteiro** em vez de por arquivo, aplicando patches do arquivo A contra
   offsets calculados para o arquivo B -- uma corrupção silenciosa (sem
   exceção, sem exit code != 0) que só um diff observado pegaria. Motivação
   canônica do item de Camada 1 "verificação adversarial pós-verde": rodar a
   suíte verde não é suficiente se o bug está no **resultado observável**
   (o arquivo escrito em disco), não no status da ferramenta.

Nenhum dos dois bugs seria pego só por "a suíte está verde" -- o primeiro
exigia uma fixture com formatação de código real (blank lines antes de um
`def`), o segundo exigia olhar o arquivo final, não o exit code do executor.
Daí as camadas 2 abaixo.

---

## Camada 1 -- universal (toda PR, sem exceção)

Já coberto pelo DoD genérico em `AGENTS.md`/`CLAUDE.md` -- citado aqui só
para fechar o framework de 4 camadas:

- Implementação sem escopo extra.
- Unit tests cobrindo a lógica isolada do módulo tocado
  (`tests/python/test_*.py`, `python -m unittest discover -s tests/python`
  ou `pytest tests/python -q`).
- Regressão: todo bug real corrigido ganha um teste que trava a regressão,
  não só o fix (`SymbolLineNumberBlankLinesTest` é o exemplo vivo).
- **Coverage com gate real em CI** -- já existe neste repo:
  `.github/workflows/python-ci.yml`, job `python-tests`, roda
  `pytest tests/python -q --cov=simplicio_mapper --cov-report=term
  --cov-fail-under=88`. Não precisa ser adicionado; só não pode regredir.
- Evidência de execução real (stdout capturado, artefato
  `.simplicio/*.json` gerado, ou resultado do `unittest`/`pytest`
  específico) -- ver critério "E2E obrigatório vs unit+lint bastam" em
  `AGENTS.md`.
- Verificação adversarial pós-verde: depois do DoD ficar verde, uma
  passada ortogonal -- reler os acceptance criteria lado a lado com o
  resultado, exercitar a feature de verdade + 1 borda + 1 caminho de erro.
  O bug 2 acima é o motivador concreto: "testes passaram" não provou que o
  arquivo final não estava corrompido.
- Sem segredo, sem `print()` de diagnóstico esquecido, sem TODO órfão (sem
  dono/prazo).

## Camada 2 -- por superfície de risco (declarada no PR)

Este repo é majoritariamente um **parser/transformador de código-fonte**
(`simplicio_mapper/mapper/*.py`: `parse.py`, `graph.py`, `emit.py`) mais uma
**CLI multi-modo** (`simplicio_mapper/cli/`). As superfícies de risco reais
deste repo, e o que cada uma exige:

- **Parsing/transformação de código (`mapper/parse.py`, `mapper/graph.py`,
  `mapper/emit.py`)** -- teste de propriedade (Hypothesis) sempre que a
  mudança tocar regex/heurística de linha/coluna/AST-like matching. Exemplo
  implementado: `tests/python/test_mapper_graph_property.py` -- gera
  variações de formatação (linhas em branco, comentários, decorators,
  docstring de módulo) antes de um `def`/`class` e verifica que a linha
  reportada por `_symbol_definitions_for_file` bate com o que `ast.parse`
  do stdlib confirma como a linha real do nó -- o oráculo independente da
  implementação sob teste, exatamente o tipo de caso que o bug 1 motivador
  expôs.
- **Fixture com código real, não sintética** -- qualquer teste de
  `mapper/*` que analisa "um projeto" deve incluir pelo menos um cenário
  contra código real committed (ex.: `contracts/mapper-artifacts/v1/fixtures/python-minimal/source/`,
  `tests/fixtures/**`), não só strings de 3 linhas fabricadas à mão. Testes
  sintéticos isolados continuam válidos para o caso específico, mas não
  substituem a fixture real.
- **Revisão por invariante quando duas funções processam a mesma
  coleção** -- pergunta obrigatória (ver `.github/PULL_REQUEST_TEMPLATE.md`
  atualizado): se a mudança adiciona uma função que particiona/agrupa/itera
  sobre uma coleção que outra função já processa (ex.: `_build_symbol_index`
  e `_build_call_graph` ambos iterando `files`; `_known_path_suffix_index` e
  `_candidate_import_targets` ambos usando a mesma chave de bucket), elas
  usam a mesma chave/granularidade? Uma discordância aí é exatamente a
  classe de bug que passa despercebida em revisão superficial.
- **Asserção sobre resultado observável, não só status auto-reportado** --
  para qualquer mudança em `mechanical_edit`-like paths (este repo não tem
  um executor de edição próprio, mas consome/valida o output de
  `simplicio-dev-cli` via `contracts/`) ou em qualquer emissor de artefato
  (`mapper/emit.py`), o teste deve ler o artefato final gerado em disco e
  comparar o conteúdo, não só checar que o comando saiu com `returncode ==
  0`. Bug 2 motivador é exatamente essa lacuna num repo irmão.
- **Benchmark com baseline+gate para caminho quente** -- `mapper/graph.py`
  tem um caminho quente documentado (`_known_path_suffix_index`, ADR-009,
  `CandidateImportTargetsQuadraticRegressionTest`); qualquer mudança nesse
  caminho roda `scripts/runtime_scale_benchmark.py` (ou o benchmark
  relevante em `scripts/*_benchmark.py`) e reporta o número medido.
- **Matriz de modos de invocação para CLI multi-modo** -- `simplicio_mapper/cli/`
  expõe múltiplos comandos e sub-verbos (`index`, `map`, `ask
  callers/callees/impact/tests-for/precedent`, `contract validate`,
  `snapshot`). Mudança em `cli/_args.py`/`cli/_repo_commands.py`/`query.py`
  cobre pelo menos: modo local (fallback), modo com delegação nativa ao
  `simplicio` runtime quando presente, e modo com o kill-switch de
  delegação setado (`SIMPLICIO_MAPPER_NO_RUNTIME_*`).
- **E2E com evidência para fluxo observável** -- critério já definido em
  `AGENTS.md` (bootstrap/scaffold, docs-site, qualquer UI navegável); não
  duplicado aqui.

## Camada 3 -- por sprint/release

- **Mutation testing** -- plano detalhado na issue de acompanhamento (ver
  seção final). Prioridade: `mapper/graph.py` (módulo com o bug 1
  motivador), depois `mapper/parse.py` e `mapper/emit.py`.
- **Quarentena de flaky com prazo** -- qualquer teste marcado flaky (ex.:
  os testes de proveniência/git remoto de `test_visualization_contract.py`
  que dependem de ambiente de rede/tag) ganha um marcador explícito +
  issue com prazo de investigação, nunca fica silenciosamente ignorado.
- **Anti-rot de documentação** -- generalização do padrão
  `scripts/claims_audit.py` do `simplicio-loop` para este repo: script já
  existe aqui (`scripts/check-doc-sync.js`) sincronizando `AGENTS.md` <->
  `CLAUDE.md`; falta um audit que valide se comandos citados em `docs/*.md`
  ainda existem/rodam. Ver issue de acompanhamento.

## Camada 4 -- ecossistema/release

- **Contract tests entre repos** -- este repo é **produtor** de
  `simplicio.map-result/v1`, `simplicio.map-handoff/v1`,
  `simplicio.symbol-index/v1`, `simplicio.call-graph/v1`,
  `simplicio.architecture-inventory/v1`, `simplicio.macro-map/v1` (ver
  `simplicio_mapper/contract.py`, `contracts/mapper-artifacts/v1/`).
  `simplicio-dev-cli` e `simplicio-runtime` são **consumidores**. Plano
  detalhado na issue de acompanhamento.
- **Eval de pass-rate pra componente com LLM** -- não aplicável
  diretamente a este repo (não chama LLM em si), mas o F10 `ask` delega
  para o runtime nativo `simplicio` -- qualquer expansão dessa delegação
  que mude o formato de resposta consumido por um LLM downstream deveria
  ter um harness de avaliação. Fora de escopo desta rodada; ver issue.
- **Canário contra dependência externa real** -- `mapper/graph.py::_macro_git`
  e o módulo de proveniência (`visualization.py`) chamam `git` real via
  subprocess; um canário periódico contra um repositório real (não só
  fixtures locais) pegaria drift de comportamento do `git` instalado no
  runner de CI.
- **Build hermético + proveniência** -- `pyproject.toml` já declara
  `[tool.hatch.build.targets.wheel.force-include]` para `contracts/`
  dentro do wheel (issue #199/#200/#208); falta assinatura/proveniência de
  build (SLSA-style) no pipeline de publish. Fora de escopo desta rodada.
- **Telemetria com caminho de volta** -- `simplicio_mapper/savings.py`
  (`record_savings_event`) já grava eventos em
  `.simplicio/ledger/savings-events.jsonl`; falta um consumidor que feche o
  loop lendo esses eventos de volta para decisão (ex.: desligar
  delegação nativa automaticamente se o savings medido cair abaixo de um
  piso). Fora de escopo desta rodada.

---

## Onde estão os detalhes de execução (Camadas 3/4)

Camadas 1 e 2 estão implementadas nesta rodada (ver commit que acompanha
este arquivo: teste de propriedade Hypothesis em
`tests/python/test_mapper_graph_property.py`, pergunta de invariante +
item de evidência observável no `.github/PULL_REQUEST_TEMPLATE.md`).

Camadas 3 e 4 exigem escolhas de ferramenta e sequenciamento maiores
(mutation testing, contract tests entre repos, anti-rot de docs) -- o plano
passo a passo para cada uma vive numa issue dedicada neste repo,
referenciando o hub [simplicio-loop#579](https://github.com/wesleysimplicio/simplicio-loop/issues/579)
e [#310](https://github.com/wesleysimplicio/simplicio-mapper/issues/310).

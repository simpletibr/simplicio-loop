# ADR-016: Projetar capabilities específicas após o mapa completo

## Status

Aceito

## Data

2026-08-08

## Autores

- Simplicio engineering

## Contexto

O Mapper já produz módulos, símbolos, precedentes, relações, testes e o
`agent_tree` Brown-Hilbert, mas esses artefatos reconstruíveis vivem em
`.simplicio/`. Skills e agents específicos do projeto precisam sobreviver à
remoção desses mapas sem misturar conteúdo gerado com arquivos humanos ou dar
ao Mapper autoridade para instanciar workers e executar efeitos.

Os destinos reais já existentes são `.skills/` e `.agents/`; não existem
`simplicio_mapper/skills.py` nem `agent_tree.py` como superfícies de geração.
O mapa canônico é produzido pelo fluxo Python `index` e o `agent_tree` é apenas
um campo de routing dentro de `project-map.json`.

## Decisão

Depois que `index` concluir, liberar o lock do mapa e comprovar estado
`complete`, mapa `fresh`, artefatos presentes e um handoff possível, o Mapper
compila descritores determinísticos e read-only:

- skills em `.skills/_generated/<project-id>/<capability>/SKILL.md`;
- agents em `.agents/_generated/<project-id>/<capability>.agent.md`;
- registry atual em `.catalog/project-capabilities.json`;
- geração imutável e receipt em
  `.catalog/_generated/<project-id>/generations/<generation-id>/`.

Conteúdo humano fora de `_generated` nunca é alterado. O `generation_id` é
content-addressed a partir de inputs normalizados, versão do gerador e hash da
policy. Timestamps, status dirty, caches e as próprias projeções geradas não
entram no fingerprint. Paths de secrets, traversal, symlinks e tokens não
allowlisted são excluídos ou rejeitados.

Em Git, somente a ref canônica limpa (default `main`) promove persistentes;
outras refs e worktrees dirty produzem preview em `.simplicio/`. Projetos
standalone sem Git podem promover uma identidade `tree:<sha256>`. A publicação
usa staging, geração imutável e rollback das projeções; falha em N+1 preserva a
última geração válida. Reexecução idêntica valida hashes e retorna `reused` sem
escrever bytes.

Agents gerados têm `authority=review`, `lane=background`, tools `[search,
read]`, quotas fixas, `effects=denied` e memória `materialized-only`. O
Brown-Hilbert permanece routing hint; `agent_key`/`yool_id` são identidades
lógicas versionadas. Mapper continua apenas produtor de descritores.

## Consequências

### Positivas (+)

- Skills/agents sobrevivem ao cleanup de `.simplicio/` e são auditáveis por
  hashes e receipts determinísticos.
- Scans idênticos não entram em self-churn nem reescrevem projeções.
- Conteúdo humano e autoridade de mutação permanecem isolados.
- Uma promoção interrompida restaura a geração anterior.

### Negativas (-)

- O repositório passa a manter uma cópia imutável e uma projeção materializada.
- Módulos acima do fan-out cap são agrupados e perdem granularidade individual.

### Neutras / observações

- `.catalog` é estado durável do projeto, não MapperStore SQLite nem cache Fast.
- Runtime/Agent ainda precisam validar tenant/scope/generation ao instanciar um
  specialist; esta decisão não lhes entrega implementação ou effect authority.

## Alternativas consideradas

### Alternativa A — Persistir em `.simplicio/`

Rejeitada porque cleanup ou reconstrução dos mapas apagaria o conhecimento
durável e misturaria ciclos de vida incompatíveis.

### Alternativa B — Sobrescrever `.skills/` e `.agents/` diretamente

Rejeitada porque destruiria conteúdo humano e tornaria impossível distinguir
provenance manual de conteúdo compilado.

### Alternativa C — Usar o `agent_id` posicional como identidade

Rejeitada porque endereços Brown-Hilbert mudam com a topologia; são hints de
routing, não identidade durável de capability.

## Critério de revisão

Revisar se o consumer Runtime exigir outro formato de projeção, se o fan-out cap
se mostrar inadequado em benchmarks reais, ou se promoção multi-diretório
precisar de uma primitive transacional comum ao ecossistema.

## Links

- Issue: [#538](https://github.com/wesleysimplicio/simplicio-mapper/issues/538)
- ADR relacionada: [ADR-014](./ADR-014-mapper-store-ownership-and-inventory.md)
- Spec YOOL: [YOOL_TUPLE_HAMT.md](../../YOOL_TUPLE_HAMT.md)

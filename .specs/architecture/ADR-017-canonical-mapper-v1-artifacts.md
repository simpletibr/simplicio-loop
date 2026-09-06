# ADR-017: Canonicalizar os envelopes dos artefatos Mapper v1

## Status

Aceito

## Data

2026-09-06

## Autores

- Simplicio engineering

## Contexto

Mapper, Runtime e Fast consomem os cinco artefatos públicos v1, mas o espelho
Node e qualquer backend ainda não promovido podem produzir objetos semântica ou
estruturalmente diferentes sob o mesmo identificador. Isso permite que um
consumer aceite uma forma incompatível sem perceber.

## Decisão

Usar os contratos JSON e fixtures versionados em
`contracts/mapper-artifacts/v1/` como a única fonte de verdade para os cinco
IDs públicos. O produtor Python é a referência comportamental até um backend
passar a mesma matriz diferencial. Todo artefato público inclui o envelope
`producer` com provenance, cobertura, degradações, omissões e digest semântico
canônico; um backend não promovido usa um ID privado `simplicio.mapper-native/*`.

Digest semântico exclui apenas dados de execução local documentados (metadata
do produtor, timestamps e root físico) e mantém a ordenação canônica definida
no contrato. Adições são compatíveis; remoção, retype ou mudança de significado
de campo obrigatório exige uma nova major pública.

## Consequências

### Positivas (+)

- Consumers têm um shape e uma semântica verificáveis por schema e fixture.
- Reexecuções equivalentes produzem digests comparáveis e drift detectável.
- Backends incompletos não podem mascarar paridade nem quebrar consumidores v1.

### Negativas (-)

- Cada promoção de backend exige saída diferencial e atualização deliberada de
  fixtures, schemas e documentação.
- O envelope acrescenta metadata a todos os artefatos públicos.

## Alternativas consideradas

### Alternativa A — Manter os mesmos IDs e aceitar union shapes

Rejeitada: consumers não conseguem distinguir incompatibilidade estrutural de
um campo opcional legítimo.

### Alternativa B — Promover o espelho Node por proximidade

Rejeitada: sem parity differential, proximidade não é evidência de equivalência
semântica.

### Alternativa C — Versionar somente no pacote Mapper

Rejeitada: versão de distribuição não identifica a major do contrato nem
impede drift entre backends.

## Critério de revisão

Revisar quando um backend passar a matriz diferencial completa, quando um
consumer exigir uma mudança incompatível, ou quando os fixtures demonstrarem
que a ordenação atual não é suficiente para digests estáveis.

## Links

- Issue: [#614](https://github.com/wesleysimplicio/simplicio-mapper/issues/614)
- Epic: [#613](https://github.com/wesleysimplicio/simplicio-mapper/issues/613)
- Contrato: [`CANONICAL_CONTRACT.md`](../../contracts/mapper-artifacts/v1/CANONICAL_CONTRACT.md)

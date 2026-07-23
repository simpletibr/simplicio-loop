# ADR-007: Adotar um PlanDAG canônico com projeções vinculadas por digest

## Status

Aceito

## Data

2026-07-23

## Autores

- wesleysimplicio
- Codex

## Contexto

Dev CLI compila `simplicio.plan-dag/v1`, mas Loop e Runtime podem precisar de
visões próprias para scheduling e execução. Recriar o plano em cada projeto
perde identidade causal e permite divergência silenciosa de dependências,
critérios de aceite, orçamento e gates.

## Decisão

Adotamos `simplicio.plan-dag/v1`, compilado pelo Dev CLI, como contrato
canônico. Loop e Runtime são consumidores registrados. Qualquer visão local é
uma `simplicio.plan-projection/v1` que preserva IDs canônicos, declara uma
transformação e carrega o SHA-256 do plano fonte.
Cada transformação é registrada por consumidor, produz payload determinístico
e carrega também o SHA-256 desse payload. Validação recalcula ambos os digests,
valida o PlanDAG fonte e rejeita mutação posterior. Conflitos entre nós são
simétricos; serialização preserva a presença explícita do campo v1 para não
alterar digests legados.

O Dev CLI publica manifesto e conformance helpers. A adoção nos repositórios
Loop e Runtime ocorre em mudanças vinculadas à issue #298; até lá, integração
cross-repo não é considerada comprovada.

## Consequências

### Positivas (+)

- Plano, efeitos, observações e receipts podem compartilhar identidade.
- Projeção adulterada ou baseada em plano diferente falha fechado.
- Compatibilidade e ownership ficam verificáveis por máquina.

### Negativas (-)

- Loop e Runtime precisam migrar contratos locais.
- Projeções existentes precisam declarar transformação e digest.

### Neutras / observações

- Plan Compiler continua sem executar efeitos.
- Adapter N/N-1 permanece temporário e expira pela política existente.

## Alternativas consideradas

### Alternativa A — Manter um plano por projeto

Descartada porque exige conversões sem uma fonte de identidade verificável.

### Alternativa B — Tornar Runtime owner do plano

Descartada porque mistura compilação de intenção com execução determinística.

## Critério de revisão

Revisar se outro componente assumir formalmente compilação ou se uma versão
major substituir `simplicio.plan-dag/v1`.

## Links

- Issue: https://github.com/wesleysimplicio/simplicio-dev-cli/issues/298
- Documento: [Plan Compiler](../../docs/plan-compiler.md)

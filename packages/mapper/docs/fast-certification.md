# Certificação e rollout do backend Fast

Execute o Fast em shadow antes do canário:

```bash
simplicio-mapper fast-certify \
  --mapper contracts/fast-certification/v1/fixtures/golden-corpus.json \
  --fast contracts/fast-certification/v1/fixtures/golden-fast.json \
  --out .simplicio/fast-certification.json
```

O shadow nunca muda decisões: `decision_backend` permanece `mapper`. O relatório
mede precision e recall por relação e linguagem. Os gates padrão exigem
precision >= 0,98 e recall >= 0,95 em todos os grupos. Cada divergência inclui
classificação e amostra reproduzível.

O canário só seleciona Fast quando os gates passam e
`SIMPICIO_MAPPER_CONTEXT_BACKEND=fast`. O rollback é somente configuração:

```bash
export SIMPLICIO_MAPPER_CONTEXT_BACKEND=mapper
```

A matriz de compatibilidade rejeita schemas Fast desconhecidos e preserva o
Mapper. O recibo separa `parsed`, `reused`, `fallback` e `degraded`. Tempo de
consulta, CPU, RSS e page faults são observados; bytes lidos ficam `null` com o
motivo quando não podem ser isolados de forma portável.

O benchmark reproduzível executa ao menos dez repetições cold, warm e
incremental em escalas pequena, média e grande. O arquivo bruto registra o
ambiente e não declara economia ou speedup.

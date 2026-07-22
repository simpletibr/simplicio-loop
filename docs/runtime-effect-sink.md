# Runtime EffectSink

`mode="integrated"` compila `PlanDAG`/`EffectPlan` e entrega cada efeito ao
Runtime por `RuntimeEffectSink`. O Dev CLI não aplica patch, escreve arquivo de
produto, executa validação ou faz commit nesse modo. `RecordingEffectSink` é
somente um double injetado explicitamente por testes.

## Contrato e compatibilidade

O cliente negocia `GET /v1/capabilities` antes do primeiro efeito. A resposta
deve anunciar `simplicio.effect-transaction/v1`, transporte `http-json` e
Runtime major `1`. O efeito segue por `POST /v1/effect-transactions`; consulta
e reconciliação usam `GET /v1/effect-transactions/{idempotency_key}`. O cliente
falha fechado diante de major, schema ou transporte incompatível. A faixa
suportada é Runtime `>=1.0.0,<2.0.0`.

Configure `SIMPLICIO_RUNTIME_URL`. O endpoint pode estar fora do checkout e não
depende de processo ou SDK do Simplicio Agent.

## Durabilidade, recovery e segurança

Antes do envio, a intenção canônica é gravada atomicamente em
`.simplicio/runtime-effects/<key>.intent.json`. Receipt e outcome verificados
são persistidos antes do retorno. Em resposta perdida, timeout ou disconnect,
o resultado é `effect_unknown`: nunca há retry ou fallback automático. O
coordenador deve consultar `RuntimeEffectSink.reconcile(key)`; restart usa a
mesma intenção persistida.

Receipts são aceitos somente quando schema, digest, toda a identidade causal
(coordenador, sessão, turno, tentativa, subworkflow, plano, goal, plan node e
effect), idempotency key, ACs, decisão do gate e hashes base/source conferem.
Estados de validation e rollback permanecem no outcome. Campos de prompt,
senha, secret, API key ou access token tornam o receipt inválido. Payloads
maiores que 1 MiB e write sets absolutos ou com `..` são rejeitados antes da
rede.

Após três falhas consecutivas, o circuit breaker abre por 30 segundos. O método
`status()` preserva reason codes para diagnóstico. Para rollback do cliente,
volte à versão anterior do pacote; não apague intents sem antes reconciliá-las
com o Runtime.

## Diagnóstico reproduzível

```bash
SIMPLICIO_RUNTIME_URL=http://runtime:8080 \
SIMPLICIO_TEST_CMD='pytest -q' simplicio-py task ...

pytest -q tests/python/test_runtime_effect_sink.py \
  tests/python/test_pipeline_integrated_mode.py
python bench/runtime_effect_sink_benchmark.py
```

Eventos contêm apenas effect ID, state, transport e latência. O payload do
efeito, prompts e secrets não são emitidos em logs.

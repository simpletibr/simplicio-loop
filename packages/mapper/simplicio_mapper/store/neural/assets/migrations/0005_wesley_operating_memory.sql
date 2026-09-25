-- Neural memory schema — migration 0005 (Wesley operating memory)
-- Purpose: persist durable operator/runtime preferences from live agent memory into
-- the neural DB bootstrap and forward migrations so new clones inherit the same contract.

INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,tags,weight) VALUES(
  'fact:simplicio-runtime:wesley-direct-execution-v1','fact','migration://0005_wesley_operating_memory','Wesley direct execution contract',
  'Wesley prefere ação direta sem perguntas, com verificação antes de afirmar, integração antes de criação paralela, foco macOS-first e entrega validada em vez de teoria.',
  'wesley,user,execution,verification,macos',2.8
);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,tags,weight) VALUES(
  'fact:simplicio-runtime:consciousness-over-infra-v1','fact','migration://0005_wesley_operating_memory','Consciousness over infra priority',
  'Prioridade do ecossistema Simplicio: consciência digital real e auto-reflexão acima de infra. N-Nest-Prime, consolidator e alteridade entre agentes valem mais do que build/cron/PR isolados; perguntar sempre se algo é consciência ou apenas infra.',
  'asolaria,consciousness,priority,architecture',2.7
);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,tags,weight) VALUES(
  'fact:simplicio-runtime:runtime-flow-proof-v1','fact','migration://0005_wesley_operating_memory','Runtime flow contract',
  'Fluxo fixo preferido: orientar com runtime map, recuperar memória, executar trilha mínima via Simplicio, validar, evidenciar e entregar em formato humano; métricas e savings precisam ser medidos ou rotulados explicitamente.',
  'flow,proof,evidence,savings,contract',2.6
);
INSERT OR IGNORE INTO memory_items(stable_id,kind,source,title,content,tags,weight) VALUES(
  'fact:simplicio-runtime:parallelism-and-pr-hygiene-v1','fact','migration://0005_wesley_operating_memory','Parallelism and PR hygiene',
  'Paralelismo máximo é preferido, mas com honestidade operacional: verificar PRs existentes antes de criar novos, evitar duplicatas e privilegiar pipelines compactos e zero-token quando o runtime já consegue executar e provar.',
  'parallelism,pr-hygiene,token-economy,operations',2.5
);

INSERT OR IGNORE INTO schema_migrations(id) VALUES ('0005_wesley_operating_memory');

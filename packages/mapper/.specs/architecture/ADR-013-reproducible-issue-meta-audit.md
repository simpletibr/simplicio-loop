# ADR-013: Auditoria de issues como artefato determinístico e read-only

> Resolve parcialmente https://github.com/wesleysimplicio/simplicio-mapper/issues/328

## Status

Aceito

## Data

2026-07-22

## Contexto

A meta-auditoria exige inventário completo e uma revisão verificável para cada
issue. Alterar 178 corpos diretamente durante a coleta mistura observação com
mutação, torna rollback difícil e permite que texto gerado seja confundido com
evidência de implementação.

## Decisão

Publicar um artefato versionado `simplicio.meta-issue-audit/v1`, gerado apenas
com stdlib a partir da API pública ou de uma exportação offline. Cada item traz
as dez seções da revisão, dependências, matriz de testes, evidências, hashes e
decisão conservadora. O coletor não escreve no GitHub; a aplicação das revisões
é uma etapa humana/autenticada posterior.

O Mapper limita-se ao ContextGraph e aos snapshots de contexto. Execução de
agentes e validação dos consumidores permanecem responsabilidades de Runtime,
Dev CLI, Agent e Loop, provadas pelos contratos entre projetos.

## Consequências

- A auditoria é reproduzível localmente, determinística e independente de
  GitHub Actions pago.
- Credenciais encontradas são mascaradas antes de qualquer conteúdo derivado.
- Issues fechadas são marcadas para revisão, nunca aprovadas por inferência.
- O critério que exige reescrever os corpos remotos só fica completo após uma
  execução autenticada, revisão do diff e anexação das evidências reais.

## Alternativas consideradas

### PATCH automático durante a coleta

Rejeitado: não é atômico para centenas de issues, exige credencial de escrita e
pode apagar contexto concorrente ou propagar uma especificação incorreta.

### Planilha manual

Rejeitada: não oferece hash, replay, validação estrutural ou regressão
automatizada.

## Rollback

Reverter o commit que introduz o schema e remover o artefato gerado. Nenhum
estado remoto precisa ser restaurado porque o coletor é read-only.

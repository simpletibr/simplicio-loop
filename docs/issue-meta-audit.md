# Auditoria reproduzível de issues

O Mapper é responsável por produzir o `ContextGraph` e os snapshots canônicos,
incrementais e versionados do projeto. Ele não executa trabalho de agentes, não
substitui os contratos dos consumidores e não considera uma descrição textual
como prova de implementação. Esses limites também estão descritos na visão do
produto no [README](../README.md#ecosystem).

## Contrato da auditoria

`scripts/meta_issue_audit.py` transforma a exportação pública da API de issues
em `simplicio.meta-issue-audit/v1`. O resultado:

- exclui pull requests, ordena issues por `created_at` e rejeita números
  duplicados;
- registra estado, datas, labels, autor, URL, referências locais e referências
  entre repositórios;
- inclui, para cada issue, as dez seções obrigatórias de revisão, o fluxo de
  testes em nove camadas, as evidências exigidas e uma decisão de encerramento;
- materializa essas seções em `proposed_body`, pronto para diff e revisão antes
  de qualquer edição autenticada, e classifica épico, componente, risco e
  prioridade sem esconder valores não inferíveis (`unassigned`/`unclassified`);
- extrai associações explícitas com PRs, commits e projetos e mantém campos
  vazios para branches, arquivos e testes quando o corpo não fornece evidência;
- publica uma matriz de dependências compacta no topo do artefato;
- mascara padrões de credencial antes de copiar conteúdo e registra quantas
  issues sofreram redação;
- usa hashes SHA-256 do corpo original, da revisão e da entrada canônica para
  permitir reprodução sem publicar o texto integral da issue em logs.

O artefato auditado de #328 está em
[`docs/evidence/issue-328-meta-audit.json`](evidence/issue-328-meta-audit.json).
Ele inventaria **178 issues acessíveis**, da mais antiga à mais recente: **175
fechadas e 3 abertas**, a partir do snapshot público consultado em 22 de julho
de 2026. As issues fechadas recebem `REVIEW_CLOSED`, não uma declaração
retroativa de sucesso; as abertas recebem `KEEP_OPEN`. Implementação e
evidência continuam precisando de revisão humana antes de alterar o estado no
GitHub.

## Reprodução local ou em container

```bash
python scripts/meta_issue_audit.py \
  --fetch \
  --repository wesleysimplicio/simplicio-mapper \
  --output docs/evidence/issue-328-meta-audit.json

python scripts/meta_issue_audit.py \
  --fetch \
  --repository wesleysimplicio/simplicio-mapper \
  --output docs/evidence/issue-328-meta-audit.json \
  --check
```

Para uma reprodução offline, salve a resposta paginada da API como um único
array e substitua `--fetch` por `--input /caminho/issues.json`. `--check` nunca
escreve: retorna `1` quando o artefato está ausente ou divergente. Entrada
inválida, timeout, falha HTTP ou paginação fora do limite retornam `2` e não
sobrescrevem evidência existente.

## Matriz operacional e fechamento

O fluxo comum cobre unidade, integração, sistema, regressão, mudança
incremental, branch/SHA, remoção de arquivo, cache frio/quente, schema
incompatível, concorrência, cancelamento, timeout, retry, desempenho, segurança
e reprodução. Cenários não aplicáveis devem ser justificados na PR; não podem
ser marcados implicitamente como aprovados.

Uma issue só muda para concluída depois de anexar PR e commit, comandos e logs,
resultado de cobertura, falhas injetadas, hashes, receipts, métricas medidas,
dependências entre projetos, risco residual, rollback e decisão explícita. Sem
isso, permanece `SPEC`, `BLOCKED` ou `NEEDS-IMPLEMENTATION`.

## Limite da automação

O script é deliberadamente somente leitura para o GitHub. Ele produz a revisão
normalizada e os hashes usados para conferir futuras edições, mas não reescreve
corpos nem fecha issues. Isso evita que uma execução local com dados obsoletos
destrua contexto ou declare trabalho concluído. A aplicação do texto revisado e
a decisão final exigem credencial de escrita, revisão do diff e confirmação das
evidências observadas.

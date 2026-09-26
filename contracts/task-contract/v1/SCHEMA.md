<!-- simplicio-contract:begin -->
contract: task-contract/v1
schema: simplicio.contract-doc/v1
purpose: Contrato canônico para intake determinístico de task textual/BDD.
rules: The JSON schema next to this file is authoritative; mutable data lives in the footer, never in this header.
<!-- simplicio-contract:end -->

# `simplicio.task-contract/v1`

Contrato canônico para intake determinístico de task textual/BDD.

Objetivo:

- preservar história, cenários, regras, NFRs, dependências, acesso, sinais de impacto e contexto adicional;
- impedir que o loop comece a implementar com perda semântica;
- fornecer uma base estável para planner, watcher e delivery.

Arquivos:

- `schema.json`: shape mínima do contrato.
- O compilador atual vive em `simplicio_loop/task_contract.py`.

Estados especiais:

- `nfrs.state=unknown`: a task disse “nenhum identificado — validar”, então isso ainda não é fato fechado.
- `dependencies.state=unknown`: mesma regra para dependências.
- `prototypes[].status=missing`: havia referência visual, mas o anexo não veio junto.

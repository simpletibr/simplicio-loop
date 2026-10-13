# Layout e fluxo do Paperclip (referência para o dashboard)

O Paperclip (`paperclipai` 2026.916.1) rodou nesta VPS como serviço `paperclipai.service`, com Postgres
embutido e UI em `http://100.68.125.23:3100`. Foi desinstalado: não é mais usado. Este documento guarda o que
ele fazia bem em layout, fluxo e uso, e o que o dashboard do simplicio-loop absorveu.

Fontes, todas locais: o bundle da UI (`@paperclipai/server/ui-dist/assets`: rotas e rótulos da sidebar), o
OpenAPI público (`/api/openapi.json`: 685 caminhos), o source map do CLI e os guias de agente em
`skills/paperclip/references/workflows.md`. A tela autenticada não foi capturada: o dashboard exige login e
nenhuma credencial foi usada para isso. O layout abaixo sai do código, não de screenshot.

## Layout (sidebar)

A sidebar do Paperclip tem estas seções, nesta ordem:

| Seção | Rota | Para que serve |
|---|---|---|
| Search | `/search` | Busca global (atalho de teclado). |
| Dashboard | `/dashboard` | Painel com contadores ao vivo: agentes ativos, tarefas em andamento, gasto do mês, aprovações pendentes. |
| Inbox | `/inbox` | Caixa de entrada com abas: mine, unread, requests, blocked, recent, all. Badge de não lidas e de runs que falharam. |
| Decisions | `/decisions` | Filas de decisão que pedem uma escolha humana. Badge com a contagem. |
| Tasks | `/issues` | Lista de tarefas com abas de estado: active, backlog, done, all, recent. Botão **New Task** no topo. |
| Projects, Routines, Artifacts | `/projects`, `/routines`, `/artifacts` | Agrupamento de tarefas, tarefas recorrentes e saídas produzidas. |
| Cases, Pipelines | `/cases`, `/pipelines` | Casos e funis de trabalho (beta). |
| Goals, Workspaces, Agents, Skills, Connectors | `/goals`, `/workspaces`, `/agents`, `/skills`, `/apps` | Metas, espaços de execução, agentes, habilidades e integrações. |
| Audit, Org, Timeline, Costs, Activity | `/activity`, `/org`, `/timeline`, `/costs`, `/activity` | Trilha de auditoria, organograma, linha do tempo, custos e atividade. |
| Settings | `/company/settings` | Configurações da empresa, membros, segredos, ambientes, acessos, plugins e adaptadores. |

A página de tarefa abre com cabeçalho (identificador, estado, responsável), corpo em markdown, a conversa
(comentários e eventos) e um painel de propriedades à direita.

## Fluxo de uma tarefa

Tradução do `workflows.md` e do `SKILL.md` do Paperclip, sem as partes de empresa e de OpenClaw:

1. **Criar**: a tarefa nasce em `todo` com um responsável (agente) e uma descrição.
2. **Acordar o agente**: o responsável é acordado por um *heartbeat*; a tarefa passa para `in_progress`.
3. **Checkout**: o agente marca a tarefa para si. Outro agente não a pega enquanto ela estiver com um dono.
4. **Executar e comentar**: cada passo vira um comentário. Estado e comentários ficam visíveis na mesma página.
5. **Pedir decisão**: quando falta uma escolha humana, a tarefa vai para Decisions (ou Inbox) com uma aprovação;
   o humano aprova, rejeita ou pede revisão, com comentário.
6. **Terminar**: `done`, ou `blocked` com a causa escrita. Nada fica como `done` sem evidência.

A regra que vale para o dashboard: **o estado de uma tarefa é sempre o que o agente declarou, com a evidência
ao lado**.

## Usabilidade que foi copiada

- **Abas de estado na lista de tarefas** (Active / Backlog / Done / All) com contagem em cada aba.
- **Badges na sidebar**: quantas tarefas estão ativas e quantas pedem ação, sem precisar abrir a seção.
- **Dashboard com números ao vivo** no topo, antes de qualquer detalhe.
- **Estado de rota pela URL**: cada seção tem um endereço, então dá para voltar, compartilhar e usar o botão
  de voltar do navegador.
- **Busca com atalho** (Ctrl+K) já existia no simplicio-loop e foi mantido.

## Port das telas (escopo escolhido)

O escopo foi escolhido: **Tasks com abas, Inbox com abas, detalhe com thread e Decisões e aprovações**.
O que ficou de cada um:

- **Tasks com abas** (`Ativas`, `Na fila`, `Concluídas`, `Todas`). Igual ao Paperclip na forma, com contagem em cada aba.
  `Na fila` são runs `QUEUED` ou `PENDING`; `Concluídas` inclui os terminais que não falharam (`PASS`, `CANCELLED`).
- **Inbox com abas** (`Todas`, `Recentes`, `Bloqueadas`, `Falhas`). O Paperclip tem `mine`, `unread`, `requests`, `blocked`, `recent`
  e `all`. O simplicio-loop não tem dono por run nem marca de lido, então **`mine`, `unread` e `requests` não foram portados**.
  `Todas` é a fila de atenção (bloqueados e falhas); `Recentes` são runs atualizados nas últimas 24 h.
- **Detalhe com propriedades**: painel à direita com status, repositório, início, fim, duração, atualização e custo.
  Custo aparece como `não medido` quando o run não tem medição. **Thread de comentários não existe**: o simplicio-loop não tem
  comentários. A conversa do run continua sendo o fluxo de eventos da página de tarefa já existente.
- **Decisões e aprovações**: fila dos runs `BLOCKED`, que são os que esperam uma escolha. **Aprovar, rejeitar e pedir revisão não existem no
  painel**: o simplicio-loop não tem endpoint de aprovação. A tela diz isso e a ação continua no terminal.

O que não é fiel ao Paperclip: os nomes e a lógica das abas de Inbox, a thread de comentários e a aprovação. Essas partes
dependem de dados que o simplicio-loop não tem; criar esses dados seria uma mudança de modelo, não de layout.

## O que foi absorvido no simplicio-loop (primeiro rascunho)

| Paperclip | simplicio-loop | Onde |
|---|---|---|
| Sidebar de seções | Sidebar com Painel, Tarefas, Tarefa, Caixa de entrada, Custos e Histórico | `static/shell/shell.js`, `static/live/index.html` |
| Dashboard com contadores | Painel: tarefas ativas, pedem ação, concluídas e total de runs | `shell.js` (`overview`) |
| Tasks com abas de estado | Tarefas com abas Ativas / Concluídas / Todas | `shell-model.js` (`filterRuns`, `countTabs`) |
| Inbox e Decisions | Caixa de entrada: alertas do run (o painel de alertas existente) | `alerts-panel` em `data-view="tarefa caixa"` |
| Costs | Custos: economia de tokens e agentes | `data-view="custos"` |
| Activity / Audit | Histórico: runs anteriores e tendências | `data-view="historico"` |
| Badges na sidebar | Badges de ativas e de pedem ação | `shell-badge`, `renderBadges` |

O detalhe de um run continua a página de pipeline que já existia (quadro por etapa, lanes, gates, DoD,
qualidade, recibos). Ele agora é a seção **Tarefa** da sidebar.

## O que não foi copiado, e por quê

- **Multiempresa, usuários, convites e permissões.** O simplicio-loop é um dashboard local de um repo, com
  token. Não há contas.
- **Plugins, conectores, chat com endpoints, runner remoto e OAuth.** Não se aplicam a um loop local.
- **Cases e Pipelines.** O simplicio-loop já tem fases e runs; uma segunda hierarquia duplicaria isso.
- **Os 685 endpoints da API.** Só foram usadas as leituras que a tela precisa (`/api/runs`, `/api/tokens`).

## Decisões a revisar

- A sidebar é só navegação: ela reaproveita os painéis existentes com `data-view`. Não há visões novas de dados,
  exceto o Painel e a lista de Tarefas, que leem `/api/runs`.
- O limite de peso da página (`test_live_directory_gzips_under_42_kib`) subiu de 40 para 42 KiB para caber
  a sidebar e as duas seções novas. Os arquivos de `static/shell/` não entram nesse número.

Ver também: [docs/DASHBOARD.md](DASHBOARD.md) · [docs/DASHBOARD_DESIGN.md](DASHBOARD_DESIGN.md)

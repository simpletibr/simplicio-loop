# Bench case (spec) — full-stack "adicionar campo ponta-a-ponta" no sindico

Status: **SPEC / proposta** — caso novo, mais complexo que os atuais.
Date: 2026-05-31

## Por que este caso

Os cases atuais do bench exec sindico (`bench/results_exec_sindico.md`) são
**aditivos e backend-only**: adicionar um método a uma classe PHP, um builder de
SQL, parsing de env, etc. — tudo num único arquivo, validado por um PHPUnit oculto.

O pedido operacional é medir **tarefa complexa de verdade**: adicionar um campo que
atravessa **front → back → banco** e validar **ponta a ponta**. Isso exige
coordenar múltiplos arquivos e camadas — um teste muito mais duro de capacidade do
modelo do que os cases single-file. É o caso decisivo para escolher o modelo
default em "testes funcionais do sindico".

## Alvo de execução

Projeto real: **`wesleysimplicio/sistema-sindico`** (PHP 8, PHPUnit 11), o mesmo
usado em `results_exec_sindico.md`.

> **Escopo de acesso:** este repositório (`simplicio-dev-cli`) é o único no escopo
> GitHub da sessão atual. A **execução** deste caso contra `sistema-sindico` (clonar,
> aplicar mudança gerada, migrar banco, rodar suíte) precisa de uma sessão/ambiente
> com acesso àquele repo. Este arquivo entrega a **especificação medível**; a
> execução fica como follow-up (ver "Decisões em aberto" no relatório de decisão).

## Definição do campo (exemplo concreto)

Adicionar o campo **`observacoes`** (texto opcional, máx 500 chars) a uma entidade
de domínio do sindico (ex.: `Ocorrencia` / `Aviso` — ajustar ao schema real).

### Camadas que a mudança deve tocar

1. **Banco (migration):** nova coluna `observacoes VARCHAR(500) NULL` + migration
   reversível. Critério: migration sobe e desce sem erro.
2. **Back (modelo + repositório + validação):** campo no model/DTO, no
   `build_insert_sql`/`build_update_sql` do repositório, e validação
   (`<= 500 chars`, opcional). Critério: round-trip persiste e lê o valor.
3. **Back (API/controller):** aceitar/retornar `observacoes` no endpoint
   create/update. Critério: payload com o campo é aceito; sem o campo, default null.
4. **Front (form):** input do campo no formulário + binding + envio. Critério:
   campo renderiza, aceita texto, envia no submit, exibe valor salvo.

## Plano de validação ponta-a-ponta

- **Banco:** rodar migration up/down; assert da coluna no `information_schema`.
- **Back:** PHPUnit oculto (padrão do harness atual) cobrindo: persistência do
  campo, default null, e a regra de `<= 500 chars` (estado verdadeiro E falso).
  `pass = phpunit exit 0` com a suíte INTEIRA verde (não quebrar nada existente).
- **Front:** Playwright (`playwright.config.ts` já existe no repo) — fluxo:
  abrir form → preencher `observacoes` → salvar → reabrir → asserir valor
  persistido. Evidência: trace + screenshot + video (política de evidências do repo).
- **E2E integrado:** um cenário Playwright que cria o registro pela UI e um assert
  de leitura via API/DB confirmando que o valor chegou ao banco.

## Critérios de aceite do CASE (para comparar modelos)

Um modelo "passa" este case quando, a partir do enunciado da tarefa, gera as
mudanças nas 4 camadas e:

- [ ] migration up/down OK
- [ ] PHPUnit (suíte completa + ocultos do campo) verde
- [ ] Playwright E2E do campo verde com evidência
- [ ] nenhuma regressão na suíte existente

Lados a medir (igual ao harness exec): `baseline | cli | cli+ag`. A hipótese é
que só `cli+ag` (verify-loop) sustenta uma tarefa multi-camada — o loop de
correção é o que fecha integração quebrada entre camadas.

## Como vira métrica no projeto

Adicionar este case a `bench/sindico_cases.py` (como tarefa multi-arquivo) e
estender `bench/run_exec_sindico.py` para suportar diffs multi-arquivo + os 3
gates (migration, phpunit, playwright). Resultado entra na tabela consolidada e
no relatório de decisão de modelo default.

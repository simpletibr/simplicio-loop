---
name: llm-verification
description: verificação independente e adversarial de uma task DEPOIS que o DoD está todo verde, antes de declarar "feito"; ativa ao fechar qualquer task técnica, ao responder "deu ok?" / "verifica de novo", ou quando alguém confunde "verde no DoD" com "concluído de verdade"
---

# Skill: `llm-verification`

DoD todo verde **não** é o mesmo que "feito de verdade". O verde mede *proxy* (teste passou, lint passou, coverage ≥80%); ele não prova que a intenção da task foi atendida. Esta skill é a passada final que fecha esse buraco.

> Princípio central: **uma re-verificação só agrega se for ortogonal à anterior.** Repetir a mesma checagem reproduz o mesmo ponto cego e só serve de teatro. Não basta "+1x igual" — precisa ser de natureza diferente, adversarial.

---

## Trigger

- Ao **fechar** qualquer task técnica com AC mensurável (depois de lint/unit/E2E verdes, antes do commit/PR).
- Quando o usuário pergunta "deu ok?", "verifica de novo", "tudo foi realmente feito?".
- Sempre que houver tentação de declarar concluído só porque o DoD ficou verde.

---

## Steps

1. **Releia a intenção, não o diff.** Abra a AC original da task e cole cada critério lado a lado com o resultado entregue. Para cada um, aponte a **evidência concreta** que o sustenta — não "deve estar ok".
2. **Troque a lente.** Pare de perguntar "tá ok?" (a IA racionaliza o "sim") e pergunte **"onde isto quebra?"**. Liste no mínimo 3 hipóteses de falha.
3. **Exercite a coisa de verdade.** Rode o binário/endpoint/UI real — não só a suíte. Inclua deliberadamente **1 cenário de borda** e **1 caminho de erro** (input vazio, valor extremo, dependência fora, concorrência).
4. **Cace o que o verde não cobre.** Verifique se: a AC foi interpretada torta, o teste testa a coisa errada, a suíte só cobre golden path, há efeito colateral fora do diff.
5. **Garanta independência.** Se a passada usar a mesma lente de quem escreveu, ela não conta. Busque ângulo diferente — delegue a um sub-agent sem o contexto de autoria, ou aos reviewers (`reviewer.agent.md`, `security-reviewer`).
6. **Registre o resultado adversarial.** Anote no PR/`PROGRESS.md` o que você *tentou quebrar* e o que aguentou. Sem isso, a verificação não aconteceu.

---

## Padrões

- **"+1x igual" é teatro.** A passada só conta se mudar de ângulo/lente em relação à anterior.
- **Verde no DoD ≠ feito.** O DoD mede sintoma; valide contra a intenção.
- **Nunca formule como confirmação.** "Deu ok?" enviesa pro "sim". Formule sempre como busca de defeito: "onde falha?".
- **Não existe 100% absoluto.** O alvo é **risco residual aceitável com evidência**, não certeza.
- **Verificação independente > auto-verificação.** Revisor fresco pega o que o autor não vê.

---

## Definition of Done

- [ ] AC relida lado a lado com o resultado, **cada critério com evidência concreta** apontada.
- [ ] Pelo menos **1 cenário de borda + 1 caminho de erro** exercitados ativamente (não só golden path).
- [ ] Feature **rodada de verdade** (binário/endpoint/UI), não apenas a suíte de testes.
- [ ] Passada de verificação é **ortogonal** à anterior (ângulo/lente diferente), não repetição.
- [ ] Resultado adversarial **registrado** (o que tentou quebrar, o que aguentou).
- [ ] Nenhum item verde aceito sem evidência que o sustente.

---

## Exemplo

```text
Task: "CLI deve aceitar --model e cair pro default quando ausente."

Verde no DoD: unit cobre --model=x e ausência -> default. Tudo passa.

Passada adversarial (ortogonal):
  - hipótese 1: --model="" (string vazia, não ausente) -> cai no default? -> NÃO, crasha. BUG.
  - hipótese 2: --model com espaço " gpt " -> trim? -> não trata. risco.
  - hipótese 3: --model repetido duas vezes -> qual vence? -> indefinido.
Registro: 1 bug real (string vazia) que o golden-path-only não pegou.
=> task NÃO estava feita, apesar do verde.
```

---

## Notas

- Esta skill é a operacionalização do item de DoD "Verificação independente/adversarial pós-verde" (ver `AGENTS.md` / `CLAUDE.md`).
- Última revisão: 2026-05-27.

<!-- simplicio-global-llm-architecture-rules:start -->
## Regras arquiteturais globais (obrigatórias)

- Delete diretamente o que está obsoleto; não preserve compatibilidade retroativa,
  não crie migrações e não deixe fallbacks.
- Escolha a implementação mais simples para a necessidade atual; sem abstrações
  preventivas ou configuração desnecessária.
- Entregue primeiro o mínimo end-to-end e evolua por camadas longas, sem desmontar
  o que funciona por complexidade inacabada.
- Mantenha modularidade e separação clara de responsabilidades.
- Prefira bibliotecas maduras e mantidas; reescreva do zero apenas com motivo
  técnico explícito.
- Inspecione as dependências existentes antes de adicionar pacotes ou reimplementar.
- Tome decisões arquiteturais para o longo prazo; não deixe soluções temporárias.
- Reutilize padrões validados por produtos maduros; não reinvente a roda.

<!-- simplicio-global-llm-architecture-rules:end -->


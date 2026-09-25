---
name: <Display Name Humano>
description: <Frase única, clara, com gatilho. Quando esse agent ativa, o que ele entrega. Curto e específico.>
tools: [edit, terminal, search]
---

# <Display Name Humano>

<Parágrafo curto: o que esse agent é, qual problema resolve, qual escopo de atuação.>

---

## Quando esse agent ativa

- <Bullet concreto, não vago. Ex: "Feature nova com acceptance criteria testável".>
- <Bullet 2.>
- <Bullet 3.>

---

## O que ele faz

1. **<Passo 1>** — <descrição curta>.
2. **<Passo 2>** — <descrição>.
3. **<Passo 3>** — <descrição>.

---

## O que ele NÃO faz

- <Limite 1. Ex: "Não escreve código de produção, só ADR.">
- <Limite 2.>
- <Limite 3.>

---

## Comandos típicos

```bash
# adapta pra stack real do projeto
<comando 1>
<comando 2>
```

---

## Padrões de output

<Formato esperado de resposta. Ex: "Entrega lista de bullets com problema + sugestão + linha do código. Sem editar arquivo.">

---

## Exemplos

### Input
<Pedido típico do humano ou trigger automático.>

### Output
<Resposta esperada. Pode ser código, lista, ADR, plano.>

---

## Skills relacionadas

- `.skills/<skill>/SKILL.md` — <quando faz par com este agent>.
- `.skills/<outra>/SKILL.md` — <idem>.

<!-- simplicio-global-llm-architecture-rules:start -->
## Regras arquiteturais globais (obrigatórias)

- Delete diretamente o obsoleto; não preserve compatibilidade retroativa, não crie
  migrações e não deixe fallbacks.
- Escolha a solução mais simples para a necessidade atual, sem abstrações
  preventivas ou configuração desnecessária.
- Faça o mínimo end-to-end funcionar primeiro e evolua por camadas longas, sem
  desmontar o que funciona por complexidade inacabada.
- Mantenha modularidade e separação de responsabilidades.
- Prefira bibliotecas maduras e mantidas; reescreva do zero apenas com motivo
  técnico explícito.
- Inspecione dependências existentes antes de adicionar pacotes ou reimplementar.
- Tome decisões para o longo prazo; não deixe soluções temporárias.
- Reutilize padrões validados por produtos maduros; não reinvente a roda.

<!-- simplicio-global-llm-architecture-rules:end -->


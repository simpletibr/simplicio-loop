Sistema: PLANES
Funcionalidade: Tela de Modelagem — Ordenação de linhas
Tipo: Evolução

COMO analista do ONS,
QUERO que as linhas da tela de modelagem sejam ordenadas por tipo (estrutural primeiro) e depois por data de início (mais antigo para mais novo) entre temporais e modelagem,
PARA que a visualização dos dados siga uma ordem lógica e facilite a análise dos estudos.

1. Critérios de Aceite

Cenário 1: Estrutural aparece primeiro
  Dado que a usina possui linhas do tipo estrutural, temporal e modelagem
  Quando a tela de modelagem for exibida
  Então a linha do tipo estrutural deve aparecer primeiro [RN01]

Cenário 2: Temporal e modelagem ordenados por data de início
  Dado que a usina possui múltiplas linhas dos tipos temporal e modelagem
  Quando a tela de modelagem for exibida
  Então as linhas temporais e de modelagem devem ser ordenadas por data de início, do mais antigo para o mais novo [RN02]

Cenário 3: Temporal e modelagem se misturam pela data
  Dado que a usina possui uma linha temporal com início em 01/08 e uma linha de modelagem com início em 01/07
  Quando a tela de modelagem for exibida
  Então a linha de modelagem (01/07) deve aparecer antes da temporal (01/08), pois a ordenação é por data independente do subtipo [RN02]

Cenário 4: Ordenação por usina em ordem alfabética
  Dado que existem múltiplas usinas na tela de modelagem
  Quando a tela for exibida
  Então as usinas devem estar em ordem alfabética [RN03]

Cenário 5: Regras de ordenação combinadas
  Dado que existem múltiplas usinas com múltiplas linhas cada
  Quando a tela de modelagem for exibida
  Então a ordenação deve respeitar: 1º usina em ordem alfabética, 2º estrutural primeiro, 3º temporal/modelagem por data de início (mais antigo → mais novo) [RN01][RN02][RN03]

2. Regras de Negócio

RN01 – Dentro de cada usina, a linha do tipo estrutural deve sempre aparecer primeiro (é única por usina e não possui datas).
RN02 – Após o estrutural, as linhas dos tipos temporal e modelagem devem ser ordenadas por data de início, do mais antigo para o mais novo. O tipo (temporal vs modelagem) não define a ordem — o que define é a data.
RN03 – As usinas devem ser exibidas em ordem alfabética.

3. Requisitos Não Funcionais

Nenhum requisito não-funcional identificado na entrada — validar com o time.

4. Protótipos

Referência visual (exemplo do problema de ordenação reportado pelo Wellington — item fora de ordem):

5. Acesso

Menu > Estudo > Tela de Modelagem

6. Dependências

Nenhuma dependência identificada na entrada — validar com o time.

7. Sinais de Impacto

Frontend: ✓ (ajuste na ordenação da listagem na tela de modelagem)
Backend: Possível (a ordenação pode vir do backend ou ser aplicada no frontend — a definir)
Banco: ✗
Integrações: ✗

8. Informações Adicionais

- O problema foi identificado no PMO de Julho em Produção: uma linha temporal com data 01/09 aparecia após linhas com datas posteriores, quebrando a sequência lógica.
- A regra anterior já previa "primeiro estrutural, depois temporal", mas faltava a ordenação por data de início dentro do bloco temporal/modelagem.
- Sem pendências.

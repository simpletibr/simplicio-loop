# simplicio-fast

[English](../README.md) · **Português**

Contexto semântico binário, incremental e mapeado em memória para agentes de software.

## Como funciona

O projeto transforma arquivos-fonte normais em um snapshot derivado `.sfast`. O snapshot é lido
com `mmap`, arquivos inalterados são reutilizados por SHA-256 e somente os trechos necessários são
entregues ao agente. Os fontes continuam sendo a única verdade.

## Resultado medido

Na POC com 500 arquivos e 1.500 símbolos, a consulta via `mmap` foi aproximadamente 23× mais rápida
e consumiu 95,65% menos CPU que analisar todas as ASTs novamente. Não é garantia universal:
projetos pequenos e a primeira execução podem não obter ganho.

## Instalação e uso

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast
python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

No fluxo oficial de agentes, `simplicio-mapper` é obrigatório e continua sendo o produtor do
ContextGraph canônico. Consulte [AGENTS.md](../AGENTS.md), o [README completo](../README.md) e o
[épico de integração](https://github.com/wesleysimplicio/simplicio-fast/issues/1).

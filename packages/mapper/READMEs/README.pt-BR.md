# simplicio-mapper

> Transforme um repositório em contexto limitado, consultável e confiável para pessoas e agentes de IA.

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/) [![Python](https://img.shields.io/pypi/pyversions/simplicio-mapper?color=22c55e&label=Python)](https://pypi.org/project/simplicio-mapper/)

[README canônico e todos os idiomas](../README.md)

<p align="center">
  <a href="../video/assets/simplicio-mapper-ink-press.pt-BR.mp4"><img src="../assets/llm-project-mapper-hero.png" alt="Um repositório se tornando contexto limitado e sustentado por evidências" width="100%"></a>
  <br>
  <strong><a href="../video/assets/simplicio-mapper-ink-press.pt-BR.mp4">Assista ao filme de produto de 36 segundos</a></strong>
</p>

O `simplicio-mapper` transforma uma base de código em artefatos versionados em `.simplicio/`: arquitetura, símbolos, fluxos, regras, testes e pacotes de contexto orientados por tarefa. Ele é o motor de mapeamento do ecossistema Simplicio, feito para tornar o conhecimento do repositório pequeno o suficiente para inspeção e explícito o suficiente para auditoria.

## Comece aqui

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "rastreie o fluxo de autenticação" --token-budget 1200 --json
```

## O que o diferencia

- **Recuperação com limite:** `handoff` e `orient` informam relevância, cobertura, orçamento de tokens, penalidades e fidelidade; não despejam silenciosamente todo o repositório no prompt.
- **Contexto sensível a mudanças:** `sync`, `history`, `diff` e `delta` mantêm o ContextGraph atualizado entre mudanças e sessões.
- **Contratos de evidência:** schemas públicos, validação, etiquetas de confiança, recibos comportamentais e certificados distinguem fatos medidos de alegações sem suporte.
- **Resultados úteis:** mapa do projeto, documentos de arquitetura, inventários de endpoints e telas, fluxos, regras de negócio, pesquisas de onboarding e consultas ao grafo.

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

O pacote Python é o motor canônico. O pacote npm [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) é um starter complementar para novos projetos.

Veja o [site de documentação](https://wesleysimplicio.github.io/simplicio-mapper/), [contratos](../contracts/), [guia de integração](../SIMPLICIO_INTEGRATION.md) e a [release v0.23.1](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1). Licença [MIT](../LICENSE).

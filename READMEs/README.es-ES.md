# simplicio-mapper

> Convierte un repositorio en contexto acotado, consultable y fiable para personas y agentes de IA.

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/)

[README canónico y todos los idiomas](../README.md)

<p align="center"><img src="../assets/llm-project-mapper-hero.png" alt="Un repositorio transformado en contexto acotado respaldado por evidencia" width="100%"></p>

`simplicio-mapper` convierte una base de código en artefactos versionados bajo `.simplicio/`: arquitectura, símbolos, flujos, reglas, pruebas y paquetes de contexto orientados a tareas. Es el motor de mapeo del ecosistema Simplicio: conocimiento suficientemente pequeño para inspeccionarlo y suficientemente explícito para auditarlo.

## Inicio rápido

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "rastrear el flujo de autenticación" --token-budget 1200 --json
```

## Por qué importa

- **Recuperación acotada:** `handoff` y `orient` muestran relevancia, cobertura, presupuesto de tokens, penalizaciones y fidelidad, en lugar de volcar el repositorio completo en un prompt.
- **Contexto que sigue los cambios:** `sync`, `history`, `diff` y `delta` mantienen el ContextGraph actualizado entre cambios y sesiones.
- **Contratos de evidencia:** esquemas públicos, validación, etiquetas de confianza, recibos de comportamiento y certificados separan hechos medidos de afirmaciones sin respaldo.
- **Resultados prácticos:** mapas, documentación de arquitectura, inventarios de endpoints y pantallas, flujos, reglas de negocio, encuestas de onboarding y consultas al grafo.

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

El paquete Python es el motor canónico. [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) para npm es un starter complementario.

Consulta el [sitio de documentación](https://wesleysimplicio.github.io/simplicio-mapper/), los [contratos](../contracts/), la [guía de integración](../SIMPLICIO_INTEGRATION.md) y la [release v0.23.1](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1). Licencia [MIT](../LICENSE).

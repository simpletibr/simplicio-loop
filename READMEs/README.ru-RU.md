# simplicio-mapper

> Превращает репозиторий в ограниченный, доступный для запросов и надёжный контекст для людей и ИИ-агентов.

[![PyPI](https://img.shields.io/pypi/v/simplicio-mapper?color=0ea5e9&label=PyPI)](https://pypi.org/project/simplicio-mapper/)

[Канонический README и все языки](../README.md)

<p align="center"><img src="../assets/llm-project-mapper-hero.png" alt="Репозиторий превращается в ограниченный контекст, подкреплённый доказательствами" width="100%"></p>

`simplicio-mapper` превращает кодовую базу в версионируемые артефакты в `.simplicio/`: архитектуру, символы, потоки, правила, тесты и контекстные пакеты для задач. Это движок картирования экосистемы Simplicio: знания о репозитории достаточно компактны для проверки и достаточно явны для аудита.

## Быстрый старт

```bash
pip install -U simplicio-mapper
simplicio-mapper index . --json
simplicio-mapper docs . --json
simplicio-mapper handoff . --goal "проследить поток аутентификации" --token-budget 1200 --json
```

## Чем он отличается

- **Ограниченное извлечение:** `handoff` и `orient` показывают релевантность, покрытие, бюджет токенов, штрафы и достоверность, а не незаметно передают весь репозиторий в prompt.
- **Контекст, учитывающий изменения:** `sync`, `history`, `diff` и `delta` поддерживают ContextGraph между изменениями и сессиями.
- **Контракты доказательств:** открытые схемы, валидация, теги уверенности, поведенческие квитанции и сертификаты отделяют измеренные факты от неподтверждённых утверждений.
- **Практические результаты:** карты проекта, документация архитектуры, инвентари endpoints и экранов, потоки, бизнес-правила, onboarding-опросы и запросы графа.

```bash
simplicio-mapper ask . impact "UserService" --json
simplicio-mapper sync . --check --json
simplicio-mapper contract validate .simplicio
simplicio-mapper doctor --contracts
```

Пакет Python — канонический движок. npm-пакет [`@wesleysimplicio/llm-project-mapper`](https://www.npmjs.com/package/@wesleysimplicio/llm-project-mapper) — дополнительный starter.

Смотрите [сайт документации](https://wesleysimplicio.github.io/simplicio-mapper/), [контракты](../contracts/), [руководство по интеграции](../SIMPLICIO_INTEGRATION.md) и [release v0.23.1](https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.23.1). Лицензия [MIT](../LICENSE).

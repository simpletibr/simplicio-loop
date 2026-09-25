# simplicio-fast

[English](../README.md) · **Русский**

Бинарный, инкрементальный и отображаемый в память семантический контекст для программных агентов.

Обычные исходные файлы создают производный кэш `.sfast`, читаемый через `mmap`. Неизменённые
файлы повторно используются по SHA-256, а исходный код остаётся единственным источником истины.

В POC на 500 файлах и 1 500 символах запрос выполнялся примерно в 23 раза быстрее и использовал
на 95,65% меньше CPU. Это измеренный результат, а не универсальная гарантия.

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast && python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

В официальном агентном потоке `simplicio-mapper` обязателен и создаёт канонический ContextGraph.
См. [AGENTS.md](../AGENTS.md) и [полный README](../README.md).

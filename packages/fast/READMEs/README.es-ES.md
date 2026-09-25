# simplicio-fast

[English](../README.md) · **Español**

Contexto semántico binario, incremental y mapeado en memoria para agentes de software.

Convierte los archivos fuente normales en una caché derivada `.sfast`, la consulta mediante
`mmap` y reutiliza por SHA-256 los archivos sin cambios. El código fuente sigue siendo la única
fuente de verdad.

En la POC de 500 archivos y 1.500 símbolos, la consulta fue aproximadamente 23 veces más rápida y
usó un 95,65 % menos de CPU. Es un resultado medido, no una garantía universal.

```bash
git clone https://github.com/wesleysimplicio/simplicio-fast
cd simplicio-fast && python -m pip install -e .
simplicio-fast build .
simplicio-fast doctor
simplicio-fast context UserService --root .
```

`simplicio-mapper` es obligatorio en el flujo oficial de agentes y conserva el ContextGraph
canónico. Consulte [AGENTS.md](../AGENTS.md) y el [README completo](../README.md).

# Simplicio LLM surface

Loop exposes a compact, stable index so an LLM can discover the available
capabilities before loading a full skill. The index is intentionally separate
from execution contracts: it names the skill, effect, prerequisites and the
existing adapter that owns execution.

```bash
simplicio-capabilities --json
simplicio-capabilities mapper
simplicio-route "corrigir os testes de autenticação"
```

The catalog follows `simplicio.capability-catalog/v1`; routes follow
`simplicio.route/v1`. `skills_to_load` is the minimal skill set for the route.
Prism expands declared prerequisites before returning `order`, so a route never
asks an LLM to load a capability without its required precondition. Portuguese
terms such as `validar`, `verificar`, `orquestrar`, `delegar`, `paralelo` and
`abrir PR` are recognized alongside their English equivalents.
The `existing_adapters` field points at the established `scripts/preflight.py`
and `scripts/route_mode.py` surfaces, so discovery does not
create a second orchestration or preflight protocol.


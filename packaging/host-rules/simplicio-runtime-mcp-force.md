# Runtime is a different product

`simplicio-runtime` (binary `simplicio`, MCP tools such as `simplicio_map`) is
**not** part of the simplicio-loop stack. This file exists so host installers
have a stable path to copy; Loop does **not** load Runtime MCP and does **not**
set `SIMPLICIO_REQUIRE_MCP` / `SIMPLICIO_MCP_FORCE` / `SIMPLICIO_LOOP_REQUIRE_RUNTIME`.

Public stack: mapper + fast + simplicio-dev-cli + loop. Runtime is **not mandatory**
here. Do not treat `which simplicio` as a Loop operator.

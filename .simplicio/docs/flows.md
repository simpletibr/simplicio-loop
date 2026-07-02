# Flow Inventory

Auto-generated from the call graph. A flow starts at a detected entry point (CLI command, `main`, bin/ script) and follows `calls` edges to the effects it produces (filesystem, network, subprocess, cache/DB).

> Steps and effects are **observed** from static analysis (evidence `path:line`). Dynamic dispatch (e.g. a string-keyed command table) is not followed by the call graph and may under-report steps — see `confidence`.

## Coverage

- Entry points detected: 8
- Entry points with a derived flow: 5
- Total flows: 8

## `bin.apply.edits`

- Kind: cli-command
- Entry: `bin/apply-edits.js` (`bin/apply-edits.js::EditError`)
- Confidence: observed
- Layers touched: entrypoint

#### Steps

```mermaid
flowchart LR
  bin_apply_edits_js["bin/apply-edits.js"]
```

<details><summary>Full list</summary>

- bin/apply-edits.js (`bin/apply-edits.js`)

</details>

**Effects**

| Type | Evidence |
| --- | --- |
| reads filesystem | `bin/apply-edits.js:74` |
| reads filesystem | `bin/apply-edits.js:348` |
| writes filesystem | `bin/apply-edits.js:292` |

## `bin.build.hamt.catalog`

- Kind: cli-command
- Entry: `bin/build-hamt-catalog`
- Confidence: heuristic
- Layers touched: entrypoint

#### Steps

```mermaid
flowchart LR
  bin_build_hamt_catalog["bin/build-hamt-catalog"]
```

<details><summary>Full list</summary>

- bin/build-hamt-catalog (`bin/build-hamt-catalog`)

</details>

_No observable effects detected for this flow._

## `bin.cli`

- Kind: cli-command
- Entry: `bin/cli.js` (`bin/cli.js::printHelp`)
- Confidence: observed
- Layers touched: code, entrypoint

#### Steps

```mermaid
flowchart LR
  bin_apply_edits_js["bin/apply-edits.js"]
  bin_auto_map_js["bin/auto-map.js"]
  bin_cli_js["bin/cli.js"]
  bin_apply_edits_js --> bin_auto_map_js
  bin_cli_js --> bin_apply_edits_js
```

<details><summary>Full list</summary>

- bin/apply-edits.js (`bin/apply-edits.js`)
- bin/auto-map.js (`bin/auto-map.js`)
- bin/cli.js (`bin/cli.js`)

</details>

**Effects**

| Type | Evidence |
| --- | --- |
| reads filesystem | `bin/apply-edits.js:74` |
| reads filesystem | `bin/apply-edits.js:348` |
| reads filesystem | `bin/auto-map.js:25` |
| reads filesystem | `bin/cli.js:434` |
| reads filesystem | `bin/cli.js:466` |
| reads filesystem | `bin/cli.js:542` |
| reads filesystem | `bin/cli.js:749` |
| reads filesystem | `bin/cli.js:1014` |
| writes filesystem | `bin/apply-edits.js:292` |
| writes filesystem | `bin/auto-map.js:1157` |
| writes filesystem | `bin/auto-map.js:1169` |
| writes filesystem | `bin/cli.js:453` |
| writes filesystem | `bin/cli.js:481` |
| writes filesystem | `bin/cli.js:829` |
| writes filesystem | `bin/cli.js:839` |
| writes filesystem | `bin/cli.js:848` |
| writes filesystem | `bin/cli.js:889` |
| writes filesystem | `bin/cli.js:1027` |
| writes filesystem | `bin/cli.js:1114` |

## `bin.skillopt`

- Kind: cli-command
- Entry: `bin/skillopt.js` (`bin/skillopt.js::printHelp`)
- Confidence: observed
- Layers touched: code, entrypoint

#### Steps

```mermaid
flowchart LR
  bin_apply_edits_js["bin/apply-edits.js"]
  bin_auto_map_js["bin/auto-map.js"]
  bin_cli_js["bin/cli.js"]
  bin_map_js["bin/map.js"]
  bin_skillopt_js["bin/skillopt.js"]
  bin_apply_edits_js --> bin_cli_js
  bin_cli_js --> bin_map_js
  bin_map_js --> bin_auto_map_js
  bin_skillopt_js --> bin_apply_edits_js
```

<details><summary>Full list</summary>

- bin/apply-edits.js (`bin/apply-edits.js`)
- bin/auto-map.js (`bin/auto-map.js`)
- bin/cli.js (`bin/cli.js`)
- bin/map.js (`bin/map.js`)
- bin/skillopt.js (`bin/skillopt.js`)

</details>

**Effects**

| Type | Evidence |
| --- | --- |
| reads filesystem | `bin/apply-edits.js:74` |
| reads filesystem | `bin/apply-edits.js:348` |
| reads filesystem | `bin/auto-map.js:25` |
| reads filesystem | `bin/cli.js:434` |
| reads filesystem | `bin/cli.js:466` |
| reads filesystem | `bin/cli.js:542` |
| reads filesystem | `bin/cli.js:749` |
| reads filesystem | `bin/cli.js:1014` |
| reads filesystem | `bin/map.js:10` |
| reads filesystem | `bin/skillopt.js:79` |
| reads filesystem | `bin/skillopt.js:145` |
| writes filesystem | `bin/apply-edits.js:292` |
| writes filesystem | `bin/auto-map.js:1157` |
| writes filesystem | `bin/auto-map.js:1169` |
| writes filesystem | `bin/cli.js:453` |
| writes filesystem | `bin/cli.js:481` |
| writes filesystem | `bin/cli.js:829` |
| writes filesystem | `bin/cli.js:839` |
| writes filesystem | `bin/cli.js:848` |
| writes filesystem | `bin/cli.js:889` |
| writes filesystem | `bin/cli.js:1027` |
| writes filesystem | `bin/cli.js:1114` |
| writes filesystem | `bin/skillopt.js:105` |
| writes filesystem | `bin/skillopt.js:163` |
| writes filesystem | `bin/skillopt.js:167` |

## `docs.api.examples.cli`

- Kind: entrypoint
- Entry: `docs/api-examples/cli.md`
- Confidence: heuristic
- Layers touched: documentation, entrypoint

#### Steps

```mermaid
flowchart LR
  docs_api_examples_cli_md["docs/api-examples/cli.md"]
```

<details><summary>Full list</summary>

- docs/api-examples/cli.md (`docs/api-examples/cli.md`)

</details>

_No observable effects detected for this flow._

## `simplicio.mapper.cli`

- Kind: entrypoint
- Entry: `simplicio_mapper/cli.py` (`simplicio_mapper/cli.py::_read_json_safe`)
- Confidence: observed
- Layers touched: code, entrypoint

#### Steps

```mermaid
flowchart LR
  bin_apply_edits_js["bin/apply-edits.js"]
  bin_auto_map_js["bin/auto-map.js"]
  bin_cli_js["bin/cli.js"]
  bin_mapper_artifacts_js["bin/mapper-artifacts.js"]
  simplicio_mapper_cli_py["simplicio_mapper/cli.py"]
  bin_apply_edits_js --> bin_auto_map_js
  bin_auto_map_js --> bin_cli_js
  bin_cli_js --> bin_mapper_artifacts_js
  simplicio_mapper_cli_py --> bin_apply_edits_js
```

<details><summary>Full list</summary>

- bin/apply-edits.js (`bin/apply-edits.js`)
- bin/auto-map.js (`bin/auto-map.js`)
- bin/cli.js (`bin/cli.js`)
- bin/mapper-artifacts.js (`bin/mapper-artifacts.js`)
- simplicio_mapper/cli.py (`simplicio_mapper/cli.py`)

</details>

**Effects**

| Type | Evidence |
| --- | --- |
| reads filesystem | `bin/apply-edits.js:74` |
| reads filesystem | `bin/apply-edits.js:348` |
| reads filesystem | `bin/auto-map.js:25` |
| reads filesystem | `bin/cli.js:434` |
| reads filesystem | `bin/cli.js:466` |
| reads filesystem | `bin/cli.js:542` |
| reads filesystem | `bin/cli.js:749` |
| reads filesystem | `bin/cli.js:1014` |
| reads filesystem | `bin/mapper-artifacts.js:63` |
| reads filesystem | `bin/mapper-artifacts.js:380` |
| reads filesystem | `simplicio_mapper/cli.py:720` |
| reads filesystem | `simplicio_mapper/cli.py:1017` |
| reads filesystem | `simplicio_mapper/cli.py:1106` |
| reads filesystem | `simplicio_mapper/cli.py:1140` |
| reads filesystem | `simplicio_mapper/cli.py:1465` |
| writes filesystem | `bin/apply-edits.js:292` |
| writes filesystem | `bin/auto-map.js:1157` |
| writes filesystem | `bin/auto-map.js:1169` |
| writes filesystem | `bin/cli.js:453` |
| writes filesystem | `bin/cli.js:481` |
| writes filesystem | `bin/cli.js:829` |
| writes filesystem | `bin/cli.js:839` |
| writes filesystem | `bin/cli.js:848` |
| writes filesystem | `bin/cli.js:889` |
| writes filesystem | `bin/cli.js:1027` |
| writes filesystem | `bin/cli.js:1114` |
| writes filesystem | `bin/mapper-artifacts.js:894` |
| writes filesystem | `simplicio_mapper/cli.py:392` |
| writes filesystem | `simplicio_mapper/cli.py:506` |
| writes filesystem | `simplicio_mapper/cli.py:507` |
| writes filesystem | `simplicio_mapper/cli.py:1689` |
| writes filesystem | `simplicio_mapper/cli.py:1691` |
| writes filesystem | `simplicio_mapper/cli.py:1721` |
| writes filesystem | `simplicio_mapper/cli.py:1722` |
| writes filesystem | `simplicio_mapper/cli.py:1723` |
| writes filesystem | `simplicio_mapper/cli.py:1729` |
| writes filesystem | `simplicio_mapper/cli.py:1731` |
| writes filesystem | `simplicio_mapper/cli.py:1814` |
| writes filesystem | `simplicio_mapper/cli.py:1815` |
| writes filesystem | `simplicio_mapper/cli.py:1816` |
| writes filesystem | `simplicio_mapper/cli.py:1821` |
| writes filesystem | `simplicio_mapper/cli.py:1823` |
| writes filesystem | `simplicio_mapper/cli.py:1849` |
| writes filesystem | `simplicio_mapper/cli.py:1851` |
| writes filesystem | `simplicio_mapper/cli.py:1857` |
| writes filesystem | `simplicio_mapper/cli.py:1884` |
| writes filesystem | `simplicio_mapper/cli.py:1885` |
| writes filesystem | `simplicio_mapper/cli.py:1886` |
| writes filesystem | `simplicio_mapper/cli.py:1891` |
| writes filesystem | `simplicio_mapper/cli.py:1893` |
| writes filesystem | `simplicio_mapper/cli.py:2432` |
| spawns subprocess | `simplicio_mapper/cli.py:425` |
| spawns subprocess | `simplicio_mapper/cli.py:434` |
| spawns subprocess | `simplicio_mapper/cli.py:441` |
| spawns subprocess | `simplicio_mapper/cli.py:456` |
| spawns subprocess | `simplicio_mapper/cli.py:1992` |
| spawns subprocess | `simplicio_mapper/cli.py:1997` |

## `tests.fixtures.parity.host.src.index`

- Kind: entrypoint
- Entry: `tests/fixtures/parity-host/src/index.js` (`tests/fixtures/parity-host/src/index.js::startServer`)
- Confidence: observed
- Layers touched: code, entrypoint, test

#### Steps

```mermaid
flowchart LR
  bin_apply_edits_js["bin/apply-edits.js"]
  bin_auto_map_js["bin/auto-map.js"]
  bin_cli_js["bin/cli.js"]
  bin_map_js["bin/map.js"]
  bin_skillopt_js["bin/skillopt.js"]
  packaging_npm_lib_python_shim_js["packaging/npm/lib/python-shim.js"]
  simplicio_mapper_cache_py["simplicio_mapper/cache.py"]
  simplicio_mapper_context_cache_py["simplicio_mapper/context_cache.py"]
  tests_fixtures_mech_edit_host_sample_py["tests/fixtures/mech-edit-host/sample.py"]
  tests_fixtures_mech_edit_host_sample_ts["tests/fixtures/mech-edit-host/sample.ts"]
  tests_fixtures_parity_host_src_greet_js["tests/fixtures/parity-host/src/greet.js"]
  tests_fixtures_parity_host_src_index_js["tests/fixtures/parity-host/src/index.js"]
  tests_python_test_cli_py["tests/python/test_cli.py"]
  bin_apply_edits_js --> bin_auto_map_js
  bin_auto_map_js --> bin_cli_js
  bin_cli_js --> bin_skillopt_js
  bin_skillopt_js --> packaging_npm_lib_python_shim_js
  packaging_npm_lib_python_shim_js --> bin_map_js
  simplicio_mapper_cache_py --> bin_apply_edits_js
  simplicio_mapper_context_cache_py --> tests_fixtures_mech_edit_host_sample_py
  tests_fixtures_mech_edit_host_sample_py --> tests_fixtures_mech_edit_host_sample_ts
  tests_fixtures_mech_edit_host_sample_ts --> tests_fixtures_parity_host_src_greet_js
  tests_fixtures_parity_host_src_greet_js --> tests_python_test_cli_py
  tests_fixtures_parity_host_src_index_js --> simplicio_mapper_context_cache_py
  tests_python_test_cli_py --> simplicio_mapper_cache_py
```

<details><summary>Full list</summary>

- bin/apply-edits.js (`bin/apply-edits.js`)
- bin/auto-map.js (`bin/auto-map.js`)
- bin/cli.js (`bin/cli.js`)
- bin/map.js (`bin/map.js`)
- bin/skillopt.js (`bin/skillopt.js`)
- packaging/npm/lib/python-shim.js (`packaging/npm/lib/python-shim.js`)
- simplicio_mapper/cache.py (`simplicio_mapper/cache.py`)
- simplicio_mapper/context_cache.py (`simplicio_mapper/context_cache.py`)
- tests/fixtures/mech-edit-host/sample.py (`tests/fixtures/mech-edit-host/sample.py`)
- tests/fixtures/mech-edit-host/sample.ts (`tests/fixtures/mech-edit-host/sample.ts`)
- tests/fixtures/parity-host/src/greet.js (`tests/fixtures/parity-host/src/greet.js`)
- tests/fixtures/parity-host/src/index.js (`tests/fixtures/parity-host/src/index.js`)
- tests/python/test_cli.py (`tests/python/test_cli.py`)

</details>

**Effects**

| Type | Evidence |
| --- | --- |
| touches cache/DB | `simplicio_mapper/cache.py:9` |
| touches cache/DB | `simplicio_mapper/cache.py:12` |
| touches cache/DB | `simplicio_mapper/cache.py:27` |
| touches cache/DB | `tests/python/test_cli.py:23` |
| touches cache/DB | `tests/python/test_cli.py:51` |
| touches cache/DB | `tests/python/test_cli.py:54` |
| touches cache/DB | `tests/python/test_cli.py:659` |
| reads filesystem | `bin/apply-edits.js:74` |
| reads filesystem | `bin/apply-edits.js:348` |
| reads filesystem | `bin/auto-map.js:25` |
| reads filesystem | `bin/cli.js:434` |
| reads filesystem | `bin/cli.js:466` |
| reads filesystem | `bin/cli.js:542` |
| reads filesystem | `bin/cli.js:749` |
| reads filesystem | `bin/cli.js:1014` |
| reads filesystem | `bin/map.js:10` |
| reads filesystem | `bin/skillopt.js:79` |
| reads filesystem | `bin/skillopt.js:145` |
| reads filesystem | `packaging/npm/lib/python-shim.js:96` |
| writes filesystem | `bin/apply-edits.js:292` |
| writes filesystem | `bin/auto-map.js:1157` |
| writes filesystem | `bin/auto-map.js:1169` |
| writes filesystem | `bin/cli.js:453` |
| writes filesystem | `bin/cli.js:481` |
| writes filesystem | `bin/cli.js:829` |
| writes filesystem | `bin/cli.js:839` |
| writes filesystem | `bin/cli.js:848` |
| writes filesystem | `bin/cli.js:889` |
| writes filesystem | `bin/cli.js:1027` |
| writes filesystem | `bin/cli.js:1114` |
| writes filesystem | `bin/skillopt.js:105` |
| writes filesystem | `bin/skillopt.js:163` |
| writes filesystem | `bin/skillopt.js:167` |
| writes filesystem | `packaging/npm/lib/python-shim.js:102` |
| writes filesystem | `simplicio_mapper/context_cache.py:81` |
| writes filesystem | `simplicio_mapper/context_cache.py:82` |
| spawns subprocess | `tests/python/test_cli.py:238` |
| spawns subprocess | `tests/python/test_cli.py:861` |
| spawns subprocess | `tests/python/test_cli.py:862` |
| spawns subprocess | `tests/python/test_cli.py:863` |
| spawns subprocess | `tests/python/test_cli.py:866` |
| spawns subprocess | `tests/python/test_cli.py:867` |

## `video.src.index`

- Kind: entrypoint
- Entry: `video/src/index.ts`
- Confidence: heuristic
- Layers touched: entrypoint

#### Steps

```mermaid
flowchart LR
  video_src_index_ts["video/src/index.ts"]
```

<details><summary>Full list</summary>

- video/src/index.ts (`video/src/index.ts`)

</details>

_No observable effects detected for this flow._

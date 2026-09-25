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

![Flow steps diagram](diagrams/flows/bin-apply-edits-0-steps.svg)

#### Steps

```mermaid
flowchart LR
  bin_apply_edits_js["bin/apply-edits.js"]
```

<details><summary>Full list</summary>

- bin/apply-edits.js (`bin/apply-edits.js`)

</details>

![Call sequence diagram](diagrams/flows/bin-apply-edits-0-sequence.svg)

#### Call Sequence

```mermaid
sequenceDiagram
  participant bin_apply_edits_js as bin/apply-edits.js
```

<details><summary>Full list</summary>

1. bin/apply-edits.js

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

![Flow steps diagram](diagrams/flows/bin-build-hamt-catalog-1-steps.svg)

#### Steps

```mermaid
flowchart LR
  bin_build_hamt_catalog["bin/build-hamt-catalog"]
```

<details><summary>Full list</summary>

- bin/build-hamt-catalog (`bin/build-hamt-catalog`)

</details>

![Call sequence diagram](diagrams/flows/bin-build-hamt-catalog-1-sequence.svg)

#### Call Sequence

```mermaid
sequenceDiagram
  participant bin_build_hamt_catalog as bin/build-hamt-catalog
```

<details><summary>Full list</summary>

1. bin/build-hamt-catalog

</details>

_No observable effects detected for this flow._

## `bin.cli`

- Kind: cli-command
- Entry: `bin/cli.js` (`bin/cli.js::printHelp`)
- Confidence: observed
- Layers touched: code, entrypoint

![Flow steps diagram](diagrams/flows/bin-cli-2-steps.svg)

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

![Call sequence diagram](diagrams/flows/bin-cli-2-sequence.svg)

#### Call Sequence

```mermaid
sequenceDiagram
  participant bin_cli_js as bin/cli.js
  participant bin_apply_edits_js as bin/apply-edits.js
  participant bin_auto_map_js as bin/auto-map.js
  bin_cli_js->>+bin_apply_edits_js: bin/apply-edits.js
  bin_apply_edits_js->>+bin_auto_map_js: bin/auto-map.js
```

<details><summary>Full list</summary>

1. bin/cli.js
2. bin/apply-edits.js
3. bin/auto-map.js

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

![Flow steps diagram](diagrams/flows/bin-skillopt-3-steps.svg)

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

![Call sequence diagram](diagrams/flows/bin-skillopt-3-sequence.svg)

#### Call Sequence

```mermaid
sequenceDiagram
  participant bin_skillopt_js as bin/skillopt.js
  participant bin_apply_edits_js as bin/apply-edits.js
  participant bin_cli_js as bin/cli.js
  participant bin_map_js as bin/map.js
  participant bin_auto_map_js as bin/auto-map.js
  bin_skillopt_js->>+bin_apply_edits_js: bin/apply-edits.js
  bin_apply_edits_js->>+bin_cli_js: bin/cli.js
  bin_cli_js->>+bin_map_js: bin/map.js
  bin_map_js->>+bin_auto_map_js: bin/auto-map.js
```

<details><summary>Full list</summary>

1. bin/skillopt.js
2. bin/apply-edits.js
3. bin/cli.js
4. bin/map.js
5. bin/auto-map.js

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

![Flow steps diagram](diagrams/flows/docs-api-examples-cli-4-steps.svg)

#### Steps

```mermaid
flowchart LR
  docs_api_examples_cli_md["docs/api-examples/cli.md"]
```

<details><summary>Full list</summary>

- docs/api-examples/cli.md (`docs/api-examples/cli.md`)

</details>

![Call sequence diagram](diagrams/flows/docs-api-examples-cli-4-sequence.svg)

#### Call Sequence

```mermaid
sequenceDiagram
  participant docs_api_examples_cli_md as docs/api-examples/cli.md
```

<details><summary>Full list</summary>

1. docs/api-examples/cli.md

</details>

_No observable effects detected for this flow._

## `simplicio.mapper.cli`

- Kind: entrypoint
- Entry: `simplicio_mapper/cli.py` (`simplicio_mapper/cli.py::_read_json_safe`)
- Confidence: observed
- Layers touched: code, entrypoint

![Flow steps diagram](diagrams/flows/simplicio-mapper-cli-5-steps.svg)

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

![Call sequence diagram](diagrams/flows/simplicio-mapper-cli-5-sequence.svg)

#### Call Sequence

```mermaid
sequenceDiagram
  participant simplicio_mapper_cli_py as simplicio_mapper/cli.py
  participant bin_apply_edits_js as bin/apply-edits.js
  participant bin_auto_map_js as bin/auto-map.js
  participant bin_cli_js as bin/cli.js
  participant bin_mapper_artifacts_js as bin/mapper-artifacts.js
  simplicio_mapper_cli_py->>+bin_apply_edits_js: bin/apply-edits.js
  bin_apply_edits_js->>+bin_auto_map_js: bin/auto-map.js
  bin_auto_map_js->>+bin_cli_js: bin/cli.js
  bin_cli_js->>+bin_mapper_artifacts_js: bin/mapper-artifacts.js
```

<details><summary>Full list</summary>

1. simplicio_mapper/cli.py
2. bin/apply-edits.js
3. bin/auto-map.js
4. bin/cli.js
5. bin/mapper-artifacts.js

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
| reads filesystem | `simplicio_mapper/cli.py:721` |
| reads filesystem | `simplicio_mapper/cli.py:1018` |
| reads filesystem | `simplicio_mapper/cli.py:1107` |
| reads filesystem | `simplicio_mapper/cli.py:1141` |
| reads filesystem | `simplicio_mapper/cli.py:1466` |
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
| writes filesystem | `simplicio_mapper/cli.py:32` |
| writes filesystem | `simplicio_mapper/cli.py:393` |
| writes filesystem | `simplicio_mapper/cli.py:507` |
| writes filesystem | `simplicio_mapper/cli.py:508` |
| writes filesystem | `simplicio_mapper/cli.py:1690` |
| writes filesystem | `simplicio_mapper/cli.py:1692` |
| writes filesystem | `simplicio_mapper/cli.py:1722` |
| writes filesystem | `simplicio_mapper/cli.py:1723` |
| writes filesystem | `simplicio_mapper/cli.py:1724` |
| writes filesystem | `simplicio_mapper/cli.py:1730` |
| writes filesystem | `simplicio_mapper/cli.py:1732` |
| writes filesystem | `simplicio_mapper/cli.py:1735` |
| writes filesystem | `simplicio_mapper/cli.py:1818` |
| writes filesystem | `simplicio_mapper/cli.py:1819` |
| writes filesystem | `simplicio_mapper/cli.py:1820` |
| writes filesystem | `simplicio_mapper/cli.py:1825` |
| writes filesystem | `simplicio_mapper/cli.py:1827` |
| writes filesystem | `simplicio_mapper/cli.py:1830` |
| writes filesystem | `simplicio_mapper/cli.py:1856` |
| writes filesystem | `simplicio_mapper/cli.py:1858` |
| writes filesystem | `simplicio_mapper/cli.py:1864` |
| writes filesystem | `simplicio_mapper/cli.py:1891` |
| writes filesystem | `simplicio_mapper/cli.py:1892` |
| writes filesystem | `simplicio_mapper/cli.py:1893` |
| writes filesystem | `simplicio_mapper/cli.py:1898` |
| writes filesystem | `simplicio_mapper/cli.py:1900` |
| writes filesystem | `simplicio_mapper/cli.py:2439` |
| spawns subprocess | `simplicio_mapper/cli.py:426` |
| spawns subprocess | `simplicio_mapper/cli.py:435` |
| spawns subprocess | `simplicio_mapper/cli.py:442` |
| spawns subprocess | `simplicio_mapper/cli.py:457` |
| spawns subprocess | `simplicio_mapper/cli.py:1999` |
| spawns subprocess | `simplicio_mapper/cli.py:2004` |

## `tests.fixtures.parity.host.src.index`

- Kind: entrypoint
- Entry: `tests/fixtures/parity-host/src/index.js` (`tests/fixtures/parity-host/src/index.js::startServer`)
- Confidence: observed
- Layers touched: code, entrypoint, test

![Flow steps diagram](diagrams/flows/tests-fixtures-parity-host-src-index-6-steps.svg)

#### Steps

```mermaid
flowchart LR
  simplicio_mapper_cache_py["simplicio_mapper/cache.py"]
  simplicio_mapper_context_cache_py["simplicio_mapper/context_cache.py"]
  tests_fixtures_mech_edit_host_sample_py["tests/fixtures/mech-edit-host/sample.py"]
  tests_fixtures_mech_edit_host_sample_ts["tests/fixtures/mech-edit-host/sample.ts"]
  tests_fixtures_parity_host_src_greet_js["tests/fixtures/parity-host/src/greet.js"]
  tests_fixtures_parity_host_src_index_js["tests/fixtures/parity-host/src/index.js"]
  tests_python_test_cli_py["tests/python/test_cli.py"]
  simplicio_mapper_context_cache_py --> tests_fixtures_mech_edit_host_sample_py
  tests_fixtures_mech_edit_host_sample_py --> tests_fixtures_mech_edit_host_sample_ts
  tests_fixtures_mech_edit_host_sample_ts --> tests_fixtures_parity_host_src_greet_js
  tests_fixtures_parity_host_src_greet_js --> tests_python_test_cli_py
  tests_fixtures_parity_host_src_index_js --> simplicio_mapper_context_cache_py
  tests_python_test_cli_py --> simplicio_mapper_cache_py
```

<details><summary>Full list</summary>

- simplicio_mapper/cache.py (`simplicio_mapper/cache.py`)
- simplicio_mapper/context_cache.py (`simplicio_mapper/context_cache.py`)
- tests/fixtures/mech-edit-host/sample.py (`tests/fixtures/mech-edit-host/sample.py`)
- tests/fixtures/mech-edit-host/sample.ts (`tests/fixtures/mech-edit-host/sample.ts`)
- tests/fixtures/parity-host/src/greet.js (`tests/fixtures/parity-host/src/greet.js`)
- tests/fixtures/parity-host/src/index.js (`tests/fixtures/parity-host/src/index.js`)
- tests/python/test_cli.py (`tests/python/test_cli.py`)

</details>

![Call sequence diagram](diagrams/flows/tests-fixtures-parity-host-src-index-6-sequence.svg)

#### Call Sequence

```mermaid
sequenceDiagram
  participant tests_fixtures_parity_host_src_index_js as tests/fixtures/parity-host/src/index.js
  participant simplicio_mapper_context_cache_py as simplicio_mapper/context_cache.py
  participant tests_fixtures_mech_edit_host_sample_py as tests/fixtures/mech-edit-host/sample.py
  participant tests_fixtures_mech_edit_host_sample_ts as tests/fixtures/mech-edit-host/sample.ts
  participant tests_fixtures_parity_host_src_greet_js as tests/fixtures/parity-host/src/greet.js
  participant tests_python_test_cli_py as tests/python/test_cli.py
  participant simplicio_mapper_cache_py as simplicio_mapper/cache.py
  tests_fixtures_parity_host_src_index_js->>+simplicio_mapper_context_cache_py: simplicio_mapper/context_cache.py
  simplicio_mapper_context_cache_py->>+tests_fixtures_mech_edit_host_sample_py: tests/fixtures/mech-edit-host/sample.py
  tests_fixtures_mech_edit_host_sample_py->>+tests_fixtures_mech_edit_host_sample_ts: tests/fixtures/mech-edit-host/sample.ts
  tests_fixtures_mech_edit_host_sample_ts->>+tests_fixtures_parity_host_src_greet_js: tests/fixtures/parity-host/src/greet.js
  tests_fixtures_parity_host_src_greet_js->>+tests_python_test_cli_py: tests/python/test_cli.py
  tests_python_test_cli_py->>+simplicio_mapper_cache_py: simplicio_mapper/cache.py
```

<details><summary>Full list</summary>

1. tests/fixtures/parity-host/src/index.js
2. simplicio_mapper/context_cache.py
3. tests/fixtures/mech-edit-host/sample.py
4. tests/fixtures/mech-edit-host/sample.ts
5. tests/fixtures/parity-host/src/greet.js
6. tests/python/test_cli.py
7. simplicio_mapper/cache.py

</details>

**Effects**

| Type | Evidence |
| --- | --- |
| touches cache/DB | `simplicio_mapper/cache.py:9` |
| touches cache/DB | `simplicio_mapper/cache.py:12` |
| touches cache/DB | `simplicio_mapper/cache.py:27` |
| touches cache/DB | `tests/python/test_cli.py:24` |
| touches cache/DB | `tests/python/test_cli.py:53` |
| touches cache/DB | `tests/python/test_cli.py:56` |
| touches cache/DB | `tests/python/test_cli.py:686` |
| writes filesystem | `simplicio_mapper/context_cache.py:81` |
| writes filesystem | `simplicio_mapper/context_cache.py:82` |
| spawns subprocess | `tests/python/test_cli.py:265` |
| spawns subprocess | `tests/python/test_cli.py:888` |
| spawns subprocess | `tests/python/test_cli.py:889` |
| spawns subprocess | `tests/python/test_cli.py:890` |
| spawns subprocess | `tests/python/test_cli.py:893` |
| spawns subprocess | `tests/python/test_cli.py:894` |

## `video.src.index`

- Kind: entrypoint
- Entry: `video/src/index.ts`
- Confidence: heuristic
- Layers touched: entrypoint

![Flow steps diagram](diagrams/flows/video-src-index-7-steps.svg)

#### Steps

```mermaid
flowchart LR
  video_src_index_ts["video/src/index.ts"]
```

<details><summary>Full list</summary>

- video/src/index.ts (`video/src/index.ts`)

</details>

![Call sequence diagram](diagrams/flows/video-src-index-7-sequence.svg)

#### Call Sequence

```mermaid
sequenceDiagram
  participant video_src_index_ts as video/src/index.ts
```

<details><summary>Full list</summary>

1. video/src/index.ts

</details>

_No observable effects detected for this flow._

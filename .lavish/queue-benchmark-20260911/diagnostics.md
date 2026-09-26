# OpenRouter diagnostic measurements

Not a qualified Loop serial/Prism/Fast comparison. No winning default.

## Provider attempts (including rejected proposal)

|Task|Request seconds|Input|Output incl. reasoning|Reasoning subset|Cached input|USD|
|---|---:|---:|---:|---:|---:|---:|
|ADO-301|3.18365725|1941|377|347|0|0.0010347|
|ADO-302|3.845987708|1822|457|363|0|0.001095|
|ADO-303|2.824652166|2013|480|373|0|0.0011799|
|ADO-303|2.994909958|2158|109|0|1920|0.00021372|
|GH-101|3.509253416|2153|352|299|0|0.0010683|
|GH-104|5.653904333|2177|994|878|0|0.0018459|
|JIRA-202|2.954908875|1900|252|155|0|0.0008724|
|JIRA-203|3.481390459|1798|432|388|0|0.0010578|
|GH-102|3.983171833|16297|96|73|0|0.0050043|
|GH-103|3.890690084|1725|429|393|0|0.0010323|
|JIRA-201|5.192997791|1670|716|647|0|0.0013602|

Missing values are unavailable, never zero. Reasoning is already included in output.

## Exact measured commands

### ADO-301 / mapper_scan

```text
simplicio-mapper scan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --sync --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 1.001685s; CPU: 0.768095s; sampled RSS peak: 86933504 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO301/mapper_scan/receipt.json`

### ADO-301 / mapper_handoff

```text
simplicio-mapper handoff /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --goal 'Find all deprecated=true entries in data/endpoints.json and write their sorted names to answers/deprecated.json.' --token-budget 12000 --limit 2 --execution-context --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.555242s; CPU: 0.5114400000000001s; sampled RSS peak: 120782848 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO301/mapper_handoff/receipt.json`

### ADO-301 / provider

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/openrouter_worker_probe.py --task /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/ADO-301.md --context /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO301/mapper_handoff/stdout.txt --handoff --output /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO301/provider.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 3.379624s; CPU: 0.12949100000000002s; sampled RSS peak: 33390592 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO301/provider/receipt.json`

### ADO-301 / apply

```text
/Users/wesleysimplicio/.local/bin/simplicio edit --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --plan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO301/edit-plan.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.447958s; CPU: 0.10886200000000001s; sampled RSS peak: 16007168 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO301/apply/receipt.json`

### ADO-301 / verify

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/verify_queue_fixture.py --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --task ADO-301
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.114402s; CPU: 0.07534499999999994s; sampled RSS peak: 4423680 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO301/verify/receipt.json`

### ADO-302 / mapper_scan

```text
simplicio-mapper scan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --sync --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.768912s; CPU: 0.710834s; sampled RSS peak: 88424448 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO302/mapper_scan/receipt.json`

### ADO-302 / mapper_handoff

```text
simplicio-mapper handoff /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --goal 'Create median(values) in src/median.py supporting odd and even nonempty lists.' --token-budget 12000 --limit 2 --execution-context --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.565279s; CPU: 0.508462s; sampled RSS peak: 120979456 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO302/mapper_handoff/receipt.json`

### ADO-302 / provider

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/openrouter_worker_probe.py --task /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/ADO-302.md --context /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO302/mapper_handoff/stdout.txt --handoff --output /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO302/provider.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 4.048048s; CPU: 0.12537700000000002s; sampled RSS peak: 33390592 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO302/provider/receipt.json`

### ADO-302 / apply

```text
/Users/wesleysimplicio/.local/bin/simplicio edit --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --plan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO302/edit-plan.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.365928s; CPU: 0.07672600000000013s; sampled RSS peak: 13467648 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO302/apply/receipt.json`

### ADO-302 / verify

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/verify_queue_fixture.py --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --task ADO-302
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.150002s; CPU: 0.08107299999999978s; sampled RSS peak: 5472256 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO302/verify/receipt.json`

### ADO-303 / mapper_scan

```text
simplicio-mapper scan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --sync --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.777053s; CPU: 0.7134689999999999s; sampled RSS peak: 80150528 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303/mapper_scan/receipt.json`

### ADO-303 / mapper_handoff

```text
simplicio-mapper handoff /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --goal 'Fix parse_bool(text) in src/boolean.py to accept true/false case-insensitively and reject other values.' --token-budget 12000 --limit 2 --execution-context --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.552932s; CPU: 0.465588s; sampled RSS peak: 121094144 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303/mapper_handoff/receipt.json`

### ADO-303 / provider

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/openrouter_worker_probe.py --task /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/ADO-303.md --context /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303/mapper_handoff/stdout.txt --handoff --output /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303/provider.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 2.955354s; CPU: 0.1150299999999998s; sampled RSS peak: 33193984 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303/provider/receipt.json`

### ADO-303 / mapper_scan

```text
simplicio-mapper scan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --sync --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.219056s; CPU: 0.173654s; sampled RSS peak: 38141952 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303-repair/mapper_scan/receipt.json`

### ADO-303 / mapper_handoff

```text
simplicio-mapper handoff /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --goal 'Fix parse_bool(text) in src/boolean.py to accept true/false case-insensitively and reject other values.' --token-budget 12000 --limit 2 --execution-context --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.434595s; CPU: 0.34467299999999995s; sampled RSS peak: 120930304 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303-repair/mapper_handoff/receipt.json`

### ADO-303 / provider

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/openrouter_worker_probe.py --task /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/ADO-303.md --context /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303-repair/mapper_handoff/stdout.txt --handoff --output /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303-repair/provider.json --repair-response /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303/provider.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 3.190174s; CPU: 0.09813299999999997s; sampled RSS peak: 33472512 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303-repair/provider/receipt.json`

### ADO-303 / apply

```text
/Users/wesleysimplicio/.local/bin/simplicio edit --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --plan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303-repair/edit-plan.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.443446s; CPU: 0.07067600000000006s; sampled RSS peak: 16072704 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303-repair/apply/receipt.json`

### ADO-303 / verify

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/verify_queue_fixture.py --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --task ADO-303
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.114382s; CPU: 0.05959700000000004s; sampled RSS peak: 5554176 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-ADO303-repair/verify/receipt.json`

### GH-101 / mapper_scan

```text
simplicio-mapper scan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --sync --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.331413s; CPU: 0.182201s; sampled RSS peak: 43139072 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH101/mapper_scan/receipt.json`

### GH-101 / mapper_handoff

```text
simplicio-mapper handoff /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --goal 'Create slugify(text) in src/slug.py; lowercase, trim and join whitespace with hyphens.' --token-budget 12000 --limit 2 --execution-context --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.442252s; CPU: 0.35232800000000003s; sampled RSS peak: 119930880 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH101/mapper_handoff/receipt.json`

### GH-101 / mapper_scan

```text
simplicio-mapper scan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --sync --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.757092s; CPU: 0.5820219999999999s; sampled RSS peak: 74711040 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH101-requirements/mapper_scan/receipt.json`

### GH-101 / mapper_handoff

```text
simplicio-mapper handoff /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --goal 'Create slugify(text) in src/slug.py; lowercase, trim and join whitespace with hyphens.' --token-budget 12000 --limit 2 --execution-context --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.435792s; CPU: 0.3829370000000001s; sampled RSS peak: 122322944 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH101-requirements/mapper_handoff/receipt.json`

### GH-101 / provider

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/openrouter_worker_probe.py --task /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/GH-101.md --context /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH101-requirements/mapper_handoff/stdout.txt --handoff --output /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH101-requirements/provider.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 3.677509s; CPU: 0.09562199999999998s; sampled RSS peak: 33439744 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH101-requirements/provider/receipt.json`

### GH-101 / apply

```text
/Users/wesleysimplicio/.local/bin/simplicio edit --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --plan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH101-requirements/edit-plan.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.328064s; CPU: 0.07939600000000002s; sampled RSS peak: 12894208 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH101-requirements/apply/receipt.json`

### GH-101 / verify

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/verify_queue_fixture.py --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --task GH-101
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.117360s; CPU: 0.06032199999999999s; sampled RSS peak: 4243456 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH101-requirements/verify/receipt.json`

### GH-104 / mapper_scan

```text
simplicio-mapper scan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --sync --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.449150s; CPU: 0.269706s; sampled RSS peak: 39026688 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH104/mapper_scan/receipt.json`

### GH-104 / mapper_handoff

```text
simplicio-mapper handoff /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --goal 'Add tests/test_total.py covering empty input, negative numbers and three positive numbers.' --token-budget 12000 --limit 2 --execution-context --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.569539s; CPU: 0.475177s; sampled RSS peak: 120258560 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH104/mapper_handoff/receipt.json`

### GH-104 / mapper_scan

```text
simplicio-mapper scan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --sync --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.219839s; CPU: 0.176487s; sampled RSS peak: 34570240 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH104-intent/mapper_scan/receipt.json`

### GH-104 / mapper_handoff

```text
simplicio-mapper handoff /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --task-file /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/GH-104.md --token-budget 12000 --limit 2 --execution-context --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.443524s; CPU: 0.3336509999999999s; sampled RSS peak: 119898112 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH104-intent/mapper_handoff/receipt.json`

### GH-104 / mapper_scan

```text
simplicio-mapper scan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --sync --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.766979s; CPU: 0.6046799999999999s; sampled RSS peak: 86900736 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH104-requirements/mapper_scan/receipt.json`

### GH-104 / mapper_handoff

```text
simplicio-mapper handoff /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --goal 'Add tests/test_total.py covering empty input, negative numbers and three positive numbers.' --token-budget 12000 --limit 2 --execution-context --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.687003s; CPU: 0.48585199999999984s; sampled RSS peak: 119619584 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH104-requirements/mapper_handoff/receipt.json`

### GH-104 / provider

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/openrouter_worker_probe.py --task /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/GH-104.md --context /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH104-requirements/mapper_handoff/stdout.txt --handoff --output /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH104-requirements/provider.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 5.816582s; CPU: 0.10973399999999994s; sampled RSS peak: 33652736 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH104-requirements/provider/receipt.json`

### GH-104 / apply

```text
/Users/wesleysimplicio/.local/bin/simplicio edit --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --plan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH104-requirements/edit-plan.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.329122s; CPU: 0.08110200000000017s; sampled RSS peak: 13336576 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH104-requirements/apply/receipt.json`

### GH-104 / verify

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/verify_queue_fixture.py --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --task GH-104
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.868423s; CPU: 0.6911379999999998s; sampled RSS peak: 66600960 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-GH104-requirements/verify/receipt.json`

### JIRA-202 / mapper_scan

```text
simplicio-mapper scan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --sync --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.991049s; CPU: 0.744594s; sampled RSS peak: 85164032 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA202/mapper_scan/receipt.json`

### JIRA-202 / mapper_handoff

```text
simplicio-mapper handoff /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --goal 'Fix clamp(value, low, high) in src/clamp.py to preserve values inside the interval.' --token-budget 12000 --limit 2 --execution-context --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.547929s; CPU: 0.47317999999999993s; sampled RSS peak: 120045568 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA202/mapper_handoff/receipt.json`

### JIRA-202 / provider

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/openrouter_worker_probe.py --task /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/JIRA-202.md --context /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA202/mapper_handoff/stdout.txt --handoff --output /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA202/provider.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 3.172450s; CPU: 0.11960600000000005s; sampled RSS peak: 33357824 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA202/provider/receipt.json`

### JIRA-202 / apply

```text
/Users/wesleysimplicio/.local/bin/simplicio edit --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --plan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA202/edit-plan.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.337045s; CPU: 0.08588000000000001s; sampled RSS peak: 13271040 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA202/apply/receipt.json`

### JIRA-202 / verify

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/verify_queue_fixture.py --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --task JIRA-202
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.117404s; CPU: 0.07351800000000014s; sampled RSS peak: 4800512 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA202/verify/receipt.json`

### JIRA-203 / mapper_scan

```text
simplicio-mapper scan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --sync --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 1.005944s; CPU: 0.782137s; sampled RSS peak: 80166912 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA203/mapper_scan/receipt.json`

### JIRA-203 / mapper_handoff

```text
simplicio-mapper handoff /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --goal 'Document the configured timeout value and its unit in docs/configuration.md.' --token-budget 12000 --limit 2 --execution-context --json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.557858s; CPU: 0.49369599999999997s; sampled RSS peak: 121061376 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA203/mapper_handoff/receipt.json`

### JIRA-203 / provider

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/openrouter_worker_probe.py --task /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/JIRA-203.md --context /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA203/mapper_handoff/stdout.txt --handoff --output /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA203/provider.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 3.613760s; CPU: 0.11995800000000018s; sampled RSS peak: 33570816 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA203/provider/receipt.json`

### JIRA-203 / apply

```text
/Users/wesleysimplicio/.local/bin/simplicio edit --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --plan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA203/edit-plan.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.448899s; CPU: 0.1046649999999999s; sampled RSS peak: 13287424 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA203/apply/receipt.json`

### JIRA-203 / verify

```text
/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/telemetry-venv/bin/python /Users/wesleysimplicio/Projetos/ai/simplicio-loop/bench/verify_queue_fixture.py --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --task JIRA-203
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture`; exit: 0; wall: 0.117200s; CPU: 0.06964600000000015s; sampled RSS peak: 4456448 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/diagnostic-JIRA203/verify/receipt.json`

### JIRA-201 / provider

```text
python3 bench/openrouter_worker_probe.py --task .simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/JIRA-201.md --context .simplicio-loop/benchmark/contexts-after-GH103/JIRA-201.handoff.json --handoff --output .simplicio-loop/benchmark/openrouter-worker-JIRA-201.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop`; exit: 0; wall: 5.399992s; CPU: 0.12204999999999999s; sampled RSS peak: 33390592 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/resource-worker-JIRA201/receipt.json`

### JIRA-201 / apply

```text
/Users/wesleysimplicio/.simplicio-loop/bin/simplicio edit --repo /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --plan /Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/JIRA-201-edit-plan.json
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop`; exit: 0; wall: 0.440175s; CPU: 0.168109s; sampled RSS peak: 25591808 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/resource-apply-JIRA201/receipt.json`

### JIRA-201 / verify

```text
python3 bench/verify_queue_fixture.py --repo .simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture --task JIRA-201
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop`; exit: 0; wall: 0.117594s; CPU: 0.08290700000000001s; sampled RSS peak: 5586944 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/resource-verify-JIRA201/receipt.json`

### all / final_verify

```text
.simplicio-loop/benchmark/telemetry-venv/bin/python bench/verify_queue_fixture.py --repo .simplicio-loop/benchmark/queue-3.43.10-20260911T135542012322Z/fixture
```

cwd: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop`; exit: 0; wall: 1.451570s; CPU: 1.058995s; sampled RSS peak: 63799296 bytes.
Receipt: `/Users/wesleysimplicio/Projetos/ai/simplicio-loop/.simplicio-loop/benchmark/queue-final-verification-20260911/receipt.json`

## Interpretation

Provider wall time is request-to-complete-response, not TTFT. CPU is local process-tree accounting, not provider CPU. RSS sampled every 100 ms can miss short peaks and double-count shared pages.

The first pilots lack full end-to-end resource coverage. Do not sum these stage maxima or heterogeneous task times into a comparative workflow result. All inputs and SHA-256 hashes are in summary.json.

# Business Flows & Rules

Auto-generated. Rules below are **observable** signals (validation, permission gates, limits/quotas, side-effects, invariants) with `path:line` evidence. Semantic intent (the *why*) is never inferred.

- Rules detected: 10
- State machines detected: 0
- Glossary terms: 279

## Invariant

| Rule | Evidence | Flows |
| --- | --- | --- |
| unexpected non-collision node at max depth | `scripts/build_hamt.py:180` | — |
| --target is required for export-docs | `simplicio_mapper/mapper.py:1808` | — |
| cannot ship after timeout | `tests/python/test_business.py:61` | — |

## Limit

| Rule | Evidence | Flows |
| --- | --- | --- |
| `MAX_COMMENT_CHARS` is compared against a value — treated as a limit/quota/timeout gate | `scripts/render-simplicio-comment.js:93` | — |
| `MAX_LEVELS` is compared against a value — treated as a limit/quota/timeout gate | `scripts/build_hamt.py:37` | — |
| `MAX_LEVELS` is compared against a value — treated as a limit/quota/timeout gate | `scripts/build_hamt.py:47` | — |
| `MAX_LEVELS` is compared against a value — treated as a limit/quota/timeout gate | `scripts/build_hamt.py:165` | — |
| `REQUEST_TIMEOUT` is compared against a value — treated as a limit/quota/timeout gate | `tests/python/test_business.py:60` | — |

## Permission

| Rule | Evidence | Flows |
| --- | --- | --- |
| access gate: authentication/authorization check observed | `tests/python/test_business.py:64` | — |

## Side Effect

| Rule | Evidence | Flows |
| --- | --- | --- |
| business side-effect observed: notification | `tests/python/test_business.py:67` | — |

## Glossary

| Term | Status | Source | Occurrences |
| --- | --- | --- | --- |
| <flow_name> | documented | docs/domain-map.md | 0 |
| architecturesignal | documented | .specs/product/DOMAIN.md | 0 |
| calledge | documented | .specs/product/DOMAIN.md | 0 |
| casos de borda | documented | .specs/product/DOMAIN.md | 0 |
| checkout | documented | docs/domain-map.md | 0 |
| core concepts | documented | docs/domain-map.md | 0 |
| critical rules | documented | docs/domain-map.md | 0 |
| edge cases | documented | docs/domain-map.md | 3 |
| endpoint | documented | .specs/product/DOMAIN.md | 9 |
| entidades | documented | .specs/product/DOMAIN.md | 0 |
| example — fictional shop saas (delete or copy as a starting point) | documented | docs/domain-map.md | 0 |
| fronteiras | documented | .specs/product/DOMAIN.md | 0 |
| glossary | documented | docs/domain-map.md | 2 |
| important flows | documented | docs/domain-map.md | 0 |
| indexstate | documented | .specs/product/DOMAIN.md | 0 |
| main entities | documented | docs/domain-map.md | 0 |
| not | documented | docs/domain-map.md | 9 |
| não | documented | .specs/product/DOMAIN.md | 0 |
| open questions | documented | docs/domain-map.md | 1 |
| precedent | documented | .specs/product/DOMAIN.md | 3 |
| product context | documented | docs/domain-map.md | 5 |
| project | documented | .specs/product/DOMAIN.md | 10 |
| projectfile | documented | .specs/product/DOMAIN.md | 0 |
| receipt | documented | .specs/product/DOMAIN.md | 1 |
| regras críticas | documented | .specs/product/DOMAIN.md | 0 |
| repo com edits unstaged | documented | .specs/product/DOMAIN.md | 3 |
| repo com tooling múltiplo | documented | .specs/product/DOMAIN.md | 3 |
| repo sem git | documented | .specs/product/DOMAIN.md | 3 |
| screen | documented | .specs/product/DOMAIN.md | 5 |
| symbol | documented | .specs/product/DOMAIN.md | 8 |
| file | undocumented | — | 50 |
| render | undocumented | — | 50 |
| run | undocumented | — | 44 |
| build | undocumented | — | 37 |
| write | undocumented | — | 37 |
| for | undocumented | — | 35 |
| read | undocumented | — | 32 |
| json | undocumented | — | 31 |
| and | undocumented | — | 27 |
| tmp | undocumented | — | 26 |
| markdown | undocumented | — | 24 |
| flow | undocumented | — | 22 |
| path | undocumented | — | 21 |
| docs | undocumented | — | 20 |
| files | undocumented | — | 19 |
| map | undocumented | — | 19 |
| down | undocumented | — | 18 |
| tear | undocumented | — | 18 |
| call | undocumented | — | 17 |
| doc | undocumented | — | 17 |
| extract | undocumented | — | 17 |
| hash | undocumented | — | 17 |
| text | undocumented | — | 17 |
| command | undocumented | — | 16 |
| parse | undocumented | — | 16 |
| artifacts | undocumented | — | 15 |
| flowchart | undocumented | — | 15 |
| safe | undocumented | — | 15 |
| status | undocumented | — | 15 |
| diagram | undocumented | — | 14 |
| graph | undocumented | — | 14 |
| collect | undocumented | — | 13 |
| context | undocumented | — | 13 |
| git | undocumented | — | 13 |
| same | undocumented | — | 13 |
| architecture | undocumented | — | 12 |
| cache | undocumented | — | 12 |
| inventory | undocumented | — | 12 |
| language | undocumented | — | 12 |
| reports | undocumented | — | 12 |
| detect | undocumented | — | 11 |
| state | undocumented | — | 11 |
| changed | undocumented | — | 10 |
| module | undocumented | — | 10 |
| python | undocumented | — | 10 |
| with | undocumented | — | 10 |
| without | undocumented | — | 10 |
| business | undocumented | — | 9 |
| cli | undocumented | — | 9 |
| load | undocumented | — | 9 |
| macro | undocumented | — | 9 |
| name | undocumented | — | 9 |
| only | undocumented | — | 9 |
| range | undocumented | — | 9 |
| snapshot | undocumented | — | 9 |
| svg | undocumented | — | 9 |
| sync | undocumented | — | 9 |
| drift | undocumented | — | 8 |
| exists | undocumented | — | 8 |
| list | undocumented | — | 8 |
| scan | undocumented | — | 8 |
| svgs | undocumented | — | 8 |
| symbols | undocumented | — | 8 |
| changes | undocumented | — | 7 |
| evidence | undocumented | — | 7 |
| handoff | undocumented | — | 7 |
| infer | undocumented | — | 7 |
| init | undocumented | — | 7 |
| layers | undocumented | — | 7 |
| missing | undocumented | — | 7 |
| node | undocumented | — | 7 |
| pack | undocumented | — | 7 |
| payload | undocumented | — | 7 |
| per | undocumented | — | 7 |
| renders | undocumented | — | 7 |
| returns | undocumented | — | 7 |
| survey | undocumented | — | 7 |
| walk | undocumented | — | 7 |
| writes | undocumented | — | 7 |
| are | undocumented | — | 6 |
| attach | undocumented | — | 6 |
| calls | undocumented | — | 6 |
| check | undocumented | — | 6 |
| entry | undocumented | — | 6 |
| formed | undocumented | — | 6 |
| help | undocumented | — | 6 |
| imports | undocumented | — | 6 |
| includes | undocumented | — | 6 |
| label | undocumented | — | 6 |
| match | undocumented | — | 6 |
| mode | undocumented | — | 6 |
| resolve | undocumented | — | 6 |
| root | undocumented | — | 6 |
| rules | undocumented | — | 6 |
| signature | undocumented | — | 6 |
| well | undocumented | — | 6 |
| args | undocumented | — | 5 |
| code | undocumented | — | 5 |
| diff | undocumented | — | 5 |
| domain | undocumented | — | 5 |
| empty | undocumented | — | 5 |
| endpoints | undocumented | — | 5 |
| ensure | undocumented | — | 5 |
| escape | undocumented | — | 5 |
| flows | undocumented | — | 5 |
| lint | undocumented | — | 5 |
| lock | undocumented | — | 5 |
| native | undocumented | — | 5 |
| normalize | undocumented | — | 5 |
| output | undocumented | — | 5 |
| package | undocumented | — | 5 |
| paths | undocumented | — | 5 |
| placeholders | undocumented | — | 5 |
| product | undocumented | — | 5 |
| route | undocumented | — | 5 |
| routes | undocumented | — | 5 |
| sequence | undocumented | — | 5 |
| slug | undocumented | — | 5 |
| stack | undocumented | — | 5 |
| strip | undocumented | — | 5 |
| truncation | undocumented | — | 5 |
| unknown | undocumented | — | 5 |
| xml | undocumented | — | 5 |
| binary | undocumented | — | 4 |
| collapse | undocumented | — | 4 |
| commands | undocumented | — | 4 |
| csharp | undocumented | — | 4 |
| delta | undocumented | — | 4 |
| deterministic | undocumented | — | 4 |
| dir | undocumented | — | 4 |
| edges | undocumented | — | 4 |
| edit | undocumented | — | 4 |
| effects | undocumented | — | 4 |
| export | undocumented | — | 4 |
| extracted | undocumented | — | 4 |
| first | undocumented | — | 4 |
| flagged | undocumented | — | 4 |
| keeps | undocumented | — | 4 |
| languages | undocumented | — | 4 |
| maybe | undocumented | — | 4 |
| mermaid | undocumented | — | 4 |
| omitted | undocumented | — | 4 |
| raises | undocumented | — | 4 |
| roles | undocumented | — | 4 |
| sanitize | undocumented | — | 4 |
| scaffold | undocumented | — | 4 |
| sha256 | undocumented | — | 4 |
| snippet | undocumented | — | 4 |
| spec | undocumented | — | 4 |
| stable | undocumented | — | 4 |
| task | undocumented | — | 4 |
| template | undocumented | — | 4 |
| threshold | undocumented | — | 4 |
| tree | undocumented | — | 4 |
| version | undocumented | — | 4 |
| when | undocumented | — | 4 |
| adversarial | undocumented | — | 3 |
| agent | undocumented | — | 3 |
| all | undocumented | — | 3 |
| angular | undocumented | — | 3 |
| apply | undocumented | — | 3 |
| artifact | undocumented | — | 3 |
| ask | undocumented | — | 3 |
| background | undocumented | — | 3 |
| between | undocumented | — | 3 |
| callers | undocumented | — | 3 |
| chain | undocumented | — | 3 |
| changelog | undocumented | — | 3 |
| clear | undocumented | — | 3 |
| client | undocumented | — | 3 |
| compact | undocumented | — | 3 |
| contain | undocumented | — | 3 |
| content | undocumented | — | 3 |
| copy | undocumented | — | 3 |
| count | undocumented | — | 3 |
| create | undocumented | — | 3 |
| cycle | undocumented | — | 3 |
| dependency | undocumented | — | 3 |
| detected | undocumented | — | 3 |
| detection | undocumented | — | 3 |
| detects | undocumented | — | 3 |
| dict | undocumented | — | 3 |
| different | undocumented | — | 3 |
| directives | undocumented | — | 3 |
| dirs | undocumented | — | 3 |
| edge | undocumented | — | 3 |
| edits | undocumented | — | 3 |
| entities | undocumented | — | 3 |
| existing | undocumented | — | 3 |
| exit | undocumented | — | 3 |
| exits | undocumented | — | 3 |
| external | undocumented | — | 3 |
| fallback | undocumented | — | 3 |
| global | undocumented | — | 3 |
| greet | undocumented | — | 3 |
| has | undocumented | — | 3 |
| history | undocumented | — | 3 |
| image | undocumented | — | 3 |
| incremental | undocumented | — | 3 |
| job | undocumented | — | 3 |
| large | undocumented | — | 3 |
| level | undocumented | — | 3 |
| line | undocumented | — | 3 |
| log | undocumented | — | 3 |
| looks | undocumented | — | 3 |
| machine | undocumented | — | 3 |
| mapper | undocumented | — | 3 |
| mapping | undocumented | — | 3 |
| marks | undocumented | — | 3 |
| matches | undocumented | — | 3 |
| modules | undocumented | — | 3 |
| multi | undocumented | — | 3 |
| must | undocumented | — | 3 |
| new | undocumented | — | 3 |
| normalization | undocumented | — | 3 |
| once | undocumented | — | 3 |
| order | undocumented | — | 3 |
| orphan | undocumented | — | 3 |
| persist | undocumented | — | 3 |
| placeholder | undocumented | — | 3 |
| positions | undocumented | — | 3 |
| print | undocumented | — | 3 |
| query | undocumented | — | 3 |
| repo | undocumented | — | 3 |
| resolved | undocumented | — | 3 |
| schema | undocumented | — | 3 |
| screens | undocumented | — | 3 |
| script | undocumented | — | 3 |
| section | undocumented | — | 3 |
| segments | undocumented | — | 3 |
| server | undocumented | — | 3 |
| service | undocumented | — | 3 |
| signals | undocumented | — | 3 |
| snapshots | undocumented | — | 3 |
| sources | undocumented | — | 3 |
| sprint | undocumented | — | 3 |
| steps | undocumented | — | 3 |
| still | undocumented | — | 3 |
| substitute | undocumented | — | 3 |
| summary | undocumented | — | 3 |
| targets | undocumented | — | 3 |
| telemetry | undocumented | — | 3 |
| theme | undocumented | — | 3 |
| top | undocumented | — | 3 |
| transitions | undocumented | — | 3 |
| use | undocumented | — | 3 |
| user | undocumented | — | 3 |
| value | undocumented | — | 3 |
| watch | undocumented | — | 3 |

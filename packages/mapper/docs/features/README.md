# Feature Notes

Create one file per relevant feature when a project has non-obvious behavior.

Suggested name:

```text
docs/features/<feature-name>.md
```

## Feature Template

```md
# <FEATURE_NAME>

## Goal

<WHAT_USER_OR_SYSTEM_CAN_DO>

## User Flow

1. <STEP>
2. <STEP>
3. <EXPECTED_RESULT>

## Main Files

| Layer | Files |
|---|---|
| UI | <FILES_OR_NONE> |
| API | <FILES_OR_NONE> |
| Service/domain | <FILES_OR_NONE> |
| Persistence | <FILES_OR_NONE> |
| Tests | <FILES_OR_NONE> |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| <METHOD> | <PATH> | <PURPOSE> |

## Data

| Table/collection/model | Purpose |
|---|---|
| <NAME> | <PURPOSE> |

## Business Rules

- <RULE>

## Test Scenarios

- <SCENARIO>

## Evidence

- Screenshot: <EXPECTED_SCREEN>
- Video: <WHEN_NEEDED>
- Trace: <WHEN_NEEDED>

## Known Risks

- <RISK>
```

---

## Example

See [`login.md`](./login.md) for a fully-filled example feature doc using the template above.

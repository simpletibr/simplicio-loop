# bash-cli

Bash scaffold for portable command-line automation with shellcheck linting and
Bats tests.

## When to use this stack

- Thin wrapper around existing system commands
- Portable automation for CI or developer machines
- No long-running service or rich UI is needed

## Layout produced

```
<project_name>/
|-- bin/app.sh
|-- test/app.bats
`-- README.md
```

## Verify loop

- `test`: `bats test`
- `lint`: `shellcheck bin/*.sh`

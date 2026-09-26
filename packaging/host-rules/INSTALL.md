# Host-aware Loop installer

The wheel owns one installer:

```text
python -m simplicio_loop.install --host claude --target . --dry-run
simplicio-loop install --host vscode --target .
python -m simplicio_loop.install --uninstall --target .
```

`scripts/install_lib.py` stays as the checkout helper and consumes the same
host registry conceptually. Standalone dry-run writes nothing. Uninstall
removes only files listed in `.simplicio-loop/install-ownership.json`.

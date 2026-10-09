# simplicio-loop-247 unit: manual check of the sandbox under the unit's filters

The unit's syscall filter must let bwrap (the turbo sandbox) start. The automated
`tests/watcher247/test_unit_hardening.py` pins the directive text; `test_sandbox_live.py`
runs the sandbox argv under bwrap. Neither runs the real unit under systemd. On a host
with systemd as PID 1, run this once after installing the unit:

```sh
sudo systemd-run --pipe --wait --quiet \
  -p User=simplicio-loop -p Group=simplicio-loop \
  -p NoNewPrivileges=yes -p CapabilityBoundingSet= \
  -p 'SystemCallFilter=@system-service @mount' \
  -p 'RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX' \
  -p LockPersonality=yes -p RestrictSUIDSGID=yes \
  bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp \
        --bind /var/lib/simplicio-loop-247/work /var/lib/simplicio-loop-247/work \
        --die-with-parent --new-session -- true
echo "rc=$?"
```

Expected: `rc=0`. Without `@mount` in `SystemCallFilter`, the same command exits with
`rc=159` (SIGSYS), which is why the unit lists it.

## Reproduction on a VPS (systemd 259, bubblewrap 0.11.1, transient `systemd-run --user` services)

`SystemCallFilter` is not a scope property (`--scope` answers `Unknown assignment`), so the checks use a
transient user service: `systemd-run --user --pipe --wait --quiet -p SystemCallFilter=... bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp true`.

| `SystemCallFilter=`                         | rc  |
|---------------------------------------------|-----|
| (none)                                      | 0   |
| `@system-service`                           | 159 (SIGSYS) |
| `@system-service mount pivot_root umount2`  | 0   |
| `@system-service mount pivot_root`          | 159 |
| `@system-service mount umount2`             | 159 |
| `@system-service pivot_root umount2`        | 159 |
| `@system-service @mount`                    | 0   |

Minimal set: `mount`, `pivot_root` and `umount2` (all three; `strace -f bwrap ...` shows exactly these
beyond `@system-service`). The unit uses the whole `@mount` group, a superset, so a newer bwrap that moves to
`fsopen`/`fsmount`/`move_mount` keeps working. `tests/watcher247/test_unit_hardening.py` pins the three
syscalls against the unit's filter and, when `bwrap` and a systemd user manager exist, runs both the bare
`@system-service` control (must be 159) and the unit's filter (must be 0).

With the unit's other lines (`NoNewPrivileges`, `RestrictAddressFamilies`, `LockPersonality`,
`RestrictSUIDSGID`, `ProtectSystem=strict`, `PrivateTmp`) and an empty `CapabilityBoundingSet=`, run as a
non-root uid (`setpriv --reuid=65534 --bounding-set=-all`), bwrap still starts (rc=0) with `@system-service @mount`.
An empty `CapabilityBoundingSet=` as uid 0 makes bwrap fail with `Creating new namespace failed` (it needs
CAP_SYS_ADMIN there), which is why the unit must keep `User=simplicio-loop`.

Not verified: the unit itself under the system manager as `User=simplicio-loop` (only transient user
services were used, nothing under `/etc`, `/var/lib` or the running services was touched). Run the command
above once on the host after installing the unit.

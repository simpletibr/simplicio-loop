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

Status: not yet run on a host with systemd. This container has no systemd as PID 1, so the
command above was not executed here; `bwrap` itself was run without the systemd filter.

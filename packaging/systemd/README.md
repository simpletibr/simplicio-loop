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
  bwrap --ro-bind / / --unshare-pid --dev /dev --proc /proc --tmpfs /tmp \
        --bind /var/lib/simplicio-loop-247/work /var/lib/simplicio-loop-247/work \
        --die-with-parent --new-session -- true
echo "rc=$?"
```

Expected: `rc=0`. Without `@mount` in `SystemCallFilter`, the same command exits with
`rc=159` (SIGSYS), which is why the unit lists it. `--unshare-pid` is what `sandbox.wrap` passes so the sandboxed process
cannot read `/proc/<watcher pid>/environ` (issue #1563); it only starts if the unit leaves `/proc` whole (see
"`--unshare-pid` under the unit" below).

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

## `--unshare-pid` under the unit (issue #1563)

`sandbox.wrap` adds `--unshare-pid`, so the sandbox has its own pid namespace and `--proc /proc` mounts a procfs for it. The
watcher's pid, and with it `/proc/<pid>/environ` (the `EnvironmentFile` secrets, readable by any process of the same uid),
is neither listed nor readable inside. Syscalls: `strace -f bwrap ...` shows the same 50 syscalls with and without the flag
(the new one is `clone(CLONE_NEWNS|CLONE_NEWPID)`); `clone`, `clone3`, `unshare` and `setns` are in `@system-service`
(`systemd-analyze syscall-filter`), and systemd's filter does not look at `clone` flags, so `@system-service @mount` needs
no change.

Measured with `systemd-run` on the system manager as `User=nobody`, carrying every sandboxing directive of the unit
(`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome=read-only`, empty `CapabilityBoundingSet`,
`RestrictAddressFamilies`, `ProtectKernelModules`, `ProtectControlGroups`, `RestrictSUIDSGID`, `LockPersonality`,
`RestrictRealtime`, `UMask`), the argv `sandbox.wrap` builds (rc of the transient service; systemd 259.5, bubblewrap 0.11.1):

| `SystemCallFilter=`                         | without `--unshare-pid` | with `--unshare-pid` |
|---------------------------------------------|-----|-----|
| (none)                                      | 0   | 0   |
| `@system-service`                           | 159 (SIGSYS) | 159 (SIGSYS) |
| `@system-service mount pivot_root umount2`  | 0   | 0   |
| `@system-service mount pivot_root`          | 159 | 159 |
| `@system-service @mount`                    | 0   | 0   |

`ProtectKernelTunables=yes` is **not** in the unit any more. With it and `@system-service @mount`, the same argv gives
rc=0 without `--unshare-pid` and rc=1 with it (`bwrap: Can't mount proc on /newroot/proc: Operation not permitted`): the
directive read-only-binds parts of `/proc`, and the kernel refuses a non-root mount of a fresh procfs while the mount
namespace hides parts of it. The service is non-root with an empty `CapabilityBoundingSet=`, so it cannot write `/proc/sys`
with or without the directive. `ProcSubset=pid` breaks the procfs mount too (rc=1 in both columns), so it must stay out;
`ProtectProc=invisible` measured fine (rc=0 in both). `test_unit_hardening.py` pins both and runs the sandbox argv under
the unit's directives (as `nobody` when root, else a `--user` transient service; skipped when neither works). The same
`Can't mount proc` error shows up in a container whose `/proc` is masked.

Probe inside the unit's directives (`User=nobody`, a fake secret in the unit's environment), by `ps`/`/proc`:

| Inside the sandbox | without `--unshare-pid` | with `--unshare-pid` |
|--------------------|-----|-----|
| watcher pid listed in `/proc` | yes | no |
| `/proc/<watcher>/cmdline`, `status` | readable | not found |
| `/proc/<watcher>/environ`, `maps` | denied *on this host* (the sandbox runs confined as `bwrap//&unpriv_bwrap`; the rule itself was not inspected) | not found |
| own pid | host pid | 2 |

As root (bwrap without a user namespace) `/proc/<watcher>/environ` is readable without the flag (the reviewer's repro, and
`test_sandbox_proc.py::test_control_without_unshare_pid_the_child_reads_the_watcher_environ`); with it, it is not found.

What stays visible by design: the service user's `HOME` (the exec CLIs read their own logins from it, e.g. `~/.claude`,
`~/.codex`, `~/.simplicio/login.json`; the sandbox does not split `HOME` per CLI), the shared network namespace
(`/proc/net`, localhost), host facts in `/proc/self/mountinfo`, `cpuinfo`, `meminfo`, and `/run`. Keep
`/etc/simplicio-loop-247.env` owned by root with mode 600: `--ro-bind / /` exposes any file the service user can read.

UNVERIFIED: reading `/proc/<watcher>/environ` as a non-root uid on a host **without** that AppArmor confinement
(the measured host denies it already; the same-uid read itself was shown with a plain, unsandboxed process), the real
unit under the system manager as `User=simplicio-loop`, and other distributions or kernels. Only runtime-only transient
services were used (user services for the first table, system-manager services as `nobody` for the `--unshare-pid` ones;
both auto-collected), nothing under `/etc`, `/var/lib` or the running services was touched. Run the command above once on
the host after installing the unit.

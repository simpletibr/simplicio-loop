"""Contract of packaging/systemd/simplicio-loop-247.service: non-root, hardened, every directive documented."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from simplicio_loop.watcher247 import sandbox

UNIT = Path(__file__).resolve().parents[2] / "packaging" / "systemd" / "simplicio-loop-247.service"

HARDENING = {
    "NoNewPrivileges=yes", "PrivateTmp=yes", "ProtectSystem=strict", "ProtectHome=read-only",
    "SystemCallFilter=@system-service @mount", "CapabilityBoundingSet=", "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
    "ProtectKernelModules=yes", "ProtectControlGroups=yes",
    "RestrictSUIDSGID=yes", "LockPersonality=yes", "RestrictRealtime=yes", "UMask=0077",
}


def lines():
    return UNIT.read_text().splitlines()


def test_unit_never_runs_as_root():
    directives = [line.strip() for line in lines()]
    assert "User=simplicio-loop" in directives
    assert "Group=simplicio-loop" in directives
    assert not [d for d in directives if d in {"User=root", "Group=root"}]


def test_unit_has_every_hardening_directive():
    present = {line.strip() for line in lines()}
    assert HARDENING <= present, sorted(HARDENING - present)


def test_syscall_filter_admits_the_mount_group_bwrap_needs():
    # bwrap builds the sandbox with mount, pivot_root and umount2; @system-service leaves them out,
    # so turbo would die with SIGSYS under a bare @system-service filter.
    present = {line.strip() for line in lines()}
    assert "SystemCallFilter=@system-service @mount" in present
    assert "SystemCallFilter=@system-service" not in present


# Minimal extra syscalls bwrap needs beyond @system-service (bisected with systemd-run --user, rc=159 SIGSYS when
# any one is missing; see packaging/systemd/README.md). @mount is the group that carries all three.
BWRAP_EXTRA_SYSCALLS = {"mount", "pivot_root", "umount2"}
MOUNT_GROUP = {"chroot", "fsconfig", "fsmount", "fsopen", "fspick", "mount", "mount_setattr", "move_mount",
               "open_tree_attr", "pivot_root", "umount", "umount2"}


def filter_tokens():
    [value] = [line.split("=", 1)[1] for line in lines() if line.startswith("SystemCallFilter=")]
    return value.split()


def test_unit_filter_covers_every_syscall_bwrap_needs():
    tokens = filter_tokens()
    assert "@system-service" in tokens
    allowed = {t for t in tokens if not t.startswith("@")}
    if "@mount" in tokens:
        allowed |= MOUNT_GROUP
    assert BWRAP_EXTRA_SYSCALLS <= allowed, sorted(BWRAP_EXTRA_SYSCALLS - allowed)


def test_mount_group_table_matches_systemd():
    analyze = shutil.which("systemd-analyze")
    if not analyze:
        pytest.skip("systemd-analyze not installed")
    out = subprocess.run([analyze, "syscall-filter", "@mount"], capture_output=True, text=True).stdout
    listed = {l.strip() for l in out.splitlines()[1:] if l.strip() and not l.strip().startswith("#")}
    assert BWRAP_EXTRA_SYSCALLS <= listed
    assert BWRAP_EXTRA_SYSCALLS <= MOUNT_GROUP


def run_bwrap_under_filter(filter_value):
    env = dict(os.environ)
    runtime = Path(f"/run/user/{os.getuid()}")
    if "XDG_RUNTIME_DIR" not in env and runtime.is_dir():
        env["XDG_RUNTIME_DIR"] = str(runtime)
    return subprocess.run(
        ["systemd-run", "--user", "--pipe", "--wait", "--quiet", "-p", f"SystemCallFilter={filter_value}",
         "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "true"],
        capture_output=True, text=True, env=env, timeout=30)


def test_bwrap_starts_under_the_unit_filter_and_dies_under_the_bare_group():
    if not (shutil.which("bwrap") and shutil.which("systemd-run")):
        pytest.skip("bwrap and systemd-run are needed")
    unit_filter = " ".join(filter_tokens())
    control = run_bwrap_under_filter("@system-service")
    if control.returncode not in (159, 0) or "connect" in control.stderr.lower():
        pytest.skip(f"no usable systemd user manager: {control.stderr.strip()[:120]}")
    assert control.returncode == 159  # SIGSYS: the negative control proves the check can fail
    assert run_bwrap_under_filter(unit_filter).returncode == 0


# The sandbox runs bwrap --unshare-pid --proc /proc (issue #1563). As a non-root user, the kernel refuses to mount a fresh
# procfs when the unit's /proc is partly overmounted: ProtectKernelTunables=yes read-only-binds /proc/sys, /proc/irq ...
# and bwrap then dies with "Can't mount proc on /newroot/proc: Operation not permitted" (measured, systemd 259).
# ProcSubset=pid refuses the procfs mount as well, even without --unshare-pid. (ProtectProc=invisible measured fine.)
PROC_OVERMOUNTS = ("ProtectKernelTunables=yes", "ProcSubset=pid")


def test_unit_leaves_proc_whole_so_the_sandbox_can_remount_it():
    present = {line.strip() for line in lines()}
    assert not present & set(PROC_OVERMOUNTS), sorted(present & set(PROC_OVERMOUNTS))
    paths = [line for line in lines() if line.split("=", 1)[0] in ("ReadOnlyPaths", "InaccessiblePaths", "TemporaryFileSystem", "BindReadOnlyPaths")]
    assert not [line for line in paths if "/proc" in line], paths


# Not sandboxing: how the service is started and supervised. ReadWritePaths names directories that exist only on the host.
NOT_SANDBOXING = {"Type", "User", "Group", "EnvironmentFile", "ExecStart", "Restart", "RestartSec", "KillMode",
                  "TimeoutStopSec", "ReadWritePaths", "Description", "After", "Wants", "WantedBy"}


def sandboxing_directives():
    return [line.strip() for line in lines()
            if "=" in line and not line.lstrip().startswith(("#", "[")) and line.split("=", 1)[0] not in NOT_SANDBOXING]


def run_under_unit(argv):
    """Run argv as a transient service carrying every sandboxing directive of the unit (as nobody when root)."""
    cmd = ["systemd-run", "--pipe", "--wait", "--quiet", "--collect"]
    env = dict(os.environ)
    if os.getuid() == 0:
        cmd += ["-p", "User=nobody"]  # stands in for User=simplicio-loop; root has CAP_SYS_ADMIN and would prove nothing
    else:
        cmd += ["--user"]
        runtime = Path(f"/run/user/{os.getuid()}")
        if "XDG_RUNTIME_DIR" not in env and runtime.is_dir():
            env["XDG_RUNTIME_DIR"] = str(runtime)
    for directive in sandboxing_directives():
        cmd += ["-p", directive]
    return subprocess.run(cmd + argv, capture_output=True, text=True, env=env, timeout=60)


def test_sandbox_with_unshare_pid_starts_under_every_hardening_directive_of_the_unit():
    if not (shutil.which("bwrap") and shutil.which("systemd-run")):
        pytest.skip("bwrap and systemd-run are needed")
    # any readable directories do for the two binds; the argv is the one the watcher builds
    argv = sandbox.wrap(["true"], clone=Path("/usr/share"), state_dir=Path("/usr/lib"), platform="linux", environ={})
    assert "--unshare-pid" in argv
    baseline = run_under_unit([part for part in argv if part != "--unshare-pid"])
    if baseline.returncode != 0:
        pytest.skip(f"this systemd cannot run the sandbox under the unit's directives at all: {baseline.stderr.strip()[:160]}")
    done = run_under_unit(argv)
    assert done.returncode == 0, done.stderr.strip()


def test_every_hardening_directive_is_documented_above_it():
    body = lines()
    for index, line in enumerate(body):
        if line.strip() in HARDENING:
            assert index > 0 and body[index - 1].lstrip().startswith("#"), line

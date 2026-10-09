"""Contract of packaging/systemd/simplicio-loop-247.service: non-root, hardened, every directive documented."""
from __future__ import annotations

from pathlib import Path

UNIT = Path(__file__).resolve().parents[2] / "packaging" / "systemd" / "simplicio-loop-247.service"

HARDENING = {
    "NoNewPrivileges=yes", "PrivateTmp=yes", "ProtectSystem=strict", "ProtectHome=read-only",
    "SystemCallFilter=@system-service @mount", "CapabilityBoundingSet=", "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
    "ProtectKernelTunables=yes", "ProtectKernelModules=yes", "ProtectControlGroups=yes",
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


def test_every_hardening_directive_is_documented_above_it():
    body = lines()
    for index, line in enumerate(body):
        if line.strip() in HARDENING:
            assert index > 0 and body[index - 1].lstrip().startswith("#"), line

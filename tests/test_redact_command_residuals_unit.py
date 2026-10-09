"""What the audit of #1571 found still leaking from ``runs.redact_command``, and what it cost (issue #1565, D5 and D6).

Seven command lines kept their secret (``redis-cli -a``, ``az login -p``, ``sqlcmd -P``, ``smbclient -U user%pw``,
``vault login hvs.``, a ``-token`` subcommand that swallowed the next flag, a JWT with a short signature), the leak
diagnostic of the check runner printed argv unmasked, and ``_PAIR_RE`` cost 131-294 ms of CPU on a 4 KB hostile command.
Only fake secrets here.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from simplicio_loop import quality_process
from simplicio_loop.dashboard import runs
from tests._secret_corpus import SECRET_CORPUS

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.abc123SIG"  # header.payload.signature, the signature far below 32 characters
LEAKS = [
    ("redis-cli -h cache.example -a hunter2hunter2 ping", "hunter2hunter2"),
    ("az login --service-principal -u me -p hunter2hunter2 --tenant t", "hunter2hunter2"),
    ("sqlcmd -S db -U sa -P hunter2hunter2 -Q 'select 1'", "hunter2hunter2"),
    ("smbclient //srv/share -U alice%hunter2hunter2 -c ls", "hunter2hunter2"),
    ("vault login hvs.fakefakefakefake0123456789abcdef", "fakefakefakefake0123456789abcdef"),
    ("gcloud auth print-identity-token --access-token hunter2hunter2", "hunter2hunter2"),
    (f"curl --jwt {JWT} https://x", "abc123SIG"),
    # the same families, spelled the other ways they are typed
    ("redis-cli -a 'hunter2 hunter2' ping", "hunter2 hunter2"),
    ("sqlcmd -P hunter2hunter2", "hunter2hunter2"),
    ("rpcclient //srv -U alice%hunter2hunter2", "hunter2hunter2"),
    ("smbclient //srv/share --user=alice%hunter2hunter2", "hunter2hunter2"),
    ("vault login -no-print hvs.fakefakefakefake0123456789abcdef", "fakefakefakefake0123456789abcdef"),
    ("vault login s.faketoken1234", "faketoken1234"),
    ("vault write auth/x/login jwt=hvb.fakefakefakefake0123456789abcdef", "fakefakefakefake0123456789abcdef"),
    ("aws sts get-session-token --serial-number arn:aws:iam::1:mfa/u --token-code 123456", "123456"),
    ("gcloud auth print-access-token --impersonate-service-account=x --token hunter2hunter2", "hunter2hunter2"),
    (f"echo {JWT}", "abc123SIG"),
    (f"echo jwt={JWT}; ls", "eyJzdWIiOiJ4In0"),
]
ORDINARY = [
    "redis-cli -h localhost ping",
    "redis-cli --scan --pattern 'user:*'",
    "redis-cli -n 2 get key",
    "sqlcmd -S localhost -E -Q 'select 1'",
    "sqlcmd -S db -U sa -p",
    "smbclient -L //srv -N",
    "smbclient //srv/share -U alice",
    "vault status",
    "vault login -method=oidc",
    "vault kv get secret/app",
    "gcloud auth print-identity-token",
    "gcloud auth list --filter=status:ACTIVE",
    "az login",
    "az login --use-device-code",
    "az group list -o table",
    "aws sts get-caller-identity",
    "aws sts get-session-token --duration-seconds 900",
    "ls -a",
    "git add -A",
    "ssh -p 2222 host",
    "docker run -p 8080:80 -u 1000:1000 img",
    "echo eyJhbGciOiJIUzI1NiJ9",
    "curl https://x/eyJ.html",
    "python3 -m pytest -q -p no:cacheprovider tests/test_dashboard_lane_extras_unit.py",
    "ruff check . && mypy --strict simplicio_loop",
    "git log 122df7e5c0a4d7f6c0e8a1b2c3d4e5f60718293a..HEAD",
    "pytest --cov=simplicio_loop --cov-report=term-missing -q",
    "npm run token-check",
    "cat secrets.md",
]
PAIRS = [  # (command, text that must be masked)
    ("password=hunter2hunter2", "hunter2hunter2"),
    ("PASSWORD: 'abcd1234'", "abcd1234"),
    ("api_key = \"abcdefgh\"", "abcdefgh"),
    ("x-access-key=abcdefgh", "abcdefgh"),
    ("db_secret=abcdefgh", "abcdefgh"),
    ("my-pwd:abcdefgh", "abcdefgh"),
    ("AWS_SECRET_ACCESS_KEY=abcdefgh", "abcdefgh"),
    ("token_value=abcdefgh", "abcdefgh"),
    ("a" * 64 + "password=abcdefgh", "abcdefgh"),
    ("a" * 64 + "_password=abcdefgh", "abcdefgh"),
    ("a" * 200 + "_password=abcdefgh", "abcdefgh"),
    ("password-" * 7 + "x=abcdefgh", "abcdefgh"),
]


def test_the_pr_corpus_is_still_28_and_all_masked():
    assert len(SECRET_CORPUS) == 28
    for command, secret in SECRET_CORPUS:
        assert secret not in runs.redact_command(command), command


@pytest.mark.parametrize(("command", "secret"), LEAKS)
def test_a_secret_the_audit_found_leaking_is_masked(command, secret):
    masked = runs.redact_command(command)
    assert secret not in masked and "[REDACTED" in masked


def test_a_jwt_is_masked_whole():
    masked = runs.redact_command(f"curl --jwt {JWT} https://x")
    assert "eyJ" not in masked and masked.endswith(" https://x")


@pytest.mark.parametrize("command", ORDINARY)
def test_an_ordinary_command_is_left_as_it_is(command):
    assert runs.redact_command(command) == command


@pytest.mark.parametrize(("command", "secret"), PAIRS)
def test_a_key_value_pair_is_still_masked(command, secret):
    assert secret not in runs.redact_text(command)
    assert secret not in runs.redact_command(command)


@pytest.mark.parametrize("command", ["password=abc", "password=", "token", "tokenize foo bar", "secret: yes", "pwd"])
def test_a_pair_with_no_value_to_hide_is_left_alone(command):
    assert runs.redact_text(command) == command


# D6: the key-value pattern costs the same per character whatever the command looks like.
HOSTILE = {
    "pwd": "pwd-" * 1024 + "=",
    "api-key": "api-key-" * 512,
    "token": "token-" * 683,
    "password": "password-" * 455,
    "secret": "secret_" * 585,
    "access-key": "access-key-" * 373,
}


# the patterns this change adds, against the commands they are most likely to be retried on
HOSTILE_COMMANDS = {
    **HOSTILE,
    "redis-cli": "redis-cli " * 409,
    "redis-cli -a": "redis-cli -a " * 341,
    "sqlcmd -P": "sqlcmd -P " * 455,
    "az login": "az login " * 455,
    "smbclient -U": "smbclient -U a" * 292,
    "vault login": "vault login " * 341,
    "vault login -x": "vault login -x " * 273,
    "eyJ": "eyJ" * 1365,
    "eyJ-": "eyJ-" * 1024,
    "eyJ.": "eyJabcde." * 455,
    "eyJ tail": "eyJ" + "a" * 4000,
    "print-identity-token": "print-identity-token --access-token " * 117,
}


def _cpu_ms(function, text: str, rounds: int = 5) -> float:
    best = float("inf")
    for _ in range(rounds):
        began = time.process_time()
        function(text)
        best = min(best, time.process_time() - began)
    return best * 1000


def _pair(text: str) -> str:
    return runs._PAIR_RE.sub(r"\1\2[REDACTED]", text)


@pytest.mark.parametrize("name", sorted(HOSTILE_COMMANDS))
def test_a_hostile_command_is_scrubbed_in_bounded_cpu_time(name):
    text = HOSTILE_COMMANDS[name]
    assert _cpu_ms(runs.redact_command, text, 3) < 400  # generous: a loaded host, not the target (about 60 ms)


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_the_pair_pattern_does_work_proportional_to_the_text_not_to_its_shape(name):
    """Machine independent: the hostile text against a benign one of the same length, measured back to back.

    The old pattern ran 500-2600 times the benign time (it retried a 64-character prefix at every word start, and a
    64-character suffix at every prefix); a pattern that does a bounded amount of work per keyword stays within a
    few times. The ratio of two timings taken together does not move with the load of the host.
    """
    text = HOSTILE[name]
    benign = "x" * len(text)
    hostile_ms, benign_ms = _cpu_ms(_pair, text, 7), max(_cpu_ms(_pair, benign, 7), 0.05)
    assert hostile_ms / benign_ms < 60, (name, hostile_ms, benign_ms)


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_the_cost_grows_linearly_with_the_command(name):
    small, large = HOSTILE[name][:1024], HOSTILE[name]
    ratio = _cpu_ms(_pair, large, 7) / max(_cpu_ms(_pair, small, 7), 0.02)
    assert ratio < 8, (name, ratio)  # 4x the text: about 4x the work, never 16x


# D5: the diagnostic of a leaked process masks argv, then clips.
@pytest.mark.skipif(os.name == "nt", reason="POSIX /proc command-line contract")
class TestLeakDiagnostic:
    @staticmethod
    def _line(argv: list[str], marker: str) -> str:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", *argv],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                with open("/proc/%d/cmdline" % proc.pid, "rb") as handle:
                    if marker.encode() in handle.read():  # exec has happened
                        break
                time.sleep(0.02)
            return quality_process._describe_leaked({proc.pid})
        finally:
            proc.kill()
            proc.wait()

    def test_a_secret_in_the_argv_of_a_leaked_process_is_masked(self):
        line = self._line(["run", "--token", "hunter2hunter2", "--password=correcthorsebattery", "tail-marker"], "tail-marker")
        assert line.startswith("descendant_leak pid=") and line.endswith("\n") and line.count("\n") == 1
        assert "hunter2hunter2" not in line and "correcthorsebattery" not in line
        assert "--token [REDACTED]" in line and "tail-marker" in line

    def test_the_secret_is_masked_before_the_clip_can_split_it(self):
        """The clip keeps the first 98 characters; cut first, ``hun`` would stay behind, too short for any pattern."""
        before = len(f"{sys.executable} -c import time; time.sleep(30) ")
        pad = 98 - 3 - len(" --token ") - before  # the secret starts three characters before the end of the clip's head
        if pad < 1:
            pytest.skip("the interpreter path is too long to place the secret at the clip boundary")
        argv = ["a" * pad, "--token", "hunter2hunter2hunter2", "z" * 400, "tail-marker"]
        line = self._line(argv, "tail-marker")
        assert "hun" not in line and "ter2" not in line
        assert len(line.split("cmd=", 1)[1].rstrip("\n")) <= quality_process.LEAK_COMMAND_LIMIT
        assert line.rstrip("\n").endswith("tail-marker")

    def test_an_ordinary_command_is_described_as_it_was(self):
        line = self._line(["--cov=simplicio_loop", "tail-marker"], "tail-marker")
        assert line.rstrip("\n").endswith("--cov=simplicio_loop tail-marker")

"""`simplicio-loop install` ends with the evidence tools (#1843), then the setup (#1841): it is complete only while every
required evidence tool is ok, and the exit code is 1 while one is not (2 when the setup failed, and 2 wins)."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from simplicio_loop import cli_impl, evidence_tools, prereqs, setup_cli

from .fakes import Fakes, check, summary_file


def chromium_missing():
    return ([check("evidence:node"), check("evidence:playwright"),
             prereqs.Check("evidence:chromium", "missing", True, None, None, None, "simplicio-loop setup", "user")],
            [prereqs.Action("evidence:chromium", "failed", "download failed")])


def all_ok():
    return [check("evidence:node"), check("evidence:playwright"), check("evidence:chromium"), check("evidence:check")], []


def test_after_install_names_the_missing_tool_its_fix_and_the_failure(home, monkeypatch, capsys):
    monkeypatch.setattr(setup_cli, "evidence_for_install", lambda environ: chromium_missing())
    monkeypatch.setattr(setup_cli, "_setup_at_the_end", lambda out: 0)  # the setup has tests of its own
    assert setup_cli.after_install() == 1
    out = capsys.readouterr().out
    assert "evidence:chromium" in out and "download failed" in out and "simplicio-loop setup" in out


def test_install_is_not_complete_while_a_required_evidence_tool_is_missing(home, monkeypatch, capsys):
    target = home / "project"
    target.mkdir()
    monkeypatch.setattr(setup_cli, "evidence_for_install", lambda environ: chromium_missing())
    monkeypatch.setattr(setup_cli, "_setup_at_the_end", lambda out: 0)
    assert cli_impl.main(["install", "--target", str(target)]) == 1
    assert "install is not complete: evidence:chromium" in capsys.readouterr().out


def test_install_is_complete_when_the_evidence_tools_are_ok(home, monkeypatch):
    target = home / "project"
    target.mkdir()
    monkeypatch.setattr(setup_cli, "evidence_for_install", lambda environ: all_ok())
    monkeypatch.setattr(setup_cli, "_setup_at_the_end", lambda out: 0)
    assert cli_impl.main(["install", "--target", str(target)]) == 0


def test_the_setup_runs_after_the_evidence_step_and_a_missing_tool_still_decides(home, monkeypatch):
    fakes = Fakes()
    fakes.evidence_checks, fakes.evidence_actions = chromium_missing()
    monkeypatch.setattr(setup_cli, "evidence_for_install", lambda environ: chromium_missing())
    monkeypatch.setattr(setup_cli, "real_seams", lambda: fakes.seams())
    assert setup_cli.after_install(out=io.StringIO()) == 1
    assert summary_file(home).exists()  # the setup ran after the evidence step and recorded its summary


def test_every_install_checks_the_evidence_tools_before_the_setup(home, monkeypatch):
    seen, order = [], []

    def evidence(environ):
        seen.append(dict(environ))
        return all_ok()

    monkeypatch.setattr(setup_cli, "evidence_for_install", evidence)
    monkeypatch.setattr(setup_cli, "_setup_at_the_end", lambda out: order.append("setup") or 0)
    assert setup_cli.after_install(out=io.StringIO()) == 0
    assert seen and order == ["setup"]


def test_the_npm_install_gets_the_node_ca_setting_it_is_given(tmp_path):
    """Node and npm read a private CA only from NODE_EXTRA_CA_CERTS (SSL_CERT_FILE is ignored): the install passes it on."""
    seen = {}

    def run(argv, timeout, cwd=None, env=None):
        if Path(argv[0]).name == "node":
            return 0, "v26.0.0\n"
        seen[Path(argv[0]).name] = dict(env or {})
        return 1, "npm ERR! network request failed"  # the install stops here: only the environment it ran with matters

    environ = {"HOME": str(tmp_path), "PATH": "/opt/fake/bin", "NODE_EXTRA_CA_CERTS": "/opt/corp/ca.pem"}
    evidence_tools.step(tmp_path / "state", environ=environ, which=lambda name: f"/opt/fake/bin/{name}", run=run,
                        dry_run=False, validate=False)
    assert seen["npm"]["NODE_EXTRA_CA_CERTS"] == "/opt/corp/ca.pem"


# --- a private CA that the install does not trust: the row names the command that works ----------------------------------

NPM_TRUST = ("npm error code SELF_SIGNED_CERT_IN_CHAIN\n"
             "npm error request to https://registry.npmjs.org/@playwright%2ftest failed, reason: self-signed certificate in certificate chain\n")
BROWSER_TRUST = "Error: self-signed certificate in certificate chain\n"
BROWSER_DRY_RUN = ("Chrome for Testing 156.0.8078.4 (playwright chromium v1248)\n"
                   "  Install location:    /cache/ms-playwright/chromium-1248\n")
PLAIN_SETUP = "simplicio-loop setup"


class PrivateCa:
    """A machine behind a proxy: npm and the browser download fail on the proxy's certificate, which the install does not trust."""

    def __init__(self, npm_text=NPM_TRUST, browser_text=BROWSER_TRUST):
        self.npm_text, self.browser_text = npm_text, browser_text

    def which(self, name):
        return f"/opt/fake/bin/{name}"

    def run(self, argv, timeout, cwd=None, env=None):
        head, args = Path(argv[0]).name, [str(part) for part in argv[1:]]
        if head == "node":
            return 0, "v26.0.0\n"
        if head == "npm":
            return 1, self.npm_text
        if head == "playwright" and args[:2] == ["install", "--dry-run"]:
            return 0, BROWSER_DRY_RUN
        if head == "playwright" and args[:2] == ["install", "chromium"]:
            return 1, self.browser_text
        return None, ""


def pinned_playwright(state):
    """The pinned @playwright/test is already in the tools folder, so only its browser is left to download."""
    package = state / evidence_tools.FOLDER / "node_modules"
    (package / "@playwright" / "test").mkdir(parents=True)
    (package / "@playwright" / "test" / "package.json").write_text(json.dumps({"version": evidence_tools.PLAYWRIGHT_VERSION}))
    (package / ".bin").mkdir(parents=True)
    (package / ".bin" / "playwright").write_text("#!/bin/sh\n")


def proxied(home, **variables):
    return {"HOME": str(home), "PATH": "/opt/fake/bin", **variables}


def row(checks, name):
    return next(check for check in checks if check.name == name)


@pytest.mark.parametrize("variable", ["SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"])
def test_a_trust_error_of_npm_names_the_command_that_works_with_the_ca_bundle(home, variable):
    bundle = home / "corp-ca.pem"
    bundle.write_text("")
    machine = PrivateCa()
    checks, _ = evidence_tools.step(home / "state", environ=proxied(home, **{variable: str(bundle)}), which=machine.which,
                                    run=machine.run, dry_run=False, validate=False)
    command = f"NODE_EXTRA_CA_CERTS={bundle} simplicio-loop setup"
    assert row(checks, "evidence:playwright").fix == command
    assert row(checks, "evidence:chromium").fix == command  # its install never starts: the same trust error stops it


def test_a_trust_error_without_a_ca_variable_names_the_placeholder_for_the_bundle(home):
    machine = PrivateCa()
    checks, _ = evidence_tools.step(home / "state", environ=proxied(home), which=machine.which, run=machine.run,
                                    dry_run=False, validate=False)
    assert row(checks, "evidence:playwright").fix == "NODE_EXTRA_CA_CERTS=<path to your CA bundle> simplicio-loop setup"


def test_a_trust_error_of_the_browser_download_names_the_same_command(home):
    bundle = home / "corp-ca.pem"
    bundle.write_text("")
    pinned_playwright(home / "state")
    machine = PrivateCa()
    checks, actions = evidence_tools.step(home / "state", environ=proxied(home, SSL_CERT_FILE=str(bundle)), which=machine.which,
                                          run=machine.run, dry_run=False, validate=False)
    assert [(action.name, action.result) for action in actions] == [("evidence:chromium", "failed")]
    assert row(checks, "evidence:chromium").fix == f"NODE_EXTRA_CA_CERTS={bundle} simplicio-loop setup"


def test_a_network_error_keeps_the_plain_setup_fix(home):
    machine = PrivateCa(npm_text="npm ERR! network request failed\n")
    checks, _ = evidence_tools.step(home / "state", environ=proxied(home), which=machine.which, run=machine.run,
                                    dry_run=False, validate=False)
    assert row(checks, "evidence:playwright").fix == PLAIN_SETUP


def test_the_optional_explainer_names_its_own_command_with_the_trust_fix(home):
    bundle = home / "corp-ca.pem"
    bundle.write_text("")
    machine = PrivateCa()
    checks, _ = evidence_tools.step(home / "state", environ=proxied(home, SSL_CERT_FILE=str(bundle)), which=machine.which,
                                    run=machine.run, dry_run=False, validate=False, hyperframes=True)
    assert row(checks, "evidence:hyperframes").fix == f"NODE_EXTRA_CA_CERTS={bundle} simplicio-loop setup --with-hyperframes"


def test_the_install_prints_the_command_that_works_for_a_trust_error(home, monkeypatch):
    bundle = home / "corp-ca.pem"
    bundle.write_text("")
    machine = PrivateCa()
    environ = proxied(home, SSL_CERT_FILE=str(bundle))
    monkeypatch.setattr(setup_cli, "evidence_for_install", lambda _: evidence_tools.step(
        home / "state", environ=environ, which=machine.which, run=machine.run, dry_run=False, validate=False))
    monkeypatch.setattr(setup_cli, "_setup_at_the_end", lambda out: 0)
    out = io.StringIO()
    assert setup_cli.after_install(out=out) == 1
    assert f"evidence:playwright: missing. Fix: NODE_EXTRA_CA_CERTS={bundle} simplicio-loop setup" in out.getvalue()

"""The login lock excludes a Rust program that locks the same way the Runtime does (#1575).

The Runtime locks `login.lock` with `std::fs::File::try_lock` (src/runtime_auth.rs `auth_lock`). This test compiles a
ten-line Rust program that makes the same calls and checks both directions against `auth.file_lock`. It proves the
lock family and the sidecar name match on this OS; it does NOT run the real Runtime. Skipped when rustc is missing.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from simplicio_loop import auth

RUST = """
use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::{env, thread, time::Duration};
fn main() {
    let args: Vec<String> = env::args().collect();
    let mut options = OpenOptions::new();
    options.read(true).write(true).create(true).truncate(false).mode(0o600); // as the Runtime's auth_lock
    let file = options.open(&args[2]).unwrap();
    match file.try_lock() {
        Ok(()) => {
            println!("locked");
            if args[1] == "hold" { thread::sleep(Duration::from_secs(args[3].parse().unwrap())); }
        }
        Err(std::fs::TryLockError::WouldBlock) => { println!("wouldblock"); std::process::exit(3); }
        Err(e) => { println!("error {e}"); std::process::exit(4); }
    }
}
"""

pytestmark = pytest.mark.skipif(shutil.which("rustc") is None or os.name == "nt",
                                reason="needs rustc (File::try_lock) on a POSIX host")


@pytest.fixture(scope="module")
def locker(tmp_path_factory):
    work = tmp_path_factory.mktemp("rustlock")
    (work / "main.rs").write_text(RUST)
    built = subprocess.run(["rustc", "-O", "main.rs", "-o", "locker"], cwd=work, capture_output=True, text=True)
    if built.returncode != 0:
        pytest.skip(f"rustc could not build the helper (File::try_lock needs Rust 1.89+): {built.stderr[-200:]}")
    return str(work / "locker")


def test_a_lock_held_by_rust_makes_python_wait(locker, tmp_path):
    login = tmp_path / "login.json"
    holder = subprocess.Popen([locker, "hold", str(auth.lock_path(login)), "5"], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(auth.LoginError) as err:
            with auth.file_lock(login, wait_s=0.4):
                pytest.fail("Python took the lock while the Rust program held it")
        assert err.value.reason_code == "login_lock_timeout"
    finally:
        holder.kill()
        holder.wait()


def test_a_lock_held_by_python_makes_rust_see_would_block(locker, tmp_path):
    login = tmp_path / "login.json"
    with auth.file_lock(login, wait_s=1):
        busy = subprocess.run([locker, "try", str(auth.lock_path(login))], capture_output=True, text=True)
        assert (busy.returncode, busy.stdout.strip()) == (3, "wouldblock")
    free = subprocess.run([locker, "try", str(auth.lock_path(login))], capture_output=True, text=True)
    assert (free.returncode, free.stdout.strip()) == (0, "locked")

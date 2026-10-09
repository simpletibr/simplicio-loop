# The daemon

`simplicio-loop` runs as a thin client over a per-user daemon. The daemon imports the loop, Mapper and dev-cli once and keeps them ready. Each command forks one child from the daemon. The child runs the command with the caller's environment and standard input, output and error. The daemon's parent process never runs command code.

## How it works

The first command to run starts the daemon. The daemon listens on a unix socket in the run directory. Each request forks a child process. The child inherits the caller's environment, current working directory, and file descriptors 0, 1 and 2 (stdin, stdout, stderr). The child runs the command and exits. The parent reports the exit code and never blocks on the child.

When the caller closes the connection (for example, pressing Ctrl-C), the child's process group gets SIGTERM, then SIGKILL after 5 seconds.

## Run directory

The daemon stores its socket, lock file and log in `$SIMPLICIO_LOOP_DAEMON_DIR`, else `$XDG_RUNTIME_DIR/simplicio-loop`, else `~/.simplicio-loop/run`. The user must own the directory (mode 0700). The socket name is `<key>.sock`, where the key is a hash of the Python interpreter, package path, PYTHONPATH, PYTHONHOME and the network guard setting.

## Operator shortcut

Inside a daemon command, calls to the Mapper and dev-cli fork from the daemon's modules instead of starting a new Python process. This skips the start of a new Python interpreter for each call. The operator must be the console script of the same Python environment as the loop. A different operator on PATH starts as a normal process.

## Protocol

Requests are JSON lines. Each request carries the program name, arguments, current working directory and environment. The daemon sends the stdin, stdout and stderr file descriptors with SCM_RIGHTS. Replies are JSON lines with the exit code when done.

Each request has a protocol version number. If the daemon's code changes (install, update or file edit), the daemon rejects the request with an error code and exits. The client starts a new daemon and retries once. Dependencies outside the loop, Mapper and dev-cli are not watched.

## Limits and lifecycle

At most N commands run at once. N is the measured safe number of workers for the machine. N is at least 1 and at most 16. More commands wait in a queue of 256. The daemon refuses a request if the queue is full. A request that a running command makes, such as a Mapper or dev-cli call, takes no slot, so the pool cannot block itself.

The daemon exits after 900 seconds of idle time (no running commands). The setting `SIMPLICIO_LOOP_DAEMON_IDLE_S` overrides this. A running command keeps the daemon alive.

## Opt-out and errors

Set `SIMPLICIO_LOOP_DAEMON=0` to run the command in-process. Platforms without fork or AF_UNIX sockets (Windows) and frozen binaries run in-process automatically. Tests do not cover these platforms (UNVERIFIED).

There is no silent fallback. If the daemon cannot start or the socket is unsafe, the client prints the reason and exits with code 69. The message names the opt-out. A refused request has a code: `stale`, `busy`, `peer_uid`, `protocol`, `socket_mode`, `dir_mode` and others.

## Known limits

A command that opens `/dev/tty` itself, such as the hidden password prompt of the 24/7 watcher setup, has no controlling terminal in the daemon. Run it with `SIMPLICIO_LOOP_DAEMON=0`. Ctrl-C stops the command with SIGTERM, not SIGINT. The 24/7 watcher runs its commands in a sandbox with `SIMPLICIO_LOOP_DAEMON=0`, so a sandboxed command never starts or reaches a daemon.

## Security

No TCP. No token on the wire. The client checks that the socket belongs to the user and is not open to group or others. The daemon checks the user id of the peer with SO_PEERCRED (Linux) or LOCAL_PEERCRED (macOS). The daemon starts with an allowlist of environment variables (PATH, HOME, locale, PYTHONPATH and similar). Logs hold the program name, the exit code and the duration. The arguments and the environment are never logged.

## Commands

| Command | Use |
|---|---|
| `simplicio-loop daemon serve` | Start the daemon in the foreground |
| `simplicio-loop daemon status` | Print daemon status as JSON. Exit code is 3 when not running. |
| `simplicio-loop daemon stop` | Stop the daemon |

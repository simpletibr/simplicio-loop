# The daemon

`simplicio-loop` runs as a thin client over a per-user daemon. The daemon imports the loop, Mapper and dev-cli once and keeps them ready. Each command forks one child from the daemon. The child runs the command with the caller's environment and standard input, output and error. The daemon's parent process never runs command code.

## How it works

The first command to run starts the daemon. The daemon listens on a unix socket in the run directory. Each request forks a child process. The child inherits the caller's environment, current working directory, and file descriptors 0, 1 and 2 (stdin, stdout, stderr). The child runs the command and exits. The parent reports the exit code and never blocks on the child.

When the caller closes the connection (for example, pressing Ctrl-C), the child's process group gets SIGTERM, then SIGKILL after 5 seconds. The command receives SIGTERM as a KeyboardInterrupt, as Ctrl-C does in a process. Its `finally` blocks and `atexit` functions run, and it exits with code 130. A command that ignores SIGTERM gets SIGKILL.

On Linux the kernel also kills a command when the daemon dies (for example, the out-of-memory killer). No command outlives its daemon, so a retry with `SIMPLICIO_LOOP_DAEMON=0` meets no second writer. This does not cover the processes that the command started. Nobody tested this on macOS (UNVERIFIED).

If the caller sets `PYTHONUNBUFFERED`, the command writes its output without a buffer, as Python does.

## Run directory

The daemon stores its socket, lock file and log in `$SIMPLICIO_LOOP_DAEMON_DIR`, else `$XDG_RUNTIME_DIR/simplicio-loop`, else `~/.simplicio-loop/run`. The user must own the directory (mode 0700). The parent directory must belong to the user or to root. Other users must not write to it, unless it is sticky. The socket name is `<key>.sock`, where the key is a hash of the Python interpreter, package path, PYTHONPATH, PYTHONHOME and the network guard setting. A unix socket path holds about 100 bytes. If `<run directory>/<key>.sock` is longer, the socket takes a short name, a hash of that path, in the private directory `simplicio-loop-<uid>` of the temporary directory. The client and the daemon derive the same path. The lock file and the log stay in the run directory.

## Operator shortcut

Inside a daemon command, calls to the Mapper and dev-cli fork from the daemon's modules instead of starting a new Python process. This skips the start of a new Python interpreter for each call. The operator must be the console script of the same Python environment as the loop. A different operator on PATH starts as a normal process.

A command can keep running while the code under the daemon changes (an update or a checkout). The daemon then answers `stale`, or the daemon is already gone (`not_running`). The top-level command exits with 69 and gives the reason, as written under Opt-out and errors. A Mapper or dev-cli call from inside a running command does not fail the whole command. It starts the operator as a normal process, as before the daemon. This is a decision, not a hidden fallback: the alternative is to fail the command that is half done. Every other refusal of such a call (`busy`, `peer_uid`, `socket_mode` and others) still fails the call.

## Protocol

Requests are JSON lines. Each request carries the program name, arguments, current working directory and environment. The daemon sends the stdin, stdout and stderr file descriptors with SCM_RIGHTS. Replies are JSON lines with the exit code when done.

Each request has a protocol version number. If the daemon's code changes (install, update or file edit), the daemon rejects the request with an error code and exits. The client starts a new daemon and retries once. Dependencies outside the loop, Mapper and dev-cli are not watched.

## Limits and lifecycle

At most N commands run at once. N is the measured safe number of workers for the machine. N is at least 1 and at most 16. More commands wait in a queue of 256. The daemon refuses a request if the queue is full. After 5 seconds in the queue, a command prints a line on its standard error that says it waits for a free slot. After `SIMPLICIO_LOOP_DAEMON_WAIT_S` seconds (600 by default), the daemon refuses it with `busy` and the time it waited. A request that a running command makes, such as a Mapper or dev-cli call, takes no slot, so the pool cannot block itself.

The daemon exits after 900 seconds of idle time (no running commands). The setting `SIMPLICIO_LOOP_DAEMON_IDLE_S` overrides this. A running command keeps the daemon alive.

## Priority, limits and cpus

The client sends its priority (`nice`), its limits (open files, processes, address space, cpu time, core size) and its set of cpus with each request. The command runs with those, not with the ones of the first caller that started the daemon. The daemon itself does not change. `nice -n 10 simplicio-loop ...` lowers the priority of the command.

An unprivileged daemon cannot give a command more priority or higher limits than it started with. Then the command runs with the settings of the daemon. It prints a line on its standard error that names what the system refused. Run `simplicio-loop daemon stop`, then start the next command from the shell that must set them. Nobody tested this on macOS (UNVERIFIED).

## Opt-out and errors

Set `SIMPLICIO_LOOP_DAEMON=0` to run the command in-process. Platforms without fork or AF_UNIX sockets (Windows) and frozen binaries run in-process automatically. Tests do not cover these platforms (UNVERIFIED).

There is no silent fallback. If the daemon cannot start or the socket is unsafe, the client prints the reason and exits with code 69. The message names the opt-out. A refused request has a code: `stale`, `busy`, `peer_uid`, `protocol`, `socket_mode`, `dir_mode` and others.

## Known limits

A command that opens `/dev/tty` itself, such as the hidden password prompt of the 24/7 watcher setup, has no controlling terminal in the daemon. Run it with `SIMPLICIO_LOOP_DAEMON=0`. The 24/7 watcher runs its commands in a sandbox with `SIMPLICIO_LOOP_DAEMON=0`, so a sandboxed command never starts or reaches a daemon.

## Security

No TCP. No token on the wire. The client checks that the socket belongs to the user and is not open to group or others. The daemon checks the user id of the peer with SO_PEERCRED (Linux) or LOCAL_PEERCRED (macOS). The daemon starts with an allowlist of environment variables (PATH, HOME, locale, PYTHONPATH and similar). Logs hold the program name, the exit code and the duration. The arguments and the environment are never logged.

## Commands

| Command | Use |
|---|---|
| `simplicio-loop daemon serve` | Start the daemon in the foreground |
| `simplicio-loop daemon status` | Print daemon status as JSON. Exit code is 3 when not running. |
| `simplicio-loop daemon stop` | Stop the daemon |

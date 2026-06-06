"""Remote command execution over SSH with live streaming.

Two execution modes:

* ``stream_exec`` — for long-running, credential-using commands (vcs pull/import,
  git fetch/pull/push/checkout). Streams output line-by-line to a callback so the
  GUI log updates live, and requests a PTY so git/vcs progress is line-buffered
  and flushed promptly (stdout and stderr arrive merged on the PTY). Git on the
  robot authenticates via the runtime-injected key (GIT_SSH_COMMAND, see
  core/credential.py) — NOT SSH agent forwarding, which is broken on Windows.

* ``capture_exec`` — for short read-only commands whose full output we need to
  parse (vcs export / status). No PTY, stdout and stderr kept separate.

foldersync/fs/sftp_fs.py reads command output all at once; this module differs
by streaming.
"""

from __future__ import annotations

import time
from typing import Callable, List, Tuple

import paramiko


def split_lines(buf: bytes) -> Tuple[List[str], bytes]:
    """Split a byte buffer into complete text lines + trailing remainder.

    Treats CRLF, lone LF, and lone CR (carriage-return progress updates from
    git) all as line breaks so progress output shows up live. The remainder is
    whatever follows the last break (an incomplete line) and is carried over to
    the next read. Pure function — unit-tested directly.
    """
    text = buf.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if b"\n" not in text:
        return [], buf
    parts = text.split(b"\n")
    remainder_text = parts.pop()
    lines = [p.decode("utf-8", "replace") for p in parts]
    # The remainder may be a partial multibyte sequence; keep it as bytes.
    remainder = remainder_text
    return lines, remainder


def stream_exec(
    client: paramiko.SSHClient,
    command: str,
    on_line: Callable[[str, str], None],
    cancel_event,
    stdin_data: str = "",
) -> int:
    """Run ``command`` on the robot, forwarding the local agent, streaming lines.

    ``on_line(text, stream)`` is called for each output line (``stream`` is
    "out" or "err"). ``stdin_data`` (e.g. .repos content for ``vcs import``) is
    written to the command's stdin then EOF. Returns the remote exit code, or -1
    if cancelled. Raises if no transport is available.
    """
    transport = client.get_transport()
    if transport is None:
        raise RuntimeError("SSH transport is not connected")

    chan = transport.open_session()
    # NOTE: no SSH agent forwarding. git/vcs on the robot authenticate via the
    # runtime-injected key (GIT_SSH_COMMAND, see core/credential.py), not a
    # forwarded agent — paramiko's agent forwarding is broken on Windows anyway.
    # A PTY line-buffers and flushes git/vcs progress promptly, but turns stdin
    # into a terminal — which would corrupt piped YAML. So use a PTY only when
    # there is no stdin payload (the common pull/fetch/push case).
    if not stdin_data:
        chan.get_pty()
    chan.exec_command(command)

    if stdin_data:
        chan.sendall(stdin_data.encode("utf-8"))
    chan.shutdown_write()

    out_buf = b""
    err_buf = b""
    try:
        while True:
            if cancel_event.is_set():
                chan.close()
                return -1

            progressed = False
            if chan.recv_ready():
                out_buf += chan.recv(8192)
                lines, out_buf = split_lines(out_buf)
                for line in lines:
                    on_line(line, "out")
                progressed = True
            if chan.recv_stderr_ready():
                err_buf += chan.recv_stderr(8192)
                lines, err_buf = split_lines(err_buf)
                for line in lines:
                    on_line(line, "err")
                progressed = True

            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                break
            if not progressed:
                time.sleep(0.05)

        # flush any trailing partial lines
        for buf, stream in ((out_buf, "out"), (err_buf, "err")):
            if buf:
                on_line(buf.decode("utf-8", "replace"), stream)
        return chan.recv_exit_status()
    finally:
        if not chan.closed:
            chan.close()


def capture_exec(client: paramiko.SSHClient, command: str) -> Tuple[int, str, str]:
    """Run a short command and return (exit_code, stdout, stderr) in full.

    Used for vcs export/status whose output we parse — no PTY so streams stay
    separate and stdout is clean YAML.
    """
    stdin, stdout, stderr = client.exec_command(command)
    stdin.close()
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err

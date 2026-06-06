"""Runtime credential injection for the robot.

paramiko's SSH agent forwarding does not work from a Windows operator PC (its
forward proxy imports the Unix-only ``fcntl`` module), so instead of forwarding
an agent we inject the operator's git SSH key into the robot's RAM for the
duration of the session:

* The key is uploaded to ``/dev/shm`` (a tmpfs — RAM-backed, never written to
  persistent disk) with mode 0600.
* git/vcs is told to use it via ``GIT_SSH_COMMAND``.
* The key directory is removed on disconnect / app close.

So nothing is persisted on the robot's disk; the key lives only in robot RAM
while a session is open, then is wiped.

Only unencrypted keys are supported (a passphrase-protected key would make
remote ``ssh`` block prompting). The github key is detected from the operator's
~/.ssh/config (see ssh_config.github_identity_file).
"""

from __future__ import annotations

import posixpath
import secrets
from dataclasses import dataclass
from typing import Optional, Tuple

import paramiko

REMOTE_BASE = "/dev/shm"  # tmpfs on Linux robots — RAM, not persistent disk


@dataclass
class Credential:
    local_path: str
    fingerprint: str
    remote_dir: str = ""
    remote_key: str = ""


def load_and_check(local_path: str) -> Tuple[Optional[str], str]:
    """Load a private key from disk to validate it.

    Returns (fingerprint, "") on success, or (None, error_message). Rejects
    passphrase-protected keys, which cannot be used non-interactively on the
    robot.
    """
    if not local_path:
        return None, "no github SSH key found (set one in ~/.ssh/config Host github.com)"
    last_err = ""
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            key = cls.from_private_key_file(local_path)
            return key.get_fingerprint().hex(), ""
        except paramiko.PasswordRequiredException:
            return None, (
                f"key {local_path} is passphrase-protected; this mode needs an "
                "unencrypted key (use a passphrase-less deploy key)"
            )
        except paramiko.SSHException as exc:
            last_err = str(exc)
            continue
    return None, f"could not load key {local_path}: {last_err}"


def inject(client: paramiko.SSHClient, local_path: str, fingerprint: str) -> Credential:
    """Upload the key to the robot's tmpfs (RAM) with mode 0600.

    Raises on failure (no /dev/shm, upload error). The caller cleans up via
    ``cleanup`` on disconnect.
    """
    with open(local_path, "rb") as f:
        key_bytes = f.read()

    token = secrets.token_hex(8)
    remote_dir = posixpath.join(REMOTE_BASE, f"vcsupdate-{token}")
    remote_key = posixpath.join(remote_dir, "id")

    sftp = client.open_sftp()
    try:
        sftp.mkdir(remote_dir, mode=0o700)
        with sftp.open(remote_key, "wb") as rf:
            rf.write(key_bytes)
        sftp.chmod(remote_key, 0o600)
    finally:
        sftp.close()

    return Credential(
        local_path=local_path,
        fingerprint=fingerprint,
        remote_dir=remote_dir,
        remote_key=remote_key,
    )


def git_ssh_command(cred: Credential) -> str:
    """The GIT_SSH_COMMAND value pointing git at the injected key."""
    return (
        f"ssh -i {cred.remote_key} -o IdentitiesOnly=yes "
        "-o StrictHostKeyChecking=accept-new -o BatchMode=yes"
    )


def cleanup(client: paramiko.SSHClient, cred: Optional[Credential]) -> None:
    """Remove the injected key directory from the robot. Best-effort."""
    if not cred or not cred.remote_dir:
        return
    try:
        _in, out, _err = client.exec_command(f"rm -rf {cred.remote_dir}")
        out.channel.recv_exit_status()  # wait so removal finishes before close
    except Exception:  # noqa: BLE001 - best-effort cleanup
        pass

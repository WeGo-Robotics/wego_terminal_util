"""Read ~/.ssh/config Host aliases and build a paramiko SSH client.

Adapted from foldersync/fs/ssh_config.py. This tool only needs an SSH *exec*
channel (not SFTP), and always relies on agent forwarding for downstream git
auth on the robot, so the connection always sets ``allow_agent`` and
``look_for_keys``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

import paramiko

SSH_CONFIG_PATH = os.path.expanduser(os.path.join("~", ".ssh", "config"))


@dataclass
class HostSpec:
    """Resolved connection parameters for one robot."""

    alias: str
    host: str
    port: int = 22
    user: str = ""
    key_files: List[str] = field(default_factory=list)


def _load_config() -> paramiko.SSHConfig:
    cfg = paramiko.SSHConfig()
    if os.path.exists(SSH_CONFIG_PATH):
        with open(SSH_CONFIG_PATH) as f:
            cfg.parse(f)
    return cfg


def list_host_aliases() -> List[str]:
    """Return concrete Host aliases from ~/.ssh/config (skip wildcard patterns)."""
    aliases: List[str] = []
    if not os.path.exists(SSH_CONFIG_PATH):
        return aliases
    with open(SSH_CONFIG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition(" ")
            if key.lower() != "host":
                continue
            for token in value.split():
                if any(c in token for c in "*?!"):
                    continue
                if token not in aliases:
                    aliases.append(token)
    return aliases


def spec_from_alias(alias: str) -> HostSpec:
    """Resolve an alias to a HostSpec via paramiko SSHConfig."""
    data = _load_config().lookup(alias)
    return HostSpec(
        alias=alias,
        host=data.get("hostname", alias),
        port=int(data.get("port", 22)),
        user=data.get("user", ""),
        key_files=list(data.get("identityfile", []) or []),
    )


def github_identity_file(host: str = "github.com") -> str:
    """Resolve the local private-key path git uses for ``host`` from ssh config.

    Returns the first IdentityFile configured for the host that exists on disk,
    expanding ``~``. Falls back to the usual defaults (~/.ssh/id_ed25519,
    id_rsa). Returns "" if nothing is found.
    """
    candidates = []
    data = _load_config().lookup(host)
    for ident in data.get("identityfile", []) or []:
        candidates.append(os.path.expanduser(ident))
    candidates.append(os.path.expanduser("~/.ssh/id_ed25519"))
    candidates.append(os.path.expanduser("~/.ssh/id_rsa"))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def build_ssh_client(spec: HostSpec) -> paramiko.SSHClient:
    """Open an SSHClient for the given host. Agent + key lookup always enabled
    so the operator's local agent can be forwarded to the robot."""
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    key_filename = [os.path.expanduser(k) for k in spec.key_files] or None
    client.connect(
        hostname=spec.host,
        port=spec.port,
        username=spec.user or None,
        key_filename=key_filename,
        look_for_keys=True,
        allow_agent=True,
        timeout=15,
    )
    return client

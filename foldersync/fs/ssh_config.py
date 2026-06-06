"""Read ~/.ssh/config aliases (populated by make_tunnel scripts) and build
SFTP connections from a source spec.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

import paramiko

SSH_CONFIG_PATH = os.path.expanduser(os.path.join("~", ".ssh", "config"))


@dataclass
class SourceSpec:
    """Describes one pane's source. Either local or ssh."""

    kind: str               # "local" | "ssh"
    path: str               # local dir, or remote base path
    # ssh-only fields:
    alias: str = ""         # ssh config Host alias (display / origin)
    host: str = ""
    port: int = 22
    user: str = ""
    key_files: List[str] = field(default_factory=list)
    password: Optional[str] = None
    passphrase: Optional[str] = None


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


def resolve_host(alias: str) -> dict:
    """Resolve an alias to connection params via paramiko SSHConfig."""
    cfg = _load_config()
    data = cfg.lookup(alias)
    return {
        "hostname": data.get("hostname", alias),
        "port": int(data.get("port", 22)),
        "user": data.get("user", ""),
        "identityfile": data.get("identityfile", []),
    }


def spec_to_dict(spec: Optional[SourceSpec]) -> Optional[dict]:
    """Serialize a SourceSpec for persistence. Omits secrets."""
    if spec is None:
        return None
    return {
        "kind": spec.kind,
        "path": spec.path,
        "alias": spec.alias,
        "host": spec.host,
        "port": spec.port,
        "user": spec.user,
        "key_files": list(spec.key_files),
    }


def spec_from_dict(d: Optional[dict]) -> Optional[SourceSpec]:
    if not d:
        return None
    return SourceSpec(
        kind=d.get("kind", "local"),
        path=d.get("path", ""),
        alias=d.get("alias", ""),
        host=d.get("host", ""),
        port=int(d.get("port", 22)),
        user=d.get("user", ""),
        key_files=list(d.get("key_files") or []),
    )


def spec_label(spec: SourceSpec) -> str:
    """Human-readable one-line description of a source spec."""
    if spec.kind == "local":
        return f"local: {spec.path}"
    origin = spec.alias or (f"{spec.user}@{spec.host}" if spec.host else "ssh")
    return f"ssh {origin}:{spec.path}"


def spec_from_alias(alias: str, remote_path: str) -> SourceSpec:
    info = resolve_host(alias)
    return SourceSpec(
        kind="ssh",
        path=remote_path,
        alias=alias,
        host=info["hostname"],
        port=info["port"],
        user=info["user"],
        key_files=list(info["identityfile"]),
    )


def build_ssh_client(spec: SourceSpec) -> paramiko.SSHClient:
    """Open an SSHClient from a SourceSpec (kind == 'ssh')."""
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    key_filename = [os.path.expanduser(k) for k in spec.key_files] or None
    client.connect(
        hostname=spec.host,
        port=spec.port,
        username=spec.user or None,
        password=spec.password,
        key_filename=key_filename,
        passphrase=spec.passphrase,
        look_for_keys=True,
        allow_agent=True,
        timeout=15,
    )
    return client

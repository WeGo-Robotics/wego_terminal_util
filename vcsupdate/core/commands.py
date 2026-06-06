"""Build remote shell command strings for vcstool and per-repo git operations.

Pure functions — no I/O — so they are easy to unit-test. All commands target a
POSIX remote shell (the robot). Paths are single-quoted with ``shquote``; the
checkout ref is additionally validated against a whitelist before it ever
reaches the shell.
"""

from __future__ import annotations

import posixpath
import re

# git refs (branch/tag) the tool will pass to ``git checkout``. Deliberately
# strict: alphanumerics plus a few separators. Blocks shell metacharacters,
# spaces, and leading dashes that could be parsed as options.
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def shquote(s: str) -> str:
    """POSIX single-quote a shell argument (mirrors foldersync's _shquote)."""
    if s and all(c.isalnum() or c in "@%_-+=:,./" for c in s):
        return s
    return "'" + s.replace("'", "'\"'\"'") + "'"


def is_valid_ref(ref: str) -> bool:
    """True if ``ref`` is a safe branch/tag name to hand to git checkout."""
    return bool(ref) and ".." not in ref and bool(_REF_RE.match(ref))


def _in_dir(path: str, rest: str) -> str:
    return f"cd {shquote(path)} && {rest}"


def with_cred(command: str, git_ssh_command: str) -> str:
    """Prefix a command with GIT_SSH_COMMAND so the git invoked by it (directly
    or via vcstool) authenticates with the runtime-injected key. Exported so it
    propagates to child git processes that vcstool spawns.
    """
    if not git_ssh_command:
        return command
    return f"export GIT_SSH_COMMAND={shquote(git_ssh_command)}; {command}"


# ---- workspace-wide vcstool commands (run at the meta workspace root) ----
def vcs_export(ws: str) -> str:
    """Dump the workspace's current repo set as YAML (used to build the tree)."""
    return _in_dir(ws, "vcs export . --exact")


def vcs_status(ws: str) -> str:
    """Human-readable status (verbose git status per repo) for the log."""
    return _in_dir(ws, "vcs status . --nested")


def vcs_status_short(ws: str) -> str:
    """Machine-parseable per-repo ``git status -sb`` via vcs custom, used to
    build the tree. ``vcs status`` prints verbose long-format git output which
    has no ``## branch...`` line; running git status -sb directly gives the
    short form (branch + ahead/behind + one line per change) that repolist
    parses.
    """
    return _in_dir(ws, "vcs custom . --nested --git --args status -sb")


def vcs_pull(ws: str, workers: int = 8) -> str:
    return _in_dir(ws, f"vcs pull . --nested --workers {int(workers)}")


def vcs_import_stdin(ws: str, subdir: str = "src", workers: int = 8) -> str:
    """Clone/sync repos read from stdin into ``subdir`` (vcstool reads .repos from
    stdin when no --input is given). The operator's local .repos content is piped
    over the SSH channel's stdin, so nothing is written to the robot's disk first.

    ``subdir`` is where the repos land (e.g. ``src`` → ``<ws>/src/<repo>``);
    pass "" or "." to import at the workspace root.
    """
    target = subdir.strip() or "."
    return _in_dir(ws, f"vcs import {shquote(target)} --workers {int(workers)}")


def vcs_import_file(ws: str, subdir: str = "src", repos_file: str = "", workers: int = 8) -> str:
    """Clone/sync repos into ``subdir`` from a .repos file already on the robot.

    ``repos_file`` may be relative to the workspace (it runs with cwd = ws).
    """
    target = subdir.strip() or "."
    return _in_dir(
        ws,
        f"vcs import {shquote(target)} --input {shquote(repos_file)} --workers {int(workers)}",
    )


def cat(ws: str, path: str) -> str:
    """Read a file on the robot (relative to the workspace, or absolute)."""
    return _in_dir(ws, f"cat {shquote(path)}")


def vcs_validate_stdin() -> str:
    return "vcs validate"


# ---- per-repo git commands (run inside one repo's working tree) ----
def repo_dir(ws: str, rel: str) -> str:
    """Absolute remote path of a repo given the workspace root and its relpath."""
    return posixpath.join(ws, rel) if rel else ws


def git_status(repo: str) -> str:
    return _in_dir(repo, "git status -sb")


def git_fetch(repo: str) -> str:
    return _in_dir(repo, "git fetch --all --prune")


def git_pull(repo: str) -> str:
    return _in_dir(repo, "git pull --ff-only")


def git_push(repo: str) -> str:
    return _in_dir(repo, "git push")


def git_sync(repo: str) -> str:
    """VSCode-style sync: fast-forward pull then push (needs the injected key)."""
    return _in_dir(repo, "git pull --ff-only && git push")


def git_checkout(repo: str, ref: str) -> str:
    """Checkout a branch/tag. Raises ValueError on an unsafe ref."""
    if not is_valid_ref(ref):
        raise ValueError(f"unsafe git ref: {ref!r}")
    return _in_dir(repo, f"git checkout {shquote(ref)}")


def git_log(repo: str, n: int = 20) -> str:
    return _in_dir(repo, f"git log --oneline -{int(n)}")


def git_diff(repo: str) -> str:
    return _in_dir(repo, "git diff --stat")

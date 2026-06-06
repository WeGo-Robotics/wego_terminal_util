"""Build the repo tree model by merging the .repos definition (operator side)
with the robot's actual workspace state (``vcs export`` + ``vcs status``).

All functions here are pure (string in, model out) so the merge logic is
unit-testable without a network or a real robot.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import yaml


def _norm(path: str) -> str:
    """Canonicalize a repo path so defined/actual compare equal regardless of how
    vcstool prints it (``./src/x`` from a ``.`` scan vs a bare ``src/x``)."""
    p = (path or "").strip()
    if not p:
        return ""
    p = posixpath.normpath(p)  # ./src/x -> src/x, trailing slash removed, . stays .
    return p

# State classifications for a repo row.
PRESENT = "present"   # in both .repos and the robot
MISSING = "missing"   # defined in .repos but not yet on the robot (needs import)
EXTRA = "extra"       # on the robot but not in .repos


@dataclass
class RepoNode:
    path: str                       # workspace-relative path ("" = meta root)
    url: str = ""
    defined_version: str = ""       # version from .repos
    actual_branch: str = ""         # branch/ref actually checked out on the robot
    state: str = PRESENT            # PRESENT | MISSING | EXTRA
    dirty: bool = False             # working tree has uncommitted changes
    ahead: int = 0                  # commits ahead of upstream
    behind: int = 0                 # commits behind upstream
    changes: int = 0                # number of changed paths
    is_repo: bool = True            # False for a pure container root
    label: str = ""                 # display label (root node only)
    children: List["RepoNode"] = field(default_factory=list)


def parse_repos_yaml(text: str) -> Dict[str, dict]:
    """Parse a vcstool .repos / ``vcs export`` document into {path: {url, version}}.

    Returns {} on empty or malformed input (the caller falls back to actual-only).
    """
    if not text or not text.strip():
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    repos = data.get("repositories")
    if not isinstance(repos, dict):
        return {}
    out: Dict[str, dict] = {}
    for path, spec in repos.items():
        if not isinstance(spec, dict):
            continue
        out[str(path)] = {
            "url": str(spec.get("url", "")),
            "version": str(spec.get("version", "")),
            "type": str(spec.get("type", "git")),
        }
    return out


_STATUS_HEADER = re.compile(r"^===\s+(?P<path>.+?)\s+\((?P<type>[^)]+)\)\s*===")
# `## branch...upstream [ahead 1, behind 2]` (any field optional)
_BRANCH = re.compile(
    r"^##\s+(?P<branch>.+?)(?:\.\.\.(?P<up>\S+?))?(?:\s+\[(?P<track>[^\]]*)\])?\s*$"
)
_AHEAD = re.compile(r"ahead\s+(\d+)")
_BEHIND = re.compile(r"behind\s+(\d+)")


@dataclass
class StatusInfo:
    branch: str = ""
    dirty: bool = False
    ahead: int = 0
    behind: int = 0
    changes: int = 0  # number of changed paths (working tree + index)


def parse_status(text: str) -> Dict[str, StatusInfo]:
    """Parse ``vcs status . --nested`` output into {path: StatusInfo}.

    vcstool prints a ``=== <path> (git) ===`` header per repo, followed by
    ``git status -sb``-style lines: a ``## branch...upstream [ahead/behind]``
    line then one line per changed path.
    """
    result: Dict[str, StatusInfo] = {}
    cur: Optional[str] = None
    info = StatusInfo()

    def flush() -> None:
        if cur is not None:
            result[cur] = info

    for raw in (text or "").splitlines():
        m = _STATUS_HEADER.match(raw.strip())
        if m:
            flush()
            cur = m.group("path")
            info = StatusInfo()
            continue
        if cur is None:
            continue
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        mb = _BRANCH.match(line.strip())
        if mb:
            info.branch = mb.group("branch").strip()
            track = mb.group("track") or ""
            a = _AHEAD.search(track)
            b = _BEHIND.search(track)
            info.ahead = int(a.group(1)) if a else 0
            info.behind = int(b.group(1)) if b else 0
        else:
            # any non-empty, non-branch line under a repo = a changed path
            info.changes += 1
            info.dirty = True
    flush()
    return result


_URL_LINE = re.compile(r"^(git@|https?://|ssh://|git://)")


def parse_remote_urls(text: str) -> Dict[str, str]:
    """Parse ``vcs custom --git --args remote get-url origin`` output into
    {path: origin_url}. Same ``=== path (git) ===`` headers as status; the repo's
    output is its origin URL (or an error if no origin)."""
    result: Dict[str, str] = {}
    cur: Optional[str] = None
    for raw in (text or "").splitlines():
        m = _STATUS_HEADER.match(raw.strip())
        if m:
            cur = m.group("path")
            continue
        if cur is None:
            continue
        line = raw.strip()
        if not line:
            continue
        # take the first url-looking line as the origin remote
        if cur not in result and _URL_LINE.match(line):
            result[cur] = line
    return result


def build_tree(
    workspace_label: str,
    status_text: str = "",
    url_text: str = "",
    ws_name: str = "",
) -> RepoNode:
    """Build the repo tree from each repo's own git state (no .repos manifest).

    The repo set + branch/ahead-behind/changes come from
    ``vcs status --nested`` (``git status -sb`` per repo, which compares against
    each repo's configured upstream remote). The origin URL comes from
    ``git remote get-url origin``. If a repo matching the workspace root
    (``.`` or ``ws_name``) is found, the root node is the meta git repo itself.
    """
    statuses = {_norm(p): v for p, v in parse_status(status_text).items()}
    urls = {_norm(p): u for p, u in parse_remote_urls(url_text).items()}
    actual = set(statuses) | set(urls)

    meta_keys = {k for k in (".", _norm(ws_name)) if k}

    root = RepoNode(path="", url="", state=PRESENT, is_repo=False, label=workspace_label)
    meta_match = next((p for p in actual if p in meta_keys), "")
    if meta_match:
        root.is_repo = True
        st = statuses.get(meta_match, StatusInfo())
        root.actual_branch = st.branch
        root.dirty = st.dirty
        root.ahead = st.ahead
        root.behind = st.behind
        root.changes = st.changes
        root.url = urls.get(meta_match, "")

    for path in sorted(actual - meta_keys):
        st = statuses.get(path, StatusInfo())
        node = RepoNode(
            path=path,
            url=urls.get(path, ""),
            actual_branch=st.branch,
            ahead=st.ahead,
            behind=st.behind,
            changes=st.changes,
            state=PRESENT,
            dirty=st.dirty,
        )
        root.children.append(node)
    return root

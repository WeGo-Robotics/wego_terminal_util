"""Git-mode scope resolver.

Narrow the comparison candidate set to the union of tracked + changed files
across the root repo and every nested repo. Ignored files (.gitignore'd) never
enter the set, so they are never walked/stat'd/hashed.

Nested repos are found by scanning the tree for ``.git`` entries, so this
catches BOTH git submodules and independent clones laid out by tools like
vcstool (a ``.repos``-managed meta workspace), which are not submodules. The
workspace root itself need not be a git repo — if it only contains nested
repos, those are still used.

Runs against any FileSystem via ``fs.run_cmd`` — local uses subprocess, SFTP
uses ssh exec, so git-mode works identically for local and remote panes.
"""

from __future__ import annotations

import posixpath
from typing import Dict, List, Set

from ..fs.base import FileSystem


class GitNotAvailable(Exception):
    """No git repo found at the root or nested, or git is missing on target."""


# Directory names skipped during nested-repo discovery: build artifacts and
# package caches that never contain source repos but can be huge (esp. remote).
_PRUNE_DIRS = {
    "build", "install", "log", "node_modules", "__pycache__",
    ".cache", ".colcon", "devel", "logs",
}


class GitScopeResolver:
    def __init__(self, fs: FileSystem):
        self.fs = fs

    def resolve(self) -> Set[str]:
        """Return compare-root-relative posix paths in scope."""
        repos = self._discover_repos()
        if not repos:
            raise GitNotAvailable(
                f"{self.fs.label()}: no git repository found (root or nested)"
            )
        candidates: Set[str] = set()
        for repo_rel in repos:
            candidates |= self._files_for_repo(repo_rel)
        return candidates

    # ---- repo discovery ----
    def _is_work_tree(self, cwd: str = "") -> bool:
        rc, out, _err = self.fs.run_cmd(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=cwd
        )
        return rc == 0 and out.strip() == "true"

    def _discover_repos(self) -> List[str]:
        """Relative roots of every repo: root (if a repo), submodules, and any
        nested independent clone (vcstool-style)."""
        repos: Set[str] = set()
        if self._is_work_tree(""):
            repos.add("")
            repos |= self._submodules()
        # Scan for .git everywhere — catches submodules AND non-submodule clones.
        repos |= self._find_nested_repos()
        return sorted(repos)

    def _submodules(self) -> Set[str]:
        result: Set[str] = set()
        rc, out, _err = self.fs.run_cmd(
            ["git", "submodule", "status", "--recursive"]
        )
        if rc == 0:
            for line in out.splitlines():
                line = line.strip()
                if not line:
                    continue
                # Format: " <sha> <path> (<describe>)" — first char is status flag.
                parts = line.split()
                if len(parts) >= 2:
                    result.add(parts[1])
        else:
            result.update(self._parse_gitmodules())
        return result

    def _find_nested_repos(self) -> Set[str]:
        """BFS the tree; a dir containing a ``.git`` entry (dir or file) is a
        repo root. Descends through non-repo dirs and into repos (to find
        nested-in-nested), pruning known heavy/irrelevant directories."""
        found: Set[str] = set()
        stack = [""]
        while stack:
            d = stack.pop()
            dirs = []
            has_git = False
            for name, is_dir in self.fs.listdir(d):
                if name == ".git":
                    has_git = True
                elif is_dir:
                    dirs.append(name)
            if has_git:
                found.add(d)
            for name in dirs:
                if name in _PRUNE_DIRS:
                    continue
                stack.append(name if not d else d + "/" + name)
        return found

    def _parse_gitmodules(self) -> List[str]:
        rc, out, _err = self.fs.run_cmd(
            ["git", "config", "-f", ".gitmodules", "--get-regexp", "path"]
        )
        if rc != 0:
            return []
        paths = []
        for line in out.splitlines():
            # "submodule.<name>.path <path>"
            parts = line.split(None, 1)
            if len(parts) == 2:
                paths.append(parts[1].strip())
        return paths

    # ---- fast oid map (no content hashing) ----
    def resolve_oids(self) -> Dict[str, str]:
        """Map every in-scope relpath -> git blob oid (SHA-1 of content).

        For committed/unmodified files the oid comes from the index for free.
        Only working-tree-modified and untracked files are re-hashed, and that
        is done by ``git hash-object`` on the device itself — no file transfer.
        Comparing left vs right oids then needs no content reads at all.
        """
        repos = self._discover_repos()
        if not repos:
            raise GitNotAvailable(
                f"{self.fs.label()}: no git repository found (root or nested)"
            )
        out: Dict[str, str] = {}
        for repo_rel in repos:
            out.update(self._oids_for_repo(repo_rel))
        return out

    def _oids_for_repo(self, repo_rel: str) -> Dict[str, str]:
        oids: Dict[str, str] = {}

        # 1) index oids for all tracked files (cached by git — essentially free)
        rc, out, _err = self.fs.run_cmd(
            ["git", "-c", "core.quotepath=false", "ls-files", "-s"], cwd=repo_rel
        )
        if rc == 0:
            for line in out.splitlines():
                # "<mode> <oid> <stage>\t<path>"
                if "\t" not in line:
                    continue
                meta, path = line.split("\t", 1)
                parts = meta.split()
                if len(parts) >= 2 and path:
                    oids[path] = parts[1]

        # 2) working-tree changes: re-hash dirty + untracked, drop deleted
        dirty: List[str] = []
        rc, out, _err = self.fs.run_cmd(
            ["git", "-c", "core.quotepath=false", "status", "--porcelain", "-uall"],
            cwd=repo_rel,
        )
        if rc == 0:
            for line in out.splitlines():
                if len(line) < 4:
                    continue
                x, y = line[0], line[1]
                path = self._porcelain_path(line)
                if not path:
                    continue
                if x == "D" or y == "D":
                    oids.pop(path, None)
                else:
                    dirty.append(path)

        # 3) actual working-tree blob oid for changed files (git computes locally)
        for chunk in _chunks(dirty, 100):
            rc, out, _err = self.fs.run_cmd(
                ["git", "hash-object", "--"] + chunk, cwd=repo_rel
            )
            if rc != 0:
                continue
            results = out.splitlines()
            for path, oid in zip(chunk, results):
                oid = oid.strip()
                if oid:
                    oids[path] = oid

        return {self._lift(repo_rel, p): o for p, o in oids.items()}

    # ---- candidate files per repo ----
    def _files_for_repo(self, repo_rel: str) -> Set[str]:
        files: Set[str] = set()

        rc, out, _err = self.fs.run_cmd(["git", "ls-files"], cwd=repo_rel)
        if rc == 0:
            for line in out.splitlines():
                p = line.strip()
                if p:
                    files.add(self._lift(repo_rel, p))

        rc, out, _err = self.fs.run_cmd(
            ["git", "status", "--porcelain"], cwd=repo_rel
        )
        if rc == 0:
            for line in out.splitlines():
                p = self._porcelain_path(line)
                if p:
                    files.add(self._lift(repo_rel, p))
        return files

    @staticmethod
    def _porcelain_path(line: str) -> str:
        # "XY <path>" or "XY <old> -> <new>" (rename); skip the XY + space prefix.
        if len(line) < 4:
            return ""
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        return path.strip().strip('"')

    @staticmethod
    def _lift(repo_rel: str, path: str) -> str:
        return posixpath.join(repo_rel, path) if repo_rel else path


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]

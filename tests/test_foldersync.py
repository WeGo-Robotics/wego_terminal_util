"""Unit tests for foldersync (no Tk, no network)."""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from foldersync.compare.engine import CompareEngine
from foldersync.compare.result import DiffStatus
from foldersync.fs.local_fs import LocalFileSystem
from foldersync.gitscope.resolver import GitScopeResolver
from foldersync.sync.copier import SyncCopier


def write(path, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


class LocalFsTest(unittest.TestCase):
    def test_walk_stat_hash(self):
        with tempfile.TemporaryDirectory() as d:
            write(os.path.join(d, "a.txt"), b"hello")
            write(os.path.join(d, "sub", "b.txt"), b"world")
            fs = LocalFileSystem(d)
            rels = sorted(e.relpath for e in fs.walk())
            self.assertEqual(rels, ["a.txt", "sub/b.txt"])
            st = fs.stat("a.txt")
            self.assertEqual(st.size, 5)
            self.assertFalse(st.is_dir)
            self.assertIsNone(fs.stat("missing"))
            import hashlib
            self.assertEqual(fs.hash_file("a.txt"), hashlib.sha256(b"hello").hexdigest())


class HashSpy(LocalFileSystem):
    """LocalFileSystem that counts hash_file calls."""

    def __init__(self, root):
        super().__init__(root)
        self.hash_calls = 0

    def hash_file(self, relpath, algo="sha256"):
        self.hash_calls += 1
        return super().hash_file(relpath, algo)


class CompareTest(unittest.TestCase):
    def test_classify(self):
        with tempfile.TemporaryDirectory() as l, tempfile.TemporaryDirectory() as r:
            write(os.path.join(l, "same.txt"), b"abc")
            write(os.path.join(r, "same.txt"), b"abc")
            write(os.path.join(l, "diffsize.txt"), b"aa")
            write(os.path.join(r, "diffsize.txt"), b"aaaa")
            write(os.path.join(l, "samesize.txt"), b"xyz")
            write(os.path.join(r, "samesize.txt"), b"xyZ")
            write(os.path.join(l, "leftonly.txt"), b"L")
            write(os.path.join(r, "rightonly.txt"), b"R")

            lfs, rfs = HashSpy(l), HashSpy(r)
            report = CompareEngine(lfs, rfs).compare()
            status = {p.relpath: p.status for p in report.pairs}
            self.assertEqual(status["same.txt"], DiffStatus.SAME)
            self.assertEqual(status["diffsize.txt"], DiffStatus.DIFFERENT)
            self.assertEqual(status["samesize.txt"], DiffStatus.DIFFERENT)
            self.assertEqual(status["leftonly.txt"], DiffStatus.LEFT_ONLY)
            self.assertEqual(status["rightonly.txt"], DiffStatus.RIGHT_ONLY)

            # hash only called on size ties (same.txt, samesize.txt) — 2 each side
            self.assertEqual(lfs.hash_calls, 2)
            self.assertEqual(rfs.hash_calls, 2)


class CopyTest(unittest.TestCase):
    def test_copy_then_same(self):
        with tempfile.TemporaryDirectory() as l, tempfile.TemporaryDirectory() as r:
            write(os.path.join(l, "deep", "x.txt"), b"payload")
            lfs, rfs = LocalFileSystem(l), LocalFileSystem(r)
            SyncCopier().copy(lfs, rfs, "deep/x.txt")
            self.assertEqual(rfs.stat("deep/x.txt").size, 7)
            report = CompareEngine(lfs, rfs).compare()
            self.assertEqual(report.pairs[0].status, DiffStatus.SAME)


def git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True,
                   capture_output=True, text=True)


class GitScopeTest(unittest.TestCase):
    def test_scope_excludes_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            git(["init", "-q"], d)
            git(["config", "user.email", "t@t"], d)
            git(["config", "user.name", "t"], d)
            write(os.path.join(d, ".gitignore"), b"ignored.txt\n")
            write(os.path.join(d, "tracked.txt"), b"t")
            write(os.path.join(d, "ignored.txt"), b"i")
            git(["add", "tracked.txt", ".gitignore"], d)
            git(["commit", "-qm", "init"], d)
            # modify tracked + add an untracked file
            write(os.path.join(d, "tracked.txt"), b"modified")
            write(os.path.join(d, "new.txt"), b"n")

            scope = GitScopeResolver(LocalFileSystem(d)).resolve()
            self.assertIn("tracked.txt", scope)
            self.assertIn(".gitignore", scope)
            self.assertIn("new.txt", scope)       # untracked, not ignored
            self.assertNotIn("ignored.txt", scope)  # .gitignore'd

    def test_vcstool_meta_root_not_a_repo(self):
        # vcstool layout: workspace root is NOT a git repo; it contains
        # independent clones (not submodules) under src/.
        with tempfile.TemporaryDirectory() as ws:
            repo_a = os.path.join(ws, "src", "pkg_a")
            repo_b = os.path.join(ws, "src", "pkg_b")
            for repo, fname in ((repo_a, "a.py"), (repo_b, "b.py")):
                os.makedirs(repo)
                git(["init", "-q"], repo)
                git(["config", "user.email", "t@t"], repo)
                git(["config", "user.name", "t"], repo)
                write(os.path.join(repo, fname), b"x")
                git(["add", fname], repo)
                git(["commit", "-qm", "init"], repo)
            # a loose, non-repo file in the workspace must be excluded
            write(os.path.join(ws, "src", "notes.txt"), b"loose")
            # a build artifact dir must be pruned (not scanned)
            write(os.path.join(ws, "build", "junk.o"), b"o")

            scope = GitScopeResolver(LocalFileSystem(ws)).resolve()
            self.assertIn("src/pkg_a/a.py", scope)
            self.assertIn("src/pkg_b/b.py", scope)
            self.assertNotIn("src/notes.txt", scope)  # not tracked by any repo
            self.assertNotIn("build/junk.o", scope)


class GitOidCompareTest(unittest.TestCase):
    def test_compare_by_oid(self):
        with tempfile.TemporaryDirectory() as base:
            left = os.path.join(base, "left")
            os.makedirs(left)
            git(["init", "-q"], left)
            git(["config", "user.email", "t@t"], left)
            git(["config", "user.name", "t"], left)
            write(os.path.join(left, "keep.txt"), b"identical")
            write(os.path.join(left, "edit.txt"), b"original")
            git(["add", "."], left)
            git(["commit", "-qm", "init"], left)

            # right = clone at same commit -> all oids identical
            right = os.path.join(base, "right")
            git(["clone", "-q", left, right], base)
            git(["config", "user.email", "t@t"], right)
            git(["config", "user.name", "t"], right)

            # diverge working trees without committing
            write(os.path.join(right, "edit.txt"), b"changed-content")  # DIFFERENT
            write(os.path.join(left, "untracked.txt"), b"new")          # LEFT_ONLY

            lfs, rfs = HashSpy(left), HashSpy(right)
            lo = GitScopeResolver(lfs).resolve_oids()
            ro = GitScopeResolver(rfs).resolve_oids()
            report = CompareEngine(lfs, rfs).compare_oids(lo, ro)
            status = {p.relpath: p.status for p in report.pairs}

            self.assertEqual(status["keep.txt"], DiffStatus.SAME)
            self.assertEqual(status["edit.txt"], DiffStatus.DIFFERENT)
            self.assertEqual(status["untracked.txt"], DiffStatus.LEFT_ONLY)
            # no content hashing happened — oids came from git
            self.assertEqual(lfs.hash_calls, 0)
            self.assertEqual(rfs.hash_calls, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

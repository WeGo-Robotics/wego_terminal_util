"""Unit tests for vcsupdate (no Tk, no network)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko

from vcsupdate.core import commands, credential, repolist
from vcsupdate.core.runner import split_lines


class CommandsTest(unittest.TestCase):
    def test_workspace_commands(self):
        self.assertEqual(commands.vcs_export("/home/ws"), "cd /home/ws && vcs export . --exact")
        self.assertEqual(commands.vcs_status("/home/ws"), "cd /home/ws && vcs status . --nested")
        self.assertEqual(
            commands.vcs_status_short("/home/ws"),
            "cd /home/ws && vcs custom . --nested --git --args status -sb",
        )
        self.assertEqual(
            commands.vcs_pull("/home/ws", 4),
            "cd /home/ws && vcs pull . --nested --workers 4",
        )
        self.assertEqual(
            commands.vcs_import_stdin("/home/ws", "src", 8),
            "cd /home/ws && vcs import src --workers 8",
        )
        self.assertEqual(
            commands.vcs_import_stdin("/home/ws", "", 8),
            "cd /home/ws && vcs import . --workers 8",
        )

    def test_path_with_spaces_is_quoted(self):
        cmd = commands.vcs_status("/home/my ws")
        self.assertIn("'/home/my ws'", cmd)

    def test_repo_dir(self):
        self.assertEqual(commands.repo_dir("/ws", "src/pkg_a"), "/ws/src/pkg_a")
        self.assertEqual(commands.repo_dir("/ws", ""), "/ws")

    def test_git_commands(self):
        self.assertEqual(commands.git_pull("/ws/src/a"), "cd /ws/src/a && git pull --ff-only")
        self.assertEqual(commands.git_push("/ws/src/a"), "cd /ws/src/a && git push")
        self.assertEqual(commands.git_fetch("/ws/src/a"), "cd /ws/src/a && git fetch --all --prune")
        self.assertEqual(commands.git_sync("/ws/src/a"), "cd /ws/src/a && git pull --ff-only && git push")

    def test_checkout_ref_validation(self):
        self.assertTrue(commands.is_valid_ref("main"))
        self.assertTrue(commands.is_valid_ref("release/1.2.0"))
        self.assertTrue(commands.is_valid_ref("v1.0"))
        self.assertFalse(commands.is_valid_ref(""))
        self.assertFalse(commands.is_valid_ref("-x"))
        self.assertFalse(commands.is_valid_ref("a; rm -rf /"))
        self.assertFalse(commands.is_valid_ref("a b"))
        self.assertFalse(commands.is_valid_ref("a..b"))
        self.assertFalse(commands.is_valid_ref("$(whoami)"))

    def test_git_checkout_rejects_unsafe_ref(self):
        with self.assertRaises(ValueError):
            commands.git_checkout("/ws/src/a", "a; rm -rf /")
        self.assertEqual(
            commands.git_checkout("/ws/src/a", "main"),
            "cd /ws/src/a && git checkout main",
        )

    def test_with_cred_prefixes_git_ssh(self):
        wrapped = commands.with_cred("cd /ws && vcs pull .", "ssh -i /dev/shm/x/id")
        self.assertTrue(wrapped.startswith("export GIT_SSH_COMMAND="))
        self.assertIn("'ssh -i /dev/shm/x/id'", wrapped)
        self.assertIn("; cd /ws && vcs pull .", wrapped)

    def test_with_cred_noop_when_empty(self):
        self.assertEqual(commands.with_cred("cd /ws && git status", ""), "cd /ws && git status")


class CredentialTest(unittest.TestCase):
    def test_load_and_check_unencrypted(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "key")
            paramiko.RSAKey.generate(2048).write_private_key_file(path)
            fp, err = credential.load_and_check(path)
            self.assertEqual(err, "")
            self.assertTrue(fp)

    def test_load_and_check_encrypted_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "key")
            paramiko.RSAKey.generate(2048).write_private_key_file(path, password="secret")
            fp, err = credential.load_and_check(path)
            self.assertIsNone(fp)
            self.assertIn("passphrase", err)

    def test_load_and_check_missing(self):
        fp, err = credential.load_and_check("")
        self.assertIsNone(fp)
        self.assertTrue(err)

    def test_git_ssh_command_format(self):
        cred = credential.Credential(local_path="k", fingerprint="ab",
                                     remote_dir="/dev/shm/vcsupdate-xx",
                                     remote_key="/dev/shm/vcsupdate-xx/id")
        cmd = credential.git_ssh_command(cred)
        self.assertIn("-i /dev/shm/vcsupdate-xx/id", cmd)
        self.assertIn("IdentitiesOnly=yes", cmd)
        self.assertIn("StrictHostKeyChecking=accept-new", cmd)
        self.assertIn("BatchMode=yes", cmd)


SAMPLE_REPOS = """\
repositories:
  src/pkg_a:
    type: git
    url: git@github.com:org/pkg_a.git
    version: main
  src/pkg_b:
    type: git
    url: git@github.com:org/pkg_b.git
    version: devel
"""

# Robot reality: pkg_a present, pkg_b absent, pkg_c extra (not in .repos).
SAMPLE_EXPORT = """\
repositories:
  src/pkg_a:
    type: git
    url: git@github.com:org/pkg_a.git
    version: abc123
  src/pkg_c:
    type: git
    url: git@github.com:org/pkg_c.git
    version: def456
"""

SAMPLE_STATUS = """\
=== src/pkg_a (git) ===
## main...origin/main
 M src/pkg_a/file.py
=== src/pkg_c (git) ===
## feature...origin/feature
"""


class RepoListParseTest(unittest.TestCase):
    def test_parse_repos_yaml(self):
        d = repolist.parse_repos_yaml(SAMPLE_REPOS)
        self.assertEqual(set(d), {"src/pkg_a", "src/pkg_b"})
        self.assertEqual(d["src/pkg_a"]["version"], "main")

    def test_parse_repos_empty_and_malformed(self):
        self.assertEqual(repolist.parse_repos_yaml(""), {})
        self.assertEqual(repolist.parse_repos_yaml("not: a repos doc"), {})
        self.assertEqual(repolist.parse_repos_yaml(": : :"), {})

    def test_parse_status(self):
        st = repolist.parse_status(SAMPLE_STATUS)
        self.assertEqual(st["src/pkg_a"].branch, "main")
        self.assertTrue(st["src/pkg_a"].dirty)
        self.assertEqual(st["src/pkg_c"].branch, "feature")
        self.assertFalse(st["src/pkg_c"].dirty)

    def test_parse_status_ahead_behind(self):
        text = (
            "=== src/a (git) ===\n"
            "## main...origin/main [ahead 2, behind 3]\n"
            " M a.py\n"
            "?? b.py\n"
            "=== src/b (git) ===\n"
            "## dev...origin/dev [ahead 1]\n"
            "=== src/c (git) ===\n"
            "## main...origin/main\n"
        )
        st = repolist.parse_status(text)
        self.assertEqual((st["src/a"].ahead, st["src/a"].behind, st["src/a"].changes), (2, 3, 2))
        self.assertEqual((st["src/b"].ahead, st["src/b"].behind), (1, 0))
        self.assertEqual((st["src/c"].ahead, st["src/c"].behind, st["src/c"].changes), (0, 0, 0))

    def test_parse_status_branch_with_dot(self):
        st = repolist.parse_status("=== src/a (git) ===\n## v1.2...origin/v1.2 [behind 1]\n")
        self.assertEqual(st["src/a"].branch, "v1.2")
        self.assertEqual(st["src/a"].behind, 1)


class RepoListMergeTest(unittest.TestCase):
    # SAMPLE_REPOS keys already carry the src/ prefix, so disable prefixing here.
    def test_present_missing_extra(self):
        root = repolist.build_tree(
            "robot:/ws", SAMPLE_REPOS, SAMPLE_EXPORT, SAMPLE_STATUS, import_prefix="",
        )
        by_path = {n.path: n for n in root.children}
        self.assertEqual(by_path["src/pkg_a"].state, repolist.PRESENT)
        self.assertEqual(by_path["src/pkg_b"].state, repolist.MISSING)
        self.assertEqual(by_path["src/pkg_c"].state, repolist.EXTRA)

    def test_status_boost(self):
        root = repolist.build_tree("robot:/ws", SAMPLE_REPOS, SAMPLE_EXPORT, SAMPLE_STATUS, import_prefix="")
        by_path = {n.path: n for n in root.children}
        self.assertEqual(by_path["src/pkg_a"].actual_branch, "main")
        self.assertTrue(by_path["src/pkg_a"].dirty)
        self.assertFalse(by_path["src/pkg_c"].dirty)

    def test_defined_version_preserved(self):
        root = repolist.build_tree("robot:/ws", SAMPLE_REPOS, SAMPLE_EXPORT, SAMPLE_STATUS, import_prefix="")
        by_path = {n.path: n for n in root.children}
        self.assertEqual(by_path["src/pkg_a"].defined_version, "main")
        self.assertEqual(by_path["src/pkg_b"].defined_version, "devel")

    def test_no_repos_file_falls_back_to_export(self):
        root = repolist.build_tree("robot:/ws", "", SAMPLE_EXPORT, "", import_prefix="")
        states = {n.path: n.state for n in root.children}
        # everything on the robot is "extra" when there is no definition
        self.assertEqual(states["src/pkg_a"], repolist.EXTRA)
        self.assertEqual(states["src/pkg_c"], repolist.EXTRA)


# Real-world scenario: bare .repos keys, repos imported under src/, meta repo is
# itself a git repo, sub-repos found via `vcs status --nested`.
BARE_REPOS = """\
repositories:
  radius-core:
    type: git
    url: git@github.com:org/radius-core.git
    version: main
  radius-piper:
    type: git
    url: git@github.com:org/radius-piper.git
    version: main
"""

# vcstool prints paths with a ./ prefix when the scan root is "." — defined keys
# (src/radius-core) must still match these (./src/radius-core).
NESTED_STATUS = """\
=== ./. (git) ===
## main
=== ./src/radius-core (git) ===
## main...origin/main [ahead 1, behind 2]
 M ./src/radius-core/x.py
=== ./src/radius-extra (git) ===
## dev
"""


class PrefixMetaMergeTest(unittest.TestCase):
    def test_prefix_matches_defined_to_actual(self):
        root = repolist.build_tree(
            "robot:radius-posco-ws", BARE_REPOS, "", NESTED_STATUS,
            import_prefix="src", ws_name="radius-posco-ws",
        )
        by_path = {n.path: n for n in root.children}
        # defined radius-core -> src/radius-core matches the nested status repo
        self.assertEqual(by_path["src/radius-core"].state, repolist.PRESENT)
        self.assertTrue(by_path["src/radius-core"].dirty)
        self.assertEqual(by_path["src/radius-core"].ahead, 1)
        self.assertEqual(by_path["src/radius-core"].behind, 2)
        self.assertEqual(by_path["src/radius-core"].changes, 1)
        # defined but not on robot
        self.assertEqual(by_path["src/radius-piper"].state, repolist.MISSING)
        # on robot but not defined
        self.assertEqual(by_path["src/radius-extra"].state, repolist.EXTRA)

    def test_meta_repo_detected_as_root(self):
        root = repolist.build_tree(
            "robot:radius-posco-ws", BARE_REPOS, "", NESTED_STATUS,
            import_prefix="src", ws_name="radius-posco-ws",
        )
        self.assertTrue(root.is_repo)              # root is the meta git repo
        self.assertEqual(root.actual_branch, "main")
        # the "." meta entry is not duplicated as a child
        self.assertNotIn(".", {n.path for n in root.children})
        self.assertNotIn("radius-posco-ws", {n.path for n in root.children})


class SplitLinesTest(unittest.TestCase):
    def test_complete_lines(self):
        lines, rem = split_lines(b"a\nb\nc\n")
        self.assertEqual(lines, ["a", "b", "c"])
        self.assertEqual(rem, b"")

    def test_partial_line_kept(self):
        lines, rem = split_lines(b"a\nb\npar")
        self.assertEqual(lines, ["a", "b"])
        self.assertEqual(rem, b"par")

    def test_no_newline_keeps_all(self):
        lines, rem = split_lines(b"partial")
        self.assertEqual(lines, [])
        self.assertEqual(rem, b"partial")

    def test_carriage_return_progress(self):
        # git progress uses \r — treat as line break so progress shows live
        lines, rem = split_lines(b"50%\r100%\r")
        self.assertEqual(lines, ["50%", "100%"])
        self.assertEqual(rem, b"")

    def test_crlf(self):
        lines, rem = split_lines(b"x\r\ny\r\n")
        self.assertEqual(lines, ["x", "y"])


if __name__ == "__main__":
    unittest.main()

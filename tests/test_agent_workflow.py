"""Tests for the agent-workflow plugin: git_preflight.py, in a scratch repository with a scratch upstream."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PRE = Path(__file__).resolve().parents[1] / "plugins" / "agent-workflow" / "skills" / "multi-session-git" \
    / "scripts" / "git_preflight.py"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=ENV).stdout


class Preflight(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.upstream, self.repo = self.tmp / "up.git", self.tmp / "work"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.upstream)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.upstream), str(self.repo)], check=True, capture_output=True)
        git(self.repo, "checkout", "-q", "-b", "main")
        for name in ("mine.txt", "theirs.txt"):
            (self.repo / name).write_text("v1\n")
        git(self.repo, "add", "mine.txt", "theirs.txt")
        git(self.repo, "commit", "-q", "-m", "init")
        git(self.repo, "push", "-q", "-u", "origin", "main")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def preflight(self, *mine, cwd=None):
        r = subprocess.run([sys.executable, str(PRE), "--repo", str(self.repo), "--json", "--mine", *mine],
                           capture_output=True, text=True, cwd=cwd or self.repo, env=ENV)
        return r.returncode, json.loads(r.stdout)

    def msgs(self, rep, level):
        return [i["message"] for i in rep["issues"] if i["level"] == level]

    def test_only_my_change_is_clean(self):
        (self.repo / "mine.txt").write_text("v2\n")
        code, rep = self.preflight("mine.txt")
        self.assertEqual(code, 0, rep)
        self.assertEqual(self.msgs(rep, "error") + self.msgs(rep, "warning"), [])

    def test_someone_elses_edit_is_flagged_as_live_and_not_mine(self):
        (self.repo / "mine.txt").write_text("v2\n")
        (self.repo / "theirs.txt").write_text("half-finished\n")
        code, rep = self.preflight("mine.txt")
        warnings = " | ".join(self.msgs(rep, "warning"))
        self.assertEqual(code, 0)
        self.assertIn("not yours, leave it: theirs.txt", warnings)
        self.assertIn("another session is probably editing now", warnings)

    def test_staging_someone_elses_file_is_an_error(self):
        (self.repo / "mine.txt").write_text("v2\n")
        (self.repo / "theirs.txt").write_text("half-finished\n")
        git(self.repo, "add", "-A")  # the classic mistake
        code, rep = self.preflight("mine.txt")
        self.assertEqual(code, 1)
        self.assertTrue(any("staged but not yours: theirs.txt" in e for e in self.msgs(rep, "error")))

    def test_a_directory_in_mine_covers_its_files(self):
        # Found by running the preflight on its own commit: a new plugin directory's files were reported as
        # "not yours, another session is editing".
        (self.repo / "pkg" / "sub").mkdir(parents=True)
        (self.repo / "pkg" / "sub" / "new.py").write_text("x\n")
        (self.repo / "pkgother.txt").write_text("not under pkg/\n")
        code, rep = self.preflight("pkg")
        warnings = " | ".join(self.msgs(rep, "warning"))
        self.assertEqual(code, 0)
        self.assertNotIn("pkg/sub/new.py", warnings)
        self.assertIn("pkgother.txt", warnings)  # a sibling that merely shares the prefix is not covered

    def test_old_edits_are_not_called_live(self):
        (self.repo / "theirs.txt").write_text("old change\n")
        past = time.time() - 3600
        os.utime(self.repo / "theirs.txt", (past, past))
        _, rep = self.preflight("mine.txt")
        self.assertFalse(any("editing now" in w for w in self.msgs(rep, "warning")))

    def test_behind_upstream_is_an_error(self):
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.upstream), str(other)], check=True, capture_output=True)
        (other / "new.txt").write_text("x\n")
        git(other, "add", "new.txt")
        git(other, "commit", "-q", "-m", "elsewhere")
        git(other, "push", "-q")
        code, rep = self.preflight()
        self.assertEqual(code, 1)
        self.assertTrue(any("behind origin/main" in e for e in self.msgs(rep, "error")))

    def test_same_branch_in_another_worktree_is_flagged(self):
        git(self.repo, "branch", "side")
        git(self.repo, "worktree", "add", "-q", str(self.tmp / "wt"), "side")
        git(self.tmp / "wt", "checkout", "-q", "--detach")
        git(self.repo, "worktree", "add", "-q", "--force", str(self.tmp / "wt2"), "main")
        _, rep = self.preflight()
        self.assertTrue(any("also checked out" in w for w in self.msgs(rep, "warning")))

    def test_not_a_repo_exits_2(self):
        r = subprocess.run([sys.executable, str(PRE), "--repo", str(self.tmp)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()

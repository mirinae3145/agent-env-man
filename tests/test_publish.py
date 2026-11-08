"""Publication uses local Git remotes and never touches user repositories."""
from process_support import run_hidden

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man.cli import main
from agent_env_man.git_source import Git
from agent_env_man.model import Error


class Publication(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aem-publish-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        environment = patch.dict(os.environ, {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                                              "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                                              "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"})
        environment.start()
        self.addCleanup(environment.stop)
        self.remote = self.root / "remote.git"
        self.git(self.root, "init", "--bare", "-b", "main", self.remote)
        self.seed = self.root / "seed"
        self.git(self.root, "clone", self.remote, self.seed)
        (self.seed / "skill").mkdir()
        (self.seed / "skill/SKILL.md").write_text("# Skill\n", encoding="utf-8")
        (self.seed / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
        self.commit(self.seed)
        self.git(self.seed, "push", "origin", "main")
        self.catalog = self.root / "catalog.toml"
        self.document = {'version': 2, 'sources': {'shared': {'type': 'git', 'repository': str(self.remote)}}, 'skills': {'one': {'subdir': 'skill', 'source': 'shared', 'install': {'mode': 'copy'}}, 'two': {'subdir': 'skill', 'source': 'shared', 'install': {'mode': 'copy'}}}, 'instructions': {'personal': {'entry': 'AGENTS.md', 'source': 'shared', 'install': {'entry': {'root': 'agent', 'destination': 'AGENTS.md'}}}}}
        self.document['payload'] = {'defaults': {'permissions': 'strict', 'exclude': []}}
        self.catalog.write_text(tomlkit.dumps(self.document), encoding="utf-8")
        self.config = self.root / "machine.toml"
        self.cli("bootstrap", self.catalog, "--checkout-root", self.root / "checkouts",
                 "--root", f"skills={self.root / 'installed'}", "--root", f"agent={self.root / 'agent'}")
        self.checkout = self.root / "checkouts/.aem-repositories/shared"

    def git(self, path, *args):
        result = run_hidden(["git", "-C", str(path), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, path):
        self.git(path, "add", "-A")
        self.git(path, "commit", "-m", "Test change")

    def cli(self, *args, code=0):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = main(["--json", "--config", str(self.config), *map(str, args)])
        self.assertEqual(result, code, output.getvalue() + errors.getvalue())
        return json.loads(output.getvalue()) if output.getvalue() else errors.getvalue()

    def edit(self, path=None):
        (path or self.checkout).joinpath("skill/SKILL.md").write_text("# Edited\n", encoding="utf-8")

    def test_preview_groups_all_consumers_and_preserves_index_and_state_offline(self):
        self.edit()
        (self.checkout / "unrelated.txt").write_text("Untracked\n", encoding="utf-8")
        self.git(self.checkout, "add", "skill/SKILL.md")
        index = (self.checkout / ".git/index").read_bytes()
        state = self.root / "machine.toml.state/state.json"
        previous = state.read_bytes()
        self.remote.rename(self.root / "offline.git")
        with patch.object(Git, "fetch", side_effect=AssertionError("preview fetched")):
            report = self.cli("publish", "one", "two", "--dry-run")
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["members"], ["one", "personal", "two"])
        self.assertIn("unrelated.txt", report[0]["changes"])
        self.assertIn("+# Edited", report[0]["diff"])
        self.assertEqual((self.checkout / ".git/index").read_bytes(), index)
        self.assertEqual(state.read_bytes(), previous)

    def test_commit_and_push_whole_checkout_once_including_unrelated_files(self):
        self.edit()
        (self.checkout / "unrelated.txt").write_text("Included\n", encoding="utf-8")
        initial = self.git(self.remote, "rev-list", "--count", "main")
        result = self.cli("publish", "one", "two", "personal", "-m", "Publish edits")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "published")
        self.assertEqual(self.git(self.remote, "rev-list", "--count", "main"), str(int(initial) + 1))
        self.assertEqual(self.git(self.remote, "show", "main:unrelated.txt"), "Included")
        self.assertEqual(self.git(self.remote, "log", "-1", "--format=%s"), "Publish edits")
        self.assertEqual(self.git(self.checkout, "status", "--porcelain"), "")
        self.assertEqual(self.cli("update", "one")[0]["status"], "updated")

    def test_existing_commits_push_without_message_and_retry_is_idempotent(self):
        self.edit()
        self.commit(self.checkout)
        review = self.cli("publish", "personal", "--dry-run")[0]
        self.assertEqual(len(review["commits"]), 1)
        head = self.git(self.checkout, "rev-parse", "HEAD")
        for _ in range(2):
            self.assertEqual(self.cli("publish", "personal")[0]["revision"], head)
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), head)

    def test_empty_remote_first_push_commits_and_existing_history(self):
        for message in (None, "Initial publication"):
            with self.subTest(message=message):
                self.git(self.remote, "update-ref", "-d", "refs/heads/main")
                if message:
                    self.edit()
                    (self.checkout / "new.txt").write_text("New", encoding="utf-8")
                args = ("-m", message) if message else ()
                result = self.cli("publish", "one", *args)[0]
                self.assertTrue(result["initial_publish"])
                self.assertEqual(result["status"], "published")
                self.assertEqual(self.git(self.remote, "rev-parse", "main"),
                                 self.git(self.checkout, "rev-parse", "HEAD"))
                self.assertEqual(self.git(self.remote, "for-each-ref", "--format=%(refname)"), "refs/heads/main")
                self.assertEqual(self.cli("publish", "one")[0]["status"], "published")

    def test_missing_branch_in_populated_remote_does_not_commit_or_push(self):
        for ref in ("refs/heads/other", "refs/tags/only-tag"):
            with self.subTest(ref=ref):
                head = self.git(self.remote, "rev-parse", "main")
                self.git(self.remote, "update-ref", ref, head)
                self.git(self.remote, "update-ref", "-d", "refs/heads/main")
                self.edit()
                index = (self.checkout / ".git/index").read_bytes()
                result = self.cli("publish", "one", "-m", "Must not commit", code=1)[0]
                self.assertIn("remote is not empty", result["error"])
                self.assertEqual((self.checkout / ".git/index").read_bytes(), index)
                self.assertEqual(self.git(self.remote, "for-each-ref", "--format=%(refname)"), ref)
                self.git(self.remote, "update-ref", "refs/heads/main", head)
                self.git(self.remote, "update-ref", "-d", ref)

    def test_remote_listing_and_fetch_errors_never_fall_back_to_push(self):
        self.edit()
        head = self.git(self.checkout, "rev-parse", "HEAD")
        index = (self.checkout / ".git/index").read_bytes()
        run = Git.run
        for command in ("ls-remote", "fetch"):
            with self.subTest(command=command):
                def fail(git, path, *args, **kwargs):
                    if command in args:
                        raise Error("Authentication or network failure")
                    if "push" in args:
                        self.fail("Push attempted after remote inspection failure")
                    return run(git, path, *args, **kwargs)
                with patch.object(Git, "run", new=fail):
                    result = self.cli("publish", "one", "-m", "Must not commit", code=1)[0]
                self.assertIn("Authentication or network failure", result["error"])
                self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), head)
                self.assertEqual((self.checkout / ".git/index").read_bytes(), index)

    def test_dirty_without_message_fails_without_staging(self):
        self.edit()
        before = (self.checkout / ".git/index").read_bytes()
        with patch.object(Git, "fetch", side_effect=AssertionError("unnecessary fetch")):
            result = self.cli("publish", "one", code=1)[0]
        self.assertIn("--message", result["error"])
        self.assertEqual((self.checkout / ".git/index").read_bytes(), before)

    def test_behind_and_diverged_preserve_local_work(self):
        self.edit(self.seed)
        self.commit(self.seed)
        self.git(self.seed, "push", "origin", "main")
        (self.checkout / "local.txt").write_text("Local\n", encoding="utf-8")
        head = self.git(self.checkout, "rev-parse", "HEAD")
        result = self.cli("publish", "one", "-m", "Must not commit", code=1)[0]
        self.assertIn("behind", result["error"])
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), head)
        self.assertEqual(self.git(self.checkout, "diff", "--cached"), "")
        self.commit(self.checkout)
        result = self.cli("publish", "one", code=1)[0]
        self.assertIn("diverged", result["error"])

    def test_remote_failure_before_commit_preserves_changes(self):
        self.edit()
        head = self.git(self.checkout, "rev-parse", "HEAD")
        self.remote.rename(self.root / "offline.git")
        self.cli("publish", "one", "-m", "Not committed", code=1)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), head)
        self.assertEqual(self.git(self.checkout, "diff", "--cached"), "")

    def test_push_failure_keeps_commit_for_retry(self):
        self.edit()
        self.git(self.remote, "config", "receive.denyCurrentBranch", "refuse")
        # A non-bare receiver refuses updating its checked-out branch on every OS.
        self.git(self.remote, "config", "core.bare", "false")
        result = self.cli("publish", "one", "-m", "Retained", code=1)[0]
        head = self.git(self.checkout, "rev-parse", "HEAD")
        self.assertEqual(result["created_commit"], head)
        self.assertNotEqual(self.git(self.remote, "rev-parse", "main"), head)
        self.git(self.remote, "config", "core.bare", "true")
        self.assertEqual(self.cli("publish", "one")[0]["revision"], head)

    def test_wrong_branch_and_unfinished_operation_are_rejected(self):
        self.git(self.checkout, "checkout", "-b", "other")
        self.assertIn("expected attached branch", self.cli("publish", "one", code=1)[0]["error"])
        self.git(self.checkout, "checkout", "main")
        (self.checkout / ".git/MERGE_HEAD").write_text(self.git(self.checkout, "rev-parse", "HEAD") + "\n")
        self.assertIn("unfinished", self.cli("publish", "one", code=1)[0]["error"])

    def test_push_configuration_cannot_publish_other_branches_or_tags(self):
        self.edit()
        self.commit(self.checkout)
        self.git(self.checkout, "branch", "other")
        self.git(self.checkout, "tag", "-a", "private-tag", "-m", "Private")
        self.git(self.checkout, "config", "push.followTags", "true")
        self.git(self.checkout, "config", "remote.origin.mirror", "true")
        self.cli("publish", "one")
        refs = self.git(self.remote, "for-each-ref", "--format=%(refname)")
        self.assertEqual(refs, "refs/heads/main")

    def test_external_and_unknown_names_are_not_reported_as_published(self):
        external = self.root / "external"
        external.mkdir()
        (external / "AGENTS.md").write_text("# External\n", encoding="utf-8")
        self.document['sources'].update({'documents': {'type': 'external'}})
        self.document['instructions']['external'] = {'entry': 'AGENTS.md', 'source': 'documents', 'install': {'entry': {'root': 'agent', 'destination': 'EXTERNAL.md'}}}
        self.catalog.write_text(tomlkit.dumps(self.document), encoding="utf-8")
        self.cli("bootstrap", "--external", f"documents={external}")
        result = self.cli("publish", "one", "external")
        self.assertEqual([r["status"] for r in result], ["published", "published"])
        self.assertFalse(result[1]['transport_complete'])
        self.assertIn("known", self.cli("publish", "missing", code=1))

    def test_ignored_files_are_not_added_and_empty_message_is_rejected(self):
        (self.checkout / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        (self.checkout / "ignored.txt").write_text("Ignore\n", encoding="utf-8")
        self.assertIn("empty", self.cli("publish", "one", "-m", " ", code=1))
        self.cli("publish", "one", "-m", "Ignore file")
        self.assertNotIn("ignored.txt", self.git(self.remote, "ls-tree", "-r", "--name-only", "main").splitlines())


if __name__ == "__main__":
    unittest.main()

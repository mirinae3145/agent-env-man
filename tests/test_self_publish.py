"""Prepared release publication uses temporary local Git repositories."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from click.testing import CliRunner

from agent_env_man.cli import cli
from agent_env_man.git_source import Git
from agent_env_man.model import Error
from agent_env_man import self_publish


class SelfPublication(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aem-self-publish-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        environment = patch.dict(os.environ, {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                                              "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                                              "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"})
        environment.start()
        self.addCleanup(environment.stop)
        self.remote = self.root / "remote.git"
        self.git(self.root, "init", "--bare", "-b", "main", str(self.remote))
        self.checkout = self.root / "checkout"
        self.git(self.root, "clone", str(self.remote), str(self.checkout))
        self.release("1.0.0")

    def git(self, path, *args):
        result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def release(self, version, *, annotated=False):
        (self.checkout / "pyproject.toml").write_text(
            f'[project]\nname = "agent-env-man"\nversion = "{version}"\n', encoding="utf-8")
        self.git(self.checkout, "add", "pyproject.toml")
        self.git(self.checkout, "commit", "-m", "Prepare release")
        args = ("-a", "-m", "Release") if annotated else ()
        self.git(self.checkout, "tag", *args, "v" + version)

    def call(self, *args, code=0, checkout=True):
        # Even malformed machine data must remain irrelevant to self publication.
        config = self.root / "invalid.toml"
        config.write_text("invalid [", encoding="utf-8")
        command = ["--config", str(config), "--json", "self", "publish"]
        if checkout:
            command += ["--checkout", str(self.checkout)]
        with patch("agent_env_man.cli_runtime.Runtime.run", side_effect=AssertionError("machine state read")):
            result = CliRunner().invoke(cli, [*command, *args])
        self.assertEqual(result.exit_code, code, result.output + repr(result.exception))
        self.assertEqual(list(self.root.glob("*.state")), [])
        return json.loads(result.output)

    def snapshot(self):
        return ((self.checkout / ".git/index").read_bytes(),
                self.git(self.checkout, "show-ref"), self.git(self.checkout, "status", "--porcelain"))

    def test_first_publication_and_retry_preserve_local_release(self):
        before = self.snapshot()
        for _ in range(2):
            result = self.call()
            self.assertEqual(result["status"], "published")
            self.assertEqual(self.git(self.remote, "rev-parse", "main"), result["revision"])
            self.assertEqual(self.git(self.remote, "rev-parse", "v1.0.0^{commit}"), result["revision"])
        # Tracking refs can change; local release and index must remain intact.
        self.assertEqual(self.snapshot()[0], before[0])
        self.assertEqual(self.git(self.checkout, "rev-parse", "v1.0.0^{commit}"), result["revision"])

    def test_prerelease_publication_and_retry(self):
        self.release("2.0.0rc1", annotated=True)
        for _ in range(2):
            result = self.call()
            self.assertEqual(result["status"], "published")
            self.assertEqual(result["version"], "2.0.0rc1")
            self.assertEqual(self.git(self.remote, "rev-parse", "v2.0.0rc1^{commit}"), result["revision"])

    def test_bare_prerelease_publication(self):
        for label in ('a', 'b', 'rc'):
            with self.subTest(label=label):
                version = '2.0.0' + label
                self.release(version, annotated=True)
                result = self.call()
                self.assertEqual(result['status'], 'published')
                self.assertEqual(result['version'], version)
                self.assertEqual(self.git(self.remote, 'rev-parse', 'v' + version + '^{commit}'), result['revision'])

    def test_semver_tag_publication_with_python_package_version(self):
        for version, tag in [('2.0.0a0', 'v2.0.0-alpha'), ('2.0.0b0', 'v2.0.0-beta'),
                             ('2.0.0b1', 'v2.0.0-beta.1'), ('2.0.0rc', 'v2.0.0-rc')]:
            with self.subTest(version=version, tag=tag):
                self.release(version, annotated=True)
                self.git(self.checkout, 'tag', '-d', 'v' + version)
                self.git(self.checkout, 'tag', '-a', '-m', 'SemVer release', tag)
                for _ in range(2):
                    result = self.call()
                    self.assertEqual(result['status'], 'published')
                    self.assertEqual(result['tag'], tag)
                    self.assertEqual(result['version'], version)
                    self.assertEqual(self.git(self.remote, 'rev-parse', tag + '^{commit}'), result['revision'])

    def test_exact_package_tag_mismatch_cannot_be_bypassed_by_semver_alias(self):
        self.release('2.0.0b0')
        self.git(self.checkout, 'tag', '-f', 'v2.0.0b0', 'HEAD~1')
        self.git(self.checkout, 'tag', 'v2.0.0-beta')
        result = self.call(code=1)
        self.assertIn('prepare local tag v2.0.0b0', result['error'])

    def test_forward_publication_preserves_annotated_tag_object(self):
        self.call()
        self.release("1.0.1", annotated=True)
        original = self.git(self.checkout, "rev-parse", "refs/tags/v1.0.1")
        result = self.call()
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), result["revision"])
        self.assertEqual(self.git(self.remote, "rev-parse", "refs/tags/v1.0.1"), original)

    def test_equivalent_remote_tag_annotation_is_preserved(self):
        self.call()
        self.git(self.remote, "tag", "-f", "-a", "v1.0.0", "main", "-m", "Remote annotation")
        original = self.git(self.remote, "rev-parse", "refs/tags/v1.0.0")
        result = self.call()
        self.assertTrue(result["tag_present"])
        self.assertEqual(self.git(self.remote, "rev-parse", "refs/tags/v1.0.0"), original)

    def test_preview_offline_preserves_refs_index_and_head(self):
        before = self.snapshot()
        self.remote.rename(self.root / "offline.git")
        run = Git.run
        def offline(git, path, *args, **kwargs):
            if any(arg in args for arg in ("ls-remote", "fetch", "push")):
                self.fail("preview accessed network")
            return run(git, path, *args, **kwargs)
        with patch.object(Git, "run", new=offline):
            result = self.call("--dry-run")
        self.assertEqual(result["status"], "planned")
        self.assertFalse(result["network"])
        self.assertFalse(result["remote_verified"])
        self.assertEqual(self.snapshot(), before)

    def test_unprepared_checkouts_fail_before_network(self):
        run = Git.run
        def offline(git, path, *args, **kwargs):
            if any(arg in args for arg in ("ls-remote", "fetch", "push")):
                self.fail("invalid release contacted remote")
            return run(git, path, *args, **kwargs)
        with patch.object(Git, "run", new=offline):
            for staged in (False, True):
                (self.checkout / "extra").write_text("local", encoding="utf-8")
                if staged:
                    self.git(self.checkout, "add", "extra")
                before = self.snapshot()
                self.assertIn("dirty", self.call(code=1)["error"])
                self.assertEqual(self.snapshot(), before)
            self.git(self.checkout, "reset", "HEAD", "extra")
            (self.checkout / "extra").unlink()
            self.git(self.checkout, "checkout", "--detach")
            self.assertIn("attached branch", self.call(code=1)["error"])
            self.git(self.checkout, "checkout", "main")
            (self.checkout / ".git/MERGE_HEAD").write_text(self.git(self.checkout, "rev-parse", "HEAD"), encoding="utf-8")
            self.assertIn("unfinished", self.call(code=1)["error"])

    def test_invalid_package_version_and_tag(self):
        self.git(self.checkout, "tag", "-d", "v1.0.0")
        self.assertIn("prepare local tag", self.call("--dry-run", code=1)["error"])
        self.git(self.checkout, "tag", "v1.0.0")
        self.release("1.0.1")
        self.git(self.checkout, "tag", "-f", "v1.0.1", "HEAD~1")
        self.assertIn("prepare local tag", self.call(code=1)["error"])
        for document, diagnostic in (
                ('[project]\nname="another"\nversion="1.0.1"', "project.name"),
                ('[project]\nname="agent-env-man"\nversion="1.0.1.dev1"', "X.Y.Z"),
                ('[project]\nname="agent-env-man"\nversion=1', "X.Y.Z")):
            (self.checkout / "pyproject.toml").write_text(document, encoding="utf-8")
            self.git(self.checkout, "commit", "-am", "Invalid package")
            self.assertIn(diagnostic, self.call(code=1)["error"])

    def test_missing_remote_branch_and_remote_tag_conflict(self):
        self.call()
        old = self.git(self.remote, "rev-parse", "main")
        self.git(self.remote, "update-ref", "-d", "refs/heads/main")
        self.assertIn("remote is not empty", self.call(code=1)["error"])
        self.git(self.remote, "update-ref", "refs/heads/main", old)
        self.release("1.0.1")
        self.git(self.remote, "tag", "v1.0.1", old)
        result = self.call(code=1)
        self.assertIn("different commit", result["error"])
        self.assertEqual(self.git(self.remote, "rev-parse", "main"), old)

    def test_behind_and_diverged_are_rejected(self):
        self.call()
        old = self.git(self.checkout, "rev-parse", "HEAD")
        self.release("1.0.1")
        self.call()
        self.git(self.checkout, "reset", "--hard", old)
        self.assertIn("behind", self.call(code=1)["error"])
        self.release("1.0.2")
        self.assertIn("diverged", self.call(code=1)["error"])

    def test_atomic_unsupported_and_rejected_push_leave_both_refs_unchanged(self):
        self.call()
        old = self.git(self.remote, "rev-parse", "main")
        self.release("1.0.1")
        for failure in ("unsupported", "rejected"):
            with self.subTest(failure=failure):
                if failure == "unsupported":
                    self.git(self.remote, "config", "receive.advertiseAtomic", "false")
                else:
                    # A non-bare remote rejects its currently checked-out branch.
                    self.git(self.remote, "config", "core.bare", "false")
                    self.git(self.remote, "config", "receive.denyCurrentBranch", "refuse")
                before = self.snapshot()
                self.assertEqual(self.call(code=1)["status"], "failed")
                self.assertEqual(self.git(self.remote, "rev-parse", "main"), old)
                self.assertEqual(self.git(self.remote, "tag", "--list", "v1.0.1"), "")
                self.assertEqual(self.snapshot(), before)
                self.git(self.remote, "config", "receive.advertiseAtomic", "true")
                self.git(self.remote, "config", "core.bare", "true")
        self.assertEqual(self.call()["status"], "published")

    def test_push_configuration_cannot_add_unselected_refs(self):
        self.git(self.checkout, "branch", "other")
        self.git(self.checkout, "tag", "-a", "private", "-m", "Private")
        self.git(self.checkout, "config", "push.followTags", "true")
        self.git(self.checkout, "config", "remote.origin.mirror", "true")
        self.call()
        self.assertEqual(self.git(self.remote, "for-each-ref", "--format=%(refname)"),
                         "refs/heads/main\nrefs/tags/v1.0.0")

    def test_push_url_mismatch_and_network_failure_are_fatal(self):
        self.git(self.checkout, "remote", "set-url", "--push", "origin", str(self.root / "other.git"))
        self.assertIn("push destination", self.call(code=1)["error"])
        self.git(self.checkout, "config", "--unset", "remote.origin.pushurl")
        run = Git.run
        for phase in ("ls-remote", "fetch"):
            if phase == "fetch":
                self.call()
            def fail(git, path, *args, **kwargs):
                if phase in args:
                    raise Error("Authentication failed")
                if "push" in args:
                    self.fail("push after network error")
                return run(git, path, *args, **kwargs)
            with patch.object(Git, "run", new=fail):
                self.assertIn("Authentication failed", self.call(code=1)["error"])

    def test_checkout_changes_during_remote_inspection_are_rejected(self):
        preflight = Git.publication_preflight
        def change(git, source):
            observed = preflight(git, source)
            self.git(self.checkout, "tag", "-f", "-a", "v1.0.0", "-m", "Changed object")
            return observed
        with patch.object(Git, "publication_preflight", new=change):
            self.assertIn("changed during", self.call(code=1)["error"])
        self.assertEqual(self.git(self.remote, "for-each-ref", "--format=%(refname)"), "")

    def test_cli_help_and_invalid_options_do_not_resolve_checkout(self):
        with patch.object(self_publish, "checkout_path", side_effect=AssertionError("discovery ran")):
            for args, code in ((["--help"], 0), (["--timeout", "nan"], 2), (["-m", "message"], 2)):
                result = CliRunner().invoke(cli, ["self", "publish", *args])
                self.assertEqual(result.exit_code, code, result.output)

    def test_explicit_root_takes_precedence_and_subdirectory_is_rejected(self):
        with patch.object(self_publish.metadata, "distribution", side_effect=AssertionError("metadata read")):
            self.call("--dry-run")
        subdir = self.checkout / "nested"
        subdir.mkdir()
        report, failed = self_publish.publish(subdir, dry_run=True)
        self.assertTrue(failed)
        self.assertIn("checkout root", report["error"])

    def test_recorded_local_source_default_and_stale_path(self):
        distribution = Mock()
        # URI decoding must preserve spaces and Unicode path components.
        renamed = self.root / "source with spaces 한글"
        self.checkout.rename(renamed)
        self.checkout = renamed
        distribution.read_text.return_value = json.dumps({"url": renamed.as_uri(), "dir_info": {}})
        with patch.object(self_publish.metadata, "distribution", return_value=distribution):
            self.assertEqual(self.call("--dry-run", checkout=False)["checkout"], str(renamed))
            self.assertEqual(self.call(checkout=False)["status"], "published")
            distribution.read_text.return_value = json.dumps({"url": (self.root / "missing").as_uri(), "dir_info": {}})
            self.assertIn("--checkout", self.call(code=1, checkout=False)["error"])

    def test_metadata_missing_git_install_and_development_fallback(self):
        module = self.root / "site-packages/agent_env_man/self_publish.py"
        distribution = Mock()
        for recorded in (None, '{"url":"https://example.invalid/aem.git","vcs_info":{"vcs":"git"}}'):
            distribution.read_text.return_value = recorded
            with patch.object(self_publish.metadata, "distribution", return_value=distribution):
                with patch.object(self_publish, "__file__", str(module)):
                    self.assertIn("--checkout", self.call(code=1, checkout=False)["error"])
                dev_module = self.checkout / "src/agent_env_man/self_publish.py"
                with patch.object(self_publish, "__file__", str(dev_module)):
                    self.assertEqual(self_publish.checkout_path(), self.checkout)

    def test_malformed_metadata_does_not_guess_another_checkout(self):
        distribution = Mock()
        for recorded in ("invalid json", "[]", '{"url":"file:relative","dir_info":{}}'):
            distribution.read_text.return_value = recorded
            with patch.object(self_publish.metadata, "distribution", return_value=distribution):
                self.assertIn("--checkout", self.call(code=1, checkout=False)["error"])

    def test_linked_worktree_and_relative_explicit_root(self):
        worktree = self.root / "worktree"
        self.git(self.checkout, "worktree", "add", "-b", "release", str(worktree))
        before = Path.cwd()
        try:
            os.chdir(self.root)
            result = self.call("--checkout", "worktree", "--dry-run", checkout=False)
        finally:
            os.chdir(before)
        self.assertEqual(result["checkout"], str(worktree))
        self.assertEqual(result["branch"], "release")

    def test_multiple_fetch_urls_are_rejected_even_with_one_push_url(self):
        self.git(self.checkout, "config", "--add", "remote.origin.url", str(self.root / "other.git"))
        self.git(self.checkout, "remote", "set-url", "--push", "origin", str(self.remote))
        self.assertIn("single fetch", self.call(code=1)["error"])

    def test_untracked_and_malformed_package_metadata_are_rejected(self):
        self.git(self.checkout, "rm", "pyproject.toml")
        self.git(self.checkout, "commit", "-m", "Remove metadata")
        self.assertIn("tracked regular file", self.call(code=1)["error"])
        (self.checkout / "pyproject.toml").write_text("[ invalid", encoding="utf-8")
        self.git(self.checkout, "add", "pyproject.toml")
        self.git(self.checkout, "commit", "-m", "Malformed metadata")
        self.assertEqual(self.call(code=1)["status"], "failed")

    def test_ignored_runtime_file_does_not_block_or_get_published(self):
        (self.checkout / ".git/info/exclude").write_text("cache.txt\n", encoding="utf-8")
        cache = self.checkout / "cache.txt"
        cache.write_text("local cache", encoding="utf-8")
        self.call()
        self.assertEqual(cache.read_text(encoding="utf-8"), "local cache")
        self.assertNotIn("cache.txt", self.git(self.remote, "ls-tree", "-r", "--name-only", "main"))

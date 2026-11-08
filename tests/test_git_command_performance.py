"""Git process counts fall while binding and operation guards remain fresh."""

from pathlib import Path
import unittest
from unittest.mock import patch

from agent_env_man.git_source import Git
from agent_env_man.model import Error, Source
import test_publish as publication_tests


class GitCommandCosts(unittest.TestCase):
    setUp = publication_tests.Publication.setUp
    git = publication_tests.Publication.git
    commit = publication_tests.Publication.commit
    cli = publication_tests.Publication.cli

    def source(self, path=None):
        return Source('shared', path or self.checkout, str(self.remote), 'main')

    def test_idle_batches_paths_and_retains_every_marker_guard(self):
        source = self.source()
        with patch.object(Git, 'run', autospec=True, side_effect=Git.run) as called:
            Git().idle(source)
        self.assertEqual(called.call_count, 1)
        for marker in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply'):
            path = Path(self.git(self.checkout, 'rev-parse', '--git-path', marker))
            if not path.is_absolute():
                path = self.checkout / path
            path.write_bytes(b'unfinished')
            with self.subTest(marker=marker), self.assertRaisesRegex(Error, marker):
                Git().idle(source)
            path.unlink()

    def test_shared_source_binding_checks_unique_paths_and_rechecks_redirects(self):
        from agent_env_man.model import Config
        config = Config(self.config)
        calls = []
        resolve = Path.resolve
        def observed(path, *args, **options):
            if path == self.checkout:
                calls.append(path)
            return resolve(path, *args, **options)
        with patch.object(Path, 'resolve', new=observed):
            sources = config.sources
            self.assertEqual(sources['one'].path, sources['two'].path)
            self.assertEqual(len(calls), 1)
            config.sources
            self.assertEqual(len(calls), 2)
        moved = self.checkout.with_name('moved-shared')
        self.checkout.rename(moved)
        try:
            self.checkout.symlink_to(moved, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'Symbolic links unavailable: {exc}')
        with self.assertRaisesRegex(Error, 'must not redirect'):
            config.sources

    def test_idle_uses_linked_worktree_git_paths(self):
        linked = self.root / 'linked'
        self.git(self.checkout, 'worktree', 'add', '-b', 'other', linked)
        path = Path(self.git(linked, 'rev-parse', '--git-path', 'MERGE_HEAD'))
        path.write_bytes(b'unfinished')
        with self.assertRaisesRegex(Error, 'MERGE_HEAD'):
            Git().idle(self.source(linked))

    def test_idle_retains_newline_paths_in_worktree_administration(self):
        moved = self.root / 'checkout\nwith newline'
        self.checkout.rename(moved)
        linked = self.root / 'linked'
        self.git(moved, 'worktree', 'add', '-b', 'other', linked)
        path = Path(self.git(linked, 'rev-parse', '--git-path', 'REVERT_HEAD'))
        path.write_bytes(b'unfinished')
        with self.assertRaisesRegex(Error, 'REVERT_HEAD'):
            Git().idle(self.source(linked))

    def test_publication_preflight_checks_guards_without_unused_diff_report(self):
        source = self.source()
        calls = []
        original = Git.run
        def recording(self, path, *args, **options):
            calls.append(args[0])
            return original(self, path, *args, **options)
        with patch.object(Git, 'run', new=recording):
            self.assertEqual(Git().publication_preflight(source), self.git(self.checkout, 'rev-parse', 'HEAD'))
        self.assertNotIn('status', calls)
        self.assertNotIn('diff', calls)
        self.assertNotIn('log', calls)
        self.git(self.checkout, 'config', 'remote.origin.pushurl', str(self.root / 'wrong.git'))
        with self.assertRaisesRegex(Error, 'push destination'):
            Git().publication_preflight(source)


if __name__ == '__main__':
    unittest.main()

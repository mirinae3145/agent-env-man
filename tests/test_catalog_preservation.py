"""Catalog inspection and concurrent delivery preserve local work."""

import json
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man import catalog
from agent_env_man.git_source import Git
import test_git_catalog as catalog_tests


class CatalogPreservation(unittest.TestCase):
    def setUp(self):
        # Reuse the local-remote fixture without rediscovering its test methods.
        self.fixture = catalog_tests.GitCatalog(methodName='runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_locate_refuses_redirected_entry_and_ancestor_without_writes(self):
        case = self.fixture
        case.boot()
        before, machine = case.state(), case.config.read_bytes()
        head = case.git(case.checkout, 'rev-parse', 'HEAD')
        for directory in (False, True):
            with self.subTest(directory=directory):
                path = case.entry.parent if directory else case.entry
                outside = case.root / ('redirected-directory' if directory else 'redirected-file')
                path.rename(outside)
                try:
                    path.symlink_to(outside, target_is_directory=directory)
                except OSError:
                    outside.rename(path)
                    self.skipTest('Symbolic link capability unavailable')
                try:
                    contents = case.entry.read_bytes()
                    with patch.object(Git, 'fetch', side_effect=AssertionError('locate fetched')):
                        error = case.cli('catalog', 'locate', code=1)
                    self.assertIn('redirects through a symlink or junction', error)
                    self.assertTrue(path.is_symlink())
                    self.assertEqual(case.entry.read_bytes(), contents)
                    self.assertEqual(case.state(), before)
                    self.assertEqual(case.config.read_bytes(), machine)
                    self.assertEqual(case.git(case.checkout, 'rev-parse', 'HEAD'), head)
                finally:
                    path.unlink()
                    outside.rename(path)

    def test_locate_refuses_missing_or_replaced_tracked_entry(self):
        case = self.fixture
        case.boot()
        case.entry.unlink()
        before, machine = case.state(), case.config.read_bytes()
        head = case.git(case.checkout, 'rev-parse', 'HEAD')
        for replacement in ('missing', 'directory'):
            with self.subTest(replacement=replacement):
                if replacement == 'directory':
                    case.entry.mkdir()
                    (case.entry / 'keep.txt').write_text('Unrelated contents\n', encoding='utf-8')
                with patch.object(Git, 'fetch', side_effect=AssertionError('locate fetched')):
                    error = case.cli('catalog', 'locate', code=1)
                self.assertTrue(
                    str(case.entry) in error or repr(str(case.entry)) in error,
                    error,
                )
                if replacement == 'missing':
                    self.assertFalse(case.entry.exists())
                else:
                    self.assertTrue(case.entry.is_dir())
                    self.assertEqual((case.entry / 'keep.txt').read_text(encoding='utf-8'), 'Unrelated contents\n')
                self.assertEqual(case.state(), before)
                self.assertEqual(case.config.read_bytes(), machine)
                self.assertEqual(case.git(case.checkout, 'rev-parse', 'HEAD'), head)

    def test_locate_requires_bootstrap_to_record_default_branch(self):
        case = self.fixture
        case.boot()
        document = tomlkit.parse(case.config.read_text(encoding='utf-8'))
        del document['catalog']['branch']
        case.config.write_text(tomlkit.dumps(document), encoding='utf-8')
        before, machine, entry = case.state(), case.config.read_bytes(), case.entry.read_bytes()
        with patch.object(Git, 'run', side_effect=AssertionError('unprepared locate contacted Git')):
            error = case.cli('catalog', 'locate', code=1)
        self.assertIn("Run bootstrap to record the catalog's default branch", error)
        self.assertEqual(case.state(), before)
        self.assertEqual(case.config.read_bytes(), machine)
        self.assertEqual(case.entry.read_bytes(), entry)

    def test_bootstrap_rejects_revision_changed_during_preflight(self):
        case = self.fixture
        validate = catalog.validate

        def concurrent_commit(config, state):
            validate(config, state)
            stages = list(case.root.glob('.aem-catalog-*'))
            self.assertEqual(len(stages), 1)
            stage = stages[0]
            (stage / 'concurrent.txt').write_text('Concurrent commit\n', encoding='utf-8')
            case.commit(stage)

        with patch.object(catalog, 'validate', side_effect=concurrent_commit):
            error = case.boot(code=1)
        self.assertIn('Catalog changed during bootstrap', error)
        self.assertFalse(case.config.exists())
        self.assertFalse(case.checkout.exists())
        self.assertFalse(case.content.exists())
        self.assertEqual(list(case.root.glob('.aem-catalog-*')), [])
        case.boot()
        self.assertEqual(case.cli('catalog', 'locate')['entry'], str(case.entry))

    def test_bootstrap_preserves_checkout_created_during_clone(self):
        case = self.fixture
        validate = catalog.validate
        marker = case.checkout / 'keep.txt'

        def concurrent_checkout(config, state):
            validate(config, state)
            case.checkout.mkdir()
            marker.write_text('Another writer owns this directory\n', encoding='utf-8')

        with patch.object(catalog, 'validate', side_effect=concurrent_checkout):
            error = case.boot(code=1)
        self.assertIn('Catalog checkout appeared while cloning', error)
        self.assertEqual(marker.read_text(encoding='utf-8'), 'Another writer owns this directory\n')
        self.assertEqual(list(case.checkout.iterdir()), [marker])
        self.assertFalse(case.config.exists())
        self.assertFalse(case.content.exists())
        self.assertEqual(list(case.root.glob('.aem-catalog-*')), [])

    def test_update_preserves_commit_made_after_candidate_validation(self):
        case = self.fixture
        case.boot()
        case.cli('apply')
        machine = case.config.read_bytes()
        items = json.loads(case.state())['items']
        installed = (case.target / 'SKILL.md').read_bytes()
        case.save_remote(tomlkit.dumps(case.document) + '\n# Remote change\n')
        validate = catalog.validate
        concurrent = {}

        def concurrent_commit(config, state):
            validate(config, state)
            case.entry.write_bytes(case.entry.read_bytes() + b'\n# Concurrent local change\n')
            case.commit(case.checkout)
            concurrent['head'] = case.git(case.checkout, 'rev-parse', 'HEAD')
            concurrent['entry'] = case.entry.read_bytes()

        with patch.object(catalog, 'validate', side_effect=concurrent_commit), \
                patch.object(Git, 'fast_forward', side_effect=AssertionError('concurrent commit was overwritten')):
            report = case.cli('catalog', 'update', code=1)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('Catalog changed during update', report['error'])
        self.assertEqual(case.git(case.checkout, 'rev-parse', 'HEAD'), concurrent['head'])
        self.assertEqual(case.entry.read_bytes(), concurrent['entry'])
        self.assertEqual(case.config.read_bytes(), machine)
        self.assertEqual(json.loads(case.state())['items'], items)
        self.assertEqual((case.target / 'SKILL.md').read_bytes(), installed)


if __name__ == '__main__':
    unittest.main()

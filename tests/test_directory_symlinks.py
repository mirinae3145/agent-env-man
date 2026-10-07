"""Opaque directory links retain their identity through the complete lifecycle."""

from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from agent_env_man import copy_publication, payload_links
from agent_env_man.model import Error
from agent_env_man.storage import fingerprint, copy_payload
import test_directories


@unittest.skipIf(os.name == 'nt', 'POSIX link preservation only')
class DirectorySymlinks(unittest.TestCase):
    setUp = test_directories.Directories.setUp
    git = test_directories.Directories.git
    commit = test_directories.Directories.commit
    repository = test_directories.Directories.repository
    save_catalog = test_directories.Directories.save_catalog
    run_cli = test_directories.Directories.run_cli
    require_links = test_directories.Directories.require_links
    write = test_directories.Directories.write
    bootstrap = test_directories.Directories.bootstrap
    external = test_directories.Directories.external
    manager = test_directories.Directories.manager

    def enable(self, mode='copy'):
        self.document['directories']['cases']['preserve_symlinks'] = True
        self.document['directories']['cases']['install']['mode'] = mode
        self.write()

    def link(self, path, text):
        path.symlink_to(text)
        return path

    def test_git_copy_update_detach_preserves_links_and_target_independence(self):
        self.enable()
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'private').write_text('private')
        self.link(self.repo / 'cases/absolute', str(outside))
        self.link(self.repo / 'cases/sibling', '../shared')
        self.link(self.repo / 'cases/dangling', 'missing')
        self.link(self.repo / 'cases/whitespace', ' trailing space\n')
        self.commit(self.repo)
        self.bootstrap()
        self.run_cli('apply')
        expected = fingerprint(self.target, preserve_symlinks=True, source_relative='cases')
        self.assertEqual(os.readlink(self.target / 'whitespace'), ' trailing space\n')
        (outside / 'private').write_text('changed outside')
        self.assertEqual(fingerprint(self.target, preserve_symlinks=True, source_relative='cases'), expected)
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')
        (self.repo / 'cases/dangling').unlink()
        self.link(self.repo / 'cases/dangling', 'different')
        self.commit(self.repo)
        self.run_cli('sync', '--item', 'cases')
        self.assertEqual(os.readlink(self.target / 'dangling'), 'different')
        self.run_cli('detach', 'cases')
        self.assertEqual((outside / 'private').read_text(), 'changed outside')
        self.assertEqual(os.readlink(self.target / 'sibling'), '../shared')

    def test_git_live_link_and_detach_use_repository_not_payload_boundary(self):
        self.enable('link')
        self.link(self.repo / 'cases/sibling', '../shared')
        self.commit(self.repo)
        self.bootstrap()
        self.run_cli('apply')
        self.assertTrue(self.target.is_symlink())
        self.run_cli('detach', 'cases')
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(os.readlink(self.target / 'sibling'), '../shared')
        self.assertTrue(self.manager().state.data['items']['cases:directory']['detached'])

    def test_relative_first_escape_rejected_before_checkout_advances(self):
        self.enable('link')
        self.bootstrap()
        self.run_cli('apply')
        head = self.git(self.checkout, 'rev-parse', 'HEAD')
        self.link(self.repo / 'cases/escape', '../../research-tools/cases')
        self.commit(self.repo)
        report = self.run_cli('update', 'cases', code=1)
        self.assertIn('escapes source root', str(report))
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), head)
        self.assertFalse((self.target / 'escape').is_symlink())

    def test_external_copy_publication_preserves_leaf_and_nested_links(self):
        self.enable()
        self.external()
        outside = self.root / 'private'
        outside.write_text('untouched')
        self.link(self.external_root / 'leaf', str(outside))
        (self.external_root / 'nested').mkdir()
        self.link(self.external_root / 'nested/up', '../first.md')
        self.run_cli('apply')
        (self.target / 'leaf').unlink()
        self.link(self.target / 'leaf', 'missing')
        self.link(self.target / 'nested/new', str(outside))
        preview = self.run_cli('publish', 'cases', '--from-copy', '--dry-run')
        self.assertIn('leaf', str(preview))
        self.run_cli('publish', 'cases', '--from-copy')
        self.assertEqual(os.readlink(self.external_root / 'leaf'), 'missing')
        self.assertEqual(os.readlink(self.external_root / 'nested/new'), str(outside))
        self.assertEqual(outside.read_text(), 'untouched')
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')
        self.assertTrue(list(self.external_root.parent.glob('.aem-collection-*')))

    def test_external_relative_escape_rejected_before_copy_collection(self):
        self.enable()
        self.external()
        self.run_cli('apply')
        self.link(self.target / 'escape', '../external/first.md')
        original = fingerprint(self.external_root)
        for args in (('--dry-run',), ()):
            report = self.run_cli('publish', 'cases', '--from-copy', *args, code=1)
            self.assertIn('escapes source root', str(report))
        self.assertEqual(fingerprint(self.external_root), original)

    def test_external_live_link_detach_after_catalog_removal(self):
        self.enable('link')
        self.external(mode='link')
        self.link(self.external_root / 'dangling', 'missing')
        self.run_cli('apply')
        self.catalog.unlink()
        self.run_cli('detach', 'cases')
        self.assertFalse(self.target.is_symlink())
        self.assertEqual(os.readlink(self.target / 'dangling'), 'missing')

    def test_disabling_refuses_existing_links_but_allows_saved_detach(self):
        self.enable()
        self.external()
        self.link(self.external_root / 'dangling', 'missing')
        self.run_cli('apply')
        self.document['directories']['cases']['preserve_symlinks'] = False
        self.write()
        self.run_cli('apply', code=1)
        self.run_cli('detach', 'cases')
        self.assertEqual(os.readlink(self.target / 'dangling'), 'missing')

    def test_disable_checks_local_copy_even_when_source_has_no_links(self):
        self.enable()
        self.bootstrap()
        self.run_cli('apply')
        self.link(self.target / 'local', 'missing')
        self.document['directories']['cases']['preserve_symlinks'] = False
        self.write()
        (self.repo / 'cases/first.md').write_text('new')
        self.commit(self.repo)
        before = self.git(self.checkout, 'rev-parse', 'HEAD')
        self.run_cli('update', 'cases', code=1)
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), before)
        self.run_cli('detach', 'cases')

    def test_disabling_after_links_removed_keeps_regular_hash_and_updates_policy(self):
        self.enable()
        self.bootstrap()
        self.run_cli('apply')
        old_hash = self.manager().state.data['items']['cases:directory']['hash']
        self.document['directories']['cases']['preserve_symlinks'] = False
        self.write()
        self.run_cli('apply')
        record = self.manager().state.data['items']['cases:directory']
        self.assertFalse(record['preserve_symlinks'])
        self.assertEqual(record['hash'], old_hash)

    def test_ignored_links_are_copied_without_becoming_tracked(self):
        self.enable()
        (self.repo / '.gitignore').write_text('cases/local-link\n')
        self.commit(self.repo)
        self.bootstrap()
        self.link(self.checkout / 'cases/local-link', '../untracked-target')
        self.run_cli('apply')
        self.assertEqual(os.readlink(self.target / 'local-link'), '../untracked-target')
        self.assertEqual(self.git(self.checkout, 'ls-files', 'cases/local-link'), '')
        self.assertFalse((self.repo / 'cases/local-link').exists())

    def test_git_text_checkout_refused_and_future_revision_stopped(self):
        self.enable()
        self.bootstrap()
        self.git(self.checkout, 'config', 'core.symlinks', 'false')
        self.link(self.repo / 'cases/link', 'first.md')
        self.commit(self.repo)
        head = self.git(self.checkout, 'rev-parse', 'HEAD')
        self.assertIn('core.symlinks', str(self.run_cli('update', 'cases', code=1)))
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), head)
        self.git(self.checkout, 'fetch', 'origin')
        self.git(self.checkout, 'merge', '--ff-only', 'origin/main')
        self.assertFalse((self.checkout / 'cases/link').is_symlink())
        self.run_cli('apply', code=1)
        self.assertFalse(self.target.exists())

    def test_strict_orphaned_consumer_stops_shared_git_update(self):
        self.enable('link')
        self.document['directories']['strict'] = {
            'source': 'store', 'subdir': 'cases', 'install': {'root': 'personal', 'destination': 'strict'}}
        self.write()
        self.bootstrap()
        self.run_cli('apply')
        del self.document['directories']['strict']
        self.write()
        head = self.git(self.checkout, 'rev-parse', 'HEAD')
        self.link(self.repo / 'cases/link', 'first.md')
        self.commit(self.repo)
        self.run_cli('update', 'cases', code=1)
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), head)

    def test_collection_protects_strict_orphaned_ancestor_consumer(self):
        self.enable()
        self.external()
        self.document['directories']['strict'] = {'source': 'store',
            'install': {'root': 'personal', 'destination': 'strict'}}
        self.write()
        self.run_cli('apply')
        del self.document['directories']['strict']
        self.write()
        self.link(self.target / 'link', 'first.md')
        original = fingerprint(self.external_root)
        for args in (('--dry-run',), ()):
            self.run_cli('publish', 'cases', '--from-copy', *args, code=1)
        self.assertEqual(fingerprint(self.external_root), original)

    def test_collection_failure_restores_links_and_nested_payload(self):
        self.enable()
        self.external()
        self.link(self.external_root / 'a-link', 'missing')
        (self.external_root / 'nested').mkdir()
        self.link(self.external_root / 'nested/link', '../first.md')
        self.run_cli('apply')
        (self.target / 'a-link').unlink()
        (self.target / 'a-link').mkdir()
        self.link(self.target / 'a-link/new', '/absent')
        (self.target / 'nested/link').unlink()
        self.link(self.target / 'nested/link', '/different')
        original = fingerprint(self.external_root, preserve_symlinks=True)
        records = deepcopy(self.manager().state.data['items'])
        replace = copy_publication.replace_link_entry
        failed = False
        def fail(source, target):
            nonlocal failed
            if not failed and Path(source).parent.name == 'stages' and Path(target).name == 'nested':
                failed = True
                raise OSError('simulated failure')
            return replace(source, target)
        with patch.object(copy_publication, 'replace_link_entry', side_effect=fail):
            self.run_cli('publish', 'cases', '--from-copy', code=1)
        self.assertEqual(fingerprint(self.external_root, preserve_symlinks=True), original)
        self.assertEqual(self.manager().state.data['items'], records)
        self.assertIsNone(self.manager().state.data['pending'])

    def test_interrupted_install_recovers_links_without_catalog(self):
        self.enable()
        self.external()
        self.link(self.external_root / 'link', 'old')
        self.run_cli('apply')
        (self.external_root / 'link').unlink()
        self.link(self.external_root / 'link', 'new')
        from agent_env_man import manager as module
        replace = module.replace_link_entry
        def interrupt(source, target):
            if Path(source).name.startswith('.aem-stage-'):
                raise KeyboardInterrupt()
            return replace(source, target)
        with patch.object(module, 'replace_link_entry', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.manager().apply()
        self.assertIsNotNone(self.manager().state.data['pending'])
        self.catalog.unlink()
        self.run_cli('recover')
        self.assertEqual(os.readlink(self.target / 'link'), 'old')

    def test_no_follow_scan_preserves_regular_hash_and_opaque_chain(self):
        self.enable()
        payload = self.repo / 'cases'
        (payload / 'empty').mkdir()
        (payload / 'run').write_text('executable')
        (payload / 'run').chmod(0o755)
        self.assertEqual(fingerprint(payload), fingerprint(payload, preserve_symlinks=True, source_relative='cases'))
        self.link(payload / 'external', '/unavailable')
        self.link(payload / 'chain', 'external/child')
        self.link(payload / 'cycle', 'cycle')
        copy_payload(payload, self.root / 'copy', preserve_symlinks=True, source_relative='cases')
        self.assertEqual(os.readlink(self.root / 'copy/chain'), 'external/child')
        self.assertEqual(fingerprint(payload, preserve_symlinks=True, source_relative='cases'),
                         fingerprint(self.root / 'copy', preserve_symlinks=True, source_relative='cases'))

    def test_file_swapped_for_symlink_is_not_opened(self):
        payload = self.repo / 'cases'
        outside = self.root / 'private'
        outside.write_text('must not read')
        real_open = payload_links.os.open
        real_read = payload_links.os.read
        reads = []
        def race(name, flags, *args, **kwargs):
            if name == 'first.md':
                (payload / name).unlink()
                self.link(payload / name, str(outside))
            return real_open(name, flags, *args, **kwargs)
        def read(fd, size):
            reads.append(fd)
            return real_read(fd, size)
        with patch.object(payload_links.os, 'open', side_effect=race), patch.object(payload_links.os, 'read', side_effect=read):
            with self.assertRaises(OSError):
                fingerprint(payload, preserve_symlinks=True, source_relative='cases')
        self.assertEqual(reads, [])
        self.assertEqual(outside.read_text(), 'must not read')

    def test_directory_swapped_for_symlink_is_not_traversed(self):
        payload = self.repo / 'cases'
        nested = payload / 'nested'
        nested.mkdir()
        outside = self.root / 'private-dir'
        outside.mkdir()
        (outside / 'secret').write_text('private')
        real_open = payload_links.os.open
        def race(name, flags, *args, **kwargs):
            if name == 'nested':
                nested.rmdir()
                self.link(nested, str(outside))
            return real_open(name, flags, *args, **kwargs)
        with patch.object(payload_links.os, 'open', side_effect=race):
            with self.assertRaises(OSError):
                copy_payload(payload, self.root / 'copy', preserve_symlinks=True, source_relative='cases')
        self.assertFalse((self.root / 'copy/nested/secret').exists())
        self.assertEqual((outside / 'secret').read_text(), 'private')

    def test_fifo_refused_without_opening(self):
        os.mkfifo(self.repo / 'cases/pipe')
        with self.assertRaisesRegex(Error, 'Special files'):
            fingerprint(self.repo / 'cases', preserve_symlinks=True, source_relative='cases')

    def test_root_payload_excludes_git_and_preserves_raw_non_utf8_link(self):
        self.enable()
        self.document['directories']['cases']['subdir'] = '.'
        self.write()
        raw = b'unknown-\xff\n'
        self.link(self.repo / 'raw-link', os.fsdecode(raw))
        self.commit(self.repo)
        self.bootstrap()
        self.run_cli('apply')
        self.assertFalse((self.target / '.git').exists())
        self.assertEqual(os.fsencode(os.readlink(self.target / 'raw-link')), raw)
        self.run_cli('detach', 'cases')

    def test_local_link_text_edit_conflicts_but_referent_edit_does_not(self):
        self.enable()
        self.external()
        outside = self.root / 'outside'
        outside.write_text('original')
        self.link(self.external_root / 'link', str(outside))
        self.run_cli('apply')
        outside.write_text('independent')
        self.run_cli('apply')
        (self.target / 'link').unlink()
        self.link(self.target / 'link', 'changed')
        (self.external_root / 'first.md').write_text('source change')
        self.run_cli('apply', code=1)
        self.run_cli('publish', 'cases', '--from-copy', code=1)
        self.assertEqual(outside.read_text(), 'independent')
        self.assertEqual(os.readlink(self.target / 'link'), 'changed')

    def test_external_disable_refuses_update_and_preserves_installed_policy(self):
        self.enable()
        self.external()
        self.link(self.external_root / 'link', 'missing')
        self.run_cli('apply')
        self.document['directories']['cases']['preserve_symlinks'] = False
        self.write()
        self.run_cli('update', 'cases', code=1)
        self.assertTrue(self.manager().state.data['items']['cases:directory']['preserve_symlinks'])
        self.run_cli('detach', 'cases')

    def test_existing_live_policy_must_be_applied_before_link_update(self):
        self.bootstrap()
        self.run_cli('apply')
        self.enable('link')
        self.link(self.repo / 'cases/link', 'first.md')
        self.commit(self.repo)
        self.run_cli('update', 'cases', code=1)
        self.run_cli('apply')
        self.run_cli('update', 'cases')
        self.catalog.unlink()
        self.run_cli('detach', 'cases')
        self.assertEqual(os.readlink(self.target / 'link'), 'first.md')

    def test_git_copy_publication_uses_final_source_subdir_and_keeps_link_mode(self):
        self.enable()
        self.bootstrap()
        self.run_cli('apply')
        remote = self.root / 'publish.git'
        self.git(self.repo, 'clone', '--bare', self.repo, remote)
        self.document['sources']['store']['repository'] = str(remote)
        self.write()
        self.git(self.checkout, 'remote', 'set-url', 'origin', remote)
        self.git(self.checkout, 'config', 'user.name', 'Test')
        self.git(self.checkout, 'config', 'user.email', 'test@example.invalid')
        self.link(self.target / 'sibling', '../shared')
        self.run_cli('publish', 'cases', '--from-copy', '-m', 'Add sibling link')
        self.assertEqual(os.readlink(self.checkout / 'cases/sibling'), '../shared')
        self.assertTrue(self.git(remote, 'ls-tree', 'main', 'cases/sibling').startswith('120000'))

    def test_ignored_local_link_not_overwritten_by_incoming_file(self):
        self.enable('link')
        (self.repo / '.gitignore').write_text('cases/cache-link\n')
        self.commit(self.repo)
        self.bootstrap()
        self.link(self.checkout / 'cases/cache-link', '/unavailable')
        self.run_cli('apply')
        (self.repo / 'cases/cache-link').write_text('incoming')
        self.git(self.repo, 'add', '-f', 'cases/cache-link')
        self.commit(self.repo)
        before = self.git(self.checkout, 'rev-parse', 'HEAD')
        self.run_cli('update', 'cases', code=1)
        self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), before)
        self.assertEqual(os.readlink(self.checkout / 'cases/cache-link'), '/unavailable')

    def test_interrupted_collection_retains_later_edits_until_reconciled(self):
        self.enable()
        self.external()
        self.link(self.external_root / 'link', 'original')
        self.run_cli('apply')
        (self.target / 'link').unlink()
        self.link(self.target / 'link', 'changed')
        original = fingerprint(self.external_root, preserve_symlinks=True)
        replace = copy_publication.replace_link_entry
        def interrupt(source, target):
            if Path(source).parent.name == 'stages':
                raise KeyboardInterrupt()
            return replace(source, target)
        with patch.object(copy_publication, 'replace_link_entry', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.manager().publish(['cases'], from_copy=True)
        manager = self.manager()
        pending = manager.state.data['pending']
        self.assertEqual(pending['operation'], 'copy-collection')
        stage = Path(pending['files'][0]['stage'])
        stage.unlink()
        self.link(stage, 'later-edit')
        self.catalog.unlink()
        self.run_cli('recover', code=1)
        self.assertEqual(os.readlink(stage), 'later-edit')
        stage.unlink()
        self.link(stage, 'changed')
        self.run_cli('recover')
        self.assertEqual(fingerprint(self.external_root, preserve_symlinks=True), original)

    def test_automatic_sync_preserves_links(self):
        self.enable()
        self.document['directories']['cases']['update'] = {'trigger': ['agent-start'], 'action': 'sync'}
        self.write()
        self.link(self.repo / 'cases/link', 'first.md')
        self.commit(self.repo)
        self.bootstrap()
        self.run_cli('auto', '--trigger', 'agent-start', '--item', 'cases')
        self.assertEqual(os.readlink(self.target / 'link'), 'first.md')

    def test_catalog_boolean_scope_and_windows_refusal(self):
        self.enable()
        with patch.object(payload_links, 'require_posix', side_effect=Error('preserve_symlinks is unsupported on Windows')):
            self.assertIn('Windows', str(self.run_cli('bootstrap', self.catalog, code=1)))
        self.document['directories']['cases']['preserve_symlinks'] = 'true'
        self.write()
        self.assertIn('Boolean', str(self.run_cli('bootstrap', self.catalog, code=1)))


class LinkPolicyValidation(unittest.TestCase):
    def test_windows_rejects_opt_in_without_rejecting_ordinary_catalogs(self):
        from types import SimpleNamespace
        from agent_env_man.catalog_schema import validate
        document = {'version': 2, 'sources': {'files': {'type': 'external'}},
                    'directories': {'files': {'source': 'files', 'preserve_symlinks': True}}}
        with patch.object(payload_links, 'os', SimpleNamespace(name='nt')):
            with self.assertRaisesRegex(Error, 'unsupported on Windows'):
                validate(document)
            document['directories']['files']['preserve_symlinks'] = False
            validate(document)

    def test_opt_in_is_not_accepted_for_skills_or_install_tables(self):
        from agent_env_man.catalog_schema import validate
        document = {'version': 2, 'sources': {'store': {'type': 'git', 'repository': 'https://example.invalid/store.git'}},
                    'skills': {'skill': {'source': 'store', 'preserve_symlinks': True}}}
        with self.assertRaises(Error):
            validate(document)
        document.pop('skills')
        document['directories'] = {'files': {'source': 'store', 'install': {'preserve_symlinks': True}}}
        with self.assertRaises(Error):
            validate(document)


if __name__ == '__main__':
    unittest.main()

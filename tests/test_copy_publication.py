"""Explicit reverse collection preserves copy baselines and publication boundaries."""

from copy import deepcopy
import io
from contextlib import redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man.cli import main
from agent_env_man.git_source import Git
from agent_env_man.manager import Manager
from agent_env_man.model import Config, Error
from agent_env_man.storage import State, fingerprint
from agent_env_man.output import format_report
import test_publish as publication_tests


class CopyPublication(unittest.TestCase):
    setUp = publication_tests.Publication.setUp
    git = publication_tests.Publication.git
    commit = publication_tests.Publication.commit
    cli = publication_tests.Publication.cli

    def install(self):
        self.cli('apply', '--item', 'one', '--item', 'two')
        return self.root / 'installed/one'

    def manager(self):
        config = Config(self.config)
        return Manager(config, State(config.state_dir))

    def external(self, *, mode='copy'):
        self.shared = self.root / 'synced folder'
        self.shared.mkdir()
        (self.shared / 'first.txt').write_text('First\n', encoding='utf-8')
        self.document = {'version': 2, 'sources': {'files': {'type': 'external'}},
                         'directories': {'files': {'source': 'files', 'install': {'root': 'skills', 'mode': mode}}}}
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')
        self.cli('bootstrap', '--external', f'files={self.shared}')
        self.cli('apply', '--item', 'files')
        return self.root / 'installed/files'

    def test_git_collection_is_explicit_and_whole_checkout_publication_remains(self):
        copy = self.install()
        (copy / 'SKILL.md').write_text('# Copy edit\n', encoding='utf-8')
        self.cli('publish', 'one')
        self.assertEqual((self.checkout / 'skill/SKILL.md').read_text(), '# Skill\n')
        (self.checkout / 'unrelated.txt').write_text('Include as before', encoding='utf-8')
        report = self.cli('publish', 'one', '--from-copy', '-m', 'Copy edits')[0]
        self.assertEqual(report['status'], 'published')
        self.assertTrue(report['collection'][0]['changed'])
        self.assertEqual(self.git(self.remote, 'show', 'main:skill/SKILL.md'), '# Copy edit')
        self.assertEqual(self.git(self.remote, 'show', 'main:unrelated.txt'), 'Include as before')
        self.assertEqual((self.root / 'installed/two/SKILL.md').read_text(), '# Skill\n')
        record = self.manager().state.data['items']['one']
        self.assertEqual(record['hash'], fingerprint(copy))
        self.assertFalse(self.cli('publish', 'one', '--from-copy')[0]['collection'][0]['changed'])

    def test_missing_message_refuses_before_collecting(self):
        copy = self.install()
        (copy / 'SKILL.md').write_text('# Edit\n', encoding='utf-8')
        before = (self.checkout / 'skill/SKILL.md').read_bytes()
        report = self.cli('publish', 'one', '--from-copy', code=1)[0]
        self.assertIn('--message', report['error'])
        self.assertEqual((self.checkout / 'skill/SKILL.md').read_bytes(), before)

    def test_preview_is_offline_and_preserves_copy_source_index_and_state(self):
        copy = self.install()
        (copy / 'added.txt').write_text('Added', encoding='utf-8')
        source = fingerprint(self.checkout / 'skill')
        index = (self.checkout / '.git/index').read_bytes()
        state = self.manager().state.path.read_bytes()
        self.remote.rename(self.root / 'offline.git')
        with patch.object(Git, 'fetch', side_effect=AssertionError('Preview fetched')):
            report = self.cli('publish', 'one', '--from-copy', '--dry-run')[0]
        self.assertEqual(report['status'], 'planned')
        self.assertIn('added.txt', report['collection'][0]['changes'])
        self.assertEqual(fingerprint(self.checkout / 'skill'), source)
        self.assertEqual((self.checkout / '.git/index').read_bytes(), index)
        self.assertEqual(self.manager().state.path.read_bytes(), state)

    def test_two_changed_copies_must_agree_before_any_source_write(self):
        first = self.install()
        (first / 'SKILL.md').write_text('# First', encoding='utf-8')
        (self.root / 'installed/two/SKILL.md').write_text('# Second', encoding='utf-8')
        report = self.cli('publish', 'one', 'two', '--from-copy', '-m', 'Reject', code=1)[0]
        self.assertIn('conflicting', report['error'].lower())
        self.assertEqual((self.checkout / 'skill/SKILL.md').read_text(), '# Skill\n')

    def test_identical_changed_copies_share_collection_and_advance_both_baselines(self):
        self.install()
        for name in ('one', 'two'):
            (self.root / f'installed/{name}/SKILL.md').write_text('# Same', encoding='utf-8')
        report = self.cli('publish', 'one', 'two', '--from-copy', '-m', 'Same')[0]
        self.assertEqual(report['status'], 'published')
        for name in ('one', 'two'):
            self.assertEqual(self.manager().state.data['items'][name]['hash'],
                             fingerprint(self.root / 'installed' / name))

    def test_source_only_changes_leave_copy_and_its_baseline_unchanged(self):
        copy = self.install()
        baseline = self.manager().state.data['items']['one']['hash']
        (self.checkout / 'skill/SKILL.md').write_text('# Source edit', encoding='utf-8')
        report = self.cli('publish', 'one', '--from-copy', '-m', 'Source')[0]
        self.assertFalse(report['collection'][0]['changed'])
        self.assertTrue(report['collection'][0]['stale'])
        self.assertEqual((copy / 'SKILL.md').read_text(), '# Skill\n')
        self.assertEqual(self.manager().state.data['items']['one']['hash'], baseline)

    def test_equal_copy_and_source_after_manual_resolution_refresh_baseline(self):
        copy = self.install()
        for path in (copy / 'SKILL.md', self.checkout / 'skill/SKILL.md'):
            path.write_text('# Resolved', encoding='utf-8')
        report = self.cli('publish', 'one', '--from-copy', '-m', 'Resolved')[0]
        self.assertFalse(report['collection'][0]['changed'])
        self.assertEqual(self.manager().state.data['items']['one']['hash'], fingerprint(copy))

    def test_conflicts_report_paths_and_git_arguments_without_launching_tools(self):
        copy = self.install()
        (copy / 'SKILL.md').write_text('# Local', encoding='utf-8')
        (self.checkout / 'skill/SKILL.md').write_text('# Shared', encoding='utf-8')
        previous = self.manager().state.path.read_bytes()
        report = self.cli('publish', 'one', '--from-copy', '-m', 'Reject', code=1)[0]
        self.assertEqual(report['status'], 'failed')
        conflict = report['collection'][0]
        self.assertTrue(conflict['conflict'])
        self.assertEqual(conflict['copy'], str(copy))
        self.assertEqual(conflict['source'], str(self.checkout / 'skill'))
        self.assertEqual(conflict['compare'][:4], ['git', 'difftool', '--no-index', '--'])
        self.assertEqual(self.manager().state.path.read_bytes(), previous)
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            code = main(['--config', str(self.config), 'publish', 'one', '--from-copy', '-m', 'Reject'])
        self.assertEqual(code, 1)
        self.assertEqual(output.getvalue(), format_report([report]) + '\n')

    def test_remote_behind_refuses_before_collection_and_index_changes(self):
        copy = self.install()
        (copy / 'SKILL.md').write_text('# Copy edit', encoding='utf-8')
        (self.seed / 'upstream').write_text('Remote change', encoding='utf-8')
        self.commit(self.seed)
        self.git(self.seed, 'push', 'origin', 'main')
        before = (self.checkout / '.git/index').read_bytes()
        report = self.cli('publish', 'one', '--from-copy', '-m', 'Reject', code=1)[0]
        self.assertIn('history', report['error'])
        self.assertEqual((self.checkout / 'skill/SKILL.md').read_text(), '# Skill\n')
        self.assertEqual((self.checkout / '.git/index').read_bytes(), before)

    def test_failed_push_keeps_collected_content_commit_and_new_baseline_for_retry(self):
        copy = self.install()
        (copy / 'SKILL.md').write_text('# Retry', encoding='utf-8')
        run = Git.run
        def fail_push(git, path, *args, **kwargs):
            if 'push' in args:
                raise Error('Simulated push failure')
            return run(git, path, *args, **kwargs)
        with patch.object(Git, 'run', fail_push):
            report = self.cli('publish', 'one', '--from-copy', '-m', 'Retry', code=1)[0]
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(report['collection_complete'])
        self.assertEqual((self.checkout / 'skill/SKILL.md').read_text(), '# Retry')
        self.assertEqual(self.manager().state.data['items']['one']['hash'], fingerprint(copy))
        report = self.cli('publish', 'one', '--from-copy')[0]
        self.assertEqual(report['status'], 'published')
        self.assertEqual(self.git(self.remote, 'show', 'main:skill/SKILL.md'), '# Retry')

    def test_uninstalled_detached_and_redirected_copies_are_refused(self):
        self.assertEqual(self.cli('publish', 'one', '--from-copy', '-m', 'Reject', code=1)[0]['status'], 'failed')
        copy = self.install()
        self.cli('detach', 'one')
        self.assertIn('detached', self.cli('publish', 'one', '--from-copy', '-m', 'Reject', code=1)[0]['error'])
        self.cli('apply', '--item', 'one', '--reattach', '--adopt')
        try:
            (copy / 'redirect').symlink_to(self.seed / 'AGENTS.md')
        except OSError:
            self.skipTest('Symbolic links unavailable')
        self.assertEqual(self.cli('publish', 'one', '--from-copy', '-m', 'Reject', code=1)[0]['status'], 'failed')

    def test_external_collection_adds_deletes_and_preserves_backup_without_git(self):
        copy = self.external()
        (copy / 'first.txt').unlink()
        (copy / 'empty').mkdir()
        (copy / 'new name.txt').write_text('New', encoding='utf-8')
        self.assertEqual(self.cli('publish', 'files', code=1)[0]['status'], 'failed')
        with patch.object(Git, 'run', side_effect=AssertionError('External used Git')):
            report = self.cli('publish', 'files', '--from-copy')[0]
        self.assertEqual(report['status'], 'published')
        self.assertFalse(report['transport_complete'])
        self.assertFalse((self.shared / 'first.txt').exists())
        self.assertTrue((self.shared / 'empty').is_dir())
        self.assertEqual((self.shared / 'new name.txt').read_text(), 'New')
        backup = Path(report['collection_backup'])
        self.assertTrue(any(p.read_text() == 'First\n' for p in backup.rglob('*') if p.is_file()))
        self.assertEqual(self.manager().state.data['items']['files:directory']['hash'], fingerprint(copy))
        self.assertEqual(fingerprint(self.shared), fingerprint(copy))

    def test_external_link_is_still_unsupported(self):
        try:
            self.external(mode='link')
        except AssertionError as exc:
            if 'symbolic link' in str(exc):
                self.skipTest('Symbolic links unavailable')
            raise
        self.assertEqual(self.cli('publish', 'files', '--from-copy', code=1)[0]['status'], 'failed')

    def test_git_root_collection_preserves_git_database_and_ignored_payloads(self):
        self.document['directories'] = {'root': {'source': 'shared', 'install': {'root': 'skills', 'mode': 'copy'}}}
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')
        self.cli('bootstrap', '--item', 'root')
        (self.checkout / '.gitignore').write_text('cache/\n', encoding='utf-8')
        self.commit(self.checkout)
        (self.checkout / 'cache').mkdir()
        (self.checkout / 'cache/value').write_text('Cache', encoding='utf-8')
        self.cli('apply', '--item', 'root')
        copy = self.root / 'installed/root'
        (copy / 'AGENTS.md').write_text('# New root', encoding='utf-8')
        (copy / 'cache/value').write_text('Edited cache', encoding='utf-8')
        config = (self.checkout / '.git/config').read_bytes()
        report = self.cli('publish', 'root', '--from-copy', '-m', 'Root')[0]
        self.assertEqual(report['status'], 'published')
        self.assertEqual((self.checkout / '.git/config').read_bytes(), config)
        self.assertEqual((self.checkout / 'cache/value').read_text(), 'Edited cache')
        self.assertEqual(self.git(self.remote, 'show', 'main:AGENTS.md'), '# New root')
        self.assertFalse((copy / '.git').exists())

    def test_collection_failure_restores_source_and_baseline(self):
        copy = self.external()
        (copy / 'first.txt').write_text('Edited', encoding='utf-8')
        (copy / 'new.txt').write_text('New', encoding='utf-8')
        before = fingerprint(self.shared)
        items = deepcopy(self.manager().state.data['items'])
        from agent_env_man import copy_publication
        replace = copy_publication.os.replace
        def fail_stage(source, target):
            if Path(source).parent.name == 'stages' and Path(target) == self.shared / 'new.txt':
                raise OSError('Simulated source replacement failure')
            return replace(source, target)
        with patch.object(copy_publication.os, 'replace', fail_stage):
            report = self.cli('publish', 'files', '--from-copy', code=1)[0]
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(fingerprint(self.shared), before)
        self.assertEqual(self.manager().state.data['items'], items)
        self.assertIsNone(self.manager().state.data['pending'])
        self.assertTrue(self.cli('publish', 'files', '--from-copy')[0]['collection_complete'])

    def test_interrupted_collection_is_recovered_without_discarding_later_edits(self):
        copy = self.external()
        (copy / 'first.txt').write_text('Edited', encoding='utf-8')
        from agent_env_man import copy_publication
        replace = copy_publication.os.replace
        def interrupt_stage(source, target):
            if Path(source).parent.name == 'stages' and Path(target) == self.shared / 'first.txt':
                raise KeyboardInterrupt('Interrupted after backup')
            return replace(source, target)
        with patch.object(copy_publication.os, 'replace', interrupt_stage):
            with self.assertRaises(KeyboardInterrupt):
                self.manager().publish(['files'], from_copy=True)
        self.assertIsNotNone(self.manager().state.data['pending'])
        (self.shared / 'first.txt').write_text('Later user edit', encoding='utf-8')
        self.assertIn('Recovery stopped', self.cli('recover', code=1))
        self.assertEqual((self.shared / 'first.txt').read_text(), 'Later user edit')
        (self.shared / 'first.txt').unlink()
        self.cli('recover')
        self.assertEqual((self.shared / 'first.txt').read_text(), 'First\n')
        self.assertIsNone(self.manager().state.data['pending'])

    def test_collection_state_commit_failure_rolls_back_all_source_changes(self):
        copy = self.external()
        (copy / 'first.txt').write_text('Edited', encoding='utf-8')
        before = fingerprint(self.shared)
        save = State.save
        def fail_commit(state):
            if state.data['pending'] is None and fingerprint(self.shared) != before:
                raise OSError('Simulated ownership commit failure')
            return save(state)
        with patch.object(State, 'save', fail_commit):
            self.cli('publish', 'files', '--from-copy', code=1)
        self.assertEqual(fingerprint(self.shared), before)
        self.assertIsNone(self.manager().state.data['pending'])

    def test_overlapping_source_payloads_agree_or_fail_before_writing(self):
        copy = self.external()
        (self.shared / 'nested').mkdir()
        (self.shared / 'nested/value.txt').write_text('Original', encoding='utf-8')
        self.document['directories']['nested'] = {'source': 'files', 'subdir': 'nested',
                                                'install': {'root': 'skills', 'mode': 'copy'}}
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')
        self.cli('apply', '--item', 'files', '--item', 'nested')
        nested = self.root / 'installed/nested'
        (copy / 'nested/value.txt').write_text('Parent edit', encoding='utf-8')
        (nested / 'value.txt').write_text('Child edit', encoding='utf-8')
        report = self.cli('publish', 'files', 'nested', '--from-copy', code=1)[0]
        self.assertTrue(all(p['conflict'] for p in report['collection']))
        self.assertEqual((self.shared / 'nested/value.txt').read_text(), 'Original')
        (nested / 'value.txt').write_text('Parent edit', encoding='utf-8')
        report = self.cli('publish', 'files', 'nested', '--from-copy')[0]
        self.assertTrue(report['collection_complete'])
        for name, path in [('files:directory', copy), ('nested:directory', nested)]:
            self.assertEqual(self.manager().state.data['items'][name]['hash'], fingerprint(path))

    def test_copy_changed_while_staging_preserves_source_and_baseline(self):
        copy = self.external()
        (copy / 'first.txt').write_text('Edited', encoding='utf-8')
        before = fingerprint(self.shared)
        items = deepcopy(self.manager().state.data['items'])
        from agent_env_man import copy_publication
        copy_payload = copy_publication.copy_payload
        def changing_copy(source, target, **kwargs):
            copy_payload(source, target, **kwargs)
            (copy / 'first.txt').write_text('Changed during staging', encoding='utf-8')
        with patch.object(copy_publication, 'copy_payload', changing_copy):
            report = self.cli('publish', 'files', '--from-copy', code=1)[0]
        self.assertIn('copy changed', report['error'])
        self.assertEqual(fingerprint(self.shared), before)
        self.assertEqual(self.manager().state.data['items'], items)
        self.assertIsNone(self.manager().state.data['pending'])

    @unittest.skipIf(os.name == 'nt', 'POSIX executable bits')
    def test_root_and_file_executable_changes_are_collected_and_recoverable(self):
        copy = self.external()
        os.chmod(copy, 0o700)
        os.chmod(copy / 'first.txt', 0o755)
        report = self.cli('publish', 'files', '--from-copy')[0]
        self.assertTrue(report['collection_complete'])
        self.assertEqual(fingerprint(self.shared), fingerprint(copy))

    def test_collection_groups_have_independent_outcomes(self):
        copy = self.external()
        other = self.root / 'other source'
        other.mkdir()
        (other / 'value.txt').write_text('Other original', encoding='utf-8')
        self.document['sources']['other'] = {'type': 'external'}
        self.document['directories']['other'] = {'source': 'other', 'install': {'root': 'skills', 'mode': 'copy'}}
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')
        self.cli('bootstrap', '--external', f'other={other}')
        self.cli('apply', '--item', 'other')
        (copy / 'first.txt').write_text('Copy conflict', encoding='utf-8')
        (self.shared / 'first.txt').write_text('Source conflict', encoding='utf-8')
        (self.root / 'installed/other/value.txt').write_text('Other edit', encoding='utf-8')
        report = self.cli('publish', 'files', 'other', '--from-copy', code=1)
        self.assertEqual([r['status'] for r in report], ['failed', 'published'])
        self.assertEqual((other / 'value.txt').read_text(), 'Other edit')
        self.assertEqual((self.shared / 'first.txt').read_text(), 'Source conflict')


if __name__ == '__main__':
    unittest.main()

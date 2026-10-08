"""Explicit reverse collection preserves copy baselines and publication boundaries."""

from copy import deepcopy
import io
from contextlib import redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man.cli import main
from agent_env_man.git_source import Git
from agent_env_man.manager import Manager
from agent_env_man.model import Config, Error
from agent_env_man.storage import State, fingerprint
import test_publish as publication_tests
import test_skill_catalog as skill_tests


class CopyPublication(unittest.TestCase):
    setUp = publication_tests.Publication.setUp
    git = publication_tests.Publication.git
    commit = publication_tests.Publication.commit
    cli = publication_tests.Publication.cli
    require_links = skill_tests.SkillCatalog.require_links

    def root_copy_with_linked_skill(self):
        self.require_links()
        self.document['skills']['two']['install']['mode'] = 'link'
        self.document['directories'] = {
            'root': {'source': 'shared', 'install': {'root': 'skills', 'mode': 'copy'}}}
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')
        self.cli('bootstrap')
        self.cli('apply', '--item', 'root', '--item', 'two')
        return self.root / 'installed/root'

    def test_collection_preserves_declared_and_orphaned_live_skill_requirements(self):
        copy = self.root_copy_with_linked_skill()
        (copy / 'skill/SKILL.md').unlink()
        source = fingerprint(self.checkout, exclude_git=True)
        state = self.manager().state.path.read_bytes()
        index = (self.checkout / '.git/index').read_bytes()
        revision = self.git(self.checkout, 'rev-parse', 'HEAD')
        for orphaned in (False, True):
            if orphaned:
                del self.document['skills']['two']
                self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')
            for preview in (True, False):
                with self.subTest(orphaned=orphaned, preview=preview):
                    args = ('--dry-run',) if preview else ('-m', 'Reject invalid skill')
                    with patch.object(Git, 'publication_preflight', side_effect=AssertionError('invalid collection contacted remote')):
                        report = self.cli('publish', 'root', '--from-copy', *args, code=1)[0]
                    self.assertIn('two', report['error'])
                    self.assertIn('detach', report['error'])
                    self.assertEqual(fingerprint(self.checkout, exclude_git=True), source)
                    self.assertEqual(self.manager().state.path.read_bytes(), state)
                    self.assertEqual((self.checkout / '.git/index').read_bytes(), index)
                    self.assertEqual(self.git(self.checkout, 'rev-parse', 'HEAD'), revision)
                    self.assertTrue((self.root / 'installed/two/SKILL.md').is_file())
                    self.assertFalse(list(self.checkout.parent.glob('.aem-collection-*')))

    def test_detaching_link_allows_intentional_descriptor_removal(self):
        copy = self.root_copy_with_linked_skill()
        self.cli('detach', 'two')
        (copy / 'skill/SKILL.md').unlink()
        self.assertEqual(self.cli('publish', 'root', '--from-copy', '-m', 'Remove descriptor')[0]['status'], 'published')
        self.assertFalse((self.checkout / 'skill/SKILL.md').exists())
        self.assertEqual((self.root / 'installed/two/SKILL.md').read_text(), '# Skill\n')

    def test_collection_allows_content_edits_and_nonessential_deletions_through_links(self):
        (self.checkout / 'skill/notes.txt').write_text('Optional', encoding='utf-8')
        self.commit(self.checkout)
        copy = self.root_copy_with_linked_skill()
        (copy / 'skill/SKILL.md').write_text('', encoding='utf-8')
        (copy / 'skill/notes.txt').unlink()
        self.assertEqual(self.cli('publish', 'root', '--from-copy', '-m', 'Edit content')[0]['status'], 'published')
        self.assertEqual((self.root / 'installed/two/SKILL.md').read_text(), '')
        self.assertFalse((self.root / 'installed/two/notes.txt').exists())

    def test_external_collection_preserves_live_directory_kind(self):
        self.require_links()
        copy = self.external()
        (self.shared / 'nested').mkdir()
        (self.shared / 'nested/value.txt').write_text('Keep', encoding='utf-8')
        self.document['directories']['nested'] = {
            'source': 'files', 'subdir': 'nested', 'install': {'root': 'skills'}}
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')
        self.cli('apply', '--item', 'files', '--item', 'nested')
        source = fingerprint(self.shared)
        state = self.manager().state.path.read_bytes()
        shutil.rmtree(copy / 'nested')
        for replacement in ('missing', 'file'):
            if replacement == 'file':
                (copy / 'nested').write_text('Wrong kind', encoding='utf-8')
            with self.subTest(replacement=replacement):
                report = self.cli('publish', 'files', '--from-copy', code=1)[0]
                self.assertIn('nested:directory', report['error'])
                self.assertEqual(fingerprint(self.shared), source)
                self.assertEqual(self.manager().state.path.read_bytes(), state)

    def test_child_collection_preserves_ancestor_instruction_entry(self):
        self.require_links()
        self.document['instructions']['personal']['entry'] = 'skill/SKILL.md'
        self.document['directories'] = {'child': {
            'source': 'shared', 'subdir': 'skill', 'install': {'root': 'skills', 'mode': 'copy'}}}
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')
        self.cli('bootstrap')
        self.cli('apply', '--item', 'child', '--item', 'personal:bundle')
        (self.root / 'installed/child/SKILL.md').unlink()
        source = fingerprint(self.checkout, exclude_git=True)
        state = self.manager().state.path.read_bytes()
        report = self.cli('publish', 'child', '--from-copy', '-m', 'Reject missing entry', code=1)[0]
        self.assertIn('personal:bundle', report['error'])
        self.assertEqual(fingerprint(self.checkout, exclude_git=True), source)
        self.assertEqual(self.manager().state.path.read_bytes(), state)

    def test_collection_preserves_standalone_instruction_file_link(self):
        self.require_links()
        self.document['directories'] = {
            'root': {'source': 'shared', 'install': {'root': 'skills', 'mode': 'copy'}}}
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')
        self.cli('bootstrap')
        self.cli('apply', '--item', 'root', '--item', 'personal:entry')
        self.cli('detach', 'personal:bundle')
        copy = self.root / 'installed/root'
        (copy / 'AGENTS.md').unlink()
        (copy / 'AGENTS.md').mkdir()
        state = self.manager().state.path.read_bytes()
        report = self.cli('publish', 'root', '--from-copy', '-m', 'Reject wrong entry kind', code=1)[0]
        self.assertIn('personal:entry', report['error'])
        self.assertEqual((self.root / 'agent/AGENTS.md').read_text(), '# Instructions\n')
        self.assertEqual(self.manager().state.path.read_bytes(), state)

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
        text = output.getvalue()
        self.assertIn('failed', text)
        self.assertIn(conflict['copy'], text)
        self.assertIn(conflict['source'], text)
        for argument in conflict['compare']:
            self.assertIn(argument, text)
        self.assertEqual(self.manager().state.path.read_bytes(), previous)

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

    def test_changed_ownership_and_invalid_baselines_refuse_collection_without_writes(self):
        copy = self.external()
        (copy / 'first.txt').write_text('Copy edit', encoding='utf-8')
        state = self.manager().state
        original = deepcopy(state.data['items']['files:directory'])
        source = fingerprint(self.shared)
        mutations = (
            ('source', str(self.root / 'different source'), 'detach before reconfiguration'),
            ('target', str(self.root / 'different target'), 'detach before reconfiguration'),
            ('mode', 'link', 'detach before reconfiguration'),
            ('kind', 'skill', 'ownership changed'),
            ('hash', None, 'no saved baseline'),
            ('exclude_git', False, 'payload boundary changed'),
        )
        for field, value, diagnostic in mutations:
            with self.subTest(field=field):
                state.data['items']['files:directory'] = {**original, field: value}
                state.save()
                before = state.path.read_bytes()
                for preview in (True, False):
                    args = ('--dry-run',) if preview else ()
                    report = self.cli('publish', 'files', '--from-copy', *args, code=1)[0]
                    self.assertIn(diagnostic, report['error'])
                    self.assertEqual(fingerprint(self.shared), source)
                    self.assertEqual((copy / 'first.txt').read_text(), 'Copy edit')
                    self.assertEqual(state.path.read_bytes(), before)
                    self.assertFalse(list(self.shared.parent.glob('.aem-collection-*')))
        state.data['items']['files:directory'] = original
        state.save()
        self.assertTrue(self.cli('publish', 'files', '--from-copy')[0]['collection_complete'])

    def test_missing_or_file_replacement_of_copy_is_preserved_and_refused(self):
        copy = self.external()
        source = fingerprint(self.shared)
        state = self.manager().state.path.read_bytes()
        shutil.rmtree(copy)
        for replacement in ('missing', 'file'):
            with self.subTest(replacement=replacement):
                if replacement == 'file':
                    copy.write_text('User replacement', encoding='utf-8')
                report = self.cli('publish', 'files', '--from-copy', code=1)[0]
                self.assertIn('copy directory is missing', report['error'])
                self.assertEqual(fingerprint(self.shared), source)
                self.assertEqual(self.manager().state.path.read_bytes(), state)
                if replacement == 'file':
                    self.assertEqual(copy.read_text(), 'User replacement')
                else:
                    self.assertFalse(copy.exists())

    def test_skill_copy_requires_descriptor_before_remote_preflight(self):
        copy = self.install()
        (copy / 'SKILL.md').unlink()
        source = fingerprint(self.checkout, exclude_git=True)
        state = self.manager().state.path.read_bytes()
        with patch.object(Git, 'publication_preflight', side_effect=AssertionError('invalid copy contacted remote')):
            report = self.cli('publish', 'one', '--from-copy', '-m', 'Reject', code=1)[0]
        self.assertIn('requires SKILL.md', report['error'])
        self.assertEqual(fingerprint(self.checkout, exclude_git=True), source)
        self.assertEqual(self.manager().state.path.read_bytes(), state)

    def test_source_edit_during_staging_is_preserved_before_collection_starts(self):
        copy = self.external()
        (copy / 'first.txt').write_text('Copy edit', encoding='utf-8')
        state = self.manager().state.path.read_bytes()
        from agent_env_man import copy_publication
        copy_payload = copy_publication.copy_payload

        def concurrent_edit(source, target, **kwargs):
            copy_payload(source, target, **kwargs)
            (self.shared / 'first.txt').write_text('Concurrent source edit', encoding='utf-8')

        with patch.object(copy_publication, 'copy_payload', concurrent_edit):
            report = self.cli('publish', 'files', '--from-copy', code=1)[0]
        self.assertIn('source changed during collection', report['error'])
        self.assertEqual((self.shared / 'first.txt').read_text(), 'Concurrent source edit')
        self.assertEqual((copy / 'first.txt').read_text(), 'Copy edit')
        self.assertEqual(self.manager().state.path.read_bytes(), state)
        self.assertFalse(list(self.shared.parent.glob('.aem-collection-*')))

    def test_damaged_stage_is_rejected_without_source_or_baseline_changes(self):
        copy = self.external()
        (copy / 'first.txt').write_text('Copy edit', encoding='utf-8')
        source = fingerprint(self.shared)
        state = self.manager().state.path.read_bytes()
        from agent_env_man import copy_publication
        copy_payload = copy_publication.copy_payload

        def damaged_stage(source, target, **kwargs):
            copy_payload(source, target, **kwargs)
            target.write_text('Damaged stage', encoding='utf-8')

        with patch.object(copy_publication, 'copy_payload', damaged_stage):
            report = self.cli('publish', 'files', '--from-copy', code=1)[0]
        self.assertIn('copy changed while staging', report['error'])
        self.assertEqual(fingerprint(self.shared), source)
        self.assertEqual((copy / 'first.txt').read_text(), 'Copy edit')
        self.assertEqual(self.manager().state.path.read_bytes(), state)
        self.assertFalse(list(self.shared.parent.glob('.aem-collection-*')))
        self.assertTrue(self.cli('publish', 'files', '--from-copy')[0]['collection_complete'])

    def test_copy_edit_after_source_replacement_rolls_back_and_can_retry(self):
        copy = self.external()
        (copy / 'first.txt').write_text('Copy edit', encoding='utf-8')
        source = fingerprint(self.shared)
        items = deepcopy(self.manager().state.data['items'])
        from agent_env_man import copy_publication
        replace = copy_publication.os.replace

        def concurrent_edit(source, target):
            result = replace(source, target)
            if Path(source).parent.name == 'stages' and Path(target) == self.shared / 'first.txt':
                (copy / 'first.txt').write_text('Later copy edit', encoding='utf-8')
            return result

        with patch.object(copy_publication.os, 'replace', concurrent_edit):
            report = self.cli('publish', 'files', '--from-copy', code=1)[0]
        self.assertIn('copy changed before collection state commit', report['error'])
        self.assertEqual(fingerprint(self.shared), source)
        self.assertEqual((copy / 'first.txt').read_text(), 'Later copy edit')
        self.assertEqual(self.manager().state.data['items'], items)
        self.assertIsNone(self.manager().state.data['pending'])
        self.assertTrue(self.cli('publish', 'files', '--from-copy')[0]['collection_complete'])
        self.assertEqual((self.shared / 'first.txt').read_text(), 'Later copy edit')

    def test_source_edit_after_journaling_stops_recovery_until_reconciled(self):
        copy = self.external()
        (copy / 'first.txt').write_text('Copy edit', encoding='utf-8')
        items = deepcopy(self.manager().state.data['items'])
        save = State.save

        def concurrent_edit(state):
            save(state)
            if state.data['pending'] and state.data['pending'].get('operation') == 'copy-collection':
                (self.shared / 'first.txt').write_text('Concurrent source edit', encoding='utf-8')

        with patch.object(State, 'save', concurrent_edit):
            report = self.cli('publish', 'files', '--from-copy', code=1)[0]
        self.assertIn('Recovery stopped', report['error'])
        self.assertEqual((self.shared / 'first.txt').read_text(), 'Concurrent source edit')
        self.assertEqual((copy / 'first.txt').read_text(), 'Copy edit')
        self.assertEqual(self.manager().state.data['items'], items)
        self.assertIsNotNone(self.manager().state.data['pending'])
        self.assertIn('Recovery stopped', self.cli('recover', code=1))
        (self.shared / 'first.txt').write_text('First\n', encoding='utf-8')
        self.cli('recover')
        self.assertIsNone(self.manager().state.data['pending'])
        self.assertTrue(self.cli('publish', 'files', '--from-copy')[0]['collection_complete'])
        self.assertEqual((self.shared / 'first.txt').read_text(), 'Copy edit')

    def test_source_edit_after_replacement_preserves_journal_and_user_edit(self):
        copy = self.external()
        (copy / 'first.txt').write_text('Copy edit', encoding='utf-8')
        items = deepcopy(self.manager().state.data['items'])
        from agent_env_man import copy_publication
        replace = copy_publication.os.replace

        def concurrent_edit(source, target):
            result = replace(source, target)
            if Path(source).parent.name == 'stages' and Path(target) == self.shared / 'first.txt':
                Path(target).write_text('Later source edit', encoding='utf-8')
            return result

        with patch.object(copy_publication.os, 'replace', concurrent_edit):
            report = self.cli('publish', 'files', '--from-copy', code=1)[0]
        self.assertIn('Recovery stopped', report['error'])
        self.assertEqual((self.shared / 'first.txt').read_text(), 'Later source edit')
        self.assertEqual((copy / 'first.txt').read_text(), 'Copy edit')
        self.assertEqual(self.manager().state.data['items'], items)
        self.assertIsNotNone(self.manager().state.data['pending'])
        self.assertIn('Recovery stopped', self.cli('recover', code=1))
        (self.shared / 'first.txt').write_text('Copy edit', encoding='utf-8')
        self.cli('recover')
        self.assertEqual((self.shared / 'first.txt').read_text(), 'First\n')
        self.assertEqual(self.manager().state.data['items'], items)
        self.assertIsNone(self.manager().state.data['pending'])
        self.assertTrue(self.cli('publish', 'files', '--from-copy')[0]['collection_complete'])

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

    def interrupted_collection(self):
        copy = self.external()
        (copy / 'first.txt').write_text('Edited', encoding='utf-8')
        (copy / 'new.txt').write_text('New', encoding='utf-8')
        items = deepcopy(self.manager().state.data['items'])
        from agent_env_man import copy_publication
        replace = copy_publication.os.replace

        def interrupt_stage(source, target):
            if Path(source).parent.name == 'stages' and Path(target) == self.shared / 'new.txt':
                raise KeyboardInterrupt('Interrupted before adding new file')
            return replace(source, target)

        with patch.object(copy_publication.os, 'replace', interrupt_stage):
            with self.assertRaises(KeyboardInterrupt):
                self.manager().publish(['files'], from_copy=True)
        self.assertEqual((self.shared / 'first.txt').read_text(), 'Edited')
        self.assertFalse((self.shared / 'new.txt').exists())
        return copy, items

    def test_recovery_preserves_edited_stage_and_backup_before_restoring_any_source(self):
        copy, items = self.interrupted_collection()
        state = self.manager().state
        journal = state.data['pending']
        paths = [Path(journal['files'][0]['backup']), Path(journal['files'][1]['stage'])]
        for path in paths:
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_text('Later user edit', encoding='utf-8')
                before = state.path.read_bytes()
                self.assertIn('Recovery stopped', self.cli('recover', code=1))
                self.assertEqual(path.read_text(), 'Later user edit')
                self.assertEqual((self.shared / 'first.txt').read_text(), 'Edited')
                self.assertFalse((self.shared / 'new.txt').exists())
                self.assertEqual(state.path.read_bytes(), before)
                path.write_bytes(original)
        self.cli('recover')
        self.assertEqual((self.shared / 'first.txt').read_text(), 'First\n')
        self.assertEqual((copy / 'first.txt').read_text(), 'Edited')
        self.assertEqual(self.manager().state.data['items'], items)
        self.assertIsNone(self.manager().state.data['pending'])

    def test_invalid_recovery_journal_preserves_source_and_outside_files(self):
        self.interrupted_collection()
        state = self.manager().state
        original = deepcopy(state.data['pending'])
        outside = self.root / 'unrelated.txt'
        outside.write_text('Unrelated', encoding='utf-8')
        mutations = {
            'storage': lambda j: j.update(scratch=str(self.root / 'unrelated-storage')),
            'missing files': lambda j: j.update(files=None),
            'unknown entry': lambda j: j['files'][0].update(unknown=True),
            'outside target': lambda j: j['files'][0].update(target=str(outside)),
            'duplicate target': lambda j: j['files'][1].update(target=j['files'][0]['target']),
            'outside backup': lambda j: j['files'][0].update(backup=str(outside)),
            'invalid observation': lambda j: j['files'][0].update(before={'kind': 'file', 'hash': None}),
            'unknown mode': lambda j: j['modes'][0].update(unknown=True),
            'outside mode': lambda j: j['modes'][0].update(target=str(self.root)),
            'boolean mode': lambda j: j['modes'][0].update(before=True),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name):
                journal = deepcopy(original)
                mutate(journal)
                state.data['pending'] = journal
                state.save()
                before = state.path.read_bytes()
                self.assertIn('Invalid' if name != 'missing files' else 'Incomplete',
                              self.cli('recover', code=1))
                self.assertEqual(state.path.read_bytes(), before)
                self.assertEqual((self.shared / 'first.txt').read_text(), 'Edited')
                self.assertEqual(outside.read_text(), 'Unrelated')
        state.data['pending'] = original
        state.save()
        self.cli('recover')
        self.assertEqual((self.shared / 'first.txt').read_text(), 'First\n')

    def test_recovery_can_retry_interruption_while_restoring_backup(self):
        copy, items = self.interrupted_collection()
        state = self.manager().state
        backup = Path(state.data['pending']['files'][0]['backup'])
        from agent_env_man import copy_publication
        replace = copy_publication.os.replace

        def interrupt_restore(source, target):
            if Path(source).parent.name == 'stages' and Path(target) == self.shared / 'first.txt':
                raise KeyboardInterrupt('Interrupted while restoring backup')
            return replace(source, target)

        with patch.object(copy_publication.os, 'replace', interrupt_restore):
            with self.assertRaises(KeyboardInterrupt):
                self.manager().recover()
        self.assertEqual(backup.read_text(), 'First\n')
        self.assertIsNotNone(self.manager().state.data['pending'])
        self.cli('recover')
        self.assertEqual((self.shared / 'first.txt').read_text(), 'First\n')
        self.assertEqual(backup.read_text(), 'First\n')
        self.assertEqual((copy / 'new.txt').read_text(), 'New')
        self.assertEqual(self.manager().state.data['items'], items)
        self.assertIsNone(self.manager().state.data['pending'])

    def test_interruption_before_baseline_commit_removes_new_source_files_on_recovery(self):
        copy = self.external()
        (copy / 'new.txt').write_text('New', encoding='utf-8')
        items = deepcopy(self.manager().state.data['items'])
        before = fingerprint(self.shared)
        save = State.save

        def interrupt_commit(state):
            if state.data['pending'] is None and (self.shared / 'new.txt').exists():
                raise KeyboardInterrupt('Interrupted before baseline commit')
            return save(state)

        with patch.object(State, 'save', interrupt_commit):
            with self.assertRaises(KeyboardInterrupt):
                self.manager().publish(['files'], from_copy=True)
        self.assertEqual((self.shared / 'new.txt').read_text(), 'New')
        self.assertEqual(self.manager().state.data['items'], items)
        self.cli('recover')
        self.assertEqual(fingerprint(self.shared), before)
        self.assertEqual((copy / 'new.txt').read_text(), 'New')
        self.assertEqual(self.manager().state.data['items'], items)
        self.assertIsNone(self.manager().state.data['pending'])

    @unittest.skipIf(os.name == 'nt', 'POSIX directory permissions')
    def test_recovery_preserves_later_directory_permission_edits(self):
        self.interrupted_collection()
        state = self.manager().state
        original = state.data['pending']['modes'][0]['before']
        self.shared.chmod(original ^ 0o020)
        self.addCleanup(self.shared.chmod, original)
        before = state.path.read_bytes()
        self.assertIn('permissions changed', self.cli('recover', code=1))
        self.assertEqual(self.shared.stat().st_mode & 0o7777, original ^ 0o020)
        self.assertEqual((self.shared / 'first.txt').read_text(), 'Edited')
        self.assertEqual(state.path.read_bytes(), before)
        self.shared.chmod(original)
        self.cli('recover')
        self.assertEqual((self.shared / 'first.txt').read_text(), 'First\n')

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

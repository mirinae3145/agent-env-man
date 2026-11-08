"""Failure paths preserve user contents, recovery artifacts, and ownership."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man import hooks, manager as manager_module, payload_policy, setup as setup_module
from agent_env_man.model import Config
from agent_env_man.payload_links import CopyCleanupError
from agent_env_man.storage import State, fingerprint, observation
import test_copy_publication as publications
import test_payload_exclusions as exclusions
import test_setup as setups
import test_workflow as workflows


class TemporaryCases(unittest.TestCase):
    def fixture(self, kind):
        case = kind()
        self.addCleanup(case.doCleanups)
        case.setUp()
        return case

    def journal(self, case, target, backup, stage, before, after, **fields):
        state = State(Config(case.config).state_dir)
        state.data['pending'] = dict(target=str(target), backup=str(backup), stage=str(stage),
                                     before=before, after=after, **fields)
        state.save()
        return state


class RetainedEntryRecovery(TemporaryCases):
    def prepared(self):
        case = self.fixture(exclusions.PayloadExclusions)
        case.prepare()
        cache = case.target / '._DAV'
        cache.mkdir()
        (cache / 'local').write_bytes(b'unowned metadata')
        vault = case.target.with_name('.aem-retained-test')
        vault.mkdir()
        return case, cache, vault

    def recover_retained(self, case, value):
        policy = {'exclusions': [['', '**/._DAV']]}
        before = observation(case.target, **policy)
        return self.journal(case, case.target, case.target.with_name('backup-retention'),
                            case.target.with_name('.aem-stage-retention'), before, before,
                            key='cases:directory', retained=value, **policy)

    def test_invalid_retention_records_refuse_before_any_file_or_state_change(self):
        case, cache, vault = self.prepared()
        sentinel = case.root / 'outside'
        sentinel.write_bytes(b'outside must survive')
        valid = {'vault': str(vault), 'paths': ['._DAV']}
        variants = [['invalid'], {'vault': str(vault)}, dict(valid, vault=42),
                    dict(valid, vault=str(case.root / '.aem-retained-outside')),
                    dict(valid, vault=str(vault.with_name('wrong-name'))),
                    dict(valid, paths='._DAV'), dict(valid, paths=[]),
                    dict(valid, paths=['._DAV', '._DAV']), dict(valid, paths=[42]),
                    dict(valid, paths=['../outside']), dict(valid, paths=['/._DAV']),
                    dict(valid, paths=['._DAV\\local']), dict(valid, paths=['C:._DAV']),
                    dict(valid, paths=['first.md']), dict(valid, paths=['._DAV', '._DAV/local'])]
        target_before = fingerprint(case.target)
        for value in variants:
            with self.subTest(record=value):
                state = self.recover_retained(case, value)
                saved = state.path.read_bytes()
                error = case.run_cli('recover', code=1)
                self.assertRegex(error, 'Invalid excluded-entry|not excluded|Overlapping excluded-entry')
                self.assertEqual(fingerprint(case.target), target_before)
                self.assertEqual((cache / 'local').read_bytes(), b'unowned metadata')
                self.assertEqual(sentinel.read_bytes(), b'outside must survive')
                self.assertEqual(state.path.read_bytes(), saved)
                self.assertEqual(list(vault.iterdir()), [])

    def test_redirected_retention_storage_preserves_referent(self):
        case, cache, vault = self.prepared()
        case.require_links()
        outside = case.root / 'outside-vault'
        outside.mkdir()
        (outside / '0').write_bytes(b'preserve referent')
        vault.rmdir()
        vault.symlink_to(outside, target_is_directory=True)
        state = self.recover_retained(case, {'vault': str(vault), 'paths': ['._DAV']})
        saved = state.path.read_bytes()
        self.assertIn('Invalid excluded-entry recovery storage', case.run_cli('recover', code=1))
        self.assertTrue(vault.is_symlink())
        self.assertEqual((outside / '0').read_bytes(), b'preserve referent')
        self.assertEqual((cache / 'local').read_bytes(), b'unowned metadata')
        self.assertEqual(state.path.read_bytes(), saved)

    def test_invalid_saved_exclusions_preserve_recovery_contents_and_journal(self):
        case, cache, vault = self.prepared()
        for exclusions in ('invalid', [['only-prefix']], [[42, '**/._DAV']],
                           [['../outside', '**/._DAV']]):
            with self.subTest(exclusions=exclusions):
                state = self.recover_retained(case, {'vault': str(vault), 'paths': ['._DAV']})
                state.data['pending']['exclusions'] = exclusions
                state.save()
                saved = state.path.read_bytes()
                self.assertIn('Invalid saved payload exclusion', case.run_cli('recover', code=1))
                self.assertEqual(state.path.read_bytes(), saved)
                self.assertEqual((cache / 'local').read_bytes(), b'unowned metadata')
                self.assertEqual(list(vault.iterdir()), [])

    def test_rollback_refuses_duplicate_metadata_locations_and_retries_after_reconciliation(self):
        case, cache, vault = self.prepared()
        policy = {'exclusions': [['', '**/._DAV']]}
        before = observation(case.target, **policy)
        backup = case.target.with_name('backup-retention')
        shutil.copytree(case.target, backup)
        shutil.rmtree(backup / '._DAV')
        (case.target / 'nested/doc.md').write_bytes(b'incoming content')
        (vault / '0').mkdir()
        (vault / '0/local').write_bytes(b'parked original metadata')
        state = self.journal(case, case.target, backup, case.target.with_name('.aem-stage-retention'),
                             before, observation(case.target, **policy), key='cases:directory',
                             retained={'vault': str(vault), 'paths': ['._DAV']}, **policy)
        saved = state.path.read_bytes()
        self.assertIn('both recovery locations', case.run_cli('recover', code=1))
        self.assertEqual(state.path.read_bytes(), saved)
        self.assertEqual((cache / 'local').read_bytes(), b'unowned metadata')
        self.assertEqual((vault / '0/local').read_bytes(), b'parked original metadata')
        self.assertEqual((backup / 'nested/doc.md').read_text(), 'original')
        preserved = case.root / 'reconciled-metadata'
        cache.rename(preserved)
        case.run_cli('recover')
        self.assertEqual((cache / 'local').read_bytes(), b'parked original metadata')
        self.assertEqual((preserved / 'local').read_bytes(), b'unowned metadata')
        self.assertEqual((case.target / 'nested/doc.md').read_text(), 'original')
        self.assertFalse(vault.exists())
        self.assertIsNone(case.manager().state.data['pending'])

    def test_metadata_moved_during_parking_preserves_included_content_and_allows_recovery(self):
        case, cache, vault = self.prepared()
        vault.rmdir()
        (case.source / 'nested/doc.md').write_bytes(b'incoming content')
        preserved = case.root / 'concurrently-moved-metadata'
        checked_parent = payload_policy.checked_parent
        moved = False
        def moving(root, relative):
            nonlocal moved
            result = checked_parent(root, relative)
            if root == case.target and relative == '._DAV' and not moved:
                cache.rename(preserved)
                moved = True
            return result
        with patch.object(payload_policy, 'checked_parent', side_effect=moving):
            error = case.run_cli('apply', '--item', 'cases', code=1)
        self.assertTrue(moved)
        self.assertIn('missing during recovery', error)
        self.assertEqual((preserved / 'local').read_bytes(), b'unowned metadata')
        self.assertEqual((case.target / 'nested/doc.md').read_text(), 'original')
        self.assertIsNotNone(case.manager().state.data['pending'])
        preserved.rename(cache)
        case.run_cli('recover')
        self.assertEqual((cache / 'local').read_bytes(), b'unowned metadata')
        self.assertIsNone(case.manager().state.data['pending'])
        case.run_cli('apply', '--item', 'cases')
        self.assertEqual((case.target / 'nested/doc.md').read_bytes(), b'incoming content')
        self.assertEqual((cache / 'local').read_bytes(), b'unowned metadata')

    def test_conflicting_retained_entry_preserves_both_copies_until_reconciled(self):
        case, cache, vault = self.prepared()
        (vault / '0').mkdir()
        (vault / '0/local').write_bytes(b'original metadata')
        state = self.recover_retained(case, {'vault': str(vault), 'paths': ['._DAV']})
        saved = state.path.read_bytes()
        self.assertIn('would be overwritten', case.run_cli('recover', code=1))
        self.assertEqual((cache / 'local').read_bytes(), b'unowned metadata')
        self.assertEqual((vault / '0/local').read_bytes(), b'original metadata')
        self.assertEqual(state.path.read_bytes(), saved)
        shutil.rmtree(cache)
        case.run_cli('recover')
        self.assertEqual((cache / 'local').read_bytes(), b'original metadata')
        self.assertFalse(vault.exists())
        self.assertIsNone(case.manager().state.data['pending'])

    def test_missing_retained_entry_keeps_journal_for_retry(self):
        case, cache, vault = self.prepared()
        shutil.rmtree(cache)
        state = self.recover_retained(case, {'vault': str(vault), 'paths': ['._DAV']})
        saved = state.path.read_bytes()
        self.assertIn('missing during recovery', case.run_cli('recover', code=1))
        self.assertEqual(state.path.read_bytes(), saved)
        (vault / '0').mkdir()
        (vault / '0/local').write_bytes(b'recovered metadata')
        case.run_cli('recover')
        self.assertEqual((cache / 'local').read_bytes(), b'recovered metadata')
        self.assertIsNone(case.manager().state.data['pending'])

    def test_excluded_entry_appearing_during_preservation_survives_failed_apply(self):
        case, cache, vault = self.prepared()
        vault.rmdir()
        (case.source / 'nested/doc.md').write_text('incoming', encoding='utf-8')
        replace = payload_policy.os.replace
        created = False
        def racing(source, destination, *args, **kwargs):
            nonlocal created
            result = replace(source, destination, *args, **kwargs)
            if Path(source) == cache and not created:
                created = True
                extra = case.target / 'nested/._DAV'
                extra.mkdir()
                (extra / 'late').write_bytes(b'concurrent metadata')
            return result
        with patch.object(payload_policy.os, 'replace', side_effect=racing):
            self.assertIn('changed during preservation', case.run_cli('apply', '--item', 'cases', code=1))
        self.assertTrue(created)
        self.assertEqual((case.target / 'nested/doc.md').read_text(), 'original')
        self.assertEqual((cache / 'local').read_bytes(), b'unowned metadata')
        self.assertEqual((case.target / 'nested/._DAV/late').read_bytes(), b'concurrent metadata')
        self.assertIsNone(case.manager().state.data['pending'])


    def test_permission_failure_restoring_metadata_keeps_contents_and_journal_for_retry(self):
        case, cache, vault = self.prepared()
        os.replace(cache, vault / '0')
        state = self.recover_retained(case, {'vault': str(vault), 'paths': ['._DAV']})
        saved = state.path.read_bytes()
        replace = payload_policy.os.replace
        def denied(source, destination, *args, **kwargs):
            if Path(source) == vault / '0':
                raise PermissionError('metadata restoration denied')
            return replace(source, destination, *args, **kwargs)
        with patch.object(payload_policy.os, 'replace', side_effect=denied):
            self.assertIn('metadata restoration denied', case.run_cli('recover', code=1))
        self.assertEqual((vault / '0/local').read_bytes(), b'unowned metadata')
        self.assertFalse(cache.exists())
        self.assertEqual(state.path.read_bytes(), saved)
        case.run_cli('recover')
        self.assertEqual((cache / 'local').read_bytes(), b'unowned metadata')
        self.assertIsNone(case.manager().state.data['pending'])

    def test_collection_restore_denial_preserves_metadata_baselines_and_recovery_artifacts(self):
        case = self.fixture(exclusions.PayloadExclusions)
        case.prepare()
        (case.target / 'nested/doc.md').write_text('local collected edit', encoding='utf-8')
        items = deepcopy(case.manager().state.data['items'])
        replace = payload_policy.os.replace
        def denied(source, destination, *args, **kwargs):
            if Path(source).parent.name.startswith('.aem-retained-'):
                raise PermissionError('metadata restoration denied')
            return replace(source, destination, *args, **kwargs)
        with patch.object(payload_policy.os, 'replace', side_effect=denied):
            report = case.run_cli('publish', 'cases', '--from-copy', code=1)[0]
        self.assertIn('metadata restoration denied', report['error'])
        state = case.manager().state
        self.assertEqual(state.data['items'], items)
        self.assertEqual(state.data['pending']['operation'], 'copy-collection')
        self.assertTrue(Path(state.data['pending']['scratch']).is_dir())
        entry, = state.data['pending']['files']
        vault = Path(entry['retained']['vault'])
        self.assertEqual((vault / '0/metadata').read_text(), 'source metadata')
        self.assertEqual((case.source / 'nested/doc.md').read_text(), 'original')
        self.assertEqual((case.target / 'nested/doc.md').read_text(), 'local collected edit')
        case.run_cli('recover')
        self.assertEqual((case.source / 'nested/._DAV/metadata').read_text(), 'source metadata')
        self.assertEqual(case.manager().state.data['items'], items)
        self.assertIsNone(case.manager().state.data['pending'])
        case.run_cli('publish', 'cases', '--from-copy')
        self.assertEqual((case.source / 'nested/doc.md').read_text(), 'local collected edit')
        self.assertEqual((case.source / 'nested/._DAV/metadata').read_text(), 'source metadata')


class InstallationRecovery(TemporaryCases):
    def test_source_edit_after_planning_does_not_replace_installed_copy(self):
        case = self.fixture(workflows.Workflow)
        target = case.installed_copy()
        case.publish_skill_change()
        case.run_cli('update')
        state_path = State(Config(case.config).state_dir).path
        saved, installed = state_path.read_bytes(), observation(target)
        plan = manager_module.Manager.plan
        changed = []
        def race(manager, item, **options):
            result = plan(manager, item, **options)
            entry = item.source / 'SKILL.md'
            entry.write_bytes(b'concurrent source edit\n')
            changed.append(entry)
            return result
        with patch.object(manager_module.Manager, 'plan', new=race):
            self.assertIn('source changed after preflight', case.run_cli('apply', '--item', 'report', code=1))
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0].read_bytes(), b'concurrent source edit\n')
        self.assertEqual(observation(target), installed)
        self.assertEqual(state_path.read_bytes(), saved)
        self.assertFalse(list(target.parent.glob('.aem-stage-*')))

    def test_redirected_backup_storage_cannot_receive_installed_contents(self):
        case = self.fixture(workflows.Workflow)
        case.require_links()
        target = case.installed_copy()
        case.publish_skill_change()
        case.run_cli('update')
        state = State(Config(case.config).state_dir)
        backups = state.path.parent / 'skill-backups'
        backups.rmdir()
        outside = case.root / 'unowned-backups'
        outside.mkdir()
        sentinel = outside / 'sentinel'
        sentinel.write_bytes(b'preserve outside\n')
        backups.symlink_to(outside, target_is_directory=True)
        saved, installed = state.path.read_bytes(), observation(target)
        self.assertIn('backup storage redirects', case.run_cli('apply', '--item', 'report', code=1))
        self.assertEqual(list(outside.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b'preserve outside\n')
        self.assertEqual(observation(target), installed)
        self.assertEqual(state.path.read_bytes(), saved)

    def interrupted_skill(self):
        case = self.fixture(workflows.Workflow)
        target = case.installed_copy()
        before = observation(target)
        backup = Config(case.config).state_dir / 'skill-backups/report-interrupted'
        backup.parent.mkdir(exist_ok=True)
        shutil.copytree(target, backup)
        (target / 'SKILL.md').write_text('replacement', encoding='utf-8')
        state = self.journal(case, target, backup, target.with_name('.aem-stage-interrupted'),
                             before, observation(target), operation='skill-replacement', key='report')
        return case, target, backup, state

    def test_edited_stage_blocks_recovery_before_target_or_backup_changes(self):
        case, target, backup, state = self.interrupted_skill()
        stage = Path(state.data['pending']['stage'])
        shutil.copytree(target, stage)
        (stage / 'SKILL.md').write_bytes(b'user edit in stage\n')
        saved = state.path.read_bytes()
        originals = {p: observation(p) for p in (target, backup, stage)}
        self.assertIn('staged content changed', case.run_cli('recover', code=1))
        self.assertEqual({p: observation(p) for p in originals}, originals)
        self.assertEqual(state.path.read_bytes(), saved)
        (stage / 'SKILL.md').write_text('replacement', encoding='utf-8')
        case.run_cli('recover')
        self.assertEqual(observation(target), originals[backup])
        self.assertIsNone(State(state.path.parent).data['pending'])

    def test_recovery_rejects_invalid_paths_and_observations_without_touching_backup(self):
        case, target, backup, state = self.interrupted_skill()
        pending = deepcopy(state.data['pending'])
        before_target, before_backup = observation(target), observation(backup)
        variants = [dict(pending, stage=str(target)), dict(pending, stage=str(case.root / 'stage')),
                    dict(pending, before={'kind': 'directory', 'hash': 42}),
                    dict(pending, after={'kind': 'link', 'to': 42}),
                    dict(pending, backup=str(backup.with_name('unrelated-name')))]
        for value in variants:
            with self.subTest(journal=value):
                state.data['pending'] = value
                state.save()
                saved = state.path.read_bytes()
                self.assertRegex(case.run_cli('recover', code=1), 'Recovery paths|Invalid recovery|Invalid skill backup')
                self.assertEqual(observation(target), before_target)
                self.assertEqual(observation(backup), before_backup)
                self.assertEqual(state.path.read_bytes(), saved)

    def test_symlink_backup_restores_identity_without_changing_referent(self):
        case, target, backup, state = self.interrupted_skill()
        case.require_links()
        referent = case.root / 'original-linked-content'
        shutil.copytree(backup, referent)
        shutil.rmtree(backup)
        backup.symlink_to(referent, target_is_directory=True)
        state.data['pending']['before'] = observation(backup)
        state.save()
        original = fingerprint(referent)
        case.run_cli('recover')
        self.assertTrue(target.is_symlink())
        self.assertEqual(os.readlink(target), os.readlink(backup))
        self.assertEqual(fingerprint(referent), original)
        self.assertTrue(backup.is_symlink())
        self.assertIsNone(State(Config(case.config).state_dir).data['pending'])

    def test_restore_cleanup_failure_retains_reported_directory_and_allows_retry(self):
        case, target, backup, state = self.interrupted_skill()
        before_target, before_backup = observation(target), observation(backup)
        retained = []
        def interrupted(source, destination, **policy):
            destination.mkdir()
            (destination / 'user.txt').write_bytes(b'raced replacement')
            retained.append(destination)
            raise CopyCleanupError('injected cleanup failure', destination)
        with patch.object(manager_module, 'copy_payload', side_effect=interrupted):
            error = case.run_cli('recover', code=1)
        self.assertIn('preserved at', error)
        self.assertEqual(len(retained), 1)
        self.assertEqual((retained[0] / 'user.txt').read_bytes(), b'raced replacement')
        self.assertEqual(observation(target), before_target)
        self.assertEqual(observation(backup), before_backup)
        self.assertIsNotNone(State(Config(case.config).state_dir).data['pending'])
        case.run_cli('recover')
        self.assertEqual(observation(target), before_backup)
        self.assertEqual((retained[0] / 'user.txt').read_bytes(), b'raced replacement')
        self.assertIsNone(State(Config(case.config).state_dir).data['pending'])

    def test_target_edit_during_restoration_preserves_edit_and_backup(self):
        case, target, backup, state = self.interrupted_skill()
        original = observation(backup)
        copy_payload = manager_module.copy_payload
        def racing(source, destination, **policy):
            copy_payload(source, destination, **policy)
            (target / 'user.txt').write_bytes(b'concurrent target edit')
        with patch.object(manager_module, 'copy_payload', side_effect=racing):
            self.assertIn('changed during restoration', case.run_cli('recover', code=1))
        self.assertEqual((target / 'user.txt').read_bytes(), b'concurrent target edit')
        self.assertEqual(observation(backup), original)
        self.assertFalse(list(target.parent.glob('.aem-restore-*')))
        self.assertIsNotNone(State(Config(case.config).state_dir).data['pending'])
        (target / 'user.txt').unlink()
        case.run_cli('recover')
        self.assertEqual(observation(target), original)
        self.assertIsNone(State(Config(case.config).state_dir).data['pending'])

    def test_backup_race_preserves_local_edit_before_journaling(self):
        case = self.fixture(workflows.Workflow)
        target = case.installed_copy()
        original = observation(target)
        state_path = State(Config(case.config).state_dir).path
        case.publish_skill_change()
        case.run_cli('update')
        saved = state_path.read_bytes()
        copy_payload = manager_module.copy_payload
        changed = False
        def racing(source, destination, **policy):
            nonlocal changed
            copy_payload(source, destination, **policy)
            if source == target and destination.parent.name == 'skill-backups':
                changed = True
                (target / 'user.txt').write_bytes(b'edit while backing up')
        with patch.object(manager_module, 'copy_payload', side_effect=racing):
            self.assertIn('target changed during backup', case.run_cli('apply', '--item', 'report', code=1))
        self.assertTrue(changed)
        self.assertEqual((target / 'user.txt').read_bytes(), b'edit while backing up')
        backup, = (Config(case.config).state_dir / 'skill-backups').iterdir()
        self.assertEqual(observation(backup), original)
        self.assertEqual(state_path.read_bytes(), saved)
        self.assertFalse(list(target.parent.glob('.aem-stage-*')))

    def test_target_parent_redirect_after_planning_cannot_write_to_referent(self):
        case = self.fixture(exclusions.PayloadExclusions)
        case.prepare()
        case.require_links()
        original = fingerprint(case.target)
        moved = case.destination.with_name('original-target-parent')
        referent = case.root / 'outside-target-parent'
        referent.mkdir()
        (referent / 'sentinel').write_bytes(b'outside')
        plan = manager_module.Manager.plan
        def racing(manager, item, **options):
            result = plan(manager, item, **options)
            case.destination.rename(moved)
            case.destination.symlink_to(referent, target_is_directory=True)
            return result
        with patch.object(manager_module.Manager, 'plan', new=racing):
            self.assertIn('target ancestry changed', case.run_cli('apply', '--item', 'cases', code=1))
        self.assertEqual(fingerprint(moved / case.target.name), original)
        self.assertEqual(list(referent.iterdir()), [referent / 'sentinel'])
        self.assertEqual((referent / 'sentinel').read_bytes(), b'outside')


class CollectionConflicts(TemporaryCases):
    def nested_copies(self, **child_options):
        case = self.fixture(publications.CopyPublication)
        parent = case.external()
        (case.shared / 'nested').mkdir()
        (case.shared / 'nested/value.txt').write_text('original', encoding='utf-8')
        case.document['directories']['nested'] = dict(source='files', subdir='nested', preserve_symlinks=False,
            install={'root': 'skills', 'mode': 'copy'}, **child_options)
        case.catalog.write_text(tomlkit.dumps(case.document), encoding='utf-8')
        case.cli('apply', '--item', 'files', '--item', 'nested')
        child = case.root / 'installed/nested'
        (parent / 'nested/value.txt').write_text('same edit', encoding='utf-8')
        (child / 'value.txt').write_text('same edit', encoding='utf-8')
        return case, parent, child

    def refused(self, case, names, message):
        source, saved = fingerprint(case.shared), case.manager().state.path.read_bytes()
        for preview in (True, False):
            with self.subTest(preview=preview):
                args = ('--dry-run',) if preview else ()
                report = case.cli('publish', *names, '--from-copy', *args, code=1)[0]
                self.assertIn(message, report['error'])
                self.assertEqual(fingerprint(case.shared), source)
                self.assertEqual(case.manager().state.path.read_bytes(), saved)
                self.assertFalse(list(case.shared.parent.glob('.aem-collection-*')))

    def test_overlapping_copies_with_different_permission_policies_refuse_together(self):
        case, parent, child = self.nested_copies(permissions='best-effort')
        self.refused(case, ('files', 'nested'), 'Differently permissioned')
        self.assertEqual((parent / 'nested/value.txt').read_text(), 'same edit')
        self.assertEqual((child / 'value.txt').read_text(), 'same edit')

    def test_filtered_nested_copies_refuse_without_advancing_baselines(self):
        case, parent, child = self.nested_copies(exclude=['local-only'])
        self.refused(case, ('files', 'nested'), 'differently filtered')
        self.assertEqual((parent / 'nested/value.txt').read_text(), 'same edit')
        self.assertEqual((child / 'value.txt').read_text(), 'same edit')

    def test_redirected_nested_copy_refuses_without_following_link(self):
        case, parent, child = self.nested_copies()
        case.require_links()
        case.document['directories']['files']['preserve_symlinks'] = True
        case.catalog.write_text(tomlkit.dumps(case.document), encoding='utf-8')
        case.cli('apply', '--item', 'files', '--replace')
        shutil.copytree(parent / 'nested', parent / 'alias')
        (parent / 'alias/value.txt').write_text('same edit', encoding='utf-8')
        shutil.rmtree(parent / 'nested')
        (parent / 'nested').symlink_to('alias', target_is_directory=True)
        self.refused(case, ('files', 'nested'), 'redirects through a link')
        self.assertTrue((parent / 'nested').is_symlink())
        self.assertEqual((parent / 'alias/value.txt').read_text(), 'same edit')

    def test_child_collection_cannot_add_links_under_live_parent_that_rejects_them(self):
        case = self.fixture(publications.CopyPublication)
        case.require_links()
        parent = case.external(mode='link')
        (case.shared / 'nested').mkdir()
        (case.shared / 'nested/value.txt').write_text('original', encoding='utf-8')
        case.document['directories']['nested'] = {'source': 'files', 'subdir': 'nested',
            'preserve_symlinks': True, 'install': {'root': 'skills', 'mode': 'copy'}}
        case.catalog.write_text(tomlkit.dumps(case.document), encoding='utf-8')
        case.cli('apply', '--item', 'nested')
        child = case.root / 'installed/nested'
        (child / 'alias').symlink_to('value.txt')
        self.refused(case, ('nested',), 'symlinks are unsupported')
        self.assertTrue(parent.is_symlink())
        self.assertFalse((case.shared / 'nested/alias').exists())
        self.assertTrue((child / 'alias').is_symlink())

    def test_disjoint_changed_copies_are_collected_as_independent_writes(self):
        case = self.fixture(publications.CopyPublication)
        parent = case.external()
        for name in ('first', 'second'):
            (case.shared / name).mkdir()
            (case.shared / name / 'value.txt').write_text('original', encoding='utf-8')
            case.document['directories'][name] = {'source': 'files', 'subdir': name,
                'install': {'root': 'skills', 'mode': 'copy'}}
        case.catalog.write_text(tomlkit.dumps(case.document), encoding='utf-8')
        case.cli('apply', '--item', 'first', '--item', 'second')
        for name in ('first', 'second'):
            (case.root / 'installed' / name / 'value.txt').write_text(name, encoding='utf-8')
        report = case.cli('publish', 'first', 'second', '--from-copy')[0]
        self.assertTrue(report['collection_complete'])
        for name in ('first', 'second'):
            self.assertEqual((case.shared / name / 'value.txt').read_text(), name)
        self.assertEqual((parent / 'first.txt').read_text(), 'First\n')


class IntegrationRefusals(TemporaryCases):
    def prepared(self):
        case = self.fixture(setups.MachineSetup)
        case.setup_cli('--shell', 'bash', '--agent', 'codex')
        return case

    def test_invalid_initial_selections_and_executables_do_not_write_profiles(self):
        case = self.fixture(setups.MachineSetup)
        sentinel = case.home / 'user.txt'
        sentinel.write_bytes(b'user settings')
        cases = [((), 'Select at least one'),
                 (('--shell', 'bash', '--remove-shell', 'bash'), 'Cannot add and remove'),
                 (('--agent', 'codex', '--executable', 'relative'), 'absolute path'),
                 (('--agent', 'codex', '--executable', str(case.home / 'missing')), 'executable is missing')]
        for args, error in cases:
            with self.subTest(args=args):
                self.assertIn(error, case.setup_cli(*args, code=1))
                self.assertFalse(case.config.exists())
                self.assertFalse((case.home / '.bashrc').exists())
                self.assertFalse((case.home / '.codex/hooks.json').exists())
                self.assertEqual(sentinel.read_bytes(), b'user settings')

    def test_relocating_saved_shell_refuses_before_other_profiles_are_written(self):
        case = self.prepared()
        config = tomlkit.parse(case.config.read_text(encoding='utf-8'))
        config['setup']['shells']['bash'] = str(case.home / 'relocated-profile')
        case.config.write_text(tomlkit.dumps(config), encoding='utf-8')
        saved, state = case.config.read_bytes(), case.state()
        bash = (case.home / '.bashrc').read_bytes()
        self.assertIn('before relocating', case.setup_cli('--shell', 'zsh', code=1))
        self.assertEqual(case.config.read_bytes(), saved)
        self.assertEqual(case.state(), state)
        self.assertEqual((case.home / '.bashrc').read_bytes(), bash)
        self.assertFalse((case.home / '.zshrc').exists())
        self.assertFalse((case.home / 'relocated-profile').exists())

    def test_new_integrations_with_same_target_refuse_before_writing_either(self):
        case = self.fixture(setups.MachineSetup)
        shared = case.home / 'shared-profile'
        shared.write_bytes(b'user profile')
        case.config.write_text(tomlkit.dumps({'version': 1, 'setup': {
            'shells': {'bash': str(shared), 'zsh': str(shared)}}}), encoding='utf-8')
        saved = case.config.read_bytes()
        self.assertIn('overlapping target files', case.setup_cli(code=1))
        self.assertEqual(case.config.read_bytes(), saved)
        self.assertEqual(shared.read_bytes(), b'user profile')
        self.assertFalse(State(Config(case.config).state_dir).data['items'])

    def test_profile_overlapping_machine_configuration_is_preserved(self):
        case = self.fixture(setups.MachineSetup)
        case.config.write_text(tomlkit.dumps({'version': 1, 'setup': {
            'shells': {'bash': str(case.config)}}}), encoding='utf-8')
        saved = case.config.read_bytes()
        self.assertIn('overlaps manager storage', case.setup_cli(code=1))
        self.assertEqual(case.config.read_bytes(), saved)
        self.assertFalse(State(Config(case.config).state_dir).data['items'])

    def test_invalid_saved_removal_ownership_preserves_profiles_and_configuration(self):
        case = self.prepared()
        state = State(Config(case.config).state_dir)
        original = deepcopy(state.data)
        saved_config = case.config.read_bytes()
        profiles = {case.home / '.bashrc': (case.home / '.bashrc').read_bytes(),
                    case.home / '.codex/hooks.json': (case.home / '.codex/hooks.json').read_bytes()}
        cases = [('shell', {'kind': 'directory'}, 'not a saved setup'),
                 ('shell', {'target': str(case.config)}, 'overlaps machine'),
                 ('shell', {'block': None}, 'no usable saved shell block'),
                 ('agent', {'hook_marker': None}, 'no usable saved hook ownership')]
        for kind, fields, error in cases:
            with self.subTest(kind=kind, fields=fields):
                state.data = deepcopy(original)
                key = 'setup:shell-bash' if kind == 'shell' else 'setup:agent-codex'
                state.data['items'][key].update(fields)
                state.save()
                saved = state.path.read_bytes()
                args = ('--remove-shell', 'bash') if kind == 'shell' else ('--remove-agent', 'codex')
                self.assertIn(error, case.run_cli('setup', *args, code=1))
                self.assertEqual(case.config.read_bytes(), saved_config)
                self.assertEqual(state.path.read_bytes(), saved)
                for path, content in profiles.items():
                    self.assertEqual(path.read_bytes(), content)

    def test_configuration_changed_during_removal_preflight_is_not_overwritten(self):
        case = self.prepared()
        config, state = case.config.read_bytes(), case.state()
        target = case.home / '.codex/hooks.json'
        saved = target.read_bytes()
        matching = hooks.saved_matching
        def racing(*args):
            result = matching(*args)
            case.config.write_bytes(config + b'\n# concurrent config edit\n')
            return result
        with patch.object(hooks, 'saved_matching', side_effect=racing):
            self.assertIn('configuration changed during removal',
                          case.run_cli('setup', '--remove-agent', 'codex', code=1))
        self.assertEqual(case.config.read_bytes(), config + b'\n# concurrent config edit\n')
        self.assertEqual(target.read_bytes(), saved)
        self.assertEqual(case.state(), state)

    def test_profile_changed_during_removal_preflight_keeps_new_user_content(self):
        case = self.prepared()
        target = case.home / '.bashrc'
        saved, config, state = target.read_bytes(), case.config.read_bytes(), case.state()
        render = setup_module.render_shell
        def racing(*args, **kwargs):
            result = render(*args, **kwargs)
            target.write_bytes(saved + b'\n# concurrent profile edit\n')
            return result
        with patch.object(setup_module, 'render_shell', side_effect=racing):
            self.assertIn('removal target changed during preflight',
                          case.run_cli('setup', '--remove-shell', 'bash', code=1))
        self.assertEqual(target.read_bytes(), saved + b'\n# concurrent profile edit\n')
        self.assertEqual(case.config.read_bytes(), config)
        self.assertEqual(case.state(), state)


if __name__ == '__main__':
    unittest.main()

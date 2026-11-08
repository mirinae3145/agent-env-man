"""Permission policies preserve payloads and independently protect native modes."""

import errno
import json
import shutil
import subprocess
import sys
import os
import unittest
from unittest.mock import patch

from agent_env_man.catalog_schema import normalize
from agent_env_man.model import Error
from agent_env_man.storage import copy_payload, observation, State
from agent_env_man import permissions
import test_directories as directory_tests


class PermissionPolicy(unittest.TestCase):
    setUp = directory_tests.Directories.setUp
    git = directory_tests.Directories.git
    commit = directory_tests.Directories.commit
    repository = directory_tests.Directories.repository
    save_catalog = directory_tests.Directories.save_catalog
    run_cli = directory_tests.Directories.run_cli
    require_links = directory_tests.Directories.require_links
    write = directory_tests.Directories.write
    external = directory_tests.Directories.external
    manager = directory_tests.Directories.manager

    def prepare(self, *, mode='copy', links=False):
        self.document['payload'] = {'defaults': {'permissions': 'best-effort'}}
        self.document['directories']['cases']['preserve_symlinks'] = links
        self.external(mode=mode)
        (self.external_root / 'first.md').chmod(0o755)

    def setter(self, function):
        return patch.object(permissions.os, 'fchmod', side_effect=function)

    def test_hierarchy_and_invalid_values(self):
        self.document['payload'] = {'defaults': {'permissions': 'best-effort'}}
        self.assertEqual(normalize(self.document)['directories']['cases']['permissions'], 'best-effort')
        self.document['sources']['store']['permissions'] = 'strict'
        self.assertEqual(normalize(self.document)['directories']['cases'].get('permissions', 'strict'), 'strict')
        self.document['directories']['cases']['permissions'] = 'best-effort'
        self.assertEqual(normalize(self.document)['directories']['cases']['permissions'], 'best-effort')
        for table in (self.document['payload']['defaults'], self.document['sources']['store'], self.document['directories']['cases']):
            for invalid in (None, False, 1, 'default', 'ignore', []):
                original = table.get('permissions')
                table['permissions'] = invalid
                with self.subTest(value=invalid), self.assertRaises(Error):
                    normalize(self.document)
                table['permissions'] = original

    def test_denied_permissions_complete_and_report(self):
        self.prepare()
        with self.setter(OSError(errno.EPERM, 'permission setter rejected')):
            result = self.run_cli('apply', '--item', 'cases')
        self.assertEqual((self.target / 'first.md').read_text(), 'External case\n')
        self.assertTrue(result[0]['permission_differences'])
        self.assertIn('error', result[0]['permission_differences'][0])
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')
        self.assertTrue(self.run_cli('status')['items'][0]['permission_differences'])
        self.assertEqual(self.run_cli('apply', '--item', 'cases')[0]['action'], 'record')

    def test_silent_mode_mismatch_does_not_hide_content_damage(self):
        self.prepare()
        real = os.fchmod
        def masked(fd, mode):
            real(fd, (mode & ~0o111) if not os.path.isdir('/proc/self/fd/' + str(fd)) else mode)
        with self.setter(masked):
            result = self.run_cli('apply', '--item', 'cases')
        self.assertTrue(result[0]['permission_differences'])
        (self.external_root / 'first.md').write_text('new content')
        before = observation(self.target, permissions='best-effort')
        def damaged(source, destination, **policy):
            copy_payload(source, destination, **policy)
            (destination / 'first.md').write_text('corrupted')
        with patch('agent_env_man.manager.copy_payload', side_effect=damaged):
            self.assertIn('copied payload differs', self.run_cli('apply', '--item', 'cases', code=1))
        self.assertEqual(observation(self.target, permissions='best-effort'), before)

    def test_io_failure_is_fatal_and_preserves_old_target(self):
        self.prepare()
        self.run_cli('apply', '--item', 'cases')
        before = observation(self.target, permissions='best-effort')
        (self.external_root / 'first.md').write_text('new content')
        with self.setter(OSError(errno.EIO, 'device failed')):
            self.assertIn('device failed', self.run_cli('apply', '--item', 'cases', code=1))
        self.assertEqual(observation(self.target, permissions='best-effort'), before)
        self.assertIsNone(self.manager().state.data['pending'])

    def test_local_read_write_permission_changes_are_protected(self):
        self.prepare()
        self.run_cli('apply', '--item', 'cases')
        file = self.target / 'first.md'
        file.chmod(file.stat().st_mode ^ 0o020)
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'modified-locally')
        self.assertIn('locally modified copy', self.run_cli('apply', '--item', 'cases', code=1))
        self.assertEqual(file.stat().st_mode & 0o777, 0o775)

    def test_source_mode_change_becomes_stale_and_refreshes(self):
        self.prepare()
        self.run_cli('apply', '--item', 'cases')
        (self.external_root / 'first.md').chmod(0o744)
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'stale')
        self.run_cli('apply', '--item', 'cases')
        self.assertEqual((self.target / 'first.md').stat().st_mode & 0o777, 0o744)
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')

    def test_policy_transition_requires_apply_and_preserves_edits(self):
        self.external()
        self.run_cli('apply', '--item', 'cases')
        self.document['directories']['cases']['permissions'] = 'best-effort'; self.write()
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'configuration-changed')
        self.assertIn('policy changed', self.run_cli('publish', 'cases', '--from-copy', '--dry-run', code=1)[0]['error'])
        (self.target / 'first.md').write_text('local edit')
        self.run_cli('apply', '--item', 'cases', code=1)
        self.run_cli('apply', '--item', 'cases', '--replace')
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')
        self.document['directories']['cases']['permissions'] = 'strict'; self.write()
        self.run_cli('apply', '--item', 'cases')
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')

    def test_detach_uses_saved_policy_without_catalog(self):
        self.require_links(); self.prepare(mode='link', links=True)
        self.run_cli('apply', '--item', 'cases')
        self.assertEqual(self.run_cli('detach', 'cases', '--dry-run')[0]['permission_check'], 'pending-copy')
        self.assertTrue(self.target.is_symlink())
        self.catalog.unlink()
        with self.setter(OSError(errno.ENOTSUP, 'modes unsupported')):
            result = self.run_cli('detach', 'cases')
        self.assertFalse(self.target.is_symlink())
        self.assertEqual((self.target / 'first.md').read_text(), 'External case\n')
        self.assertTrue(result[0]['permission_differences'])

    def test_collection_preserves_source_modes_and_adds_files(self):
        self.prepare()
        self.run_cli('apply', '--item', 'cases')
        (self.target / 'first.md').chmod(0o644)
        (self.target / 'first.md').write_text('collected edit')
        (self.target / 'new.md').write_text('new file')
        (self.target / 'new.md').chmod(0o744)
        self.run_cli('publish', 'cases', '--from-copy')
        self.assertEqual((self.external_root / 'first.md').read_text(), 'collected edit')
        self.assertEqual((self.external_root / 'first.md').stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.external_root / 'new.md').stat().st_mode & 0o777, 0o744)
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')

    def test_permission_only_collection_does_not_export_modes(self):
        self.prepare(); self.run_cli('apply', '--item', 'cases')
        (self.target / 'first.md').chmod(0o644)
        result = self.run_cli('publish', 'cases', '--from-copy', '--dry-run')
        self.assertFalse(result[0]['collection'][0]['changed'])
        self.run_cli('publish', 'cases', '--from-copy')
        self.assertEqual((self.external_root / 'first.md').stat().st_mode & 0o777, 0o755)
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'modified-locally')

    def test_preview_does_not_claim_permission_support(self):
        self.prepare()
        result = self.run_cli('apply', '--item', 'cases', '--dry-run')
        self.assertEqual(result[0]['permission_check'], 'pending-copy')
        self.assertFalse(self.target.exists())

    def test_source_permission_change_during_copy_is_fatal(self):
        self.prepare(); self.run_cli('apply', '--item', 'cases')
        (self.external_root / 'first.md').write_text('updated')
        before = observation(self.target, permissions='best-effort')
        def changing(source, destination, **policy):
            copy_payload(source, destination, **policy)
            (source / 'first.md').chmod(0o744)
        with patch('agent_env_man.manager.copy_payload', side_effect=changing):
            self.assertIn('source changed while copying', self.run_cli('apply', '--item', 'cases', code=1))
        self.assertEqual(observation(self.target, permissions='best-effort'), before)

    def test_target_permission_change_during_staging_is_fatal(self):
        self.prepare(); self.run_cli('apply', '--item', 'cases')
        (self.external_root / 'first.md').write_text('updated')
        def changing(source, destination, **policy):
            copy_payload(source, destination, **policy)
            (self.target / 'first.md').chmod(0o744)
        with patch('agent_env_man.manager.copy_payload', side_effect=changing):
            self.assertIn('target changed during staging', self.run_cli('apply', '--item', 'cases', code=1))
        self.assertEqual((self.target / 'first.md').stat().st_mode & 0o777, 0o744)
        self.assertEqual((self.target / 'first.md').read_text(), 'External case\n')

    def test_interrupted_install_recovery_protects_later_permissions(self):
        self.prepare(); self.run_cli('apply', '--item', 'cases')
        (self.external_root / 'first.md').write_text('updated')
        original_save = State.save
        def interrupt(state):
            if state.data['pending'] is None and (self.target / 'first.md').read_text() == 'updated':
                raise KeyboardInterrupt('crash before state commit')
            original_save(state)
        with patch.object(State, 'save', interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.manager().apply(['cases'])
        (self.target / 'first.md').chmod(0o744)
        self.assertIn('Recovery stopped', self.run_cli('recover', code=1))
        self.assertEqual((self.target / 'first.md').stat().st_mode & 0o777, 0o744)
        self.assertIsNotNone(self.manager().state.data['pending'])
        (self.target / 'first.md').chmod(0o755)
        self.run_cli('recover')
        self.assertEqual((self.target / 'first.md').read_text(), 'External case\n')

    def test_collection_failure_rolls_back_and_protects_permissions(self):
        self.prepare(); self.run_cli('apply', '--item', 'cases')
        (self.target / 'first.md').write_text('collected')
        original_save = State.save
        def interrupt(state):
            if state.data['pending'] is None and (self.external_root / 'first.md').read_text() == 'collected':
                raise KeyboardInterrupt('crash before collection state commit')
            original_save(state)
        with patch.object(State, 'save', interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.manager().publish(['cases'], from_copy=True)
        (self.external_root / 'first.md').chmod(0o744)
        self.assertIn('Recovery stopped', self.run_cli('recover', code=1))
        self.assertEqual((self.external_root / 'first.md').stat().st_mode & 0o777, 0o744)
        (self.external_root / 'first.md').chmod(0o755)
        self.run_cli('recover')
        self.assertEqual((self.external_root / 'first.md').read_text(), 'External case\n')
        self.assertEqual((self.target / 'first.md').read_text(), 'collected')

    def check_link_retarget_collection(self, *, nested):
        self.require_links(); self.prepare(links=True)
        (self.external_root / 'second.md').write_text('Second case\n', encoding='utf-8')
        relative = 'links/alias' if nested else 'alias'
        source_link = self.external_root / relative
        source_link.parent.mkdir(parents=True, exist_ok=True)
        prefix = '../' if nested else ''
        source_link.symlink_to(prefix + 'first.md')
        self.run_cli('apply', '--item', 'cases')
        copy_link = self.target / relative
        copy_link.unlink(); copy_link.symlink_to(prefix + 'second.md')
        preview = self.run_cli('publish', 'cases', '--from-copy', '--dry-run')[0]['collection'][0]
        self.assertTrue(preview['changed'])
        self.assertIn(relative, preview['changes'])
        self.run_cli('publish', 'cases', '--from-copy')
        self.assertEqual(os.readlink(source_link), prefix + 'second.md')
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')
        self.assertIsNone(self.manager().state.data['pending'])

    def test_collection_retargets_top_level_link(self):
        self.check_link_retarget_collection(nested=False)

    def test_collection_retargets_nested_link(self):
        self.check_link_retarget_collection(nested=True)

    def check_type_replacement_collection(self, *, nested, incoming_directory):
        self.prepare()
        relative = 'outer/entry' if nested else 'entry'
        source_entry = self.external_root / relative
        source_entry.parent.mkdir(parents=True, exist_ok=True)
        if nested:
            source_entry.parent.chmod(0o755)
        if incoming_directory:
            source_entry.write_text('Old file\n', encoding='utf-8')
            source_entry.chmod(0o644)
        else:
            source_entry.mkdir(); source_entry.chmod(0o711)
            (source_entry / 'old.txt').write_text('Old directory\n', encoding='utf-8')
        self.run_cli('apply', '--item', 'cases')
        copy_entry = self.target / relative
        if incoming_directory:
            copy_entry.unlink(); copy_entry.mkdir()
            (copy_entry / 'new.txt').write_text('New directory\n', encoding='utf-8')
            (copy_entry / 'new.txt').chmod(0o640)
            copy_entry.chmod(0o750)
        else:
            shutil.rmtree(copy_entry)
            copy_entry.write_text('New file\n', encoding='utf-8')
            copy_entry.chmod(0o640)
        if nested:
            copy_entry.parent.chmod(0o700)

        def make_stages_accessible():
            # A failed regression can leave a directory with a file's 0644 mode.
            # Restore traversal only in disposable staging trees for fixture cleanup.
            for scratch in self.root.glob('.aem-collection-*'):
                for directory, _, _ in os.walk(scratch):
                    os.chmod(directory, os.stat(directory).st_mode | 0o700)
        self.addCleanup(make_stages_accessible)

        self.run_cli('publish', 'cases', '--from-copy')
        if incoming_directory:
            self.assertTrue(source_entry.is_dir())
            self.assertEqual((source_entry / 'new.txt').read_text(encoding='utf-8'), 'New directory\n')
            self.assertEqual(source_entry.stat().st_mode & 0o777, 0o750)
            self.assertEqual((source_entry / 'new.txt').stat().st_mode & 0o777, 0o640)
        else:
            self.assertTrue(source_entry.is_file())
            self.assertEqual(source_entry.read_text(encoding='utf-8'), 'New file\n')
            self.assertEqual(source_entry.stat().st_mode & 0o777, 0o640)
        if nested:
            self.assertEqual(source_entry.parent.stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.external_root / 'first.md').read_text(encoding='utf-8'), 'External case\n')
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')
        self.assertIsNone(self.manager().state.data['pending'])

    def test_collection_replaces_top_level_file_with_directory(self):
        self.check_type_replacement_collection(nested=False, incoming_directory=True)

    def test_collection_replaces_nested_file_with_directory(self):
        self.check_type_replacement_collection(nested=True, incoming_directory=True)

    def test_collection_replaces_top_level_directory_with_file(self):
        self.check_type_replacement_collection(nested=False, incoming_directory=False)

    def test_collection_replaces_nested_directory_with_file(self):
        self.check_type_replacement_collection(nested=True, incoming_directory=False)

    def test_exclusions_and_opaque_links_share_permission_policy(self):
        self.require_links(); self.prepare(links=True)
        self.document['payload']['defaults']['exclude'] = ['**/._DAV']; self.write()
        (self.external_root / '._DAV').mkdir()
        (self.external_root / '._DAV/local').write_text('source metadata')
        (self.external_root / 'alias').symlink_to('first.md')
        self.run_cli('apply', '--item', 'cases')
        self.assertTrue((self.target / 'alias').is_symlink())
        (self.target / '._DAV').mkdir(); (self.target / '._DAV/local').write_text('target metadata')
        (self.external_root / 'first.md').write_text('updated')
        self.run_cli('apply', '--item', 'cases')
        self.assertEqual((self.target / '._DAV/local').read_text(), 'target metadata')
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')

    def test_git_skill_uses_best_effort_and_protects_local_permissions(self):
        import test_workflow as workflow_tests
        case = workflow_tests.Workflow()
        try:
            case.setUp(); case.copy_mode()
            case.skills['report']['permissions'] = 'best-effort'; case.save_catalog()
            case.bootstrap()
            case.run_cli('apply')
            self.assertEqual(case.run_cli('status')['items'][0]['status'], 'current')
            case.publish_skill_change(); case.run_cli('update'); case.run_cli('apply')
            self.assertIn('Published change', (case.destination / 'report/SKILL.md').read_text())
            self.assertEqual(case.run_cli('status')['items'][0]['status'], 'current')
        finally:
            case.doCleanups()

    def test_instruction_bundle_inherits_policy_but_hooks_do_not(self):
        self.prepare()
        self.document['directories'] = {}
        self.document['instructions'] = {'rules': {'source': 'store', 'entry': 'first.md',
            'install': {'bundle': {'root': 'personal', 'mode': 'copy'}, 'entry': {'root': 'personal', 'destination': 'AGENTS.md'}}}}
        self.write()
        self.require_links()
        self.run_cli('apply', '--item', 'rules:entry')
        records = self.manager().state.data['items']
        self.assertEqual(records['rules:bundle']['permissions'], 'best-effort')
        self.assertNotIn('permissions', records['rules:hook'])
        self.assertNotIn('permissions', records['rules:entry'])
        self.assertEqual((self.destination / 'rules/first.md').read_text(), 'External case\n')

    def test_strict_preserved_link_copy_rejects_denied_permissions(self):
        self.prepare(links=True)
        self.document['directories']['cases']['permissions'] = 'strict'; self.write()
        with self.setter(OSError(errno.ENOTSUP, 'modes unsupported')):
            self.assertIn('modes unsupported', self.run_cli('apply', '--item', 'cases', code=1))
        self.assertFalse(self.target.exists())

    def test_fresh_cli_processes_apply_status_collection_and_detach(self):
        self.prepare()
        def cli(*args):
            result = subprocess.run([sys.executable, '-m', 'agent_env_man', '--json', '--config', str(self.config), *args],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        cli('apply', '--item', 'cases')
        self.assertEqual(cli('status')['items'][0]['status'], 'current')
        (self.target / 'first.md').write_text('collected by fresh process')
        cli('publish', 'cases', '--from-copy')
        self.assertEqual((self.external_root / 'first.md').read_text(), 'collected by fresh process')
        cli('detach', 'cases')
        self.assertEqual(cli('status')['items'][0]['status'], 'detached')

    def test_converged_content_advances_baseline_without_replacement(self):
        self.prepare(); self.run_cli('apply', '--item', 'cases')
        (self.target / 'first.md').write_text('converged content')
        (self.external_root / 'first.md').write_text('converged content')
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'current')
        self.assertEqual(self.run_cli('apply', '--item', 'cases')[0]['action'], 'record')
        self.assertEqual(self.run_cli('status')['items'][0]['installation'], 'matches-last-apply')

    def test_source_permission_and_local_content_edits_are_conflicting(self):
        self.prepare(); self.run_cli('apply', '--item', 'cases')
        (self.target / 'first.md').write_text('local edit')
        (self.external_root / 'first.md').chmod(0o744)
        self.assertEqual(self.run_cli('status')['items'][0]['status'], 'conflict')
        self.assertTrue(self.run_cli('publish', 'cases', '--from-copy', '--dry-run', code=1)[0]['collection'][0]['conflict'])

    def test_collection_setter_failures_remain_visible_in_status(self):
        self.prepare(); self.run_cli('apply', '--item', 'cases')
        (self.target / 'first.md').write_text('collected with permission rejection')
        with self.setter(OSError(errno.ENOTSUP, 'source modes unavailable')):
            result = self.run_cli('publish', 'cases', '--from-copy')
        changes = result[0]['collection'][0]['permission_differences']
        self.assertEqual(changes[0]['path'], 'first.md')
        self.assertIn('source modes unavailable', changes[0]['error'])
        self.assertTrue(self.run_cli('status')['items'][0]['collection_permission_differences'])

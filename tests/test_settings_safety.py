"""Failure and recovery boundaries for settings files and saved ownership."""

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_env_man.model import Error
from agent_env_man import settings
from agent_env_man.settings import Bundle, recover_group, transaction
from agent_env_man.storage import State, observation
import test_settings as settings_tests


class SettingsSafety(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aem-settings-safety-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.state = State(self.root / "state")
        self.state.data["items"]["unselected"] = {"mode": "copy", "opaque": "keep"}
        self.state.save()
        self.target = self.root / "config.toml"
        self.target.write_bytes(b"count = 1\n")

    def writes(self):
        return [(self.target, b"count = 2\n", observation(self.target))]

    def test_duplicate_writes_rejected_without_mutation(self):
        before = self.state.path.read_bytes()
        with self.assertRaisesRegex(Error, "Duplicate grouped"):
            transaction(self.state, self.writes() * 2, {})
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")
        self.assertEqual(self.state.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".aem-*")))

    def test_unknown_group_operation_preserves_files_and_ownership(self):
        saved = self.state.path.read_bytes()
        for preview in (False, True):
            with self.subTest(preview=preview), self.assertRaisesRegex(Error, 'Unsupported grouped file operation'):
                transaction(self.state, self.writes(), {'new': {}},
                            operation='unknown-group', dry_run=preview)
        self.assertEqual(self.target.read_bytes(), b'count = 1\n')
        self.assertEqual(self.state.path.read_bytes(), saved)
        self.assertFalse(list(self.root.glob('.aem-*')))

    def test_initial_stage_failure_does_not_create_durable_state(self):
        state = State(self.root / 'new-state')
        original = deepcopy(state.data)
        with patch.object(settings, 'atomic_write', side_effect=OSError('initial disk failure')):
            with self.assertRaisesRegex(OSError, 'initial disk failure'):
                transaction(state, self.writes(), {'new': {'mode': 'settings'}})
        self.assertEqual(self.target.read_bytes(), b'count = 1\n')
        self.assertEqual(state.data, original)
        self.assertFalse(state.path.exists())
        self.assertFalse(list(self.root.glob('.aem-*')))

    def test_stale_read_rejected_even_in_preview(self):
        writes = self.writes()
        self.target.write_bytes(b"user edit\n")
        before = self.state.path.read_bytes()
        for preview in (False, True):
            with self.subTest(preview=preview), self.assertRaisesRegex(Error, "changed after reading"):
                transaction(self.state, writes, {}, dry_run=preview)
        self.assertEqual(self.target.read_bytes(), b"user edit\n")
        self.assertEqual(self.state.path.read_bytes(), before)

    def test_preview_preserves_files_and_ownership(self):
        before = self.state.path.read_bytes()
        transaction(self.state, self.writes(), {"new": {"mode": "settings"}}, dry_run=True)
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")
        self.assertEqual(self.state.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".aem-*")))

    def test_failed_stage_creation_preserves_existing_target_and_state(self):
        before = self.state.path.read_bytes()
        with patch("agent_env_man.settings.atomic_write", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                transaction(self.state, self.writes(), {"new": {"mode": "settings"}})
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")
        self.assertEqual(self.state.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".aem-*")))

    def test_failed_journal_save_cleans_prepared_files(self):
        before = self.state.path.read_bytes()
        with patch.object(self.state, "save", side_effect=OSError("journal failed")):
            with self.assertRaisesRegex(OSError, "journal failed"):
                transaction(self.state, self.writes(), {})
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")
        self.assertEqual(self.state.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".aem-stage-*")))
        self.assertFalse(list(self.root.glob("*.aem-backup-*")))

    def test_failed_state_commit_restores_group_and_all_ownership(self):
        missing = self.root / "new.json"
        writes = self.writes() + [(missing, b"{}\n", observation(missing))]
        original_items = deepcopy(self.state.data["items"])
        save = self.state.save
        calls = 0

        def fail_commit_once():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("state commit failed")
            save()

        with patch.object(self.state, "save", side_effect=fail_commit_once):
            with self.assertRaisesRegex(OSError, "state commit failed"):
                transaction(self.state, writes, {"new": {"mode": "settings"}})
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")
        self.assertFalse(missing.exists())
        durable = State(self.state.path.parent)
        self.assertEqual(durable.data["items"], original_items)
        self.assertIsNone(durable.data["pending"])
        self.assertFalse(list(self.root.glob(".aem-stage-*")))
        transaction(durable, self.writes(), {"new": {"mode": "settings"}})
        self.assertEqual(self.target.read_bytes(), b"count = 2\n")
        self.assertEqual(State(self.state.path.parent).data["items"]["unselected"], original_items["unselected"])

    def test_guard_edit_during_staging_preserves_inputs_and_ownership(self):
        source = self.root / 'source.toml'
        source.write_bytes(b'original source\n')
        guard = (source, observation(source))
        saved = self.state.path.read_bytes()
        write = settings.atomic_write
        def race(path, content, **kwargs):
            write(path, content, **kwargs)
            source.write_bytes(b'concurrent source edit\n')
        with patch.object(settings, 'atomic_write', side_effect=race):
            with self.assertRaisesRegex(Error, 'Input changed during transaction'):
                transaction(self.state, self.writes(), {'new': {}}, guards=[guard])
        self.assertEqual(source.read_bytes(), b'concurrent source edit\n')
        self.assertEqual(self.target.read_bytes(), b'count = 1\n')
        self.assertEqual(self.state.path.read_bytes(), saved)
        self.assertFalse(list(self.root.glob('.aem-stage-*')))

    def test_unchanged_write_is_guarded_while_other_members_are_staged(self):
        other = self.root / 'other.toml'
        writes = [(self.target, self.target.read_bytes(), observation(self.target)),
                  (other, b'other = 1\n', observation(other))]
        saved = self.state.path.read_bytes()
        write = settings.atomic_write
        def race(path, content, **kwargs):
            write(path, content, **kwargs)
            self.target.write_bytes(b'concurrent unchanged-member edit\n')
        with patch.object(settings, 'atomic_write', side_effect=race):
            with self.assertRaisesRegex(Error, 'Input changed during transaction'):
                transaction(self.state, writes, {'new': {}})
        self.assertFalse(other.exists())
        self.assertEqual(self.target.read_bytes(), b'concurrent unchanged-member edit\n')
        self.assertEqual(self.state.path.read_bytes(), saved)
        self.assertFalse(list(self.root.glob('.aem-stage-*')))

    def test_target_edit_after_journaling_keeps_edit_and_recoverable_stage(self):
        save = self.state.save
        def race():
            save()
            self.target.write_bytes(b'user edit after journal\n')
        with patch.object(self.state, 'save', side_effect=race):
            with self.assertRaisesRegex(Error, 'Recovery stopped'):
                transaction(self.state, self.writes(), {'new': {}})
        durable = State(self.state.path.parent)
        entry = durable.data['pending']['files'][0]
        self.assertEqual(self.target.read_bytes(), b'user edit after journal\n')
        self.assertEqual(Path(entry['stage']).read_bytes(), b'count = 2\n')
        self.assertFalse(Path(entry['backup']).exists())
        self.assertNotIn('new', durable.data['items'])
        self.target.write_bytes(b'count = 1\n')
        recover_group(durable)
        self.assertIsNone(State(self.state.path.parent).data['pending'])
        self.assertFalse(Path(entry['stage']).exists())

    def test_target_edit_after_replacement_keeps_backup_and_journal(self):
        replace = os.replace
        def race(source, destination):
            replace(source, destination)
            if Path(destination) == self.target:
                self.target.write_bytes(b'user edit after replacement\n')
        with patch.object(settings.os, 'replace', side_effect=race):
            with self.assertRaisesRegex(Error, 'Recovery stopped'):
                transaction(self.state, self.writes(), {'new': {}})
        durable = State(self.state.path.parent)
        entry = durable.data['pending']['files'][0]
        self.assertEqual(self.target.read_bytes(), b'user edit after replacement\n')
        self.assertEqual(Path(entry['backup']).read_bytes(), b'count = 1\n')
        self.assertNotIn('new', durable.data['items'])
        self.target.write_bytes(b'count = 2\n')
        recover_group(durable)
        self.assertEqual(self.target.read_bytes(), b'count = 1\n')
        self.assertIsNone(State(self.state.path.parent).data['pending'])

    def interrupted_entry(self, target=None):
        target = target or self.target
        before = observation(target)
        backup = target.with_name(target.name + ".aem-backup-test")
        if target.exists():
            target.rename(backup)
        target.write_bytes(b"new content\n")
        return {"target": str(target), "stage": str(target.with_name(".aem-stage-" + target.name)),
                "backup": str(backup), "before": before, "after": observation(target)}

    def journal(self, entries):
        self.state.data["pending"] = {"operation": "settings-group", "files": entries}
        self.state.save()

    def test_recovery_restores_existing_and_removes_new_file(self):
        entries = [self.interrupted_entry(), self.interrupted_entry(self.root / "new.json")]
        self.journal(entries)
        recover_group(self.state)
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")
        self.assertFalse((self.root / "new.json").exists())
        self.assertIsNone(State(self.state.path.parent).data["pending"])
        self.assertEqual(self.state.data["items"]["unselected"]["opaque"], "keep")

    def test_interrupted_group_restoration_can_resume_after_one_member_is_restored(self):
        other = self.root / 'second.toml'
        other.write_bytes(b'second original\n')
        entries = [self.interrupted_entry(), self.interrupted_entry(other)]
        self.journal(entries)
        saved = self.state.path.read_bytes()
        replace = os.replace
        def fail_first_member(source, destination):
            if Path(destination) == self.target:
                raise OSError('interrupted restoration')
            replace(source, destination)
        with patch.object(settings.os, 'replace', side_effect=fail_first_member):
            with self.assertRaisesRegex(OSError, 'interrupted restoration'):
                recover_group(self.state)
        self.assertEqual(other.read_bytes(), b'second original\n')
        self.assertEqual(self.target.read_bytes(), b'new content\n')
        self.assertEqual(Path(entries[0]['backup']).read_bytes(), b'count = 1\n')
        self.assertEqual(self.state.path.read_bytes(), saved)
        recover_group(State(self.state.path.parent))
        self.assertEqual(self.target.read_bytes(), b'count = 1\n')
        self.assertEqual(other.read_bytes(), b'second original\n')
        self.assertIsNone(State(self.state.path.parent).data['pending'])

    def test_recovery_state_save_failure_keeps_journal_for_idempotent_retry(self):
        entries = [self.interrupted_entry(), self.interrupted_entry(self.root / 'new.toml')]
        self.journal(entries)
        saved = self.state.path.read_bytes()
        with patch.object(self.state, 'save', side_effect=OSError('state unavailable')):
            with self.assertRaisesRegex(OSError, 'state unavailable'):
                recover_group(self.state)
        self.assertEqual(self.target.read_bytes(), b'count = 1\n')
        self.assertFalse((self.root / 'new.toml').exists())
        self.assertEqual(self.state.path.read_bytes(), saved)
        recover_group(State(self.state.path.parent))
        self.assertIsNone(State(self.state.path.parent).data['pending'])
        self.assertEqual(self.target.read_bytes(), b'count = 1\n')

    def test_invalid_later_journal_entry_prevents_all_rollback(self):
        mutations = [
            (None, "Incomplete"),
            ({"stage": str(self.root / "elsewhere/stage")}, "distinct siblings"),
            ({"stage": str(self.root / "second.json")}, "distinct siblings"),
            ({"stage": str(self.root / "wrong-name")}, "artifact paths"),
            ({"backup": str(self.root / "wrong-backup")}, "artifact paths"),
            ({"before": {"kind": "link", "to": "other"}}, "observation"),
            ({"after": {"kind": "file", "hash": 7}}, "observation"),
        ]
        entry = self.interrupted_entry()
        second = self.interrupted_entry(self.root / "second.json")
        for changes, message in mutations:
            with self.subTest(changes=changes):
                invalid = None if changes is None else dict(second, **changes)
                self.journal([entry, invalid])
                before = self.state.path.read_bytes()
                with self.assertRaisesRegex(Error, message):
                    recover_group(self.state)
                self.assertEqual(self.target.read_bytes(), b"new content\n")
                self.assertEqual(Path(entry["backup"]).read_bytes(), b"count = 1\n")
                self.assertEqual(self.state.path.read_bytes(), before)

    def test_overlapping_recovery_artifacts_preserved(self):
        entry = self.interrupted_entry()
        self.journal([entry, entry])
        with self.assertRaisesRegex(Error, "Overlapping settings recovery"):
            recover_group(self.state)
        self.assertEqual(self.target.read_bytes(), b"new content\n")
        self.assertTrue(Path(entry["backup"]).exists())

    def test_non_list_recovery_files_rejected(self):
        self.journal({})
        with self.assertRaisesRegex(Error, "Invalid grouped"):
            recover_group(self.state)
        self.assertEqual(self.target.read_bytes(), b"count = 1\n")

    def test_changed_stage_or_backup_blocks_entire_recovery(self):
        entry = self.interrupted_entry()
        backup = Path(entry["backup"])
        stage = Path(entry["stage"])
        for artifact in (stage, backup):
            with self.subTest(artifact=artifact):
                artifact.write_bytes(b"user edit\n")
                self.journal([entry])
                before = self.state.path.read_bytes()
                with self.assertRaisesRegex(Error, "preserve files and backups"):
                    recover_group(self.state)
                self.assertEqual(artifact.read_bytes(), b"user edit\n")
                self.assertEqual(self.target.read_bytes(), b"new content\n")
                self.assertEqual(self.state.path.read_bytes(), before)
                stage.unlink(missing_ok=True)
                backup.write_bytes(b"count = 1\n")


class SettingsStorageSafety(unittest.TestCase):
    setUp = settings_tests.StagedSettings.setUp
    call = settings_tests.StagedSettings.call
    bootstrap = settings_tests.StagedSettings.bootstrap
    manager = settings_tests.StagedSettings.manager

    def test_targets_cannot_overwrite_sources_or_manager_storage(self):
        manager = self.manager()
        config = manager.config
        source = config.sources['editor']
        originals = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        protected = (self.payload, config.path, config.state_dir / 'overwrite.toml',
                     config.checkout_root / 'overwrite.toml', self.stage, config.catalog_path)
        for target in protected:
            with self.subTest(target=target):
                config.doc['settings']['editor']['target'] = str(target)
                with self.assertRaisesRegex(Error, 'Setting target overlaps sources or manager storage'):
                    settings.declaration(config, source, {'path': 'editor.toml'})
        self.assertEqual({path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}, originals)

    def test_stage_storage_cannot_be_created_inside_settings_source(self):
        config = self.manager().config
        source = config.sources['editor']
        original = self.payload.read_bytes()
        config.path = self.source / 'nested-machine.toml'
        with self.assertRaisesRegex(Error, 'Settings stage storage overlaps sources or manager storage'):
            settings.declaration(config, source, {'path': 'editor.toml'})
        self.assertEqual(self.payload.read_bytes(), original)
        self.assertFalse(config.path.exists())
        self.assertFalse((self.source / 'nested-machine.toml.stages').exists())


class SettingsMetadataSafety(unittest.TestCase):
    def test_invalid_saved_snapshots_and_formats_are_rejected(self):
        for snapshot in (None, {}, {"config": "", "management": "", "extra": ""}):
            with self.subTest(snapshot=snapshot), self.assertRaisesRegex(Error, "comparison base"):
                Bundle.from_snapshot(snapshot)
        for format in (None, [], "jsonc"):
            with self.subTest(format=format):
                with self.assertRaisesRegex(Error, "Unsupported settings format"):
                    Bundle.empty(format=format)
                with self.assertRaisesRegex(Error, "Unsupported settings format"):
                    Bundle.from_snapshot({"config": "", "management": ""}, format=format)

    def test_invalid_intent_metadata_rejected_before_use(self):
        cases = [
            ('version = true\n', "requires version"),
            ('version = 2\n', "requires version"),
            ('version = 1\nunknown = []\n', "requires version"),
            ('version = 1\ndeleted = "key"\n', "must be an array"),
            ('version = 1\nreleased = [[]]\n', "nonempty string arrays"),
            ('version = 1\ndeleted = [[1]]\n', "nonempty string arrays"),
            ('version = 1\ndeleted = [["key"], ["key"]]\n', "Duplicate metadata"),
            ('version = 1\ndeleted = [["key"]]\nreleased = [["key", "child"]]\n', "Overlapping"),
        ]
        for management, message in cases:
            with self.subTest(management=management), self.assertRaisesRegex(Error, message):
                Bundle.from_snapshot({"config": "", "management": management})

    def test_read_race_rejected_without_changing_source(self):
        with tempfile.TemporaryDirectory(prefix="aem-settings-read-") as directory:
            path = Path(directory).resolve() / "config.toml"
            path.write_bytes(b"count = 1\n")
            with patch("agent_env_man.settings.observation", side_effect=[observation(path), {"kind": "missing"}]):
                with self.assertRaisesRegex(Error, "changed while reading"):
                    Bundle.load(path)
            self.assertEqual(path.read_bytes(), b"count = 1\n")

"""Profile copies preserve omitted ownership, opaque files, and failed inputs."""

import os
from pathlib import Path
import stat
from unittest import mock

from agent_env_man.storage import State
import test_profile_copy


class ProfileCopyPreservation(test_profile_copy.Copy):
    def test_managed_styles_and_hook_directory_are_left_for_target_installation(self):
        hook_source = self.source / 'managed-hooks'
        hook_source.mkdir()
        (hook_source / 'owned.sh').write_text('exit 0\n', encoding='utf-8')
        owned_hooks = self.left / 'hooks' / 'managed'
        owned_hooks.mkdir()
        (owned_hooks / 'owned.sh').write_text('exit 0\n', encoding='utf-8')
        user_script = self.source / 'user-hook.sh'
        user_script.write_text('exit 0\n', encoding='utf-8')
        user_link = self.left / 'hooks' / 'user.sh'
        user_link.symlink_to(os.path.relpath(user_script, user_link.parent))
        state = State(self.config.parent / (self.config.name + '.state'))
        state.data['items'] = {
            'styles:directory': {'kind': 'directory', 'mode': 'link',
                                 'source': str(self.source), 'target': str(self.left / 'output-styles')},
            'hook:directory': {'kind': 'directory', 'mode': 'copy',
                               'source': str(hook_source), 'target': str(owned_hooks)},
        }
        state.save()
        saved = state.path.read_bytes()
        before = self.snapshot()

        report = self.report('--write')

        skipped = {item['item']: item['reason'] for item in report['skipped']}
        for name in ('output-styles', 'hooks/managed'):
            self.assertIn('installed by AEM', skipped[name])
            self.assertFalse(os.path.lexists(self.target / name))
        copied = self.target / 'hooks' / 'user.sh'
        self.assertTrue(copied.is_symlink())
        self.assertEqual(copied.resolve(), user_script)
        self.assertTrue((self.target / 'hooks' / 'herdr.sh').is_file())
        self.assertEqual(report['verification']['unexpected'], [])
        self.assertEqual(state.path.read_bytes(), saved)
        self.assertEqual(self.snapshot(), before)

    def test_style_directory_keeps_user_links_and_reports_regular_files(self):
        styles = self.left / 'output-styles'
        styles.unlink()
        styles.mkdir()
        external = self.source / 'style.md'
        external.write_text('User style\n', encoding='utf-8')
        (styles / 'linked.md').symlink_to(external)
        (styles / 'local.md').write_text('Local style\n', encoding='utf-8')
        (self.left / 'hooks' / 'nested').mkdir()
        (self.left / 'hooks' / 'nested' / 'keep.sh').write_text('exit 0\n', encoding='utf-8')
        before = self.snapshot()

        report = self.report('--write')

        self.assertIn({'item': 'output-styles/local.md', 'reason': 'not a link'}, report['skipped'])
        self.assertEqual((self.target / 'output-styles' / 'linked.md').resolve(), external)
        self.assertFalse((self.target / 'output-styles' / 'local.md').exists())
        self.assertFalse((self.target / 'hooks' / 'nested').exists())
        self.assertEqual(report['verification']['unexpected'], [])
        self.assertEqual(self.snapshot(), before)

    def test_non_utf8_entry_and_hook_payloads_keep_their_bytes_and_modes(self):
        entry = self.left / 'CLAUDE.md'
        entry.unlink()
        data = b'\xff\x00opaque payload\n'
        entry.write_bytes(data)
        script = self.left / 'hooks' / 'opaque.bin'
        script.write_bytes(data)
        script.chmod(0o700)
        before = self.snapshot()

        report = self.report('--write')

        for original, copied in ((entry, self.target / 'CLAUDE.md'),
                                 (script, self.target / 'hooks' / 'opaque.bin')):
            self.assertEqual(copied.read_bytes(), data)
            self.assertEqual(stat.S_IMODE(copied.stat().st_mode), stat.S_IMODE(original.stat().st_mode))
        self.assertEqual(report['verification']['unexpected'], [])
        self.assertEqual(self.snapshot(), before)

    def test_empty_profile_does_not_manufacture_settings_or_payloads(self):
        source = self.tmp / 'empty-profile'
        source.mkdir(mode=0o750)

        report = self.report('--write', source=source)

        self.assertFalse(report['settings'])
        self.assertEqual(report['files'], [])
        self.assertEqual(report['links'], [])
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertEqual(list(source.iterdir()), [])
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), stat.S_IMODE(source.stat().st_mode))
        self.assertEqual(report['verification']['unexpected'], [])

    def test_unreadable_payloads_preserve_source_and_existing_empty_target(self):
        entry = self.left / 'CLAUDE.md'
        entry.unlink()
        entry.write_text('Keep original rules\n', encoding='utf-8')
        self.target.mkdir(mode=0o750)
        mode = stat.S_IMODE(self.target.stat().st_mode)
        before = self.snapshot()
        read_bytes = Path.read_bytes
        for unavailable in (entry, self.left / 'hooks' / 'herdr.sh'):
            for options in ((), ('--write',)):
                with self.subTest(unavailable=unavailable.name, options=options):
                    def denied(path):
                        if path == unavailable:
                            raise PermissionError('payload read denied')
                        return read_bytes(path)

                    with mock.patch.object(Path, 'read_bytes', denied):
                        code, output, errors = self.copy(*options)
                    self.assertEqual(code, 1)
                    self.assertEqual(output, '')
                    self.assertIn('payload read denied', errors)
                    self.assertEqual(list(self.target.iterdir()), [])
                    self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), mode)
                    self.assertEqual(list(self.tmp.glob('.aem-copy-*')), [])
                    self.assertEqual(self.snapshot(), before)

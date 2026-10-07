"""Offline editing lookup distinguishes sources from installed copies."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import shlex
import tomlkit

from click.testing import CliRunner
from agent_env_man.cli import cli
from agent_env_man.setup import shell_block
import unittest
from unittest.mock import patch

from agent_env_man.git_source import Git
import test_publish as publication_tests


class Locate(unittest.TestCase):
    setUp = publication_tests.Publication.setUp
    git = publication_tests.Publication.git
    commit = publication_tests.Publication.commit
    cli = publication_tests.Publication.cli
    edit = publication_tests.Publication.edit

    def test_cd_path_output_and_json_usage_validation(self):
        runner = CliRunner()
        for args, expected in ((['locate', 'one', '--source', '--cd'], self.checkout / 'skill'),
                               (['locate', 'one', '--repo', '--cd'], self.checkout),
                               (['locate', 'one', '--source', '--repo', '--cd'], self.checkout),
                               (['catalog', 'locate', '--cd'], self.catalog.parent)):
            result = runner.invoke(cli, ['--config', str(self.config), *args])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(result.output, str(expected) + '\n')
        result = runner.invoke(cli, ['--config', str(self.root / 'missing'), '--json', 'locate', 'one', '--cd'])
        self.assertEqual(result.exit_code, 2)
        self.assertIn('--json', result.output)
        self.cli('apply', '--item', 'one')
        result = runner.invoke(cli, ['--config', str(self.config), 'locate', 'one', '--cd'])
        self.assertEqual(result.output, str(self.root / 'installed/one') + '\n')

    def test_repo_locates_all_consumer_kinds_without_payloads_or_network(self):
        self.document['sources']['shared']['branch'] = 'main'
        self.document['directories'] = {'cases': {'source': 'shared', 'subdir': 'missing',
                                                  'install': {'root': 'skills', 'destination': 'cases'}}}
        self.document['settings'] = {'editor': {'source': 'shared', 'path': 'missing.toml', 'format': 'toml'}}
        self.document['hooks'] = {'observer': {'source': 'shared', 'agents': {'claude': {
            'event': 'SessionEnd', 'runtime': 'python', 'script': 'missing.py'}}}}
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')
        machine = tomlkit.loads(self.config.read_text(encoding='utf-8'))
        machine['settings'] = {'editor': {'target': str(self.root / 'app/editor.toml')}}
        machine['agents'] = {'claude': {'root': str(self.root / 'claude'), 'skills': str(self.root / 'claude-skills')}}
        machine['runtimes'] = {'python': sys.executable}
        self.config.write_text(tomlkit.dumps(machine), encoding='utf-8')
        self.edit()
        (self.checkout / 'skill/SKILL.md').unlink()
        self.remote.rename(self.root / 'offline.git')
        state = self.root / 'machine.toml.state/state.json'
        before = state.read_bytes()
        members = ['cases', 'editor', 'observer', 'one', 'personal', 'two']
        with patch.object(Git, 'fetch', side_effect=AssertionError('locate fetched')):
            for name in members:
                with self.subTest(name=name):
                    report = self.cli('locate', name, '--repo')
                    self.assertEqual(report['root'], str(self.checkout))
                    self.assertEqual(report['entry'], str(self.checkout))
                    self.assertEqual(report['checkout'], str(self.checkout))
                    self.assertEqual(report['repository'], str(self.remote))
                    self.assertEqual(report['members'], members)
                    self.assertEqual(report['location'], 'source')
                    self.assertIsNone(report['installed_root'])
                    self.assertFalse(report['detached'])
        self.assertEqual(state.read_bytes(), before)

    def test_repo_bypasses_broken_installation_and_validates_checkout(self):
        self.cli('apply', '--item', 'one')
        (self.root / 'installed/one/SKILL.md').unlink()
        self.cli('locate', 'one', code=1)
        self.assertEqual(self.cli('locate', 'one', '--repo')['root'], str(self.checkout))
        self.git(self.checkout, 'checkout', '-b', 'other')
        self.assertIn('branch', self.cli('locate', 'one', '--repo', code=1))
        self.git(self.checkout, 'checkout', 'main')
        self.git(self.checkout, 'remote', 'set-url', 'origin', str(self.root / 'other.git'))
        self.assertIn('origin', self.cli('locate', 'one', '--repo', code=1))
        self.checkout.rename(self.root / 'missing-checkout')
        self.assertIn('bootstrap', self.cli('locate', 'one', '--repo', code=1))
        self.assertIn('unknown', self.cli('locate', 'unknown', '--repo', code=1))

    def test_repo_rejects_external_sources_and_incompatible_options(self):
        self.document['sources']['external'] = {'type': 'external'}
        self.document['skills']['outside'] = {'source': 'external'}
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')
        machine = tomlkit.loads(self.config.read_text(encoding='utf-8'))
        machine.setdefault('external_paths', {})['external'] = str(self.seed)
        self.config.write_text(tomlkit.dumps(machine), encoding='utf-8')
        self.assertIn('external', self.cli('locate', 'outside', '--repo', code=1))
        runner = CliRunner()
        for options in (['--repo', '--target'], ['--source', '--repo', '--target'],
                        ['--repo', '--cd', '--json']):
            args = ['--config', str(self.root / 'missing')]
            if '--json' in options:
                args += ['--json']
                options = [option for option in options if option != '--json']
            result = runner.invoke(cli, [*args, 'locate', 'one', *options])
            self.assertEqual(result.exit_code, 2, result.output)
        result = runner.invoke(cli, ['--config', str(self.root / 'missing'), 'locate', '--help'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('--repo', result.output)

    @unittest.skipUnless(os.name != 'nt' and shutil.which('bash'), 'Requires POSIX paths and Bash')
    def test_shell_cd_success_failure_help_and_literal_paths(self):
        executable = self.root / "aem tool"
        executable.write_text('#!/bin/sh\nexec ' + shlex.join([sys.executable, '-m', 'agent_env_man']) + ' "$@"\n')
        executable.chmod(0o755)
        block = shell_block('bash', self.config, executable, executable.parent)[2]
        script = block + '\n' + shlex.join(['aem', '--config', str(self.config), 'locate', 'one', '--source', '--cd'])
        script += '\npwd\n' + shlex.join(['aem', '--config', str(self.config), 'locate', 'missing', '--cd'])
        script += '\nstatus=$?; pwd; test "$status" = 1 || exit 9\n'
        script += 'aem locate --cd --help\npwd\n'
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines().count(str(self.checkout / 'skill')), 3)
        self.assertIn('Usage:', result.stdout)

    @unittest.skipUnless(os.name != 'nt' and shutil.which('bash'), 'Requires POSIX paths and Bash')
    def test_shell_repo_cd_and_failure_preserve_directory(self):
        executable = self.root / 'aem tool'
        executable.write_text('#!/bin/sh\nexec ' + shlex.join([sys.executable, '-m', 'agent_env_man']) + ' "$@"\n')
        executable.chmod(0o755)
        block = shell_block('bash', self.config, executable, executable.parent)[2]
        script = block + '\n' + shlex.join(['aem', '--config', str(self.config), 'locate', 'one', '--source', '--repo', '--cd'])
        script += '\npwd\n' + shlex.join(['aem', '--config', str(self.config), 'locate', 'missing', '--repo', '--cd'])
        script += '\nstatus=$?; pwd; test "$status" = 1 || exit 9\n'
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [str(self.checkout), str(self.checkout)])

    @unittest.skipUnless(os.name != 'nt' and shutil.which('bash'), 'Requires POSIX paths and Bash')
    def test_shell_cd_treats_special_characters_as_literal(self):
        destination = self.root / "directory with '$() chars"
        destination.mkdir()
        executable = self.root / 'fake-aem'
        executable.write_text('#!/bin/sh\nprintf \'%s\\n\' ' + shlex.quote(str(destination)) + '\n')
        executable.chmod(0o755)
        block = shell_block('bash', self.config, executable, executable.parent)[2]
        result = subprocess.run(['bash', '-c', block + '\naem locate one --cd\npwd\n'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, str(destination) + '\n')

    def require_links(self):
        probe = self.root / "probe"
        try:
            probe.symlink_to(self.catalog)
        except OSError:
            self.skipTest("Symbolic link capability unavailable")
        probe.unlink()

    def test_prepared_skill_and_instruction_lookup_is_offline_and_read_only(self):
        state = self.root / 'machine.toml.state/state.json'
        before = state.read_bytes()
        self.remote.rename(self.root / 'offline.git')
        with patch.object(Git, 'fetch', side_effect=AssertionError('Unexpected fetch')):
            skill = self.cli('locate', 'one')
            instruction = self.cli('locate', 'personal')
        self.assertEqual(skill['root'], str(self.checkout / 'skill'))
        self.assertEqual(skill['entry'], str(self.checkout / 'skill/SKILL.md'))
        self.assertEqual(skill['checkout'], str(self.checkout))
        self.assertEqual(skill['members'], ['one', 'personal', 'two'])
        self.assertIsNone(skill['installed_root'])
        self.assertEqual(instruction['entry'], str(self.checkout / 'AGENTS.md'))
        self.assertEqual(state.read_bytes(), before)
        self.assertIn('not been installed', self.cli('agent-hook', 'personal', '--agent', 'codex')[
            'stopReason'])

    def test_copy_lookup_and_explicit_source_remain_distinct_after_detach(self):
        self.cli('apply', '--item', 'one')
        installed = self.root / 'installed/one'
        self.assertEqual(self.cli('locate', 'one')['root'], str(installed))
        source = self.cli('locate', 'one', '--source')
        self.assertEqual(source['root'], str(self.checkout / 'skill'))
        Path(source['entry']).write_text('# Edited at source\n', encoding='utf-8')
        self.cli('publish', 'one', '-m', 'Edit located source')
        self.assertEqual(self.git(self.remote, 'show', 'main:skill/SKILL.md'), '# Edited at source')
        self.assertEqual((installed / 'SKILL.md').read_text(), '# Skill\n')
        self.cli('detach', 'one')
        self.assertTrue(self.cli('locate', 'one')['detached'])
        self.assertEqual(self.cli('locate', 'one', '--source')['root'], source['root'])
        self.catalog.unlink()
        self.checkout.rename(self.root / "offline-checkouts")
        self.assertEqual(self.cli('locate', 'one')['root'], str(installed))
        self.cli('locate', 'one', '--source', code=1)

    def test_installed_link_and_replaced_copy_do_not_silently_fall_back(self):
        self.require_links()
        import tomlkit

        self.document['skills']['one'].setdefault('install', {})['mode'] = 'link'
        self.catalog.write_text(tomlkit.dumps(self.document), encoding='utf-8')
        self.cli('apply', '--item', 'one')
        target = self.root / 'installed/one'
        self.assertEqual(self.cli('locate', 'one')['root'], str(self.checkout / 'skill'))
        target.unlink()
        target.mkdir()
        self.assertIn('replaced', self.cli('locate', 'one', code=1))
        self.assertEqual(self.cli('locate', 'one', '--source')['root'], str(self.checkout / 'skill'))

    def test_source_requires_prepared_valid_entry_but_accepts_dirty_work(self):
        self.edit()
        self.cli('locate', 'one', '--source')
        (self.checkout / 'skill/SKILL.md').unlink()
        self.assertIn('missing', self.cli('locate', 'one', code=1))
        self.cli('locate', 'unknown', code=1)
        self.checkout.rename(self.root / "offline-checkouts")
        self.assertIn('bootstrap', self.cli('locate', 'personal', code=1))

    def test_redirected_source_entry_is_rejected(self):
        self.require_links()
        entry = self.checkout / 'skill/SKILL.md'
        entry.unlink()
        entry.symlink_to(self.checkout / 'AGENTS.md')
        self.assertIn('symlink', self.cli('locate', 'one', code=1))

    def test_detached_instruction_lookup_can_explicitly_find_publish_source(self):
        self.require_links()
        self.cli('apply', '--item', 'personal:entry')
        self.cli('detach', 'personal:bundle', 'personal:entry')
        saved = self.cli('locate', 'personal')
        source = self.cli('locate', 'personal', '--source')
        self.assertTrue(saved['detached'])
        self.assertFalse(source['detached'])
        self.assertNotEqual(saved['root'], source['root'])
        self.assertEqual(source['checkout'], str(self.checkout))

    def test_saved_copy_survives_old_state_and_invalid_catalog_fields(self):
        self.cli('apply', '--item', 'one')
        state = self.root / 'machine.toml.state/state.json'
        data = json.loads(state.read_text())
        data['version'] = 1
        state.write_text(json.dumps(data))
        with self.config.open('a') as output:
            output.write('\n[obsolete]\nkeep = true\n')
        self.catalog.unlink()
        before = state.read_bytes()
        self.assertEqual(self.cli('locate', 'one')['root'], str(self.root / 'installed/one'))
        self.assertEqual(state.read_bytes(), before)

"""Instruction metadata reaches child agents without changing session callbacks."""
import base64
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import shlex
import shutil
from unittest.mock import patch

import tomlkit

from agent_env_man import agents, hooks
from agent_env_man.model import Config
from agent_env_man.storage import State
from process_support import run_hidden
from test_setup import SetupFixture


class SubagentHooks(SetupFixture):
    def configure_agents(self):
        self.configure()
        document = tomlkit.parse(self.catalog.read_text())
        del document['instructions']['personal']['install']['entry']
        self.catalog.write_text(tomlkit.dumps(document))
        self.setup_cli('--agent', 'codex', '--agent', 'claude')

    def hook_record(self, agent):
        key = 'personal:hook' + ('@claude' if agent == 'claude' else '')
        return self.state()['items'][key]

    def invoke(self, group, event):
        return run_hidden(shlex.split(group['hooks'][0]['command']),
                          input=json.dumps({'hook_event_name': event, 'agent_type': 'Explore',
                                            'agent_id': 'test-child'}),
                          capture_output=True, text=True, encoding='utf-8')

    def legacy_install(self):
        # The 1.2.0 contract has the same primary groups/commands and one saved
        # hook_group per item. It has no additional event ownership field.
        adapters = {name: replace(agents.profile(name), instruction_events=('SessionStart',))
                    for name in ('codex', 'claude')}
        with patch.dict(agents.PROFILES, adapters):
            self.run_cli('apply')
        state = State(Config(self.config).state_dir)
        for record in state.data['items'].values():
            record.pop('additional_hook_groups', None)
        state.save()

    def status_for(self, agent):
        key = 'personal:hook' + ('@claude' if agent == 'claude' else '')
        return next(item for item in self.run_cli('status')['items'] if item['item'] == key)

    def test_installed_subagent_callbacks_deliver_locations(self):
        self.configure_agents()
        self.run_cli('apply')
        for agent in ('codex', 'claude'):
            with self.subTest(agent=agent):
                record = self.hook_record(agent)
                groups = json.loads(Path(record['target']).read_text())['hooks']
                self.assertIn('SubagentStart', groups)
                self.assertEqual(len(groups['SubagentStart']), 1)
                group = groups['SubagentStart'][0]
                self.assertNotIn('matcher', group)
                saved = self.state()
                result = self.invoke(group, 'SubagentStart')
                self.assertEqual(self.state(), saved)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                context = json.loads(result.stdout)['hookSpecificOutput']
                self.assertEqual(context['hookEventName'], 'SubagentStart')
                locations = json.loads(context['additionalContext'].splitlines()[1])
                self.assertEqual(locations['root'], str(self.bundle))
                self.assertEqual(locations['entry'], str(self.bundle / 'start.md'))
                self.assertNotIn('Read development/rules.md', context['additionalContext'])

    def test_legacy_upgrade_preserves_commands_user_hooks_and_preview(self):
        self.configure_agents()
        self.legacy_install()
        before = {}
        user_group = '{"hooks":[{"type":"command","command":"echo user","number":1.234567890123456789}]}'
        for agent in ('codex', 'claude'):
            record = self.hook_record(agent)
            path = Path(record['target'])
            document = json.loads(path.read_text())
            session = json.dumps(document['hooks']['SessionStart'])
            path.write_text('{"keep":true,"hooks":{"SessionStart":' + session
                            + ',"SubagentStart":[' + user_group + ']}}', encoding='utf-8')
            before[agent] = (record, path.read_bytes())
            self.assertEqual(self.status_for(agent)['status'], 'stale')
        state_path = Config(self.config).state_dir / 'state.json'
        saved = state_path.read_bytes()
        preview = self.run_cli('apply', '--item', 'personal:entry', '--dry-run')
        self.assertEqual(state_path.read_bytes(), saved)
        for agent, (record, content) in before.items():
            self.assertEqual(Path(record['target']).read_bytes(), content)
        self.run_cli('apply', '--item', 'personal:entry')
        for agent, (previous, content) in before.items():
            record = self.hook_record(agent)
            path = Path(record['target'])
            document = json.loads(path.read_text())
            self.assertEqual(record['hook_group'], previous['hook_group'])
            self.assertEqual(record['hook_marker'], previous['hook_marker'])
            self.assertEqual(document['hooks']['SessionStart'], json.loads(content)['hooks']['SessionStart'])
            self.assertEqual(len(document['hooks']['SubagentStart']), 2)
            self.assertIn(user_group, path.read_text())
            self.assertTrue(document['keep'])
            self.assertEqual(self.status_for(agent)['status'], 'current')
            row = next(r for r in preview if r['target'] == str(path))
            self.assertEqual(row['hook_group'], previous['hook_group'])
            self.assertEqual(row['additional_hook_groups'], record['additional_hook_groups'])
            installed = path.read_bytes()
            self.run_cli('apply', '--agent', agent)
            self.setup_cli('--agent', agent)
            self.assertEqual(path.read_bytes(), installed)
            # A released callback still uses its original output transport,
            # even if its stdin contains an unrelated event name.
            result = self.invoke(previous['hook_group'], 'SubagentStart')
            self.assertEqual(result.returncode, 0, result.stderr)
            if agent == 'codex':
                self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['hookEventName'], 'SessionStart')
            else:
                self.assertTrue(result.stdout.startswith('AEM instruction document locations'))

    def test_upgrade_refuses_existing_primary_hook_edits(self):
        self.configure_agents()
        self.legacy_install()
        for agent in ('codex', 'claude'):
            with self.subTest(agent=agent):
                path = Path(self.hook_record(agent)['target'])
                document = json.loads(path.read_text())
                document['hooks']['SessionStart'][-1]['hooks'][0]['command'] = 'echo local edit'
                path.write_text(json.dumps(document))
                before, state = path.read_bytes(), self.state()
                self.run_cli('apply', '--agent', agent, code=1)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(self.state(), state)
                self.run_cli('apply', '--agent', agent, '--item', 'personal:entry', '--replace')
                self.assertIn('SubagentStart', json.loads(path.read_text())['hooks'])

    def test_child_hook_edits_removal_and_duplicates_preserve_files_and_state(self):
        self.configure_agents()
        self.run_cli('apply')
        for agent in ('codex', 'claude'):
            path = Path(self.hook_record(agent)['target'])
            original = path.read_bytes()
            for change in ('edit', 'delete', 'duplicate'):
                with self.subTest(agent=agent, change=change):
                    document = json.loads(original)
                    groups = document['hooks']['SubagentStart']
                    if change == 'edit':
                        groups[0]['hooks'][0]['command'] = 'echo local edit'
                    elif change == 'delete':
                        groups.clear()
                    else:
                        groups.append(deepcopy(groups[0]))
                    path.write_text(json.dumps(document))
                    before, state = path.read_bytes(), self.state()
                    self.assertEqual(self.status_for(agent)['status'], 'modified-locally')
                    self.assertEqual(self.status_for(agent)['installation'], 'modified-locally')
                    self.run_cli('apply', '--agent', agent, code=1)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(self.state(), state)
                    self.run_cli('apply', '--item', 'personal:entry', '--agent', agent,
                                 '--replace', code=1 if change == 'duplicate' else 0)
                    if change == 'duplicate':
                        self.assertEqual(path.read_bytes(), before)
                        self.assertEqual(self.state(), state)
                    else:
                        self.assertEqual(self.status_for(agent)['status'], 'current')
                    path.write_bytes(original)

    def test_detached_copy_callbacks_work_without_catalog_or_sources(self):
        self.configure_agents()
        document = tomlkit.parse(self.catalog.read_text())
        document['instructions']['personal']['install']['bundle']['mode'] = 'copy'
        self.catalog.write_text(tomlkit.dumps(document))
        self.run_cli('apply')
        before = {agent: Path(self.hook_record(agent)['target']).read_bytes()
                  for agent in ('codex', 'claude')}
        self.run_cli('detach', 'personal:bundle', 'personal:entry', 'report')
        self.catalog.unlink()
        shutil.rmtree(self.external)
        self.setup_cli('--remove-agent', 'codex', '--remove-agent', 'claude')
        state_path = Config(self.config).state_dir / 'state.json'
        saved = state_path.read_bytes()
        for agent in ('codex', 'claude'):
            with self.subTest(agent=agent):
                record = self.hook_record(agent)
                actual = json.loads(Path(record['target']).read_text())['hooks']
                self.assertEqual(actual['SubagentStart'], json.loads(before[agent])['hooks']['SubagentStart'])
                self.assertEqual(actual['SessionStart'], [record['hook_group']])
                result = self.invoke(actual['SubagentStart'][0], 'SubagentStart')
                self.assertEqual(result.returncode, 0, result.stderr)
                locations = json.loads(json.loads(result.stdout)['hookSpecificOutput']['additionalContext'].splitlines()[1])
                located = self.run_cli('locate', 'personal', '--agent', agent)
                self.assertEqual(locations['root'], located['root'])
                self.assertTrue(record['detached'])
        self.assertEqual(state_path.read_bytes(), saved)

    def test_subagent_lookup_failures_do_not_claim_to_stop_creation(self):
        self.configure_agents()
        self.run_cli('apply')
        (self.bundle / 'start.md').unlink()
        for agent in ('codex', 'claude'):
            with self.subTest(agent=agent):
                group = self.hook_record(agent)['additional_hook_groups']['SubagentStart']
                result = self.invoke(group, 'SubagentStart')
                if agent == 'codex':
                    self.assertEqual(result.returncode, 0, result.stderr)
                    response = json.loads(result.stdout)
                    self.assertIn('lookup failed', response['systemMessage'])
                    self.assertNotIn('continue', response)
                    self.assertNotIn('hookSpecificOutput', response)
                else:
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, '')
                    self.assertIn('lookup failed', result.stderr)

    def test_interrupted_upgrade_recovers_both_events_and_can_retry(self):
        self.configure_agents()
        self.legacy_install()
        for agent in ('codex', 'claude'):
            with self.subTest(agent=agent):
                path = Path(self.hook_record(agent)['target'])
                before, record = path.read_bytes(), self.hook_record(agent)
                original = os.replace

                def interrupt(src, dst):
                    original(src, dst)
                    if Path(dst) == path and Path(src).name.startswith('.aem-stage-'):
                        raise KeyboardInterrupt('Simulated interruption before ownership commit')

                with patch('agent_env_man.manager.os.replace', side_effect=interrupt):
                    self.run_cli('apply', '--agent', agent, code=1)
                self.assertIsNotNone(self.state()['pending'])
                self.assertIn('SubagentStart', json.loads(path.read_text())['hooks'])
                self.assertEqual(self.hook_record(agent), record)
                self.run_cli('recover')
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(self.hook_record(agent), record)
                self.assertIsNone(self.state()['pending'])
                self.run_cli('apply', '--agent', agent)
                self.assertEqual(self.status_for(agent)['status'], 'current')

    def test_windows_subagent_commands_retain_literal_arguments_and_exit_transport(self):
        config = Path("C:/Users/space ' and $name/machine.toml")
        for agent in ('codex', 'claude'):
            with self.subTest(agent=agent), patch.object(hooks.os, 'name', 'nt'):
                _, _, additional = agents.instruction_definition(agent, config, 'personal')
                command = additional['SubagentStart']['hooks'][0]['command']
            decoded = base64.b64decode(command.split()[-1]).decode('utf-16le')
            self.assertIn("'--hook-event' 'SubagentStart'", decoded)
            self.assertIn("'" + str(config).replace("'", "''") + "'", decoded)
            self.assertEqual(decoded.endswith('; exit $LASTEXITCODE'), agent == 'claude')

"""Package-coupled Git sources keep checkouts still in automation and report drift."""

from contextlib import redirect_stderr, redirect_stdout
import io
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man import automation
from agent_env_man.cli import main
from agent_env_man.git_source import Git
from agent_env_man.manager import Manager
from agent_env_man.model import Config, Error
from agent_env_man.storage import State
from agent_env_man.updates import resolve_policies, startup_briefing
import test_skill_catalog as skill_tests


NOTE = "uv tool install --force ."


class SourcePackages(unittest.TestCase):
    setUp = skill_tests.SkillCatalog.setUp
    git = skill_tests.SkillCatalog.git
    commit = skill_tests.SkillCatalog.commit
    repository = skill_tests.SkillCatalog.repository
    save_catalog = skill_tests.SkillCatalog.save_catalog
    run_cli = skill_tests.SkillCatalog.run_cli
    bootstrap = skill_tests.SkillCatalog.bootstrap
    copy_mode = skill_tests.SkillCatalog.copy_mode
    update_policy = skill_tests.SkillCatalog.update_policy
    publish_skill_change = skill_tests.SkillCatalog.publish_skill_change

    def declare(self, package=None):
        self.catalog_sources['report']['package'] = {'note': NOTE} if package is None else package
        self.save_catalog()

    def checkout_head(self):
        return self.git(self.checkouts / '.aem-repositories/report', 'rev-parse', 'HEAD')

    def manager(self):
        config = Config(self.config)
        return Manager(config, State(config.state_dir))

    def load(self, package):
        document = {'version': 2, 'sources': {'report': {'type': 'git', 'repository': str(self.repo),
                                                         'package': package}},
                    'skills': {'report': {'source': 'report', 'subdir': 'skills/report'}}}
        config = Config(self.config, document={'version': 1, 'catalog': str(self.catalog),
                        'checkout_root': str(self.checkouts), 'roots': {'skills': str(self.destination)}},
                        catalog_document=document)
        config.catalog()
        return config

    def test_schema_accepts_git_declarations_and_rejects_other_shapes(self):
        self.assertEqual(self.load({}).package('report'), {})
        self.assertEqual(self.load({'note': NOTE}).package('report'), {'note': NOTE})
        for package in (True, 'note', [], {'note': ''}, {'note': '  '}, {'note': 1}, {'command': 'x'}):
            with self.subTest(package=package), self.assertRaises(Error):
                self.load(package)
        document = {'version': 2, 'sources': {'shared': {'type': 'external', 'package': {}}},
                    'instructions': {'personal': {'source': 'shared', 'entry': 'AGENTS.md'}}}
        self.catalog.write_text(tomlkit.dumps(document), encoding='utf-8')
        message = self.bootstrap(code=1)
        self.assertIn('package is supported only for Git sources', str(message))

    def test_policy_precedence_puts_package_default_after_catalog_defaults(self):
        updates = {'defaults': {'trigger': ['agent-start'], 'action': 'sync'},
                   'policies': {'follow': {'action': 'sync'}}}
        skills = {'plain': {'repo': 'other'}, 'coupled': {'repo': 'tools'},
                  'named': {'repo': 'tools', 'update': {'policy': 'follow'}},
                  'local': {'repo': 'tools', 'update': {'action': 'sync'}}}
        result = resolve_policies(updates, skills, packaged=frozenset({'tools'}))
        self.assertEqual({name: policy['action'] for name, policy in result.items()},
                         {'plain': 'sync', 'coupled': 'check', 'named': 'sync', 'local': 'sync'})
        self.assertEqual(result['coupled']['trigger'], ['agent-start'])

    def test_automatic_default_checks_and_reports_pending_reinstall(self):
        self.copy_mode()
        self.declare()
        self.update_policy({'trigger': ['agent-start']})
        self.bootstrap()
        self.run_cli('apply')
        head = self.checkout_head()
        before = (self.destination / 'report/SKILL.md').read_bytes()
        self.publish_skill_change()
        result = self.run_cli('auto', '--trigger', 'agent-start')
        self.assertEqual(result[0]['policy']['action'], 'check')
        self.assertEqual(result[0]['status'], 'checked')
        self.assertEqual(result[0]['package'], {'reinstall': 'after-update', 'note': NOTE})
        self.assertIn(NOTE, result[0]['notice'])
        self.assertEqual(self.checkout_head(), head)
        self.assertEqual((self.destination / 'report/SKILL.md').read_bytes(), before)
        briefing = startup_briefing(result)
        self.assertIn('report: incoming revision', briefing)
        self.assertNotIn(NOTE, briefing)
        status = self.run_cli('status')['sources'][0]
        self.assertEqual(status['remote_relation'], 'behind')
        self.assertEqual(status['package']['reinstall'], 'after-update')

    def test_no_notice_without_incoming_revision_or_declaration(self):
        self.copy_mode()
        self.declare()
        self.update_policy({'trigger': ['agent-start']})
        self.bootstrap()
        result = self.run_cli('auto', '--trigger', 'agent-start')
        self.assertEqual(result[0]['status'], 'checked')
        self.assertNotIn('package', result[0])
        del self.catalog_sources['report']['package']
        self.save_catalog()
        self.update_policy({'trigger': ['agent-start']})
        self.publish_skill_change()
        with patch('agent_env_man.updates.time.time', return_value=10 ** 10):
            result = self.run_cli('auto', '--trigger', 'agent-start')
        self.assertEqual(result[0]['status'], 'synced')
        self.assertNotIn('package', result[0])
        self.assertNotIn('package', self.run_cli('update', 'report')[0])

    def test_explicit_update_and_automatic_sync_report_revisions(self):
        self.copy_mode()
        self.declare()
        self.bootstrap()
        previous = self.checkout_head()
        self.publish_skill_change()
        result = self.run_cli('update', 'report')
        revision = self.checkout_head()
        self.assertNotEqual(previous, revision)
        self.assertEqual(result[0]['package'], {'reinstall': 'required', 'previous_revision': previous,
                                                'revision': revision, 'note': NOTE})
        self.assertIn(f'{previous[:8]} -> {revision[:8]}', result[0]['notice'])
        self.assertNotIn('package', self.run_cli('update', 'report')[0])

        output = io.StringIO()
        self.publish_skill_change()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--config', str(self.config), 'update', 'report']), 0)
        self.assertIn('reinstall the package', output.getvalue())
        self.assertIn(NOTE, output.getvalue())

        self.skills['report']['update'] = {'action': 'sync', 'trigger': ['agent-start']}
        self.save_catalog()
        previous = self.checkout_head()
        self.publish_skill_change()
        result = self.run_cli('auto', '--trigger', 'agent-start')
        self.assertEqual(result[0]['status'], 'synced')
        self.assertEqual(result[0]['package']['reinstall'], 'required')
        self.assertIn('(reinstall its package)', startup_briefing(result))
        self.assertEqual(result[0]['package']['previous_revision'], previous)

    def test_full_mode_fetches_declared_sources_unless_policy_selects_sync(self):
        self.copy_mode()
        self.declare()
        self.bootstrap()
        with patch.object(Git, 'fetch', side_effect=AssertionError('Unexpected fetch')):
            report, failed = automation.full_content(self.manager(), 30, dry_run=True)
        self.assertFalse(failed)
        self.assertEqual((report['sources'], report['checked_sources'], report['status']), ([], ['report'], 'planned'))

        head = self.checkout_head()
        report, failed = automation.full_content(self.manager(), 30)
        self.assertFalse(failed, report)
        self.assertEqual(report['check'][0]['status'], 'checked')
        self.assertNotIn('package', report['check'][0])
        self.publish_skill_change()
        report, failed = automation.full_content(self.manager(), 30)
        self.assertFalse(failed, report)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['check'][0]['remote_relation'], 'behind')
        self.assertEqual(report['check'][0]['package']['reinstall'], 'after-update')
        self.assertNotIn('update', report)
        self.assertEqual(self.checkout_head(), head)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.run_cli('status')['sources'][0]['package']['reinstall'], 'after-update')

        self.skills['report']['update'] = {'action': 'sync'}
        self.save_catalog()
        report, failed = automation.full_content(self.manager(), 30)
        self.assertFalse(failed, report)
        self.assertEqual(report['sources'], ['report'])
        self.assertNotIn('checked_sources', report)
        self.assertNotEqual(self.checkout_head(), head)
        self.assertEqual(report['update'][0]['package']['reinstall'], 'required')

    def test_settings_automation_only_checks_declared_sources(self):
        from agent_env_man.updates import run_settings_updates
        (self.repo / 'editor.toml').write_text('color = "blue"\n', encoding='utf-8')
        self.commit(self.repo)
        self.copy_mode()
        self.declare()
        document = tomlkit.parse(self.catalog.read_text(encoding='utf-8'))
        document['settings'] = {'editor': {'source': 'report', 'path': 'editor.toml', 'format': 'toml',
                                           'update': {'trigger': ['interval']}}}
        self.catalog.write_text(tomlkit.dumps(document), encoding='utf-8')
        self.run_cli('bootstrap', '--catalog', self.catalog, '--checkout-root', self.checkouts,
                     '--root', f'skills={self.destination}',
                     '--setting-target', f'editor={self.root / "editor.toml"}')
        self.run_cli('apply')
        head = self.checkout_head()
        self.publish_skill_change()
        report, failed = run_settings_updates(self.manager(), 'interval')
        self.assertFalse(failed, report)
        self.assertEqual(report[0]['status'], 'checked')
        self.assertEqual(report[0]['remote_relation'], 'behind')
        self.assertEqual(report[0]['package']['reinstall'], 'after-update')
        self.assertEqual(self.checkout_head(), head)

    def test_full_mode_check_failure_does_not_block_other_sources(self):
        self.copy_mode()
        other = self.repository('other', '.')
        self.catalog_sources['other'] = {'type': 'git', 'repository': str(other)}
        self.skills['other'] = {'source': 'other', 'install': {'mode': 'copy'}}
        self.declare()
        self.bootstrap()
        original = Git.fetch

        def fetch(git, source):
            if source.name == 'report':
                raise Error('offline')
            return original(git, source)
        with patch.object(Git, 'fetch', fetch):
            report, failed = automation.full_content(self.manager(), 30)
        self.assertTrue(failed)
        self.assertEqual(report['check'], [{'source': 'report', 'status': 'failed', 'error': 'offline'}])
        self.assertEqual(report['sources'], ['other'])
        self.assertTrue((self.destination / 'other/SKILL.md').exists())

if __name__ == '__main__':
    unittest.main()

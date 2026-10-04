"""Local inventories deliver independent Git skill repositories end to end."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man.cli import main
from agent_env_man.git_source import Git
from agent_env_man.model import Config, Error
from agent_env_man.storage import fingerprint


class SkillCatalog(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="aem-skills-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "machine.toml"
        self.catalog = self.root / "inventory/skills.toml"
        self.catalog.parent.mkdir()
        self.checkouts = self.root / "checkouts"
        self.destination = self.root / "installed-skills"
        self.environment = patch.dict(os.environ, {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.repo = self.repository("research-tools", "skills/report")
        self.catalog_sources = {'report': {'type': 'git', 'repository': str(self.repo)}}
        self.skills = {'report': {'subdir': 'skills/report', 'source': 'report'}}
        self.save_catalog()

    def git(self, path, *args):
        result = subprocess.run(["git", "-C", str(path), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, path):
        self.git(path, "add", "-A")
        self.git(path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "Test content")

    def repository(self, name, skill_path):
        repo = self.root / name
        folder = repo / skill_path
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("---\nname: report\ndescription: Test skill\n---\n\nUse the test helper.\n", encoding="utf-8")
        (folder / "helper.py").write_text("print('test')\n", encoding="utf-8")
        self.git(repo, "init", "-b", "main")
        self.commit(repo)
        return repo

    def save_catalog(self):
        self.catalog.write_text(tomlkit.dumps({'version': 2, 'sources': self.catalog_sources, 'skills': self.skills}), encoding="utf-8")

    def run_cli(self, *args, code=0, config=None):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = main(["--json", "--config", str(config or self.config), *map(str, args)])
        self.assertEqual(result, code, f"{args}\n{output.getvalue()}\n{errors.getvalue()}")
        return json.loads(output.getvalue()) if output.getvalue() else errors.getvalue()

    def bootstrap(self, **kwargs):
        return self.run_cli("bootstrap", "--catalog", self.catalog, "--checkout-root", self.checkouts,
                            "--root", f"skills={self.destination}", **kwargs)

    def require_links(self):
        probe = self.root / "link-probe"
        try:
            probe.symlink_to(self.catalog)
        except OSError:
            self.skipTest("Symbolic link capability unavailable")
        probe.unlink()

    def copy_mode(self):
        self.skills['report'].setdefault('install', {})['mode'] = "copy"
        self.save_catalog()

    def update_policy(self, defaults, policies=None):
        document = tomlkit.parse(self.catalog.read_text(encoding="utf-8"))
        document["updates"] = {"defaults": defaults, "policies": policies or {}}
        self.catalog.write_text(tomlkit.dumps(document), encoding="utf-8")

    def publish_skill_change(self):
        descriptor = self.repo / "skills/report/SKILL.md"
        descriptor.write_text(descriptor.read_text() + "Published change\n", encoding="utf-8")
        self.commit(self.repo)

    def test_auto_defaults_to_manual_and_explicit_sync_still_works(self):
        self.copy_mode()
        self.bootstrap()
        self.publish_skill_change()
        with patch.object(Git, "fetch", side_effect=AssertionError("Unexpected fetch")):
            result = self.run_cli("auto", "--trigger", "shell-start")
        self.assertEqual(result[0]["status"], "not-triggered")
        self.assertFalse(self.destination.exists())
        self.run_cli("sync")
        self.assertIn("Published change", (self.destination / "report/SKILL.md").read_text())

    def test_auto_check_fetches_without_changing_checkout_or_target(self):
        self.copy_mode()
        self.update_policy({"trigger": ["shell-start", "agent-start"], "action": "check"})
        self.bootstrap()
        self.run_cli("apply")
        checkout = self.checkouts / ".aem-repositories/report"
        head = self.git(checkout, "rev-parse", "HEAD")
        before = (self.destination / "report/SKILL.md").read_bytes()
        self.publish_skill_change()
        result = self.run_cli("auto", "--trigger", "agent-start")
        self.assertEqual(result[0]["status"], "checked")
        self.assertEqual(result[0]["remote_relation"], "behind")
        self.assertEqual(self.git(checkout, "rev-parse", "HEAD"), head)
        self.assertEqual((self.destination / "report/SKILL.md").read_bytes(), before)
        self.assertEqual(self.run_cli("status")["sources"][0]["automation"]["status"], "checked")

    def test_auto_sync_updates_link_and_copy(self):
        self.require_links()
        for mode in ("link", "copy"):
            with self.subTest(mode=mode):
                config = self.root / f"{mode}.toml"
                destination = self.root / f"{mode}-targets"
                self.skills['report'].setdefault('install', {})['mode'] = mode
                self.save_catalog()
                self.update_policy({'trigger': ['shell-start']})
                self.run_cli("bootstrap", "--catalog", self.catalog, "--root", f"skills={destination}", config=config)
                self.run_cli("apply", config=config)
                self.publish_skill_change()
                result = self.run_cli("auto", "--trigger", "shell-start", config=config)
                self.assertEqual(result[0]["status"], "synced")
                self.assertEqual((destination / "report/SKILL.md").read_bytes(),
                                 (self.repo / "skills/report/SKILL.md").read_bytes())
                self.assertEqual((destination / "report").is_symlink(), mode == "link")

    def test_auto_policy_preview_is_offline_and_does_not_record_attempt(self):
        self.copy_mode()
        self.skills["report"]["update"] = {"policy": "observe", "timeout": 7}
        self.save_catalog()
        self.update_policy({"trigger": ["shell-start", "interval"], "min_interval": 1200},
                           {"observe": {'action': 'check', 'trigger': ['agent-start']}})
        self.bootstrap()
        state_path = self.config.parent / (self.config.name + ".state/state.json")
        before = state_path.read_bytes()
        with patch.object(Git, "fetch", side_effect=AssertionError("Unexpected fetch")):
            result = self.run_cli("auto", "--trigger", "agent-start", "--dry-run")
        self.assertEqual(result[0]["status"], "planned")
        self.assertEqual(result[0]["policy"], {"trigger": ["agent-start"], "action": "check",
                                              "timeout": 7, "min_interval": 1200})
        self.assertEqual(state_path.read_bytes(), before)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.run_cli("auto", "--trigger", "shell-start")[0]["status"], "not-triggered")

    def test_auto_attempt_intervals_are_per_skill_and_shared_across_events(self):
        self.copy_mode()
        other = self.repository("other", ".")
        self.catalog_sources['other'] = {'type': 'git', 'repository': str(other)}
        self.skills['other'] = {'update': {'min_interval': 60}, 'source': 'other', 'install': {'mode': 'copy'}}
        self.save_catalog()
        self.update_policy({"trigger": ["shell-start", "interval"], "action": "check", "min_interval": 600})
        self.bootstrap()
        with patch("agent_env_man.updates.time.time", return_value=1000):
            self.run_cli("auto", "--trigger", "shell-start")
        with patch("agent_env_man.updates.time.time", return_value=1060):
            result = self.run_cli("auto", "--trigger", "interval")
        self.assertEqual({r["skill"]: r["status"] for r in result}, {"report": "throttled", "other": "checked"})
        with patch("agent_env_man.updates.time.time", return_value=1600):
            result = self.run_cli("auto", "--trigger", "shell-start", "--item", "report")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "checked")

    def test_auto_failed_skill_does_not_block_others_and_failure_is_throttled(self):
        self.copy_mode()
        other = self.repository("other", ".")
        self.catalog_sources['other'] = {'type': 'git', 'repository': str(other)}
        self.skills['other'] = {'source': 'other', 'install': {'mode': 'copy'}}
        self.save_catalog()
        self.update_policy({'trigger': ['shell-start']})
        self.bootstrap()
        self.repo.rename(self.root / "unavailable-research-tools")
        with patch("agent_env_man.updates.time.time", return_value=1000):
            result = self.run_cli("auto", "--trigger", "shell-start", code=1)
        self.assertEqual({r["skill"]: r["status"] for r in result}, {"report": "failed", "other": "synced"})
        self.assertTrue((self.destination / "other/SKILL.md").is_file())
        with patch("agent_env_man.updates.time.time", return_value=1001):
            result = self.run_cli("auto", "--trigger", "shell-start")
        self.assertEqual([r["status"] for r in result], ["throttled", "throttled"])

    def test_auto_preserves_modified_copies_and_detached_skills(self):
        self.copy_mode()
        self.update_policy({'trigger': ['shell-start'], 'min_interval': 0})
        self.bootstrap()
        self.run_cli("apply")
        target = self.destination / "report/SKILL.md"
        target.write_text("Local edits", encoding="utf-8")
        self.publish_skill_change()
        self.assertEqual(self.run_cli("auto", "--trigger", "shell-start", code=1)[0]["status"], "failed")
        self.assertEqual(target.read_text(), "Local edits")
        self.run_cli("detach", "report")
        with patch.object(Git, "fetch", side_effect=AssertionError("Unexpected fetch")):
            self.assertEqual(self.run_cli("auto", "--trigger", "shell-start")[0]["status"], "detached")
        self.assertEqual(target.read_text(), "Local edits")

    def test_auto_keeps_live_link_removal_guard(self):
        self.require_links()
        self.update_policy({'trigger': ['agent-start']})
        self.bootstrap()
        self.run_cli("apply")
        (self.repo / "skills/report/SKILL.md").unlink()
        self.commit(self.repo)
        result = self.run_cli("auto", "--trigger", "agent-start", code=1)
        self.assertEqual(result[0]["status"], "failed")
        self.assertTrue((self.destination / "report/SKILL.md").is_file())

    def test_invalid_policy_fails_bootstrap_before_clone_or_config_write(self):
        self.skills["report"]["update"] = {"policy": "missing"}
        self.save_catalog()
        with patch.object(Git, "run", side_effect=AssertionError("Unexpected Git command")):
            error = self.bootstrap(code=1)
        self.assertIn("unknown update policy", error)
        self.assertFalse(self.config.exists())
        self.assertFalse(self.checkouts.exists())

    def test_catalog_clones_two_independent_repositories_without_manifests(self):
        self.require_links()
        standalone = self.repository("standalone", ".")
        self.catalog_sources['standalone'] = {'type': 'git', 'repository': str(standalone)}
        self.skills['standalone'] = {'source': 'standalone'}
        self.save_catalog()
        before = self.catalog.read_bytes()
        self.bootstrap()
        self.assertFalse(self.destination.exists())
        self.assertEqual(len(self.run_cli("apply", "--dry-run")), 2)
        self.run_cli("apply")
        self.assertEqual((self.destination / "report").resolve(), self.checkouts / ".aem-repositories/report/skills/report")
        self.assertEqual((self.destination / "standalone").resolve(), self.checkouts / ".aem-repositories/standalone")
        for name in ("report", "standalone"):
            self.assertTrue((self.checkouts / ".aem-repositories" / name / ".git").is_dir())
            self.assertFalse((self.checkouts / ".aem-repositories" / name / "links.conf").exists())
        self.assertEqual(self.catalog.read_bytes(), before)
        self.assertEqual(self.git(self.repo, "status", "--porcelain"), "")

    def shared_auto_fixture(self, *, second_policy=None):
        second = self.repo / 'skills/second'
        second.mkdir()
        (second / 'SKILL.md').write_text('# Second\n', encoding='utf-8')
        self.commit(self.repo)
        self.skills = {name: {'subdir': 'skills/' + name, 'source': 'tools',
                             'install': {'mode': 'copy'}} for name in ('report', 'second')}
        if second_policy:
            self.skills['second']['update'] = second_policy
        self.catalog_sources = {'tools': {'type': 'git', 'repository': str(self.repo)}}
        self.save_catalog()
        self.update_policy({'trigger': ['agent-start'], 'action': 'check', 'min_interval': 0})
        self.bootstrap()
        self.run_cli('apply')
        self.publish_skill_change()

    def test_auto_shares_fetch_across_check_and_sync_but_not_events(self):
        self.shared_auto_fixture(second_policy={'action': 'sync'})
        original = Git.run
        fetches = []

        def record(git, path, *args, **kwargs):
            if args[0] == 'fetch':
                fetches.append(path)
            return original(git, path, *args, **kwargs)

        with patch.object(Git, 'run', record):
            result = self.run_cli('auto', '--trigger', 'agent-start')
            self.assertEqual(len(fetches), 1)
            self.assertEqual([item['status'] for item in result], ['checked', 'synced'])
            self.run_cli('auto', '--trigger', 'agent-start')
            self.assertEqual(len(fetches), 2)
        self.assertNotIn('Published change', (self.destination / 'report/SKILL.md').read_text())
        self.assertEqual((self.destination / 'second/SKILL.md').read_text(), '# Second\n')
        self.assertIn('Published change', (self.checkouts / '.aem-repositories/tools/skills/report/SKILL.md').read_text())

    def test_shared_fetch_keeps_modified_copy_and_other_skill_independent(self):
        self.shared_auto_fixture(second_policy={'action': 'sync'})
        self.update_policy({'trigger': ['agent-start'], 'action': 'sync', 'min_interval': 0})
        target = self.destination / 'report/SKILL.md'
        target.write_text('# Local edit\n')
        original = Git.run
        fetches = []

        def record(git, path, *args, **kwargs):
            if args[0] == 'fetch':
                fetches.append(path)
            return original(git, path, *args, **kwargs)

        with patch.object(Git, 'run', record):
            result = self.run_cli('auto', '--trigger', 'agent-start', code=1)
        self.assertEqual(len(fetches), 1)
        self.assertEqual([item['status'] for item in result], ['failed', 'synced'])
        self.assertEqual(target.read_text(), '# Local edit\n')
        self.assertEqual((self.destination / 'second/SKILL.md').read_text(), '# Second\n')

    def test_auto_keeps_distinct_fetch_timeout_budgets(self):
        self.shared_auto_fixture(second_policy={'timeout': 15})
        original = Git.run
        budgets = []

        def record(git, path, *args, **kwargs):
            if args[0] == 'fetch':
                budgets.append(git.timeout)
            return original(git, path, *args, **kwargs)

        with patch.object(Git, 'run', record):
            self.run_cli('auto', '--trigger', 'agent-start')
        self.assertEqual(budgets, [30, 15])

    def changing_shared_remote(self, *, rewrite=False):
        self.catalog_sources = {'tools': {'type': 'git', 'repository': str(self.repo)}}
        self.skills = {
            name: {'subdir': 'skills/report', 'source': 'tools', 'install': {'mode': 'copy'},
                   'update': {'timeout': timeout, 'action': action}}
            for name, timeout, action in (
                ('first', 30, 'sync' if rewrite else 'check'),
                ('second', 15, 'check'),
                ('third', 30, 'sync' if rewrite else 'check'))}
        self.save_catalog()
        self.update_policy({'trigger': ['agent-start'], 'min_interval': 0})
        self.bootstrap()
        self.run_cli('apply')
        original_head = self.git(self.repo, 'rev-parse', 'HEAD')
        if rewrite:
            self.publish_skill_change()
        original = Git.run
        fetches = []

        def change_before_second_fetch(git, path, *args, **kwargs):
            if args[0] == 'fetch':
                fetches.append(git.timeout)
                if len(fetches) == 2:
                    if rewrite:
                        self.git(self.repo, 'reset', '--hard', original_head)
                        (self.repo / 'skills/report/helper.py').write_text(
                            "print('new remote history')\n", encoding='utf-8')
                        self.commit(self.repo)
                    else:
                        self.publish_skill_change()
            return original(git, path, *args, **kwargs)

        with patch.object(Git, 'run', change_before_second_fetch):
            result = self.run_cli('auto', '--trigger', 'agent-start')
        self.assertEqual(fetches, [30, 15])
        return result

    def test_cached_check_compares_its_observation_after_another_timeout_fetches(self):
        result = self.changing_shared_remote()
        self.assertEqual([entry['status'] for entry in result], ['checked'] * 3)
        self.assertEqual([entry['remote_relation'] for entry in result],
                         ['equal-at-last-fetch', 'behind', 'equal-at-last-fetch'])
        sources = self.run_cli('status')['sources']
        observations = {entry['source']: entry['observed_revision'] for entry in sources}
        self.assertEqual(observations['first'], observations['third'])
        self.assertNotEqual(observations['second'], observations['third'])
        self.assertNotIn('Published change', (self.destination / 'third/SKILL.md').read_text())

    def test_cached_sync_uses_its_observation_after_another_timeout_fetches_rewritten_history(self):
        result = self.changing_shared_remote(rewrite=True)
        self.assertEqual([entry['status'] for entry in result], ['synced', 'checked', 'synced'])
        self.assertEqual(result[1]['remote_relation'], 'diverged')
        self.assertEqual(result[0]['revision'], result[2]['revision'])
        self.assertIn('Published change', (self.destination / 'third/SKILL.md').read_text())
        self.assertEqual((self.destination / 'third/helper.py').read_text(), "print('test')\n")

    def test_auto_shares_network_failure_and_records_each_skill_attempt(self):
        self.shared_auto_fixture()
        original = Git.run
        attempts = []

        def fail(git, path, *args, **kwargs):
            if args[0] == 'fetch':
                attempts.append(path)
                raise Error('Remote unavailable')
            return original(git, path, *args, **kwargs)

        with patch.object(Git, 'run', fail):
            result = self.run_cli('auto', '--trigger', 'agent-start', code=1)
        self.assertEqual(len(attempts), 1)
        self.assertEqual([item['status'] for item in result], ['failed', 'failed'])
        sources = self.run_cli('status')['sources']
        self.assertTrue(all(item['automation']['status'] == 'failed' for item in sources))

    def test_shared_repository_prepares_once_and_installs_two_skills(self):
        second = self.repo / "skills/second"
        second.mkdir()
        (second / "SKILL.md").write_text("# Second\n", encoding="utf-8")
        self.commit(self.repo)
        self.skills = {"report": {'subdir': 'skills/report', 'source': 'tools', 'install': {'mode': 'copy'}},
                       "second": {'subdir': 'skills/second', 'source': 'tools', 'install': {'mode': 'copy'}}}
        self.catalog_sources = {'tools': {'type': 'git', 'repository': str(self.repo)}}
        self.save_catalog()
        report = self.bootstrap()
        checkout = self.checkouts / ".aem-repositories/tools"
        self.assertEqual([entry["checkout"] for entry in report["skills"]], [str(checkout)] * 2)
        self.assertTrue((checkout / ".git").is_dir())
        self.assertFalse((self.checkouts / ".aem-repositories/report").exists())
        self.run_cli("apply")
        self.assertTrue((self.destination / "report/SKILL.md").is_file())
        self.assertTrue((self.destination / "second/SKILL.md").is_file())
        (second / "SKILL.md").write_text("# Updated\n", encoding="utf-8")
        self.commit(self.repo)
        self.assertEqual(len(self.run_cli("update")), 2)
        self.run_cli("apply")
        self.assertEqual((self.destination / "second/SKILL.md").read_text(), "# Updated\n")

    def test_shared_repository_rejects_missing_sibling_before_publish(self):
        self.skills = {"report": {'subdir': 'skills/report', 'source': 'tools'},
                       "missing": {'subdir': 'skills/missing', 'source': 'tools'}}
        self.catalog_sources = {'tools': {'type': 'git', 'repository': str(self.repo)}}
        self.save_catalog()
        result = self.bootstrap(code=1)
        self.assertEqual([entry["status"] for entry in result["skills"]], ["failed", "failed"])
        self.assertFalse((self.checkouts / ".aem-repositories/tools").exists())

    def test_named_repository_reference_is_validated_before_clone(self):
        self.skills = {"report": {'subdir': 'skills/report', 'source': 'unknown'}}
        self.save_catalog()
        with patch.object(Git, "run", side_effect=AssertionError("Unexpected Git command")):
            self.assertIn("source must name a declared source", self.bootstrap(code=1))
        self.assertFalse(self.checkouts.exists())

    def test_shared_repository_selective_update_retains_skill_installation_boundary(self):
        second = self.repo / "skills/second"
        second.mkdir()
        (second / "SKILL.md").write_text("# Second\n", encoding="utf-8")
        self.commit(self.repo)
        self.skills = {"report": {'subdir': 'skills/report', 'source': 'tools', 'install': {'mode': 'copy'}},
                       "second": {'subdir': 'skills/second', 'source': 'tools', 'install': {'mode': 'copy'}}}
        self.catalog_sources = {'tools': {'type': 'git', 'repository': str(self.repo)}}
        self.save_catalog()
        self.bootstrap()
        self.run_cli("apply")
        before = (self.destination / "second/SKILL.md").read_text()
        (second / "SKILL.md").write_text("# Updated\n", encoding="utf-8")
        self.commit(self.repo)
        self.assertEqual(self.run_cli("update", "report")[0]["source"], "report")
        self.run_cli("apply", "--item", "report")
        self.assertEqual((self.destination / "second/SKILL.md").read_text(), before)
        self.run_cli("apply", "--item", "second")
        self.assertEqual((self.destination / "second/SKILL.md").read_text(), "# Updated\n")

    def test_shared_update_guards_other_skills_live_link(self):
        self.require_links()
        second = self.repo / "skills/second"
        second.mkdir()
        (second / "SKILL.md").write_text("# Second\n", encoding="utf-8")
        self.commit(self.repo)
        self.skills = {"report": {'subdir': 'skills/report', 'source': 'tools'},
                       "second": {'subdir': 'skills/second', 'source': 'tools'}}
        self.catalog_sources = {'tools': {'type': 'git', 'repository': str(self.repo)}}
        self.save_catalog()
        self.bootstrap()
        self.run_cli("apply")
        (second / "SKILL.md").unlink()
        self.commit(self.repo)
        self.run_cli("update", "report", code=1)
        self.assertTrue((self.destination / "second/SKILL.md").is_file())

    def test_shared_link_guard_covers_sibling_record_without_link_capability(self):
        second = self.repo / "skills/second"
        second.mkdir()
        (second / "SKILL.md").write_text("# Second\n", encoding="utf-8")
        self.commit(self.repo)
        self.skills = {"report": {'subdir': 'skills/report', 'source': 'tools'},
                       "second": {'subdir': 'skills/second', 'source': 'tools'}}
        self.catalog_sources = {'tools': {'type': 'git', 'repository': str(self.repo)}}
        self.save_catalog()
        self.bootstrap()
        config = Config(self.config)
        source = config.sources["report"]
        record = {"source_name": "second", "relative": "skills/second",
                  "source": str(source.path / "skills/second"), "mode": "link",
                  "directory": True, "kind": "skill"}
        (second / "SKILL.md").unlink()
        self.commit(self.repo)
        self.git(source.path, "fetch", "origin")
        revision = self.git(source.path, "rev-parse", "FETCH_HEAD")
        with self.assertRaises(Error):
            Git().guard_links(source, revision, {"second": record})

    def test_after_bootstrap_local_use_does_not_fetch(self):
        self.copy_mode()
        self.bootstrap()
        original = Git.run

        def offline(git, path, *args, **kwargs):
            self.assertNotIn(args[0], ("fetch", "pull", "clone", "push", "merge"))
            return original(git, path, *args, **kwargs)

        with patch.object(Git, "run", offline):
            self.run_cli("apply")
            self.run_cli("status")
            self.run_cli("detach", "report")

    def test_same_local_catalog_bootstraps_another_device_without_per_repo_bindings(self):
        self.copy_mode()
        self.bootstrap()
        self.run_cli("apply")
        second_config = self.root / "other-machine.toml"
        second_target = self.root / "other-skills"
        self.run_cli("bootstrap", "--catalog", self.catalog, "--root", f"skills={second_target}", config=second_config)
        self.run_cli("apply", config=second_config)
        self.assertEqual((self.destination / "report/SKILL.md").read_bytes(), (second_target / "report/SKILL.md").read_bytes())
        self.assertNotIn("repositories", tomlkit.parse(second_config.read_text()))

    def test_update_delivers_git_change_and_apply_refreshes_copy(self):
        self.copy_mode()
        self.bootstrap()
        self.run_cli("apply")
        descriptor = self.repo / "skills/report/SKILL.md"
        descriptor.write_text(descriptor.read_text() + "Published change\n", encoding="utf-8")
        self.commit(self.repo)
        self.run_cli("update")
        self.assertNotIn("Published change", (self.destination / "report/SKILL.md").read_text())
        self.run_cli("apply")
        self.assertIn("Published change", (self.destination / "report/SKILL.md").read_text())

    def test_failed_update_preserves_installed_skill(self):
        self.copy_mode()
        self.bootstrap()
        self.run_cli("apply")
        self.repo.rename(self.root / "unavailable-research-tools")
        self.run_cli("sync", code=1)
        self.assertTrue((self.destination / "report/SKILL.md").is_file())
        self.run_cli("apply")

    def test_root_skill_copy_excludes_git_metadata(self):
        standalone = self.repository("standalone", ".")
        self.catalog_sources = {'standalone': {'type': 'git', 'repository': str(standalone)}}
        self.skills = {'standalone': {'source': 'standalone', 'install': {'mode': 'copy'}}}
        self.save_catalog()
        self.bootstrap()
        self.run_cli("apply")
        target = self.destination / "standalone"
        self.assertFalse((target / ".git").exists())
        self.assertTrue((target / "SKILL.md").is_file())
        self.run_cli("detach", "standalone")
        self.assertTrue((self.checkouts / ".aem-repositories/standalone/.git").is_dir())

    def test_root_skill_link_detach_materializes_only_skill_contents(self):
        self.require_links()
        standalone = self.repository("standalone", ".")
        self.catalog_sources = {'standalone': {'type': 'git', 'repository': str(standalone)}}
        self.skills = {'standalone': {'source': 'standalone'}}
        self.save_catalog()
        self.bootstrap()
        self.run_cli("apply")
        target = self.destination / "standalone"
        before = fingerprint(self.checkouts / ".aem-repositories/standalone", exclude_git=True)
        self.run_cli("detach", "standalone")
        self.checkouts.rename(self.root / "offline-checkouts")
        self.assertFalse(target.is_symlink())
        self.assertFalse((target / ".git").exists())
        self.assertEqual(fingerprint(target), before)
        self.assertEqual(self.run_cli("apply"), [])

    def test_default_branch_is_discovered_and_retained(self):
        self.copy_mode()
        self.git(self.repo, "branch", "-m", "stable")
        self.bootstrap()
        self.run_cli("apply")
        self.assertEqual(self.run_cli("status")["sources"][0]["branch"], "stable")
        self.git(self.checkouts / ".aem-repositories/report", "checkout", "-b", "other")
        self.run_cli("update", code=1)

    def test_missing_skill_descriptor_fails_before_publishing_checkout(self):
        self.git(self.repo, "rm", "skills/report/SKILL.md")
        self.commit(self.repo)
        report = self.bootstrap(code=1)
        self.assertEqual(report["skills"][0]["status"], "failed")
        self.assertFalse((self.checkouts / ".aem-repositories/report").exists())
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.checkouts.glob(".aem-clone-*")))

    def test_unsupported_source_type_is_rejected_before_network(self):
        self.catalog_sources['report']['type'] = "syncthing"
        self.save_catalog()
        self.assertIn("type must be git or external", self.bootstrap(code=1))
        self.assertFalse(self.config.exists())
        self.assertFalse(self.checkouts.exists())

    def test_clone_failure_can_be_retried_from_saved_catalog_binding(self):
        self.catalog_sources['report']['repository'] = str(self.root / "missing.git")
        self.save_catalog()
        self.bootstrap(code=1)
        self.assertTrue(self.config.exists())
        self.assertFalse((self.checkouts / ".aem-repositories/report").exists())
        self.catalog_sources['report']['repository'] = str(self.repo)
        self.save_catalog()
        self.assertEqual(self.run_cli("bootstrap")["skills"][0]["status"], "cloned")

    def test_inventory_cannot_live_in_managed_checkout_storage(self):
        self.run_cli("bootstrap", "--catalog", self.catalog, "--checkout-root", self.catalog.parent,
                     "--root", f"skills={self.destination}", code=1)
        self.assertFalse(self.config.exists())

    def test_missing_inventory_does_not_prevent_preserving_detach(self):
        self.require_links()
        self.bootstrap()
        self.run_cli("apply")
        self.catalog.unlink()
        report = self.run_cli("status")
        self.assertIn("catalog_error", report)
        self.assertEqual(report["items"][0]["installation"], "linked")
        self.run_cli("detach", "report")
        self.assertFalse((self.destination / "report").is_symlink())

    def test_removing_catalog_entry_keeps_target_until_detach(self):
        self.require_links()
        self.bootstrap()
        self.run_cli("apply")
        self.skills = {}
        self.save_catalog()
        self.assertEqual(self.run_cli("apply"), [])
        self.assertTrue((self.destination / "report").is_symlink())
        self.assertEqual(self.run_cli("status")["items"][0]["status"], "orphaned-or-source-unavailable")
        self.run_cli("detach", "report")

    def test_traversal_subdirectory_is_rejected(self):
        for subdir in (None, "../escape", "/absolute", "skills/../report"):
            with self.subTest(subdir=subdir):
                entry = dict(self.skills["report"], subdir=subdir)
                if subdir is None:
                    entry["subdir"] = 123
                self.catalog.write_text(tomlkit.dumps({'version': 2, 'sources': self.catalog_sources, 'skills': {'report': entry}}), encoding="utf-8")
                self.bootstrap(code=1)
                self.assertFalse(self.checkouts.exists())

    def test_update_guards_skill_descriptor_removal_even_if_folder_remains(self):
        self.require_links()
        self.bootstrap()
        self.run_cli("apply")
        (self.repo / "skills/report/SKILL.md").unlink()
        self.commit(self.repo)
        self.run_cli("update", code=1)
        self.assertTrue((self.destination / "report/SKILL.md").is_file())

    def test_changed_catalog_repository_does_not_reuse_an_unrelated_checkout(self):
        self.copy_mode()
        self.bootstrap()
        self.run_cli("apply")
        replacement = self.repository("replacement", "skills/report")
        self.catalog_sources['report']['repository'] = str(replacement)
        self.save_catalog()
        self.run_cli("apply", code=1)
        self.run_cli("bootstrap", code=1)
        self.assertEqual(self.git(self.checkouts / ".aem-repositories/report", "remote", "get-url", "origin"), str(self.repo))

    def test_root_git_administration_changes_are_not_skill_content_changes(self):
        self.require_links()
        standalone = self.repository("standalone", ".")
        self.catalog_sources = {'standalone': {'type': 'git', 'repository': str(standalone)}}
        self.skills = {'standalone': {'source': 'standalone'}}
        self.save_catalog()
        self.bootstrap()
        self.run_cli("apply")
        self.git(self.checkouts / ".aem-repositories/standalone", "config", "aem.test", "metadata-only")
        item = self.run_cli("status")["items"][0]
        self.assertNotIn("note", item)
        self.assertEqual(item["status"], "current")

    def test_machine_can_explicitly_override_link_with_copy(self):
        self.bootstrap()
        config = tomlkit.parse(self.config.read_text())
        config["modes"] = {"report": "copy"}
        self.config.write_text(tomlkit.dumps(config), encoding="utf-8")
        self.run_cli("apply")
        self.assertFalse((self.destination / "report").is_symlink())
        self.assertEqual(self.run_cli("status")["items"][0]["mode"], "copy")

    def test_new_repository_does_not_inherit_the_previous_default_branch(self):
        self.copy_mode()
        self.git(self.repo, "branch", "-m", "old-default")
        self.bootstrap()
        self.run_cli("apply")
        self.run_cli("detach", "report")
        (self.checkouts / ".aem-repositories/report").rename(self.root / "saved-old-checkout")
        replacement = self.repository("replacement", "skills/report")
        self.catalog_sources['report']['repository'] = str(replacement)
        self.save_catalog()
        self.run_cli("bootstrap")
        self.assertEqual(self.git(self.checkouts / ".aem-repositories/report", "symbolic-ref", "--short", "HEAD"), "main")

    def test_root_skill_link_receives_update_without_an_apply_step(self):
        self.require_links()
        standalone = self.repository("standalone", ".")
        self.catalog_sources = {'standalone': {'type': 'git', 'repository': str(standalone)}}
        self.skills = {'standalone': {'source': 'standalone'}}
        self.save_catalog()
        self.bootstrap()
        self.run_cli("apply")
        (standalone / "helper.py").write_text("print('new revision')\n", encoding="utf-8")
        self.commit(standalone)
        self.run_cli("update")
        self.assertIn("new revision", (self.destination / "standalone/helper.py").read_text())

    def test_git_symlinks_are_rejected_even_when_checked_out_as_text(self):
        self.require_links()
        (self.repo / "skills/report/helper-link").symlink_to("helper.py")
        self.commit(self.repo)
        with patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.symlinks", "GIT_CONFIG_VALUE_0": "false"}):
            report = self.bootstrap(code=1)
        self.assertIn("Git symlink", report["skills"][0]["error"])
        self.assertFalse((self.checkouts / ".aem-repositories/report").exists())


if __name__ == "__main__":
    unittest.main()

"""Presentation contracts and callback compatibility at the CLI boundary."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import tomlkit

from click.testing import CliRunner

from agent_env_man.cli import main, cli
from agent_env_man.output import format_report, human_report
from agent_env_man.manager import Manager
from agent_env_man.model import Config
from agent_env_man.storage import State
import test_skill_catalog


class OutputTests(unittest.TestCase):
    def test_nested_reports_preserve_paths_failures_and_notices(self):
        report = {"items": [{"item": "한글-skill", "status": "conflict",
                             "target": "/path with spaces/SKILL.md",
                             "error": "first line\nsecond line"}],
                  "pending": None, "failed": True, "outcomes": [],
                  "notice": "Review /hooks"}
        text = format_report(report)
        self.assertIn("items:\n  - item: 한글-skill\n    status: conflict", text)
        self.assertIn("target: /path with spaces/SKILL.md", text)
        self.assertIn("error: first line\n           second line", text)
        self.assertIn("pending: none", text)
        self.assertIn("failed: yes", text)
        self.assertIn("outcomes: none", text)
        self.assertIn("notice: Review /hooks", text)

    def test_empty_and_scalar_lists(self):
        self.assertEqual(format_report([]), "none")
        self.assertEqual(format_report({}), "none")
        self.assertEqual(format_report({"names": ["one", "two"]}), "names:\n  - one\n  - two")

    def test_json_is_a_global_option(self):
        with tempfile.TemporaryDirectory() as directory:
            config = str(Path(directory) / "machine.toml")
            result = CliRunner().invoke(cli, ["--config", config, "--json", "self", "status"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(json.loads(result.stdout)["mode"], "off")
            for args in (["status", "--json"], ["catalog", "--json", "status"],
                         ["catalog", "status", "--json"]):
                with self.subTest(args=args):
                    result = CliRunner().invoke(cli, ["--config", config, *args])
                    self.assertEqual(result.exit_code, 2)
                    self.assertIn("No such option", result.output)
                    self.assertIn("--json", result.output)

    def test_default_text_and_explicit_json_share_report(self):
        with tempfile.TemporaryDirectory() as directory:
            config = str(Path(directory) / "machine.toml")
            reports = []
            for flags in ([], ["--json"]):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(["--config", config, *flags, "self", "status"])
                self.assertEqual(code, 0)
                reports.append(output.getvalue())
            report = json.loads(reports[1])
            self.assertIn(f"version: {report['version']}", reports[0])
            self.assertIn("mode: off", reports[0])
            self.assertNotIn("last attempt: none", reports[0])
            self.assertNotIn(report['repository'], reports[0])
            detailed = CliRunner().invoke(cli, ["--config", config, "--verbose", "self", "status"])
            self.assertEqual(detailed.exit_code, 0, detailed.output)
            self.assertIn(report['repository'], detailed.output)

    def test_verbose_is_global_and_incompatible_with_json_before_runtime(self):
        with patch('agent_env_man.cli_runtime.Runtime.run', side_effect=AssertionError('runtime reached')):
            for args in (["--json", "--verbose", "status"], ["status", "--verbose"]):
                result = CliRunner().invoke(cli, args)
                self.assertEqual(result.exit_code, 2, result.output)

    def test_short_output_preserves_nested_failures_recovery_and_comparisons(self):
        report = {"items": [{"item": "한글", "kind": "instruction", "status": "conflict",
                              "target": "/path with spaces/AGENTS.md", "error": "first\nsecond",
                              "comparisons": [{"argv": ["diff", "/old path", "/new path"]}]}],
                  "pending": {"target": "/recover here", "operation": "replace"},
                  "automation": {"last_attempt": {"status": "failed", "error": "past failure"}},
                  "notice": "Review /hooks"}
        text = human_report(report, command="status")
        for expected in ("Instructions:", "conflict", "/path with spaces/AGENTS.md", "first", "second",
                         "/old path", "/new path", "aem recover", "/recover here", "past failure", "Review /hooks"):
            self.assertIn(expected, text)
        self.assertNotIn("all healthy", text.lower())

    def test_empty_preview_and_time_units(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "machine.toml"
            config.write_text('version = 1\n', encoding='utf-8')
            runner = CliRunner()
            result = runner.invoke(cli, ["--config", str(config), "apply", "--dry-run"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("preview: no items to install", result.output)
            result = runner.invoke(cli, ["--config", str(config), "status"])
            self.assertIn("3600 seconds", result.output)
            self.assertIn("30 seconds", result.output)
            self.assertNotIn("none", result.output)

    def test_startup_retains_json_without_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--config", str(Path(directory) / "machine.toml"),
                             "startup", "--trigger", "shell-start"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue()), {})


class MixedOutputTests(unittest.TestCase):
    setUp = test_skill_catalog.SkillCatalog.setUp
    repository = test_skill_catalog.SkillCatalog.repository
    git = test_skill_catalog.SkillCatalog.git
    commit = test_skill_catalog.SkillCatalog.commit
    save_catalog = test_skill_catalog.SkillCatalog.save_catalog

    def configure(self, external=False):
        self.config.write_text(tomlkit.dumps({'version': 1, 'agents': {'codex': {
            'root': str(self.root / 'agent'), 'skills': str(self.destination)}}}), encoding='utf-8')
        (self.repo / "rules").mkdir()
        (self.repo / "rules/start.md").write_text("Guidance", encoding="utf-8")
        (self.repo / "data").mkdir()
        (self.repo / "data/file.txt").write_text("Data", encoding="utf-8")
        (self.repo / "editor.toml").write_text('color = "blue"\n', encoding="utf-8")
        (self.repo / "observer.py").write_text('raise AssertionError("Do not execute")\n', encoding="utf-8")
        self.commit(self.repo)
        source = "external" if external else "shared"
        document = {"version": 2,
                    "sources": {"shared": {"type": "git", "repository": str(self.repo)}},
                    "skills": {"report": {"source": "shared", "subdir": "skills/report", "install": {"mode": "copy"}}},
                    "instructions": {"personal": {"source": source, "subdir": "rules", "entry": "start.md"}},
                    "directories": {"data": {"source": source, "subdir": "data", "install": {"mode": "copy"}}},
                    "settings": {"editor": {"source": source, "path": "editor.toml", "format": "toml"}},
                    "hooks": {"observer": {"source": source, "agents": {"codex": {
                        "event": "SessionEnd", "runtime": "python", "script": "observer.py"}}}}}
        if external:
            document["sources"]["external"] = {"type": "external"}
        self.catalog.write_text(tomlkit.dumps(document), encoding="utf-8")
        args = ["bootstrap", str(self.catalog), "--checkout-root", str(self.checkouts),
                "--root", f"skills={self.destination}", "--root", f"home={self.root / 'home'}",
                "--root", f"agent={self.root / 'agent'}", "--runtime", f"python={sys.executable}",
                "--setting-target", f"editor={self.root / 'app/editor.toml'}"]
        if external:
            args.extend(["--external", f"external={self.repo}"])
        return self.call(*args, flags=["--json"])

    def call(self, *args, flags=(), code=0):
        result = CliRunner().invoke(cli, ["--config", str(self.config), *flags, *args])
        self.assertEqual(result.exit_code, code, result.output + repr(result.exception))
        return json.loads(result.output) if "--json" in flags else result.output

    def check_preparation(self, first):
        self.assertEqual({row['kind'] for row in first['items']},
                         {'skill', 'instruction', 'directory', 'setting', 'personal-hook'})
        # Preparation and staging are distinct results for the same setting.
        self.assertEqual(sum(row['name'] == 'editor' for row in first['items']), 2)
        config = Config(self.config)
        state = State(config.state_dir)
        before, failed = Manager(config, state).prepare_skills()
        self.assertFalse(failed)
        report = self.call("bootstrap", flags=["--json"])
        stripped = [{key: value for key, value in row.items() if key not in ('kind', 'compatibility_note')}
                    for row in report['skills']]
        self.assertEqual(stripped, before)
        for row in report['skills']:
            if row.get('kind'):
                self.assertIn('Use items instead', row['compatibility_note'])
        text = self.call("bootstrap")
        for heading in ("Instructions:", "Skills:", "Directories:", "Settings:", "Hooks:"):
            self.assertIn(heading, text)
        self.assertNotIn('compatibility', text)
        self.assertNotIn(str(self.checkouts), text)
        detailed = self.call("bootstrap", flags=["--verbose"])
        self.assertIn(str(self.checkouts), detailed)
        self.assertNotIn('compatibility', detailed)
        self.assertNotIn('skills:', detailed)
        self.assertTrue((Path(str(self.config) + '.stages') / 'editor/config.toml').is_file())

    def test_git_types_legacy_compatibility_and_settings_stage(self):
        self.check_preparation(self.configure())

    def test_external_types_legacy_compatibility_and_settings_stage(self):
        self.check_preparation(self.configure(external=True))

    def test_failed_git_consumers_keep_types_and_error_details(self):
        self.configure()
        checkout = self.checkouts / '.aem-repositories/shared'
        (checkout / 'untracked.txt').write_text('Local edit', encoding='utf-8')
        report = self.call('bootstrap', flags=['--json'], code=1)
        self.assertEqual({row['kind'] for row in report['items']},
                         {'skill', 'instruction', 'directory', 'setting', 'personal-hook'})
        self.assertTrue(all(row['status'] == 'failed' for row in report['items']))
        text = self.call('bootstrap', code=1)
        self.assertIn('(failed)', text)
        self.assertIn('error:', text)
        self.assertIn(report['items'][0]['error'], text)
        self.assertIn('retry aem bootstrap', text)
        self.assertNotIn('next: apply', text)

    def test_status_inspection_and_saved_instruction_types(self):
        self.configure()
        text = self.call('status')
        self.assertIn('Instructions:', text)
        self.assertIn('Settings:', text)
        self.assertLess(len(text), len(self.call('status', flags=['--verbose'])))
        # A saved-only lookup must not load or repair an unavailable catalog.
        from agent_env_man.reports import describe_report
        from agent_env_man.model import MachineFile
        state = State(Path(str(self.config) + '.state'))
        state.data['items']['personal:entry'] = {'kind': 'instruction-entry'}
        state.data['items']['personal:hook'] = {'kind': 'instruction-hook'}
        self.catalog.unlink()
        report = describe_report([{'item': key, 'status': 'recorded'} for key in ('personal:entry', 'personal:hook')],
                                 MachineFile(self.config), state)
        self.assertTrue(all(row['kind'] == 'instruction' for row in report))

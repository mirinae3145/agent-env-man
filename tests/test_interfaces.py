"""Public schema boundaries and removed interfaces fail without destructive writes."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tomlkit

from agent_env_man.cli import main
from agent_env_man.git_source import Git
from agent_env_man.model import Config, Error
from agent_env_man.storage import State


class Interfaces(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aem-interface-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.machine = self.root / "machine.toml"
        self.machine.write_text("version = 1\n", encoding="utf-8")

    def test_removed_commands_and_flags_are_usage_errors(self):
        for arguments in (("codex-hook", "personal"), ("sync", "--min-interval", "600"),
                          *(("bootstrap", "personal", flag, "value") for flag in
                            ("--path", "--git", "--branch", "--manifest")),
                          ("bootstrap", "--attach")):
            with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--config", str(self.machine), *arguments]), 2)
        self.assertFalse(Path(str(self.machine) + ".state").exists())
        self.assertEqual(self.machine.read_text(), "version = 1\n")

    def test_machine_unknown_fields_and_invalid_tables_are_rejected(self):
        invalid = ({"sources": {}}, {"checkout_rooot": str(self.root)}, {"roots": []},
                   {"external_paths": []}, {"external_paths": {"docs": "relative"}},
                   {"setup": {"unknown": True}}, {"setup": {"shells": {"fish": "/tmp/profile"}}},
                   {"setup": {"shells": {"bash": "relative"}}},
                   {"setup": {"executable": 1}}, {"setup": {"executable": "relative"}},
                   {"agents": {"codex": {"unknown": "/tmp"}}}, {"modes": {"report": "codex-merge"}})
        for extra in invalid:
            with self.subTest(extra=extra), self.assertRaises(Error):
                Config(self.machine, document={"version": 1, **extra})

    def test_schema_versions_require_integers(self):
        for version in (True, 1.0, "1", 2):
            with self.subTest(version=version), self.assertRaises(Error):
                Config(self.machine, document={"version": version})
        for version in (True, 2.0, "2", 1):
            catalog = self.root / "catalog.toml"
            catalog.write_text(tomlkit.dumps({"version": version}), encoding="utf-8")
            config = Config(self.machine, document={"version": 1, "catalog": str(catalog)})
            with self.subTest(catalog_version=version), self.assertRaises(Error):
                config.catalog()

    def test_old_state_remains_rejected_by_installation_commands(self):
        state_dir = Path(str(self.machine) + ".state")
        state_dir.mkdir()
        target = self.root / "preserved.txt"
        target.write_text("user contents", encoding="utf-8")
        data = {"version": 1, "items": {"personal:entry": {"target": str(target), "mode": "entry"}},
                "sources": {}, "pending": {"target": str(target)}}
        path = state_dir / "state.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        before = path.read_bytes()
        for args, code in ((["apply"], 1), (["bootstrap"], 1), (["setup", "--dry-run"], 1),
                           (["status", "--refresh"], 1), (["update"], 1), (["sync"], 1),
                           (["auto", "--trigger", "shell-start"], 1),
                           (["startup", "--trigger", "agent-start"], 0)):
            with self.subTest(args=args), redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(main(["--config", str(self.machine), *args]), code)
                self.assertIn("Unsupported state version", output.getvalue() + errors.getvalue())
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(target.read_text(), "user contents")

    def test_obsolete_modes_are_not_accepted_in_current_state(self):
        directory = self.root / "state"
        directory.mkdir()
        for mode in ("entry", "codex-merge", "codex-hook"):
            (directory / "state.json").write_text(json.dumps({"version": 2, "items": {"item": {"mode": mode}}, "sources": {}, "pending": None}), encoding="utf-8")
            with self.subTest(mode=mode), self.assertRaisesRegex(Error, "Unsupported installation mode"):
                State(directory)

    def test_documented_catalog_examples_validate_offline(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        for path in examples.glob("*.toml"):
            if "machine" in path.name:
                continue
            document = tomlkit.parse(path.read_text(encoding="utf-8"))
            bindings = {name: str(self.root / "externals" / name) for name, value in document.get("sources", {}).items() if value["type"] == "external"}
            machine = {"version": 1, "catalog": str(path), "external_paths": bindings,
                       "roots": {"agent": str(self.root / "agent"), "skills": str(self.root / "skills")}}
            for directory in document.get("directories", {}).values():
                root = directory.get("install", {}).get("root", "home")
                machine["roots"].setdefault(root, str(self.root / root))
            machine['runtimes'] = {binding['runtime']: sys.executable
                                   for hook in document.get('hooks', {}).values()
                                   for binding in hook['agents'].values()}
            if document.get("documents"):
                machine["agents"] = {name: {"root": str(self.root / name), "skills": str(self.root / name / "skills")}
                                     for name in ("codex", "claude")}
            with self.subTest(path=path.name), patch.object(Git, "run", side_effect=AssertionError("Unexpected Git")):
                config = Config(self.machine, document=machine)
                config.catalog()
                for source in config.sources.values():
                    config.declarations(source)

    def test_removed_catalog_fields_fail_before_bootstrap_writes(self):
        catalog = self.root / "catalog.toml"
        catalog.write_text('version = 1\n[sources.personal]\npath = "/tmp/source"\n', encoding="utf-8")
        before = self.machine.read_bytes()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                patch.object(Git, "run", side_effect=AssertionError("Unexpected Git")):
            self.assertEqual(main(["--config", str(self.machine), "bootstrap", str(catalog)]), 1)
        self.assertEqual(self.machine.read_bytes(), before)
        self.assertFalse(Path(str(self.machine) + ".checkouts").exists())

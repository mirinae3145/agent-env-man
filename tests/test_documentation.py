"""Local documentation lookup works independently of configured installations."""

import importlib.util
import json
import os
from contextlib import chdir
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from agent_env_man.cli import cli
from agent_env_man.commands import documentation
from setuptools import Distribution

# The build hook ships in the sdist, not as an installed runtime module.
_spec = importlib.util.spec_from_file_location("_build", Path(__file__).parents[1] / "src/_build.py")
_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_build)


class Documentation(unittest.TestCase):
    def test_lookup_without_configuration_or_working_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config = root / "invalid.toml"
            config.write_text("not valid TOML [", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(root)
                # Any accidental entry into ordinary execution would read
                # configuration and take locks, which docs must bypass.
                with patch("agent_env_man.cli_runtime.Runtime.run", side_effect=AssertionError("operation executed")):
                    for flags in ([], ["--json"]):
                        result = CliRunner().invoke(cli, ["--config", str(config), *flags, "docs"])
                        self.assertEqual(result.exit_code, 0, result.output)
                        entry = (json.loads(result.output)["entry"] if flags else result.output.strip())
                        self.assertTrue(Path(entry).is_absolute())
                        self.assertTrue(Path(entry).is_file())
                        self.assertTrue((Path(entry).parent / "docs" / "commands.md").is_file())
            finally:
                os.chdir(previous)
            self.assertEqual(list(root.iterdir()), [config])

    def test_installed_resources_take_precedence_and_missing_resources_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory).resolve() / "site-packages" / "agent_env_man"
            module = package / "commands" / "documentation.py"
            module.parent.mkdir(parents=True)
            root = package / "_documentation"
            root.mkdir()
            entry = root / "README.md"
            entry.write_text("local docs", encoding="utf-8")
            with patch.object(documentation, "__file__", str(module)):
                result = CliRunner().invoke(cli, ["--json", "docs"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(json.loads(result.output), {"root": str(root), "entry": str(entry)})
                entry.unlink()
                result = CliRunner().invoke(cli, ["docs"])
                self.assertEqual(result.exit_code, 1)
                self.assertIn("documentation", result.output)


class DocumentationBuild(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="aem-build-docs-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.sources = {
            "README.md": b"[Guide](docs/guide.md)\n",
            "LICENSE.txt": b"license\n",
            "docs/guide.md": b"guide\n",
            "examples/catalog.toml": b"version = 2\n",
        }
        for relative, content in self.sources.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        patcher = patch.object(_build, "__file__", str(self.root / "src/_build.py"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.command = _build.BuildPy(Distribution({"packages": [], "py_modules": []}))
        self.command.build_lib = str(self.root / "build")
        self.command.ensure_finalized()
        self.destination = Path(self.command.build_lib) / "agent_env_man/_documentation"

    def test_normal_build_copies_bytes_and_removes_obsolete_resources(self):
        # Exercise both a fresh build and a rebuild into the same output tree.
        with chdir(self.root):
            self.command.run()
        for relative, content in self.sources.items():
            self.assertEqual((self.destination / relative).read_bytes(), content)
        (self.destination / "obsolete.md").write_text("old", encoding="utf-8")
        unrelated = Path(self.command.build_lib) / "unrelated.txt"
        unrelated.write_bytes(b"keep")
        with chdir(self.root):
            self.command.run()
        self.assertFalse((self.destination / "obsolete.md").exists())
        self.assertEqual(unrelated.read_bytes(), b"keep")
        for relative, content in self.sources.items():
            self.assertEqual((self.destination / relative).read_bytes(), content)
            self.assertEqual((self.root / relative).read_bytes(), content)

    def test_editable_build_preserves_existing_documentation_tree(self):
        self.destination.mkdir(parents=True)
        marker = self.destination / "local.md"
        marker.write_bytes(b"preserve")
        self.command.editable_mode = True
        with chdir(self.root):
            self.command.run()
        self.assertEqual(list(self.destination.iterdir()), [marker])
        self.assertEqual(marker.read_bytes(), b"preserve")

    def test_dry_run_preserves_existing_resources_without_creating_new_ones(self):
        self.destination.mkdir(parents=True)
        marker = self.destination / "local.md"
        marker.write_bytes(b"preserve")
        self.command.dry_run = True
        with chdir(self.root):
            self.command.run()
        self.assertEqual(list(self.destination.iterdir()), [marker])
        self.assertEqual(marker.read_bytes(), b"preserve")
        self.assertFalse((self.destination / "README.md").exists())

    def test_build_metadata_tracks_source_and_destination_resources(self):
        mapping = {str(self.destination / relative): str(Path(relative)) for relative in self.sources}
        self.assertEqual(self.command.get_output_mapping(), mapping)
        self.assertEqual(set(self.command.get_source_files()), {str(Path(relative)) for relative in self.sources})
        self.assertEqual(set(self.command.get_outputs(include_bytecode=False)), set(mapping))

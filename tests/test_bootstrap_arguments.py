"""Bootstrap persists device bindings without a hand-written machine file."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

import tomlkit

from agent_env_man.cli import main
from agent_env_man.model import default_config
from test_instructions import InstructionFixture


class BootstrapArguments(InstructionFixture):
    def setUp(self):
        super().setUp()
        self.home = self.root / 'home'
        self.agent = self.home / 'custom-codex'
        self.external = self.root / 'external documents'
        (self.external / 'development').mkdir(parents=True)
        (self.external / 'AGENTS.md').write_text('Read development/rules.md\n', encoding='utf-8')
        (self.external / 'development/rules.md').write_text('Guidance\n', encoding='utf-8')
        catalog = {'version': 2, 'sources': {**self.catalog_sources, 'personal': {'type': 'external'}}, 'skills': self.skills, 'instructions': {'personal': {'entry': 'AGENTS.md', 'source': 'personal', 'install': {'entry': {'root': 'agent', 'destination': 'AGENTS.md'}}}}}
        self.catalog.write_text(tomlkit.dumps(catalog), encoding='utf-8')
        for context in (patch.object(Path, 'home', return_value=self.home),
                        patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.home / 'config'),
                            'LOCALAPPDATA': str(self.home / 'config'), 'CODEX_HOME': str(self.agent)})):
            context.start()
            self.addCleanup(context.stop)
        self.config = default_config()

    def cli(self, *args, code=0):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = main(["--json", *map(str, args)])
        self.assertEqual(result, code, output.getvalue() + errors.getvalue())
        return json.loads(output.getvalue()) if output.getvalue() else errors.getvalue()

    def boot(self, *args, code=0):
        return self.cli('bootstrap', self.catalog, '--external', f'personal={self.external}', *args, code=code)

    def test_combined_install_and_saved_bindings_without_config_argument(self):
        self.require_links()
        self.boot()
        self.assertFalse((self.agent / 'AGENTS.md').exists())
        self.assertFalse((self.agent / 'hooks.json').exists())
        saved = tomlkit.parse(self.config.read_text(encoding='utf-8'))
        self.assertEqual(saved['external_paths']['personal'], str(self.external))
        self.assertEqual(saved['roots']['agent'], str(self.agent))
        self.assertEqual(saved['roots']['home'], str(self.home))
        with patch.dict(os.environ, {'CODEX_HOME': str(self.home / 'different')}):
            self.cli('bootstrap')
            self.cli('apply')
        self.assertTrue((self.home / '.agents/skills/report/SKILL.md').is_file())
        self.assertEqual((self.agent / 'AGENTS.md').resolve(), self.external / 'AGENTS.md')
        bundle = self.config.with_name(self.config.name + '.bundles') / 'personal'
        self.assertEqual((bundle / 'development/rules.md').read_text(), 'Guidance\n')
        self.assertIn('SessionStart', json.loads((self.agent / 'hooks.json').read_text())['hooks'])
        self.assertEqual(self.cli('locate', 'personal')['root'], str(self.external))

    def test_agent_fallback_and_explicit_overrides(self):
        with patch.dict(os.environ, {'CODEX_HOME': ''}):
            self.boot()
        self.assertEqual(tomlkit.parse(self.config.read_text())['roots']['agent'], str(self.home / '.codex'))
        custom = self.root / 'custom.toml'
        self.cli('--config', custom, 'bootstrap', '--catalog', self.catalog,
                 '--external', f'personal={self.external}', '--root', f'agent={self.agent}')
        self.assertEqual(tomlkit.parse(custom.read_text())['roots']['agent'], str(self.agent))

    def test_invalid_bindings_do_not_save_or_clone(self):
        for args in (('--external', 'bad'), ('--external', 'personal='),
                     ('--external', f'personal={self.external}'),
                     ('--external', f'typo={self.root / "other"}'), ('--catalog', self.catalog)):
            with self.subTest(args=args):
                self.boot(*args, code=1)
                self.assertFalse(self.config.exists())
                self.assertFalse(self.config.with_name(self.config.name + '.checkouts').exists())

    def test_missing_binding_is_required_only_for_external_catalog(self):
        self.cli('bootstrap', self.catalog, code=1)
        self.assertFalse(self.config.exists())
        self.save_catalog()
        self.cli('bootstrap', self.catalog)
        self.assertTrue(self.config.exists())

    def test_active_rebinding_rejected_without_changing_saved_config(self):
        self.require_links()
        self.boot()
        self.cli('apply')
        saved = self.config.read_bytes()
        other = self.root / 'other'
        other.mkdir()
        (other / 'AGENTS.md').write_text('Other guidance', encoding='utf-8')
        self.cli('bootstrap', '--external', f'personal={other}', code=1)
        self.assertEqual(self.config.read_bytes(), saved)
        self.assertEqual((self.agent / 'AGENTS.md').resolve(), self.external / 'AGENTS.md')

    def test_multiple_bindings_and_relative_path_resolution(self):
        catalog = tomlkit.parse(self.catalog.read_text(encoding='utf-8'))
        catalog['sources']['reference'] = {'type': 'external'}
        self.catalog.write_text(tomlkit.dumps(catalog), encoding='utf-8')
        other = self.root / 'reference'
        other.mkdir()
        # Relative paths must share a drive with the working directory on Windows.
        from contextlib import chdir
        with chdir(self.root):
            relative = os.path.relpath(other, Path.cwd())
            self.boot('--external', f'reference={relative}')
        bindings = tomlkit.parse(self.config.read_text(encoding='utf-8'))['external_paths']
        self.assertEqual(dict(bindings), {'personal': str(self.external), 'reference': str(other)})

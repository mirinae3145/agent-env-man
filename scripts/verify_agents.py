#!/usr/bin/env python3
"""Verify that installed agent CLIs accept AEM's setup without account credentials.

The checkout is installed through its repository installer into a disposable profile
connected to Codex and Claude Code. The agent CLIs on PATH then read that profile:
Codex must load its configuration and list the official skill in its prompt input, and
Claude Code must report no invalid settings and run AEM's session-start hook.
No account is used, so model requests, authenticated features, and Codex hook
execution remain outside this check.
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolated_profile import IsolatedProfile, require  # noqa: E402


def listed_skill_roots(prompt, name):
    """Return the roots under which Codex prompt input lists skill `name`."""
    # Codex may shorten skill files to aliases listed in its skill roots table.
    roots = {alias: Path(path) for alias, path in re.findall(r'- `(r\d+)` = `([^`]+)`', prompt)}
    return {roots.get(alias, Path(alias))
            for alias in re.findall(r'\(file: ([^)]+?)/' + re.escape(name) + r'/SKILL\.md\)', prompt)}


def verify_codex(profile, codex):
    doctor = profile.run([codex, 'doctor', '--json'], code=None, limit=120)
    checks = json.loads(doctor.stdout)['checks']
    require(checks.get('config.load', {}).get('status') == 'ok',
            f'Codex did not load the configured profile: {checks.get("config.load")}')
    skills = profile.agent_skills('codex')
    prompt = profile.run([codex, 'debug', 'prompt-input'], limit=120).stdout
    listed = listed_skill_roots(prompt, 'idk-aem')
    require(skills in listed, f'Codex prompt input does not list the official skill under {skills}: {listed}')


def verify_claude(profile, claude):
    doctor = profile.run([claude, 'doctor'], code=None, limit=120)
    require('Invalid settings' not in doctor.stdout,
            'Claude Code reported invalid settings:\n' + doctor.stdout)
    before = json.loads(profile.aem('status')).get('startup')
    # Without credentials the request fails, but session-start hooks run first.
    profile.run([claude, '-p', 'AEM integration check'], code=None, limit=120)
    after = json.loads(profile.aem('status')).get('startup') or {}
    require(after != before and after.get('trigger') == 'agent-start',
            f'Claude Code did not run the AEM session-start hook: {after}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--checkout', type=Path, default=Path(__file__).resolve().parents[1],
                        help='AEM checkout to install (default: this repository)')
    options = parser.parse_args(argv)
    try:
        tools = {name: shutil.which(name) for name in ('git', 'uv', 'codex', 'claude')}
        missing = [name for name, path in tools.items() if not path]
        require(not missing, 'Required commands are missing from PATH: ' + ', '.join(missing))
        with tempfile.TemporaryDirectory(prefix='aem-agents-') as directory:
            profile = IsolatedProfile(directory)
            profile.install(options.checkout.resolve(), '--shell', 'bash', '--agent', 'codex', '--agent', 'claude',
                            '--automation', 'off', '--self-update', 'off')
            for name in ('codex', 'claude'):
                version = profile.run([tools[name], '--version'], limit=60).stdout.strip().splitlines()[-1]
                print(f'{name}: {version}', flush=True)
            verify_codex(profile, tools['codex'])
            verify_claude(profile, tools['claude'])
        print('Verified Codex configuration and skill discovery, and Claude Code settings and startup hook')
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        print(f'Agent integration verification: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

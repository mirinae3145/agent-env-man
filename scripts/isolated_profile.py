"""Install AEM checkouts into a disposable user profile for end-to-end verification.

The profile owns its home, configuration, uv tool directories, and Git identity.
Commands run with that environment and never touch the invoking user's profiles.
"""

import os
from pathlib import Path
import subprocess
import sys
import tomllib


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_captured(*arguments, **options):
    """Run children without opening Windows console windows."""
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(*arguments, **options)


class IsolatedProfile:
    """A temporary user profile with its own AEM installation."""

    def __init__(self, root):
        # Temporary roots may use Windows short names or a redirected TMPDIR.
        self.root = Path(root).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.bin_dir = self.root / 'uv-bin'
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(('GIT_', 'UV_TOOL_', 'VIRTUAL_ENV', 'COVERAGE_'))}
        environment.update(HOME=str(self.home), USERPROFILE=str(self.home),
                           XDG_CONFIG_HOME=str(self.home / '.config'), CODEX_HOME=str(self.home / '.codex'),
                           APPDATA=str(self.home / 'AppData/Roaming'), LOCALAPPDATA=str(self.home / 'AppData/Local'),
                           UV_TOOL_DIR=str(self.root / 'uv-tools'), UV_TOOL_BIN_DIR=str(self.bin_dir),
                           PATH=os.pathsep.join([str(self.bin_dir), environment.get('PATH', '')]),
                           GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                           GIT_ALLOW_PROTOCOL='file', GIT_TEMPLATE_DIR='', GIT_TERMINAL_PROMPT='0',
                           GIT_AUTHOR_NAME='AEM verification', GIT_AUTHOR_EMAIL='verification@example.invalid',
                           GIT_COMMITTER_NAME='AEM verification', GIT_COMMITTER_EMAIL='verification@example.invalid',
                           PYTHONNOUSERSITE='1')
        for key in ('PYTHONPATH', 'PYTHONHOME'):
            environment.pop(key, None)
        self.environment = environment
        self.machine = self.home / '.config/agent-env-man/machine.toml'

    def run(self, command, *, cwd=None, code=0, limit=300):
        """Run a command in the profile; `code=None` accepts any exit status."""
        result = run_captured([str(part) for part in command], cwd=cwd or self.root, env=self.environment,
                              capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=limit)
        require(code is None or result.returncode == code,
                f'{command}: expected exit {code}, got {result.returncode}\n{result.stdout}\n{result.stderr}')
        return result

    def git(self, repository, *arguments):
        return self.run(['git', '-C', repository, '-c', f'core.hooksPath={os.devnull}', *arguments]).stdout

    def aem(self, *arguments, code=0):
        executable = self.bin_dir / ('aem.exe' if os.name == 'nt' else 'aem')
        return self.run([executable, '--json', *arguments], code=code).stdout

    def install(self, checkout, *options):
        """Install `checkout` through its own repository installer."""
        self.run([sys.executable, Path(checkout) / 'scripts/setup.py', *options], limit=600)

    def agent_skills(self, agent):
        """Return the skill root that setup bound for `agent`."""
        machine = tomllib.loads(self.machine.read_text(encoding='utf-8'))
        return Path(machine['agents'][agent]['skills'])

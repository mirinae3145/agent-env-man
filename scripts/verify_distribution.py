#!/usr/bin/env python3
"""Build and verify direct and sdist wheels in separate clean runtime environments.

Run from a Python environment with pip and build installed. Package acquisition
may use the network; the runtime verifier uses only disposable local fixtures.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def run(*arguments, cwd):
    print('+', ' '.join(map(str, arguments)), flush=True)
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    subprocess.run(list(map(str, arguments)), cwd=cwd, check=True, **options)


def only_file(directory, pattern):
    matches = list(directory.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f'Expected one {pattern} in {directory}, found {len(matches)}')
    return matches[0]


def main():
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='aem-distribution-') as temporary:
        root = Path(temporary)
        direct = root / 'direct'
        rebuilt = root / 'from-sdist'
        run(sys.executable, '-m', 'build', '--wheel', '--sdist', '--outdir', direct,
            repository, cwd=root)
        # pip unpacks and builds only the sdist, outside the original checkout.
        run(sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-cache-dir',
            '--wheel-dir', rebuilt, only_file(direct, '*.tar.gz'), cwd=root)
        for name, directory in [('direct', direct), ('from-sdist', rebuilt)]:
            runtime = root / ('runtime-' + name)
            run(sys.executable, '-m', 'venv', '--without-pip', runtime, cwd=root)
            python = runtime / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            # External pip keeps pip, setuptools, coverage and build out of runtime.
            run(sys.executable, '-m', 'pip', '--python', python, 'install',
                only_file(directory, '*.whl'), cwd=root)
            run(sys.executable, repository / 'scripts/verify_runtime.py',
                '--python', python, cwd=root)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'Distribution verification: {exc}', file=sys.stderr)
        raise SystemExit(1)

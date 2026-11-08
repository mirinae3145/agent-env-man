#!/usr/bin/env python3
"""Exercise payload copies on a chosen filesystem using disposable directories."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify(root):
    source, targets = root / 'source', root / 'targets'
    (source / 'nested/local-only').mkdir(parents=True)
    (source / 'nested/content').write_text('original', encoding='utf-8')
    (source / 'nested/local-only/metadata').write_text('source metadata', encoding='utf-8')
    # Keep machine state off the tested filesystem so source/target behavior is
    # measured independently of state-file locking and atomic-write support.
    with tempfile.TemporaryDirectory(prefix='aem-mount-state-') as local:
        config, catalog = Path(local) / 'machine.toml', Path(local) / 'catalog.toml'
        catalog.write_text('''version = 2
[payload.defaults]
exclude = ["**/._DAV", "**/local-only"]
[sources.store]
type = "external"
[directories.sample]
source = "store"
preserve_symlinks = true
[directories.sample.install]
root = "test"
mode = "copy"
''', encoding='utf-8')

        def cli(*args, code=0):
            result = subprocess.run([sys.executable, '-m', 'agent_env_man', '--config', str(config),
                                     '--json', *map(str, args)], capture_output=True, text=True)
            require(result.returncode == code, f'{args}: {result.stdout}\n{result.stderr}')
            return result.stdout + result.stderr if code else json.loads(result.stdout)

        cli('bootstrap', catalog, '--external', f'store={source}', '--root', f'test={targets}')
        cli('apply', '--item', 'sample', '--dry-run')
        cli('apply', '--item', 'sample')
        target = targets / 'sample'
        require(not (target / 'nested/local-only').exists(), 'Source metadata was copied')
        (target / 'nested/local-only').mkdir()
        (target / 'nested/local-only/metadata').write_text('target metadata', encoding='utf-8')
        (source / 'nested/content').write_text('updated', encoding='utf-8')
        cli('apply', '--item', 'sample')
        require((target / 'nested/content').read_text() == 'updated', 'Apply did not update content')
        require((target / 'nested/local-only/metadata').read_text() == 'target metadata', 'Apply lost metadata')
        require(cli('status')['items'][0]['status'] == 'current', 'Copy is not current')
        (target / 'nested/content').write_text('collected', encoding='utf-8')
        cli('publish', 'sample', '--from-copy', '--dry-run')
        cli('publish', 'sample', '--from-copy')
        require((source / 'nested/content').read_text() == 'collected', 'Collection did not update source')
        require((source / 'nested/local-only/metadata').read_text() == 'source metadata', 'Collection lost metadata')
        shutil.rmtree(target / 'nested')
        error = cli('publish', 'sample', '--from-copy', '--dry-run', code=1)
        require('Cannot preserve excluded entry' in error, 'Collection preview missed ancestor removal')
        cli('apply', '--item', 'sample', '--replace')
        (target / 'nested/local-only').mkdir()
        (target / 'nested/local-only/metadata').write_text('keep', encoding='utf-8')
        shutil.rmtree(source / 'nested')
        error = cli('apply', '--item', 'sample', '--dry-run', code=1)
        require('Cannot preserve excluded entry' in error, 'Apply preview missed ancestor removal')
        require((target / 'nested/local-only/metadata').read_text() == 'keep', 'Preview changed metadata')
        cli('detach', 'sample')
        require((target / 'nested/local-only/metadata').read_text() == 'keep', 'Detach lost metadata')
        print('PASS: apply, status, collection, both preservation previews, and detach')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='Existing writable directory on the filesystem to test')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='.aem-payload-check-', dir=args.root) as temporary:
        print(f'Test directory: {temporary}', flush=True)
        verify(Path(temporary))


if __name__ == '__main__':
    main()

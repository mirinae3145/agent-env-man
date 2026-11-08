"""Count payload inspections for command regression tests."""

from collections import Counter
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from unittest.mock import patch

from agent_env_man.cli import main as cli_main
from agent_env_man import copy_publication, manager, payload_links, permissions, storage


def run(config, *args):
    output, errors = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        code = cli_main(['--config', str(config), '--json', *args])
    if code:
        raise RuntimeError(f'{args}: {output.getvalue()}\n{errors.getvalue()}')
    return json.loads(output.getvalue())


def count_inspections(config, args, source, target):
    counts = Counter()
    fingerprint, scan, snapshot = storage.fingerprint, payload_links.scan, permissions.snapshot

    def location(path):
        path = Path(path)
        if path == source:
            return 'source'
        if path == target:
            return 'target'
        if source in path.parents:
            return 'source-child'
        if target in path.parents:
            return 'target-child'
        return 'other'

    def hashed(path, **policy):
        if not policy.get('preserve_symlinks'):
            counts[f'content:{location(path)}'] += 1
        return fingerprint(path, **policy)

    def scanned(path, **policy):
        kind = 'permissions' if policy.get('modes_only') else 'copy' if policy.get('destination') is not None else 'content'
        counts[f'{kind}:{location(path)}'] += 1
        return scan(path, **policy)

    def modes(path, **policy):
        # Snapshots delegate to scan, which counts the permission walk.
        return snapshot(path, **policy)

    with ExitStack() as stack:
        stack.enter_context(patch.object(storage, 'fingerprint', hashed))
        stack.enter_context(patch.object(manager, 'fingerprint', hashed))
        stack.enter_context(patch.object(copy_publication, 'fingerprint', hashed))
        stack.enter_context(patch.object(payload_links, 'scan', scanned))
        stack.enter_context(patch.object(copy_publication, 'scan', scanned))
        stack.enter_context(patch.object(permissions, 'snapshot', modes))
        run(config, *args)
    return dict(sorted(counts.items()))

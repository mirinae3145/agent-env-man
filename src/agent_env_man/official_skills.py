"""Standard-library-only official skill identity checks, also copied to the worker."""

import hashlib
from importlib import resources
import os
from pathlib import Path
import stat

try:
    from .link_paths import same_destination
except ImportError:  # Copied worker runs without the installed package.
    from link_paths import same_destination

NAME = 'idk-aem'


def source():
    """Find packaged resources, or the original tree during PYTHONPATH development."""
    try:
        return Path(str(resources.files('agent_env_man.builtin_skills'))) / NAME
    except ModuleNotFoundError as exc:
        if exc.name != 'agent_env_man.builtin_skills':
            raise
        path = Path(__file__).resolve().parents[2] / 'skills' / NAME
        if not (path / 'SKILL.md').is_file():
            raise ValueError('Official AEM skill is missing from the installation') from exc
        return path


def signature(path):
    """Hash the complete regular tree so edits and added files block replacement."""
    digest = hashlib.sha256()

    def visit(current):
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f'Official skill payload redirects: {current}')
        relative = current.relative_to(path).as_posix()
        digest.update(relative.encode('utf-8') + b'\0')
        digest.update(str(info.st_mode & 0o111).encode() + b'\0')
        if stat.S_ISDIR(info.st_mode):
            digest.update(b'd\0')
            for child in sorted(current.iterdir()):
                visit(child)
        elif stat.S_ISREG(info.st_mode):
            digest.update(b'f\0')
            file_digest = hashlib.sha256()
            with current.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    file_digest.update(block)
            digest.update(file_digest.digest())
        else:
            raise ValueError(f'Official skill payload is not regular: {current}')

    visit(path)
    return digest.hexdigest()


def check(records, *, payload=True, package_version=None):
    """Validate active recorded links before package replacement or link refresh."""
    for record in records.values():
        if not record.get('official_skill') or record.get('detached'):
            continue
        if any(not isinstance(record.get(field), str) for field in ('target', 'source', 'official_hash', 'package_version')):
            raise ValueError('Official skill ownership metadata is malformed')
        target, original = Path(record['target']), Path(record['source'])
        if not target.is_absolute() or not original.is_absolute():
            raise ValueError('Official skill ownership paths must be absolute')
        if target.parent.resolve() / target.name != target:
            raise ValueError(f'Official skill target ancestry changed: {target}')
        if not target.is_symlink() or not same_destination(os.readlink(target), str(original)):
            raise ValueError(f'Official skill link changed: {target}; reconcile before setup/update')
        if (payload and (package_version is None or record.get('package_version') == package_version)
                and signature(original) != record.get('official_hash')):
            raise ValueError(f'Official skill source changed locally: {original}; preserve edits before update')

"""POSIX link payloads, inspected through pinned, non-following descriptors.

Physical staging locations never determine link policy: ``source_relative`` is
always the node's location inside its logical source root. Referents are opaque.
"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import shutil

from .model import Error


def options(value):
    """Read optional payload policy from a current item or saved ownership."""
    if isinstance(value, dict):
        enabled = value.get('preserve_symlinks', False)
        relative = value.get('relative', '.')
    else:
        enabled = value.preserve_symlinks
        relative = value.relative
    if not isinstance(enabled, bool):
        raise Error('Invalid saved preserve_symlinks policy')
    if not enabled:
        return {}
    require_posix()
    if not isinstance(relative, str) or PurePosixPath(relative).is_absolute() or '..' in relative.split('/'):
        raise Error('Invalid logical payload location')
    return {'preserve_symlinks': True, 'source_relative': relative}


def require_posix():
    if os.name == 'nt':
        raise Error('preserve_symlinks is unsupported on Windows')


def validate_link(target, location):
    """Reject a relative target at its first step above the source root."""
    require_posix()
    if not target or '\0' in target:
        raise Error(f'Invalid symbolic link target: {location}')
    if target.startswith('/'):
        return
    depth = len(PurePosixPath(location).parent.parts)
    for part in target.split('/'):
        if part == '..':
            depth -= 1
            if depth < 0:
                raise Error(f'Relative symbolic link escapes source root: {location} -> {target}')
        elif part not in ('', '.'):
            depth += 1


@contextmanager
def directory_fd(path):
    """Pin every ancestor without resolving any symbolic links."""
    require_posix()
    path = Path(os.path.abspath(path))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        yield fd
    finally:
        os.close(fd)


def replace(source, destination):
    """Rename entries without following a concurrently redirected ancestor."""
    source, destination = Path(source), Path(destination)
    with directory_fd(source.parent) as left, directory_fd(destination.parent) as right:
        os.replace(source.name, destination.name, src_dir_fd=left, dst_dir_fd=right)


def remove(path):
    """Remove an entry through its pinned parent; never recurse into a link."""
    path = Path(path)
    with directory_fd(path.parent) as parent:
        try:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISDIR(info.st_mode):
            if not shutil.rmtree.avoids_symlink_attacks:
                raise Error('Safe directory removal is unavailable on this platform')
            shutil.rmtree(path.name, dir_fd=parent)
        else:
            os.unlink(path.name, dir_fd=parent)


def chmod_directory(path, mode):
    with directory_fd(path) as fd:
        os.fchmod(fd, mode)


def scan(path, *, source_relative='.', exclude_git=False, destination=None, allow_symlinks=True):
    """Hash and optionally copy one opaque-link tree; also return preview entries.

    Regular node encoding is identical to storage.fingerprint. O_NOFOLLOW and
    descriptor-relative recursion prevent check/open races from reading link
    referents. Changes during traversal abort rather than committing a mixture.
    """
    require_posix()
    path = Path(path)
    digest = hashlib.sha256()
    entries = {}

    def identity(info):
        return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns

    def visit(parent, name, relative, out_parent, out_name):
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        kind = ('l' if stat.S_ISLNK(before.st_mode) else 'd' if stat.S_ISDIR(before.st_mode)
                else 'f' if stat.S_ISREG(before.st_mode) else None)
        logical = str(PurePosixPath(source_relative) / relative.lstrip('/'))
        if kind is None:
            raise Error(f'Special files are unsupported: {logical}')
        executable = before.st_mode & 0o111 if kind != 'l' else 0
        digest.update(json.dumps([relative, kind, executable], ensure_ascii=True).encode() + b'\0')
        target = None
        file_hash = None
        if kind == 'l':
            if not allow_symlinks:
                raise Error(f'Payload symlinks/junctions are unsupported: {logical}')
            target = os.readlink(name, dir_fd=parent)
            validate_link(target, logical)
            digest.update(json.dumps(target, ensure_ascii=True).encode() + b'\0')
            if out_parent is not None:
                os.symlink(target, out_name, dir_fd=out_parent)
        else:
            flags = os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if kind == 'd' else os.O_NONBLOCK)
            fd = os.open(name, flags, dir_fd=parent)
            out_fd = None
            try:
                if identity(os.fstat(fd)) != identity(before):
                    raise Error(f'Payload changed while opening: {logical}')
                if out_parent is not None:
                    if kind == 'd':
                        os.mkdir(out_name, mode=0o700, dir_fd=out_parent)
                        out_fd = os.open(out_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=out_parent)
                    else:
                        out_fd = os.open(out_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                         0o600, dir_fd=out_parent)
                if kind == 'd':
                    for child in sorted(os.listdir(fd)):
                        if exclude_git and not relative and child == '.git':
                            continue
                        visit(fd, child, f'{relative}/{child}', out_fd, child)
                else:
                    content = hashlib.sha256()
                    while block := os.read(fd, 1024 * 1024):
                        content.update(block)
                        if out_fd is not None:
                            remaining = memoryview(block)
                            while remaining:
                                remaining = remaining[os.write(out_fd, remaining):]
                    file_hash = content.digest()
                    digest.update(file_hash)
                if identity(os.fstat(fd)) != identity(before):
                    raise Error(f'Payload changed during inspection: {logical}')
                if out_fd is not None:
                    os.fchmod(out_fd, stat.S_IMODE(before.st_mode))
                    os.utime(out_fd, ns=(before.st_atime_ns, before.st_mtime_ns))
            finally:
                if out_fd is not None:
                    os.close(out_fd)
                os.close(fd)
        if identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity(before):
            raise Error(f'Payload changed during inspection: {logical}')
        entries[relative.lstrip('/') or '.'] = (kind, executable, target if kind == 'l' else file_hash)

    with directory_fd(path.parent) as parent:
        if destination is None:
            visit(parent, path.name, '', None, None)
        else:
            destination = Path(destination)
            with directory_fd(destination.parent) as out:
                visit(parent, path.name, '', out, destination.name)
    return digest.hexdigest(), entries

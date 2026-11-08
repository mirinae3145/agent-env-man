"""POSIX link payloads, inspected through pinned, non-following descriptors.

Physical staging locations never determine link policy: ``source_relative`` is
always the node's location inside its logical source root. Referents are opaque.
"""

from contextlib import contextmanager
from concurrent.futures import wait
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import shutil
import uuid

from .model import Error
from .payload_io import PayloadReads


class CopyCleanupError(Error):
    """Stop enclosing stage cleanup so raced content remains recoverable."""

    def __init__(self, message, preserved_path):
        self.preserved_path = Path(preserved_path)
        super().__init__(f'{message}; preserved at {self.preserved_path}')


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
    from .payload_policy import rules
    exclusions = rules(value.get('exclusions', ()) if isinstance(value, dict) else value.exclusions)
    result = {'exclusions': exclusions} if exclusions else {}
    from .permissions import validate
    permission_policy = validate(value.get("permissions", "strict") if isinstance(value, dict) else value.permissions)
    if permission_policy == "best-effort":
        result["permissions"] = permission_policy
    if isinstance(value, dict) and value.get('exclude_prefix'):
        prefix = value['exclude_prefix']
        rules([(prefix, 'placeholder')])
        result['exclude_prefix'] = prefix
    if not enabled:
        return result
    if not isinstance(relative, str) or PurePosixPath(relative).is_absolute() or '..' in relative.split('/'):
        raise Error('Invalid logical payload location')
    return {**result, 'preserve_symlinks': True, 'source_relative': relative}


def validate_link(target, location):
    """Reject a relative target at its first step above the source root."""
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


def _discard_copy(destination, expected_identity):
    """Detach before deleting, retaining a raced replacement for recovery.

    A stat followed by rmtree/unlink cannot protect the original name from a
    replacement. Rename into an exclusive private directory, then check the
    moved entry; a mismatch stays there and its location is reported. Removal
    inside that directory cannot touch a recreated original destination.
    """
    destination = Path(destination)
    with directory_fd(destination.parent) as parent:
        try:
            info = os.stat(destination.name, dir_fd=parent, follow_symlinks=False)
        except OSError as exc:
            raise CopyCleanupError(f'Cannot inspect copied payload before timestamp reinspection: {exc}', destination) from exc
        if (info.st_dev, info.st_ino) != expected_identity:
            raise CopyCleanupError('Copied payload changed before timestamp reinspection', destination)
        if stat.S_ISDIR(info.st_mode) and not shutil.rmtree.avoids_symlink_attacks:
            raise CopyCleanupError('Safe directory removal is unavailable on this platform', destination)
        if stat.S_ISDIR(info.st_mode):
            try:
                root = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    opened = os.fstat(root)
                    if (opened.st_dev, opened.st_ino) != expected_identity:
                        raise CopyCleanupError('Copied payload changed before timestamp reinspection', destination)
                    # Moving a directory to another parent can require write access
                    # to update its '..' entry. Change only the verified copy inode.
                    os.fchmod(root, stat.S_IMODE(opened.st_mode) | 0o700)
                finally:
                    os.close(root)
            except OSError as exc:
                raise CopyCleanupError(f'Cannot prepare copied payload for timestamp reinspection: {exc}', destination) from exc
        holding = '.aem-reinspection-' + uuid.uuid4().hex
        os.mkdir(holding, mode=0o700, dir_fd=parent)
        retained = destination.parent / holding / 'payload'
        moved = False
        try:
            fd = os.open(holding, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                os.rename(destination.name, 'payload', src_dir_fd=parent, dst_dir_fd=fd)
                moved = True
                info = os.stat('payload', dir_fd=fd, follow_symlinks=False)
                if (info.st_dev, info.st_ino) != expected_identity:
                    raise CopyCleanupError('Copied payload changed before timestamp reinspection', retained)
                if stat.S_ISDIR(info.st_mode):
                    root = os.open('payload', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        _writable_copy_directories(root)
                    finally:
                        os.close(root)
                    shutil.rmtree('payload', dir_fd=fd)
                else:
                    os.unlink('payload', dir_fd=fd)
                moved = False
            finally:
                os.close(fd)
        except CopyCleanupError:
            raise
        except Exception as exc:
            raise CopyCleanupError(f'Cannot remove copied payload before timestamp reinspection: {exc}',
                                   retained if moved else destination) from exc
        finally:
            if not moved:
                os.rmdir(holding, dir_fd=parent)


def _writable_copy_directories(fd):
    """Restore owner access only inside the retired, verified temporary copy."""
    info = os.fstat(fd)
    os.fchmod(fd, stat.S_IMODE(info.st_mode) | 0o700)
    with os.scandir(fd) as listing:
        children = [entry.name for entry in listing if entry.is_dir(follow_symlinks=False)]
    for name in children:
        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            _writable_copy_directories(child)
        finally:
            os.close(child)


def scan(path, *, source_relative='.', exclude_git=False, destination=None, allow_symlinks=True, exclusions=(), exclude_prefix="", permissions="strict", modes=None, node_types=None, permission_failures=None, destination_modes=None, modes_only=False):
    """Retry one timestamp-only race, exposing only a complete matching capture.

    The first traversal still rejects identity, mode, size and structural edits.
    When only timestamps drift, finish collecting its contents before making a
    fresh strict traversal. Matching both captures prevents a same-size edit
    from being adopted merely because the second traversal was stable.
    """
    policy = dict(source_relative=source_relative, exclude_git=exclude_git,
                  destination=destination, allow_symlinks=allow_symlinks,
                  exclusions=exclusions, exclude_prefix=exclude_prefix,
                  permissions=permissions, destination_modes=destination_modes,
                  modes_only=modes_only)
    first = None
    for attempt in range(2):
        state = {'defer_timestamps': attempt == 0, 'timestamp_changed': False}
        captured_modes = {} if modes is not None else None
        captured_types = {} if node_types is not None else None
        failures = [] if permission_failures is not None else None
        try:
            result = _scan(path, modes=captured_modes, node_types=captured_types,
                           permission_failures=failures, state=state, **policy)
        except FileExistsError as exc:
            if attempt and destination is not None:
                raise CopyCleanupError('Copy destination appeared before timestamp reinspection', destination) from exc
            raise
        if first is not None or state['timestamp_changed']:
            identities = {name: value[:4] if len(value) == 6 else value
                          for name, value in state['guarded'].items()}
            if first is not None and (result != first[0] or identities != first[1]):
                raise Error(f'Payload changed during timestamp reinspection: {source_relative}')
        if not state['timestamp_changed']:
            if modes is not None:
                modes.update(captured_modes)
            if node_types is not None:
                node_types.update(captured_types)
            if permission_failures is not None:
                permission_failures.extend(failures)
            return result
        first = result, identities
        if destination is not None:
            _discard_copy(destination, state['destination_identity'])


def _scan(path, *, state, source_relative='.', exclude_git=False, destination=None, allow_symlinks=True, exclusions=(), exclude_prefix="", permissions="strict", modes=None, node_types=None, permission_failures=None, destination_modes=None, modes_only=False):
    """Hash and optionally copy one opaque-link tree; also return preview entries.

    Regular node encoding is identical to storage.fingerprint. O_NOFOLLOW and
    descriptor-relative recursion prevent check/open races from reading link
    referents. Non-timestamp changes abort; the caller compares complete captures
    before accepting a deferred timestamp change.
    """
    from .permissions import validate, apply as apply_permissions
    validate(permissions)
    from .payload_policy import excluded
    path = Path(path)
    digest = hashlib.sha256()
    entries = {}
    guarded = {}
    state['guarded'] = guarded
    def identity(info):
        if exclusions and stat.S_ISDIR(info.st_mode):
            # Excluded children may appear or change while included entries are
            # read. Guard directory identity and the included name set instead.
            return info.st_dev, info.st_ino, info.st_mode
        return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns

    def check(before, after, logical, *, opening=False):
        if before == after:
            return
        if (state['defer_timestamps'] and before is not None and len(before) == 6
                and len(after) == 6 and before[:4] == after[:4]):
            state['timestamp_changed'] = True
            return
        when = 'while opening' if opening else 'during inspection'
        raise Error(f'Payload changed {when}: {logical}')

    def visit(parent, name, relative, out_parent, out_name, *, leaf=False):
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        guarded[relative] = identity(before)
        kind = ('l' if stat.S_ISLNK(before.st_mode) else 'd' if stat.S_ISDIR(before.st_mode)
                else 'f' if stat.S_ISREG(before.st_mode) else None)
        logical = str(PurePosixPath(source_relative) / relative.lstrip('/'))
        if kind is None:
            raise Error(f'Special files are unsupported: {logical}')
        if leaf and kind == 'd':
            raise Error(f'Payload changed during inspection: {logical}')
        executable = before.st_mode & 0o111 if kind != 'l' and permissions == 'strict' else 0
        logical_path = relative.lstrip('/') or '.'
        if modes is not None and kind != 'l':
            modes[logical_path] = stat.S_IMODE(before.st_mode)
        if node_types is not None and kind != 'l':
            node_types[logical_path] = kind
        target = None
        file_hash = None
        if kind == 'l':
            if not allow_symlinks:
                raise Error(f'Payload symlinks are unsupported: {logical}')
            target = os.readlink(name, dir_fd=parent)
            validate_link(target, logical)
            if out_parent is not None:
                os.symlink(target, out_name, dir_fd=out_parent)
                if not relative:
                    created = os.stat(out_name, dir_fd=out_parent, follow_symlinks=False)
                    state['destination_identity'] = created.st_dev, created.st_ino
        else:
            flags = os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if kind == 'd' else os.O_NONBLOCK)
            fd = os.open(name, flags, dir_fd=parent)
            out_fd = None
            try:
                check(identity(before), identity(os.fstat(fd)), logical, opening=True)
                if out_parent is not None:
                    if kind == 'd':
                        os.mkdir(out_name, mode=0o700, dir_fd=out_parent)
                        out_fd = os.open(out_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=out_parent)
                    else:
                        out_fd = os.open(out_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                         0o600, dir_fd=out_parent)
                    if not relative:
                        created = os.fstat(out_fd)
                        state['destination_identity'] = created.st_dev, created.st_ino
                if kind == 'd':
                    with os.scandir(fd) as listing:
                        children = [child for child in sorted(listing, key=lambda entry: entry.name)
                                    if not (exclude_git and not relative and child.name == '.git')
                                    and not excluded(f'{relative}/{child.name}', exclusions, exclude_prefix)]
                    names = [child.name for child in children]
                    pending = []
                    try:
                        for child in children:
                            if child.is_dir(follow_symlinks=False):
                                visit(fd, child.name, f'{relative}/{child.name}', out_fd, child.name)
                            else:
                                pending.append(pool.submit(visit, fd, child.name, f'{relative}/{child.name}',
                                                      out_fd, child.name, leaf=True))
                                if len(pending) >= 8:
                                    pending.pop(0).result()
                        for future in pending:
                            future.result()
                    finally:
                        # Parents stay pinned until all readers/copy writers have
                        # finished, including when another child fails inspection.
                        wait(pending)
                    if exclusions and names != [child for child in sorted(os.listdir(fd))
                            if not (exclude_git and not relative and child == '.git')
                            and not excluded(f'{relative}/{child}', exclusions, exclude_prefix)]:
                        raise Error(f'Payload changed during inspection: {logical}')
                elif not modes_only:
                    content = hashlib.sha256()
                    while block := os.read(fd, 1024 * 1024):
                        content.update(block)
                        if out_fd is not None:
                            remaining = memoryview(block)
                            while remaining:
                                remaining = remaining[os.write(out_fd, remaining):]
                    file_hash = content.digest()
                check(identity(before), identity(os.fstat(fd)), logical)
                if out_fd is not None:
                    if kind == 'f':
                        # davfs can apply a stale zero length during metadata
                        # updates on an open write handle. Close it first, then
                        # reopen through the pinned parent and verify identity.
                        copied = os.fstat(out_fd)
                        os.close(out_fd)
                        out_fd = None
                        out_fd = os.open(out_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=out_parent)
                        reopened = os.fstat(out_fd)
                        if (copied.st_dev, copied.st_ino) != (reopened.st_dev, reopened.st_ino):
                            raise Error(f'Copied payload changed before metadata update: {logical}')
                    wanted = (destination_modes or {}).get(logical_path, stat.S_IMODE(before.st_mode))
                    if permissions == "best-effort":
                        apply_permissions(out_fd, wanted, path=logical_path, failures=permission_failures)
                    else:
                        os.fchmod(out_fd, wanted)
                    os.utime(out_fd, ns=(before.st_atime_ns, before.st_mtime_ns))
            finally:
                if out_fd is not None:
                    os.close(out_fd)
                os.close(fd)
        check(identity(before), identity(os.stat(name, dir_fd=parent, follow_symlinks=False)), logical)
        entries[relative.lstrip('/') or '.'] = (kind, executable, target if kind == 'l' else file_hash)

    def verify(parent, name, relative, seen):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        check(guarded.get(relative), identity(info), relative or source_relative)
        seen.add(relative)
        if stat.S_ISDIR(info.st_mode):
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                check(identity(info), identity(os.fstat(fd)), relative or source_relative)
                pending = []
                try:
                    with os.scandir(fd) as listing:
                        children = sorted(listing, key=lambda entry: entry.name)
                    for child in children:
                        if exclude_git and not relative and child.name == '.git':
                            continue
                        child_relative = f'{relative}/{child.name}'
                        if excluded(child_relative, exclusions, exclude_prefix):
                            continue
                        if child.is_dir(follow_symlinks=False):
                            verify(fd, child.name, child_relative, seen)
                        else:
                            pending.append(pool.submit(verify_leaf, fd, child.name, child_relative))
                            if len(pending) >= 8:
                                seen.add(pending.pop(0).result())
                    for future in pending:
                        seen.add(future.result())
                finally:
                    wait(pending)
            finally:
                os.close(fd)

    def verify_leaf(parent, name, relative):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            raise Error(f'Payload changed during inspection: {relative}')
        check(guarded.get(relative), identity(info), relative)
        return relative

    with PayloadReads() as pool, directory_fd(path.parent) as parent:
        if destination is None:
            visit(parent, path.name, '', None, None)
        else:
            destination = Path(destination)
            with directory_fd(destination.parent) as out:
                visit(parent, path.name, '', out, destination.name)
        if exclusions or state['timestamp_changed'] or not state['defer_timestamps']:
            # Exclusions and deferred timestamps cannot prove the included name
            # set stayed fixed. Recheck every included identity before retrying.
            seen = set()
            verify(parent, path.name, '', seen)
            if seen != guarded.keys():
                raise Error(f'Payload changed during inspection: {source_relative}')
    # Reconstruct the unchanged preorder encoding after concurrent leaf I/O.
    # Sorting path components puts each directory before its own descendants.
    for relative in sorted(entries, key=lambda name: () if name == '.' else tuple(name.split('/'))):
        kind, executable, value = entries[relative]
        encoded_relative = '' if relative == '.' else '/' + relative
        digest.update(json.dumps([encoded_relative, kind, executable], ensure_ascii=True).encode() + b'\0')
        if kind == 'l':
            digest.update(json.dumps(value, ensure_ascii=True).encode() + b'\0')
        elif kind == 'f' and not modes_only:
            digest.update(value)
    return digest.hexdigest(), entries

"""Local bookkeeping, process locks, and conservative filesystem inspection."""

from collections import deque
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from .model import Error
from .link_paths import same_destination
from .payload_io import PayloadReads


def exists(path: Path) -> bool:
    return os.path.lexists(path)


def atomic_write(path: Path, data: bytes, mode: int = 0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".aem-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def fingerprint(path: Path, *, exclude_git: bool = False, preserve_symlinks=False, source_relative=".", exclusions=(), exclude_prefix="", permissions="strict", entries=None) -> str:
    """Hash regular payloads, including empty directories and executable bits.

    The default rejects nested links and special files. Opted-in POSIX directory
    links retain opaque identity under a separately supplied logical location;
    ordinary node hashes remain compatible with existing ownership.
    Optional comparison entries retain node kinds, executable bits, opaque link
    text, and file digests from these same reads without changing hash encoding.
    """
    from .payload_policy import excluded
    from .permissions import validate
    validate(permissions)
    if preserve_symlinks:
        from .payload_links import scan
        hashed, captured = scan(path, source_relative=source_relative, exclude_git=exclude_git, exclusions=exclusions, exclude_prefix=exclude_prefix, permissions=permissions)
        if entries is not None:
            entries.update(captured)
        return hashed
    digest = hashlib.sha256()

    # Consume a bounded window in traversal order, including across recursive
    # directory visits, so completed reads do not accumulate for the whole tree.
    pieces = deque()

    def consume():
        piece = pieces.popleft()
        digest.update(piece if isinstance(piece, bytes) else piece.result())

    def append(piece):
        pieces.append(piece)
        if len(pieces) >= 8:
            consume()

    def metadata(current, relative):
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise Error(f"Payload symlinks are unsupported: {current}")
        kind = "d" if stat.S_ISDIR(info.st_mode) else "f" if stat.S_ISREG(info.st_mode) else None
        if kind is None:
            raise Error(f"Special files are unsupported: {current}")
        executable = info.st_mode & 0o111 if permissions == "strict" else 0
        return info, kind, json.dumps([relative, kind, executable], ensure_ascii=True).encode() + b"\0"

    def file_piece(current, relative):
        info, kind, encoded = metadata(current, relative)
        if kind != "f":
            raise Error(f"Payload changed during inspection: {current}")
        file_hash = hashlib.sha256()
        with current.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                file_hash.update(block)
        content = file_hash.digest()
        if entries is not None:
            executable = info.st_mode & 0o111 if permissions == "strict" else 0
            entries[relative.lstrip('/') or '.'] = (kind, executable, content)
        return encoded + content

    def visit(current, relative, pool):
        info, kind, encoded = metadata(current, relative)
        if kind == "f":
            append(file_piece(current, relative))
            return
        append(encoded)
        if entries is not None:
            executable = info.st_mode & 0o111 if permissions == "strict" else 0
            entries[relative.lstrip('/') or '.'] = (kind, executable, None)
        with os.scandir(current) as listing:
            children = sorted(listing, key=lambda entry: entry.name)
        for child in children:
            if exclude_git and not relative and child.name == ".git":
                continue
            child_relative = f"{relative}/{child.name}"
            if excluded(child_relative, exclusions, exclude_prefix):
                continue
            if child.is_dir(follow_symlinks=False):
                visit(Path(child.path), child_relative, pool)
            else:
                append(pool.submit(file_piece, Path(child.path), child_relative))

    with PayloadReads() as pool:
        visit(path, "", pool)
        while pieces:
            consume()
    return digest.hexdigest()


def link_matches(observed: dict, source: str) -> bool:
    """Compare desired link ownership without changing raw journal observations."""
    return observed.get("kind") == "link" and same_destination(observed.get("to"), source)


def observation(path: Path, *, modes=None, entries=None, **policy) -> dict:
    if path.is_symlink():
        return {"kind": "link", "to": os.readlink(path)}
    if not exists(path):
        return {"kind": "missing"}
    kind = "directory" if path.is_dir() else "file"
    if policy.get("permissions") == "best-effort":
        from .payload_links import scan
        from .permissions import digest
        captured = {}
        # The same guarded descriptors yield contents and modes. A separate
        # permission walk both costs another traversal and can observe a later
        # version of a file than the content hash did.
        hashed, tree = scan(path, modes=captured, allow_symlinks=policy.get("preserve_symlinks", False),
                         **{k: v for k, v in policy.items() if k != "preserve_symlinks"})
        if modes is not None:
            modes.update(captured)
        if entries is not None:
            entries.update(tree)
        return {"kind": kind, "hash": hashed, "permissions_hash": digest(captured)}
    options = {"entries": entries} if entries is not None else {}
    return {"kind": kind, "hash": fingerprint(path, **options, **policy)}


def copy_payload(source: Path, destination: Path, *, exclude_git: bool = False, permission_failures=None, destination_modes=None, **policy):
    if policy.get("preserve_symlinks") or policy.get("permissions") == "best-effort":
        from .payload_links import scan
        scan(source, destination=destination, exclude_git=exclude_git, allow_symlinks=policy.get("preserve_symlinks", False), permission_failures=permission_failures, destination_modes=destination_modes, **{k: v for k, v in policy.items() if k != "preserve_symlinks"})
        return
    from .payload_policy import excluded
    fingerprint(source, exclude_git=exclude_git, **policy)
    if policy.get("permissions") == "best-effort":
        from .permissions import apply as apply_permissions
        def metadata(src, dst):
            info = src.stat()
            relative = src.relative_to(source).as_posix() if source.is_dir() else "."
            wanted = (destination_modes or {}).get(relative, stat.S_IMODE(info.st_mode))
            apply_permissions(dst, wanted, path=relative, failures=permission_failures)
            os.utime(dst, ns=(info.st_atime_ns, info.st_mtime_ns))
        def copy_file(src, dst):
            shutil.copyfile(src, dst)
            metadata(Path(src), Path(dst))
            return dst
        from .payload_policy import excluded
        def visit(src, dst, relative=""):
            if src.is_dir():
                dst.mkdir()
                for child in sorted(src.iterdir()):
                    name = "/".join(p for p in (relative, child.name) if p)
                    if not (exclude_git and not relative and child.name == ".git") and not excluded(name, policy.get("exclusions", ()), policy.get("exclude_prefix", "")):
                        visit(child, dst / child.name, name)
                metadata(src, dst)
            else:
                copy_file(src, dst)
        visit(source, destination)
        return
    if source.is_dir():
        # A repository-root skill can be installed directly, but detaching or
        # copying it must not clone Git administration data or a worktree link.
        def ignored(directory, names):
            prefix = Path(directory).relative_to(source).as_posix()
            prefix = '' if prefix == '.' else prefix
            return {name for name in names if (exclude_git and not prefix and name == '.git')
                    or excluded('/'.join(p for p in (prefix, name) if p), policy.get('exclusions', ()), policy.get('exclude_prefix', ''))}
        shutil.copytree(source, destination, symlinks=True, ignore=ignored)
    else:
        shutil.copy2(source, destination)


def remove(path: Path):
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)


def lock(directory: Path, *, timeout: float = 0, shared: bool = False):
    from .process_lock import lock as process_lock
    return process_lock(directory, timeout=timeout, error_type=Error, shared=shared)

class State:
    def __init__(self, directory: Path, *, maintenance=False):
        self.maintenance = maintenance
        self.path = directory / "state.json"
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {"version": 2, "items": {}, "sources": {}, "pending": None}
        # Versions 1 and 2 share the ownership/journal envelope. Maintenance
        # preserves their version and opaque fields; it never migrates them.
        versions = (1, 2) if maintenance else (2,)
        if (not isinstance(self.data, dict) or isinstance(self.data.get("version"), bool)
                or not isinstance(self.data.get("version"), int) or self.data["version"] not in versions):
            requirement = ("maintenance requires state version 1 or 2" if maintenance else
                           "installation requires version 2; use status, detach, recover, or removal-only setup for old state")
            raise Error(f"Unsupported state version; {requirement}; do not delete ownership records")
        if (not isinstance(self.data.get("items"), dict)
                or any(not isinstance(r, dict) for r in self.data["items"].values())
                or not isinstance(self.data.get("sources"), dict)
                or "pending" not in self.data
                or (self.data["pending"] is not None and not isinstance(self.data["pending"], dict))):
            raise Error("Invalid ownership state envelope; do not delete ownership records")
        if not maintenance:
            for record in self.data["items"].values():
                if record.get("mode") not in ("link", "copy", "agent-hook", "setup-shell", "setup-config", "settings"):
                    raise Error("Unsupported installation mode in saved state; use maintenance commands to release it")

    def save(self):
        atomic_write(self.path, (json.dumps(self.data, indent=2, ensure_ascii=True) + "\n").encode())

    def ready(self):
        if self.data["pending"] is not None:
            raise Error("An interrupted replacement needs `aem recover`; inspect `aem status` first")


def saved_path(value):
    """Validate a recorded mutation path without resolving its final symlink."""
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise Error("Saved target/recovery path must be absolute")
    path = Path(value)
    if ".." in path.parts or path == path.parent or path.parent.resolve() != path.parent:
        raise Error(f"Saved path has redirected or invalid ancestry: {path}")
    return path

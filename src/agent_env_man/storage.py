"""Local bookkeeping, process locks, and conservative filesystem inspection."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from .model import Error
from .link_paths import same_destination


def exists(path: Path) -> bool:
    return os.path.lexists(path)


def is_reparse(path: Path) -> bool:
    # Path.is_junction is unavailable on supported Python 3.11 installations.
    # Reject all Windows reparse payloads rather than following a junction.
    return bool(getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


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


def fingerprint(path: Path, *, exclude_git: bool = False, preserve_symlinks=False, source_relative=".") -> str:
    """Hash regular payloads, including empty directories and executable bits.

    The default rejects nested links and special files. Opted-in POSIX directory
    links retain opaque identity under a separately supplied logical location;
    ordinary node hashes remain compatible with existing ownership.
    """
    if preserve_symlinks:
        from .payload_links import scan
        return scan(path, source_relative=source_relative, exclude_git=exclude_git)[0]
    digest = hashlib.sha256()

    def visit(current, relative):
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise Error(f"Payload symlinks/junctions are unsupported: {current}")
        kind = "d" if stat.S_ISDIR(info.st_mode) else "f" if stat.S_ISREG(info.st_mode) else None
        if kind is None:
            raise Error(f"Special files are unsupported: {current}")
        executable = info.st_mode & 0o111 if os.name != "nt" else 0
        digest.update(json.dumps([relative, kind, executable], ensure_ascii=True).encode() + b"\0")
        if kind == "d":
            for child in sorted(current.iterdir(), key=lambda p: p.name):
                if exclude_git and not relative and child.name == ".git":
                    continue
                visit(child, f"{relative}/{child.name}")
        else:
            file_hash = hashlib.sha256()
            with current.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    file_hash.update(block)
            digest.update(file_hash.digest())

    visit(path, "")
    return digest.hexdigest()


def link_matches(observed: dict, source: str) -> bool:
    """Compare desired link ownership without changing raw journal observations."""
    return observed.get("kind") == "link" and same_destination(observed.get("to"), source)


def observation(path: Path, **policy) -> dict:
    if path.is_symlink():
        return {"kind": "link", "to": os.readlink(path)}
    if not exists(path):
        return {"kind": "missing"}
    return {"kind": "directory" if path.is_dir() else "file", "hash": fingerprint(path, **policy)}


def copy_payload(source: Path, destination: Path, *, exclude_git: bool = False, **policy):
    if policy.get("preserve_symlinks"):
        from .payload_links import scan
        scan(source, destination=destination, exclude_git=exclude_git, **{k: v for k, v in policy.items() if k != "preserve_symlinks"})
        return
    fingerprint(source, exclude_git=exclude_git)
    if source.is_dir():
        # A repository-root skill can be installed directly, but detaching or
        # copying it must not clone Git administration data or a worktree link.
        def ignored(directory, names):
            return {".git"} if exclude_git and Path(directory) == source else set()
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

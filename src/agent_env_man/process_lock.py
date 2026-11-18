"""Standard-library OS locking shared with the out-of-environment updater."""

from contextlib import contextmanager
import errno
import fcntl
import json
import os
from pathlib import Path
import time

HOLDERS = "lock.holders"


@contextmanager
def lock(directory: Path, *, timeout: float = 0, error_type=RuntimeError, shared: bool = False,
         name: str = "configuration", holder=None):
    """Serialize managers, optionally waiting up to timeout seconds for contention.

    Shared locks admit concurrent readers while excluding writers.
    OS locks are released even after a crash; the persistent file is not a
    stale lock to delete. Ordinary commands retain immediate failure.
    A holder description, such as a command name without arguments, is recorded
    beside the lock so that contention can say what to wait for.
    """
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "lock").open("a+b") as stream:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(stream.fileno(), (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise error_type(f"Another process holds the AEM {name} lock: "
                                     f"{describe_holders(directory)}") from exc
                time.sleep(min(0.05, remaining))
        record = None
        try:
            record = _record(directory, holder, exclusive=not shared)
            yield
        finally:
            if record is not None:
                try:
                    record.unlink(missing_ok=True)
                except OSError:
                    pass
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _record(directory, holder, *, exclusive):
    """Write a best-effort holder record; diagnostics must never prevent locking."""
    records = directory / HOLDERS
    try:
        if exclusive and records.is_dir():
            # Holders write records only while locked and remove them before
            # unlocking, so under an exclusive lock every remaining record is stale.
            for path in records.iterdir():
                path.unlink(missing_ok=True)
        if holder is None:
            return None
        records.mkdir(exist_ok=True)
        pid = os.getpid()
        path = records / f"{pid}-{os.urandom(4).hex()}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"pid": pid, "holder": holder, "acquired": time.time()}), encoding="utf-8")
        os.replace(temporary, path)
        return path
    except OSError:
        return None


def describe_holders(directory: Path):
    """Describe current holders of directory's lock for a contention message.

    The kernel decides which processes hold the lock, so records left by a
    crashed holder are ignored. A holder without a record, such as a process
    from an earlier release, appears by process name rather than its command
    line, which may contain credentials.
    """
    records = {}
    try:
        for path in (directory / HOLDERS).glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data.get("holder"), str) and isinstance(data.get("acquired"), (int, float)):
                    pid = int(data["pid"])
                    # A reused PID may leave an older record; the newest one is current.
                    if pid not in records or data["acquired"] > records[pid]["acquired"]:
                        records[pid] = data
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue
    except OSError:
        pass
    pids = _kernel_holders(directory / "lock")
    if pids is None:
        # Without kernel ownership data, only records of live processes remain plausible.
        pids = sorted(pid for pid in records if _alive(pid))
    now = time.time()
    descriptions = [f"pid {pid} `{records[pid]['holder']}`, held for {_duration(now - records[pid]['acquired'])}"
                    if pid in records else f"pid {pid} ({_process_name(pid)})" for pid in pids]
    return "; ".join(descriptions) if descriptions else "holder unknown"


def _kernel_holders(path):
    """Return PIDs holding flock locks on path, or None when /proc/locks is unavailable."""
    try:
        status = path.stat()
        lines = Path("/proc/locks").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    identity = (os.major(status.st_dev), os.minor(status.st_dev), status.st_ino)
    holders = set()
    for line in lines:
        fields = line.split()
        # Waiters ("->") and POSIX/OFD record locks are not AEM's flock holders.
        if len(fields) < 6 or fields[1] != "FLOCK":
            continue
        try:
            major, minor, inode = fields[5].split(":")
            if (int(major, 16), int(minor, 16), int(inode)) == identity:
                holders.add(int(fields[4]))
        except ValueError:
            continue
    return sorted(holders)


def _duration(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{seconds // 60 % 60:02d}m"


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _process_name(pid):
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip() or "unknown process"
    except OSError:
        return "unknown process"

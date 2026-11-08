"""Standard-library OS locking shared with the out-of-environment updater."""

from contextlib import contextmanager
import errno
import fcntl
from pathlib import Path
import time


@contextmanager
def lock(directory: Path, *, timeout: float = 0, error_type=RuntimeError, shared: bool = False):
    """Serialize managers, optionally waiting up to timeout seconds for contention.

    Shared locks admit concurrent readers while excluding writers.
    OS locks are released even after a crash; the persistent file is not a
    stale lock to delete. Ordinary commands retain immediate failure.
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
                    raise error_type("Another aem command holds this config's lock") from exc
                time.sleep(min(0.05, remaining))
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

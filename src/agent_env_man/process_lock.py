"""Standard-library OS locking shared with the out-of-environment updater."""

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import time


@contextmanager
def lock(directory: Path, *, timeout: float = 0, error_type=RuntimeError, shared: bool = False):
    """Serialize managers, optionally waiting up to timeout seconds for contention.

    Shared readers are supported on POSIX; Windows retains exclusive locking.
    OS locks are released even after a crash; the persistent file is not a
    stale lock to delete. Ordinary commands retain immediate failure.
    """
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
        else:
            import fcntl
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
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
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


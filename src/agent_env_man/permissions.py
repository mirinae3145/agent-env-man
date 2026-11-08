"""Permission preservation is separate from payload equality and ownership."""

import errno
import hashlib
import json
import os

from .model import Error


def validate(value, location="permissions"):
    if not isinstance(value, str) or value not in ("strict", "best-effort"):
        raise Error(f"{location}: expected strict or best-effort")
    return value


def snapshot(path, *, node_types=None, **policy):
    """Observe native modes without following links or including exclusions.

    If supplied, node_types records "d"/"f" for the same included paths.
    """
    from .payload_links import scan
    result = {}
    scan(path, modes=result, node_types=node_types, modes_only=True, allow_symlinks=policy.get("preserve_symlinks", False),
         **{k: v for k, v in policy.items() if k != "preserve_symlinks"})
    return result


def digest(modes):
    return hashlib.sha256(json.dumps(modes, sort_keys=True).encode()).hexdigest()


def differences(requested, actual, failures=()):
    result = {path: {"path": path, "requested": wanted, "actual": actual.get(path)}
              for path, wanted in requested.items() if actual.get(path) != wanted}
    for failure in failures:
        path = failure["path"]
        result.setdefault(path, {"path": path, "requested": failure["requested"], "actual": actual.get(path)})["error"] = failure["error"]
    return [result[path] for path in sorted(result)]


def apply(target, wanted, *, path=".", failures=None):
    """Only unsupported/denied permission setters are optional, never I/O errors."""
    try:
        (os.fchmod if isinstance(target, int) else os.chmod)(target, wanted)
    except OSError as exc:
        if exc.errno not in {errno.EPERM, errno.EACCES, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
            raise
        if failures is not None:
            failures.append({"path": path, "requested": wanted, "error": str(exc)})

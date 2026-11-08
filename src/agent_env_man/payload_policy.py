"""Catalog exclusions and opaque retention of unowned payload entries."""

from functools import lru_cache
import fnmatch
import os
from pathlib import Path
import uuid

from .model import Error


def patterns(value, location='exclude'):
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(p, str) or not p or p.startswith(('/', '!')) or '\\' in p or ':' in p
        or any(part in ('', '.', '..') for part in p.split('/')) or '\0' in p
        or any('**' in part and part != '**' for part in p.split('/')) for p in value
    ):
        raise Error(f'{location}: expected relative /-separated glob paths without .., negation, or partial **')
    return tuple(dict.fromkeys(value))


def rules(value):
    if not isinstance(value, (list, tuple)):
        raise Error('Invalid saved payload exclusions')
    result = []
    for rule in value:
        if not isinstance(rule, (list, tuple)) or len(rule) != 2:
            raise Error('Invalid saved payload exclusion rule')
        prefix, pattern = rule
        if not isinstance(prefix, str) or (prefix and (prefix.startswith('/') or '\0' in prefix or '\\' in prefix
                or ':' in prefix or any(p in ('', '.', '..') for p in prefix.split('/')))):
            raise Error('Invalid saved payload exclusion prefix')
        patterns([pattern])
        result.append((prefix, pattern))
    return tuple(sorted(set(result)))


def effective(defaults, source, item, subdir):
    return rules([('', p) for p in defaults] + [(subdir if subdir != '.' else '', p) for p in source]
                 + [('', p) for p in item])


@lru_cache(maxsize=4096)
def match(path, pattern):
    """Anchor globs; ** matches zero or more whole path components."""
    parts, glob = tuple(path.split('/')), tuple(pattern.split('/'))
    @lru_cache(maxsize=None)
    def visit(i, j):
        if j == len(glob):
            return i == len(parts)
        if glob[j] == '**':
            return visit(i, j + 1) or (i < len(parts) and visit(i + 1, j))
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], glob[j]) and visit(i + 1, j + 1)
    return visit(0, 0)


def excluded(relative, exclusions=(), exclude_prefix=''):
    relative = relative.strip('/')
    if not relative:
        return False
    for prefix, pattern in exclusions:
        candidate = '/'.join(p for p in (prefix, exclude_prefix, relative) if p)
        # Excluding an ancestor excludes every descendant, even for a subtree scan.
        if any(match('/'.join(candidate.split('/')[:i]), pattern)
               for i in range(1, len(candidate.split('/')) + 1)):
            return True
    return False


def child_options(policy, name):
    result = dict(policy)
    if result.get('preserve_symlinks'):
        result['source_relative'] = str(Path(result['source_relative']) / name).replace('\\', '/')
    if result.get('exclusions'):
        result['exclude_prefix'] = '/'.join(p for p in (result.get('exclude_prefix', ''), name) if p)
    return result


def saved(policy):
    result = {}
    if policy.get("permissions") == "best-effort":
        result["permissions"] = "best-effort"
    if policy.get('preserve_symlinks'):
        result.update(preserve_symlinks=True, relative=policy['source_relative'])
    if policy.get('exclusions'):
        result['exclusions'] = [list(r) for r in policy['exclusions']]
        if policy.get('exclude_prefix'):
            result['exclude_prefix'] = policy['exclude_prefix']
    return result


def retained_paths(root, policy):
    """List excluded entries without opening them or following any link."""
    result = []
    def visit(directory, prefix=''):
        for child in sorted(directory.iterdir()):
            rel = '/'.join(p for p in (prefix, child.name) if p)
            if excluded(rel, policy.get('exclusions', ()), policy.get('exclude_prefix', '')):
                result.append(rel)
            elif not child.is_symlink() and child.is_dir():
                visit(child, rel)
    if not root.is_symlink() and root.is_dir():
        visit(root)
    return result


def checked_parent(root, relative):
    path = root
    if path.is_symlink() or not path.is_dir():
        raise Error(f'Cannot preserve excluded entry beneath removed or redirected directory: {relative}')
    for part in relative.split('/')[:-1]:
        path /= part
        if path.is_symlink() or not path.is_dir():
            raise Error(f'Cannot preserve excluded entry beneath removed or redirected directory: {relative}')
    return path


def preservation_paths(root, incoming, policy):
    """Validate excluded ancestors against the incoming tree, including previews."""
    paths = retained_paths(root, policy) if policy.get('exclusions') else []
    for rel in paths:
        checked_parent(incoming, rel)
    return paths


def retention(root, stage, policy):
    paths = preservation_paths(root, stage, policy)
    if not paths:
        return None
    for rel in paths:
        if os.path.lexists(stage / rel):
            raise Error(f'Excluded staging path unexpectedly exists: {rel}')
    vault = root.with_name('.aem-retained-' + uuid.uuid4().hex)
    return {'vault': str(vault), 'paths': paths}


def validate_retention(root, value, policy):
    if not isinstance(value, dict) or set(value) != {'vault', 'paths'}:
        raise Error('Invalid excluded-entry recovery record')
    if not isinstance(value['vault'], str):
        raise Error('Invalid excluded-entry recovery storage')
    vault = Path(value['vault'])
    if vault.parent != root.parent or not vault.name.startswith('.aem-retained-') or vault.is_symlink():
        raise Error('Invalid excluded-entry recovery storage')
    paths = value['paths']
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths) or len(set(paths)) != len(paths):
        raise Error('Invalid excluded-entry recovery paths')
    for rel in paths:
        if not isinstance(rel, str) or any(p in ('', '.', '..') for p in rel.split('/')) or '\\' in rel or ':' in rel:
            raise Error('Invalid excluded-entry recovery path')
        if not excluded(rel, policy.get('exclusions', ()), policy.get('exclude_prefix', '')):
            raise Error('Recovery retention path is not excluded')
        if any(other != rel and rel.startswith(other + '/') for other in paths):
            raise Error('Overlapping excluded-entry recovery paths')
    return vault, paths


def park(root, value, policy):
    """Move unowned entries into same-filesystem storage, retaining their identity."""
    # Included-content hashes deliberately ignore metadata. A new excluded entry
    # since preflight must therefore stop replacement even if no vault was planned.
    planned = value['paths'] if value else []
    if policy.get('exclusions') and set(retained_paths(root, policy)) - set(planned):
        raise Error('Excluded entries changed before replacement; retry after inspection')
    if not value:
        return
    vault, paths = validate_retention(root, value, policy)
    vault.mkdir(exist_ok=True)
    for i, rel in enumerate(paths):
        slot = vault / str(i)
        if os.path.lexists(slot):
            if os.path.lexists(root / rel):
                raise Error(f'Excluded entry exists at both recovery locations: {rel}')
            continue
        checked_parent(root, rel)
        if not os.path.lexists(root / rel):
            raise Error(f'Excluded entry disappeared before preservation: {rel}')
        from .payload_links import replace
        (replace if policy.get('preserve_symlinks') else os.replace)(root / rel, slot)
    if retained_paths(root, policy):
        raise Error('Excluded entries changed during preservation; retry after inspection')


def restore_retained(root, value, policy):
    if not value:
        return
    vault, paths = validate_retention(root, value, policy)
    for i, rel in enumerate(paths):
        slot = vault / str(i)
        if not os.path.lexists(slot):
            if not os.path.lexists(root / rel):
                raise Error(f'Excluded entry missing during recovery: {rel}')
            continue
        checked_parent(root, rel)
        if os.path.lexists(root / rel):
            raise Error(f'Excluded entry would be overwritten during recovery: {rel}')
        from .payload_links import replace
        (replace if policy.get('preserve_symlinks') else os.replace)(slot, root / rel)
    if vault.exists():
        vault.rmdir()

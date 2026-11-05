#!/usr/bin/env python3
"""Check Markdown structure with the mddt checker and report findings for review.

Errors fail the check across the whole tree, because a change can break links in
files it did not touch. Warnings call for a writer's judgment, so only those in
files changed since the base revision are reported.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def changed_files(base):
    """Return repository-relative paths changed between base and HEAD."""
    result = subprocess.run(
        ['git', 'diff', '--name-only', '--diff-filter=d', base, 'HEAD'],
        cwd=ROOT, check=True, capture_output=True, text=True)
    return set(result.stdout.splitlines())


def selected(diagnostics, changed):
    """Keep every error and the warnings in changed files (all when changed is None)."""
    return [item for item in diagnostics
            if item['severity'] == 'error' or changed is None or item['file'] in changed]


def escape_data(value):
    return value.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


def escape_property(value):
    return escape_data(value).replace(':', '%3A').replace(',', '%2C')


def format_finding(item, github):
    if github:
        level = 'error' if item['severity'] == 'error' else 'warning'
        properties = ','.join([
            f"file={escape_property(item['file'])}",
            f"line={item['line']}",
            f"endLine={item.get('endLine') or item['line']}",
            f"title={escape_property('mddt ' + item['code'])}",
        ])
        return f'::{level} {properties}::{escape_data(item["message"])}'
    return f"{item['file']}:{item['line']}: {item['severity']} {item['code']}: {item['message']}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--mddt', required=True, type=Path,
                        help='path to the mddt checker script (skills/mddt/scripts/mddt.py)')
    parser.add_argument('--base', help='report warnings only for files changed since this revision')
    arguments = parser.parse_args()

    result = subprocess.run(
        ['uv', 'run', '--quiet', str(arguments.mddt.resolve()), '--format', 'json', '.'],
        cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    if result.returncode not in (0, 1):
        sys.stderr.write(result.stderr)
        raise SystemExit(f'mddt checker failed with status {result.returncode}')
    report = json.loads(result.stdout)

    changed = changed_files(arguments.base) if arguments.base else None
    findings = selected(report['diagnostics'], changed)
    github = os.environ.get('GITHUB_ACTIONS') == 'true'
    for item in findings:
        print(format_finding(item, github))

    errors = sum(item['severity'] == 'error' for item in findings)
    warnings = len(findings) - errors
    scope = f'files changed since {arguments.base}' if changed is not None else 'all files'
    summary = (f"mddt: {len(report['files'])} files checked; {errors} error(s); "
               f'{warnings} warning(s) reported for {scope}')
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as handle:
            handle.write(f'### Document structure\n\n{summary}\n')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())

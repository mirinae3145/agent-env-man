# Measure and interpret coverage

Run the ordinary test suite under coverage.py from the repository root in the activated development environment.
The configuration measures statements and branches in `src/` and `scripts/`, including the build hook and standalone installer.
Python subprocesses are also measured; combine their data before generating reports.

```bash
python -m coverage erase
python -m coverage run -m unittest discover -s tests -v
python -m coverage combine
python -m coverage report
python -m coverage html
python -m coverage json
```

Check the test command's exit status before treating a report as a successful baseline.
Reports from a failed run may help diagnosis but do not establish successful validation.
The terminal report shows missing lines and branch destinations; `htmlcov/index.html` provides file-level detail and `coverage.json` contains machine-readable results.

Coverage data and reports are ignored local artifacts.
CI source jobs report coverage without a minimum threshold, and no hook enforces it.
Keep coverage.py's default exclusions; do not exclude whole files to improve the percentage.

## Interpret coverage results

Review unmeasured failure, recovery, and platform paths for meaningful behavior tests before choosing a minimum threshold.
Record the source revision, environment, test outcomes and skips, statement and branch coverage, and combined percentage with validation results.
Do not embed changing baselines in this guidance.
Linux/WSL measurement does not establish coverage of Windows-only behavior.

The same commands work with the native Windows environment's Python, but report its results separately.
Workers copied into temporary request directories are outside the configured source roots; subprocess measurement does not map those copies back to their originals.
Test the original worker's policy, failure, and continuation behavior separately from copied-worker lifetime integration.
Mocked Windows API tests check branching and resource handling; they do not establish native Windows lock or process behavior.

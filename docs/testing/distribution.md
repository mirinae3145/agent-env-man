# Verify installed distributions

Use separate build and runtime environments to verify installation, dependency isolation, and packaged resources.

## Installation and dependency boundaries

Base installation supports ordinary AEM use; the `dev` extra supports contribution work and the full test suite.
Both installations must have identical command behavior, configuration defaults, and automation policy.
Installing either package does not register shell or agent integrations; `aem setup` owns those explicit changes.
The repository installer combines package installation and requested setup as a user-facing workflow.

### Runtime dependency isolation

Runtime commands must not import development or build tools.
Build-system requirements provision isolated package builds independently of the `dev` extra; setuptools in `dev` supports source build-hook tests.
Keep the standalone installer and copied worker standard-library-only, and verify them with Python site packages disabled.

### Installed distribution checks

Source tests in an editable development environment and verification of an installed distribution are separate acceptance checks.
For packaging or dependency changes, also install a built wheel without extras into a fresh environment with neither coverage.py nor setuptools, and run the runtime verifier from the checkout:

```bash
python -m venv --without-pip /path/to/runtime-venv
python -m pip --python /path/to/runtime-venv install /path/to/agent_env_man-VERSION-py3-none-any.whl
python scripts/verify_runtime.py --python /path/to/runtime-venv/bin/python
```

Use a separate temporary environment; on Windows pass its `Scripts/python.exe` to the verifier.
The pip installation command uses the development environment's pip to install only the wheel and its runtime dependencies into the target environment.
Package acquisition may require network access; verification itself uses only temporary local Git repositories and never registers integrations.
The verifier rejects editable installations and environments containing development dependencies, disables Python source-path inheritance, and checks installed CLI help, local documentation, and bootstrap/apply/status/detach behavior.
It also exercises TOML and JSON settings reception, stage editing, application, export, local Git publication, conflict preservation, and detach through the installed CLI.
Verify both a direct wheel and a wheel rebuilt from the sdist as required by the installed-documentation contract in [Documentation authoring](../documentation-authoring.md#installed-documentation).

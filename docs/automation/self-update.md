# Update AEM itself

Inspect the installed tool, choose a permitted release range, and preview an update before queuing it.
Automatic tool updates are configured independently of content policies.

1. Inspect `aem self status` for the installed version, saved mode, and last attempt.
1. Choose the release permission using the [release selection reference](releases.md).
   `compatible` is the default for explicit updates; `--mode breaking` permits a newer incompatible release for that attempt.
1. Preview with `aem self update --dry-run`, then run `aem self update` with the selected mode.
1. Check `aem self status` again for the eventual worker result.

For automatic updates, the installer can register the runtime and mode with `python scripts/setup.py --shell bash --agent codex --self-update compatible`.
Use `aem setup --self-update off` to disable automatic tool updates without disabling explicit updates.

## Scheduling and completion

In `policies` mode with tool updates enabled, the existing startup callback queues at most one attempt per day across shell and agent events; failures are throttled too.
It works without a bound content catalog.
The worker waits for the requesting AEM process to exit, then uses the installer's external Python rather than the environment being replaced.
The saved external Python and uv executables must remain available; rerun the installer if they move.
A queued result means the attempt has been scheduled, not completed; use `aem self status` for the eventual result.
Explicit updates bypass the daily throttle and work even with automatic updates off.
Content updates, catalog delivery, instruction location callbacks, and `auto` do not update AEM itself.
No daemon or OS scheduler is installed.

## Replacement and repair

Self-updates coordinate registered AEM commands sharing the same uv tools directory.
Remote release discovery and metadata validation release the installation and configuration locks, so other commands can run during that preparation.
Before replacement, the worker reacquires the locks and rechecks the request, policies, recovery state, owned official skills, and installed version.
If another update changed the installed version during preparation, the attempt is cancelled; an explicit `aem self update` can retry.
Commands can report lock contention during replacement; startup remains fail-open.
Other package-manager processes and external editors are not covered by these locks.
A failed uv replacement is reported without a rollback guarantee; rerun `scripts/setup.py` to repair the installation if AEM cannot start.
Native Windows worker/replacement and actual agent hook continuity require platform validation.

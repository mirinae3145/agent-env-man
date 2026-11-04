# Automation configuration

Machine automation fields control tool releases, catalog reception, and device orchestration.
They are independent of the catalog skill policies and per-setting schedules.

## Agent startup hook duration

Machine `[setup].startup_hook_timeout` is a finite positive integer or float in seconds, defaulting to `10`; Boolean values are invalid.
Set it with `aem setup --startup-hook-timeout 60` or `python scripts/setup.py --startup-hook-timeout 60`.
Setup updates the registered Codex and Claude startup hooks and preserves the saved value when the option is omitted.
It can also save the value before agents are registered.
Codex requires an unsigned integer timeout: its generated hook rounds fractional seconds up (for example, `65.5` becomes `66`) and rejects values at or above `2**64`.
Claude retains the configured fractional value.
Instruction-location hooks retain their ten-second limit, and shell callbacks have no corresponding agent hook limit.
Git policy `timeout` fields remain independent; in policies mode, all synchronous startup work must fit within the outer agent limit.
In full mode, the callback queues the update sequence for execution after it exits.

## AEM self-update settings

This policy belongs to the machine, independently of the content catalog and skill update policies.
The installer records runtime paths; manage the mode with `aem setup --self-update MODE`.
An omitted field on subsequent setup/installer calls retains its saved value.
Unknown fields are rejected.

### Policy fields

| Field | Type | Meaning/default |
| --- | --- | --- |
| `mode` | String | `off` (default), `compatible`, or `breaking`. |
| `repository` | String | Release Git repository; defaults to `https://github.com/mirinae3145/agent-env-man.git`. Supports HTTPS, SSH, and absolute local paths. |
| `python` | Absolute path string | External Python 3.11+ used by the standalone worker and uv installation. Must be outside the uv tools directory, including resolved symlink locations. |
| `uv` | Absolute path string | Installer-discovered uv executable. |
| `tool_dir` | Absolute path string | Installer-discovered uv tools directory; also identifies the shared installation lock. |
| `bin_dir` | Absolute path string | Installer-discovered executable directory; passed to uv to preserve executable locations. |

### Runtime and release selection

All four runtime paths are required when enabling automatic updates or requesting an explicit update.
For final releases from `1.0.0` onward, `compatible` permits the same major.
For a prerelease, `compatible` permits only a higher numeric subversion with the same base `X.Y.Z` and the same `a`, `b`, or `rc` label (for example, `1.0.0rc1` to `1.0.0rc2`).
Changing the label, base version, or moving to a final release requires `breaking`.
Final installations retain their existing compatible range and do not select prereleases in `compatible` mode.
`breaking` permits any newer final or `a`/`b`/`rc` prerelease.
Release tags use `vVERSION` in Python notation or supported SemVer-style `-alpha`/`-beta`/`-rc` notation with an optional `.N` number.
Tag conversion and omitted-zero normalization must match the Python package version.
Development, post, local versions, and untagged commits are excluded.
See [version syntax and ordering](../automation/self-update.md).
Attempts share a fixed 86,400-second interval across startup events and are recorded before launching the worker.
An explicit update bypasses the interval and can override the mode for that attempt without changing the saved policy.
Existing machine files remain usable with self-updates disabled until runtime registration through the installer.

## Catalog automatic update settings

The machine-owned `catalog_update` table controls the bound Git catalog, without relying on policies inside the file it updates.
Manage it with `bootstrap` during registration or `setup` afterward: repeat `--catalog-trigger` for events, set `--catalog-interval` for `min_interval`, and use `--catalog-git-timeout` for `timeout`.
Supplied triggers replace the saved list; omitted options retain their existing fields.
`--catalog-trigger manual` disables automatic catalog updates.
Policy-only setup supports `--dry-run`, requires no integration selections or executable, and does not rewrite existing profiles.
Omission leaves catalog delivery manual.
Unknown fields are rejected, and an enabled event policy requires a Git catalog binding; local catalogs remain externally managed.

### Catalog policy fields

| Field | Type | Default/meaning |
| --- | --- | --- |
| `trigger` | String or array of strings | `"manual"`; alternatively one or more unique `shell-start`, `agent-start`, or `interval` events. `manual` cannot be combined with events. |
| `min_interval` | Integer or float | `3600` seconds; finite and nonnegative. One clock shared across events for the repository/branch/entry binding. |
| `timeout` | Integer or float | `5` seconds per Git phase; finite and positive. |

### Catalog attempts

Boolean numeric values are rejected.
There is no action field: catalog automation always performs the existing validated fast-forward update, without bootstrapping or applying declarations.
Attempts are persisted before remote access and failures are throttled too.
A changed repository, branch, or entry binding starts a separate attempt clock.
Explicit catalog update/publication commands do not consult or reset this clock.
The policy does not register startup hooks or an OS scheduler; use setup's existing callback or invoke `catalog auto` externally.

## Device automation settings

Manage the machine-owned `automation` table through installer/setup options.
Use `--automation MODE`, repeated `--automation-trigger EVENT`, `--automation-interval SECONDS`, and `--automation-git-timeout SECONDS`.
Use `--automation-skip-unsupported` or `--no-automation-skip-unsupported` to save the full-mode platform exclusion policy.
Omitted fields retain saved values; a supplied trigger list replaces the saved list.
Policy-only setup uses the machine journal and does not rewrite profiles or require integration selections.
Unknown fields are rejected.

### Device policy fields

| Field | Type | Default/meaning |
| --- | --- | --- |
| `mode` | String | `policies` (default), `off`, or `full`. |
| `trigger` | String or array of strings | Defaults to `shell-start` and `agent-start`. May contain unique supported events or only `manual`. Used in full mode. |
| `min_interval` | Integer or float | `3600` seconds, finite and nonnegative; full runs share one clock across events, including failures. |
| `timeout` | Integer or float | `30` seconds per content/catalog Git phase, finite and positive; used in full mode. |
| `skip_unsupported` | Boolean | `false`; explicitly exclude platform-unsupported items from full content selection and report their reasons. Stored but inactive in other modes. |

Boolean numeric values are rejected.
`policies` retains the independent self-update, catalog-update, and skill policies and their clocks.
`off` disables all event-driven automatic entrypoints while leaving explicit commands available.
`full` uses the shared schedule, without consulting or modifying individual attempt clocks.
Its tool stage retains the self-update release permission (`off`, `compatible`, or `breaking`); the copied worker uses the existing 300-second tool subprocess bounds.
Full mode requires installer-registered runtime paths even when tool updates are off.

### Full-mode eligibility and cancellation

In full mode the implicit skill/directory trigger default becomes eligible for the full run, while explicitly declared trigger fields keep the existing precedence.
A resulting explicit or inherited `[]` excludes a skill or directory; other trigger lists and per-item actions/intervals are replaced by the full-run schedule and prepare/update/apply behavior.
Instruction groups with detached components are excluded together; remaining bundles participate without introducing instruction-specific policy tables.
A shared repository can still advance live links of excluded consumers.
Local or unbound catalogs skip Git delivery and use the existing local declarations.
Mode, schedule, exclusion-policy, or runtime changes cancel queued work; the fresh continuation also verifies the saved request binding before advancing content.


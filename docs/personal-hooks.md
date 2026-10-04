# Personal command hooks

AEM prepares user-authored scripts and registers explicitly selected native command
hook groups. Codex or Claude Code executes the scripts, using its own event JSON,
stdout/stderr and exit-code contract. AEM never executes the scripts or installs
runtimes, plugins or authentication. Product trust remains a separate user action.

## Prepare and register

Declare a named source and one binding per selected product:

```toml
version = 2

[sources.logger]
type = "git"
repository = "https://example.com/owner/session-logger.git"

[hooks.session-log]
source = "logger"

[hooks.session-log.agents.codex]
event = "SessionEnd"
runtime = "python"
script = "bin/session-logger"
args = ["hook", "codex"]
timeout = 3

[hooks.session-log.agents.claude]
event = "SessionEnd"
runtime = "python"
script = "bin/session-logger"
args = ["hook", "claude"]
timeout = 3
```

Bind the interpreter on each device and explicitly select the registration:

```bash
aem bootstrap /absolute/catalog.toml --runtime python=/absolute/python
aem apply --item session-log --dry-run
aem apply --item session-log
```

The machine's existing agent bindings select product roots. Without agent
bindings, only Codex is selected, using `roots.agent`.
An external source uses `type = "external"` and a bootstrap
`--external logger=/absolute/prepared-source` binding instead of a Git URL.
A common script must implement both products' contracts itself; AEM does not
translate event payloads or discover hooks inside skills or plugins.

Bootstrap validates and prepares without registration. Plain `apply`, plain
`sync`, and automatic full runs exclude personal registrations. An explicitly
selected `sync --item session-log` can register after updating all sources.
An explicit apply never approves Codex trust; review the concrete command using
its native `/hooks` interface.

## Live sources and ownership

The registered command points directly at the prepared source script. Updating a
shared Git checkout or external source can change its behavior immediately, even
without apply. Changing event, arguments, interpreter binding, timeout or matcher
requires selected apply to change the installed definition. AEM's stable command
identity is a silent prefix outside script arguments; it does not authenticate
script contents or freeze revisions. Native trust in a command definition must
not be confused with a content signature.

AEM owns one complete group per resource and agent, rather than the entire JSON
file. Other groups, events and unrelated preferences survive application and
removal. Claude preferences and hook groups can share one file; a settings owner
cannot claim the `hooks` field. Multiple selected groups for one file preflight
together and commit one replacement. When settings share that file, the combined
image and comparison records use the existing grouped settings journal.
Transactions remain per target; an earlier successful target can remain after a
later target fails.

Locally edited, missing or duplicate owned groups block normal apply and removal.
Explicit selected `--replace` follows existing backup and recovery rules.
Matching unowned groups require selected `--adopt`; target relocation requires
detach. An event move removes the unchanged saved group and adds its replacement
within one target transaction.

```bash
aem status
aem locate session-log --agent codex
aem hooks remove session-log --agent codex --dry-run
aem hooks remove session-log --agent codex
```

Removal uses saved ownership and remains available without the catalog, source,
runtime or current profile. Omitting `--agent` removes all saved registrations
for the selected name. Removal releases ownership; explicit
`apply --item session-log --reattach` is required to install again.
`detach session-log` retains registrations and releases ownership without copying
scripts or removing groups. Detached scripts remain dependent on their original
source/runtime; preserve those paths or manage the retained group yourself.
Removing a declaration never removes its installed group. Active Git scripts
remain guarded against removal/type changes even when another shared consumer
initiates update after the hook declaration disappears. Recovery preserves later
user edits and stops rather than guessing ownership.

See [Configuration](configuration.md#personal-hook-declarations-and-runtime-bindings)
for supported fields and events, [Commands](commands.md#hooks-remove) for selection,
and [Maintenance](maintenance.md) for backups and recovery.

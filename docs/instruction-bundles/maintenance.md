# Maintain an instruction installation

Use this guide to understand source changes, detach an instruction installation, and preserve existing destinations during an upgrade.

## Changes, missing sources, and management removal

Source edits and management changes have different effects on linked instructions.

| Action or event | Links and hook behavior |
| --- | --- |
| Edit `guidance/development/conventions.md` externally | The installed path sees the edit immediately through the link. No apply is needed. Status reports a live content change relative to the last apply. |
| Run `update personal` for the external source | AEM checks that the external root exists and reports `external-no-fetch`. It does not run Syncthing or restore documents. |
| Delete an auxiliary document | That installed document disappears too. AEM does not detect broken prose references; the remaining bundle can still be valid. |
| Remove `guidance/start.md` | Apply cannot validate the entry, and status reports the bundle unavailable. The directory link remains and the global entry link breaks; the hook reports lookup failure. |
| Remove or temporarily disconnect the whole external source | Both installed links break and the registered hook reports lookup failure. Restore the source before detaching so AEM can preserve its contents. |
| Delete `[instructions.personal]` from the catalog | Existing targets and ownership remain. This is not an uninstall command. |
| Write through the global AGENTS.md link | The original entry changes immediately. Replace the link with a regular file to keep a separate local edit; apply then reports a conflict. |
| Detach bundle and entry | AEM materializes both links, releases their ownership and the associated hook ownership, and retains hook configuration for continued root discovery. |
| Edit/remove an owned AEM hook group | Ordinary apply reports a conflict. Explicit replacement restores the owned groups and preserves other hooks. |

## Existing installations

Explicit `install.bundle.root` and `install.bundle.destination` settings remain supported; retaining their values avoids relocating an existing installation.
For example, `install.bundle.root = "rules"`, `install.bundle.destination = "personal"`, and machine `roots.rules = "/home/me/.agent-rules"` retain the earlier destination.
Removing those fields from an installed bundle can change its target path, so detach and deliberately reattach if you want to move to the default.
For old catalogs, follow the [catalog v2 transition](../removed-interfaces.md#catalog-v2-transition).
Older state and generated-guide installations are not upgraded in place; follow [Removed interfaces](../removed-interfaces.md) before installing the current version.

## Detach the bundle and entry

To detach the example:

```bash
aem detach personal:bundle personal:entry
```

### State after detaching

The same locator command now returns `/home/me/.config/agent-env-man/machine.toml.bundles/personal` as `root` and its `start.md` as `entry`, with `detached: true`.
It uses the saved installation record even if the catalog or original source is gone.
Later edits in the external source no longer affect this copy.

### Reattachment and the retained hook

Ordinary apply skips all detached items; explicit reattachment is needed to manage them again.
Detach preserves instructions and the registered hook for continued use; it does not disable them or restore a global AGENTS.md from before installation.
Disable the retained hook through Codex `/hooks` if you no longer want it to execute.

### Item selection

`bootstrap --item personal` selects the whole source for preparation.
`apply --item personal:entry` includes the bundle and hook automatically; explicit `personal:hook` selection also includes both links.
`personal:bundle` alone installs only the directory link for staged preparation.
Detach uses the two link ownership IDs without `--item` and includes the saved hook record automatically when detaching the entry.

### Failures, replacement, and partial detach

Transactions are per target, so links and hook configuration are not one atomic installation.
If hook installation fails after the links were installed, recovery restores the previous hook file; retry apply after fixing the error.
For an existing global entry, use `apply --item personal:entry --replace`; also select `personal:bundle` if an existing bundle destination intentionally needs replacement.
An implicitly selected bundle never gains replacement permission.
If you detach only the directory while leaving the global entry linked, the hook continues to report the live original root for that entry; detach both links for an independent local copy.

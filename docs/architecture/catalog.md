# Catalog delivery contracts

Preserve compatibility for local catalog path strings, and keep Git and explicit local copy bindings in machine configuration.

## Local copy bindings

A local copy binding separates the external original from the managed file always consumed by catalog readers.
Keep its common content hash and binding in separate `catalog_copy` state, never content ownership or Git observations.
Initial registration and rebinding validate candidates before journaling the managed file and machine binding together.
Reuse an existing binding without reading the original; refresh and reverse publication are explicit.

Local update and publication use a common baseline, preserve one-sided edits in the opposite direction, and refuse competing changes.
Only `catalog publish --from-copy` writes the external original; require an existing regular file and never invoke its synchronization service.
Use grouped file recovery with input observations and separate baseline updates; recovery must work without parsing the catalog.
Reject redirected paths, overlapping storage/targets, unmanaged copy replacement, and rebinding over copy edits.

## Bootstrap and checkout separation

Bootstrap accepts the catalog repository, relative entry path, and optional branch without requiring a hand-written machine file; persist the resolved branch for subsequent operations.
Catalog delivery precedes content delivery and must not depend on declarations inside the catalog itself.
Use a separate checkout even when catalog and content share a remote, so content updates cannot implicitly change the inventory or automatic policies.
Do not merge checkout identities by URL.

## Candidate validation

Preparing a missing Git catalog checkout is the explicit exception to declaration validation before network access.
Clone it to temporary storage.
Validate its tracked regular UTF-8 entry, declarations, machine bindings, and existing ownership before publishing the checkout or saving the binding.

Content repositories must remain untouched until preflight succeeds.
Validate candidate revisions against final machine paths without temporarily changing the active binding or checkout.
Catalog updates fast-forward only after the candidate passes the same declaration and ownership checks.
Preserve the old catalog on validation failure, local edits on delivery failure, and installed ownership when declarations disappear.
Do not reset mismatching checkouts on rebind.

## Catalog automation boundaries

Explicit catalog update/publication and separately opted-in catalog automation may contact an existing catalog's remote.

### Policy configuration

Keep catalog automation policy in machine configuration, outside the file it updates.
Default to manual, and require a Git binding when automation is enabled.
Expose trigger/interval/timeout selection through bootstrap and setup, preserving omitted fields and replacing explicitly supplied trigger lists.
Validate supplied policies before network access or saving configuration.
Policy-only setup must use the machine configuration journal without requiring an executable, registering integrations, or rewriting profiles.

### Attempt clocks and startup ordering

Use the same candidate validation and fast-forward safeguards as explicit catalog update, without bootstrapping or applying declarations.
Persist a separate attempt clock before remote access, throttle failed attempts across events, and reset the effective clock on a changed repository/branch/entry binding.
Explicit catalog operations ignore this clock, and automatic previews remain offline without recording attempts.
In `policies` mode, startup must run due catalog work before resolving skill policies and reload successfully updated declarations.
A failed catalog attempt must skip skill work for that event while allowing startup to continue.

### Independence from content operations

Ordinary content update, sync, skill automatic policies, and refreshed content status must not fetch or advance the catalog.
Keep catalog inspection/location offline and usable for repairing malformed catalog contents, and retain catalog-independent maintenance paths.
Catalog publication selects the whole repository and follows the existing publication contracts; it never installs declarations or changes content attempt clocks.
Keep catalog delivery observations separate from item/source names and protect the whole catalog checkout from targets and external sources.

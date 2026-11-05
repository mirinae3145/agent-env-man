# Personal instruction bundles

An instruction bundle keeps an entry document and its referenced guidance together for installation into an agent profile.
AEM delivers the files and supplies reading locations; the documents determine their own applicability and reading order.
The [configuration reference](configuration/instructions.md) and [command reference](commands.md) define the public interfaces.

## Three things to keep separate

A bundle installation involves these three parts, each with its own owner.

| Part | What it contains | Who manages it |
| --- | --- | --- |
| Original documents | Your entry document, development/research/workspace guidance, and references | You; optionally an external synchronization service |
| Shared catalog | Which bundle to use, its entry file, and logical installation destinations | You; the same declaration can be used on different devices |
| Machine configuration | Where this device keeps the catalog, external folders, checkouts, and installation roots | You; paths can differ on each device |

## What AEM does with them

AEM reads the two TOML files, chooses the bundle installation directory, and links the document tree and original entry.
It registers Codex SessionStart and SubagentStart hooks for session and child-agent reading locations.
The hook discovers the actual bundle root and original entry file using AEM's local locator; it supplies path metadata to Codex without embedding commands or changing the original document.
It does not supply the personal instructions or decide when development, research, or workspace guidance applies.

## Install a bundle

The [external bundle walkthrough](instruction-bundles/install.md) starts with an existing source folder, registers a shared catalog, and installs linked instructions on Linux/WSL.
Skills are optional and are not a prerequisite for instructions.
The [installation variants](instruction-bundles/variants.md) adapt that example for Windows, Git sources, accompanying skills, and separate or shared offline copies.

## Inspect and maintain

The [hook and reading-location reference](instruction-bundles/locations.md) explains trust, generated hook groups, metadata fields, relative references, and lookup failures.
The [instruction maintenance guide](instruction-bundles/maintenance.md) covers source changes, detach, and existing-installation precautions.

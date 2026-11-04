# AEM documentation

These guides describe installing, operating, and contributing to Agent Environment Manager.
Start with the [project README](../README.md) for installation and a minimal catalog, then choose the guide for your task.
Commands and configuration references define the public interfaces; workflow guides explain how to use them together.

## Install and operate

Use these guides for complete workflows and their preservation boundaries.

- [Instruction bundles](instruction-bundles.md) walks through preparing and installing personal instructions on Linux/WSL and Windows.
- [Staged application settings](settings-management.md) explains how to receive, edit, apply, and share selected TOML or JSON fields.
- [Automation and AEM updates](automation.md) covers device modes, tool updates, and independent content policies.
- [Personal command hooks](personal-hooks.md) covers preparing, registering, and maintaining user-authored agent scripts.
- [Maintenance and recovery](maintenance.md) covers conflicts, detach, backups, recovery, and removal.

## Look up a contract

Use these references when you need exact syntax, fields, or compatibility boundaries.

- [Command reference](commands.md) introduces command groups and their selection, output, and failure contracts.
- [TOML configuration reference](configuration.md) introduces catalog declarations, machine bindings, and policy fields.
- [Compatibility policy](compatibility.md) defines public interfaces, release classification, and supported format generations.
- [Removed interfaces and existing installations](removed-interfaces.md) identifies obsolete interfaces and precautions before upgrading an existing installation.

## Develop and maintain AEM

Start with [Contributing](https://github.com/mirinae3145/agent-env-man/blob/master/CONTRIBUTING.md) for development setup and contribution decisions.
These local guides describe the contracts and checks relevant to a change.

- [Architecture and preservation contracts](architecture.md) introduces delivery, installation, ownership, and integration responsibilities.
- [Agent profile contracts](agent-profiles.md) defines the internal product extension boundary and supported profile behavior.
- [Testing and distribution verification](testing.md) explains how to select and run environment, packaging, and integration checks.
- [Documentation authoring](documentation-authoring.md) defines the roles of guides, CLI help, installed resources, and the official operations skill.

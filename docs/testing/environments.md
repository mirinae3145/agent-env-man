# Test environment contracts

These rules guide portable fixtures and the evidence needed for claims about Linux and WSL.

## Writing for multiple execution environments

Consider supported environments while designing the change, even when only one is available for execution.
For affected behavior, identify relevant differences between Linux and WSL mounted filesystems, shell invocation, interactive terminals and redirected input, and editable versus installed or copied-worker execution.
Do not require every environment for every change; select the relevant dimensions and checks according to the affected contract.

- **Serialized paths**: Treat filesystem paths and serialized representations as different values.
  Parse JSON before comparing path values, and decode encoded commands before checking their arguments.
  Assert exact bytes or quoting when serialization or byte preservation is the contract, with expectations appropriate to the platform.
- **Filesystem behavior**: Account for drive and UNC paths, separators, case behavior, symlink/reparse capabilities, permissions, line endings, and non-ASCII or shell-sensitive characters where they affect the change.
  Do not normalize away distinctions that ownership, identity, or preservation checks rely on.
- **Fixture isolation**: Make test prerequisites explicit rather than inheriting the developer's machine state.
  Control home/configuration locations, relevant environment variables, executable discovery, working directory, TTY detection, and input responses when they influence the behavior under test.
  An unattended-flow test should fail if input is requested; interactive-flow tests should supply their expected responses.
- **Process creation**: Use platform-appropriate fake executables and subprocess invocation.
  A POSIX shebang is not a portable executable fixture, and successful command serialization does not establish execution or exit-code propagation in the target shell.
  Keep portable policy and output checks runnable everywhere; isolate native process, shell, and filesystem checks behind explicit capability requirements.
- **Preservation**: Exercise both success and failure behavior, especially preservation of user files, unrelated configuration, and saved ownership when an operation cannot proceed.
  A platform limitation should skip only checks requiring that capability, not portable validation of the corresponding error or refusal path.

When another relevant environment is unavailable, review its code paths and fixture assumptions and run the meaningful checks available locally.
Record the environments actually exercised, skipped capabilities, and remaining uncertainty with the change's validation results.
Mocks and static review support portability reasoning but do not establish native readiness; retain that distinction in compatibility claims.

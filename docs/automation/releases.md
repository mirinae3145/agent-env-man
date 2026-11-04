# Release selection reference

This reference defines allowed update ranges and how release tags match Python package versions.

## Allowed release ranges

For final releases from `1.0.0` onward, `compatible` permits newer final releases in the same major version.
For a prerelease, `compatible` permits only a higher numeric subversion with the same base `X.Y.Z` and the same `a`, `b`, or `rc` label (for example, `1.0.0rc1` to `1.0.0rc2`).
Changing the label, base version, or moving to a final release requires `breaking`.
This permission also gates the first stable release: `1.0.0rc0` to `1.0.0` requires `breaking`, without implying a `2.0.0` version requirement.
Same-series subversion releases must preserve compatibility because existing `compatible` installations can select them automatically.
Final installations retain their existing compatible range and do not select prereleases in `compatible` mode.
`breaking` permits any newer final or prerelease version, including incompatible changes; review migration instructions before enabling it.
## Version syntax and ordering

Supported prereleases use Python package notation `X.Y.ZaN`, `X.Y.ZbN`, or `X.Y.ZrcN`, with an optional nonnegative numeric subversion without leading zeroes.
An omitted number is `0`: `1.0.0rc` and `1.0.0rc0` are equivalent, and `1.0.0rc1` is their next compatible release.
Git tags may also use `vX.Y.Z-alpha`, `vX.Y.Z-beta`, or `vX.Y.Z-rc`, with an optional `.N` number (for example, `v1.0.0-beta.1` maps to package version `1.0.0b1`).
Bare `v1.0.0-beta` maps to `1.0.0b0`; package metadata and installed versions continue to use Python notation.
When equivalent tags coexist, update selection prefers Python notation, then an explicit-zero spelling, and resolves annotated tags to their commits.
A release may start at any supported label; earlier phases need not exist.
Tag and package metadata comparisons accept the same omitted-zero equivalence.
Ordering is numeric by base version, then `a` < `b` < `rc` < final, then numeric subversion.
Development, post, local versions, and untagged commits are excluded.
## Release source

AEM reads `vVERSION` tags from its upstream Git repository, verifies the matching package metadata, and installs the selected commit through uv.
Use the installer's `--update-repository URL` to select another release repository.
Development checkout edits are not published or installed by this path.

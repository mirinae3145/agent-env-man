# Personal hook integration contracts

Catalog `hooks` extends declared content, independently of skill/plugin discovery.
The catalog owns per-agent event/script/literal arguments; the machine binds runtime executable paths.
Profiles own supported events, timeout/matcher limits and direct command rendering.
AEM never invokes script logic or grants product trust.
No callback proxy, scheduler, workflow runner or source manifest is added.

Preparation validates all agent scripts in a shared checkout before publishing.
Incoming revisions guard declared and saved active scripts, including orphaned consumers; updates expose source content directly without changing registration.
Personal hooks require explicit apply selection and remain excluded from full mode.

Group ownership recognizes an exact silent command prefix and compares the complete saved event/group.
Duplicate identities across events fail closed.
Event moves, multiple selected groups and shared JSON settings use one image per target and existing journals.
Preserve unrelated JSON fields, including exact numeric tokens.
Saved removal remains independent of catalog/profile/runtime; detach retains groups and does not materialize standalone scripts.
